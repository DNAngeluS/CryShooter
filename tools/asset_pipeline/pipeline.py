from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .common import copy_tree, ensure_removed, project_root, read_json, relative_to_repo, slugify, utc_now, write_json, write_text
from .level_builder import build_level_job
from .mesh_converter import convert_mesh_job, try_compile_mesh
from .specs import build_prompt_pack, synthesize_spec
from .tracker_store import TrackerStore
from .validator import validate_level_job, validate_mesh_job


class AssetPipeline:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_root()
        self.jobs_root = self.root / "user" / "asset_pipeline" / "jobs"
        self.tracker = TrackerStore(self.root / "memory" / "asset_pipeline_tracker.json")

    def _job_root(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def create_job(self, asset_kind: str, prompt: str, target_package: str | None = None, source_inputs: list[str] | None = None) -> dict[str, Any]:
        if asset_kind not in {"level", "mesh_import"}:
            raise ValueError(f"Unsupported asset_kind: {asset_kind}")
        base = target_package or prompt[:48]
        job_id = f"{asset_kind}-{slugify(base)}"
        stage_root = self._job_root(job_id)
        stage_root.mkdir(parents=True, exist_ok=True)
        request = {
            "job_id": job_id,
            "asset_kind": asset_kind,
            "natural_language_prompt": prompt,
            "target_package": target_package,
            "source_inputs": source_inputs or [],
            "status": "created",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "stage_dir": relative_to_repo(stage_root, base=self.root),
        }
        write_json(stage_root / "request.json", request)
        tracker_job = {
            "job_id": job_id,
            "asset_kind": asset_kind,
            "prompt": prompt,
            "status": "created",
            "created_at": request["created_at"],
            "updated_at": request["updated_at"],
            "stage_dir": request["stage_dir"],
            "target_package": target_package,
            "published_paths": [],
        }
        self.tracker.add_job(tracker_job)
        return request

    def _set_dotted_value(self, payload: dict[str, Any], dotted_key: str, raw_value: str) -> None:
        cursor: dict[str, Any] = payload
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                raise ValueError(f"Cannot set nested value below non-object path: {dotted_key}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        cursor[parts[-1]] = value

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def plan_spec(self, job_id: str, llm_mode: str = "auto") -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        request = read_json(stage_root / "request.json")
        if not request:
            raise FileNotFoundError(f"Missing request.json for job {job_id}")
        prompt_pack = build_prompt_pack(request)
        write_text(stage_root / "prompt_pack.md", prompt_pack)
        if request["asset_kind"] == "level":
            spec = synthesize_spec(request, self.root)
        else:
            spec = {
                "asset_kind": "mesh_import",
                "slug": request["target_package"] or slugify(Path(request["source_inputs"][0]).stem),
                "summary": request["natural_language_prompt"],
                "llm_mode": llm_mode,
            }
        spec["llm_mode"] = llm_mode
        write_json(stage_root / "asset_spec.json", spec)
        self.tracker.update_job(job_id, status="spec_ready")
        return spec

    def edit_job(
        self,
        job_id: str,
        *,
        prompt: str | None = None,
        set_values: list[tuple[str, str]] | None = None,
        merge_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        request = read_json(stage_root / "request.json")
        spec = read_json(stage_root / "asset_spec.json")
        if not request:
            raise FileNotFoundError(f"Missing request.json for job {job_id}")

        if prompt:
            request["natural_language_prompt"] = prompt
            request["updated_at"] = utc_now()
            write_json(stage_root / "request.json", request)
            if request["asset_kind"] == "level":
                spec = synthesize_spec(request, self.root)
                spec["llm_mode"] = "auto"

        if not spec:
            raise FileNotFoundError(f"Missing asset_spec.json for job {job_id}")

        for key, value in set_values or []:
            self._set_dotted_value(spec, key, value)
        if merge_patch:
            spec = self._deep_merge(spec, merge_patch)

        write_json(stage_root / "asset_spec.json", spec)
        self.tracker.update_job(job_id, status="edited")
        return {"request": request, "spec": spec}

    def build(self, job_id: str, *, compile_mesh: bool = False, cryengine_dir: str | None = None) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        ensure_removed(stage_root / "staged_assets")
        spec = read_json(stage_root / "asset_spec.json")
        request = read_json(stage_root / "request.json")
        if not spec or not request:
            raise FileNotFoundError(f"Missing job inputs for {job_id}")
        build_manifest: dict[str, Any]
        if request["asset_kind"] == "level":
            build_manifest = build_level_job(stage_root / "staged_assets", spec)
        else:
            if not request["source_inputs"]:
                raise ValueError("Mesh import jobs require source_inputs")
            input_path = Path(request["source_inputs"][0])
            build_manifest = convert_mesh_job(
                stage_root,
                input_path=input_path,
                target=request["target_package"] or f"Objects/Imported/{input_path.stem}",
                kind="static_mesh",
                cryengine_dir_arg=cryengine_dir,
                repo_root=self.root,
            )
            if compile_mesh:
                build_manifest["compile_result"] = try_compile_mesh(stage_root)
        write_json(stage_root / "build_manifest.json", build_manifest)
        self.tracker.update_job(job_id, status="built")
        return build_manifest

    def validate(self, job_id: str) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        spec = read_json(stage_root / "asset_spec.json")
        request = read_json(stage_root / "request.json")
        if request["asset_kind"] == "level":
            report = validate_level_job(stage_root, spec)
        else:
            report = validate_mesh_job(stage_root, request)
        write_json(stage_root / "validation_report.json", report)
        status = "validated" if report["status"] == "passed" else "blocked"
        self.tracker.update_job(job_id, status=status)
        return report

    def publish(self, job_id: str) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        report = read_json(stage_root / "validation_report.json")
        if not report:
            raise FileNotFoundError(f"Missing validation_report.json for {job_id}")
        if report["status"] != "passed":
            raise RuntimeError(f"Cannot publish {job_id}: validation failed")

        publish_manifest: dict[str, Any] = {"job_id": job_id, "published_paths": []}
        stage_assets = stage_root / "staged_assets" / "Assets"
        if stage_assets.exists():
            publish_manifest["published_paths"] = copy_tree(stage_assets, self.root / "Assets")
        else:
            source_root = stage_root / "source_mesh"
            staged_assets = stage_root / "staged_assets" / "Assets"
            if source_root.exists() and staged_assets.exists():
                publish_manifest["published_paths"] = copy_tree(staged_assets, self.root / "Assets")
        write_json(stage_root / "publish_manifest.json", publish_manifest)
        self.tracker.update_job(job_id, status="published", published_paths=publish_manifest["published_paths"])
        return publish_manifest

    def run(
        self,
        asset_kind: str,
        prompt: str,
        *,
        target_package: str | None = None,
        source_inputs: list[str] | None = None,
        llm_mode: str = "auto",
        publish: bool = True,
        compile_mesh: bool = False,
        cryengine_dir: str | None = None,
    ) -> dict[str, Any]:
        request = self.create_job(asset_kind, prompt, target_package=target_package, source_inputs=source_inputs)
        spec = self.plan_spec(request["job_id"], llm_mode=llm_mode)
        build_manifest = self.build(request["job_id"], compile_mesh=compile_mesh, cryengine_dir=cryengine_dir)
        validation = self.validate(request["job_id"])
        publish_manifest = None
        if publish and validation["status"] == "passed":
            publish_manifest = self.publish(request["job_id"])
        return {
            "request": request,
            "spec": spec,
            "build_manifest": build_manifest,
            "validation_report": validation,
            "publish_manifest": publish_manifest,
        }
