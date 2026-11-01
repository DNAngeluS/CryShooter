"""DDS writer and block decoders for plasmid_assets (ported from the P0(f) spike; logic unchanged).

write_dds(path, w, h, px, fmt, ...) writes a monolithic DDS with a legacy 128-byte header from RGBA
pixels. Formats: rgba8, bc1, bc3, bc5. decode_mip0 is an independent decoder used by the tests.
Stdlib only.
"""

import math
import os
import struct

DDSD = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000  # CAPS HEIGHT WIDTH PIXELFORMAT MIPMAPCOUNT
DDSD_PITCH, DDSD_LINEARSIZE = 0x8, 0x80000
EIF_SRGBREAD = 0x800          # ImageExtensionHelper.h:196
BC5_FORMATS = ("bc5", "bc5s")  # bc5 = unsigned ATI2 (kept for byte parity with the FPS writer); bc5s = DX10 BC5_SNORM, what the engine reads as a normal map
DXGI_BC5_SNORM = 84
DXGI_BC4_UNORM = 80
EIF_ATTACHED_ALPHA = 0x400      # ImageExtensionHelper.h:195; the attached image (gloss) follows the mip chain in an AttC chunk
CRYF_STAGE = 0x43525946       # 'CRYF' multi-char constant, stored little-endian
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB = 0x1, 0x4, 0x40
CAPS = 0x8 | 0x1000 | 0x400000  # COMPLEX TEXTURE MIPMAP

_S2L = [((i / 255.0) / 12.92 if i / 255.0 <= 0.04045 else ((i / 255.0 + 0.055) / 1.055) ** 2.4) for i in range(256)]


def _l2s(v):
    v = 0.0 if v <= 0 else 1.0 if v >= 1 else v
    return int(round(255 * (v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)))


