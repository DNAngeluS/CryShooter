"""Read-only dumper for CRYENGINE .cgf chunk files (ported from the P0(f) spike; logic unchanged).

dump(path) prints the file header, the chunk table and the decoded fields of the chunks that have a
decoder, and returns True only if every check passes. The input is opened 'rb' and never written.
Stdlib only.
"""

import math
import struct

# ChunkTypes enum: CryCommon/Cry3DEngine/CGF/CryHeaders.h:16-68
CHUNK_NAMES = {
    0x0000: "ANY",
    0x1000: "Mesh", 0x1001: "Helper", 0x1002: "VertAnim", 0x1003: "BoneAnim",
    0x1004: "GeomNameList", 0x1005: "BoneNameList", 0x1006: "MtlList", 0x1007: "MRM",
    0x1008: "SceneProps", 0x1009: "Light", 0x100A: "PatchMesh", 0x100B: "Node",
    0x100C: "Mtl", 0x100D: "Controller", 0x100E: "Timing", 0x100F: "BoneMesh",
    0x1010: "BoneLightBinding", 0x1011: "MeshMorphTarget", 0x1012: "BoneInitialPos",
    0x1013: "SourceInfo", 0x1014: "MtlName", 0x1015: "ExportFlags", 0x1016: "DataStream",
    0x1017: "MeshSubsets", 0x1018: "MeshPhysicsData", 0x1019: "ImportSettings",
    0x101A: "VCloth", 0x101B: "AssetMetadata",
    0x2000: "CompiledBones", 0x2001: "CompiledPhysicalBones", 0x2002: "CompiledMorphTargets",
    0x2003: "CompiledPhysicalProxies", 0x2004: "CompiledIntFaces",
    0x2005: "CompiledIntSkinVertices", 0x2006: "CompiledExt2IntMap",
    0x3000: "BreakablePhysics", 0x3001: "FaceMap", 0x3002: "MotionParameters",
    0x3003: "FootPlantInfo", 0x3004: "BonesBoxes", 0x3005: "FoliageInfo",
    0x3006: "Timestamp", 0x3007: "GlobalAnimationHeaderCAF",
    0x3008: "GlobalAnimationHeaderAIM", 0x3009: "BspTreeData",
}

# ECgfStreamType enum: CryCommon/Cry3DEngine/CGF/CryHeaders.h:70-88 (index = value)
STREAM_NAMES = [
    "POSITIONS", "NORMALS", "TEXCOORDS", "COLORS", "COLORS2", "INDICES", "TANGENTS",
    "DUMMY0_", "DUMMY1_", "BONEMAPPING", "FACEMAP", "VERT_MATS", "QTANGENTS",
    "SKINDATA", "DUMMY2_", "P3S_C4B_T2S",
]

T_MESH = 0x1000
T_NODE = 0x100B
T_CONTROLLER = 0x100D
T_MTLNAME = 0x1014
T_DATASTREAM = 0x1016
T_MESHSUBSETS = 0x1017
T_MESHPHYSICSDATA = 0x1018

MESH_FLAGS = [(0x0001, "MESH_IS_EMPTY"), (0x0002, "HAS_TEX_MAPPING_DENSITY"),
              (0x0004, "HAS_EXTRA_WEIGHTS"), (0x0008, "HAS_FACE_AREA")]
SUBSET_FLAGS = [(0x0001, "SH_HAS_DECOMPR_MAT"), (0x0002, "BONEINDICES"),
                (0x0004, "HAS_SUBSET_TEXEL_DENSITY")]


class Chunk(object):
    def __init__(self, index, ctype, version, be, cid, offset, size):
        self.index = index
        self.ctype = ctype      # 0x746 numbering
        self.version = version  # with the big-endian flag stripped
        self.be = be            # chunk body is big-endian
        self.cid = cid
        self.offset = offset
        self.size = size


def cname(ctype):
    return CHUNK_NAMES.get(ctype, "unknown")


def convert_type_to_0x746(t):
    # ConvertChunkTypeTo0x746: ChunkFileComponents.h:174-204
    if t <= 0xFFFF:
        return t
    if (t & 0xFFFF) >= 0xF000:
        return 0
    hi = t & 0xFFFF0000
    if hi == 0xCCCC0000:
        return 0x1000 + (t & 0x0FFF)
    if hi == 0xACDC0000:
        return 0x2000 + (t & 0x0FFF)
    if hi == 0xAAFC0000:
        return 0x3000 + (t & 0x0FFF)
    return 0


