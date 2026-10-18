#!/usr/bin/env python3
"""Dev command runner for CRYENGINE game projects (currently FirstPersonShooter-shaped; see Tools/dev/config-schema.md) (stdlib only).

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
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

# Project-dependent globals: harmless placeholders here, (re)assigned by init_project() from --project-dir and the config.
ROOT = Path.cwd()
DEV = ROOT / ".dev"
PIDS = DEV / "pids"
LOGS = DEV / "logs"
DEV_REL = ".dev"  # config dev_dir, as printed in messages
VENV_PY: Path | None = None  # <project>/<python.venv>/bin/python3 when `python` is configured
SERVICES: dict = {}  # background services (config `services`), name -> {match, port, cmd}; set by init_project()
GAME_MATCH = ""  # /proc match for the game process (config launcher); set by init_project()
LOG_FILES: dict = {}  # name -> path for `logs`; set by init_project()
SHADER_CACHE: dict | None = None  # config `shader_cache` (link, slots_dir); None = not managed; set by init_project()


def init_project(project_dir: Path) -> None:
    """Point the module-level project paths at the project root, from CONFIG (already loaded). Called once, before the CLI parser is built."""
    global ROOT, DEV, PIDS, LOGS, DEV_REL, VENV_PY, SERVICES, GAME_MATCH, LOG_FILES, SHADER_CACHE
    ROOT = project_dir
    SHADER_CACHE = CONFIG.get("shader_cache")
    DEV_REL = CONFIG.get("dev_dir", ".dev")
    DEV = ROOT / DEV_REL
    PIDS = DEV / "pids"
    LOGS = DEV / "logs"
    py = CONFIG.get("python")
    VENV_PY = ROOT / py["venv"] / "bin" / "python3" if py and py.get("venv") else None
    SERVICES = {}
    for name, svc in CONFIG.get("services", {}).items():
        script = script_path(svc["script"])
        SERVICES[name] = {"match": script.name, "port": svc["port"],
                          "cmd": (lambda p=script: [sys.executable, str(p)])}
    GAME_MATCH = launcher_name()
    LOG_FILES = {"game": ROOT / "game.log", "game.out": LOGS / "game.out.log",
                 **{n: LOGS / f"{n}.log" for n in SERVICES}, "gdb": LOGS / "gdb.log"}


COMPILERS: tuple[str, ...] = ()  # union of engine preset keys (argparse --compiler choices); set in main()
TYPES = ("Debug", "Profile", "Release")

# Per-project config: <project dir>/cryengine-dev.config.json, documented in Tools/dev/config-schema.md.
# Loaded once in main() (CONFIG); the engine table below is derived from it.
CONFIG_NAME = "cryengine-dev.config.json"
CONFIG_SCHEMA = 1
CONFIG_KEYS = frozenset({"schema", "name", "cryproject", "source_dir", "plugin_lib", "plugin_out_dir", "engine_bin_dir",
                         "launcher", "dev_dir", "env_file", "default_engine", "engines", "build_dirs", "services",
                         "python", "extra_verbs", "doctor_extra_compilers", "shader_cache", "tools_version"})
CONFIG_REQUIRED = ("name", "cryproject", "engines", "default_engine")
ENGINE_CONFIG_KEYS = frozenset({"label", "dir", "env", "fallback_env", "compiler", "presets"})
ENGINE_REQUIRED = ("label", "dir", "env", "compiler", "presets")
BUILTIN_VERBS = frozenset({"setup", "doctor", "configure", "build", "clean", "up", "down", "run", "debug", "stop", "status", "logs"})

CONFIG: dict = {}  # the parsed cryengine-dev.config.json; set in main()

# Engine checkouts the plugin can be built against / run on (`engines` in the config; `--engine` picks one).
# ENGINES is derived from CONFIG["engines"] in main(). Inner keys:
#   env      -> variable in .env naming the checkout (fallback_env in the config, read as `fallback`)
#   dir      -> directory name under <Crytek>/Engines/
#   compiler -> default compiler when --compiler is not given
#   presets  -> compiler -> CMake preset (source_dir/CMakePresets.json)
ENGINES: dict = {}
ENGINE: str | None = None  # the selected engine key; set from CONFIG["default_engine"] and --engine in main()

DRY = False

# Tooling release: TOOL_DIR is the directory holding this dev.py (the repo's Tools/dev, or a project's vendored copy).
TOOL_DIR = Path(__file__).resolve().parent
VENDOR_MARKER = ".vendored-from"  # JSON written by the vendoring step: tool, version, tag, commit, vendored_at, files{name: sha256}


# --------------------------------------------------------------------------- helpers

def tool_version() -> str:
    """First line of TOOL_DIR/VERSION, stripped; "unknown" when the file is missing or empty."""
    try:
        first = (TOOL_DIR / "VERSION").read_text().splitlines()
    except OSError:
        return "unknown"
    return first[0].strip() if first and first[0].strip() else "unknown"


def read_vendor_marker() -> dict | None:
    """The parsed TOOL_DIR/.vendored-from, or None when there is no marker. Raises ValueError when it is malformed."""
    path = TOOL_DIR / VENDOR_MARKER
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"not valid JSON ({exc})") from exc
    if (not isinstance(data, dict) or not isinstance(data.get("version"), str)
            or not isinstance(data.get("commit"), str) or not isinstance(data.get("files"), dict)):
        raise ValueError("needs string 'version' and 'commit' and an object 'files'")
    return data


def vendored_commit() -> str | None:
    """Commit the vendored copy was taken from; None when not vendored or the marker is malformed."""
    try:
        marker = read_vendor_marker()
    except ValueError:
        return None
    return marker["commit"] if marker else None


def vendored_integrity() -> dict | None:
    """Compare the vendored files with the hashes in the marker. None when there is no marker."""
    try:
        marker = read_vendor_marker()
    except ValueError as exc:
        return {"error": f"malformed {VENDOR_MARKER}: {exc}"}
    if marker is None:
        return None
    modified = []
    for name, digest in marker["files"].items():
        path = TOOL_DIR / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            modified.append(name)
    return {"version": marker["version"], "commit": marker["commit"], "modified": modified, "extra": []}


def version_line() -> str:
    line = f"cryengine-dev {tool_version()}"
    commit = vendored_commit()
    return f"{line} (vendored from {commit[:8]})" if commit else line


def _asked_for_version(argv: list[str]) -> bool:
    """`--version` given as a global option (before the verb). Skips the values of the global options that take one."""
    skip = False
    for tok in argv:
        if skip:
            skip = False
        elif tok == "--version":
            return True
        elif tok in ("--project-dir", "--engine"):
            skip = True
        elif not tok.startswith("-"):
            return False  # reached the verb
    return False


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config(project_dir: Path) -> dict:
    """Read and validate <project_dir>/cryengine-dev.config.json. Every problem is a usage error (exit 2)."""
    path = project_dir / CONFIG_NAME
    if not path.is_file():
        die(f"no {CONFIG_NAME} in {project_dir}; see Tools/dev/config-schema.md", 2)
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        die(f"{path}: not valid JSON ({exc})", 2)
    if not isinstance(cfg, dict):
        die(f"{path}: top level must be a JSON object", 2)
    if cfg.get("schema") != CONFIG_SCHEMA or isinstance(cfg.get("schema"), bool):
        die(f"{path}: schema must be {CONFIG_SCHEMA} (got {cfg.get('schema')!r})", 2)
    for key in sorted(set(cfg) - CONFIG_KEYS):
        die(f"{path}: unknown top-level key {key!r}; allowed keys: {', '.join(sorted(CONFIG_KEYS))}", 2)
    missing = [k for k in CONFIG_REQUIRED if k not in cfg]
    if missing:
        die(f"{path}: missing required key(s): {', '.join(missing)}", 2)
    engines = cfg["engines"]
    if not isinstance(engines, dict) or not engines:
        die(f"{path}: 'engines' must be a non-empty object", 2)
    for k, e in engines.items():
        if not isinstance(e, dict):
            die(f"{path}: engines.{k} must be an object", 2)
        for key in sorted(set(e) - ENGINE_CONFIG_KEYS):
            die(f"{path}: unknown key {key!r} in engines.{k}; allowed keys: {', '.join(sorted(ENGINE_CONFIG_KEYS))}", 2)
        missing = [x for x in ENGINE_REQUIRED if x not in e]
        if missing:
            die(f"{path}: engines.{k} missing required key(s): {', '.join(missing)}", 2)
    if cfg["default_engine"] not in engines:
        die(f"{path}: default_engine {cfg['default_engine']!r} is not one of engines ({', '.join(engines)})", 2)
    for name, svc in cfg.get("services", {}).items():
        if not (isinstance(svc, dict) and isinstance(svc.get("script"), str) and isinstance(svc.get("port"), int)):
            die(f"{path}: services.{name} needs 'script' (string) and 'port' (integer)", 2)
    sc = cfg.get("shader_cache")
    if sc is not None and not (isinstance(sc, dict) and isinstance(sc.get("link"), str)
                               and isinstance(sc.get("slots_dir"), str)):
        die(f"{path}: shader_cache needs 'link' and 'slots_dir' (both project-relative strings)", 2)
    for name, verb in cfg.get("extra_verbs", {}).items():
        if name in BUILTIN_VERBS or not isinstance(verb, dict) or ("python_module" in verb) == ("python_script" in verb):
            die(f"{path}: extra_verbs.{name} must be a non-built-in name with exactly one of python_module / python_script", 2)
    for c in cfg.get("doctor_extra_compilers", []):
        if not (isinstance(c, str) or (isinstance(c, dict) and isinstance(c.get("bin"), str))):
            die(f"{path}: doctor_extra_compilers entries are strings or {{\"bin\": ..., \"label\": ...}} objects", 2)
    if "tools_version" in cfg and not (isinstance(cfg["tools_version"], str) and cfg["tools_version"].strip()):
        die(f"{path}: tools_version must be a non-empty string", 2)
    return cfg


def cfg_req(key: str) -> str:
    """A config value the requested command needs; absent -> usage error (exit 2)."""
    value = CONFIG.get(key)
    if not value:
        die(f"{CONFIG_NAME}: '{key}' is required for this command", 2)
    return value


def launcher_name() -> str:
    return CONFIG.get("launcher", "GameLauncher")


def engine_bin_rel() -> str:
    return CONFIG.get("engine_bin_dir", "bin/linux_x64_gcc")


def source_dir() -> Path:
    return ROOT / CONFIG.get("source_dir", "Code")


def script_path(script: str) -> Path:
    """`tool:<file>` = Tools/dev/<file> (next to this file); anything else is relative to the project root."""
    if script.startswith("tool:"):
        return Path(__file__).resolve().parent / script[len("tool:"):]
    return ROOT / script


def engines_from(cfg_engines: dict) -> dict:
    """Engine table in the shape the rest of this file reads (config fallback_env -> `fallback`)."""
    return {k: {"label": e["label"], "dir": e["dir"], "env": e["env"], "fallback": e.get("fallback_env"),
                "compiler": e["compiler"], "presets": dict(e["presets"])} for k, e in cfg_engines.items()}


def compilers_from(engines: dict) -> tuple[str, ...]:
    """Union of the engines' preset keys, in first-seen order."""
    seen: list[str] = []
    for e in engines.values():
        for c in e["presets"]:
            if c not in seen:
                seen.append(c)
    return tuple(seen)


