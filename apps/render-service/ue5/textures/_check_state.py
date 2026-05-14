"""What's actually in the current level after the last pipeline run."""
import unreal

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
unreal.log(f"Current level : {world.get_path_name()}")

subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = subsys.get_all_level_actors()
unreal.log(f"Total actors : {len(actors)}")
classes = {}
stages = []
for a in actors:
    cls = type(a).__name__
    classes[cls] = classes.get(cls, 0) + 1
    if isinstance(a, unreal.UsdStageActor):
        stages.append(a)
for c, n in sorted(classes.items()):
    unreal.log(f"  {n:3d}  {c}")
unreal.log("")
unreal.log(f"UsdStageActor count = {len(stages)} (should be 1)")

vp_loc, vp_rot = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_level_viewport_camera_info()
unreal.log(f"Viewport camera loc={vp_loc} rot={vp_rot}")
