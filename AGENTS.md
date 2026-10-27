# FirstPersonShooter — Agent Instructions

## Advisor mode (read first, whenever this session has an `advisor` tool)
If an advisor is available, the front session is **orchestrator + operator**: it plans, delegates, verifies and integrates; the **advisor** (the stronger model) reviews the approach before substantive work, when stuck, and before declaring done; **Haiku agents** are the workers (bounded edits, builds) and read-only researchers. Briefs to workers are self-contained, and a worker's report is a claim: verify the diff or the output before relaying. No external executor (Codex etc.) unless Lucio asks. Read this at the start of every such session, before acting.

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
| gotchas behind configure/build/run/debug (what `make` wraps) | `.agents/workflows/build-run.md` |
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

## Dev commands (use these, not raw cmake)

Run from the project root. `make help` lists everything; logic is in the generic runner `tools/plasmid-dev/plas-dev`
(stdlib Python). The runner is a VENDORED, numbered copy of the shared plasmid-dev tooling in `tools/plasmid-dev/` (committed here so a standalone clone works; pin: `tools_version` in the config, marker `tools/plasmid-dev/.vendored-from`). Never edit it here: change the tooling repo (`<Crytek>/Tools/plasmid-dev`, tagged `vX.Y.Z`), then `python3 <Crytek>/Tools/plasmid-dev/plasmid_dev/vendor.py --project-dir .`; `tools/plasmid-dev/plas-dev doctor` flags a mismatch or local edits. FPS settings live in `plasmid.config.json` (schema: `tools/plasmid-dev/config-schema.md`).
There are no forwarding shims: `tools/dev.py` and `tools/cry_shader_server.py` were removed 2026-10-27. Use `make <target>` or `tools/plasmid-dev/plas-dev <command>`.

| Do this | Command |
|---|---|
| first time / check environment | `make setup` · `make doctor` |
| compile (deploys plugin into the engine) | `make build` (`ENGINE=56\|57`, `COMPILER=gcc9\|gcc13\|gcc14\|clang`, `TYPE=Debug\|Profile\|Release`) |
| pick the engine | `ENGINE=56` (default, CRYENGINE 5.6.7, gcc9) or `ENGINE=57` (5.7.1, gcc13): `make run ENGINE=57`. Paths: `CRYENGINE_DIR` (=56) / `CRYENGINE_DIR_57` in `.env` |
| production build | `make release` |
| play (starts shader server, launches game **in background**) | `make run` (returns at once) |
| inspect state | `make status` (`tools/plasmid-dev/plas-dev status --json`) |
| shader cache per engine, compile progress | `make shaders-status` |
| read results | `make logs` (warnings/errors from `game.log`), or files in `.dev/logs/` |
| crash investigation without a terminal UI | `make debug-batch TIMEOUT=120` → `.dev/logs/gdb.log` |
| stop everything | `make stop` (idempotent) |
| tests · asset pipeline | `make test` · `make pipeline ARGS="…"` |

Rules for agents: never run `GameLauncher`, `gdb` or `shader_server.py` directly in the foreground — use
`make run` / `make debug-batch` / `make up`. `run` and `debug` need a desktop session; if `make doctor` warns
there is none, do not launch the game — build and test only. Always `make stop` when done. Commands print
the exact underlying command line (`$ …`) and exit non-zero on failure.
Do not edit `.dev/` (gitignored runtime state). After a milestone or a change that could break someone's
setup, add an entry to `CHANGELOG.md`.

## Working rules

- Engine path: `CRYENGINE_DIR` (env or `.env`, gitignored). Never hardcode it.
- Test: `make test` (uses `tools/.venv`; the `noise` package lives only in that venv).
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
- Changed what is in flight? Update `.agents/status.md`. Finished a milestone or changed something that could break a setup? Add a `CHANGELOG.md` entry (`Breaking / may break` heading).
- Learned something durable? Put it in the relevant card or workflow — not in this file.
- Run `python3 <project-agentize>/scripts/project_context.py check .` to confirm the boundary still holds.