def load_env() -> dict[str, str]:
    """os.environ plus the env file (real environment wins). Ignores the .env.example placeholder."""
    env = dict(os.environ)
    dotenv = ROOT / CONFIG.get("env_file", ".env")
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


def crytek_root() -> Path:
    """<Crytek> root holding Engines/: env CRYTEK_ROOT, else the nearest ancestor of ROOT (ROOT itself first) with an Engines/ dir."""
    override = os.environ.get("CRYTEK_ROOT")
    if override:
        return Path(override)
    start = Path(os.path.abspath(ROOT))
    for cand in (start, *start.parents):
        if (cand / "Engines").is_dir():
            return cand
    return ROOT.parent.parent


def resolve_engine_dir(env: dict[str, str], key: str) -> str | None:
    spec = ENGINES[key]
    explicit = env.get(spec["env"]) or (env.get(spec["fallback"]) if spec["fallback"] else None)
    if explicit:
        return explicit
    default = crytek_root() / "Engines" / spec["dir"]  # <Crytek>/Projects/<this project> -> <Crytek>/Engines/<dir>
    return str(default) if default.is_dir() else None


def engine_dir(env: dict[str, str]) -> Path:
    path = env.get("CRYENGINE_DIR")
    if not path:
        ef = CONFIG.get("env_file", ".env")
        die(f"CRYENGINE_DIR is not set. Copy {ef}.example to {ef} and set it (or export it).", 2)
    p = Path(path)
    if not p.is_dir():
        die(f"CRYENGINE_DIR does not exist: {p}", 2)
    return p


