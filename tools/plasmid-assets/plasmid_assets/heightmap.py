"""Heightmap sources and the heightmap.dat writer (stdlib port of the FPS heightmap_writer and flat_heightmap).

A heightmap is an array('H') of size*size unsigned 16 bit samples, row-major (index = y * size + x). A sample maps to
metres as sample * max_height_m / 65535. Sources:
  from_png(path)            8 bit gray samples are scaled to 16 bit (v * 257); 16 bit samples are kept in full.
  flat(size, z_m)           constant height, the FPS flat_heightmap formula.
  hills(seed, size, ...)    deterministic value noise, integer hashes only (no random module, no numpy). Not
                            parity-bound: the FPS code has no equivalent.

heightmap.dat header: the FPS writer has the header only for sizes 512, 1024 and 2048 (verified against the golden
templates). Other sizes raise ValueError rather than guess the prefix bytes.
"""
from __future__ import annotations

import array
import struct
import sys
from pathlib import Path

from .png import read_png_gray

HEIGHTMAP_PREFIX = {
    512: b"\xff\x5a\x03",
    1024: b"\xff\x5d\x03",
    2048: b"\xff\x60\x03",  # extrapolated pattern, as in the FPS writer
}
HEIGHTMAP_XML = ('<Heightmap Width="{size}" Height="{size}" UnitSize="2" WaterLevel="{water_level}" '
                 'HeightRange="{max_height}" Flags="0" />')  # UnitSize is fixed at 2 in the FPS writer; kept for parity
DEFAULT_MAX_HEIGHT_M = 1024.0
DEFAULT_WATER_LEVEL = 16


def _check_size(heights, size: int) -> None:
    if len(heights) != size * size:
        raise ValueError(f"heightmap must have {size * size} samples for size {size}, got {len(heights)}")


def heightmap_dat_bytes(heights, size: int, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M,
                        water_level: int = DEFAULT_WATER_LEVEL) -> bytes:
    """The heightmap.dat file bytes for an array('H') heightmap of `size` x `size` samples."""
    if size not in HEIGHTMAP_PREFIX:
        raise ValueError(f"Unsupported heightmap size: {size}. Supported: {sorted(HEIGHTMAP_PREFIX)}")
    _check_size(heights, size)
    xml = HEIGHTMAP_XML.format(size=size, water_level=water_level, max_height=int(max_height_m)).encode("utf-8")
    samples = array.array("H", heights)
    if sys.byteorder == "big":
        samples.byteswap()  # the file is little-endian
    body = samples.tobytes()
    chunk0 = b"HeightmapDataW\x00" + struct.pack("<I", len(body)) + body
    chunk1 = b"VegetationMap\x00" + struct.pack("<I", 0)
    chunk2 = b"LayerId\x00" + struct.pack("<I", 0)
    return HEIGHTMAP_PREFIX[size] + xml + b"\n" + struct.pack("<I", 3) + chunk0 + chunk1 + chunk2


def write_heightmap_dat(path, heights, size: int, **kw) -> None:
    data = heightmap_dat_bytes(heights, size, **kw)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def flat(size: int, z_m: float, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M) -> array.array:
    """Constant heightmap at z_m metres (FPS flat_heightmap: int(z / max * 65535), clamped to 0..65535)."""
    value = max(0, min(65535, int(z_m / max_height_m * 65535)))
    return array.array("H", [value]) * (size * size)


