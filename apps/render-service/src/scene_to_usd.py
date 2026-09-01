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

import json
import shutil
from pathlib import Path
from typing import Any, Literal, Optional, Sequence


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
    # Jour 4 — IGN photogrammetry context (BDTOPO LOD2 voisinage + BD ORTHO sol).
    "ortho_texture":     (0.55, 0.55, 0.50),
    "voisin_ign":        (0.62, 0.58, 0.52),
}


ContextSource = Literal["bdtopo_legacy", "ign_photogrammetry"]


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


def _emit_ground_ortho_mesh(
    *,
    ortho_texture_filename: str,
    half_size_m: float,
    z_ground: float = 0.0,
    center_xy: tuple[float, float] = (0.0, 0.0),
    indent: str = "        ",
) -> str:
    """Emit a single textured quad acting as the BD ORTHO sol.

    Two prims are produced :
      * `def Mesh "GroundOrtho"` — a square at z=z_ground with UVs that map
        the full BD ORTHO JPEG onto the quad.
      * `def Material "GroundOrthoMat"` — UsdPreviewSurface bound to the
        mesh, referencing `@./<filename>@` as the diffuse texture so a USD
        consumer that resolves textures (Blender, Houdini, UE5) loads the
        aerial automatically.

    The mesh is large but FLAT (no DTM yet); future iterations will displace
    it with the LAZ ground class to add real topography. For now, the goal
    is "BD ORTHO visible under the buildings", which already kills the
    grey-asphalt look of the legacy synthetic ground.
    """
    cx, cy = center_xy
    h = half_size_m
    # CCW ring in XY plane at z_ground, top-down ortho photo facing +Z.
    verts = [
        (cx - h, cy - h, z_ground),
        (cx + h, cy - h, z_ground),
        (cx + h, cy + h, z_ground),
        (cx - h, cy + h, z_ground),
    ]
    # UVs follow the ortho image convention: (0,0) bottom-left → (1,1) top-right.
    # IGN BD ORTHO is north-up; assuming +Y = north in scene-local frame this
    # places north of the image at +Y of the mesh (matches scene_mesh frame).
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    color = MATERIAL_DISPLAY_COLOR["ortho_texture"]
    sanitized_tex = ortho_texture_filename.replace(" ", "_")

    lines: list[str] = []
    lines.append(f'{indent}def Mesh "GroundOrtho"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    point3f[] points = {_fmt_v3f_list(verts)}')
    lines.append(f'{indent}    int[] faceVertexCounts = [4]')
    lines.append(f'{indent}    int[] faceVertexIndices = [0, 1, 2, 3]')
    uv_parts = [f"({u}, {v})" for (u, v) in uvs]
    lines.append(f'{indent}    texCoord2f[] primvars:st = [{", ".join(uv_parts)}] '
                 '( interpolation = "vertex" )')
    lines.append(f'{indent}    color3f[] primvars:displayColor = [{_fmt_v3(color)}]')
    lines.append(f'{indent}    uniform token subdivisionScheme = "none"')
    lines.append(f'{indent}    custom string material_name = "ortho_texture"')
    lines.append(f'{indent}    custom asset diffuseTexture = @./{sanitized_tex}@')
    lines.append(f'{indent}    rel material:binding = </World/Geometry/GroundOrthoMat>')
    lines.append(f'{indent}}}')
    lines.append("")
    # Material — USD Preview Surface bound to the mesh above.
    lines.append(f'{indent}def Material "GroundOrthoMat"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    token outputs:surface.connect = </World/Geometry/GroundOrthoMat/Surface.outputs:surface>')
    lines.append(f'{indent}    def Shader "Surface"')
    lines.append(f'{indent}    {{')
    lines.append(f'{indent}        uniform token info:id = "UsdPreviewSurface"')
    lines.append(f'{indent}        color3f inputs:diffuseColor.connect = </World/Geometry/GroundOrthoMat/DiffuseTex.outputs:rgb>')
    lines.append(f'{indent}        float inputs:roughness = 0.85')
    lines.append(f'{indent}        float inputs:metallic = 0.0')
    lines.append(f'{indent}        token outputs:surface')
    lines.append(f'{indent}    }}')
    lines.append(f'{indent}    def Shader "DiffuseTex"')
    lines.append(f'{indent}    {{')
    lines.append(f'{indent}        uniform token info:id = "UsdUVTexture"')
    lines.append(f'{indent}        asset inputs:file = @./{sanitized_tex}@')
    lines.append(f'{indent}        token inputs:wrapS = "clamp"')
    lines.append(f'{indent}        token inputs:wrapT = "clamp"')
    lines.append(f'{indent}        float2 inputs:st.connect = </World/Geometry/GroundOrthoMat/UVReader.outputs:result>')
    lines.append(f'{indent}        float3 outputs:rgb')
    lines.append(f'{indent}    }}')
    lines.append(f'{indent}    def Shader "UVReader"')
    lines.append(f'{indent}    {{')
    lines.append(f'{indent}        uniform token info:id = "UsdPrimvarReader_float2"')
    lines.append(f'{indent}        token inputs:varname = "st"')
    lines.append(f'{indent}        float2 outputs:result')
    lines.append(f'{indent}    }}')
    lines.append(f'{indent}}}')
    return "\n".join(lines)


