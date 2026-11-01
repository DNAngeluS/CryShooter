"""glTF 2.0 (.gltf/.glb) static-mesh importer for CRYENGINE (ported from the P0(f) spike; logic unchanged).

import_gltf(path, scale) reads the default scene's triangle primitives into flat lists;
convert_textures(asset, out_dir, name) writes a .dds per referenced PNG; write_mtl writes a .mtl.
Contract: what cannot be expressed raises GltfError; nothing degrades silently. The command-line
wiring lives in cli.py. Stdlib only.

Axes: glTF is Y-up (+Z toward viewer); CRYENGINE is Z-up with +Y forward. Mapping (x, y, z) -> (x, -z, y),
a pure rotation, so triangle winding is kept. UVs are passed through unchanged (both use v = 0 at the top);
this is unproven until the render check.
"""

import base64
import json
import math
import os
import struct

from . import cgf
from .cache import write_dds_cached
from . import bake as bake_mod
from .materials import MaterialOptions, illum_params
from .png import read_png

MTL_DEFAULT = cgf.MTL_EDITORPRIMITIVE
COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
SUPPORTED_EXT = set()  # none: any extensionsRequired entry is an error


class GltfError(Exception):
    pass


def load(path):
    """Return (json dict, binary chunk bytes or None, base directory)."""
    data = open(path, "rb").read()
    base = os.path.dirname(os.path.abspath(path))
    if data[:4] == b"glTF":
        ver, total = struct.unpack_from("<II", data, 4)
        if ver != 2:
            raise GltfError("only glTF 2.0 supported (got %d)" % ver)
        pos, doc, binchunk = 12, None, None
        while pos + 8 <= min(total, len(data)):
            n, typ = struct.unpack_from("<I4s", data, pos)
            body = data[pos + 8:pos + 8 + n]
            if typ == b"JSON":
                doc = json.loads(body.decode("utf-8"))
            elif typ == b"BIN\0" and binchunk is None:
                binchunk = body
            pos += 8 + n
        if doc is None:
            raise GltfError("GLB without JSON chunk")
        return doc, binchunk, base
    return json.loads(data.decode("utf-8")), None, base


class Asset:
    def __init__(self, path):
        self.doc, self.glb_bin, self.base = load(path)
        d = self.doc
        if d.get("asset", {}).get("version") != "2.0":
            raise GltfError("asset.version must be 2.0")
        for ext in d.get("extensionsRequired", []):
            if ext not in SUPPORTED_EXT:
                raise GltfError("required extension not supported: " + ext)
        self._buffers = {}
        self.warnings = []

    def buffer(self, i):
        if i not in self._buffers:
            b = self.doc["buffers"][i]
            uri = b.get("uri")
            if uri is None:
                if i != 0 or self.glb_bin is None:
                    raise GltfError("buffer %d has no uri and no GLB binary chunk" % i)
                raw = self.glb_bin
            else:
                raw = self.read_uri(uri)
            if len(raw) < b["byteLength"]:
                raise GltfError("buffer %d shorter than byteLength" % i)
            self._buffers[i] = raw
        return self._buffers[i]

    def read_uri(self, uri):
        if uri.startswith("data:"):
            head, _, payload = uri.partition(",")
            if not head.endswith(";base64"):
                raise GltfError("only base64 data URIs supported")
            return base64.b64decode(payload)
        if "://" in uri or uri.startswith("/") or ".." in uri.replace("\\", "/").split("/"):
            raise GltfError("uri must be a relative path inside the asset directory: " + uri)
        return open(os.path.join(self.base, uri.replace("%20", " ")), "rb").read()

    def accessor(self, idx):
        """Return list of tuples (or scalars for SCALAR) for accessor idx."""
        a = self.doc["accessors"][idx]
        if "sparse" in a:
            raise GltfError("sparse accessors are not supported (accessor %d)" % idx)
        if a["componentType"] not in COMP or a["type"] not in NCOMP:
            raise GltfError("unsupported accessor type in %d" % idx)
        fmt, csize = COMP[a["componentType"]]
        n = NCOMP[a["type"]]
        count = a["count"]
        if "bufferView" not in a:
            return [(0.0,) * n if n > 1 else 0.0 for _ in range(count)]
        bv = self.doc["bufferViews"][a["bufferView"]]
        raw = self.buffer(bv["buffer"])
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride") or csize * n
        norm = a.get("normalized", False) and a["componentType"] != 5126
        scale = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}.get(a["componentType"], 1.0)
        out = []
        for i in range(count):
            p = off + i * stride
            if p + csize * n > len(raw):
                raise GltfError("accessor %d reads past its buffer" % idx)
            vals = struct.unpack_from("<%d%s" % (n, fmt), raw, p)
            if norm:
                vals = tuple(max(v / scale, -1.0) for v in vals)
            out.append(vals if n > 1 else vals[0])
        return out

    def image_png(self, image_index):
        im = self.doc["images"][image_index]
        if "uri" in im:
            data = self.read_uri(im["uri"])
        elif "bufferView" in im:
            bv = self.doc["bufferViews"][im["bufferView"]]
            off = bv.get("byteOffset", 0)
            data = self.buffer(bv["buffer"])[off:off + bv["byteLength"]]
        else:
            raise GltfError("image %d has neither uri nor bufferView" % image_index)
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise GltfError("image %d is not a PNG (only PNG supported)" % image_index)
        return data


