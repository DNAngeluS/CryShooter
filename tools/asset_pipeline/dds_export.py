"""dds_export.py — runtime DDS for generated textures.

The engine's material loader has no PNG reader ("Unsupported texture extension 'png'"), so every PNG master the pipeline
writes gets a sibling `.dds` that the `.mtl` files reference. Conversion uses the vendored `tools/cry-assets` (tag in its
`.vendored-from`), with the parameters `cry_assets gltf2cgf` uses for colour textures (engine-verified): BC1 for opaque
images, BC3 when there is alpha, sRGB (the CRYF header block sets EIF_SRGBRead), full mip chain, all mips persistent.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VENDORED = Path(__file__).resolve().parents[1] / "cry-assets"
if str(_VENDORED) not in sys.path:
    sys.path.insert(0, str(_VENDORED))

from cry_assets.dds import write_dds  # noqa: E402
from cry_assets.gltf import png_has_alpha  # noqa: E402
from cry_assets.png import read_png  # noqa: E402


def png_to_runtime_dds(png_path: Path, dds_path: Path | None = None) -> Path:
    """Write the sRGB colour DDS for `png_path` (next to it unless `dds_path` is given) and return its path."""
    png_path = Path(png_path)
    dds_path = Path(dds_path) if dds_path else png_path.with_suffix(".dds")
    width, height, pixels = read_png(str(png_path))
    fmt = "bc3" if png_has_alpha(str(png_path)) else "bc1"
    write_dds(str(dds_path), width, height, pixels, fmt, 0, srgb=True)
    return dds_path
