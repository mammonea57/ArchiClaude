"""Query the actual vertex positions of the enduit_blanc mesh after UE5
import. We need to know if the geometry actually has the wall surface,
and where it ended up in world space."""
import unreal

# Find the enduit_blanc mesh asset
asset_path = None
for p in unreal.EditorAssetLibrary.list_assets("/Game/UsdAssets", recursive=True):
    if "enduit_blanc" in p.lower():
        asset_path = p
        break

if asset_path is None:
    # Try alternative locations
    for p in unreal.EditorAssetLibrary.list_assets("/Game", recursive=True):
        if "enduit_blanc" in p.lower() and "sm_" in p.lower():
            asset_path = p
            break

if asset_path is None:
    raise SystemExit("!! could not find SM_enduit_blanc asset")
unreal.log(f"asset : {asset_path}")

mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
unreal.log(f"loaded : {mesh.get_path_name()}")

# Bounds in local space
try:
    bounds = mesh.get_bounds()
    unreal.log(f"bounds origin = {bounds.origin}")
    unreal.log(f"bounds box_extent = {bounds.box_extent}")
    unreal.log(f"bounds sphere_radius = {bounds.sphere_radius}")
except Exception as e:
    unreal.log(f"get_bounds err : {e}")

# Try get_bounding_box
try:
    bbox = mesh.get_bounding_box()
    unreal.log(f"bbox min={bbox.min} max={bbox.max}")
except Exception as e:
    unreal.log(f"get_bounding_box err : {e}")

# Vertex count, triangle count
try:
    nv = mesh.get_num_vertices(0)
    nt = mesh.get_num_triangles(0)
    unreal.log(f"num_vertices(LOD0) = {nv}, num_triangles(LOD0) = {nt}")
except Exception as e:
    unreal.log(f"vertex count err : {e}")

# Sample some vertices
try:
    # use static_mesh_editor or geometry_script
    pass
except Exception:
    pass
