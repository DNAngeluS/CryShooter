# plasmid-assets

Stdlib-only Python tools for CRYENGINE assets: PNG to DDS, static-mesh CGF writer and dumper, and a glTF 2.0
static-mesh importer, and the terrain files of a level (terrain.dat, heightmap.dat, terraintexture.pak).
Version 0.6.0 (see `VERSION` and `CHANGELOG.md`).

Liftable: this package has no references to the host project. It needs only Python 3 and the standard library,
and it does not read files outside its own directory.

## Subcommands

| Command | What it does |
| --- | --- |
| `png2dds <in.png> <out.dds> --format {rgba8,bc1,bc3,bc5} [--mips N] [--trailer] [--persistent N] [--srgb] [--allow-misnamed] [--jobs N] [--cache-dir DIR]` | Writes a monolithic DDS with a box-filtered mip chain. BC5 must be named `*_ddn.dds` unless `--allow-misnamed`. `--jobs` encodes block-row bands in N processes (default 1, 0 = all CPUs). `--cache-dir` enables the content-hash cache (off when absent). Output bytes do not depend on `--jobs`. |
| `cgf-write <preset> <out.cgf> [--position-format {f32,f16}]` | Writes a static-mesh `.cgf` from a built-in preset (`box10`, `tri`). |
| `cgf-dump <file.cgf> [...]` | Read-only dump of the chunk table and decoded chunks. Exit 0 only if every check passes. |
| `gltf2cgf <in.gltf\|in.glb> <out_dir> [--name NAME] [--scale S] [--game-dir DIR] [--jobs N] [--cache-dir DIR]` | Imports the default scene's triangles into `<out_dir>/<name>.cgf`, converts the referenced PNGs to DDS, and prints a JSON manifest on stdout. `--game-dir` also writes a `.mtl`. `--jobs` converts independent textures in N processes (default 1, 0 = all CPUs); `--cache-dir` as for `png2dds`. |
| `pfx-write <out_dir> --png <in.png> [--tag a]` | Writes `<out_dir>/Textures/plasmid_spark_<tag>.dds` (BC3, sRGB, from the PNG) and `<out_dir>/particles/plasmid_spark_<tag>.pfx` (PFX2 effect JSON). The tag letter selects the feature family (a to g). Prints a JSON list of the two paths. |
| `schematyc-write <out_dir> [--name plasmid_probe] [--variant ok] [--mesh-file PATH]` | Writes `<out_dir>/<name>.schematyc_ent`. Variants: `ok`, `truncated`, `badguid`, `mesh`, `badtype`, `multi`, `light`. `--mesh-file` is the FilePath written into the Mesh component. Prints a JSON list. |
| `audio-write <out_dir>` | Writes `<out_dir>/sdlmixer/assets/plasmid_beep.wav` (2 s, 440 Hz, 22.05 kHz mono s16) and `<out_dir>/sdlmixer/ace/plasmid_test.xml` (ATL control file, trigger `Play_plasmid_beep`). Prints a JSON list. |
| `terrain-write --out-dir D --size N --heightmap {png:PATH,flat:Z,hills:SEED} [--max-height M] [--brushes FILE.json --assets-dir DIR]` | Writes the level files that depend on the heightmap size: `terrain/terrain.dat`, `leveldata/heightmap.dat`, `leveldata/vegetationmap.dat`, `terraintexture.pak`, `leveldata/terraintexture.xml`, and the navmesh `.bai` stubs. Also writes `<out_dir>/manifest.json` (sha256 and size of each file, and the XML size attributes) and prints it. `png:` takes a square gray PNG (8 or 16 bit) whose side is `N`. `hills:SEED` is our own deterministic generator. Size 256 is refused: the heightmap.dat header is known only for 512, 1024 and 2048. `--brushes` adds brush instances to terrain.dat (see Brushes below); the manifest then gets a `brushes` key (count and per-cgf counts). |
| `terrain-check <terrain.dat> [--lenient]` | Parses a terrain.dat (strict: the object block must be whole brush records ending at EOF, and the file uses 0xDE gaps) and prints its structure, the brush table size, the brush count and warnings. Exit 0 if it parses, 1 if it does not, 2 if the file cannot be read. |
| `cgf-bounds <file.cgf> [--assets-dir DIR]` | Prints the vertex AABB of a 0x746 `.cgf` as JSON `{file, min, max}` (read only). Exit 2 if it cannot be read. `--assets-dir` makes the path relative to that folder. |
| `terrain-sample --size N --heightmap SPEC --max-height M --points "x,y;x,y;..."` | Ground height at each point as JSON `{points: [{x, y, z}]}`, read from the quantised leaves the writer stores (see Ground height below). Each point needs 0 <= x, y <= N, else exit 2. |

