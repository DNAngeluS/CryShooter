from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from asset_pipeline.procgen.noise_utils import octave_noise_2d
from asset_pipeline.procgen.heightmap_writer import write_heightmap_dat, flat_heightmap
from asset_pipeline.procgen.mesh_writer import write_obj, write_mtl, add_box_mesh
from asset_pipeline.procgen.classifier import classify_level
from asset_pipeline.procgen.terrain_gen import generate_open_terrain
from asset_pipeline.procgen.interior_gen import generate_interior
from asset_pipeline.procgen.structured_gen import generate_structured
from asset_pipeline.asset_graph import AssetGraphValidationError, validate_asset_graph
from asset_pipeline.pipeline import AssetPipeline
import numpy as np


def _seed_pipeline_root(root: Path) -> None:
    (root / "Assets").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "asset_pipeline").mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT_ROOT / "tools" / "asset_pipeline" / "templates",
                    root / "tools" / "asset_pipeline" / "templates")
    shutil.copytree(PROJECT_ROOT / "Assets" / "levels" / "plain",
                    root / "Assets" / "levels" / "plain")
    shutil.copytree(PROJECT_ROOT / "Assets" / "levels" / "example",
                    root / "Assets" / "levels" / "example")
    shutil.copy2(PROJECT_ROOT / "Assets" / "levels" / "plain.level.cryasset",
                 root / "Assets" / "levels" / "plain.level.cryasset")
    shutil.copy2(PROJECT_ROOT / "Assets" / "levels" / "example.level.cryasset",
                 root / "Assets" / "levels" / "example.level.cryasset")
    shutil.copytree(PROJECT_ROOT / "Assets" / "Objects" / "default",
                    root / "Assets" / "Objects" / "default")


# ---------------------------------------------------------------------------
# Noise utils
# ---------------------------------------------------------------------------

class TestNoiseUtils(unittest.TestCase):
    def test_octave_noise_deterministic(self):
        a = octave_noise_2d(32, 32, seed=7)
        b = octave_noise_2d(32, 32, seed=7)
        np.testing.assert_array_equal(a, b)

    def test_octave_noise_different_seeds_differ(self):
        a = octave_noise_2d(32, 32, seed=1)
        b = octave_noise_2d(32, 32, seed=2)
        self.assertFalse(np.array_equal(a, b))

    def test_octave_noise_range(self):
        arr = octave_noise_2d(64, 64, seed=42)
        self.assertGreaterEqual(float(arr.min()), 0.0)
        self.assertLessEqual(float(arr.max()), 1.0)

    def test_octave_noise_shape(self):
        arr = octave_noise_2d(128, 64, seed=0)
        self.assertEqual(arr.shape, (64, 128))


# ---------------------------------------------------------------------------
# Heightmap writer
# ---------------------------------------------------------------------------

