# Known issues

Warnings and errors seen in `game.log` when launching on Linux, and what we know about each.
Last reviewed against a log captured on 2026-10-14 (errors table only; warnings last fully reviewed 2026-04-03). To check your own log:

```bash
grep -iE "\[Warning\]|\[Error\]" game.log | grep -v "Vulkan"
```

| Status | Meaning |
|---|---|
| **Open** | not investigated or not fixed yet |
| **Deferred** | cause understood, no gameplay impact today |
| **Fixed** | resolved in this repository or in the patched engine |
| **Engine-side** | not actionable from the game plugin |

## Errors

| Status | Message | Notes |
|---|---|---|
| Open | `Failed to load character Objects/Characters/SampleCharacter/firstperson.cdf` and `CryAnimation: failed to parse XML file …firstperson.cdf` | The character definition is missing or malformed, so no first-person arms or weapon render and the camera uses a fixed eye height. See [Character mesh](character_mesh.md). |
| Open | `Color Grading: Default color chart is missing` and missing `shadererror.dds` | Seen in a clean run 2026-10-14; cause not investigated (tracked under E-01). |
| Open | `Vulkan: Cannot create staging buffer` assert on CRYENGINE 5.7.1 (`make run ENGINE=57`) | Engine 5.7.1 rendering is unhealthy; 5.6.7 unaffected. See E-03 notes. |

## Missing engine textures

| Status | Files | Notes |
|---|---|---|
| Deferred | `textures/rain/ripple/ripple1–24_ddn.dds`, `surface_flow_ddn`, `rainfall(_ddn)`, `rain_spatter`, `puddle_mask` | The engine ships `.tif` sources only; its resource compiler is Windows-only. No rain in current levels. Options: run RC under Wine, generate stub DDS files, or patch the engine to skip loading them. |
| Open | `frozen/snow_spatter.dds`, `frost_noise4.dds` | Frozen weather textures; unused so far. |
| Open | `skys/night/half_moon.dds` | Night sky; also leaks after level unload. |
| Open | `palette/cloak_palette.dds` | Cloak shader falls back to the error texture. |
| Open | `texturemsg/shadererror.dds`, `shadercompiling.dds` | Affects in-editor shader error display only. |

## Wrong texture format — fixed

Five engine normal maps were DXT1 where the engine requires BC5 for `_ddn` textures. They were
recompressed to BC5 (R and G channels preserved): `perlinnoisenormal_ddn`, `oceanwaves_ddn`,
`screenfrost_ddn`, `hex_ddn`, `glass_decalatlas_ddn`. Details: [DDS normal-map format](dds_normal_map_format.md).

## Missing configuration files

| Status | File | Effect |
|---|---|---|
| Open | `libs/materialeffects/materialeffects.xml` | Material effects disabled: no footstep or bullet-impact surface effects |
| Open | `Scripts/AI/Cover.xml` | AI cover system unavailable |
| Open | `Libs/SmartObjects.xml` | Smart objects unavailable |
| Open | `assets/cryschematycsettings/log_settings.sc_settings` | Schematyc log settings; non-critical |
| Open | `Assets/localization/english.pak` | No localization strings; UI text may show raw keys |

## Miscellaneous

| Status | Issue | Notes |
|---|---|---|
| Fixed | `Unknown command: goto` | The engine runs `goto` after each screenshot to log the camera position. The plugin now registers it (and it also teleports the player when given coordinates). |
| Fixed | `[Screenshot] ScreenShot() failed` | Three causes: the JPEG writer and texture read-back were no-ops on Linux (engine patches, require an engine rebuild), and the engine's `ScreenShot()` reads a swapchain image the app no longer owns after present. The player now captures via `CaptureFrameBuffer()` (`capture_file_name`, `capture_frame_once`, `capture_frames`), which runs before present. |
| Engine-side | `Vk AsyncCommandQueue — no thread config found` | The Vulkan async queue runs at default priority; fixing it needs an engine thread-config XML. |
| Open | Debug screenshots (`K` then `P`) are not saved when the game is started with `make run` | `game.log` shows `mkdir('/user') failed` and `Frame capture failed!`: the plugin asked for `%USER%/Screenshots` and got a relative path (`user/screenshots/…`), which the engine's capture code cannot create. The same feature saved files to `user/screenshots/` when launched from VS Code in April. Cause not yet identified; being investigated as workstream E-03. Workaround: none known — launch from VS Code. |
| Open | `[CScriptSystem] OnShutdown not found` | A Lua script lacks an `OnShutdown` handler; called on level/game exit. |

## Fixed 2026-10-24: 512 m levels rejected, PNG layer textures, wrong layer shader
- `terrain.dat` lacked the trailing object-tree chunk and 0xDE padding: 512 m levels hung after load (see `terrain.md`). `fix-terrain` patched `fps_forest_basin`.
- Terrain layer materials referenced PNGs (not loadable) and used `Illum`: now DDS and `Terrain.Layer` (see `textures.md`). The detail pattern on `fps_forest_basin` (zig-zag on steep slopes) is the PLACEHOLDER layer textures (checker, stripes, radial gradient from `texture_builder`) tiled at 1 m and minified; it follows `DetailScaleX/Y` (A/B 2026-10-24: 0.25 gives large diamonds, 4 gives fine grain). Not a shader or projection bug; real layer textures (imagegen / import) or a larger `DetailScale` removes it. Kept by Lucio.
- Open: no normal maps for generated materials; `mesh_import` only stages source files for `rc.exe` (no Linux import path in the pipeline; `Tools/plasmid-assets` has one). Fixed in `Tools/plasmid-dev` 1.2.0 (then `Tools/dev`): `make health` now reuses a shader server held by another session.

## Observation 2026-10-24: dark blue blotches on far hills at a non-spawn view
At spawn (512, 512, 53.55) yaw 0 the terrain is evenly lit. With the camera turned down (pitch -37, yaw 56, same position) `fps_forest_basin` shows dark blue blotches on the far hills and a black patch on the near slope. Reproduced twice with scratch overlays and identical with the previous `Illum` layer materials, so it is not caused by the layer shader, the DDS textures or the terrain.dat fix. Most likely the `Probes=(0)` lighting fact (no environment probes: surfaces facing away from the sun get only a blue ambient; SandboxLLM OF-23). Not investigated further; a camera INSIDE the terrain is also black (unlit mesh interior). Use the spawn pose for visual tests.

