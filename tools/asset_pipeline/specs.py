from __future__ import annotations

import json
from pathlib import Path

from .catalogs import (
    build_asset_graph_stub,
    build_capability_catalog,
    load_character_template_catalog,
    load_level_template_catalog,
    load_material_template_catalog,
    load_procedural_mesh_catalog,
    load_texture_preset_catalog,
)
from .common import normalize_level_target_package, slugify


def build_prompt_pack(request: dict, project_root: Path) -> str:
    target_package = normalize_level_target_package(request.get("target_package")) or slugify(request["job_id"])
    capabilities = build_capability_catalog(project_root)
    node_types = capabilities["graph_contract"]["supported_node_types"]
    procedural_meshes = [item["name"] for item in capabilities["procedural_meshes"]]
    texture_modes = capabilities["texture_modes"]
    return "\n".join(
        [
            "# CRYENGINE Asset Bundle Authoring Pack",
            "",
            "Author a strict dependency graph. Python will compile the graph deterministically and will not infer missing assets from prose.",
            "",
            f"Asset kind: {request['asset_kind']}",
            f"User brief: {request['natural_language_prompt']}",
            f"Requested target package: {target_package}",
            f"Requested capabilities: {', '.join(request.get('requested_capabilities', [])) or 'none'}",
            "",
            "Top-level graph shape:",
            json.dumps(
                {
                    "asset_kind": request["asset_kind"],
                    "bundle_kind": "environment_package" if request["asset_kind"] == "level" else "character_package",
                    "bundle_slug": target_package,
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
                        }
                    ],
                },
                indent=2,
            ),
            "",
            "Required graph rules:",
            f"- Node types must be one of {node_types}.",
            f"- texture_source.mode must be one of {texture_modes}.",
            f"- mesh_procedural.archetype must be one of {procedural_meshes}.",
            "- Put all node dependencies in node.inputs.",
            "- scene_level root nodes must depend on terrain_archetype and object_placement_set nodes.",
            "- terrain_archetype nodes must declare non-empty paint_materials and non-empty paint_zones.",
            "- character_fp_package nodes must target the first-person runtime package contract used by Player.cpp.",
            "- Do not invent freeform vertex arrays or arbitrary binary formats.",
            "- If geometry cannot be represented procedurally, use mesh_import instead.",
            "- imagegen texture nodes may be requested, but the graph still needs a complete concrete texture node definition.",
        ]
    )


def build_template_catalog(root: Path) -> dict:
    return {
        "levels": load_level_template_catalog(root),
        "procedural_meshes": load_procedural_mesh_catalog(root),
        "materials": load_material_template_catalog(root),
        "characters": load_character_template_catalog(root),
        "textures": load_texture_preset_catalog(root),
    }


def build_authoring_artifacts(request: dict, project_root: Path) -> dict:
    return {
        "prompt_pack": build_prompt_pack(request, project_root),
        "capability_catalog": build_capability_catalog(project_root),
        "asset_graph_stub": build_asset_graph_stub(request, project_root),
        "template_catalog": build_template_catalog(project_root),
    }
