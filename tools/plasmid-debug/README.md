# plasmid-debug

A debug kit for CRYENGINE 5.6 game plugins on Linux. It **extends the engine's own console** (`IConsole`) with `plasmid_debug_*`
commands instead of replacing it, and adds the debug features a game needs while it runs: render views (wireframe,
normals, albedo...), screenshots, debug menu, pause, free camera, camera locks, sky/time and weather debugging.

Everything is a console command or CVar, so the dropdown console, the Remote Console, an MCP `console` tool and `+cvar`
launch args all reach it the same way.

Status: 0.1.0 scaffold. Release notes: `CHANGELOG.md`.

## Use from a game plugin

1. Vendor a tagged copy into the project (`tools/plasmid-debug`; never edit the copy).
2. In the plugin's `CMakeLists.txt`: `include(${PLASMID_DEBUG_DIR}/cmake/PlasmidDebug.cmake)` and add the `PLASMID_DEBUG_SOURCES` list to
   the module sources (see the file for the exact call).
3. In the plugin: `#include <plasmid/debug/Debug.h>`; call `Plasmid::Debug::Init()` once the system is up
   (`ESYSTEM_EVENT_GAME_POST_INIT`) and `Plasmid::Debug::Shutdown()` on `ESYSTEM_EVENT_FULL_SHUTDOWN`.

## Layout

| Path | What |
|---|---|
| `include/plasmid/debug/` | public headers (the only API a game uses) |
| `src/` | implementation, one file per feature |
| `cmake/PlasmidDebug.cmake` | source list + include dirs for the host plugin build |
| `docs/` | findings and design notes |
| `tests/` | Python-side tests (Remote Console client, when it exists) |

Rules: no reference to a host project; no engine edits; every release bumps `VERSION`, adds a `CHANGELOG.md` entry and a git
tag `vX.Y.Z`.
