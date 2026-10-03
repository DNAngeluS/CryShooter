# CRYENGINE 5.6 — Terrain

> **Read this when:** You need to know how a level is laid out on disk, why terrain renders wrong (water, spawn), or how to edit a level without Sandbox.
> **Related:** [Terrain textures](textures.md) · [LOD](lod.md) · [Lighting](lighting.md) · [All docs](README.md)

## Overview

Terrain in CRYENGINE is a heightmap-based mesh divided into sectors. Each sector is a square
patch of the world. The terrain is stored as a set of files, some inside `level.pak` and some
alongside it.

---

## Level File Structure

```
Assets/levels/<name>/
├── level.pak                  ← main binary archive (ZIP)
│   ├── levelinfo.xml          ← terrain dimensions, water level
│   ├── leveldata.xml          ← surface types, water level (duplicate)
│   ├── mission_mission0.xml   ← entities, environment, time-of-day
│   ├── terrain/
│   │   └── terrain.dat        ← raw heightmap data
│   └── ...
├── terraintexture.pak         ← separate archive for base colour tiles
│   └── terrain/cover.ctc      ← compiled terrain texture (binary)
└── leveldata/
    ├── environment.xml        ← fog, sky, ocean settings
    └── timeofday.xml          ← sun/TOD preset reference
```

---

## Key Configuration Values (`levelinfo.xml`)

```xml
<TerrainInfo
  HeightmapSize="1024"          <!-- heightmap samples per side -->
  UnitSize="1"                  <!-- metres per heightmap sample -->
  SectorSize="32"               <!-- metres per terrain sector -->
  SectorsTableSize="32"         <!-- sectors per side (= HeightmapSize/SectorSize) -->
  HeightmapZRatio="0.015625"    <!-- height = raw_value × ZRatio  (1/64) -->
  OceanWaterLevel="16"/>        <!-- Z height of ocean surface -->
```

Terrain world size = `HeightmapSize × UnitSize` = 1024 × 1 = **1024 m × 1024 m**.

---

## Water / Ocean

| CVar | Default | Effect |
|------|---------|--------|
| `e_WaterOcean` | 1 | 0 = disable ocean surface entirely |
| `e_WaterOceanBottom` | 1 | 0 = disable the flat bottom quad |

If `OceanWaterLevel` equals the terrain height (common with a fresh flat level), the ocean
surface and terrain triangles are co-planar → **z-fighting** (flickering black/grey).

**Fix in code** — apply at `ESYSTEM_EVENT_LEVEL_LOAD_END`:
```cpp
gEnv->pConsole->ExecuteString("e_WaterOcean 0",       false, true);
gEnv->pConsole->ExecuteString("e_WaterOceanBottom 0", false, true);
```

**Fix in data** — edit `levelinfo.xml` and `leveldata.xml` inside `level.pak`:
```
OceanWaterLevel="-100"
WaterLevel="-100"
```

---

## Environment / Lighting Preset

`mission_mission0.xml` references a time-of-day preset:
```xml
<TimeOfDay Time="12" ...>
  <Presets>
    <Preset Name="%ENGINE%/EngineAssets/Shading/default.env" Default="1"/>
  </Presets>
</TimeOfDay>
```

Use the engine-bundled `%ENGINE%/EngineAssets/Shading/default.env`.
Custom paths like `libs/environmentpresets/levels/example.env` must exist on disk or
the sun/sky will not render (black screen).

---

## Spawn Points

The engine finds spawn positions by iterating all entities with `CSpawnPointComponent`.
If no entity exists in the level, `GetFirstSpawnPointTransform()` returns `IDENTITY` (Z = 0).

**Code fallback using terrain elevation:**
```cpp
static Matrix34 GetFirstSpawnPointTransform()
{
    // ... iterate entities for CSpawnPointComponent ...

    // Fallback: terrain centre at a safe height
    const float cx = 512.f, cy = 512.f;
    const float terrainZ = gEnv->p3DEngine
        ? gEnv->p3DEngine->GetTerrainElevation(cx, cy)
        : 32.f;
    return Matrix34::Create(Vec3(1.f), IDENTITY, Vec3(cx, cy, terrainZ + 10.f));
}
```

`GetTerrainElevation(x, y)` lives on `I3DEngine` (`gEnv->p3DEngine`).

---

## Adding Entities to a Level (without Sandbox)

Entities live in `mission_mission0.xml` inside `level.pak`. The entity XML uses the
Schematyc component system:

```xml
<Objects>
  <Entity Name="SpawnPoint1" Pos="512,512,20" Rotate="1,0,0,0" Scale="1,1,1"
          EntityClass="SchematycEntity" Layer="Main" Id="{guid}">
    <Components>
      <Component>
        <TypeGUID>{41316132-8A1E-4073-B0CD-A242FD3D2E90}</TypeGUID>  <!-- CSpawnPointComponent -->
        <Name>SpawnPoint</Name>
        <GUID>{another-guid}</GUID>
      </Component>
    </Components>
  </Entity>
</Objects>
```

Component GUIDs come from `ReflectType`: `desc.SetGUID("..."_cry_guid)`.

---

## Editing `level.pak` Programmatically (Python)

```python
import zipfile, shutil, os, tempfile

pak = 'Assets/levels/example/level.pak'
tmp = tempfile.mkdtemp()

with zipfile.ZipFile(pak, 'r') as z:
    z.extractall(tmp)

# edit files in tmp/...

shutil.copy2(pak, pak + '.bak')
with zipfile.ZipFile(pak, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(tmp):
        for f in files:
            path = os.path.join(root, f)
            z.write(path, os.path.relpath(path, tmp))

shutil.rmtree(tmp)
```

---

## Sandbox Workflow

1. Open **CRYENGINE Sandbox** → open your `.cryproject`.
2. **File → Open Level** → select your level.
3. **Terrain → Edit Terrain** to sculpt heightmap.
4. **Terrain → Generate Terrain Texture** to bake `terraintexture.pak`.
5. **File → Save Level** — writes all XML and paks.
6. Place spawn points via **Entity → SpawnPoint** drag into viewport.
