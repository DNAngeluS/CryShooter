#!/usr/bin/env python3
"""
CRYENGINE Remote Shader Compiler Server for Linux.

Implements the CrySCompileServer wire protocol so that CRYENGINE 5.6 can
compile Vulkan SPIR-V shaders on Linux using Wine + DXC.

Requirements:
    wine, python3

Usage (CLI):
    source .env  # or export CRYENGINE_DIR=/path/to/CRYENGINE
    python3 plasmid_dev/shader_server.py   (inside the plasmid-dev tool root; or the service that plas-dev starts)

Usage (VS Code):
    Terminal > Run Task > Start Shader Server

Then launch the game with these CVars set in the ENGINE-ROOT system.cfg (<CRYENGINE_DIR>/system.cfg; the engine reads only
that file, a project-folder system.cfg is never read; a private runtime copy of the engine needs its own copy of it):
    r_ShadersRemoteCompiler=1
    r_ShaderCompilerServer=127.0.0.1
    r_VkShaderCompiler=DXC
"""

import os
import re
import argparse
import hashlib
import shutil
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

# DXC backend (1.3.0): "wine" (default, the engine's bundled dxc.exe through Wine, the only mode up to 1.2.x),
# "native" (a Linux dxc binary: ~12-20x faster, but a newer, stricter DXC), "auto" (native first, Wine for the
# shaders native refuses). Choose with --dxc or the PLASMID_DEV_DXC environment variable; the flag wins.
DXC_MODES  = ("wine", "native", "auto")
NATIVE_DXC = (os.environ.get("PLASMID_DEV_DXC_NATIVE") or os.environ.get("CRY_DXC_NATIVE")  # legacy-alias: removed in 3.0
              or shutil.which("dxc") or shutil.which("dxc-3.7"))
DXC_MODE   = os.environ.get("PLASMID_DEV_DXC") or os.environ.get("CRY_DXC", "wine")  # legacy-alias: removed in 3.0
NATIVE_ARGS = ["-HV", "2018"]   # DXC 1.10 defaults to HLSL 2021 (ternary short-circuit rules); the engine shaders are 2018

# Compile errors are deterministic and the engine retries a failed shader on every frame (thousands of times for a
# shader it can never build): remember the error text per (entry, profile, flags, source, backend mode).
_FAILED: dict[str, str] = {}
_FAILED_LOCK = threading.Lock()
FAILED_MAX = 20000

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


def _backend_cmd(backend: str, compile_flags: str):
    """Return (command prefix, flags after the compiler path) for one backend, or None if the flags name another compiler."""
    for rel_path in _COMPILER_MAP:
        if compile_flags.startswith(rel_path):
            rest = compile_flags[len(rel_path):]
            if backend == "wine":
                return ["wine", DXC_EXE], rest, None
            return [NATIVE_DXC], rest, NATIVE_ARGS
    return None


def _run_backend(backend: str, entry: str, profile: str, compile_flags: str, hlsl_source: str) -> bytes:
    """Compile HLSL -> SPIR-V with one backend ('wine' or 'native'). Returns SPIR-V bytes or raises RuntimeError."""
    resolved = _backend_cmd(backend, compile_flags)
    if resolved is None:
        raise RuntimeError(f"Unknown compiler in CompileFlags: {compile_flags[:80]}")
    cmd_prefix, remaining, extra = resolved
    with tempfile.TemporaryDirectory(prefix="plasmid_shader_") as tmpdir:
        in_file  = os.path.join(tmpdir, "shader.hlsl")
        out_file = os.path.join(tmpdir, "shader.spv")
        with open(in_file, "w", encoding="utf-8") as fh:
            fh.write(hlsl_source)
        # remaining holds flags with %s placeholders for (entry, profile, out_file, in_file)
        args = _sprintf4(remaining.strip(), entry, profile, out_file, in_file).split()
        if extra and "-HV" not in args:
            args += extra
        full_cmd = cmd_prefix + args
        print(f"  Compiling: {profile} {entry} [{backend}]", flush=True)
        env = {**os.environ, "WINEDEBUG": "-all"} if backend == "wine" else dict(os.environ)
        result = subprocess.run(full_cmd, cwd=DXC_DIR if backend == "wine" else None,
                                capture_output=True, timeout=120, env=env)
        if result.returncode != 0 or not os.path.exists(out_file):
            stderr = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            raise RuntimeError(stderr or "Compilation failed (no output)")
        with open(out_file, "rb") as fh:
            spv = fh.read()
    if len(spv) == 0:
        raise RuntimeError("Compiler produced empty SPIR-V")
    return spv


