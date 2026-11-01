"""glTF skinned mesh -> CRYENGINE character files (.chr skeleton, .skin mesh, .caf animations, .cdf, .chrparams, .mtl).

Written from the engine's loaders (CGFLoader.cpp ReadCompiled*, LoaderCHR.cpp InitializeBones, GlobalAnimationHeaderCAF.cpp)
and proven in the engine (docs/findings/2026-10-28-p4-skinned-mesh-spec.md in the sandbox): there is no RC on Linux, so the
files are the COMPILED chunk files the engine expects. Stdlib only.

import_gltf_skin(path, scale) -> Rig dict; build_* turn it into file bytes; convert_skin writes a folder.
What cannot be expressed raises SkinError; nothing degrades silently. Limits of this first version: one skin per file,
one weight set (JOINTS_0/WEIGHTS_0, up to 4 influences), no morph targets, no cubic-spline animation, bind poses without
scale of their own (one uniform scale shared by all joints, from an ancestor node, is folded in). Axes as in gltf.py: glTF (x, y, z) -> engine (x, -z, y) (a pure rotation).
"""

import math
import os
import struct
import zlib

from . import cgf, gltf
from .materials import MaterialOptions

FPS = 30.0
T_COMPILED_BONES, T_COMPILED_PHYS_BONES, T_INT_SKIN_VERTS = 0x2000, 0x2001, 0x2005
T_INT_FACES, T_EXT2INT, T_BONES_BOXES = 0x2004, 0x2006, 0x3004
T_TIMING, T_MOTION_PARAMS, T_CONTROLLER = 0x100E, 0x3002, 0x100D
STREAM_BONEMAPPING = 9
ID_BONEMAP = 26                      # the chunk id after the ones cgf.build_static_mesh uses (0..25)
ROOT_TOLERANCE_RAD = 0.14            # InitializeBones: the root must be within ~8 degrees of identity
MAX_BONES = 255                      # MAX_JOINT_AMOUNT is larger; stay far below it
MAX_VERTICES = 32767                 # BonesBoxes indices are int16, IntFaces are uint16


class SkinError(Exception):
    pass


# ------------------------------------------------------------------ small math (3x3 row-major, quats x y z w)
def _cry(v):
    return (v[0], -v[2], v[1])


def _quat_cry(q):
    return (q[0], -q[2], q[1], q[3])


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def _qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def _qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def _qrot(q, v):
    t = _qmul(_qmul(q, (v[0], v[1], v[2], 0.0)), _qinv(q))
    return (t[0], t[1], t[2])


def _slerp(a, b, u):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0.0:
        b, d = tuple(-c for c in b), -d
    if d > 0.9995:
        return _qnorm(tuple(x + (y - x) * u for x, y in zip(a, b)))
    th = math.acos(min(1.0, d))
    s = math.sin(th)
    ka, kb = math.sin((1 - u) * th) / s, math.sin(u * th) / s
    return _qnorm(tuple(ka * x + kb * y for x, y in zip(a, b)))


def _mat_to_quat(r):
    """r: 3x3 row-major rotation -> (x, y, z, w)."""
    t = r[0][0] + r[1][1] + r[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s, 0.25 * s)
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = (0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s, (r[2][1] - r[1][2]) / s)
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = ((r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s, (r[0][2] - r[2][0]) / s)
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = ((r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s, (r[1][0] - r[0][1]) / s)
    return _qnorm(q)


def _quat_to_mat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _mat4_inverse(m):
    """General inverse of a column-major 4x4 (glTF); raises SkinError when singular."""
    a = [[m[c * 4 + r] for c in range(4)] for r in range(4)] + [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    a = [row_a + row_i for row_a, row_i in zip(a[:4], a[4:])]
    for col in range(4):
        piv = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            raise SkinError("singular matrix in the skin (inverse bind matrix or joint transform)")
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [v / d for v in a[col]]
        for r in range(4):
            if r != col:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col])]
    inv = [row[4:] for row in a]
    return [inv[r][c] for c in range(4) for r in range(4)]


