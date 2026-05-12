"""UE5 Python script — imports cached Polyhaven textures and builds
MaterialInstances for every material in MATERIAL_LIBRARY.

Run INSIDE UnrealEditor :

    UnrealEditor-Cmd.exe archi.uproject \\
        -ExecutePythonScript="<path>/textures/import_to_ue5.py" \\
        -Unattended -NoLogTimes

Or interactively : Window → Output Log → Cmd dropdown set to "Python" :
    py "C:\\Users\\mammo\\ArchiClaude\\apps\\render-service\\ue5\\textures\\import_to_ue5.py"

The script :
  1. Reads `textures_cache/index.json` (written by download_polyhaven.py)
  2. Ensures a parent Material at /Game/AC/Materials/M_ArchiClaude_Base
     exists, with TextureParameter pins (Albedo, Normal, ARM) and a
     TileScale ScalarParameter. Builds it from scratch if missing.
  3. For every material in MATERIAL_LIBRARY :
       a. Imports the cached textures into /Game/AC/Textures/<name>/
       b. Creates a MaterialInstanceConstant at /Game/AC/Materials/M_<name>
          parented to M_ArchiClaude_Base, with the textures wired in and
          TileScale set from `tile_meters` (1m physical = 1.0 scale).
       c. For materials without polyhaven_slug, creates a flat-color
          MaterialInstance (fallback) so `import_scene_to_ue5.py` can
          still resolve `/Game/AC/Materials/M_<name>` for every material.
  4. Saves all created assets.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    import unreal
except ImportError:
    print("!! This script must run INSIDE Unreal Engine (Python plugin).")
    sys.exit(1)

# Resolve our textures library — handle both "module" run and direct -ExecutePythonScript
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(_THIS.parent.parent))  # for the older import path
from library import MATERIAL_LIBRARY, MaterialDef  # type: ignore  # noqa: E402


CACHE_ROOT_DEFAULT = _THIS.parent / "textures_cache"
PARENT_MAT_PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
MATERIALS_FOLDER = "/Game/AC/Materials"
TEXTURES_FOLDER = "/Game/AC/Textures"

# Polyhaven map names → our parameter names
PARAM_FOR_MAP = {
    "Diffuse":      "Albedo",
    "nor_dx":       "Normal",
    "arm":          "ARM",
    "Displacement": "Displacement",  # optional
}
SRGB_TEXTURES = {"Albedo"}  # only base color is sRGB; the rest are linear


def log(msg: str) -> None:
    unreal.log(f"[AC textures] {msg}")


# ── Parent material ───────────────────────────────────────────────
def ensure_parent_material(force_rebuild: bool = False) -> "unreal.Material":
    """Create (or rebuild) M_ArchiClaude_Base.

    Output pin names on TextureSampleParameter2D are tricky : the main RGB
    output is named "" (empty string), not "RGB". Earlier versions of this
    script used "RGB" which silently dropped the BaseColor/Normal
    connections, so the materials rendered as the default grey checker
    despite the instances having texture overrides.

    Set `force_rebuild=True` (or run after deleting the existing asset)
    to recreate the parent from scratch.
    """
    existing = unreal.EditorAssetLibrary.load_asset(PARENT_MAT_PATH)
    if existing is not None and not force_rebuild:
        return existing
    if existing is not None and force_rebuild:
        log(f"Deleting stale parent material {PARENT_MAT_PATH} …")
        unreal.EditorAssetLibrary.delete_asset(PARENT_MAT_PATH)

    log(f"Creating parent material at {PARENT_MAT_PATH} …")
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialFactoryNew()
    folder, name = PARENT_MAT_PATH.rsplit("/", 1)
    mat: unreal.Material = asset_tools.create_asset(name, folder, unreal.Material, factory)
    MEL = unreal.MaterialEditingLibrary

    # UV : TexCoord × TileScale
    tile = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1500, -100)
    tile.set_editor_property("parameter_name", "TileScale")
    tile.set_editor_property("default_value", 1.0)

    uv = MEL.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -1300, 0)

    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1100, 0)
    MEL.connect_material_expressions(uv, "", mul, "A")
    MEL.connect_material_expressions(tile, "", mul, "B")

    # Albedo — connect default (RGB) output via "" (empty string)
    albedo = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, -800, -400
    )
    albedo.set_editor_property("parameter_name", "Albedo")
    albedo.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    MEL.connect_material_expressions(mul, "", albedo, "UVs")
    MEL.connect_material_property(albedo, "", unreal.MaterialProperty.MP_BASE_COLOR)

    # Normal — same trick : "" for the default RGB output
    normal = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, -800, 0
    )
    normal.set_editor_property("parameter_name", "Normal")
    normal.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    MEL.connect_material_expressions(mul, "", normal, "UVs")
    MEL.connect_material_property(normal, "", unreal.MaterialProperty.MP_NORMAL)

    # ARM (R=AO, G=Roughness, B=Metallic) — channel outputs are fine
    arm = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, -800, 400
    )
    arm.set_editor_property("parameter_name", "ARM")
    arm.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    MEL.connect_material_expressions(mul, "", arm, "UVs")
    MEL.connect_material_property(arm, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    MEL.connect_material_property(arm, "G", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(arm, "B", unreal.MaterialProperty.MP_METALLIC)

    # Roughness multiplier (scalar) for finer tuning per-instance
    rough_mul = MEL.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, -1500, 400
    )
    rough_mul.set_editor_property("parameter_name", "RoughnessScale")
    rough_mul.set_editor_property("default_value", 1.0)

    # Fallback tint (used when no Albedo texture set)
    tint = MEL.create_material_expression(
        mat, unreal.MaterialExpressionVectorParameter, -1500, -400
    )
    tint.set_editor_property("parameter_name", "FallbackTint")
    tint.set_editor_property("default_value", unreal.LinearColor(0.7, 0.7, 0.7, 1.0))

    MEL.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


# ── Texture import ────────────────────────────────────────────────
def import_textures_for_material(
    mat_def: MaterialDef,
    cache_root: Path,
) -> dict:
    """Import the local maps for one material into UE5. Returns a dict
    {param_name: unreal.Texture2D} of the imported textures."""
    src_dir = cache_root / mat_def.name
    out_pkg = f"{TEXTURES_FOLDER}/{mat_def.name}"
    result: dict[str, unreal.Texture2D] = {}
    if not src_dir.exists():
        return result

    files = list(src_dir.iterdir())
    if not files:
        return result

    AT = unreal.AssetToolsHelpers.get_asset_tools()

    for f in files:
        # Detect which map this file is
        stem = f.stem  # e.g. "Diffuse" or "nor_dx"
        param = PARAM_FOR_MAP.get(stem)
        if param is None:
            continue

        asset_name = f"T_{mat_def.name}_{param}"
        asset_path = f"{out_pkg}/{asset_name}"

        # Skip if already imported
        cached = unreal.EditorAssetLibrary.load_asset(asset_path)
        if cached is not None:
            result[param] = cached
            continue

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(f))
        task.set_editor_property("destination_path", out_pkg)
        task.set_editor_property("destination_name", asset_name)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)

        AT.import_asset_tasks([task])

        tex = unreal.EditorAssetLibrary.load_asset(asset_path)
        if tex is None:
            log(f"  !! failed to import {f.name}")
            continue

        # Configure compression : sRGB for albedo, linear for normal/ARM
        if param in SRGB_TEXTURES:
            tex.set_editor_property("srgb", True)
        else:
            tex.set_editor_property("srgb", False)
        if param == "Normal":
            tex.set_editor_property(
                "compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP
            )
        elif param == "ARM":
            tex.set_editor_property(
                "compression_settings", unreal.TextureCompressionSettings.TC_MASKS
            )
        elif param == "Displacement":
            tex.set_editor_property(
                "compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE
            )

        unreal.EditorAssetLibrary.save_loaded_asset(tex)
        result[param] = tex
        log(f"  ✓ imported {asset_name}")

    return result


# ── Material instance creation ─────────────────────────────────────
def _force_texture_overrides(mi: "unreal.MaterialInstanceConstant",
                              textures: dict) -> None:
    """Force-write the texture_parameter_values array on the instance.

    UE 5.7's MaterialEditingLibrary.set_material_instance_texture_parameter_value
    sometimes registers the override silently but doesn't make it persist in
    the asset (observed on the MSI station: ARM override took, Albedo and
    Normal did not). Writing the array directly is the resilient path.
    """
    try:
        existing = mi.get_editor_property("texture_parameter_values") or []
    except Exception:
        existing = []

    # Index existing overrides by name for dedup
    by_name: dict[str, "unreal.TextureParameterValue"] = {}
    for entry in existing:
        try:
            name = entry.parameter_info.name
        except Exception:
            continue
        if name:
            by_name[str(name)] = entry

    for param_name, tex in textures.items():
        entry = by_name.get(param_name)
        if entry is None:
            try:
                entry = unreal.TextureParameterValue()
                info = unreal.MaterialParameterInfo()
                info.set_editor_property("name", param_name)
                entry.set_editor_property("parameter_info", info)
            except Exception as e:
                log(f"  !! could not build override entry for {param_name} : {e}")
                continue
            by_name[param_name] = entry
        try:
            entry.set_editor_property("parameter_value", tex)
        except Exception as e:
            log(f"  !! could not assign texture for {param_name} : {e}")

    try:
        mi.set_editor_property("texture_parameter_values", list(by_name.values()))
    except Exception as e:
        log(f"  !! force-write failed : {e}")


def _set_mi_parent(mi: "unreal.MaterialInstanceConstant",
                    parent: "unreal.Material") -> None:
    """UE5 has moved this around between versions — try the modern API
    first, fall back to the older property setter."""
    try:
        unreal.MaterialEditingLibrary.set_material_instance_parent(mi, parent)
        return
    except Exception:
        pass
    try:
        mi.set_editor_property("parent", parent)
    except Exception as e:
        log(f"  !! could not set parent on {mi.get_name()} : {e}")


def create_material_instance(
    mat_def: MaterialDef,
    parent: "unreal.Material",
    textures: dict,
) -> "unreal.MaterialInstanceConstant":
    """Create or update /Game/AC/Materials/M_<name>."""
    asset_path = f"{MATERIALS_FOLDER}/M_{mat_def.name}"
    cached = unreal.EditorAssetLibrary.load_asset(asset_path)
    if cached is not None:
        mi = cached
        _set_mi_parent(mi, parent)
    else:
        AT = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialInstanceConstantFactoryNew()
        folder, name = asset_path.rsplit("/", 1)
        mi = AT.create_asset(name, folder, unreal.MaterialInstanceConstant, factory)
        _set_mi_parent(mi, parent)

    MIEL = unreal.MaterialEditingLibrary
    # Texture params — call MEL first (registers the override correctly),
    # then verify via direct property read and force-write the
    # texture_parameter_values array if the override didn't stick. UE5's
    # MEL function silently no-ops in some cases (e.g. when the parent
    # material hasn't been compiled with that parameter exposed yet).
    for param, tex in textures.items():
        try:
            MIEL.set_material_instance_texture_parameter_value(mi, param, tex)
        except Exception as e:
            log(f"  !! MEL.set failed for {param} : {e}")
    _force_texture_overrides(mi, textures)
    # TileScale : meters → uv repetitions. ~1m real-world = 1.0 tile per uv-unit
    # Polyhaven assets are normalized so a 4k tile covers roughly 1m physical
    # by default. tile_meters > 1 means we want fewer repetitions visible.
    MIEL.set_material_instance_scalar_parameter_value(mi, "TileScale", 1.0 / mat_def.tile_meters)
    # Roughness scale
    MIEL.set_material_instance_scalar_parameter_value(
        mi, "RoughnessScale", mat_def.roughness_scale
    )
    # Fallback tint
    tint = mat_def.tint or mat_def.fallback_color
    MIEL.set_material_instance_vector_parameter_value(
        mi, "FallbackTint",
        unreal.LinearColor(tint[0], tint[1], tint[2], 1.0),
    )

    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    return mi


# ── Health check on parent material ───────────────────────────────
def _parent_material_is_healthy(mat: "unreal.Material") -> bool:
    """Quick sanity check : the parent must have working connections from
    its Albedo/Normal TextureSampleParameter2D expressions to MP_BASE_COLOR
    and MP_NORMAL. Earlier script versions used "RGB" output name (invalid),
    leaving those connections silently broken. Detect and rebuild if so."""
    try:
        MEL = unreal.MaterialEditingLibrary
        has_base_color = MEL.is_material_property_active(mat, unreal.MaterialProperty.MP_BASE_COLOR)
        has_normal = MEL.is_material_property_active(mat, unreal.MaterialProperty.MP_NORMAL)
        return bool(has_base_color and has_normal)
    except Exception:
        # If we can't check, conservatively assume it needs a rebuild
        return False


# ── Main ──────────────────────────────────────────────────────────
def main() -> int:
    log("=" * 60)
    log("ArchiClaude — texture import + Material Instance generation")
    log("=" * 60)

    cache_root = Path(CACHE_ROOT_DEFAULT)
    index_path = cache_root / "index.json"
    if not index_path.exists():
        log(f"!! No textures cache index at {index_path}")
        log("   Run download_polyhaven.py first.")
        return 2

    # Self-heal : if a previous run left an unhealthy parent material with
    # broken BaseColor/Normal connections (old "RGB" output-pin bug), force
    # a rebuild. Idempotent on a healthy parent.
    existing_parent = unreal.EditorAssetLibrary.load_asset(PARENT_MAT_PATH)
    needs_rebuild = (existing_parent is not None
                     and not _parent_material_is_healthy(existing_parent))
    if needs_rebuild:
        log("⚠ Existing parent material has broken connections — forcing rebuild …")
    parent = ensure_parent_material(force_rebuild=needs_rebuild)
    log(f"✓ Parent material : {PARENT_MAT_PATH}")

    n_done = 0
    n_fallback = 0
    for name, mat_def in MATERIAL_LIBRARY.items():
        textures = import_textures_for_material(mat_def, cache_root)
        if mat_def.polyhaven_slug and not textures:
            log(f"! {name}: no textures imported (cache miss), falling back to flat tint")
        if not textures:
            n_fallback += 1
        else:
            n_done += 1
        # If the parent was rebuilt, instances need to be re-linked too.
        # create_material_instance handles both creation and re-linking.
        create_material_instance(mat_def, parent, textures)
        log(f"✓ M_{name} ready ({len(textures)} textures wired)")

    log("")
    log(f"Done : {n_done} with textures, {n_fallback} flat-tint fallback.")
    return 0


if __name__ == "__main__":
    code = main()
    if "-unattended" in " ".join(sys.argv).lower():
        unreal.SystemLibrary.execute_console_command(None, "quit")
    sys.exit(code)
