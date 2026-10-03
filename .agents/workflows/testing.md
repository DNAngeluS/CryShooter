<!-- when: running, adding or judging tests for this project -->
# Testing

**Python (`tools/`)** — the only automated tests.

```bash
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/requirements.txt   # once
tools/.venv/bin/python3 -m pytest tests/ -v
```

| File | Covers |
|---|---|
| `tests/test_asset_pipeline.py` | job lifecycle, graph validation, build/validate/publish |
| `tests/test_procgen.py` | terrain/interior/structured generators, classifier, terrain.dat writer (largest suite, 45 tests; 58 total at index time, all passing) |
| `tests/test_tracker_store.py` | tracker persistence |
| `tests/test_memory_contracts.py` | `memory/asset_pipeline_interface.json` has the bundle-graph verbs and skills |

Use the venv interpreter — system Python lacks the `noise` package and procgen tests will fail to import.

**C++ (`Code/`)** — no automated tests. Verify by building and running `GameLauncher`
(see `build-run.md`), then inspect `game.log`. Treat any `Code/` change as unverified until a launch confirms it.

**Smoke test of a published level** — `CRY_ASSET_PIPELINE_ENABLE_SMOKE=1` with `validate` (needs engine path).