def parse_container(data):
    """Return (header_dict, [Chunk]). Raises ValueError on a bad file."""
    if len(data) >= 16 and data[0:4] == b"CrCh":
        # FileHeader_0x746, ChunkFileComponents.h:59-90; little-endian.
        version, count, table_off = struct.unpack_from("<III", data, 4)
        if version != 0x746:
            raise ValueError("CrCh header with version 0x%x, expected 0x746" % version)
        if count > 10000000:
            raise ValueError("chunk count %d out of range" % count)
        if table_off + 16 * count > len(data):
            raise ValueError("chunk table extends past end of file")
        hdr = {"sig": "CrCh", "version": version, "fileType": None, "count": count,
               "table_offset": table_off, "header_size": 16,
               "table_len": 16 * count, "format": "0x746"}
        chunks = []
        for i in range(count):
            # ChunkTableEntry_0x746, ChunkFileComponents.h:131-149
            t, v, cid, size, off = struct.unpack_from("<HHIII", data, table_off + 16 * i)
            chunks.append(Chunk(i, t, v & 0x7FFF, bool(v & 0x8000), cid, off, size))
        return hdr, chunks

    if len(data) >= 20 and data[0:7] == b"CryTek\x00":
        # FileHeader_0x744_0x745, ChunkFileComponents.h:14-57
        ftype, version, table_off = struct.unpack_from("<III", data, 8)
        if version not in (0x744, 0x745):
            raise ValueError("CryTek header with version 0x%x" % version)
        if table_off + 4 > len(data):
            raise ValueError("chunk table offset past end of file")
        count = struct.unpack_from("<I", data, table_off)[0]
        if count > 1000000:
            raise ValueError("chunk count %d out of range" % count)
        entry = 16 if version == 0x744 else 20
        if table_off + 4 + entry * count > len(data):
            raise ValueError("chunk table extends past end of file")
        hdr = {"sig": "CryTek", "version": version, "fileType": ftype, "count": count,
               "table_offset": table_off, "header_size": 20,
               "table_len": 4 + entry * count, "format": "0x%x" % version}
        raw = []
        for i in range(count):
            base = table_off + 4 + entry * i
            vals = struct.unpack_from("<IIII", data, base)  # type, version, offsetInFile, id
            size = struct.unpack_from("<I", data, base + 16)[0] if version == 0x745 else None
            raw.append((vals, size))
        # 0x744 has no size field: derive from the next chunk's offset (ChunkFileReaders.cpp:325-339)
        end_of_data = len(data)
        if raw:
            min_off = min(r[0][2] for r in raw)
            if table_off >= min_off:
                end_of_data = table_off
        chunks = []
        for i, (vals, size) in enumerate(raw):
            t32, v32, off, cid = vals
            if size is None:
                offs = sorted(r[0][2] for r in raw)
                pos = offs.index(off)
                nxt = offs[pos + 1] if pos + 1 < len(offs) else end_of_data
                size = nxt - off
            ctype = convert_type_to_0x746(t32)
            be = bool(v32 & 0x80000000)
            chunks.append(Chunk(i, ctype, v32 & 0x7FFFFFFF, be, cid, off, size))
        return hdr, chunks

    raise ValueError("unknown signature (not 'CrCh' or 'CryTek')")


def cstr(b):
    return b.split(b"\0", 1)[0].decode("latin-1")


def flags_str(v, table):
    names = [n for bit, n in table if v & bit]
    return "|".join(names) if names else "0"


def ref_note(label, cid, expect, by_id, problems):
    if cid <= 0:
        return None
    hit = by_id.get(cid)
    if hit is None:
        problems.append("%s references missing chunk id %d" % (label, cid))
        return "%s -> id %d MISSING" % (label, cid)
    if expect is not None and hit.ctype != expect:
        problems.append("%s id %d is %s, expected %s" % (
            label, cid, cname(hit.ctype), cname(expect)))
        return "%s -> id %d is %s (WRONG TYPE)" % (label, cid, cname(hit.ctype))
    return "%s -> id %d (%s)" % (label, cid, cname(hit.ctype))