def engine_bin(env: dict[str, str]) -> Path:
    return engine_dir(env) / engine_bin_rel()


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> int:
    cwd = ROOT if cwd is None else cwd
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    if DRY:
        return 0
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env).returncode


def python_exe() -> str:
    return str(VENV_PY) if VENV_PY is not None and VENV_PY.exists() else sys.executable


def pick_compiler(compiler: str | None) -> str:
    """Compiler for the selected engine: the explicit one, else the engine's default; reject unsupported combos."""
    spec = ENGINES[ENGINE]
    compiler = compiler or spec["compiler"]
    if compiler not in spec["presets"]:
        die(f"{spec['label']} has no preset for COMPILER={compiler} (available: {', '.join(spec['presets'])}). "
            f"Add one to {CONFIG.get('source_dir', 'Code')}/CMakePresets.json and `engines.<k>.presets` in cryengine-dev.config.json.", 2)
    return compiler


def preset_name(compiler: str) -> str:
    return ENGINES[ENGINE]["presets"][pick_compiler(compiler)]


def preset_dir(preset: str) -> Path:
    return ROOT / CONFIG.get("build_dirs", {}).get(preset, f"build/{preset}")


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

def cmd_up(args, env) -> int:
    engine_dir(env)
    if not SERVICES:
        print("no services configured")
        return 0
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
            die(f"{name}: did not start listening on :{svc['port']} (log: {DEV_REL}/logs/{name}.log)", 3)
        print(f"{name}: up (pid {pid}, port {svc['port']}, log {DEV_REL}/logs/{name}.log)")
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
    return run(["cmake", "--preset", preset_name(compiler), f"-DCMAKE_BUILD_TYPE={btype}"], cwd=source_dir(), env=env)