def _decompose_rigid(m, what, scale=1.0):
    """Column-major glTF 4x4 -> (engine-space rotation quat, engine-space translation) of a rigid transform times a
    uniform `scale` (the translation is the world position, so it already includes that scale)."""
    cols = [(m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])]
    for c in cols:
        if abs(math.sqrt(sum(v * v for v in c)) / scale - 1.0) > 1e-3:
            raise SkinError("%s has scale in its bind pose; the engine needs an orthonormal bone matrix" % what)
    rot = [[m[0] / scale, m[4] / scale, m[8] / scale], [m[1] / scale, m[5] / scale, m[9] / scale],
           [m[2] / scale, m[6] / scale, m[10] / scale]]
    q = _mat_to_quat(rot)
    t = _cry((m[12], m[13], m[14]))
    return _quat_cry(q), t


def _world_scale(joint_world, names):
    """The uniform scale S shared by the world bind matrices of all joints (1.0 for a rigid skeleton). A scaled ancestor
    above the skeleton (an FBX centimetre wrapper, scale 100) gives every joint the same S; anything else is refused."""
    s0 = None
    for m, nm in zip(joint_world, names):
        for c in ((m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])):
            ln = math.sqrt(sum(v * v for v in c))
            if s0 is None:
                s0 = ln
            if s0 < 1e-9 or abs(ln / s0 - 1.0) > 1e-3:
                raise SkinError("joint %r has scale in its bind pose; the engine needs an orthonormal bone matrix "
                                "(only one uniform scale shared by all joints, from an ancestor, is folded)" % nm)
    if abs(s0 - 1.0) <= 1e-3:
        return 1.0
    return s0


def _rigid_mul(a, b):
    """(q, t) * (q, t): apply b first, then a."""
    qa, ta = a
    qb, tb = b
    r = _qrot(qa, tb)
    return _qnorm(_qmul(qa, qb)), (ta[0] + r[0], ta[1] + r[1], ta[2] + r[2])


def _rigid_inv(a):
    q, t = a
    qi = _qinv(q)
    r = _qrot(qi, t)
    return qi, (-r[0], -r[1], -r[2])


