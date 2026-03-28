# CRYENGINE 5.6 — Level of Detail (LOD)

## Overview

LOD (Level of Detail) is the mechanism by which CRYENGINE renders less geometry and lower
resolution textures for objects that are far from the camera. For terrain specifically, the engine
uses a **quad-tree** where each node can be rendered at a different mesh resolution depending on
distance and an error threshold.

---

## Terrain LOD Architecture

The terrain is divided into a quad-tree of `CTerrainNode` objects:

```
Root (covers full terrain)
├── NW quadrant
│   ├── NW/NW quadrant
│   │   └── ... (down to individual sectors)
│   └── ...
└── ...
```

For a 1024 m × 1024 m terrain with 32 m sectors (32×32 = 1024 sectors):

| Tree level | Nodes | Coverage per node |
|-----------|-------|-------------------|
| 0 (root) | 1 | 1024 × 1024 m |
| 1 | 4 | 512 × 512 m |
| 2 | 16 | 256 × 256 m |
| 3 | 64 | 128 × 128 m |
| 4 | 256 | 64 × 64 m |
| 5 (leaf) | 1024 | 32 × 32 m |
| **Total** | **1365** | — |

Each node selects its mesh resolution based on distance from the camera. The transition between
resolutions at node boundaries is where **z-fighting** occurs if the settings are too coarse.

---

## Key CVars

### Terrain LOD

| CVar | Default | Our Value | Effect |
|------|---------|-----------|--------|
| `e_TerrainLodErrorRatio` | `0.05` | `0.001` | Maximum allowed pixel error at LOD transition. Lower = finer mesh near camera. |
| `e_TerrainLodDistanceRatio` | `0.5` | `4.0` | How far out the fine LOD extends. Higher = finer mesh at larger radius. |
| `e_TerrainMeshInstancingMinLod` | `3` | — | Minimum LOD level for mesh instancing. |

### Water (affects z-fighting with terrain)

| CVar | Default | Our Value | Effect |
|------|---------|-----------|--------|
| `e_WaterOcean` | `1` | `0` | Disable ocean surface quad. |
| `e_WaterOceanBottom` | `1` | `0` | Disable ocean bottom fill quad. |

---

## Why Z-Fighting Happens

Z-fighting (flickering between two surfaces) occurs when two triangles are at nearly identical
depth from the camera. The common causes in this project:

1. **Ocean co-planar with terrain** — `OceanWaterLevel = 16` equals flat terrain height → ocean
   surface and terrain triangles at same Z. Fix: move ocean to -100 or disable it.

2. **Terrain LOD seam triangles** — At the boundary between two adjacent LOD sectors, triangles
   from different meshes can be nearly co-planar. Fix: tighten `e_TerrainLodErrorRatio`.

3. **Camera below terrain** — If the player entity sinks slightly into terrain (physics precision),
   the camera sees terrain triangles from below (backface-culled = black) and from above (grey),
   flickering as the entity oscillates. Fix: increase camera height above entity origin.

---

## Applying LOD CVars in Code

Apply after level load so values override the level's defaults:

```cpp
// In GamePlugin.cpp, ESYSTEM_EVENT_LEVEL_LOAD_END:
case ESYSTEM_EVENT_LEVEL_LOAD_END:
{
    gEnv->pConsole->ExecuteString("e_WaterOcean 0",                false, true);
    gEnv->pConsole->ExecuteString("e_WaterOceanBottom 0",          false, true);
    gEnv->pConsole->ExecuteString("e_TerrainLodErrorRatio 0.001",  false, true);
    gEnv->pConsole->ExecuteString("e_TerrainLodDistanceRatio 4.0", false, true);
}
break;
```

> The third argument `true` to `ExecuteString` means "execute silently / suppress logging".

---

## LOD CVars via `system.cfg`

You can also set persistent CVars in `system.cfg` at the project root (applied at engine startup,
before any level loads):

```ini
e_TerrainLodErrorRatio=0.001
e_TerrainLodDistanceRatio=4.0
e_WaterOcean=0
e_WaterOceanBottom=0
```

---

## Sandbox Workflow

In the Sandbox editor you can tune LOD interactively:

1. Open **View → Console** (`~` key).
2. Type a CVar + value, e.g. `e_TerrainLodErrorRatio 0.001`, press Enter.
3. Observe terrain mesh change in real time in the viewport.
4. To make permanent: add to `system.cfg` or write the console command into a level script.

To inspect terrain LOD visually:
- `e_TerrainLodDebug 1` — colours sectors by LOD level (if available in build).
- `r_DisplayInfo 1` — shows poly count and other render stats.

---

## Object / Static Mesh LOD

For non-terrain geometry (brushes, character meshes), LOD is driven by:

| CVar | Default | Effect |
|------|---------|--------|
| `e_LodRatio` | `1.0` | Global LOD distance multiplier. Higher = stay at fine LOD longer. |
| `e_ViewDistRatio` | `75` | View distance multiplier for static objects. |
| `e_ViewDistRatioVegetation` | `75` | Same for vegetation. |

LOD meshes for static objects must be authored in the 3D asset with the naming convention
`_lod1`, `_lod2`, etc., and imported via the Sandbox Asset Browser.
