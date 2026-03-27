# CLAUDE.md — FirstPersonShooter

CRYENGINE 5.6 First Person Shooter game plugin project (C++, Linux/GCC-9).

## Project Structure

```
FirstPersonShooter/
├── Game.cryproject          # Project definition (engine version, plugins, assets)
├── Assets/
│   └── levels/              # Game levels (created via Sandbox editor)
└── Code/
    ├── CMakeLists.txt        # Build definition
    ├── GamePlugin.cpp/h      # ICryPlugin entry point, network listener
    ├── StdAfx.cpp/h          # Precompiled header
    └── Components/
        ├── Player.cpp/h      # First-person player (camera, movement, input, shooting)
        ├── SpawnPoint.cpp/h  # Spawn location marker
        └── Bullet.h          # Projectile physics component
```

The game is built as a shared library (`libGamePlugin.so`) loaded by the engine at runtime.

## Configure

Run from the project root (`FirstPersonShooter/`):

```bash
cmake -B build -G Ninja \
  -S Code \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCRYENGINE_DIR=CRYENGINE_DIR_PATH \
  -DCMAKE_TOOLCHAIN_FILE=CRYENGINE_DIR_PATH/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-9 \
  -DCMAKE_CXX_COMPILER=g++-9
```

Change build type by replacing `-DCMAKE_BUILD_TYPE=Debug` with `Profile` or `Release`.

## Build

```bash
cmake --build build --parallel $(nproc)
```

Output: `bin/linux_x64_gcc/libGamePlugin.so` (project root).
The post-build step also copies it to `$CRYENGINE_DIR/bin/linux_x64_gcc/` automatically.

> **After deleting the build directory**, always do a full reconfigure (`rm -rf build && cmake -B build ...`).
> A partial re-run of `cmake -B build` with a stale cache will not regenerate the uber files
> (`GamePlugin_uber.cpp`, `Components_uber.cpp`) and the build will fail.

## Run

```bash
CRYENGINE_DIR_PATH/bin/linux_x64_gcc/GameLauncher \
  -project PROJECT_DIR_PATH/Game.cryproject
```

> The build automatically copies `libGamePlugin.so` to the engine's bin dir via a post-build step.
> This is required because on Linux, `CryLoadLibrary` resolves plugin names relative to `MODULE_PATH`,
> which the launcher sets to its own directory (the engine's bin dir) at startup.

## Adding a New Component

1. Create `Code/Components/MyComponent.h` and `.cpp`
2. Add both files to `Code/CMakeLists.txt` under the `Components_uber.cpp` `add_sources()` block
3. In the `.cpp`, include `StdAfx.h` first, then register via `CRY_STATIC_AUTO_REGISTER_WITH_PARAM` or `CRYREGISTER_CLASS`

## Key Engine Paths

| Resource | Path |
|----------|------|
| Engine headers | `CRYENGINE_DIR_PATH/Code/CryEngine/CryCommon/` |
| Default component headers | `CRYENGINE_DIR_PATH/Code/CryPlugins/CryDefaultEntities/Module/` |
| Engine binaries | `CRYENGINE_DIR_PATH/bin/linux_x64_gcc/` |
| CMake helpers | `CRYENGINE_DIR_PATH/Tools/CMake/` |

## Build Configurations

| Config | Defines | Optimisation |
|--------|---------|--------------|
| `Debug` | `_DEBUG`, `DEBUG` | `-O0 -g` |
| `Profile` | `_PROFILE`, `NDEBUG` | `-O2` |
| `Release` | `_RELEASE`, `NDEBUG` | `-O3` |
