from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from asset_pipeline.tracker_store import TrackerStore


class TrackerStoreTests(unittest.TestCase):
    def test_default_tracker_and_job_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tracker.json"
            store = TrackerStore(path)

            tracker = store.load()
            self.assertEqual(tracker["roadmap"]["active_milestone"], "M1-level-generation")
            self.assertEqual(tracker["jobs"], [])

            store.add_job(
                {
                    "job_id": "level-test",
                    "asset_kind": "level",
                    "prompt": "test prompt",
                    "status": "created",
                    "created_at": "2026-03-29T00:00:00+00:00",
                    "updated_at": "2026-03-29T00:00:00+00:00",
                    "stage_dir": "user/asset_pipeline/jobs/level-test",
                    "target_package": "level-test",
                    "published_paths": [],
                }
            )
            updated = store.update_job("level-test", status="published", published_paths=["Assets/levels/level-test/level.pak"])

            self.assertEqual(updated["status"], "published")
            snapshot = store.snapshot()
            self.assertEqual(snapshot["jobs"][0]["published_paths"], ["Assets/levels/level-test/level.pak"])


if __name__ == "__main__":
    unittest.main()
