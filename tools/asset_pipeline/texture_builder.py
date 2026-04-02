from __future__ import annotations

import binascii
import json
import struct
import zlib
import zipfile
from pathlib import Path
from typing import Any

from .common import write_json, write_text


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = b"".join(b"\x00" + pixels[row * width * 4 : (row + 1) * width * 4] for row in range(height))
    data = zlib.compress(rows, level=9)
    payload = header + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", data) + _chunk(b"IEND", b"")
    path.write_bytes(payload)


def average_rgba(pixels: bytes) -> list[int]:
    samples = len(pixels) // 4
    if samples == 0:
        return [128, 128, 128, 255]
    totals = [0, 0, 0, 0]
    for offset in range(0, len(pixels), 4):
        for index in range(4):
            totals[index] += pixels[offset + index]
    return [int(value / samples) for value in totals]


def _solid_pixels(width: int, height: int, rgba: list[int]) -> bytes:
    return bytes(rgba) * (width * height)


def _checker_pixels(width: int, height: int, palette: list[list[int]], tile: int = 16) -> bytes:
    colors = [bytes(rgba) for rgba in palette]
    data = bytearray()
    for y in range(height):
        for x in range(width):
            index = ((x // tile) + (y // tile)) % len(colors)
            data.extend(colors[index])
    return bytes(data)


def _stripe_pixels(width: int, height: int, palette: list[list[int]], stripe_width: int = 24) -> bytes:
    colors = [bytes(rgba) for rgba in palette]
    data = bytearray()
    for y in range(height):
        for x in range(width):
            index = (x // stripe_width) % len(colors)
            data.extend(colors[index])
    return bytes(data)


def _radial_pixels(width: int, height: int, palette: list[list[int]]) -> bytes:
    colors = palette if len(palette) >= 2 else [palette[0], [255, 255, 255, 255]]
    center_x = width / 2.0
    center_y = height / 2.0
    max_distance = max(center_x, center_y)
    data = bytearray()
    for y in range(height):
        for x in range(width):
            distance = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5 / max_distance
            blend = max(0.0, min(1.0, distance))
            rgba = [
                int(colors[0][channel] * (1.0 - blend) + colors[1][channel] * blend)
                for channel in range(4)
            ]
            data.extend(rgba)
    return bytes(data)


def generate_texture_pixels(spec: dict[str, Any]) -> tuple[bytes, list[int]]:
    width = int(spec["width"])
    height = int(spec["height"])
    mode = spec["mode"]
    if mode == "solid_color":
        pixels = _solid_pixels(width, height, spec["rgba"])
    elif mode == "procedural_pattern":
        pattern = spec.get("pattern", "checker")
        if pattern == "checker":
            pixels = _checker_pixels(width, height, spec["palette"])
        elif pattern == "stripes":
            pixels = _stripe_pixels(width, height, spec["palette"])
        elif pattern == "radial":
            pixels = _radial_pixels(width, height, spec["palette"])
        else:
            raise ValueError(f"Unsupported procedural pattern: {pattern}")
    elif mode == "imagegen":
        fallback_rgba = spec.get("fallback_rgba", [128, 128, 128, 255])
        pixels = _checker_pixels(width, height, [fallback_rgba, [min(255, fallback_rgba[0] + 20), min(255, fallback_rgba[1] + 20), min(255, fallback_rgba[2] + 20), fallback_rgba[3]]], tile=32)
    else:
        raise ValueError(f"Texture pixels cannot be generated for mode={mode}")
    return pixels, average_rgba(pixels)


def _resample_rgba(pixels: bytes, width: int, height: int, target_width: int, target_height: int) -> bytes:
    data = bytearray()
    for y in range(target_height):
        source_y = min(height - 1, int(y * height / target_height))
        for x in range(target_width):
            source_x = min(width - 1, int(x * width / target_width))
            offset = (source_y * width + source_x) * 4
            data.extend(pixels[offset : offset + 4])
    return bytes(data)


def make_cover_ctc(diffuse_pixels: bytes, width: int, height: int, sector_table_size: int) -> bytes:
    file_type = 100
    version = 9
    diff_pix = 64
    hmap_pix = 32
    diff_data = _resample_rgba(diffuse_pixels, width, height, diff_pix, diff_pix)
    average = average_rgba(diffuse_pixels)
    hmap_data = bytes([average[0], average[1], 0, 0]) * (hmap_pix * hmap_pix)
    diff_bytes = len(diff_data)
    hmap_bytes = len(hmap_data)
    depth = 0
    size = sector_table_size
    while size > 1:
        size //= 2
        depth += 1
    tree_nodes = (4 ** (depth + 1) - 1) // 3
    common = b"CRY\x00" + struct.pack("<BBH", file_type, 0, version)
    tex_hdr = struct.pack("<HHf", 2, 0, 1.0)
    layer0 = struct.pack("<HHiI", diff_pix, 0, 2, diff_bytes)
    layer1 = struct.pack("<HHiI", hmap_pix, 0, 2, hmap_bytes)
    index_block = struct.pack("<H", tree_nodes) + b"".join(struct.pack("<h", i) for i in range(tree_nodes))
    one_tile = diff_data + hmap_data
    return common + tex_hdr + layer0 + layer1 + index_block + one_tile * tree_nodes


def build_terraintexture_pak(path: Path, diffuse_pixels: bytes, width: int, height: int, sector_table_size: int) -> dict[str, Any]:
    ctc = make_cover_ctc(diffuse_pixels, width, height, sector_table_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("terrain/cover.ctc", ctc)
    return {"path": path.as_posix(), "cover_ctc_bytes": len(ctc)}


def emit_imagegen_request(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)
    write_text(path.with_suffix(".prompt.txt"), payload["prompt"] + "\n")