# ------------------------------------------------------------------ math
def mat_identity():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]  # column-major


def mat_mul(a, b):
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def node_matrix(node):
    if "matrix" in node:
        if len(node["matrix"]) != 16:
            raise GltfError("node.matrix must have 16 numbers")
        return [float(v) for v in node["matrix"]]
    tx, ty, tz = node.get("translation", [0, 0, 0])
    qx, qy, qz, qw = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if abs(n - 1.0) > 1e-3:
        raise GltfError("node rotation quaternion is not normalised")
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    r = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
         2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
         2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy)]
    return [r[0] * sx, r[1] * sx, r[2] * sx, 0, r[3] * sy, r[4] * sy, r[5] * sy, 0,
            r[6] * sz, r[7] * sz, r[8] * sz, 0, tx, ty, tz, 1.0]


def xform_point(m, p):
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def normal_matrix(m):
    """Cofactor of the upper 3x3 (= det * inverse-transpose); sign handled by the caller via det."""
    a, b, c, d, e, f, g, h, i = m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]  # rows
    cof = [e * i - f * h, f * g - d * i, d * h - e * g,
           c * h - b * i, a * i - c * g, b * g - a * h,
           b * f - c * e, c * d - a * f, a * e - b * d]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return cof, det


def to_cry(v):
    return (v[0], -v[2], v[1])


def normalize(v):
    l = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / l, v[1] / l, v[2] / l) if l > 1e-12 else (0.0, 0.0, 1.0)


def flat_normals(pos, idx):
    """Split vertices per triangle with face normals (used when NORMAL is absent)."""
    P, N, T = [], [], []
    out_idx = []
    return P, N, T, out_idx


