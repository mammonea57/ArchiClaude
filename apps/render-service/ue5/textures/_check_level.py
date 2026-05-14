"""Find out which level the editor is currently displaying, vs the one
our pipeline writes to (/Game/Maps/ArchiClaudeScene)."""
import unreal

# Current level (what the user sees in the viewport)
try:
    lev_subsys = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    current = lev_subsys.get_current_level()
except Exception as e:
    current = f"err: {e}"

unreal.log(f"Current level object : {current}")

# World name (often the level)
try:
    world = unreal.UnrealEditorSubsystem().get_editor_world()
    unreal.log(f"World name : {world.get_name()} path={world.get_path_name()}")
except Exception as e:
    unreal.log(f"world err : {e}")

# All maps known to the project
import os
proj_dir = unreal.SystemLibrary.get_project_directory()
content_root = os.path.join(proj_dir, "Content")
unreal.log(f"Content root : {content_root}")
for root, dirs, files in os.walk(content_root):
    for f in files:
        if f.endswith(".umap"):
            unreal.log(f"  level on disk : {os.path.join(root, f)}")
