#!/usr/bin/env python3
"""Dev command runner for FirstPersonShooter (stdlib only).

The npm-scripts equivalent for this project: build the plugin, manage background
services (remote shader compiler), launch / debug the game, read logs, run tests and
the asset pipeline. Designed to be driven by humans and by agents without an IDE:

  * nothing blocks unless asked to (run/up return immediately; logs go to .dev/logs/)
  * commands are idempotent and exit non-zero on failure
  * `status --json` is machine readable

Usually invoked through the Makefile (`make help`), or directly: `python3 tools/dev.py -h`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / ".dev"
PIDS = DEV / "pids"
LOGS = DEV / "logs"
VENV_PY = ROOT / "tools" / ".venv" / "bin" / "python3"

COMPILERS = ("gcc9", "gcc13", "gcc14", "clang")
TYPES = ("Debug", "Profile", "Release")

# Engine checkouts the plugin can be built against / run on. `--engine 56|57` (Makefile: ENGINE=).
#   env      -> variable in .env naming the checkout (56 also falls back to the legacy CRYENGINE_DIR);
#               if unset, the checkout is looked up at <Crytek>/Engines/<dir> (this project lives at <Crytek>/Projects/)
#   dir      -> directory name under <Crytek>/Engines/
#   compiler -> default compiler when --compiler is not given
#   presets  -> compiler -> CMake preset (Code/CMakePresets.json). Build dir = build/<preset>, except the gcc9 preset,
#               which is `build/gcc` because that is the directory VS Code uses; keep it that way.
ENGINES = {
    "56": {"label": "CRYENGINE 5.6.7", "dir": "ce-5.6.7", "env": "CRYENGINE_DIR_56", "fallback": "CRYENGINE_DIR", "compiler": "gcc9",
           "presets": {"gcc9": "gcc9", "gcc13": "gcc13", "gcc14": "gcc14", "clang": "clang"}},
    "57": {"label": "CRYENGINE 5.7.1", "dir": "ce-5.7.1", "env": "CRYENGINE_DIR_57", "fallback": None, "compiler": "gcc13",
           "presets": {"gcc13": "e57-gcc13"}},
}
ENGINE = "56"  # set from --engine in main()
SHADER_PORT = 61453  # keep in sync with tools/cry_shader_server.py

DRY = False


# --------------------------------------------------------------------------- helpers

def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_env() -> dict[str, str]:
    """os.environ plus .env (real environment wins). Ignores the .env.example placeholder."""
    env = dict(os.environ)
    dotenv = ROOT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.removeprefix("export ").partition("=")
            value = value.strip().strip("'\"")
            if key.strip() and value and value != "/path/to/CRYENGINE":
                env.setdefault(key.strip(), value)
    return env


def resolve_engine_dir(env: dict[str, str], key: str) -> str | None:
    spec = ENGINES[key]
    explicit = env.get(spec["env"]) or (env.get(spec["fallback"]) if spec["fallback"] else None)
    if explicit:
        return explicit
    default = ROOT.parent.parent / "Engines" / spec["dir"]  # <Crytek>/Projects/<this project> -> <Crytek>/Engines/<dir>
    return str(default) if default.is_dir() else None


def engine_dir(env: dict[str, str]) -> Path:
    path = env.get("CRYENGINE_DIR")
    if not path:
        die("CRYENGINE_DIR is not set. Copy .env.example to .env and set it (or export it).", 2)
    p = Path(path)
    if not p.is_dir():
        die(f"CRYENGINE_DIR does not exist: {p}", 2)
    return p


def engine_bin(env: dict[str, str]) -> Path:
    return engine_dir(env) / "bin" / "linux_x64_gcc"


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> int:
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    if DRY:
        return 0
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env).returncode


def python_exe() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def pick_compiler(compiler: str | None) -> str:
    """Compiler for the selected engine: the explicit one, else the engine's default; reject unsupported combos."""
    spec = ENGINES[ENGINE]
    compiler = compiler or spec["compiler"]
    if compiler not in spec["presets"]:
        die(f"{spec['label']} has no preset for COMPILER={compiler} (available: {', '.join(spec['presets'])}). "
            "Add one to Code/CMakePresets.json and ENGINES in tools/dev.py.", 2)
    return compiler


def preset_name(compiler: str) -> str:
    return ENGINES[ENGINE]["presets"][pick_compiler(compiler)]


def preset_dir(preset: str) -> Path:
    return ROOT / "build" / ("gcc" if preset == "gcc9" else preset)


