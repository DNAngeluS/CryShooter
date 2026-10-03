<!-- when: sizing, quoting or planning a change to this project -->
# Estimating work here

## Read order
1. `.memory/graph.json` → `seams` (what a *kind* of change touches)
2. *Effort signals* in the cards of the components involved
3. `testing.md` (what verification exists) · `open-questions.md` (what is unknown)

## Project-wide multipliers
- **No C++ tests, no CI.** Every `Code/` change needs a manual `GameLauncher` run to verify: add that time to every task.
- **Engine is external and patched.** Anything that touches engine behaviour (screenshots, GCC 14, shader server) may need an engine rebuild — evidence: engine patches listed in `build-run.md`.
- **Binary formats** (`cover.ctc`, `terrain.dat`, `heightmap.dat`, DDS): failures surface as black rendering, not errors. Budget debugging time, not just coding time.
- **Sandbox-only features** (painted terrain layers, light placement) cannot be automated by the pipeline.

## Churn (last 90 days at index time)
| Component | Commits | Reading |
|---|---|---|
| `Code` | 1 | quiet — expect rediscovery cost |
| `tools` | 0 | dormant since procgen (M3) landed — read tests before editing |

## Worked example — "add a new procgen biome"
Seam `terrain-pipeline` → touches `procgen/terrain_gen.py`, `classifier.py`, `templates/procgen/catalog.json`,
`asset_graph.py` validators, and `tests/test_procgen.py` (cards: tools). Test net exists (Python) → verifiable without the engine.
But visual correctness needs a `GameLauncher` smoke run (see the first multiplier) and a `cover.ctc` check (see the binary-formats multiplier). The answer is
therefore code+tests estimate **plus** a manual in-engine verification block, with the paint/foliage fidelity listed as unknown.
