from __future__ import annotations

import json
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

from asset_pipeline.asset_graph import AssetGraphValidationError
from asset_pipeline.mesh_converter import convert_mesh_job
from asset_pipeline.pipeline import AssetPipeline


def _seed_pipeline_root(root: Path) -> None:
    (root / "Assets").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "asset_pipeline").mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT_ROOT / "tools" / "asset_pipeline" / "templates", root / "tools" / "asset_pipeline" / "templates")
    shutil.copytree(PROJECT_ROOT / "Assets" / "levels" / "plain", root / "Assets" / "levels" / "plain")
    shutil.copytree(PROJECT_ROOT / "Assets" / "levels" / "example", root / "Assets" / "levels" / "example")
    shutil.copy2(PROJECT_ROOT / "Assets" / "levels" / "plain.level.cryasset", root / "Assets" / "levels" / "plain.level.cryasset")
    shutil.copy2(PROJECT_ROOT / "Assets" / "levels" / "example.level.cryasset", root / "Assets" / "levels" / "example.level.cryasset")
    shutil.copytree(PROJECT_ROOT / "Assets" / "Objects" / "default", root / "Assets" / "Objects" / "default")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _environment_graph(slug: str, *, include_imported_mesh: bool = False) -> dict:
    nodes = [
        {
            "id": "texture_ground",
            "type": "texture_source",
            "inputs": {},
            "outputs": {},
            "spec": {
                "name": "forest_ground_albedo",
                "mode": "procedural_pattern",
                "width": 256,
                "height": 256,
                "pattern": "checker",
                "palette": [[88, 110, 58, 255], [116, 96, 62, 255], [132, 126, 84, 255]],
            },
        },
        {
            "id": "texture_mask",
            "type": "texture_source",
            "inputs": {},
            "outputs": {},
            "spec": {
                "name": "clover_patch_mask",
                "mode": "solid_color",
                "width": 128,
                "height": 128,
                "rgba": [180, 200, 180, 255],
            },
        },
        {
            "id": "material_ground",
            "type": "material_surface",
            "inputs": {"diffuse_texture": "texture_ground"},
            "outputs": {},
            "spec": {
                "name": "forest_ground",
                "template": "default_illum",
                "surface_type": "mat_default",
            },
        },
        {
            "id": "terrain_main",
            "type": "terrain_archetype",
            "inputs": {"paint_materials": ["material_ground"], "foliage_meshes": []},
            "outputs": {},
            "spec": {
                "template_profile": "basin",
                "heightmap_size": 1024,
                "paint_zones": [{"material_node": "material_ground", "zone": "base", "coverage": 1.0}],
                "foliage_zones": [],
            },
        },
        {
            "id": "mesh_cover_box",
            "type": "mesh_procedural",
            "inputs": {"material": "material_ground"},
            "outputs": {},
            "spec": {
                "name": "cover_box",
                "archetype": "box",
                "dimensions": [2.0, 1.2, 1.0],
            },
        },
    ]
    mesh_nodes = ["mesh_cover_box"]
    placements = [
        {
            "name": "cover-box-01",
            "target_node": "mesh_cover_box",
            "layer": "Main",
            "transform": {
                "position": [480, 500, 32],
                "rotation": [1, 0, 0, 0],
                "scale": [1, 1, 1],
            },
        }
    ]
    if include_imported_mesh:
        nodes.append(
            {
                "id": "mesh_imported_crate",
                "type": "mesh_import",
                "inputs": {},
                "outputs": {},
                "spec": {
                    "name": "crate",
                    "mesh_kind": "static_mesh",
                    "source_file": "__IMPORT_ME__",
                    "target_path": f"Objects/Imported/{slug}/crate",
                },
            }
        )
        mesh_nodes.append("mesh_imported_crate")
        placements.append(
            {
                "name": "crate-cover-01",
                "target_node": "mesh_imported_crate",
                "layer": "Main",
                "transform": {
                    "position": [520, 516, 32],
                    "rotation": [1, 0, 0, 0],
                    "scale": [1, 1, 1],
                },
            }
        )
    nodes.extend(
        [
            {
                "id": "placements_main",
                "type": "object_placement_set",
                "inputs": {"mesh_nodes": mesh_nodes},
                "outputs": {},
                "spec": {"placements": placements},
            },
            {
                "id": "scene_main",
                "type": "scene_level",
                "inputs": {"terrain": "terrain_main", "placement_sets": ["placements_main"]},
                "outputs": {},
                "spec": {
                    "level_slug": slug,
                    "display_name": "Forest Basin",
                    "lighting": {
                        "preset": "%ENGINE%/EngineAssets/Shading/default.env",
                        "time_of_day": "afternoon",
                        "time_hour": 15,
                        "sun_rotation": 240,
                        "sun_height": 55,
                        "sun_vector": "-0.51961529,-0.29999986,-0.79999995",
                    },
                    "spawn": {
                        "layer": "Main",
                        "transform": {
                            "position": [512, 512, 42],
                            "rotation": [1, 0, 0, 0],
                            "scale": [1, 1, 1],
                        },
                    },
                },
            },
        ]
    )
    return {
        "asset_kind": "level",
        "bundle_kind": "environment_package",
        "bundle_slug": slug,
        "summary": "Environment bundle",
        "root_scene": "scene_main",
        "nodes": nodes,
    }


