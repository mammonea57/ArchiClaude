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
    """Open a fresh level so subsequent imports don't conflict with stale
    actors from prior runs."""
    log("Creating fresh empty level …")
    editor_level_lib = unreal.EditorLevelLibrary
    try:
        editor_level_lib.new_level(LEVEL_PATH)
    except Exception as e:
        log(f"new_level failed ({e}) — fallback to current level")
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
    back to MEGASCANS_ASSETS keys when running outside the repo tree."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
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


def setup_lighting() -> None:
    """Lumen + Sky Atmosphere + DirectionalLight (sun) + Fog."""
    log("Setting up Lumen lighting …")
    # SunLight (DirectionalLight)
    sun = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.DirectionalLight,
        unreal.Vector(0, 0, 5000),
        unreal.Rotator(-45, 140, 0),
    )
    sun.light_component.set_intensity(5.0)
    sun.light_component.set_light_color(unreal.LinearColor(1.0, 0.97, 0.92))
    # SkyAtmosphere
    unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyAtmosphere, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)
    )
    # SkyLight (catch ambient from sky)
    sky = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0, 0, 0)
    )
    sky.light_component.set_intensity(1.0)
    # ExponentialHeightFog
    fog = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.ExponentialHeightFog, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0)
    )
    log("✓ Lighting : Sun + SkyAtmosphere + SkyLight + Fog")


def create_level_sequence_with_camera() -> Optional[object]:
    """Create a LevelSequence with a single CineCameraActor for MRQ to render.
    Camera position/target derived from USD camera prim if present."""
    log("Creating LevelSequence + CineCamera …")
    # Find the camera position from USD imported camera (or fallback)
    cam_pos = unreal.Vector(2500, -2500, 1500)
    cam_target = unreal.Vector(0, 0, 700)
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if isinstance(actor, unreal.CineCameraActor):
            cam_pos = actor.get_actor_location()
            log(f"  found imported camera at {cam_pos}")
            break
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
    cine_cam.camera_component.set_field_of_view(42.0)

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
    setup_lighting()
    sequence = create_level_sequence_with_camera()
    ok = render_with_movie_pipeline(sequence, OUTPUT_PNG, OUTPUT_WIDTH, OUTPUT_HEIGHT)

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
