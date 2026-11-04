<!-- when: you need to find durable project facts; read this before opening any .memory file -->
# .memory index

| File | Holds | Open when |
|---|---|---|
| [cards/code.md](cards/code.md) | The C++ game plugin (`Code/`): structure and gotchas | working anywhere inside `Code/` |
| [cards/tools.md](cards/tools.md) | Python asset pipeline, procgen, tracker, shader server (`tools/`, `tests/`) | working inside `tools/` or `tests/` |
| [inventory/code.json](inventory/code.json) | Machine inventory of `Code/` | query with `jq`, never read whole |
| [inventory/tools.json](inventory/tools.json) | Machine inventory of `tools/` | query with `jq`, never read whole |
| `env.json`, `glossary.json`, `graph.json`, `index.json` | Machine shards (environment, terms, dependency graph, file index) | query with `jq`, never read whole |

Work in flight is in [.agents/status.md](../.agents/status.md) and `.agents/workstreams/epics/`.
