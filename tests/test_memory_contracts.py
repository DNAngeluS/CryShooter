from __future__ import annotations

import json
import unittest
from pathlib import Path


class MemoryContractTests(unittest.TestCase):
    def test_asset_pipeline_interface_has_core_verbs_and_skills(self) -> None:
        root = Path(__file__).resolve().parents[1]
        interface = json.loads((root / "memory" / "asset_pipeline_interface.json").read_text(encoding="utf-8"))

        for verb in ("create", "build", "edit", "validate", "publish", "convert_mesh", "resume"):
            self.assertIn(verb, interface["verbs"])

        self.assertIn("crate", interface["verbs"]["create"]["aliases"])
        self.assertIn("create_level_package", interface["skills"])
        self.assertEqual(interface["entrypoints"]["pipeline_cli"], "python3 tools/cry_asset_pipeline.py")


if __name__ == "__main__":
    unittest.main()
