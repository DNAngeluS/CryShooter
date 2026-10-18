# cryengine-dev changelog

Semver. Every change to this tooling gets a version here, a `VERSION` bump and a git tag `vX.Y.Z`; projects vendor a tagged
copy (see "Releasing" in README.md). Newest first.

## 1.0.0 — 2026-10-18
First numbered release (extracted from FirstPersonShooter's `tools/dev.py`).
- Generic runner `dev.py` driven by `<project>/cryengine-dev.config.json` (schema 1, see `config-schema.md`): setup, doctor, configure, build, clean, up, down, run, debug, stop, status, logs, shaders-status + project-declared extra verbs.
- Shared `Makefile.common` menu; Wine+DXC `cry_shader_server.py` (one server for both engines).
- Per-engine shader cache slots (`shader_cache` config; `user/shaders/cache` symlink switched on run/debug).
- Tests: golden dry-run characterization (FPS), config validation, synthetic second project, services, shader cache.