def do_build(compiler: str, btype: str, env: dict[str, str]) -> int:
    engine_dir(env)
    rc = do_configure(compiler, btype, env)
    if rc:
        return rc
    rc = run(["cmake", "--build", "--preset", preset_name(compiler)], cwd=source_dir(), env=env)
    if rc == 0 and not DRY:
        so = ROOT / cfg_req("plugin_out_dir") / cfg_req("plugin_lib")
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
    exe = ebin / launcher_name()
    if not exe.exists():
        die(f"{launcher_name()} not found at {exe}", 2)
    return [str(exe), "-project", str(ROOT / cfg_req("cryproject")), *extra], ebin


def check_display() -> None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        die("no DISPLAY / WAYLAND_DISPLAY in this shell; the game needs a desktop session", 4)


def ensure_plugin(env: dict[str, str]) -> None:
    deployed = engine_bin(env) / cfg_req("plugin_lib")
    if not deployed.exists():
        die(f"{deployed} is missing — run `make build` first", 2)


# --------------------------------------------------------------------------- shader cache (per-engine slots)
# Config `shader_cache`: the engine writes its shader cache into `link` (project-relative). Engines 5.6.7 and 5.7.1
# invalidate each other's entries, so `link` is a relative symlink to <slots_dir>/<engine key>, switched before launch.

