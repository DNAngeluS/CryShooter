"""Command-line wiring for cry_assets. Flags, defaults, stdout text and exit codes follow the P0(f) spike CLIs.

Subcommands:
  png2dds    <in.png> <out.dds> --format {rgba8,bc1,bc3,bc5} [--mips N] [--trailer] [--persistent N]
             [--srgb] [--allow-misnamed]
  cgf-write  <preset> <out.cgf> [--position-format {f32,f16}]
  cgf-dump   <file.cgf> [...]
  gltf2cgf   <in.gltf|in.glb> <out_dir> [--name NAME] [--scale S] [--game-dir DIR]
  pfx-write  <out_dir> --png <in.png> [--tag a]
  schematyc-write <out_dir> [--name snl_probe] [--variant ok] [--mesh-file PATH]
  audio-write <out_dir>
The three fixture writers print a JSON list of the files they wrote.
"""

import argparse
import json
import os
import sys

from . import audio, cgf, cgf_dump, gltf, pfx, schematyc
from .cache import write_dds_cached
from .png import read_png

CGF_DUMP_USAGE = "usage: cry_assets cgf-dump FILE.cgf [MORE.cgf ...]"


def _png2dds(a):
    if a.jobs < 0:
        print("png2dds: --jobs must be 0 (all CPUs) or a positive number", file=sys.stderr)
        return 2
    jobs = (os.cpu_count() or 1) if a.jobs == 0 else a.jobs
    w, h, px = read_png(a.png)
    with open(a.png, "rb") as f:
        png_bytes = f.read() if a.cache_dir else None
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


def _gltf2cgf(a):
    name = a.name or os.path.splitext(os.path.basename(a.src))[0]
    os.makedirs(a.out_dir, exist_ok=True)
    try:
        r = gltf.import_gltf(a.src, a.scale)
        cgf_path = os.path.join(a.out_dir, name + ".cgf")
        textures = gltf.convert_textures(r["asset"], a.out_dir, name, a.jobs, a.cache_dir)
        mtl_name = gltf.MTL_DEFAULT
        if a.game_dir:
            game_dir = a.game_dir.strip("/")
            mtl_name = game_dir + "/" + name
            gltf.write_mtl(os.path.join(a.out_dir, name + ".mtl"), game_dir, name, r["asset"].doc,
                           r["materials"], textures)
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
                    textures=textures, material=mtl_name, warnings=r["warnings"])
    print(json.dumps(manifest, indent=1))
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


def build_parser():
    ap = argparse.ArgumentParser(prog="cry_assets", description="CRYENGINE asset tools (stdlib only).")
    sub = ap.add_subparsers(dest="cmd", required=True,
                            metavar="{png2dds,cgf-write,cgf-dump,gltf2cgf,pfx-write,schematyc-write,audio-write}")

    p = sub.add_parser("png2dds", help="PNG -> DDS (rgba8, bc1, bc3, bc5)")
    p.add_argument("png")
    p.add_argument("dds")
    p.add_argument("--format", choices=["rgba8", "bc1", "bc3", "bc5"], required=True)
    p.add_argument("--mips", type=int, default=0, help="0 = full chain")
    p.add_argument("--trailer", action="store_true")
    p.add_argument("--persistent", type=int, default=None,
                   help="persistent mips (3..mip count); default all, i.e. not streamed")
    p.add_argument("--srgb", action="store_true",
                   help="colour texture: set the engine sRGB-read flag and filter mips in linear light")
    p.add_argument("--allow-misnamed", action="store_true", help="negative tests only: allow BC5 without a _ddn name")
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
                   help="game-relative folder the output will live in (e.g. Objects/snl_test); "
                        "writes a .mtl and links the cgf to it")
    p.add_argument("--jobs", type=int, default=1,
                   help="encode textures in N worker processes (default 1; 0 = all CPUs); output is identical")
    p.add_argument("--cache-dir", default=None,
                   help="content-hash cache of finished DDS files in this directory (no cache when absent)")
    p.set_defaults(func=_gltf2cgf)

    p = sub.add_parser("pfx-write", help="write a PFX2 particle effect and its BC3 texture; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.add_argument("--png", required=True, help="source PNG for the texture")
    p.add_argument("--tag", default="a", help="file name tag and variant family (default a)")
    p.set_defaults(func=_pfx_write)

    p = sub.add_parser("schematyc-write", help="write a .schematyc_ent entity class; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.add_argument("--name", default="snl_probe")
    p.add_argument("--variant", default="ok",
                   help="ok, truncated, badguid, mesh, badtype, multi, light (default ok)")
    p.add_argument("--mesh-file", default=schematyc.DEFAULT_MESH_FILE,
                   help="FilePath written into the Mesh component (default %(default)s)")
    p.set_defaults(func=_schematyc_write)

    p = sub.add_parser("audio-write", help="write a 440 Hz wav and its ATL xml; JSON list of paths on stdout")
    p.add_argument("out_dir")
    p.set_defaults(func=_audio_write)
    return ap


def main(argv=None):
    a = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    return a.func(a)