# ------------------------------------------------------------------ import
def import_gltf_skin(path, scale=1.0, fps=FPS):
    """Return dict(bones, positions, normals, uvs, indices, subsets, materials, weights, animations, warnings, asset).

    bones: list of dict(name, parent, q, t) in engine order (parents first, children contiguous), q/t the BIND pose in
    world space (engine axes, metres * scale). weights: per vertex ((id,id,id,id), (w,w,w,w)) with u8 weights summing to 255.
    animations: list of dict(name, frames, tracks) with tracks[bone] = [(position_cm, quat, scale)] bone-relative, 30 Hz."""
    A = gltf.Asset(path)
    d = A.doc
    skins = d.get("skins", [])
    if len(skins) != 1:
        raise SkinError("exactly one skin is supported, the file has %d" % len(skins))
    skin = skins[0]
    joints = skin["joints"]
    if not joints or len(joints) > MAX_BONES:
        raise SkinError("the skin has %d joints (1..%d supported)" % (len(joints), MAX_BONES))
    if len(set(joints)) != len(joints):
        raise SkinError("a joint is listed twice in the skin")
    nodes = d["nodes"]
    parent_of = {}
    for ni, node in enumerate(nodes):
        for c in node.get("children", []):
            parent_of[c] = ni
    joint_set = {n: i for i, n in enumerate(joints)}
    if "inverseBindMatrices" not in skin:
        raise SkinError("the skin has no inverseBindMatrices")
    ibm = A.accessor(skin["inverseBindMatrices"])
    if len(ibm) != len(joints):
        raise SkinError("inverseBindMatrices count differs from the joint count")

    def rest_world(ni):
        m = gltf.mat_identity()
        chain = []
        while ni is not None:
            chain.append(ni)
            ni = parent_of.get(ni)
        for n in reversed(chain):
            m = gltf.mat_mul(m, gltf.node_matrix(nodes[n]))
        return m

    names, used = [], set()
    for j, ni in enumerate(joints):
        base = "".join(ch for ch in (nodes[ni].get("name") or "joint%d" % j) if 32 < ord(ch) < 127) or "joint%d" % j
        base = base[:120]
        nm = base if base.lower() not in used else "%s_%d" % (base, j)
        used.add(nm.lower())
        names.append(nm)

    # The character frame is the scene's world space (glTF 3.7.3.3: the skinned mesh node's own transform cancels, so a
    # vertex lands at joint_world * inverseBind * v). A joint's bind pose is its REST world transform; skinning to it is
    # the identity only when the file is consistent, and real models are not: RiggedFigure hangs skeleton and mesh under
    # a Z_UP node that stands the model up.
    users = [ni for ni, n in enumerate(nodes) if "skin" in n]
    if not users:
        raise SkinError("no node uses the skin")
    if any(nodes[ni]["skin"] != 0 for ni in users):
        raise SkinError("a node refers to a skin that does not exist")
    frame_inv = gltf.mat_identity()
    joint_world = [rest_world(joints[j]) for j in range(len(joints))]
    bind = []
    world_s = _world_scale(joint_world, names)
    if world_s != 1.0:
        A.warnings.append("the skeleton hangs under a node with uniform scale %g: folded into the bone positions and the "
                          "animation keys (bone matrices stay orthonormal)" % world_s)
    for j in range(len(joints)):
        q, t = _decompose_rigid(joint_world[j], "joint %r" % names[j], world_s)
        bind.append((q, tuple(c * scale for c in t)))
    skin_mat = [gltf.mat_mul(joint_world[j], [float(v) for v in ibm[j]]) for j in range(len(joints))]
    identity = gltf.mat_identity()
    consistent = all(max(abs(x - y) for x, y in zip(m, identity)) < 1e-5 for m in skin_mat)
    if not consistent:
        A.warnings.append("the joints' rest pose does not cancel the inverse bind matrices (a transform above the skeleton); vertices were skinned to the rest pose")

    def joint_parent(j):
        ni = parent_of.get(joints[j])
        while ni is not None and ni not in joint_set:
            ni = parent_of.get(ni)
        return joint_set[ni] if ni is not None else -1

    parents = [joint_parent(j) for j in range(len(joints))]
    roots = [j for j in range(len(joints)) if parents[j] < 0]
    ident = (0.0, 0.0, 0.0, 1.0)
    synthetic = len(roots) != 1 or abs(_qnorm(bind[roots[0]][0])[3]) < math.cos(ROOT_TOLERANCE_RAD / 2)
    entries = []        # engine bones before ordering: (name, parent index in entries or -1, q, t, glTF joint or None)
    if synthetic:
        rn = "root" if "root" not in used else "plasmid_root"
        entries.append((rn, -1, ident, (0.0, 0.0, 0.0), None))
        off = 1
        for j in range(len(joints)):
            entries.append((names[j], 0 if parents[j] < 0 else parents[j] + off, bind[j][0], bind[j][1], j))
    else:
        for j in range(len(joints)):
            entries.append((names[j], parents[j], bind[j][0], bind[j][1], j))
    # breadth-first so that the children of every bone are contiguous
    kids = {}
    for i, e in enumerate(entries):
        kids.setdefault(e[1], []).append(i)
    order, queue = [], list(kids.get(-1, []))
    while queue:
        i = queue.pop(0)
        order.append(i)
        queue.extend(kids.get(i, []))
    if len(order) != len(entries):
        raise SkinError("the joint hierarchy has a cycle")
    new_index = {old: new for new, old in enumerate(order)}
    bones = []
    for old in order:
        nm, par, q, t, _j = entries[old]
        bones.append(dict(name=nm, parent=new_index[par] if par >= 0 else -1, q=q, t=t, joint=_j))
    joint_to_bone = {b["joint"]: i for i, b in enumerate(bones) if b["joint"] is not None}

    # mesh: the primitives of every node that uses the skin; skinned vertices are in bind space, the node transform is ignored
    positions, normals, uvs, indices, subsets, mats, weights = [], [], [], [], [], [], []
    for ni in users:
        mesh = d["meshes"][nodes[ni]["mesh"]]
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                raise SkinError("only triangle lists are supported")
            if "targets" in prim:
                raise SkinError("morph targets are not supported")
            at = prim["attributes"]
            if "JOINTS_0" not in at or "WEIGHTS_0" not in at:
                raise SkinError("a primitive of a skinned node has no JOINTS_0/WEIGHTS_0")
            if "JOINTS_1" in at or "WEIGHTS_1" in at:
                raise SkinError("more than 4 influences per vertex (JOINTS_1) are not supported")
            pos = A.accessor(at["POSITION"])
            n = len(pos)
            nor = A.accessor(at["NORMAL"]) if "NORMAL" in at else None
            tex = A.accessor(at["TEXCOORD_0"]) if "TEXCOORD_0" in at else [(0.0, 0.0)] * n
            jt, wt = A.accessor(at["JOINTS_0"]), A.accessor(at["WEIGHTS_0"])
            idx = A.accessor(prim["indices"]) if "indices" in prim else list(range(n))
            if len(idx) % 3 or (idx and max(idx) >= n):
                raise SkinError("bad index buffer")
            if not (len(tex) == len(jt) == len(wt) == n and (nor is None or len(nor) == n)):
                raise SkinError("attribute counts differ")
            if any(i >= len(joints) for ids in jt for i in ids):
                raise SkinError("JOINTS_0 refers to a joint outside the skin")
            norm_w = []
            for ws in wt:
                tot = sum(ws)
                if tot <= 0:
                    raise SkinError("a vertex has no weight")
                norm_w.append([w / tot for w in ws])
            if not consistent:
                pos, nor = _skin_to_rest(pos, nor, jt, norm_w, skin_mat)
            if nor is None:
                nor = _smooth_normals(pos, idx)
                A.warnings.append("a primitive had no NORMAL: smooth normals were generated")
            base, first = len(positions), len(indices)
            positions.extend(tuple(c * scale for c in _cry(p)) for p in pos)
            normals.extend(_cry(v) for v in nor)
            uvs.extend((float(u[0]), float(u[1])) for u in tex)
            indices.extend(base + i for i in idx)
            for ids, f in zip(jt, norm_w):
                q8 = [int(round(x * 255)) for x in f]
                q8[q8.index(max(q8))] += 255 - sum(q8)
                for k in range(4):
                    if q8[k] and ids[k] not in joint_to_bone:
                        raise SkinError("a vertex is weighted to a joint outside the skin")
                weights.append((tuple(joint_to_bone.get(ids[k], 0) if q8[k] else 0 for k in range(4)), tuple(q8)))
            mat = prim.get("material")
            if mat not in mats:
                mats.append(mat)
            subsets.append((first, len(idx), mats.index(mat)))
    if not indices:
        raise SkinError("no skinned triangles found")
    _check_winding(A, positions, normals, indices)
    if len(positions) > MAX_VERTICES:
        raise SkinError("%d vertices; at most %d are supported (16-bit indices)" % (len(positions), MAX_VERTICES))

    animations = _import_animations(A, bones, joints, joint_set, parent_of, rest_world, frame_inv, scale, fps, world_s)
    return dict(bones=bones, positions=positions, normals=normals, uvs=uvs, indices=indices, subsets=subsets,
                materials=mats, weights=weights, animations=animations, warnings=A.warnings, asset=A)


