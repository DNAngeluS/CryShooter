"""terrain_dat_parser.py — read a CRYENGINE 5.6 terrain.dat the way CTerrain::Load_T does.

Used by the validator and by `fix-terrain` to check generated files and to find where the node tree ends. The walk follows
Code/CryEngine/Cry3DEngine/terrain_compile.cpp (tables, nodes, object tree) and terrain_node_compile.cpp (node record).

  header (32) | vegetation table | brush table | brush-material table | node tree | object tree (COctreeNode)

Tables (variable length): int32 n + n × StatInstGroupChunk (368 B, vegetation), int32 n + n × SNameChunk (256 B, brushes),
int32 n + n × SNameChunk (materials). Only an empty vegetation table is supported (the pipeline never writes one; Sandbox's
own files used to check the parser have 0 vegetation groups); anything else raises TerrainDatError.

The node tree is complete when the walk of the quadtree (root = whole heightmap, children while size > sector size) ends;
what follows is the object tree. `strict=True` is for files this pipeline wrote: it additionally requires exactly one
32-byte empty octree chunk (version 5, objectsBlockSize 0) ending at EOF and 0xDE in every alignment gap.
"""
from __future__ import annotations

import struct

from .terrain_dat_writer import (
    ALIGN_FILL,
    OCTREE_CHUNK_FMT,
    OCTREE_CHUNK_VERSION,
    TERRAIN_CHUNK_VERSION,
    TERRAIN_NODE_CHUNK_VERSION,
    _HEADER_FMT,
    _NODE_CHUNK_FMT,
)

STAT_INST_GROUP_CHUNK_SIZE = 368  # sizeof(StatInstGroupChunk), terrain.h:92 (only used to name the unsupported case)
NAME_CHUNK_SIZE = 256             # sizeof(SNameChunk)


class TerrainDatError(ValueError):
    """The file does not parse like the engine reads it; the message names the byte offset."""


def _fail(offset: int, message: str):
    raise TerrainDatError(f"terrain.dat offset {offset}: {message}")


def parse_terrain_dat(data: bytes, *, strict: bool = False) -> dict:
    """Walk `data` and return {header, tables, nodes, leaves, nodes_end, octree_chunks}. Raises TerrainDatError."""
    size = len(data)
    if size < 32:
        _fail(0, f"file is {size} bytes, shorter than the 32-byte header")
    (version, _dummy, flags, flags2, chunk_size, hm_size, unit_m, sector_m, sectors_table, z_ratio, ocean) = struct.unpack_from(
        _HEADER_FMT, data, 0)
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
        fields = struct.unpack_from(_NODE_CHUNK_FMT, data, pos)
        node_version, _holes = fields[0], fields[1]
        n_size, n_surf = fields[10], fields[11]
        if node_version != TERRAIN_NODE_CHUNK_VERSION:
            _fail(pos, f"node chunk version {node_version}, expected {TERRAIN_NODE_CHUNK_VERSION}")
        if n_size < 0 or n_surf < 0:
            _fail(pos, f"negative sizes in node record (nSize {n_size}, nSurfaceTypesNum {n_surf})")
        if not root_box:
            root_box.extend(fields[2:8])  # AABB of the root node: minX, minY, minZ, maxX, maxY, maxZ
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
    if strict:
        if size - nodes_end != 32:
            _fail(nodes_end, f"expected exactly one 32-byte octree chunk after the nodes, found {size - nodes_end} bytes")
    if size - nodes_end >= 32:
        (ver, child_mask, *_aabb, objects_size) = struct.unpack_from(OCTREE_CHUNK_FMT, data, nodes_end)
        octree.append({"version": ver, "child_mask": child_mask, "objects_block_size": objects_size})
        if strict and (ver != OCTREE_CHUNK_VERSION or child_mask != 0 or objects_size != 0):
            _fail(nodes_end, f"octree chunk is not the empty chunk (version {ver}, childMask {child_mask}, objects {objects_size})")
    elif strict:
        _fail(nodes_end, "no octree chunk after the node tree")

    return {
        "header": {"version": version, "flags": flags, "flags2": flags2, "chunk_size": chunk_size, "heightmap_size": hm_size,
                   "unit_m": unit_m, "sector_m": sector_m, "sectors_table": sectors_table, "z_ratio": z_ratio, "ocean": ocean},
        "tables": tables,
        "nodes": counts["nodes"],
        "leaves": counts["leaves"],
        "bad_pad_bytes": counts["pad_bad"],
        "bad_pad_offsets": pad_offsets,
        "root_aabb": tuple(root_box),
        "nodes_end": nodes_end,
        "octree_chunks": octree,
    }