COLD_FILES = 20  # fewer files than this in the active slot -> the next launch recompiles shaders
SHADER_LOG_TAIL = 4 * 1024 * 1024  # bytes read from the end of the game log by shaders-status
LEGACY_SLOT = "legacy-unlabelled"  # where a pre-slot real cache directory is moved (its engine is unknown)
IDLE_DONE_S = 60  # shaders-status: no cache or service-log activity for this long -> compilation looks finished


def shader_link() -> Path:
    return ROOT / SHADER_CACHE["link"]


def shader_slot(key: str) -> Path:
    return ROOT / SHADER_CACHE["slots_dir"] / key


def shader_target(key: str) -> str:
    """Symlink target of an engine slot, relative to the directory that holds the link."""
    return os.path.relpath(shader_slot(key), shader_link().parent)


def _files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else []


def _is_empty(path: Path) -> bool:
    return not path.is_dir() or not any(path.iterdir())


def ensure_shader_cache(engine_key: str, env: dict[str, str]) -> None:
    """Make the shader cache link point at this engine's slot. No-op unless config `shader_cache` is set."""
    if not SHADER_CACHE:
        return
    link_rel, slots_rel = SHADER_CACHE["link"], SHADER_CACHE["slots_dir"]
    label = ENGINES[engine_key]["label"]
    if DRY:
        print(f"shader cache: {link_rel} -> {slots_rel}/{engine_key} (dry-run: nothing changed)")
        return
    link, slot, target = shader_link(), shader_slot(engine_key), shader_target(engine_key)
    slot.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if os.readlink(link) != target:
            pid = running_pid("game", GAME_MATCH)
            if pid:
                die("game is running on another engine's cache; `make stop` first", 3)
            tmp = link.with_name(link.name + ".switch")
            tmp.unlink(missing_ok=True)
            os.symlink(target, tmp)
            os.replace(tmp, link)  # atomic: the link is never missing
            print(f"shader cache: switched to {label} slot")
    elif link.is_dir():
        legacy = ROOT / slots_rel / LEGACY_SLOT
        if legacy.exists():
            die(f"{link_rel} is a real directory and {slots_rel}/{LEGACY_SLOT} already exists; "
                "resolve by hand (nothing changed)", 3)
        link.rename(legacy)
        print(f"shader cache: moved the real {link_rel} to {slots_rel}/{LEGACY_SLOT} (engine unknown)")
        for key in ENGINES:
            s = shader_slot(key)
            if _is_empty(s):
                shutil.copytree(legacy, s, dirs_exist_ok=True)  # real copies, not hardlinks
                print(f"shader cache: seeded {slots_rel}/{key} with a copy of {LEGACY_SLOT}")
        os.symlink(target, link)
        print(f"shader cache: {link_rel} -> {slots_rel}/{engine_key}")
    elif link.exists():
        die(f"{link_rel} exists and is neither a directory nor a symlink; move it aside by hand", 3)
    else:
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link)
        print(f"shader cache: {link_rel} -> {slots_rel}/{engine_key}")
    files = len(_files_under(slot))
    if files < COLD_FILES:
        print(f"shader cache for {label} is COLD: the first run recompiles shaders via the Wine+DXC server "
              "(~6-10 s each; black window for several minutes). Watch: make shaders-status")


def _age_s(mtime: float | None) -> int | None:
    return None if mtime is None else int(time.time() - mtime)


def _fmt_time(mtime: float | None) -> str | None:
    return None if mtime is None else time.strftime("%F %T", time.localtime(mtime))