def box_down(px, w, h, srgb=False):
    """2x2 box filter. srgb=True averages RGB in linear light (what the sRGB read of the texture implies); alpha is linear."""
    nw, nh = max(1, w // 2), max(1, h // 2)
    out = bytearray()
    for y in range(nh):
        for x in range(nw):
            acc = [0, 0, 0, 0]
            for dy in (0, 1):
                for dx in (0, 1):
                    sx, sy = min(w - 1, x * 2 + dx), min(h - 1, y * 2 + dy)
                    o = (sy * w + sx) * 4
                    for k in range(4):
                        acc[k] += _S2L[px[o + k]] if (srgb and k < 3) else px[o + k]
            if srgb:
                out += bytes((_l2s(acc[0] / 4), _l2s(acc[1] / 4), _l2s(acc[2] / 4), (acc[3] + 2) // 4))
            else:
                out += bytes((v + 2) // 4 for v in acc)
    return bytes(out), nw, nh


def mip_chain(px, w, h, count, min_dim=1, srgb=False):
    """min_dim=4 for BC5: the engine rejects normal maps whose last mip is under 4 px (DDSImage.cpp:473-478)."""
    full = 1 + min(w, h).bit_length() - 1 if min_dim == 1 and w == h else 1 + max(w, h).bit_length() - 1
    while min_dim > 1 and (min(w, h) >> (full - 1)) < min_dim:
        full -= 1
    count = min(count, full) if count else full
    levels = [(px, w, h)]
    while len(levels) < count:
        px, w, h = box_down(px, w, h, srgb)
        levels.append((px, w, h))
    return levels


def block_pixels(px, w, h, bx, by):
    """16 RGBA tuples of a 4x4 block; edge pixels clamp."""
    blk = []
    for j in range(4):
        for i in range(4):
            o = (min(h - 1, by * 4 + j) * w + min(w - 1, bx * 4 + i)) * 4
            blk.append(px[o:o + 4])
    return blk


def rgb565(r, g, b):
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def expand565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def _pack_color(e0, e1, blk):
    """Quantise two RGB endpoints to 565, order them for 4-colour mode, index each pixel to the nearest palette entry.
    Returns (error, c0, c1, bits, indices)."""
    c0, c1 = rgb565(*e0), rgb565(*e1)
    if c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1:  # solid: every index 0, error against the single colour
        p0 = expand565(c0)
        return sum((p[k] - p0[k]) ** 2 for p in blk for k in range(3)), c0, c1, 0, [0] * 16
    q0, q1 = expand565(c0), expand565(c1)
    r0, g0, b0 = q0
    r1, g1, b1 = q1
    # Same palette and same integer arithmetic as the generic form; inlined because this is the encoder's hot loop.
    # Ties go to the lowest index, as min(range(4), key=...) did.
    # palette index order is [q0, q1, (2*q0+q1)//3, (q0+2*q1)//3], as in the generic form
    p0r, p0g, p0b = r0, g0, b0
    p1r, p1g, p1b = r1, g1, b1
    p2r, p2g, p2b = (2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3
    p3r, p3g, p3b = (r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3
    bits, err, idx = 0, 0, []
    for i, p in enumerate(blk):
        pr, pg, pb = p[0], p[1], p[2]
        d0 = (pr - p0r) ** 2 + (pg - p0g) ** 2 + (pb - p0b) ** 2
        d1 = (pr - p1r) ** 2 + (pg - p1g) ** 2 + (pb - p1b) ** 2
        d2 = (pr - p2r) ** 2 + (pg - p2g) ** 2 + (pb - p2b) ** 2
        d3 = (pr - p3r) ** 2 + (pg - p3g) ** 2 + (pb - p3b) ** 2
        best, dm = 0, d0
        if d1 < dm:
            best, dm = 1, d1
        if d2 < dm:
            best, dm = 2, d2
        if d3 < dm:
            best, dm = 3, d3
        bits |= best << (2 * i)
        err += dm
        idx.append(best)
    return err, c0, c1, bits, idx


def _refine(blk, idx):
    """Least-squares endpoints for fixed indices (weight of c0 per index: 1, 0, 2/3, 1/3)."""
    w = (1.0, 0.0, 2 / 3, 1 / 3)
    a11 = a12 = a22 = 0.0
    b0, b1 = [0.0] * 3, [0.0] * 3
    for p, j in zip(blk, idx):
        a, b = w[j], 1.0 - w[j]
        a11 += a * a
        a12 += a * b
        a22 += b * b
        for k in range(3):
            b0[k] += a * p[k]
            b1[k] += b * p[k]
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-6:
        return None
    clamp = lambda v: max(0, min(255, int(round(v))))
    e0 = tuple(clamp((b0[k] * a22 - b1[k] * a12) / det) for k in range(3))
    e1 = tuple(clamp((b1[k] * a11 - b0[k] * a12) / det) for k in range(3))
    return e0, e1


def enc_color_block(blk):
    """BC1 colour block (4-colour mode). Candidates: bounding-box diagonal and principal-axis endpoints, each followed
    by two least-squares refinements of the endpoints; the lowest squared error wins (OF-04: the box diagonal alone
    fails on two-colour blocks whose colours are off the diagonal, e.g. stripes or hard edges)."""
    lo = [min(p[k] for p in blk) for k in range(3)]
    hi = [max(p[k] for p in blk) for k in range(3)]
    cands = [(tuple(hi), tuple(lo))]
    mean = [sum(p[k] for p in blk) / 16.0 for k in range(3)]
    cov = [[sum((p[i] - mean[i]) * (p[j] - mean[j]) for p in blk) for j in range(3)] for i in range(3)]
    # Seed with the strongest covariance column (the box diagonal can be exactly orthogonal to the principal axis, e.g.
    # for two anti-correlated colours, and power iteration from it collapses to zero).
    col = max(range(3), key=lambda j: sum(cov[i][j] ** 2 for i in range(3)))
    axis = [cov[i][col] for i in range(3)]
    if not any(axis):
        axis = [hi[k] - lo[k] + 1e-3 for k in range(3)]
    for _ in range(8):
        axis = [sum(cov[i][j] * axis[j] for j in range(3)) for i in range(3)]
        norm = math.sqrt(sum(v * v for v in axis)) or 1.0
        axis = [v / norm for v in axis]
    t = [sum((p[k] - mean[k]) * axis[k] for k in range(3)) for p in blk]
    clamp = lambda v: max(0, min(255, int(round(v))))
    cands.append((tuple(clamp(mean[k] + axis[k] * max(t)) for k in range(3)),
                  tuple(clamp(mean[k] + axis[k] * min(t)) for k in range(3))))
    best = None
    for e0, e1 in cands:
        cur = _pack_color(e0, e1, blk)
        for _ in range(2):
            r = _refine(blk, cur[4])
            if r is None:
                break
            nxt = _pack_color(r[0], r[1], blk)
            if nxt[0] >= cur[0]:
                break
            cur = nxt
        if best is None or cur[0] < best[0]:
            best = cur
    return struct.pack("<HHI", best[1], best[2], best[3])


def enc_alpha_block(vals):
    """BC4/BC3-alpha block, 8-value mode (a0 > a1)."""
    a0, a1 = max(vals), min(vals)
    if a0 == a1:
        return struct.pack("<BB", a0, a1) + b"\0" * 6
    pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    bits = 0
    for i, v in enumerate(vals):
        best, dm = 0, abs(v - pal[0])  # first minimum wins, as min(range(8), key=...) did
        for j in range(1, 8):
            d = abs(v - pal[j])
            if d < dm:
                best, dm = j, d
        bits |= best << (3 * i)
    return struct.pack("<BB", a0, a1) + struct.pack("<Q", bits)[:6]


def to_signed(b):
    """Unsigned map byte (128 = neutral) to the BC4_SNORM integer scale -127..127 (0 = neutral)."""
    return max(-127, min(127, int(round((2 * b - 255) / 255.0 * 127.0))))


def enc_snorm_block(vals):
    """BC4_SNORM block, 8-value mode (r0 > r1 as signed ints); vals are -127..127. The engine samples a normal map as
    already signed (common.cfi GetXYNormalMap returns the raw .yx, no *2-1), so a neutral map must decode to 0."""
    a0, a1 = max(vals), min(vals)
    if a0 == a1:
        return struct.pack("<bb", a0, a1) + b"\0" * 6
    pal = [float(a0), float(a1)] + [((7 - i) * a0 + i * a1) / 7.0 for i in range(1, 7)]
    bits = 0
    for i, v in enumerate(vals):
        best, dm = 0, abs(v - pal[0])
        for j in range(1, 8):
            d = abs(v - pal[j])
            if d < dm:
                best, dm = j, d
        bits |= best << (3 * i)
    return struct.pack("<bb", a0, a1) + struct.pack("<Q", bits)[:6]


def encode_level(fmt, px, w, h):
    if fmt == "rgba8":  # A8R8G8B8 little-endian = B,G,R,A bytes
        out = bytearray()
        for o in range(0, len(px), 4):
            out += bytes((px[o + 2], px[o + 1], px[o], px[o + 3]))
        return bytes(out)
    out = bytearray()
    for by in range(max(1, (h + 3) // 4)):
        for bx in range(max(1, (w + 3) // 4)):
            blk = block_pixels(px, w, h, bx, by)
            if fmt == "bc1":
                out += enc_color_block(blk)
            elif fmt == "bc3":
                out += enc_alpha_block([p[3] for p in blk]) + enc_color_block(blk)
            elif fmt == "bc5":
                out += enc_alpha_block([p[0] for p in blk]) + enc_alpha_block([p[1] for p in blk])
            elif fmt == "bc4":
                out += enc_alpha_block([p[0] for p in blk])
            elif fmt == "bc5s":
                out += enc_snorm_block([to_signed(p[0]) for p in blk]) + enc_snorm_block([to_signed(p[1]) for p in blk])
    return bytes(out)


def _encode_band(task):
    """Worker entry point (module level so it pickles): encode one band of block rows."""
    fmt, sub, w, h = task
    return encode_level(fmt, sub, w, h)


def _encode_levels(fmt, levels, jobs):
    """encode_level for every (px, w, h) in levels. jobs > 1 splits each BC level into bands of whole block rows, encoded
    in worker processes and joined in order. A band is itself a valid image: every band but the last holds a multiple of
    4 pixel rows, and the last one ends at the image bottom, so the edge clamping is the same as in the whole image.
    The output is byte-identical to jobs=1."""
    if jobs <= 1 or fmt == "rgba8":
        return [encode_level(fmt, p, w, h) for p, w, h in levels]
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    ctx = multiprocessing.get_context("fork") if "fork" in multiprocessing.get_all_start_methods() else None
    out, pool = [], None
    try:
        for p, w, h in levels:
            nby = max(1, (h + 3) // 4)
            n = min(jobs, nby)
            if n <= 1:
                out.append(encode_level(fmt, p, w, h))
                continue
            if pool is None:
                pool = ProcessPoolExecutor(max_workers=jobs, mp_context=ctx)
            per = -(-nby // n)  # block rows per band
            tasks = []
            for b0 in range(0, nby, per):
                y0, y1 = b0 * 4, min(h, min(nby, b0 + per) * 4)
                tasks.append((fmt, p[y0 * w * 4:y1 * w * 4], w, y1 - y0))
            out.append(b"".join(pool.map(_encode_band, tasks)))
    finally:
        if pool is not None:
            pool.shutdown()
    return out


def pixelformat(fmt):
    if fmt == "rgba8":
        return struct.pack("<8I", 32, DDPF_RGB | DDPF_ALPHAPIXELS, 0, 32,
                           0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    cc = {"bc1": b"DXT1", "bc3": b"DXT5", "bc5": b"ATI2", "bc5s": b"DX10", "bc4": b"DX10"}[fmt]
    return struct.pack("<II4s5I", 32, DDPF_FOURCC, cc, 0, 0, 0, 0, 0)


def check_args(path, fmt, allow_misnamed=False, srgb=False):
    """The argument rules of write_dds, separated so that a cache hit can apply them without encoding."""
    # The engine treats BC5 as a normal map and warns 'Not a normal map texture attempted to be used as a normal map'
    # when the name lacks _ddn (finding 2026-10-23, OF-06). The mip cap in mip_chain covers the other rule.
    if fmt in BC5_FORMATS and not allow_misnamed and not os.path.basename(path).lower().endswith(("_ddn.dds", "_ddna.dds")):
        raise ValueError("BC5 is a normal-map format: name the file *_ddn.dds, or *_ddna.dds with a gloss (or pass allow_misnamed for a negative test)")
    if srgb and fmt in BC5_FORMATS:
        raise ValueError("normal maps are linear data: srgb is for colour textures")


def write_dds(path, w, h, px, fmt, mips=0, trailer=False, allow_misnamed=False, srgb=False, persistent=None, jobs=1, gloss=None):
    """gloss: one byte per pixel (w*h) for per-texel smoothness, only with fmt bc5s: written as the normal map's attached alpha
    (the engine-built `_ddna` layout, see attached_alpha_chunk)."""
    check_args(path, fmt, allow_misnamed, srgb)
    if gloss is not None and (fmt != "bc5s" or trailer or len(gloss) != w * h):
        raise ValueError("gloss needs fmt bc5s, no trailer and w*h bytes")
    if gloss is not None and not allow_misnamed and not os.path.basename(path).lower().endswith("_ddna.dds"):
        raise ValueError("a normal map with gloss is named *_ddna.dds (the engine's suffix table: _ddna = normals with smoothness)")
    levels = mip_chain(px, w, h, mips, 4 if fmt in BC5_FORMATS else 1, srgb)
    blobs = _encode_levels(fmt, levels, jobs)
    if fmt == "rgba8":
        flags, top = DDSD | DDSD_PITCH, w * 4
    else:
        flags, top = DDSD | DDSD_LINEARSIZE, len(blobs[0])
    # Crytek extension (ImageExtensionHelper.h DDS_HEADER): image flags live in dwReserved1 (offset 32) and are only read when
    # dwTextureStage (offset 120) is 'CRYF'. EIF_SRGBRead = 0x800 makes the engine sample the texture as sRGB; without it a
    # colour texture is treated as linear data and renders far too bright (render check 2026-10-24, OF-03/OF-05).
    crytek = bytearray(44)
    if srgb:
        struct.pack_into("<I", crytek, 4, EIF_SRGBREAD)  # dwAlphaBitDepth(28) is crytek[0:4]; dwReserved1(32) is crytek[4:8]
    if gloss is not None:
        struct.pack_into("<I", crytek, 4, EIF_ATTACHED_ALPHA)
    hdr = struct.pack("<7I", 124, flags, h, w, top, 0, len(levels)) + bytes(crytek)
    hdr += pixelformat(fmt) + struct.pack("<5I", CAPS, 0, 0, 0, 0)
    # bNumPersistentMips (offset 112) is only read with 'CRYF' (DDSImage.cpp, loader); without the block the engine forces the
    # count to 0 and then clamps it up to 3, so only the 3 smallest mips are resident and a single-file DDS looks blurry under
    # streaming (OF-05). Default: every mip persistent, so the texture is not streamed and loads whole.
    npers = len(levels) if persistent is None else persistent
    if not 3 <= npers <= len(levels) and len(levels) >= 3:
        raise ValueError("persistent mips must be between 3 and the mip count (%d)" % len(levels))
    hdr = hdr[:112] + bytes([min(npers, 255)]) + hdr[113:120] + struct.pack("<I", CRYF_STAGE)
    assert len(hdr) == 124
    # DX10 extension header (dxgiFormat, resourceDimension TEXTURE2D, miscFlag, arraySize 1, miscFlags2) after the 124 bytes
    dx10 = struct.pack("<5I", DXGI_BC5_SNORM, 3, 0, 1, 0) if fmt == "bc5s" else \
        struct.pack("<5I", DXGI_BC4_UNORM, 3, 0, 1, 0) if fmt == "bc4" else b""     # bc4 is DX10 too: the engine reads its dxgiFormat
    data = b"DDS " + hdr + dx10 + b"".join(blobs)
    if trailer:
        data += trailer_bytes()
    if gloss is not None:
        data += attached_alpha_chunk(gloss, w, h, len(levels))
    open(path, "wb").write(data)
    return len(levels), len(data)


def attached_alpha_chunk(gloss, w, h, count):
    """The `_ddna` attached image, as the engine-built SampleCharacter/mcg_ddna.dds carries it after the normal map's mips:
    b'CExt' + b'AttC' + u32 size + a full BC4_UNORM DDS (DX10 header dxgi 80, same size and mip count, the CRYF stage, its own
    empty CExt/CEnd) + b'CEnd'. The engine loads it as the smoothness texture: shaders read .r linearly, 1 = glossy."""
    gpx = bytearray(w * h * 4)
    gpx[0::4] = gloss
    levels = mip_chain(bytes(gpx), w, h, count, 4, False)
    if len(levels) != count:
        raise ValueError("gloss mip chain has %d levels, the normal map %d" % (len(levels), count))
    blobs = [encode_level("bc4", p, lw, lh) for p, lw, lh in levels]
    hdr = struct.pack("<7I", 124, DDSD | DDSD_LINEARSIZE, h, w, len(blobs[0]), 0, count) + bytes(44)
    hdr += pixelformat("bc4") + struct.pack("<5I", CAPS, 0, 0, 0, 0)
    hdr = hdr[:112] + bytes([min(count, 255)]) + hdr[113:120] + struct.pack("<I", CRYF_STAGE)
    payload = b"DDS " + hdr + struct.pack("<5I", DXGI_BC4_UNORM, 3, 0, 1, 0) + b"".join(blobs) + b"CExtCEnd"
    return b"CExt" + b"AttC" + struct.pack("<I", len(payload)) + payload + b"CEnd"


def trailer_bytes():
    """RC-style extension block (ImageExtensionHelper.h:180, :262): CExt, chunks of name+size+payload, CEnd.
    One AvgC chunk (average colour, uint32). The base loader never reads it (finding 2026-10-23)."""
    return b"CExt" + b"AvgC" + struct.pack("<II", 4, 0xFF808080) + b"CEnd"


def dec_alpha(b):
    a0, a1 = b[0], b[1]
    pal = [a0, a1] + ([((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)] if a0 > a1
                      else [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255])
    bits = int.from_bytes(b[2:8], "little")
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]

def dec_snorm(b):
    """BC4_SNORM block back to unsigned bytes (the inverse of to_signed)."""
    a0, a1 = struct.unpack("<bb", b[:2])
    pal = [a0, a1] + ([((7 - i) * a0 + i * a1) / 7.0 for i in range(1, 7)] if a0 > a1
                      else [((5 - i) * a0 + i * a1) / 5.0 for i in range(1, 5)] + [-127, 127])
    bits = int.from_bytes(b[2:8], "little")
    return [int(round((max(-127.0, min(127.0, pal[(bits >> (3 * i)) & 7])) / 127.0 + 1.0) / 2.0 * 255.0)) for i in range(16)]


def dec_color(b):
    c0, c1, bits = struct.unpack("<HHI", b)
    e0, e1 = expand565(c0), expand565(c1)
    pal = [e0, e1, tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)), tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3))] \
        if c0 > c1 else [e0, e1, tuple((e0[k] + e1[k]) // 2 for k in range(3)), (0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]

def decode_mip0(fmt, data, w, h):
    if fmt == "rgba8":
        return b"".join(bytes((data[o + 2], data[o + 1], data[o], data[o + 3])) for o in range(0, w * h * 4, 4))
    out = bytearray(w * h * 4)
    bsz = {"bc1": 8, "bc3": 16, "bc5": 16, "bc5s": 16}[fmt]
    for by in range(h // 4):
        for bx in range(w // 4):
            b = data[(by * (w // 4) + bx) * bsz:][:bsz]
            if fmt == "bc1": rgb, a = dec_color(b), [255] * 16
            elif fmt == "bc3": rgb, a = dec_color(b[8:]), dec_alpha(b[:8])
            else:
                rr, gg = (dec_snorm(b[:8]), dec_snorm(b[8:])) if fmt == "bc5s" else (dec_alpha(b[:8]), dec_alpha(b[8:]))
                rgb, a = [(rr[i], gg[i], 0) for i in range(16)], [255] * 16
            for i in range(16):
                o = ((by * 4 + i // 4) * w + bx * 4 + i % 4) * 4
                out[o:o + 4] = bytes(rgb[i]) + bytes((a[i],))
    return bytes(out)
