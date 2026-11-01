"""Command-line wiring for plasmid_assets. Flags, defaults, stdout text and exit codes follow the P0(f) spike CLIs.

Subcommands:
  png2dds    <in.png> <out.dds> --format {rgba8,bc1,bc3,bc5,bc5s} [--mips N] [--trailer] [--persistent N]
             [--srgb] [--allow-misnamed]
  cgf-write  <preset> <out.cgf> [--position-format {f32,f16}]
  cgf-dump   <file.cgf> [...]
  gltf2cgf   <in.gltf|in.glb> <out_dir> [--name NAME] [--scale S] [--game-dir DIR]
  gltf2chr   <in.gltf|in.glb> <out_dir> --game-dir DIR [--name NAME] [--scale S]   (skinned: .chr .skin .caf .cdf .chrparams .mtl)
  pfx-write  <out_dir> --png <in.png> [--tag a]
  schematyc-write <out_dir> [--name plasmid_probe] [--variant ok] [--mesh-file PATH]
  audio-write <out_dir>
  terrain-write --out-dir D --size N --heightmap {png:PATH,flat:Z,hills:SEED} [--max-height M]
                [--brushes brushes.json --assets-dir DIR]
  terrain-check <terrain.dat> [--lenient]
  cgf-bounds <file.cgf> [--assets-dir D]
  terrain-sample --size N --heightmap {png:PATH,flat:Z,hills:SEED} --max-height M --points "x,y;x,y;..."
The three fixture writers print a JSON list of the files they wrote. terrain-write writes the level files that depend
on the heightmap size into out_dir and prints a JSON manifest (sha256 per file, also saved as out_dir/manifest.json).
"""

import argparse
import hashlib
import json
import math
import os
import sys

from . import audio, cgf, cgf_dump, dds, gltf, heightmap, pfx, schematyc, skin, terrain
from .cache import write_dds_cached
from .png import read_png

CGF_DUMP_USAGE = "usage: plas-assets cgf-dump FILE.cgf [MORE.cgf ...]"


def _png2dds(a):
    if a.jobs < 0:
        print("png2dds: --jobs must be 0 (all CPUs) or a positive number", file=sys.stderr)
        return 2
    jobs = (os.cpu_count() or 1) if a.jobs == 0 else a.jobs
    w, h, px = read_png(a.png)
    with open(a.png, "rb") as f:
        png_bytes = f.read() if a.cache_dir else None
    if a.gloss:
        if a.cache_dir:
            print("png2dds: --gloss and --cache-dir cannot be combined (the cache key does not cover the gloss image)", file=sys.stderr)
            return 2
        gw, gh, gpx = read_png(a.gloss)
        if (gw, gh) != (w, h):
            print(f"png2dds: gloss {gw}x{gh} must match the normal map {w}x{h}", file=sys.stderr)
            return 2
        n, size = dds.write_dds(a.dds, w, h, px, a.format, a.mips, a.trailer, a.allow_misnamed, a.srgb, a.persistent, jobs,
                                gloss=bytes(gpx[0::4]))
    else:
        n, size = write_dds_cached(a.dds, png_bytes, w, h, px, a.format, a.cache_dir, a.mips, a.trailer,
                                   a.allow_misnamed, a.srgb, a.persistent, jobs)
    print(f"{a.dds}: {w}x{h} {a.format} mips {n} bytes {size}")
    return 0


def _cgf_write(a):
    pos, nrm, uv, idx = cgf.PRESETS[a.preset]()
    n = cgf.write_static_mesh(a.out, pos, nrm, uv, idx, None, cgf.MTL_EDITORPRIMITIVE,
                              a.position_format)
    print("wrote %s (%d bytes, %d verts, %d indices, positions %s)" % (
        a.out, n, len(pos), len(idx), a.position_format))
    return 0


