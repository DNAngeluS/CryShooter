"""glTF material -> CRYENGINE Illum material parameters (scalar form; textures are not baked).

Why this exists (engine-proven 2026-10-30, docs/findings/2026-10-30-materials-lighting in the sandbox): the Illum shader gets
its reflectance from the material's `Specular` colour (linear F0) and its smoothness from `Shininess` (0..255), both 0 by
default. A material that only carries a diffuse texture is therefore pure Lambert: no highlight from any light (a point
light's `specular` multiplier has nothing to scale), no probe reflections. glTF carries metallic and roughness; CRYENGINE
uses a specular-colour workflow, so:

    Diffuse   = baseColor * (1 - metallic)
    Specular  = lerp(0.04, baseColor, metallic)       linear, no gamma (the shader constants take the XML value as is)
    Shininess = (1 - roughness) * 255                 the shader divides by 255 and clamps at 2/255
    Emittance = emissiveFactor, intensity             the shader multiplies rgb by intensity / 10
    occlusionTexture                                  a BC4 map in the Custom slot + %OCCLUSION_MAP (the sandbox shader extension, engine-ext/):
                                                      R scales the indirect light only, strength is baked into the texels (see gltf.py)

A metallicRoughness texture cannot be evaluated per texel here; its mean over a coarse grid scales the factors (a warning says
so). A material without a pbrMetallicRoughness block keeps the old matte result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DIELECTRIC_F0 = 0.04
GRID = 64                      # samples per side when averaging a metallicRoughness texture
EMITTANCE_DEFAULT = 10.0       # emissiveFactor 1.0 reads about as bright as an albedo-1 surface (rgb * intensity / 10)


@dataclass
class MaterialOptions:
    pbr: bool = True                        # False: the 0.9.1 output (Diffuse colour and textures only)
    opaque: object = None                   # None, "all", or a set of glTF material names forced to Opacity 1
    emissive_intensity: float = EMITTANCE_DEFAULT
    ao: bool = False                        # bake an occlusionTexture into the diffuse (bake.py); False: ignored with a warning
    occlusion_map: bool = True              # write an occlusionTexture as a BC4 map for %OCCLUSION_MAP (needs the sandbox shader extension); --no-occlusion-map: ignore it
    bake: bool = True                       # bake a metallicRoughnessTexture per texel (bake.py); False: the 0.13.0 mean approximation
    warnings: list = field(default_factory=list)


def _clamp01(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def texture_means(asset, tex_ref, channels):
    """Mean of the given channels (0=R..3=A, each 0..1) of a glTF texture over a GRID x GRID sample; None if unreadable."""
    from .png import read_png
    import os
    import tempfile
    try:
        tex = asset.doc["textures"][tex_ref["index"]]
        png = asset.image_png(tex["source"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.png")
            open(path, "wb").write(png)
            w, h, px = read_png(path)
    except Exception:
        return None
    sums, n = [0.0] * len(channels), 0
    for j in range(GRID):
        y = min(h - 1, int((j + 0.5) * h / GRID))
        for i in range(GRID):
            x = min(w - 1, int((i + 0.5) * w / GRID))
            o = (y * w + x) * 4
            for k, c in enumerate(channels):
                sums[k] += px[o + c] / 255.0
            n += 1
    return [s / n for s in sums]


def illum_params(mat, asset, options, baked=False):
    """Return dict(diffuse, specular|None, shininess|None, emittance|None, opacity, alpha_test|None) for glTF material `mat`
    (a dict, or {} for a primitive without a material). Warnings go to options.warnings."""
    label = mat.get("name", "material")
    pbr = mat.get("pbrMetallicRoughness")
    bc = (pbr or {}).get("baseColorFactor", [1.0, 1.0, 1.0, 1.0])
    base = [_clamp01(c) for c in bc[:3]]
    out = {"diffuse": list(base), "specular": None, "shininess": None, "emittance": None,
           "opacity": 1.0, "alpha_test": None}

    mode = mat.get("alphaMode", "OPAQUE")
    forced = options.opaque == "all" or (isinstance(options.opaque, (set, frozenset)) and mat.get("name") in options.opaque)
    if mode == "BLEND" and not forced:
        out["opacity"] = bc[3] if len(bc) > 3 else 1.0
    elif mode == "MASK":
        out["alpha_test"] = mat.get("alphaCutoff", 0.5)
    # OPAQUE: alpha is ignored (glTF); a forced-opaque BLEND material is opaque too

    if baked:
        # the diffuse, `_spec` and `_ddna` maps carry the whole PBR result (bake.py): neutral scalars, as in the Island materials
        out["diffuse"], out["specular"], out["shininess"] = [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], 255
    elif options.pbr and pbr is not None:
        m = pbr.get("metallicFactor", 1.0)
        r = pbr.get("roughnessFactor", 1.0)
        if "metallicRoughnessTexture" in pbr:
            means = texture_means(asset, pbr["metallicRoughnessTexture"], (1, 2)) if asset is not None else None
            if means is None:
                options.warnings.append("material %r: metallicRoughnessTexture unreadable, factors only" % label)
            else:
                r, m = r * means[0], m * means[1]          # glTF: roughness in G, metalness in B
                options.warnings.append("material %r: metallicRoughnessTexture approximated by its mean (metallic %.2f, "
                                        "roughness %.2f), not per texel" % (label, m, r))
        m, r = _clamp01(m), _clamp01(r)
        out["diffuse"] = [c * (1.0 - m) for c in base]
        out["specular"] = [DIELECTRIC_F0 + (c - DIELECTRIC_F0) * m for c in base]
        out["shininess"] = int(round((1.0 - r) * 255.0))

    if "occlusionTexture" in mat and not (baked and options.ao) and not (options.pbr and options.occlusion_map):
        options.warnings.append("material %r: occlusionTexture ignored (--no-occlusion-map, or --no-pbr; --bake-ao multiplies it "
                                "into the diffuse instead)" % label)

    emissive = mat.get("emissiveFactor")
    if options.pbr and emissive and any(c > 0 for c in emissive):
        strength = (mat.get("extensions", {}).get("KHR_materials_emissive_strength", {})).get("emissiveStrength", 1.0)
        # an emissiveTexture is written as the Emittance map (gltf.convert_textures / write_mtl): the shader multiplies the
        # attribute (factor, intensity) by the texture's rgb x alpha
        out["emittance"] = [_clamp01(c) for c in emissive[:3]] + [options.emissive_intensity * strength]
    elif options.pbr and "emissiveTexture" in mat:
        options.warnings.append("material %r: emissiveTexture without an emissiveFactor emits nothing (glTF default factor is 0)" % label)
    return out
