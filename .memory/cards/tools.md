<!-- when: working anywhere inside tools/ or tests/ (Python asset pipeline, procgen, tracker, shader server) -->
# tools — asset pipeline and helpers

**Path:** `tools` (+ `tests/`, `memory/*.json`) · **Stack:** Python 3, `noise==1.2.2`, pytest · **Size:** 33 files / ~5.4k LOC
**Entrypoints:** `cry_asset_pipeline.py`, `cry_asset_tracker.py`, `cry_shader_server.py`
**Runs with:** `python3 tools/cry_asset_pipeline.py <cmd>` · **Tests:** `tools/.venv/bin/python3 -m pytest tests/ -v`

## Purpose
A staged, bundle-graph-driven compiler for CRYENGINE levels and first-person character packages. The LLM authors
`asset_graph.json`; Python validates it against checked-in catalogs/templates, compiles nodes in dependency order,
validates the staged output and publishes into `Assets/`. Also holds a tracker for cross-session state and a
Linux remote shader compiler server. It is not an interpreter of prose and not a general DCC converter.

## Structure
| Path | Holds |
|---|---|
| `cry_asset_pipeline.py` | CLI: create-job, plan-spec, author-spec, edit, build, validate, publish, run, convert-mesh |
| `asset_pipeline/pipeline.py` | job orchestration |
| `asset_pipeline/asset_graph.py` | graph schema + node validators (incl. procgen types) |
| `asset_pipeline/bundle_builder.py` | per-node compilers and level XML/layer writers (largest module) |
| `asset_pipeline/validator.py` | post-build checks, smoke report |
| `asset_pipeline/catalogs.py`, `templates/` | capability/template catalogs; golden level terrain, materials, meshes, procgen catalog |
| `asset_pipeline/procgen/` | terrain/interior/structured generators, `terrain_dat_writer.py`, heightmap/mesh writers |
| `asset_pipeline/texture_builder.py` | PNG masters, `cover.ctc` + `terraintexture.pak` |
| `asset_pipeline/character_builder.py`, `mesh_converter.py` | first-person package (`.cdf`, `.adb`, controller XML); mesh staging |
| `asset_pipeline/dds_normalmap_fix.py` | DXT1→BC5 normal-map recompression |
| `asset_pipeline/tracker_store.py`, `cry_asset_tracker.py` | state in `memory/asset_pipeline_tracker.json` |
| `cry_shader_server.py` | CrySCompileServer protocol over Wine + DXC |

## Depends on
- internal: `Code` consumes its outputs (character contract used by `Player.cpp`; spawn point entity in `main.lyr`)
- external: CRYENGINE install (optional: smoke tests, RC tooling), Wine+DXC (shader server), `noise`

## Key flows
Level: create-job → plan-spec → LLM authors graph → author-spec → build → validate → publish. Procgen terrain: heightmap →
`terrain_dat_writer` → `level.pak`. Details: `.agents/workflows/asset-pipeline.md`.

## Gotchas
- `cover.ctc` layer-1 pixel must be `[128,128,0,0]` (not the diffuse average — that skews lighting).
- Never rely on `e_TerrainAutoGenerateBaseTexture` to paper over `cover.ctc` problems.
- heightmap.dat has a size-specific 3-byte prefix (`512: ff5a03`, `1024: ff5d03`).
- `_compile_scene_level` reads exact terrain-report keys; renaming one breaks level assembly silently.
- Procgen tests need the venv's `noise` package.

## Effort signals
- **Size / churn:** ~5.4k LOC, 0 commits in 90 days — dormant (last big work: procgen/M3)
- **Test safety net:** pytest, ~1.1k test LOC across 4 files; covers structure and writers, **not** in-engine rendering
- **Coupling:** binary formats shared with the engine; template catalogs; `Code/Player.cpp` character contract
- **Unknowns:** smoke-run status of generated levels; tracker (`memory/`) is stale vs shipped procgen

## Unknowns
Whether `imagegen` will ever call a real generator; fidelity roadmap beyond template-backed terrain (E-02).