def decode_node(c, b, e, by_id, problems):
    # NODE_CHUNK_DESC_0824, CryHeaders.h:1068-1103 (fixed part 204 bytes)
    fmt = e + "64s4i4s16f3f4f3f4i"
    if len(b) < struct.calcsize(fmt):
        raise ValueError("chunk shorter than fixed NODE_CHUNK_DESC_0824 part")
    v = struct.unpack_from(fmt, b, 0)
    name = cstr(v[0])
    obj_id, parent_id, n_children, mat_id = v[1:5]
    tm = v[6:22]
    pos_c, rot_c, scl_c, prop_len = v[32:36]
    fixed = struct.calcsize(fmt)
    props = b[fixed:fixed + max(prop_len, 0)]
    fields = [
        ("name", repr(name)),
        ("ObjectID", obj_id), ("ParentID", parent_id), ("nChildren", n_children),
        ("MatID", mat_id),
        ("tm (row-major 4x4)", [list(tm[r * 4:r * 4 + 4]) for r in range(4)]),
        ("pos_cont_id", pos_c), ("rot_cont_id", rot_c), ("scl_cont_id", scl_c),
        ("PropStrLen", prop_len),
    ]
    if prop_len > 0:
        fields.append(("properties", repr(props.decode("latin-1"))))
    refs = [ref_note("ObjectID", obj_id, None, by_id, problems),
            ref_note("ParentID", parent_id, T_NODE, by_id, problems),
            ref_note("pos_cont_id", pos_c, T_CONTROLLER, by_id, problems),
            ref_note("rot_cont_id", rot_c, T_CONTROLLER, by_id, problems),
            ref_note("scl_cont_id", scl_c, T_CONTROLLER, by_id, problems)]
    if prop_len < 0 or fixed + prop_len > len(b):
        raise ValueError("PropStrLen %d does not fit in chunk" % prop_len)
    return {"fields": fields, "consumed": fixed + prop_len,
            "refs": [r for r in refs if r]}


def decode_mesh(c, b, e, by_id, problems):
    # MESH_CHUNK_DESC_0801, CryHeaders.h:571-616: 264 bytes, 66 int/float values
    fmt = e + "7i16i4i6f2f31i"
    if len(b) < struct.calcsize(fmt):
        raise ValueError("chunk shorter than MESH_CHUNK_DESC_0801")
    v = struct.unpack_from(fmt, b, 0)
    n_flags, n_flags2, n_verts, n_idx, n_sub, sub_cid, vanim = v[0:7]
    streams = v[7:23]
    phys = v[23:27]
    bmin, bmax = v[27:30], v[30:33]
    tex_density, face_area = v[33], v[34]
    fields = [
        ("nFlags", "0x%x (%s)" % (n_flags, flags_str(n_flags, MESH_FLAGS))),
        ("nFlags2", n_flags2), ("nVerts", n_verts), ("nIndices", n_idx),
        ("nSubsets", n_sub), ("nSubsetsChunkId", sub_cid), ("nVertAnimID", vanim),
        ("bboxMin", ["%g" % x for x in bmin]), ("bboxMax", ["%g" % x for x in bmax]),
        ("texMappingDensity", "%g" % tex_density),
        ("geometricMeanFaceArea", "%g" % face_area),
    ]
    refs = [ref_note("nSubsetsChunkId", sub_cid, T_MESHSUBSETS, by_id, problems)]
    for i, cid in enumerate(streams):
        if cid > 0:
            fields.append(("stream[%s] chunk id" % STREAM_NAMES[i], cid))
            refs.append(ref_note("stream %s" % STREAM_NAMES[i], cid, T_DATASTREAM,
                                 by_id, problems))
    for i, cid in enumerate(phys):
        if cid > 0:
            refs.append(ref_note("physics[%d]" % i, cid, T_MESHPHYSICSDATA, by_id, problems))
    return {"fields": fields, "consumed": struct.calcsize(fmt),
            "refs": [r for r in refs if r]}