def _skin_to_rest(pos, nor, jt, norm_w, skin_mat):
    """Blend each vertex (and normal) through its joints' skin matrices (inverse(meshNode) * joint * inverseBind)."""
    out_p, out_n = [], ([] if nor is not None else None)
    for i, (p, ids, f) in enumerate(zip(pos, jt, norm_w)):
        x = y = z = 0.0
        nx = ny = nz = 0.0
        for k in range(4):
            if f[k] <= 0.0:
                continue
            m = skin_mat[ids[k]]
            q = gltf.xform_point(m, p)
            x, y, z = x + f[k] * q[0], y + f[k] * q[1], z + f[k] * q[2]
            if nor is not None:
                v = nor[i]
                nx += f[k] * (m[0] * v[0] + m[4] * v[1] + m[8] * v[2])
                ny += f[k] * (m[1] * v[0] + m[5] * v[1] + m[9] * v[2])
                nz += f[k] * (m[2] * v[0] + m[6] * v[1] + m[10] * v[2])
        out_p.append((x, y, z))
        if out_n is not None:
            out_n.append(gltf.normalize((nx, ny, nz)))
    return out_p, out_n


def _smooth_normals(pos, idx):
    """Area-weighted vertex normals for a primitive that has none."""
    acc = [[0.0, 0.0, 0.0] for _ in pos]
    for t in range(0, len(idx), 3):
        a, b, c = idx[t], idx[t + 1], idx[t + 2]
        u = [pos[b][k] - pos[a][k] for k in range(3)]
        w = [pos[c][k] - pos[a][k] for k in range(3)]
        fn = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        for v in (a, b, c):
            for k in range(3):
                acc[v][k] += fn[k]
    return [gltf.normalize(tuple(v)) for v in acc]