def _cgf_dump(a):
    if not a.files:
        print(CGF_DUMP_USAGE, file=sys.stderr)
        return 2
    ok = True
    for path in a.files:
        ok = cgf_dump.dump(path) and ok
    return 0 if ok else 1


def _material_options(a):
    """MaterialOptions from the shared --opaque / --no-pbr / --emissive-intensity flags."""
    from .materials import MaterialOptions
    opaque = None
    if a.opaque:
        opaque = "all" if a.opaque.strip().lower() == "all" else {n for n in a.opaque.split(",") if n}
    return MaterialOptions(pbr=not a.no_pbr, opaque=opaque, emissive_intensity=a.emissive_intensity, bake=not a.no_bake, ao=a.bake_ao, occlusion_map=not a.no_occlusion_map)


def _add_material_flags(p):
    p.add_argument("--opaque", metavar="all|NAME,NAME",
                   help="force these glTF materials (or all) opaque: a BLEND material is drawn in the engine's forward pass "
                        "(no ambient light, lit only where a direct light reaches it)")
    p.add_argument("--no-pbr", action="store_true",
                   help="write the 0.9.1 matte materials (no Specular, Shininess or Emittance)")
    p.add_argument("--no-bake", action="store_true",
                   help="do not bake a metallicRoughnessTexture per texel (diffuse, _spec and _ddna gloss maps): use the 0.13.0 "
                        "mean approximation of its factors")
    p.add_argument("--bake-ao", action="store_true",
                   help="multiply a glTF occlusionTexture into the diffuse map instead of writing an occlusion map: works on a stock "
                        "engine, but also darkens direct light (the default writes a BC4 occlusion map in the Custom slot with "
                        "%%OCCLUSION_MAP, which scales indirect light only and needs the sandbox shader extension)")
    p.add_argument("--no-occlusion-map", action="store_true",
                   help="ignore a glTF occlusionTexture (with a warning) unless --bake-ao is given")
    p.add_argument("--emissive-intensity", type=float, default=10.0,
                   help="Emittance intensity for emissiveFactor 1.0 (default 10; the shader multiplies rgb by intensity/10)")


def _gltf2cgf(a):
    name = a.name or os.path.splitext(os.path.basename(a.src))[0]
    os.makedirs(a.out_dir, exist_ok=True)
    try:
        r = gltf.import_gltf(a.src, a.scale)
        cgf_path = os.path.join(a.out_dir, name + ".cgf")
        mat_options = _material_options(a)
        textures = gltf.convert_textures(r["asset"], a.out_dir, name, a.jobs, a.cache_dir, emissive=mat_options.pbr,
                                           bake=mat_options.pbr and mat_options.bake, warnings=mat_options.warnings,
                                           ao=mat_options.ao, occlusion=mat_options.pbr and mat_options.occlusion_map)
        mtl_name = gltf.MTL_DEFAULT
        if a.game_dir:
            game_dir = a.game_dir.strip("/")
            mtl_name = game_dir + "/" + name
            gltf.write_mtl(os.path.join(a.out_dir, name + ".mtl"), game_dir, name, r["asset"].doc,
                           r["materials"], textures, r["asset"], mat_options)
        size = cgf.write_static_mesh(cgf_path, r["positions"], r["normals"], r["uvs"], r["indices"],
                                     r["subsets"], mtl_name)
    except gltf.GltfError as e:
        print("gltf_import: " + str(e), file=sys.stderr)
        return 2
    xs = [p[0] for p in r["positions"]]
    ys = [p[1] for p in r["positions"]]
    zs = [p[2] for p in r["positions"]]
    manifest = dict(cgf=name + ".cgf", cgf_bytes=size, vertices=len(r["positions"]), indices=len(r["indices"]),
                    subsets=len(r["subsets"]), materials_in_source=len(r["materials"]),
                    aabb=[[min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]],
                    textures=textures, material=mtl_name, warnings=r["warnings"] + mat_options.warnings)
    print(json.dumps(manifest, indent=1))
    return 0


