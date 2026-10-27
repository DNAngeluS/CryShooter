"""Terrain files of a level: stdlib port of the FPS terrain writer, parser and level-size helpers. Byte parity.

Ported from the FPS asset pipeline (tools/asset_pipeline/procgen/terrain_dat_writer.py, terrain_dat_parser.py,
heightmap_writer.py, texture_builder.py make_cover_ctc / build_terraintexture_pak, bundle_builder.py level helpers at
the FPS commit d131636). The FPS formats were reverse-engineered from these engine source files:
  Code/CryEngine/Cry3DEngine/terrain_compile.cpp   (GetCompiledData / Load_T)
  Code/CryEngine/Cry3DEngine/terrain_node_compile.cpp (CTerrainNode::GetData)
  Code/CryEngine/Cry3DEngine/terrain_sector.h      (STerrainNodeChunk, SHeightMapItem)
  Code/CryEngine/CryCommon/Cry3DEngine/I3DEngine.h (STerrainChunkHeader, STerrainInfo)

terrain.dat layout (little-endian, #pragma pack(4)):
  [0..31]   STerrainChunkHeader: int8 nVersion=29, int8 nDummy, int8 nFlags=6, int8 nFlags2, int32 nChunkSize (whole
            file), int32 heightMapSize, float unitSize, int32 sectorSize, int32 sectorsTableSize, float
            heightmapZRatio=1/64, float oceanWaterLevel
  [32..]    SaveTables: int32 vegetation count (0), int32 brush count + that many 256-byte names,
            int32 material count (0). Brushes: see the brush block below.
  [44..]    quadtree node records, preorder DFS, children SW, SE, NW, NE:
            STerrainNodeChunk (44 B): int16 nChunkVersion=8, int16 bHasHoles=0, AABB (6 x float), float fOffset,
            float fRange, int32 nSize (sector + 1 for leaves, 0 otherwise), int32 nSurfaceTypesNum=1;
            leaves: uint32[nSize*nSize] SHeightMapItem = (height_bits << 20), height_m = fOffset + bits * fRange,
            bits in 0..4095, stored x-major (index xi * nSize + yi), clamped at the heightmap edge;
            then align4, nUnitsToSectorBitShift float zeros, one uint8 surface type 0, align4.
  [end]     SOcTreeNodeChunk (32 B): int16 version=5, int16 childMask=0, AABB (6 x float), int32 objectsBlockSize.
            CTerrain::Load_T reads it right after the nodes; files under 4 MiB are rejected without it (FPS
            finding OF-09). Without brushes the object block is empty (objectsBlockSize 0).
  [then]    Object block (brushes only): one 104-byte record per brush, int32 EERType 1 + SBrushChunk (100 B,
            pack 4, layout in BRUSH_CHUNK_FMT). No count; the block size in the octree chunk ends it.
Alignment gaps are filled with 0xDE (CTerrain::LoadDataFromFile_FixAllignemt asserts on it, terrain.h:414).

Heightmap samples are 16 bit; metres = sample * max_height_m / 65535 in float32, as the FPS numpy code computes it.
The FPS writer used numpy float32 arithmetic; this port reproduces that rounding with struct float32 rounding (see
_f32), and the terrain_, heightmap_ and cover_ctc_ lines of tests/parity.sha256 pin the result against the FPS output.

Level files that depend on the heightmap size (level_terrain_files): terrain/terrain.dat, leveldata/heightmap.dat,
leveldata/vegetationmap.dat, terraintexture.pak (terrain/cover.ctc inside), leveldata/terraintexture.xml, and the
navmesh stubs. Size attributes for leveldata.xml, levelinfo.xml, the .level file and mission_mission0.xml come from
level_size_attributes.
Template entries: the FPS level builder overrides only leveldata.xml, levelinfo.xml, mission_mission0.xml and
terrain/terrain.dat (OVERRIDDEN_LEVEL_PAK_ENTRIES, bundle_builder.py:28). Everything else in the template level.pak,
including terrain/cover.ctc and the .bai files, is copied from the template. Checked on the 1024 m template
(fps_forest_basin/level.pak, offsets from the file start): the cover.ctc texture scale is 0.125 (make_cover_ctc writes
1.0); its two layers are 256 px, format 24, 65536 bytes each (make_cover_ctc: 64 px and 32 px, format 2); its tree
holds 21 nodes, the quadtree of the 4x4 tiles that terraintexture.xml lists for 1024 m (make_cover_ctc uses the sector
table: 1365 nodes at 1024 m). So the template cover.ctc is tied to the template size. Not verified: whether the engine
accepts a new-size level with it, whether the stub navmesh files are valid for a new size, and the spawn in the .level
file (needs an engine run).
"""
from __future__ import annotations

import array
import io
import math
import os
import struct
import zipfile
from pathlib import Path

from .cgf_dump import mesh_bounds
from .heightmap import HEIGHTMAP_PREFIX, heightmap_dat_bytes

TERRAIN_CHUNK_VERSION = 29
TERRAIN_NODE_CHUNK_VERSION = 8
SERIAL_FLAGS = 6  # SECTOR_PALETTES(2) | INSTANCES_PRESORTED(4)
MAX_HEIGHT_BITS = 4095
ALIGN_FILL = 0xDE
OCTREE_CHUNK_VERSION = 5
HEIGHTMAP_Z_RATIO = 1.0 / 64.0
DEFAULT_MAX_HEIGHT_M = 1024.0
DEFAULT_OCEAN_WATER_LEVEL = -100.0

HEADER_FMT = "<bbbbiifiiff"
NODE_CHUNK_FMT = "<hh" + "f" * 8 + "ii"
OCTREE_CHUNK_FMT = "<hh6fi"
assert struct.calcsize(HEADER_FMT) == 32
assert struct.calcsize(NODE_CHUNK_FMT) == 44
assert struct.calcsize(OCTREE_CHUNK_FMT) == 32

STAT_INST_GROUP_CHUNK_SIZE = 368  # sizeof(StatInstGroupChunk), terrain.h:92
NAME_CHUNK_SIZE = 256             # sizeof(SNameChunk)