class TestHeightmapWriter(unittest.TestCase):
    def test_write_512(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heightmap.dat"
            heights = flat_heightmap(512, elevation_m=32.0)
            write_heightmap_dat(path, heights)
            data = path.read_bytes()
            # 3-byte prefix check
            self.assertEqual(data[:3], b'\xff\x5a\x03')
            # XML header contains Width="512"
            self.assertIn(b'Width="512"', data)

    def test_write_1024(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heightmap.dat"
            heights = flat_heightmap(1024, elevation_m=0.0)
            write_heightmap_dat(path, heights)
            data = path.read_bytes()
            self.assertEqual(data[:3], b'\xff\x5d\x03')
            self.assertIn(b'Width="1024"', data)

    def test_height_encoding(self):
        # 0 m → uint16 = 0; 1024 m → uint16 = 65535
        h_zero = flat_heightmap(512, elevation_m=0.0)
        h_max = flat_heightmap(512, elevation_m=1024.0)
        self.assertEqual(int(h_zero[0, 0]), 0)
        self.assertEqual(int(h_max[0, 0]), 65535)

    def test_flat_heightmap_uniform(self):
        h = flat_heightmap(512, elevation_m=50.0)
        self.assertEqual(h.min(), h.max())

    def test_unsupported_size_raises(self):
        with self.assertRaises(ValueError):
            write_heightmap_dat(Path("/dev/null"), flat_heightmap(256, 0))


# ---------------------------------------------------------------------------
# Mesh writer
# ---------------------------------------------------------------------------

class TestMeshWriter(unittest.TestCase):
    def test_box_mesh_produces_12_triangles(self):
        v, f, u, ui, m = [], [], [], [], []
        add_box_mesh(v, f, u, ui, m, min_corner=(0,0,0), max_corner=(1,1,1), material_id=0)
        self.assertEqual(len(f), 12)
        self.assertEqual(len(v), 8)

    def test_face_indices_valid(self):
        v, f, u, ui, m = [], [], [], [], []
        add_box_mesh(v, f, u, ui, m, min_corner=(0,0,0), max_corner=(4,4,4), material_id=0)
        for tri in f:
            for idx in tri:
                self.assertGreaterEqual(idx, 0)
                self.assertLess(idx, len(v))

    def test_uv_scale_with_size(self):
        """A 4×4×4 m box face should have UV span up to 4.0."""
        v, f, u, ui, m = [], [], [], [], []
        add_box_mesh(v, f, u, ui, m, min_corner=(0,0,0), max_corner=(4,4,4), material_id=0)
        max_u = max(uv[0] for uv in u)
        self.assertAlmostEqual(max_u, 4.0)

    def test_write_obj_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            v, f, u, ui, m = [], [], [], [], []
            add_box_mesh(v, f, u, ui, m, min_corner=(0,0,0), max_corner=(2,2,2))
            path = Path(tmp) / "test.obj"
            write_obj(path, v, f, u, ui, m, ["default"])
            content = path.read_text(encoding="utf-8")
            self.assertIn("mtllib", content)
            self.assertIn("v ", content)
            self.assertIn("f ", content)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TestClassifier(unittest.TestCase):
    def test_explicit_subtype(self):
        cat, sub = classify_level("terrain_procgen", {"subtype": "desert"})
        self.assertEqual(cat, "open")
        self.assertEqual(sub, "desert")

    def test_keyword_fallback(self):
        cat, sub = classify_level("interior_procgen", {"subtype": "", "name": "dark cave system"})
        self.assertEqual(cat, "interior")
        self.assertEqual(sub, "cave")

    def test_default_fallback(self):
        cat, sub = classify_level("structured_procgen", {"subtype": ""})
        self.assertEqual(cat, "structured")
        self.assertEqual(sub, "arena")

    def test_unknown_node_type_raises(self):
        with self.assertRaises(ValueError):
            classify_level("unknown_type", {})


# ---------------------------------------------------------------------------
# Terrain generator
# ---------------------------------------------------------------------------

class TestTerrainGen(unittest.TestCase):
    def test_forest_deterministic(self):
        spec = {"subtype": "forest", "seed": 99, "erosion_passes": 2}
        r1 = generate_open_terrain(spec, seed=99, heightmap_size=64, max_height_m=200.0)
        r2 = generate_open_terrain(spec, seed=99, heightmap_size=64, max_height_m=200.0)
        np.testing.assert_array_equal(r1.heights_uint16, r2.heights_uint16)

    def test_different_seeds_differ(self):
        spec = {"subtype": "forest"}
        r1 = generate_open_terrain(spec, seed=1, heightmap_size=64, max_height_m=200.0)
        r2 = generate_open_terrain(spec, seed=2, heightmap_size=64, max_height_m=200.0)
        self.assertFalse(np.array_equal(r1.heights_uint16, r2.heights_uint16))

    def test_heights_have_variation(self):
        spec = {"subtype": "forest"}
        r = generate_open_terrain(spec, seed=42, heightmap_size=64, max_height_m=200.0)
        self.assertGreater(int(r.heights_uint16.max()) - int(r.heights_uint16.min()), 100)

    def test_spawn_hint_in_bounds(self):
        spec = {"subtype": "forest"}
        r = generate_open_terrain(spec, seed=42, heightmap_size=64, max_height_m=200.0)
        hints = r.procgen_json["spawn_hints"]
        self.assertTrue(len(hints) > 0)
        pos = hints[0]["position_m"]
        world_size = 64 * 2  # heightmap_size * unit_size
        self.assertGreaterEqual(pos[0], 0)
        self.assertLessEqual(pos[0], world_size)

    def test_paint_zone_hints_present(self):
        spec = {"subtype": "forest"}
        r = generate_open_terrain(spec, seed=42, heightmap_size=64, max_height_m=200.0)
        hints = r.procgen_json["paint_zone_hints"]
        self.assertTrue(len(hints) > 0)
        zones = {h["zone"] for h in hints}
        self.assertIn("base", zones)

    def test_output_dtype_uint16(self):
        spec = {"subtype": "tundra"}
        r = generate_open_terrain(spec, seed=5, heightmap_size=64, max_height_m=200.0)
        self.assertEqual(r.heights_uint16.dtype, np.uint16)

    def test_desert_subtype(self):
        spec = {"subtype": "desert", "erosion_passes": 3}
        r = generate_open_terrain(spec, seed=42, heightmap_size=64, max_height_m=200.0)
        self.assertEqual(r.heights_uint16.shape, (64, 64))


# ---------------------------------------------------------------------------
# Interior generator
# ---------------------------------------------------------------------------

class TestInteriorGen(unittest.TestCase):
    def test_cave_has_sectors(self):
        r = generate_interior({"subtype": "cave"}, seed=42, world_size_m=64.0)
        self.assertTrue(len(r.procgen_json["sectors"]) > 0)

    def test_cave_has_spawn_hint(self):
        r = generate_interior({"subtype": "cave"}, seed=42, world_size_m=64.0)
        self.assertTrue(len(r.procgen_json["spawn_hints"]) > 0)

    def test_cave_has_geometry(self):
        r = generate_interior({"subtype": "cave"}, seed=42, world_size_m=64.0)
        self.assertTrue(len(r.vertices) > 0)
        self.assertTrue(len(r.faces) > 0)

    def test_dungeon_sectors_no_overlap(self):
        r = generate_interior({"subtype": "dungeon", "min_rooms": 3, "max_rooms": 5}, seed=42, world_size_m=128.0)
        rooms = [s for s in r.procgen_json["sectors"] if s["sector_type"] == "room"]
        self.assertGreater(len(rooms), 0)
        # Check no two rooms have same sector_id
        ids = [s["sector_id"] for s in rooms]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ship_connected(self):
        r = generate_interior({"subtype": "ship", "min_rooms": 3, "max_rooms": 5}, seed=7, world_size_m=128.0)
        self.assertTrue(len(r.procgen_json["sectors"]) > 0)

    def test_obj_face_indices_valid(self):
        r = generate_interior({"subtype": "dungeon", "min_rooms": 3, "max_rooms": 4}, seed=1, world_size_m=64.0)
        n_verts = len(r.vertices)
        for tri in r.faces:
            for idx in tri:
                self.assertGreaterEqual(idx, 0)
                self.assertLess(idx, n_verts)

    def test_category_in_procgen_json(self):
        r = generate_interior({"subtype": "cave"}, seed=42, world_size_m=64.0)
        self.assertEqual(r.procgen_json["level_category"], "interior")


# ---------------------------------------------------------------------------
# Structured generator
# ---------------------------------------------------------------------------

class TestStructuredGen(unittest.TestCase):
    def test_arena_has_perimeter_walls(self):
        r = generate_structured({"subtype": "arena"}, seed=42, world_size_m=96.0)
        wall_sectors = [s for s in r.procgen_json["sectors"]
                        if s["sector_type"] in ("wall", "tower", "gate")]
        self.assertTrue(len(wall_sectors) > 0)

    def test_arena_has_spawn_in_courtyard(self):
        r = generate_structured({"subtype": "arena"}, seed=42, world_size_m=96.0)
        self.assertTrue(len(r.procgen_json["spawn_hints"]) > 0)

    def test_castle_deterministic(self):
        spec = {"subtype": "castle", "cell_size_m": 12, "wall_height_m": 8}
        r1 = generate_structured(spec, seed=10, world_size_m=120.0)
        r2 = generate_structured(spec, seed=10, world_size_m=120.0)
        ids1 = [s["sector_id"] for s in r1.procgen_json["sectors"]]
        ids2 = [s["sector_id"] for s in r2.procgen_json["sectors"]]
        self.assertEqual(ids1, ids2)

    def test_obj_face_indices_valid(self):
        r = generate_structured({"subtype": "arena"}, seed=42, world_size_m=96.0)
        n_verts = len(r.vertices)
        for tri in r.faces:
            for idx in tri:
                self.assertGreaterEqual(idx, 0)
                self.assertLess(idx, n_verts)

    def test_category_in_procgen_json(self):
        r = generate_structured({"subtype": "fortress"}, seed=5, world_size_m=120.0)
        self.assertEqual(r.procgen_json["level_category"], "structured")


# ---------------------------------------------------------------------------
# Asset graph validation for new node types
# ---------------------------------------------------------------------------

def _terrain_procgen_graph(slug: str) -> dict:
    return {
        "asset_kind": "level",
        "bundle_kind": "environment_package",
        "bundle_slug": slug,
        "summary": "Procgen forest test",
        "root_scene": "scene_main",
        "nodes": [
            {
                "id": "texture_ground",
                "type": "texture_source",
                "inputs": {},
                "outputs": {},
                "spec": {"name": "ground", "mode": "solid_color", "width": 64, "height": 64, "rgba": [80, 100, 60, 255]},
            },
            {
                "id": "material_ground",
                "type": "material_surface",
                "inputs": {"diffuse_texture": "texture_ground"},
                "outputs": {},
                "spec": {"name": "ground_mat", "template": "default_illum", "surface_type": "mat_default"},
            },
            {
                "id": "terrain_main",
                "type": "terrain_procgen",
                "inputs": {"paint_materials": ["material_ground"]},
                "outputs": {},
                "spec": {
                    "name": "forest_terrain",
                    "subtype": "forest",
                    "heightmap_size": 512,
                    "world_size_m": 512,
                    "max_height_m": 200.0,
                    "seed": 42,
                    "erosion_passes": 2,
                    "paint_zone_config": {"base": "material_ground"},
                    "foliage_density": 0.5,
                    "template_profile": "basin",
                },
            },
            {
                "id": "placements_main",
                "type": "object_placement_set",
                "inputs": {"mesh_nodes": []},
                "outputs": {},
                "spec": {
                    "placements": [
                        {
                            "name": "placeholder",
                            "target_node": "placeholder_mesh",
                            "layer": "Main",
                            "transform": {"position": [256, 256, 0], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]},
                        }
                    ]
                },
            },
            {
                "id": "scene_main",
                "type": "scene_level",
                "inputs": {"terrain": "terrain_main", "placement_sets": []},
                "outputs": {},
                "spec": {
                    "level_slug": slug,
                    "display_name": "Test Forest",
                    "lighting": {
                        "preset": "%ENGINE%/EngineAssets/Shading/default.env",
                        "time_of_day": "afternoon",
                        "time_hour": 15,
                        "sun_rotation": 240,
                        "sun_height": 55,
                        "sun_vector": "-0.5,-0.3,-0.8",
                    },
                    "spawn": {
                        "layer": "Main",
                        "transform": {"position": [256, 256, 42], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]},
                    },
                },
            },
        ],
    }