def _check_winding(A, positions, normals, indices):
    """Warn when most triangles are wound against their vertex normals: the engine then lights the inside faces
    (the drawn surface is the far wall seen from within, with flipped normals) and the character looks black or inverted."""
    bad = total = 0
    for t in range(0, len(indices), 3):
        a, b, c = indices[t], indices[t + 1], indices[t + 2]
        u = [positions[b][k] - positions[a][k] for k in range(3)]
        w = [positions[c][k] - positions[a][k] for k in range(3)]
        fn = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        nn = [sum(normals[v][k] for v in (a, b, c)) for k in range(3)]
        if sum(fn[k] * nn[k] for k in range(3)) < 0:
            bad += 1
        total += 1
    if total and bad * 2 > total:
        A.warnings.append("%d of %d triangles are wound against their normals; the engine will light the inside faces "
                          "(black or inverted look). glTF wants counter-clockwise front faces." % (bad, total))


def _node_trs(node):
    """(translation, rotation xyzw, scale) of a node, from its TRS or by decomposing its matrix (no shear)."""
    if "matrix" not in node:
        return (tuple(node.get("translation", (0.0, 0.0, 0.0))), tuple(node.get("rotation", (0.0, 0.0, 0.0, 1.0))),
                tuple(node.get("scale", (1.0, 1.0, 1.0))))
    m = [float(v) for v in node["matrix"]]
    cols = [(m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])]
    sc = [math.sqrt(sum(v * v for v in c)) or 1.0 for c in cols]
    rot = [[cols[c][r] / sc[c] for c in range(3)] for r in range(3)]
    return (m[12], m[13], m[14]), _mat_to_quat(rot), tuple(sc)


def _import_animations(A, bones, joints, joint_set, parent_of, rest_world, frame_inv, scale, fps, world_s=1.0):
    d = A.doc
    nodes = d["nodes"]
    out = []
    for ai, anim in enumerate(d.get("animations", [])):
        chans = {}
        t_end = 0.0
        for ch in anim.get("channels", []):
            tgt = ch["target"]
            ni, path = tgt.get("node"), tgt.get("path")
            if ni not in joint_set:
                A.warnings.append("animation %d: a channel targets a node outside the skin and was ignored" % ai)
                continue
            if path not in ("translation", "rotation", "scale"):
                raise SkinError("animation %d: channel path %r is not supported" % (ai, path))
            s = anim["samplers"][ch["sampler"]]
            if s.get("interpolation", "LINEAR") not in ("LINEAR", "STEP"):
                raise SkinError("animation %d: only LINEAR and STEP interpolation are supported" % ai)
            times = A.accessor(s["input"])
            vals = A.accessor(s["output"])
            if len(times) != len(vals) or not times:
                raise SkinError("animation %d: sampler input/output lengths differ" % ai)
            chans[(ni, path)] = (list(times), list(vals), s.get("interpolation", "LINEAR") == "STEP")
            t_end = max(t_end, times[-1])
        if not chans:
            A.warnings.append("animation %d has no usable channel and was skipped" % ai)
            continue
        frames = max(2, int(round(t_end * fps)) + 1)

        def sample(key, default, t, is_quat):
            if key not in chans:
                return default
            times, vals, step = chans[key]
            if t <= times[0]:
                return tuple(vals[0]) if isinstance(vals[0], tuple) else (vals[0],)
            if t >= times[-1]:
                return tuple(vals[-1])
            k = max(i for i in range(len(times)) if times[i] <= t)
            if step:
                return tuple(vals[k])
            u = (t - times[k]) / (times[k + 1] - times[k])
            if is_quat:
                return _slerp(_qnorm(tuple(vals[k])), _qnorm(tuple(vals[k + 1])), u)
            return tuple(a + (b - a) * u for a, b in zip(vals[k], vals[k + 1]))

        tracks = {}
        bone_of = {b["joint"]: i for i, b in enumerate(bones) if b["joint"] is not None}
        for ni, jidx in joint_set.items():
            node = nodes[ni]
            rest_t, rest_q, rest_s = _node_trs(node)
            bi = bone_of[jidx]
            par_bone = bones[bi]["parent"]
            frames_out = []
            for f in range(frames):
                t = f / fps
                tr = sample((ni, "translation"), rest_t, t, False)
                ro = sample((ni, "rotation"), rest_q, t, True)
                sc = sample((ni, "scale"), rest_s, t, False)
                q, p = _quat_cry(_qnorm(tuple(ro))), tuple(c * scale * world_s for c in _cry(tr))
                # a joint whose glTF parent is not a joint: fold the rest transform of the non-joint ancestors in
                gpar = parent_of.get(ni)
                if gpar is not None and gpar not in joint_set:
                    anc = gltf.mat_mul(frame_inv, rest_world(gpar))
                    aq, at_ = _decompose_rigid_loose(anc)
                    q, p = _rigid_mul((aq, tuple(c * scale for c in at_)), (q, p))
                frames_out.append((tuple(100.0 * c for c in p), q, tuple(sc)))
            tracks[bi] = frames_out
        for bi, b in enumerate(bones):
            if b["joint"] is None:      # the synthetic root
                tracks[bi] = [((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))] * frames
        if bones[0]["joint"] is not None:      # joint 0 is the locator: its keys are root motion, so keep it at its bind pose
            if any(k[0] == joints[bones[0]["joint"]] for k in chans):
                A.warnings.append("animation %d: the root joint's keys are root motion in the engine and were replaced by its bind pose" % ai)
            tracks[0] = [(tuple(100.0 * c for c in bones[0]["t"]), bones[0]["q"], (1.0, 1.0, 1.0))] * frames
        out.append(dict(name=anim.get("name") or "anim%d" % ai, frames=frames, tracks=tracks))
    return out