def _log_counts(path: Path) -> dict | None:
    """Global Cache Miss / crc mismatch counts in the last SHADER_LOG_TAIL bytes of a log."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(max(0, size - SHADER_LOG_TAIL))
            text = fh.read().decode(errors="replace")
    except OSError:
        return None
    return {"global_cache_miss": len(re.findall(r"Global Cache Miss", text, re.I)),
            "crc_mismatch": len(re.findall(r"crc mismatch", text, re.I))}


def cmd_shaders_status(args, env) -> int:
    """Read-only: which cache slot is active, how much each holds, and whether shader compilation is still going."""
    link = shader_link()
    active = os.readlink(link) if link.is_symlink() else ("not a symlink" if link.exists() else "missing")
    active_files = _files_under(link)
    active_newest = max((p.stat().st_mtime for p in active_files), default=None)
    slots = {}
    for key, spec in ENGINES.items():
        files = _files_under(shader_slot(key))
        newest = max((p.stat().st_mtime for p in files), default=None)
        slots[key] = {"label": spec["label"], "files": len(files), "newest_mtime": _fmt_time(newest),
                      "newest_age_s": _age_s(newest)}
    first_svc = next(iter(SERVICES), None)
    svc_log = LOGS / f"{first_svc}.log" if first_svc else None
    svc_age = _age_s(svc_log.stat().st_mtime) if svc_log and svc_log.exists() else None
    game_counts = _log_counts(LOG_FILES["game"])
    ages = [a for a in (_age_s(active_newest), svc_age) if a is not None]
    if not ages:
        verdict = "no cache activity recorded yet"
    elif min(ages) >= IDLE_DONE_S:
        verdict = f"idle >= {IDLE_DONE_S} s: shader compilation looks finished"
    else:
        verdict = f"still compiling (activity {min(ages)} s ago)"
    st = {"active": active, "active_newest_age_s": _age_s(active_newest), "slots": slots,
          "service_log": {"name": first_svc, "age_s": svc_age} if first_svc else None,
          "game_log": game_counts, "verdict": verdict}
    if args.json:
        print(json.dumps(st, indent=2))
        return 0
    print(f"active   {SHADER_CACHE['link']} -> {active}")
    for key, s in slots.items():
        newest = "-" if s["newest_mtime"] is None else f"{s['newest_mtime']} ({s['newest_age_s']} s ago)"
        print(f"slot     {key:<6} {s['label']:<18} {s['files']:>5} files  newest {newest}")
    age = "-" if st["active_newest_age_s"] is None else f"{st['active_newest_age_s']} s ago"
    print(f"newest file in active slot: {age}")
    if first_svc:
        print(f"service log ({first_svc}): {'-' if svc_age is None else f'{svc_age} s ago'}")
    if game_counts is None:
        print(f"game log: {LOG_FILES['game'].name} not readable")
    else:
        print(f"game log (last {SHADER_LOG_TAIL // 2**20} MB): Global Cache Miss x{game_counts['global_cache_miss']}, "
              f"crc mismatch x{game_counts['crc_mismatch']}")
    print(verdict)
    return 0


def cmd_run(args, env) -> int:
    extra = strip_sep(args.extra)
    check_display()
    pid = running_pid("game", GAME_MATCH)
    if pid:
        die(f"game already running (pid {pid}); `make stop` first", 3)
    ensure_shader_cache(ENGINE, env)
    if args.build:
        rc = do_build(args.compiler, args.type, env)
        if rc:
            return rc
    ensure_plugin(env)
    if SERVICES and not args.no_services:
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
    print(f"game: running (pid {pid}); stdout {DEV_REL}/logs/game.out.log, engine log game.log; stop with `make stop`")
    return 0


def cmd_debug(args, env) -> int:
    extra = strip_sep(args.extra)
    check_display()
    if running_pid("game", GAME_MATCH):
        die("game already running; `make stop` first", 3)
    ensure_shader_cache(ENGINE, env)
    ensure_plugin(env)
    if SERVICES and not args.no_services:
        rc = cmd_up(args, env)
        if rc:
            return rc
    cmd, cwd = launcher_cmd(env, extra)
    gdb = ["gdb", "-q", "-ex", "set pagination off",
           "-ex", "handle SIGTRAP nostop noprint nopass",
           "-ex", f"set solib-search-path {ROOT / cfg_req('plugin_out_dir')}"]
    if not args.batch:
        return run([*gdb, "--args", *cmd], cwd=cwd, env=env)
    log = LOGS / "gdb.log"
    LOGS.mkdir(parents=True, exist_ok=True)
    full = [*gdb, "-batch", "-ex", "run", "-ex", "bt 40", "-ex", "thread apply all bt 12", "--args", *cmd]
    print(f"$ {' '.join(full)}  > {DEV_REL}/logs/gdb.log", flush=True)
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
    so = ROOT / cfg_req("plugin_out_dir") / cfg_req("plugin_lib")
    plugin_lib = cfg_req("plugin_lib")
    deployed = Path(ed) / engine_bin_rel() / plugin_lib if ed else None
    fmt = lambda p: time.strftime("%F %T", time.localtime(p.stat().st_mtime)) if p and p.exists() else None
    deployed_all = {}
    for k in ENGINES:
        d = resolve_engine_dir(env, k)
        deployed_all[k] = fmt(Path(d) / engine_bin_rel() / plugin_lib) if d else None
    st = {
        "engine": ENGINE,
        "engine_label": ENGINES[ENGINE]["label"],
        "cryengine_dir": ed,
        "deployed_per_engine": deployed_all,
        "services": {n: {"running": bool(running_pid(n, s["match"])), "pid": running_pid(n, s["match"]),
                         "port_open": port_open(s["port"])} for n, s in SERVICES.items()},
        "game": {"running": bool(running_pid("game", GAME_MATCH)), "pid": running_pid("game", GAME_MATCH)},
        "plugin": {"built": fmt(so), "deployed": fmt(deployed)},
        "builds": {c: build_info(c, env) for c in ENGINES[ENGINE]["presets"]},
        "tooling": {"version": tool_version(), "vendored_commit": vendored_commit()},
    }
    if VENV_PY is not None:
        st["venv"] = VENV_PY.exists()
    return st


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
    if "venv" in st:
        print(f"venv     {'ok' if st['venv'] else 'missing (make setup)'}")
    t = st["tooling"]
    print(f"tooling  {t['version']}" + (f"  (vendored {t['vendored_commit'][:8]})" if t["vendored_commit"] else ""))
    return 0


def tooling_checks() -> list[tuple[str, bool, bool]]:
    """Doctor rows about the tooling release (never required: warn, not MISS)."""
    tv = tool_version()
    rows = [(f"tooling version {tv}", True, False)]
    pin = CONFIG.get("tools_version")
    if pin is not None and pin != tv:
        rows.append((f"tools_version pin {pin} != tooling {tv} (re-vendor or update the pin)", False, False))
    integ = vendored_integrity()
    if integ is not None and "error" in integ:
        rows.append((f"vendored tooling marker unreadable: {integ['error']}", False, False))
    elif integ is not None and integ["modified"]:
        rows.append((f"vendored tooling files modified locally: {', '.join(integ['modified'])} "
                     "(change the tooling repo, release, re-vendor)", False, False))
    elif integ is not None:
        rows.append(("vendored tooling unmodified", True, False))
    return rows


def cmd_doctor(args, env) -> int:
    ed = env.get("CRYENGINE_DIR")
    launcher = launcher_name()
    extra_bins = [(c, c) if isinstance(c, str) else (c.get("label", c["bin"]), c["bin"])
                  for c in CONFIG.get("doctor_extra_compilers", [])]
    checks = [
        ("CRYENGINE_DIR set", bool(ed), True),
        ("engine dir exists", bool(ed) and Path(ed).is_dir(), True),
        (f"{launcher} present", bool(ed) and (Path(ed) / engine_bin_rel() / launcher).exists(), True),
        *[(f"{s['label']} engine dir ({k})", bool(resolve_engine_dir(env, k)) and Path(resolve_engine_dir(env, k)).is_dir(), False)
          for k, s in ENGINES.items()],
        ("cmake", bool(shutil.which("cmake")), True),
        ("ninja", bool(shutil.which("ninja")), True),
        *[(label, bool(shutil.which(b)), False) for label, b in extra_bins],
        ("gdb (debug)", bool(shutil.which("gdb")), False),
        *([("wine (shader server)", bool(shutil.which("wine")), False)] if SERVICES else []),
        ("display session (run/debug)", bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")), False),
        *([(f"python venv ({CONFIG['python']['venv']})", VENV_PY.exists(), False)] if VENV_PY is not None else []),
    ]
    if args.cmd == "doctor":  # tooling rows: only for `doctor` itself, not the doctor step inside `setup` (its output is golden)
        checks += tooling_checks()
    bad = 0
    for label, ok, required in checks:
        print(f"{'ok  ' if ok else ('MISS' if required else 'warn')}  {label}")
        bad += (not ok) and required
    return 1 if bad else 0


def cmd_setup(args, env) -> int:
    py = CONFIG.get("python", {})
    if VENV_PY is not None and py.get("requirements"):
        if not VENV_PY.exists():
            rc = run([sys.executable, "-m", "venv", str(ROOT / py["venv"])])
            if rc:
                return rc
        rc = run([python_exe(), "-m", "pip", "install", "-q", "-r", str(ROOT / py["requirements"])])
        if rc:
            return rc
    if not DRY:
        PIDS.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
    rc = cmd_doctor(args, env)
    if rc == 0:
        rc = do_configure(args.compiler, args.type, env)
    return rc


# --------------------------------------------------------------------------- project verbs (config `extra_verbs`)

def cmd_extra(verb_spec: dict, args, env) -> int:
    """`<verb>` from config extra_verbs: <venv python> -m <module> | <script>, then fixed_args, then user args (after `--`) or default_args."""
    head = ["-m", verb_spec["python_module"]] if "python_module" in verb_spec else [verb_spec["python_script"]]
    user = strip_sep(args.extra) or verb_spec.get("default_args", [])
    return run([python_exe(), *head, *verb_spec.get("fixed_args", []), *user], env=env)


# --------------------------------------------------------------------------- cli

def main() -> int:
    global DRY, ENGINE, CONFIG, ENGINES, COMPILERS
    if _asked_for_version(sys.argv[1:]):  # before the config is loaded: works in any directory
        print(version_line())
        return 0
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--project-dir")
    known, _ = pre.parse_known_args()
    project = Path(os.path.abspath(known.project_dir or os.environ.get("CRY_DEV_PROJECT_DIR") or os.getcwd()))
    CONFIG = load_config(project)
    init_project(project)
    ENGINES = engines_from(CONFIG["engines"])
    COMPILERS = compilers_from(ENGINES)
    ENGINE = CONFIG["default_engine"]

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--project-dir", default=None,
                   help="project root (default: env CRY_DEV_PROJECT_DIR, else the current directory)")
    p.add_argument("--version", action="version", version=version_line(),
                   help="print the tooling version (and the vendored commit, if any) and exit")
    p.add_argument("--dry-run", action="store_true", help="print what would run; change nothing")
    p.add_argument("--engine", choices=ENGINES,
                   default=os.environ.get("ENGINE") if os.environ.get("ENGINE") in ENGINES else CONFIG["default_engine"],
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
    if SHADER_CACHE:
        sp = add("shaders-status", cmd_shaders_status, "shader cache slots and compile progress")
        sp.add_argument("--json", action="store_true")
    for name, spec in CONFIG.get("extra_verbs", {}).items():
        add(name, partial(cmd_extra, spec), spec["help"], extra=True)

    args = p.parse_args()
    DRY = args.dry_run
    ENGINE = args.engine
    env = load_env()
    for spec in ENGINES.values():
        # legacy variable name (e.g. CRYENGINE_DIR for 5.6.7): capture before CRYENGINE_DIR is overwritten below
        if spec["fallback"] and env.get(spec["fallback"]) and not env.get(spec["env"]):
            env[spec["env"]] = env[spec["fallback"]]
    path = resolve_engine_dir(env, ENGINE)
    if path:
        env["CRYENGINE_DIR"] = path  # everything downstream (cmake, launcher, status) reads this
    elif ENGINE != CONFIG["default_engine"] or args.cmd in ("build", "run", "debug", "configure", "setup", "clean"):
        spec = ENGINES[ENGINE]
        die(f"{spec['label']}: set {spec['env']} in {CONFIG.get('env_file', '.env')} (path of the checkout), or export it.", 2)
    return args.fn(args, env) or 0


if __name__ == "__main__":
    sys.exit(main())
