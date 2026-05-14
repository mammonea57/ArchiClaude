"""Reapply our M_<name> materials (which the debug pass overwrote with
WorldGridMaterial) and render at the SAME viewport pose so we can
A/B compare the grid version against the textured version."""
import unreal
from pathlib import Path

# 1) Reapply materials
try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

def walk(actor, found):
    try:
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = c.get_editor_property("static_mesh")
            if mesh is None:
                continue
            found.append(c)
    except Exception:
        pass
    try:
        for child in actor.get_attached_actors():
            walk(child, found)
    except Exception:
        pass

components = []
for a in actors:
    walk(a, components)

n_applied = 0
for c in components:
    mesh = c.get_editor_property("static_mesh")
    name = mesh.get_name().lower()
    if "cinecam" in name:
        continue
    # Mesh name is SM_<material> — strip SM_ prefix
    base = name.replace("sm_", "")
    mat_path = f"/Game/AC/Materials/M_{base}"
    mat = unreal.EditorAssetLibrary.load_asset(mat_path)
    if mat is None:
        unreal.log_warning(f"  no material {mat_path}")
        continue
    n_slots = c.get_num_materials()
    for i in range(max(1, n_slots)):
        c.set_material(i, mat)
        n_applied += 1
unreal.log(f"re-applied {n_applied} material slot(s)")

# 2) Render at viewport pose
OUT_PATH = Path(r"C:\Users\mammo\ArchiClaude\refs\renders\_debug_textured.png")
WIDTH = 1024
HEIGHT = 1024

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
vp_loc, vp_rot = ues.get_level_viewport_camera_info()
unreal.log(f"viewport pose : loc={vp_loc} rot={vp_rot}")

world = ues.get_editor_world()
rt = unreal.RenderingLibrary.create_render_target2d(
    world, WIDTH, HEIGHT, unreal.TextureRenderTargetFormat.RTF_RGBA8
)

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
unreal.log(f"textured render done → {OUT_PATH}")
