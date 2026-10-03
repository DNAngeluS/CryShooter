# CLAUDE.md

Read `AGENTS.md` first — it holds the routing table and working rules for every agent. This file
adds only what is specific to Claude in this project.

## Skills
- `khem:project-agentize` (refresh mode) — after significant changes, to re-index `.agents/` and `.memory/`.
- `skill-creator` — the asset-pipeline verbs in `memory/asset_pipeline_interface.json` are candidates for project-local skills in `.agents/skills/`.

## Subagents
Large asset-pipeline or procgen work is worth fanning out per module (`tools/asset_pipeline/procgen/`
vs `bundle_builder.py`). Tell a subagent to read `.memory/cards/tools.md` first, not the source.

## Plan mode
Use it before changing the `cover.ctc` / `terrain.dat` writers or the engine patches described in
`.agents/workflows/build-run.md` — both are binary-format work where a wrong guess renders as black terrain.
