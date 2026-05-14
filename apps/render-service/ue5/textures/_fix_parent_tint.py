"""Patch the parent material so the FallbackTint vector parameter
actually affects the rendered Albedo. Currently FallbackTint is wired
into the material as an unused parameter — meaning fallback materials
(verre, zinc_anthracite, fer_forge, road_paint_white) end up
rendering with the parent's default Albedo texture (T_brique_rouge_*),
which makes them look brick-red instead of their intended flat color.

Fix : insert a Multiply node between the Albedo TextureSampleParameter2D
output and the BaseColor pin, with FallbackTint as the other input.
For textured materials we'll keep FallbackTint at white (1,1,1), so
the multiply is a no-op. For fallback materials, set FallbackTint to
the intended color (0.10, 0.18, 0.28 for verre, etc.) and the Albedo
becomes (default_brique_red × tint) which approximates the tint when
tint is dark.

Even better : also set the Albedo default texture to a pure-white
engine texture instead of T_brique_rouge — that way fallback tints
display CORRECTLY (white × tint = tint) instead of muddy red × tint.
"""
import unreal

MAT_PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
mat = unreal.EditorAssetLibrary.load_asset(MAT_PATH)
if mat is None:
    raise SystemExit(f"!! parent not found : {MAT_PATH}")

MEL = unreal.MaterialEditingLibrary


# 1. Find Albedo TextureSampleParameter2D
albedo_node = None
tint_node = None
for prop in (
    unreal.MaterialProperty.MP_BASE_COLOR,
    unreal.MaterialProperty.MP_NORMAL,
    unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
):
    n = MEL.get_material_property_input_node(mat, prop)
    if n is None:
        continue
    try:
        name = str(n.get_editor_property("parameter_name"))
    except Exception:
        continue
    if name == "Albedo" and prop == unreal.MaterialProperty.MP_BASE_COLOR:
        albedo_node = n

# Find FallbackTint among the loose nodes (it's not currently connected)
# We can iterate the material's expressions through MEL.get_used_textures
# doesn't work; instead use MaterialEditingLibrary.get_num_material_expressions
# and access by index via... actually we'll just rely on get_material_property_input_node
# for the wired ones, and re-create the tint param if it doesn't auto-find.

# Try to find the tint by walking : check if there's an unconnected VectorParameter
# named "FallbackTint" by re-creating one (UE will de-dup by parameter_name when
# resolving in the MaterialInstance, so adding a fresh one is fine).
if albedo_node is None:
    raise SystemExit("!! could not find Albedo expression")

# 2. Set default texture for Albedo to a WHITE engine texture so fallback
# tints display as their actual color (white × tint = tint).
WHITE_PATH = "/Engine/EngineMaterials/DefaultWhiteGrid"  # may not exist
white_tex = unreal.EditorAssetLibrary.load_asset(WHITE_PATH)
if white_tex is None:
    # Try a few other known engine white textures
    for p in (
        "/Engine/EngineResources/WhiteSquareTexture",
        "/Engine/EngineResources/Black",
        "/Engine/EngineMaterials/WorldGridMaterial",
    ):
        white_tex = unreal.EditorAssetLibrary.load_asset(p)
        if white_tex is not None and isinstance(white_tex, unreal.Texture2D):
            unreal.log(f"  using {p} as white default")
            break
        white_tex = None

if white_tex is not None:
    albedo_node.set_editor_property("texture", white_tex)
    unreal.log(f"  ✓ set Albedo default texture to white")

# 3. Disconnect BaseColor and rewire through a Multiply with FallbackTint
try:
    MEL.disconnect_material_property(mat, unreal.MaterialProperty.MP_BASE_COLOR)
except Exception:
    pass

mul = MEL.create_material_expression(
    mat, unreal.MaterialExpressionMultiply, -300, -400
)
tint = MEL.create_material_expression(
    mat, unreal.MaterialExpressionVectorParameter, -800, -650
)
tint.set_editor_property("parameter_name", "FallbackTint")
tint.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

MEL.connect_material_expressions(albedo_node, "RGB", mul, "A")
MEL.connect_material_expressions(tint, "", mul, "B")
MEL.connect_material_property(mul, "", unreal.MaterialProperty.MP_BASE_COLOR)

MEL.recompile_material(mat)
unreal.EditorAssetLibrary.save_loaded_asset(mat)
unreal.log("✓ parent material patched : Albedo × FallbackTint")
