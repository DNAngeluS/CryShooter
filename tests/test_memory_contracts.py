from __future__ import annotations

import json
import unittest
from pathlib import Path


class MemoryContractTests(unittest.TestCase):
    def test_asset_pipeline_interface_has_bundle_graph_verbs_and_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        interface = json.loads((root / "memory" / "asset_pipeline_interface.json").read_text(encoding="utf-8"))

        for verb in ("create", "plan_spec", "author_spec", "build", "edit", "validate", "publish", "run", "convert_mesh", "resume"):
            self.assertIn(verb, interface["verbs"])

        self.assertIn("create_level_package", interface["skills"])
        self.assertIn("create_environment_package", interface["skills"])
        self.assertIn("create_character_package", interface["skills"])
        self.assertIn("import_asset_bundle", interface["skills"])
        self.assertEqual(interface["entrypoints"]["pipeline_cli"], "python3 tools/cry_asset_pipeline.py")
        self.assertFalse(interface["dispatch_rules"]["defaults"]["publish_after_success"])
        self.assertIn("character_fp_package", interface["graph_contract"]["supported_node_types"])


if __name__ == "__main__":
    unittest.main()
