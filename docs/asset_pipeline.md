# CRYENGINE 5.6 — Bundle Graph Asset Pipeline

## Overview

This project includes a Python asset pipeline designed for **LLM-authored, bundle-graph-driven** CRYENGINE asset creation.

Current focus:
- **Environment bundles** that compile terrain, textures, materials, procedural meshes, imported meshes, and placements into staged levels.
- **Character bundles** that package imported character sources into the first-person runtime contract used by the FPS player.
- **Direct mesh import staging** for local assets such as `.obj`, `.fbx`, `.dae`, `.dxf`, `.3ds`, and `.cgf`.
- **Conversation memory / tracking** so future LLM sessions can resume work deterministically.

The pipeline is **staged-first**:
1. Create a job in `user/asset_pipeline/jobs/<job_id>/`
2. Emit authoring artifacts (`prompt_pack.md`, `capability_catalog.json`, `asset_graph.stub.json`, `template_catalog.json`)
3. Submit a validated `asset_graph.json`
4. Build staged outputs in dependency order
5. Validate staged outputs
6. Publish validated assets into `Assets/`

`user/` is gitignored, so intermediate files stay out of version control.

## CLI Tools

### Asset Pipeline

```bash
python3 tools/cry_asset_pipeline.py create-job \
  --kind level \
  --prompt "High-fidelity forest basin arena" \
  --target-package fps_forest_basin

python3 tools/cry_asset_pipeline.py plan-spec --job level-fps-forest-basin
python3 tools/cry_asset_pipeline.py author-spec --job level-fps-forest-basin --json-file ./asset_graph.json
python3 tools/cry_asset_pipeline.py build --job level-fps-forest-basin
python3 tools/cry_asset_pipeline.py validate --job level-fps-forest-basin
python3 tools/cry_asset_pipeline.py publish --job level-fps-forest-basin
```

Character packaging follows the same flow:

```bash
python3 tools/cry_asset_pipeline.py create-job \
  --kind character_package \
  --prompt "First-person rifleman character" \
  --target-package fps_rifleman \
  --source-input /path/to/fps_rifleman.fbx
```

Direct import staging remains available:

```bash
python3 tools/cry_asset_pipeline.py convert-mesh \
  --input /path/to/model.obj \
  --target Objects/Imported/model
```

Core subcommands:
- `create-job`
- `plan-spec`
- `author-spec`
- `edit`
- `build`
- `validate`
- `publish`
- `run`
- `convert-mesh`

`run` is a convenience wrapper, but for `level` and `character_package` it still requires an explicit `--asset-graph`.

### Tracker

```bash
python3 tools/cry_asset_tracker.py status
python3 tools/cry_asset_tracker.py next
python3 tools/cry_asset_tracker.py resume
```

The tracker reads and writes `memory/asset_pipeline_tracker.json`.

## Generated Job Layout

```
user/asset_pipeline/jobs/<job_id>/
├── request.json
├── prompt_pack.md
├── capability_catalog.json
├── asset_graph.stub.json
├── template_catalog.json
├── asset_graph.json
├── build_manifest.json
├── node_build_reports.json
├── validation_report.json
├── smoke_report.json
├── publish_manifest.json
├── imagegen_requests/             # imagegen texture nodes only
├── mesh_import_recipe.json        # mesh jobs and mesh_import nodes
├── mesh_import_summary.md         # mesh jobs only
├── source_mesh/                   # staged imported mesh + sidecars
└── staged_assets/
    └── Assets/
        └── ...
```

## Bundle Graph Rules

Python does **not** infer terrain, lighting, geometry, materials, or character runtime structure from the prose brief.
The LLM authors a strict `asset_graph.json`, and Python only validates and compiles it.

Top-level graph fields:
- `asset_kind`
- `bundle_kind`
- `bundle_slug`
- `summary`
- `root_scene`
- `nodes`

Supported node types:
- `scene_level`
- `terrain_archetype`
- `texture_source`
- `material_surface`
- `mesh_procedural`
- `mesh_import`
- `object_placement_set`
- `character_fp_package`

Each node must contain:
- `id`
- `type`
- `inputs`
- `outputs`
- `spec`

## Environment Bundle Rules

Environment bundles are rooted by a `scene_level` node and currently support:
- terrain archetypes backed by checked-in golden templates
- texture generation/import nodes
- material surface nodes
- procedural static mesh nodes
- imported static mesh nodes
- placement sets compiled into level layers

