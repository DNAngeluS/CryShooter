from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalogs import (
    build_capability_catalog,
    load_character_template_catalog,
    load_level_template_catalog,
    load_material_template_catalog,
    load_procedural_mesh_catalog,
    load_texture_preset_catalog,
)
from .common import normalize_level_target_package, project_root, slugify


SUPPORTED_NODE_TYPES = {
    "scene_level",
    "terrain_archetype",
    "texture_source",
    "material_surface",
    "mesh_procedural",
    "mesh_import",
    "object_placement_set",
    "character_fp_package",
}
ALLOWED_GRAPH_TOP_LEVEL_KEYS = {"asset_kind", "bundle_kind", "bundle_slug", "summary", "root_scene", "nodes"}
ALLOWED_NODE_KEYS = {"id", "type", "inputs", "outputs", "spec"}
ALLOWED_TRANSFORM_KEYS = {"position", "rotation", "scale"}
TEXTURE_SPEC_KEYS = {"name", "mode", "source_file", "width", "height", "rgba", "pattern", "palette", "prompt", "fallback_rgba", "average_rgba"}
MATERIAL_SPEC_KEYS = {"name", "template", "surface_type"}
MESH_PROCEDURAL_SPEC_KEYS = {"name", "archetype", "dimensions"}
MESH_IMPORT_SPEC_KEYS = {"name", "mesh_kind", "source_file", "target_path"}
TERRAIN_SPEC_KEYS = {"template_profile", "heightmap_size", "paint_zones", "foliage_zones"}
PLACEMENT_SET_SPEC_KEYS = {"placements"}
SCENE_LEVEL_SPEC_KEYS = {"level_slug", "display_name", "lighting", "spawn"}
CHARACTER_SPEC_KEYS = {"character_name", "controller_scope", "default_fragment", "skeleton_file", "skin_file", "attachment_bone"}


class AssetGraphValidationError(ValueError):
    pass