def _interior_procgen_graph(slug: str, subtype: str = "cave") -> dict:
    return {
        "asset_kind": "level",
        "bundle_kind": "environment_package",
        "bundle_slug": slug,
        "summary": f"Procgen {subtype} test",
        "root_scene": "scene_main",
        "nodes": [
            {
                "id": "terrain_main",
                "type": "interior_procgen",
                "inputs": {},
                "outputs": {},
                "spec": {
                    "name": f"{subtype}_level",
                    "subtype": subtype,
                    "world_size_m": 64,
                    "seed": 7,
                    "min_rooms": 3,
                    "max_rooms": 6,
                    "corridor_width_m": 3.0,
                    "wall_height_m": 4.0,
                },
            },
            {
                "id": "scene_main",
                "type": "scene_level",
                "inputs": {"terrain": "terrain_main", "placement_sets": []},
                "outputs": {},
                "spec": {
                    "level_slug": slug,
                    "display_name": f"Test {subtype.title()}",
                    "lighting": {
                        "preset": "%ENGINE%/EngineAssets/Shading/default.env",
                        "time_of_day": "night",
                        "time_hour": 0,
                        "sun_rotation": 0,
                        "sun_height": 0,
                        "sun_vector": "0,0,-1",
                    },
                    "spawn": {
                        "layer": "Main",
                        "transform": {"position": [32, 32, 5], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]},
                    },
                },
            },
        ],
    }


