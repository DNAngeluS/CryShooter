# Tools/dev — generic dev runner for CRYENGINE game projects

One `make` UX for every CRYENGINE 5.6.7 / 5.7.1 project: `cd Projects/<X> && make run ENGINE=56`.
`dev.py` is the runner, `Makefile.common` the shared menu, `cry_shader_server.py` the Wine+DXC SPIR-V
shader server (one server serves both engines; `dxc.exe` is byte-identical). Per-project settings live in
`cryengine-dev.config.json` ([schema](config-schema.md)).

## Quick start for a new project

1. Create `cryengine-dev.config.json` at the project root ([config-schema.md](config-schema.md)).
2. Create a 5-line `Makefile`: `include $(or $(CRYTEK_ROOT),$(abspath $(CURDIR)/../..))/Tools/dev/Makefile.common`
   (plus a comment header; project-only targets go in `extra_verbs`).
3. Copy `.env.example` to `.env`; set `CRYENGINE_DIR_56` and `CRYENGINE_DIR_57`.
4. `make doctor`, then `make setup`, then `make run ENGINE=56`.

## Verbs

| Verb | What it does |
|---|---|
| `setup`, `doctor`, `configure` | venv + deps; check engine/compilers/gdb/wine/display; CMake configure |
| `build`, `clean`, `release` | dev compile, deployed to the engine's `bin/linux_x64_gcc`; clean; Release build |
| `up`, `down` | start / stop background services (shader server) |
| `run`, `run-release`, `debug`, `debug-batch` | launch in background; launch under gdb (interactive or batch) |
| `stop`, `status`, `logs`, `logs-all` | stop everything; service/build state; recent log lines |
| `shaders-status` | shader cache slot in use and compile progress |
| `health` | launch (or reuse) the game, screenshot it, fail if it is not rendering (see below) |

`make help` lists all targets, including the project's `extra_verbs`.
## `make health` (since 1.1.0)

Answers "is the game actually rendering?" (a black window must not pass). `make health [ARGS="--delay 40 --json"]`:
launches the game (or reuses a running one), captures it, checks the shader cache, and prints a verdict; exit `0` pass, `1` fail, `2` could not check (never a pass).
- **Capture:** in-engine (config `health.capture`: launch args that make the game write a screenshot and log a `saved`/`failed` line) and/or the game window (`wmctrl`/`xdotool` + ImageMagick `import`, X11 only; `import -window` flakes now and then, so it is retried and then replaced by a root-window crop of the window's rectangle). The window is the independent oracle: an in-engine capture error with a passing window is a PASS with a note, so assert `method == "both"` in the JSON when that matters.
- **Shader settle:** active cache slot file count unchanged between two samples and zero `Global Cache Miss` / `crc mismatch` in THIS run's log slice (the `shaders-status` idle verdict reads "still compiling" until ~60 s after launch even when warm, so it is not used). Cold cache => `cache-cold` / `shaders-still-compiling`.
- **Shared shader port:** if the service port is already served by a process this project did not start (another session's shader server), `health` reuses it with a notice and does not stop it (`external_services` in the report).
- **Shader cache `globals.txt`:** after the settle check the active slot's `globals.txt` must list at least 10 common flags (`globals-stub` otherwise) and have `%TEMP_TERRAIN 200000000` (`globals-terrain-flag`). An empty stub makes terrain draws read the wrong per-draw constants and half the far terrain renders black (T8, 2026-10-24); fix: delete the file, the engine re-creates it, shaders recompile.
- **Image checks** (`healthcheck.py`, thresholds from real baselines): `black` p99 luma < 12, `mostly-black`, `uniform` (std < 6 or < 48 colours), `transparent`, `too-small`; `colour-drift` is warn-only against `--reference R,G,B` (a per-GPU, per-view reference: Intel and NVIDIA render the spawn view with different colours).
- **Output:** `--json` prints only the report (also saved to `<dev_dir>/health/<engine>-<stamp>.json` with the images). Keys: `status`, `reason`, `method`, `message`, `game` (`launched`, `pid`, `leftover_game`), `process`, `shaders`, `in_engine`, `window`, `log_signals`.
- A game launched by `health` is always stopped (even on failure) unless `--keep-running`. Needs numpy and Pillow (`make setup` installs them in the project venv; without them it exits 2 before launching). Do not touch the game window during the run.
- Config: optional `health` block (`default_delay_s`, `capture.{launch_args,saved,failed}`), see `config-schema.md`.

## Environment

- `CRYTEK_ROOT`: the `Crytek/` root (default: derived from the project location).
- `CRY_DEV_PROJECT_DIR`: project root for `dev.py` when run outside it.
- `CRY_DEV_CONFIG`: read this file instead of `<project>/cryengine-dev.config.json` (try or gate a config change without editing the project).
- `ENGINE`: `56` or `57`. Empty root `ENGINE=` is handled.
- `.env`: `CRYENGINE_DIR_56`, `CRYENGINE_DIR_57` (`CRYENGINE_DIR` is a 5.6.7 fallback).

## Tests

```sh
cd Projects/FirstPersonShooter && tools/.venv/bin/python3 -m pytest ../../Tools/dev/tests -q -p no:cacheprovider
```

192 tests (the `health` tests need numpy + Pillow: read the skip count). Dry-run tests cannot see process matching, so every gate also needs a real run.

## Shims

`Projects/FirstPersonShooter/tools/dev.py` and `tools/cry_shader_server.py` forward to `Tools/dev/`. Project-only commands (`make test`, `make pipeline`) are `extra_verbs`.

## Versioning and releasing

`Tools/dev` is its OWN git repo (`Tools/dev/.git`; the Crytek domain root and `Tools/` are deliberately not repos). `VERSION` holds the semver,
`CHANGELOG.md` the history, git tags `vX.Y.Z` the releases. Projects do not read this checkout at runtime: each project VENDORS a tagged copy into
`<project>/tools/cryengine-dev/` (committed in the project's own git, so a standalone clone works) and pins it with `"tools_version"` in its config.

Releasing an improvement (order matters — never tag before the real gate):
1. Change the code + tests; bump `VERSION`; add a `CHANGELOG.md` entry.
2. Generic tests green: `cd <FPS> && tools/.venv/bin/python3 -m pytest <Tools/dev>/tests -q -p no:cacheprovider` (read the skip count).
3. REAL gate from this checkout (`python3 Tools/dev/dev.py --project-dir <FPS> ...`): `build` + `run` + `stop` on ENGINE=56 and 57, `pgrep -af '[G]ameLauncher|[c]ry_shader'` empty, one `debug-batch --timeout 60`, `shaders-status`. Dry-run goldens cannot see process bugs.
4. Commit, then `git tag -a vX.Y.Z -m "..."`.
5. Roll a project forward: `python3 Tools/dev/vendor.py --project-dir <project> [--version X.Y.Z]` (refuses a dirty tree or an untagged commit; copies runtime files only, no tests; writes `.vendored-from` with version, commit and file hashes; updates `tools_version`), re-run the real gate in that project, commit in the project.
`doctor`/`status` report the vendored version, a `tools_version` mismatch, and local edits to vendored files (never edit them in a project: change this repo, release, re-vendor).
No remote is configured yet: until one is added this repo exists only on this machine.
