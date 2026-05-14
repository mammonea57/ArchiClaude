"""Enable two-sided rendering on the parent material. If walls exist
with inverted normals, they'll become visible from outside."""
import unreal
from pathlib import Path

PARENT_PATH = "/Game/AC/Materials/M_ArchiClaude_Base"
mat = unreal.EditorAssetLibrary.load_asset(PARENT_PATH)
unreal.log(f"two_sided before : {mat.get_editor_property('two_sided')}")
mat.set_editor_property("two_sided", True)
unreal.MaterialEditingLibrary.recompile_material(mat)
unreal.EditorAssetLibrary.save_loaded_asset(mat)
unreal.log(f"two_sided after  : {mat.get_editor_property('two_sided')}")

# Render at viewport pose
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
out = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_twosided.png")
unreal.RenderingLibrary.export_render_target(None, rt, str(out.parent), out.name)
cap.destroy_actor()
unreal.log(f"done → {out}")
