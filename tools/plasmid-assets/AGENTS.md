# Tools/plasmid-assets — Agent Instructions

## Advisor mode (read first, whenever this session has an `advisor` tool)
If an advisor is available, the front session is **orchestrator + operator**: it plans, delegates, verifies and integrates; the **advisor** (the stronger model) reviews the approach before substantive work, when stuck, and before declaring done; **Haiku agents** are the workers (bounded edits, builds) and read-only researchers. Briefs to workers are self-contained, and a worker's report is a claim: verify the diff or the output before relaying. No external executor (Codex etc.) unless the maintainer asks. Read this at the start of every such session, before acting.

Scope: stdlib-only Python tools for CRYENGINE assets (PNG to DDS, CGF writer/dumper, glTF importer, fixture writers). Liftable: no references to a host project, no files outside this directory. Every change needs a `VERSION` bump, a `CHANGELOG.md` entry, passing tests (`python3 -m pytest -q tests`) and a git tag `vX.Y.Z`; projects use a tagged copy. Read `README.md` and `CHANGELOG.md` first.
