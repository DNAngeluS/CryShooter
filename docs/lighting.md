# CRYENGINE 5.6 — Lighting

## Overview

CRYENGINE lighting has three layers that must all be correctly wired together:

1. **Time-of-Day (TOD) system** — animates the sun, sky, fog and ambient over a 24-hour cycle.
2. **Environment preset (`.env` file)** — defines the spline values for every TOD parameter.
3. **Level environment XML** — declares which `.env` to load and sets the static sun direction.

If any layer is missing or misconfigured the scene renders completely black.

---

## The Most Common Cause of a Black Screen

The level's `mission_mission0.xml` references a TOD preset:

```xml
<TimeOfDay Time="12" TimeStart="0" TimeEnd="24" TimeAnimSpeed="0">
  <Presets>
    <Preset Name="libs/environmentpresets/levels/example.env" Default="1"/>
  </Presets>
</TimeOfDay>
```

If the `.env` file doesn't exist on disk the engine silently skips it — **no sun, no sky, black**.

**Fix:** use the engine-bundled default that always exists:

```xml
<Preset Name="%ENGINE%/EngineAssets/Shading/default.env" Default="1"/>
```

This is the only `.env` file that ships with the engine at a predictable path.

---

## File Locations

| File | Path | Contents |
|------|------|---------|
| Default preset | `%ENGINE%/EngineAssets/Shading/default.env` | Full day/night spline values |
| Level environment | `level.pak/leveldata/environment.xml` | Fog, sky, ocean, sun direction |
| Level TOD reference | `level.pak/mission_mission0.xml` → `<TimeOfDay>` | Which `.env` to load, current time |

---

## Environment Preset Format (`.env`)

The `.env` file is XML with `<EnvironmentPreset CryXmlVersion="2" version="3">` as root.
Each parameter is a named `<var>` containing up to three `<spline>` channels (RGB or scalar).

### Time Encoding

The spline key positions represent time-of-day:

| Key value | Time |
|-----------|------|
| `0` | 00:00 (midnight) |
| `36000` | 06:00 (dawn) |
| `72000` | 12:00 (noon) |
| `108000` | 18:00 (dusk) |
| `144000` | 24:00 (end of day, wraps to midnight) |

### Key Parameter IDs

| Parameter | Type | Effect |
|-----------|------|--------|
| `PARAM_SUN_COLOR` | COLOR | Sun light RGB colour (0–1) |
| `PARAM_SUN_INTENSITY` | FLOAT | Sun irradiance in lux (0–550000; noon ≈ 244000) |
| `PARAM_SUN_SPECULAR_MULTIPLIER` | FLOAT | Specular highlight strength |
| `PARAM_FOG_COLOR` | COLOR | Horizon/base fog colour |
| `PARAM_FOG_COLOR_MULTIPLIER` | FLOAT | Fog brightness scale |
| `PARAM_SKY_COLOR` | COLOR | Zenith sky colour |
| `PARAM_AMBIENT_GROUND_COLOR` | COLOR | Bounce light from below |
| `PARAM_AMBIENT_MIN_HEIGHT` | FLOAT | Height below which ambient is at minimum |
| `PARAM_HDR_DYNAMIC_POWER_FACTOR` | FLOAT | Eye-adaptation exposure speed |

### Minimal Static Preset (always noon, no animation)

```xml
<?xml version="1.0" encoding="utf-8"?>
<EnvironmentPreset CryXmlVersion="2" version="3">
  <!-- Sun colour: warm white at all times -->
  <var id="PARAM_SUN_COLOR" type="TYPE_COLOR" minValue="0" maxValue="1">
    <spline0 keys="0:0.95:0:0:0:0:4:4:0,144000:0.95:0:0:0:0:4:4:0,"/>
    <spline1 keys="0:0.90:0:0:0:0:4:4:0,144000:0.90:0:0:0:0:4:4:0,"/>
    <spline2 keys="0:0.80:0:0:0:0:4:4:0,144000:0.80:0:0:0:0:4:4:0,"/>
  </var>
  <var id="PARAM_SUN_INTENSITY" type="TYPE_FLOAT" minValue="0" maxValue="550000">
    <spline0 keys="0:120000:0:0:0:0:4:4:0,144000:120000:0:0:0:0:4:4:0,"/>
    <spline1 keys=""/>
    <spline2 keys=""/>
  </var>
</EnvironmentPreset>
```

---

## Level Environment XML (`environment.xml`)

