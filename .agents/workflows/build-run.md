<!-- when: configuring, building, running or debugging the C++ plugin (libGamePlugin.so) -->
# Build, run, debug the plugin

**Use `make` first** (`make help`; implemented in `tools/dev.py`): `make setup`, `make build`, `make run`,
`make debug-batch`, `make status`, `make logs`, `make stop`. It wraps the presets in `Code/CMakePresets.json`
(build dirs `build/gcc`, `build/gcc14`, `build/clang`), reads `.env` itself, starts the shader server, and logs
to `.dev/logs/`. The manual commands below are the reference for what it runs and for the gotchas.

Run everything from the project root. Needs `CRYENGINE_DIR` (`source .env`).

## Configure (once per compiler)

```bash
# GCC 9 (default)
cmake -B build/gcc -G Ninja -S Code -DCMAKE_BUILD_TYPE=Debug -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$CRYENGINE_DIR/Tools/CMake/toolchain/linux/Linux_GCC.cmake \
  -DCMAKE_C_COMPILER=gcc-9 -DCMAKE_CXX_COMPILER=g++-9
# GCC 14: same with build/gcc14, gcc-14, g++-14
# Clang: project-local toolchain
cmake -B build/clang -G Ninja -S Code -DCMAKE_BUILD_TYPE=Debug -DCRYENGINE_DIR=$CRYENGINE_DIR \
  -DCMAKE_TOOLCHAIN_FILE=$(pwd)/cmake/toolchain/Linux_Clang_System.cmake
# add -DCLANG_OUTPUT_DIR_NAME=linux_x64_clang only for a full Clang engine build
```

Build types: `Debug` (`-O0 -g`), `Profile` (`-O2`), `Release` (`-O3`).

## Build

`cmake --build build/<gcc|gcc14|clang> --parallel $(nproc)`.
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

`python3 tools/cry_shader_server.py` (Wine + DXC), then in `system.cfg`:
`r_ShadersRemoteCompiler=1`, `r_ShaderCompilerServer=127.0.0.1`, `r_VkShaderCompiler=DXC`.
