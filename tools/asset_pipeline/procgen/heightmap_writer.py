from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

# Verified against golden templates (512 and 1024 sizes)
_PREFIX_BY_SIZE: dict[int, bytes] = {
    512:  b'\xff\x5a\x03',
    1024: b'\xff\x5d\x03',
    2048: b'\xff\x60\x03',  # extrapolated pattern
}

_XML_TEMPLATE = (
    '<Heightmap Width="{size}" Height="{size}" UnitSize="2" '
    'WaterLevel="{water_level}" '
    'HeightRange="{max_height}" '
    'Flags="0" />'
)


def write_heightmap_dat(
    path: Path,
    heights_uint16: np.ndarray,
    *,
    max_height_m: float = 1024.0,
    water_level: int = 16,
) -> None:
    """Write a CRYENGINE 5.6 heightmap.dat from a uint16 numpy array.

    heights_uint16: shape (N, N), dtype uint16, row-major (Y, X).
    Values are pre-encoded: uint16 = int(meters / max_height_m * 65535).
    """
    size = heights_uint16.shape[0]
    if heights_uint16.shape != (size, size):
        raise ValueError(f"Heightmap must be square, got {heights_uint16.shape}")
    if size not in _PREFIX_BY_SIZE:
        raise ValueError(f"Unsupported heightmap size: {size}. Supported: {sorted(_PREFIX_BY_SIZE)}")

    xml_header = _XML_TEMPLATE.format(
        size=size,
        water_level=water_level,
        max_height=int(max_height_m),
    ).encode("utf-8")

    height_bytes = heights_uint16.astype("<u2").tobytes()

    # Chunk 0: HeightmapDataW — N*N uint16 LE
    chunk0_name = b"HeightmapDataW\x00"
    chunk0_data = height_bytes
    chunk0 = chunk0_name + struct.pack("<I", len(chunk0_data)) + chunk0_data

    # Chunks 1–2: empty (vegetationmap / layerid pattern from templates)
    chunk1_name = b"VegetationMap\x00"
    chunk1 = chunk1_name + struct.pack("<I", 0)

    chunk2_name = b"LayerId\x00"
    chunk2 = chunk2_name + struct.pack("<I", 0)

    prefix = _PREFIX_BY_SIZE[size]
    chunk_count = struct.pack("<I", 3)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(prefix)
        fh.write(xml_header)
        fh.write(b"\n")
        fh.write(chunk_count)
        fh.write(chunk0)
        fh.write(chunk1)
        fh.write(chunk2)


def flat_heightmap(size: int, elevation_m: float, max_height_m: float = 1024.0) -> np.ndarray:
    """Return a flat uint16 heightmap array at the given elevation."""
    value = int(elevation_m / max_height_m * 65535)
    value = max(0, min(65535, value))
    return np.full((size, size), value, dtype=np.uint16)
