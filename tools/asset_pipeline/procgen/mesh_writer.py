from __future__ import annotations

from pathlib import Path


def write_obj(
    path: Path,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    uvs: list[tuple[float, float]],
    uv_indices: list[tuple[int, int, int]],
    material_ids: list[int],
    material_names: list[str],
    *,
    mtl_filename: str | None = None,
) -> None:
    """Write a Wavefront OBJ file. UV scale = 1.0 unit per meter (natural tiling).

    Coordinates are Z-up (CRYENGINE convention).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if mtl_filename is None:
        mtl_filename = path.stem + ".mtl"

    lines: list[str] = [f"mtllib {mtl_filename}\n"]

    for vx, vy, vz in vertices:
        lines.append(f"v {vx:.6f} {vy:.6f} {vz:.6f}\n")

    for u, v in uvs:
        lines.append(f"vt {u:.6f} {v:.6f}\n")

    # Group faces by material
    current_mat: int | None = None
    for i, (f0, f1, f2) in enumerate(faces):
        mat_id = material_ids[i] if i < len(material_ids) else 0
        if mat_id != current_mat:
            mat_name = material_names[mat_id] if mat_id < len(material_names) else f"mat_{mat_id}"
            lines.append(f"usemtl {mat_name}\n")
            current_mat = mat_id
        ui, uj, uk = uv_indices[i] if i < len(uv_indices) else (f0, f1, f2)
        # OBJ indices are 1-based
        lines.append(f"f {f0+1}/{ui+1} {f1+1}/{uj+1} {f2+1}/{uk+1}\n")

    with path.open("w", encoding="utf-8") as fh:
        fh.writelines(lines)


def write_mtl(
    path: Path,
    material_names: list[str],
    engine_mtl_paths: list[str] | None = None,
) -> None:
    """Write a companion .mtl file referencing engine material paths."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, name in enumerate(material_names):
        lines.append(f"newmtl {name}\n")
        lines.append("Ka 0.2 0.2 0.2\n")
        lines.append("Kd 0.8 0.8 0.8\n")
        lines.append("Ks 0.0 0.0 0.0\n")
        if engine_mtl_paths and i < len(engine_mtl_paths):
            lines.append(f"# engine_mtl: {engine_mtl_paths[i]}\n")
        lines.append("\n")
    with path.open("w", encoding="utf-8") as fh:
        fh.writelines(lines)


def add_box_mesh(
    verts: list,
    faces: list,
    uvs: list,
    uv_indices: list,
    mat_ids: list,
    *,
    min_corner: tuple[float, float, float],
    max_corner: tuple[float, float, float],
    material_id: int = 0,
) -> None:
    """Append an axis-aligned box (8 verts, 12 triangles) to the mesh lists in-place.

    UV tiling: 1.0 unit per meter so tiling engine materials repeat at natural density.
    Coordinates: Z-up (x=right, y=forward, z=up).
    """
    x0, y0, z0 = min_corner
    x1, y1, z1 = max_corner
    dx = x1 - x0
    dy = y1 - y0
    dz = z1 - z0

    base = len(verts)

    # 8 corners
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),  # bottom (z=z0)
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),  # top    (z=z1)
    ]
    verts.extend(corners)

    uv_base = len(uvs)
    # Per-face UV sets (4 UVs per quad face, tiled by face dimensions)
    face_uvs = [
        # bottom (-Z normal): dx * dy
        [(0,0),(dx,0),(dx,dy),(0,dy)],
        # top (+Z): dx * dy
        [(0,0),(dx,0),(dx,dy),(0,dy)],
        # front (-Y): dx * dz
        [(0,0),(dx,0),(dx,dz),(0,dz)],
        # back (+Y): dx * dz
        [(0,0),(dx,0),(dx,dz),(0,dz)],
        # left (-X): dy * dz
        [(0,0),(dy,0),(dy,dz),(0,dz)],
        # right (+X): dy * dz
        [(0,0),(dy,0),(dy,dz),(0,dz)],
    ]
    for quad_uvs in face_uvs:
        for u, v in quad_uvs:
            uvs.append((float(u), float(v)))

    # 6 quad faces → 12 triangles
    # Indices into the 8 corners (0-based), CCW winding
    quads = [
        (3, 2, 1, 0),  # bottom
        (4, 5, 6, 7),  # top
        (0, 1, 5, 4),  # front
        (2, 3, 7, 6),  # back
        (3, 0, 4, 7),  # left
        (1, 2, 6, 5),  # right
    ]

    for fi, (a, b, c, d) in enumerate(quads):
        va, vb, vc, vd = base+a, base+b, base+c, base+d
        ua = uv_base + fi * 4
        # tri 0: a b c
        faces.append((va, vb, vc))
        uv_indices.append((ua+0, ua+1, ua+2))
        mat_ids.append(material_id)
        # tri 1: a c d
        faces.append((va, vc, vd))
        uv_indices.append((ua+0, ua+2, ua+3))
        mat_ids.append(material_id)