def first_error_line(msg: str, limit: int = 200) -> str:
    """The first line that says 'error' (Wine and Mesa print unrelated warnings first), else the first line."""
    lines = [l.strip() for l in msg.splitlines() if l.strip()]
    for l in lines:
        if "error" in l.lower():
            return l[:limit]
    return (lines[0] if lines else "compilation failed")[:limit]


def backends_for(mode: str, have_native: bool, have_wine: bool) -> list[str]:
    """Backends to try, in order, for a DXC mode, limited to the ones that exist. 'auto' tries native first and Wine
    for what native refuses."""
    wanted = {"wine": ["wine"], "native": ["native"], "auto": ["native", "wine"]}[mode]
    return [b for b in wanted if (have_native if b == "native" else have_wine)]


def compile_dxc(entry: str, profile: str, compile_flags: str,
                hlsl_source: str) -> bytes:
    """
    Compile HLSL -> SPIR-V (backend chosen by DXC_MODE). Returns raw SPIR-V bytes, or raises RuntimeError.
    A failed compile is remembered and answered from memory the next time the same shader is requested.
    """
    key = hashlib.sha1("\0".join((DXC_MODE, entry, profile, compile_flags, hlsl_source)).encode("utf-8", "replace")).hexdigest()
    with _FAILED_LOCK:
        known = _FAILED.get(key)
    if known is not None:
        print(f"  ERR {profile} {entry}: (cached) {first_error_line(known)}", flush=True)
        raise CachedCompileError(known)
    order = backends_for(DXC_MODE, bool(NATIVE_DXC), os.path.exists(DXC_EXE))
    if not order:
        raise RuntimeError(f"no DXC backend available for mode {DXC_MODE!r}")
    last: RuntimeError | None = None
    for backend in order:
        try:
            return _run_backend(backend, entry, profile, compile_flags, hlsl_source)
        except RuntimeError as exc:
            last = exc
            if backend != order[-1]:
                print(f"  fallback {profile} {entry}: {backend} refused ({first_error_line(str(exc), 120)})", flush=True)
    with _FAILED_LOCK:
        if len(_FAILED) < FAILED_MAX:
            _FAILED[key] = str(last)
    raise last


class CachedCompileError(RuntimeError):
    """A compile error answered from the failure memory (already logged)."""

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
                if not isinstance(exc, CachedCompileError):
                    print(f"  ERR {profile} {entry}: {first_error_line(msg)}", flush=True)
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

def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="CryEngine remote shader compiler server (Linux)")
    ap.add_argument("--dxc", choices=DXC_MODES, default=DXC_MODE,
                    help="DXC backend: wine (default, bundled dxc.exe), native (Linux dxc, faster, stricter), "
                         "auto (native, Wine for what it refuses); env PLASMID_DEV_DXC")
    ap.add_argument("--port", type=int, default=PORT)
    return ap.parse_args(argv)


def main() -> None:
    global DXC_MODE, PORT
    ns = parse_args()
    DXC_MODE, PORT = ns.dxc, ns.port
    if not os.environ.get("CRYENGINE_DIR"):
        print("ERROR: CRYENGINE_DIR is not set. Source .env or export the variable.", file=sys.stderr)
        sys.exit(1)

    have_wine = os.path.exists(DXC_EXE) and bool(shutil.which("wine"))
    order = backends_for(DXC_MODE, bool(NATIVE_DXC), have_wine)
    if not order:
        if DXC_MODE == "native":
            print("ERROR: --dxc native but no native dxc found (install directx-shader-compiler or set PLASMID_DEV_DXC_NATIVE)", file=sys.stderr)
        elif not os.path.exists(DXC_EXE):
            print(f"ERROR: dxc.exe not found at {DXC_EXE}", file=sys.stderr)
        else:
            print("ERROR: wine not found; the Wine backend needs Wine + dxc.exe", file=sys.stderr)
        sys.exit(1)
    if DXC_MODE == "wine" and not os.path.exists(DXC_EXE):
        print(f"ERROR: dxc.exe not found at {DXC_EXE}", file=sys.stderr)
        sys.exit(1)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(32)
    print(f"CryEngine shader compiler server listening on port {PORT}")
    print(f"DXC mode: {DXC_MODE} (backends: {', '.join(order)})")
    print(f"DXC wine: {DXC_EXE}")
    print(f"DXC native: {NATIVE_DXC or '-'}")

    while True:
        conn, addr = srv.accept()
        print(f"[{addr[0]}] connected", flush=True)
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    main()
