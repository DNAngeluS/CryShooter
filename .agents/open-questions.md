<!-- when: something in this project looks ambiguous, contradictory or unverified -->
# Open questions

| Question | Why it matters | Current assumption | Who can answer |
|---|---|---|---|
| Current phase and owner of in-flight work | status.md is derived from git + tracker, not from a person | pre-release, single developer `[assumed]` | Lucio |
| Is `memory/asset_pipeline_tracker.json` still the roadmap of record? Last update 2026-04-03, milestone M2, but M3 procgen shipped after | agents would resume stale next-actions | tracker is stale; E-02 reflects it `[assumed]` | Lucio |
| Does the startup-level auto-load still need `fps_forest_basin` hard-coded (`kStartupLevel`)? Earlier value was `fps_tech_ruins_interior` | smoke tests and screenshots depend on it | intentional dev convenience `[assumed]` | Lucio |
| Is Clang 22 verified against the current engine path? Personal notes say "not yet verified" and mention the engine dir was renamed `CRYENGINE_Source` | build matrix may be partly untested | GCC 9 and GCC 14 verified; Clang unverified `[assumed]` | Lucio |
| Do the GCC 14 engine patches (`IEntityComponent.h`, `CryArray.h`) still apply in the current engine checkout? | GCC 14 build fails without them | must be re-applied per checkout `[assumed]` | Lucio |
| Are `README.md` (GCC 9 only) and the multi-compiler instructions meant to converge? | README under-documents GCC 14/Clang | README lags `[assumed]` | Lucio |
| Why is the `%USER%/Screenshots` path relative (`user/screenshots/…`) under `make run`, breaking `K`+`P` screenshots? It worked from VS Code in April | the capture path is a visible regression of the new launch method (E-03) | launch environment (cwd/stdio/session/env) or an engine-tree change; unverified `[assumed]` | Lucio, by running `make run` vs `make debug` vs VS Code |
| What else did the VS Code setup do implicitly (build-before-launch task, shader-server task with a listening wait, env, IntelliSense paths) that `tools/dev.py` does not? | the project was designed around VS Code; gaps may surface one at a time | none enumerated yet (E-03/T-03) | audit of `.vscode/` |
| Which toolchain should `make` use: the project-local `Linux_GCC_System.cmake` (presets) or the engine's `Linux_GCC.cmake` (VS Code tasks)? | different flags could explain behaviour differences | presets are fine `[assumed]` | Lucio |
| Does `make status` / plugin deploy target the right engine for `ENGINE=57`? | status shows gcc13 unconfigured though `build/e57-gcc13` exists; 5.7.1 bin .so older than last build | unverified 2026-10-14 | Lucio |
