"""Boost the SkyLight intensity to fill shadow areas, change sun
direction to match the camera angle so walls facing the camera are lit.
Then re-render."""
import unreal
from pathlib import Path

try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

for a in actors:
    if isinstance(a, unreal.DirectionalLight):
        # Aim sun from a high front-right angle so the walls facing the
        # camera (which is at +X-Y looking back at origin) catch direct
        # light. pitch -55 = high noon-ish, yaw -50 = from NE quadrant.
        a.set_actor_rotation(unreal.Rotator(-55, -50, 0), False)
        a.light_component.set_intensity(8.0)
        unreal.log(f"sun rotated + intensity 8.0")
    elif isinstance(a, unreal.SkyLight):
        # Big sky light so shadowed sides are not pitch black.
        a.light_component.set_intensity(4.0)
        try:
            a.light_component.set_editor_property("real_time_capture", True)
            a.light_component.recapture_sky()
        except Exception:
            pass
        unreal.log("skylight intensity 4.0")

# Re-apply our M_xxx materials too (in case the previous test left
# M_brique_rouge on everything).
for a in actors:
    pass  # skip — we'll do it in walk

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
            mat_path = f"/Game/AC/Materials/M_{base}"
            mat = unreal.EditorAssetLibrary.load_asset(mat_path)
            if mat is None:
                continue
            for i in range(max(1, c.get_num_materials())):
                c.set_material(i, mat)
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
out = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_brighter.png")
unreal.RenderingLibrary.export_render_target(None, rt, str(out.parent), out.name)
cap.destroy_actor()
unreal.log(f"done → {out}")