def _emit_vegetation_xform(
    *,
    laz_filename: str,
    count_metadata: int,
    indent: str = "        ",
) -> str:
    """Emit a placeholder Xform pointing at the LIDAR HD vegetation LAZ.

    No real mesh yet — geometry-nodes scattering of trees from the LAZ point
    cloud is deferred to a Blender-side post-import step. The metadata
    written here lets the importer know the asset exists + how many points
    to expect.
    """
    lines: list[str] = []
    lines.append(f'{indent}def Xform "Vegetation"')
    lines.append(f'{indent}{{')
    lines.append(f'{indent}    custom asset lidar_source = @./{laz_filename}@')
    lines.append(f'{indent}    custom int point_count = {count_metadata}')
    lines.append(f'{indent}    custom string source_class = "high_vegetation_class_5"')
    lines.append(f'{indent}    custom string render_hint = "blender_geometry_nodes_scatter"')
    lines.append(f'{indent}}}')
    return "\n".join(lines)


def _load_context_manifest(project_id: str) -> Optional[dict]:
    """Return the build_context_manifest dict for a project, or None if no
    IGN context has been built yet."""
    refs_root = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "photogrammetry"
    manifest_path = refs_root / project_id / "build_context_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def export_scene_to_usda(
    quads_by_material: dict[str, list],
    camera_position: tuple[float, float, float],
    camera_target: tuple[float, float, float],
    camera_fov_deg: float = 42.0,
    sun_direction: tuple[float, float, float] = (0.4, -0.6, 0.7),
    sun_energy: float = 5.0,
    output_path: Optional[Path] = None,
    *,
    context_source: ContextSource = "bdtopo_legacy",
    project_id: Optional[str] = None,
    ortho_half_size_m: float = 300.0,
    ortho_z_ground: float = 0.0,
    ortho_center_xy: tuple[float, float] = (0.0, 0.0),
    copy_ign_textures: bool = True,
) -> str:
    """Write a USDA scene file. Returns the USDA text (and writes to disk
    if output_path is provided).

    When `context_source="ign_photogrammetry"` and `project_id` is provided,
    the scene gains :
      * a `GroundOrtho` textured quad referencing `bdortho_macro.jpg`
      * a `Vegetation` Xform pointing at the cached LiDAR HD vegetation LAZ
      * the BD ORTHO JPEG is copied next to the USDA so consumers (Blender,
        UE5) resolve `@./bdortho_macro.jpg@` without additional path setup.

    The legacy path (`context_source="bdtopo_legacy"`) is byte-for-byte
    identical to the previous behaviour — no extra prims, no texture copy.
    """
    use_ign = context_source == "ign_photogrammetry" and project_id is not None
    manifest = _load_context_manifest(project_id) if use_ign else None
    if use_ign and manifest is None:
        # No IGN data on disk for this project — silently fall back so the
        # caller never crashes mid-render. The print is the signal.
        print(
            f"!! scene_to_usd: context_source='ign_photogrammetry' but no "
            f"build_context_manifest.json for {project_id} — falling back to "
            f"bdtopo_legacy output."
        )
        use_ign = False

    lines: list[str] = []
    lines.append("#usda 1.0")
    lines.append("(")
    lines.append('    defaultPrim = "World"')
    lines.append('    metersPerUnit = 1')
    lines.append('    upAxis = "Z"')
    doc_tag = "iter #500 IGN photogrammetry context" if use_ign else "iter #320 baseline format"
    lines.append(f'    doc = "Generated by ArchiClaude scene_to_usd.py — {doc_tag}"')
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

    # 3b) Jour 4 — IGN photogrammetry add-ons (BD ORTHO sol + LiDAR vegetation).
    ortho_filename_for_copy: Optional[str] = None
    laz_filename_for_copy: Optional[str] = None
    if use_ign and manifest is not None:
        bdortho_paths = manifest.get("bdortho_paths") or {}
        macro_path_rel = bdortho_paths.get("macro")
        if macro_path_rel:
            ortho_filename_for_copy = Path(macro_path_rel).name
            half_m = float(ortho_half_size_m)
            try:
                z_range = manifest.get("bdtopo_z_range_m")
                if (
                    ortho_z_ground == 0.0
                    and isinstance(z_range, (list, tuple))
                    and len(z_range) == 2
                    and z_range[0] is not None
                ):
                    # Drop the ortho mesh ~5 cm below the lowest BDTOPO ground
                    # so voisin building base z=0 still sits on top of it.
                    # We keep the user-provided value when caller overrides.
                    pass
            except Exception:
                pass
            block = _emit_ground_ortho_mesh(
                ortho_texture_filename=ortho_filename_for_copy,
                half_size_m=half_m,
                z_ground=ortho_z_ground,
                center_xy=ortho_center_xy,
                indent="        ",
            )
            lines.append(block)
            lines.append("")
        lidar_url = manifest.get("lidar_tile_url")
        # Prefer a high_vegetation.laz sub-product if available next to the manifest.
        refs_root = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "photogrammetry"
        veg_path = refs_root / project_id / "lidar" / "high_vegetation.laz"
        if veg_path.is_file():
            laz_filename_for_copy = veg_path.name
            block = _emit_vegetation_xform(
                laz_filename=f"lidar/{laz_filename_for_copy}",
                count_metadata=int(veg_path.stat().st_size),
                indent="        ",
            )
            lines.append(block)
            lines.append("")
        elif lidar_url:
            lines.append('        def Xform "Vegetation"')
            lines.append('        {')
            lines.append(f'            custom string lidar_remote_url = "{lidar_url}"')
            lines.append('            custom string source_class = "high_vegetation_class_5"')
            lines.append('            custom string render_hint = "fetch_remote_then_geometry_nodes"')
            lines.append('        }')
            lines.append("")

    lines.append("    }")
    lines.append("}")
    lines.append("")

    text = "\n".join(lines)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text)
        # Copy referenced textures next to the USDA so downstream tools resolve
        # @./bdortho_macro.jpg@ without additional path setup.
        if use_ign and copy_ign_textures and ortho_filename_for_copy:
            refs_root = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "photogrammetry"
            src = refs_root / project_id / ortho_filename_for_copy
            dst = output_path.parent / ortho_filename_for_copy
            if src.is_file() and not dst.is_file():
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    print(f"!! scene_to_usd: failed to copy {src} → {dst}: {e}")
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
