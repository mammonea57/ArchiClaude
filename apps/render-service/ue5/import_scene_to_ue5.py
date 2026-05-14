"""UE5 Python script : end-to-end headless import + render of a USD scene.

Runs INSIDE Unreal Engine 5.4 via the Python plugin. Designed to be invoked
headless from the command line :

    UnrealEditor-Cmd.exe MyProject.uproject \\
        -ExecutePythonScript="<path>/import_scene_to_ue5.py" \\
        -Unattended -NoLogTimes

When run headless, the script :
  1. Imports the .usda file via UE5 USD Importer
  2. Maps our material names → Megascans Quixel assets (fallback to defaults)
  3. Sets up Lumen + Sky Atmosphere + Sun (warm late-morning light)
  4. Adds the CineCameraActor from USD camera prim
  5. Configures Movie Render Queue for a single-frame 2K PNG
  6. EXECUTES the render synchronously
  7. Writes the PNG to disk
  8. Exits UE5 cleanly

The output PNG path is taken from env var UE5_OUTPUT_PNG, falls back to
/workspace/ue5_render.png.

PREREQUISITES (one-time UE5 setup) :
  - Plugins enabled : USD Importer, Python Editor Script, Movie Render Queue,
    Quixel Bridge
  - Quixel Bridge logged in (Megascans free for UE5 users)
  - Megascans assets pre-downloaded (see MEGASCANS_ASSETS dict)
  - Project must be a UE5.4+ project with /Game/Maps directory
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import unreal
except ImportError:
    print("!! This script must run INSIDE Unreal Engine (Python plugin).")
    sys.exit(1)


# ── Configuration from environment ─────────────────────────────────
USDA_PATH = os.environ.get(
    "UE5_USDA_PATH",
    "C:/workspace/scene.usda" if sys.platform == "win32" else "/workspace/scene.usda",
)
OUTPUT_PNG = os.environ.get(
    "UE5_OUTPUT_PNG",
    "C:/workspace/ue5_render.png" if sys.platform == "win32" else "/workspace/ue5_render.png",
)
OUTPUT_WIDTH = int(os.environ.get("UE5_OUTPUT_WIDTH", "2048"))
OUTPUT_HEIGHT = int(os.environ.get("UE5_OUTPUT_HEIGHT", "2048"))
LEVEL_PATH = "/Game/Maps/ArchiClaudeScene"
SEQUENCE_PATH = "/Game/Maps/ArchiClaudeSequence"


# ── Megascans material mapping ─────────────────────────────────────
# Each entry maps our internal material name to a Quixel Megascans slug
# (the trailing identifier shown in the Quixel Bridge URL). Free for UE5.
# Pre-download via Quixel Bridge before running this script — otherwise
# the script falls back to a default UE5 material with our displayColor.
MEGASCANS_ASSETS: dict[str, dict] = {
    "enduit_blanc":      {"slug": "white_plaster_wall_uknlfczra",   "tile_m": 2.0},
    "brique_rouge":      {"slug": "red_brick_wall_te4qaak",          "tile_m": 1.5},
    "asphalte":          {"slug": "asphalt_road_uglfdjqva",          "tile_m": 4.0},
    "pavers_concrete":   {"slug": "concrete_floor_paving_pkmkbi3fa", "tile_m": 2.0},
    "pierre_taille":     {"slug": "limestone_wall_uflnedhfa",        "tile_m": 2.0},
    "zinc_anthracite":   {"slug": "zinc_panel_ud4nccffa",            "tile_m": 1.0},
    "balcon_concrete":   {"slug": "smooth_concrete_uemngafnw",       "tile_m": 2.0},
    "vegetation":        {"slug": "grass_lawn_short_pjkkacrn",       "tile_m": 1.0},
    "voisin":            {"slug": "old_plaster_wall_pdmgcefea",      "tile_m": 2.0},
    "terre_neutre":      {"slug": "soil_dry_dusty_uflpebqva",        "tile_m": 3.0},
    "pierre_kerb":       {"slug": "kerbstone_limestone_pkmkbi3fa",   "tile_m": 1.5},
    "bois_porte":        {"slug": "wood_walnut_uemnffmgw",           "tile_m": 1.0},
    "fer_forge":         {"slug": "wrought_iron_black_pkmkbi3fa",    "tile_m": 0.5},
}

# Fallback colors (sRGB 0-1) if Megascans asset not present.
FALLBACK_COLORS: dict[str, tuple[float, float, float]] = {
    "enduit_blanc":      (0.92, 0.86, 0.74),
    "brique_rouge":      (0.55, 0.22, 0.12),
    "asphalte":          (0.16, 0.16, 0.16),
    "pavers_concrete":   (0.58, 0.58, 0.55),
    "pierre_taille":     (0.82, 0.74, 0.58),
    "zinc_anthracite":   (0.16, 0.16, 0.18),
    "balcon_concrete":   (0.94, 0.92, 0.88),
    "balcon_metal":      (0.18, 0.18, 0.20),
    "verre":             (0.05, 0.10, 0.18),
    "vegetation":        (0.28, 0.52, 0.18),
    "voisin":            (0.50, 0.45, 0.38),
    "terre_neutre":      (0.42, 0.40, 0.36),
    "pierre_kerb":       (0.78, 0.74, 0.68),
    "bois_porte":        (0.28, 0.15, 0.08),
    "metal_noir":        (0.05, 0.05, 0.05),
    "fer_forge":         (0.04, 0.04, 0.05),
    "road_paint_white":  (0.97, 0.97, 0.95),
}


# ── Logging helpers ───────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[ArchiClaude UE5] {msg}", flush=True)


def fatal(msg: str) -> None:
    log(f"FATAL — {msg}")
    unreal.SystemLibrary.execute_console_command(None, "quit")
    sys.exit(1)


# ── Scene setup ───────────────────────────────────────────────────
def create_or_clear_level() -> None:
    """Hard-clear the current level instead of creating a new one.

    Earlier versions created /Game/Maps/ArchiClaudeScene and worked in
    there. Problem : the user's editor viewport stays on whatever level
    they had open (Main.umap by default with the Architecture template),
    so they kept seeing their template scene unchanged — our changes
    were happening in an off-screen level. Now we modify the level the
    user is actively viewing.
    """
    log("Cleaning current level …")

    # Whether new_level succeeded or not, force-remove any UsdStageActor +
    # USD-spawned children left over from a previous run. This prevents
    # the "two stages stacked" rendering bug.
    try:
        actor_subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        all_actors = actor_subsys.get_all_level_actors()
    except Exception:
        all_actors = list(unreal.EditorLevelLibrary.get_all_level_actors())

    def _walk(a, acc):
        acc.append(a)
        try:
            for c in a.get_attached_actors():
                _walk(c, acc)
        except Exception:
            pass

    # We keep exactly :
    #   - 1 UsdStageActor (we re-spawn one with the new USDA)
    #   - 1 DirectionalLight + 1 SkyAtmosphere + 1 SkyLight + 1 ExpFog
    #   - 1 CineCameraActor
    # Everything else from the template (SunSky blueprint, Floor mesh,
    # InstancedFoliageActor, default Player/PostProcess, etc.) we wipe so
    # the render isn't polluted by template lights/geometry.
    KEEP_CLASSES = ("PlayerStart", "PostProcessVolume",
                    "Brush", "WorldSettings", "LevelInstance")
    to_remove = []
    for a in all_actors:
        is_stage = isinstance(a, unreal.UsdStageActor)
        if is_stage:
            _walk(a, to_remove)
            continue
        if isinstance(a, (unreal.DirectionalLight, unreal.SkyAtmosphere,
                          unreal.SkyLight, unreal.ExponentialHeightFog,
                          unreal.CineCameraActor)):
            to_remove.append(a)
            continue
        cls_name = type(a).__name__
        if cls_name in KEEP_CLASSES:
            continue
        # Drop the default "Floor" checker plane that comes with the
        # Architecture template, InstancedFoliageActor, SunSky blueprint,
        # any extra StaticMeshActors from the template, etc.
        to_remove.append(a)

    if to_remove:
        log(f"  cleaning {len(to_remove)} stale actor(s) …")
        for a in to_remove:
            try:
                a.destroy_actor()
            except Exception:
                pass

    log("✓ Level ready")


def import_usda(usda_path: str) -> None:
    """Spawn a UsdStageActor pointing at the USDA file. UE5's USD plugin
    handles the rest : it creates static meshes for each Mesh prim and
    actors for cameras/lights.

    Crucially, we disable prim collapsing + identical-material-slot
    merging BEFORE assigning root_layer. Default behaviour fuses every
    Mesh under a parent xform into ONE static mesh with ONE material
    slot driven by a DisplayColor material — which destroys our
    per-material workflow.
    """
    if not Path(usda_path).exists():
        fatal(f"USDA not found : {usda_path}")
    log(f"Importing USDA : {usda_path}")
    stage_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.UsdStageActor,
        unreal.Vector(0, 0, 0),
        unreal.Rotator(0, 0, 0),
    )
    if stage_actor is None:
        fatal("Failed to spawn UsdStageActor — USD Importer plugin enabled?")

    # Disable collapsing and slot merging BEFORE loading. These options
    # are read at stage-load time, not after the fact.
    try:
        stage_actor.set_editor_property("kinds_to_collapse", 0)
    except Exception as e:
        log(f"  ! could not set kinds_to_collapse : {e}")
    try:
        stage_actor.set_editor_property("merge_identical_material_slots", False)
    except Exception as e:
        log(f"  ! could not set merge_identical_material_slots : {e}")

    stage_actor.set_editor_property("root_layer", unreal.FilePath(usda_path))
    # Wait for stage to load — bigger USDs need more time
    time.sleep(4)
    log("✓ USDA imported via UsdStageActor (no prim collapse, no slot merge)")


def _load_archiclaude_material(mat_name: str) -> Optional[unreal.MaterialInterface]:
    """Resolve the MaterialInstance for one of our internal material names.

    Resolution order :
      1. /Game/AC/Materials/M_<name> — Polyhaven-backed MaterialInstance,
         the primary path produced by `textures/import_to_ue5.py`.
      2. Legacy Megascans paths under /Game/Megascans/Surfaces/<slug>/M_<slug>
         (kept as a fallback for setups where Megascans assets were
         manually downloaded via Fab/Bridge).

    Returns None if nothing matches — caller will use the flat-color fallback.
    """
    # Primary : ArchiClaude Polyhaven-backed material instance
    ac_path = f"/Game/AC/Materials/M_{mat_name}"
    asset = unreal.EditorAssetLibrary.load_asset(ac_path)
    if asset is not None:
        return asset
    # Legacy Megascans fallback
    if mat_name in MEGASCANS_ASSETS:
        slug = MEGASCANS_ASSETS[mat_name]["slug"]
        for p in (
            f"/Game/Megascans/Surfaces/{slug}/M_{slug}",
            f"/Game/Megascans/Surfaces/{slug}/M_{slug}_inst",
            f"/Game/MS_Surfaces/{slug}/M_{slug}",
        ):
            asset = unreal.EditorAssetLibrary.load_asset(p)
            if asset is not None:
                return asset
    return None


# Backwards-compatible alias for any caller still using the old name
_load_megascans_material = _load_archiclaude_material


def _make_fallback_material(mat_name: str) -> unreal.MaterialInterface:
    """Create a simple lambertian material with the iter #320 sRGB color
    when no Megascans asset is available. Cached as /Game/AC/Fallback_<name>.
    """
    color = FALLBACK_COLORS.get(mat_name, (0.7, 0.7, 0.7))
    asset_path = f"/Game/AC/Fallback_{mat_name}"
    cached = unreal.EditorAssetLibrary.load_asset(asset_path)
    if cached is not None:
        return cached
    # Build a Material Instance Dynamic from the engine's WorldGridMaterial
    # so we get a valid material handle quickly. Real PBR setup left for
    # when Megascans assets are properly mapped.
    base = unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/WorldGridMaterial")
    if base is None:
        return None
    factory = unreal.MaterialFactoryNew()
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder, name = asset_path.rsplit("/", 1)
    new_asset = asset_tools.create_asset(name, folder, unreal.Material, factory)
    return new_asset


def _known_material_names() -> list:
    """Return the canonical list of material names to match labels against.
    Prefers the centralised MATERIAL_LIBRARY in textures/library.py, falls
    back to MEGASCANS_ASSETS keys when running outside the repo tree.

    Forces a reload to dodge UE5's long-lived Python interpreter caching
    a stale version of library.py from an earlier session.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        # Drop the cached module so we pick up edits to library.py
        sys.modules.pop("textures.library", None)
        sys.modules.pop("library", None)
        from textures.library import MATERIAL_LIBRARY  # type: ignore
        return list(MATERIAL_LIBRARY.keys())
    except Exception:
        return list(MEGASCANS_ASSETS.keys())