def _decompose_rigid_loose(m):
    """Like _decompose_rigid for an ancestor chain; scale is dropped with a clean rotation (axes are normalised)."""
    cols = [(m[0], m[1], m[2]), (m[4], m[5], m[6]), (m[8], m[9], m[10])]
    cols = [tuple(v / (math.sqrt(sum(x * x for x in c)) or 1.0) for v in c) for c in cols]
    rot = [[cols[0][0], cols[1][0], cols[2][0]], [cols[0][1], cols[1][1], cols[2][1]], [cols[0][2], cols[1][2], cols[2][2]]]
    return _quat_cry(_mat_to_quat(rot)), _cry((m[12], m[13], m[14]))


# ------------------------------------------------------------------ chunk writers
def _mat34(q, t):
    r = _quat_to_mat(q)
    vals = (r[0][0], r[0][1], r[0][2], t[0], r[1][0], r[1][1], r[1][2], t[1], r[2][0], r[2][1], r[2][2], t[2])
    return struct.pack("<12f", *[v + 0.0 for v in vals])      # + 0.0 turns -0.0 into 0.0: canonical bytes


def _phys_comp():
    # CryBonePhysics_Comp: i32 physGeom, i32 flags, min3 max3 springAngle3 springTension3 damping3, framemtx 3x3
    return struct.pack("<2i15f9f", -1, -1, *([0.0] * 15), 1, 0, 0, 0, 1, 0, 0, 0, 1)


def _crc(name):
    return zlib.crc32(name.lower().encode("ascii")) & 0xFFFFFFFF


def compiled_bones(bones):
    kids = {}
    for i, b in enumerate(bones):
        kids.setdefault(b["parent"], []).append(i)
    body = bytes(32)
    for i, b in enumerate(bones):
        k = kids.get(i, [])
        qi, ti = _rigid_inv((b["q"], b["t"]))
        body += struct.pack("<I", _crc(b["name"])) + _phys_comp() + _phys_comp() + struct.pack("<f", 0.0)
        body += _mat34(qi, ti) + _mat34(b["q"], b["t"])
        body += b["name"].encode("ascii").ljust(256, b"\0")
        body += struct.pack("<iiIi", -1, (b["parent"] - i) if b["parent"] >= 0 else 0, len(k), (k[0] - i) if k else 0)
    return body


def compiled_phys_bones(bones):
    kids = {}
    for b in bones:
        kids[b["parent"]] = kids.get(b["parent"], 0) + 1
    body = bytes(32)
    for i, b in enumerate(bones):
        body += struct.pack("<iiiI32s", i, b["parent"], kids.get(i, 0), _crc(b["name"]), b"") + _phys_comp()
    return body


