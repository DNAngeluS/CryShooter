# CRYENGINE 5.6 — Terrain Textures (`cover.ctc`)

> **Read this when:** Terrain renders solid black, or you are generating `cover.ctc` yourself.
> **Related:** [Terrain](terrain.md) · [Asset pipeline](asset_pipeline.md) · [All docs](README.md)

## Overview

Terrain base colour is stored in `terraintexture.pak` as a single binary file:
`terrain/cover.ctc` (Compiled Terrain Texture Container).

When a level is created in Sandbox but **"Generate Terrain Texture"** is never run,
`terraintexture.pak` is an empty ZIP (22 bytes). The engine cannot initialise its texture
pools, every terrain sector renders **solid black**, and `e_TerrainAutoGenerateBaseTexture 1`
has no effect (no pool = nothing to auto-generate into).

---

## File Location

```
Assets/levels/<name>/terraintexture.pak
                      └── terrain/cover.ctc   ← this file
```

Engine constant (CryCommon):
```cpp
#define COMPILED_TERRAIN_TEXTURE_FILE_NAME "terrain\\cover.ctc"
```

CryPak normalises path separators, so `"terrain/cover.ctc"` works on Linux.

---

## Binary Format

All values are **little-endian**. No padding between fields (natural alignment already satisfied).

### 1 — `SCommonFileHeader` (8 bytes)

| Field | Type | Value |
|-------|------|-------|
| `signature` | `char[4]` | `"CRY\0"` |
| `file_type` | `uint8` | `100` (`eTerrainTextureFile`) |
| `flags` | `uint8` | `0` |
| `version` | `uint16` | `9` (`FILEVERSION_TERRAIN_TEXTURE_FILE`) |

### 2 — `STerrainTextureFileHeader` (8 bytes)

| Field | Type | Notes |
|-------|------|-------|
| `nLayerCount` | `uint16` | `2` (diffuse layer + heightmap layer) |
| `dwFlags` | `uint16` | `0` |
| `fBrMultiplier` | `float` | `1.0` (brightness multiplier inverse) |

### 3 — `STerrainTextureLayerFileHeader` × `nLayerCount` (12 bytes each)

| Field | Type | Notes |
|-------|------|-------|
| `nSectorSizePixels` | `uint16` | Pixels per side per sector tile |
| `nReserved` | `uint16` | `0` |
| `eTexFormat` | `int32` | `2` = `eTF_R8G8B8A8`, `24` = `eTF_BC3` (DXT5) |
| `nSectorSizeBytes` | `uint32` | `nSectorSizePixels² × bytes_per_pixel` |

Common configurations:

| Layer | Purpose | Pixels | Format | Bytes/sector |
|-------|---------|--------|--------|--------------|
| 0 | Diffuse (RGB colour) | 64 | R8G8B8A8 | 16 384 |
| 1 | Heightmap / normals | 32 | R8G8B8A8 | 4 096 |

### 4 — Index Table

```
uint16  wSize            ← total number of quad-tree nodes
int16   entries[wSize]   ← one entry per node, pre-order DFS
                            -1 = no tile (inherits from nearest ancestor with tile)
                            ≥0 = index into tile data array
```

`nDiffTexIndexTableSize` (used for file-seek) = `wSize × 2 + 2`.

### 5 — Tile Data (interleaved per index)

For each unique index `i`, tile data is at:
```
offset = sizeof(SCommonFileHeader)
       + sizeof(STerrainTextureFileHeader)
       + nLayerCount × sizeof(STerrainTextureLayerFileHeader)
       + nDiffTexIndexTableSize
       + i × (layer0.nSectorSizeBytes + layer1.nSectorSizeBytes)
```

Layout at that offset:
```
[layer0 pixel data: nSectorSizeBytes bytes]
[layer1 pixel data: nSectorSizeBytes bytes]
```

---

## Quad-Tree Node Count

For a 32×32 sector terrain (6 levels, root=0, leaf=5):

```
Total nodes = 1 + 4 + 16 + 64 + 256 + 1024 = 1365
```

General formula for `n×n` sector terrain where `n = 2^d`:
```
Total = (4^(d+1) - 1) / 3
```

---

## Generating `cover.ctc` Programmatically (Python)

This script generates a valid `cover.ctc` with every tree node assigned a sandy-brown tile.
Because all tiles are identical solid colour, deflate compression reduces 27 MB → ~36 KB.