def _walk_actors_recursive(root) -> list:
    """Yield root + every descendant in attached-actor hierarchy.

    UsdStageActor exposes its USD prims as a tree of attached actors
    rather than as top-level actors in the level. `get_all_level_actors`
    on the editor subsystem only returns the top-level ones, so we walk
    `get_attached_actors` recursively to find every mesh-bearing actor.
    """
    seen = []
    stack = [root]
    while stack:
        a = stack.pop()
        seen.append(a)
        try:
            stack.extend(a.get_attached_actors())
        except Exception:
            pass
    return seen


def _all_static_mesh_components_in_level() -> list:
    """Collect every StaticMeshComponent in the level, walking the full
    attached-actor tree (USD plugin parents components under USD prim
    actors that aren't top-level level actors)."""
    try:
        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        top = subsys.get_all_level_actors()
    except Exception:
        top = unreal.EditorLevelLibrary.get_all_level_actors()
    comps: list = []
    seen_ids: set = set()
    for root in top:
        for a in _walk_actors_recursive(root):
            key = id(a)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            try:
                for c in a.get_components_by_class(unreal.StaticMeshComponent):
                    if c.get_editor_property("static_mesh") is not None:
                        comps.append((a, c))
            except Exception:
                pass
    return comps


def apply_materials_to_imported_meshes() -> int:
    """Two strategies, applied in order :

    (a) per-actor : if a mesh actor's label contains one of our known
        material names (legacy behaviour), assign M_<name> to slot 0.

    (b) per-slot : for each mesh component, walk its material slots ;
        if a slot name matches a material in MATERIAL_LIBRARY, override
        that slot with M_<name>. This is the path that matters for our
        USD import (one mesh, many slots).
    """
    log("Applying materials to imported meshes …")
    known = _known_material_names()
    n_applied_ac = 0
    n_applied_fb = 0

    found_components = _all_static_mesh_components_in_level()
    log(f"  found {len(found_components)} static mesh component(s) to inspect")
    for actor, comp in found_components:
        try:
            slots = list(comp.get_material_slot_names())
            mesh = comp.get_editor_property("static_mesh")
            mesh_name = mesh.get_name() if mesh else "(no mesh)"
            log(f"    actor='{actor.get_actor_label()}' mesh='{mesh_name}' "
                f"slots={[str(s) for s in slots]}")
        except Exception as e:
            log(f"    inspect error : {e}")

    for actor, comp in found_components:
        # Try matching against (in priority) :
        #   1. the StaticMesh asset name (e.g. "SM_brique_rouge")  ← UsdStageActor case
        #   2. each material slot name                              ← legacy multi-slot
        #   3. the actor label                                       ← legacy whole-actor
        candidates = []
        try:
            mesh = comp.get_editor_property("static_mesh")
            if mesh:
                candidates.append(mesh.get_name().lower())
        except Exception:
            pass
        try:
            for s in comp.get_material_slot_names():
                candidates.append(str(s).lower())
        except Exception:
            pass
        try:
            candidates.append(actor.get_actor_label().lower())
        except Exception:
            pass

        matched = None
        for cand in candidates:
            for mat_name in known:
                if mat_name in cand:
                    matched = mat_name
                    break
            if matched:
                break

        if matched is None:
            continue

        # How many slots ? Apply to every slot (each mesh from the USD
        # plugin has a single slot named '0' anyway).
        try:
            n_slots = comp.get_num_materials()
        except Exception:
            n_slots = 1
        ac = _load_archiclaude_material(matched)
        for idx in range(max(1, n_slots)):
            if ac is not None:
                comp.set_material(idx, ac)
                n_applied_ac += 1
            else:
                fb = _make_fallback_material(matched)
                if fb is not None:
                    comp.set_material(idx, fb)
                    n_applied_fb += 1

    log(f"✓ Materials : {n_applied_ac} ArchiClaude + {n_applied_fb} fallback")
    return n_applied_ac + n_applied_fb