def skin_chunks(bones, positions, indices, weights):
    nv = len(positions)
    ivs = bytes(32)
    for p, (ids, w) in zip(positions, weights):
        ivs += struct.pack("<9f4H4f4B", 0, 0, 0, *p, 0, 0, 0, *ids, *[x / 255.0 for x in w], 255, 255, 255, 7)
    faces = b"".join(struct.pack("<3H", *indices[k:k + 3]) for k in range(0, len(indices), 3))
    out = [(T_COMPILED_BONES, 0x800, compiled_bones(bones)), (T_COMPILED_PHYS_BONES, 0x800, compiled_phys_bones(bones)),
           (T_INT_SKIN_VERTS, 0x800, ivs), (T_INT_FACES, 0x800, faces),
           (T_EXT2INT, 0x800, struct.pack("<%dH" % nv, *range(nv)))]
    for b in range(len(bones)):
        used = [i for i, (ids, w) in enumerate(weights) if any(ids[j] == b and w[j] for j in range(4))]
        pts = [positions[i] for i in used] or [(0.0, 0.0, 0.0)]
        lo = [min(p[k] for p in pts) for k in range(3)]
        hi = [max(p[k] for p in pts) for k in range(3)]
        out.append((T_BONES_BOXES, 0x801, struct.pack("<i6fi%dh" % len(used), b, *lo, *hi, len(used), *used)))
    return out


def mesh_chunks(positions, normals, uvs, indices, subsets, weights, mtl_name):
    """The static-mesh chunks of cgf.py plus a BONEMAPPING stream (u16 ids[4] + u8 weights[4] per vertex)."""
    blob = cgf.build_static_mesh(positions, normals, uvs, indices, subsets, mtl_name)
    count = struct.unpack_from("<I", blob, 8)[0]
    table = struct.unpack_from("<I", blob, 12)[0]
    chunks = []
    for i in range(count):
        t, v, cid, size, off = struct.unpack_from("<HHIII", blob, table + 16 * i)
        chunks.append([t, v, cid, blob[off:off + size]])
    bonemap = b"".join(struct.pack("<4H4B", *ids, *w) for ids, w in weights)
    chunks.insert(-2, [cgf.T_DATASTREAM, cgf.V_DATASTREAM, ID_BONEMAP,
                       cgf._datastream_body(STREAM_BONEMAPPING, len(positions), 12, bonemap)])
    for c in chunks:
        if c[0] == cgf.T_MESH:
            body = bytearray(c[3])
            struct.pack_into("<i", body, 7 * 4 + STREAM_BONEMAPPING * 4, ID_BONEMAP)
            c[3] = bytes(body)
    return [tuple(c) for c in chunks]


def assemble(chunks):
    """chunks: (type, version, body) or (type, version, id, body); ids are assigned (from 100) where missing."""
    norm, next_id = [], 100
    for c in chunks:
        if len(c) == 3:
            norm.append((c[0], c[1], next_id, c[2]))
            next_id += 1
        else:
            norm.append(tuple(c))
    offset = 16 + 16 * len(norm)
    table, data = bytearray(), bytearray()
    for t, v, cid, body in norm:
        table += struct.pack("<HHIII", t, v, cid, len(body), offset)
        data += body
        offset += len(body)
    return struct.pack("<4sIII", b"CrCh", 0x746, len(norm), 16) + bytes(table) + bytes(data)


def build_skin(rig, mtl_name):
    return assemble(mesh_chunks(rig["positions"], rig["normals"], rig["uvs"], rig["indices"], rig["subsets"],
                                rig["weights"], mtl_name)
                    + skin_chunks(rig["bones"], rig["positions"], rig["indices"], rig["weights"]))


def build_chr(rig, mtl_name):
    """The skeleton file: the bone chunks plus a one-triangle proxy mesh (the loader requires a mesh with BONEMAPPING)."""
    tri = rig["indices"][0:3]
    pos = [rig["positions"][i] for i in tri]
    nor = [rig["normals"][i] for i in tri]
    uv = [rig["uvs"][i] for i in tri]
    wt = [rig["weights"][i] for i in tri]
    return assemble(mesh_chunks(pos, nor, uv, [0, 1, 2], None, wt, mtl_name)
                    + skin_chunks(rig["bones"], pos, [0, 1, 2], wt))


