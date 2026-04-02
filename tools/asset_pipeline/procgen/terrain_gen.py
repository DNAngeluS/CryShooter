from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter

from .noise_utils import octave_noise_2d, make_seeded_rng

# Noise parameters per subtype
_SUBTYPE_PARAMS: dict[str, dict] = {
    "forest":   {"octaves": 6, "frequency": 0.003, "persistence": 0.5,  "lacunarity": 2.0, "erosion": 3, "style": "hydraulic"},
    "desert":   {"octaves": 4, "frequency": 0.002, "persistence": 0.4,  "lacunarity": 2.2, "erosion": 5, "style": "thermal"},
    "tundra":   {"octaves": 5, "frequency": 0.004, "persistence": 0.6,  "lacunarity": 1.8, "erosion": 2, "style": "thermal"},
    "swamp":    {"octaves": 5, "frequency": 0.005, "persistence": 0.45, "lacunarity": 2.0, "erosion": 1, "style": "hydraulic"},
    "savanna":  {"octaves": 4, "frequency": 0.002, "persistence": 0.35, "lacunarity": 2.0, "erosion": 2, "style": "thermal"},
    "volcanic": {"octaves": 7, "frequency": 0.004, "persistence": 0.65, "lacunarity": 2.5, "erosion": 4, "style": "hydraulic"},
}
_DEFAULT_PARAMS = _SUBTYPE_PARAMS["forest"]

# Paint zone rules per subtype: which zone gets which material key
_ZONE_RULES: dict[str, dict[str, str]] = {
    "forest":   {"base": "base", "ridge": "ridge", "basin": "basin"},
    "desert":   {"base": "base", "ridge": "ridge", "perimeter": "base"},
    "tundra":   {"base": "base", "ridge": "ridge", "basin": "basin"},
    "swamp":    {"base": "basin", "ridge": "base",  "basin": "basin"},
    "savanna":  {"base": "base", "ridge": "ridge",  "perimeter": "base"},
    "volcanic": {"base": "ridge", "ridge": "ridge", "basin": "base"},
}


@dataclass
class TerrainResult:
    heights_uint16: np.ndarray          # (N, N) uint16
    procgen_json: dict                  # full procgen_mesh.json payload
    # terrain report dict in the same shape _compile_scene_level expects
    report_extras: dict = field(default_factory=dict)


