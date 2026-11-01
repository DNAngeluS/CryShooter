# Changelog

## 0.1.0 (unreleased, scaffold; console spike verified 2026-10-26)

- The project is named plasmid-debug (repo `Tools/plasmid-debug/`, vendored as `tools/plasmid-debug/`). It was called cry-debug
  before the first tag, so no release of the old name exists.
- Scaffold: directory layout, CMake fragment `cmake/PlasmidDebug.cmake`, console extension skeleton
  (`plasmid_debug_help`, `plasmid_debug_console`, `plasmid_debug_keylog`, argument autocomplete) used by the E-04/T-02 spike in FirstPersonShooter.
- Names renamed before the first tag (old -> new; no compatibility aliases, since 0.1.0 is unreleased):
  - namespace `crydebug` -> `Plasmid::Debug`; public header `<crydebug/CryDebug.h>` -> `<plasmid/debug/Debug.h>`
  - `include/crydebug/CryDebug.h` -> `include/plasmid/debug/Debug.h`; `src/CryDebug.cpp` -> `src/Debug.cpp`; `cmake/crydebug.cmake` -> `cmake/PlasmidDebug.cmake`
  - CMake variables `CRYDEBUG_DIR`, `CRYDEBUG_SOURCES`, `CRYDEBUG_INCLUDE_DIR` -> `PLASMID_DEBUG_DIR`, `PLASMID_DEBUG_SOURCES`, `PLASMID_DEBUG_INCLUDE_DIR`
  - console commands `dbg_help`, `dbg_ping`, `dbg_console`, `dbg_keylog` -> `plasmid_debug_help`, `plasmid_debug_ping`, `plasmid_debug_console`, `plasmid_debug_keylog`
  - CVar `dbg_console_key` -> `plasmid_debug_console_key`
  - log tag `[crydebug]` -> `[plasmid:debug]`
  - internal `crydebug::console` namespace -> class `Plasmid::Debug::Console`
