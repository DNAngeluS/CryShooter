"""PNG reader for plasmid_assets (ported from the P0(f) spike; logic unchanged).

read_png(path) returns (width, height, rgba bytes) for any non-animated PNG: gray, palette (+tRNS),
gray+alpha, RGB or RGBA, bit depth 1..16, non-interlaced or Adam7. Stdlib only.
"""

import array
import itertools
import struct
import zlib

_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))  # x0, y0, dx, dy


def _unfilter(raw, pos, w, h, bits_pp):
    """Undo PNG scanline filters for a w x h (sub)image; returns (rows, new_pos)."""
    stride, bpp = (w * bits_pp + 7) // 8, max(1, bits_pp // 8)
    rows, prev = [], bytearray(stride)
    for _ in range(h):
        ft, line = raw[pos], bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ft == 1:
            for c in range(bpp):
                line[c::bpp] = bytes(itertools.accumulate(line[c::bpp], lambda x, y: (x + y) & 255))
        elif ft == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif ft in (3, 4):
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                if ft == 3:
                    line[i] = (line[i] + ((a + b) >> 1)) & 255
                else:
                    c = prev[i - bpp] if i >= bpp else 0
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        elif ft != 0:
            raise ValueError("bad PNG filter type %d" % ft)
        rows.append(line)
        prev = line
    return rows, pos


def read_png(path):
    """Return (width, height, rgba bytes) for any non-animated PNG: gray / palette (+tRNS) / gray+alpha / RGB / RGBA,
    bit depth 1..16 (16 bit keeps the high byte), non-interlaced or Adam7. A tRNS colour key on gray/RGB images is ignored."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr, plte, trns = 8, b"", None, b"", b""
    while pos < len(data):
        n, typ = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
        elif typ == b"PLTE":
            plte = body
        elif typ == b"tRNS":
            trns = body
        pos += 12 + n
    w, h, depth, ctype, _c, _f, interlace = ihdr
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if chans is None or depth not in (1, 2, 4, 8, 16) or (ctype == 3 and not plte):
        raise ValueError("unsupported PNG (colour type %d, depth %d)" % (ctype, depth))
    bits_pp = chans * depth
    raw = zlib.decompress(idat)
    out = bytearray(w * h * 4)

    def put(x, y, row, i):
        """Store pixel i of a decoded scanline at (x, y) as RGBA."""
        if depth == 8:
            v = row[i * chans:(i + 1) * chans]
        elif depth == 16:
            v = row[i * chans * 2:(i + 1) * chans * 2:2]
        else:
            bit = i * depth
            v = [(row[bit >> 3] >> (8 - depth - (bit & 7))) & ((1 << depth) - 1)]
        if ctype == 3:
            k = v[0]
            rgba = plte[k * 3:k * 3 + 3] + bytes([trns[k] if k < len(trns) else 255])
        elif ctype == 0:
            g = v[0] * 255 // ((1 << depth) - 1) if depth < 8 else v[0]
            rgba = bytes((g, g, g, 255))
        elif ctype == 4:
            rgba = bytes((v[0], v[0], v[0], v[1]))
        else:
            rgba = bytes(v[:3]) + (bytes([v[3]]) if ctype == 6 else b"\xff")
        o = (y * w + x) * 4
        out[o:o + 4] = rgba

    if not interlace and depth == 8 and ctype in (2, 6):  # common case, vectorised
        rows, _ = _unfilter(raw, 0, w, h, bits_pp)
        flat = b"".join(rows)
        for c in range(3):
            out[c::4] = flat[c::chans]
        out[3::4] = flat[3::4] if ctype == 6 else b"\xff" * (w * h)
    elif not interlace:
        rows, _ = _unfilter(raw, 0, w, h, bits_pp)
        for y, row in enumerate(rows):
            for x in range(w):
                put(x, y, row, x)
    else:
        pos = 0
        for x0, y0, dx, dy in _ADAM7:
            pw, ph = (w - x0 + dx - 1) // dx, (h - y0 + dy - 1) // dy
            if pw <= 0 or ph <= 0:
                continue
            rows, pos = _unfilter(raw, pos, pw, ph, bits_pp)
            for j, row in enumerate(rows):
                for i in range(pw):
                    put(x0 + i * dx, y0 + j * dy, row, i)
    return w, h, bytes(out)


def read_png_gray(path):
    """Return (width, height, bit_depth, samples) for a non-animated gray PNG (colour type 0, depth 1, 2, 4, 8 or
    16, non-interlaced or Adam7). samples is an array('H') of the raw sample values (0 .. 2**bit_depth - 1), row-major.
    Unlike read_png, 16 bit samples are kept in full. Any other colour type raises ValueError. Used for heightmaps."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n, typ = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat += body
        pos += 12 + n
    if ihdr is None:
        raise ValueError("PNG has no IHDR chunk")
    w, h, depth, ctype, _c, _f, interlace = ihdr
    if ctype != 0 or depth not in (1, 2, 4, 8, 16):
        raise ValueError("not a gray PNG (colour type %d, depth %d)" % (ctype, depth))
    raw = zlib.decompress(idat)
    out = array.array("H", bytes(2 * w * h))

    def samples(row, count):
        if depth == 16:
            return [(row[2 * i] << 8) | row[2 * i + 1] for i in range(count)]
        if depth == 8:
            return list(row[:count])
        mask = (1 << depth) - 1
        return [(row[(i * depth) >> 3] >> (8 - depth - ((i * depth) & 7))) & mask for i in range(count)]

    if not interlace:
        rows, _ = _unfilter(raw, 0, w, h, depth)
        for y, row in enumerate(rows):
            out[y * w:(y + 1) * w] = array.array("H", samples(row, w))
    else:
        pos = 0
        for x0, y0, dx, dy in _ADAM7:
            pw, ph = (w - x0 + dx - 1) // dx, (h - y0 + dy - 1) // dy
            if pw <= 0 or ph <= 0:
                continue
            rows, pos = _unfilter(raw, pos, pw, ph, depth)
            for j, row in enumerate(rows):
                for i, v in enumerate(samples(row, pw)):
                    out[(y0 + j * dy) * w + x0 + i * dx] = v
    return w, h, depth, out
