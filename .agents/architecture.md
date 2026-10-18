<!-- when: you need to know how the plugin, engine, asset pipeline and generated levels fit together -->
# Architecture

## Shape

Two halves that meet only through files on disk:

```
 tools/ (Python)                                   Code/ (C++ plugin)
 asset_graph.json ──validate/compile──▶ staged ──publish──▶ Assets/levels/<slug>/ ──▶ CRYENGINE
 (authored by an LLM)                   user/asset_pipeline/jobs/<job>/                    │
                                                                                          ▼
                                                  libGamePlugin.so ◀── loaded by GameLauncher
                                                  (auto-loads fps_forest_basin on GAME_POST_INIT)
```

The engine (`$CRYENGINE_DIR`) is external and not in this repo. The plugin is copied into the
engine's `bin/linux_x64_gcc/` by a POST_BUILD step because `CryLoadLibrary` resolves plugin names
relative to `MODULE_PATH` (the launcher's own directory).

## Boundaries

- `Code/` owns runtime behaviour only: player, spawn, projectile, startup level, level-load CVars.
  It must not generate assets.
- `tools/` owns asset generation. It must not assume the engine is present: validation and
  compilation run without it; smoke tests run only if `CRYENGINE_DIR` resolves and
  `CRY_ASSET_PIPELINE_ENABLE_SMOKE=1`.
- The LLM is the authoring layer (writes `asset_graph.json`); Python is a deterministic compiler.
  Do not add prose interpretation to Python.

## Data flow

1. **Level build.** `create-job` → `plan-spec` → LLM writes graph → `author-spec` → `build`
   (nodes compiled in dependency order by `bundle_builder.py`) → `validate` → `publish` into `Assets/levels/<slug>/`.
2. **Procgen terrain.** `terrain_procgen` node → `procgen/terrain_gen.py` heightmap →
   `terrain_dat_writer.py` writes `terrain.dat` natively (no Sandbox) → injected into `level.pak`.
   `terrain_archetype` nodes copy golden binaries from `templates/levels/` instead.
3. **Runtime.** `GameLauncher -project Game.cryproject` → plugin `Initialize` registers `goto` →
   `GAME_POST_INIT` loads the startup level (outside the editor) → `LEVEL_LOAD_END` applies water/LOD CVars →
   `CPlayerComponent` spawns at the first `CSpawnPointComponent` (fallback: terrain centre + 10 m).

## External dependencies

- CRYENGINE 5.6 source build (path via `CRYENGINE_DIR`); a few engine patches were applied for GCC 14 (see build-run workflow).
- Wine + DXC for the optional remote shader compiler (`tools/cry_shader_server.py`, a shim; real file in `tools/cryengine-dev/`).
- `noise==1.2.2` Python package (procgen only).

## Known weak points

- Generated `terrain.dat` for template-derived paths can mismatch physics vs visuals until a Sandbox re-export (`CRYENGINE_TODO` in code).
- Interior levels use a flat terrain underlay; `vegetationmap.dat` is copied from a template (`PROCGEN_TODO`).
- `imagegen` texture mode only emits request artifacts plus fallback PNGs; no model is called.
- C++ has no automated tests.
- Decisions are not recorded as ADRs (`docs/adr/` does not exist).
