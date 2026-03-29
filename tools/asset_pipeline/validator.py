from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .common import md5_file


def validate_level_job(stage_root: Path, spec: dict) -> dict:
    slug = spec["slug"]
    assets_root = stage_root / "staged_assets" / "Assets" / "levels" / slug
    errors: list[str] = []
    warnings: list[str] = []

    required_paths = [
        assets_root / f"{slug}.level",
        assets_root / "filelist.xml",
        assets_root / "level.pak",
        assets_root / "terraintexture.pak",
        assets_root / "leveldata" / "environment.xml",
        assets_root / "leveldata" / "timeofday.xml",
        assets_root / "leveldata" / "terraintexture.xml",
        assets_root.parent / f"{slug}.level.cryasset",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required output: {path}")

    level_pak = assets_root / "level.pak"
    if level_pak.exists():
        with zipfile.ZipFile(level_pak) as archive:
            names = set(archive.namelist())
            for required in ["levelinfo.xml", "leveldata.xml", "mission_mission0.xml", "terrain/terrain.dat", "terrain/cover.ctc"]:
                if required not in names:
                    errors.append(f"level.pak missing {required}")
            if "mission_mission0.xml" in names:
                mission = archive.read("mission_mission0.xml").decode("utf-8", "replace")
                if "%ENGINE%/EngineAssets/Shading/default.env" not in mission:
                    errors.append("mission_mission0.xml does not reference the default engine env preset")
            if "levelinfo.xml" in names:
                levelinfo = archive.read("levelinfo.xml").decode("utf-8", "replace")
                if 'OceanWaterLevel="-100"' not in levelinfo:
                    warnings.append("OceanWaterLevel is not pinned to -100")

    terraintexture_pak = assets_root / "terraintexture.pak"
    if terraintexture_pak.exists():
        with zipfile.ZipFile(terraintexture_pak) as archive:
            if "terrain/cover.ctc" not in archive.namelist():
                errors.append("terraintexture.pak missing terrain/cover.ctc")

    filelist_path = assets_root / "filelist.xml"
    if filelist_path.exists() and level_pak.exists():
        filelist_text = filelist_path.read_text(encoding="utf-8")
        expected_md5 = md5_file(level_pak)
        expected_size = str(level_pak.stat().st_size)
        if expected_md5 not in filelist_text:
            errors.append("filelist.xml md5 does not match level.pak")
        if f'size="{expected_size}"' not in filelist_text:
            errors.append("filelist.xml size does not match level.pak")

    return {
        "asset_kind": "level",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
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
