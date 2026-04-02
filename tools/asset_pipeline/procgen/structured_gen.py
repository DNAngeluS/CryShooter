from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .noise_utils import make_seeded_rng
from .mesh_writer import add_box_mesh

_EMPTY = 0
_WALL = 1
_TOWER = 2
_GATE = 3
_COURTYARD = 4
_ROOM = 5

_CELL_TYPE_NAME = {
    _EMPTY: "empty", _WALL: "wall", _TOWER: "tower",
    _GATE: "gate", _COURTYARD: "courtyard", _ROOM: "room",
}


@dataclass
class StructuredResult:
    procgen_json: dict
    vertices: list = field(default_factory=list)
    faces: list = field(default_factory=list)
    uvs: list = field(default_factory=list)
    uv_indices: list = field(default_factory=list)
    material_ids: list = field(default_factory=list)
    material_names: list = field(default_factory=list)


def generate_structured(spec: dict, seed: int, world_size_m: float) -> StructuredResult:
    subtype = spec.get("subtype", "arena").lower()
    cell_size = float(spec.get("cell_size_m", 12.0))
    wall_height = float(spec.get("wall_height_m", 8.0))

    grid_n = max(5, int(world_size_m / cell_size))

    if subtype in ("castle", "fortress", "ruins"):
        grid = _gen_castle_grid(grid_n, seed, max_backtracks=50)
    else:  # arena, warehouse, default
        grid = _gen_arena_grid(grid_n)

    return _build_geometry(grid, grid_n, cell_size, wall_height, subtype, seed, world_size_m)


# ---------------------------------------------------------------------------
# Grid generators
# ---------------------------------------------------------------------------

def _gen_arena_grid(grid_n: int) -> np.ndarray:
    """Simple arena: perimeter walls, corner towers, one gate, open courtyard."""
    grid = np.full((grid_n, grid_n), _COURTYARD, dtype=np.int8)
    # Perimeter walls
    grid[0, :] = _WALL
    grid[-1, :] = _WALL
    grid[:, 0] = _WALL
    grid[:, -1] = _WALL
    # Corner towers
    grid[0, 0] = grid[0, -1] = grid[-1, 0] = grid[-1, -1] = _TOWER
    # North gate
    mid = grid_n // 2
    grid[0, mid] = _GATE
    return grid


