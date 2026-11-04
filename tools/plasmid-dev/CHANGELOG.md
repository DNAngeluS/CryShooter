# plasmid-dev changelog

Semver. Every change to this tooling gets a version here, a `VERSION` bump and a git tag `vX.Y.Z`; projects vendor a tagged
copy (see "Releasing" in README.md). Newest first.

## 2.2.1 - 2026-11-04 - vendored copies include `rconsole.py`

2.2.0 added `plasmid_dev/rconsole.py` but `vendor.py` did not list it, so a vendored 2.2.0 copy failed on `health.startup_map`.
- `RUNTIME_FILES` now lists it; `tests/test_vendor.py::test_every_runtime_module_is_vendored` fails when a module in
  `plasmid_dev/` is missing from the list. Use 2.2.1, not 2.2.0.

## 2.2.0 - 2026-11-04 - `health.startup_map`: `run` and `health` can load a level

A project whose bare launch loads no level (SandboxLLM loads levels over the Remote Console) could never pass `make health`:
the real window is a flat frame, which 2.1.0 correctly refuses.
- Config key `health.startup_map` (level folder name; letters, digits, `_ . -`). After launching, `run` and `health` send
  `map <level> s` over the engine Remote Console (`plasmid_dev/rconsole.py`, port read from the engine log line
  `Remote console listening on: N`) and wait for `*LOADING: Level <level> loading time`. A `+map` launch argument is ignored by
  the engine here, so it is not used. `health` counts its capture delay from the loaded level; every existing check
  (mostly-black, capture-mismatch, shader settle) is unchanged.
- Failures are exit 5 for `run` / `launch-failed` for `health`, reason `startup-map-failed: ...` (no Remote Console line, send
  failed, game exited, level never finished loading). Needs an engine built with the Remote Console option.
- Without the key nothing changes.
- Tests: `tests/test_startup_map.py` (config validation; the client against a fake engine). Real gate: SandboxLLM
  `make health ENGINE=57` with `startup_map` = `light_room` passes; a name that is not a level fails.

## 2.1.0 - 2026-11-03 - `make health` no longer passes a window capture that is not the game

Root cause (found after the safety net below caught it on Intel, about 1 run in 2): the game window was not mapped, viewable
or on top when captured, so the root-window crop fallback grabbed the desktop wallpaper.
- `health_window_shot()` now prepares the window before every grab: `xdotool windowmap`, `windowraise`, `windowactivate`, then waits
  (bounded, `HEALTH_WINDOW_READY_S` = 10 s) until `xwininfo` reports `Map State: IsViewable`. The whole sequence is retried
  (3 attempts).
- The root-window crop is used only when the window is confirmed viewable AND the active window (`xdotool getactivewindow`).
  Otherwise the capture is reported unavailable: error `window-unavailable: ...` naming the cause, never a pass. With an in-engine
  pass and no usable window, `combine_verdicts()` returns `fail`, reason `window-unavailable` (the independent oracle did not look).
- Tests: fakes for wmctrl/xdotool/xwininfo/import (no display): prepare order, wait until viewable, never-viewable and
  not-on-top refuse the crop, window-unavailable never passes. The `capture-mismatch` check below stays as the safety net.

Fixed: `make health` once reported `status: pass`, `method: both` while the window capture was the desktop wallpaper (the
in-engine capture was right). Each image alone looked "rendered", so the independent oracle confirmed nothing.
- New `compare_captures()` (healthcheck.py): when both captures exist, their per-channel means must agree within
  `THRESHOLDS["capture_mismatch"]` (20; healthy runs on record differ by < 0.5, the worst pass by 4.6, the wallpaper by 39-105).
- New verdict: `fail`, reason `capture-mismatch`, method `both`; the message names the suspect capture (the window by default;
  with `--reference`, the one farther from the reference colour). The report gains an `agreement` key (`agree`, `diff`,
  `worst_channel_diff`, `suspect`). `combine_verdicts()` takes an optional `agreement` argument; without it nothing changes.
