# First Person Shooter

A first-person shooter game plugin for [CRYENGINE 5.6](https://www.cryengine.com/), written in C++.

The game code compiles as a shared library (`libGamePlugin.so`) that the engine loads at runtime. It includes a first-person player controller with camera, movement, input handling, and shooting, along with spawn points and a projectile component.

## Prerequisites

| Requirement | Version |
|-------------|---------|
| CRYENGINE | 5.6 |
| CMake | 3.14+ |
| Ninja | any |
| GCC | 9 (`gcc-9`, `g++-9`) |

The engine path must be configured once per machine. Choose one approach:

**VS Code** — create `.vscode/settings.json` (gitignored):
```json
{
    "cmake.sourceDirectory": "${workspaceFolder}/Code",
    "cryengineDir": "/path/to/CRYENGINE"
}
```
Tasks and launch configurations read `${config:cryengineDir}` from this file automatically.

**CLI** — copy `.env.example` to `.env` (gitignored) and source it:
```bash
cp .env.example .env
# edit .env and set CRYENGINE_DIR
source .env
```

## Dev commands

Day-to-day development goes through `make` (a thin menu over the generic runner `tools/cryengine-dev/dev.py`, which needs only Python 3 and
`make`; FPS settings are in `cryengine-dev.config.json`, schema in `tools/cryengine-dev/config-schema.md`; `tools/dev.py` is a forwarding shim). It works from a plain terminal — no IDE required — and every command is safe for scripts and AI agents:
nothing blocks unless you ask it to, commands are idempotent, and background output goes to `.dev/logs/`.

```bash
make help        # list every target
make setup       # first time: Python venv + deps, prerequisite check, CMake configure
make doctor      # check engine path, compilers, gdb, wine, display session
```

| Goal | Command |
|------|---------|
| Compile the plugin (deploys to the engine bin dir) | `make build` |
| Production build (Release) | `make release` |
| Play: start services + launch the game in the background | `make run` |
| Build Release, then play | `make run-release` |
| Debug in gdb (interactive) | `make debug` |
| Debug in gdb, non-interactive; backtrace saved to `.dev/logs/gdb.log` | `make debug-batch TIMEOUT=120` |
| Start / stop only the shader compiler server | `make up` / `make down` |
| Stop the game and all services | `make stop` |
| What is running, what is built | `make status` (`python3 tools/dev.py status --json` for scripts) |
| Warnings and errors from the engine log | `make logs` (`make logs-all` for the raw tail) |
| Shader cache per engine and compile progress | `make shaders-status` |
| Python tests | `make test` |
| Asset pipeline CLI | `make pipeline ARGS="plan-spec --job level-fps-forest-basin"` |

Choose the engine (`ENGINE=56` default = CRYENGINE 5.6.7, `ENGINE=57` = 5.7.1 via `CRYENGINE_DIR_57` in `.env`), compiler and build type with variables: `make build COMPILER=gcc14 TYPE=Profile`
(`COMPILER` = `gcc9` (default) \| `gcc13` (5.7.1 engine) \| `gcc14` \| `clang`; `TYPE` = `Debug` (default) \| `Profile` \| `Release`).
Pass arguments to the game with `make run ARGS="..."`.

Typical loop: `make build && make run`, play, `make logs`, `make stop`.

Notes:
- The engine path comes from `CRYENGINE_DIR` in your environment or `.env` (see [Prerequisites](#prerequisites)); `make` reads `.env` itself, so you do not need to `source` it.
- `make run` / `make debug` need a desktop session (`DISPLAY` or `WAYLAND_DISPLAY`) and start the shader compiler server first, because `system.cfg` enables remote shader compilation.
- Services and the game are tracked in `.dev/pids/`; `make stop` is always safe to run.
- The manual cmake commands below still work; `make` just wraps the presets in `Code/CMakePresets.json`.

## Manual build and run (what `make` wraps)

```bash
cd Code
cmake --preset gcc9            # or gcc13 / gcc14 / clang; add -DCMAKE_BUILD_TYPE=Profile|Release
cmake --build --preset gcc9    # output bin/linux_x64_gcc/libGamePlugin.so, auto-copied to $CRYENGINE_DIR/bin/linux_x64_gcc/
cd $CRYENGINE_DIR/bin/linux_x64_gcc && ./GameLauncher -project /path/to/FirstPersonShooter/Game.cryproject
```

The launcher must run from `$CRYENGINE_DIR/bin/linux_x64_gcc/`: it sets `MODULE_PATH` from its working directory, which is how the engine locates plugins.
After deleting a build directory, always do a full reconfigure — a stale cache will not regenerate the unity build files.
The presets read `CRYENGINE_DIR` from the environment (`source .env`).

## VS Code

The repository includes VS Code configuration for building, running, and debugging from the IDE.

**Setup**: create `.vscode/settings.json` as described in [Prerequisites](#prerequisites) above — the tasks and launch configs will not resolve the engine path without it.

| Action | How |
|--------|-----|
| Configure CMake (Debug) | **Terminal > Run Task > CMake Configure (Debug)** |
| Configure CMake (Profile) | **Terminal > Run Task > CMake Configure (Profile)** |
| Build | `Ctrl+Shift+B` |
| Start shader server | **Terminal > Run Task > Start Shader Server** |
| Launch & debug | **Run > Launch Game (Debug/Profile)** (`F5`) |
| Attach to running process | **Run > Attach to GameLauncher** |

GDB is pre-configured to suppress CRYENGINE's `SIGTRAP`-based soft assertions so the debugger does not stop on every library load.

## Development Tools

The `tools/` directory contains development utilities needed to run the project on Linux.

### Asset Pipeline (`tools/cry_asset_pipeline.py`)

Natural-language oriented tooling for CRYENGINE-compatible asset packages.

Implemented slices:
- `level` jobs: prompt -> structured spec -> staged CRYENGINE level package -> validation -> publish
- `mesh_import` jobs: local mesh source -> staged import package -> validation -> optional compiler hand-off

**Examples:**
```bash
python3 tools/cry_asset_pipeline.py run \
  --kind level \
  --prompt "small desert combat arena at noon" \
  --target-package desert_arena

python3 tools/cry_asset_pipeline.py convert-mesh \
  --input /path/to/model.obj \
  --target Objects/Imported/model
```

The staged workspace lives under `user/asset_pipeline/jobs/` and is gitignored.

### Tracker (`tools/cry_asset_tracker.py`)

Reads and updates `memory/asset_pipeline_tracker.json` so future LLM sessions can resume the current pipeline state.

```bash
python3 tools/cry_asset_tracker.py status
python3 tools/cry_asset_tracker.py next
python3 tools/cry_asset_tracker.py resume
```

### Shader Server (`tools/cry_shader_server.py`)

CRYENGINE's Vulkan renderer requires a running shader compiler server to compile HLSL shaders to SPIR-V at runtime. On Linux this is provided by `cry_shader_server.py`, which implements the CrySCompileServer wire protocol using Wine + DXC. The real file is `tools/cryengine-dev/cry_shader_server.py`; `tools/cry_shader_server.py` is a forwarding shim.

**Prerequisites:** `wine`, `python3`

**Start (CLI):**
```bash
source .env  # or: export CRYENGINE_DIR=/path/to/CRYENGINE
python3 tools/cry_shader_server.py
```

**Start (VS Code):** `Terminal > Run Task > Start Shader Server`

The server must be running before you launch the game. It listens on `127.0.0.1:61453` and stays alive until you kill it (`Ctrl+C`).

The following CVars in `system.cfg` activate the remote compiler (already set in this project):
```
r_ShadersRemoteCompiler=1
r_ShaderCompilerServer=127.0.0.1
r_VkShaderCompiler=DXC
```

## Project Structure

```
FirstPersonShooter/
├── Game.cryproject          # Project definition (engine version, plugins, assets)
├── Assets/
│   └── levels/              # Game levels (created via Sandbox editor)
├── tools/
│   ├── cry_shader_server.py # Shim → tools/cryengine-dev/cry_shader_server.py (Wine + DXC)
│   ├── cry_asset_pipeline.py # Natural-language asset pipeline CLI
│   ├── cry_asset_tracker.py  # Asset tracker / resume CLI
│   └── asset_pipeline/       # Internal helpers for level generation and mesh import
├── .env.example             # Template for CLI env var setup (copy to .env)
├── .vscode/                 # VS Code build/launch/IntelliSense config
├── docs/
│   └── asset_pipeline.md     # Human-readable asset pipeline reference
└── memory/
    ├── asset_pipeline_plan.json
    ├── asset_pipeline_interface.json
    └── asset_pipeline_tracker.json
└── Code/
    ├── CMakeLists.txt        # Build definition
    ├── GamePlugin.cpp/h      # ICryPlugin entry point
    ├── StdAfx.cpp/h          # Precompiled header
    └── Components/
        ├── Player.cpp/h      # First-person player (camera, movement, input, shooting)
        ├── SpawnPoint.cpp/h  # Spawn location marker
        └── Bullet.h          # Projectile physics component
```

## Adding a New Component

1. Create `Code/Components/MyComponent.h` and `MyComponent.cpp`
2. Add both files to `Code/CMakeLists.txt` under the `Components_uber.cpp` `add_sources()` block
3. In the `.cpp`, `#include "StdAfx.h"` first, then register the component via `CRYREGISTER_CLASS` or `CRY_STATIC_AUTO_REGISTER_WITH_PARAM`

## Build Configurations

| Config | Defines | Optimisation |
|--------|---------|--------------|
| `Debug` | `_DEBUG`, `DEBUG` | `-O0 -g` |
| `Profile` | `_PROFILE`, `NDEBUG` | `-O2` |
| `Release` | `_RELEASE`, `NDEBUG` | `-O3` |

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — milestones and anything that could break a working setup.
- [docs/](docs/README.md) — architecture overview, asset pipeline guide, known issues, and the CRYENGINE 5.6 knowledge base (terrain, textures, LOD, lighting, characters, DDS formats), with a "something looks wrong" symptom table.

## Working with AI agents

This project carries a maintained agent context layer: [`AGENTS.md`](AGENTS.md) (entry point), `.agents/` (conventions, workflows, status, workstreams) and `.memory/` (indexes and component cards). `CLAUDE.md` only adds Claude-specific notes. Regenerate or refresh it with the `khem:project-agentize` skill after significant changes.
