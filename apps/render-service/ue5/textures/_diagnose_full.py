"""Full diagnostic of the current level state — no screenshots needed."""
import unreal

try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

unreal.log(f"--- Top-level actors : {len(actors)} ---")
classes: dict[str, int] = {}
stage_actors: list = []
for a in actors:
    cls = type(a).__name__
    classes[cls] = classes.get(cls, 0) + 1
    if isinstance(a, unreal.UsdStageActor):
        stage_actors.append(a)
for cls, n in sorted(classes.items()):
    unreal.log(f"  {n:4d}  {cls}")

unreal.log("")
unreal.log(f"UsdStageActor count : {len(stage_actors)} (target = 1)")
for sa in stage_actors:
    rl = sa.get_editor_property("root_layer")
    unreal.log(f"  stage : {sa.get_actor_label()}  root_layer={rl}")

# Light mobility
unreal.log("")
unreal.log("--- Lights ---")
for a in actors:
    if isinstance(a, (unreal.DirectionalLight, unreal.SkyLight)):
        try:
            mob = a.root_component.mobility
        except Exception:
            mob = "?"
        unreal.log(f"  {type(a).__name__:25s} label='{a.get_actor_label()}' mobility={mob}")

# Mesh -> material assignments
unreal.log("")
unreal.log("--- Mesh component material assignments (walking USD tree) ---")

def walk(actor, depth=0):
    try:
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = c.get_editor_property("static_mesh")
            if mesh is None:
                continue
            n = c.get_num_materials()
            mats = []
            for i in range(n):
                m = c.get_material(i)
                if m is None:
                    mats.append("None")
                else:
                    mats.append(m.get_name())
            unreal.log(f"  {mesh.get_name():32s} → {mats}")
    except Exception:
        pass
    try:
        for child in actor.get_attached_actors():
            walk(child, depth + 1)
    except Exception:
        pass

for sa in stage_actors:
    walk(sa)
