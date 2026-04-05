"""
dds_normalmap_fix.py — DXT1/BC1 → BC5/ATI2 normal-map texture converter
=========================================================================

CryEngine requires that any DDS texture whose filename ends with ``_ddn`` uses
a two-channel compressed format (``eTF_BC5U`` / FourCC ``ATI2``).  Engine assets
shipped with DXT1/BC1 (a three-channel colour format) trigger a

    [Warning] Wrong format 'Unknown' for normal map texture '..._ddn.dds'

at load time and fall back to the error texture, breaking surface normal detail
on water, glass, frost, and noise shaders.

This module converts in-place: reads the DXT1 DDS, decompresses it, re-encodes
the R and G channels (normal X and Y components) as BC5/ATI2, and writes the
result back.  Only ``struct`` and ``numpy`` are required; no external tools needed.

Public API
----------
    scan_dxt1_ddns(root)              → list[Path]
    convert_dxt1_to_bc5(path, ...)    → ConvertResult
    fix_engine_ddns(engine_dir, ...)  → list[ConvertResult]

CLI
---
    # Fix the five known broken engine assets
    python3 tools/asset_pipeline/dds_normalmap_fix.py \\
        --engine-dir /path/to/CRYENGINE

    # Fix an explicit list of files
    python3 tools/asset_pipeline/dds_normalmap_fix.py \\
        --files a_ddn.dds b_ddn.dds

    # Scan a directory tree and fix every DXT1 _ddn.dds found
    python3 tools/asset_pipeline/dds_normalmap_fix.py \\
        --scan /path/to/CRYENGINE/Engine

    # Dry-run: report what would change without writing anything
    python3 tools/asset_pipeline/dds_normalmap_fix.py \\
        --engine-dir /path/to/CRYENGINE --dry-run

Integration
-----------
Call ``fix_engine_ddns`` from the asset pipeline build step before launching the
engine, or add it as a post-install hook that runs once after a fresh engine
checkout.  See docs/dds_normal_map_format.md for the full rationale.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# DDS constants
# ---------------------------------------------------------------------------

_MAGIC           = b"DDS "
_DDPF_FOURCC     = 0x00000004
_FOURCC_DXT1     = struct.unpack("<I", b"DXT1")[0]
_FOURCC_ATI2     = struct.unpack("<I", b"ATI2")[0]

# DDS_HEADER flags
_DDSD_CAPS        = 0x00000001
_DDSD_HEIGHT      = 0x00000002
_DDSD_WIDTH       = 0x00000004
_DDSD_PIXELFORMAT = 0x00001000
_DDSD_MIPMAPCOUNT = 0x00020000
_DDSD_LINEARSIZE  = 0x00080000

# DDS_CAPS flags
_DDSCAPS_COMPLEX  = 0x00000008
_DDSCAPS_TEXTURE  = 0x00001000
_DDSCAPS_MIPMAP   = 0x00400000

# Offsets within the DDS file (after 4-byte magic)
# DDS_HEADER is 124 bytes; DDS_PIXELFORMAT starts at header offset 72 → file offset 80
_HDR_OFFSET       = 4       # start of DDS_HEADER
_PF_OFFSET        = 76      # start of DDS_PIXELFORMAT (file-absolute)
_DATA_OFFSET      = 128     # first byte of pixel data


# ---------------------------------------------------------------------------
# DDS header parsing helpers
# ---------------------------------------------------------------------------

def _read_header(raw: bytes) -> tuple[int, int, int, int]:
    """Return (width, height, mip_count, fourcc) from a DDS byte string."""
    if raw[:4] != _MAGIC:
        raise ValueError("Not a DDS file (bad magic)")
    # DDS_HEADER fields at file offsets 4…27
    _, _, h, w, _, _, mips = struct.unpack_from("<IIIIIII", raw, _HDR_OFFSET)
    # DDS_PIXELFORMAT.dwFourCC at file offset 84
    fourcc = struct.unpack_from("<I", raw, _PF_OFFSET + 8)[0]
    return w, h, mips, fourcc


def _build_dds_header(w: int, h: int, mips: int, top_size: int) -> bytes:
    """Build a 128-byte DDS header for a BC5/ATI2 mipmapped 2-D texture."""
    flags = _DDSD_CAPS | _DDSD_HEIGHT | _DDSD_WIDTH | _DDSD_PIXELFORMAT | _DDSD_LINEARSIZE | _DDSD_MIPMAPCOUNT
    caps  = _DDSCAPS_COMPLEX | _DDSCAPS_TEXTURE | _DDSCAPS_MIPMAP

    pixelformat = struct.pack(
        "<8I",
        32,              # dwSize  (always 32)
        _DDPF_FOURCC,    # dwFlags
        _FOURCC_ATI2,    # dwFourCC  → 'ATI2' = BC5U
        0, 0, 0, 0, 0,   # dwRGBBitCount + masks (unused for FourCC formats)
    )
    header = struct.pack("<7I", 124, flags, h, w, top_size, 0, mips)
    header += b"\x00" * 44           # dwReserved1[11]
    header += pixelformat
    header += struct.pack("<4I", caps, 0, 0, 0)   # dwCaps1-4
    header += b"\x00" * 4            # dwReserved2
    assert len(header) == 124
    return _MAGIC + header


# ---------------------------------------------------------------------------
# DXT1 / BC1 decoder
# ---------------------------------------------------------------------------

def _rgb565(v: int) -> tuple[int, int, int]:
    return (((v >> 11) & 0x1F) * 255 // 31,
            ((v >> 5)  & 0x3F) * 255 // 63,
            ( v        & 0x1F) * 255 // 31)


def _decode_dxt1_block(raw: bytes, off: int) -> np.ndarray:
    """Decode one 4×4 DXT1 block → (4,4,3) uint8 array."""
    c0, c1 = struct.unpack_from("<HH", raw, off)
    bits   = struct.unpack_from("<I",  raw, off + 4)[0]
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    if c0 > c1:
        palette = [(r0,g0,b0),(r1,g1,b1),
                   ((2*r0+r1)//3,(2*g0+g1)//3,(2*b0+b1)//3),
                   ((r0+2*r1)//3,(g0+2*g1)//3,(b0+2*b1)//3)]
    else:
        palette = [(r0,g0,b0),(r1,g1,b1),
                   ((r0+r1)//2,(g0+g1)//2,(b0+b1)//2),(0,0,0)]
    block = np.empty((4, 4, 3), dtype=np.uint8)
    for i in range(16):
        row, col = divmod(i, 4)
        block[row, col] = palette[(bits >> (i * 2)) & 3]
    return block


def _decompress_dxt1_mip(raw: bytes, off: int, w: int, h: int) -> tuple[np.ndarray, int]:
    """Decode one DXT1 mip level → (h,w,3) uint8, return updated offset."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    canvas = np.zeros((bh * 4, bw * 4, 3), dtype=np.uint8)
    for by in range(bh):
        for bx in range(bw):
            canvas[by*4:by*4+4, bx*4:bx*4+4] = _decode_dxt1_block(raw, off)
            off += 8
    return canvas[:h, :w, :], off