def build_solid_wrapper() -> None:
    """The Blender → USD export of iter500 only contains floor slabs +
    columns, not the building's exterior walls (the baseline iter#320
    PNG was rendered straight from Blender with a much fuller model).

    Re-generate the missing solid shell procedurally : compute the
    bounding box of every building-material mesh (enduit_blanc, brique_
    rouge, pierre_taille, zinc_anthracite, balcon_concrete, verre,
    bois_porte, fer_forge), spawn an Engine /Engine/BasicShapes/Cube
    mesh scaled to those bounds, and assign M_enduit_blanc as its
    material. The cube hides the see-through "skeleton" appearance and
    gives the building a solid silhouette from any angle.
    """
    BUILDING_MAT_NAMES = (
        "enduit_blanc", "brique_rouge", "pierre_taille", "zinc_anthracite",
        "balcon_concrete", "verre", "bois_porte", "fer_forge",
    )
    INF = 1e9
    mn = [INF, INF, INF]
    mx = [-INF, -INF, -INF]
    n_meshes = 0

    def walk(actor):
        nonlocal n_meshes
        try:
            for c in actor.get_components_by_class(unreal.StaticMeshComponent):
                mesh = c.get_editor_property("static_mesh")
                if mesh is None:
                    continue
                name = mesh.get_name().lower()
                is_building = any(b in name for b in BUILDING_MAT_NAMES)
                if not is_building:
                    continue
                origin = c.get_world_location()
                try:
                    bounds = c.calc_local_bounds()
                    ext = bounds.box_extent
                except Exception:
                    ext = unreal.Vector(100, 100, 100)
                ox, oy, oz = origin.x, origin.y, origin.z
                ex, ey, ez = ext.x, ext.y, ext.z
                for axis, (o, e) in enumerate(((ox, ex), (oy, ey), (oz, ez))):
                    mn[axis] = min(mn[axis], o - e)
                    mx[axis] = max(mx[axis], o + e)
                n_meshes += 1
        except Exception:
            pass
        try:
            for child in actor.get_attached_actors():
                walk(child)
        except Exception:
            pass

    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in subsys.get_all_level_actors():
        walk(a)

    if mn[0] > 1e8 or n_meshes == 0:
        log("  ! no building meshes found, skip solid wrapper")
        return

    cube_mesh = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube")
    if cube_mesh is None:
        log("  ! /Engine/BasicShapes/Cube not found, skip solid wrapper")
        return

    center = unreal.Vector(
        (mn[0] + mx[0]) / 2.0,
        (mn[1] + mx[1]) / 2.0,
        (mn[2] + mx[2]) / 2.0,
    )
    # 100×100×100 cm engine cube; scale to fit the building bbox.
    # Slightly inset (0.97) so the existing balcony/window details still
    # poke out a bit and we don't have a perfect rectangular silhouette.
    INSET = 0.97
    scale = unreal.Vector(
        max((mx[0] - mn[0]) * INSET / 100.0, 0.1),
        max((mx[1] - mn[1]) * INSET / 100.0, 0.1),
        max((mx[2] - mn[2]) * INSET / 100.0, 0.1),
    )
    log(f"  building bbox : ({mn[0]:.0f},{mn[1]:.0f},{mn[2]:.0f}) → "
        f"({mx[0]:.0f},{mx[1]:.0f},{mx[2]:.0f}) from {n_meshes} meshes")
    log(f"  shell center  : {center}   scale : {scale}")

    shell = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.StaticMeshActor, center, unreal.Rotator(0, 0, 0)
    )
    shell.set_actor_label("ProceduralBuildingShell")
    smc = shell.static_mesh_component
    smc.set_static_mesh(cube_mesh)
    shell.set_actor_scale3d(scale)
    wall_mat = unreal.EditorAssetLibrary.load_asset("/Game/AC/Materials/M_enduit_blanc")
    if wall_mat is not None:
        smc.set_material(0, wall_mat)
    log("  ✓ procedural building shell spawned")


