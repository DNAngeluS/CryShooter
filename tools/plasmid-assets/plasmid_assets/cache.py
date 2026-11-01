"""Opt-in content-hash cache for finished DDS files. Stdlib only.

Nothing is cached unless the caller passes a cache directory; there is no default location. A cache hit copies the
stored bytes to the destination, which are the bytes write_dds would have produced.

key()       sha256 over the PNG bytes and every input that changes the output: format, srgb, mips, persistent,
            trailer and __version__.
load()      returns the stored bytes only if they parse as a DDS of the expected length (header magic, CRYF stage
            word, mip sizes derived from the header, trailer when the request asks for one); otherwise None.
store()     writes to a temporary name in the cache directory and renames it into place with os.replace.
write_dds_cached() is the one entry point: same arguments and return value as dds.write_dds, plus cache_dir.
"""

import hashlib
import json
import os
import struct

from . import __version__
from . import dds as dds_mod
from .dds import CRYF_STAGE, DDPF_FOURCC, DXGI_BC5_SNORM, check_args, trailer_bytes, write_dds

_BLOCK_BYTES = {b"DXT1": 8, b"DXT5": 16, b"ATI2": 16}
_FILE_SUFFIX = ".dds"


def key(png_bytes, fmt, srgb, mips, persistent, trailer):
    meta = json.dumps({"fmt": fmt, "srgb": bool(srgb), "mips": mips, "persistent": persistent,
                       "trailer": bool(trailer), "version": __version__}, sort_keys=True).encode()
    h = hashlib.sha256()
    h.update(len(meta).to_bytes(8, "little"))
    h.update(meta)
    h.update(png_bytes)
    return h.hexdigest()


def _expected_len(data):
    """Length of a file write_dds wrote for this header, without the trailer; None if the header is not ours."""
    if len(data) < 128 or data[:4] != b"DDS ":
        return None
    size, _flags, h, w, _pitch, _depth, mips = struct.unpack_from("<7I", data, 4)
    if size != 124 or mips < 1 or w < 1 or h < 1:
        return None
    if struct.unpack_from("<I", data, 124)[0] != CRYF_STAGE:
        return None
    pf_flags = struct.unpack_from("<I", data, 80)[0]
    total = 128
    if pf_flags & DDPF_FOURCC and data[84:88] == b"DX10":
        if len(data) < 148 or struct.unpack_from("<I", data, 128)[0] != DXGI_BC5_SNORM:
            return None
        total = 148
    for i in range(mips):
        lw, lh = max(1, w >> i), max(1, h >> i)
        if pf_flags & DDPF_FOURCC:
            bsz = 16 if data[84:88] == b"DX10" else _BLOCK_BYTES.get(data[84:88])
            if bsz is None:
                return None
            total += max(1, (lw + 3) // 4) * max(1, (lh + 3) // 4) * bsz
        else:
            total += lw * lh * 4  # A8R8G8B8
    return total


def _valid(data, trailer):
    n = _expected_len(data)
    if n is None:
        return False
    if struct.unpack_from("<I", data, 36)[0] & dds_mod.EIF_ATTACHED_ALPHA:     # a `_ddna`: the attached image follows the mips
        if trailer or len(data) < n + 16 or data[n:n + 8] != b"CExtAttC":
            return False
        size = struct.unpack_from("<I", data, n + 8)[0]
        return len(data) == n + 12 + size + 4 and data[-4:] == b"CEnd"
    if trailer:
        tb = trailer_bytes()
        return len(data) == n + len(tb) and data[n:] == tb
    return len(data) == n


def load(cache_dir, k, trailer=False):
    try:
        with open(os.path.join(cache_dir, k + _FILE_SUFFIX), "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if _valid(data, trailer) else None


def _write_atomic(dst, data):
    tmp = "%s.%d.tmp" % (dst, os.getpid())  # same permissions as a plain open(); renamed only when complete
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def store(cache_dir, k, data):
    os.makedirs(cache_dir, exist_ok=True)
    _write_atomic(os.path.join(cache_dir, k + _FILE_SUFFIX), data)


def write_dds_cached(path, png_bytes, w, h, px, fmt, cache_dir, mips=0, trailer=False, allow_misnamed=False,
                     srgb=False, persistent=None, jobs=1):
    """dds.write_dds with an optional cache. cache_dir None means no cache. Returns (mip count, byte size)."""
    if cache_dir is None:
        return write_dds(path, w, h, px, fmt, mips, trailer, allow_misnamed, srgb, persistent, jobs)
    check_args(path, fmt, allow_misnamed, srgb)  # refused requests are refused on a hit too
    k = key(png_bytes, fmt, srgb, mips, persistent, trailer)
    data = load(cache_dir, k, trailer)
    if data is not None:
        _write_atomic(path, data)
        return struct.unpack_from("<I", data, 28)[0], len(data)
    n, size = write_dds(path, w, h, px, fmt, mips, trailer, allow_misnamed, srgb, persistent, jobs)
    with open(path, "rb") as f:
        store(cache_dir, k, f.read())
    return n, size


def write_lazy(path, parts, make, fmt, cache_dir, srgb=False, jobs=1):
    """A cached DDS whose pixels are expensive to compute: the key hashes `parts` (bytes: every source, every factor, a bake
    version), `make()` -> (w, h, rgba px, gloss bytes | None) runs only on a miss. Returns (width, height, mips, bytes)."""
    k = key(b"|".join(parts), fmt, srgb, 0, None, False)
    data = load(cache_dir, k) if cache_dir else None
    if data is not None:
        _write_atomic(path, data)
    else:
        w, h, px, gloss = make()
        write_dds(path, w, h, px, fmt, 0, False, False, srgb, None, jobs, gloss=gloss)
        with open(path, "rb") as f:
            data = f.read()
        if cache_dir:
            store(cache_dir, k, data)
    h, w, mips = struct.unpack_from("<I", data, 12)[0], struct.unpack_from("<I", data, 16)[0], struct.unpack_from("<I", data, 28)[0]
    return w, h, mips, len(data)
