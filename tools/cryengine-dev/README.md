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

`make help` lists all targets, including the project's `extra_verbs`.
## Environment

- `CRYTEK_ROOT`: the `Crytek/` root (default: derived from the project location).
- `CRY_DEV_PROJECT_DIR`: project root for `dev.py` when run outside it.
- `ENGINE`: `56` or `57`. Empty root `ENGINE=` is handled.
- `.env`: `CRYENGINE_DIR_56`, `CRYENGINE_DIR_57` (`CRYENGINE_DIR` is a 5.6.7 fallback).

## Tests

```sh
cd Projects/FirstPersonShooter && tools/.venv/bin/python3 -m pytest ../../Tools/dev/tests -q -p no:cacheprovider
```

92 tests. Dry-run tests cannot see process matching, so every gate also needs a real run.

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
