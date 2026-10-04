<!-- when: the game renders black, flickers, shows black terrain, or logs missing-texture / missing-config warnings -->
# Debugging rendering and log warnings

Deep explanations live in `docs/` (see `docs/README.md` symptom table). This is the agent-facing triage list.

| Symptom | Cause → fix |
|---|---|
| Whole scene black | `.env` preset path in `mission_mission0.xml` doesn't exist → use `%ENGINE%/EngineAssets/Shading/default.env` |
| Terrain solid black, from the start | `terraintexture.pak` empty/invalid → needs a valid `terrain/cover.ctc` (pipeline generates it) |
| Black sectors spreading diagonally as the player moves | `e_TerrainAutoGenerateBaseTexture 1` overwrote `cover.ctc` → keep it at `0` for pipeline levels |
| Terrain lit with a tilt / skewed shading | `cover.ctc` layer-1 pixel not `[128,128,0,0]` |
| Flicker at ocean level | `OceanWaterLevel` == terrain height → set `-100` or `e_WaterOcean 0`, `e_WaterOceanBottom 0` |
| Flicker at terrain LOD seams | tighten `e_TerrainLodErrorRatio` (0.001 used), `e_TerrainLodDistanceRatio 4.0` |
| Flicker/grey-black as player stands | camera too low / capsule sinking → raise camera over entity origin |
| Spawn at Z=0 / underground | no `CSpawnPointComponent` in level → fallback is terrain centre + 10 m; pipeline injects one |
| No arms/weapon, no `barrel_out` | `firstperson.cdf` missing or malformed (open issue E-01) |
| `Wrong format … for normal map` | `_ddn` textures must be BC5/BC7/EAC_RG11 (`Texture.cpp:1186`); five engine files were converted with `tools/asset_pipeline/dds_normalmap_fix.py` |
| 30+ `Texture does not exist … rain/ripple…` | engine ships `.tif`+`.cryasset` only; RC.exe is Windows-only. No gameplay impact; fix = Wine+RC, stub 1×1 DDS script, or engine patch |
| `Unknown command: goto` | registered in `GamePlugin::Initialize()` (engine calls it after each screenshot) |
| `K`+`P` screenshot not saved, log has `mkdir('/user') failed` | relative `%USER%` path under `make run`; open investigation → `.agents/workstreams/epics/E-03.md` (do not patch blindly) |
| Screenshot fails/black | engine `WriteJPG` and `RT_ReadTexture` needed Linux guards removed (engine rebuild); `Player.cpp` uses `CaptureFrameBuffer()` via `capture_file_name`/`capture_frame_once`/`capture_frames` CVars, because `ScreenShot()` reads a presented swapchain image |

Still-open engine/config warnings (no action yet): snow/frost and night-sky textures, `cloak_palette.dds`, shader-message textures,
`materialeffects.xml` (MFX off), `Scripts/AI/Cover.xml`, `Libs/SmartObjects.xml`, `english.pak`, Schematyc log settings, Lua `OnShutdown`,
Vulkan async-queue thread config (engine-side). Full historical table: `docs/known-issues.md`.

Refresh the list: `grep -iE "\[Warning\]|\[Error\]" game.log | grep -v Vulkan`.
