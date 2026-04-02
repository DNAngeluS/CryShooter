from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import label, uniform_filter

import networkx as nx

from .noise_utils import make_seeded_rng
from .mesh_writer import add_box_mesh


@dataclass
class InteriorResult:
    procgen_json: dict
    vertices: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    uv_indices: list = field(default_factory=list)
    material_ids: list = field(default_factory=list)
    material_names: list = field(default_factory=list)


def generate_interior(spec: dict, seed: int, world_size_m: float) -> InteriorResult:
    subtype = spec.get("subtype", "cave").lower()
    min_rooms = int(spec.get("min_rooms", 5))
    max_rooms = int(spec.get("max_rooms", 12))
    corridor_width = float(spec.get("corridor_width_m", 3.0))

    if subtype == "cave":
        return _gen_cave(spec, seed, world_size_m)
    elif subtype in ("dungeon", "sewer"):
        return _gen_dungeon(spec, seed, world_size_m, min_rooms, max_rooms, corridor_width)
    else:  # ship, bunker, and fallback
        return _gen_corridor_graph(spec, seed, world_size_m, min_rooms, max_rooms, corridor_width)


# ---------------------------------------------------------------------------
# Cave — Cellular Automata
# ---------------------------------------------------------------------------

def _gen_cave(spec: dict, seed: int, world_size_m: float) -> InteriorResult:
    rng = make_seeded_rng(seed)
    cell_size = 2.0  # metres per grid cell
    grid_n = max(16, int(world_size_m / cell_size))
    wall_height = float(spec.get("wall_height_m", 6.0))

    # 1. Random fill (~52% solid)
    grid = (rng.random((grid_n, grid_n)) < 0.52).astype(np.uint8)

    # 2. CA smoothing passes
    for _ in range(6):
        neighbor_sum = uniform_filter(grid.astype(np.float32), size=3, mode="constant", cval=1) * 9
        grid = (neighbor_sum >= 5).astype(np.uint8)

    # 3. Keep only the largest connected open region
    open_mask = (grid == 0).astype(np.int32)
    labeled, n_features = label(open_mask)
    if n_features == 0:
        # Fallback: open a 5×5 room in the centre
        c = grid_n // 2
        grid[c-2:c+3, c-2:c+3] = 0
        labeled, _ = label((grid == 0).astype(np.int32))

    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0  # ignore background
    largest_label = int(sizes.argmax())
    open_mask = (labeled == largest_label)

    # 4. Build sectors and geometry from open cells
    sectors, spawn_hints = _sectors_from_grid(open_mask, cell_size, wall_height, grid_n)
    verts, faces, uvs, uv_idx, mat_ids, mat_names = _mesh_from_grid(
        open_mask, cell_size, wall_height, grid_n, wall_mat=0, floor_mat=1
    )

    mat_names = ["cave_wall", "cave_floor"]

    procgen_json = _make_interior_json(
        "cave", seed, world_size_m, wall_height, sectors, spawn_hints,
        verts, faces, mat_names,
    )
    return InteriorResult(
        procgen_json=procgen_json,
        vertices=verts, faces=faces, uvs=uvs, uv_indices=uv_idx,
        material_ids=mat_ids, material_names=mat_names,
    )


# ---------------------------------------------------------------------------
# Dungeon — Binary Space Partition
# ---------------------------------------------------------------------------