def decode_subsets(c, b, e, by_id, problems):
    # MESH_SUBSETS_CHUNK_DESC_0800, CryHeaders.h:639-690; loader CGFLoader.cpp:3521-3590
    if len(b) < 16:
        raise ValueError("chunk shorter than MeshSubsets header")
    n_flags, n_count = struct.unpack_from(e + "ii", b, 0)
    if n_count < 0 or 16 + 36 * n_count > len(b):
        raise ValueError("nCount %d does not fit in chunk" % n_count)
    pos = 16
    subsets = []
    for _ in range(n_count):
        # MeshSubset: 5 ints, float fRadius, Vec3 vCenter = 36 bytes
        subsets.append(struct.unpack_from(e + "5if3f", b, pos))
        pos += 36
    bone_counts = []
    if n_flags & 0x0002:  # BONEINDICES: MeshBoneIDs = uint32 + uint16[128] = 260 bytes
        for _ in range(n_count):
            n_bones = struct.unpack_from(e + "I", b, pos)[0]
            bone_counts.append(n_bones)
            pos += 260
    densities = []
    if n_flags & 0x0004:  # HAS_SUBSET_TEXEL_DENSITY: float per subset
        for _ in range(n_count):
            densities.append(struct.unpack_from(e + "f", b, pos)[0])
            pos += 4
    fields = [("nFlags", "0x%x (%s)" % (n_flags, flags_str(n_flags, SUBSET_FLAGS))),
              ("nCount", n_count)]
    for i, s in enumerate(subsets[:16]):
        fields.append(("subset[%d] firstIndex=%d numIndices=%d firstVert=%d numVerts=%d "
                       "matID=%d radius=%g center=(%g,%g,%g)" % ((i,) + s[:5] + (s[5],) + s[6:9]),
                       ""))
    if len(subsets) > 16:
        fields.append(("...", "%d more subsets not listed" % (len(subsets) - 16)))
    if bone_counts:
        fields.append(("numBoneIDs per subset", bone_counts[:16]))
    if densities:
        fields.append(("texelDensity per subset", ["%g" % d for d in densities[:16]]))
    return {"fields": fields, "consumed": pos, "refs": []}


def decode_elems(stype, esize, count, raw, e):
    """First up-to-3 elements of a stream, or raw hex when the element type is unknown."""
    fmt = None
    if stype in (0, 1) and esize == 12:
        fmt = e + "3f"                 # POSITIONS / NORMALS as Vec3 (float)
    elif stype == 0 and esize == 8:
        fmt = e + "4e"                 # POSITIONSF16: Vec3f16 = CryHalf4
    elif stype == 2 and esize == 8:
        fmt = e + "2f"                 # TEXCOORDS: SMeshTexCoord {float s, t}
    elif stype in (3, 4) and esize == 4:
        fmt = e + "4B"                 # COLORS / COLORS2: SMeshColor {uint8 r,g,b,a}
    elif stype == 5 and esize == 2:
        fmt = e + "H"                  # INDICES as uint16
    elif stype == 5 and esize == 4:
        fmt = e + "I"                  # INDICES as uint32
    elif stype == 11 and esize == 4:
        fmt = e + "i"                  # VERT_MATS: int
    n = min(3, count)
    if fmt is None:
        return "raw hex (undecoded element type): " + raw[:n * esize].hex()
    out = []
    for i in range(n):
        vals = struct.unpack_from(fmt, raw, i * esize)
        if fmt.endswith("4e"):
            vals = vals[:3]
        out.append(tuple(round(x, 6) if isinstance(x, float) else x for x in vals))
    return out


def decode_datastream(c, b, e, by_id, problems):
    # STREAM_DATA_CHUNK_DESC_0800, CryHeaders.h:619-637 (24-byte header)
    if len(b) < 24:
        raise ValueError("chunk shorter than STREAM_DATA_CHUNK_DESC_0800")
    n_flags, stype, count, esize, _r0, _r1 = struct.unpack_from(e + "4i2i", b, 0)
    if count < 0 or esize < 0 or 24 + count * esize > len(b):
        raise ValueError("nCount*nElementSize (%d*%d) does not fit in chunk" % (count, esize))
    raw = b[24:24 + count * esize]
    sname = STREAM_NAMES[stype] if 0 <= stype < len(STREAM_NAMES) else "unknown"
    fields = [("nFlags", n_flags), ("nStreamType", "%d (%s)" % (stype, sname)),
              ("nCount", count), ("nElementSize", esize),
              ("first elements", decode_elems(stype, esize, count, raw, e))]
    return {"fields": fields, "consumed": 24 + count * esize, "refs": []}