- Unchanged: every existing pass path (agreeing captures still pass), single-channel runs (`--no-window`, no in-engine capture)
  and the other failure reasons. A window-only run has no second channel to compare, so it cannot detect this.
- Tests: synthetic non-game image (no third-party content) at unit level and through `cmd_health`.

## 2.0.0 - 2026-10-27 - Renamed to plasmid-dev

Breaking: the tool is now `plasmid-dev` (brand Plasmid, DEC-05). Behaviour is unchanged except for the names below.

Renamed:
- Repo and tool directory: `Tools/dev` -> `Tools/plasmid-dev` (the orchestrator moves the directory; no path here depends on it).
- Runner: `dev.py` -> package `plasmid_dev/cli.py`, run as `plas-dev` (launcher at the tool root) or `python3 -m plasmid_dev`.
- Shader server: `cry_shader_server.py` -> `plasmid_dev/shader_server.py` (`tool:` services now resolve inside the package).
- Health check: `healthcheck.py` -> `plasmid_dev/healthcheck.py`; vendoring: `vendor.py` -> `plasmid_dev/vendor.py`.
- Config file: `cryengine-dev.config.json` -> `plasmid.config.json` (the schema is unchanged, `schema: 1`).
- Environment: `CRY_DEV_PROJECT_DIR` -> `PLASMID_DEV_PROJECT_DIR`, `CRY_DEV_CONFIG` -> `PLASMID_DEV_CONFIG`, `CRY_DXC` -> `PLASMID_DEV_DXC`, `CRY_DXC_NATIVE` -> `PLASMID_DEV_DXC_NATIVE`. New: `PLASMID_DEV_PYTHON` (the interpreter `plas-dev` runs under; Makefile.common sets it from `PY`). Tests: `PLASMID_DEV_PY`, `PLASMID_DEV_FPS`, `PLASMID_DEV_PREFIX`, `PLASMID_DEV_REGEN`, `PLASMID_DEV_TEST_PY`, `PLASMID_DEV_SERVER_PY`.
- Version line: `plasmid-dev <version>`. Vendored copies go to `tools/plasmid-dev/` and hold the `plasmid_dev/` package, the `plas-dev` launcher, `Makefile.common`, docs and `VERSION`.
- Makefile.common keeps every target name (`make run`, `make build`, ...) and calls `plas-dev`.
- Shader server temp directories: prefix `plasmid_shader_`.
- Tests: no user paths. The FPS-integration tests skip unless `PLASMID_DEV_FPS` names the FirstPersonShooter project.

Legacy aliases (read-only, removed in 3.0; each marked `# legacy-alias: removed in 3.0` in the code):
- `cryengine-dev.config.json` is read when `plasmid.config.json` is absent. The tool never writes the old name.
- `CRY_DEV_PROJECT_DIR`, `CRY_DEV_CONFIG`, `CRY_DXC`, `CRY_DXC_NATIVE` are read when the `PLASMID_DEV_*` name is unset.
- `tool:cry_shader_server.py` in a config resolves to `shader_server.py`.

Unchanged on purpose: the `.dev/` runtime directory (`dev_dir`), the `tools_version` key, the `CRYENGINE_DIR*` engine variables, and the engine's own names.

Migration for a consumer project (one vendor step, then commit):
1. Rename `cryengine-dev.config.json` to `plasmid.config.json` (or let `vendor.py` write the new name; it reads the old one).
2. Rename environment variables in project scripts, CI and `.env` files: `CRY_DEV_*` -> `PLASMID_DEV_*`, `CRY_DXC*` -> `PLASMID_DEV_DXC*`.
3. Re-vendor at 2.0.0: `python3 <CRYTEK>/Tools/plasmid-dev/plasmid_dev/vendor.py --project-dir <project> --version 2.0.0`. It writes `tools/plasmid-dev/` (the package tree and `plas-dev`) and `plasmid.config.json`; the 1.x copy in `tools/cryengine-dev/` is left for step 4.
4. Remove `tools/cryengine-dev/` and the forwarding shims `tools/dev.py` / `tools/cry_shader_server.py` from the project, then point `Makefile` at `Tools/plasmid-dev/Makefile.common` (the old include path still works only while the old directory exists).
5. Real gate: `make build`, `make run ENGINE=56` and `ENGINE=57`, `make stop`, `make health`, then commit in the project's git.

