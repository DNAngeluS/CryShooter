from __future__ import annotations

from pathlib import Path

from .common import slugify


def _detect_size(prompt: str) -> int:
    text = prompt.lower()
    if any(token in text for token in ("tiny", "small", "compact")):
        return 512
    if any(token in text for token in ("huge", "massive", "large")):
        return 2048
    if any(token in text for token in ("medium", "mid-sized")):
        return 1024
    return 1024


def _detect_time_of_day(prompt: str) -> tuple[str, int]:
    text = prompt.lower()
    mapping = {
        "dawn": ("dawn", 6),
        "sunrise": ("dawn", 6),
        "morning": ("morning", 9),
        "noon": ("noon", 12),
        "midday": ("noon", 12),
        "afternoon": ("afternoon", 15),
        "dusk": ("dusk", 18),
        "sunset": ("dusk", 18),
        "night": ("night", 22),
    }
    for key, value in mapping.items():
        if key in text:
            return value
    return ("noon", 12)


def _detect_biome(prompt: str) -> str:
    text = prompt.lower()
    for biome in ("desert", "forest", "snow", "arctic", "urban", "jungle", "volcanic", "grassland"):
        if biome in text:
            return biome
    return "temperate"


def _detect_height_profile(prompt: str) -> str:
    text = prompt.lower()
    if any(token in text for token in ("flat", "arena", "test")):
        return "flat"
    if any(token in text for token in ("mountain", "cliff", "steep")):
        return "mountainous"
    if any(token in text for token in ("hill", "rolling", "valley")):
        return "hilly"
    return "gentle"


def _terrain_color(biome: str) -> list[int]:
    mapping = {
        "desert": [140, 120, 90, 255],
        "snow": [220, 224, 230, 255],
        "arctic": [210, 220, 225, 255],
        "forest": [78, 105, 72, 255],
        "jungle": [58, 96, 64, 255],
        "urban": [118, 118, 118, 255],
        "volcanic": [74, 62, 60, 255],
        "grassland": [108, 132, 84, 255],
        "temperate": [118, 108, 86, 255],
    }
    return mapping[biome]


def synthesize_spec(request: dict, project_root: Path) -> dict:
    prompt = request["natural_language_prompt"]
    kind = request["asset_kind"]
    if kind != "level":
        raise ValueError(f"Unsupported automatic spec synthesis for asset_kind={kind}")

    size = _detect_size(prompt)
    slug = request.get("target_package") or slugify(prompt[:48])
    biome = _detect_biome(prompt)
    time_label, time_hour = _detect_time_of_day(prompt)
    height_profile = _detect_height_profile(prompt)
    center = size // 2
    tile_count = max(1, size // 256)
    return {
        "asset_kind": "level",
        "slug": slug,
        "display_name": slug.replace("-", " ").title(),
        "summary": prompt.strip(),
        "world": {
            "heightmap_size": size,
            "unit_size": 1,
            "sector_size": 32,
            "heightmap_z_ratio": 0.015625,
            "max_height": 1024,
            "height_profile": height_profile,
            "ocean_water_level": -100,
        },
        "terrain": {
            "biome": biome,
            "diffuse_rgba": _terrain_color(biome),
            "height_rgba": [128, 128, 0, 0],
            "tile_resolution": 512,
            "tile_count_x": tile_count,
            "tile_count_y": tile_count,
        },
        "lighting": {
            "preset": "%ENGINE%/EngineAssets/Shading/default.env",
            "time_label": time_label,
            "time_hour": time_hour,
            "sun_rotation": 240,
            "sun_height": 80 if time_hour == 12 else 32 if time_hour in (6, 18) else 16,
            "sun_vector": "-0.51961529,-0.29999986,-0.79999995",
        },
        "spawn": {
            "mode": "center_fallback",
            "position": [center, center, 42],
        },
        "level_paths": {
            "level_root": f"Assets/levels/{slug}",
            "level_file": f"Assets/levels/{slug}/{slug}.level",
            "cryasset_file": f"Assets/levels/{slug}.level.cryasset",
        },
        "source_context": {
            "docs": [
                "docs/terrain.md",
                "docs/textures.md",
                "docs/lighting.md",
                "docs/lod.md",
            ],
            "memory": [
                "memory/terrain.json",
                "memory/textures.json",
                "memory/lighting.json",
                "memory/lod.json",
            ],
            "project_root": project_root.as_posix(),
        },
    }


def build_prompt_pack(request: dict) -> str:
    return "\n".join(
        [
            "# CRYENGINE Asset Prompt Pack",
            "",
            f"Asset kind: {request['asset_kind']}",
            f"Prompt: {request['natural_language_prompt']}",
            "",
            "Return strict JSON matching this shape:",
            "{",
            '  "asset_kind": "level",',
            '  "slug": "kebab-case-package-name",',
            '  "display_name": "Human Title",',
            '  "summary": "short summary",',
            '  "world": {"heightmap_size": 512|1024|2048, "unit_size": 1, "sector_size": 32, "heightmap_z_ratio": 0.015625, "max_height": 1024, "height_profile": "flat|gentle|hilly|mountainous", "ocean_water_level": -100},',
            '  "terrain": {"biome": "desert|forest|snow|urban|temperate|...", "diffuse_rgba": [r,g,b,a], "height_rgba": [r,g,b,a], "tile_resolution": 512, "tile_count_x": 2|4|8, "tile_count_y": 2|4|8},',
            '  "lighting": {"preset": "%ENGINE%/EngineAssets/Shading/default.env", "time_label": "dawn|noon|dusk|night", "time_hour": 0-24, "sun_rotation": 0-360, "sun_height": 0-90, "sun_vector": "x,y,z"},',
            '  "spawn": {"mode": "center_fallback", "position": [x,y,z]}',
            "}",
            "",
            "Hard constraints:",
            "- Output paths must be relative to Assets/ and CRYENGINE conventions.",
            "- Levels must be publishable into Assets/levels/<slug>/.",
            "- Use %ENGINE%/EngineAssets/Shading/default.env unless explicitly overridden.",
            "- Terrain texture output must be valid and non-empty.",
            "- Spawn must be safe even when no Sandbox-authored spawn entities exist.",
        ]
    )

