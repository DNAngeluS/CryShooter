# CRYENGINE 5.6 — LLM Asset Pipeline

## Overview

This project includes a Python asset pipeline designed for natural-language driven CRYENGINE asset creation.

Current focus:
- **Level / terrain generation** from prompt to staged CRYENGINE package.
- **Mesh import conversion** for local assets such as `.obj`, `.fbx`, `.dae`, `.dxf`, `.3ds`.
- **Conversation memory / tracking** so future LLM sessions can resume work deterministically.

The pipeline is **staged-first**:
1. Create a job in `user/asset_pipeline/jobs/<job_id>/`
2. Generate a structured spec and prompt pack
3. Build staged outputs
4. Validate staged outputs
5. Publish validated assets into `Assets/`

`user/` is gitignored, so intermediate files stay out of version control.

---

## CLI Tools

### Asset Pipeline

```bash
python3 tools/cry_asset_pipeline.py run \
  --kind level \
  --prompt "small desert combat arena at noon" \
  --target-package desert_arena
```

Core subcommands:
- `create-job`
- `plan-spec`
- `edit`
- `build`
- `validate`
- `publish`
- `run`
- `convert-mesh`

### Tracker

```bash
python3 tools/cry_asset_tracker.py status
python3 tools/cry_asset_tracker.py next
python3 tools/cry_asset_tracker.py resume
```

The tracker reads and writes `memory/asset_pipeline_tracker.json`.

---

## Generated Job Layout

```
user/asset_pipeline/jobs/<job_id>/
├── request.json
├── prompt_pack.md
├── asset_spec.json
├── build_manifest.json
├── validation_report.json
├── publish_manifest.json
├── mesh_import_recipe.json        # mesh jobs only
├── mesh_import_summary.md         # mesh jobs only
├── source_mesh/                   # mesh source + sidecars
└── staged_assets/
    └── Assets/
        └── ...
```

---

## Level Generation Rules

The level generator is based on the local project knowledge in:
- `docs/terrain.md`
- `docs/textures.md`
- `docs/lighting.md`
- `docs/lod.md`

It enforces these defaults:
- `%ENGINE%/EngineAssets/Shading/default.env` for lighting
- `OceanWaterLevel="-100"` to avoid ocean/terrain z-fighting
- Valid `terrain/cover.ctc` output so terrain does not render black
- Level files published under `Assets/levels/<slug>/`
- A deterministic spawn fallback at the level center

Generated level packages include:
- `<slug>.level`
- `.level.cryasset`
- `filelist.xml`
- `level.pak`
- `terraintexture.pak`
- `leveldata/environment.xml`
- `leveldata/timeofday.xml`
- `leveldata/terraintexture.xml`
- `layers/main.lyr`
- `layers/terrain.lyr`

---

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
- `.obj` is treated as **static geometry** only.
- Skeletal character / animated vehicle import should use `.fbx` or `.dae`.
- If the compiler is not found, the package is still staged and ready for a later compile pass.

---

## LLM Integration

The pipeline is designed for LLMs, but keeps generation deterministic inside the repo:
- `--llm-mode auto` synthesizes a structured spec locally from the prompt.
- `--llm-mode prompts-only` emits the exact prompt contract for use with ChatGPT, Claude, or another external model.

This separation lets future sessions switch to a direct provider adapter without changing the build, validation, or publish steps.

---

## Persistent Memory

Two machine-readable files anchor cross-conversation continuity:
- `memory/asset_pipeline_plan.json`
- `memory/asset_pipeline_tracker.json`
- `memory/asset_pipeline_interface.json`

The plan file records the roadmap and default decisions.
The tracker file records actual jobs, status, stage directories, and next actions.
The interface file defines the LLM-facing verbs, aliases, command templates, and higher-level skills used to trigger the pipeline.
