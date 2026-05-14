"""Diagnose the current UE5 level : list every StaticMeshActor with its
label so we can fix the material-matching heuristic if labels don't
contain our material names."""
import unreal

# Use the new subsystem (the old EditorLevelLibrary is deprecated in 5.7)
try:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

unreal.log(f"--- Current level : {len(actors)} actors ---")

by_class: dict[str, int] = {}
mesh_labels: list[str] = []
for a in actors:
    cls = type(a).__name__
    by_class[cls] = by_class.get(cls, 0) + 1
    if isinstance(a, unreal.StaticMeshActor):
        try:
            label = a.get_actor_label()
        except Exception:
            label = "?"
        mesh_labels.append(label)

unreal.log("Classes :")
for cls, n in sorted(by_class.items(), key=lambda x: -x[1]):
    unreal.log(f"  {n:4d} × {cls}")

unreal.log("")
unreal.log(f"--- {len(mesh_labels)} StaticMeshActor labels (first 30) ---")
for lab in mesh_labels[:30]:
    unreal.log(f"  '{lab}'")
