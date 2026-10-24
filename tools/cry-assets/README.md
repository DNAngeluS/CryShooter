# cry-assets

Stdlib-only Python tools for CRYENGINE assets: PNG to DDS, static-mesh CGF writer and dumper, and a glTF 2.0
static-mesh importer. Version 0.2.0 (see `VERSION` and `CHANGELOG.md`).

Liftable: this package has no references to the host project. It needs only Python 3 and the standard library,
and it does not read files outside its own directory.

## Subcommands

| Command | What it does |
| --- | --- |
| `png2dds <in.png> <out.dds> --format {rgba8,bc1,bc3,bc5} [--mips N] [--trailer] [--persistent N] [--srgb] [--allow-misnamed] [--jobs N] [--cache-dir DIR]` | Writes a monolithic DDS with a box-filtered mip chain. BC5 must be named `*_ddn.dds` unless `--allow-misnamed`. `--jobs` encodes block-row bands in N processes (default 1, 0 = all CPUs). `--cache-dir` enables the content-hash cache (off when absent). Output bytes do not depend on `--jobs`. |
| `cgf-write <preset> <out.cgf> [--position-format {f32,f16}]` | Writes a static-mesh `.cgf` from a built-in preset (`box10`, `tri`). |
| `cgf-dump <file.cgf> [...]` | Read-only dump of the chunk table and decoded chunks. Exit 0 only if every check passes. |
| `gltf2cgf <in.gltf\|in.glb> <out_dir> [--name NAME] [--scale S] [--game-dir DIR] [--jobs N] [--cache-dir DIR]` | Imports the default scene's triangles into `<out_dir>/<name>.cgf`, converts the referenced PNGs to DDS, and prints a JSON manifest on stdout. `--game-dir` also writes a `.mtl`. `--jobs` converts independent textures in N processes (default 1, 0 = all CPUs); `--cache-dir` as for `png2dds`. |
| `pfx-write <out_dir> --png <in.png> [--tag a]` | Writes `<out_dir>/Textures/snl_spark_<tag>.dds` (BC3, sRGB, from the PNG) and `<out_dir>/particles/snl_spark_<tag>.pfx` (PFX2 effect JSON). The tag letter selects the feature family (a to g). Prints a JSON list of the two paths. |
| `schematyc-write <out_dir> [--name snl_probe] [--variant ok] [--mesh-file PATH]` | Writes `<out_dir>/<name>.schematyc_ent`. Variants: `ok`, `truncated`, `badguid`, `mesh`, `badtype`, `multi`, `light`. `--mesh-file` is the FilePath written into the Mesh component. Prints a JSON list. |
| `audio-write <out_dir>` | Writes `<out_dir>/sdlmixer/assets/snl_beep.wav` (2 s, 440 Hz, 22.05 kHz mono s16) and `<out_dir>/sdlmixer/ace/snl_test.xml` (ATL control file, trigger `Play_snl_beep`). Prints a JSON list. |

The three fixture writers are for engine test content. They take explicit output directories and write nothing else.
The `audio-write` samples are opened by a plain path relative to the working directory, so a caller that plays them
from a project root must link `audio` to the output directory itself; the writer does not create that link.
`schematyc-write` GUIDs come from `uuid.uuid4()`, so the output differs on every run.

## Running

Run from this directory. Use `-E -s` rather than `-I`: `-I` also drops the current directory from `sys.path`,
so the package cannot be found from here.

```
cd tools/cry-assets
python3 -E -s -m cry_assets png2dds in.png out.dds --format bc1
python3 -E -s -m cry_assets cgf-write box10 out.cgf
python3 -E -s -m cry_assets cgf-dump out.cgf
python3 -E -s -m cry_assets gltf2cgf scene.gltf out_dir --name scene
```

Tests (no network, no game files; fixtures are generated in-test, and every test writes only inside a temporary
directory):

```
cd tools/cry-assets
python3 -I -m unittest discover -s tests -t .
```

`tests/test_parity.py` compares outputs with `tests/parity.sha256` when that file is present, and is skipped otherwise.

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

Measured on a 20-CPU machine, one noisy RGBA PNG, wall seconds (`time python3 -E -s -m cry_assets png2dds in.png out.dds --format bc1 --jobs N`):

| Image | Format | 0.1.0 | 0.2.0 `--jobs 1` | 0.2.0 `--jobs 20` |
|---|---|---|---|---|
| 1024x1024 | bc1 | 88.85 | 33.15 | 5.90 |
| 1024x1024 | bc3 | 98.69 | 39.65 | 6.35 |
| 1024x1024 | bc5 | 11.01 | 5.56 | 2.49 |
| 2048x2048 | bc1 | 268.22 | 117.13 | 20.72 |
| 2048x2048 | bc3 | 272.98 | 115.50 | 21.58 |
| 2048x2048 | bc5 | 29.40 | 18.02 | 7.63 |

Cache: 2048x2048 bc1 miss 20.92 s (`--jobs 20`), hit 0.21 s.
