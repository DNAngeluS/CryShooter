"""Environment-probe cube maps for plasmid_assets: a BC6H (unsigned half float) cube map DDS written without the resource compiler.

The engine's tiled shading keeps every probe in a BC6UH texture-array atlas and rejects other formats (renderer log:
"TiledShading: Unsupported texture format ... it has to be equal to the tile-atlas (F:BC6UH)"). The specular map must be at least 256
pixels square with 7 mips (256 down to 4), the diffuse (irradiance) map at least 32 pixels square with one mip. Both are what the
GameSDK probe files look like. `write_probe` writes a pair `<name>_cm.dds` and `<name>_cm_diff.dds` for a sky / horizon / ground
gradient. Block encoder: BC6H mode 11 (one region, two 10-bit endpoints, 4-bit indices); the unquantise and interpolation
arithmetic follows the format description, decode_bc6h_mode11 is the matching decoder the tests use. Stdlib only.
"""

import bisect
import math
import struct
from pathlib import Path

WEIGHTS = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)
SPEC_SIZE, DIFF_SIZE = 256, 32
DXGI_BC6H_UF16 = 95
# Cube face order in a DDS: +X -X +Y -Y +Z -Z. The engine samples probes in world axes (seen in frames: the crate side facing +X takes
# face 0, +Y takes face 2), so +Z, face 4, is the sky.
FACE_UP, FACE_DOWN = 4, 5
HALF_MAX_ENDPOINT = 1000          # 10-bit code; 1023 would decode to 0xFFFF (infinity)


_FLOAT = [struct.unpack("<e", struct.pack("<H", h))[0] for h in range(0x8000)]   # unsigned half bits -> float (NaN above 0x7C00 unused)


def _half(v: float) -> int:
    return struct.unpack("<H", struct.pack("<e", min(max(v, 0.0), 60000.0)))[0]


def _unq(e: int) -> int:
    """10-bit endpoint code -> 16-bit value (unsigned mode)."""
    return 0 if e == 0 else 0xFFFF if e == 1023 else ((e << 16) + 0x8000) >> 10


def _fin(v: int) -> int:
    return (v * 31) >> 6


def _code(h: int) -> int:
    """Half-float bits -> nearest 10-bit endpoint code (inverse of _unq then _fin, up to rounding)."""
    return max(0, min(HALF_MAX_ENDPOINT, int(round((h - 15.5) / 31.0)))) if h else 0


def encode_bc6h_block(pixels) -> bytes:
    """16 (r, g, b) float pixels in raster order -> one 16-byte BC6H block (mode 11)."""
    halves = [(_half(r), _half(g), _half(b)) for r, g, b in pixels]
    lum = [h[0] + 2 * h[1] + h[2] for h in halves]
    lo, hi = halves[lum.index(min(lum))], halves[lum.index(max(lum))]
    e0 = [_code(c) for c in lo]
    e1 = [_code(c) for c in hi]
    a = [_unq(c) for c in e0]
    b = [_unq(c) for c in e1]
    d = [b[i] - a[i] for i in range(3)]
    dd = sum(x * x for x in d)
    # the format interpolates half-float bit patterns, which are not linear in value: take the palette as the decoder will
    # build it and pick, around the straight projection, the entry nearest in float space
    palette = [[_FLOAT[_fin((a[i] * (64 - w) + b[i] * w + 32) >> 6)] for i in range(3)] for w in WEIGHTS]
    idx = []
    for (r, g, bl), h in zip(pixels, halves):
        j = 0
        if dd:
            t = sum((h[i] * 64.0 / 31.0 - a[i]) * d[i] for i in range(3)) / dd * 64.0
            j = bisect.bisect_left(WEIGHTS, min(max(t, 0.0), 64.0))
            j = min(j, 15)
        best, best_err = j, None
        for k in range(max(0, j - 2), min(16, j + 3)):
            pr, pg, pb = palette[k]
            err = (pr - r) ** 2 + (pg - g) ** 2 + (pb - bl) ** 2
            if best_err is None or err < best_err:
                best, best_err = k, err
        idx.append(best)
    if idx[0] >= 8:                       # the anchor index has 3 bits: swap the endpoints and mirror the indices
        e0, e1 = e1, e0
        idx = [15 - i for i in idx]
    bits = 0b00011
    pos = 5
    for v in (*e0, *e1):
        bits |= v << pos
        pos += 10
    for n, i in enumerate(idx):
        bits |= i << pos
        pos += 3 if n == 0 else 4
    assert pos == 128
    return bits.to_bytes(16, "little")


def decode_bc6h_mode11(block: bytes):
    """Inverse of encode_bc6h_block: 16 (r, g, b) half-float bit triples. Raises ValueError for any other mode."""
    bits = int.from_bytes(block, "little")
    if bits & 0x1F != 0b00011:
        raise ValueError("not a BC6H mode 11 block")
    vals = [(bits >> (5 + 10 * k)) & 0x3FF for k in range(6)]
    a, b = [_unq(v) for v in vals[:3]], [_unq(v) for v in vals[3:]]
    pos, out = 65, []
    for n in range(16):
        width = 3 if n == 0 else 4
        w = WEIGHTS[(bits >> pos) & ((1 << width) - 1)]
        pos += width
        out.append(tuple(_fin((a[i] * (64 - w) + b[i] * w + 32) >> 6) for i in range(3)))
    return out


