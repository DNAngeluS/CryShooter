"""terrain_dat_writer.py — Generate CRYENGINE 5.6 terrain.dat without Sandbox.

Binary format reverse-engineered from:
  Code/CryEngine/Cry3DEngine/terrain_compile.cpp   (GetCompiledData / Load_T)
  Code/CryEngine/Cry3DEngine/terrain_node_compile.cpp (CTerrainNode::GetData)
  Code/CryEngine/Cry3DEngine/terrain_sector.h      (STerrainNodeChunk, SHeightMapItem)
  Code/CryEngine/CryCommon/Cry3DEngine/I3DEngine.h (STerrainChunkHeader, STerrainInfo)

File layout:
  [0..31]   STerrainChunkHeader  (32 bytes, little-endian, #pragma pack(4))
  [32..43]  SaveTables: 3 × int32(0) — empty vegetation/brush/material tables
  [44..]    Quadtree node records, preorder DFS

Each node record:
  STerrainNodeChunk (44 bytes):
    int16 nChunkVersion = TERRAIN_NODE_CHUNK_VERSION (8)
    int16 bHasHoles = 0
    AABB  boxHeightmap (6 × float32: minX, minY, minZ, maxX, maxY, maxZ)
    float fOffset
    float fRange
    int32 nSize         (leaf_size_units+1 for leaves, 0 for internal nodes)
    int32 nSurfaceTypesNum (1 for all nodes)
  uint32[nSize × nSize]  SHeightMapItem data  (only written when nSize > 0)
      item = (height_bits << 20)  where height_bits in [0, 4095]
      height_meters = fOffset + float(height_bits) * fRange
  [align to 4 bytes]
  float32[nUnitsToSectorBitShift]  geometry error (all 0)
  uint8[1]   surface type palette entry (0 = first registered surface type)
  [align to 4 bytes]
  4 children recursively (children present only for non-leaf nodes)
  [after the last node]
  SOcTreeNodeChunk (32 bytes): int16 version = 5, int16 childMask = 0, AABB (6 × float32), int32 objectsBlockSize = 0
    An empty object tree. CTerrain::Load_T reads it right after the nodes (COctreeNode::Load); without it files under
    4 MiB (in-memory load path) are rejected with `nDataSize == 0`, larger ones only load because the short read of the
    FILE path is not an error (OF-09, SandboxLLM 2026-10-21).
  STerrainChunkHeader.nChunkSize counts the whole file (header, tables, nodes, octree chunk).
  Alignment gaps are filled with 0xDE (222): CTerrain::LoadDataFromFile_FixAllignemt asserts on it (terrain.h:414).

Child ordering for node covering (x0,y0)-(x1,y1):
  child[0] = (x0,     y0)     – SW
  child[1] = (x0+half,y0)     – SE
  child[2] = (x0,     y0+half)– NW
  child[3] = (x0+half,y0+half)– NE
  where half = (x1-x0)/2 in heightmap units
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import numpy as np

# ── Constants ────────────────────────────────────────────────────────────────
TERRAIN_CHUNK_VERSION = 29       # STerrainChunkHeader.nVersion
TERRAIN_NODE_CHUNK_VERSION = 8   # STerrainNodeChunk.nChunkVersion
_SERIAL_FLAGS = 6                # SECTOR_PALETTES(2) | INSTANCES_PRESORTED(4)
_MAX_HEIGHT_BITS = 4095          # 12-bit height (2^12 - 1)
ALIGN_FILL = 0xDE                # byte the engine expects in alignment gaps (assert(*f == 222))
OCTREE_CHUNK_VERSION = 5         # SOcTreeNodeChunk.nChunkVersion

# STerrainChunkHeader: 4×int8 + int32 + 6×(int or float) = 32 bytes
_HEADER_FMT = "<bbbbiifiiff"
assert struct.calcsize(_HEADER_FMT) == 32

# SOcTreeNodeChunk: int16 version, int16 childMask, AABB (6 × float), int32 objectsBlockSize = 32 bytes
OCTREE_CHUNK_FMT = "<hh6fi"
assert struct.calcsize(OCTREE_CHUNK_FMT) == 32

# STerrainNodeChunk: int16+int16 + 6×float + float+float + int32+int32 = 44 bytes
_NODE_CHUNK_FMT = "<hh" + "f" * 8 + "ii"
assert struct.calcsize(_NODE_CHUNK_FMT) == 44


# ── Internal helpers ─────────────────────────────────────────────────────────

def _align4(buf: io.BytesIO) -> None:
    pos = buf.tell()
    pad = (-pos) & 3  # equivalent to (4 - pos % 4) % 4
    if pad:
        buf.write(bytes([ALIGN_FILL]) * pad)


def _write_node(
    buf: io.BytesIO,
    heights_m: np.ndarray,
    x0: int,
    y0: int,
    size_units: int,
    leaf_size_units: int,
    unit_m: float,
    n_shift: int,
) -> None:
    """Write one terrain quadtree node and its 4-child subtree (preorder DFS).

    Parameters
    ----------
    buf           : output buffer
    heights_m     : float32 array shape (N, N), indexed [row=y, col=x], meters
    x0, y0        : origin of this node in heightmap units
    size_units    : side length of this node in heightmap units
    leaf_size_units: side length of leaf nodes (= sector_size_m / unit_size_m)
    unit_m        : metres per heightmap unit
    n_shift       : nUnitsToSectorBitShift (number of geom-error floats per node)
    """
    is_leaf = size_units == leaf_size_units
    n_rows, n_cols = heights_m.shape

    # AABB in world-space metres
    x0_m = x0 * unit_m
    y0_m = y0 * unit_m
    x1_m = (x0 + size_units) * unit_m
    y1_m = (y0 + size_units) * unit_m

    # Height bounds — clamp indices to valid heightmap range
    x1c = min(x0 + size_units, n_cols - 1)
    y1c = min(y0 + size_units, n_rows - 1)
    region = heights_m[y0 : y1c + 1, x0 : x1c + 1]
    z_min = float(region.min())
    z_max = float(region.max())

    if is_leaf:
        nSize = leaf_size_units + 1  # e.g. 33 for 32-unit sectors
        if z_max - z_min < 1e-6:
            fOffset = z_min
            fRange = 1.0 / _MAX_HEIGHT_BITS
        else:
            fOffset = z_min
            fRange = (z_max - z_min) / _MAX_HEIGHT_BITS
    else:
        nSize = 0
        fOffset = 0.0
        fRange = 0.0

    # ── STerrainNodeChunk ─────────────────────────────────────────────────────
    buf.write(struct.pack(
        _NODE_CHUNK_FMT,
        TERRAIN_NODE_CHUNK_VERSION, 0,          # nChunkVersion, bHasHoles
        x0_m, y0_m, z_min, x1_m, y1_m, z_max,  # AABB min/max
        fOffset, fRange, nSize, 1,               # fOffset, fRange, nSize, nSurfaceTypesNum
    ))

    # ── Heightmap data (leaves only) ──────────────────────────────────────────
    if is_leaf:
        # Build nSize×nSize uint32 array in x-major order (data[xi * nSize + yi]).
        # heights_m is indexed [y, x], so we need to transpose.
        xs = np.arange(x0, x0 + nSize, dtype=np.int32).clip(0, n_cols - 1)
        ys = np.arange(y0, y0 + nSize, dtype=np.int32).clip(0, n_rows - 1)

        # region_xy shape (nSize_x, nSize_y) = (nSize, nSize)
        region_xy = heights_m[np.ix_(ys, xs)].T  # [xi, yi]

        h_bits = np.clip(
            np.round((region_xy - fOffset) / fRange),
            0, _MAX_HEIGHT_BITS,
        ).astype(np.uint32)
        items = (h_bits << 20).astype("<u4")  # SHeightMapItem: height in bits 20-31
        buf.write(items.tobytes())

    # ── Alignment → geometry error → surface type palette → alignment ─────────
    _align4(buf)
    buf.write(struct.pack(f"<{n_shift}f", *([0.0] * n_shift)))  # geom error (all 0)
    buf.write(struct.pack("<B", 0))                              # surface type ID 0
    _align4(buf)

    # ── Recurse into 4 children (non-leaf only) ───────────────────────────────
    if not is_leaf:
        half = size_units // 2
        for cx, cy in (
            (x0,        y0),
            (x0 + half, y0),
            (x0,        y0 + half),
            (x0 + half, y0 + half),
        ):
            _write_node(buf, heights_m, cx, cy, half, leaf_size_units, unit_m, n_shift)


def octree_chunk_bytes(size_m: float, z_min: float, z_max: float) -> bytes:
    """The empty object-tree chunk that must follow the node tree: version 5, no children, no objects, whole-terrain AABB."""
    return struct.pack(OCTREE_CHUNK_FMT, OCTREE_CHUNK_VERSION, 0, 0.0, 0.0, z_min, size_m, size_m, z_max, 0)


# ── Public API ────────────────────────────────────────────────────────────────

def write_terrain_dat(
    path: Path,
    heights_uint16: np.ndarray,
    *,
    unit_size_m: float = 1.0,
    sector_size_m: int = 32,
    max_height_m: float = 1024.0,
    ocean_water_level: float = -100.0,
) -> None:
    """Write a CRYENGINE 5.6 terrain.dat from a uint16 heightmap — no Sandbox needed.

    Parameters
    ----------
    path           : destination path
    heights_uint16 : shape (N, N) uint16 array where
                     height_metres = value * max_height_m / 65535
    unit_size_m    : metres per heightmap unit (default 1.0)
    sector_size_m  : sector side length in metres (default 32)
    max_height_m   : maximum terrain height in metres (default 1024.0)
    ocean_water_level : ocean Z level in metres (default -100, i.e. below terrain)
    """
    n = heights_uint16.shape[0]
    if heights_uint16.shape != (n, n):
        raise ValueError(f"Heightmap must be square, got {heights_uint16.shape}")
    if n == 0:
        raise ValueError("Heightmap cannot be empty")

    leaf_size_units = int(round(sector_size_m / unit_size_m))
    if n % leaf_size_units != 0:
        raise ValueError(
            f"Heightmap size {n} is not divisible by "
            f"sector_size_m/unit_size_m = {leaf_size_units}"
        )

    sectors_table = n // leaf_size_units
    heightmap_z_ratio = 1.0 / 64.0  # matches golden templates

    # nUnitsToSectorBitShift = number of geom-error floats per node
    n_shift = 0
    sec_f = float(sector_size_m)
    while sec_f > unit_size_m:
        sec_f /= 2.0
        n_shift += 1

    # Convert uint16 → float32 metres
    heights_m = heights_uint16.astype(np.float32) * (max_height_m / 65535.0)

    # ── Build node payload ────────────────────────────────────────────────────
    node_buf = io.BytesIO()

    # Empty SaveTables: vegetation count=0, brush count=0, material count=0
    node_buf.write(struct.pack("<iii", 0, 0, 0))

    # Quadtree starting from the root (covers the whole terrain)
    _write_node(node_buf, heights_m, 0, 0, n, leaf_size_units, unit_size_m, n_shift)

    # Empty object tree after the nodes (see the module docstring)
    node_buf.write(octree_chunk_bytes(n * unit_size_m, float(heights_m.min()), float(heights_m.max())))

    node_data = node_buf.getvalue()

    # ── STerrainChunkHeader ───────────────────────────────────────────────────
    total_size = 32 + len(node_data)
    header = struct.pack(
        _HEADER_FMT,
        TERRAIN_CHUNK_VERSION,   # int8 nVersion
        0,                       # int8 nDummy
        _SERIAL_FLAGS,           # int8 nFlags (SECTOR_PALETTES | INSTANCES_PRESORTED)
        0,                       # int8 nFlags2
        total_size,              # int32 nChunkSize (= full file size)
        n,                       # int32 heightMapSize_InUnits
        unit_size_m,             # float unitSize_InMeters
        sector_size_m,           # int32 sectorSize_InMeters
        sectors_table,           # int32 sectorsTableSize_InSectors
        heightmap_z_ratio,       # float heightmapZRatio
        ocean_water_level,       # float oceanWaterLevel
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(header)
        fh.write(node_data)
