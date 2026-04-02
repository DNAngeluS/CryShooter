from __future__ import annotations

import numpy as np

try:
    import noise as _noise_pkg
    _HAS_NOISE = True
except ImportError:
    _HAS_NOISE = False


def octave_noise_2d(
    width: int,
    height: int,
    *,
    octaves: int = 6,
    frequency: float = 0.003,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
    seed: int = 0,
    use_simplex: bool = True,
) -> np.ndarray:
    """Return a float32 array of shape (height, width) with values in [0, 1].

    Uses the `noise` package (C-accelerated simplex/Perlin) when available.
    Falls back to a numpy-native multi-frequency sine approximation otherwise.
    """
    if _HAS_NOISE:
        return _noise_pkg_noise(width, height, octaves=octaves, frequency=frequency,
                                persistence=persistence, lacunarity=lacunarity,
                                seed=seed, use_simplex=use_simplex)
    return _numpy_fallback_noise(width, height, octaves=octaves, frequency=frequency,
                                 persistence=persistence, lacunarity=lacunarity, seed=seed)


def _noise_pkg_noise(width, height, *, octaves, frequency, persistence, lacunarity, seed, use_simplex):
    fn = _noise_pkg.snoise2 if use_simplex else _noise_pkg.pnoise2
    xs = np.arange(width, dtype=np.float32) * frequency
    ys = np.arange(height, dtype=np.float32) * frequency
    out = np.empty((height, width), dtype=np.float32)
    for y in range(height):
        for x in range(width):
            out[y, x] = fn(xs[x], ys[y], octaves=octaves,
                           persistence=persistence, lacunarity=lacunarity,
                           base=seed & 0xFF)
    # snoise2 returns [-1, 1]; normalize to [0, 1]
    out = (out + 1.0) * 0.5
    return np.clip(out, 0.0, 1.0)


def _numpy_fallback_noise(width, height, *, octaves, frequency, persistence, lacunarity, seed):
    """Deterministic multi-octave sine noise — not perceptually Perlin but seeded and fast."""
    rng = np.random.default_rng(seed)
    xs = np.arange(width, dtype=np.float64)
    ys = np.arange(height, dtype=np.float64)
    xg, yg = np.meshgrid(xs, ys)
    out = np.zeros((height, width), dtype=np.float64)
    amp = 1.0
    freq = frequency
    norm = 0.0
    for _ in range(octaves):
        phase_x = rng.uniform(0, 2 * np.pi)
        phase_y = rng.uniform(0, 2 * np.pi)
        angle = rng.uniform(0, 2 * np.pi)
        out += amp * (
            np.sin(freq * (xg * np.cos(angle) + yg * np.sin(angle)) + phase_x) *
            np.cos(freq * (xg * np.sin(angle) - yg * np.cos(angle)) + phase_y)
        )
        norm += amp
        amp *= persistence
        freq *= lacunarity
    out = out / norm
    out = (out + 1.0) * 0.5
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def make_seeded_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)