```python
import struct, zipfile

# Constants
FILE_TYPE_TERRAIN_TEXTURE = 100   # eTerrainTextureFile
VERSION                   = 9     # FILEVERSION_TERRAIN_TEXTURE_FILE
ETF_R8G8B8A8              = 2

DIFF_PIX   = 64
HMAP_PIX   = 32
DIFF_BYTES = DIFF_PIX * DIFF_PIX * 4
HMAP_BYTES = HMAP_PIX * HMAP_PIX * 4

# Headers
common  = b'CRY\x00' + struct.pack('<BBH', FILE_TYPE_TERRAIN_TEXTURE, 0, VERSION)
tex_hdr = struct.pack('<HHf', 2, 0, 1.0)
layer0  = struct.pack('<HHiI', DIFF_PIX, 0, ETF_R8G8B8A8, DIFF_BYTES)
layer1  = struct.pack('<HHiI', HMAP_PIX, 0, ETF_R8G8B8A8, HMAP_BYTES)

# Index table (1365 nodes, all assigned unique sequential indices)
TREE_NODES  = 1 + 4 + 16 + 64 + 256 + 1024   # = 1365
index_block = struct.pack('<H', TREE_NODES)
for i in range(TREE_NODES):
    index_block += struct.pack('<h', i)

# Tile data: all tiles same sandy-brown colour
DIFF_PIXEL = bytes([140, 120, 90, 255])        # R G B A  (sand/dirt)
HMAP_PIXEL = bytes([128, 128,  0,   0])        # flat heightmap
one_tile   = DIFF_PIXEL * (DIFF_PIX**2) + HMAP_PIXEL * (HMAP_PIX**2)
tile_data  = one_tile * TREE_NODES

ctc = common + tex_hdr + layer0 + layer1 + index_block + tile_data

pak_path = 'Assets/levels/example/terraintexture.pak'
with zipfile.ZipFile(pak_path, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('terrain/cover.ctc', ctc)
```

---

## `e_TerrainAutoGenerateBaseTexture`

```
e_TerrainAutoGenerateBaseTexture 1
```

Generates tile data at runtime from the terrain's painted surface materials instead of reading
from `cover.ctc`. Requires:
1. The texture pools to be initialised (a valid `cover.ctc` must exist and open successfully).
2. Terrain detail materials to be painted onto sectors in Sandbox.

Without condition 1 the CVar has no effect. Without condition 2 it generates black.

> **Warning for generated levels.** Do not enable this CVar on levels produced by the asset
> pipeline. Their terrain layers are never painted in Sandbox, so once a valid `cover.ctc` exists the
> engine lazily overwrites its tiles with auto-generated ones — which are solid black — as each sector
> becomes visible. The symptom is a diagonal wave of black sectors spreading as the player moves,
> which looks like a lighting bug. Leave it at its default (`0`).
>
> Likewise, the heightmap/normal layer (layer 1) of generated tiles must use the neutral pixel
> `[128, 128, 0, 0]`, not an average of the diffuse colour — otherwise the terrain is lit as if tilted.

---

## Sandbox Workflow

1. Paint terrain layers: **Terrain → Edit Layers** → add a layer, assign a material.
2. Paint the layer onto the terrain using the brush tools.
3. **Terrain → Generate Terrain Texture** — bakes all painted layers into `terraintexture.pak`.
4. Save the level.

To rebake after edits: repeat step 3. The Sandbox replaces the pak in place.

---

## Texture Formats (`ETEX_Format` enum values)

| Value | Name | Description |
|-------|------|-------------|
| `0` | `eTF_Unknown` | Invalid |
| `2` | `eTF_R8G8B8A8` | Uncompressed RGBA, 4 bytes/pixel |
| `24` | `eTF_BC3` | DXT5 compressed, ~1 byte/pixel |

BC3 is the preferred format (smaller files, GPU native). Use R8G8B8A8 if GPU does not support BC3
(the engine falls back automatically at runtime).

---

## Material textures are DDS, PNG is only the master (since 2026-10-24)

The engine's material loader has no PNG reader (`Unsupported texture extension 'png'`). Every texture node of the pipeline still writes the PNG master (`Textures/Generated/<bundle>/<name>.png`, used for the terrain base colour and as source) and now also `<name>.dds` beside it, written with the vendored `tools/plasmid-assets` (tag in `tools/plasmid-assets/.vendored-from`): BC1 for opaque images, BC3 with alpha, sRGB (the CRYF header block sets `EIF_SRGBRead`), full mip chain, all mips persistent (without the block a single-file DDS looks blurry under streaming). Materials reference the `.dds`; the validator requires it.

Terrain paint materials (the materials listed in a terrain node's `paint_materials`) are written in the stock terrain LAYER form (`Shader="Terrain.Layer"`, `%TEMP_TERRAIN`), not `Illum`. Normal maps are not generated yet. Imported meshes are a different case: the pipeline only STAGES the OBJ, its Wavefront `.mtl` and the PNGs as input for CRYENGINE's `rc.exe` (Wine, not available on this machine), so no engine `.mtl` or `.cgf` is produced; the Linux route is `Tools/plasmid-assets` (`gltf2cgf`, `cgf-write`, `png2dds`).

