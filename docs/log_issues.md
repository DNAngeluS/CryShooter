# Game Log Issues Tracker

Captured from `game.log` (session 2026-04-03). Each issue has a status and notes column.
Re-run `grep -iE "\[Warning\]|\[Error\]" game.log | grep -v "Vulkan"` to refresh.

---

## Errors

| ID  | Status | Message | Notes |
|-----|--------|---------|-------|
| E1  | open   | `[Error] Failed to load character Objects/Characters/SampleCharacter/firstperson.cdf!` | CDF file missing or malformed; no first-person arms/weapon mesh rendered |
| E2  | open   | `[Error] CryAnimation: failed to parse XML file: objects/characters/samplecharacter/firstperson.cdf` | Same root cause as E1 |

---

## Warnings — Missing Textures

| ID  | Status | File | Notes |
|-----|--------|------|-------|
| W1  | known  | `%engine%/engineassets/textures/rain/ripple/ripple1–24_ddn.dds` (24 files) | Rain ripple normal maps missing from engine install. No rain in current levels so no gameplay impact. Tracked separately in memory. |
| W2  | known  | `rain/surface_flow_ddn.dds`, `rainfall_ddn.dds`, `rainfall.dds`, `rain_spatter.dds`, `puddle_mask.dds` | Same rain system as W1 |
| W3  | open   | `frozen/snow_spatter.dds`, `frost_noise4.dds` | Frozen/snow weather textures missing; no frozen weather in use currently |
| W4  | open   | `%engine%/engineassets/textures/skys/night/half_moon.dds` | Night sky texture missing; also leaks after level unload |
| W5  | open   | `%engine%/engineassets/textures/palette/cloak_palette.dds` | Cloak shader palette missing; falls back to error texture |
| W6  | open   | `%engine%/engineassets/texturemsg/shadererror.dds`, `shadercompiling.dds` | Engine UI feedback textures missing; affects in-editor shader error display |

---

## Warnings — Wrong Texture Format

All five were in DXT1/BC1 format (engine expects BC5/ATI2 for `_ddn` normal maps).
Fixed by recompressing DXT1 → BC5 (ATI2) using a Python converter (R+G channels preserved).
The engine check at `Texture.cpp:1186` only accepts `eTF_BC5U/S`, `eTF_BC7`, or `eTF_EAC_RG11` for `_ddn` textures.

| ID  | Status | File |
|-----|--------|------|
| W7  | fixed  | `%engine%/engineassets/textures/perlinnoisenormal_ddn.dds` |
| W8  | fixed  | `%engine%/engineassets/textures/oceanwaves_ddn.dds` |
| W9  | fixed  | `%engine%/engineassets/textures/screenfrost_ddn.dds` |
| W10 | fixed  | `%engine%/engineassets/textures/hex_ddn.dds` |
| W11 | fixed  | `%engine%/engineassets/textures/glass_decalatlas_ddn.dds` |

---

## Warnings — Missing XML / Config Files

| ID  | Status | File | Notes |
|-----|--------|------|-------|
| W12 | open   | `libs/materialeffects/materialeffects.xml` | MFX system entirely disabled; no surface material effects (footsteps, bullet impacts, etc.) |
| W13 | open   | `Scripts/AI/Cover.xml` | AI cover system unavailable |
| W14 | open   | `Libs/SmartObjects.xml` | Smart objects system unavailable |
| W15 | open   | `assets/cryschematycsettings/log_settings.sc_settings` | Schematyc log settings not found; non-critical |

---

## Warnings — Miscellaneous

| ID  | Status | Message | Notes |
|-----|--------|---------|-------|
| W16 | open   | `Cannot open Pak file Assets/localization/english.pak` | No localization strings loaded; UI text may show raw keys |
| W17 | fixed  | `Unknown command: goto` (×3 per session) | Engine calls `goto` after every screenshot (DriverD3D.cpp:3640) to log camera position. Fixed by registering `goto` in `GamePlugin::Initialize()` — also supports teleport with args. |
| W18 | fixed  | `[Screenshot] ScreenShot() failed` (×3 per session) | Three sub-issues: (1) `WriteJPG` was a Linux no-op — removed `#if CRY_PLATFORM_LINUX` guard in `JpgImage.cpp`. (2) `RT_ReadTexture` was a Windows-only stub — removed `#if CRY_PLATFORM_WINDOWS` guard in `DriverD3D.cpp`. (3) Screenshots were black/corrupted — `ScreenShot()` dispatches to the render thread and reads `GetPresentedBackBuffer()` after `vkQueuePresentKHR`, a swapchain image the app no longer owns. Fixed in `Player.cpp` by switching to `CaptureFrameBuffer()` via the `capture_file_name` / `capture_frame_once` / `capture_frames` CVars; this path runs BEFORE present with a safely re-acquired back buffer. Requires engine rebuild for (1) and (2). |
| W19 | info   | `Vk AsyncCommandQueue` — no thread config found (×3) | Engine-side; Vulkan async queue runs on default thread priority. Fix requires engine thread config XML. |
| W20 | open   | `[CScriptSystem] OnShutdown not found` | Lua script missing `OnShutdown` handler; called on level/game exit |

---

## Status Legend

| Status | Meaning |
|--------|---------|
| `open`  | Not yet investigated or fixed |
| `known` | Root cause understood; fix deferred or not needed |
| `fixed` | Resolved |
| `info`  | Engine-side / not actionable from the plugin |
