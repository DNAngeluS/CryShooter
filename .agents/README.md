<!-- when: you need something from .agents and do not know which file -->
# .agents

| File | Read it when |
|---|---|
| `architecture.md` | you need to know how plugin, engine, pipeline and levels fit together |
| `conventions.md` | you are about to write or review code |
| `status.md` | you need to know what is happening right now |
| `open-questions.md` | something looks ambiguous or contradictory |
| `workflows/build-run.md` | configuring, building, running or debugging the plugin |
| `workflows/asset-pipeline.md` | generating a level, character or mesh |
| `workflows/testing.md` | running or adding tests |
| `workflows/debugging.md` | black screen, z-fighting, black terrain, engine log warnings |
| `workflows/estimating.md` | sizing or quoting work |
| `workstreams/` | picking up, updating or estimating planned work |
| `plans/` | implementing something that was designed first (empty today) |

New design docs go in `plans/<slug>.md`. Durable lessons go in the relevant component card under
`.memory/cards/`, not here. `archive/` holds pre-migration originals for people; nothing routes to it.
