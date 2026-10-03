# FirstPersonShooter — Agent Instructions

**What this is.** A CRYENGINE 5.6 first-person shooter game plugin (C++, Linux) plus a Python
asset pipeline that generates levels and character packages from an LLM-authored bundle graph.
The plugin builds to `libGamePlugin.so`, which the engine loads at runtime. Phase: active
development, pre-release `[assumed]`.

**Stack:** C++17 / CMake+Ninja (GCC 9 default, GCC 14, Clang 22) · Python 3 asset pipeline ·
**Components:** 2 (`code`, `tools`) · **Repos:** 1 · **Indexed:** 2026-10-03 @ 3afb06b

## How to use this context

Answer from this file plus `.memory/index.json`. Open at most one route below, then at most one
shard it names. Needing a third hop means a route is missing — fix the route rather than reading
around it.

## Components

| Path | Kind | Stack | Responsible for | Card |
|---|---|---|---|---|
| `code` | game plugin | C++ / CRYENGINE 5.6 | player, spawn points, bullets, level auto-load, level-load CVars | `.memory/cards/code.md` |
| `tools` | tooling | Python 3 | bundle-graph asset pipeline, procgen, tracker, shader server | `.memory/cards/tools.md` |

`tests/` (pytest) covers `tools/` only. `memory/*.json` (top-level) is the pipeline's own
machine-readable state — see routes.

## Routes

| If you need to… | Read |
|---|---|
| see how the plugin, engine and pipeline fit together | `.agents/architecture.md` |
| know what is in flight or blocked | `.agents/status.md` |
| write code the way this project writes it | `.agents/conventions.md` |
| configure, build, run or debug the plugin | `.agents/workflows/build-run.md` |
| generate or change a level / character / mesh | `.agents/workflows/asset-pipeline.md` |
| run tests | `.agents/workflows/testing.md` |
| diagnose black screen, z-fighting, black terrain, missing textures | `.agents/workflows/debugging.md` |
| size or quote a piece of work | `.agents/workflows/estimating.md` |
| know what a change ripples into | query `.memory/graph.json` (`edges`, and `seams`) |
| find the file that does X | query `.memory/inventory/<component>.json` |
| know what an env var configures | query `.memory/env.json` |
| understand a project term (bundle graph, golden template, cover.ctc…) | query `.memory/glossary.json` |
| pick up or update planned work | `.agents/workstreams/index.json` |
| judge how risky one component is | *Effort signals* in its card |
| read pipeline job/tracker state or roadmap | `memory/asset_pipeline_tracker.json`, `memory/asset_pipeline_plan.json` (`tools/cry_asset_tracker.py status`) |
| CRYENGINE facts (terrain, LOD, lighting, textures, characters, DDS) | `docs/README.md` — human-owned, route to it, never copy it |

## Query, don't read

Files under `.memory/*.json` are indexes. Filter them instead of loading them:

```bash
jq '.files[] | select(.role=="route")' .memory/inventory/tools.json
jq '.vars[] | select(.secret==true) | .name' .memory/env.json
jq '.seams[] | select(.id=="terrain-pipeline")' .memory/graph.json
```

## Working rules

- Engine path: `CRYENGINE_DIR` (env or `.env`, gitignored). Never hardcode it.
- Build: `cmake --build build/gcc --parallel $(nproc)` (configure steps: build-run workflow).
- Test: `tools/.venv/bin/python3 -m pytest tests/ -v` (the `noise` package lives only in that venv).
- **Do not set `e_TerrainAutoGenerateBaseTexture 1`** for pipeline-generated levels — it overwrites
  `cover.ctc` with black tiles. The `cover.ctc` hmap layer must be `[128,128,0,0]`.
- Python never interprets prose: the LLM authors `asset_graph.json`; Python validates and compiles it.
- After deleting a build dir, fully reconfigure — a stale cache will not regenerate the uber files.
- New components: add `.h/.cpp` to `Code/CMakeLists.txt` under the `Components_uber.cpp` block; `StdAfx.h` first.

## Where to write what

| You are writing… | It goes in | Not in |
|---|---|---|
| a plan you are about to execute | `.agents/plans/` | `docs/` |
| progress, session notes, what you just did | `.agents/status.md` | a new file anywhere |
| something durable about a component | its card in `.memory/cards/` | `docs/` |
| a decision and its rationale | `docs/adr/` (humans own this) | `.agents/` |
| documentation a person will read | `docs/`, linked from `docs/README.md` | `.agents/` |

`docs/` is curated for people. Do not create new top-level markdown files. If nothing above
fits, add it to `.agents/open-questions.md` and ask.

## Before you finish

- Run the tests if you touched `tools/`; build if you touched `Code/`.
- Changed what is in flight? Update `.agents/status.md`. Shipped something? Add a `CHANGELOG.md` entry.
- Learned something durable? Put it in the relevant card or workflow — not in this file.
- Run `python3 <project-agentize>/scripts/project_context.py check .` to confirm the boundary still holds.
