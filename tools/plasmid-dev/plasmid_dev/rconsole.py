"""Minimal CRYENGINE Remote Console client: send console commands to a running game.

Protocol: packets are NUL-terminated and the first byte is the type. The engine sends `1` when it asks for a
request (we answer `5<command>` while one is queued, else `0`); `2`/`3`/`4` are log lines (answered `0`).
The engine accepts one client at a time and must be built with the Remote Console option ON.
"""

from __future__ import annotations

import socket
import time

DEFAULT_PORT = 4600


def send_commands(commands: list[str], port: int = DEFAULT_PORT, host: str = "127.0.0.1",
                  timeout_s: float = 30.0, linger_s: float = 1.0) -> list[str]:
    """Connect, deliver `commands` in order, return the log lines seen. Raises OSError / TimeoutError."""
    for c in commands:
        if not c or any(ch in c for ch in "\0\r\n"):
            raise ValueError("a command must be one non-empty line without NUL")
    pending = list(commands)
    seen: list[str] = []
    deadline = time.monotonic() + timeout_s
    sock = socket.create_connection((host, port), timeout=5.0)
    sock.settimeout(1.0)
    buf = bytearray()
    sent_all_at = None
    try:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"engine did not ask for {pending[0]!r} within {timeout_s:g} s")
            if sent_all_at is not None and time.monotonic() - sent_all_at > linger_s:
                return seen
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                if pending:
                    raise OSError("Remote Console closed before the command was sent")
                return seen
            buf += chunk
            while (end := buf.find(b"\0")) >= 0:
                packet = bytes(buf[:end])
                del buf[: end + 1]
                kind = packet[:1]
                if kind in (b"2", b"3", b"4"):
                    seen.append(packet[1:].decode("utf-8", "replace"))
                    reply = b"0\0"
                elif kind == b"1" and pending:
                    reply = b"5" + pending.pop(0).encode("utf-8") + b"\0"
                    if not pending:
                        sent_all_at = time.monotonic()
                else:
                    reply = b"0\0"
                sock.sendall(reply)
    finally:
        try:
            sock.close()
        except OSError:
            pass
