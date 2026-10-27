"""Stdlib writer for compiled static-mesh CRYENGINE .cgf files (CrCh, format 0x746).

Ported from the P0(f) spike (logic unchanged). The command-line wiring lives in cli.py.

Library:
    write_static_mesh(path, positions, normals, uvs, indices, subsets, mtl_name,
                      position_format='f32')

    positions  list of (x, y, z) floats
    normals    list of (x, y, z) floats, one per vertex
    uvs        list of (u, v) floats, one per vertex
    indices    flat list of vertex indices, len % 3 == 0
    subsets    None (one subset over all indices, matID 0) or a list of
               (first_index, num_indices, mat_id) tuples
    mtl_name   material path, e.g. 'Objects/default/editorprimitive' (< 128 bytes)
    position_format  'f32' (POSITIONS element = Vec3 float, 12 bytes)
                     'f16' (POSITIONS element = CryHalf4, 8 bytes, w = 1.0)

Choices that are not confirmed by the golden sample:
  - Tangent element (16 bytes) = tangent int16[4] + binormal int16[4], snorm16, w = handedness
    (both w fields carry the handedness sign). Inferred from the single quad in the golden sample.
  - Mesh nVertAnimID = 0 and geometricMeanFaceArea = 0, as in the golden sample.
  - Node tm[15] = 0, as in the golden sample (the loader ignores it).
  - Subset radius = half-diagonal of the subset AABB, center = AABB center (matches the
    quad and the sphere sample; not proven for other shapes).
  - Mesh texMappingDensity = sum(uv triangle area) / sum(world triangle area).
"""

import math
import struct

# --- chunk types and versions (ChunkTypes) ---
T_SOURCEINFO = 0x1013
T_TIMING = 0x100E
T_EXPORTFLAGS = 0x1015
T_MTLNAME = 0x1014
T_MESHSUBSETS = 0x1017
T_DATASTREAM = 0x1016
T_MESH = 0x1000
T_NODE = 0x100B

# --- stream types (ECgfStreamType) ---
STREAM_POSITIONS = 0
STREAM_NORMALS = 1
STREAM_TEXCOORDS = 2
STREAM_INDICES = 5
STREAM_TANGENTS = 6

# --- chunk ids and versions, as in the golden sample's chunk table ---
ID_SOURCEINFO = 0
ID_TIMING = 2
ID_EXPORTFLAGS = 16
ID_MTLNAME = 17
ID_SUBSETS = 18
ID_STREAM_POSITIONS = 19
ID_STREAM_NORMALS = 20
ID_STREAM_TEXCOORDS = 21
ID_STREAM_INDICES = 22
ID_STREAM_TANGENTS = 23
ID_MESH = 24
ID_NODE = 25

V_SOURCEINFO = 0x0000
V_TIMING = 0x0918
V_EXPORTFLAGS = 0x0001
V_MTLNAME = 0x0802
V_MESHSUBSETS = 0x0800
V_DATASTREAM = 0x0800
V_MESH = 0x0801
V_NODE = 0x0824

MESH_FLAGS_TEXDENSITY = 0x0002  # HAS_TEX_MAPPING_DENSITY, as in the golden sample
ROOT_NODE_NAME = "Merged"
MTL_PHYSICALIZE_TYPE = -1       # golden sample MtlName physicalizeType[0]

ROOT_TM = (1.0, 0.0, 0.0, 0.0,
           0.0, 1.0, 0.0, 0.0,
           0.0, 0.0, 1.0, 0.0,
           0.0, 0.0, 0.0, 0.0)  # index 15 is 0 in the golden sample


# ---------------------------------------------------------------- vector helpers
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _len(a):
    return math.sqrt(_dot(a, a))