# ------------------------------------------------------------------ import
def import_gltf(path, scale=1.0):
    """Return dict(positions, normals, uvs, indices, subsets, materials, warnings)."""
    A = Asset(path)
    d = A.doc
    scenes = d.get("scenes", [])
    if not scenes:
        raise GltfError("no scenes")
    scene = scenes[d.get("scene", 0)]
    positions, normals, uvs, indices, subsets, mats = [], [], [], [], [], []

    def visit(ni, parent_m, depth=0):
        if depth > 64:
            raise GltfError("node hierarchy too deep or cyclic")
        node = d["nodes"][ni]
        if "skin" in node:
            raise GltfError("skins are not supported (node %d)" % ni)
        for k in ("camera",):
            if k in node:
                A.warnings.append("node %d: %s ignored" % (ni, k))
        if "extensions" in node and "KHR_lights_punctual" in node["extensions"]:
            A.warnings.append("node %d: KHR_lights_punctual ignored" % ni)
        m = mat_mul(parent_m, node_matrix(node))
        if "mesh" in node:
            add_mesh(d["meshes"][node["mesh"]], m)
        for c in node.get("children", []):
            visit(c, m, depth + 1)

    def add_mesh(mesh, m):
        cof, det = normal_matrix(m)
        if abs(det) < 1e-12:
            raise GltfError("degenerate node transform (zero determinant)")
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                raise GltfError("only triangle lists (mode 4) supported, got %s" % prim.get("mode"))
            if "targets" in prim or "extensions" in prim:
                raise GltfError("morph targets / primitive extensions are not supported")
            attrs = prim["attributes"]
            if "POSITION" not in attrs:
                raise GltfError("primitive without POSITION")
            if "JOINTS_0" in attrs or "WEIGHTS_0" in attrs:
                raise GltfError("skinned primitives are not supported")
            pos = A.accessor(attrs["POSITION"])
            n = len(pos)
            tex = A.accessor(attrs["TEXCOORD_0"]) if "TEXCOORD_0" in attrs else [(0.0, 0.0)] * n
            nor = A.accessor(attrs["NORMAL"]) if "NORMAL" in attrs else None
            idx = A.accessor(prim["indices"]) if "indices" in prim else list(range(n))
            if len(idx) % 3:
                raise GltfError("index count not a multiple of 3")
            if idx and max(idx) >= n:
                raise GltfError("index out of range")
            if len(tex) != n or (nor is not None and len(nor) != n):
                raise GltfError("attribute counts differ")
            flip = det < 0
            tri = [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
            if nor is None:  # unshared vertices with face normals
                P, N, T, I = [], [], [], []
                for t in tri:
                    q = [xform_point(m, pos[v]) for v in t]
                    u = (q[1][0] - q[0][0], q[1][1] - q[0][1], q[1][2] - q[0][2])
                    w = (q[2][0] - q[0][0], q[2][1] - q[0][1], q[2][2] - q[0][2])
                    fn = normalize((u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]))
                    order = (0, 2, 1) if flip else (0, 1, 2)
                    for k in order:
                        I.append(len(P)); P.append(q[k]); N.append(fn); T.append(tex[t[k]])
                A.warnings.append("a primitive had no NORMAL: flat face normals generated")
            else:
                P = [xform_point(m, p) for p in pos]
                N = [normalize((cof[0] * v[0] + cof[1] * v[1] + cof[2] * v[2],
                                cof[3] * v[0] + cof[4] * v[1] + cof[5] * v[2],
                                cof[6] * v[0] + cof[7] * v[1] + cof[8] * v[2])) for v in nor]
                if det < 0:
                    N = [(-a, -b, -c) for a, b, c in N]  # cofactor carries the sign of det
                T = list(tex)
                I = []
                for t in tri:
                    I += [t[0], t[2], t[1]] if flip else list(t)
            base = len(positions)
            first = len(indices)
            positions.extend(tuple(c * scale for c in to_cry(p)) for p in P)
            normals.extend(to_cry(v) for v in N)
            uvs.extend((float(u[0]), float(u[1])) for u in T)
            indices.extend(base + i for i in I)
            mat = prim.get("material")
            if mat not in mats:
                mats.append(mat)
            subsets.append((first, len(I), mats.index(mat)))

    for ni in scene.get("nodes", []):
        visit(ni, mat_identity())
    if not indices:
        raise GltfError("scene contains no triangles")
    return dict(positions=positions, normals=normals, uvs=uvs, indices=indices, subsets=subsets,
                materials=mats, warnings=A.warnings, asset=A)


def png_has_alpha(png_path):
    w, h, px = read_png(png_path)
    return any(px[o] < 255 for o in range(3, len(px), 4))


def _convert_one(task):
    """Worker entry point (module level so it pickles). task = (png bytes, source index, slot, name, out_dir,
    cache_dir, jobs). Returns (format, fname, width, height, mips, bytes). Each (source, slot) is converted once,
    so the temporary PNG names never collide between workers."""
    png, source, slot, name, out_dir, cache_dir, jobs, nscale = task
    tmp = os.path.join(out_dir, ".tmp_%d_%d_%s.png" % (os.getpid(), source, slot))   # pid: concurrent imports into one folder
    open(tmp, "wb").write(png)
    try:
        if slot == "normal":
            fmt, fname = "bc5s", "%s_img%d_ddn.dds" % (name, source)  # signed: the engine reads the map as already signed
            if nscale != 1.0:      # normalTexture.scale: another file per scale, so two materials can share one image
                fname = "%s_img%d_s%g_ddn.dds" % (name, source, nscale)
                png = png + b"|nscale=%r" % nscale          # the cache key is the PNG bytes plus what changes the output
        elif slot == "occlusion":
            # glTF occlusionTexture: R only, linear, strength baked in; one BC4 file per strength (the Custom slot, %OCCLUSION_MAP)
            fmt, fname = "bc4", "%s_img%d_occ.dds" % (name, source)
            if nscale != 1.0:
                fname = "%s_img%d_occ_s%g.dds" % (name, source, nscale)
            png = png + b"|occ=%r" % nscale
        elif slot == "emissive":
            # glTF emissive colour is sRGB; the Illum shader reads rgb x alpha of the map, so no alpha channel (BC1)
            fmt, fname = "bc1", "%s_img%d_em.dds" % (name, source)
        else:
            fmt = "bc3" if png_has_alpha(tmp) else "bc1"
            fname = "%s_img%d.dds" % (name, source)
        w, h, px = read_png(tmp)
        if slot == "normal" and nscale != 1.0:
            px = bake_mod.scale_normals(px, nscale)
        elif slot == "occlusion":
            px = bake_mod.occlusion_pixels(px, nscale)
        mips, size = write_dds_cached(os.path.join(out_dir, fname), png, w, h, px, fmt, cache_dir, 0,
                                      srgb=(slot in ("baseColor", "emissive")), jobs=jobs)
    finally:
        os.remove(tmp)
    return fmt, fname, w, h, mips, size


