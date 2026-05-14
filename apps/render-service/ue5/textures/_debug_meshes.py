"""Deep debug : list every mesh's location, bbox, material slot,
visibility, then force all meshes to WorldGridMaterial so we can see
which prims are actually being imported geometrically vs invisible."""
import unreal

DEBUG_MAT_PATH = "/Engine/EngineMaterials/WorldGridMaterial"
debug_mat = unreal.EditorAssetLibrary.load_asset(DEBUG_MAT_PATH)
unreal.log(f"WorldGridMaterial loaded : {debug_mat is not None}")

try:
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsys.get_all_level_actors()
except Exception:
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

mesh_records = []

def walk(actor):
    try:
        for c in actor.get_components_by_class(unreal.StaticMeshComponent):
            mesh = c.get_editor_property("static_mesh")
            if mesh is None:
                continue
            origin = c.get_world_location()
            scale = c.get_world_scale3d() if hasattr(c, "get_world_scale3d") else None
            try:
                bounds = c.calc_local_bounds()
                ext = bounds.box_extent
            except Exception:
                ext = unreal.Vector(0, 0, 0)
            visible = c.is_visible() if hasattr(c, "is_visible") else "?"
            n_slots = c.get_num_materials()
            mats = []
            for i in range(n_slots):
                m = c.get_material(i)
                mats.append(m.get_name() if m else "None")
            try:
                num_tris = mesh.get_num_triangles(0) if hasattr(mesh, "get_num_triangles") else "?"
            except Exception:
                num_tris = "?"
            mesh_records.append({
                "actor_label": actor.get_actor_label(),
                "mesh_name": mesh.get_name(),
                "tris": num_tris,
                "origin": (origin.x, origin.y, origin.z),
                "extent": (ext.x, ext.y, ext.z),
                "visible": visible,
                "mats": mats,
                "comp": c,
            })
    except Exception as e:
        unreal.log(f"  walk err on {actor}: {e}")
    try:
        for child in actor.get_attached_actors():
            walk(child)
    except Exception:
        pass

for a in actors:
    walk(a)

unreal.log(f"--- {len(mesh_records)} mesh components found ---")
for r in mesh_records:
    ox, oy, oz = r["origin"]
    ex, ey, ez = r["extent"]
    unreal.log(
        f"  '{r['actor_label']}' / {r['mesh_name']:32s} "
        f"tris={r['tris']:>6} origin=({ox:6.0f},{oy:6.0f},{oz:6.0f}) "
        f"ext=({ex:6.0f},{ey:6.0f},{ez:6.0f}) visible={r['visible']} mats={r['mats']}"
    )

# Now apply WorldGridMaterial to EVERY mesh slot of every mesh in the scene
# (except SM_CineCam helper geometry). This is the debug pass: if we now
# see all the prims with grid texture in the next render, geometry is fine
# and the issue was materials.
if debug_mat is not None:
    n = 0
    for r in mesh_records:
        mname = r["mesh_name"].lower()
        if "cinecam" in mname:
            continue
        for i in range(len(r["mats"])):
            try:
                r["comp"].set_material(i, debug_mat)
                n += 1
            except Exception:
                pass
    unreal.log(f"--- forced WorldGridMaterial on {n} slot(s) ---")
