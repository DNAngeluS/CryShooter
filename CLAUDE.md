# CLAUDE.md — FirstPersonShooter

CRYENGINE 5.6 First Person Shooter game plugin project (C++, Linux).
Supported compilers: GCC 9 (default), GCC 14, Clang 22.

## Prerequisites

The engine path must be configured once per machine. Choose one approach:

### VS Code

Add to `.vscode/settings.json` (gitignored — create it if it doesn't exist):

```json
{
    "cmake.sourceDirectory": "${workspaceFolder}/Code",
    "cryengineDir": "/path/to/CRYENGINE",
    "cmake.useCMakePresets": "always",
    "cmake.environment": {
        "CRYENGINE_DIR": "/path/to/CRYENGINE"
    }
}
```

`cryengineDir` is used by tasks and launch configs (`${config:cryengineDir}`).
`cmake.environment.CRYENGINE_DIR` feeds the CMake presets — keep both paths in sync.
Note: `${config:cryengineDir}` is **not** expanded inside `cmake.environment`; the path must be set literally there.

### CLI

Copy `.env.example` to `.env` (gitignored) and fill in your path, then source it:

```bash
cp .env.example .env
# edit .env and set CRYENGINE_DIR
source .env
```

Or export directly in your shell profile (`~/.bashrc`, `~/.zshrc`) for a permanent setup.

## Project Structure

```
FirstPersonShooter/
├── Game.cryproject          # Project definition (engine version, plugins, assets)
├── Assets/
│   └── levels/              # Game levels (created via Sandbox editor)
├── tools/
│   ├── cry_shader_server.py # Remote shader compiler server (Wine + DXC)
│   ├── cry_asset_pipeline.py # Natural-language asset pipeline CLI
│   ├── cry_asset_tracker.py  # Conversation resume / tracking CLI
│   └── asset_pipeline/       # Internal asset pipeline helpers
├── Code/
│   ├── CMakeLists.txt        # Build definition
│   ├── GamePlugin.cpp/h      # ICryPlugin entry point, network listener
│   ├── StdAfx.cpp/h          # Precompiled header
│   └── Components/
│       ├── Player.cpp/h      # First-person player (camera, movement, input, shooting)
│       ├── SpawnPoint.cpp/h  # Spawn location marker
│       └── Bullet.h          # Projectile physics component
├── docs/                     # Human-readable engine knowledge base
│   ├── asset_pipeline.md     # Pipeline workflow, commands, and constraints
│   ├── terrain.md            # Level files, water, spawn points, env presets
│   ├── lod.md                # Terrain LOD CVars, z-fighting causes and fixes
│   ├── textures.md           # cover.ctc binary format, Python generation
│   ├── character_mesh.md     # Mannequin, CDF, camera, character controller
│   └── lighting.md           # TOD system, .env presets, sky, shadows, CVars
└── memory/                   # LLM-focused JSON quick-reference (machine-readable)
    ├── asset_pipeline_plan.json
    ├── asset_pipeline_interface.json
    ├── asset_pipeline_tracker.json
    ├── terrain.json
    ├── lod.json
    ├── textures.json
    ├── character_mesh.json
    └── lighting.json
```

The game is built as a shared library (`libGamePlugin.so`) loaded by the engine at runtime.

## Configure

Run from the project root (`FirstPersonShooter/`). Three compiler options are supported:

### GCC 9 (default)

```bash
cmake -B build/gcc -G Ninja \
  -S Code \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$CRYENGINE_DIR/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-9 \
  -DCMAKE_CXX_COMPILER=g++-9
```

### GCC 14 (latest stable)

```bash
cmake -B build/gcc14 -G Ninja \
  -S Code \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$CRYENGINE_DIR/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-14 \
  -DCMAKE_CXX_COMPILER=g++-14
```

### Clang (system clang)

Uses the project-local toolchain at `cmake/toolchain/Linux_Clang_System.cmake`.
By default the plugin deploys to `linux_x64_gcc/` (where the GCC-compiled engine lives).
Pass `-DCLANG_OUTPUT_DIR_NAME=linux_x64_clang` when building against a full Clang engine.

```bash
cmake -B build/clang -G Ninja \
  -S Code \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$(pwd)/cmake/toolchain/Linux_Clang_System.cmake
```

Change build type by replacing `-DCMAKE_BUILD_TYPE=Debug` with `Profile` or `Release`.

## Build

```bash
cmake --build build/gcc --parallel $(nproc)    # GCC 9
cmake --build build/gcc14 --parallel $(nproc)  # GCC 14
cmake --build build/clang --parallel $(nproc)  # Clang
```

Output: `bin/linux_x64_gcc/libGamePlugin.so` (project root).
The post-build step also copies it to `$CRYENGINE_DIR/bin/linux_x64_gcc/` automatically.

> **After deleting a build directory**, always do a full reconfigure (e.g. `rm -rf build/gcc && cmake -B build/gcc ...`).
> A partial re-run with a stale cache will not regenerate the uber files
> (`GamePlugin_uber.cpp`, `Components_uber.cpp`) and the build will fail.

## Run

```bash
$CRYENGINE_DIR/bin/linux_x64_gcc/GameLauncher \
  -project $PROJECT_ROOT/Game.cryproject
```

> The build automatically copies `libGamePlugin.so` to the engine's bin dir via a post-build step.
> This is required because on Linux, `CryLoadLibrary` resolves plugin names relative to `MODULE_PATH`,
> which the launcher sets to its own directory (the engine's bin dir) at startup.

## Adding a New Component

1. Create `Code/Components/MyComponent.h` and `.cpp`
2. Add both files to `Code/CMakeLists.txt` under the `Components_uber.cpp` `add_sources()` block
3. In the `.cpp`, include `StdAfx.h` first, then register via `CRY_STATIC_AUTO_REGISTER_WITH_PARAM` or `CRYREGISTER_CLASS`

## Asset Pipeline Tools

The repo now includes a staged Python asset pipeline for natural-language driven CRYENGINE packages.

### `tools/cry_asset_pipeline.py`

Implemented slices:
- `level` jobs: prompt -> spec -> staged CRYENGINE level package -> validate -> publish into `Assets/levels/`
- `mesh_import` jobs: local source mesh -> staged import package -> validation -> optional compiler hand-off

Examples:

```bash
python3 tools/cry_asset_pipeline.py run \
  --kind level \
  --prompt "small desert combat arena at noon" \
  --target-package desert_arena

python3 tools/cry_asset_pipeline.py convert-mesh \
  --input /path/to/model.obj \
  --target Objects/Imported/model
```

The staging root is `user/asset_pipeline/jobs/`.

### `tools/cry_asset_tracker.py`

Uses `memory/asset_pipeline_tracker.json` to preserve roadmap state, active jobs, and resume context for future LLM sessions.

```bash
python3 tools/cry_asset_tracker.py status
python3 tools/cry_asset_tracker.py next
python3 tools/cry_asset_tracker.py resume
```

## Key Engine Paths

| Resource | Path |
|----------|------|
| Engine headers | `$CRYENGINE_DIR/Code/CryEngine/CryCommon/` |
| Default component headers | `$CRYENGINE_DIR/Code/CryPlugins/CryDefaultEntities/Module/` |
| Engine binaries | `$CRYENGINE_DIR/bin/linux_x64_gcc/` |
| CMake helpers | `$CRYENGINE_DIR/Tools/CMake/` |

## Build Configurations

| Config | Defines | Optimisation |
|--------|---------|--------------|
| `Debug` | `_DEBUG`, `DEBUG` | `-O0 -g` |
| `Profile` | `_PROFILE`, `NDEBUG` | `-O2` |
| `Release` | `_RELEASE`, `NDEBUG` | `-O3` |