def resolve_jobs(jobs):
    """0 means os.cpu_count(); 1 (the default) is serial."""
    if jobs == 0:
        return os.cpu_count() or 1
    if jobs < 0:
        raise GltfError("jobs must be 0 (all CPUs) or a positive number")
    return jobs


def convert_textures(A, out_dir, name, jobs=1, cache_dir=None, emissive=True, bake=False, warnings=None, ao=False, occlusion=False):
    """Convert the PNGs used by materials to DDS. Returns list of manifest entries, in material order.

    Independent textures are encoded in a process pool when jobs > 1 (one texture at a time otherwise, with the
    row-band split inside each texture). Entry order and content do not depend on jobs. cache_dir enables the
    content-hash cache (see cache.py). emissive=False skips emissiveTexture (the --no-pbr output). occlusion=True writes an
    occlusionTexture as a BC4 map for the Illum %OCCLUSION_MAP flag (not when ao baked it into the diffuse already)."""
    jobs = resolve_jobs(jobs)
    d = A.doc
    plan, done, uses = [], {}, []  # plan: one encode per (source, slot, scale); uses: every (material, slot, key) that points at one
    baked_entries = []
    for mi, mat in enumerate(d.get("materials", [])):
        slots = []
        pbr = mat.get("pbrMetallicRoughness", {})
        baked = False
        if bake and bake_mod.can_bake(mat, ao):
            try:
                baked_entries += bake_mod.bake_material(A, mi, mat, name, out_dir, None, cache_dir, jobs, ao)
                baked = True
            except bake_mod.Unbakeable as e:
                if warnings is not None:
                    warnings.append("material %r: not baked (%s), falling back to the mean approximation" % (mat.get("name", mi), e))
        if "baseColorTexture" in pbr and not baked:
            slots.append(("baseColor", pbr["baseColorTexture"]))
        if "normalTexture" in mat and not baked:
            slots.append(("normal", mat["normalTexture"]))
        if emissive and "emissiveTexture" in mat:
            slots.append(("emissive", mat["emissiveTexture"]))
        if occlusion and "occlusionTexture" in mat and not (baked and ao):
            oref = mat["occlusionTexture"]
            if oref.get("texCoord", 0) != 0:
                if warnings is not None:
                    warnings.append("material %r: occlusionTexture uses TEXCOORD_%d, only TEXCOORD_0 is supported: ignored"
                                    % (mat.get("name", mi), oref["texCoord"]))
            else:
                slots.append(("occlusion", oref))
        for slot, ref in slots:
            if ref.get("texCoord", 0) != 0:
                raise GltfError("only TEXCOORD_0 supported (material %d %s)" % (mi, slot))
            tex = d["textures"][ref["index"]]
            if "source" not in tex:
                raise GltfError("texture %d has no source" % ref["index"])
            nscale = float(ref.get("scale", 1.0)) if slot == "normal" else float(ref.get("strength", 1.0)) if slot == "occlusion" else 1.0
            key = (tex["source"], slot, nscale)
            uses.append((mi, slot, key))
            if key in done:
                continue
            done[key] = True
            plan.append((mi, slot, tex["source"], A.image_png(tex["source"]), nscale))
    inner = 1 if len(plan) > 1 else jobs  # textures in parallel, or bands inside the one texture
    tasks = [(png, src, slot, name, out_dir, cache_dir, inner, ns) for _mi, slot, src, png, ns in plan]
    if jobs > 1 and len(plan) > 1:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        ctx = multiprocessing.get_context("fork") if "fork" in multiprocessing.get_all_start_methods() else None
        with ProcessPoolExecutor(max_workers=min(jobs, len(plan)), mp_context=ctx) as ex:
            results = list(ex.map(_convert_one, tasks))
    else:
        results = [_convert_one(t) for t in tasks]
    entries = []
    by_key = {(src, slot, ns): r for (_mi, slot, src, _png, ns), r in zip(plan, results)}
    for mi, slot, key in uses:      # a material that shares an image with an earlier one points at the same file
        fmt, fname, w, h, mips, size = by_key[key]
        entries.append(dict(material=mi, slot=slot, image=key[0], dds=fname, format=fmt,
                            width=w, height=h, mips=mips, bytes=size))
    entries += baked_entries
    entries.sort(key=lambda e: e["material"])        # stable: the order of a plain import is unchanged
    return entries