def decode_mtlname(c, b, e, by_id, problems):
    # MTL_NAME_CHUNK_DESC_0802, CryHeaders.h:520-531; loader CGFLoader.cpp:3863-3925
    if len(b) < 132:
        raise ValueError("chunk shorter than MTL_NAME_CHUNK_DESC_0802")
    raw_name, n_sub = struct.unpack_from(e + "128si", b, 0)
    name = cstr(raw_name)
    pos = 132
    if n_sub <= 0:
        ptype = struct.unpack_from(e + "i", b, pos)[0]
        pos += 4
        types, names = [ptype], []
    else:
        if n_sub > 128:
            raise ValueError("nSubMaterials %d > MAX_SUB_MATERIALS (128)" % n_sub)
        types = list(struct.unpack_from(e + "%di" % n_sub, b, pos))
        pos += 4 * n_sub
        names = []
        for _ in range(n_sub):
            end = b.find(b"\0", pos)
            if end < 0:
                raise ValueError("unterminated sub-material name")
            names.append(b[pos:end].decode("latin-1"))
            pos = end + 1
    fields = [("name", repr(name)), ("nSubMaterials", n_sub),
              ("physicalizeTypes", types)]
    if names:
        fields.append(("subMaterialNames", names))
    return {"fields": fields, "consumed": pos, "refs": []}


DECODERS = {
    (T_NODE, (0x824, 0x823)): decode_node,
    (T_MESH, (0x801, 0x800)): decode_mesh,
    (T_MESHSUBSETS, (0x800,)): decode_subsets,
    (T_DATASTREAM, (0x800,)): decode_datastream,
    (T_MTLNAME, (0x802,)): decode_mtlname,
}


def check_coverage(data, hdr, chunks):
    """Tile the file: header, chunk table, every chunk. Report gaps and overlaps."""
    problems = []
    ivs = [(0, hdr["header_size"], "file header"),
           (hdr["table_offset"], hdr["table_offset"] + hdr["table_len"], "chunk table")]
    for c in chunks:
        if c.offset + c.size > len(data):
            problems.append("chunk %d extends past end of file" % c.index)
        ivs.append((c.offset, c.offset + c.size, "chunk %d" % c.index))
    ivs.sort()
    pos = 0
    for s, end, label in ivs:
        if s < pos:
            problems.append("overlap at 0x%x (%s)" % (s, label))
        elif s > pos:
            problems.append("gap of %d bytes at 0x%x before %s" % (s - pos, pos, label))
        pos = max(pos, end)
    if pos < len(data):
        problems.append("%d unaccounted bytes after 0x%x" % (len(data) - pos, pos))
    return problems


def dump(path):
    with open(path, "rb") as f:  # read-only
        data = f.read()
    print("== %s (%d bytes)" % (path, len(data)))
    try:
        hdr, chunks = parse_container(data)
    except (ValueError, struct.error) as exc:
        print("PARSE ERROR: %s" % exc)
        return False
    ft = "" if hdr["fileType"] is None else " fileType=0x%x" % hdr["fileType"]
    print("file header: signature=%r format=%s%s chunkCount=%d chunkTableOffset=0x%x "
          "(header %d bytes, table %d bytes)" % (
              hdr["sig"], hdr["format"], ft, hdr["count"], hdr["table_offset"],
              hdr["header_size"], hdr["table_len"]))
    if hdr["format"] != "0x746":
        print("note: legacy %s table; chunk bodies are not decoded by this script" % hdr["format"])
    by_id = {}
    for c in chunks:
        by_id.setdefault(c.cid, c)

    print("chunk table:")
    print("  %3s  %-8s %-24s %-8s %-10s %-10s %-8s" % (
        "#", "type", "name", "version", "id", "offset", "size"))
    for c in chunks:
        print("  %3d  0x%04x   %-24s 0x%04x   %-10d 0x%08x %-8d%s" % (
            c.index, c.ctype, cname(c.ctype), c.version, c.cid, c.offset, c.size,
            "  (big-endian body)" if c.be else ""))

    all_ok = True
    decoded = 0
    for c in chunks:
        print()
        print("[%d] %s (0x%04x) version=0x%04x id=%d offset=0x%x size=%d" % (
            c.index, cname(c.ctype), c.ctype, c.version, c.cid, c.offset, c.size))
        if c.offset + c.size > len(data):
            print("    body not read: chunk runs past end of file")
            all_ok = False
            continue
        body = data[c.offset:c.offset + c.size]
        key = None
        for (t, vers), fn in DECODERS.items():
            if c.ctype == t and c.version in vers:
                key = (t, vers)
                break
        if key is None or hdr["format"] != "0x746":
            print("    not decoded (no decoder for this type/version); size taken from table")
            continue
        decoded += 1
        e = ">" if c.be else "<"
        try:
            problems = []
            res = DECODERS[key](c, body, e, by_id, problems)
        except (ValueError, struct.error) as exc:
            print("    DECODE ERROR: %s" % exc)
            all_ok = False
            continue
        for label, value in res["fields"]:
            if value == "" and label.startswith("subset"):
                print("    %s" % label)
            elif isinstance(value, list) and value and isinstance(value[0], list):
                print("    %s:" % label)
                for row in value:
                    print("      %s" % row)
            else:
                print("    %s: %s" % (label, value))
        for r in res["refs"]:
            print("    ref: %s" % r)
        for p in problems:
            print("    REF PROBLEM: %s" % p)
            all_ok = False
        consumed = res["consumed"]
        if consumed == c.size:
            print("    consumed %d of %d bytes: OK" % (consumed, c.size))
        else:
            print("    consumed %d of %d bytes: MISMATCH" % (consumed, c.size))
            all_ok = False

    print()
    cov = check_coverage(data, hdr, chunks)
    if cov:
        for p in cov:
            print("coverage: %s" % p)
        all_ok = False
    else:
        print("coverage: OK (file header, chunk table and %d chunks tile the file exactly)"
              % len(chunks))
    print("summary: %d chunks, %d with a decoder, %s" % (
        len(chunks), decoded, "all checks passed" if all_ok else "PROBLEMS FOUND"))
    print()
    return all_ok