def from_png(path) -> tuple[int, array.array]:
    """Read a square gray PNG (8 or 16 bit, or 1, 2, 4 bit) as a heightmap. Returns (size, samples)."""
    width, height, depth, values = read_png_gray(path)
    if width != height:
        raise ValueError(f"heightmap PNG must be square, got {width}x{height}")
    if depth == 16:
        return width, values
    top = (1 << depth) - 1
    return width, array.array("H", [v * 65535 // top for v in values])


_M64 = 0xFFFFFFFFFFFFFFFF


def _lattice(ix: int, iy: int, seed: int, octave: int) -> float:
    """Integer hash of a lattice point to [0, 1). Only integer arithmetic, so the result is the same everywhere."""
    h = (ix * 0x27D4EB2D + iy * 0x165667B1 + seed * 0x9E3779B97F4A7C15 + octave * 0x85EBCA6B) & _M64
    h ^= h >> 29
    h = (h * 0xBF58476D1CE4E5B9) & _M64
    h ^= h >> 32
    h = (h * 0x94D049BB133111EB) & _M64
    h ^= h >> 29
    return (h >> 11) / float(1 << 53)


def hills(seed: int, size: int, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M, base_m: float = 16.0,
          relief_m: float = 240.0, cell: int | None = None, octaves: int = 4) -> array.array:
    """Deterministic rolling terrain: 4-octave value noise (smoothstep interpolation), scaled to base_m + relief_m * v
    metres, then encoded as the 16 bit heightmap for max_height_m. Same seed and size give the same samples on every
    run and every Python version (float ops are IEEE double; no random module, no numpy)."""
    if size <= 0:
        raise ValueError("size must be positive")
    seed = int(seed)
    cell = int(cell) if cell else max(4, size // 4)
    levels = []
    for o in range(octaves):
        c = max(1, cell >> o)
        n = size // c + 2
        grid = [[_lattice(ix, iy, seed, o) for ix in range(n)] for iy in range(n)]
        # per-column and per-row lattice index and smoothstep weight, computed once per octave
        cols = []
        for x in range(size):
            ix, rx = divmod(x, c)
            t = rx / c
            cols.append((ix, t * t * (3 - 2 * t)))
        levels.append((c, grid, cols))
    amp = [0.5 ** o for o in range(octaves)]
    total = sum(amp)
    out = array.array("H", [0]) * (size * size)
    for y in range(size):
        acc = [0.0] * size
        for o, (c, grid, cols) in enumerate(levels):
            iy, ry = divmod(y, c)
            ty = ry / c
            sy = ty * ty * (3 - 2 * ty)
            r0, r1 = grid[iy], grid[iy + 1]
            a_o = amp[o]
            for x in range(size):
                ix, sx = cols[x]
                top = r0[ix] + (r0[ix + 1] - r0[ix]) * sx
                bot = r1[ix] + (r1[ix + 1] - r1[ix]) * sx
                acc[x] += a_o * (top + (bot - top) * sy)
        row = y * size
        for x in range(size):
            v = acc[x] / total
            h_m = base_m + relief_m * v
            u = int(round(h_m / max_height_m * 65535.0))
            out[row + x] = 0 if u < 0 else (65535 if u > 65535 else u)
    return out


def hills_u_at(seed: int, size: int, x: int, y: int, *, max_height_m: float = DEFAULT_MAX_HEIGHT_M,
               base_m: float = 16.0, relief_m: float = 240.0, cell: int | None = None, octaves: int = 4) -> int:
    """One sample of hills(seed, size, ...) with the same arithmetic in the same order, so hills_u_at(...) equals
    hills(...)[y * size + x] exactly. Used by terrain-sample to read a few points without the whole map."""
    seed = int(seed)
    cell = int(cell) if cell else max(4, size // 4)
    acc = 0.0
    total = sum(0.5 ** o for o in range(octaves))
    for o in range(octaves):
        c = max(1, cell >> o)
        ix, rx = divmod(x, c)
        iy, ry = divmod(y, c)
        tx = rx / c
        sx = tx * tx * (3 - 2 * tx)
        ty = ry / c
        sy = ty * ty * (3 - 2 * ty)
        r0 = (_lattice(ix, iy, seed, o), _lattice(ix + 1, iy, seed, o))
        r1 = (_lattice(ix, iy + 1, seed, o), _lattice(ix + 1, iy + 1, seed, o))
        top = r0[0] + (r0[1] - r0[0]) * sx
        bot = r1[0] + (r1[1] - r1[0]) * sx
        acc += (0.5 ** o) * (top + (bot - top) * sy)
    v = acc / total
    h_m = base_m + relief_m * v
    u = int(round(h_m / max_height_m * 65535.0))
    return 0 if u < 0 else (65535 if u > 65535 else u)
