from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .common import relative_to_repo, resolve_cryengine_dir, write_json, write_text


SUPPORTED_EXTENSIONS = {".fbx", ".obj", ".dae", ".dxf", ".3ds", ".cgf"}
SKELETAL_EXTENSIONS = {".fbx", ".dae"}


def _parse_obj(path: Path) -> dict:
    vertices = 0
    normals = 0
    texcoords = 0
    faces = 0
    materials: set[str] = set()
    mtllibs: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("v "):
                vertices += 1
            elif line.startswith("vn "):
                normals += 1
            elif line.startswith("vt "):
                texcoords += 1
            elif line.startswith("f "):
                faces += 1
            elif line.startswith("usemtl "):
                materials.add(line.split(maxsplit=1)[1])
            elif line.startswith("mtllib "):
                mtllibs.append(line.split(maxsplit=1)[1])
    return {
        "vertices": vertices,
        "normals": normals,
        "texcoords": texcoords,
        "faces": faces,
        "materials": sorted(materials),
        "mtllibs": mtllibs,
    }


def _parse_mtl(path: Path) -> dict:
    textures: list[str] = []
    materials: set[str] = set()
    if not path.exists():
        return {"materials": [], "textures": []}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("newmtl "):
                materials.add(line.split(maxsplit=1)[1])
            elif line.startswith(("map_Kd ", "map_Ka ", "map_Bump ", "bump ", "norm ")):
                textures.append(line.split(maxsplit=1)[1].strip())
    return {"materials": sorted(materials), "textures": textures}


def _discover_compiler(cryengine_dir: Path | None) -> str | None:
    if cryengine_dir is None:
        return None
    candidates = [
        cryengine_dir / "Tools" / "rc" / "rc.exe",
        cryengine_dir / "Tools" / "rc" / "rc",
        cryengine_dir / "Bin64" / "rc" / "rc.exe",
        cryengine_dir / "bin" / "win_x64" / "rc" / "rc.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            if candidate.suffix.lower() == ".exe":
                return f"wine {candidate}"
            return str(candidate)
    return None


def stage_mesh_asset(
    *,
    stage_root: Path,
    stage_assets_root: Path,
    input_path: Path,
    target: str,
    kind: str,
    repo_root: Path | None = None,
) -> dict:
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported mesh input: {input_path.suffix}")
    if kind == "character_source" and input_path.suffix.lower() not in SKELETAL_EXTENSIONS:
        raise ValueError("OBJ can be staged as static geometry only; skeletal character imports require FBX or DAE.")

    source_root = stage_root / "source_mesh"
    source_root.mkdir(parents=True, exist_ok=True)
    copied_input = source_root / input_path.name
    shutil.copy2(input_path, copied_input)

    inspection = {"input": input_path.as_posix(), "format": input_path.suffix.lower()}
    sidecars: list[str] = []
    if input_path.suffix.lower() == ".obj":
        obj_stats = _parse_obj(input_path)
        inspection["obj_stats"] = obj_stats
        for mtllib in obj_stats["mtllibs"]:
            source_mtl = (input_path.parent / mtllib).resolve()
            if source_mtl.exists():
                shutil.copy2(source_mtl, source_root / source_mtl.name)
                sidecars.append(source_mtl.name)
                mtl_stats = _parse_mtl(source_mtl)
                inspection.setdefault("mtl_stats", {})[source_mtl.name] = mtl_stats
                for texture in mtl_stats["textures"]:
                    texture_path = (source_mtl.parent / texture).resolve()
                    if texture_path.exists() and texture_path.is_file():
                        shutil.copy2(texture_path, source_root / texture_path.name)
                        sidecars.append(texture_path.name)

    staged_target = stage_assets_root / "Assets" / target
    staged_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(copied_input, staged_target.with_suffix(input_path.suffix))
    for sidecar_name in sidecars:
        shutil.copy2(source_root / sidecar_name, staged_target.parent / sidecar_name)
    return {
        "inspection": inspection,
        "asset_path": f"{target}{input_path.suffix}",
        "source_file": copied_input.name,
        "sidecar_files": sorted(set(sidecars)),
        "preferred_output": f"{target}.cgf",
        "kind": kind,
    }


def convert_mesh_job(
    stage_root: Path,
    input_path: Path,
    target: str,
    kind: str,
    cryengine_dir_arg: str | None = None,
    repo_root: Path | None = None,
) -> dict:
    staged = stage_mesh_asset(
        stage_root=stage_root,
        stage_assets_root=stage_root / "staged_assets",
        input_path=input_path,
        target=target,
        kind=kind,
        repo_root=repo_root,
    )
    import_recipe = {
        "target": target,
        "kind": kind,
        "input_file": staged["source_file"],
        "sidecar_files": staged["sidecar_files"],
        "preferred_output": staged["preferred_output"],
        "notes": [
            "CRYENGINE importer expects the compiled mesh beside the source asset.",
            "FBX is preferred for skeletal assets; OBJ is limited to static geometry.",
        ],
    }
    compiler = _discover_compiler(resolve_cryengine_dir(cryengine_dir_arg))
    if compiler:
        import_recipe["compiler_command"] = f"{compiler} {copied_input}"
    else:
        import_recipe["compiler_command"] = None
        import_recipe["notes"].append("No CRYENGINE compiler was discovered from CRYENGINE_DIR; the job is staged and ready for compilation when the engine toolchain is available.")

    recipe_path = stage_root / "mesh_import_recipe.json"
    write_json(recipe_path, import_recipe)
    write_text(stage_root / "mesh_import_summary.md", json.dumps(import_recipe, indent=2) + "\n")

    return {
        "inspection": staged["inspection"],
        "import_recipe": import_recipe,
        "staged_asset": staged["asset_path"],
        "compiler_available": bool(compiler),
    }


def try_compile_mesh(stage_root: Path) -> dict:
    recipe_path = stage_root / "mesh_import_recipe.json"
    if not recipe_path.exists():
        raise FileNotFoundError(f"Missing recipe: {recipe_path}")
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    command = recipe.get("compiler_command")
    if not command:
        return {"status": "skipped", "reason": "compiler_unavailable"}
    result = subprocess.run(command, shell=True, cwd=stage_root, capture_output=True, text=True)
    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }
