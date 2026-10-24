"""terrain.dat writer and parser (OF-09): size formula, header size, 0xDE padding, octree chunk, Sandbox ground truth."""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402

from asset_pipeline.procgen.terrain_dat_parser import TerrainDatError, parse_terrain_dat  # noqa: E402
from asset_pipeline.procgen import terrain_dat_writer  # noqa: E402
from asset_pipeline.procgen.terrain_dat_fix import fix_level_pak, patch_terrain_dat  # noqa: E402
from asset_pipeline.procgen.terrain_dat_writer import ALIGN_FILL, write_terrain_dat  # noqa: E402


def _heights(n: int) -> np.ndarray:
    ys, xs = np.mgrid[0:n, 0:n]
    return (((xs * 37 + ys * 91) % 4096) * 8).astype(np.uint16)


def _write(n: int, **kw) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "terrain.dat"
        write_terrain_dat(path, _heights(n), **kw)
        return path.read_bytes()


class TestTerrainDatWriter(unittest.TestCase):
    def test_size_formula_matches_the_sandboxllm_finding(self):
        # 12 (tables) + 32 (header) + leaves * 4424 + internal * 68 + 32 (octree chunk), from the 2026-10-21 finding.
        for n, leaves, internal in ((256, 64, 21), (512, 256, 85), (1024, 1024, 341)):
            data = _write(n)
            self.assertEqual(len(data), 12 + 32 + leaves * 4424 + internal * 68 + 32, f"{n} m")

    def test_header_counts_the_whole_file(self):
        for n in (256, 512):
            data = _write(n)
            (chunk_size,) = struct.unpack_from("<i", data, 4)
            self.assertEqual(chunk_size, len(data))

    def test_strict_parse_accepts_256_512_and_1024(self):
        for n in (256, 512, 1024):
            info = parse_terrain_dat(_write(n), strict=True)
            self.assertEqual(info["tables"], {"vegetation": 0, "brushes": 0, "materials": 0, "end": 44})
            self.assertEqual(info["octree_chunks"], [{"version": 5, "child_mask": 0, "objects_block_size": 0}])
            self.assertEqual(info["bad_pad_bytes"], 0)

    def test_alignment_gaps_are_0xde(self):
        data = _write(256)
        info = parse_terrain_dat(data, strict=True)  # strict fails on any non-0xDE alignment byte
        self.assertEqual(info["bad_pad_bytes"], 0)
        self.assertEqual(ALIGN_FILL, 0xDE)

    def test_octree_chunk_aabb_spans_the_terrain(self):
        data = _write(512)
        version, mask, x0, y0, z0, x1, y1, z1, objects = struct.unpack("<hh6fi", data[-32:])
        self.assertEqual((version, mask, objects), (5, 0, 0))
        self.assertEqual((x0, y0, x1, y1), (0.0, 0.0, 512.0, 512.0))
        self.assertLessEqual(z0, z1)

    def test_deterministic(self):
        self.assertEqual(_write(256), _write(256))

    def test_old_layout_without_the_octree_chunk_is_rejected_in_strict_mode(self):
        data = bytearray(_write(256))[:-32]
        struct.pack_into("<i", data, 4, len(data))
        with self.assertRaises(TerrainDatError):
            parse_terrain_dat(bytes(data), strict=True)
        parse_terrain_dat(bytes(data))  # non-strict: still a walkable file, just no trailer

    def test_wrong_size_in_header_is_rejected(self):
        data = bytearray(_write(256))
        struct.pack_into("<i", data, 4, len(data) + 1)
        with self.assertRaises(TerrainDatError):
            parse_terrain_dat(bytes(data))


def _old_layout(n: int) -> bytes:
    """What the writer produced before OF-09: 0x00 alignment fill and no object-tree chunk."""
    saved = terrain_dat_writer.ALIGN_FILL
    terrain_dat_writer.ALIGN_FILL = 0
    try:
        data = bytearray(_write(n))[:-32]
    finally:
        terrain_dat_writer.ALIGN_FILL = saved
    struct.pack_into("<i", data, 4, len(data))
    return bytes(data)