Controls global scene settings independent of TOD:

```xml
<Environment>
  <!-- Sky material — must point to a valid .mtl -->
  <SkyBox Material="%ENGINE%/EngineAssets/Materials/Sky/Sky"
          MaterialLowSpec="%ENGINE%/EngineAssets/Materials/Sky/Sky"
          Angle="0" Stretching="0.5"/>

  <!-- Static sun direction (when SunLinkedToTOD="0") -->
  <Lighting SunRotation="240" SunHeight="80"
            SunLinkedToTOD="1"
            SunVector="-0.52,-0.30,-0.80"/>

  <!-- Fog settings -->
  <Fog ViewDistance="8000" ViewDistanceLowSpec="1000" LDRGlobalDensMult="1.0"/>
</Environment>
```

### `SunLinkedToTOD`

| Value | Behaviour |
|-------|-----------|
| `1` | Sun direction follows the TOD system (angle changes during day) |
| `0` | Sun locked to `SunVector` regardless of TOD time |

### `SunVector`

Normalised direction vector pointing **toward** the sun.
`(-0.52, -0.30, -0.80)` ≈ sun at SunHeight=80° (nearly overhead), SunRotation=240°.

---

## TimeOfDay XML Block (`mission_mission0.xml`)

```xml
<TimeOfDay Time="12"           <!-- current time in hours (0–24) -->
           TimeStart="0"       <!-- animation start time -->
           TimeEnd="24"        <!-- animation end time -->
           TimeAnimSpeed="0">  <!-- 0 = frozen, >0 = seconds per in-game hour -->
  <Presets>
    <Preset Name="%ENGINE%/EngineAssets/Shading/default.env" Default="1"/>
  </Presets>
</TimeOfDay>
```

Set `Time="12"` for noon (maximum sun height). Set `TimeAnimSpeed="0"` to freeze time.

---

## Lighting CVars

### Sky

| CVar | Default | Effect |
|------|---------|--------|
| `e_SkyBox` | `1` | 0 = disable sky rendering (black background) |

### Shadows

| CVar | Default | Effect |
|------|---------|--------|
| `e_Shadows` | `1` | 0 = disable all shadow maps |
| `e_ShadowsMaxTexRes` | `1024` | Shadow map resolution in pixels |
| `e_ShadowsResScale` | `2.8` | Shadow resolution scale |
| `e_ShadowsConstBias` | `1.0` | Constant shadow bias (reduces acne) |
| `e_ShadowsSlopeBias` | `1.0` | Slope-scale shadow bias |
| `e_ShadowsBlendCascades` | `1` | Smooth cascade transitions |

### Global Illumination / Ambient

| CVar | Default | Effect |
|------|---------|--------|
| `e_GI` | `0` | 1 = enable voxel-based GI (expensive) |
| `e_HorizonBasedAmbient` | `1` | Screen-space horizon ambient occlusion |

### Debug

| CVar | Default | Effect |
|------|---------|--------|
| `e_ShadowsDebug` | `0` | 1 = visualise shadow cascades |
| `r_DisplayInfo` | `0` | 1 = show render stats overlay |

---

## Applying Lighting Settings in Code

Set CVars at `ESYSTEM_EVENT_LEVEL_LOAD_END` to override level defaults:

```cpp
case ESYSTEM_EVENT_LEVEL_LOAD_END:
{
    // Freeze time at noon
    gEnv->p3DEngine->SetTimeOfDay(12.0f, true);

    // Reduce shadow acne on flat terrain
    gEnv->pConsole->ExecuteString("e_ShadowsConstBias 0.5", false, true);
    gEnv->pConsole->ExecuteString("e_ShadowsSlopeBias 0.5", false, true);
}
break;
```

---

## Sandbox Workflow

### Editing Time-of-Day

1. **View → Time Of Day** — opens the TOD editor.
2. Select a parameter from the list (e.g. Sun Color).
3. Drag spline handles on the timeline to set values at each hour.
4. **File → Export** inside the TOD editor → saves as `.env`.

### Placing Lights

- **Entity → Light** — omni / spot / projector lights.
- **Entity → EnvironmentProbe** — captures local cubemap for IBL.
- `r_HDRRendering` must be `1` (default) for physical light units to display correctly.

### Sun Direction

Adjust in **Environment → Sun** panel. `SunRotation` = azimuth (0 = North), `SunHeight` = elevation in degrees above horizon.