def setup_lighting() -> None:
    """Movable Lumen lighting : Sun + SkyAtmosphere + SkyLight + Fog.

    Critical : all lights are set to Movable mobility. With the default
    Stationary lights UE prompts "L'éclairage doit être régénéré" and
    refuses to render dynamic GI. Movable + Lumen Dynamic = no lightmap
    bake needed.
    """
    log("Setting up Lumen lighting …")
    MOVABLE = unreal.ComponentMobility.MOVABLE

    # Force dynamic Lumen via console (cheap, idempotent)
    for cvar in (
        "r.DynamicGlobalIlluminationMethod 1",   # 1 = Lumen
        "r.ReflectionMethod 1",                  # 1 = Lumen
        "r.Lumen.HardwareRayTracing 0",          # software RT (more stable on 3070L)
        "r.Mobility.AllowStaticLighting 0",      # no static lighting prompts
    ):
        try:
            unreal.SystemLibrary.execute_console_command(None, cvar)
        except Exception:
            pass

    # SunLight (DirectionalLight) — Movable so it casts dynamic shadows
    sun = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.DirectionalLight,
        unreal.Vector(0, 0, 5000),
        unreal.Rotator(-45, 140, 0),
    )
    try:
        sun.root_component.set_mobility(MOVABLE)
    except Exception:
        pass
    sun.light_component.set_intensity(5.0)
    sun.light_component.set_light_color(unreal.LinearColor(1.0, 0.97, 0.92))

    # SkyAtmosphere
    unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyAtmosphere, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
    )

    # SkyLight (Movable + real-time capture so Lumen GI uses live env)
    sky = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0, 0, 0)
    )
    try:
        sky.root_component.set_mobility(MOVABLE)
    except Exception:
        pass
    try:
        sky.light_component.set_editor_property("real_time_capture", True)
    except Exception:
        pass
    sky.light_component.set_intensity(1.0)

    # ExponentialHeightFog
    unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.ExponentialHeightFog, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0)
    )
    log("✓ Lighting : Movable Sun + SkyAtmosphere + Real-time SkyLight + Fog + Lumen Dynamic")