# Brushes (static mesh instances): byte layout from the engine source research of 2026-10-24, section 1.
BRUSH_TABLE_MAX = 4096
EERTYPE_BRUSH = 1                 # IRenderNode.h:35-38
BRUSH_RECORD_SIZE = 104           # int32 EERType + 100-byte SBrushChunk (pack 4)
# SBrushChunk after the base render node chunk, offsets from the chunk start. Written with '<' (no native padding):
# 0 AABB (6 f), 24 layer, 26 shadow bias, 27 dummy, 28 rnd flags (uint64), 36 object type index, 38 view ratio,
# 39 lod ratio, 40 Matrix34f row-major (12 f), 88 collision class, 90 flags, 92 material id, 96 material layers.
BRUSH_CHUNK_FMT = "<6fHbBQHBB12fhHii"
assert struct.calcsize(BRUSH_CHUNK_FMT) == 100
assert struct.calcsize("<i" + BRUSH_CHUNK_FMT[1:]) == BRUSH_RECORD_SIZE
# Defaults for the fields the research leaves open. Sources: BRUSH_LAYER_ID, BRUSH_SHADOW_BIAS, BRUSH_VIEW_RATIO,
# BRUSH_LOD_RATIO are the values of the measured sample record (section 1, V); BRUSH_RND_FLAGS and BRUSH_FLAGS
# are 0 as the research says to write (its sample flag word includes ERF_PENDING_DELETE); BRUSH_COLLISION_CLASS,
# BRUSH_MATERIAL_LAYERS and BRUSH_DUMMY are the sample's 0 (section 1). BRUSH_LAYER_ID = 22 is an open question:
# the minimal example in the research and its layer-0 assumption are U (section 7, item 7).
BRUSH_LAYER_ID = 22
BRUSH_SHADOW_BIAS = 0
BRUSH_DUMMY = 0
BRUSH_RND_FLAGS = 0
BRUSH_VIEW_RATIO = 100
BRUSH_LOD_RATIO = 100
BRUSH_COLLISION_CLASS = 0
BRUSH_FLAGS = 0
BRUSH_MATERIAL_LAYERS = 0
BRUSH_KEYS = frozenset({"cgf", "pos", "rot", "scale", "material_id"})

# Stubs taken from the FPS template level (fps_forest_basin/level.pak). Size independent; the navmesh and cover
# stubs replace the template's navmesh, which belongs to the template's size.
NAVMESH_STUBS = {
    "mnmnavmission0.bai": bytes.fromhex("0e00000000000000000000000000000200000000000000000000000000000000000001"),
    "areasmission0.bai": bytes.fromhex("180000000000000000000000"),
    "covermission0.bai": bytes.fromhex("0200000000000000"),
}
INDOOR_DAT_STUB = bytes.fromhex("0600000014000000000000000000000000000000")  # terrain/indoor.dat, 20 B
# leveldata/vegetationmap.dat of the FPS template (63 B): the same bytes for every size; FPS copies it from the
# template for every level, so this is the neutral "no vegetation" file.
VEGETATIONMAP_EMPTY = bytes.fromhex(
    "3a3c56656765746174696f6e4d61702056657273696f6e3d2233223e0a203c4f626a65637473202f3e0a3c2f56656765746174696f6e4d"
    "61703e0a00000000")
DEFAULT_DIFFUSE_RGBA = (128, 128, 128, 255)  # the FPS fallback for a level without a diffuse texture

_F32 = struct.Struct("<f")


def _f32(x: float) -> float:
    """Round a double to the nearest float32 (what numpy float32 arithmetic stores)."""
    return _F32.unpack(_F32.pack(x))[0]


def heights_to_metres(heights, max_height_m: float) -> array.array:
    """float32 metres from 16 bit samples: float32(sample) * float32(max / 65535), as the FPS numpy code computes it."""
    scale = _f32(max_height_m / 65535.0)
    return array.array("f", [u * scale for u in heights])


def _align4(buf: bytearray) -> None:
    pad = (-len(buf)) & 3
    if pad:
        buf.extend(bytes([ALIGN_FILL]) * pad)


def leaf_quantised(hm, n: int, x0: int, y0: int, leaf: int):
    """The quantised leaf of the sector at (x0, y0): the encoding the writer stores and terrain-sample reads.

    hm[y * n + x] is the float32 metres of sample (x, y) (any indexable works). Samples past the heightmap edge repeat
    the edge, as the writer clamps them. Returns (foff, frange, bits): foff and frange are float32 values (the
    fOffset and fRange the engine reads), bits[xi * (leaf + 1) + yi] are the 12-bit codes, 0..4095, for xi, yi in 0..leaf.
    The height of a code is foff + code * frange."""
    x1c = min(x0 + leaf, n - 1)
    y1c = min(y0 + leaf, n - 1)
    lows, highs = [], []
    for y in range(y0, y1c + 1):
        seg = [hm[y * n + x] for x in range(x0, x1c + 1)]
        lows.append(min(seg))
        highs.append(max(seg))
    z_min, z_max = min(lows), max(highs)
    span = z_max - z_min
    foff = _f32(z_min)
    frange = _f32((1.0 / MAX_HEIGHT_BITS) if span < 1e-6 else (span / MAX_HEIGHT_BITS))
    bits = []
    nsize = leaf + 1
    for xi in range(nsize):
        xs = min(x0 + xi, n - 1)
        for yi in range(nsize):
            ys = min(y0 + yi, n - 1)
            q = _f32(_f32(hm[ys * n + xs] - foff) / frange)
            code = round(q)
            if code < 0:
                code = 0
            elif code > MAX_HEIGHT_BITS:
                code = MAX_HEIGHT_BITS
            bits.append(code)
    return foff, frange, bits