def _character_graph(slug: str, source_file: str) -> dict:
    return {
        "asset_kind": "character_package",
        "bundle_kind": "character_package",
        "bundle_slug": slug,
        "summary": "First person character package",
        "root_scene": "character_main",
        "nodes": [
            {
                "id": "character_source",
                "type": "mesh_import",
                "inputs": {},
                "outputs": {},
                "spec": {
                    "name": slug,
                    "mesh_kind": "character_source",
                    "source_file": source_file,
                    "target_path": f"Objects/Characters/{slug}/{slug}",
                },
            },
            {
                "id": "character_main",
                "type": "character_fp_package",
                "inputs": {"source_mesh": "character_source"},
                "outputs": {},
                "spec": {
                    "character_name": slug,
                    "controller_scope": "FirstPersonCharacter",
                    "default_fragment": "Idle",
                    "skeleton_file": f"Objects/Characters/{slug}/{slug}.chr",
                    "skin_file": f"Objects/Characters/{slug}/{slug}.skin",
                    "attachment_bone": "R_hand",
                },
            },
        ],
    }


class AssetPipelineTests(unittest.TestCase):
    def test_environment_bundle_builds_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Forest basin arena", target_package="fps_forest_basin")
            pipeline.plan_spec(request["job_id"])
            graph_path = root / "graph.json"
            _write_json(graph_path, _environment_graph("fps_forest_basin"))
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))

            build_manifest = pipeline.build(request["job_id"])
            self.assertEqual(build_manifest["bundle_kind"], "environment_package")
            validation = pipeline.validate(request["job_id"])
            self.assertEqual(validation["status"], "passed")
            publish = pipeline.publish(request["job_id"])
            self.assertIn("levels/fps_forest_basin/terraintexture.pak", publish["published_paths"])
            self.assertTrue((root / "Assets" / "Textures" / "Generated" / "fps_forest_basin" / "forest_ground_albedo.png").exists())
            self.assertTrue((root / "Assets" / "Materials" / "Generated" / "fps_forest_basin" / "forest_ground.mtl").exists())
            dds = root / "Assets" / "Textures" / "Generated" / "fps_forest_basin" / "forest_ground_albedo.dds"
            self.assertTrue(dds.exists())
            self.assertEqual(dds.read_bytes()[:4], b"DDS ")  # runtime texture; the material must reference it, not the PNG
            mtl_text = (root / "Assets" / "Materials" / "Generated" / "fps_forest_basin" / "forest_ground.mtl").read_text(encoding="utf-8")
            self.assertIn("forest_ground_albedo.dds", mtl_text)
            self.assertNotIn(".png", mtl_text)
            # terrain paint materials are terrain LAYER materials (stock form), not Illum
            self.assertIn('Shader="Terrain.Layer"', mtl_text)
            self.assertIn('StringGenMask="%TEMP_TERRAIN"', mtl_text)
            self.assertIn("BlendFalloff", mtl_text)

    def test_mixed_graph_supports_procedural_and_imported_meshes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            imported_source = root / "crate.cgf"
            imported_source.write_bytes(b"fakecgf")
            graph = _environment_graph("mixed-environment", include_imported_mesh=True)
            for node in graph["nodes"]:
                if node["id"] == "mesh_imported_crate":
                    node["spec"]["source_file"] = str(imported_source)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Arena with crate", target_package="mixed-environment")
            pipeline.plan_spec(request["job_id"])
            graph_path = root / "graph.json"
            _write_json(graph_path, graph)
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))
            pipeline.build(request["job_id"])
            validation = pipeline.validate(request["job_id"])
            self.assertEqual(validation["status"], "passed")
            main_layer = (root / "user" / "asset_pipeline" / "jobs" / request["job_id"] / "staged_assets" / "Assets" / "levels" / "mixed-environment" / "layers" / "main.lyr").read_text(encoding="utf-8")
            self.assertIn("Objects/Imported/mixed-environment/crate.cgf", main_layer)
            self.assertIn("Objects/Generated/mixed-environment/cover_box.cgf", main_layer)

    def test_author_spec_rejects_unsupported_freeform_mesh_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Bad mesh", target_package="bad-mesh")
            pipeline.plan_spec(request["job_id"])
            graph = _environment_graph("bad-mesh")
            for node in graph["nodes"]:
                if node["id"] == "mesh_cover_box":
                    node["spec"]["vertices"] = [[0, 0, 0]]
            graph_path = root / "graph.json"
            _write_json(graph_path, graph)
            with self.assertRaises(AssetGraphValidationError):
                pipeline.author_spec(request["job_id"], json_file=str(graph_path))

    def test_author_spec_rejects_template_only_terrain_without_paint_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Bad terrain", target_package="bad-terrain")
            pipeline.plan_spec(request["job_id"])
            graph = _environment_graph("bad-terrain")
            for node in graph["nodes"]:
                if node["id"] == "terrain_main":
                    node["inputs"]["paint_materials"] = []
                    node["spec"]["paint_zones"] = []
            graph_path = root / "graph.json"
            _write_json(graph_path, graph)
            with self.assertRaises(AssetGraphValidationError):
                pipeline.author_spec(request["job_id"], json_file=str(graph_path))

    def test_build_fails_when_import_texture_source_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Missing imported texture", target_package="missing-texture")
            pipeline.plan_spec(request["job_id"])
            graph = _environment_graph("missing-texture")
            for node in graph["nodes"]:
                if node["id"] == "texture_ground":
                    node["spec"] = {
                        "name": "forest_ground_albedo",
                        "mode": "import",
                        "source_file": str(root / "does-not-exist.png"),
                    }
            graph_path = root / "graph.json"
            _write_json(graph_path, graph)
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))
            with self.assertRaises(FileNotFoundError):
                pipeline.build(request["job_id"])

    def test_character_package_builds_from_import_plus_template_rig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            source = root / "hero.fbx"
            source.write_text("FBX_PLACEHOLDER\n", encoding="utf-8")
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("character_package", "First person hero", target_package="samplehero")
            pipeline.plan_spec(request["job_id"])
            graph_path = root / "character.json"
            _write_json(graph_path, _character_graph("samplehero", str(source)))
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))
            build_manifest = pipeline.build(request["job_id"])
            self.assertEqual(build_manifest["bundle_kind"], "character_package")
            validation = pipeline.validate(request["job_id"])
            self.assertEqual(validation["status"], "passed")
            publish = pipeline.publish(request["job_id"])
            self.assertIn("Objects/Characters/samplehero/firstperson.cdf", publish["published_paths"])
            self.assertIn("Animations/Mannequin/ADB/sampleheroFirstPerson.adb", publish["published_paths"])

    def test_author_spec_rejects_character_graph_missing_template_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            source = root / "hero.fbx"
            source.write_text("FBX_PLACEHOLDER\n", encoding="utf-8")
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("character_package", "Bad hero", target_package="badhero")
            pipeline.plan_spec(request["job_id"])
            graph = _character_graph("badhero", str(source))
            del graph["nodes"][1]["spec"]["controller_scope"]
            graph_path = root / "bad-character.json"
            _write_json(graph_path, graph)
            with self.assertRaises(AssetGraphValidationError):
                pipeline.author_spec(request["job_id"], json_file=str(graph_path))

    def test_dependency_order_builds_texture_then_material_then_mesh_then_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Dependency order", target_package="dependency-order")
            pipeline.plan_spec(request["job_id"])
            graph_path = root / "graph.json"
            _write_json(graph_path, _environment_graph("dependency-order"))
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))
            build_manifest = pipeline.build(request["job_id"])
            node_ids = [report["node_id"] for report in build_manifest["node_reports"]]
            self.assertLess(node_ids.index("texture_ground"), node_ids.index("material_ground"))
            self.assertLess(node_ids.index("material_ground"), node_ids.index("mesh_cover_box"))
            self.assertLess(node_ids.index("mesh_cover_box"), node_ids.index("placements_main"))
            self.assertLess(node_ids.index("placements_main"), node_ids.index("scene_main"))

    def test_publish_is_blocked_when_scene_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            pipeline = AssetPipeline(root=root)
            request = pipeline.create_job("level", "Regression", target_package="regression")
            pipeline.plan_spec(request["job_id"])
            graph_path = root / "graph.json"
            _write_json(graph_path, _environment_graph("regression"))
            pipeline.author_spec(request["job_id"], json_file=str(graph_path))
            pipeline.build(request["job_id"])
            staged_root = root / "user" / "asset_pipeline" / "jobs" / request["job_id"] / "staged_assets" / "Assets" / "levels" / "regression"
            (staged_root / "leveldata" / "heightmap.dat").write_bytes(b"\x00" * 4096)
            level_pak = staged_root / "level.pak"
            with zipfile.ZipFile(level_pak) as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
            entries["terrain/terrain.dat"] = b"\x00" * 4096
            with zipfile.ZipFile(level_pak, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in entries.items():
                    archive.writestr(name, data)
            validation = pipeline.validate(request["job_id"])
            self.assertEqual(validation["status"], "failed")
            with self.assertRaises(RuntimeError):
                pipeline.publish(request["job_id"])

    def test_mesh_import_job_still_stages_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_pipeline_root(root)
            source = root / "source"
            source.mkdir()
            obj = source / "crate.obj"
            mtl = source / "crate.mtl"
            texture = source / "crate_albedo.png"
            texture.write_bytes(b"fakepng")
            mtl.write_text("newmtl crate\nmap_Kd crate_albedo.png\n", encoding="utf-8")
            obj.write_text(
                "\n".join(
                    [
                        "mtllib crate.mtl",
                        "usemtl crate",
                        "v 0 0 0",
                        "v 1 0 0",
                        "v 0 1 0",
                        "vt 0 0",
                        "vt 1 0",
                        "vt 0 1",
                        "vn 0 0 1",
                        "f 1/1/1 2/2/1 3/3/1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            pipeline = AssetPipeline(root=root)
            result = pipeline.run("mesh_import", "Import crate", target_package="Objects/Imported/crate", source_inputs=[str(obj)], publish=True)
            self.assertEqual(result["validation_report"]["status"], "passed")
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate.obj").exists())
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate.mtl").exists())
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate_albedo.png").exists())

    def test_obj_character_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stage = root / "job"
            obj = root / "hero.obj"
            obj.write_text("v 0 0 0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "skeletal character imports require FBX or DAE"):
                convert_mesh_job(stage, input_path=obj, target="Objects/Characters/hero", kind="character_source")


if __name__ == "__main__":
    unittest.main()
