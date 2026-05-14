"""Position camera head-on the east wall (max X) of the building, 30m
back, mid-height. If walls are real and visible, we should see a
solid white plaster wall filling most of the frame."""
import unreal
from pathlib import Path

# Camera positioned at +X far enough to be outside building
cam_loc = unreal.Vector(6500, 0, 800)         # 30m past east edge, building mid
cam_target = unreal.Vector(0, 0, 800)
fwd = cam_target - cam_loc
cam_rot = unreal.MathLibrary.find_look_at_rotation(cam_loc, cam_target)
unreal.log(f"head-on cam at {cam_loc} rot={cam_rot}")

# Render
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
rt = unreal.RenderingLibrary.create_render_target2d(
    world, 1024, 1024, unreal.TextureRenderTargetFormat.RTF_RGBA8
)
cap = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.SceneCapture2D, cam_loc, cam_rot
)
cc = cap.capture_component2d
cc.set_editor_property("texture_target", rt)
cc.set_editor_property("fov_angle", 65.0)
cc.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
cc.capture_scene()
out = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_headon.png")
unreal.RenderingLibrary.export_render_target(None, rt, str(out.parent), out.name)
cap.destroy_actor()
unreal.log(f"done → {out}")
