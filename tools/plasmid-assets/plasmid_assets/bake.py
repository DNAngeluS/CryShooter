"""Per-texel bake of a glTF metallic-roughness material into the maps the Illum shader reads.

glTF stores metalness (B) and roughness (G) per texel; Illum has a specular-colour workflow: a diffuse texture, a `_spec`
reflectance texture (the shader multiplies the `Specular` attribute by it and needs `%SPECULAR_MAP`) and a smoothness that
lives in the alpha attached to the normal map (`_ddna`, see dds.attached_alpha_chunk). For one material this module writes,
all in linear light and sRGB-encoded where the engine expects sRGB:

    diffuse   base x baseColorFactor x (1 - m)                       `<name>_m<N>_d.dds`     BC1 (BC3 with alpha), sRGB
    specular  0.04 + (base x baseColorFactor - 0.04) x m             `<name>_m<N>_spec.dds`  BC1, sRGB
    gloss     1 - r  (the attached alpha of the normal map)          `<name>_m<N>_ddna.dds`  BC5_SNORM + BC4 gloss

with m = metallicFactor x B, r = roughnessFactor x G (the red channel, a packed occlusion, is ignored). The material then
carries `Diffuse="1,1,1" Specular="1,1,1" Shininess="255"` (what 156 of the 311 GameSDK-Island materials with a spec map
carry), so the maps drive everything. Without a normalTexture the `_ddna` holds a neutral normal map at the size of the bake.

Anything the bake cannot honour (a non-PNG image, a texCoord other than 0, KHR_texture_transform) raises Unbakeable; the
caller then falls back to the mean approximation of materials.py and says so.
"""

import hashlib
import os
import tempfile

from . import dds as dds_mod
from .cache import write_lazy
from .materials import DIELECTRIC_F0
from .png import read_png

BAKE_VERSION = 1   # part of every cache key: change it when the maths changes


class Unbakeable(Exception):
    pass


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(v):
    v = 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055


DECODE = [_srgb_to_linear(i / 255.0) for i in range(256)]
_ENC_N = 4096
ENCODE = bytes(min(255, int(round(_linear_to_srgb(i / (_ENC_N - 1)) * 255.0))) for i in range(_ENC_N))


def encode(v):
    """Linear 0..1 to an sRGB byte."""
    v = 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
    return ENCODE[int(v * (_ENC_N - 1) + 0.5)]


def decode_png(png):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.png")
        with open(path, "wb") as f:
            f.write(png)
        return read_png(path)