def generate_open_terrain(
    spec: dict,
    seed: int,
    heightmap_size: int,
    max_height_m: float,
) -> TerrainResult:
    subtype = spec.get("subtype", "forest").lower()
    params = _SUBTYPE_PARAMS.get(subtype, _DEFAULT_PARAMS)
    erosion_passes = spec.get("erosion_passes", params["erosion"])
    foliage_density = float(spec.get("foliage_density", 0.5))

    # 1. Generate base noise
    heightmap = octave_noise_2d(
        heightmap_size, heightmap_size,
        octaves=params["octaves"],
        frequency=params["frequency"],
        persistence=params["persistence"],
        lacunarity=params["lacunarity"],
        seed=seed,
    )

    # 2. Profile shaping (basin by default for FPS levels — natural bowl)
    profile = spec.get("template_profile", "basin")
    heightmap = _apply_profile(heightmap, profile)

    # 3. Erosion
    if params["style"] == "hydraulic":
        heightmap = _erode_hydraulic(heightmap, passes=erosion_passes)
    else:
        heightmap = _erode_thermal(heightmap, passes=erosion_passes)

    # 4. Guarantee flat spawn zone (48×48 m / unit_size=2 → 24×24 cells near centre)
    heightmap = _flatten_spawn_zone(heightmap, radius_cells=12)

    # 5. Normalize to [0, 1] then encode to uint16
    lo, hi = heightmap.min(), heightmap.max()
    if hi > lo:
        heightmap = (heightmap - lo) / (hi - lo)
    heights_uint16 = (heightmap * 65535).astype(np.uint16)

    # 6. Derive paint zone hints from gradient and elevation
    paint_zone_hints = _derive_paint_zones(heightmap, subtype, spec)

    # 7. Foliage hints via Poisson disc sampling
    foliage_hints = _foliage_hints(heightmap, seed=seed + 1, density=foliage_density,
                                   world_size_m=heightmap_size * 2)

    # 8. Spawn hint (centre flat zone)
    centre_m = heightmap_size  # world_size_m = heightmap_size * unit_size(2)
    spawn_z = float(heightmap[heightmap_size // 2, heightmap_size // 2]) * max_height_m
    spawn_hints = [{"position_m": [centre_m, centre_m, spawn_z + 1.8], "yaw_deg": 0,
                    "role": "player_start", "sector_id": "terrain"}]

    procgen_json = {
        "$schema": "procgen-mesh-v1",
        "format_version": 1,
        "level_category": "open",
        "level_subtype": subtype,
        "seed": seed,
        "world_bounds": {
            "width_m": heightmap_size * 2,
            "depth_m": heightmap_size * 2,
            "height_m": max_height_m,
        },
        "geometry": {"obj_file": None},
        "sectors": [{"sector_id": "terrain", "sector_type": "terrain",
                     "bounds_m": [0, 0, 0, heightmap_size * 2, heightmap_size * 2, max_height_m],
                     "center_m": [centre_m, centre_m, max_height_m / 2],
                     "connections": [], "tags": ["spawn_candidate"]}],
        "spawn_hints": spawn_hints,
        "foliage_hints": foliage_hints,
        "paint_zone_hints": paint_zone_hints,
    }

    return TerrainResult(heights_uint16=heights_uint16, procgen_json=procgen_json)


# ---------------------------------------------------------------------------
# Profile shapers
# ---------------------------------------------------------------------------

def _apply_profile(h: np.ndarray, profile: str) -> np.ndarray:
    size = h.shape[0]
    cx, cy = size / 2.0, size / 2.0
    xs = np.arange(size, dtype=np.float32)
    ys = np.arange(size, dtype=np.float32)
    xg, yg = np.meshgrid(xs, ys)
    dist = np.sqrt((xg - cx) ** 2 + (yg - cy) ** 2) / (size * 0.5)

    if profile == "basin":
        # Bowl: lower in centre, higher on edges
        h = h * 0.6 + dist * 0.4
    elif profile == "ridge_ring":
        # Ridge around a flat centre
        ridge = np.exp(-((dist - 0.55) ** 2) / 0.02)
        h = h * 0.5 + ridge * 0.5
    elif profile == "valley":
        # Trench along X axis
        ycenter = np.abs(yg / size - 0.5)
        h = h * 0.5 + ycenter * 0.5
    # flat_arena / default: no shaping
    return h


# ---------------------------------------------------------------------------
# Erosion
# ---------------------------------------------------------------------------

def _erode_hydraulic(h: np.ndarray, passes: int) -> np.ndarray:
    for _ in range(passes):
        smoothed = uniform_filter(h, size=3, mode="reflect")
        slope = h - smoothed
        # Water carries sediment downhill
        h = h - np.clip(slope, 0, None) * 0.3 + np.clip(-slope, 0, None) * 0.05
        h = np.clip(h, 0.0, 1.0)
    return h


def _erode_thermal(h: np.ndarray, passes: int) -> np.ndarray:
    talus = 0.05
    for _ in range(passes):
        grad_y, grad_x = np.gradient(h)
        slope = np.sqrt(grad_x ** 2 + grad_y ** 2)
        excess = np.maximum(slope - talus, 0)
        h = h - excess * 0.2
        h = np.clip(h, 0.0, 1.0)
    return h


# ---------------------------------------------------------------------------
# Spawn zone flattening
# ---------------------------------------------------------------------------

def _flatten_spawn_zone(h: np.ndarray, radius_cells: int) -> np.ndarray:
    size = h.shape[0]
    cx, cy = size // 2, size // 2
    y0 = max(0, cy - radius_cells)
    y1 = min(size, cy + radius_cells)
    x0 = max(0, cx - radius_cells)
    x1 = min(size, cx + radius_cells)
    target = float(h[cy, cx])
    h = h.copy()
    h[y0:y1, x0:x1] = np.clip(
        h[y0:y1, x0:x1],
        target - 0.02,
        target + 0.02,
    )
    return h


# ---------------------------------------------------------------------------
# Paint zone hints
# ---------------------------------------------------------------------------

def _derive_paint_zones(h: np.ndarray, subtype: str, spec: dict) -> list[dict]:
    grad_y, grad_x = np.gradient(h)
    slope = np.sqrt(grad_x ** 2 + grad_y ** 2)
    mean_h = float(h.mean())
    std_h = float(h.std())

    ridge_mask = slope > slope.mean() + slope.std()
    basin_mask = h < (mean_h - std_h)

    zones = spec.get("paint_zone_config", {})
    rules = _ZONE_RULES.get(subtype, _ZONE_RULES["forest"])

    hints = []
    hints.append({
        "zone": "base",
        "material_key": rules.get("base", "base"),
        "material_slot": zones.get("base", "base"),
        "coverage_fraction": float(1.0 - ridge_mask.mean() - basin_mask.mean()),
    })
    if ridge_mask.any():
        hints.append({
            "zone": "ridge",
            "material_key": rules.get("ridge", "ridge"),
            "material_slot": zones.get("ridge", "ridge"),
            "coverage_fraction": float(ridge_mask.mean()),
        })
    if basin_mask.any():
        hints.append({
            "zone": "basin",
            "material_key": rules.get("basin", "basin"),
            "material_slot": zones.get("basin", "basin"),
            "coverage_fraction": float(basin_mask.mean()),
        })
    return hints


# ---------------------------------------------------------------------------
# Foliage hints (Poisson-disc-style rejection sampling)
# ---------------------------------------------------------------------------

def _foliage_hints(
    h: np.ndarray,
    seed: int,
    density: float,
    world_size_m: float,
    max_hints: int = 200,
) -> list[dict]:
    rng = make_seeded_rng(seed)
    size = h.shape[0]
    unit = world_size_m / size
    mean_h = float(h.mean())
    std_h = float(h.std())
    count = int(max_hints * density)
    hints = []
    attempts = 0
    while len(hints) < count and attempts < count * 10:
        attempts += 1
        xi = int(rng.integers(0, size))
        yi = int(rng.integers(0, size))
        elev = float(h[yi, xi])
        # Trees in mid-elevation band; rocks on ridges
        if mean_h - std_h < elev < mean_h + std_h:
            hints.append({
                "position_m": [xi * unit, yi * unit, 0.0],
                "type": "tree",
                "density_weight": float(density),
            })
        elif elev > mean_h + std_h:
            hints.append({
                "position_m": [xi * unit, yi * unit, 0.0],
                "type": "rock",
                "density_weight": float(density * 0.4),
            })
    return hints