### Ground height

`terrain-sample` answers "what is the ground at x, y" for a level built from the same heightmap and max height. The
height follows `CTerrain::GetZApr` (`Code/CryEngine/Cry3DEngine/terrain_hmap.cpp`): the four corners of the unit cell
come from the leaf sector that owns it, stored as 12-bit codes (`foff + code * frange`), and the cell is triangulated,
not bilinear. The stored heights differ from the float source by at most half a leaf step (span/8190 m). Points on
the far edge use the last cell; `GetZApr` itself returns 0 there and for x or y <= 0. Not verified: the engine returns
these heights in a running game (the MCP `ground_height` tool is the first check; the orchestrator runs it on the engine).

The three fixture writers are for engine test content. They take explicit output directories and write nothing else.
The `audio-write` samples are opened by a plain path relative to the working directory, so a caller that plays them
from a project root must link `audio` to the output directory itself; the writer does not create that link.
`schematyc-write` GUIDs come from `uuid.uuid4()`, so the output differs on every run.

## Terrain

The terrain code is stdlib only (`array`, `struct`, `zipfile`), with no numpy: the output bytes match the FPS numpy
writer, which uses float32 arithmetic. `tests/parity.sha256` (the `terrain_`, `heightmap_` and `cover_ctc_` lines) pins those bytes for fixed heightmaps.
The `terraintexture.pak` member date is fixed (1980-01-01), so repeated runs give the same file; the FPS writer
stamps the current time, so only the `terrain/cover.ctc` member is comparable with FPS.

Provenance: the terrain formats were ported from the FPS asset pipeline (`tools/asset_pipeline/procgen/`,
`texture_builder.py`, `bundle_builder.py`), which was reverse-engineered from these engine source files:
`Code/CryEngine/Cry3DEngine/terrain_compile.cpp`, `Code/CryEngine/Cry3DEngine/terrain_node_compile.cpp`,
`Code/CryEngine/Cry3DEngine/terrain_sector.h` and `Code/CryEngine/CryCommon/Cry3DEngine/I3DEngine.h`.

Not verified by these tools: that the engine loads a new-size level built from these files (needs an engine run).
The template `terrain/cover.ctc` kept in a level pak is tied to the template size (a 21-node tile tree at 1024 m);
`make_cover_ctc` writes a sector-table tree (1365 nodes at 1024 m). Which one the engine reads is unverified.

### Brushes

`terrain-write --brushes brushes.json --assets-dir DIR` writes brushes (static mesh instances) into `terrain/terrain.dat`.
`brushes.json` is a list of objects; at most 4096 entries:

```
[{"cgf": "Objects/snl_3p/box.cgf", "pos": [1725, 357, 68], "rot": [1, 0, 0, 0], "scale": 1, "material_id": -1}]
```

- `cgf` (required): the .cgf path relative to `--assets-dir`, ASCII, `/` separators, no empty or `..` part, ending in
  `.cgf`, under 256 bytes. One brush table entry per distinct cgf, in first-use order.
- `pos` (required): world position in metres. `rot` (default `[1, 0, 0, 0]`): unit quaternion (w, x, y, z), checked to
  1e-6. `scale` (default 1): a number or `[sx, sy, sz]`, each > 0; the rotation's column j is multiplied by scale j.
- `material_id` (default -1): must be -1. The material table is written empty, so another index has no target.

Each brush is one object-block record under a single childless root octree chunk. Its stored world AABB is the
transformed 8 corners of the .cgf vertex bounds (the POSITIONS stream of its Mesh chunk, float32 or half-float). The
engine trusts the stored AABB, so it must match the mesh. A missing or unreadable .cgf is an error (exit 2), never a
guessed box. The writer reads each distinct .cgf once.