def _gltf2chr(a):
    name = a.name or os.path.splitext(os.path.basename(a.src))[0]
    try:
        manifest = skin.convert_skin(a.src, a.out_dir, a.game_dir, name, a.scale, a.jobs, a.cache_dir, _material_options(a))
    except (gltf.GltfError, skin.SkinError) as e:
        print("gltf2chr: " + str(e), file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=1))
    return 0


def _cgf_bounds(a):
    path = os.path.join(a.assets_dir, a.file) if a.assets_dir else a.file
    try:
        lo, hi = cgf_dump.mesh_bounds(path)
    except (cgf_dump.CgfBoundsError, OSError) as e:
        print("cgf-bounds: " + str(e), file=sys.stderr)
        return 2
    print(json.dumps({"file": a.file, "min": list(lo), "max": list(hi)}, sort_keys=True))
    return 0


def _parse_points(text, size):
    points = []
    for part in text.split(";"):
        pieces = part.split(",")
        if len(pieces) != 2:
            raise ValueError("point %r is not x,y" % part)
        x, y = float(pieces[0]), float(pieces[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("point %r is not finite" % part)
        if not (0.0 <= x <= size and 0.0 <= y <= size):
            raise ValueError("point (%g, %g) is outside [0, %d]" % (x, y, size))
        points.append((x, y))
    if not points:
        raise ValueError("no points given")
    return points


def _terrain_sample(a):
    try:
        size = a.size
        if size not in heightmap.HEIGHTMAP_PREFIX:
            raise ValueError("no heightmap.dat header for size %d: supported %s" % (size, sorted(heightmap.HEIGHTMAP_PREFIX)))
        if not (math.isfinite(a.max_height) and a.max_height > 0):
            raise ValueError("--max-height must be a finite number greater than 0")
        points = _parse_points(a.points, size)
        spec = a.heightmap
        if spec.startswith("png:"):
            png_size, samples = heightmap.from_png(spec[4:])
            if png_size != size:
                raise ValueError("PNG is %dx%d, --size is %d" % (png_size, png_size, size))

            def u_at(x, y):
                return samples[y * size + x]
        elif spec.startswith("flat:"):
            value = heightmap.flat(1, float(spec[5:]), max_height_m=a.max_height)[0]

            def u_at(x, y):
                return value
        elif spec.startswith("hills:"):
            seed = int(spec[6:])

            def u_at(x, y):
                return heightmap.hills_u_at(seed, size, x, y, max_height_m=a.max_height)
        else:
            raise ValueError("--heightmap must be png:PATH, flat:Z or hills:SEED, got %r" % spec)
        hm = terrain.OnDemandHeights(size, u_at, a.max_height)
        out = [{"x": x, "y": y, "z": terrain.ground_height(hm, size, x, y)} for x, y in points]
    except (ValueError, OSError) as e:
        print("terrain-sample: " + str(e), file=sys.stderr)
        return 2
    print(json.dumps({"points": out}, sort_keys=True))
    return 0


def _pfx_write(a):
    print(json.dumps(pfx.write_pfx(a.out_dir, a.png, a.tag)))
    return 0


def _schematyc_write(a):
    print(json.dumps(schematyc.write_schematyc(a.out_dir, a.name, a.variant, a.mesh_file)))
    return 0


def _audio_write(a):
    print(json.dumps(audio.write_audio(a.out_dir)))
    return 0


def _terrain_write(a):
    spec = a.heightmap
    try:
        if bool(a.brushes) != bool(a.assets_dir):
            raise ValueError("--brushes and --assets-dir go together")
        brushes = None
        if a.brushes:
            with open(a.brushes, encoding="utf-8") as f:
                brushes = terrain.normalize_brushes(json.load(f))
        if spec.startswith("png:"):
            size, heights = heightmap.from_png(spec[4:])
            if size != a.size:
                raise ValueError("PNG is %dx%d, --size is %d" % (size, size, a.size))
        elif spec.startswith("flat:"):
            size, heights = a.size, heightmap.flat(a.size, float(spec[5:]), max_height_m=a.max_height)
        elif spec.startswith("hills:"):
            size, heights = a.size, heightmap.hills(int(spec[6:]), a.size, max_height_m=a.max_height)
        else:
            raise ValueError("--heightmap must be png:PATH, flat:Z or hills:SEED, got %r" % spec)
        files = terrain.level_terrain_files(heights, size, max_height_m=a.max_height, brushes=brushes,
                                            assets_dir=a.assets_dir)
    except (ValueError, OSError) as e:
        print("terrain-write: " + str(e), file=sys.stderr)
        return 2
    entries = {}
    for name in sorted(files):
        path = os.path.join(a.out_dir, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(files[name])
        entries[name] = {"bytes": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()}
    attributes = {f: {k: {a_: str(v_) for a_, v_ in attrs.items()} for k, attrs in groups.items()}
                  for f, groups in terrain.level_size_attributes(size, max_height_m=a.max_height).items()}
    manifest = {"size": size, "max_height_m": a.max_height, "heightmap": spec, "files": entries,
                "attributes": attributes}
    if brushes is not None:
        per_cgf = {}
        for b in brushes:
            per_cgf[b["cgf"]] = per_cgf.get(b["cgf"], 0) + 1
        manifest["brushes"] = {"count": len(brushes), "per_cgf": dict(sorted(per_cgf.items()))}
    text = json.dumps(manifest, indent=1, sort_keys=True)
    with open(os.path.join(a.out_dir, "manifest.json"), "w") as f:
        f.write(text + "\n")
    print(text)
    return 0


def _probe_cubemap(a):
    from . import cubemap

    def colour(text, label):
        try:
            parts = [float(x) for x in text.split(",")]
        except ValueError:
            parts = []
        if len(parts) != 3:
            raise ValueError("--%s must be three comma-separated numbers, got %r" % (label, text))
        return tuple(parts)

    try:
        paths = cubemap.write_probe(a.out_dir, a.name, sky=colour(a.sky, "sky"), horizon=colour(a.horizon, "horizon"),
                                    ground=colour(a.ground, "ground"), size=a.size)
    except (ValueError, OSError) as e:
        print("probe-cubemap: " + str(e), file=sys.stderr)
        return 2
    files = {os.path.basename(p): {"bytes": os.path.getsize(p), "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest()}
             for p in paths}
    print(json.dumps({"files": files}, indent=1, sort_keys=True))
    return 0


def _terrain_check(a):
    try:
        with open(a.file, "rb") as f:
            data = f.read()
    except OSError as e:
        print("terrain-check: " + str(e), file=sys.stderr)
        return 2
    try:
        info = terrain.parse_terrain_dat(data, strict=not a.lenient)
    except terrain.TerrainDatError as e:
        print("terrain-check: FAIL %s: %s" % (a.file, e), file=sys.stderr)
        return 1
    h = info["header"]
    print("terrain-check: OK %s" % a.file)
    print("  file bytes %d, chunk_size %d, heightmap %d, unit %s, sector %s, sectors table %d"
          % (len(data), h["chunk_size"], h["heightmap_size"], h["unit_m"], h["sector_m"], h["sectors_table"]))
    print("  nodes %d, leaves %d, tables: vegetation %d, brushes %d, materials %d"
          % (info["nodes"], info["leaves"], info["tables"]["vegetation"], info["tables"]["brushes"],
             info["tables"]["materials"]))
    print("  octree chunks %d, bad alignment bytes %d, mode %s"
          % (len(info["octree_chunks"]), info["bad_pad_bytes"], "strict" if not a.lenient else "lenient"))
    print("  brush table entries %d, brush records %d, warnings %d"
          % (len(info["brush_names"]), len(info["brush_records"]), len(info["warnings"])))
    for w in info["warnings"]:
        print("  warning: " + w)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="plas-assets", description="CRYENGINE asset tools (stdlib only).")
    sub = ap.add_subparsers(dest="cmd", required=True,
                            metavar="{png2dds,cgf-write,cgf-dump,gltf2cgf,gltf2chr,pfx-write,schematyc-write,audio-write,"
                                    "terrain-write,terrain-check,cgf-bounds,terrain-sample,probe-cubemap}")

    p = sub.add_parser("png2dds", help="PNG -> DDS (rgba8, bc1, bc3, bc5, bc5s)")
    p.add_argument("png")
    p.add_argument("dds")
    p.add_argument("--format", choices=["rgba8", "bc1", "bc3", "bc5", "bc5s"], required=True)
    p.add_argument("--mips", type=int, default=0, help="0 = full chain")
    p.add_argument("--trailer", action="store_true")
    p.add_argument("--persistent", type=int, default=None,
                   help="persistent mips (3..mip count); default all, i.e. not streamed")
    p.add_argument("--srgb", action="store_true",
                   help="colour texture: set the engine sRGB-read flag and filter mips in linear light")
    p.add_argument("--allow-misnamed", action="store_true", help="negative tests only: allow BC5 without a _ddn name")
    p.add_argument("--gloss", metavar="PNG", default=None,
                   help="bc5s only: per-texel smoothness (the red channel of this PNG, same size) written as the normal map's attached alpha")
    p.add_argument("--cache-dir", default=None,
                   help="content-hash cache of finished DDS files in this directory (no cache when absent)")
    p.add_argument("--jobs", type=int, default=1,
                   help="encode block rows in N worker processes (default 1; 0 = all CPUs); output is identical")
    p.set_defaults(func=_png2dds)

    p = sub.add_parser("cgf-write", help="write a static-mesh .cgf from a built-in preset")
    p.add_argument("preset", choices=sorted(cgf.PRESETS))
    p.add_argument("out", help="output .cgf path")
    p.add_argument("--position-format", choices=["f32", "f16"], default="f32")
    p.set_defaults(func=_cgf_write)

    p = sub.add_parser("cgf-dump", help="dump and check .cgf files (read-only)")
    p.add_argument("files", nargs="*", metavar="FILE.cgf")
    p.set_defaults(func=_cgf_dump)

    p = sub.add_parser("gltf2cgf", help="import a glTF/GLB static mesh: .cgf + .dds textures, JSON manifest on stdout")
    p.add_argument("src")
    p.add_argument("out_dir")
    p.add_argument("--name")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--game-dir",
                   help="game-relative folder the output will live in (e.g. Objects/plasmid_test); "
                        "writes a .mtl and links the cgf to it")
    p.add_argument("--jobs", type=int, default=1,
                   help="encode textures in N worker processes (default 1; 0 = all CPUs); output is identical")
    p.add_argument("--cache-dir", default=None,
                   help="content-hash cache of finished DDS files in this directory (no cache when absent)")
    _add_material_flags(p)
    p.set_defaults(func=_gltf2cgf)

    p = sub.add_parser("gltf2chr", help="import a skinned glTF/GLB: .chr .skin .caf .cdf .chrparams .mtl + textures, JSON manifest")
    p.add_argument("src")
    p.add_argument("out_dir")
    p.add_argument("--game-dir", required=True,
                   help="game-relative folder the output will live in (e.g. Objects/plasmid_skin); written into the .cdf/.chrparams/.mtl")
    p.add_argument("--name")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--cache-dir", default=None)
    _add_material_flags(p)
    p.set_defaults(func=_gltf2chr)

    p = sub.add_parser("probe-cubemap", help="write an environment-probe cube map pair (BC6H, sky/horizon/ground gradient); JSON on stdout")
    p.add_argument("out_dir")
    p.add_argument("--name", default="ambient", help="file stem: <name>_cm.dds and <name>_cm_diff.dds (default ambient)")
    p.add_argument("--sky", default="0.35,0.5,0.8", help="colour straight up, r,g,b linear (default %(default)s)")
    p.add_argument("--horizon", default="0.7,0.75,0.8", help="colour at the horizon (default %(default)s)")
    p.add_argument("--ground", default="0.25,0.22,0.18", help="colour straight down (default %(default)s)")
    p.add_argument("--size", type=int, default=256, help="specular map side, a power of two, at least 256 (default 256)")
    p.set_defaults(func=_probe_cubemap)

    p = sub.add_parser("pfx-write", help="write a PFX2 particle effect and its BC3 texture; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.add_argument("--png", required=True, help="source PNG for the texture")
    p.add_argument("--tag", default="a", help="file name tag and variant family (default a)")
    p.set_defaults(func=_pfx_write)

    p = sub.add_parser("schematyc-write", help="write a .schematyc_ent entity class; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.add_argument("--name", default="plasmid_probe")
    p.add_argument("--variant", default="ok",
                   help="ok, truncated, badguid, mesh, badtype, multi, light (default ok)")
    p.add_argument("--mesh-file", default=schematyc.DEFAULT_MESH_FILE,
                   help="FilePath written into the Mesh component (default %(default)s)")
    p.set_defaults(func=_schematyc_write)

    p = sub.add_parser("audio-write", help="write a 440 Hz wav and its ATL xml; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.set_defaults(func=_audio_write)

    p = sub.add_parser("terrain-write", help="write a level's size-dependent terrain files and a sha256 manifest")
    p.add_argument("--out-dir", dest="out_dir", required=True, help="directory to write the level files into")
    p.add_argument("--size", type=int, required=True, help="heightmap side in units (512, 1024 or 2048 for heightmap.dat)")
    p.add_argument("--heightmap", required=True, help="png:PATH (square gray PNG), flat:Z (metres) or hills:SEED")
    p.add_argument("--max-height", type=float, default=terrain.DEFAULT_MAX_HEIGHT_M,
                   help="metres per full 16 bit range (default %(default)s)")
    p.add_argument("--brushes", default=None,
                   help="JSON list of brushes: {cgf, pos, rot?, scale?, material_id?} (at most 4096)")
    p.add_argument("--assets-dir", dest="assets_dir", default=None,
                   help="directory the brush cgf paths are relative to (required with --brushes)")
    p.set_defaults(func=_terrain_write)

    p = sub.add_parser("terrain-check", help="parse a terrain.dat and print its structure (exit 0 ok, 1 fails)")
    p.add_argument("file", metavar="terrain.dat")
    p.add_argument("--lenient", action="store_true", help="accept files without the strict 0xDE and octree rules")
    p.set_defaults(func=_terrain_check)

    p = sub.add_parser("cgf-bounds", help="vertex AABB of a 0x746 .cgf as JSON (exit 0; 2 if unreadable)")
    p.add_argument("file", metavar="FILE.cgf", help="path, or relative to --assets-dir when given")
    p.add_argument("--assets-dir", dest="assets_dir", default=None, help="directory FILE.cgf is relative to")
    p.set_defaults(func=_cgf_bounds)

    p = sub.add_parser("terrain-sample", help="ground height at points, from the quantised terrain (JSON on stdout)")
    p.add_argument("--size", type=int, required=True, help="heightmap side in metres (512, 1024 or 2048)")
    p.add_argument("--heightmap", required=True, help="png:PATH (square gray PNG), flat:Z (metres) or hills:SEED")
    p.add_argument("--max-height", dest="max_height", type=float, required=True,
                   help="metres per full 16 bit range; the same value terrain-write got")
    p.add_argument("--points", required=True, help='"x,y;x,y;..." in metres, each 0 <= x, y <= size')
    p.set_defaults(func=_terrain_sample)
    return ap


def main(argv=None):
    a = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return a.func(a)
