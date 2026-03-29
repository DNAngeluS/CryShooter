from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import project_root, read_json, utc_now, write_json


TRACKER_PATH = project_root() / "memory" / "asset_pipeline_tracker.json"


def default_tracker() -> dict[str, Any]:
    return {
        "_meta": {
            "engine": "CRYENGINE 5.6",
            "topic": "asset_pipeline_tracker",
            "version": 1,
            "updated_at": utc_now(),
        },
        "roadmap": {
            "active_milestone": "M1-level-generation",
            "next_actions": [
                "Use cry_asset_pipeline.py run --kind level --prompt 'small desert combat arena at noon' to create the first generated level package.",
                "Use cry_asset_pipeline.py convert-mesh --input path/to/model.obj --target Objects/Imported/model to stage a mesh import job.",
            ],
        },
        "jobs": [],
    }


class TrackerStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or TRACKER_PATH

    def load(self) -> dict[str, Any]:
        data = read_json(self.path)
        if not data:
            data = default_tracker()
            write_json(self.path, data)
        return data

    def save(self, data: dict[str, Any]) -> None:
        data["_meta"]["updated_at"] = utc_now()
        write_json(self.path, data)

    def add_job(self, job: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        jobs = [existing for existing in data["jobs"] if existing["job_id"] != job["job_id"]]
        jobs.append(job)
        data["jobs"] = sorted(jobs, key=lambda item: item["created_at"])
        self.save(data)
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        data = self.load()
        for job in data["jobs"]:
            if job["job_id"] == job_id:
                return job
        raise KeyError(f"Unknown job_id: {job_id}")

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        data = self.load()
        updated = None
        for job in data["jobs"]:
            if job["job_id"] == job_id:
                job.update(changes)
                job["updated_at"] = utc_now()
                updated = job
                break
        if updated is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        self.save(data)
        return updated

    def snapshot(self) -> dict[str, Any]:
        return self.load()

