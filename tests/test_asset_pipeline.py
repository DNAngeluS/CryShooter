from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from asset_pipeline.mesh_converter import convert_mesh_job
from asset_pipeline.pipeline import AssetPipeline


class AssetPipelineTests(unittest.TestCase):
    def test_level_job_runs_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Assets").mkdir()
            pipeline = AssetPipeline(root=root)

            result = pipeline.run(
                "level",
                "small desert combat arena at noon",
                target_package="desert-arena",
                publish=True,
            )

            self.assertEqual(result["validation_report"]["status"], "passed")
            self.assertIsNotNone(result["publish_manifest"])
            published_level_root = root / "Assets" / "levels" / "desert-arena"
            self.assertTrue((published_level_root / "level.pak").exists())
            self.assertTrue((published_level_root / "terraintexture.pak").exists())
            self.assertTrue((root / "Assets" / "levels" / "desert-arena.level.cryasset").exists())

            tracker = json.loads((root / "memory" / "asset_pipeline_tracker.json").read_text(encoding="utf-8"))
            self.assertEqual(tracker["jobs"][0]["status"], "published")

    def test_mesh_import_copies_sidecars_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Assets").mkdir()
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

            result = pipeline.run(
                "mesh_import",
                "Import a static crate mesh",
                target_package="Objects/Imported/crate",
                source_inputs=[str(obj)],
                publish=True,
            )

            self.assertEqual(result["validation_report"]["status"], "passed")
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate.obj").exists())
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate.mtl").exists())
            self.assertTrue((root / "Assets" / "Objects" / "Imported" / "crate_albedo.png").exists())

    def test_edit_job_updates_level_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Assets").mkdir()
            pipeline = AssetPipeline(root=root)

            request = pipeline.create_job("level", "small forest arena at dawn", target_package="forest-arena")
            pipeline.plan_spec(request["job_id"])
            edited = pipeline.edit_job(
                request["job_id"],
                prompt="large desert arena at dusk",
                set_values=[("lighting.time_hour", "18"), ("terrain.biome", "\"desert\"")],
            )

            self.assertEqual(edited["spec"]["world"]["heightmap_size"], 2048)
            self.assertEqual(edited["spec"]["lighting"]["time_hour"], 18)
            self.assertEqual(edited["spec"]["terrain"]["biome"], "desert")

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
