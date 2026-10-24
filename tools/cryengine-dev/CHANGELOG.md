# cryengine-dev changelog

Semver. Every change to this tooling gets a version here, a `VERSION` bump and a git tag `vX.Y.Z`; projects vendor a tagged
copy (see "Releasing" in README.md). Newest first.

## 1.1.2 — 2026-10-24
- `health` now watches the shader cache's `globals.txt`: a file with fewer than 10 flags (an empty stub from an early run) fails the run with reason `globals-stub`, a `%TEMP_TERRAIN` value other than `200000000` with `globals-terrain-flag`. Cause found in T8: an empty stub leaves `%TEMP_TERRAIN` unmapped and the renderer writes the wrong per-draw constant layout for terrain (half the far terrain renders black). New pure function `healthcheck.check_globals_flags`; runs after the shader-settle check. Tests: 198.

## 1.1.1 — 2026-10-21
- `health`: when `import -window <id>` keeps failing (observed: two consecutive runs failed all retries while another game was running on the same engine), the window rectangle is cropped out of the root window instead (`import -window root -crop WxH+X+Y`, geometry from `xwininfo`); a notice goes to stderr. Skipped when the window is not fully on the root window.
- Tests: 192.

## 1.1.0 — 2026-10-21
- New verb `health` / `make health` (see README): launch or reuse the game, in-engine and window screenshots, image and shader-cache checks, JSON report, exit 0/1/2; always stops a game it launched. New `healthcheck.py` (pure functions: image metrics, verdicts, shader settle, log/marker parsing).
- Config: optional `health` block (`default_delay_s`, `capture`); env `CRY_DEV_CONFIG=<file>` reads that config instead of the project's.
- Window grab retried (ImageMagick `import -window` is flaky); window lookup only matches THIS project's game (another project's GameLauncher on the same engine is ignored).
- `vendor.py` now vendors `healthcheck.py`. Tests: 192 (health tests need numpy + Pillow).
- Gated for real on engines 56 and 57, Intel and NVIDIA GPUs, plus a cold-cache negative test (fails `shaders-still-compiling`), `build`, `debug --batch`, no leftover processes.

## 1.0.0 — 2026-10-18
First numbered release (extracted from FirstPersonShooter's `tools/dev.py`).
- Generic runner `dev.py` driven by `<project>/cryengine-dev.config.json` (schema 1, see `config-schema.md`): setup, doctor, configure, build, clean, up, down, run, debug, stop, status, logs, shaders-status + project-declared extra verbs.
- Shared `Makefile.common` menu; Wine+DXC `cry_shader_server.py` (one server for both engines).
- Per-engine shader cache slots (`shader_cache` config; `user/shaders/cache` symlink switched on run/debug).
- Tests: golden dry-run characterization (FPS), config validation, synthetic second project, services, shader cache.