def build_caf(anim, bones):
    """Uncompressed CAF: Timing 0x0919, MotionParameters 0x0922, one Controller 0x0833 per bone (positions in cm)."""
    chunks = [(T_TIMING, 0x0919, struct.pack("<iff", anim["frames"], FPS, 0.0)),
              (T_MOTION_PARAMS, 0x0922, struct.pack("<3fI3f4f3f", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0))]
    for bi, b in enumerate(bones):
        keys = b"".join(struct.pack("<3f4f3f", *p, *q, *s) for p, q, s in anim["tracks"][bi])
        chunks.append((T_CONTROLLER, 0x0833, struct.pack("<II", anim["frames"], _crc(b["name"])) + keys))
    return assemble(chunks)


def build_cdf(game_dir, name, mtl_ref):
    return ('<CharacterDefinition>\n <Model File="%s/%s.chr" Material="%s"/>\n <AttachmentList>\n'
            '  <Attachment Type="CA_SKIN" AName="body" Binding="%s/%s.skin" Material="%s.mtl" Flags="0"/>\n'
            ' </AttachmentList>\n</CharacterDefinition>\n' % (game_dir, name, mtl_ref, game_dir, name, mtl_ref))


def build_chrparams(game_dir, anim_files):
    """anim_files: list of (animation name, file name). A bare path is looked up under animations/, so #filepath is set."""
    rows = ['  <Animation name="#filepath" path="%s"/>\n' % game_dir]
    rows += ['  <Animation name="%s" path="%s"/>\n' % (n, f) for n, f in anim_files]
    return "<Params>\n <AnimationList>\n" + "".join(rows) + " </AnimationList>\n</Params>\n"


def _file_stem(text):
    keep = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in text)
    return keep.strip("_") or "anim"


def convert_skin(src, out_dir, game_dir, name, scale=1.0, jobs=1, cache_dir=None, material_options=None):
    """Write <name>.chr/.skin/.cdf/.chrparams/.mtl, one <name>_<anim>.caf per animation and the textures. Returns a manifest."""
    rig = import_gltf_skin(src, scale)
    os.makedirs(out_dir, exist_ok=True)
    game_dir = game_dir.strip("/")
    opts = material_options if material_options is not None else MaterialOptions()
    textures = gltf.convert_textures(rig["asset"], out_dir, name, jobs, cache_dir, emissive=opts.pbr,
                                     bake=opts.pbr and opts.bake, warnings=opts.warnings, ao=opts.ao,
                                     occlusion=opts.pbr and opts.occlusion_map)
    gltf.write_mtl(os.path.join(out_dir, name + ".mtl"), game_dir, name, rig["asset"].doc, rig["materials"], textures,
                   rig["asset"], material_options)
    mtl_ref = game_dir + "/" + name
    files = {name + ".chr": build_chr(rig, mtl_ref), name + ".skin": build_skin(rig, mtl_ref)}
    anim_files, seen = [], set()
    for a in rig["animations"]:
        stem = _file_stem(a["name"])
        if stem.lower() in seen:
            stem = "%s_%d" % (stem, len(seen))
        seen.add(stem.lower())
        fname = "%s_%s.caf" % (name, stem)
        files[fname] = build_caf(a, rig["bones"])
        anim_files.append((stem, fname))
    for fname, blob in files.items():
        with open(os.path.join(out_dir, fname), "wb") as f:
            f.write(blob)
    with open(os.path.join(out_dir, name + ".cdf"), "w") as f:
        f.write(build_cdf(game_dir, name, mtl_ref))
    with open(os.path.join(out_dir, name + ".chrparams"), "w") as f:
        f.write(build_chrparams(game_dir, anim_files))
    return dict(chr=name + ".chr", skin=name + ".skin", cdf=name + ".cdf", chrparams=name + ".chrparams",
                bones=[b["name"] for b in rig["bones"]], vertices=len(rig["positions"]),
                animations=[dict(name=n, file=f, frames=a["frames"]) for (n, f), a in zip(anim_files, rig["animations"])],
                textures=textures, material=mtl_ref,
                warnings=rig["warnings"] + (material_options.warnings if material_options else []))
