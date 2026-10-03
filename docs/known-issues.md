# Known issues

Warnings and errors seen in `game.log` when launching on Linux, and what we know about each.
Last reviewed against a log captured on 2026-04-03. To check your own log:

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
| Open | `[CScriptSystem] OnShutdown not found` | A Lua script lacks an `OnShutdown` handler; called on level/game exit. |