def _gen_dungeon(
    spec: dict, seed: int, world_size_m: float,
    min_rooms: int, max_rooms: int, corridor_width: float,
) -> InteriorResult:
    rng = make_seeded_rng(seed)
    wall_height = float(spec.get("wall_height_m", 4.0))

    # BSP partitioning
    leaves = _bsp_split(0, 0, world_size_m, world_size_m, rng, max_depth=4)
    rooms = [_leaf_to_room(leaf, rng) for leaf in leaves[:max_rooms]]

    # Room connectivity via MST + extra edges
    G = nx.Graph()
    for i, r in enumerate(rooms):
        G.add_node(i, center=((r[0]+r[2])/2, (r[1]+r[3])/2))
    for i in range(len(rooms)):
        for j in range(i+1, len(rooms)):
            ci = G.nodes[i]["center"]
            cj = G.nodes[j]["center"]
            dist = ((ci[0]-cj[0])**2 + (ci[1]-cj[1])**2) ** 0.5
            G.add_edge(i, j, weight=dist)
    mst = nx.minimum_spanning_tree(G, weight="weight")
    # Add ~15% extra edges for loops
    all_edges = sorted(G.edges(data=True), key=lambda e: e[2]["weight"])
    extra = max(1, int(len(all_edges) * 0.15))
    added = 0
    for u, v, _ in all_edges:
        if not mst.has_edge(u, v) and added < extra:
            mst.add_edge(u, v)
            added += 1

    verts, faces, uvs, uv_idx, mat_ids = [], [], [], [], []
    mat_names = ["dungeon_wall", "dungeon_floor"]
    sectors = []
    spawn_hints = []

    for i, room in enumerate(rooms):
        x0, y0, x1, y1 = room
        _add_room_box(verts, faces, uvs, uv_idx, mat_ids,
                      x0, y0, x1, y1, 0.0, wall_height, floor_mat=1, wall_mat=0)
        cx, cy = (x0+x1)/2, (y0+y1)/2
        sectors.append({
            "sector_id": f"room_{i}", "sector_type": "room",
            "bounds_m": [x0, y0, 0.0, x1, y1, wall_height],
            "center_m": [cx, cy, wall_height/2],
            "connections": [f"corridor_{i}_{j}" for j in mst.neighbors(i)],
            "tags": ["spawn_candidate"] if i == 0 else [],
        })
        if i == 0:
            spawn_hints.append({"position_m": [cx, cy, 1.8], "yaw_deg": 0,
                                 "role": "player_start", "sector_id": "room_0"})

    for u, v in mst.edges():
        cu = G.nodes[u]["center"]
        cv = G.nodes[v]["center"]
        _add_corridor(verts, faces, uvs, uv_idx, mat_ids,
                      cu, cv, corridor_width, wall_height, floor_mat=1, wall_mat=0)

    procgen_json = _make_interior_json(
        "dungeon", seed, world_size_m, wall_height, sectors, spawn_hints,
        verts, faces, mat_names,
    )
    return InteriorResult(
        procgen_json=procgen_json,
        vertices=verts, faces=faces, uvs=uvs, uv_indices=uv_idx,
        material_ids=mat_ids, material_names=mat_names,
    )


# ---------------------------------------------------------------------------
# Corridor graph — Ship / Bunker
# ---------------------------------------------------------------------------