def _compute_scene_bounds():
    """Walk every imported mesh in the level and return (min_v, max_v) of the
    combined world-space bounding box. Used to auto-frame the camera so we
    don't end up rendering the inside of a wall."""
    INF = 1e9
    mn = [INF, INF, INF]
    mx = [-INF, -INF, -INF]
    try:
        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        top = subsys.get_all_level_actors()
    except Exception:
        top = list(unreal.EditorLevelLibrary.get_all_level_actors())

    def walk(actor):
        try:
            for c in actor.get_components_by_class(unreal.StaticMeshComponent):
                if c.get_editor_property("static_mesh") is None:
                    continue
                # CineCam helper mesh — skip
                m = c.get_editor_property("static_mesh")
                if m.get_name() in ("SM_CineCam",):
                    continue
                origin = c.get_world_location()
                extents = unreal.Vector(0, 0, 0)
                try:
                    bounds = c.calc_local_bounds()
                    extents = bounds.box_extent
                except Exception:
                    pass
                for axis in (0, 1, 2):
                    mn[axis] = min(mn[axis], origin.x if axis == 0 else origin.y if axis == 1 else origin.z)
                    mx[axis] = max(mx[axis], origin.x if axis == 0 else origin.y if axis == 1 else origin.z)
        except Exception:
            pass
        try:
            for child in actor.get_attached_actors():
                walk(child)
        except Exception:
            pass
    for a in top:
        walk(a)
    if mn[0] > 1e8:
        return None, None
    return unreal.Vector(*mn), unreal.Vector(*mx)


