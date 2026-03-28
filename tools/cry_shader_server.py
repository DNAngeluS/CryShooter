#!/usr/bin/env python3
"""
CRYENGINE Remote Shader Compiler Server for Linux.

Implements the CrySCompileServer wire protocol so that CRYENGINE 5.6 can
compile Vulkan SPIR-V shaders on Linux using Wine + DXC.

Requirements:
    wine, python3

Usage (CLI):
    source .env  # or export CRYENGINE_DIR=/path/to/CRYENGINE
    python3 tools/cry_shader_server.py

Usage (VS Code):
    Terminal > Run Task > Start Shader Server

Then launch the game with system.cfg containing:
    r_ShadersRemoteCompiler=1
    r_ShaderCompilerServer=127.0.0.1
    r_VkShaderCompiler=DXC
"""

import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import zlib

# ── Configuration ──────────────────────────────────────────────────────────────
PORT    = 61453
DXC_EXE = os.path.join(
    os.environ.get("CRYENGINE_DIR", ""),
    "Code/SDKs/DXC/bin/dxc.exe"
)
DXC_DIR = os.path.dirname(DXC_EXE)   # so Wine finds dxcompiler.dll

# State codes that match the server-side enum (do not change these values)
STATE_DONE          = 1
STATE_COMPILE_ERROR = 5

# ── Protocol helpers ───────────────────────────────────────────────────────────

def _compress_payload(data: bytes) -> bytes:
    """4-byte little-endian uncompressed length + zlib-compressed data."""
    return struct.pack("<I", len(data)) + zlib.compress(data)


def send_response(conn: socket.socket, state: int, data: bytes) -> None:
    """
    Wire format:
        uint32 LE  – total payload length (everything after this field + state byte)
        uint8      – state code
        <payload>  – _compress_payload(data)
    """
    payload = _compress_payload(data)
    header  = struct.pack("<IB", len(payload), state)
    conn.sendall(header + payload)


def recv_request(conn: socket.socket) -> bytes:
    """
    Read one request frame:
        uint64 LE – byte count of the following XML
        <XML>     – raw bytes (may include trailing NUL)
    Returns the XML bytes (without trailing NUL).
    """
    size_buf = _recv_exactly(conn, 8)
    if size_buf is None:
        return b""
    xml_size = struct.unpack("<Q", size_buf)[0]
    xml_buf  = _recv_exactly(conn, xml_size)
    return xml_buf.rstrip(b"\x00") if xml_buf else b""


def _recv_exactly(conn: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

# ── XML parsing ────────────────────────────────────────────────────────────────

def _unescape(s: str) -> str:
    return (s.replace("&amp;",  "&")
             .replace("&lt;",   "<")
             .replace("&gt;",   ">")
             .replace("&quot;", '"')
             .replace("&apos;", "'"))


_ATTR_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.|&[^;]+;)*)"')


def parse_attrs(xml: str) -> dict:
    """
    Minimal attribute parser for the single-element CrySCompileServer XML.
    Returns a dict of {name: unescaped_value}.
    """
    return {m.group(1): _unescape(m.group(2)) for m in _ATTR_RE.finditer(xml)}

# ── Shader compilation ─────────────────────────────────────────────────────────

# Maps the relative compiler paths used in CompileFlags to Wine commands.
_COMPILER_MAP = {
    "SPIRV/V006/dxc/dxc.exe": ["wine", DXC_EXE],
}


def _sprintf4(template: str, a: str, b: str, c: str, d: str) -> str:
    """Replace the four '%s' placeholders in order (same as C sprintf)."""
    result = template
    for val in (a, b, c, d):
        result = result.replace("%s", val, 1)
    return result


def compile_dxc(entry: str, profile: str, compile_flags: str,
                hlsl_source: str) -> bytes:
    """
    Compile HLSL → SPIR-V using Wine + dxc.exe.
    Returns raw SPIR-V bytes, or raises RuntimeError on failure.
    """
    with tempfile.TemporaryDirectory(prefix="cry_shader_") as tmpdir:
        in_file  = os.path.join(tmpdir, "shader.hlsl")
        out_file = os.path.join(tmpdir, "shader.spv")

        with open(in_file, "w", encoding="utf-8") as fh:
            fh.write(hlsl_source)

        # compile_flags starts with a relative compiler path, then flags with
        # %s placeholders for (entry, profile, out_file, in_file).
        # Find which compiler is being requested.
        cmd_prefix = None
        remaining  = compile_flags
        for rel_path, cmd in _COMPILER_MAP.items():
            if compile_flags.startswith(rel_path):
                cmd_prefix = cmd
                remaining  = compile_flags[len(rel_path):]
                break

        if cmd_prefix is None:
            raise RuntimeError(
                f"Unknown compiler in CompileFlags: {compile_flags[:80]}"
            )

        # Substitute %s → (entry, profile, out_file, in_file)
        args_str = _sprintf4(remaining.strip(), entry, profile, out_file, in_file)
        args     = args_str.split()

        full_cmd = cmd_prefix + args
        print(f"  Compiling: {profile} {entry}", flush=True)

        result = subprocess.run(
            full_cmd,
            cwd=DXC_DIR,
            capture_output=True,
            timeout=120,
            env={**os.environ, "WINEDEBUG": "-all"},
        )

        if result.returncode != 0 or not os.path.exists(out_file):
            stderr = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            raise RuntimeError(stderr or "Compilation failed (no output)")

        with open(out_file, "rb") as fh:
            spv = fh.read()

    if len(spv) == 0:
        raise RuntimeError("Compiler produced empty SPIR-V")

    return spv

# ── Client handler ─────────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr) -> None:
    try:
        xml_bytes = recv_request(conn)
        if not xml_bytes:
            return

        xml_str = xml_bytes.decode("utf-8", errors="replace")
        attrs   = parse_attrs(xml_str)

        job_type = attrs.get("JobType", "")

        if job_type == "Compile":
            profile       = attrs.get("Profile", "")
            entry         = attrs.get("Entry", "")
            compile_flags = attrs.get("CompileFlags", "")
            program       = attrs.get("Program", "")

            try:
                spv = compile_dxc(entry, profile, compile_flags, program)
                send_response(conn, STATE_DONE, spv)
                print(f"  OK  {profile} {entry} ({len(spv)} bytes)", flush=True)
            except RuntimeError as exc:
                msg = str(exc)
                print(f"  ERR {profile} {entry}: {msg[:120]}", flush=True)
                send_response(conn, STATE_COMPILE_ERROR, msg.encode("utf-8"))

        else:
            # RequestLine and other non-compile jobs: just acknowledge
            send_response(conn, STATE_DONE, b"")

    except Exception as exc:
        print(f"[{addr}] unhandled error: {exc}", flush=True)
    finally:
        try:
            conn.close()
        except OSError:
            pass

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if not os.environ.get("CRYENGINE_DIR"):
        print("ERROR: CRYENGINE_DIR is not set. Source .env or export the variable.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(DXC_EXE):
        print(f"ERROR: dxc.exe not found at {DXC_EXE}", file=sys.stderr)
        sys.exit(1)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(32)
    print(f"CryEngine shader compiler server listening on port {PORT}")
    print(f"DXC: {DXC_EXE}")

    while True:
        conn, addr = srv.accept()
        print(f"[{addr[0]}] connected", flush=True)
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
