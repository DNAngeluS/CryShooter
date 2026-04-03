# Debug Screenshot Feature — Design Spec

**Date:** 2026-04-02
**Status:** Approved

## Summary

Add an in-game debug screenshot capability bound to **Ctrl+P**. Screenshots are saved to `FirstPersonShooter/Screenshots/` with timestamped filenames for easy handoff to developers.

## Scope

All changes are confined to `Code/Components/Player.cpp` and `Code/Components/Player.h`. No new files, no new components.

## Input Handling

Register a `"screenshot"` action in `CPlayerComponent::InitializeLocalPlayer()`, bound to `eKI_P`. The callback fires on `eAAM_OnPress` only. Before taking the screenshot, the callback checks that either `eKI_LCtrl` or `eKI_RCtrl` is currently held via `gEnv->pInput->IsKeyDown()`. This is the standard CRYENGINE pattern for modifier combos, since `CInputComponent::BindAction` does not natively support modifier keys.

## New Method: `TakeDebugScreenshot()`

Declared `private` in `Player.h`, implemented in `Player.cpp`.

Steps:
1. Resolve the project root directory via `gEnv->pSystem->GetIProjectManager()->GetCurrentProjectDirectoryAbsolute()`.
2. Build a timestamped filename using `time()` + `localtime()` → format `screenshot_YYYYMMDD_HHMMSS.jpg`.
3. Construct the full output path: `<project_root>/Screenshots/<filename>`.
4. Call `gEnv->pFileIO->MakeDir(<project_root>/Screenshots)` — idempotent, safe to call on every screenshot.
5. Call `gEnv->pRenderer->ScreenShot(fullPath)` — engine writes the JPEG to disk.

## Output

```
FirstPersonShooter/Screenshots/screenshot_20260402_143055.jpg
```

The `Screenshots/` directory is created automatically on first use. It is gitignored (not tracked).

## Files Changed

| File | Change |
|------|--------|
| `Code/Components/Player.h` | Add `void TakeDebugScreenshot()` private declaration |
| `Code/Components/Player.cpp` | Register/bind input action in `InitializeLocalPlayer()`; implement `TakeDebugScreenshot()` |

## Out of Scope

- No console command variant
- No standalone component
- No custom output path configuration
- No on-screen HUD notification