def _structured_procgen_graph(slug: str, subtype: str = "arena") -> dict:
    return {
        "asset_kind": "level",
        "bundle_kind": "environment_package",
        "bundle_slug": slug,
        "summary": f"Procgen {subtype} test",
        "root_scene": "scene_main",
        "nodes": [
            {
                "id": "terrain_main",
                "type": "structured_procgen",
                "inputs": {},
                "outputs": {},
                "spec": {
                    "name": f"{subtype}_level",
                    "subtype": subtype,
                    "world_size_m": 120,
                    "seed": 5,
                    "cell_size_m": 12.0,
                    "wall_height_m": 8.0,
                },
            },
            {
                "id": "scene_main",
                "type": "scene_level",
                "inputs": {"terrain": "terrain_main", "placement_sets": []},
                "outputs": {},
                "spec": {
                    "level_slug": slug,
                    "display_name": f"Test {subtype.title()}",
                    "lighting": {
                        "preset": "%ENGINE%/EngineAssets/Shading/default.env",
                        "time_of_day": "noon",
                        "time_hour": 12,
                        "sun_rotation": 180,
                        "sun_height": 80,
                        "sun_vector": "0,-0.1,-1",
                    },
                    "spawn": {
                        "layer": "Main",
                        "transform": {"position": [60, 60, 5], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]},
                    },
                },
            },
        ],
    }