Terrain constraints:
- Supported profiles: `flat_arena`, `basin`, `ridge_ring`, `valley`
- Supported heightmap sizes: `512`, `1024`, `2048`
- `paint_materials` inputs must be non-empty
- `paint_zones` must be non-empty
- If a terrain request cannot be represented by the supported archetype + paint model, validation must fail instead of silently degrading

Geometry constraints:
- Procedural geometry is limited to the checked-in archetypes from the mesh catalog
- Arbitrary freeform vertex or triangle payloads are rejected
- Imported static meshes may be referenced through `mesh_import` nodes

Texture constraints:
- Supported modes: `import`, `imagegen`, `solid_color`, `procedural_pattern`
- Generated master format is PNG
- `imagegen` is integrated as a graph mode, but the current compiler writes request artifacts plus deterministic fallback PNGs instead of calling an external image model directly

Compilation rules:
- `%ENGINE%/EngineAssets/Shading/default.env` for default lighting
- `OceanWaterLevel="-100"` by default to avoid ocean/terrain z-fighting
- Golden terrain binaries are copied from checked-in verified templates
- Terrain texture packs are rebuilt with `terrain/cover.ctc`
- Level files publish under `Assets/levels/<bundle_slug>/`
- Publish remains a separate explicit command after validation

Generated level packages include:
- `<slug>.level`
- `.level.cryasset`
- `filelist.xml`
- `level.pak`
- `terraintexture.pak`
- `leveldata/environment.xml`
- `leveldata/timeofday.xml`
- `leveldata/terraintexture.xml`
- `leveldata/terrain_manifest.json`
- `layers/main.lyr`
- `layers/terrain.lyr`

## Character Bundle Rules

Character bundles are rooted by a `character_fp_package` node and currently support:
- imported character source meshes via `mesh_import`
- first-person runtime packaging only
- generated `.cdf`, controller definition XML, and `.adb`

Character constraints:
- Character source imports require `.fbx` or `.dae`
- The current milestone packages against the FPS first-person runtime only
- Novel rig synthesis is out of scope; packaging assumes a compatible imported character source

Generated character outputs include:
- `Assets/Objects/Characters/<name>/firstperson.cdf`
- `Assets/Animations/Mannequin/ADB/<name>FirstPerson.adb`
- `Assets/Animations/Mannequin/ADB/<name>FirstPersonControllerDefinition.xml`

## Validation

Validation runs after build and checks:
- bundle-graph structural validity
- per-node output presence
- PNG output enforcement for texture nodes
- material-to-texture references
- mesh output presence
- character package outputs plus `barrel_out` attachment in the CDF
- `leveldata/heightmap.dat` header structure and dimensions
- `terrain/terrain.dat` presence and non-zero content
- `terraintexture.pak` contents including `terrain/cover.ctc`
- cross-file consistency between the graph and packed XML files
- placement references in `layers/main.lyr`
- optional smoke-report generation when engine tooling is configured

Smoke tests only run when:
- `CRYENGINE_DIR` resolves successfully
- `GameLauncher` exists
- `CRY_ASSET_PIPELINE_ENABLE_SMOKE=1`

Otherwise validation still completes with `smoke_report.json` marked as skipped.

## Mesh Import Rules

Use:

```bash
python3 tools/cry_asset_pipeline.py convert-mesh \
  --input /path/to/model.obj \
  --target Objects/Imported/model
```

Current behavior:
- Stages the source mesh and sidecar files (`.mtl`, referenced textures for OBJ).
- Emits a machine-readable import recipe.
- Resolves CRYENGINE compiler/import tooling from `CRYENGINE_DIR` when available.
- Copies the source asset beside the intended compiled output path because CRYENGINE expects the compiled mesh to live next to the source asset.

Constraints:
- `.obj` is treated as static geometry only
- skeletal character import should use `.fbx` or `.dae`
- if the compiler is not found, the package is still staged and ready for a later compile pass

## LLM Integration Boundary

The LLM is the **authoring layer**:
- it reads the user brief
- it infers which bundle graph nodes are required
- it emits the strict `asset_graph.json`

Python is the **deterministic compiler**:
- schema validation
- dependency ordering
- template resolution
- texture emission
- safe XML/text substitution
- packing/compression
- structural validation
- optional smoke-report generation

## Persistent Memory

Three machine-readable files anchor cross-conversation continuity:
- `memory/asset_pipeline_plan.json`
- `memory/asset_pipeline_tracker.json`
- `memory/asset_pipeline_interface.json`

The plan file records the roadmap and default decisions.
The tracker file records actual jobs, status, stage directories, and next actions.
The interface file defines the LLM-facing verbs, aliases, command templates, graph contract, and higher-level skills used to trigger the pipeline.