def _assert_exact_keys(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    extra = sorted(set(payload.keys()) - allowed)
    if extra:
        raise AssetGraphValidationError(f"{label} contains unsupported keys: {', '.join(extra)}")


def _require_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AssetGraphValidationError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _require_int(payload: dict[str, Any], key: str, label: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise AssetGraphValidationError(f"{label}.{key} must be an integer")
    return value


def _require_number_list(payload: dict[str, Any], key: str, length: int, label: str) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) != length or not all(isinstance(item, (int, float)) for item in value):
        raise AssetGraphValidationError(f"{label}.{key} must be a {length}-element numeric array")
    return [float(item) for item in value]


def _validate_transform(payload: dict[str, Any], label: str) -> None:
    _assert_exact_keys(payload, ALLOWED_TRANSFORM_KEYS, label)
    _require_number_list(payload, "position", 3, label)
    _require_number_list(payload, "rotation", 4, label)
    _require_number_list(payload, "scale", 3, label)


def bundle_slug(asset_graph: dict[str, Any]) -> str:
    if "bundle_slug" in asset_graph:
        if asset_graph["asset_kind"] == "level":
            normalized = normalize_level_target_package(asset_graph["bundle_slug"])
            if not normalized:
                raise AssetGraphValidationError("bundle_slug could not be normalized into a valid level package")
            return normalized
        return slugify(str(asset_graph["bundle_slug"]))
    if "slug" in asset_graph:
        normalized = normalize_level_target_package(asset_graph["slug"])
        if normalized:
            return normalized
    raise AssetGraphValidationError("asset graph is missing bundle_slug/slug")


def _resolve_level_template(profile: str, heightmap_size: int, root: Path) -> dict[str, Any]:
    catalog = load_level_template_catalog(root)
    for template in catalog["templates"]:
        if template["profile"] == profile and template["heightmap_size"] == heightmap_size:
            if not template.get("available"):
                raise AssetGraphValidationError(
                    f"No checked-in golden template is available for profile={profile} heightmap_size={heightmap_size}"
                )
            return template
    raise AssetGraphValidationError(f"No checked-in level template matches profile={profile} heightmap_size={heightmap_size}")


def _legacy_level_to_bundle_graph(asset_graph: dict[str, Any]) -> dict[str, Any]:
    slug = normalize_level_target_package(asset_graph["slug"]) or slugify(asset_graph["slug"])
    terrain_texture_name = asset_graph["terrain"]["texture_profile"]
    nodes: list[dict[str, Any]] = [
        {
            "id": "texture_ground",
            "type": "texture_source",
            "inputs": {},
            "outputs": {},
            "spec": {
                "name": terrain_texture_name,
                "mode": "solid_color",
                "width": 128,
                "height": 128,
                "rgba": [96, 112, 64, 255],
            },
        },
        {
            "id": "material_ground",
            "type": "material_surface",
            "inputs": {"diffuse_texture": "texture_ground"},
            "outputs": {},
            "spec": {
                "name": terrain_texture_name,
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
                "template_profile": asset_graph["terrain"]["template_profile"],
                "heightmap_size": asset_graph["world"]["heightmap_size"],
                "paint_zones": [{"material_node": "material_ground", "zone": "base", "coverage": 1.0}],
                "foliage_zones": [],
            },
        },
    ]
    mesh_nodes: list[str] = []
    placements = []
    for index, placement in enumerate(asset_graph.get("placements", [])):
        mesh_node_id = f"legacy_mesh_{index}"
        if placement["kind"] == "primitive_prefab":
            archetype = placement["ref"]
            if archetype not in {"box", "wall", "ramp"}:
                raise AssetGraphValidationError(f"Legacy placement {placement['name']} references unsupported primitive archetype {archetype}")
            nodes.append(
                {
                    "id": mesh_node_id,
                    "type": "mesh_procedural",
                    "inputs": {},
                    "outputs": {},
                    "spec": {
                        "name": placement["name"],
                        "archetype": archetype,
                        "dimensions": [1.0, 1.0, 1.0],
                    },
                }
            )
        else:
            nodes.append(
                {
                    "id": mesh_node_id,
                    "type": "mesh_import",
                    "inputs": {},
                    "outputs": {},
                    "spec": {
                        "name": placement["name"],
                        "mesh_kind": "static_mesh",
                        "source_file": placement["ref"],
                        "target_path": placement["ref"].removeprefix("Assets/"),
                    },
                }
            )
        mesh_nodes.append(mesh_node_id)
        placements.append(
            {
                "name": placement["name"],
                "target_node": mesh_node_id,
                "layer": placement["layer"],
                "transform": placement["transform"],
            }
        )
    nodes.append(
        {
            "id": "placements_main",
            "type": "object_placement_set",
            "inputs": {"mesh_nodes": mesh_nodes},
            "outputs": {},
            "spec": {"placements": placements},
        }
    )
    nodes.append(
        {
            "id": "scene_main",
            "type": "scene_level",
            "inputs": {"terrain": "terrain_main", "placement_sets": ["placements_main"]},
            "outputs": {},
            "spec": {
                "level_slug": slug,
                "display_name": asset_graph["display_name"],
                "lighting": asset_graph["lighting"],
                "spawn": asset_graph["spawn"],
            },
        }
    )
    return {
        "asset_kind": "level",
        "bundle_kind": "environment_package",
        "bundle_slug": slug,
        "summary": asset_graph["summary"],
        "root_scene": "scene_main",
        "nodes": nodes,
    }


def _collect_refs(inputs: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in inputs.values():
        if isinstance(value, str):
            refs.append(value)
        elif isinstance(value, list):
            refs.extend(item for item in value if isinstance(item, str))
    return refs


def _topological_order(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_map = {node["id"]: node for node in nodes}
    remaining = {node["id"]: set(_collect_refs(node["inputs"])) for node in nodes}
    ordered: list[dict[str, Any]] = []
    while remaining:
        ready = sorted(node_id for node_id, deps in remaining.items() if not deps)
        if not ready:
            raise AssetGraphValidationError("Asset graph contains a dependency cycle or unresolved dependency chain")
        for node_id in ready:
            ordered.append(node_map[node_id])
            remaining.pop(node_id)
            for deps in remaining.values():
                deps.discard(node_id)
    return ordered


def _validate_texture_node(node: dict[str, Any], root: Path) -> None:
    spec = node["spec"]
    _assert_exact_keys(spec, TEXTURE_SPEC_KEYS, f'node[{node["id"]}].spec')
    mode = _require_string(spec, "mode", f'node[{node["id"]}].spec')
    presets = load_texture_preset_catalog(root)
    if mode not in presets["modes"]:
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.mode must be one of {presets["modes"]}')
    _require_string(spec, "name", f'node[{node["id"]}].spec')
    if mode == "import":
        _require_string(spec, "source_file", f'node[{node["id"]}].spec')
    else:
        width = _require_int(spec, "width", f'node[{node["id"]}].spec')
        height = _require_int(spec, "height", f'node[{node["id"]}].spec')
        if width <= 0 or height <= 0:
            raise AssetGraphValidationError(f'node[{node["id"]}].spec width/height must be positive')
    if mode == "solid_color":
        rgba = spec.get("rgba")
        if not isinstance(rgba, list) or len(rgba) != 4:
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.rgba must be a 4-element array')
    if mode == "procedural_pattern":
        palette = spec.get("palette")
        if not isinstance(palette, list) or len(palette) < 2:
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.palette must contain at least two colors')
        if spec.get("pattern") not in {"checker", "stripes", "radial"}:
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.pattern must be checker, stripes, or radial')
    if mode == "imagegen":
        _require_string(spec, "prompt", f'node[{node["id"]}].spec')


def _validate_material_node(node: dict[str, Any], root: Path) -> None:
    _assert_exact_keys(node["spec"], MATERIAL_SPEC_KEYS, f'node[{node["id"]}].spec')
    _require_string(node["spec"], "name", f'node[{node["id"]}].spec')
    template_name = _require_string(node["spec"], "template", f'node[{node["id"]}].spec')
    templates = {item["name"] for item in load_material_template_catalog(root)["templates"]}
    if template_name not in templates:
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.template references unknown material template {template_name}')
    _require_string(node["spec"], "surface_type", f'node[{node["id"]}].spec')
    if node["inputs"].get("diffuse_texture") is None:
        raise AssetGraphValidationError(f'node[{node["id"]}] must declare inputs.diffuse_texture')


def _validate_mesh_procedural_node(node: dict[str, Any], root: Path) -> None:
    _assert_exact_keys(node["spec"], MESH_PROCEDURAL_SPEC_KEYS, f'node[{node["id"]}].spec')
    _require_string(node["spec"], "name", f'node[{node["id"]}].spec')
    archetype = _require_string(node["spec"], "archetype", f'node[{node["id"]}].spec')
    catalog = {item["name"] for item in load_procedural_mesh_catalog(root)["archetypes"]}
    if archetype not in catalog:
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.archetype references unsupported procedural archetype {archetype}')
    _require_number_list(node["spec"], "dimensions", 3, f'node[{node["id"]}].spec')


def _validate_mesh_import_node(node: dict[str, Any], root: Path) -> None:
    spec = node["spec"]
    _assert_exact_keys(spec, MESH_IMPORT_SPEC_KEYS, f'node[{node["id"]}].spec')
    _require_string(spec, "name", f'node[{node["id"]}].spec')
    mesh_kind = _require_string(spec, "mesh_kind", f'node[{node["id"]}].spec')
    if mesh_kind not in {"static_mesh", "character_source"}:
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.mesh_kind must be static_mesh or character_source')
    source_file = _require_string(spec, "source_file", f'node[{node["id"]}].spec')
    path = Path(source_file)
    suffix = path.suffix.lower()
    if mesh_kind == "character_source" and suffix not in {".fbx", ".dae"}:
        raise AssetGraphValidationError(f'node[{node["id"]}] character_source imports require FBX or DAE')
    if suffix not in {".fbx", ".obj", ".dae", ".dxf", ".3ds", ".cgf"}:
        raise AssetGraphValidationError(f'node[{node["id"]}] source extension {suffix} is unsupported')
    _require_string(spec, "target_path", f'node[{node["id"]}].spec')


def _validate_terrain_node(node: dict[str, Any], root: Path) -> None:
    spec = node["spec"]
    _assert_exact_keys(spec, TERRAIN_SPEC_KEYS, f'node[{node["id"]}].spec')
    profile = _require_string(spec, "template_profile", f'node[{node["id"]}].spec')
    if profile not in {"flat_arena", "basin", "ridge_ring", "valley"}:
        raise AssetGraphValidationError(f'node[{node["id"]}] template_profile must be flat_arena, basin, ridge_ring, or valley')
    heightmap_size = _require_int(spec, "heightmap_size", f'node[{node["id"]}].spec')
    if heightmap_size not in {512, 1024, 2048}:
        raise AssetGraphValidationError(f'node[{node["id"]}] heightmap_size must be 512, 1024, or 2048')
    _resolve_level_template(profile, heightmap_size, root)
    paint_materials = node["inputs"].get("paint_materials", [])
    if not isinstance(paint_materials, list) or not paint_materials:
        raise AssetGraphValidationError(f'node[{node["id"]}] must declare at least one paint material input')
    paint_zones = spec.get("paint_zones")
    if not isinstance(paint_zones, list) or not paint_zones:
        raise AssetGraphValidationError(f'node[{node["id"]}] must declare non-empty paint_zones to avoid template-only terrain output')
    for index, zone in enumerate(paint_zones):
        if not isinstance(zone, dict):
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.paint_zones[{index}] must be an object')
        material_node = _require_string(zone, "material_node", f'node[{node["id"]}].spec.paint_zones[{index}]')
        if material_node not in paint_materials:
            raise AssetGraphValidationError(f'node[{node["id"]}] paint zone references material {material_node} not declared in inputs.paint_materials')
        zone_name = _require_string(zone, "zone", f'node[{node["id"]}].spec.paint_zones[{index}]')
        if zone_name not in {"base", "ridge", "basin", "perimeter"}:
            raise AssetGraphValidationError(f'node[{node["id"]}] paint zone name {zone_name} is unsupported')
    foliage_zones = spec.get("foliage_zones", [])
    if not isinstance(foliage_zones, list):
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.foliage_zones must be an array')


def _validate_placement_node(node: dict[str, Any]) -> None:
    _assert_exact_keys(node["spec"], PLACEMENT_SET_SPEC_KEYS, f'node[{node["id"]}].spec')
    mesh_nodes = node["inputs"].get("mesh_nodes", [])
    if not isinstance(mesh_nodes, list):
        raise AssetGraphValidationError(f'node[{node["id"]}].inputs.mesh_nodes must be an array')
    placements = node["spec"].get("placements")
    if not isinstance(placements, list) or not placements:
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.placements must be a non-empty array')
    for index, placement in enumerate(placements):
        if not isinstance(placement, dict):
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.placements[{index}] must be an object')
        _require_string(placement, "name", f'node[{node["id"]}].spec.placements[{index}]')
        target_node = _require_string(placement, "target_node", f'node[{node["id"]}].spec.placements[{index}]')
        if target_node not in mesh_nodes:
            raise AssetGraphValidationError(f'node[{node["id"]}] placement target {target_node} is not listed in inputs.mesh_nodes')
        if _require_string(placement, "layer", f'node[{node["id"]}].spec.placements[{index}]') != "Main":
            raise AssetGraphValidationError(f'node[{node["id"]}] placement layer must be Main')
        transform = placement.get("transform")
        if not isinstance(transform, dict):
            raise AssetGraphValidationError(f'node[{node["id"]}].spec.placements[{index}].transform must be an object')
        _validate_transform(transform, f'node[{node["id"]}].spec.placements[{index}].transform')


def _validate_scene_level_node(node: dict[str, Any]) -> None:
    _assert_exact_keys(node["spec"], SCENE_LEVEL_SPEC_KEYS, f'node[{node["id"]}].spec')
    if "terrain" not in node["inputs"]:
        raise AssetGraphValidationError(f'node[{node["id"]}] must declare inputs.terrain')
    placement_sets = node["inputs"].get("placement_sets", [])
    if not isinstance(placement_sets, list):
        raise AssetGraphValidationError(f'node[{node["id"]}].inputs.placement_sets must be an array')
    spec = node["spec"]
    level_slug = normalize_level_target_package(_require_string(spec, "level_slug", f'node[{node["id"]}].spec'))
    if not level_slug:
        raise AssetGraphValidationError(f'node[{node["id"]}] level_slug is invalid')
    spec["level_slug"] = level_slug
    _require_string(spec, "display_name", f'node[{node["id"]}].spec')
    lighting = spec.get("lighting")
    if not isinstance(lighting, dict):
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.lighting must be an object')
    for key in ("preset", "time_of_day", "sun_vector"):
        _require_string(lighting, key, f'node[{node["id"]}].spec.lighting')
    for key in ("time_hour", "sun_rotation", "sun_height"):
        _require_int(lighting, key, f'node[{node["id"]}].spec.lighting')
    spawn = spec.get("spawn")
    if not isinstance(spawn, dict):
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.spawn must be an object')
    if _require_string(spawn, "layer", f'node[{node["id"]}].spec.spawn') != "Main":
        raise AssetGraphValidationError(f'node[{node["id"]}] spawn layer must be Main')
    transform = spawn.get("transform")
    if not isinstance(transform, dict):
        raise AssetGraphValidationError(f'node[{node["id"]}].spec.spawn.transform must be an object')
    _validate_transform(transform, f'node[{node["id"]}].spec.spawn.transform')


def _validate_character_node(node: dict[str, Any], root: Path) -> None:
    _assert_exact_keys(node["spec"], CHARACTER_SPEC_KEYS, f'node[{node["id"]}].spec')
    if "source_mesh" not in node["inputs"]:
        raise AssetGraphValidationError(f'node[{node["id"]}] must declare inputs.source_mesh')
    spec = node["spec"]
    _require_string(spec, "character_name", f'node[{node["id"]}].spec')
    template_scope = _require_string(spec, "controller_scope", f'node[{node["id"]}].spec')
    _require_string(spec, "default_fragment", f'node[{node["id"]}].spec')
    _require_string(spec, "skeleton_file", f'node[{node["id"]}].spec')
    _require_string(spec, "skin_file", f'node[{node["id"]}].spec')
    _require_string(spec, "attachment_bone", f'node[{node["id"]}].spec')
    templates = load_character_template_catalog(root)["templates"]
    if template_scope != templates[0]["controller_scope"]:
        raise AssetGraphValidationError(f'node[{node["id"]}] controller_scope must match the first-person template scope')


def validate_asset_graph(asset_graph: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    asset_graph = dict(asset_graph)
    asset_graph.pop("dependency_order", None)
    if "bundle_kind" not in asset_graph and asset_graph.get("asset_kind") == "level" and "slug" in asset_graph:
        asset_graph = _legacy_level_to_bundle_graph(asset_graph)

    _assert_exact_keys(asset_graph, ALLOWED_GRAPH_TOP_LEVEL_KEYS, "asset_graph")
    asset_kind = _require_string(asset_graph, "asset_kind", "asset_graph")
    if asset_kind not in {"level", "character_package", "mesh_import"}:
        raise AssetGraphValidationError(f"Unsupported asset_kind: {asset_kind}")
    _require_string(asset_graph, "bundle_kind", "asset_graph")
    asset_graph["bundle_slug"] = bundle_slug(asset_graph)
    _require_string(asset_graph, "summary", "asset_graph")
    root_scene = _require_string(asset_graph, "root_scene", "asset_graph")
    nodes = asset_graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise AssetGraphValidationError("asset_graph.nodes must be a non-empty array")

    node_ids: set[str] = set()
    node_map: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise AssetGraphValidationError(f"asset_graph.nodes[{index}] must be an object")
        _assert_exact_keys(node, ALLOWED_NODE_KEYS, f"asset_graph.nodes[{index}]")
        node_id = _require_string(node, "id", f"asset_graph.nodes[{index}]")
        if node_id in node_ids:
            raise AssetGraphValidationError(f"Duplicate node id: {node_id}")
        node_ids.add(node_id)
        node_type = _require_string(node, "type", f"asset_graph.nodes[{index}]")
        if node_type not in SUPPORTED_NODE_TYPES:
            raise AssetGraphValidationError(f"Unsupported node type: {node_type}")
        if not isinstance(node.get("inputs"), dict):
            raise AssetGraphValidationError(f"asset_graph.nodes[{index}].inputs must be an object")
        if not isinstance(node.get("outputs"), dict):
            raise AssetGraphValidationError(f"asset_graph.nodes[{index}].outputs must be an object")
        if not isinstance(node.get("spec"), dict):
            raise AssetGraphValidationError(f"asset_graph.nodes[{index}].spec must be an object")
        node_map[node_id] = node

    if root_scene not in node_map:
        raise AssetGraphValidationError(f"asset_graph.root_scene references unknown node {root_scene}")

    for node in nodes:
        for ref in _collect_refs(node["inputs"]):
            if ref not in node_map:
                raise AssetGraphValidationError(f'node[{node["id"]}] references unknown dependency {ref}')
        if node["type"] == "texture_source":
            _validate_texture_node(node, repo_root)
        elif node["type"] == "material_surface":
            _validate_material_node(node, repo_root)
        elif node["type"] == "mesh_procedural":
            _validate_mesh_procedural_node(node, repo_root)
        elif node["type"] == "mesh_import":
            _validate_mesh_import_node(node, repo_root)
        elif node["type"] == "terrain_archetype":
            _validate_terrain_node(node, repo_root)
        elif node["type"] == "object_placement_set":
            _validate_placement_node(node)
        elif node["type"] == "scene_level":
            _validate_scene_level_node(node)
        elif node["type"] == "character_fp_package":
            _validate_character_node(node, repo_root)

    if asset_kind == "level" and node_map[root_scene]["type"] != "scene_level":
        raise AssetGraphValidationError("Level bundles must use a scene_level root node")
    if asset_kind == "character_package" and node_map[root_scene]["type"] != "character_fp_package":
        raise AssetGraphValidationError("Character bundles must use a character_fp_package root node")

    asset_graph["nodes"] = nodes
    asset_graph["dependency_order"] = _topological_order(nodes)
    return asset_graph


def capability_contract(root: Path | None = None) -> dict[str, Any]:
    return build_capability_catalog(root)
