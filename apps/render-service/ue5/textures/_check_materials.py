"""Inspect the actual state of every M_xxx material instance and the
parent material's blend mode / domain / opacity properties."""
import unreal

PARENT_PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
parent = unreal.EditorAssetLibrary.load_asset(PARENT_PATH)
if parent is None:
    raise SystemExit("no parent")

# Parent material blend mode + domain + opacity
for prop in ("blend_mode", "material_domain", "shading_model", "two_sided",
              "opacity_mask_clip_value", "dithered_lod_transition"):
    try:
        v = parent.get_editor_property(prop)
        unreal.log(f"parent.{prop} = {v}")
    except Exception as e:
        unreal.log(f"parent.{prop} : err {e}")

# Texture parameters on instances
MEL = unreal.MaterialEditingLibrary
for path in unreal.EditorAssetLibrary.list_assets("/Game/AC/Materials"):
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if not isinstance(asset, unreal.MaterialInstanceConstant):
        continue
    unreal.log(f"--- {asset.get_name()} ---")
    for param in ("Albedo", "Normal", "ARM"):
        try:
            tex = MEL.get_material_instance_texture_parameter_value(asset, param)
            tex_name = tex.get_path_name() if tex else "None"
        except Exception as e:
            tex_name = f"err {e}"
        unreal.log(f"  {param:8s} → {tex_name}")
    for param in ("FallbackTint",):
        try:
            v = MEL.get_material_instance_vector_parameter_value(asset, param)
            unreal.log(f"  {param:8s} → ({v.r:.2f},{v.g:.2f},{v.b:.2f},{v.a:.2f})")
        except Exception as e:
            unreal.log(f"  {param:8s} → err {e}")