MTL_FLAG_MULTI_SUBMTL = 0x0100  # IMaterial.h:56
MTL_FLAG_2SIDED = 0x0002        # IMaterial.h:49, read per material node (MatMan.cpp:427)
WHITE_TEXTURE = "%ENGINE%/EngineAssets/Textures/white.dds"


def write_mtl(path, game_dir, name, doc, mats, textures, asset=None, options=None):
    """Write <name>.mtl next to the cgf: one sub-material per glTF material used by a subset, in subset-id order
    (the cgf mesh subset matID indexes SubMaterials; ids past the count wrap, CGFLoader.cpp:2480). A single material
    is written without the multi-submaterial flag. Texture File paths are game-relative (MaterialHelpers.cpp:349)."""
    from xml.sax.saxutils import quoteattr
    options = options or MaterialOptions()
    by_slot = {(t["material"], t["slot"]): t["dds"] for t in textures}

    def one(mi, label):
        m = doc["materials"][mi] if mi is not None else {}
        baked = (mi, "specular") in by_slot
        p = illum_params(m, asset, options, baked=baked)
        diffuse = ",".join("%g" % c for c in p["diffuse"])
        rows = []
        if (mi, "baseColor") in by_slot:
            rows.append(("Diffuse", game_dir + "/" + by_slot[(mi, "baseColor")]))
        else:
            # Illum without a diffuse texture shows the engine's red "Replace Me" placeholder (render check 2026-10-24),
            # so an untextured material points at the engine's white texture and keeps its colour in Diffuse=.
            rows.append(("Diffuse", WHITE_TEXTURE))
        if (mi, "normal") in by_slot:
            rows.append(("Bumpmap", game_dir + "/" + by_slot[(mi, "normal")]))
        if baked:
            rows.append(("Specular", game_dir + "/" + by_slot[(mi, "specular")]))
        if (mi, "emissive") in by_slot and p["emittance"] is not None:
            rows.append(("Emittance", game_dir + "/" + by_slot[(mi, "emissive")]))
        if (mi, "occlusion") in by_slot:
            rows.append(("Custom", game_dir + "/" + by_slot[(mi, "occlusion")]))     # read by Illum under %OCCLUSION_MAP
        tex = "".join('   <Texture Map="%s" File=%s/>\n' % (slot, quoteattr(f)) for slot, f in rows)
        attrs = 'Name=%s Shader="Illum" Diffuse="%s"' % (quoteattr(label), diffuse)
        if m.get("doubleSided"):
            attrs += ' MtlFlags="%d"' % MTL_FLAG_2SIDED       # glTF doubleSided: no back-face culling, the shader flips the normal
        if p["specular"] is not None:
            attrs += ' Specular="%s" Shininess="%d"' % (",".join("%.6g" % c for c in p["specular"]), p["shininess"])
        if p["emittance"] is not None:
            attrs += ' Emittance="%s"' % ",".join("%.6g" % c for c in p["emittance"])
        attrs += ' Opacity="%g"' % p["opacity"]
        if p["alpha_test"] is not None:
            attrs += ' AlphaTest="%g"' % p["alpha_test"]
        # the editor writes the shader generation mask for a bump map; without it the Illum variant is wrong (render check 2026-10-24);
        # a Specular texture needs %SPECULAR_MAP the same way (Illum.cfx:489), concatenated as the engine's own materials write it;
        # %OCCLUSION_MAP exists only in an engine with the sandbox's shader extension (engine-ext), others ignore the unknown flag
        mask = ("%NORMAL_MAP" if (mi, "normal") in by_slot else "") + ("%SPECULAR_MAP" if baked else "") \
            + ("%OCCLUSION_MAP" if (mi, "occlusion") in by_slot else "")
        if mask:
            attrs += ' StringGenMask="%s"' % mask
        return attrs, tex

    out = []
    if len(mats) == 1:
        attrs, tex = one(mats[0], name)
        out.append("<Material %s>\n  <Textures>\n%s  </Textures>\n</Material>\n" % (attrs, tex))
    else:
        out.append('<Material MtlFlags="%d">\n <SubMaterials>\n' % MTL_FLAG_MULTI_SUBMTL)
        for i, mi in enumerate(mats):
            label = (doc["materials"][mi].get("name") if mi is not None else None) or "mat%d" % i
            attrs, tex = one(mi, label)
            out.append("  <Material %s>\n   <Textures>\n%s   </Textures>\n  </Material>\n" % (attrs, tex))
        out.append(" </SubMaterials>\n</Material>\n")
    open(path, "w").write("".join(out))
