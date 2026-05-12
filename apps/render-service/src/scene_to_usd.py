"""Export a scene_mesh Quad set to USD (Universal Scene Description) format.

USD is the industry-standard scene interchange format used by Omniverse,
Unreal Engine 5 (USD plugin), Blender, Houdini, Maya, etc. It carries
geometry, materials, lighting, cameras, animation — everything needed to
move our BM-derived scene from Blender Cycles to UE5 + Lumen without
re-creating it.

We emit USDA (USD ASCII text format) directly — no `pxr` library needed
on the export side. UE5 and Omniverse will read it natively.

Pipeline integration :

    BM JSON ─→ scene_mesh.py ─→ quads_by_material + camera + lighting
                                          │
                                          ├─→ Blender Cycles (current path)
                                          │
                                          └─→ scene_to_usd.py (this module)
                                                        ↓
                                              .usda file on disk
                                                        ↓
                                              UE5 USD import (auto)
                                              or Omniverse USD Composer

What this module emits :
  - World Xform (root) with up-axis Z (matching Blender + our scene_mesh)
  - One Mesh prim per material group (so the importer can assign UE5
    materials by name : "asphalte" → Megascans Asphalt 04, etc.)
  - One Camera prim with FOV + position + target
  - One DistantLight (sun) prim with direction + intensity
  - displayColor on each Mesh (RGB derived from our PBR material colors)
    as a hint to the importer for unmatched materials

What we DON'T emit yet (future iterations) :
  - MaterialX shaders (real PBR materials) — UE5 will assign Megascans by name
  - Trees / lamps as USD references (current implementation as Blender
    primitives stays in Blender-only path until USD asset library exists)
  - Animation / timeline — single-frame static scene only
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence


# Material → (R, G, B) sRGB color in [0,1] — used as `displayColor` USD hint.
# These match the colors in modal_blender_endpoint.py at iter #320 so UE5
# import has the same starting point. UE5 then re-maps by material NAME
# to real Megascans PBR via the import script.
MATERIAL_DISPLAY_COLOR: dict[str, tuple[float, float, float]] = {
    "enduit_blanc":      (0.92, 0.86, 0.74),
    "brique_rouge":      (0.55, 0.22, 0.12),
    "balcon_concrete":   (0.94, 0.92, 0.88),
    "balcon_metal":      (0.18, 0.18, 0.20),
    "verre":             (0.05, 0.10, 0.18),
    "asphalte":          (0.16, 0.16, 0.16),
    "pavers_concrete":   (0.58, 0.58, 0.55),
    "terre_neutre":      (0.42, 0.40, 0.36),
    "pierre_kerb":       (0.78, 0.74, 0.68),
    "vegetation":        (0.28, 0.52, 0.18),
    "metal_noir":        (0.05, 0.05, 0.05),
    "voisin":            (0.50, 0.45, 0.38),
    "road_paint_white":  (0.97, 0.97, 0.95),
    "bois_porte":        (0.28, 0.15, 0.08),
    "pierre_taille":     (0.82, 0.74, 0.58),
    "zinc_anthracite":   (0.16, 0.16, 0.18),
    "bois_clair":        (0.50, 0.32, 0.18),
}


def _fmt_v3(v: Sequence[float]) -> str:
    return f"({v[0]}, {v[1]}, {v[2]})"


def _fmt_v3f_list(verts: list[tuple[float, float, float]]) -> str:
    parts = [f"({v[0]}, {v[1]}, {v[2]})" for v in verts]
    return "[" + ", ".join(parts) + "]"


def _emit_mesh_prim(mat_name: str, quads: list, indent: str = "    ") -> str:
    """Emit a USD Mesh prim for a single material group.

    `quads` is a list of (v0, v1, v2, v3) where each v is (x, y, z) tuple.
    Mesh is in world coordinates (no transform on the prim itself).
    """
    if not quads:
        return ""
    # Flatten verts + build per-face vertex indices
    verts: list[tuple[float, float, float]] = []
    face_counts: list[int] = []
    face_indices: list[int] = []
    for q in quads:
        v0, v1, v2, v3 = q
        base = len(verts)
        # Detect degenerate (triangle) — if v3 == v0, emit as triangle
        if v3 == v0 or v3 == v2:
            verts.extend([v0, v1, v2])
            face_counts.append(3)
            face_indices.extend([base, base + 1, base + 2])
        else:
            verts.extend([v0, v1, v2, v3])
            face_counts.append(4)
            face_indices.extend([base, base + 1, base + 2, base + 3])

    color = MATERIAL_DISPLAY_COLOR.get(mat_name, (0.8, 0.8, 0.8))
    sanitized = mat_name.replace("-", "_")

    lines: list[str] = []
    lines.append(f'{indent}def Mesh "{sanitized}"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    point3f[] points = {_fmt_v3f_list(verts)}')
    lines.append(f'{indent}    int[] faceVertexCounts = [{", ".join(str(c) for c in face_counts)}]')
    lines.append(f'{indent}    int[] faceVertexIndices = [{", ".join(str(i) for i in face_indices)}]')
    lines.append(f'{indent}    color3f[] primvars:displayColor = [{_fmt_v3(color)}]')
    lines.append(f'{indent}    uniform token subdivisionScheme = "none"')
    lines.append(f'{indent}    custom string material_name = "{mat_name}"')
    lines.append(f'{indent}}}')
    return "\n".join(lines)


def _emit_camera_prim(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    fov_deg: float,
    indent: str = "    ",
) -> str:
    """Emit a USD Camera prim. UE5 import will create an equivalent
    CineCameraActor. Position + target define the look-at orientation.
    """
    # Compute look-at rotation : USD cameras look along -Z axis by default.
    # We'll just emit the position + a "look at" hint via xformOp:translate
    # + a custom "lookAt" property the importer can resolve.
    lines: list[str] = []
    lines.append(f'{indent}def Camera "MainCamera"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    float focalLength = 35')
    lines.append(f'{indent}    float horizontalAperture = 36')
    lines.append(f'{indent}    float verticalAperture = 24')
    lines.append(f'{indent}    custom float fov_deg = {fov_deg}')
    lines.append(f'{indent}    custom point3f position = {_fmt_v3(position)}')
    lines.append(f'{indent}    custom point3f target = {_fmt_v3(target)}')
    lines.append(f'{indent}    matrix4d xformOp:transform = (')
    lines.append(f'{indent}        (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0),')
    lines.append(f'{indent}        ({position[0]}, {position[1]}, {position[2]}, 1)')
    lines.append(f'{indent}    )')
    lines.append(f'{indent}    uniform token[] xformOpOrder = ["xformOp:transform"]')
    lines.append(f'{indent}}}')
    return "\n".join(lines)


def _emit_sun_light(
    direction: tuple[float, float, float],
    energy: float = 5.0,
    color: tuple[float, float, float] = (1.0, 0.97, 0.92),
    indent: str = "    ",
) -> str:
    """Emit a USD DistantLight (parallel rays, like our Blender Sun)."""
    lines: list[str] = []
    lines.append(f'{indent}def DistantLight "SunLight"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    float inputs:intensity = {energy * 1000}')
    lines.append(f'{indent}    color3f inputs:color = {_fmt_v3(color)}')
    lines.append(f'{indent}    float inputs:angle = 2.0')
    lines.append(f'{indent}    custom vector3f direction = {_fmt_v3(direction)}')
    lines.append(f'{indent}}}')
    return "\n".join(lines)


def export_scene_to_usda(
    quads_by_material: dict[str, list],
    camera_position: tuple[float, float, float],
    camera_target: tuple[float, float, float],
    camera_fov_deg: float = 42.0,
    sun_direction: tuple[float, float, float] = (0.4, -0.6, 0.7),
    sun_energy: float = 5.0,
    output_path: Optional[Path] = None,
) -> str:
    """Write a USDA scene file. Returns the USDA text (and writes to disk
    if output_path is provided)."""
    lines: list[str] = []
    lines.append("#usda 1.0")
    lines.append("(")
    lines.append('    defaultPrim = "World"')
    lines.append('    metersPerUnit = 1')
    lines.append('    upAxis = "Z"')
    lines.append('    doc = "Generated by ArchiClaude scene_to_usd.py — iter #320 baseline format"')
    lines.append(")")
    lines.append("")
    lines.append('def Xform "World"')
    lines.append("{")

    # 1) Camera
    lines.append(_emit_camera_prim(camera_position, camera_target, camera_fov_deg))
    lines.append("")

    # 2) Sun light
    lines.append(_emit_sun_light(sun_direction, sun_energy))
    lines.append("")

    # 3) Geometry per material
    lines.append('    def Xform "Geometry"')
    lines.append("    {")
    for mat_name, quads in quads_by_material.items():
        if not quads:
            continue
        # Convert internal Quad dataclass instances to tuples if needed.
        normalized = []
        for q in quads:
            if hasattr(q, "v0"):
                normalized.append((q.v0, q.v1, q.v2, q.v3))
            elif isinstance(q, tuple) and len(q) == 4:
                normalized.append(q)
            else:
                continue
        block = _emit_mesh_prim(mat_name, normalized, indent="        ")
        if block:
            lines.append(block)
            lines.append("")
    lines.append("    }")
    lines.append("}")
    lines.append("")

    text = "\n".join(lines)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
    return text


def quick_smoke_test() -> None:
    """Sanity check : build a tiny 1-quad scene and export it."""
    quads_by_mat = {
        "enduit_blanc": [
            ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)),
        ],
        "asphalte": [
            ((-5.0, -5.0, -0.01), (15.0, -5.0, -0.01),
             (15.0, 15.0, -0.01), (-5.0, 15.0, -0.01)),
        ],
    }
    text = export_scene_to_usda(
        quads_by_material=quads_by_mat,
        camera_position=(20.0, -10.0, 15.0),
        camera_target=(5.0, 5.0, 5.0),
        camera_fov_deg=42.0,
        output_path=Path("/tmp/archiclaude_smoke.usda"),
    )
    print(text)
    print(f"\n✓ Wrote /tmp/archiclaude_smoke.usda ({len(text)} bytes)")


if __name__ == "__main__":
    quick_smoke_test()
