# Changelog

## 0.6.0 - 2026-10-27 - Renamed to plasmid-assets

- Package `cry_assets` is now `plasmid_assets`. Import path: `from plasmid_assets import png`; module run: `python3 -m plasmid_assets`.
- Command `plas-assets`: an executable launcher at the repo root that resolves its own directory and runs the package from any working directory. The usage text reads `plas-assets`. Subcommands, flags, stdout and exit codes are unchanged.
- Fixture names (defaults and output names): `schematyc-write --name` default `snl_probe` -> `plasmid_probe`; `pfx-write` `snl_spark_<tag>` -> `plasmid_spark_<tag>` (.dds and .pfx); `audio-write` `snl_beep.wav` -> `plasmid_beep.wav`, `snl_test.xml` -> `plasmid_test.xml`, trigger `Play_snl_beep` -> `Play_plasmid_beep`, ATL name `snl_test` -> `plasmid_test`. The game-relative asset folders (`Objects/snl_test/uvquad.cgf`, `Objects/snl_3p/...`) are unchanged: they name on-disk assets.
- Test environment variable `CRY_REFERENCE_DIR` -> `PLASMID_ASSETS_REFERENCE_DIR`.
- Repo and VERSION: `plasmid-assets` (the repo is `Tools/plasmid-assets/`), VERSION 0.6.0. `.gitignore` gains local env, editor and secret files.
- Migration for vendoring consumers:
  1. Re-vendor the v0.6.0 tag into `tools/plasmid-assets/` (replace `tools/cry-assets/`; never edit the copy in place).
  2. Change imports `cry_assets` -> `plasmid_assets`, and `python3 -m cry_assets` -> `python3 -m plasmid_assets`, or call `tools/plasmid-assets/plas-assets`.
  3. Update any script that passes `--name snl_probe` or reads `snl_spark_*`, `snl_beep.wav` or `Play_snl_beep` to the `plasmid_` names above.
  4. Rename the environment variable `CRY_REFERENCE_DIR` to `PLASMID_ASSETS_REFERENCE_DIR` where it is set.

## 0.5.0

- `cgf-bounds <file.cgf> [--assets-dir D]`: the vertex AABB of a 0x746 .cgf as JSON (`{"file", "min", "max"}`), from
  `cgf_dump.mesh_bounds`. Exit 2 with `cgf-bounds: ...` on stderr when the file cannot be read. Read only.
- `terrain-sample --size N --heightmap {png:PATH,flat:Z,hills:SEED} --max-height M --points "x,y;x,y;..."`: the ground
  height at each point as JSON (`{"points": [{"x", "y", "z"}]}`). Every point must satisfy 0 <= x, y <= N, else exit 2.
  The height is read from the same quantised leaves the writer stores (`terrain.leaf_quantised`, now shared with
  `_write_node`), so it is the height the engine reads from terrain.dat, not the float source. Only the sectors the
  points need are computed (`OnDemandHeights`, `hills_u_at`, which equals `hills()` sample for sample).
- Ground model: `terrain.ground_height` follows `CTerrain::GetZApr` (`Code/CryEngine/Cry3DEngine/terrain_hmap.cpp`,
  lines 133 and 29): the unit cell (int(x), int(y)), its four corners from the leaf sector that owns the lower-left
  unit, triangulated with the diagonal from (x, y) to (x+1, y+1). It is not bilinear.
  Tolerance: the stored height differs from the float32 source sample by at most half the leaf step, span/8190 m of
  that leaf (tests/test_ground.py checks this bound). `terrain-sample` and the parser read-back of the written
  terrain.dat agree exactly (test_ground.py). Engine float32 arithmetic may differ by about 1e-4 m (not measured).
- Not the engine's behaviour in a running game (needs an engine run): the nUnitBitShift == 0 assumption (full
  detail codes at every distance), and the edges. `GetZApr` returns 0 for x <= 0 or y <= 0 and for points at or past
  the far edge; `terrain-sample` returns the clamped edge height there instead.
- Output bytes of terrain-write are unchanged (parity lines, the 2048 hills terrain.dat, and the level pins of the
  mcp tests).

## 0.4.0

- Release note: 0.3.0 (below) and 0.4.0 were developed and committed together in one change, sharing `terrain.py`, `cli.py`,
  the parity file and the tests. They are not separable without inventing an untested state, so the single tag `v0.4.0`
  carries both; there is no `v0.3.0` tag. The 0.3.0 entry below describes what 0.3.0 added and is part of this tag.
- Brushes in `terrain/terrain.dat`: `terrain_dat_bytes(..., brushes=None, assets_dir=None)` and `level_terrain_files`
  take a list of brushes (`cgf`, `pos`, optional `rot` quaternion, `scale`, `material_id`). Output with no brushes is
  byte-identical to 0.3.0 (parity lines unchanged).
- Brush table: one SNameChunk per distinct cgf, first-use order. Object block: one record per brush (int32 EERType 1 +
  100-byte SBrushChunk, `struct` format `BRUSH_CHUNK_FMT`, all offsets from the brush layout research, section 1), under
  the single childless root octree chunk; its objectsBlockSize is 104 per brush. The root chunk AABB is unchanged.