def _write_node(buf: bytearray, hm, n: int, x0: int, y0: int, size: int, leaf: int, unit_m: float, n_shift: int) -> None:
    """One quadtree node and its subtree (preorder). hm is the float32 metres array, index y * n + x."""
    is_leaf = size == leaf
    x1c = min(x0 + size, n - 1)
    y1c = min(y0 + size, n - 1)
    lows, highs = [], []
    for y in range(y0, y1c + 1):
        seg = hm[y * n + x0:y * n + x1c + 1]
        lows.append(min(seg))
        highs.append(max(seg))
    z_min, z_max = min(lows), max(highs)

    if is_leaf:
        nsize = leaf + 1
        foff, frange, bits = leaf_quantised(hm, n, x0, y0, leaf)
    else:
        nsize, foff, frange = 0, 0.0, 0.0

    buf.extend(struct.pack(NODE_CHUNK_FMT, TERRAIN_NODE_CHUNK_VERSION, 0,
                           x0 * unit_m, y0 * unit_m, z_min, (x0 + size) * unit_m, (y0 + size) * unit_m, z_max,
                           foff, frange, nsize, 1))

    if is_leaf:
        items = [b << 20 for b in bits]
        buf.extend(struct.pack("<%dI" % len(items), *items))

    _align4(buf)
    buf.extend(bytes(4 * n_shift))  # nUnitsToSectorBitShift geometry-error floats, all 0.0
    buf.append(0)                   # surface type palette entry 0
    _align4(buf)

    if not is_leaf:
        half = size // 2
        for cx, cy in ((x0, y0), (x0 + half, y0), (x0, y0 + half), (x0 + half, y0 + half)):
            _write_node(buf, hm, n, cx, cy, half, leaf, unit_m, n_shift)


