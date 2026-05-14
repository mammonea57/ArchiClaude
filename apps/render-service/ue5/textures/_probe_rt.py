"""Find the right API to create a TextureRenderTarget2D in UE 5.7."""
import unreal

# Check TextureRenderTarget2D methods
attrs = [a for a in dir(unreal.TextureRenderTarget2D) if not a.startswith("_")]
unreal.log(f"TextureRenderTarget2D public methods : {len(attrs)}")
for a in sorted(attrs):
    unreal.log(f"  .{a}")

unreal.log("")
unreal.log("RenderingLibrary methods (filtered):")
for a in sorted(dir(unreal.RenderingLibrary)):
    if a.startswith("_"): continue
    if "render_target" in a.lower() or "screenshot" in a.lower() or "capture" in a.lower():
        unreal.log(f"  .{a}")

unreal.log("")
unreal.log("Available factories with 'RenderTarget' :")
for a in dir(unreal):
    if "RenderTarget" in a and "Factory" in a:
        unreal.log(f"  unreal.{a}")
