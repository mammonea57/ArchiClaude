"""Apply M_brique_rouge (our working textured material) to every mesh
in the scene. If the building shows solid red bricks everywhere with
no see-through, then geometry+material combo works and our previous
"see through" was due to specific fallback materials being misconfigured.
If still see-through, there's an opacity bug in the parent material."""
import unreal
from pathlib import Path

red_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_brique_rouge")
if red_mat is None:
    unreal.log_error("!! M_brique_rouge not found")
    raise SystemExit(1)
unreal.log(f"using {red_mat.get_path_name()}")

try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

n = 0
def walk(actor):
    global n
    try:
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = c.get_editor_property("static_mesh")
            if mesh is None:
                continue
            if "cinecam" in mesh.get_name().lower():
                continue
            for i in range(max(1, c.get_num_materials())):
                c.set_material(i, red_mat)
                n += 1
    except Exception as e:
        unreal.log(f"err : {e}")
    try:
        for child in actor.get_attached_actors():
            walk(child)
    except Exception:
        pass
for a in actors:
    walk(a)
unreal.log(f"applied M_brique_rouge on {n} slots")

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

out = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_solid.png")
unreal.RenderingLibrary.export_render_target(None, rt, str(out.parent), out.name)
cap.destroy_actor()
unreal.log(f"done → {out}")
