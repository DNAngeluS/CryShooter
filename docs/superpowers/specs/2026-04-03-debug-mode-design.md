# Debug Mode Design

**Date:** 2026-04-03
**Status:** Approved

## Overview

Replace the broken `Ctrl+P` screenshot shortcut with a proper debug mode system. Pressing `K` toggles a debug mode on/off. While debug mode is active, a "DEBUG" label is rendered at the bottom-left of the screen, and pressing `P` takes a screenshot. The design is intentionally minimal — future debug actions simply gate on the same `m_debugMode` flag.

## Problem

The existing `Ctrl+P` screenshot did not work reliably. The action was registered for `eKI_P` via `CInputComponent`, but the modifier guard (`gEnv->pInput->GetModifiers() & eMM_Ctrl`) was checked inside the callback. This is fragile on Linux: the action-map system may consume the key event independently of modifier state, making the combo unreliable.

## Design

### State

Add one member to `CPlayerComponent`:

```cpp
bool m_debugMode = false;
```

No changes to `EInputFlag` — debug mode is a modal state, not a movement flag.

### Input — K (toggle)

Register a `"debug_toggle"` action bound to `eKI_K`. On `eAAM_OnPress`, flip `m_debugMode`:

```cpp
m_pInputComponent->RegisterAction("player", "debug_toggle", [this](int activationMode, float value) {
    if (activationMode == eAAM_OnPress)
        m_debugMode = !m_debugMode;
});
m_pInputComponent->BindAction("player", "debug_toggle", eAID_KeyboardMouse, EKeyId::eKI_K);
```

### Input — P (screenshot)

Replace the old `"screenshot"` registration with `"debug_screenshot"`. No modifier check — the mode gate is sufficient:

```cpp
m_pInputComponent->RegisterAction("player", "debug_screenshot", [this](int activationMode, float value) {
    if (activationMode == eAAM_OnPress && m_debugMode)
        TakeDebugScreenshot();
});
m_pInputComponent->BindAction("player", "debug_screenshot", eAID_KeyboardMouse, EKeyId::eKI_P);
```

### HUD Overlay

In `ProcessEvent` → `EEvent::Update`, inside the `IsLocalClient()` block (alongside `UpdateCamera`), render the label when debug mode is active:

```cpp
if (m_debugMode)
{
    gEnv->pRenderer->Draw2dLabel(
        10.f,
        (float)gEnv->pRenderer->GetHeight() - 30.f,
        2.0f,
        Col_Red,
        false,
        "DEBUG"
    );
}
```

Position: 10px from left, 30px from bottom. Font size 2.0 — readable without being obtrusive.

### TakeDebugScreenshot

No changes. The function itself is correct; only the input path was broken.

## Files Changed

- `Code/Components/Player.h` — add `bool m_debugMode = false`
- `Code/Components/Player.cpp` — replace screenshot registration, add debug_toggle registration, add HUD render call

## Extensibility

Any future debug action (e.g. show FPS overlay, spawn entity, log state) follows the same pattern: register an action, check `m_debugMode` in the callback. When debug actions accumulate into a distinct subsystem, extract to a `CDebugOverlayComponent`.
