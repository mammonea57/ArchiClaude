"""Diagnostic v2 : use UE 5.7-compatible APIs."""
import unreal

PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
mat = unreal.EditorAssetLibrary.load_asset(PATH)
if mat is None:
    unreal.log_error(f"NOT FOUND : {PATH}")
    raise SystemExit(1)

MEL = unreal.MaterialEditingLibrary
unreal.log("--- Parent material state ---")

n_exprs = MEL.get_num_material_expressions(mat)
unreal.log(f"num_material_expressions = {n_exprs}")

textures = list(MEL.get_used_textures(mat))
unreal.log(f"used_textures = {len(textures)}")
for t in textures:
    unreal.log(f"  - {t.get_path_name()}")

scalars = list(MEL.get_scalar_parameter_names(mat))
unreal.log(f"scalar_parameter_names = {list(scalars)}")

# Connection state per material property
for prop_name in ("MP_BASE_COLOR", "MP_NORMAL", "MP_AMBIENT_OCCLUSION",
                   "MP_ROUGHNESS", "MP_METALLIC"):
    prop = getattr(unreal.MaterialProperty, prop_name)
    try:
        node = MEL.get_material_property_input_node(mat, prop)
        out_name = MEL.get_material_property_input_node_output_name(mat, prop)
    except Exception as e:
        node, out_name = f"err: {e}", "?"
    unreal.log(f"  {prop_name:25s} input_node={node} out='{out_name}'")
