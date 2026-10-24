from __future__ import annotations

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from .asset_graph import bundle_slug, validate_asset_graph
from .common import md5_file, project_root, read_json, resolve_cryengine_dir
from .procgen.terrain_dat_parser import TerrainDatError, parse_terrain_dat


HEIGHTMAP_HEADER_RE = re.compile(r'<Heightmap[^>]*Width="(?P<width>\d+)"[^>]*Height="(?P<height>\d+)"')


def _is_zero_filled(data: bytes) -> bool:
    return bool(data) and not any(data)


def _parse_heightmap_header(path: Path) -> dict[str, int] | None:
    data = path.read_bytes()[:1024]
    if _is_zero_filled(data):
        return None
    decoded = data.decode("latin-1", errors="ignore")
    match = HEIGHTMAP_HEADER_RE.search(decoded)
    if not match:
        return None
    return {"width": int(match.group("width")), "height": int(match.group("height"))}


def _parse_xml(text: str, label: str, errors: list[str]) -> ET.Element | None:
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        errors.append(f"{label} is not valid XML: {exc}")
        return None


def _smoke_report(level_slug: str, root: Path) -> dict:
    cryengine_dir = resolve_cryengine_dir()
    if cryengine_dir is None:
        return {"status": "skipped", "reason": "cryengine_dir_unavailable"}
    launcher = cryengine_dir / "bin" / "linux_x64_gcc" / "GameLauncher"
    if not launcher.exists():
        return {"status": "skipped", "reason": "launcher_not_found", "launcher": launcher.as_posix()}
    if os.environ.get("CRY_ASSET_PIPELINE_ENABLE_SMOKE") != "1":
        return {
            "status": "skipped",
            "reason": "set_CRY_ASSET_PIPELINE_ENABLE_SMOKE=1_to_run_engine_smoke_test",
            "launcher": launcher.as_posix(),
        }
    command = [
        launcher.as_posix(),
        "-project",
        str((root / "Game.cryproject").resolve()),
        "+map",
        level_slug,
        "s",
        "+quit",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, cwd=root)
    except Exception as exc:  # pragma: no cover
        return {"status": "failed", "reason": str(exc), "command": command}
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "command": command,
    }


def _node_report_map(stage_root: Path) -> dict[str, dict]:
    manifest = read_json(stage_root / "node_build_reports.json", default={})
    reports = manifest.get("node_reports", [])
    return {report["node_id"]: report for report in reports}


def _validate_texture_node(report: dict, stage_root: Path, errors: list[str]) -> None:
    path = stage_root / "staged_assets" / "Assets" / report["asset_path"]
    if not path.exists():
        errors.append(f'texture node {report["node_id"]} output is missing: {path}')
    if path.suffix.lower() != ".png":
        errors.append(f'texture node {report["node_id"]} output must be a PNG')


def _validate_material_node(report: dict, stage_root: Path, errors: list[str]) -> None:
    path = stage_root / "staged_assets" / "Assets" / report["asset_path"]
    if not path.exists():
        errors.append(f'material node {report["node_id"]} output is missing: {path}')
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if report["diffuse_texture"] not in text:
        errors.append(f'material node {report["node_id"]} does not reference its diffuse texture')


def _validate_mesh_node(report: dict, stage_root: Path, errors: list[str]) -> None:
    path = stage_root / "staged_assets" / "Assets" / report["asset_path"]
    if not path.exists():
        errors.append(f'mesh node {report["node_id"]} output is missing: {path}')


def _validate_character_node(report: dict, stage_root: Path, errors: list[str]) -> None:
    for rel_path in [report["asset_path"], report["adb_path"], report["controller_path"]]:
        path = stage_root / "staged_assets" / "Assets" / rel_path
        if not path.exists():
            errors.append(f'character node {report["node_id"]} output is missing: {path}')
    cdf_path = stage_root / "staged_assets" / "Assets" / report["asset_path"]
    if cdf_path.exists():
        text = cdf_path.read_text(encoding="utf-8", errors="replace")
        if 'AName="barrel_out"' not in text:
            errors.append(f'character node {report["node_id"]} CDF is missing barrel_out attachment')


