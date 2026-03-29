#!/usr/bin/env python3
"""
Tracker CLI for the CRYENGINE asset pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from asset_pipeline.tracker_store import TrackerStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Asset pipeline tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Print the full tracker state")
    sub.add_parser("snapshot", help="Alias for status")
    sub.add_parser("next", help="Show next roadmap actions and non-published jobs")
    resume = sub.add_parser("resume", help="Summarize active jobs for a future conversation")
    resume.add_argument("--job")
    return parser


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, sort_keys=False))


def main() -> int:
    args = build_parser().parse_args()
    store = TrackerStore()
    tracker = store.snapshot()

    if args.command in {"status", "snapshot"}:
        _print(tracker)
        return 0

    if args.command == "next":
        pending_jobs = [job for job in tracker["jobs"] if job["status"] != "published"]
        _print(
            {
                "active_milestone": tracker["roadmap"]["active_milestone"],
                "next_actions": tracker["roadmap"]["next_actions"],
                "pending_jobs": pending_jobs,
            }
        )
        return 0

    if args.command == "resume":
        jobs = tracker["jobs"]
        if args.job:
            jobs = [job for job in jobs if job["job_id"] == args.job]
        _print(
            {
                "resume_summary": [
                    {
                        "job_id": job["job_id"],
                        "asset_kind": job["asset_kind"],
                        "status": job["status"],
                        "stage_dir": job["stage_dir"],
                        "published_paths": job.get("published_paths", []),
                    }
                    for job in jobs
                ],
                "next_actions": tracker["roadmap"]["next_actions"],
            }
        )
        return 0

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