## 1.3.0 — 2026-10-25
- `cry_shader_server.py`: `--dxc wine|native|auto` (env `CRY_DXC`; default `wine`, so nothing changes unless a project opts in) and `--port`. `native` uses a Linux `dxc` (12-20x faster than Wine, a stricter DXC 1.10: `-HV 2018` is added), `auto` tries native and falls back to Wine per shader. Backends are limited to the ones that exist.
- The server remembers failed compiles (per source, flags and mode) and answers repeats from memory: the engine retries a failing shader every frame (5000+ attempts for one shader in the GameSDK sample).
- Log: first real `error:` line instead of the first 120 characters (Mesa/Wine warnings came first), backend per compile, `fallback` lines, mode in the start banner.
- Config: `services.<n>.args` (list of strings appended to the service command); unknown service keys are now an error.
- `doctor` (the verb only): rows for native dxc and for a `system.cfg` with `r_ShadersRemoteCompiler=1` (engine root or project); a private engine root without one leaves every frame black.
- Tests: 222 (new `tests/test_release_130.py`, 18; it caught `native` mode starting without a native dxc).
- Gate (real, GameSDK-Island on engine key 57f, `make run`/`stop` from this checkout, 70 s per mode, cold cache seeded from FPS): `wine` banner + 6 compiles (the old speed), `native` 177 OK and 1283 errors of which 1274 were answered from the failure memory (9 real attempts), `auto` 132 OK / 8 ERR / 5 fallbacks / 3 cached; every mode stopped cleanly (no game, no server, port free). A first attempt was blocked twice by another session's shader server on :61453 (`error: shader: port 61453 is in use by something we did not start`, the intended refusal); rerun once the port was free.
- Not done: an A/B of native versus Wine SPIR-V for rendering equivalence (TASK-gamesdk-linux-validation-05); a `shaders-warm` verb; client-side retry cap (engine side).

## 1.2.0 — 2026-10-24
- `health` reuses a shader server that another process holds on the service port (e.g. a second session's `cry_shader_server.py` on 61453) instead of failing with exit 3 / `launch-failed`; stderr says so, the report has `external_services`, and that server is never stopped by the run (OF-26). Ports free as before: the run starts and stops its own.
- `build` message tells the truth about the deploy (OF-11): it prints `-> <engine bin>` only when the plugin library in that bin is the one this build produced (written since the build started, or byte-identical after a no-op build); otherwise a warning that the project's CMake deployed elsewhere (see its `Deploying ...` line).
- `cry_shader_server.py` header: the remote-compile CVars go in the ENGINE-ROOT `system.cfg`; a project-folder `system.cfg` is never read (OF-22).
- Window capture: `_window_geometry` also rejects a window whose right/bottom edge is beyond the root window (second monitor), so the root-crop fallback is not used for a partial crop; new `_root_size()` (`xwininfo -root`). The 1.1.1 changelog line that implied this was wrong (that tag and the vendored copy are not edited).
- `shaders-status`: the game-log counts cover only the latest launch when the log carries the engine's `Log Started at` marker (FPS's appended `game.log` has none, so it still counts its whole 4 MB tail; the idle verdict is unchanged).
- Tests: 204 (new `tests/test_release_120.py`; `test_health_verb` fake root size).
- Not done (stays in TASK-dev-tooling-05): per-channel colour reference replacing the per-GPU ones; a real run that forces the root-crop fallback.

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
