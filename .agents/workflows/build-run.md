<!-- when: configuring, building, running or debugging the C++ plugin (libGamePlugin.so) -->
# Build, run, debug the plugin

**Use `make` first** (`make help`; implemented in the generic `tools/plasmid-dev/plas-dev`, with FPS settings in
`plasmid.config.json`): `make setup`, `make build`, `make run`,
`make debug-batch`, `make status`, `make shaders-status`, `make logs`, `make stop`. It wraps the presets in `Code/CMakePresets.json`
(build dirs `build/gcc`, `build/gcc13`, `build/gcc14`, `build/clang`), reads `.env` itself, starts the shader server, and logs
to `.dev/logs/`. The manual commands below are the reference for what it runs and for the gotchas.

Run everything from the project root. Needs `CRYENGINE_DIR` (`source .env`).

## Two engines: `ENGINE=56|57`

`make <target> ENGINE=57` builds/runs against CRYENGINE 5.7.1 (`CRYENGINE_DIR_57` in `.env`; default compiler gcc13,
preset `e57-gcc13`, build dir `build/e57-gcc13`). `ENGINE=56` (default) is 5.6.7 + gcc9 = `build/gcc`, the directory
VS Code uses — **never repoint it**. Each engine gets only its own plugin copy (`CRYENGINE*/bin/linux_x64_gcc/libGamePlugin.so`).
`make status [ENGINE=…]` shows the deployed plugin time for both. `Game.cryproject` (`engine-5.6`) is accepted unchanged
by 5.7.1. Both engines write the project-level `game.log` (appended) and their own `<engine>/game.log`.

## Shader cache per engine

`user/shaders/cache` is a relative symlink to `user/shaders/cache-by-engine/<56|57>`, switched automatically by
`make run` / `make debug`. The first run per engine is a cold cache: the window stays black for minutes while shaders
compile through the Wine+DXC server. Watch progress with `make shaders-status`. The old shared cache directory is kept
as `legacy-unlabelled`. (Implemented and accepted 2026-10-18 (56→57→56: third run 0 crc mismatch, 0 cache miss).)

## Configure (once per compiler)

```bash
# GCC 9 (default)
cmake -B build/gcc -G Ninja -S Code -DCMAKE_BUILD_TYPE=Debug -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$CRYENGINE_DIR/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-9 -DCMAKE_CXX_COMPILER=g++-9
# GCC 13 (what the 5.7.1 engine is built with) / GCC 14: same with build/gcc13|gcc14, gcc-13|14, g++-13|14
# Clang: project-local toolchain
cmake -B build/clang -G Ninja -S Code -DCMAKE_BUILD_TYPE=Debug -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$(pwd)/cmake/toolchain/Linux_Clang_System.cmake
# add -DCLANG_OUTPUT_DIR_NAME=linux_x64_clang only for a full Clang engine build
```

Build types: `Debug` (`-O0 -g`), `Profile` (`-O2`), `Release` (`-O3`).

## Build

`cmake --build build/<gcc|gcc13|gcc14|clang> --parallel $(nproc)`.
Output `bin/linux_x64_gcc/libGamePlugin.so`; POST_BUILD copies it to `$CRYENGINE_DIR/bin/linux_x64_gcc/`.

**After deleting a build dir, do a full reconfigure** (`rm -rf build/gcc && cmake -B build/gcc …`).
Uber files (`GamePlugin_uber.cpp`, `Components_uber.cpp`) are generated at configure time into the
binary dir; a partial re-run with a stale cache fails.

## Run

`$CRYENGINE_DIR/bin/linux_x64_gcc/GameLauncher -project $PWD/Game.cryproject`
Outside the editor the plugin auto-loads `kStartupLevel` (`Code/GamePlugin.cpp`) on `GAME_POST_INIT`.
In game: `K` toggles debug mode, `P` takes a screenshot (debug mode only), `Esc` quits (deferred to next tick).
Console `goto x y z [yaw [pitch]]` teleports the player; bare `goto` logs the position.

## Gotchas (each cost real debugging time)

- `Game.cryproject` Linux plugin entry must be bare `"GamePlugin"`; a path becomes `libbin/…`.
- `Configure.cmake:33` clears `OUTPUT_DIRECTORY_NAME`; recover with `get_filename_component(_bin_subdir "${OUTPUT_DIRECTORY}" NAME)`.
- GDB: `handle SIGTRAP nostop noprint nopass` — engine soft assertions and `ld.so` notifications use `int3`.
  `solib-search-path` = `${workspaceFolder}/bin/linux_x64_gcc`.
- The `Loading plug-in Game` error for `bin/win_x64/Game.dll` is expected and harmless on Linux.
- VS Code: `${config:cryengineDir}` expands in tasks/launch only, **not** in `cmake.environment`. Set
  `cmake.environment.CRYENGINE_DIR` literally in `.vscode/settings.json` and keep it equal to `cryengineDir`.
  With `cmake.useCMakePresets: always`, `cmake.configureSettings` is ignored; do not put `$env{CRYENGINE_DIR}`
  in `CMakePresets.json` cacheVariables (it breaks preset listing when unset). The system toolchain files `FORCE`
  `CRYENGINE_DIR` from env for that reason.
- GCC 14 needs two **engine** patches (re-apply per engine checkout): move the Schematyc partial specialization
  block after the `IEntityComponent` definition in `CryCommon/CryEntitySystem/IEntityComponent.h`, and add
  `#include <limits>` to `CryCommon/CryCore/Containers/CryArray.h`. In our code, `GamePlugin.cpp` uses `const auto&` in a range-for.
- Engine-side screenshot support was patched (see `debugging.md`); an engine rebuild is required for those.

## Optional: remote shader compiler

`python3 tools/plasmid-dev/plasmid_dev/shader_server.py` (Wine + DXC; vendored with plasmid-dev), then in `system.cfg`:
`r_ShadersRemoteCompiler=1`, `r_ShaderCompilerServer=127.0.0.1`, `r_VkShaderCompiler=DXC`.

> **Caveat (2026-10-18):** launching from VS Code (F5 / `launch.json` with preLaunchTask "CMake Build", or running GameLauncher directly) bypasses `make run`, so the per-engine shader-cache link is NOT switched. After using VS Code, or on first use of an engine, run `make shaders-status`; a cold cache can reappear and look like T2 failed. Use `make run ENGINE=56|57` / `make debug` to get the right slot.
