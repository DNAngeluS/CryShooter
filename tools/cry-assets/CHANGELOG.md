# Changelog

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