class TestTerrainDatFix(unittest.TestCase):
    def test_patching_the_old_layout_reproduces_the_new_writer_output_byte_for_byte(self):
        for n in (256, 512):
            old = _old_layout(n)
            patched, report = patch_terrain_dat(old)
            self.assertEqual(patched, _write(n), f"{n} m")
            self.assertTrue(report["appended_octree_chunk"] and report["changed"])
            self.assertGreater(report["repadded_bytes"], 0)

    def test_patching_is_idempotent(self):
        data = _write(256)
        patched, report = patch_terrain_dat(data)
        self.assertEqual(patched, data)
        self.assertFalse(report["changed"])

    def test_fix_level_pak_keeps_the_other_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            pak = Path(tmp) / "level.pak"
            with zipfile.ZipFile(pak, "w") as zf:
                zf.writestr("levelinfo.xml", "<LevelInfo/>", compress_type=zipfile.ZIP_DEFLATED)
                zf.writestr("terrain/terrain.dat", _old_layout(256), compress_type=zipfile.ZIP_STORED)
                zf.writestr("terrain/cover.ctc", b"\x01\x02\x03", compress_type=zipfile.ZIP_STORED)
            (Path(tmp) / "filelist.xml").write_text('<download name="t" type="Map">\n <files>\n  <file src="level.pak" dest="level.pak" size="1" md5="00"/>\n </files>\n</download>\n', encoding="utf-8")
            self.assertTrue(fix_level_pak(pak, check_only=True)["changed"])
            with zipfile.ZipFile(pak) as zf:  # check_only wrote nothing
                self.assertEqual(len(zf.read("terrain/terrain.dat")), len(_old_layout(256)))
            report = fix_level_pak(Path(tmp))  # folder form
            self.assertTrue(report["changed"])
            with zipfile.ZipFile(pak) as zf:
                self.assertEqual(zf.namelist(), ["levelinfo.xml", "terrain/terrain.dat", "terrain/cover.ctc"])
                self.assertEqual(zf.read("terrain/terrain.dat"), _write(256))
                self.assertEqual(zf.read("terrain/cover.ctc"), b"\x01\x02\x03")
                self.assertEqual(zf.getinfo("levelinfo.xml").compress_type, zipfile.ZIP_DEFLATED)
            import hashlib
            raw = pak.read_bytes()
            filelist = (Path(tmp) / "filelist.xml").read_text(encoding="utf-8")
            self.assertTrue(report["filelist_updated"])
            self.assertIn(f'size="{len(raw)}" md5="{hashlib.md5(raw).hexdigest()}"', filelist)
            second = fix_level_pak(pak)
            self.assertFalse(second["changed"])  # second run does nothing
            self.assertFalse(second["filelist_updated"])


class TestParserOnSandboxFiles(unittest.TestCase):
    """Ground truth: files written by Sandbox itself (stock levels shipped in Assets/levels)."""

    def _terrain(self, level: str) -> bytes:
        pak = ROOT / "Assets" / "levels" / level / "level.pak"
        if not pak.exists():
            self.skipTest(f"{pak} not present")
        with zipfile.ZipFile(pak) as zf:
            return zf.read("terrain/terrain.dat")

    def test_plain_512m_parses_with_its_tables_and_0xde_padding(self):
        info = parse_terrain_dat(self._terrain("plain"))
        self.assertEqual((info["nodes"], info["leaves"]), (341, 256))
        self.assertEqual(info["bad_pad_bytes"], 0)  # Sandbox pads with 0xDE too
        self.assertEqual(info["octree_chunks"][0]["version"], 5)

    def test_fix_leaves_sandbox_files_alone(self):
        for level in ("plain", "example"):
            patched, report = patch_terrain_dat(self._terrain(level))
            self.assertFalse(report["changed"], level)

    def test_example_1024m_ends_in_exactly_the_empty_octree_chunk_we_write(self):
        data = self._terrain("example")
        info = parse_terrain_dat(data, strict=True)
        self.assertEqual(len(data) - info["nodes_end"], 32)


if __name__ == "__main__":
    unittest.main()