def _dds_header(size: int, mips: int) -> bytes:
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x20000 if mips > 1 else 0)
    caps = 0x8 | 0x1000 | (0x400000 if mips > 1 else 0)
    head = b"DDS " + struct.pack("<7I", 124, flags, size, size, 0, 0, mips) + bytes(44)
    head += struct.pack("<2I4s5I", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    head += struct.pack("<5I", caps, 0xFE00, 0, 0, 0)
    return head + struct.pack("<5I", DXGI_BC6H_UF16, 3, 4, 6, 0)       # 2D, cube, array size 6


def face_direction(face: int, u: float, v: float):
    """Direction for texel coordinates u, v in [-1, 1] (u to the right, v down) on a DDS cube face; X, Y, Z are the cube-space axes."""
    return [(1, -v, -u), (-1, -v, u), (u, 1, v), (u, -1, -v), (u, -v, 1), (-u, -v, -1)][face]


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def up_component(direction) -> float:
    """Height of a world-axis direction (+1 straight up, +Z)."""
    return _norm(direction)[2]


def gradient(up: float, sky, horizon, ground):
    """Environment colour for a direction whose height is `up` (-1 straight down to +1 straight up)."""
    if up >= 0:
        t = up ** 0.6
        return tuple(horizon[i] + (sky[i] - horizon[i]) * t for i in range(3))
    t = (-up) ** 0.6
    return tuple(horizon[i] + (ground[i] - horizon[i]) * t for i in range(3))


def _face_pixels(face, size, env):
    px = []
    for y in range(size):
        for x in range(size):
            px.append(env(face_direction(face, 2 * (x + 0.5) / size - 1, 2 * (y + 0.5) / size - 1)))
    return px


def _encode_surface(px, size) -> bytes:
    out = bytearray()
    for by in range(0, size, 4):
        for bx in range(0, size, 4):
            out += encode_bc6h_block([px[(by + j) * size + bx + i] for j in range(4) for i in range(4)])
    return bytes(out)


def build_cubemap(env, size: int, mips: int) -> bytes:
    """BC6UH cube map DDS: env(direction) -> (r, g, b), sampled at every mip resolution."""
    body = bytearray()
    for face in range(6):
        for m in range(mips):
            s = size >> m
            body += _encode_surface(_face_pixels(face, s, env), s)
    return _dds_header(size, mips) + bytes(body)


def _irradiance_env(env, samples=192):
    """Cosine-weighted average of env over the sphere, as a function of direction (the diffuse probe)."""
    pts = []
    for i in range(samples):                                   # Fibonacci sphere
        y = 1 - 2 * (i + 0.5) / samples            # y is the height here
        r = math.sqrt(1 - y * y)
        a = i * math.pi * (3 - math.sqrt(5))
        pts.append(((math.cos(a) * r, math.sin(a) * r, y)))
    cols = [env(p) for p in pts]

    def irradiance(direction):
        n = _norm(direction)
        acc, wsum = [0.0, 0.0, 0.0], 0.0
        for p, c in zip(pts, cols):
            w = max(0.0, n[0] * p[0] + n[1] * p[1] + n[2] * p[2])
            wsum += w
            for k in range(3):
                acc[k] += c[k] * w
        return tuple(a / wsum for a in acc)
    return irradiance


def write_probe(out_dir, name: str, sky=(0.35, 0.5, 0.8), horizon=(0.7, 0.75, 0.8), ground=(0.25, 0.22, 0.18),
                size: int = SPEC_SIZE) -> list[str]:
    """Write <name>_cm.dds (specular, `size` square, mips down to 4) and <name>_cm_diff.dds (diffuse, 32 square); returns the paths."""
    if size < SPEC_SIZE or size & (size - 1):
        raise ValueError(f"size must be a power of two of at least {SPEC_SIZE}")
    for label, colour in (("sky", sky), ("horizon", horizon), ("ground", ground)):
        if len(colour) != 3 or not all(isinstance(c, (int, float)) and 0 <= c <= 100 for c in colour):
            raise ValueError(f"{label} must be three numbers between 0 and 100")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("name must be a plain file stem")

    def env(direction):
        return gradient(up_component(direction), sky, horizon, ground)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec, diff = out / f"{name}_cm.dds", out / f"{name}_cm_diff.dds"
    spec.write_bytes(build_cubemap(env, size, size.bit_length() - 2))   # 256 -> 7 mips (256 ... 4)
    diff.write_bytes(build_cubemap(_irradiance_env(env), DIFF_SIZE, 1))
    return [str(spec), str(diff)]