class TestAssetGraphProcgenValidation(unittest.TestCase):
    def test_terrain_procgen_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pipeline_root(root)
            g = _terrain_procgen_graph("test-forest")
            # Remove the broken placement node and reference
            g["nodes"] = [n for n in g["nodes"] if n["id"] not in ("placements_main",)]
            validated = validate_asset_graph(g, root=root)
            self.assertIn("dependency_order", validated)

    def test_interior_procgen_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pipeline_root(root)
            g = _interior_procgen_graph("test-cave", "cave")
            validated = validate_asset_graph(g, root=root)
            self.assertIn("dependency_order", validated)

    def test_structured_procgen_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pipeline_root(root)
            g = _structured_procgen_graph("test-arena", "arena")
            validated = validate_asset_graph(g, root=root)
            self.assertIn("dependency_order", validated)

    def test_unknown_subtype_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pipeline_root(root)
            g = _interior_procgen_graph("test-bad", "underwater_city")
            with self.assertRaises(AssetGraphValidationError):
                validate_asset_graph(g, root=root)

    def test_missing_seed_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_pipeline_root(root)
            g = _structured_procgen_graph("test-noseed", "arena")
            g["nodes"][0]["spec"].pop("seed")
            with self.assertRaises(AssetGraphValidationError):
                validate_asset_graph(g, root=root)