def _normalize(a):
    n = _len(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return _scale(a, 1.0 / n)


def _stable_perp(n):
    """Unit vector perpendicular to n, from the world axis least aligned with n."""
    axes = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    a = min(axes, key=lambda ax: abs(_dot(ax, n)))
    return _normalize(_sub(a, _scale(n, _dot(a, n))))


def _snorm16(v):
    v = max(-1.0, min(1.0, v))
    return int(round(v * 32767.0))


# ---------------------------------------------------------------- stream encoders
def _tangent_stream(positions, normals, uvs, indices):
    """16-byte TANGENTS element: tangent int16[4] + binormal int16[4] (snorm, w = handedness)."""
    n = len(positions)
    acc_t = [(0.0, 0.0, 0.0)] * n
    acc_b = [(0.0, 0.0, 0.0)] * n
    for k in range(0, len(indices), 3):
        ia, ib, ic = indices[k], indices[k + 1], indices[k + 2]
        p0, p1, p2 = positions[ia], positions[ib], positions[ic]
        e1 = _sub(p1, p0)
        e2 = _sub(p2, p0)
        du1 = uvs[ib][0] - uvs[ia][0]
        dv1 = uvs[ib][1] - uvs[ia][1]
        du2 = uvs[ic][0] - uvs[ia][0]
        dv2 = uvs[ic][1] - uvs[ia][1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) < 1e-12:
            continue  # degenerate UV triangle contributes nothing
        r = 1.0 / det
        t = _scale(_sub(_scale(e1, dv2), _scale(e2, dv1)), r)
        b = _scale(_sub(_scale(e2, du1), _scale(e1, du2)), r)
        for i in (ia, ib, ic):
            acc_t[i] = _add(acc_t[i], t)
            acc_b[i] = _add(acc_b[i], b)
    out = bytearray()
    for i in range(n):
        nrm = _normalize(normals[i])
        if nrm == (0.0, 0.0, 0.0):
            nrm = (0.0, 0.0, 1.0)
        t = _sub(acc_t[i], _scale(nrm, _dot(acc_t[i], nrm)))  # Gram-Schmidt against N
        if _len(t) < 1e-9:
            t = _stable_perp(nrm)                              # degenerate UVs: stable axis
        t = _normalize(t)
        c = _cross(nrm, t)
        w = -1.0 if _dot(c, acc_b[i]) < 0.0 else 1.0           # handedness
        b = _scale(c, w)
        out += struct.pack("<8h",
                           _snorm16(t[0]), _snorm16(t[1]), _snorm16(t[2]), _snorm16(w),
                           _snorm16(b[0]), _snorm16(b[1]), _snorm16(b[2]), _snorm16(w))
    return bytes(out)


def _pack_half4(p):
    try:
        return struct.pack("<4e", p[0], p[1], p[2], 1.0)
    except OverflowError:
        raise ValueError("position %r is outside the float16 range (+/-65504); "
                         "use position_format='f32'" % (p,))


def _datastream_body(stype, count, esize, payload):
    # STREAM_DATA_CHUNK_DESC_0800: nFlags, nStreamType, nCount, nElementSize, reserved[2]
    return struct.pack("<4i2i", 0, stype, count, esize, 0, 0) + payload


def _subset_entry(first, count, mat, positions, indices):
    # MeshSubset: nFirstIndexId, nNumIndices, nFirstVertId, nNumVerts, nMatID, fRadius, vCenter
    used = sorted(set(indices[first:first + count]))
    lo, hi = used[0], used[-1]
    pts = [positions[i] for i in used]
    bmin = tuple(min(p[k] for p in pts) for k in range(3))
    bmax = tuple(max(p[k] for p in pts) for k in range(3))
    center = _scale(_add(bmin, bmax), 0.5)
    radius = _len(_scale(_sub(bmax, bmin), 0.5))
    return struct.pack("<5if3f", first, count, lo, hi - lo + 1, mat, radius,
                       center[0], center[1], center[2])


def _tex_mapping_density(positions, uvs, indices):
    uv_area = 0.0
    world_area = 0.0
    for k in range(0, len(indices), 3):
        ia, ib, ic = indices[k], indices[k + 1], indices[k + 2]
        e1 = _sub(positions[ib], positions[ia])
        e2 = _sub(positions[ic], positions[ia])
        world_area += 0.5 * _len(_cross(e1, e2))
        du1 = uvs[ib][0] - uvs[ia][0]
        dv1 = uvs[ib][1] - uvs[ia][1]
        du2 = uvs[ic][0] - uvs[ia][0]
        dv2 = uvs[ic][1] - uvs[ia][1]
        uv_area += 0.5 * abs(du1 * dv2 - du2 * dv1)
    return uv_area / world_area if world_area > 0.0 else 0.0


# ---------------------------------------------------------------- container
def build_static_mesh(positions, normals, uvs, indices, subsets, mtl_name,
                      position_format="f32"):
    """Return the complete .cgf file as bytes. No SourceInfo, Timing or ExportFlags chunks are written
    (chunk ids of the rest are unchanged)."""
    if position_format not in ("f32", "f16"):
        raise ValueError("position_format must be 'f32' or 'f16'")
    positions = [tuple(float(c) for c in p) for p in positions]
    normals = [tuple(float(c) for c in n) for n in normals]
    uvs = [tuple(float(c) for c in t) for t in uvs]
    indices = [int(i) for i in indices]
    nv = len(positions)
    if nv == 0:
        raise ValueError("no vertices")
    if len(normals) != nv or len(uvs) != nv:
        raise ValueError("normals and uvs must have one entry per vertex")
    if not indices or len(indices) % 3:
        raise ValueError("indices must be a non-empty multiple of 3")
    if min(indices) < 0 or max(indices) >= nv:
        raise ValueError("index out of range for %d vertices" % nv)
    if len(mtl_name.encode("ascii")) > 127:
        raise ValueError("mtl_name must be < 128 bytes")
    if subsets is None:
        subsets = [(0, len(indices), 0)]
    for first, count, _mat in subsets:
        if count <= 0 or first < 0 or first + count > len(indices):
            raise ValueError("subset (%d, %d) outside index buffer" % (first, count))

    # Mesh bbox and texel density
    bmin = tuple(min(p[k] for p in positions) for k in range(3))
    bmax = tuple(max(p[k] for p in positions) for k in range(3))
    tex_density = _tex_mapping_density(positions, uvs, indices)

    # POSITIONS
    if position_format == "f32":
        pos_esize = 12
        pos_payload = b"".join(struct.pack("<3f", *p) for p in positions)
    else:
        pos_esize = 8
        pos_payload = b"".join(_pack_half4(p) for p in positions)

    # Subsets
    sub_body = struct.pack("<4i", 0, len(subsets), 0, 0)
    for first, count, mat in subsets:
        sub_body += _subset_entry(first, count, mat, positions, indices)

    # Mesh: 264 bytes, format 7i16i4i6f2f31i
    streams = [0] * 16
    streams[STREAM_POSITIONS] = ID_STREAM_POSITIONS
    streams[STREAM_NORMALS] = ID_STREAM_NORMALS
    streams[STREAM_TEXCOORDS] = ID_STREAM_TEXCOORDS
    streams[STREAM_INDICES] = ID_STREAM_INDICES
    streams[STREAM_TANGENTS] = ID_STREAM_TANGENTS
    mesh_body = struct.pack(
        "<7i16i4i6f2f31i",
        MESH_FLAGS_TEXDENSITY, 0, nv, len(indices), len(subsets), ID_SUBSETS, 0,
        *streams,
        0, 0, 0, 0,
        bmin[0], bmin[1], bmin[2], bmax[0], bmax[1], bmax[2],
        tex_density, 0.0,
        *([0] * 31))

    # Node: 204 bytes, format <64s4i4s16f3f4f3f4i
    node_body = struct.pack(
        "<64s4i4s16f3f4f3f4i",
        ROOT_NODE_NAME.encode("ascii"), ID_MESH, -1, 0, ID_MTLNAME,
        b"\0" * 4, *ROOT_TM,
        0.0, 0.0, 0.0,                 # _obsoleteB_ 3f
        0.0, 0.0, 0.0, 0.0,            # _obsoleteC_ 4f
        0.0, 0.0, 0.0,                 # _obsoleteD_ 3f
        0, 0, 0, 0)                    # pos/rot/scl controller ids, PropStrLen

    # MtlName: 128-byte name, nSubMaterials = 0, one physicalizeType
    mtl_body = struct.pack("<128sii", mtl_name.encode("ascii"), 0, MTL_PHYSICALIZE_TYPE)

    chunks = [
        (T_MTLNAME, V_MTLNAME, ID_MTLNAME, mtl_body),
        (T_MESHSUBSETS, V_MESHSUBSETS, ID_SUBSETS, sub_body),
        (T_DATASTREAM, V_DATASTREAM, ID_STREAM_POSITIONS,
         _datastream_body(STREAM_POSITIONS, nv, pos_esize, pos_payload)),
        (T_DATASTREAM, V_DATASTREAM, ID_STREAM_NORMALS,
         _datastream_body(STREAM_NORMALS, nv, 12,
                          b"".join(struct.pack("<3f", *n) for n in normals))),
        (T_DATASTREAM, V_DATASTREAM, ID_STREAM_TEXCOORDS,
         _datastream_body(STREAM_TEXCOORDS, nv, 8,
                          b"".join(struct.pack("<2f", *t) for t in uvs))),
        (T_DATASTREAM, V_DATASTREAM, ID_STREAM_INDICES,
         _datastream_body(STREAM_INDICES, len(indices), 4,
                          struct.pack("<%dI" % len(indices), *indices))),
        (T_DATASTREAM, V_DATASTREAM, ID_STREAM_TANGENTS,
         _datastream_body(STREAM_TANGENTS, nv, 16,
                          _tangent_stream(positions, normals, uvs, indices))),
        (T_MESH, V_MESH, ID_MESH, mesh_body),
        (T_NODE, V_NODE, ID_NODE, node_body),
    ]

    # File: 16-byte header, then the 16-byte-per-entry table, then the bodies back to back
    # (no padding in the golden sample: first body at 0xD0 = 16 + 12 * 16).
    table_off = 16
    offset = table_off + 16 * len(chunks)
    table = bytearray()
    data = bytearray()
    for ctype, cver, cid, body in chunks:
        # ChunkTableEntry_0x746: type H, version H, id I, size I, offsetInFile I
        table += struct.pack("<HHIII", ctype, cver, cid, len(body), offset)
        data += body
        offset += len(body)
    header = struct.pack("<4sIII", b"CrCh", 0x746, len(chunks), table_off)
    return bytes(header) + bytes(table) + bytes(data)


def write_static_mesh(path, positions, normals, uvs, indices, subsets, mtl_name,
                      position_format="f32"):
    """Write a static-mesh .cgf. Returns the number of bytes written."""
    blob = build_static_mesh(positions, normals, uvs, indices, subsets, mtl_name,
                             position_format)
    with open(path, "wb") as f:
        f.write(blob)
    return len(blob)


# ---------------------------------------------------------------- presets
MTL_EDITORPRIMITIVE = "Objects/default/editorprimitive"


def box10_mesh(size=10.0):
    """Axis-aligned box centred on X/Y = 0, base on z = 0. 24 verts, 36 indices, per-face normals."""
    h = size / 2.0
    z0, z1 = 0.0, size
    faces = [
        ((1.0, 0.0, 0.0), [(h, -h, z0), (h, h, z0), (h, h, z1), (h, -h, z1)]),
        ((-1.0, 0.0, 0.0), [(-h, h, z0), (-h, -h, z0), (-h, -h, z1), (-h, h, z1)]),
        ((0.0, 1.0, 0.0), [(h, h, z0), (-h, h, z0), (-h, h, z1), (h, h, z1)]),
        ((0.0, -1.0, 0.0), [(-h, -h, z0), (h, -h, z0), (h, -h, z1), (-h, -h, z1)]),
        ((0.0, 0.0, 1.0), [(-h, -h, z1), (h, -h, z1), (h, h, z1), (-h, h, z1)]),
        ((0.0, 0.0, -1.0), [(-h, -h, z0), (-h, h, z0), (h, h, z0), (h, -h, z0)]),
    ]
    face_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    positions, normals, uvs, indices = [], [], [], []
    for f, (normal, corners) in enumerate(faces):
        base = 4 * f
        for corner, uv in zip(corners, face_uv):
            positions.append(corner)
            normals.append(normal)
            uvs.append(uv)
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return positions, normals, uvs, indices


def triangle_mesh():
    """One CCW triangle in the XY plane at z = 0, normal +Z."""
    positions = [(-5.0, -5.0, 0.0), (5.0, -5.0, 0.0), (0.0, 5.0, 0.0)]
    normals = [(0.0, 0.0, 1.0)] * 3
    uvs = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    return positions, normals, uvs, [0, 1, 2]


PRESETS = {"box10": box10_mesh, "tri": triangle_mesh}