# ---------------------------------------------------------------- bounds (read-only, used by terrain brushes)

class CgfBoundsError(ValueError):
    """The file is not a .cgf whose vertex bounds can be read; the message says why."""


def mesh_bounds(path):
    """Min and max of the POSITIONS of every Mesh chunk in a 0x746 .cgf, as ((x, y, z), (x, y, z)) floats.

    Reads the Mesh chunk (MESH_CHUNK_DESC_0801, the same layout decode_mesh uses), follows its POSITIONS stream id
    to the DataStream chunk and reads the vertices: float32 (element size 12) or half-float Vec3f16 stored as CryHalf4
    (element size 8). Read-only. Raises CgfBoundsError for anything it cannot read exactly; it never guesses a box."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        hdr, chunks = parse_container(data)
    except (ValueError, struct.error) as exc:
        raise CgfBoundsError("%s: not a readable .cgf container: %s" % (path, exc))
    if hdr["format"] != "0x746":
        raise CgfBoundsError("%s: %s container, only the 0x746 format has vertex bounds here" % (path, hdr["format"]))
    by_id = {}
    for c in chunks:
        by_id.setdefault(c.cid, c)
    meshes = [c for c in chunks if c.ctype == T_MESH]
    if not meshes:
        raise CgfBoundsError("%s: no Mesh chunk" % path)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for m in meshes:
        if m.version != 0x801 or m.offset + m.size > len(data) or m.size < 264:
            raise CgfBoundsError("%s: Mesh chunk %d has version 0x%x or size %d, not MESH_CHUNK_DESC_0801"
                                 % (path, m.index, m.version, m.size))
        e = ">" if m.be else "<"
        v = struct.unpack_from(e + "7i16i4i6f2f31i", data, m.offset)
        n_verts, pos_cid = v[2], v[7]
        if n_verts <= 0:
            raise CgfBoundsError("%s: Mesh chunk %d has no vertices" % (path, m.index))
        if pos_cid <= 0:
            raise CgfBoundsError("%s: Mesh chunk %d has no POSITIONS stream" % (path, m.index))
        ds = by_id.get(pos_cid)
        if ds is None or ds.ctype != T_DATASTREAM or ds.offset + ds.size > len(data) or ds.size < 24:
            raise CgfBoundsError("%s: POSITIONS stream id %d is not a DataStream chunk in the file" % (path, pos_cid))
        de = ">" if ds.be else "<"
        n_flags, stype, count, esize = struct.unpack_from(de + "4i", data, ds.offset)
        if stype != 0 or count != n_verts:
            raise CgfBoundsError("%s: POSITIONS stream has type %d and %d elements, Mesh has %d vertices"
                                 % (path, stype, count, n_verts))
        if esize == 12:
            fmt = de + "3f"
        elif esize == 8:
            fmt = de + "4e"
        else:
            raise CgfBoundsError("%s: POSITIONS element size %d is neither float32 (12) nor half (8)" % (path, esize))
        if 24 + count * esize > ds.size:
            raise CgfBoundsError("%s: POSITIONS stream does not fit its chunk" % path)
        base = ds.offset + 24
        for i in range(count):
            p = struct.unpack_from(fmt, data, base + i * esize)[:3]
            for k in range(3):
                if not math.isfinite(p[k]):
                    raise CgfBoundsError("%s: non-finite vertex position" % path)
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    return tuple(lo), tuple(hi)
