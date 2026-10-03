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

The repo now includes a staged Python asset pipeline for **LLM-authored, bundle-graph-driven** CRYENGINE packages.

### Python venv (required for procgen)

The procgen modules require the `noise` package. Set up a venv once:

```bash
python3 -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.txt
```

Run tests with the venv interpreter:

```bash
tools/.venv/bin/python3 -m pytest tests/ -v
```

### `tools/cry_asset_pipeline.py`

Implemented slices:
- `level` jobs: brief -> authoring artifacts -> authored bundle graph -> staged CRYENGINE level package -> validate -> publish into `Assets/levels/`
- `character_package` jobs: imported character source -> authored bundle graph -> first-person runtime package -> validate -> publish into `Assets/`
- `mesh_import` jobs: local source mesh -> staged import package -> validation -> optional compiler hand-off

Examples:

```bash
python3 tools/cry_asset_pipeline.py create-job \
  --kind level \
  --prompt "small desert combat arena at noon" \
  --target-package desert_arena

python3 tools/cry_asset_pipeline.py plan-spec --job level-desert-arena
python3 tools/cry_asset_pipeline.py author-spec --job level-desert-arena --json-file ./asset_graph.json
python3 tools/cry_asset_pipeline.py build --job level-desert-arena
python3 tools/cry_asset_pipeline.py validate --job level-desert-arena
python3 tools/cry_asset_pipeline.py publish --job level-desert-arena

python3 tools/cry_asset_pipeline.py create-job \
  --kind character_package \
  --prompt "first-person rifleman" \
  --target-package fps_rifleman \
  --source-input /path/to/fps_rifleman.fbx

python3 tools/cry_asset_pipeline.py convert-mesh \
  --input /path/to/model.obj \
  --target Objects/Imported/model
```

The staging root is `user/asset_pipeline/jobs/`.

Level jobs accept either a package slug (for example `fps_forest_basin`) or a full level path like
`Assets/levels/fps_forest_basin`; the pipeline normalizes the latter so the publish destination
still lands in `Assets/levels/fps_forest_basin/` instead of duplicating the path segments.

The pipeline no longer asks Python to interpret prose into terrain, geometry, materials, textures,
or character structure. The LLM authors the canonical bundle `asset_graph.json`, Python validates
that graph against the checked-in capability/template catalogs, then compiles node dependencies in
order. Supported node types:

| Node type | Description |
|-----------|-------------|
| `scene_level` | Top-level level assembly node |
| `terrain_archetype` | Golden-template terrain (copy from verified template) |
| `terrain_procgen` | Procedurally generated open terrain (forest/desert/tundra/swamp/savanna/volcanic) |
| `interior_procgen` | Procedurally generated interior (cave/dungeon/ship/bunker/sewer) |
| `structured_procgen` | Procedurally generated structured level (castle/arena/fortress/warehouse/ruins) |
| `texture_source` | Texture input (baked or imagegen-requested) |
| `material_surface` | Material combining texture nodes |
| `mesh_procedural` | Procedurally generated mesh |
| `mesh_import` | Imported FBX/OBJ/DAE mesh |
| `object_placement_set` | Placement list referencing mesh/material nodes |
| `character_fp_package` | First-person character package |

Level compilation copies golden terrain binaries from verified templates, rebuilds terrain texture
packs, writes level layers from placement nodes, and validates `heightmap.dat`, `terrain.dat`,
`terraintexture.pak`, cross-file XML consistency, and placement references. For `terrain_procgen`
nodes the pipeline generates `terrain.dat` natively from the procgen heightmap via
`tools/asset_pipeline/procgen/terrain_dat_writer.py` — no Sandbox required. Character compilation
packages imported FBX/DAE sources into the first-person runtime contract used by `Player.cpp`,
including `.cdf`, controller definition XML, and `.adb` outputs.

The pipeline auto-inserts a `CSpawnPointComponent` entity into `main.lyr` at the position
specified in `scene_spec["spawn"]["transform"]["position"]`. `SpawnPoint.h::GetFirstSpawnPointTransform()`
falls back to terrain center + 10 m elevation when no spawn point exists in the level.

`imagegen` is now a supported texture node mode in the graph contract, but the current compiler only
emits image-generation request artifacts plus deterministic fallback PNGs; it does not call an
external image generator directly yet.

`Code/GamePlugin.cpp` auto-loads `fps_forest_basin` on `ESYSTEM_EVENT_GAME_POST_INIT` when the
game runs outside the editor so newly generated gameplay levels can be smoke-tested from
`GameLauncher` without changing the startup map command each time. `Esc` remains bound in the
local player input path, but shutdown is now deferred to the next update tick instead of calling
`gEnv->pSystem->Quit()` directly inside the input callback.

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
