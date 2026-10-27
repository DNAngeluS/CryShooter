<!-- when: writing or reading a project's plasmid.config.json, or changing plasmid_dev/cli.py -->
# `plasmid.config.json` — per-project config for plasmid-dev

One file at the project root. `plas-dev --project-dir <dir>` (the Makefile passes `$(CURDIR)`) reads it; nothing
project-specific lives in the tool. Plain JSON (no comments). Paths are relative to the project root unless noted.
Every key below mirrors a constant that was hard-wired in FirstPersonShooter's original runner before 2026-10-18.

| Key | Type | Meaning (FPS value) |
|---|---|---|
| `schema` | int | config format version (`1`) |
| `name` | str | project name for messages |
| `cryproject` | str | project file passed to the launcher (`Game.cryproject`) |
| `source_dir` | str | dir holding `CMakeLists.txt` + `CMakePresets.json` (`Code`) |
| `plugin_lib` | str | plugin file name the build produces/deploys (`libGamePlugin.so`) |
| `plugin_out_dir` | str | where the project build leaves the plugin (`bin/linux_x64_gcc`) |
| `engine_bin_dir` | str | engine-relative dir with the launcher and where the plugin is deployed (`bin/linux_x64_gcc`) |
| `launcher` | str | launcher executable name (`GameLauncher`) |
| `dev_dir` | str | state dir for pids/logs (`.dev`) |
| `env_file` | str | dotenv file read for engine paths (`.env`; real environment wins) |
| `default_engine` | str | key into `engines` when `--engine`/`ENGINE` is absent (`"56"`) |
| `engines.<k>.label` | str | human name |
| `engines.<k>.dir` | str | directory under `<Crytek>/Engines/` used when no env var is set |
| `engines.<k>.env` / `fallback_env` | str / null | variable naming the checkout / legacy variable (56 only) |
| `engines.<k>.compiler` | str | default compiler key |
| `engines.<k>.presets` | map | compiler key -> CMake preset name |
| `build_dirs` | map | preset name -> build dir override (`gcc9` -> `build/gcc`, the dir VS Code uses); default `build/<preset>` |
| `services.<n>` | map | background service: `script` (project-relative, or a file of the `plasmid_dev` package via `"tool:<file>"`, e.g. `"tool:shader_server.py"`; the 1.x shader script name still resolves until 3.0), `port`, optional `args` (list of strings appended to the command, e.g. `["--dxc", "auto"]` for the shader server; unknown keys are an error) |
| `python.venv` / `python.requirements` | str | optional; omit for projects without a Python toolchain |
| `extra_verbs.<v>` | map | project-specific verbs: `help`, `python_module` **or** `python_script`, `fixed_args` (always passed first, e.g. `["tests/"]`), `default_args` (used only when the user passes no args after `--`, e.g. `["-q"]`) |
| `shader_cache` | map | optional per-engine shader cache: `link` (project-relative dir the engine reads, `user/shaders/cache`) becomes a relative symlink to `<slots_dir>/<engine key>`, switched before every `run`/`debug` (refused while the game runs on another engine's slot). `slots_dir` (`user/shaders/cache-by-engine`) holds one slot per engine key. Enables the `shaders-status` verb; omit to leave the cache alone |
| `health` | map | optional, for the `health` verb. `default_delay_s` (int > 0, default 40): seconds after launch to capture. `capture` (optional): in-engine screenshot. `launch_args`: list of strings appended to the launcher command; `{delay}` in them is replaced by the delay (e.g. `["+fps_autoshot_after_s", "{delay}"]`). `saved`: regex matching the engine's success marker, named groups `path` and `bytes`. `failed`: regex matching its failure marker, named group `reason`. Both are matched against game.log written since the launch; the last marker wins; `saved` with 0 bytes counts as failed. Without `capture` the verb takes a window screenshot only (needs an X11 session, `wmctrl` or `xdotool`, and ImageMagick `import`). Usage: `make health` (`ARGS="--delay 40 --json"`) |
| `tools_version` | str | tooling release this project is pinned to (matches the vendored VERSION); doctor warns on mismatch |
| `doctor_extra_compilers` | list | extra binaries `doctor` reports as warnings: a string (`"g++-9"`) or `{"bin": "g++-13", "label": "g++-13 (ENGINE=57)"}` when the row label differs from the binary name (`g++-9`, `g++-13 (ENGINE=57)`, `g++-14`, `clang++`) |

Rules: unknown keys are an error (typos must not pass silently); missing optional sections disable the matching verbs
(no `python` -> no `setup` venv step, no `extra_verbs` -> no `test`/`pipeline`). The Crytek root is found as the first
ancestor of the project dir that contains `Engines/` (not by `parent.parent`).

Env `PLASMID_DEV_CONFIG=<file>` makes the runner read that file instead of `<project>/plasmid.config.json` (paths in it stay project-relative; the project dir is still `--project-dir`). For trying a config change, or a real-run gate with a modified config, without touching the project.