- The stored world AABB is the transformed 8 corners of the .cgf vertex bounds (`cgf_dump.mesh_bounds`, which reads the
  Mesh chunk's POSITIONS stream, float32 or half-float). A missing or unreadable .cgf is a ValueError (exit 2 in the CLI).
- Matrix: row-major 3x4 `[R * diag(scale) | pos]`, the translation at matrix indices 3, 7, 11. Scale composition (each
  column of R times the scale of that axis) is not in the research: unverified.
- Defaults, with sources. From the measured sample record (research section 1, V): layer id 22, shadow bias 0, view
  distance ratio 100, LOD ratio 100, dummy 0, collision class 0, material layers 0. From the research's explicit advice:
  render-node flags 0 and flags 0 (its sample flag word includes ERF_PENDING_DELETE, so it is not copied). Material id -1
  (the sample's value; the only accepted value, since the material table is written empty).
  OPEN QUESTION: layer id 22 is the sample's value, but the research's own minimal example uses 0 and marks the
  layer-0 behaviour U. The engine may treat the layer differently; an engine run should decide.
- Parser: `parse_terrain_dat` returns `brush_names`, `brush_records` (each with cgf, AABB, layer, type index, matrix,
  material id and the other fields) and `warnings`. Strict mode fails on structural faults; a brush AABB whose x or y
  lies outside `(0,0)-(heightmap size x unit)` is a warning in both modes (z is not checked). The strict rule for an empty octree chunk at EOF is now
  a rule for a block of whole records that ends at EOF.
- CLI: `terrain-write --brushes FILE --assets-dir DIR` (exit 2 when only one of the two is given, or on any brush
  error); the manifest gets a `brushes` key only when brushes are given; `terrain-check` prints the brush table size,
  the brush count and the warnings.
- Alignment: every brush table entry and record is a multiple of 4 bytes, so no 0xDE gap is written around the brush
  table or the object block. The research says nothing about alignment there; this follows from the sizes.
- Not in this version: vegetation groups (the parser still refuses a non-empty vegetation table, and its 368-byte
  StatInstGroupChunk constant is the research's open item 6, 364 bytes), child octree nodes, and any check of the
  material table names.
- Not verified: engine rendering, culling and collision of brushes; the layer id default; the z extent of the engine's
  root box; that the engine loads brushes from these bytes (needs an engine run).

## 0.3.0

(Released only inside `v0.4.0`; see the release note above.)

- Terrain files ported from the FPS asset pipeline (stdlib only, byte parity with the FPS writer, commit d131636):
  `cry_assets/terrain.py` (terrain.dat writer with the empty octree chunk and 0xDE gaps, strict and lenient parser,
  `level_terrain_files` for the size-dependent level files, `level_size_attributes` for the XML size fields,
  `make_cover_ctc` and the terraintexture pak, navmesh and vegetation stubs) and `cry_assets/heightmap.py`
  (heightmap.dat writer for sizes 512, 1024 and 2048, `from_png`, `flat`, and `hills`, a deterministic
  integer-hash value noise of our own).
- `png.read_png_gray` reads gray PNGs at full bit depth (1, 2, 4, 8 and 16 bit). `read_png` is unchanged.
- Subcommands: `terrain-write` (writes the level terrain file set and a sha256 manifest) and `terrain-check` (parses a
  terrain.dat and prints its structure; exit 0 or 1).
- Parity: tests/parity.sha256 gained 15 lines (terrain_, heightmap_, cover_ctc_): the FPS sha256 for 3 sizes and 3
  heightmap kinds (terrain.dat), the 512 heightmap.dat for the same kinds, and the cover.ctc member for 3 sizes.
  tests/test_terrain.py checks them; test_parity.py checks only its own names.
- Not parity-bound: the terraintexture pak member date is fixed (1980-01-01), where the FPS writer stamps the current time.
- Not verified: the engine loading a new-size level built from these files (needs an engine run); the template
  cover.ctc kept inside level.pak (it has a different layout from make_cover_ctc output).

## 0.2.0

- Fixture writers ported from the P0(c), P0(d) and P0(i) spike generators, with explicit output directories:
  `pfx` (PFX2 effect JSON and its BC3 texture), `schematyc` (`.schematyc_ent` entity class, with a mesh-path
  parameter in place of the spike's environment variable) and `audio` (440 Hz wav and ATL xml; the caller makes
  the project-root `audio` link, the writer does not).
- Subcommands: `pfx-write`, `schematyc-write`, `audio-write`. They print a JSON list of the written files.
- Output bytes match the spike generators for the same parameters (pfx and audio byte for byte; schematyc with a seeded
  `uuid4`, because its GUIDs are random per run).
- Tests for each writer and CLI smoke tests for the new subcommands.
- Content-hash cache (`cache` module), opt-in with `--cache-dir PATH` on `png2dds` and `gltf2cgf`. The key is the
  sha256 of the PNG bytes, format, srgb, mips, persistent, trailer and `__version__`. A hit copies the stored bytes;
  entries that are short, mis-headed or have the wrong length are ignored and rewritten. Writes go to a temporary
  name and are renamed into place. Without `--cache-dir` nothing is cached.
- `--jobs N` on `png2dds` (encodes block-row bands in worker processes) and `gltf2cgf` (encodes independent
  textures in a process pool). Default 1; 0 means all CPUs. Output is byte-identical for every job count.
- BC encoder: the colour palette distance and the alpha index search are inlined, with the same integer and float
  arithmetic and the same tie-breaking. No algorithm change; output bytes are unchanged.
- `dds.write_dds` takes an optional `jobs` argument (default 1). Its argument checks are in `dds.check_args`.
- `__main__.py` runs `main()` only under `if __name__ == "__main__"`, so spawned workers can import it.

## 0.1.0

- First port of the DDS, CGF and glTF tools from the P0(f) spike. Logic, tables, constants and output
  formatting are unchanged; only imports, module structure and CLI wiring changed.
- Modules: `png` (PNG reader), `dds` (DDS writer and decoder), `cgf` (static-mesh CGF writer), `cgf_dump`
  (CGF dumper), `gltf` (glTF/GLB importer), `cli` (subcommands).
- Subcommands: `png2dds`, `cgf-write`, `cgf-dump`, `gltf2cgf`.
- Stdlib only. Tests are unittest, with fixtures generated in-test.
