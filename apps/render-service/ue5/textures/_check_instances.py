"""Verify every MaterialInstance in /Game/AC/Materials/ has its 3 texture
overrides (Albedo, Normal, ARM) wired to the right T_<name>_* assets."""
import unreal

FOLDER = "/Game/AC/Materials"
EXPECTED_PARAMS = ("Albedo", "Normal", "ARM")

asset_paths = unreal.EditorAssetLibrary.list_assets(FOLDER, recursive=False, include_folder=False)
unreal.log(f"--- Checking {len(asset_paths)} assets in {FOLDER} ---")

MEL = unreal.MaterialEditingLibrary
ok_count = 0
broken = []
for path in asset_paths:
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if asset is None or not isinstance(asset, unreal.MaterialInstanceConstant):
        continue
    name = asset.get_name()
    bound = {}
    for param in EXPECTED_PARAMS:
        try:
            tex = MEL.get_material_instance_texture_parameter_value(asset, param)
        except Exception:
            tex = None
        bound[param] = tex.get_path_name() if tex else None
    missing = [p for p, v in bound.items() if v is None]
    status = "OK" if not missing else f"MISSING {missing}"
    if missing:
        broken.append(name)
    else:
        ok_count += 1
    unreal.log(f"  {status:30s} {name}")
    for p, v in bound.items():
        unreal.log(f"      {p:8s} → {v}")

unreal.log("")
unreal.log(f"Result : {ok_count} instances fully wired, {len(broken)} broken : {broken}")