def _gen_castle_grid(grid_n: int, seed: int, max_backtracks: int = 50) -> np.ndarray:
    """WFC-lite castle layout with keep, great_hall, courtyard, and perimeter walls."""
    rng = make_seeded_rng(seed)
    grid = np.full((grid_n, grid_n), _EMPTY, dtype=np.int8)

    # Perimeter walls and towers
    grid[0, :] = _WALL
    grid[-1, :] = _WALL
    grid[:, 0] = _WALL
    grid[:, -1] = _WALL
    grid[0, 0] = grid[0, -1] = grid[-1, 0] = grid[-1, -1] = _TOWER

    # Gate on north face
    mid = grid_n // 2
    grid[0, mid] = _GATE

    # Interior: courtyard in centre, rooms around it
    interior_cells = [(y, x) for y in range(1, grid_n-1) for x in range(1, grid_n-1)]
    # Centre region = courtyard
    c = grid_n // 2
    radius = max(1, grid_n // 4)
    for y, x in interior_cells:
        if abs(y - c) <= radius and abs(x - c) <= radius:
            grid[y, x] = _COURTYARD

    # Place rooms via WFC-lite
    room_cells = [(y, x) for y, x in interior_cells
                  if grid[y, x] == _EMPTY and not _is_corner_adjacent(y, x, grid_n)]
    backtracks = 0
    attempts = 0
    while room_cells and attempts < len(room_cells) + max_backtracks:
        attempts += 1
        if backtracks >= max_backtracks:
            # Fallback: fill remaining empty interior with rooms
            for y, x in room_cells:
                if grid[y, x] == _EMPTY:
                    grid[y, x] = _ROOM
            break
        idx = int(rng.integers(0, len(room_cells)))
        y, x = room_cells[idx]
        if grid[y, x] != _EMPTY:
            room_cells.pop(idx)
            continue
        # Check adjacency constraint: must adjoin courtyard or another room
        neighbors = _get_neighbors(y, x, grid_n)
        adj_types = {grid[ny, nx] for ny, nx in neighbors}
        if _COURTYARD in adj_types or _ROOM in adj_types or _GATE in adj_types:
            grid[y, x] = _ROOM
            room_cells.pop(idx)
        else:
            backtracks += 1

    return grid


def _is_corner_adjacent(y, x, grid_n):
    corners = {(0, 0), (0, grid_n-1), (grid_n-1, 0), (grid_n-1, grid_n-1)}
    return any((y+dy, x+dx) in corners for dy in (-1, 0, 1) for dx in (-1, 0, 1))


def _get_neighbors(y, x, grid_n):
    result = []
    for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
        ny, nx = y+dy, x+dx
        if 0 <= ny < grid_n and 0 <= nx < grid_n:
            result.append((ny, nx))
    return result


# ---------------------------------------------------------------------------
# Geometry builder
# ---------------------------------------------------------------------------

def _build_geometry(
    grid: np.ndarray,
    grid_n: int,
    cell_size: float,
    wall_height: float,
    subtype: str,
    seed: int,
    world_size_m: float,
) -> StructuredResult:
    mat_names = [f"{subtype}_wall", f"{subtype}_floor", f"{subtype}_tower"]
    verts, faces, uvs, uv_idx, mat_ids = [], [], [], [], []
    sectors = []
    spawn_hints = []

    for yi in range(grid_n):
        for xi in range(grid_n):
            cell_type = int(grid[yi, xi])
            x0 = xi * cell_size
            y0 = yi * cell_size
            x1 = x0 + cell_size
            y1 = y0 + cell_size
            cx, cy = (x0+x1)/2, (y0+y1)/2

            if cell_type in (_EMPTY,):
                continue

            floor_mat = 1
            if cell_type in (_WALL, _GATE):
                add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                             min_corner=(x0, y0, 0.0), max_corner=(x1, y1, wall_height),
                             material_id=0)
            elif cell_type == _TOWER:
                # Taller tower
                add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                             min_corner=(x0, y0, 0.0), max_corner=(x1, y1, wall_height * 1.6),
                             material_id=2)
            else:  # COURTYARD, ROOM
                # Floor slab
                add_box_mesh(verts, faces, uvs, uv_idx, mat_ids,
                             min_corner=(x0, y0, 0.0), max_corner=(x1, y1, 0.2),
                             material_id=floor_mat)

            sector_id = f"cell_{yi}_{xi}"
            tags = []
            if cell_type == _COURTYARD:
                tags = ["spawn_candidate"]
                if not spawn_hints:
                    spawn_hints.append({
                        "position_m": [cx, cy, 1.8], "yaw_deg": 0,
                        "role": "player_start", "sector_id": sector_id,
                    })
            sectors.append({
                "sector_id": sector_id,
                "sector_type": _CELL_TYPE_NAME.get(cell_type, "unknown"),
                "bounds_m": [x0, y0, 0.0, x1, y1, wall_height],
                "center_m": [cx, cy, wall_height/2],
                "connections": [f"cell_{yi+dy}_{xi+dx}"
                                for dy, dx in ((-1,0),(1,0),(0,-1),(0,1))
                                if 0 <= yi+dy < grid_n and 0 <= xi+dx < grid_n
                                and int(grid[yi+dy, xi+dx]) not in (_EMPTY, _WALL, _TOWER)],
                "tags": tags,
            })

    if not spawn_hints:
        # Fallback spawn at world centre
        spawn_hints.append({"position_m": [world_size_m/2, world_size_m/2, 1.8],
                             "yaw_deg": 0, "role": "player_start", "sector_id": "fallback"})

    procgen_json = {
        "$schema": "procgen-mesh-v1",
        "format_version": 1,
        "level_category": "structured",
        "level_subtype": subtype,
        "seed": seed,
        "world_bounds": {
            "width_m": world_size_m,
            "depth_m": world_size_m,
            "height_m": wall_height * 2,
        },
        "geometry": {
            "obj_file": "geometry.obj",
            "vertex_count": len(verts),
            "face_count": len(faces),
            "material_slots": [{"slot_id": i, "name": n} for i, n in enumerate(mat_names)],
        },
        "sectors": sectors,
        "spawn_hints": spawn_hints,
        "foliage_hints": [],
        "paint_zone_hints": [],
    }

    return StructuredResult(
        procgen_json=procgen_json,
        vertices=verts, faces=faces, uvs=uvs, uv_indices=uv_idx,
        material_ids=mat_ids, material_names=mat_names,
    )
