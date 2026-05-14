"""Find the actual MovieRenderPipeline classes available in UE 5.7."""
import unreal

# Get all attrs on unreal that contain "MoviePipeline" in their name
candidates = [a for a in dir(unreal) if "MoviePipeline" in a]
unreal.log(f"MoviePipeline* names on unreal module : {len(candidates)}")
for c in sorted(candidates):
    unreal.log(f"  {c}")