def create_level_sequence_with_camera() -> Optional[object]:
    """Create a LevelSequence with a single CineCameraActor.

    We **ignore** the USD-imported camera's position/orientation : Blender's
    USD export uses meters while UE5 imports as centimeters with axis
    remap, leaving the camera somewhere inside the building. Instead we
    compute the scene's bounding box and place the camera in a 3/4 view
    looking at the building centre — a guaranteed-good frame for archi-viz.
    """
    log("Creating LevelSequence + CineCamera …")
    mn, mx = _compute_scene_bounds()
    if mn is None:
        cam_pos = unreal.Vector(2500, -2500, 1500)
        cam_target = unreal.Vector(0, 0, 700)
        log("  ! could not compute bounds — using default 3/4 view")
    else:
        cx = (mn.x + mx.x) / 2.0
        cy = (mn.y + mx.y) / 2.0
        cz_top = max(mx.z, 1000.0)
        # 3/4 upper hero shot — matches the iter#320 baseline framing
        # (camera up-front-right of the building, looking slightly down).
        cam_pos = unreal.Vector(
            mx.x + 3000,        # 30 m past max X
            mn.y - 3000,        # 30 m before min Y
            cz_top * 1.3,       # 30% above building top
        )
        cam_target = unreal.Vector(cx, cy, cz_top * 0.5)
        log(f"  bounds : {mn} → {mx}")
        log(f"  cam_pos    : {cam_pos}")
        log(f"  cam_target : {cam_target}")
    # If no camera was imported, spawn one
    cine_cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor,
        cam_pos,
        unreal.Rotator(0, 0, 0),
    )
    # Compute look-at from cam_pos to cam_target
    direction = cam_target - cam_pos
    rotation = unreal.MathLibrary.find_look_at_rotation(cam_pos, cam_target)
    cine_cam.set_actor_rotation(rotation, False)
    # 65° FOV is closer to the editor viewport default and gives a
    # comfortable archi-viz framing (42° is too narrow, makes everything
    # feel zoomed in and clipped).
    cine_cam.camera_component.set_field_of_view(65.0)

    # Create LevelSequence asset
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder, name = SEQUENCE_PATH.rsplit("/", 1)
    factory = unreal.LevelSequenceFactoryNew()
    sequence = asset_tools.create_asset(name, folder, unreal.LevelSequence, factory)
    sequence.set_playback_start(0)
    sequence.set_playback_end(1)
    # Bind cine_cam to sequence
    binding = sequence.add_possessable(cine_cam)
    log("✓ Sequence + Camera ready")
    return sequence


def _get_viewport_camera_pose():
    """Return (location, rotation) of the active editor viewport's
    free-fly camera, so the SceneCapture can render exactly what the
    user is seeing in the editor."""
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        loc, rot = ues.get_level_viewport_camera_info()
        return loc, rot
    except Exception:
        return None, None


