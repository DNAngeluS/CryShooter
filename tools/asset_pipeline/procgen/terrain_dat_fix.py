"""terrain_dat_fix.py — repair a terrain.dat written by the old pipeline writer, in place, without regenerating it.

The old writer (before 2026-10-24, OF-09) left out the trailing empty object-tree chunk and padded alignment gaps with 0x00.
Regenerating would need the original heightmap and could change the quantisation, so this patches the existing bytes:
rewrite the bad alignment bytes to 0xDE, append the 32-byte empty chunk with the root node's AABB, and update nChunkSize.
Idempotent: a file that already ends in an object-tree chunk (this pipeline's fixed output, or a Sandbox file) is only
repadded if needed, never extended.
"""
from __future__ import annotations

import hashlib
import re
import struct
import zipfile
from pathlib import Path

from .terrain_dat_parser import TerrainDatError, parse_terrain_dat
from .terrain_dat_writer import ALIGN_FILL, octree_chunk_bytes

TERRAIN_ENTRY = "terrain/terrain.dat"


def patch_terrain_dat(data: bytes) -> tuple[bytes, dict]:
    """Return (patched bytes, report). Raises TerrainDatError when the file cannot be walked."""
    info = parse_terrain_dat(data)
    out = bytearray(data)
    for offset in info["bad_pad_offsets"]:
        out[offset] = ALIGN_FILL
    appended = False
    if len(data) == info["nodes_end"]:  # nothing after the node tree: the old layout
        box = info["root_aabb"]
        size_m = info["header"]["heightmap_size"] * info["header"]["unit_m"]
        out += octree_chunk_bytes(size_m, box[2], box[5])
        appended = True
    struct.pack_into("<i", out, 4, len(out))
    patched = bytes(out)
    parse_terrain_dat(patched)  # must still walk; raises otherwise
    report = {"repadded_bytes": len(info["bad_pad_offsets"]), "appended_octree_chunk": appended,
              "old_size": len(data), "new_size": len(patched), "changed": patched != data}
    return patched, report


def _pak_path(target: Path) -> Path:
    target = Path(target)
    return target / "level.pak" if target.is_dir() else target


_FILELIST_PAK_RE = re.compile(r'(<file src="level\.pak" dest="level\.pak" size=")\d+(" md5=")[0-9a-fA-F]+(")')


def sync_filelist(pak: Path) -> bool:
    """Make the level folder's filelist.xml (size and md5 of level.pak, written by the pipeline) match the pak. Returns
    True when the file was rewritten; a level folder without a filelist.xml is left alone."""
    filelist = Path(pak).with_name("filelist.xml")
    if not filelist.is_file():
        return False
    data = Path(pak).read_bytes()
    text = filelist.read_text(encoding="utf-8")
    new = _FILELIST_PAK_RE.sub(lambda m: f"{m.group(1)}{len(data)}{m.group(2)}{hashlib.md5(data).hexdigest()}{m.group(3)}", text)
    if new == text:
        return False
    filelist.write_text(new, encoding="utf-8")
    return True


def fix_level_pak(target: Path, *, check_only: bool = False) -> dict:
    """Patch `terrain/terrain.dat` inside a level.pak (path to the pak or to the level folder). Other entries keep their
    order, names, compression type and bytes; filelist.xml (size, md5 of the pak) is kept in sync. With check_only nothing is written."""
    pak = _pak_path(target)
    with zipfile.ZipFile(pak) as src:
        if TERRAIN_ENTRY not in src.namelist():
            raise TerrainDatError(f"{pak}: no {TERRAIN_ENTRY} entry")
        patched, report = patch_terrain_dat(src.read(TERRAIN_ENTRY))
        report["pak"] = str(pak)
        if check_only:
            return report
        if not report["changed"]:
            report["filelist_updated"] = sync_filelist(pak)  # a pak fixed by an older run may leave filelist.xml stale
            return report
        tmp = pak.with_suffix(".pak.tmp")
        with zipfile.ZipFile(tmp, "w") as dst:
            for item in src.infolist():
                content = patched if item.filename == TERRAIN_ENTRY else src.read(item.filename)
                dst.writestr(item, content, compress_type=item.compress_type)
    tmp.replace(pak)
    report["filelist_updated"] = sync_filelist(pak)
    return report
