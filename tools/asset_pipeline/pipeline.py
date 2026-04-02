from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .common import copy_tree, ensure_removed, normalize_level_target_package, project_root, read_json, relative_to_repo, slugify, utc_now, write_json, write_text
from .asset_graph import AssetGraphValidationError, bundle_slug, validate_asset_graph
from .bundle_builder import build_asset_bundle
from .mesh_converter import convert_mesh_job, try_compile_mesh
from .specs import build_authoring_artifacts
from .tracker_store import TrackerStore
from .validator import validate_bundle_job, validate_mesh_job


class AssetPipeline:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_root()
        self.jobs_root = self.root / "user" / "asset_pipeline" / "jobs"
        self.tracker = TrackerStore(self.root / "memory" / "asset_pipeline_tracker.json")

    def _job_root(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def create_job(
        self,
        asset_kind: str,
        prompt: str,
        target_package: str | None = None,
        source_inputs: list[str] | None = None,
        requested_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        if asset_kind not in {"level", "mesh_import", "character_package"}:
            raise ValueError(f"Unsupported asset_kind: {asset_kind}")
        normalized_target = normalize_level_target_package(target_package) if asset_kind == "level" else target_package
        base = normalized_target or prompt[:48]
        job_id = f"{asset_kind}-{slugify(base)}"
        stage_root = self._job_root(job_id)
        stage_root.mkdir(parents=True, exist_ok=True)
        request = {
            "job_id": job_id,
            "asset_kind": asset_kind,
            "natural_language_prompt": prompt,
            "target_package": normalized_target,
            "source_inputs": source_inputs or [],
            "requested_capabilities": requested_capabilities or [],
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
            "target_package": normalized_target,
            "requested_capabilities": request["requested_capabilities"],
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

    def plan_spec(self, job_id: str) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        request = read_json(stage_root / "request.json")
        if not request:
            raise FileNotFoundError(f"Missing request.json for job {job_id}")
        artifacts = build_authoring_artifacts(request, self.root)
        write_text(stage_root / "prompt_pack.md", artifacts["prompt_pack"])
        write_json(stage_root / "capability_catalog.json", artifacts["capability_catalog"])
        write_json(stage_root / "asset_graph.stub.json", artifacts["asset_graph_stub"])
        write_json(stage_root / "template_catalog.json", artifacts["template_catalog"])
        self.tracker.update_job(job_id, status="awaiting_author_spec")
        return {
            "job_id": job_id,
            "status": "awaiting_author_spec",
            "prompt_pack": relative_to_repo(stage_root / "prompt_pack.md", base=self.root),
            "capability_catalog": artifacts["capability_catalog"],
            "asset_graph_stub": artifacts["asset_graph_stub"],
            "template_catalog": artifacts["template_catalog"],
        }

    def author_spec(self, job_id: str, *, json_file: str | None = None, asset_graph: dict[str, Any] | None = None) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        request = read_json(stage_root / "request.json")
        if not request:
            raise FileNotFoundError(f"Missing request.json for job {job_id}")
        authored_graph = asset_graph or json.loads(Path(json_file).read_text(encoding="utf-8"))
        if request["asset_kind"] in {"level", "character_package"}:
            authored_graph = validate_asset_graph(authored_graph, self.root)
            if request.get("target_package") and bundle_slug(authored_graph) != request["target_package"]:
                raise AssetGraphValidationError(
                    f"Authored bundle slug {bundle_slug(authored_graph)} does not match requested target_package {request['target_package']}"
                )
        write_json(stage_root / "asset_graph.json", authored_graph)
        self.tracker.update_job(job_id, status="author_spec_ready")
        return authored_graph

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
        graph_path = stage_root / "asset_graph.json"
        stub_path = stage_root / "asset_graph.stub.json"
        spec = read_json(graph_path) or read_json(stub_path)
        if not request:
            raise FileNotFoundError(f"Missing request.json for job {job_id}")

        if prompt:
            request["natural_language_prompt"] = prompt
            request["updated_at"] = utc_now()
            write_json(stage_root / "request.json", request)

        if not spec:
            raise FileNotFoundError(f"Missing authored asset graph or stub for job {job_id}")

        for key, value in set_values or []:
            self._set_dotted_value(spec, key, value)
        if merge_patch:
            spec = self._deep_merge(spec, merge_patch)

        if graph_path.exists():
            if request["asset_kind"] in {"level", "character_package"}:
                spec = validate_asset_graph(spec, self.root)
            write_json(graph_path, spec)
            self.tracker.update_job(job_id, status="author_spec_ready")
        else:
            write_json(stub_path, spec)
            self.tracker.update_job(job_id, status="awaiting_author_spec")
        return {"request": request, "spec": spec}

    def build(self, job_id: str, *, compile_mesh: bool = False, cryengine_dir: str | None = None) -> dict[str, Any]:
        stage_root = self._job_root(job_id)
        ensure_removed(stage_root / "staged_assets")
        request = read_json(stage_root / "request.json")
        if not request:
            raise FileNotFoundError(f"Missing job inputs for {job_id}")
        build_manifest: dict[str, Any]
        if request["asset_kind"] in {"level", "character_package"}:
            asset_graph = read_json(stage_root / "asset_graph.json")
            if not asset_graph:
                raise FileNotFoundError(f"Missing asset_graph.json for job {job_id}")
            asset_graph = validate_asset_graph(asset_graph, self.root)
            build_manifest = build_asset_bundle(stage_root, asset_graph, root=self.root)
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
        request = read_json(stage_root / "request.json")
        if request["asset_kind"] in {"level", "character_package"}:
            asset_graph = read_json(stage_root / "asset_graph.json")
            if not asset_graph:
                raise FileNotFoundError(f"Missing asset_graph.json for job {job_id}")
            report = validate_bundle_job(stage_root, asset_graph, root=self.root)
        else:
            report = validate_mesh_job(stage_root, request)
        write_json(stage_root / "validation_report.json", report)
        if "smoke_report" in report:
            write_json(stage_root / "smoke_report.json", report["smoke_report"])
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
        requested_capabilities: list[str] | None = None,
        asset_graph_file: str | None = None,
        publish: bool = False,
        compile_mesh: bool = False,
        cryengine_dir: str | None = None,
    ) -> dict[str, Any]:
        request = self.create_job(
            asset_kind,
            prompt,
            target_package=target_package,
            source_inputs=source_inputs,
            requested_capabilities=requested_capabilities,
        )
        plan = self.plan_spec(request["job_id"])
        authored = None
        if asset_kind in {"level", "character_package"}:
            if not asset_graph_file:
                raise ValueError(f"{asset_kind} runs require --asset-graph with a validated authored asset_graph.json")
            authored = self.author_spec(request["job_id"], json_file=asset_graph_file)
        build_manifest = self.build(request["job_id"], compile_mesh=compile_mesh, cryengine_dir=cryengine_dir)
        validation = self.validate(request["job_id"])
        publish_manifest = None
        if publish and validation["status"] == "passed":
            publish_manifest = self.publish(request["job_id"])
        return {
            "request": request,
            "authoring_plan": plan,
            "asset_graph": authored,
            "build_manifest": build_manifest,
            "validation_report": validation,
            "publish_manifest": publish_manifest,
        }
