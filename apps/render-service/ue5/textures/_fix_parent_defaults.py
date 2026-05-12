"""Fix M_ArchiClaude_Base : set sensible default textures on the Normal
and ARM TextureSampleParameter2D nodes so the shader compiles cleanly.

UE5 was complaining :
  [SM6] Sampler type is Normal, should be Color for DefaultTexture
  [SM6] Sampler type is Linear Color, should be Color for DefaultTexture

→ The expressions have sampler_type=Normal / LinearColor but their
implicit default texture is the engine DefaultTexture (a Color asset),
which causes the parent material's shader to fail to compile cleanly
and renders as the world-grid checker. Once the parent is broken, no
instance override can save the visual.

Fix : point each expression at one of our already-imported textures
that matches its sampler_type (T_brique_rouge_Normal, T_brique_rouge_ARM).
Instances still override these defaults per-material.
"""
import unreal

MAT_PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
DEFAULT_ALBEDO = "/Game/AC/Textures/brique_rouge/T_brique_rouge_Albedo"
DEFAULT_NORMAL = "/Game/AC/Textures/brique_rouge/T_brique_rouge_Normal"
DEFAULT_ARM    = "/Game/AC/Textures/brique_rouge/T_brique_rouge_ARM"

mat = unreal.EditorAssetLibrary.load_asset(MAT_PATH)
if mat is None:
    unreal.log_error(f"!! parent not found : {MAT_PATH}")
    raise SystemExit(1)

MEL = unreal.MaterialEditingLibrary


def load(path: str):
    t = unreal.EditorAssetLibrary.load_asset(path)
    if t is None:
        unreal.log_warning(f"  texture missing : {path}")
    return t


def get_param_expression(material, param_name: str):
    """Walk inputs of all standard material properties to find the
    TextureSampleParameter2D node with the given parameter_name."""
    for prop in (
        unreal.MaterialProperty.MP_BASE_COLOR,
        unreal.MaterialProperty.MP_NORMAL,
        unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
        unreal.MaterialProperty.MP_ROUGHNESS,
        unreal.MaterialProperty.MP_METALLIC,
    ):
        node = MEL.get_material_property_input_node(material, prop)
        if node is None:
            continue
        try:
            n = str(node.get_editor_property("parameter_name"))
        except Exception:
            continue
        if n == param_name:
            return node
    return None


def assign_default(material, param_name: str, texture_path: str) -> bool:
    tex = load(texture_path)
    if tex is None:
        return False
    node = get_param_expression(material, param_name)
    if node is None:
        unreal.log_warning(f"  no expression for parameter '{param_name}'")
        return False
    try:
        node.set_editor_property("texture", tex)
        unreal.log(f"  ✓ {param_name} default → {texture_path}")
        return True
    except Exception as e:
        unreal.log_error(f"  ✗ set_editor_property(texture) failed for {param_name} : {e}")
        return False


unreal.log(f"--- Fixing default textures on {MAT_PATH} ---")
assign_default(mat, "Albedo", DEFAULT_ALBEDO)
assign_default(mat, "Normal", DEFAULT_NORMAL)
assign_default(mat, "ARM", DEFAULT_ARM)

unreal.log("Recompiling …")
MEL.recompile_material(mat)
unreal.EditorAssetLibrary.save_loaded_asset(mat)
unreal.log("✓ done")
