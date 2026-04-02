from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import normalize_level_target_package, project_root, read_json, slugify


TEMPLATES_ROOT = project_root() / "tools" / "asset_pipeline" / "templates"


def _load_catalog(root: Path, *parts: str) -> dict[str, Any]:
    catalog = read_json(root.joinpath("tools", "asset_pipeline", "templates", *parts))
    if not catalog:
        raise FileNotFoundError(f"Missing catalog: {'/'.join(parts)}")
    return catalog


def load_level_template_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    return _load_catalog(repo_root, "levels", "catalog.json")


def load_procedural_mesh_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    return _load_catalog(repo_root, "meshes", "procedural_meshes.json")


def load_material_template_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    return _load_catalog(repo_root, "materials", "catalog.json")


def load_character_template_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    return _load_catalog(repo_root, "characters", "first_person_templates.json")


def load_texture_preset_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    return _load_catalog(repo_root, "textures", "catalog.json")


def build_capability_catalog(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    template_catalog = load_level_template_catalog(repo_root)
    mesh_catalog = load_procedural_mesh_catalog(repo_root)
    material_catalog = load_material_template_catalog(repo_root)
    character_catalog = load_character_template_catalog(repo_root)
    texture_catalog = load_texture_preset_catalog(repo_root)
    return {
        "graph_contract": {
            "top_level_fields": ["asset_kind", "bundle_kind", "bundle_slug", "summary", "root_scene", "nodes"],
            "node_fields": ["id", "type", "inputs", "outputs", "spec"],
            "supported_node_types": [
                "scene_level",
                "terrain_archetype",
                "texture_source",
                "material_surface",
                "mesh_procedural",
                "mesh_import",
                "object_placement_set",
                "character_fp_package",
            ],
        },
        "asset_kinds": {
            "level": {
                "authoring_mode": "bundle_graph",
                "bundle_kind": "environment_package",
                "root_node_type": "scene_level",
                "supported_heightmap_sizes": [512, 1024, 2048],
                "supported_template_profiles": ["flat_arena", "basin", "ridge_ring", "valley"],
            },
            "character_package": {
                "authoring_mode": "bundle_graph",
                "bundle_kind": "character_package",
                "root_node_type": "character_fp_package",
                "supported_runtime_target": "first_person_only",
            },
            "mesh_import": {
                "authoring_mode": "deterministic_import_recipe",
                "supported_inputs": [".fbx", ".obj", ".dae", ".dxf", ".3ds", ".cgf"],
            },
        },
        "level_templates": template_catalog["templates"],
        "procedural_meshes": mesh_catalog["archetypes"],
        "material_templates": material_catalog["templates"],
        "character_templates": character_catalog["templates"],
        "texture_presets": texture_catalog["presets"],
        "texture_modes": texture_catalog["modes"],
    }


def build_asset_graph_stub(request: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    template_catalog = load_level_template_catalog(repo_root)
    default_template = next(template for template in template_catalog["templates"] if template.get("default_for_authoring"))
    slug = normalize_level_target_package(request.get("target_package")) or slugify(request["job_id"])
    if request["asset_kind"] == "level":
        size = default_template["heightmap_size"]
        center = size // 2
        return {
            "asset_kind": "level",
            "bundle_kind": "environment_package",
            "bundle_slug": slug,
            "summary": request["natural_language_prompt"].strip(),
            "root_scene": "scene_main",
            "nodes": [
                {
                    "id": "texture_ground",
                    "type": "texture_source",
                    "inputs": {},
                    "outputs": {},
                    "spec": {
                        "name": "forest_ground_albedo",
                        "mode": "procedural_pattern",
                        "width": 256,
                        "height": 256,
                        "pattern": "checker",
                        "palette": [[88, 110, 58, 255], [116, 96, 62, 255], [132, 126, 84, 255]],
                    },
                },
                {
                    "id": "material_ground",
                    "type": "material_surface",
                    "inputs": {"diffuse_texture": "texture_ground"},
                    "outputs": {},
                    "spec": {
                        "name": "forest_ground",
                        "template": "default_illum",
                        "surface_type": "mat_default",
                    },
                },
                {
                    "id": "terrain_main",
                    "type": "terrain_archetype",
                    "inputs": {"paint_materials": ["material_ground"], "foliage_meshes": []},
                    "outputs": {},
                    "spec": {
                        "template_profile": default_template["profile"],
                        "heightmap_size": size,
                        "paint_zones": [{"material_node": "material_ground", "zone": "base", "coverage": 1.0}],
                        "foliage_zones": [],
                    },
                },
                {
                    "id": "mesh_cover_box",
                    "type": "mesh_procedural",
                    "inputs": {"material": "material_ground"},
                    "outputs": {},
                    "spec": {
                        "name": "cover_box",
                        "archetype": "box",
                        "dimensions": [2.0, 1.0, 1.0],
                    },
                },
                {
                    "id": "placements_main",
                    "type": "object_placement_set",
                    "inputs": {"mesh_nodes": ["mesh_cover_box"]},
                    "outputs": {},
                    "spec": {
                        "placements": [
                            {
                                "name": "cover-box-01",
                                "target_node": "mesh_cover_box",
                                "layer": "Main",
                                "transform": {
                                    "position": [center - 32, center, 32],
                                    "rotation": [1, 0, 0, 0],
                                    "scale": [1, 1, 1],
                                },
                            }
                        ]
                    },
                },
                {
                    "id": "scene_main",
                    "type": "scene_level",
                    "inputs": {"terrain": "terrain_main", "placement_sets": ["placements_main"]},
                    "outputs": {},
                    "spec": {
                        "level_slug": slug,
                        "display_name": slug.replace("-", " ").replace("_", " ").title(),
                        "lighting": {
                            "preset": "%ENGINE%/EngineAssets/Shading/default.env",
                            "time_of_day": "afternoon",
                            "time_hour": 15,
                            "sun_rotation": 240,
                            "sun_height": 55,
                            "sun_vector": "-0.51961529,-0.29999986,-0.79999995",
                        },
                        "spawn": {
                            "layer": "Main",
                            "transform": {
                                "position": [center, center, 42],
                                "rotation": [1, 0, 0, 0],
                                "scale": [1, 1, 1],
                            },
                        },
                    },
                },
            ],
        }
    if request["asset_kind"] == "character_package":
        source_inputs = request.get("source_inputs") or ["character.fbx"]
        return {
            "asset_kind": "character_package",
            "bundle_kind": "character_package",
            "bundle_slug": slug,
            "summary": request["natural_language_prompt"].strip(),
            "root_scene": "character_main",
            "nodes": [
                {
                    "id": "character_source",
                    "type": "mesh_import",
                    "inputs": {},
                    "outputs": {},
                    "spec": {
                        "name": slug,
                        "mesh_kind": "character_source",
                        "source_file": source_inputs[0],
                        "target_path": f"Objects/Characters/{slug}/{slug}",
                    },
                },
                {
                    "id": "character_main",
                    "type": "character_fp_package",
                    "inputs": {"source_mesh": "character_source"},
                    "outputs": {},
                    "spec": {
                        "character_name": slug.replace("-", "_"),
                        "controller_scope": "FirstPersonCharacter",
                        "default_fragment": "Idle",
                        "skeleton_file": f"Objects/Characters/{slug}/{slug}.chr",
                        "skin_file": f"Objects/Characters/{slug}/{slug}.skin",
                        "attachment_bone": "R_hand",
                    },
                },
            ],
        }
    return {
        "asset_kind": "mesh_import",
        "bundle_kind": "import_asset_bundle",
        "bundle_slug": request.get("target_package") or slugify(request["job_id"]),
        "summary": request["natural_language_prompt"].strip(),
        "root_scene": "mesh_import_root",
        "nodes": [],
    }