def build_dir(compiler: str) -> Path:
    return preset_dir(preset_name(compiler))


def strip_sep(extra: list[str]) -> list[str]:
    return extra[1:] if extra and extra[0] == "--" else extra


# --------------------------------------------------------------------------- processes

def pid_file(name: str) -> Path:
    return PIDS / f"{name}.pid"


def running_pid(name: str, match: str) -> int | None:
    """PID of a process we started, verified against /proc so reused PIDs do not fool us."""
    pf = pid_file(name)
    try:
        pid = int(pf.read_text())
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        if match in cmdline:
            return pid
    except (OSError, ValueError):
        pass
    pf.unlink(missing_ok=True)
    return None


def spawn(name: str, cmd: list[str], cwd: Path, env: dict[str, str], log: Path) -> int | None:
    print(f"$ {' '.join(str(c) for c in cmd)}  > {log.relative_to(ROOT)}", flush=True)
    if DRY:
        return None
    PIDS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        fh.write(f"\n--- {time.strftime('%F %T')} start: {' '.join(map(str, cmd))}\n".encode())
        proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    pid_file(name).write_text(str(proc.pid))
    return proc.pid


def stop(name: str, match: str) -> bool:
    pid = running_pid(name, match)
    if pid is None:
        return False
    print(f"stopping {name} (pid {pid})")
    if DRY:
        return True
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            break
        deadline = time.time() + wait
        while time.time() < deadline and Path(f"/proc/{pid}").exists():
            time.sleep(0.1)
        if not Path(f"/proc/{pid}").exists():
            break
    pid_file(name).unlink(missing_ok=True)
    return True


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(cond, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def tail(path: Path, n: int) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


# --------------------------------------------------------------------------- services

SERVICES = {
    "shader": {"match": "cry_shader_server.py", "port": SHADER_PORT,
               "cmd": lambda: [sys.executable, str(ROOT / "tools" / "cry_shader_server.py")]},
}
GAME_MATCH = "GameLauncher"


def cmd_up(args, env) -> int:
    engine_dir(env)
    if not shutil.which("wine"):
        print("warning: wine not found; the shader compiler server needs Wine + DXC", file=sys.stderr)
    for name, svc in SERVICES.items():
        pid = running_pid(name, svc["match"])
        if pid:
            print(f"{name}: already running (pid {pid})")
            continue
        if port_open(svc["port"]):
            die(f"{name}: port {svc['port']} is in use by something we did not start", 3)
        pid = spawn(name, svc["cmd"](), ROOT, env, LOGS / f"{name}.log")
        if DRY:
            continue
        if not wait_for(lambda s=svc: port_open(s["port"]), 10):
            print("\n".join(tail(LOGS / f"{name}.log", 15)))
            die(f"{name}: did not start listening on :{svc['port']} (log: .dev/logs/{name}.log)", 3)
        print(f"{name}: up (pid {pid}, port {svc['port']}, log .dev/logs/{name}.log)")
    return 0


def cmd_down(args, env) -> int:
    stopped = [n for n, s in SERVICES.items() if stop(n, s["match"])]
    print("stopped: " + ", ".join(stopped) if stopped else "no services running")
    return 0


# --------------------------------------------------------------------------- build

def cmake_cache_type(bdir: Path) -> str | None:
    try:
        m = re.search(r"^CMAKE_BUILD_TYPE:\w+=(\w*)", (bdir / "CMakeCache.txt").read_text(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def do_configure(compiler: str, btype: str, env: dict[str, str], force: bool = False) -> int:
    bdir = build_dir(compiler)
    if not force and (bdir / "build.ninja").exists() and cmake_cache_type(bdir) == btype:
        return 0
    return run(["cmake", "--preset", preset_name(compiler), f"-DCMAKE_BUILD_TYPE={btype}"], cwd=ROOT / "Code", env=env)


def do_build(compiler: str, btype: str, env: dict[str, str]) -> int:
    engine_dir(env)
    rc = do_configure(compiler, btype, env)
    if rc:
        return rc
    rc = run(["cmake", "--build", "--preset", preset_name(compiler)], cwd=ROOT / "Code", env=env)
    if rc == 0 and not DRY:
        so = ROOT / "bin" / "linux_x64_gcc" / "libGamePlugin.so"
        print(f"built {btype} ({pick_compiler(compiler)}) for {ENGINES[ENGINE]['label']}: {so.relative_to(ROOT)} -> {engine_bin(env)}"
              if so.exists() else "build ok (plugin not found?)")
    return rc


def cmd_configure(args, env) -> int:
    engine_dir(env)
    return do_configure(args.compiler, args.type, env, force=True)


def cmd_build(args, env) -> int:
    return do_build(args.compiler, args.type, env)


def cmd_clean(args, env) -> int:
    return run(["cmake", "--build", str(build_dir(args.compiler)), "--target", "clean"], env=env)


# --------------------------------------------------------------------------- run / debug

def launcher_cmd(env: dict[str, str], extra: list[str]) -> tuple[list[str], Path]:
    ebin = engine_bin(env)
    exe = ebin / "GameLauncher"
    if not exe.exists():
        die(f"GameLauncher not found at {exe}", 2)
    return [str(exe), "-project", str(ROOT / "Game.cryproject"), *extra], ebin


def check_display() -> None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        die("no DISPLAY / WAYLAND_DISPLAY in this shell; the game needs a desktop session", 4)


def ensure_plugin(env: dict[str, str]) -> None:
    deployed = engine_bin(env) / "libGamePlugin.so"
    if not deployed.exists():
        die(f"{deployed} is missing — run `make build` first", 2)


def cmd_run(args, env) -> int:
    extra = strip_sep(args.extra)
    check_display()
    pid = running_pid("game", GAME_MATCH)
    if pid:
        die(f"game already running (pid {pid}); `make stop` first", 3)
    if args.build:
        rc = do_build(args.compiler, args.type, env)
        if rc:
            return rc
    ensure_plugin(env)
    if not args.no_services:
        rc = cmd_up(args, env)
        if rc:
            return rc
    cmd, cwd = launcher_cmd(env, extra)
    if args.foreground:
        return run(cmd, cwd=cwd, env=env)
    log = LOGS / "game.out.log"
    pid = spawn("game", cmd, cwd, env, log)
    if DRY:
        return 0
    time.sleep(3)
    if not running_pid("game", GAME_MATCH):
        print("\n".join(tail(log, 30)))
        die("game exited during startup (see output above; engine log: game.log)", 5)
    print(f"game: running (pid {pid}); stdout .dev/logs/game.out.log, engine log game.log; stop with `make stop`")
    return 0


def cmd_debug(args, env) -> int:
    extra = strip_sep(args.extra)
    check_display()
    if running_pid("game", GAME_MATCH):
        die("game already running; `make stop` first", 3)
    ensure_plugin(env)
    if not args.no_services:
        rc = cmd_up(args, env)
        if rc:
            return rc
    cmd, cwd = launcher_cmd(env, extra)
    gdb = ["gdb", "-q", "-ex", "set pagination off",
           "-ex", "handle SIGTRAP nostop noprint nopass",
           "-ex", f"set solib-search-path {ROOT / 'bin' / 'linux_x64_gcc'}"]
    if not args.batch:
        return run([*gdb, "--args", *cmd], cwd=cwd, env=env)
    log = LOGS / "gdb.log"
    LOGS.mkdir(parents=True, exist_ok=True)
    full = [*gdb, "-batch", "-ex", "run", "-ex", "bt 40", "-ex", "thread apply all bt 12", "--args", *cmd]
    print(f"$ {' '.join(full)}  > .dev/logs/gdb.log", flush=True)
    if DRY:
        return 0
    with open(log, "wb") as fh:
        proc = subprocess.Popen(full, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=args.timeout or None)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            rc = 124
            print(f"gdb session killed after {args.timeout}s")
    print("\n".join(tail(log, 60)))
    return rc


def cmd_stop(args, env) -> int:
    game = stop("game", GAME_MATCH)
    cmd_down(args, env)
    if not game:
        print("game was not running")
    return 0


# --------------------------------------------------------------------------- logs / status

LOG_FILES = {"game": ROOT / "game.log", "game.out": LOGS / "game.out.log",
             "shader": LOGS / "shader.log", "gdb": LOGS / "gdb.log"}


def cmd_logs(args, env) -> int:
    path = LOG_FILES[args.name]
    if not path.exists():
        die(f"{path.relative_to(ROOT)} does not exist yet", 2)
    lines = path.read_text(errors="replace").splitlines()
    if args.name == "game" and not args.all:
        pat = re.compile(r"\[(Warning|Error)\]", re.I)
        total = len(lines)
        lines = [ln for ln in lines if pat.search(ln) and "Vulkan" not in ln]
        print(f"# {path.name}: {len(lines)} warning/error lines of {total} (use --all for everything)")
    print("\n".join(lines[-args.lines:]))
    return 0


def build_info(compiler: str, env: dict[str, str]) -> dict:
    bdir = preset_dir(ENGINES[ENGINE]["presets"][compiler])
    return {"configured": (bdir / "build.ninja").exists(), "type": cmake_cache_type(bdir)}


def gather_status(env: dict[str, str]) -> dict:
    ed = env.get("CRYENGINE_DIR")
    so = ROOT / "bin" / "linux_x64_gcc" / "libGamePlugin.so"
    deployed = Path(ed) / "bin" / "linux_x64_gcc" / "libGamePlugin.so" if ed else None
    fmt = lambda p: time.strftime("%F %T", time.localtime(p.stat().st_mtime)) if p and p.exists() else None
    deployed_all = {}
    for k, spec in ENGINES.items():
        d = resolve_engine_dir(env, k)
        deployed_all[k] = fmt(Path(d) / "bin" / "linux_x64_gcc" / "libGamePlugin.so") if d else None
    return {
        "engine": ENGINE,
        "engine_label": ENGINES[ENGINE]["label"],
        "cryengine_dir": ed,
        "deployed_per_engine": deployed_all,
        "services": {n: {"running": bool(running_pid(n, s["match"])), "pid": running_pid(n, s["match"]),
                         "port_open": port_open(s["port"])} for n, s in SERVICES.items()},
        "game": {"running": bool(running_pid("game", GAME_MATCH)), "pid": running_pid("game", GAME_MATCH)},
        "plugin": {"built": fmt(so), "deployed": fmt(deployed)},
        "builds": {c: build_info(c, env) for c in ENGINES[ENGINE]["presets"]},
        "venv": VENV_PY.exists(),
    }


def cmd_status(args, env) -> int:
    st = gather_status(env)
    if args.json:
        print(json.dumps(st, indent=2))
        return 0
    print(f"engine   {st['engine_label']} (ENGINE={st['engine']})  {st['cryengine_dir'] or 'NOT SET'}")
    for n, s in st["services"].items():
        print(f"service  {n:<8} {'running pid ' + str(s['pid']) if s['running'] else 'stopped'}"
              f"{'  (port busy, not ours)' if s['port_open'] and not s['running'] else ''}")
    g = st["game"]
    print(f"game     {'running pid ' + str(g['pid']) if g['running'] else 'stopped'}")
    print(f"plugin   built {st['plugin']['built']}  deployed {st['plugin']['deployed']}")
    print("deployed " + "  ".join(f"{k}: {v or '-'}" for k, v in st["deployed_per_engine"].items()))
    for c, b in st["builds"].items():
        print(f"build    {c:<6} {'configured ' + str(b['type']) if b['configured'] else 'not configured'}")
    print(f"venv     {'ok' if st['venv'] else 'missing (make setup)'}")
    return 0


def cmd_doctor(args, env) -> int:
    ed = env.get("CRYENGINE_DIR")
    checks = [
        ("CRYENGINE_DIR set", bool(ed), True),
        ("engine dir exists", bool(ed) and Path(ed).is_dir(), True),
        ("GameLauncher present", bool(ed) and (Path(ed) / "bin/linux_x64_gcc/GameLauncher").exists(), True),
        *[(f"{s['label']} engine dir ({k})", bool(resolve_engine_dir(env, k)) and Path(resolve_engine_dir(env, k)).is_dir(), False)
          for k, s in ENGINES.items()],
        ("cmake", bool(shutil.which("cmake")), True),
        ("ninja", bool(shutil.which("ninja")), True),
        ("g++-9", bool(shutil.which("g++-9")), False),
        ("g++-13 (ENGINE=57)", bool(shutil.which("g++-13")), False),
        ("g++-14", bool(shutil.which("g++-14")), False),
        ("clang++", bool(shutil.which("clang++")), False),
        ("gdb (debug)", bool(shutil.which("gdb")), False),
        ("wine (shader server)", bool(shutil.which("wine")), False),
        ("display session (run/debug)", bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")), False),
        ("python venv (tools/.venv)", VENV_PY.exists(), False),
    ]
    bad = 0
    for label, ok, required in checks:
        print(f"{'ok  ' if ok else ('MISS' if required else 'warn')}  {label}")
        bad += (not ok) and required
    return 1 if bad else 0


def cmd_setup(args, env) -> int:
    if not VENV_PY.exists():
        rc = run([sys.executable, "-m", "venv", str(ROOT / "tools" / ".venv")])
        if rc:
            return rc
    rc = run([python_exe(), "-m", "pip", "install", "-q", "-r", str(ROOT / "tools" / "requirements.txt")])
    if rc:
        return rc
    if not DRY:
        PIDS.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
    rc = cmd_doctor(args, env)
    if rc == 0:
        rc = do_configure(args.compiler, args.type, env)
    return rc


# --------------------------------------------------------------------------- python tools

def cmd_test(args, env) -> int:
    return run([python_exe(), "-m", "pytest", "tests/", *(strip_sep(args.extra) or ["-q"])], env=env)


def cmd_pipeline(args, env) -> int:
    extra = strip_sep(args.extra)
    return run([python_exe(), "tools/cry_asset_pipeline.py", *(extra or ["--help"])], env=env)


# --------------------------------------------------------------------------- cli

def main() -> int:
    global DRY, ENGINE
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="print what would run; change nothing")
    p.add_argument("--engine", choices=ENGINES, default=os.environ.get("ENGINE") if os.environ.get("ENGINE") in ENGINES else "56",
                   help="engine checkout: 56 = CRYENGINE 5.6.7 (default), 57 = CRYENGINE 5.7.1 (also env ENGINE)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    def add(name, fn, help_, compiler=False, extra=False):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        if compiler:
            sp.add_argument("--compiler", choices=COMPILERS, default=None, help="default: the engine's (56: gcc9, 57: gcc13)")
            sp.add_argument("--type", choices=TYPES, default="Debug")
        if extra:
            sp.add_argument("extra", nargs=argparse.REMAINDER, help="passed through after `--`")
        return sp

    add("setup", cmd_setup, "create venv, install deps, check prerequisites, configure CMake", compiler=True)
    add("doctor", cmd_doctor, "check prerequisites (exit 1 if a required one is missing)")
    add("configure", cmd_configure, "(re)configure CMake with a preset", compiler=True)
    add("build", cmd_build, "configure if needed, then build the plugin (deploys to the engine bin dir)", compiler=True)
    add("clean", cmd_clean, "clean build outputs", compiler=True)
    add("up", cmd_up, "start background services (shader compiler server)")
    add("down", cmd_down, "stop background services")
    sp = add("run", cmd_run, "start services and launch the game in the background", compiler=True, extra=True)
    sp.add_argument("--build", action="store_true", help="build first")
    sp.add_argument("--no-services", action="store_true")
    sp.add_argument("--foreground", action="store_true", help="attach instead of backgrounding")
    sp = add("debug", cmd_debug, "launch the game under gdb (SIGTRAP handling preset)", extra=True)
    sp.add_argument("--batch", action="store_true", help="non-interactive: run, print backtrace on crash, log to .dev/logs/gdb.log")
    sp.add_argument("--timeout", type=int, default=0, help="batch mode: kill after N seconds")
    sp.add_argument("--no-services", action="store_true")
    add("stop", cmd_stop, "stop the game and all services")
    sp = add("status", cmd_status, "show services, game, builds, plugin timestamps")
    sp.add_argument("--json", action="store_true")
    sp = add("logs", cmd_logs, "show recent warnings/errors from game.log (or another log)")
    sp.add_argument("name", nargs="?", choices=LOG_FILES, default="game")
    sp.add_argument("-n", "--lines", type=int, default=40)
    sp.add_argument("--all", action="store_true", help="game log: do not filter to warnings/errors")
    add("test", cmd_test, "run pytest with the venv interpreter", extra=True)
    add("pipeline", cmd_pipeline, "run tools/cry_asset_pipeline.py (args after `--`)", extra=True)

    args = p.parse_args()
    DRY = args.dry_run
    ENGINE = args.engine
    env = load_env()
    if env.get("CRYENGINE_DIR") and not env.get("CRYENGINE_DIR_56"):
        env["CRYENGINE_DIR_56"] = env["CRYENGINE_DIR"]  # legacy name = 5.6.7; capture before it is overwritten below
    path = resolve_engine_dir(env, ENGINE)
    if path:
        env["CRYENGINE_DIR"] = path  # everything downstream (cmake, launcher, status) reads this
    elif ENGINE != "56" or args.cmd in ("build", "run", "debug", "configure", "setup", "clean"):
        spec = ENGINES[ENGINE]
        die(f"{spec['label']}: set {spec['env']} in .env (path of the checkout), or export it.", 2)
    return args.fn(args, env) or 0


if __name__ == "__main__":
    sys.exit(main())