def _number(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def _numbers(value, count: int, what: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f"{what} must be a list of {count} numbers")
    return tuple(_number(x, what) for x in value)


def _brush_cgf_name(name) -> str:
    """A brush table name: ASCII, relative, '/' separated, no empty or '..' part, ends in .cgf, fits char[256]."""
    if not isinstance(name, str) or not name:
        raise ValueError("cgf must be a non-empty string")
    if not name.isascii():
        raise ValueError(f"cgf name {name!r} is not ASCII")
    if len(name) > NAME_CHUNK_SIZE - 1:
        raise ValueError(f"cgf name is {len(name)} bytes, the brush table holds 255 plus NUL")
    if "\\" in name or ":" in name or name.startswith("/"):
        raise ValueError(f"cgf name {name!r} must be a relative path with '/' separators")
    if any(part in ("", "..") for part in name.split("/")):
        raise ValueError(f"cgf name {name!r} has an empty or '..' part")
    if not name.endswith(".cgf"):
        raise ValueError(f"cgf name {name!r} must end in .cgf")
    return name


def normalize_brushes(brushes) -> list:
    """Validate a brush list and fill the defaults. Input items are dicts with keys:
      cgf          str, path of a .cgf relative to the assets directory, e.g. "Objects/snl_3p/box.cgf" (required)
      pos          [x, y, z] world position in metres (required); the matrix translation
      rot          [w, x, y, z] unit quaternion (default identity [1, 0, 0, 0]); must be unit length within 1e-6
      scale        a number or [sx, sy, sz], each > 0 (default 1); column j of the rotation is scaled by sx/sy/sz
      material_id  must be -1 (default): the material table is written empty, so no other index has a target
    Returns a new list of dicts with cgf, pos, rot, scale (3-tuple) and material_id. Raises ValueError with the brush
    index in the message. At most BRUSH_TABLE_MAX brushes; None and [] mean no brushes."""
    if brushes is None:
        return []
    if not isinstance(brushes, list):
        raise ValueError("brushes must be a list of brush objects")
    if len(brushes) > BRUSH_TABLE_MAX:
        raise ValueError(f"at most {BRUSH_TABLE_MAX} brushes, got {len(brushes)}")
    out = []
    for i, b in enumerate(brushes):
        try:
            if not isinstance(b, dict):
                raise ValueError("expected an object")
            extra = sorted(set(b) - BRUSH_KEYS)
            if extra:
                raise ValueError(f"unknown keys {extra}")
            if "cgf" not in b or "pos" not in b:
                raise ValueError("cgf and pos are required")
            cgf_name = _brush_cgf_name(b["cgf"])
            pos = _numbers(b["pos"], 3, "pos")
            rot = _numbers(b.get("rot", [1.0, 0.0, 0.0, 0.0]), 4, "rot")
            if abs(sum(q * q for q in rot) - 1.0) > 1e-6:
                raise ValueError(f"rot {list(rot)} is not a unit quaternion")
            scale = b.get("scale", 1.0)
            scale = (_number(scale, "scale"),) * 3 if not isinstance(scale, (list, tuple)) \
                else _numbers(scale, 3, "scale")
            if any(s <= 0 for s in scale):
                raise ValueError(f"scale {list(scale)} must be > 0 on every axis")
            material_id = b.get("material_id", -1)
            if isinstance(material_id, bool) or not isinstance(material_id, int) or material_id != -1:
                raise ValueError(f"material_id must be -1, got {material_id!r}")
        except ValueError as e:
            raise ValueError(f"brush {i}: {e}") from None
        out.append({"cgf": cgf_name, "pos": pos, "rot": rot, "scale": scale, "material_id": material_id})
    return out


def brush_matrix(pos, rot, scale) -> list:
    """Row-major 3x4 matrix as rows of 4 floats: [R * diag(scale) | pos]. R is the rotation of the unit quaternion
    (w, x, y, z); column j of R is multiplied by scale[j] (composition order not in the research: U)."""
    w, x, y, z = rot
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
         [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
         [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]
    return [[r[i][j] * scale[j] for j in range(3)] + [pos[i]] for i in range(3)]


def transform_box(box_min, box_max, matrix) -> tuple:
    """World AABB of an axis-aligned box after the 3x4 matrix: min and max over its 8 transformed corners."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for cx in (box_min[0], box_max[0]):
        for cy in (box_min[1], box_max[1]):
            for cz in (box_min[2], box_max[2]):
                for i in range(3):
                    v = matrix[i][0] * cx + matrix[i][1] * cy + matrix[i][2] * cz + matrix[i][3]
                    lo[i] = min(lo[i], v)
                    hi[i] = max(hi[i], v)
    return tuple(lo), tuple(hi)


def brush_world_boxes(brushes, assets_dir) -> list:
    """World AABB of each normalized brush: its .cgf vertex bounds (cgf_dump.mesh_bounds) under assets_dir, transformed.
    Each distinct .cgf is read once. Raises ValueError for a missing file or an unreadable .cgf (never a guessed box)."""
    if brushes and assets_dir is None:
        raise ValueError("brushes need assets_dir, the directory their cgf paths are relative to")
    bounds = {}
    boxes = []
    for b in brushes:
        name = b["cgf"]
        if name not in bounds:
            path = os.path.join(assets_dir, *name.split("/"))
            if not os.path.isfile(path):
                raise ValueError(f"brush cgf not found: {name} (under {assets_dir})")
            bounds[name] = mesh_bounds(path)
        lo, hi = bounds[name]
        boxes.append(transform_box(lo, hi, brush_matrix(b["pos"], b["rot"], b["scale"])))
    return boxes


def brush_record(brush, box, type_index: int) -> bytes:
    """One object-block record: int32 EERType 1, then the 100-byte SBrushChunk. box is the stored world AABB."""
    lo, hi = box
    flat = [v for row in brush_matrix(brush["pos"], brush["rot"], brush["scale"]) for v in row]
    body = struct.pack(BRUSH_CHUNK_FMT, *lo, *hi, BRUSH_LAYER_ID, BRUSH_SHADOW_BIAS, BRUSH_DUMMY, BRUSH_RND_FLAGS,
                       type_index, BRUSH_VIEW_RATIO, BRUSH_LOD_RATIO, *flat, BRUSH_COLLISION_CLASS, BRUSH_FLAGS,
                       brush["material_id"], BRUSH_MATERIAL_LAYERS)
    return struct.pack("<i", EERTYPE_BRUSH) + body


def terrain_dat_bytes(heights, size: int, *, unit_size_m: float = 1.0, sector_size_m: int = 32,
                      max_height_m: float = DEFAULT_MAX_HEIGHT_M,
                      ocean_water_level: float = DEFAULT_OCEAN_WATER_LEVEL, brushes=None, assets_dir=None) -> bytes:
    """terrain.dat bytes for an array('H') heightmap of size x size samples (FPS write_terrain_dat).

    brushes: None or a list as normalize_brushes describes. Each distinct cgf becomes one brush table entry, in first-use
    order; the object block is one record per brush in list order, under a single childless root octree chunk. The
    stored AABB is the transformed vertex bounds of the .cgf read from assets_dir (the engine trusts it). With no
    brushes the bytes are those of version 0.3.0. Alignment: the table and record sizes are multiples of 4, so no 0xDE
    gap is written around the brush table or the object block."""
    n = int(size)
    if n <= 0:
        raise ValueError("Heightmap cannot be empty")
    if len(heights) != n * n:
        raise ValueError(f"heightmap must have {n * n} samples for size {n}, got {len(heights)}")
    sector = int(sector_size_m)
    leaf = int(round(sector / unit_size_m))
    if leaf <= 0 or n % leaf != 0:
        raise ValueError(f"Heightmap size {n} is not divisible by sector_size_m/unit_size_m = {leaf}")
    sectors_table = n // leaf
    n_shift = 0
    sec = float(sector)
    while sec > unit_size_m:
        sec /= 2.0
        n_shift += 1

    hm = heights_to_metres(heights, max_height_m)
    brushes = normalize_brushes(brushes)
    boxes = brush_world_boxes(brushes, assets_dir)
    table = list(dict.fromkeys(b["cgf"] for b in brushes))
    index = {name: i for i, name in enumerate(table)}
    node = bytearray(struct.pack("<i", 0))           # vegetation table: no groups
    node.extend(struct.pack("<i", len(table)))       # brush table: one SNameChunk per distinct cgf
    for name in table:
        node.extend(name.encode("ascii").ljust(NAME_CHUNK_SIZE, b"\0"))
    node.extend(struct.pack("<i", 0))                # material table: empty
    _write_node(node, hm, n, 0, 0, n, leaf, unit_size_m, n_shift)
    node.extend(struct.pack(OCTREE_CHUNK_FMT, OCTREE_CHUNK_VERSION, 0, 0.0, 0.0, min(hm), n * unit_size_m,
                            n * unit_size_m, max(hm), len(brushes) * BRUSH_RECORD_SIZE))
    try:
        for brush, box in zip(brushes, boxes):
            node.extend(brush_record(brush, box, index[brush["cgf"]]))
    except OverflowError:
        raise ValueError("a brush value does not fit in a float32") from None
    total = 32 + len(node)
    header = struct.pack(HEADER_FMT, TERRAIN_CHUNK_VERSION, 0, SERIAL_FLAGS, 0, total, n, unit_size_m, sector,
                         sectors_table, HEIGHTMAP_Z_RATIO, ocean_water_level)
    return header + bytes(node)


def write_terrain_dat(path, heights, size: int, **kw) -> None:
    data = terrain_dat_bytes(heights, size, **kw)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class TerrainDatError(ValueError):
    """The file does not parse like the engine reads it; the message names the byte offset."""


def _fail(offset: int, message: str):
    raise TerrainDatError(f"terrain.dat offset {offset}: {message}")


def parse_terrain_dat(data: bytes, *, strict: bool = False) -> dict:
    """Walk `data` the way CTerrain::Load_T does and return {header, tables, nodes, leaves, bad_pad_bytes,
    bad_pad_offsets, root_aabb, nodes_end, octree_chunks, brush_names, brush_records, warnings}. Raises TerrainDatError.
    brush_records: one dict per brush record of the root object block (cgf name, AABB, matrix, fields).
    strict=True: the octree chunk must be version 5 with childMask 0; its object block must be whole 104-byte records
    of EERType 1 that end at EOF; brush type indices and material ids must be in their tables; a non-finite or
    inverted AABB, a 0xDE gap that is not 0xDE, and a wrong nChunkSize are errors. Lenient mode reports the same
    problems in `warnings` and parses what it can. A brush AABB whose x or y lies outside (0,0)-(hm*unit) is a warning in
    both modes. z is not checked: the research leaves the engine root box's z extent U."""
    size = len(data)
    if size < 32:
        _fail(0, f"file is {size} bytes, shorter than the 32-byte header")
    (version, _dummy, flags, flags2, chunk_size, hm_size, unit_m, sector_m, sectors_table, z_ratio,
     ocean) = struct.unpack_from(HEADER_FMT, data, 0)
    if version != TERRAIN_CHUNK_VERSION:
        _fail(0, f"chunk version {version}, expected {TERRAIN_CHUNK_VERSION}")
    if chunk_size != size:
        _fail(4, f"nChunkSize {chunk_size} does not match the file size {size}")
    if unit_m <= 0 or sector_m <= 0 or hm_size <= 0:
        _fail(8, f"bad sizes: heightmap {hm_size}, unit {unit_m}, sector {sector_m}")
    leaf_units = int(round(sector_m / unit_m))
    if leaf_units <= 0 or hm_size % leaf_units:
        _fail(8, f"heightmap size {hm_size} is not a multiple of the sector size {leaf_units} units")
    n_shift = 0
    sec = float(sector_m)
    while sec > unit_m:
        sec /= 2.0
        n_shift += 1

    pos = 32

    def take_int(what: str) -> int:
        nonlocal pos
        if pos + 4 > size:
            _fail(pos, f"truncated while reading {what}")
        (value,) = struct.unpack_from("<i", data, pos)
        pos += 4
        return value

    n_veg = take_int("vegetation count")
    if n_veg != 0:
        _fail(pos - 4, f"{n_veg} vegetation groups ({STAT_INST_GROUP_CHUNK_SIZE} bytes each): not supported by this parser")
    n_brush = take_int("brush count")
    if n_brush < 0 or pos + n_brush * NAME_CHUNK_SIZE > size:
        _fail(pos - 4, f"brush table of {n_brush} entries does not fit")
    brush_names = [data[pos + k * NAME_CHUNK_SIZE:pos + (k + 1) * NAME_CHUNK_SIZE].split(b"\0", 1)[0]
                   .decode("latin-1") for k in range(n_brush)]
    pos += n_brush * NAME_CHUNK_SIZE
    n_mat = take_int("brush material count")
    if n_mat < 0 or pos + n_mat * NAME_CHUNK_SIZE > size:
        _fail(pos - 4, f"material table of {n_mat} entries does not fit")
    pos += n_mat * NAME_CHUNK_SIZE
    tables = {"vegetation": n_veg, "brushes": n_brush, "materials": n_mat, "end": pos}

    counts = {"nodes": 0, "leaves": 0, "pad_bad": 0}
    pad_offsets: list[int] = []
    root_box: list[float] = []

    def align(label: str) -> None:
        nonlocal pos
        while pos & 3:
            if pos >= size:
                _fail(pos, f"truncated in the alignment after {label}")
            if data[pos] != ALIGN_FILL:
                counts["pad_bad"] += 1
                pad_offsets.append(pos)
                if strict:
                    _fail(pos, f"alignment byte after {label} is 0x{data[pos]:02x}, the engine expects 0xDE")
            pos += 1

    def node(node_units: int) -> None:
        nonlocal pos
        if pos + 44 > size:
            _fail(pos, "truncated node record")
        fields = struct.unpack_from(NODE_CHUNK_FMT, data, pos)
        node_version, n_size, n_surf = fields[0], fields[10], fields[11]
        if node_version != TERRAIN_NODE_CHUNK_VERSION:
            _fail(pos, f"node chunk version {node_version}, expected {TERRAIN_NODE_CHUNK_VERSION}")
        if n_size < 0 or n_surf < 0:
            _fail(pos, f"negative sizes in node record (nSize {n_size}, nSurfaceTypesNum {n_surf})")
        if not root_box:
            root_box.extend(fields[2:8])
        pos += 44
        counts["nodes"] += 1
        if n_size:
            need = n_size * n_size * 4
            if pos + need > size:
                _fail(pos, f"truncated heightmap data ({need} bytes)")
            pos += need
            align("heightmap data")
        need = n_shift * 4
        if pos + need > size:
            _fail(pos, "truncated geometry error floats")
        pos += need
        if n_surf:
            if pos + n_surf > size:
                _fail(pos, "truncated surface type palette")
            pos += n_surf
            align("surface types")
        if node_units > leaf_units:
            half = node_units // 2
            for _ in range(4):
                node(half)
        else:
            counts["leaves"] += 1

    node(hm_size)
    nodes_end = pos

    octree = []
    brush_records = []
    warnings: list[str] = []

    def issue(offset: int, message: str) -> None:
        if strict:
            _fail(offset, message)
        warnings.append(f"offset {offset}: {message}")

    terrain_box_max = hm_size * unit_m
    if size - nodes_end < 32:
        issue(nodes_end, "no octree chunk after the node tree")
    else:
        (ver, child_mask, bx0, by0, bz0, bx1, by1, bz1, objects_size) = struct.unpack_from(
            OCTREE_CHUNK_FMT, data, nodes_end)
        octree.append({"version": ver, "child_mask": child_mask, "objects_block_size": objects_size})
        if ver != OCTREE_CHUNK_VERSION:
            issue(nodes_end, f"octree chunk version {ver}, expected {OCTREE_CHUNK_VERSION}")
        if child_mask != 0:
            issue(nodes_end, f"childMask {child_mask}: child octree nodes are not parsed by this tool")
        block = nodes_end + 32
        block_end = block + objects_size
        if objects_size < 0 or block_end > size:
            issue(nodes_end + 28, f"object block of {objects_size} bytes does not fit the {size - block} bytes left")
        elif objects_size % BRUSH_RECORD_SIZE:
            issue(nodes_end + 28, f"object block of {objects_size} bytes is not a whole number of "
                                  f"{BRUSH_RECORD_SIZE}-byte brush records")
        else:
            if block_end != size:
                issue(block_end, f"{size - block_end} bytes follow the object block")
            for k in range(objects_size // BRUSH_RECORD_SIZE):
                off = block + k * BRUSH_RECORD_SIZE
                (eer,) = struct.unpack_from("<i", data, off)
                if eer != EERTYPE_BRUSH:
                    issue(off, f"record {k} has EERType {eer}, only brushes (1) are parsed")
                    break
                f = struct.unpack_from(BRUSH_CHUNK_FMT, data, off + 4)
                rec = {"offset": off, "aabb": tuple(f[0:6]), "layer_id": f[6], "shadow_bias": f[7],
                       "dummy": f[8], "rnd_flags": f[9], "type_index": f[10], "view_ratio": f[11],
                       "lod_ratio": f[12], "matrix": tuple(f[13:25]), "collision": f[25], "flags": f[26],
                       "material_id": f[27], "material_layers": f[28]}
                rec["cgf"] = brush_names[rec["type_index"]] if 0 <= rec["type_index"] < len(brush_names) else None
                lo, hi = rec["aabb"][0:3], rec["aabb"][3:6]
                if not all(math.isfinite(v) for v in rec["aabb"]) or any(a > b for a, b in zip(lo, hi)):
                    issue(off + 4, f"record {k} has a non-finite or inverted AABB")
                if rec["cgf"] is None:
                    issue(off + 4 + 36, f"record {k} object type index {rec['type_index']} is outside the brush "
                                        f"table of {len(brush_names)} entries")
                if rec["material_id"] != -1 and not 0 <= rec["material_id"] < n_mat:
                    issue(off + 4 + 92, f"record {k} material id {rec['material_id']} is outside the material table")
                if any(v < 0.0 or v > terrain_box_max for v in lo[:2] + hi[:2]):
                    warnings.append(f"offset {off}: record {k} AABB lies outside the terrain footprint "
                                    f"(0,0)-({terrain_box_max:g},{terrain_box_max:g}) in x and y; "
                                    "the engine still links it to the root (culling only, unverified)")
                brush_records.append(rec)

    return {
        "header": {"version": version, "flags": flags, "flags2": flags2, "chunk_size": chunk_size,
                   "heightmap_size": hm_size, "unit_m": unit_m, "sector_m": sector_m,
                   "sectors_table": sectors_table, "z_ratio": z_ratio, "ocean": ocean},
        "tables": tables,
        "nodes": counts["nodes"],
        "leaves": counts["leaves"],
        "bad_pad_bytes": counts["pad_bad"],
        "bad_pad_offsets": pad_offsets,
        "root_aabb": tuple(root_box),
        "nodes_end": nodes_end,
        "octree_chunks": octree,
        "brush_names": brush_names,
        "brush_records": brush_records,
        "warnings": warnings,
    }


# ── ground height (terrain-sample) ───────────────────────────────────────────

SECTOR_UNITS = 32  # leaf sector side in units (the sector size of the writer, 32 m at unit 1)


class OnDemandHeights:
    """hm[y * n + x] like heights_to_metres, computed per sample from u_at(x, y) (16 bit codes) and cached. The float32
    metres are the same values terrain_dat_bytes writes; this avoids building the whole heightmap for a few points."""

    def __init__(self, n: int, u_at, max_height_m: float) -> None:
        self.n = n
        self.u_at = u_at
        self.scale = _f32(max_height_m / 65535.0)
        self.cache: dict[int, float] = {}

    def __getitem__(self, index: int) -> float:
        value = self.cache.get(index)
        if value is None:
            y, x = divmod(index, self.n)
            value = _f32(float(self.u_at(x, y)) * self.scale)
            self.cache[index] = value
        return value


def triangulated(v, fx: float, fy: float) -> float:
    """Height inside a unit cell from its 4 corners, as CTerrain::GetHeightTriangulated (terrain_hmap.cpp:29): v is
    (x,y), (x+1,y), (x,y+1), (x+1,y+1); the diagonal runs from (x,y) to (x+1,y+1)."""
    if fx + fy < 1.0:
        return v[0] * (1.0 - fx - fy) + v[1] * fx + v[2] * fy
    return v[3] * (fx + fy - 1.0) + v[2] * (1.0 - fx) + v[1] * (1.0 - fy)


def ground_height(hm, n: int, x: float, y: float, leaf: int = SECTOR_UNITS) -> float:
    """Height at (x, y) metres for a terrain of n x n samples at 1 m units, from the quantised leaves the writer stores.

    Follows CTerrain::GetZApr (terrain_hmap.cpp:133): the unit cell is (int(x), int(y)), its four corners come from the
    leaf sector that owns the lower-left unit (all four, the upper ones included, read from that sector's own codes),
    and the height is triangulated. Points on the far edge (x or y == n) use the last cell. Engine difference: GetZApr
    returns 0 for x or y <= 0 and for points past the edge; this returns the edge height (see the plasmid-assets README)."""
    if not (0.0 <= x <= n and 0.0 <= y <= n):
        raise ValueError(f"point ({x:g}, {y:g}) is outside the terrain [0, {n}]")
    ux = min(int(x), n - 1)
    uy = min(int(y), n - 1)
    x0 = (ux // leaf) * leaf
    y0 = (uy // leaf) * leaf
    foff, frange, bits = leaf_quantised(hm, n, x0, y0, leaf)
    lx, ly = ux - x0, uy - y0
    nsize = leaf + 1
    corners = [foff + bits[i * nsize + j] * frange for i, j in ((lx, ly), (lx + 1, ly), (lx, ly + 1), (lx + 1, ly + 1))]
    return triangulated(corners, x - ux, y - uy)


def _leaf_codes_at(data: bytes, ux: int, uy: int):
    """Walk the node tree of terrain.dat bytes and return (foff, frange, codes) of the leaf sector owning unit (ux, uy),
    read the way CTerrain::Load_T reads them (the 4 byte codes are the top 12 bits of each SHeightMapItem)."""
    if len(data) < 32:
        _fail(0, "shorter than the header")
    (version, _d, _f, _f2, chunk_size, hm_size, unit_m, sector_m, _st, _z, _o) = struct.unpack_from(HEADER_FMT, data, 0)
    if version != TERRAIN_CHUNK_VERSION or chunk_size != len(data) or unit_m != 1.0:
        _fail(0, "not a 1 m terrain.dat this reader understands")
    leaf = int(round(sector_m / unit_m))
    n_shift = 0
    sec = float(sector_m)
    while sec > unit_m:
        sec /= 2.0
        n_shift += 1
    pos = 32
    n_veg = struct.unpack_from("<i", data, pos)[0]
    if n_veg != 0:
        _fail(pos, "vegetation groups: not supported by this reader")
    n_brush = struct.unpack_from("<i", data, pos + 4)[0]
    pos += 8 + n_brush * NAME_CHUNK_SIZE
    n_mat = struct.unpack_from("<i", data, pos)[0]
    pos += 4 + n_mat * NAME_CHUNK_SIZE
    found = []

    def align() -> None:
        nonlocal pos
        pos = (pos + 3) & ~3

    def node(x0: int, y0: int, size: int) -> None:
        nonlocal pos
        fields = struct.unpack_from(NODE_CHUNK_FMT, data, pos)
        foff, frange, n_size, n_surf = fields[8], fields[9], fields[10], fields[11]
        pos += 44
        if n_size:
            count = n_size * n_size
            if size == leaf and x0 <= ux < x0 + size and y0 <= uy < y0 + size:
                raw = struct.unpack_from("<%dI" % count, data, pos)
                found.append((foff, frange, [v >> 20 for v in raw]))
            pos += 4 * count
            align()
        pos += 4 * n_shift
        if n_surf:
            pos += n_surf
            align()
        if size > leaf:
            half = size // 2
            for cx, cy in ((x0, y0), (x0 + half, y0), (x0, y0 + half), (x0 + half, y0 + half)):
                node(cx, cy, half)

    node(0, 0, hm_size)
    if not found:
        _fail(pos, f"no leaf owns unit ({ux}, {uy})")
    return found[0]


def ground_height_from_terrain_dat(data: bytes, x: float, y: float) -> float:
    """The same height as ground_height, read back from terrain.dat bytes (the writer's output) instead of computed
    from the samples. The two paths share only the triangulation, so a difference means the stored leaves differ."""
    size = struct.unpack_from("<i", data, 8)[0]
    if not (0.0 <= x <= size and 0.0 <= y <= size):
        raise ValueError(f"point ({x:g}, {y:g}) is outside the terrain [0, {size}]")
    ux = min(int(x), size - 1)
    uy = min(int(y), size - 1)
    foff, frange, codes = _leaf_codes_at(data, ux, uy)
    x0 = (ux // SECTOR_UNITS) * SECTOR_UNITS
    y0 = (uy // SECTOR_UNITS) * SECTOR_UNITS
    lx, ly = ux - x0, uy - y0
    nsize = SECTOR_UNITS + 1
    corners = [foff + codes[i * nsize + j] * frange for i, j in ((lx, ly), (lx + 1, ly), (lx, ly + 1), (lx + 1, ly + 1))]
    return triangulated(corners, x - ux, y - uy)


# ── terraintexture.pak (terrain/cover.ctc) ───────────────────────────────────

def _resample_rgba(pixels: bytes, width: int, height: int, target_width: int, target_height: int) -> bytes:
    data = bytearray()
    for y in range(target_height):
        source_y = min(height - 1, int(y * height / target_height))
        for x in range(target_width):
            source_x = min(width - 1, int(x * width / target_width))
            offset = (source_y * width + source_x) * 4
            data.extend(pixels[offset:offset + 4])
    return bytes(data)


def _average_rgba(pixels: bytes) -> list[int]:
    samples = len(pixels) // 4
    if samples == 0:
        return [128, 128, 128, 255]
    totals = [0, 0, 0, 0]
    for offset in range(0, len(pixels), 4):
        for index in range(4):
            totals[index] += pixels[offset + index]
    return [int(value / samples) for value in totals]


def make_cover_ctc(diffuse_pixels: bytes, width: int, height: int, sector_table_size: int) -> bytes:
    """terrain/cover.ctc (FPS make_cover_ctc): 64x64 diffuse, 32x32 flat normal layer, one tile per tree node."""
    file_type = 100
    version = 9
    diff_pix = 64
    hmap_pix = 32
    diff_data = _resample_rgba(diffuse_pixels, width, height, diff_pix, diff_pix)
    # Layer 1 encodes terrain surface normals: [128, 128, 0, 0] = neutral flat-surface normal.
    hmap_data = bytes([128, 128, 0, 0]) * (hmap_pix * hmap_pix)
    diff_bytes = len(diff_data)
    hmap_bytes = len(hmap_data)
    depth = 0
    size = sector_table_size
    while size > 1:
        size //= 2
        depth += 1
    tree_nodes = (4 ** (depth + 1) - 1) // 3
    common = b"CRY\x00" + struct.pack("<BBH", file_type, 0, version)
    tex_hdr = struct.pack("<HHf", 2, 0, 1.0)
    layer0 = struct.pack("<HHiI", diff_pix, 0, 2, diff_bytes)
    layer1 = struct.pack("<HHiI", hmap_pix, 0, 2, hmap_bytes)
    index_block = struct.pack("<H", tree_nodes) + b"".join(struct.pack("<h", i) for i in range(tree_nodes))
    one_tile = diff_data + hmap_data
    return common + tex_hdr + layer0 + layer1 + index_block + one_tile * tree_nodes


def terraintexture_pak_bytes(diffuse_pixels: bytes, width: int, height: int, sector_table_size: int) -> bytes:
    """terraintexture.pak: a zip holding terrain/cover.ctc. The member date is fixed (1980-01-01) so the output is
    reproducible; the FPS writer stamps the current time, so only the member content is comparable with FPS."""
    ctc = make_cover_ctc(diffuse_pixels, width, height, sector_table_size)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("terrain/cover.ctc", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        archive.writestr(info, ctc)
    return buf.getvalue()


def solid_pixels(width: int, height: int, rgba) -> bytes:
    return bytes(rgba) * (width * height)


def terraintexture_xml(heightmap_size: int) -> str:
    """leveldata/terraintexture.xml (FPS _terrain_texture_xml): one 512 px tile per 256 units."""
    tile_count = max(1, heightmap_size // 256)
    rows = [f'   <tile X="{x}" Y="{y}" Size="512"/>' for y in range(tile_count) for x in range(tile_count)]
    return "\n".join([
        f'<TerrainTexture TileCountX="{tile_count}" TileCountY="{tile_count}" TileResolution="512">',
        " <RGBLayer>",
        "  <Tiles>",
        *rows,
        "  </Tiles>",
        " </RGBLayer>",
        "</TerrainTexture>",
        "",
    ])


# ── level files ──────────────────────────────────────────────────────────────

def level_editor_size(heightmap_size: int) -> int:
    """HeightmapSize as the editor writes it (FPS _level_editor_size)."""
    return (heightmap_size * 25) // 64


def level_terrain_files(heights, size: int, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M, unit_size_m: float = 1.0,
                        sector_size_m: int = 32, ocean_water_level: float = DEFAULT_OCEAN_WATER_LEVEL,
                        water_level: int = 16, diffuse=None, brushes=None, assets_dir=None) -> dict[str, bytes]:
    """Every file of a level that depends on the heightmap size, keyed by its path inside the level.

    Keys and where they go: terrain/terrain.dat and the three .bai files are members of level.pak (terrain/ and the
    root of the pak). leveldata/heightmap.dat, leveldata/vegetationmap.dat, leveldata/terraintexture.xml and
    terraintexture.pak are level folder files. Values are bytes. The .bai navmesh stubs are included because a
    new-size level cannot use the template's navmesh.
    diffuse: None (a DEFAULT_DIFFUSE_RGBA 64x64 fill, as FPS does without a diffuse texture) or (rgba_bytes, width, height).
    brushes, assets_dir: passed to terrain_dat_bytes (brush list, and the directory its cgf paths are relative to).
    Raises ValueError for a heightmap size that has no heightmap.dat header (FPS supports 512, 1024, 2048)."""
    if size not in HEIGHTMAP_PREFIX:
        raise ValueError(f"No heightmap.dat header for size {size}: supported {sorted(HEIGHTMAP_PREFIX)} (FPS verified "
                         "512 and 1024 against the golden templates)")
    if diffuse is None:
        pixels, width, height = solid_pixels(64, 64, DEFAULT_DIFFUSE_RGBA), 64, 64
    else:
        pixels, width, height = diffuse
    files = {
        "terrain/terrain.dat": terrain_dat_bytes(heights, size, unit_size_m=unit_size_m, sector_size_m=sector_size_m,
                                                 max_height_m=max_height_m, ocean_water_level=ocean_water_level,
                                                 brushes=brushes, assets_dir=assets_dir),
        "leveldata/heightmap.dat": heightmap_dat_bytes(heights, size, max_height_m=max_height_m,
                                                       water_level=water_level),
        "leveldata/vegetationmap.dat": VEGETATIONMAP_EMPTY,
        "terraintexture.pak": terraintexture_pak_bytes(pixels, width, height, size // int(sector_size_m)),
        "leveldata/terraintexture.xml": terraintexture_xml(size).encode("utf-8"),
    }
    files.update(NAVMESH_STUBS)
    return files


def _as_int_if_whole(value):
    """FPS writes these values from ints (1, 1024, -100); render the same text."""
    return int(value) if float(value).is_integer() else value


def level_size_attributes(size: int, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M, unit_size_m: float = 1.0,
                          sector_size_m: int = 32, ocean_water_level: float = DEFAULT_OCEAN_WATER_LEVEL,
                          heightmap_z_ratio: float = HEIGHTMAP_Z_RATIO) -> dict:
    """Attribute values that the size puts into the level's XML files. Render each with str() as FPS does.
    leveldata.xml     <LevelInfo> HeightmapSize, HeightmapUnitSize, HeightmapMaxHeight, WaterLevel, TerrainSectorSizeInMeters
    levelinfo.xml     <LevelInfo> HeightmapSize; <TerrainInfo> HeightmapSize, UnitSize, SectorSize, SectorsTableSize,
                      HeightmapZRatio, OceanWaterLevel
    <level>.level    and mission_mission0.xml  <MiniMap> CenterX, CenterY, ExtendsX, ExtendsY (TexWidth/TexHeight 1024)
    terraintexture.xml  already rendered by level_terrain_files.
    <level>.level  View ViewerPosXY: the x and y of ViewerPos (the centre, 3 decimals). The caller appends ",<z>" with
                   z from the spawn, which the size does not decide.
    The MiniMap values are the centre and extents of the square terrain, as the FPS writer renders them."""
    sector = int(sector_size_m)
    unit, max_h, ocean = _as_int_if_whole(unit_size_m), _as_int_if_whole(max_height_m), _as_int_if_whole(ocean_water_level)
    editor = level_editor_size(size)
    half = size // 2
    minimap = {"CenterX": half, "CenterY": half, "ExtendsX": half, "ExtendsY": half, "TexWidth": 1024, "TexHeight": 1024}
    centre = f"{size / 2:.3f}"
    return {
        "leveldata.xml": {"LevelInfo": {
            "HeightmapSize": editor,
            "HeightmapUnitSize": unit,
            "HeightmapMaxHeight": max_h,
            "WaterLevel": ocean,
            "TerrainSectorSizeInMeters": sector,
        }},
        "levelinfo.xml": {
            "LevelInfo": {"HeightmapSize": editor},
            "TerrainInfo": {
                "HeightmapSize": size,
                "UnitSize": unit,
                "SectorSize": sector,
                "SectorsTableSize": size // sector,
                "HeightmapZRatio": heightmap_z_ratio,
                "OceanWaterLevel": ocean,
            },
        },
        "<level>.level": {"View": {"ViewerPosXY": f"{centre},{centre}"},
                          "Level/Missions/Mission/MiniMap": dict(minimap)},
        "mission_mission0.xml": {"Mission/MiniMap": dict(minimap)},
    }
