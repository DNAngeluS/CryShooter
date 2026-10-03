<!-- when: generating, changing or publishing a level, character package or imported mesh with tools/cry_asset_pipeline.py -->
# Asset pipeline

Staging root: `user/asset_pipeline/jobs/<job_id>/` (gitignored). Human-facing walkthrough: `docs/asset_pipeline.md`.

## Level / character flow

```bash
python3 tools/cry_asset_pipeline.py create-job --kind level --prompt "<brief>" --target-package <slug>
python3 tools/cry_asset_pipeline.py plan-spec   --job level-<slug>      # emits prompt_pack.md, capability + template catalogs, graph stub
# LLM authors asset_graph.json from those artifacts
python3 tools/cry_asset_pipeline.py author-spec --job level-<slug> --json-file ./asset_graph.json
python3 tools/cry_asset_pipeline.py build       --job level-<slug>
python3 tools/cry_asset_pipeline.py validate    --job level-<slug>
python3 tools/cry_asset_pipeline.py publish     --job level-<slug>      # writes Assets/levels/<slug>/
```

Character: `--kind character_package --source-input /path/model.fbx` (`.fbx`/`.dae` only), same flow.
Mesh only: `convert-mesh --input model.obj --target Objects/Imported/model` (`.obj` = static only).
`run` wraps the flow but still needs `--asset-graph` for level/character jobs.

## Graph contract

Top-level: `asset_kind, bundle_kind, bundle_slug, summary, root_scene, nodes`. Each node: `id, type, inputs, outputs, spec`.
Node types: `scene_level`, `terrain_archetype` (golden template), `terrain_procgen` (forest/desert/tundra/swamp/savanna/volcanic),
`interior_procgen` (cave/dungeon/ship/bunker/sewer), `structured_procgen` (castle/arena/fortress/warehouse/ruins),
`texture_source`, `material_surface`, `mesh_procedural`, `mesh_import`, `object_placement_set`, `character_fp_package`.

Constraints that fail validation on purpose:
- terrain archetype profiles `flat_arena|basin|ridge_ring|valley`; heightmap sizes `512|1024|2048`; `paint_materials` and `paint_zones` non-empty
- procedural meshes only from the checked-in catalog (no freeform vertices)
- texture modes `import|imagegen|solid_color|procedural_pattern`; masters are PNG. `imagegen` only writes request artifacts + fallback PNGs
- if the brief cannot be expressed in the supported model, **fail, don't degrade**

## Compile defaults (do not change casually)

`%ENGINE%/EngineAssets/Shading/default.env` for lighting · `OceanWaterLevel="-100"` · golden terrain binaries copied from
verified templates · terrain texture pack rebuilt with `terrain/cover.ctc` (hmap layer `[128,128,0,0]`) ·
procgen terrain writes `terrain.dat` natively · `main.lyr` gets a `CSpawnPointComponent` at `scene_spec["spawn"]["transform"]["position"]`.

## Validation and smoke

Validation checks graph structure, node outputs, PNG-only textures, material→texture refs, `heightmap.dat` header,
`terrain.dat` non-empty, `terraintexture.pak` contents, graph↔XML consistency, `main.lyr` placement refs.
Smoke (`smoke_report.json`) runs only if `CRYENGINE_DIR` resolves, `GameLauncher` exists and `CRY_ASSET_PIPELINE_ENABLE_SMOKE=1`; otherwise it is marked skipped.

## Tracker

`python3 tools/cry_asset_tracker.py status|next|resume` reads/writes `memory/asset_pipeline_tracker.json`.
Procgen runtime facts: heightmap.dat 3-byte prefix `{512: ff 5a 03, 1024: ff 5d 03}`; `_compile_scene_level` reads exact keys
`world, template_level_dir, heightmap_path, vegetationmap_path, terraintexture_pak_path, manifest_path, paint_material_assets`
from the terrain report; scene_level validation only checks presence of `inputs.terrain`, not its type.