def _gen_corridor_graph(
    spec: dict, seed: int, world_size_m: float,
    min_rooms: int, max_rooms: int, corridor_width: float,
) -> InteriorResult:
    rng = make_seeded_rng(seed)
    subtype = spec.get("subtype", "ship")
    wall_height = float(spec.get("wall_height_m", 3.0))
    n_rooms = int(rng.integers(min_rooms, max_rooms + 1))

    # Place rooms with repulsion
    room_size = world_size_m / (n_rooms ** 0.5 + 1) * 0.6
    rooms = _place_rooms_repulsion(rng, n_rooms, world_size_m, room_size)

    G = nx.Graph()
    for i, (cx, cy) in enumerate(rooms):
        G.add_node(i, center=(cx, cy))
    for i in range(len(rooms)):
        for j in range(i+1, len(rooms)):
            ci, cj = rooms[i], rooms[j]
            dist = ((ci[0]-cj[0])**2 + (ci[1]-cj[1])**2)**0.5
            G.add_edge(i, j, weight=dist)
    mst = nx.minimum_spanning_tree(G, weight="weight")

    verts, faces, uvs, uv_idx, mat_ids = [], [], [], [], []
    mat_names = [f"{subtype}_wall", f"{subtype}_floor"]
    sectors = []
    spawn_hints = []

    for i, (cx, cy) in enumerate(rooms):
        half = room_size / 2
        x0, y0, x1, y1 = cx-half, cy-half, cx+half, cy+half
        _add_room_box(verts, faces, uvs, uv_idx, mat_ids,
                      x0, y0, x1, y1, 0.0, wall_height, floor_mat=1, wall_mat=0)
        sectors.append({
            "sector_id": f"room_{i}", "sector_type": "room",
            "bounds_m": [x0, y0, 0.0, x1, y1, wall_height],
            "center_m": [cx, cy, wall_height/2],
            "connections": [f"room_{j}" for j in mst.neighbors(i)],
            "tags": ["spawn_candidate"] if i == 0 else [],
        })
        if i == 0:
            spawn_hints.append({"position_m": [cx, cy, 1.8], "yaw_deg": 0,
                                 "role": "player_start", "sector_id": "room_0"})

    for u, v in mst.edges():
        _add_corridor(verts, faces, uvs, uv_idx, mat_ids,
                      rooms[u], rooms[v], corridor_width, wall_height, floor_mat=1, wall_mat=0)

    procgen_json = _make_interior_json(
        subtype, seed, world_size_m, wall_height, sectors, spawn_hints,
        verts, faces, mat_names,
    )
    return InteriorResult(
        procgen_json=procgen_json,
        vertices=verts, faces=faces, uvs=uvs, uv_indices=uv_idx,
        material_ids=mat_ids, material_names=mat_names,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bsp_split(x0, y0, x1, y1, rng, max_depth):
    if max_depth == 0 or (x1-x0) < 20 or (y1-y0) < 20:
        return [(x0, y0, x1, y1)]
    if (x1-x0) > (y1-y0):
        split = float(rng.uniform(x0 + (x1-x0)*0.35, x0 + (x1-x0)*0.65))
        return (_bsp_split(x0, y0, split, y1, rng, max_depth-1) +
                _bsp_split(split, y0, x1, y1, rng, max_depth-1))
    else:
        split = float(rng.uniform(y0 + (y1-y0)*0.35, y0 + (y1-y0)*0.65))
        return (_bsp_split(x0, y0, x1, split, rng, max_depth-1) +
                _bsp_split(x0, split, x1, y1, rng, max_depth-1))


def _leaf_to_room(leaf, rng):
    x0, y0, x1, y1 = leaf
    margin = (x1-x0) * float(rng.uniform(0.05, 0.15))
    return (x0+margin, y0+margin, x1-margin, y1-margin)


def _place_rooms_repulsion(rng, n_rooms, world_size_m, room_size):
    positions = []
    margin = room_size
    for _ in range(n_rooms):
        for attempt in range(50):
            cx = float(rng.uniform(margin, world_size_m - margin))
            cy = float(rng.uniform(margin, world_size_m - margin))
            if all(((cx-px)**2 + (cy-py)**2)**0.5 > room_size * 1.5 for px, py in positions):
                positions.append((cx, cy))
                break
        else:
            positions.append((float(rng.uniform(margin, world_size_m-margin)),
                              float(rng.uniform(margin, world_size_m-margin))))
    return positions


def _add_room_box(verts, faces, uvs, uv_idx, mat_ids,
                  x0, y0, x1, y1, z0, z1, *, floor_mat, wall_mat):
    # Floor
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0, y0, z0), max_corner=(x1, y1, z0 + 0.2), material_id=floor_mat)
    # Walls
    thick = 0.3
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0-thick, y0-thick, z0), max_corner=(x1+thick, y0, z1), material_id=wall_mat)
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0-thick, y1, z0), max_corner=(x1+thick, y1+thick, z1), material_id=wall_mat)
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0-thick, y0, z0), max_corner=(x0, y1, z1), material_id=wall_mat)
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x1, y0, z0), max_corner=(x1+thick, y1, z1), material_id=wall_mat)
    # Ceiling
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0, y0, z1), max_corner=(x1, y1, z1 + 0.2), material_id=wall_mat)


