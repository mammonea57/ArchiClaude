"""Test : disable USD prim merging, reload stage, re-check tree."""
import time
import unreal

try:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = subsystem.get_all_level_actors()
except Exception:
    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()

stage_actor = None
for a in all_actors:
    if isinstance(a, unreal.UsdStageActor):
        stage_actor = a
        break
if stage_actor is None:
    unreal.log("!! no UsdStageActor — spawning a fresh one")
    raise SystemExit(1)

# Remember the current root_layer
root_layer = stage_actor.get_editor_property("root_layer")
unreal.log(f"current root_layer : {root_layer}")

# Clear root_layer so the changes to merge options actually take effect
# when we re-assign it.
stage_actor.set_editor_property("root_layer", unreal.FilePath(""))
time.sleep(1)

# Tune merge options
stage_actor.set_editor_property("kinds_to_collapse", 0)
stage_actor.set_editor_property("merge_identical_material_slots", False)
unreal.log("set kinds_to_collapse=0, merge_identical_material_slots=False")

# Reload the stage
stage_actor.set_editor_property("root_layer", root_layer)
time.sleep(4)

# Walk the tree again
def walk(actor, depth: int = 0):
    indent = "  " * depth
    cls = type(actor).__name__
    label = actor.get_actor_label()
    sm_comps = []
    try:
        sm_comps = list(actor.get_components_by_class(unreal.StaticMeshComponent))
    except Exception:
        pass
    info = ""
    for c in sm_comps:
        try:
            mesh = c.get_editor_property("static_mesh")
            n_slots = c.get_num_materials() if mesh else 0
            info += f" [mesh:{mesh.get_name() if mesh else 'None'} slots:{n_slots}]"
        except Exception:
            pass
    unreal.log(f"{indent}{cls} label='{label}'{info}")
    try:
        for child in actor.get_attached_actors():
            walk(child, depth + 1)
    except Exception:
        pass

unreal.log("--- Stage tree after reload ---")
walk(stage_actor)