# ---------------------------------------------------------------------------
# Integration: full pipeline build
# ---------------------------------------------------------------------------

class TestProcgenPipelineIntegration(unittest.TestCase):
    def _make_pipeline(self, tmp: str) -> tuple[AssetPipeline, Path]:
        root = Path(tmp)
        _seed_pipeline_root(root)
        pipeline = AssetPipeline(root=root)
        return pipeline, root

    def test_terrain_procgen_full_build(self):
        import struct, zipfile as _zipfile
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, root = self._make_pipeline(tmp)
            graph = _terrain_procgen_graph("test-procgen-forest")
            graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in ("placements_main",)]
            job = pipeline.create_job("level", "test forest", target_package="test-procgen-forest")
            pipeline.author_spec(job["job_id"], asset_graph=graph)
            manifest = pipeline.build(job["job_id"])
            self.assertIsNotNone(manifest)
            stage_dir = root / "user" / "asset_pipeline" / "jobs" / job["job_id"]
            heightmap_files = list(stage_dir.rglob("heightmap.dat"))
            self.assertTrue(len(heightmap_files) > 0, "heightmap.dat not generated")
            # Verify generated terrain.dat is inside level.pak with correct header
            paks = list(stage_dir.rglob("level.pak"))
            self.assertTrue(len(paks) > 0, "level.pak not found")
            with _zipfile.ZipFile(paks[0]) as z:
                self.assertIn("terrain/terrain.dat", z.namelist(), "terrain.dat missing from level.pak")
                dat = z.read("terrain/terrain.dat")
                ver = struct.unpack_from("<b", dat, 0)[0]
                chunk_size = struct.unpack_from("<i", dat, 4)[0]
                self.assertEqual(ver, 29, "terrain.dat version must be 29")
                self.assertEqual(chunk_size, len(dat), "terrain.dat nChunkSize must equal file size")

    def test_interior_procgen_cave_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, root = self._make_pipeline(tmp)
            graph = _interior_procgen_graph("test-cave-build", "cave")
            job = pipeline.create_job("level", "test cave", target_package="test-cave-build")
            pipeline.author_spec(job["job_id"], asset_graph=graph)
            manifest = pipeline.build(job["job_id"])
            self.assertIsNotNone(manifest)
            stage_dir = root / "user" / "asset_pipeline" / "jobs" / job["job_id"]
            obj_files = list(stage_dir.rglob("*.obj"))
            self.assertTrue(len(obj_files) > 0, "OBJ geometry not staged")

    def test_structured_procgen_arena_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline, root = self._make_pipeline(tmp)
            graph = _structured_procgen_graph("test-arena-build", "arena")
            job = pipeline.create_job("level", "test arena", target_package="test-arena-build")
            pipeline.author_spec(job["job_id"], asset_graph=graph)
            manifest = pipeline.build(job["job_id"])
            self.assertIsNotNone(manifest)

    def test_same_seed_produces_identical_heightmap(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            for tmp, slug in [(tmp1, "seed-test-a"), (tmp2, "seed-test-b")]:
                root = Path(tmp)
                _seed_pipeline_root(root)
                pipeline = AssetPipeline(root=root)
                graph = _terrain_procgen_graph(slug)
                graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in ("placements_main",)]
                job = pipeline.create_job("level", "seed test", target_package=slug)
                pipeline.author_spec(job["job_id"], asset_graph=graph)
                pipeline.build(job["job_id"])

            stage_a = Path(tmp1) / "user" / "asset_pipeline" / "jobs"
            stage_b = Path(tmp2) / "user" / "asset_pipeline" / "jobs"
            h_a = list(stage_a.rglob("heightmap.dat"))[0].read_bytes()
            h_b = list(stage_b.rglob("heightmap.dat"))[0].read_bytes()
            self.assertEqual(h_a, h_b, "Same seed must produce identical heightmap.dat")


if __name__ == "__main__":
    unittest.main()