def _add_corridor(verts, faces, uvs, uv_idx, mat_ids,
                  c0, c1, width, height, *, floor_mat, wall_mat):
    half = width / 2
    dx = c1[0] - c0[0]
    dy = c1[1] - c0[1]
    length = (dx**2 + dy**2)**0.5
    if length < 0.1:
        return
    nx_ = -dy / length
    ny_ = dx / length
    p0x = c0[0] + nx_ * half
    p0y = c0[1] + ny_ * half
    p1x = c1[0] + nx_ * half
    p1y = c1[1] + ny_ * half
    x0 = min(p0x, p1x, c0[0]-nx_*half, c1[0]-nx_*half)
    y0 = min(p0y, p1y, c0[1]-ny_*half, c1[1]-ny_*half)
    x1 = max(p0x, p1x, c0[0]-nx_*half, c1[0]-nx_*half)
    y1 = max(p0y, p1y, c0[1]-ny_*half, c1[1]-ny_*half)
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0, y0, 0.0), max_corner=(x1, y1, 0.2), material_id=floor_mat)
    add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                 min_corner=(x0, y0, 0.0), max_corner=(x1, y1, height), material_id=wall_mat)


def _sectors_from_grid(open_mask, cell_size, wall_height, grid_n):
    sectors = []
    spawn_hints = []
    # Label connected regions as sectors
    labeled, n_feat = label(open_mask.astype(np.int32))
    for i in range(1, min(n_feat + 1, 20)):
        ys, xs = np.where(labeled == i)
        if len(xs) == 0:
            continue
        x0 = float(xs.min()) * cell_size
        y0 = float(ys.min()) * cell_size
        x1 = float(xs.max() + 1) * cell_size
        y1 = float(ys.max() + 1) * cell_size
        cx, cy = (x0+x1)/2, (y0+y1)/2
        sector = {
            "sector_id": f"cave_sector_{i}",
            "sector_type": "room",
            "bounds_m": [x0, y0, 0.0, x1, y1, wall_height],
            "center_m": [cx, cy, wall_height/2],
            "connections": [],
            "tags": ["spawn_candidate"] if i == 1 else [],
        }
        sectors.append(sector)
        if i == 1:
            spawn_hints.append({"position_m": [cx, cy, 1.8], "yaw_deg": 0,
                                 "role": "player_start", "sector_id": "cave_sector_1"})
    return sectors, spawn_hints


def _mesh_from_grid(open_mask, cell_size, wall_height, grid_n, wall_mat, floor_mat):
    verts, faces, uvs, uv_idx, mat_ids = [], [], [], [], []
    for yi in range(grid_n):
        for xi in range(grid_n):
            if open_mask[yi, xi]:
                x0 = xi * cell_size
                y0 = yi * cell_size
                x1 = x0 + cell_size
                y1 = y0 + cell_size
                # Floor slab
                add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                             min_corner=(x0, y0, 0.0), max_corner=(x1, y1, 0.1),
                             material_id=floor_mat)
                # Wall faces only on solid neighbours
                for nyi, nxi, wx0, wx1, wy0, wy1 in [
                    (yi-1, xi,   x0, x1,   y0, y0+0.2),
                    (yi+1, xi,   x0, x1,   y1-0.2, y1),
                    (yi, xi-1,   x0, x0+0.2, y0, y1),
                    (yi, xi+1,   x1-0.2, x1, y0, y1),
                ]:
                    if nyi < 0 or nyi >= grid_n or nxi < 0 or nxi >= grid_n or not open_mask[nyi, nxi]:
                        add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                                     min_corner=(wx0, wy0, 0.0),
                                     max_corner=(wx1, wy1, wall_height),
                                     material_id=wall_mat)
    return verts, faces, uvs, uv_idx, mat_ids, ["cave_wall", "cave_floor"]


def _make_interior_json(subtype, seed, world_size_m, wall_height,
                        sectors, spawn_hints, verts, faces, mat_names):
    return {
        "$schema": "procgen-mesh-v1",
        "format_version": 1,
        "level_category": "interior",
        "level_subtype": subtype,
        "seed": seed,
        "world_bounds": {
            "width_m": world_size_m,
            "depth_m": world_size_m,
            "height_m": wall_height,
        },
        "geometry": {
            "obj_file": "geometry.obj",
            "vertex_count": len(verts),
            "face_count": len(faces),
            "material_slots": [
                {"slot_id": i, "name": n} for i, n in enumerate(mat_names)
            ],
        },
        "sectors": sectors,
        "spawn_hints": spawn_hints,
        "foliage_hints": [],
        "paint_zone_hints": [],
    }