def render_with_screenshot(camera_actor, output_path: str,
                            width: int, height: int) -> bool:
    """Single-frame render via SceneCaptureComponent2D + RenderTarget2D.

    Pure Python path : we spawn a SceneCapture2D at the editor viewport's
    camera location (so the PNG matches what the user sees in the editor),
    point it at a transient RenderTarget2D, trigger a synchronous capture,
    then export the render target to PNG via RenderingLibrary.

    Falls back to the CineCameraActor's transform if the viewport pose
    can't be queried.

    Works under Remote Execution because it doesn't depend on a focused
    viewport — the engine renders straight into the render target.
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log(f"Rendering via SceneCapture2D → {out_path.name} ({width}×{height}) …")

    # 1. Create a transient RenderTarget2D.
    # The UE 5.7 RenderingLibrary method is `create_render_target2d`
    # (target2d, not target_2d — the underscore went missing in newer
    # versions).
    rt = None
    try:
        try:
            world = unreal.UnrealEditorSubsystem().get_editor_world()
        except Exception:
            world = unreal.EditorLevelLibrary.get_editor_world()
        rt = unreal.RenderingLibrary.create_render_target2d(
            world, width, height, unreal.TextureRenderTargetFormat.RTF_RGBA8
        )
    except Exception as e:
        log(f"  ! create_render_target2d failed : {e}")

    if rt is None:
        try:
            rt = unreal.TextureRenderTarget2D()
            rt.set_editor_property("size_x", width)
            rt.set_editor_property("size_y", height)
            rt.set_editor_property("render_target_format",
                                    unreal.TextureRenderTargetFormat.RTF_RGBA8)
        except Exception as e:
            log(f"!! could not create RenderTarget2D : {e}")
            return False
    log(f"  ✓ render target ready ({width}x{height})")

    # 2. Spawn SceneCapture2D at our deterministic CineCamera pose so
    # consecutive runs produce a reproducible PNG (independent of where
    # the user happens to be free-flying their viewport).
    cam_loc = camera_actor.get_actor_location()
    cam_rot = camera_actor.get_actor_rotation()
    log(f"  using CineCamera pose : loc={cam_loc} rot={cam_rot}")
    try:
        capture = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.SceneCapture2D, cam_loc, cam_rot
        )
        ccomp = capture.capture_component2d
        ccomp.set_editor_property("texture_target", rt)
        # Match the cine camera FOV (default UE5 FOV 90 is too wide)
        try:
            cine = camera_actor.camera_component
            fov = cine.get_editor_property("field_of_view")
            ccomp.set_editor_property("fov_angle", fov)
        except Exception:
            ccomp.set_editor_property("fov_angle", 42.0)
        ccomp.set_editor_property("capture_source",
                                    unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        log("  ✓ SceneCapture2D spawned")
    except Exception as e:
        log(f"!! could not spawn SceneCapture2D : {e}")
        return False

    # 3. Trigger capture (synchronous on this thread)
    try:
        ccomp.capture_scene()
        log("  ✓ scene captured")
    except Exception as e:
        log(f"!! capture_scene raised : {e}")
        try:
            capture.destroy_actor()
        except Exception:
            pass
        return False

    # 4. Export render target to PNG
    try:
        unreal.RenderingLibrary.export_render_target(
            None, rt, str(out_path.parent), out_path.name
        )
    except Exception as e:
        log(f"!! export_render_target raised : {e}")
        try:
            capture.destroy_actor()
        except Exception:
            pass
        return False

    # 5. Cleanup the capture actor
    try:
        capture.destroy_actor()
    except Exception:
        pass

    if out_path.exists():
        log(f"✓ render saved → {out_path} ({out_path.stat().st_size:,} bytes)")
        return True
    # export_render_target may have written `<out_dir>/<file_name>` or
    # something subtly different — scan the dir for any matching PNG
    for f in out_path.parent.glob(out_path.stem + "*.png"):
        if f.stat().st_mtime > time.time() - 30:
            try:
                if out_path.exists():
                    out_path.unlink()
                f.rename(out_path)
                log(f"✓ render saved (renamed from {f.name}) → {out_path}")
                return True
            except Exception:
                pass
    log(f"!! export finished but no PNG found at expected path {out_path}")
    return False


def render_with_movie_pipeline(sequence_asset, output_path: str,
                                width: int, height: int) -> bool:
    """Configure Movie Render Queue and execute synchronous render.
    Returns True if render succeeded."""
    log(f"Configuring Movie Render Queue → {output_path} ({width}×{height}) …")
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log("  step a : MoviePipelineQueueSubsystem.get_queue()")
    subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = subsystem.get_queue()
    log("  step b : clear stale jobs")
    for j in list(queue.get_jobs()):
        queue.delete_job(j)
    log("  step c : allocate_new_job")
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    log("  step d : set sequence + map SoftObjectPath")
    job.sequence = unreal.SoftObjectPath(SEQUENCE_PATH)
    job.map = unreal.SoftObjectPath(LEVEL_PATH)
    log("  step e : get_configuration")
    config = job.get_configuration()
    log(f"    config type : {type(config).__name__}")
    log("  step f : PNG format selector (no own properties in UE 5.7+)")
    # In UE 5.7 the PNG class is just a format selector with no editable
    # properties of its own — the actual output_directory / file_name_format
    # live on MoviePipelineOutputSetting.
    config.find_or_add_setting_by_class(unreal.MoviePipelineImageSequenceOutput_PNG)
    log("  step g : MoviePipelineOutputSetting (path + resolution + range)")
    res_setting = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    res_setting.set_editor_property(
        "output_directory", unreal.DirectoryPath(str(out_path.parent))
    )
    res_setting.set_editor_property("file_name_format", out_path.stem)
    res_setting.set_editor_property("output_resolution", unreal.IntPoint(width, height))
    res_setting.set_editor_property("use_custom_playback_range", True)
    res_setting.set_editor_property("custom_start_frame", 0)
    res_setting.set_editor_property("custom_end_frame", 1)
    log("  step h : MoviePipelineAntiAliasingSetting")
    aa_setting = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa_setting.spatial_sample_count = 8
    aa_setting.temporal_sample_count = 1
    aa_setting.engine_warm_up_count = 16
    aa_setting.render_warm_up_count = 8
    log("  step i : MoviePipelineDeferredPassBase")
    config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)
    log("  ✓ MRQ configured")

    # Execute synchronously
    log("Starting render execution (this can take 1-10 min)…")
    executor = unreal.MoviePipelinePIEExecutor()
    rendered_event = []
    def _on_finished(executor, success):
        rendered_event.append(success)
    executor.on_executor_finished_delegate.add_callable_unique(_on_finished)
    subsystem.render_queue_with_executor_instance(executor)

    # Poll until done (UE5 doesn't return synchronously from PIEExecutor)
    timeout_s = 600
    waited = 0
    while not rendered_event and waited < timeout_s:
        time.sleep(2)
        waited += 2
        if waited % 30 == 0:
            log(f"  … render in progress ({waited}s elapsed)")

    if not rendered_event:
        log(f"!! render timed out after {timeout_s}s")
        return False
    if not rendered_event[0]:
        log("!! render reported failure")
        return False

    # Movie Render Queue writes <stem>.0000.png by default — fix the name
    candidate = out_path.parent / f"{out_path.stem}.0000.png"
    if candidate.exists() and not out_path.exists():
        candidate.rename(out_path)
    if out_path.exists():
        log(f"✓ Render complete : {out_path} ({out_path.stat().st_size:,} bytes)")
        return True
    log(f"!! Render finished but expected file not found : {out_path}")
    return False


# ── Main pipeline ─────────────────────────────────────────────────
def _find_cine_camera() -> "unreal.CineCameraActor":
    """Pick the CineCameraActor we (or the USD) added to the level."""
    try:
        subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = subsys.get_all_level_actors()
    except Exception:
        actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for a in actors:
        if isinstance(a, unreal.CineCameraActor):
            return a
        try:
            for child in a.get_attached_actors():
                if isinstance(child, unreal.CineCameraActor):
                    return child
        except Exception:
            pass
    return None


def _save_current_level_safely() -> None:
    """Best-effort save of the current level so a subsequent crash doesn't
    lose all the import/material work."""
    try:
        subsys = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        subsys.save_current_level()
        log("  ✓ level saved")
    except Exception:
        try:
            unreal.EditorLevelLibrary.save_current_level()
            log("  ✓ level saved (legacy API)")
        except Exception as e:
            log(f"  ! could not save level : {e}")


def main() -> int:
    log("=" * 60)
    log("ArchiClaude UE5 Headless Importer + Renderer")
    log("=" * 60)
    log(f"USDA       : {USDA_PATH}")
    log(f"Output PNG : {OUTPUT_PNG}")
    log(f"Size       : {OUTPUT_WIDTH}×{OUTPUT_HEIGHT}")
    log("")

    if not Path(USDA_PATH).exists():
        fatal(f"USDA file not found : {USDA_PATH}")

    create_or_clear_level()
    import_usda(USDA_PATH)
    apply_materials_to_imported_meshes()
    # build_solid_wrapper() : disabled. Wrapping the building in a solid
    # cube made the render look worse (the cube hides intentional
    # balconies + windows that ARE in the USD). The fundamental fix has
    # to happen on the Mac side : improve the Blender → USD export so it
    # ships the full architectural model (walls, fenestration, parapets)
    # rather than the current "skeleton" simplification.
    setup_lighting()
    # Save now : if the screenshot step crashes UE5 we don't lose the
    # whole scene setup.
    _save_current_level_safely()
    create_level_sequence_with_camera()
    camera = _find_cine_camera()
    if camera is None:
        fatal("No CineCameraActor found after setup")

    # Lightweight path : HighRes screenshot. MRQ is overkill for our
    # one-PNG-per-iter use case and was crashing UE 5.7 on this hardware.
    ok = render_with_screenshot(camera, OUTPUT_PNG, OUTPUT_WIDTH, OUTPUT_HEIGHT)

    if ok:
        log("✓ Pipeline complete")
        return 0
    log("✗ Pipeline failed")
    return 1


if __name__ == "__main__":
    exit_code = main()
    # Quit UE5 cleanly when running headless
    if "-unattended" in " ".join(sys.argv).lower() or os.environ.get("UE5_QUIT_ON_DONE"):
        log("Exiting UE5 …")
        unreal.SystemLibrary.execute_console_command(None, "quit")
    sys.exit(exit_code)
