from __future__ import annotations

OPEN_SUBTYPES = {"forest", "desert", "tundra", "swamp", "savanna", "volcanic"}
INTERIOR_SUBTYPES = {"cave", "dungeon", "ship", "bunker", "sewer"}
STRUCTURED_SUBTYPES = {"castle", "arena", "fortress", "warehouse", "ruins"}

_KEYWORD_MAP: dict[str, tuple[str, str]] = {
    # open
    "forest": ("open", "forest"), "tree": ("open", "forest"), "woods": ("open", "forest"),
    "desert": ("open", "desert"), "sand": ("open", "desert"), "dune": ("open", "desert"),
    "tundra": ("open", "tundra"), "snow": ("open", "tundra"), "arctic": ("open", "tundra"),
    "swamp": ("open", "swamp"), "marsh": ("open", "swamp"),
    "savanna": ("open", "savanna"), "grassland": ("open", "savanna"),
    "volcanic": ("open", "volcanic"), "lava": ("open", "volcanic"),
    # interior
    "cave": ("interior", "cave"), "cavern": ("interior", "cave"), "grotto": ("interior", "cave"),
    "dungeon": ("interior", "dungeon"), "crypt": ("interior", "dungeon"),
    "ship": ("interior", "ship"), "spaceship": ("interior", "ship"), "vessel": ("interior", "ship"),
    "bunker": ("interior", "bunker"), "facility": ("interior", "bunker"),
    "sewer": ("interior", "sewer"), "tunnel": ("interior", "sewer"),
    # structured
    "castle": ("structured", "castle"), "keep": ("structured", "castle"),
    "arena": ("structured", "arena"), "colosseum": ("structured", "arena"),
    "fortress": ("structured", "fortress"), "fort": ("structured", "fortress"),
    "warehouse": ("structured", "warehouse"),
    "ruins": ("structured", "ruins"), "ruin": ("structured", "ruins"),
}

_NODE_TYPE_TO_CATEGORY = {
    "terrain_procgen": "open",
    "interior_procgen": "interior",
    "structured_procgen": "structured",
}

_CATEGORY_DEFAULT_SUBTYPE = {
    "open": "forest",
    "interior": "cave",
    "structured": "arena",
}


def classify_level(node_type: str, spec: dict) -> tuple[str, str]:
    """Return (category, subtype) from a procgen node type and its spec dict."""
    category = _NODE_TYPE_TO_CATEGORY.get(node_type)
    if category is None:
        raise ValueError(f"Unknown procgen node type: {node_type!r}")

    subtype = spec.get("subtype", "").lower().strip()
    if subtype:
        return category, subtype

    # Keyword scan fallback on summary or name
    text = (spec.get("summary", "") + " " + spec.get("name", "")).lower()
    for keyword, result in _KEYWORD_MAP.items():
        if keyword in text and result[0] == category:
            return result

    return category, _CATEGORY_DEFAULT_SUBTYPE[category]