def resample(px, w, h, W, H, channels=4):
    """Bilinear resample (texel centres, clamped edges) of an interleaved `channels` bytes/pixel image to W x H."""
    if (w, h) == (W, H):
        return px
    out = bytearray(W * H * channels)
    xs = []
    for X in range(W):
        fx = (X + 0.5) * w / W - 0.5
        x0 = int(fx // 1)
        t = fx - x0
        xs.append((min(max(x0, 0), w - 1), min(max(x0 + 1, 0), w - 1), t))
    for Y in range(H):
        fy = (Y + 0.5) * h / H - 0.5
        y0 = int(fy // 1)
        u = fy - y0
        r0 = min(max(y0, 0), h - 1) * w
        r1 = min(max(y0 + 1, 0), h - 1) * w
        o = Y * W * channels
        for x0, x1, t in xs:
            for c in range(channels):
                a = px[(r0 + x0) * channels + c] * (1 - t) + px[(r0 + x1) * channels + c] * t
                b = px[(r1 + x0) * channels + c] * (1 - t) + px[(r1 + x1) * channels + c] * t
                out[o] = int(a * (1 - u) + b * u + 0.5)
                o += 1
    return bytes(out)


def occlusion_pixels(px, strength):
    """glTF occlusionTexture on RGBA bytes: only R counts; the shader samples R and multiplies the indirect light by it, so
    strength is baked here as 1 + strength * (r - 1) (the glTF formula). Returns RGBA with R replaced (G, B, A unused)."""
    out = bytearray(len(px))
    for o in range(0, len(px), 4):
        r = px[o] / 255.0
        v = int(round(max(0.0, min(1.0, 1.0 + strength * (r - 1.0))) * 255.0))
        out[o] = v
        out[o + 3] = 255
    return bytes(out)


def scale_normals(px, scale):
    """glTF normalTexture.scale on RGBA bytes: n = normalize((rgb * 2 - 1) * (scale, scale, 1)), written back to R, G, B.
    The signed maps the engine reads rebuild z from x and y, so the result is always a unit vector."""
    out = bytearray(px)
    for o in range(0, len(px), 4):
        x = (px[o] * 2.0 - 255.0) / 255.0 * scale
        y = (px[o + 1] * 2.0 - 255.0) / 255.0 * scale
        z = (px[o + 2] * 2.0 - 255.0) / 255.0
        n = (x * x + y * y + z * z) ** 0.5 or 1.0
        out[o] = int(round((x / n * 0.5 + 0.5) * 255.0))
        out[o + 1] = int(round((y / n * 0.5 + 0.5) * 255.0))
        out[o + 2] = int(round((z / n * 0.5 + 0.5) * 255.0))
    return bytes(out)


def _ref_png(A, ref, what):
    """PNG bytes of a glTF textureInfo, or Unbakeable."""
    if ref.get("texCoord", 0) != 0:
        raise Unbakeable("%s uses TEXCOORD_%d, only TEXCOORD_0 is baked" % (what, ref["texCoord"]))
    if "KHR_texture_transform" in ref.get("extensions", {}):
        raise Unbakeable("%s has KHR_texture_transform" % what)
    try:
        tex = A.doc["textures"][ref["index"]]
        return A.image_png(tex["source"])
    except Exception as e:                       # GltfError for a non-PNG, KeyError for a broken reference
        raise Unbakeable("%s unreadable: %s" % (what, e))


def can_bake(mat, ao=False):
    """A metallicRoughnessTexture is baked per texel; so is an occlusionTexture when `ao` asks for it (opt-in: Illum has no
    occlusion map, the bake multiplies it into the diffuse, which darkens direct light too)."""
    return "metallicRoughnessTexture" in mat.get("pbrMetallicRoughness", {}) or (ao and "occlusionTexture" in mat)


def bake_pixels(base, bw, bh, mr, mw, mh, base_factor, m_factor, r_factor, keep_alpha, ao=None, aw=0, ah=0, ao_strength=1.0):
    """Per-texel maths at W x H = the largest of the textures. base is None for a material without a baseColorTexture, mr
    for one without a metallicRoughnessTexture (the factors alone), ao for one baked without occlusion (else the R channel
    scales the diffuse by 1 + strength x (o - 1), the glTF occlusion formula).
    Returns (W, H, diffuse rgba, specular rgba, gloss bytes)."""
    sizes = [(w, h) for t, w, h in ((base, bw, bh), (mr, mw, mh), (ao, aw, ah)) if t is not None]
    W, H = max(w for w, _ in sizes), max(h for _, h in sizes)
    mrr = resample(mr, mw, mh, W, H) if mr is not None else None
    bsr = resample(base, bw, bh, W, H) if base is not None else None
    aor = resample(ao, aw, ah, W, H) if ao is not None else None
    fr, fg, fb, fa = base_factor
    n = W * H
    diff = bytearray(n * 4)
    spec = bytearray(n * 4)
    gloss = bytearray(n)
    for i in range(n):
        o = i * 4
        m = m_factor * (mrr[o + 2] / 255.0 if mrr is not None else 1.0)
        m = 0.0 if m < 0.0 else 1.0 if m > 1.0 else m
        r = r_factor * (mrr[o + 1] / 255.0 if mrr is not None else 1.0)
        r = 0.0 if r < 0.0 else 1.0 if r > 1.0 else r
        gloss[i] = int(round((1.0 - r) * 255.0))
        if bsr is not None:
            br, bg, bb = DECODE[bsr[o]] * fr, DECODE[bsr[o + 1]] * fg, DECODE[bsr[o + 2]] * fb
            a = bsr[o + 3] if keep_alpha else 255
        else:
            br, bg, bb, a = fr, fg, fb, 255
        k = 1.0 - m
        if aor is not None:
            k *= 1.0 + ao_strength * (aor[o] / 255.0 - 1.0)
        diff[o] = encode(br * k)
        diff[o + 1] = encode(bg * k)
        diff[o + 2] = encode(bb * k)
        diff[o + 3] = a
        spec[o] = encode(DIELECTRIC_F0 + (br - DIELECTRIC_F0) * m)
        spec[o + 1] = encode(DIELECTRIC_F0 + (bg - DIELECTRIC_F0) * m)
        spec[o + 2] = encode(DIELECTRIC_F0 + (bb - DIELECTRIC_F0) * m)
        spec[o + 3] = 255
    return W, H, bytes(diff), bytes(spec), bytes(gloss)


def bake_material(A, mi, mat, name, out_dir, game_dir_unused=None, cache_dir=None, jobs=1, ao=False):
    """Bake material `mi`; returns manifest entries (slots baseColor, specular, normal) or raises Unbakeable."""
    pbr = mat.get("pbrMetallicRoughness", {})
    mr_png = _ref_png(A, pbr["metallicRoughnessTexture"], "metallicRoughnessTexture") if "metallicRoughnessTexture" in pbr else None
    ao_ref = mat.get("occlusionTexture") if ao else None
    ao_png = _ref_png(A, ao_ref, "occlusionTexture") if ao_ref else None
    ao_strength = float(ao_ref.get("strength", 1.0)) if ao_ref else 1.0
    base_ref = pbr.get("baseColorTexture")
    base_png = _ref_png(A, base_ref, "baseColorTexture") if base_ref else None
    nrm_ref = mat.get("normalTexture")
    nrm_png = _ref_png(A, nrm_ref, "normalTexture") if nrm_ref else None
    nscale = float(nrm_ref.get("scale", 1.0)) if nrm_ref else 1.0
    factor = [float(c) for c in pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])]
    mf, rf = float(pbr.get("metallicFactor", 1.0)), float(pbr.get("roughnessFactor", 1.0))
    keep_alpha = mat.get("alphaMode", "OPAQUE") in ("BLEND", "MASK")
    parts = [b"bake%d" % BAKE_VERSION, repr((factor, mf, rf, keep_alpha)).encode(), hashlib.sha256(mr_png or b"-").digest(),
             hashlib.sha256(base_png or b"-").digest(), hashlib.sha256(nrm_png or b"-").digest()] + ([b"nscale%r" % nscale] if nscale != 1.0 else []) \
        + ([b"ao%r" % ao_strength, hashlib.sha256(ao_png).digest()] if ao_png else [])

    state = {}

    def pixels():
        if "px" not in state:
            mrt = decode_png(mr_png) if mr_png else None
            base = decode_png(base_png) if base_png else None
            aot = decode_png(ao_png) if ao_png else None
            state["px"] = bake_pixels(base[2] if base else None, base[0] if base else 0, base[1] if base else 0,
                                      mrt[2] if mrt else None, mrt[0] if mrt else 0, mrt[1] if mrt else 0,
                                      factor, mf, rf, keep_alpha,
                                      aot[2] if aot else None, aot[0] if aot else 0, aot[1] if aot else 0, ao_strength)
        return state["px"]

    alpha_used = keep_alpha and base_png is not None
    entries = []

    def emit(slot, fname, fmt, parts_extra, make, srgb):
        path = os.path.join(out_dir, fname)
        w, h, mips, size = write_lazy(path, parts + [parts_extra], make, fmt, cache_dir, srgb=srgb, jobs=jobs)
        entries.append(dict(material=mi, slot=slot, image=None, dds=fname, format=fmt, width=w, height=h, mips=mips,
                            bytes=size, baked=True))

    emit("baseColor", "%s_m%d_d.dds" % (name, mi), "bc3" if alpha_used else "bc1", b"diffuse",
         lambda: (pixels()[0], pixels()[1], pixels()[2], None), True)
    emit("specular", "%s_m%d_spec.dds" % (name, mi), "bc1", b"specular",
         lambda: (pixels()[0], pixels()[1], pixels()[3], None), True)

    def ddna():
        W, H, _d, _s, gloss = pixels()
        if nrm_png:
            nw, nh, npx = decode_png(nrm_png)
            if nscale != 1.0:
                npx = scale_normals(npx, nscale)
        else:
            nw, nh, npx = W, H, bytes((128, 128, 255, 255)) * (W * H)
        return nw, nh, npx, resample(gloss, W, H, nw, nh, 1)
    emit("normal", "%s_m%d_ddna.dds" % (name, mi), "bc5s", b"ddna", ddna, False)
    return entries
