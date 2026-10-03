<!-- when: you are about to write, review or commit code in Code/ or tools/ -->
# Conventions

Enforcer in brackets: **[CI]** automated, **[test]** a pytest asserts it, **[social]** nobody checks.

## C++ (`Code/`)
- `StdAfx.h` is the first include in every `.cpp`. [social]
- Components register via `CRY_STATIC_AUTO_REGISTER_WITH_PARAM` or `CRYREGISTER_CLASS`. [social]
- New component files must be listed in `Code/CMakeLists.txt` under the `Components_uber.cpp` `add_sources()` block, or they are not compiled. [build]
- Tabs for indentation; `Type *name` pointer spacing (the last commit reformatted `GamePlugin.cpp` this way). [social]
- Never call `gEnv->pSystem->Quit()` from inside an input callback — set a flag and quit on the next update tick (ESC handling in `Player.cpp`). [social]
- Apply per-level CVars at `ESYSTEM_EVENT_LEVEL_LOAD_END`, not at plugin init, so they override level defaults. [social]
- Plugin entry in `Game.cryproject` for Linux must be the bare name `"GamePlugin"` (`CryLoadLibrary` prepends `lib`). [social]

## Python (`tools/`)
- Interpreter: `tools/.venv/bin/python3`; deps in `tools/requirements.txt`. [social]
- Pipeline stages stay separate commands: `build` → `validate` → `publish`. Publish is never implicit. [test]
- A request the graph cannot represent must **fail validation**, never degrade silently. [test]
- Level jobs accept a slug or `Assets/levels/<slug>`; the pipeline normalises to the slug. [test]
- Generated assets, jobs and logs stay out of git: `user/`, `build/`, `bin/`, `*.log` are ignored. [social]
- Terrain texture hmap layer pixel is always `bytes([128,128,0,0])`; default ocean level is `-100`; default env preset is `%ENGINE%/EngineAssets/Shading/default.env`. [test, partly]

## Git
- Conventional-commit style (`feat:`, `fix:`, `docs:`, `chore:`, scoped like `fix(textures):`). [social]
- Do not commit or push unless asked. Machine-specific config (`.env`, `.vscode/settings.json`, `CMakeUserPresets.json`) is gitignored.

## Boundary
Default human/agent split applies: `docs/` is human documentation (engine knowledge guides are
deliberately kept there and indexed by `docs/README.md`); agents write to `.agents/` and `.memory/`.
The top-level `memory/*.json` directory is **pipeline state read by `tools/`** (the tracker reads
and writes it) — it stays where it is.