Defaults for the fields the research leaves open (written into every record): layer id 22, shadow bias 0, dummy 0,
view distance ratio 100, LOD ratio 100, render-node flags 0, collision class 0, flags 0, material layers 0. Their sources
are in the `terrain.py` comments and in the CHANGELOG. Layer id 22 is an open question (the research's own minimal
example uses 0).

`terrain-check` parses the brush records back: the brush table, each record's cgf, AABB and matrix. Strict mode fails
on structural faults (block size not a whole number of records, EERType other than 1, a type index or material id
outside its table, an inverted or non-finite AABB, bytes after the object block). A brush AABB whose x or y lies outside
`(0,0)-(heightmap size x unit)` is a warning, not an error, since the engine links such a brush to the root (culling
only, unverified). z is not checked.

Not verified by these tools: engine rendering or culling of brushes, the default layer id, the z extent of the engine's root
box, and whether the engine loads a brush from these bytes (needs an engine run). Only the byte layout is checked,
against the layout written in the tests.

## Running

The launcher `plas-assets` (in this directory) runs the package from any working directory; it takes the same
subcommands as `python3 -m plasmid_assets`. The examples below run from this directory. Use `-E -s` rather than `-I`:
`-I` also drops the current directory from `sys.path`, so the package cannot be found from here.

```
cd tools/plasmid-assets
./plas-assets png2dds in.png out.dds --format bc1
python3 -E -s -m plasmid_assets png2dds in.png out.dds --format bc1
python3 -E -s -m plasmid_assets cgf-write box10 out.cgf
python3 -E -s -m plasmid_assets cgf-dump out.cgf
python3 -E -s -m plasmid_assets gltf2cgf scene.gltf out_dir --name scene
```

Tests (no network, no game files; fixtures are generated in-test, and every test writes only inside a temporary
directory):

```
cd tools/plasmid-assets
python3 -I -m unittest discover -s tests -t .
```

`tests/test_parity.py` compares outputs with `tests/parity.sha256` when that file is present, and is skipped otherwise.
`tests/test_terrain.py` compares terrain outputs with the `terrain_`, `heightmap_` and `cover_ctc_` lines of `tests/parity.sha256` (FPS writer output).
To run the reference-level parser test, set `PLASMID_ASSETS_REFERENCE_DIR` to a directory that holds
`fps_forest_basin/level.pak`; without it that test is skipped.

## Exit codes

- `png2dds`: 0 on success; an unhandled error (for example a misnamed BC5) gives a traceback and exit 1.
- `cgf-dump`: 0 if every file passes, 1 if any check fails, 2 with no arguments.
- `gltf2cgf`: 0 on success; 2 with `gltf_import: <message>` on stderr when the input cannot be expressed.
- `pfx-write`, `schematyc-write`, `audio-write`: 0 on success; 2 on a usage error (for example a missing `--png`).

## Speed

The encoders are pure Python; speed comes from parallelism and a cache, never from changing output bytes
(all outputs below are byte-identical to the 0.1.0 encoder, checked with `cmp`).

- `--jobs N` (default 1, `0` = all CPUs): `png2dds` splits block rows into bands; `gltf2cgf` encodes independent textures in parallel.
- `--cache-dir PATH` (off unless given): finished DDS files keyed by sha256 of the PNG bytes, format, srgb, mips, persistent, trailer and tool version; corrupt entries are ignored and re-encoded.

Measured on a 20-CPU machine, one noisy RGBA PNG, wall seconds (`time python3 -E -s -m plasmid_assets png2dds in.png out.dds --format bc1 --jobs N`):

| Image | Format | 0.1.0 | 0.2.0 `--jobs 1` | 0.2.0 `--jobs 20` |
|---|---|---|---|---|
| 1024x1024 | bc1 | 88.85 | 33.15 | 5.90 |
| 1024x1024 | bc3 | 98.69 | 39.65 | 6.35 |
| 1024x1024 | bc5 | 11.01 | 5.56 | 2.49 |
| 2048x2048 | bc1 | 268.22 | 117.13 | 20.72 |
| 2048x2048 | bc3 | 272.98 | 115.50 | 21.58 |
| 2048x2048 | bc5 | 29.40 | 18.02 | 7.63 |

Cache: 2048x2048 bc1 miss 20.92 s (`--jobs 20`), hit 0.21 s.
