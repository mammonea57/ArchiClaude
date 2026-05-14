"""Paint ONLY the enduit_blanc mesh in bright magenta, everything else
grey. If we see large magenta surfaces forming building walls, the
geometry is there. If we see only tiny strips of magenta, the wall
mesh in the USD is genuinely sparse."""
import unreal
from pathlib import Path

# Build dynamic MIDs with vivid colors
base = unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultMaterial")
brique_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_brique_rouge")
enduit_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_enduit_blanc")
verre_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_verre")
balcon_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_balcon_concrete")

# Override FallbackTint per-instance with very different colors
def tint(mi, r, g, b):
    unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
        mi, "FallbackTint", unreal.LinearColor(r, g, b, 1.0)
    )

# Force fallback tints with extreme colors so each material is unmistakable
# enduit_blanc → magenta
# brique_rouge → bright red
# verre → cyan
# balcon_concrete → bright yellow
tint(enduit_mat, 1.0, 0.0, 1.0)
tint(brique_mat, 1.0, 0.2, 0.2)
tint(verre_mat, 0.0, 1.0, 1.0)
tint(balcon_mat, 1.0, 1.0, 0.0)

# Also override the textured Albedo override with the white default so the
# texture doesn't drown out the tint. To do this we need to clear the
# texture override. set_material_instance_texture_parameter_value with None
# may work, or directly clear the texture_parameter_values array.
def clear_texture(mi):
    try:
        mi.set_editor_property("texture_parameter_values", [])
    except Exception:
        pass

clear_texture(enduit_mat)
clear_texture(brique_mat)
clear_texture(verre_mat)
clear_texture(balcon_mat)

# Re-apply our materials to all
try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

def walk(actor):
    try:
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = c.get_editor_property("static_mesh")
            if mesh is None:
                continue
            name = mesh.get_name().lower()
            if "cinecam" in name:
                continue
            base = name.replace("sm_", "")
            m = unreal.EditorAssetLibrary.load_asset(f"/Game/AC/Materials/M_{base}")
            if m is not None:
                for i in range(max(1, c.get_num_materials())):
                    c.set_material(i, m)
    except Exception:
        pass
    try:
        for child in actor.get_attached_actors():
            walk(child)
    except Exception:
        pass

for a in actors:
    walk(a)

# Render
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
vp_loc, vp_rot = ues.get_level_viewport_camera_info()
world = ues.get_editor_world()
rt = unreal.RenderingLibrary.create_render_target2d(
    world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8
)
cap = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.SceneCapture2D, vp_loc, vp_rot
)
cc = cap.capture_component2d
cc.set_editor_property("texture_target", rt)
cc.set_editor_property("fov_angle", 65.0)
cc.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
cc.capture_scene()
out = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_isolate.png")
unreal.RenderingLibrary.export_render_target(None, rt, str(out.parent), out.name)
cap.destroy_actor()
unreal.log(f"done → {out}")
