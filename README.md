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

## Configure

Run from the project root:

```bash
cmake -B build -G Ninja \
  -S Code \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$CRYENGINE_DIR/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-9 \
  -DCMAKE_CXX_COMPILER=g++-9
```

Available build types: `Debug`, `Profile`, `Release`.

> After deleting the build directory, always do a full reconfigure (`rm -rf build && cmake -B build ...`).
> A bare `cmake -B build` with a stale cache will not regenerate the unity build files and the build will fail.

## Build

```bash
cmake --build build --parallel $(nproc)
```

Output: `bin/linux_x64_gcc/libGamePlugin.so`

The post-build step automatically copies the plugin to `$CRYENGINE_DIR/bin/linux_x64_gcc/`, where the engine looks for it at runtime.

## Run

```bash
$CRYENGINE_DIR/bin/linux_x64_gcc/GameLauncher \
  -project /path/to/FirstPersonShooter/Game.cryproject
```

The working directory must be `$CRYENGINE_DIR/bin/linux_x64_gcc/` (the launcher sets `MODULE_PATH` from its CWD, which is how the engine locates plugins).

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

CRYENGINE's Vulkan renderer requires a running shader compiler server to compile HLSL shaders to SPIR-V at runtime. On Linux this is provided by `cry_shader_server.py`, which implements the CrySCompileServer wire protocol using Wine + DXC.

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
│   ├── cry_shader_server.py # Remote shader compiler server (Wine + DXC)
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

- [docs/](docs/README.md) — architecture overview, asset pipeline guide, known issues, and the CRYENGINE 5.6 knowledge base (terrain, textures, LOD, lighting, characters, DDS formats), with a "something looks wrong" symptom table.

## Working with AI agents

This project carries a maintained agent context layer: [`AGENTS.md`](AGENTS.md) (entry point), `.agents/` (conventions, workflows, status, workstreams) and `.memory/` (indexes and component cards). `CLAUDE.md` only adds Claude-specific notes. Regenerate or refresh it with the `khem:project-agentize` skill after significant changes.
