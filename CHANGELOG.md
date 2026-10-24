# Changelog

All notable changes to this project are documented here, newest first.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no tagged releases yet, so
entries are grouped by **milestone** (dated) instead of version numbers.

**How to use this file (humans and agents):**
- Add an entry under `[Unreleased]` whenever you finish a milestone or change behaviour others rely on.
- Anything that could break a working setup goes under **Breaking / may break**, with what to do about it.
  If nothing can break, omit that heading.
- Milestone = a feature or fix a person would mention ("procgen levels", "debug screenshots"), not every commit.
- Sections: `Added` · `Changed` · `Fixed` · `Removed` · `Breaking / may break`.

## [Unreleased]

### Fixed (2026-10-24)
- `terrain.dat` writer: appends the empty object-tree chunk and pads with 0xDE like Sandbox, so 512 m levels load (OF-09). New `procgen/terrain_dat_parser.py`, validator check and `fix-terrain` verb; `fps_forest_basin/level.pak` patched. **May break:** none for 1024 m levels (same frame); levels built before this change must be passed through `fix-terrain` if they are 512 m.
- Generated textures also get a runtime `.dds` (vendored `tools/cry-assets` 0.2.0); layer materials reference it (the engine cannot load PNG material textures). `fps_forest_basin` and `fps_tech_ruins_interior` regenerated.
- Terrain paint materials use `Terrain.Layer` (stock form) instead of `Illum`; `fps_forest_basin` regenerated (detail layers now visible).

### Added (2026-10-24)
- Launch CVar `fps_startup_level <name>` (`GameLauncher ... +fps_startup_level plain`): level under `Assets/levels` to load at startup. Empty or a missing level falls back to `fps_forest_basin` (logged). Replaces the compile-time `kStartupLevel` (the 2026-10 entries below refer to it).
- Vendored `Tools/dev` 1.1.2: `make health` also fails when the shader-cache `globals.txt` is an empty stub (it made half of the far terrain render black). The project's shader cache slots were repaired.

### Added
- **Dev command runner.** `Makefile` + `tools/dev.py` (stdlib only): `make setup | build | release | up | down | run | debug | stop | status | logs | test | pipeline`.
  Background services and the game log to `.dev/logs/`, pids in `.dev/pids/` (both gitignored). See README → *Dev commands*.
- **Per-engine shader cache** (2026-10-18, implemented and accepted: 56→57→56, third run 0 crc mismatch / 0 cache miss). `user/shaders/cache` links to `user/shaders/cache-by-engine/<56|57>`, switched by `make run` / `make debug`. `make shaders-status` shows the state.
- **`make shaders-status`** (2026-10-18) reports the shader cache and compile progress for the selected engine.

### Changed
- `AGENTS.md`, `CLAUDE.md` and the build/run workflow now point at `make` targets instead of long cmake commands.
- **Tooling is versioned and vendored** (2026-10-18): `tools/cryengine-dev/` is a numbered copy (v1.0.0, commit 599bb8c of the cryengine-dev repo) pinned by `tools_version` in `cryengine-dev.config.json`; `.vendored-from` records version, commit and file hashes. Roll forward with `python3 <Crytek>/Tools/dev/vendor.py --project-dir .`.
- **Dev runner moved** (2026-10-18) to the generic `tools/cryengine-dev/dev.py`. `tools/dev.py` and `tools/cry_shader_server.py` are now 20-line forwarding shims, so existing commands still work.
- **FPS settings** (2026-10-18) live in `cryengine-dev.config.json` at the project root (schema: `tools/cryengine-dev/config-schema.md`). The `Makefile` is now a thin include of `tools/cryengine-dev/Makefile.common` plus the FPS-only `test` and `pipeline` targets.

### Breaking / may break
- `ENGINE=56|57` selects the engine checkout for every `make` target (5.7.1 defaults to gcc13, preset `e57-gcc13`, build dir `build/e57-gcc13`; plugin deploys only into that engine). Add `CRYENGINE_DIR_57` to `.env`. `COMPILER` now defaults per engine, and `gcc13` was added.
- `make build` uses the presets in `Code/CMakePresets.json`, which build into `build/gcc`, `build/gcc13`, `build/gcc14`, `build/clang`.
  The old README commands that configured `build/` are obsolete; delete a stale `build/` directory if you still have one.