# ---------------------------------------------------------------------------
# BC4 / BC5 encoder
# ---------------------------------------------------------------------------

def _encode_bc4_block(ch: np.ndarray) -> bytes:
    """Encode one 4×4 single-channel uint8 block → 8-byte BC4 block.

    Uses the 8-value interpolation mode (alpha0 > alpha1) throughout, which
    covers the full 0-255 range without special 0/255 sentinels.
    """
    flat = ch.flatten().tolist()
    a0, a1 = max(flat), min(flat)   # a0 = max, a1 = min  →  8-value mode

    if a0 == a1:
        # Uniform block: index 0 selects a0 for all pixels.
        idx_bits = 0
    else:
        # Build the 8-entry interpolation palette.
        palette = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
        idx_bits = 0
        for i, v in enumerate(flat):
            best = min(range(8), key=lambda j, _v=v: abs(_v - palette[j]))
            idx_bits |= best << (i * 3)

    # Pack: 2 bytes for a0/a1, then 6 bytes of 3-bit indices (48 bits).
    return struct.pack("<BB", a0, a1) + struct.pack("<Q", idx_bits)[:6]


def _compress_bc5_mip(rg: np.ndarray) -> bytes:
    """Encode one mip level of a two-channel (R,G) image → BC5/ATI2 bytes.

    Args:
        rg: numpy array of shape (h, w, 2), dtype uint8, channels [X, Y].

    Returns:
        BC5 block data: (ceil(h/4) × ceil(w/4)) × 16 bytes.
    """
    h, w = rg.shape[:2]
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    # Pad to a block-aligned size before iterating.
    padded = np.zeros((bh * 4, bw * 4, 2), dtype=np.uint8)
    padded[:h, :w] = rg
    out = bytearray()
    for by in range(bh):
        for bx in range(bw):
            blk = padded[by*4:by*4+4, bx*4:bx*4+4]
            out += _encode_bc4_block(blk[:, :, 0])   # R channel → BC4 block 0
            out += _encode_bc4_block(blk[:, :, 1])   # G channel → BC4 block 1
    return bytes(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ConvertResult:
    path: Path
    width: int = 0
    height: int = 0
    mips: int = 0
    src_bytes: int = 0
    dst_bytes: int = 0
    skipped: bool = False
    dry_run: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def scan_dxt1_ddns(root: Path) -> list[Path]:
    """Return all ``*_ddn.dds`` files under *root* that are encoded as DXT1/BC1.

    This is a non-destructive scan; nothing is modified.
    """
    results: list[Path] = []
    for path in sorted(root.rglob("*_ddn.dds")):
        try:
            raw = path.read_bytes()
            _, _, _, fourcc = _read_header(raw)
            if fourcc == _FOURCC_DXT1:
                results.append(path)
        except Exception:
            pass
    return results


def convert_dxt1_to_bc5(
    path: Path,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> ConvertResult:
    """Convert a single DXT1 DDS normal-map file to BC5/ATI2 in place.

    Args:
        path:    Path to the ``.dds`` file.
        dry_run: If *True*, parse and validate but do not write any output.
        verbose: If *True*, print progress to stdout.

    Returns:
        A :class:`ConvertResult` describing what happened.
    """
    result = ConvertResult(path=path)
    try:
        raw = path.read_bytes()
        result.src_bytes = len(raw)

        w, h, mips, fourcc = _read_header(raw)
        result.width, result.height, result.mips = w, h, mips

        if fourcc == _FOURCC_ATI2:
            result.skipped = True
            if verbose:
                print(f"  skip (already ATI2): {path.name}")
            return result

        if fourcc != _FOURCC_DXT1:
            fourcc_str = struct.pack("<I", fourcc).decode("ascii", errors="replace")
            result.error = f"unexpected FourCC '{fourcc_str}' — only DXT1→BC5 conversion is supported"
            return result

        # Decode every mip level.
        off = _DATA_OFFSET
        mip_rg: list[np.ndarray] = []
        mw, mh = w, h
        for _ in range(mips):
            img, off = _decompress_dxt1_mip(raw, off, mw, mh)
            mip_rg.append(img[:, :, :2].copy())   # keep R (X) and G (Y) only
            mw, mh = max(1, mw // 2), max(1, mh // 2)

        # Re-encode as BC5.
        mip_blobs = [_compress_bc5_mip(rg) for rg in mip_rg]
        top_size  = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        out = _build_dds_header(w, h, mips, top_size)
        for blob in mip_blobs:
            out += blob

        result.dst_bytes = len(out)
        result.dry_run   = dry_run

        if not dry_run:
            path.write_bytes(out)

        if verbose:
            tag = "[dry-run] " if dry_run else ""
            print(
                f"  {tag}converted {path.name}: "
                f"{w}×{h} {mips}mips  "
                f"{result.src_bytes // 1024}KB → {result.dst_bytes // 1024}KB  (ATI2/BC5)"
            )

    except Exception as exc:
        result.error = str(exc)
        if verbose:
            print(f"  ERROR {path.name}: {exc}")

    return result


# Known broken engine normal-map textures (relative to Engine/EngineAssets/Textures/).
_ENGINE_DDN_ASSETS = [
    "perlinnoisenormal_ddn.dds",
    "oceanwaves_ddn.dds",
    "screenfrost_ddn.dds",
    "hex_ddn.dds",
    "glass_decalatlas_ddn.dds",
]


def fix_engine_ddns(
    engine_dir: Path,
    *,
    dry_run: bool = False,
    verbose: bool = True,
) -> list[ConvertResult]:
    """Fix the five known DXT1 normal-map textures in the engine asset tree.

    Args:
        engine_dir: Root of the CRYENGINE checkout (the directory that contains
                    the ``Engine/`` folder).
        dry_run:    Report what would change without writing files.
        verbose:    Print one line per file.

    Returns:
        One :class:`ConvertResult` per file processed.
    """
    tex_dir = engine_dir / "Engine" / "EngineAssets" / "Textures"
    results: list[ConvertResult] = []
    for name in _ENGINE_DDN_ASSETS:
        p = tex_dir / name
        if not p.exists():
            r = ConvertResult(path=p, error="file not found")
            results.append(r)
            if verbose:
                print(f"  missing: {p}")
            continue
        results.append(convert_dxt1_to_bc5(p, dry_run=dry_run, verbose=verbose))
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert DXT1/BC1 normal-map DDS files to BC5/ATI2 for CryEngine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--engine-dir", metavar="PATH",
        help="Root of the CRYENGINE checkout. Fixes the five known broken DDN assets.",
    )
    mode.add_argument(
        "--files", nargs="+", metavar="FILE",
        help="One or more explicit _ddn.dds paths to convert.",
    )
    mode.add_argument(
        "--scan", metavar="DIR",
        help="Recursively scan DIR and convert every DXT1 *_ddn.dds found.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing files.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-file output.")

    args = parser.parse_args()
    verbose = not args.quiet

    results: list[ConvertResult] = []

    if args.engine_dir:
        results = fix_engine_ddns(Path(args.engine_dir), dry_run=args.dry_run, verbose=verbose)

    elif args.files:
        for f in args.files:
            results.append(convert_dxt1_to_bc5(Path(f), dry_run=args.dry_run, verbose=verbose))

    elif args.scan:
        ddns = scan_dxt1_ddns(Path(args.scan))
        if verbose:
            print(f"Found {len(ddns)} DXT1 _ddn.dds file(s) under {args.scan}")
        for p in ddns:
            results.append(convert_dxt1_to_bc5(p, dry_run=args.dry_run, verbose=verbose))

    # Summary
    converted = sum(1 for r in results if r.ok and not r.skipped and not r.dry_run)
    dry_would = sum(1 for r in results if r.ok and not r.skipped and r.dry_run)
    skipped   = sum(1 for r in results if r.skipped)
    errors    = sum(1 for r in results if r.error)

    if verbose:
        print(
            f"\nDone: {converted} converted, "
            f"{dry_would} would convert (dry-run), "
            f"{skipped} skipped (already ATI2), "
            f"{errors} error(s)."
        )

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
