<!-- when: you need to know what is happening in this project right now -->
# Status — updated 2026-10-03

**Phase:** active development, pre-release `[assumed]`
**Live:** nothing deployed; local `GameLauncher` smoke runs only `[assumed]`

## In flight
| What | Component | Owner | State | Workstream |
|---|---|---|---|---|
| Smoke-test published `fps_forest_basin` via GameLauncher with `CRY_ASSET_PIPELINE_ENABLE_SMOKE=1` | tools | `[assumed]` Lucio | not started per tracker | E-02/T-01 |
| Verify deferred ESC shutdown removes teardown errors | Code | `[assumed]` Lucio | pending verification | E-02/T-04 |
| First-person character fails to load (`firstperson.cdf` missing/malformed) | Code + assets | `[assumed]` Lucio | open since 2026-04-03 | E-01/T-01 |

## Blocked
Nothing known.

## Open investigation (start here in a fresh session)
**E-03** — debug screenshots (`K` then `P`) fail when the game is started with `make run`: `mkdir('/user') failed`,
`Frame capture failed!`. Worked in the VS Code era (April). Cause not yet known; do not edit `Player.cpp` before
comparing launch environments. Full plan: `.agents/workstreams/epics/E-03.md`. The broader task is auditing what VS Code
gave for free versus `tools/dev.py` (E-03/T-03).

## Next up
1. Investigate E-03 (screenshots + VS Code→make gaps).
2. Fix the first-person CDF load error (E-01) — no arms/weapon mesh renders today.
3. Richer environment fidelity: more paint zones, foliage, textures (E-02).
4. Decide on stub DDS vs Wine+RC for missing engine weather textures (E-01/T-03).

## Recently shipped
- 2026-10-03 — dev command runner: `Makefile` + `tools/dev.py` (build, services, run/debug, logs, status); `CHANGELOG.md` introduced
- 2026-10-03 — default startup level changed to `fps_forest_basin` (3afb06b)
- DXT1→BC5 conversion of five engine `_ddn` normal maps (5bcf131)
- New test level creation (417f985); licence + notice added (9f1fcc7)
- Debug screenshot mode (K toggle, P capture) with TRANSFER_SRC swapchain fix (3ba31dc…abb4cf4)
- Procedural level generation (terrain/interior/structured) with native `terrain.dat` (6421730)

Evidence: `git log`, `memory/asset_pipeline_tracker.json` (last updated 2026-04-03; roadmap
milestone `M2-bundle-graph-compiler`, which is older than the procgen M3 work — treat as stale).