- **Known regression:** debug screenshots (`K` then `P`) are not saved when the game is launched with `make run` (`mkdir('/user') failed`); they worked from VS Code. Under investigation — workstream E-03, `docs/known-issues.md`.
- `make build` redeploys `libGamePlugin.so` into `$CRYENGINE_DIR/bin/linux_x64_gcc/` (same as before), replacing whatever plugin was there.
- **Cold shader cache per engine** (2026-10-18): the first `make run` / `make debug` on each engine starts with an empty cache. The window stays black for minutes while shaders compile through the Wine+DXC server; watch `make shaders-status`. The old shared cache is kept as `legacy-unlabelled`.

## Milestone: agent context layer — 2026-10-03

### Added
- `AGENTS.md` router, thin `CLAUDE.md`, `.agents/` (architecture, conventions, status, workflows, workstreams), `.memory/` (cards, inventories, seams graph, glossary, env vars).
- `docs/README.md` index with a symptom table, `docs/architecture.md`, `docs/known-issues.md`; "Read this when" headers on every engine guide.

### Changed
- `docs/log_issues.md` replaced by `docs/known-issues.md`; the original is kept in `.agents/archive/`.
- Default startup level changed from `fps_tech_ruins_interior` to `fps_forest_basin` (`kStartupLevel` in `Code/GamePlugin.cpp`).
- `CLAUDE.md` shrank from 281 to ~17 lines; its content moved into `.agents/` (original in `.agents/archive/CLAUDE.md.pre-agentize`).

### Breaking / may break
- Anything that read `docs/log_issues.md` or relied on the old long `CLAUDE.md` must use the new locations.
- `GameLauncher` now opens `fps_forest_basin` by default; edit `kStartupLevel` and rebuild to change it.

---
<!-- Everything below was reconstructed from git history on 2026-10-03 and may be incomplete. -->

## Milestone: engine texture fixes and new test level — 2026-04-04

### Added
- A new test level (`417f985`), licence and NOTICE files (`9f1fcc7`).
- List of issues found while debugging the engine log (`3fe4329`, later superseded by `docs/known-issues.md`).

### Fixed
- Five engine `_ddn` normal maps recompressed from DXT1 to BC5/ATI2 (`5bcf131`).
- Black debug screenshots: swapchain images now created with `TRANSFER_SRC` (`3ba31dc`).

### Breaking / may break
- The BC5 conversion edits files **inside the engine install** (`$CRYENGINE_DIR/Engine/EngineAssets/Textures/`); a fresh engine checkout needs `tools/asset_pipeline/dds_normalmap_fix.py` run again.
- The screenshot fixes also rely on patches in the engine source tree (see `docs/known-issues.md`, "ScreenShot() failed") that require an engine rebuild.

## Milestone: debug mode and screenshots — 2026-04-02 → 2026-04-03

### Added
- `K` toggles debug mode; `P` saves a timestamped JPEG to `Screenshots/` with an on-screen confirmation (`abb4cf4`, `7d8a11b`). Replaces the earlier `Ctrl+P` binding.

### Fixed
- Black terrain sectors in `fps_forest_basin` (`2cc67b2`): `e_TerrainAutoGenerateBaseTexture` removed and the `cover.ctc` normal layer corrected to `[128,128,0,0]`.

## Milestone: procedural level generation (M3) — 2026-04-02

### Added
- `terrain_procgen`, `interior_procgen`, `structured_procgen` graph node types; native `terrain.dat` writer (no Sandbox needed); spawn point injected into generated levels (`6421730`).
- Python `noise` dependency (`tools/requirements.txt`, venv at `tools/.venv`).

### Breaking / may break
- Procgen tests require the venv (`tools/.venv/bin/python3`); system Python lacks `noise`.

## Milestone: bundle-graph asset pipeline (M2) — 2026-03-29 → 2026-04-02

### Added
- LLM-authored `asset_graph.json` → staged package → validate → publish pipeline for levels, first-person characters and mesh imports (`47ec402`, `4373222`); asset tracker with state in `memory/`.

## Milestone: multi-compiler build — 2026-03-28

### Added
- GCC 9 (default), GCC 14 and Clang support via `Code/CMakePresets.json` and `cmake/toolchain/Linux_*_System.cmake` (`7c0dde3`).
- Engine path configurable through `CRYENGINE_DIR` (`.env` for CLI, `.vscode/settings.json` for VS Code); development tools including the remote shader compiler server (`9c99604`).

### Breaking / may break
- GCC 14 needs two engine-header patches (`IEntityComponent.h`, `CryArray.h`) re-applied per engine checkout.

## Milestone: initial project — 2026-03-27 → 2026-03-28

### Added
- CRYENGINE 5.6 FPS plugin: first-person player, spawn points, bullets, startup level loading (`ee66a5b`, `d33cc03`), plus the first engine-knowledge docs.
