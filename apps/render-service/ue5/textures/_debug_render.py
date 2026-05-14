"""Capture the current level state (with WorldGridMaterial applied)
without re-running the import pipeline. We want to see whether the
mesh geometry is actually located in world space."""
import unreal
from pathlib import Path

OUT_PATH = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_worldgrid.png")
WIDTH = 1024
HEIGHT = 1024

# Use viewport pose for the capture
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
vp_loc, vp_rot = ues.get_level_viewport_camera_info()
unreal.log(f"viewport pose : loc={vp_loc} rot={vp_rot}")

# Make render target
world = ues.get_editor_world()
rt = unreal.RenderingLibrary.create_render_target2d(
    world, WIDTH, HEIGHT, unreal.TextureRenderTargetFormat.RTF_RGBA8
)

# Spawn SceneCapture2D at viewport pose
cap = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.SceneCapture2D, vp_loc, vp_rot
)
cc = cap.capture_component2d
cc.set_editor_property("texture_target", rt)
cc.set_editor_property("fov_angle", 65.0)
cc.set_editor_property(
    "capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR
)
cc.capture_scene()

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
unreal.RenderingLibrary.export_render_target(
    None, rt, str(OUT_PATH.parent), OUT_PATH.name
)
cap.destroy_actor()
unreal.log(f"debug render done → {OUT_PATH}")