def _validate_scene_bundle(stage_root: Path, asset_graph: dict, node_reports: dict[str, dict], root: Path, errors: list[str], warnings: list[str]) -> dict:
    slug = bundle_slug(asset_graph)
    root_node = next(node for node in asset_graph["nodes"] if node["id"] == asset_graph["root_scene"])
    terrain_node_id = root_node["inputs"]["terrain"]
    terrain_report = node_reports[terrain_node_id]
    world = terrain_report["world"]
    assets_root = stage_root / "staged_assets" / "Assets" / "levels" / slug
    required_paths = [
        assets_root / f"{slug}.level",
        assets_root / "filelist.xml",
        assets_root / "level.pak",
        assets_root / "terraintexture.pak",
        assets_root / "layers" / "main.lyr",
        assets_root / "layers" / "terrain.lyr",
        assets_root / "leveldata" / "heightmap.dat",
        assets_root / "leveldata" / "terrain_manifest.json",
        assets_root.parent / f"{slug}.level.cryasset",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required scene output: {path}")

    heightmap_path = assets_root / "leveldata" / "heightmap.dat"
    if heightmap_path.exists():
        header = _parse_heightmap_header(heightmap_path)
        if not header:
            errors.append("leveldata/heightmap.dat is missing a valid CRYENGINE heightmap header or is zero-filled")
        elif header["width"] != world["heightmap_size"] or header["height"] != world["heightmap_size"]:
            errors.append("leveldata/heightmap.dat dimensions do not match terrain node world size")

    terrain_manifest: dict = {}
    terrain_manifest_path = assets_root / "leveldata" / "terrain_manifest.json"
    if terrain_manifest_path.exists():
        terrain_manifest = read_json(terrain_manifest_path)
        # Interior/structured procgen levels use paint_zone_hints instead of paint_zones;
        # skip the paint-layer checks for those template types.
        is_procgen_interior = str(terrain_manifest.get("template_id", "")).startswith("procgen:")
        if not is_procgen_interior:
            if not terrain_manifest.get("paint_zones"):
                errors.append("terrain_manifest.json is missing paint_zones")
            if not terrain_manifest.get("paint_material_assets"):
                errors.append("terrain_manifest.json is missing paint material assets")

    level_pak = assets_root / "level.pak"
    if level_pak.exists():
        with zipfile.ZipFile(level_pak) as archive:
            names = set(archive.namelist())
            for required in ["levelinfo.xml", "leveldata.xml", "mission_mission0.xml", "terrain/terrain.dat", "terrain/cover.ctc"]:
                if required not in names:
                    errors.append(f"level.pak missing {required}")
            terrain_data = archive.read("terrain/terrain.dat") if "terrain/terrain.dat" in names else b""
            if not terrain_data or _is_zero_filled(terrain_data[:4096]):
                errors.append("terrain/terrain.dat is empty or zero-filled")
            elif terrain_data:
                # Walk the file like CTerrain::Load_T does; a pipeline-written file must also end in the empty object-tree chunk
                # (OF-09: without it the engine rejects levels under 4 MiB).
                try:
                    parse_terrain_dat(terrain_data, strict=terrain_manifest.get("terrain_dat_source") == "pipeline-writer")
                except TerrainDatError as exc:
                    errors.append(str(exc))

            levelinfo_text = archive.read("levelinfo.xml").decode("utf-8", "replace") if "levelinfo.xml" in names else ""
            levelinfo_root = _parse_xml(levelinfo_text, "levelinfo.xml", errors) if levelinfo_text else None
            if levelinfo_root is not None:
                terrain_info = levelinfo_root.find("TerrainInfo")
                if terrain_info is None:
                    errors.append("levelinfo.xml is missing TerrainInfo")
                elif terrain_info.attrib.get("HeightmapSize") != str(world["heightmap_size"]):
                    errors.append("levelinfo.xml heightmap size does not match terrain node")

    terraintexture_pak = assets_root / "terraintexture.pak"
    if terraintexture_pak.exists():
        with zipfile.ZipFile(terraintexture_pak) as archive:
            if "terrain/cover.ctc" not in archive.namelist():
                errors.append("terraintexture.pak missing terrain/cover.ctc")

    main_layer = assets_root / "layers" / "main.lyr"
    if main_layer.exists():
        main_text = main_layer.read_text(encoding="utf-8", errors="replace")
        for node_id, report in node_reports.items():
            if report["type"] == "object_placement_set":
                for placement in report["placements"]:
                    if placement["name"] not in main_text:
                        errors.append(f'layers/main.lyr is missing placement "{placement["name"]}"')
                    if placement["asset_path"] not in main_text:
                        errors.append(f'layers/main.lyr is missing asset reference "{placement["asset_path"]}"')

    filelist_path = assets_root / "filelist.xml"
    if filelist_path.exists() and level_pak.exists():
        filelist_text = filelist_path.read_text(encoding="utf-8")
        expected_md5 = md5_file(level_pak)
        expected_size = str(level_pak.stat().st_size)
        if expected_md5 not in filelist_text:
            errors.append("filelist.xml md5 does not match level.pak")
        if f'size="{expected_size}"' not in filelist_text:
            errors.append("filelist.xml size does not match level.pak")

    smoke_report = _smoke_report(slug, root)
    if smoke_report["status"] == "failed":
        warnings.append("Engine smoke test failed; inspect smoke_report.json for details")
    return smoke_report


def validate_bundle_job(stage_root: Path, asset_graph: dict, root: Path | None = None) -> dict:
    repo_root = root or project_root()
    asset_graph = validate_asset_graph(asset_graph, repo_root)
    errors: list[str] = []
    warnings: list[str] = []
    node_reports = _node_report_map(stage_root)
    if not node_reports:
        errors.append("Missing node_build_reports.json")
    for node in asset_graph["dependency_order"]:
        report = node_reports.get(node["id"])
        if not report:
            errors.append(f"Missing build report for node {node['id']}")
            continue
        if node["type"] == "texture_source":
            _validate_texture_node(report, stage_root, errors)
        elif node["type"] == "material_surface":
            _validate_material_node(report, stage_root, errors)
        elif node["type"] in {"mesh_procedural", "mesh_import"}:
            _validate_mesh_node(report, stage_root, errors)
        elif node["type"] == "character_fp_package":
            _validate_character_node(report, stage_root, errors)

    smoke_report = {"status": "skipped", "reason": "not_applicable"}
    if asset_graph["asset_kind"] == "level":
        smoke_report = _validate_scene_bundle(stage_root, asset_graph, node_reports, repo_root, errors, warnings)

    return {
        "asset_kind": asset_graph["asset_kind"],
        "bundle_kind": asset_graph["bundle_kind"],
        "bundle_slug": asset_graph["bundle_slug"],
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "node_reports": list(node_reports.values()),
        "smoke_report": smoke_report,
    }


def validate_mesh_job(stage_root: Path, job: dict) -> dict:
    recipe_path = stage_root / "mesh_import_recipe.json"
    errors: list[str] = []
    warnings: list[str] = []
    if not recipe_path.exists():
        errors.append("Missing mesh_import_recipe.json")
    else:
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        if recipe.get("compiler_command") is None:
            warnings.append("No compiler command resolved from CRYENGINE_DIR; staged package is ready but not compiled.")
    return {
        "asset_kind": "mesh_import",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
    }
