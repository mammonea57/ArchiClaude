"""Blender + Cycles render endpoint on Modal A100.

Pipeline (final) :
  BM JSON → scene_mesh quads → Blender mesh + PBR materials + camera + lighting
         → Cycles path-traced render 1024×1024
         → optional FLUX img2img finish (strength 0.18-0.22, photoreal polish)
         → ESRGAN x4 → 2048×2048 final

Why Blender Cycles (vs FLUX text2img-only in modal_flux_endpoint.py) :
  - Geometric precision : parallel walls, exact mullions, no AI hallucination
  - PBR materials with global illumination (Cycles path tracer)
  - Real shadows, ambient occlusion, indirect light
  - 100% deterministic from BM data (no seed drift)
  - Free + open-source

Usage : .venv/bin/modal run src/modal_blender_endpoint.py
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-blender-render")

# Blender 5.1.1 requires Python 3.13
image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install(
        # X11 + OpenGL libs needed by bpy (Blender headless still
        # links against these for context creation).
        "libxxf86vm1", "libxfixes3", "libxi6", "libxkbcommon0",
        "libxrender1", "libxrandr2", "libxinerama1", "libxcursor1",
        "libsm6", "libice6", "libgl1", "libegl1", "libglu1-mesa",
        "libglib2.0-0", "libdbus-1-3",
        "wget",   # for HDRI download
    )
    .pip_install(
        "bpy==5.1.1",
        "numpy>=1.26",
        "pillow>=10.4",
    )
    .run_commands(
        # iter 2026-06-27 (light2 agent) : le HDRI kloppenheim_06_puresky est un
        # ciel NUAGEUX → même saturé il reste gris/laiteux en haut (B-R≈+9, ciel
        # quasi blanc). Les Street View Nogent montrent un CIEL BLEU FRANC dégagé.
        # On passe à qwantani_noon (Poly Haven, ciel bleu midi dégagé, soleil
        # haut net). On garde puresky en FALLBACK si le primaire échoue.
        "mkdir -p /root/textures && wget -q "
        "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/qwantani_noon_1k.hdr "
        "-O /root/hdri.hdr || echo 'HDRI primaire (qwantani_noon) failed'",
        # Fallback ciel : si le primaire est trop petit/manquant, on récupère le
        # puresky (nuageux mais valide) pour ne jamais retomber sur Nishita seul.
        "test -s /root/hdri.hdr && [ $(stat -c%s /root/hdri.hdr) -gt 100000 ] || "
        "wget -q https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/kloppenheim_06_puresky_1k.hdr "
        "-O /root/hdri.hdr || echo 'HDRI fallback (puresky) failed too — Nishita sky'",
        # PBR textures — Poly Haven CC0, 1k diffuse maps for photorealism.
        # Each texture is the diffuse/albedo channel for its material.
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/red_brick_03/red_brick_03_diff_2k.jpg -O /root/textures/brique_rouge.jpg || echo 'brique fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/red_brick_03/red_brick_03_nor_gl_2k.jpg -O /root/textures/brique_rouge_normal.jpg || echo 'brique norm fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/cobblestone_floor_03/cobblestone_floor_03_diff_1k.jpg -O /root/textures/pierre_taille.jpg || echo 'pierre fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/painted_plaster_wall/painted_plaster_wall_diff_1k.jpg -O /root/textures/enduit.jpg || echo 'enduit fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/asphalt_02/asphalt_02_diff_1k.jpg -O /root/textures/asphalte.jpg || echo 'asphalt fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/concrete_floor_painted/concrete_floor_painted_diff_1k.jpg -O /root/textures/concrete.jpg || echo 'concrete fail'",
        # iter 2026-06-27 (mat2 agent) — matériaux LISSES/PLASTIQUE → on ajoute
        # des textures DÉFINIES pour pierre façade, béton balcon, dallage trottoir.
        # Béton lisse propre (neuf) pour les dalles/sous-faces de balcon : grain
        # béton + normal map → tranche/sous-face lisent comme béton mat, pas aplat.
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/concrete_wall_006/concrete_wall_006_diff_2k.jpg -O /root/textures/beton_lisse.jpg || echo 'beton_lisse fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/concrete_wall_006/concrete_wall_006_nor_gl_2k.jpg -O /root/textures/beton_lisse_normal.jpg || echo 'beton_lisse norm fail'",
        # Pierre/enduit de taille DÉFINIE : mur beige fin avec grain + normal map →
        # remplace l'aplat lisse de la façade par une vraie pierre/enduit claire.
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/beige_wall_001/beige_wall_001_diff_2k.jpg -O /root/textures/pierre_facade.jpg || echo 'pierre_facade fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/beige_wall_001/beige_wall_001_nor_gl_2k.jpg -O /root/textures/pierre_facade_normal.jpg || echo 'pierre_facade norm fail'",
        # Normal map de l'enduit existant (painted plaster) → relief sur enduit_blanc.
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/painted_plaster_wall/painted_plaster_wall_nor_gl_1k.jpg -O /root/textures/enduit_normal.jpg || echo 'enduit norm fail'",
        # Dallage trottoir avec DALLES + JOINTS visibles (vrai trottoir, pas aplat).
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/concrete_pavement_03/concrete_pavement_03_diff_2k.jpg -O /root/textures/dallage.jpg || echo 'dallage fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/2k/concrete_pavement_03/concrete_pavement_03_nor_gl_2k.jpg -O /root/textures/dallage_normal.jpg || echo 'dallage norm fail'",
        # Asphalte avec normal map (grain) → bitume non-aplat.
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/asphalt_02/asphalt_02_nor_gl_1k.jpg -O /root/textures/asphalte_normal.jpg || echo 'asphalt norm fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/wood_planks/wood_planks_diff_1k.jpg -O /root/textures/bois.jpg || echo 'bois fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/metal_corrugated_iron_02/metal_corrugated_iron_02_diff_1k.jpg -O /root/textures/zinc.jpg || echo 'zinc fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/forest_ground_01/forest_ground_01_diff_1k.jpg -O /root/textures/terre.jpg || echo 'terre fail'",
        "wget -q https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/aerial_grass_rock/aerial_grass_rock_diff_1k.jpg -O /root/textures/herbe.jpg || echo 'herbe fail'",
        "ls -la /root/textures/ /root/hdri.hdr 2>&1 || true",
    )
)

@app.cls(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    scaledown_window=180,
)
class BlenderPipeline:
    @modal.enter()
    def load(self):
        """Verify Blender bpy is loaded and Cycles GPU is available."""
        import bpy
        print(f"✓ bpy loaded — Blender {bpy.app.version_string}")
        # Configure Cycles to use GPU (CUDA on the A100).
        prefs = bpy.context.preferences
        cprefs = prefs.addons["cycles"].preferences
        cprefs.compute_device_type = "CUDA"
        cprefs.refresh_devices()
        for d in cprefs.devices:
            d.use = (d.type == "CUDA")
            print(f"  device {d.name} type={d.type} use={d.use}")
        bpy.context.scene.cycles.device = "GPU"
        print("✓ Cycles GPU enabled")
        self.bpy = bpy

    @modal.method()
    def render_from_quads(
        self,
        quads_by_material: dict,         # {material_name: [(v0,v1,v2,v3), ...]}
        camera_pos: tuple,               # (x, y, z) in scene_mesh local coords
        camera_target: tuple,            # (x, y, z)
        camera_fov_deg: float = 42.0,
        sun_direction: tuple = (0.4, -0.6, 0.7),  # default upper-left morning
        width: int = 1024,
        height: int = 1024,
        samples: int = 128,
        tree_positions: Optional[list] = None,    # [(x, y, height_m, canopy_r), ...]
        lamp_positions: Optional[list] = None,    # [(x, y), ...] (height fixed 5m)
        silhouette_mode: bool = False,            # iter #302 : pure white emit on black bg
        add_real_assets: bool = False,            # POC entourage : vrais arbres/voitures/personnes 3D
        photoreal: bool = False,                  # persuasion-mode : Poly Haven PBR textures
        adaptive_threshold: float = 0.01,         # 0 = fixed `samples` (identical pixels);
                                                  # >0 = adaptive sampling, `samples` becomes
                                                  # the max cap, converged pixels stop early.
                                                  # 0.01 validated lossless on Nogent (PSNR
                                                  # 69 dB) for −41 % Cycles time — see ArchiBrain.
    ) -> bytes:
        """Render a scene_mesh Quad list with Cycles path tracing.

        `quads_by_material` maps material names to lists of Quads, where
        each Quad is a 4-tuple of (x,y,z) vertices. Materials supported :
            "enduit_blanc"     → off-white smooth troweled lime render
            "balcon_concrete"  → light grey concrete (balcony slabs)
            "balcon_metal"     → matt anthracite RAL 7016 (railings, partitions)
            "verre"            → clear glass (windows, doors)
            "asphalte"         → matt dark grey asphalt road
            "pavers_concrete"  → pale grey concrete sidewalk pavers
            "pierre_kerb"      → cream-grey limestone (kerbstones, piers)
            "vegetation"       → green sedum / lawn / hedges
            "metal_noir"       → matt black wrought iron (grille, bollards)
            "voisin"           → cream beige neighbor render
        Defaults to "enduit_blanc" if material name unknown.
        """
        import bpy
        # Reset scene.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        # Build PBR materials dict.
        materials = self._build_materials(photoreal=photoreal)

        # Build a single mesh with multiple materials.
        mesh = bpy.data.meshes.new("ProjectMesh")
        verts: list[tuple] = []
        faces: list[tuple] = []
        face_materials: list[int] = []
        material_index: dict[str, int] = {}

        for mat_name, quad_list in quads_by_material.items():
            mat = materials.get(mat_name) or materials["enduit_blanc"]
            if mat_name not in material_index:
                material_index[mat_name] = len(material_index)
            mat_idx = material_index[mat_name]
            for quad in quad_list:
                base = len(verts)
                verts.extend(quad)   # quad = (v0, v1, v2, v3)
                faces.append((base, base + 1, base + 2, base + 3))
                face_materials.append(mat_idx)

        if not verts:
            print("!! no verts to render — empty scene")
            return b""

        mesh.from_pydata(verts, [], faces)
        # Attach materials in the right order.
        ordered_mats = sorted(material_index.items(), key=lambda x: x[1])
        for name, _idx in ordered_mats:
            mesh.materials.append(materials.get(name) or materials["enduit_blanc"])
        for poly, mat_idx in zip(mesh.polygons, face_materials):
            poly.material_index = mat_idx
        mesh.update()

        obj = bpy.data.objects.new("Project", mesh)
        bpy.context.collection.objects.link(obj)
        print(f"✓ mesh built : {len(verts)} verts, {len(faces)} faces, "
              f"{len(material_index)} materials")

        # ── POC ENTOURAGE : VRAIS assets 3D (arbres / voitures / personnes) ──
        # Étape #2 du POC « base seule = photo ». Les proxys carton (quads plats)
        # sont retirés en amont (POC_NOENTOURAGE). On injecte ici de VRAIS objets
        # 3D volumétriques (ombres portées, matière) placés le long du trottoir,
        # PROCHES du carrefour et DEVANT la caméra. Désactivable via
        # add_real_assets=False (silhouette pass, etc.).
        if add_real_assets and not silhouette_mode:
            try:
                self._add_real_entourage(camera_pos, camera_target)
            except Exception as _ea:
                import traceback as _tb
                print(f"!! real-entourage step failed ({_ea})")
                _tb.print_exc()

        # ── Trees as Blender primitives (cylinder trunk + sphere canopy) ──
        # iter #218/#219 showed flat-quad trees look like ad panels.
        # UV sphere + cylinder give organic shapes FLUX reads as trees.
        if tree_positions:
            trunk_mat = materials.get("metal_noir") or materials["enduit_blanc"]
            canopy_mat = materials.get("vegetation") or materials["enduit_blanc"]
            for tx, ty, theight, tradius in tree_positions:
                trunk_h = theight - tradius
                bpy.ops.mesh.primitive_cylinder_add(
                    vertices=8,
                    radius=0.10,
                    depth=trunk_h,
                    location=(tx, ty, trunk_h / 2.0),
                )
                trunk = bpy.context.active_object
                trunk.data.materials.append(trunk_mat)
                bpy.ops.mesh.primitive_uv_sphere_add(
                    radius=tradius,
                    location=(tx, ty, trunk_h + tradius * 0.5),
                    segments=12,
                    ring_count=6,
                )
                canopy = bpy.context.active_object
                canopy.data.materials.append(canopy_mat)
                # Squash slightly for natural ovoid canopy.
                canopy.scale = (1.0, 1.0, 0.85)
            print(f"  + {len(tree_positions)} primitive trees (cylinder + sphere)")

        # ── Lamp posts (OSM man_made=street_lamp) ──
        # Vertical pole 5m + small spherical bulb at top. Pole material =
        # metal_noir (or a "vert RAL 6005" if we add the material).
        if lamp_positions:
            pole_mat = materials.get("metal_noir") or materials["enduit_blanc"]
            for lx, ly in lamp_positions:
                bpy.ops.mesh.primitive_cylinder_add(
                    vertices=8,
                    radius=0.06,
                    depth=5.0,
                    location=(lx, ly, 2.5),
                )
                pole = bpy.context.active_object
                pole.data.materials.append(pole_mat)
                bpy.ops.mesh.primitive_uv_sphere_add(
                    radius=0.18,
                    location=(lx, ly, 5.05),
                    segments=8,
                    ring_count=4,
                )
                bulb = bpy.context.active_object
                bulb.data.materials.append(pole_mat)
            print(f"  + {len(lamp_positions)} street lamps (pole + bulb)")

        # ── Sun light : plein jour ENSOLEILLÉ DOUX — pas golden hour cramé ──
        # iter 2026-06-24 (light agent) : le réglage golden hour (energy 7.5 +
        # élévation forcée 18°) CRAMAIT le côté droit (flare, voisin invisible
        # dans la lumière). AMBIANCE_REELLE = rue claire crème, lumineuse mais
        # DOUCE. On vise donc une lumière de plein jour ensoleillée modelée :
        #   - energy 3.4 : éclaire et modèle sans blowout (était 7.5 → cramait).
        #   - élévation 34° : soleil plus HAUT → sort de l'axe caméra plongeante,
        #     plus de lèche-façade aveuglant, ombres courtes/modelées pas plates.
        #   - azimut DÉCALÉ +28° vers le côté : lumière plus LATÉRALE pour
        #     sculpter les reliefs (bandeaux, encadrements) sans frapper la
        #     caméra de face → tue le flare directionnel côté droit.
        #   - couleur à peine chaude (lumière du jour douce, pas ambre saturé).
        import math
        # iter 2026-06-27 (light2 agent) : constat user = "ne lit pas comme une
        # photo", lumière PLATE et GRISE, ciel laiteux. Les vraies Street View
        # (refs/streetview/survey_*) montrent PLEIN SOLEIL : ciel bleu franc,
        # OMBRES PORTÉES NETTES, façade modelée (un côté chaud / un côté ombre).
        # On RÉ-AUGMENTE le punch directionnel pour ce modelé-là :
        #   - energy 4.2 → 6.2 : soleil franc → ombres portées VISIBLES + fort
        #     modelé. Filmic High Contrast compresse les highlights donc on peut
        #     monter sans cramer (blowout surveillé <1% à 255).
        #   - angle 2.0° → 0.5° : bord d'ombre NET. 2° donnait des ombres molles
        #     qui se lisaient comme de la brume. 0.5° = ombre dure de plein jour
        #     (le soleil réel = ~0.53° de diamètre apparent).
        #   - couleur À PEINE chaude (0.90→0.95 sur G/B) : lumière du jour claire,
        #     pas ambre — l'ambre jaunissait la pierre et tuait la lecture photo.
        sun_data = bpy.data.lights.new(name="Sun", type="SUN")
        sun_data.energy = 7.5                 # plein soleil franc mais split moins dur (face ombre pas noire)
        sun_data.angle = math.radians(0.5)    # bord d'ombre net (réaliste, pas de flou brume)
        sun_data.color = (1.0, 0.96, 0.90)    # lumière du jour ensoleillée (à peine chaude)
        sun_obj = bpy.data.objects.new("Sun", sun_data)
        bpy.context.collection.objects.link(sun_obj)
        # On part de l'AZIMUT fourni par sun_direction (cohérence HDRI), mais on
        # le rend plus LATÉRAL (+28°) et on remonte l'élévation à 34° pour
        # modeler sans flare frontal côté droit.
        # iter 2026-06-27 (light2 agent) : on RAKE davantage le soleil en travers
        # des deux faces visibles du coin (offset +28° → +55°) pour un vrai
        # split lumière/ombre (une face au soleil, l'autre à l'ombre = le modelé
        # qui fait la photo), et on abaisse un peu l'élévation (34° → 30°) pour
        # des ombres portées plus LONGUES et lisibles au sol sans flare frontal.
        sx, sy, sz = sun_direction
        _az = math.atan2(sx, -sy) + math.radians(22.0)   # rake modéré : éclaire le coin face caméra + garde un côté à l'ombre
        _elev = math.radians(30.0)            # soleil un peu plus bas → ombres longues lisibles
        sx = math.cos(_elev) * math.sin(_az)
        sy = -math.cos(_elev) * math.cos(_az)
        sz = math.sin(_elev)
        sun_obj.rotation_euler = (math.atan2(-sy, sz), math.atan2(sx, sz), 0.0)

        # ── Sky : Poly Haven HDRI (real photo + clouds) with fallback ──
        world = bpy.data.worlds.new("World")
        world.use_nodes = True
        nt = world.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        bg = nt.nodes.new("ShaderNodeBackground")
        out = nt.nodes.new("ShaderNodeOutputWorld")

        # iter #302 — SILHOUETTE MODE : black world + replace ALL materials
        # with pure white EMISSION shaders. The resulting render is a
        # binary mask (white = main-building pixels, black = everywhere
        # else). Used by the FLUX composite to lock the building silhouette
        # exactly — no more depth-mask ambiguity (holes under building, ghost
        # transparency). All atmospheric/lighting/colour settings below are
        # skipped because we just want a clean alpha matte.
        if silhouette_mode:
            bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            bg.inputs["Strength"].default_value = 0.0
            nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
            scene.world = world
            # Override every material on the project mesh with pure white emit.
            white_emit = bpy.data.materials.new("silhouette_white")
            white_emit.use_nodes = True
            wnt = white_emit.node_tree
            for n in list(wnt.nodes):
                wnt.nodes.remove(n)
            emit = wnt.nodes.new("ShaderNodeEmission")
            emit.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            emit.inputs["Strength"].default_value = 1.0
            wout = wnt.nodes.new("ShaderNodeOutputMaterial")
            wnt.links.new(emit.outputs["Emission"], wout.inputs["Surface"])
            for slot_i in range(len(mesh.materials)):
                mesh.materials[slot_i] = white_emit
            # Filmic colour transform would crush pure-white emission down
            # to ~0.85, blurring the binary edges. Use Standard for crisp
            # 1.0 silhouette → background ratio.
            scene.view_settings.view_transform = "Standard"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0.0
            # Cycles config — minimal samples (no lighting/denoising needed).
            scene.render.engine = "CYCLES"
            scene.cycles.device = "GPU"
            scene.cycles.samples = 16
            scene.cycles.use_denoising = False
            scene.render.resolution_x = width
            scene.render.resolution_y = height
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = "/tmp/blender_silhouette.png"
            # Camera (re-use main camera setup below — return early if camera
            # not yet built; in practice the camera section runs BEFORE this
            # block because we restructured). Defer to main camera block.
            # NB : the camera + render call still happen below in the normal
            # flow. The silhouette block only changes world/material/view.
            print(f"→ Cycles SILHOUETTE pass {width}×{height} samples=16 GPU …")
            # Set up camera (same as the regular block below) inline so we
            # can short-circuit cleanly and skip the rest of the lighting /
            # render block.
            cam_data = bpy.data.cameras.new(name="CamSilhouette")
            cam_data.lens_unit = "FOV"
            cam_data.angle = math.radians(camera_fov_deg)
            cam_obj = bpy.data.objects.new("CamSilhouette", cam_data)
            cam_obj.location = camera_pos
            bpy.context.collection.objects.link(cam_obj)
            from mathutils import Vector
            direction = Vector(camera_target) - Vector(camera_pos)
            cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
            scene.camera = cam_obj
            bpy.ops.render.render(write_still=True)
            print(f"✓ silhouette render complete")
            return Path("/tmp/blender_silhouette.png").read_bytes()

        hdri_path = "/root/hdri.hdr"
        import os as _os
        used_hdri = False
        if _os.path.exists(hdri_path) and _os.path.getsize(hdri_path) > 100_000:
            try:
                hdri_img = bpy.data.images.load(hdri_path)
                env_node = nt.nodes.new("ShaderNodeTexEnvironment")
                env_node.image = hdri_img
                # Mapping → rotate the HDRI so the sun lines up with our
                # geometry (sun_direction param).
                tex_coord = nt.nodes.new("ShaderNodeTexCoord")
                mapping = nt.nodes.new("ShaderNodeMapping")
                mapping.inputs["Rotation"].default_value[2] = math.radians(140)
                nt.links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
                nt.links.new(mapping.outputs["Vector"], env_node.inputs["Vector"])
                # iter 2026-06-24 : le HDRI puresky est NEUTRE/FROID (bleu-gris).
                # On le RÉCHAUFFE pour un ciel golden hour : (1) Hue/Sat décale
                # légèrement la teinte vers le chaud, (2) un Mix MULTIPLY ambre
                # baigne l'ensemble dans une dominante fin d'après-midi. Le fill
                # ambiant qui éclaire les ombres devient ainsi chaud (plus de
                # bleu froid dans les zones d'ombre).
                # iter 2026-06-24 (light agent) : on calme le grade ambre (il
                # virait orange + assombrissait le fill, ce qui forçait à monter
                # le soleil → flare). Léger réchauffement seulement ; le ciel
                # reste un fill diffus CLAIR qui débouche les ombres et baigne
                # la pierre crème dans une lumière douce.
                # iter 2026-06-27 (light2 agent) : HDRI = qwantani_noon (ciel
                # bleu midi dégagé). Il est DÉJÀ bleu donc on sature modérément
                # (1.30) pour un bleu d'été franc sans virer cyan irréel, et on
                # densifie un peu (Value 0.94) pour qu'il ne lave pas en blanc.
                hsv = nt.nodes.new("ShaderNodeHueSaturation")
                hsv.inputs["Saturation"].default_value = 1.30   # bleu d'été franc
                hsv.inputs["Value"].default_value = 0.94        # ciel dense (pas blanc lavé)
                nt.links.new(env_node.outputs["Color"], hsv.inputs["Color"])
                # iter 2026-06-26 (atmo agent) — ANTI-BRUME / horizon cramé.
                # Le puresky est ÉBLOUISSANT à l'horizon (bande Z≈0.5) : pile là
                # où se trouvent les bâtiments voisins. Avec Filmic+exposure ils
                # se noyaient dans le blanc (côté droit + fond du cadre lavés).
                # On atténue UNIQUEMENT la bande d'horizon par un dégradé
                # vertical : on lit le Z du vecteur de direction du ciel
                # (Generated → Separate XYZ → Z), on le remappe en masque
                # [horizon→plancher .. ciel haut→1] et on multiplie le ciel par
                # ce masque (jamais nul). Le HAUT du ciel reste lumineux et
                # ensoleillé, mais l'HORIZON redescend assez pour que les
                # volumes voisins ressortent → profondeur photographique.
                # ORDRE IMPORTANT : on applique le dégradé AVANT le grade chaud,
                # comme ça le réchauffement (multiply ambre) teinte aussi la
                # bande d'horizon assombrie → l'horizon reste CHAUD, pas gris.
                sep = nt.nodes.new("ShaderNodeSeparateXYZ")
                nt.links.new(tex_coord.outputs["Generated"], sep.inputs["Vector"])
                # Z du Generated ≈ 0.5 à l'horizon, →1 au zénith, →0 au nadir.
                horizon_map = nt.nodes.new("ShaderNodeMapRange")
                horizon_map.inputs["From Min"].default_value = 0.46
                horizon_map.inputs["From Max"].default_value = 0.82
                horizon_map.inputs["To Min"].default_value = 0.78   # iter light2 : plancher remonté → horizon reste BLEU (qwantani clear), pas gris
                horizon_map.inputs["To Max"].default_value = 1.0    # ciel haut : pleine luminosité
                horizon_map.clamp = True
                nt.links.new(sep.outputs["Z"], horizon_map.inputs["Value"])
                horizon_atten = nt.nodes.new("ShaderNodeMixRGB")
                horizon_atten.blend_type = "MULTIPLY"
                horizon_atten.inputs["Fac"].default_value = 1.0
                nt.links.new(hsv.outputs["Color"], horizon_atten.inputs["Color1"])
                nt.links.new(horizon_map.outputs["Result"], horizon_atten.inputs["Color2"])

                # iter 2026-06-27 (light2 agent) : le grade ambre MULTIPLY
                # fac=0.50 (1.0,0.81,0.60) était la CAUSE n°1 du ciel laiteux/
                # jaune — il repeignait le bleu en crème chaud et baignait toute
                # la scène dans une dominante terne. On le RETIRE quasiment :
                # fac 0.50 → 0.10 et un ambre BEAUCOUP plus léger (0.97,0.94,0.90),
                # juste de quoi éviter un fill cyan glacé dans les ombres SANS
                # tuer le bleu du ciel. Le ciel reste BLEU, l'ambiance ensoleillée
                # vient du soleil directionnel chaud, pas d'un wash global ambre.
                warm = nt.nodes.new("ShaderNodeMixRGB")
                warm.blend_type = "MULTIPLY"
                warm.inputs["Fac"].default_value = 0.10           # réchauffement minimal (garde le bleu)
                warm.inputs["Color2"].default_value = (0.97, 0.94, 0.90, 1.0)  # quasi neutre tiède
                nt.links.new(horizon_atten.outputs["Color"], warm.inputs["Color1"])
                nt.links.new(warm.outputs["Color"], bg.inputs["Color"])
                # strength : fill ambiant qui débouche les ombres. Baissé
                # 0.80 → 0.62 : avec un soleil plus fort (energy 6.2) le fill HDRI
                # peut être plus bas → meilleur CONTRASTE soleil/ombre (les ombres
                # ne sont plus débouchées à plat) tout en restant lisibles. Évite
                # aussi de cramer la pierre claire côté soleil.
                # PHASE 1 (photo agent) : le POV corner montrait une face à
                # l'ombre BOUCHÉE (presque noire) = tell CGI. En plein soleil
                # réel le ciel bleu remplit fortement les ombres → elles restent
                # LISIBLES (cf. réfs SV : faces nord crème-gris, jamais noires).
                # On remonte le fill ambiant 0.78 → 1.0. AgX compresse le haut
                # donc la face soleil ne crame pas malgré le fill plus fort.
                bg.inputs["Strength"].default_value = 1.0   # fill plein-soleil : ombres débouchées, lisibles
                used_hdri = True
                print("✓ HDRI environment loaded (puresky) + bleu saturé + soleil franc")
            except Exception as e:
                print(f"!! HDRI load failed ({e}) — fallback to procedural sky")
        if not used_hdri:
            sky = nt.nodes.new("ShaderNodeTexSky")
            sky.sky_type = "MULTIPLE_SCATTERING"
            for attr, val in (
                ("sun_elevation", math.radians(45)),
                ("sun_rotation",  math.radians(140)),
                ("air_density",   1.2),
                ("dust_density",  1.0),
                ("altitude",      50.0),
            ):
                if hasattr(sky, attr):
                    try: setattr(sky, attr, val)
                    except Exception: pass
            nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
            bg.inputs["Strength"].default_value = 0.6
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
        scene.world = world

        # ── Color management : AgX (PHASE 1, photo agent 2026-06-27) ──
        # On passe Filmic → AgX. AgX est le tone-mapper de référence pour le
        # photoréalisme (desaturation progressive des highlights, pas de
        # virage de teinte sur la pierre claire en plein soleil ; rendu
        # « caméra » plutôt que « CGI saturé »). Filmic High Contrast donnait
        # une image dense mais qui « claquait » trop façon 3D. AgX + look
        # Medium High Contrast garde le punch ensoleillé tout en restant doux
        # comme une vraie photo. On laisse un fallback Filmic si AgX absent.
        try:
            scene.view_settings.view_transform = "AgX"
            # Look AgX : « AgX - Medium High Contrast » donne le contraste
            # ensoleillé sans cramer la pierre crème. On tente les noms
            # connus, fallback sur le premier look AgX dispo.
            for _look in ("AgX - Medium High Contrast", "AgX - Base Contrast",
                          "Medium High Contrast", "None"):
                try:
                    scene.view_settings.look = _look
                    break
                except Exception:
                    continue
            print("✓ color management : AgX")
        except Exception as _e:
            scene.view_settings.view_transform = "Filmic"
            scene.view_settings.look = "High Contrast"
            print(f"!! AgX unavailable ({_e}) — fallback Filmic High Contrast")
        # exposure : AgX est légèrement plus sombre que Filmic dans les
        # midtones → on remonte +0.3 EV pour retrouver une façade claire
        # ensoleillée sans cramer (AgX compresse fort le haut).
        scene.view_settings.exposure = 0.55   # façade plus claire (réf SV = murs lumineux)
        scene.view_settings.gamma = 1.0

        # ── Camera (avec PROFONDEUR DE CHAMP — signature photo) ──
        cam_data = bpy.data.cameras.new(name="Cam")
        cam_data.lens_unit = "FOV"
        cam_data.angle = math.radians(camera_fov_deg)
        cam_obj = bpy.data.objects.new("Cam", cam_data)
        cam_obj.location = camera_pos
        bpy.context.collection.objects.link(cam_obj)
        # Aim camera at target by computing rotation.
        from mathutils import Vector
        direction = Vector(camera_target) - Vector(camera_pos)
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam_obj

        # DOF : mise au point sur le bâtiment (camera_target), arrière-plan
        # (voisins lointains, ciel) légèrement flou → signature optique d'une
        # VRAIE photo prise au reflex. f/5.6 = flou doux qui n'écrase pas la
        # netteté du bâtiment principal mais détache le fond. focus_distance
        # = distance caméra→cible exacte pour que la façade soit nette.
        _focus_dist = (Vector(camera_target) - Vector(camera_pos)).length
        cam_data.dof.use_dof = True
        cam_data.dof.focus_distance = _focus_dist
        cam_data.dof.aperture_fstop = 5.6
        cam_data.dof.aperture_blades = 7   # bokeh hexagonal réaliste
        print(f"✓ DOF on — focus {_focus_dist:.1f} m, f/5.6")

        # Cycles config.
        scene.render.engine = "CYCLES"
        scene.cycles.device = "GPU"
        scene.cycles.samples = samples
        # ── Denoiser OpenImageDenoise (PHASE 1) ──
        # OIDN (Intel) = denoiser de référence pour le photoréalisme : nettoie
        # le bruit Cycles sans baver les détails. On le configure explicitement
        # avec passes Albedo+Normal (guides) → bords nets, matières préservées.
        scene.cycles.use_denoising = True
        try:
            scene.cycles.denoiser = "OPENIMAGEDENOISE"
            scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
            if hasattr(scene.cycles, "denoising_prefilter"):
                scene.cycles.denoising_prefilter = "ACCURATE"
            print("✓ denoiser : OpenImageDenoise (Albedo+Normal guides)")
        except Exception as _e:
            print(f"!! OIDN config failed ({_e}) — default denoiser")
        # ── Light path bounces : GI suffisante pour le rebond de lumière ──
        # Le verre (transmission) + l'ambiance réaliste ont besoin de bounces
        # généreux pour que la lumière traverse les baies et rebondisse dans la
        # rue (sous-faces de balcon débouchées, fenêtres avec profondeur).
        scene.cycles.max_bounces = 12
        scene.cycles.diffuse_bounces = 6
        scene.cycles.glossy_bounces = 8
        scene.cycles.transmission_bounces = 12   # verre : assez de bounces pour la profondeur
        scene.cycles.transparent_max_bounces = 12
        # Adaptive sampling : Cycles stops sampling pixels that have already
        # converged (flat sky / enduit / asphalte) and pours the budget into
        # noisy regions. `samples` becomes the per-pixel cap. Perceptually
        # lossless ; default off (threshold 0) keeps the exact prior behaviour.
        if adaptive_threshold > 0.0:
            scene.cycles.use_adaptive_sampling = True
            scene.cycles.adaptive_threshold = adaptive_threshold
        else:
            scene.cycles.use_adaptive_sampling = False
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = "/tmp/blender_scene.png"

        print(f"→ Cycles {width}×{height} samples={samples} "
              f"adaptive={adaptive_threshold or 'off'} GPU …")
        import time as _time
        _t0 = _time.time()
        bpy.ops.render.render(write_still=True)
        _dt = _time.time() - _t0
        print(f"✓ render complete — RENDER_SECONDS={_dt:.2f}")
        return Path("/tmp/blender_scene.png").read_bytes()

    # ──────────────────────────────────────────────────────────────────────
    # POC ENTOURAGE — VRAIS assets 3D (arbres / voitures / personnes)
    # ──────────────────────────────────────────────────────────────────────
    def _add_real_entourage(self, camera_pos, camera_target):
        """Place QUELQUES vrais assets 3D le long du trottoir, proches du
        carrefour et devant la caméra. Volume réel + ombres portées + matière
        (vs proxys carton plats). Tout est procédural/intégré → zéro download
        obligatoire (les cutouts CC0 sont tentés mais ont un fallback 3D).

        Repère : coords locales scene_mesh. Sol à z≈0. JUNCTION ≈ (11.9, 32.5).
        La caméra regarde grosso modo vers -Y (carrefour → bâtiment).
        """
        import bpy, math, os
        from mathutils import Vector

        cam = Vector(camera_pos)
        tgt = Vector(camera_target)
        fwd = (tgt - cam)
        fwd.z = 0.0
        if fwd.length < 1e-6:
            fwd = Vector((0.0, -1.0, 0.0))
        fwd.normalize()
        # Vecteur « droite » au sol (perpendiculaire à la visée) pour décaler
        # les assets latéralement de l'axe caméra→cible vers le trottoir.
        right = Vector((fwd.y, -fwd.x, 0.0))

        def ground_point(dist, lateral):
            """Point au sol à `dist` m devant la caméra, décalé de `lateral` m
            sur la droite (latéral). z=0."""
            p = cam + fwd * dist + right * lateral
            return (p.x, p.y, 0.0)

        # ── Matériaux dédiés entourage ─────────────────────────────────────
        def _mat_leaves():
            m = bpy.data.materials.new("entourage_leaves")
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            # vert feuillage été, légère translucence simulée par base color claire
            bsdf.inputs["Base Color"].default_value = (0.10, 0.26, 0.07, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.85
            # variation de teinte par noise pour casser l'aplat
            noise = nt.nodes.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = 6.0
            noise.inputs["Detail"].default_value = 5.0
            cr = nt.nodes.new("ShaderNodeValToRGB")
            cr.color_ramp.elements[0].color = (0.07, 0.18, 0.04, 1.0)
            cr.color_ramp.elements[1].color = (0.16, 0.34, 0.10, 1.0)
            nt.links.new(noise.outputs["Fac"], cr.inputs["Fac"])
            nt.links.new(cr.outputs["Color"], bsdf.inputs["Base Color"])
            # micro-bump pour accrocher la lumière
            bump = nt.nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = 0.25
            nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
            nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            return m

        def _mat_bark():
            m = bpy.data.materials.new("entourage_bark")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (0.18, 0.12, 0.08, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.9
            return m

        def _mat_carpaint(rgb):
            m = bpy.data.materials.new("entourage_carpaint")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.85
            bsdf.inputs["Roughness"].default_value = 0.28
            for k in ("Coat Weight", "Clearcoat", "Coat"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = 1.0
                    break
            for k in ("Coat Roughness", "Clearcoat Roughness"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = 0.05
                    break
            return m

        def _mat_glass_dark():
            m = bpy.data.materials.new("entourage_carglass")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (0.02, 0.03, 0.04, 1.0)
            bsdf.inputs["Metallic"].default_value = 0.0
            bsdf.inputs["Roughness"].default_value = 0.08
            for k in ("Specular IOR Level", "Specular"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = 0.9
                    break
            return m

        def _mat_rubber():
            m = bpy.data.materials.new("entourage_rubber")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.8
            return m

        def _mat_chrome():
            m = bpy.data.materials.new("entourage_chrome")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.82, 1.0)
            bsdf.inputs["Metallic"].default_value = 1.0
            bsdf.inputs["Roughness"].default_value = 0.15
            return m

        def _mat_cloth(rgb):
            m = bpy.data.materials.new("entourage_cloth")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.9
            return m

        def _mat_skin():
            m = bpy.data.materials.new("entourage_skin")
            m.use_nodes = True
            nt = m.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (0.62, 0.46, 0.38, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.65
            return m

        leaves_mat = _mat_leaves()
        bark_mat = _mat_bark()
        rubber_mat = _mat_rubber()
        chrome_mat = _mat_chrome()
        carglass_mat = _mat_glass_dark()
        skin_mat = _mat_skin()

        # ════════════════════════ 1) ARBRES (Sapling) ════════════════════════
        n_trees = 0
        sapling_ok = False
        try:
            try:
                bpy.ops.preferences.addon_enable(module="add_curve_sapling")
            except Exception:
                bpy.ops.preferences.addon_enable(module="add_curve_extra_objects")
            sapling_ok = hasattr(bpy.ops.curve, "tree_add")
        except Exception as e:
            print(f"  !! Sapling addon enable failed ({e})")

        # Positions arbres : sur le trottoir, latéral +6 m (côté droit de la
        # visée), à 16 m et 30 m de la caméra → encadrent le carrefour.
        tree_spots = [
            ground_point(17.0, 7.5),
            ground_point(30.0, 9.0),
        ]
        if sapling_ok:
            for ti, (tx, ty, tz) in enumerate(tree_spots):
                try:
                    bpy.ops.curve.tree_add(
                        do_update=True,
                        bevel=True,
                        prune=False,
                        showLeaves=True,
                        useArm=False,
                        levels=3,
                        length=(0.9, 0.45, 0.45, 0.45),
                        branches=(0, 28, 22, 1),
                        leaves=180,
                        leafScale=0.32,
                        ratio=0.018,
                        scale=6.0, scaleV=0.8,
                    )
                except Exception:
                    # Signature ops varie selon versions → fallback presets.
                    bpy.ops.curve.tree_add(do_update=True, showLeaves=True)
                # Le tronc (curve) est l'objet actif ; les feuilles sont un
                # mesh enfant créé dans la foulée. On les déplace ensemble.
                created = [o for o in bpy.context.selected_objects]
                tree_curve = bpy.context.active_object
                grp = set(created) | {tree_curve}
                # Récupère aussi un éventuel objet "leaves" récent.
                for o in bpy.data.objects:
                    if o.name.lower().startswith("leaves") and o not in grp:
                        grp.add(o)
                for o in grp:
                    o.location = (o.location.x + tx, o.location.y + ty, o.location.z + tz)
                    nm = o.name.lower()
                    if "leaves" in nm or "leaf" in nm:
                        o.data.materials.clear() if hasattr(o.data, "materials") else None
                        try: o.data.materials.append(leaves_mat)
                        except Exception: pass
                    else:
                        try:
                            o.data.materials.clear()
                            o.data.materials.append(bark_mat)
                        except Exception:
                            pass
                n_trees += 1
            print(f"  + {n_trees} Sapling trees (vrai arbre ramifié + feuillage)")
        if not sapling_ok or n_trees == 0:
            # Fallback : tronc conique haut + 3 amas de feuillage (icosphères
            # lissées, bruitées, de tailles/positions variées) → silhouette
            # d'arbre organique (pas une boule low-poly). Smooth shading +
            # subdivisions=4 tuent l'aspect facetté.
            import random as _rnd
            _rnd.seed(7)
            for ci, (tx, ty, tz) in enumerate(tree_spots):
                trunk_h = 2.6
                # Tronc légèrement conique (cône tronqué) → vrai tronc.
                bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.22,
                                                radius2=0.12, depth=trunk_h,
                                                location=(tx, ty, trunk_h / 2))
                trunk = bpy.context.active_object
                bpy.ops.object.shade_smooth()
                trunk.data.materials.append(bark_mat)
                # 3 amas de feuillage formant une couronne organique.
                clusters = [
                    (0.0, 0.0, trunk_h + 1.7, 2.3),
                    (0.9, 0.5, trunk_h + 2.6, 1.7),
                    (-0.8, -0.6, trunk_h + 2.3, 1.8),
                ]
                for (dx, dy, dz, r) in clusters:
                    rr = r * (0.92 + 0.16 * _rnd.random())
                    bpy.ops.mesh.primitive_ico_sphere_add(
                        subdivisions=4, radius=rr,
                        location=(tx + dx, ty + dy, dz))
                    can = bpy.context.active_object
                    can.scale = (1.0, 1.0, 1.05)
                    bpy.ops.object.shade_smooth()
                    # déformation organique pour casser la sphère parfaite
                    bpy.ops.object.modifier_add(type="DISPLACE")
                    try:
                        disp = can.modifiers[-1]
                        tex = bpy.data.textures.new("canopy_noise", type="CLOUDS")
                        tex.noise_scale = 0.5
                        disp.texture = tex
                        disp.strength = 0.5
                    except Exception:
                        pass
                    can.data.materials.append(leaves_mat)
                n_trees += 1
            print(f"  + {n_trees} fallback trees (tronc conique + 3 amas feuillage lissés)")

        # ════════════════════════ 2) VOITURES (procédural) ════════════════════
        # Pas de modèle CC0 fiable garanti en headless → carrosserie low-poly
        # crédible : châssis + cabine inclinée (boolean-free, profil biseauté) +
        # 4 roues cylindriques + vitres. Matériau car-paint metallic + clearcoat.
        def build_car(origin, heading_deg, color):
            ox, oy, oz = origin
            paint = _mat_carpaint(color)
            parts = []
            L, W = 4.3, 1.8          # longueur / largeur réelles
            # Corps bas (capot/coffre) : boîte biseautée.
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.55))
            body = bpy.context.active_object
            body.scale = (L / 2, W / 2, 0.45)
            bpy.ops.object.transform_apply(scale=True)
            bpy.ops.object.modifier_add(type="BEVEL")
            body.modifiers[-1].width = 0.18
            body.modifiers[-1].segments = 2
            body.data.materials.append(paint)
            parts.append(body)
            # Cabine (toit) plus étroite et reculée, biseautée → pare-brise incliné.
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.15, 0, 1.15))
            cab = bpy.context.active_object
            cab.scale = (L / 4.2, W / 2.4, 0.32)
            bpy.ops.object.transform_apply(scale=True)
            bpy.ops.object.modifier_add(type="BEVEL")
            cab.modifiers[-1].width = 0.28
            cab.modifiers[-1].segments = 3
            cab.data.materials.append(carglass_mat)
            parts.append(cab)
            # Roues : 4 cylindres couchés.
            for wx, wy in ((L/2 - 0.95, W/2 - 0.05), (L/2 - 0.95, -(W/2 - 0.05)),
                           (-(L/2 - 0.95), W/2 - 0.05), (-(L/2 - 0.95), -(W/2 - 0.05))):
                bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.34,
                                                    depth=0.22, location=(wx, wy, 0.34),
                                                    rotation=(math.radians(90), 0, 0))
                w = bpy.context.active_object
                w.data.materials.append(rubber_mat)
                parts.append(w)
            # Joindre, orienter, positionner.
            for p in parts:
                p.select_set(True)
            bpy.context.view_layer.objects.active = body
            bpy.ops.object.join()
            car = bpy.context.active_object
            car.rotation_euler = (0, 0, math.radians(heading_deg))
            car.location = (ox, oy, oz)
            return car

        # Heading aligné approx. avec la rue (le long de la visée caméra).
        street_heading = math.degrees(math.atan2(fwd.y, fwd.x))
        car_specs = [
            (ground_point(24.0, 1.5), street_heading + 4, (0.12, 0.16, 0.28)),    # bleu, sur chaussée
            (ground_point(36.0, -6.0), street_heading + 182, (0.55, 0.06, 0.07)), # rouge, sens inverse
        ]
        n_cars = 0
        for (pos, hd, col) in car_specs:
            try:
                build_car(pos, hd, col)
                n_cars += 1
            except Exception as e:
                print(f"  !! car build failed ({e})")
        print(f"  + {n_cars} voitures low-poly (car-paint metallic + clearcoat + vitres)")

        # ════════════════════════ 3) PERSONNES ════════════════════════════════
        # Tentative cutout photo CC0 (PNG alpha) sur plan face-caméra. Si pas de
        # source fiable → figures low-poly proportionnées (tête/torse/jambes).
        # Personnes : sur le trottoir côté droit, ÉCHELONNÉES en distance et
        # espacées latéralement pour qu'elles se lisent individuellement
        # (l'angle plongeant tasse la perspective → on évite le cluster).
        person_spots = [
            ground_point(12.0, 6.0),
            ground_point(15.5, 9.0),
            ground_point(21.0, 7.0),
            ground_point(28.0, 11.0),
        ]
        cutout_png = "/root/textures/person_cutout.png"
        cutout_ok = False
        if not os.path.exists(cutout_png):
            # Sources CC0 possibles (silhouettes alpha). Best-effort, timeout court.
            for url in (
                "https://dl.polyhaven.org/file/ph-assets/Models/png/1k/person/person.png",
            ):
                try:
                    import subprocess
                    subprocess.run(["wget", "-q", "-T", "8", url, "-O", cutout_png],
                                   check=True, timeout=12)
                    if os.path.getsize(cutout_png) > 2000:
                        cutout_ok = True
                        break
                except Exception:
                    pass
        else:
            cutout_ok = os.path.getsize(cutout_png) > 2000

        def build_person_lowpoly(origin, cloth_rgb):
            ox, oy, oz = origin
            cloth = _mat_cloth(cloth_rgb)
            parts = []
            # Jambes (deux cylindres) 0.0 → 0.85
            for lx in (-0.11, 0.11):
                bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.08,
                                                    depth=0.85, location=(lx, 0, 0.43))
                leg = bpy.context.active_object
                leg.data.materials.append(cloth)
                parts.append(leg)
            # Torse (cube biseauté) 0.85 → 1.42
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.13))
            torso = bpy.context.active_object
            torso.scale = (0.20, 0.13, 0.30)
            bpy.ops.object.transform_apply(scale=True)
            bpy.ops.object.modifier_add(type="BEVEL")
            torso.modifiers[-1].width = 0.06
            torso.data.materials.append(cloth)
            parts.append(torso)
            # Bras (deux cylindres le long du corps)
            for ax in (-0.24, 0.24):
                bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=0.05,
                                                    depth=0.55, location=(ax, 0, 1.12))
                arm = bpy.context.active_object
                arm.data.materials.append(cloth)
                parts.append(arm)
            # Tête (icosphère) ~1.55 → 1.72
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.115,
                                                  location=(0, 0, 1.60))
            head = bpy.context.active_object
            head.data.materials.append(skin_mat)
            parts.append(head)
            for p in parts:
                p.select_set(True)
            bpy.context.view_layer.objects.active = torso
            bpy.ops.object.join()
            person = bpy.context.active_object
            person.location = (ox, oy, oz)
            return person

        n_people = 0
        # Couleurs vêtements variées et assez contrastées pour se détacher du
        # damier clair du trottoir (sinon les figures se noient en gris).
        cloth_palette = [(0.18, 0.30, 0.55), (0.60, 0.18, 0.16),
                         (0.85, 0.82, 0.78), (0.25, 0.45, 0.30)]
        if cutout_ok:
            try:
                img = bpy.data.images.load(cutout_png)
                pmat = bpy.data.materials.new("entourage_person_cutout")
                pmat.use_nodes = True
                pmat.blend_method = "CLIP"
                nt = pmat.node_tree
                bsdf = nt.nodes.get("Principled BSDF")
                tex = nt.nodes.new("ShaderNodeTexImage")
                tex.image = img
                nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
                nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
                bsdf.inputs["Roughness"].default_value = 0.7
                for (px, py, pz) in person_spots:
                    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(px, py, 0.9))
                    pl = bpy.context.active_object
                    pl.rotation_euler = (math.radians(90), 0,
                                         math.atan2(cam.y - py, cam.x - px) + math.radians(90))
                    pl.scale = (0.7, 1.8, 1.0)
                    pl.data.materials.append(pmat)
                    n_people += 1
                print(f"  + {n_people} personnes (cutout photo CC0 face-caméra)")
            except Exception as e:
                print(f"  !! cutout people failed ({e}) — fallback low-poly")
                cutout_ok = False
        if not cutout_ok:
            for i, (px, py, pz) in enumerate(person_spots):
                try:
                    build_person_lowpoly((px, py, pz), cloth_palette[i % len(cloth_palette)])
                    n_people += 1
                except Exception as e:
                    print(f"  !! person build failed ({e})")
            print(f"  + {n_people} personnes low-poly (tête/torse/bras/jambes proportionnés)")

        print(f"✓ entourage 3D réel : {n_trees} arbres, {n_cars} voitures, {n_people} personnes")

    def _build_materials(self, photoreal: bool = False) -> dict:
        """Build a dict of PBR materials for the scene.

        `photoreal=True` swaps the key facade / ground / vegetation materials
        from flat-colour `_make_principled` to Poly Haven PBR via
        `_make_textured`. Used in persuasion-mode (brochure renders that go
        through the SDXL + LoRA pipeline) — the LoRA polishes the realistic
        texture into a clean new brick brochure look. For PC-dossier mode
        we keep flat colours so the building reads as new construction
        (the 2026-05 textured tests looked « 20 years dirty »).
        """
        import bpy
        mats: dict = {}

        import os as _os_mat
        def _make_textured(name: str, tex_path: str, normal_path: str | None = None,
                           tile_size_m: float = 2.0, fallback_color=(0.7, 0.7, 0.7),
                           roughness: float = 0.7, metallic: float = 0.0, specular: float = 0.3,
                           color_break: float = 0.0, break_scale: float = 0.9,
                           normal_strength: float = 0.8, tint=None,
                           rough_var: float = 0.0, rough_var_scale: float = 6.0,
                           bump_strength: float = 0.0):
            """PBR material : diffuse texture + optional normal map, tiled by tile_size_m in world space.

            Uses Object texture coords (world space meters) + Mapping scale
            = 1/tile_size to tile across building automatically. If texture
            file missing, falls back to flat color.
            """
            m = bpy.data.materials.new(name=name)
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Roughness"].default_value = roughness
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = metallic
            for k in ("Specular IOR Level", "Specular"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = specular
                    break
            if _os_mat.path.exists(tex_path) and _os_mat.path.getsize(tex_path) > 1000:
                tex_coord = nt.nodes.new("ShaderNodeTexCoord")
                mapping = nt.nodes.new("ShaderNodeMapping")
                mapping.inputs["Scale"].default_value = (1.0/tile_size_m, 1.0/tile_size_m, 1.0/tile_size_m)
                tex = nt.nodes.new("ShaderNodeTexImage")
                try:
                    tex.image = bpy.data.images.load(tex_path)
                    tex.image.colorspace_settings.name = "sRGB"
                    nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])
                    nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
                    if color_break > 0:
                        # Variation tonale MACRO : un bruit grande-échelle (en
                        # mètres-monde, indépendant du tiling) module la couleur
                        # par zones — certaines briques plus chaudes/sombres,
                        # d'autres plus claires. Casse l'aspect texture-tuilée
                        # uniforme et donne la lecture "brique-par-brique" réelle.
                        bcoord = nt.nodes.new("ShaderNodeTexCoord")
                        bmap = nt.nodes.new("ShaderNodeMapping")
                        bmap.inputs["Scale"].default_value = (break_scale, break_scale, break_scale)
                        noise = nt.nodes.new("ShaderNodeTexNoise")
                        noise.inputs["Scale"].default_value = 1.0
                        noise.inputs["Detail"].default_value = 4.0
                        if "Roughness" in noise.inputs:
                            noise.inputs["Roughness"].default_value = 0.6
                        ramp = nt.nodes.new("ShaderNodeValToRGB")
                        # rampe resserrée autour de 1.0 → multiplie ±, garde la teinte
                        ramp.color_ramp.elements[0].position = 0.30
                        ramp.color_ramp.elements[0].color = (1.0 - 0.45 * color_break,) * 3 + (1.0,)
                        ramp.color_ramp.elements[1].position = 0.72
                        ramp.color_ramp.elements[1].color = (1.0 + 0.30 * color_break,) * 3 + (1.0,)
                        mix = nt.nodes.new("ShaderNodeMixRGB")
                        mix.blend_type = "MULTIPLY"
                        mix.inputs["Fac"].default_value = 1.0
                        nt.links.new(bcoord.outputs["Object"], bmap.inputs["Vector"])
                        nt.links.new(bmap.outputs["Vector"], noise.inputs["Vector"])
                        nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
                        nt.links.new(tex.outputs["Color"], mix.inputs["Color1"])
                        nt.links.new(ramp.outputs["Color"], mix.inputs["Color2"])
                        color_out = mix.outputs["Color"]
                    else:
                        color_out = tex.outputs["Color"]
                    # TINT optionnel : multiplie l'albédo de la photo par une
                    # teinte cible → on impose la couleur (ex. crème clair) quelle
                    # que soit la dominante propre de la texture (qui peut être
                    # plus brune/grise). Garde le GRAIN + le relief de la photo
                    # mais aligne la teinte sur le matériau voulu.
                    if tint is not None:
                        tnode = nt.nodes.new("ShaderNodeMixRGB")
                        tnode.blend_type = "MULTIPLY"
                        tnode.inputs["Fac"].default_value = 1.0
                        tnode.inputs["Color2"].default_value = (*tint, 1.0)
                        nt.links.new(color_out, tnode.inputs["Color1"])
                        color_out = tnode.outputs["Color"]
                    nt.links.new(color_out, bsdf.inputs["Base Color"])
                    # ── NORMAL : carte normale de la photo, chaînée vers une
                    #    couche BUMP procédurale optionnelle (micro-relief macro
                    #    de pierre/enduit que la normal map 2k ne porte pas à
                    #    cette échelle de façade). bump_strength>0 ajoute du
                    #    grain grande-échelle qui accroche la lumière → la pierre
                    #    cesse de lire comme un aplat plastique.
                    normal_socket = None
                    if normal_path and _os_mat.path.exists(normal_path) and _os_mat.path.getsize(normal_path) > 1000:
                        nor_tex = nt.nodes.new("ShaderNodeTexImage")
                        nor_tex.image = bpy.data.images.load(normal_path)
                        nor_tex.image.colorspace_settings.name = "Non-Color"
                        nor_map = nt.nodes.new("ShaderNodeNormalMap")
                        nor_map.inputs["Strength"].default_value = normal_strength
                        nt.links.new(mapping.outputs["Vector"], nor_tex.inputs["Vector"])
                        nt.links.new(nor_tex.outputs["Color"], nor_map.inputs["Color"])
                        normal_socket = nor_map.outputs["Normal"]
                    if bump_strength > 0:
                        bcoord = nt.nodes.new("ShaderNodeTexCoord")
                        bnoise = nt.nodes.new("ShaderNodeTexNoise")
                        bnoise.inputs["Scale"].default_value = 12.0   # ~grain de pierre
                        bnoise.inputs["Detail"].default_value = 6.0
                        if "Roughness" in bnoise.inputs:
                            bnoise.inputs["Roughness"].default_value = 0.7
                        bump = nt.nodes.new("ShaderNodeBump")
                        bump.inputs["Strength"].default_value = bump_strength
                        nt.links.new(bcoord.outputs["Object"], bnoise.inputs["Vector"])
                        nt.links.new(bnoise.outputs["Fac"], bump.inputs["Height"])
                        if normal_socket is not None:
                            nt.links.new(normal_socket, bump.inputs["Normal"])
                        normal_socket = bump.outputs["Normal"]
                    if normal_socket is not None:
                        nt.links.new(normal_socket, bsdf.inputs["Normal"])
                    # ── ROUGHNESS variation : un vrai mur n'a PAS une rugosité
                    #    uniforme. On module la roughness par un bruit macro →
                    #    micro-variations de brillance qui captent la lumière du
                    #    soleil = signal « surface réelle » fort (≠ plastique).
                    if rough_var > 0:
                        rcoord = nt.nodes.new("ShaderNodeTexCoord")
                        rmap = nt.nodes.new("ShaderNodeMapping")
                        rmap.inputs["Scale"].default_value = (rough_var_scale,)*3
                        rnoise = nt.nodes.new("ShaderNodeTexNoise")
                        rnoise.inputs["Scale"].default_value = 1.5
                        rnoise.inputs["Detail"].default_value = 4.0
                        rramp = nt.nodes.new("ShaderNodeMapRange")
                        rramp.inputs["To Min"].default_value = max(0.0, roughness - rough_var)
                        rramp.inputs["To Max"].default_value = min(1.0, roughness + rough_var)
                        nt.links.new(rcoord.outputs["Object"], rmap.inputs["Vector"])
                        nt.links.new(rmap.outputs["Vector"], rnoise.inputs["Vector"])
                        nt.links.new(rnoise.outputs["Fac"], rramp.inputs["Value"])
                        nt.links.new(rramp.outputs["Result"], bsdf.inputs["Roughness"])
                    print(f"  ✓ textured material {name} ← {_os_mat.path.basename(tex_path)}")
                except Exception as _e:
                    print(f"  !! material {name} texture load failed ({_e}), using color")
                    bsdf.inputs["Base Color"].default_value = (*fallback_color, 1.0)
            else:
                bsdf.inputs["Base Color"].default_value = (*fallback_color, 1.0)
                print(f"  !! material {name} : texture not found at {tex_path}, fallback color")
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            return m

        def _make_principled(name: str, base_color, roughness=0.6, metallic=0.0,
                             alpha=1.0, specular=0.5, noise_amount=0.0,
                             noise_scale=20.0, color_variation=0.0):
            """Build a Principled BSDF material with optional procedural
            noise on bump and color variation. noise_amount > 0 adds a
            Noise texture as displacement bump (micro-detail).
            color_variation > 0 modulates base_color brightness via Voronoi.
            """
            m = bpy.data.materials.new(name=name)
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
            bsdf.inputs["Roughness"].default_value = roughness
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = metallic
            for k in ("Specular IOR Level", "Specular"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = specular
                    break
            if alpha < 1.0 and "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = alpha
                m.blend_method = "BLEND"

            # Procedural noise → BUMP : micro-detail on flat surfaces.
            if noise_amount > 0:
                noise = nt.nodes.new("ShaderNodeTexNoise")
                noise.inputs["Scale"].default_value = noise_scale
                noise.inputs["Detail"].default_value = 6.0
                noise.inputs["Roughness"].default_value = 0.5
                bump = nt.nodes.new("ShaderNodeBump")
                bump.inputs["Strength"].default_value = noise_amount
                nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
                if "Normal" in bsdf.inputs:
                    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

            # Color variation : tile-based Voronoi modulates albedo.
            if color_variation > 0:
                vor = nt.nodes.new("ShaderNodeTexVoronoi")
                vor.inputs["Scale"].default_value = 8.0
                cr = nt.nodes.new("ShaderNodeMixRGB")
                cr.blend_type = "MULTIPLY"
                cr.inputs["Fac"].default_value = color_variation
                cr.inputs["Color1"].default_value = (*base_color, 1.0)
                cr.inputs["Color2"].default_value = (1.0, 1.0, 1.0, 1.0)
                nt.links.new(vor.outputs["Distance"], cr.inputs["Color2"])
                nt.links.new(cr.outputs["Color"], bsdf.inputs["Base Color"])

            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            return m

        def _make_glass(name: str, tint=(0.55, 0.68, 0.72),
                        roughness=0.04, ior=1.45,
                        interior=(0.015, 0.020, 0.030), interior_emit=0.06):
            """Verre architectural PHOTORÉALISTE (PHASE 1, photo agent).

            Construction Fresnel-mixée : un seul shader « verre » ne peut pas à
            la fois réfléchir le ciel sous angle rasant ET montrer un intérieur
            profond de face. On mixe donc deux shaders par le FRESNEL de la
            surface (Layer Weight) :
              - GLOSSY (reflet ciel net) → domine sous angle rasant (Fresnel↑),
                c'est le reflet du ciel bleu + voisins qui fait « vitre ».
              - INTÉRIEUR (Glass transmission + légère émission bleu-sombre) →
                domine de face. L'émission faible évite le « trou noir » plat :
                la baie a une PROFONDEUR sombre vivante (intérieur d'appart non
                éclairé) au lieu d'un aplat noir.
            IOR 1.45, roughness 0.04 = verre réel net. tint bleu-vert léger.
            """
            m = bpy.data.materials.new(name=name)
            m.use_nodes = True
            nt = m.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            out = nt.nodes.new("ShaderNodeOutputMaterial")

            # NB : on n'utilise PAS de Glass/transmission ici. Sur une façade,
            # un verre transmissif laisse voir le MUR INTÉRIEUR (quad enduit
            # juste derrière la baie) → la fenêtre lisait beige-plat « peinte ».
            # Le vrai vitrage d'un immeuble vu de la rue = MIROIR SOMBRE : on ne
            # voit pas l'intérieur, on voit un intérieur sombre + le reflet du
            # ciel. On construit donc un « dark mirror glass » OPAQUE :
            #   intérieur sombre bleuté  ⟶ (Fresnel) ⟶  reflet ciel glossy net.

            # 1) Reflet ciel : Glossy net, presque blanc → renvoie le HDRI bleu.
            glossy = nt.nodes.new("ShaderNodeBsdfGlossy")
            glossy.inputs["Color"].default_value = (0.95, 0.97, 1.0, 1.0)
            glossy.inputs["Roughness"].default_value = roughness

            # 2) Intérieur sombre : verre teinté bleu-froid TRÈS sombre (vitre
            #    vue de face = on devine un intérieur non éclairé) + une lueur
            #    d'émission infime pour ne pas être noir-mort. Glossy sombre =
            #    garde un micro-reflet même de face (pas un aplat).
            inner = nt.nodes.new("ShaderNodeBsdfGlossy")
            inner.inputs["Color"].default_value = (*tint, 1.0)
            inner.inputs["Roughness"].default_value = 0.18   # reflet flou sombre = profondeur
            emit = nt.nodes.new("ShaderNodeEmission")
            emit.inputs["Color"].default_value = (*interior, 1.0)
            emit.inputs["Strength"].default_value = interior_emit
            interior_mix = nt.nodes.new("ShaderNodeMixShader")
            interior_mix.inputs["Fac"].default_value = 0.35   # surtout reflet sombre, un peu de lueur
            nt.links.new(inner.outputs["BSDF"], interior_mix.inputs[1])
            nt.links.new(emit.outputs["Emission"], interior_mix.inputs[2])

            # 3) Fresnel : de face → intérieur sombre ; angle rasant → reflet
            #    ciel net. C'est CE gradient (sombre au centre, ciel clair sur
            #    les bords/haut) qui fait lire « vitre » à l'œil.
            fres = nt.nodes.new("ShaderNodeFresnel")
            fres.inputs["IOR"].default_value = ior
            fresnel_mix = nt.nodes.new("ShaderNodeMixShader")
            nt.links.new(fres.outputs["Fac"], fresnel_mix.inputs["Fac"])
            # Fresnel Fac≈0 de face → slot1 (intérieur) ; →1 rasant → slot2 (ciel)
            nt.links.new(interior_mix.outputs["Shader"], fresnel_mix.inputs[1])
            nt.links.new(glossy.outputs["BSDF"], fresnel_mix.inputs[2])
            nt.links.new(fresnel_mix.outputs["Shader"], out.inputs["Surface"])
            return m

        # Materials with procedural noise → adds the micro-detail FLUX needs
        # to grab onto. Without this, FLUX sees uniform flat colour and the
        # img2img stays neutral. With noise, every surface has tiny texture
        # variation that FLUX can amplify into real material detail.
        # REVERT to clean flat colors — Poly Haven textures are photos of
        # AGED buildings (weathered brick, dirty plaster, rusty zinc) →
        # render looked "20 years dirty". For NEW construction PC dossier,
        # we want CLEAN BRIGHT materials = flat colors with subtle noise.
        # ENDUIT beige clair PROPRE
        mats["enduit_blanc"]    = _make_principled("enduit_blanc",
                                                    (0.92, 0.86, 0.74), 0.75,
                                                    specular=0.25,
                                                    noise_amount=0.05, noise_scale=80.0)
        # BRIQUE ROUGE neuve éclatante — iter #311 : darker + saturated
        # so it READS as brick (not pinkish) and contrasts with enduit.
        mats["brique_rouge"]    = _make_principled("brique_rouge",
                                                    (0.55, 0.22, 0.12), 0.78,
                                                    specular=0.15,
                                                    noise_amount=0.15, noise_scale=80.0,
                                                    color_variation=0.15)
        mats["bois_clair"]      = _make_principled("bois_clair",
                                                    (0.50, 0.32, 0.18), 0.65,
                                                    specular=0.25,
                                                    noise_amount=0.05, noise_scale=180.0)
        # iter #315 — balcon_concrete lighter so shadow under slabs doesn't
        # read as DARK INDUSTRIAL BANDS in FLUX cn_img2img. Goes from 0.82
        # to 0.94 light cream-gray. With Filmic + exposure this should
        # render as bright cream-white concrete, balcons read as elegant
        # slim slabs (residential) not heavy industrial bands.
        # iter 2026-06-27 (mat2 agent) — CAUSE DU LISERÉ JAUNE sous les balcons :
        # cette couleur était (0.94, 0.92, 0.88), un crème CHAUD (B nettement <
        # R). La sous-face + le chant de dalle reçoivent la lumière chaude
        # (soleil 1.0,0.96,0.90) + le rebond de la pierre crème → avec Filmic
        # High Contrast cette teinte chaude SATURE en jaune-or. Fix = béton
        # blanc-GRIS NEUTRE FROID (R=G=B, B très légèrement >) → plus de jaune.
        mats["balcon_concrete"] = _make_principled("balcon_concrete",
                                                    (0.88, 0.89, 0.90), 0.82,
                                                    specular=0.12,
                                                    noise_amount=0.04, noise_scale=40.0)
        mats["balcon_metal"]    = _make_principled("balcon_metal",
                                                    (0.18, 0.18, 0.20), 0.5, 0.6,
                                                    specular=0.5)
        # iter 2026-06-27 (mat2 agent) — verre INCOHÉRENT (baies opaques blanches
        # vs bleues plates, sans reflet). Cause : Principled BSDF sans
        # transmission ni reflet contrôlé → l'angle de vue décidait du rendu
        # (Fresnel → certaines baies renvoyaient le ciel en blanc cramé, d'autres
        # le bleu sombre du base color → mélange incohérent). On construit un
        # vrai verre architectural homogène : Transmission élevée + teinte
        # sombre-bleutée + roughness basse → reflet ciel net + lecture vitrage
        # uniforme sur TOUTES les baies. Helper dédié plus bas.
        mats["verre"]           = _make_glass("verre")
        # iter #320 — REVERT EMISSION → PBR photoreal voirie.
        # Emission shader was a hack to kill the building shadow on chaussée
        # (iter #306). But it gave flat unconvincing "maquette" voirie.
        # Now with WIDER SETBACK (5m vs 2.5m), the building shadow projects
        # less far onto the chaussée — we can afford realistic PBR materials
        # that receive ambient lighting + minor shadows for photoreal feel.
        # Asphalt = dark medium-gray with real micro-noise grain.
        # Trottoir pavers = distinct light gray with subtle joint variation.
        # User wants : « vrai bitume d'asphalte avec sa texture mate et
        # quelques traces, un vrai trottoir parisien de banlieue chic avec
        # ses pavés ou dalles en béton légèrement usés, des joints visibles ».
        mats["asphalte"]        = _make_principled("asphalte",
                                                    (0.16, 0.16, 0.16), 0.92,
                                                    specular=0.04,
                                                    noise_amount=0.18, noise_scale=120.0,
                                                    color_variation=0.05)
        mats["pavers_concrete"] = _make_principled("pavers_concrete",
                                                    (0.58, 0.58, 0.55), 0.86,
                                                    specular=0.12,
                                                    noise_amount=0.10, noise_scale=8.0,
                                                    color_variation=0.10)
        mats["terre_neutre"]    = _make_principled("terre_neutre",
                                                    (0.42, 0.40, 0.36), 0.92,
                                                    specular=0.05,
                                                    noise_amount=0.20, noise_scale=15.0,
                                                    color_variation=0.12)
        mats["pierre_kerb"]     = _make_principled("pierre_kerb",
                                                    (0.78, 0.74, 0.68), 0.78,
                                                    specular=0.15)
        # Vegetation — iter #311 : richer saturation + brighter so lawn
        # and jardin partitions READ AS GRASS in the photoreal harmonize.
        mats["vegetation"]      = _make_principled("vegetation",
                                                    (0.28, 0.52, 0.18), 0.88,
                                                    specular=0.05,
                                                    noise_amount=0.40, noise_scale=60.0,
                                                    color_variation=0.20)
        mats["metal_noir"]      = _make_principled("metal_noir",
                                                    (0.05, 0.05, 0.05), 0.45, 0.7,
                                                    specular=0.5)
        # VOISIN material : nettement différent de l'enduit_blanc (0.92,0.86,0.74)
        # pour que FLUX distingue les volumes voisins de notre building (sinon
        # FLUX fusionne les voisins blancs avec notre bâtiment blanc).
        # iter #300 : encore plus sombre (0.50 au lieu de 0.62) pour kill
        # définitivement la fusion gauche.
        mats["voisin"]          = _make_principled("voisin",
                                                    (0.50, 0.45, 0.38), 0.92,
                                                    specular=0.08,
                                                    noise_amount=0.18, noise_scale=30.0,
                                                    color_variation=0.25)
        # Pure white road paint (zebra crossing, lane markings) — very
        # bright + slightly glossy for high contrast against asphalt.
        mats["road_paint_white"] = _make_principled("road_paint_white",
                                                    (0.97, 0.97, 0.95), 0.40,
                                                    specular=0.6)
        mats["bois_porte"]      = _make_principled("bois_porte",
                                                    (0.28, 0.15, 0.08), 0.55,
                                                    specular=0.30,
                                                    noise_amount=0.06, noise_scale=120.0)
        # PIERRE TAILLE — iter #311 : warmer cream-beige distinct from
        # enduit_blanc (0.92, 0.86, 0.74) so RDC stone reads as STONE
        # not as wall. More yellow cream-honey tone like real Parisian limestone.
        mats["pierre_taille"]   = _make_principled("pierre_taille",
                                                    (0.82, 0.74, 0.58), 0.72,
                                                    specular=0.20,
                                                    noise_amount=0.10, noise_scale=20.0,
                                                    color_variation=0.08)
        # ZINC anthracite NEUF — iter #311 : darker for clear contrast with
        # the cream enduit + cream pierre. RAL 7016 anthracite ≈ 0.18.
        mats["zinc_anthracite"] = _make_principled("zinc_anthracite",
                                                    (0.16, 0.16, 0.18), 0.35, 0.85,
                                                    specular=0.7,
                                                    noise_amount=0.02, noise_scale=80.0)
        # Fer forgé noir pour garde-corps balcons (vertical bars).
        # Reuse metal_noir, ou clone plus brillant pour fer forgé.
        mats["fer_forge"]       = _make_principled("fer_forge",
                                                    (0.04, 0.04, 0.05), 0.30, 0.8,
                                                    specular=0.6)

        # ── Photoreal swap : replace key surface materials with Poly Haven
        # PBR textures (downloaded at image-build time, see image.run_commands
        # at top of this file). Tile sizes chosen for archviz human-scale.
        if photoreal:
            mats["brique_rouge"] = _make_textured(
                "brique_rouge",
                "/root/textures/brique_rouge.jpg",
                normal_path="/root/textures/brique_rouge_normal.jpg",
                tile_size_m=1.5, fallback_color=(0.55, 0.22, 0.12),
                roughness=0.78, specular=0.15,
                color_break=0.85, break_scale=0.85,   # variation brique-par-brique (cible_B)
            )
            mats["asphalte"] = _make_textured(
                "asphalte", "/root/textures/asphalte.jpg",
                normal_path="/root/textures/asphalte_normal.jpg",
                tile_size_m=3.0, fallback_color=(0.16, 0.16, 0.16),
                roughness=0.93, specular=0.04, normal_strength=0.6,
            )
            # iter 2026-06-27 (mat2 agent) — dallage trottoir : aplat gris
            # quadrillé → vraie texture béton avec DALLES + JOINTS visibles +
            # normal map (relief des joints). tile 1.2 m ≈ dalle réelle. tint
            # gris clair froid neutre (pas crème) pour un trottoir parisien net.
            mats["pavers_concrete"] = _make_textured(
                "pavers_concrete", "/root/textures/dallage.jpg",
                normal_path="/root/textures/dallage_normal.jpg",
                tile_size_m=1.2, fallback_color=(0.60, 0.60, 0.60),
                roughness=0.85, specular=0.10, normal_strength=0.9,
                tint=(0.80, 0.81, 0.82),
            )
            # FIX 2026-06-24 : la texture aerial_grass_rock (herbe.jpg) sortait
            # en BANDES JAUNES/VERTES criardes à chaque balcon (jardinières) —
            # pelouse sèche/rocailleuse vue du ciel, hideux à l'échelle façade.
            # On repasse en PRINCIPLED vert NATUREL PROFOND et MAT, discret :
            # vert forêt désaturé, roughness haute (feuillage mat), micro-noise
            # léger pour éviter l'aplat plastique. Plus de jaune criard.
            mats["vegetation"] = _make_principled(
                "vegetation", (0.075, 0.135, 0.065), roughness=0.97,
                specular=0.02, noise_amount=0.07, noise_scale=70.0,
                color_variation=0.05,
            )
            mats["terre_neutre"] = _make_textured(
                "terre_neutre", "/root/textures/terre.jpg",
                tile_size_m=2.5, fallback_color=(0.42, 0.40, 0.36),
                roughness=0.92, specular=0.05,
            )
            # iter 2026-06-24 (light agent) : variation tonale DISCRÈTE sur
            # l'enduit crème pour casser l'aplat plat (profondeur sans salir,
            # reste clair crème). Plus subtil que la pierre (façade plus lisse).
            # iter 2026-06-27 (mat2 agent) — enduit façade : aplat lisse plastique
            # → on ajoute la NORMAL MAP de l'enduit (relief de crépi) + tint crème
            # clair pour aligner la teinte (la photo painted_plaster est plus
            # grise). Grain + micro-relief = lecture enduit réel, reste CLAIR.
            # PHASE 1 (photo agent) : enduit_blanc = CORPS de façade des étages
            # (mur extrudé de base) → c'est la grande surface qui lisait
            # « carton » plat. On la matière fortement :
            #   - tile 1.6 → 1.1 m : grain d'enduit lisible.
            #   - normal 1.2 → 1.6 + BUMP 0.22 : micro-relief de crépi qui
            #     accroche la lumière (le levier #1 du « pas plat »).
            #   - rough_var 0.20 : taloche non-uniforme → micro-reflets soleil.
            mats["enduit_blanc"] = _make_textured(
                "enduit_blanc", "/root/textures/enduit.jpg",
                normal_path="/root/textures/enduit_normal.jpg",
                tile_size_m=1.1, fallback_color=(0.92, 0.86, 0.74),
                roughness=0.88, specular=0.16, normal_strength=1.6,
                color_break=0.30, break_scale=0.45,
                tint=(0.96, 0.93, 0.87),   # crème clair froid (anti-orange)
                rough_var=0.20, rough_var_scale=4.0, bump_strength=0.22,
            )
            mats["voisin"] = _make_textured(
                "voisin", "/root/textures/enduit.jpg",
                normal_path="/root/textures/enduit_normal.jpg",
                tile_size_m=3.5, fallback_color=(0.50, 0.45, 0.38),
                roughness=0.92, specular=0.08, normal_strength=0.5,
                tint=(0.62, 0.58, 0.50),
            )
            # FIX 2026-06-24 : la cobblestone faisait des RAYURES sur les murs.
            # Pierre de taille = plâtre LISSE (enduit) teinté pierre crème.
            # Le relief vient de la géométrie (soubassement, bandeaux, encadrements).
            # iter 2026-06-24 (light agent) : la pierre lisait PLATE ("pâte à
            # modeler"). On ajoute color_break = variation tonale MACRO (bruit
            # grande-échelle multiplié autour de 1.0 → garde la teinte CRÈME,
            # certaines zones un peu plus claires/sombres) + on remonte break_scale
            # pour des plages de la taille d'un bloc de pierre. Donne la
            # profondeur d'une VRAIE pierre claire, pas un beige uniforme.
            # roughness un peu plus haute + micro normal map (déjà dans la
            # texture enduit) → grain mat photographique.
            # iter 2026-06-27 (mat2 agent) — pierre de taille = CORPS de façade B.
            # AVANT : enduit.jpg sans normal map → aplat lisse "pâte à modeler".
            # MAINTENANT : texture beige_wall DÉDIÉE (grain de pierre fin) +
            # NORMAL MAP (vrai relief de surface) + color_break modéré (variation
            # tonale crème par blocs, pas par brique) + tint crème CLAIR pour
            # garder la teinte voulue (pas brun, pas jaune). tile 2.4 m → grain à
            # l'échelle. normal_strength 0.7 → relief lisible sans bosseler.
            # PHASE 1 (photo agent) : la pierre lisait PLATE (aplat crème
            # « carton »). On la rend matiérée :
            #   - tile 1.6 → 0.9 m : grain de pierre VISIBLE à l'échelle façade.
            #   - normal_strength 1.3 → 1.6 + BUMP procédural 0.18 : vrai relief
            #     qui accroche la lumière rasante (modelé pierre).
            #   - rough_var 0.18 : rugosité non-uniforme → micro-reflets soleil.
            #   - color_break 0.55 : variation tonale bloc-à-bloc plus marquée.
            mats["pierre_taille"] = _make_textured(
                "pierre_taille", "/root/textures/pierre_facade.jpg",
                normal_path="/root/textures/pierre_facade_normal.jpg",
                tile_size_m=0.9, fallback_color=(0.85, 0.79, 0.66),
                roughness=0.78, specular=0.18, normal_strength=1.6,
                color_break=0.55, break_scale=0.55,
                tint=(0.94, 0.91, 0.85),   # crème CLAIR FROID (moins ambré → lecture photo)
                rough_var=0.18, rough_var_scale=4.0, bump_strength=0.30,
            )
            mats["bois_clair"] = _make_textured(
                "bois_clair", "/root/textures/bois.jpg",
                tile_size_m=1.4, fallback_color=(0.50, 0.32, 0.18),
                roughness=0.65, specular=0.25,
            )
            # Zinc anthracite LISSE (la tôle ondulée donnait des vagues).
            mats["zinc_anthracite"] = _make_principled(
                "zinc_anthracite", (0.17, 0.17, 0.19), 0.42, 0.55,
                specular=0.5, noise_amount=0.015, noise_scale=120.0,
            )
            # iter 2026-06-27 (mat2 agent) — béton balcon (dalle/sous-face/chant).
            # En plus du fix couleur (gris neutre froid, anti-liseré-jaune), on
            # ajoute le GRAIN béton + normal map → la dalle et sa sous-face lisent
            # comme du vrai béton mat, plus comme un aplat plastique. tint gris
            # blanc-froid (B léger >) pour verrouiller la neutralité même sous le
            # soleil chaud / le rebond crème (la cause du jaune). normal léger.
            mats["balcon_concrete"] = _make_textured(
                "balcon_concrete", "/root/textures/beton_lisse.jpg",
                normal_path="/root/textures/beton_lisse_normal.jpg",
                tile_size_m=2.0, fallback_color=(0.88, 0.89, 0.90),
                roughness=0.82, specular=0.10, normal_strength=0.4,
                tint=(0.84, 0.86, 0.88),   # blanc-gris froid neutre (anti-jaune)
            )
        return mats

    @modal.method()
    def render_test_cube(self, width: int = 1024, height: int = 1024) -> bytes:
        """POC : render a default cube + ground + sun light to verify the
        full stack works end-to-end. Outputs a PNG bytes.
        """
        import bpy
        # Reset to default scene.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene

        # Add a cube and a ground plane.
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
        cube = bpy.context.active_object
        cube.name = "TestCube"
        bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
        ground = bpy.context.active_object
        ground.name = "Ground"

        # Add a sun light.
        bpy.ops.object.light_add(type="SUN", location=(5, -5, 10))
        sun = bpy.context.active_object
        sun.data.energy = 5.0
        sun.rotation_euler = (0.785, 0.0, 0.785)   # 45° angle

        # Add a camera 8 m back, looking at origin.
        bpy.ops.object.camera_add(location=(8, -8, 5), rotation=(1.1, 0, 0.785))
        cam = bpy.context.active_object
        scene.camera = cam

        # Cycles config.
        scene.render.engine = "CYCLES"
        scene.cycles.device = "GPU"
        scene.cycles.samples = 64
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = "/tmp/blender_poc.png"

        # Render.
        print(f"→ Cycles rendering {width}×{height} samples=64 …")
        bpy.ops.render.render(write_still=True)
        print(f"✓ render complete")

        return Path("/tmp/blender_poc.png").read_bytes()


def _render_one(
    project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
    preset: str = "rue_se_eloignee",
    seed: int = 11,
    width: int = 1024,
    height: int = 1024,
    samples: int = 128,
    test_only: bool = False,
    photoreal: bool = False,
    adaptive_threshold: float = 0.01,   # validated lossless (−41 % Cycles); 0 to force fixed
):
    """Build the project's scene_mesh quads + render ONE preset via Blender
    Cycles. Plain function (no entrypoint decorator) so it can be called both
    by the single-shot `main` entrypoint and looped by `batch` within a single
    warm Modal container."""
    if test_only:
        bp = BlenderPipeline()
        print("→ rendering test cube …")
        png = bp.render_test_cube.remote(width=width, height=height)
        Path("/tmp/blender_poc.png").write_bytes(png)
        print(f"✓ saved {len(png):,} bytes → /tmp/blender_poc.png")
        return

    import json, urllib.request, sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.depth_map import camera_from_preset
    from src.scene_mesh import (
        Quad,
        balcons_filants_quads,  # noqa: F401  kept for reference
        clip_footprint_to_parcelle,
        entrance_canopy_quad,
        far_ground_quad,
        jardins_rdc_quads,
        lane_markings_quads,
        opposing_street_quads,
        pleine_terre_quads,
        rdc_bandeau_quads,
        rdc_windows_quads,
        rooftop_terrace_quads,
        roads_bdtopo_to_quads,
        synthetic_voirie_roads_quads,
        voirie_strip_quads,
        zebra_crossing_quads,
    )
    from src.depth_map import _polygon_inset, extrude_footprint
    from src.voisinage_mesh import (
        fetch_osm_street_lamps,
        fetch_osm_trees,
        fetch_roads_bdtopo,
        fetch_voisins_bdtopo,
        geocode_address,
        roads_to_local_polylines,
        voisins_to_local_polygons,
        wgs84_to_local,
    )

    with urllib.request.urlopen(
        f"http://localhost:8000/api/v1/projects/{project_id}/building_model"
    ) as r:
        bm = json.load(r)
    model = bm.get("model_json", bm)
    fp = model["envelope"]["footprint_geojson"]["coordinates"][0]
    fp_xy = [(float(p[0]), float(p[1])) for p in fp]
    h = float(model["envelope"].get("hauteur_totale_m", 17.0))
    cam = camera_from_preset(fp_xy, h, preset)

    # Special override : "junction_pov" places camera AT the X-intersection
    # (Rue de Plaisance × Rue des Héros Nogentais) at eye level, looking
    # at the building/parcel. This matches the user's mental model :
    # camera is at the middle of the X, the road forms an X around camera,
    # the parcel is at one of the X's 4 corners.
    if preset == "junction_pov":
        # Place camera AT the X-intersection middle (Rue de Plaisance ×
        # Rue des Héros), then BACK OFF 8m toward NE so we have enough
        # space to see the parcel facing camera. The building is at the
        # SW corner of the X so we look SW.
        _parc = bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0]
        _ppts = [(p[0], p[1]) for p in _parc[:-1]]
        _pcx = sum(p[0] for p in _ppts) / len(_ppts)
        _pcy = sum(p[1] for p in _ppts) / len(_ppts)
        junction_xy = (_pcx + 2.13, _pcy + 5.90)
        # Back off 8m NE from junction along Rue des Héros east direction
        # (NE-ward) so camera is outside the parcel polygon.
        back_dx, back_dy = 0.984, 0.180   # OSM Rue des Héros east tangent
        cam_x = junction_xy[0] + 8.0 * back_dx
        cam_y = junction_xy[1] + 8.0 * back_dy
        # Building centre in BM frame.
        _xs = [p[0] for p in fp_xy]; _ys = [p[1] for p in fp_xy]
        bld_cx = (min(_xs) + max(_xs)) / 2
        bld_cy = (min(_ys) + max(_ys)) / 2
        cam.position = (cam_x, cam_y, 1.7)
        cam.target = (bld_cx, bld_cy, 6.0)
        cam.fov_deg = 75.0
        print(f"  ⤷ junction_pov : cam at ({cam_x:.1f},{cam_y:.1f}) "
              f"(8m NE of junction) → building ({bld_cx:.1f},{bld_cy:.1f})")

    parc = bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0]
    parc_pts = [(p[0], p[1]) for p in parc[:-1]]
    clipped_rings = clip_footprint_to_parcelle(fp_xy, parc_pts)
    real_building_ring = max(clipped_rings,
                              key=lambda r: abs(sum(
                                  (r[i][0] * r[(i+1)%len(r)][1]
                                   - r[(i+1)%len(r)][0] * r[i][1])
                                  for i in range(len(r))) / 2))
    voirie_sides = bm["model_json"]["site"].get("voirie_orientations") or ["sud"]

    # Build all the quads, grouped by material.
    # iter #302 — ARCHITECTURE FIX : on maintient DEUX dicts en parallèle.
    #   quads_by_mat          → scène complète (building + voirie + voisin + tout)
    #   building_quads_by_mat → UNIQUEMENT le bâtiment principal (notre R+5)
    # La 2ᵉ passe Blender (silhouette) ne rend que building_quads_by_mat sur
    # fond noir. Le mask composite vient de cette silhouette = zéro ambiguïté
    # building vs voirie. Plus de trou/fantôme par construction.
    quads_by_mat: dict = {}
    building_quads_by_mat: dict = {}

    def _add(mat: str, qs):
        if not qs:
            return
        items = quads_by_mat.setdefault(mat, [])
        for q in qs:
            items.append((q.v0, q.v1, q.v2, q.v3))

    def _add_building(mat: str, qs):
        """Add to the full scene AND mark these quads as 'main building'
        for the silhouette pass. Use this for any geometry that belongs to
        OUR R+5 (walls, balcons, fenêtres, attique, toit végétal, …).
        Do NOT use for : bahut/grille (voirie boundary), voisin, voirie ground,
        kerb, trees, far ground, vegetation outside the building."""
        if not qs:
            return
        items_full = quads_by_mat.setdefault(mat, [])
        items_bld = building_quads_by_mat.setdefault(mat, [])
        for q in qs:
            t = (q.v0, q.v1, q.v2, q.v3)
            items_full.append(t)
            items_bld.append(t)

    # 1) Building extruded — MAIN BUILDING walls
    _add_building("enduit_blanc", extrude_footprint(real_building_ring, h))

    # Compute "adjusted parcel" (building bbox + margin) used as the
    # property line for road + bahut placement.
    # iter #320 — REAL SCALE setback : 5.0m (was 2.5m). A French
    # residential premium project has 5-8m setback from public road to
    # building face → room for real lawn, walkway, trees, hedges, bahut
    # fence. This is the scale the user explicitly asked for (« il faut
    # que tu mette la bonne echelle partout »).
    _bxs = [p[0] for p in real_building_ring]
    _bys = [p[1] for p in real_building_ring]
    _bmargin = 5.0
    adjusted_parc = [
        (min(_bxs) - _bmargin, min(_bys) - _bmargin),
        (max(_bxs) + _bmargin, min(_bys) - _bmargin),
        (max(_bxs) + _bmargin, max(_bys) + _bmargin),
        (min(_bxs) - _bmargin, max(_bys) + _bmargin),
    ]

    # 2) Voirie strip (bahut + grille + walkway) — uses adjusted_parc so
    # bahut sits 0.5m south/east of building face (not 3m yard).
    # iter #316 : bahut 0.2m + grille 0.6m = 0.8m total. Even lower so the
    # camera sees deeper into the lawn → pleine_terre vegetation reads
    # CLEARLY as a residential lawn (was the user's blocking complaint).
    _add("enduit_blanc",
         voirie_strip_quads(adjusted_parc, voirie_sides, thickness_m=6.0,
                            bahut_height_m=0.2, grille_height_m=0.6,
                            emit_flat_ground=False))

    # 3) Pleine terre + jardins
    _add("vegetation", pleine_terre_quads(parc_pts, real_building_ring))

    niveaux = int(model["envelope"].get("niveaux") or 6)
    h_rdc = float(model["envelope"].get("hauteur_rdc_m") or 3.5)
    h_etage = float(model["envelope"].get("hauteur_etage_courant_m") or 2.7)

    # Balcons : split the output of balcons_filants_quads so the railing
    # gets a metal_noir material (visible black band on top of each slab,
    # the highest-impact "garde-corps" cue for both human and FLUX eyes).
    # Per-floor structure : 3 slab quads + 1 railing + N partition quads.
    # We rebuild explicitly to avoid fragile index math.
    bal_concrete_quads: list = []
    bal_railing_quads: list = []
    fp_b = list(real_building_ring)
    if fp_b and fp_b[0] == fp_b[-1]:
        fp_b = fp_b[:-1]
    n_b = len(fp_b)
    if n_b >= 3 and voirie_sides:
        xs_b = [p[0] for p in fp_b]; ys_b = [p[1] for p in fp_b]
        minx_b, maxx_b = min(xs_b), max(xs_b)
        miny_b, maxy_b = min(ys_b), max(ys_b)
        floor_levels_b = []
        z_cur_b = h_rdc
        # Include TOP floor (attique R+5) in balcons : range goes to niveaux
        # not niveaux - 1. Was skipping last floor by default.
        for fi in range(1, niveaux):
            floor_levels_b.append(z_cur_b)
            z_cur_b += h_etage
        floor_depths_b = [0.9 if i == 0 else 1.6 for i in range(len(floor_levels_b))]
        TOL_b = 0.5
        for side in voirie_sides:
            s = side.lower()
            for i in range(n_b):
                a = fp_b[i]; b = fp_b[(i + 1) % n_b]
                ex = b[0] - a[0]; ey = b[1] - a[1]
                length_b = (ex * ex + ey * ey) ** 0.5
                if length_b < 0.5:
                    continue
                horizontal = abs(ex) > abs(ey)
                mx = (a[0] + b[0]) / 2; my = (a[1] + b[1]) / 2
                keep = (
                    (s in ("sud", "south", "s") and horizontal and (my - miny_b) < TOL_b)
                    or (s in ("nord", "north", "n") and horizontal and (maxy_b - my) < TOL_b)
                    or (s in ("est", "east", "e") and not horizontal and (maxx_b - mx) < TOL_b)
                    or (s in ("ouest", "west", "w") and not horizontal and (mx - minx_b) < TOL_b)
                )
                if not keep:
                    continue
                tx = ex / length_b; ty = ey / length_b
                nx = ey / length_b; ny = -ex / length_b
                if s in ("sud", "south", "s") and ny > 0: nx, ny = -nx, -ny
                elif s in ("nord", "north", "n") and ny < 0: nx, ny = -nx, -ny
                elif s in ("est", "east", "e") and nx < 0: nx, ny = -nx, -ny
                elif s in ("ouest", "west", "w") and nx > 0: nx, ny = -nx, -ny
                for fi, z_floor in enumerate(floor_levels_b):
                    d = floor_depths_b[fi]
                    a_out = (a[0] + nx * d, a[1] + ny * d)
                    b_out = (b[0] + nx * d, b[1] + ny * d)
                    a_out_e = (a_out[0] - tx * d, a_out[1] - ty * d)
                    b_out_e = (b_out[0] + tx * d, b_out[1] + ty * d)
                    a_e = (a[0] - tx * d, a[1] - ty * d)
                    b_e = (b[0] + tx * d, b[1] + ty * d)
                    z_top = z_floor + 0.18
                    z_rail = z_top + 1.0
                    # Slab top + bottom + front → concrete.
                    bal_concrete_quads.append(Quad(
                        v0=(a_e[0], a_e[1], z_top),
                        v1=(b_e[0], b_e[1], z_top),
                        v2=(b_out_e[0], b_out_e[1], z_top),
                        v3=(a_out_e[0], a_out_e[1], z_top),
                    ))
                    bal_concrete_quads.append(Quad(
                        v0=(a_e[0], a_e[1], z_floor),
                        v1=(a_out_e[0], a_out_e[1], z_floor),
                        v2=(b_out_e[0], b_out_e[1], z_floor),
                        v3=(b_e[0], b_e[1], z_floor),
                    ))
                    bal_concrete_quads.append(Quad(
                        v0=(a_out_e[0], a_out_e[1], z_floor),
                        v1=(b_out_e[0], b_out_e[1], z_floor),
                        v2=(b_out_e[0], b_out_e[1], z_top),
                        v3=(a_out_e[0], a_out_e[1], z_top),
                    ))
                    # RAILING → metal_noir (visible black band).
                    bal_railing_quads.append(Quad(
                        v0=(a_out_e[0], a_out_e[1], z_top),
                        v1=(b_out_e[0], b_out_e[1], z_top),
                        v2=(b_out_e[0], b_out_e[1], z_rail),
                        v3=(a_out_e[0], a_out_e[1], z_rail),
                    ))
                    # PRIVACY PARTITIONS entre balcons d'apartments
                    # adjacents. Vertical walls perpendiculaires au facade,
                    # hauteur 1.8m (privacy totale), espacées de 6m
                    # (apartment_pitch). Material balcon_concrete (panneau
                    # béton classique entre balcons français).
                    apt_pitch = 6.0
                    partition_h = 1.8
                    if length_b > apt_pitch:
                        n_part = int(length_b // apt_pitch)
                        for k in range(1, n_part + 1):
                            t = k / (n_part + 1)
                            ix = a[0] + t * (b[0] - a[0])
                            iy = a[1] + t * (b[1] - a[1])
                            # Partition extends FROM facade OUTWARD to balcon edge
                            ox = ix + nx * d
                            oy = iy + ny * d
                            z_top_part = z_top + partition_h
                            bal_concrete_quads.append(Quad(
                                v0=(ix, iy, z_top),
                                v1=(ox, oy, z_top),
                                v2=(ox, oy, z_top_part),
                                v3=(ix, iy, z_top_part),
                            ))
    _add_building("balcon_concrete", bal_concrete_quads)
    _add_building("fer_forge", bal_railing_quads)
    print(f"  balcons : {len(bal_concrete_quads)} slabs+partitions + {len(bal_railing_quads)} railings (fer forgé)")

    # jardins_rdc : partitions HAUTES (2.0m) + FULL YARD DEPTH (2.5m =
    # adjusted_parc margin). Couvre du facade jusqu'au bahut pour ZERO
    # vision latérale entre jardins voisins. Privacy garantie.
    _add("vegetation",
         jardins_rdc_quads(real_building_ring, voirie_sides,
                           garden_depth_m=_bmargin, partition_height_m=2.0,
                           apartment_pitch_m=6.0, add_trees=False))

    # Force entrance on SUD face if available (address #80 is on Rue des
    # Héros = south face). BM may declare 'est' as primary which would
    # put the canopy on east face — wrong for this address.
    entrance_sides = ["sud"] if any(s.lower().startswith(("sud", "s")) for s in voirie_sides) else voirie_sides[:1]

    _add_building("enduit_blanc",
         entrance_canopy_quad(real_building_ring, entrance_sides,
                              canopy_width_m=3.0, canopy_depth_m=1.0,
                              canopy_z_base_m=2.6, canopy_z_top_m=3.0))

    _add_building("enduit_blanc",
         rdc_bandeau_quads(real_building_ring, hauteur_rdc_m=h_rdc))

    # ── Style Haussmannien moderne : RDC pierre + cordon + zinc attique ──
    # Façade overlay quads protrudés 5cm depuis le facade pour z-fighting
    # safety. RDC = pierre_taille (z=0 to h_rdc), cordon = pierre 0.4m above
    # h_rdc, attique = zinc_anthracite (z=h_total - h_etage to h_total).
    OVERLAY_OFFSET = 0.05
    CORDON_HEIGHT = 0.30
    fp_ovr = list(real_building_ring)
    if fp_ovr and fp_ovr[0] == fp_ovr[-1]:
        fp_ovr = fp_ovr[:-1]
    z_attique_bot = h - h_etage   # top floor z range
    rdc_pierre_quads: list = []
    cordon_quads: list = []
    attique_zinc_quads: list = []
    for i in range(len(fp_ovr)):
        a = fp_ovr[i]; b = fp_ovr[(i + 1) % len(fp_ovr)]
        ex = b[0] - a[0]; ey = b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        if L < 0.5:
            continue
        # Outward normal (CCW footprint → right of edge direction).
        nx = ey / L; ny = -ex / L
        ox_a = a[0] + nx * OVERLAY_OFFSET
        oy_a = a[1] + ny * OVERLAY_OFFSET
        ox_b = b[0] + nx * OVERLAY_OFFSET
        oy_b = b[1] + ny * OVERLAY_OFFSET
        # RDC pierre overlay : z=0 to h_rdc
        rdc_pierre_quads.append(Quad(
            v0=(ox_a, oy_a, 0.0),
            v1=(ox_b, oy_b, 0.0),
            v2=(ox_b, oy_b, h_rdc),
            v3=(ox_a, oy_a, h_rdc),
        ))
        # Cordon pierre overlay : bandeau horizontal au-dessus du RDC,
        # 0.30m de haut, protrudé un peu plus (8cm).
        ox_a2 = a[0] + nx * 0.08
        oy_a2 = a[1] + ny * 0.08
        ox_b2 = b[0] + nx * 0.08
        oy_b2 = b[1] + ny * 0.08
        cordon_quads.append(Quad(
            v0=(ox_a2, oy_a2, h_rdc),
            v1=(ox_b2, oy_b2, h_rdc),
            v2=(ox_b2, oy_b2, h_rdc + CORDON_HEIGHT),
            v3=(ox_a2, oy_a2, h_rdc + CORDON_HEIGHT),
        ))
        # Attique zinc overlay : top floor cladding
        attique_zinc_quads.append(Quad(
            v0=(ox_a, oy_a, z_attique_bot),
            v1=(ox_b, oy_b, z_attique_bot),
            v2=(ox_b, oy_b, h),
            v3=(ox_a, oy_a, h),
        ))
    _add_building("pierre_taille", rdc_pierre_quads)
    _add_building("pierre_taille", cordon_quads)
    _add_building("zinc_anthracite", attique_zinc_quads)
    print(f"  + Style Haussmannien : {len(rdc_pierre_quads)} pierre RDC + "
          f"{len(cordon_quads)} cordons + {len(attique_zinc_quads)} attique zinc")

    # ── Colonne brique rouge centrale (cage d'escalier saillante) ──
    # Protrude 2.0m past balcons (1.6m depth) so brique apparait en
    # AVANT des balcons (architecturalement = module saillant cage
    # d'escalier qui interrompt les balcons filants).
    BRIQUE_WIDTH = 3.5
    BRIQUE_PROTRUDE = 2.0
    # Use the same _bxs/_bys variables from adjusted_parc computation
    bminx_b, bmaxx_b = min(_bxs), max(_bxs)
    bminy_b, bmaxy_b = min(_bys), max(_bys)
    brique_quads: list = []
    for side in voirie_sides:
        s = side.lower()
        # Center of the longest edge facing this voirie
        TOL_p = 2.0
        longest_edge = None
        longest_len = 0.0
        for i in range(len(fp_ovr)):
            a = fp_ovr[i]; b = fp_ovr[(i + 1) % len(fp_ovr)]
            ex = b[0] - a[0]; ey = b[1] - a[1]
            L = (ex * ex + ey * ey) ** 0.5
            if L < 1.0:
                continue
            horizontal = abs(ex) > abs(ey)
            mx = (a[0] + b[0]) / 2; my = (a[1] + b[1]) / 2
            keep = (
                (s.startswith(("sud", "s")) and horizontal and (my - bminy_b) < TOL_p)
                or (s.startswith(("nord", "n")) and horizontal and (bmaxy_b - my) < TOL_p)
                or (s.startswith(("est", "e")) and not horizontal and (bmaxx_b - mx) < TOL_p)
                or (s.startswith(("ouest", "o", "w")) and not horizontal and (mx - bminx_b) < TOL_p)
            )
            if keep and L > longest_len:
                longest_len = L
                longest_edge = (a, b)
        if longest_edge is None or longest_len < BRIQUE_WIDTH + 1.0:
            continue
        a, b = longest_edge
        ex = b[0] - a[0]; ey = b[1] - a[1]
        L = (ex * ex + ey * ey) ** 0.5
        tx = ex / L; ty = ey / L
        # Outward normal — flip sign based on side to ensure points AWAY
        # from building (footprint winding may be CW).
        nx = ey / L; ny = -ex / L
        # Force normal to point outward (away from building bbox centre)
        bld_cx = (bminx_b + bmaxx_b) / 2
        bld_cy = (bminy_b + bmaxy_b) / 2
        mid_x = (a[0] + b[0]) / 2
        mid_y = (a[1] + b[1]) / 2
        # Dot of normal with vector from building centre to edge midpoint
        if (mid_x - bld_cx) * nx + (mid_y - bld_cy) * ny < 0:
            nx, ny = -nx, -ny
        # Place brique column at midpoint of edge, BRIQUE_WIDTH wide
        cx_b = (a[0] + b[0]) / 2; cy_b = (a[1] + b[1]) / 2
        halfw = BRIQUE_WIDTH / 2
        # 4 corners on facade, protruded
        a_b = (cx_b - tx * halfw + nx * BRIQUE_PROTRUDE,
               cy_b - ty * halfw + ny * BRIQUE_PROTRUDE)
        b_b = (cx_b + tx * halfw + nx * BRIQUE_PROTRUDE,
               cy_b + ty * halfw + ny * BRIQUE_PROTRUDE)
        # Front face (visible)
        brique_quads.append(Quad(
            v0=(a_b[0], a_b[1], 0.0),
            v1=(b_b[0], b_b[1], 0.0),
            v2=(b_b[0], b_b[1], h),
            v3=(a_b[0], a_b[1], h),
        ))
        # Side faces of the protrusion (2 sides)
        a_back = (cx_b - tx * halfw, cy_b - ty * halfw)
        b_back = (cx_b + tx * halfw, cy_b + ty * halfw)
        brique_quads.append(Quad(
            v0=(a_back[0], a_back[1], 0.0),
            v1=(a_b[0], a_b[1], 0.0),
            v2=(a_b[0], a_b[1], h),
            v3=(a_back[0], a_back[1], h),
        ))
        brique_quads.append(Quad(
            v0=(b_b[0], b_b[1], 0.0),
            v1=(b_back[0], b_back[1], 0.0),
            v2=(b_back[0], b_back[1], h),
            v3=(b_b[0], b_b[1], h),
        ))
    _add_building("brique_rouge", brique_quads)
    print(f"  + {len(brique_quads)} brique column faces (cage escalier)")

    # Entrance door : a 2.0 × 2.4 m dark walnut wood quad on the south
    # voirie facade at RDC (under the canopy). Pushed 3 cm OUT of the
    # facade so it's clearly visible (decal). Material bois_porte (dark
    # walnut). Classic French immeuble entrance door.
    fp_d = list(real_building_ring)
    if fp_d and fp_d[0] == fp_d[-1]:
        fp_d = fp_d[:-1]
    if len(fp_d) >= 3 and voirie_sides:
        xs_d = [p[0] for p in fp_d]; ys_d = [p[1] for p in fp_d]
        miny_d = min(ys_d); maxx_d = max(xs_d); minx_d = min(xs_d); maxy_d = max(ys_d)
        TOL_d = 0.5
        door_quads: list = []
        # Only one door, on the entrance side (matches the address street).
        for side in entrance_sides:
            s = side.lower()
            for i in range(len(fp_d)):
                a = fp_d[i]; b = fp_d[(i + 1) % len(fp_d)]
                ex = b[0] - a[0]; ey = b[1] - a[1]
                length_d = (ex * ex + ey * ey) ** 0.5
                if length_d < 2.0:
                    continue
                horizontal = abs(ex) > abs(ey)
                mx = (a[0] + b[0]) / 2; my = (a[1] + b[1]) / 2
                keep = (
                    (s in ("sud", "south", "s") and horizontal and (my - miny_d) < TOL_d)
                    or (s in ("nord", "north", "n") and horizontal and (maxy_d - my) < TOL_d)
                    or (s in ("est", "east", "e") and not horizontal and (maxx_d - mx) < TOL_d)
                    or (s in ("ouest", "west", "w") and not horizontal and (mx - minx_d) < TOL_d)
                )
                if not keep:
                    continue
                tx = ex / length_d; ty = ey / length_d
                nx = ey / length_d; ny = -ex / length_d
                if s in ("sud", "south", "s") and ny > 0: nx, ny = -nx, -ny
                elif s in ("nord", "north", "n") and ny < 0: nx, ny = -nx, -ny
                elif s in ("est", "east", "e") and nx < 0: nx, ny = -nx, -ny
                elif s in ("ouest", "west", "w") and nx > 0: nx, ny = -nx, -ny
                # Door at midpoint of edge, 2.0 m wide × 2.4 m tall, dark wood.
                cx_d = (a[0] + b[0]) / 2; cy_d = (a[1] + b[1]) / 2
                halfw = 1.0
                p_l = (cx_d - tx * halfw + nx * 0.03, cy_d - ty * halfw + ny * 0.03)
                p_r = (cx_d + tx * halfw + nx * 0.03, cy_d + ty * halfw + ny * 0.03)
                door_quads.append(Quad(
                    v0=(p_l[0], p_l[1], 0.0),
                    v1=(p_r[0], p_r[1], 0.0),
                    v2=(p_r[0], p_r[1], 2.4),
                    v3=(p_l[0], p_l[1], 2.4),
                ))
                break  # one door per side
        _add_building("bois_porte", door_quads)
        print(f"  + {len(door_quads)} doors RDC (bois_porte)")

        # Bandeau béton : a 60cm tall strip at building base, all voirie
        # facades. Slightly protruded 4cm so it reads as a distinct base
        # course. Material pierre_kerb (cream-grey limestone). Classic
        # French immeuble socle.
        bandeau_h = 0.60
        bandeau_protrude = 0.04
        bandeau_quads: list = []
        for side in voirie_sides:
            s = side.lower()
            for i in range(len(fp_d)):
                a = fp_d[i]; b = fp_d[(i + 1) % len(fp_d)]
                ex = b[0] - a[0]; ey = b[1] - a[1]
                length_b = (ex * ex + ey * ey) ** 0.5
                if length_b < 0.5:
                    continue
                horizontal = abs(ex) > abs(ey)
                mx = (a[0] + b[0]) / 2; my = (a[1] + b[1]) / 2
                keep = (
                    (s in ("sud", "south", "s") and horizontal and (my - miny_d) < TOL_d)
                    or (s in ("nord", "north", "n") and horizontal and (maxy_d - my) < TOL_d)
                    or (s in ("est", "east", "e") and not horizontal and (maxx_d - mx) < TOL_d)
                    or (s in ("ouest", "west", "w") and not horizontal and (mx - minx_d) < TOL_d)
                )
                if not keep:
                    continue
                nx = ey / length_b; ny = -ex / length_b
                if s in ("sud", "south", "s") and ny > 0: nx, ny = -nx, -ny
                elif s in ("nord", "north", "n") and ny < 0: nx, ny = -nx, -ny
                elif s in ("est", "east", "e") and nx < 0: nx, ny = -nx, -ny
                elif s in ("ouest", "west", "w") and nx > 0: nx, ny = -nx, -ny
                p_a = (a[0] + nx * bandeau_protrude, a[1] + ny * bandeau_protrude)
                p_b = (b[0] + nx * bandeau_protrude, b[1] + ny * bandeau_protrude)
                bandeau_quads.append(Quad(
                    v0=(p_a[0], p_a[1], 0.0),
                    v1=(p_b[0], p_b[1], 0.0),
                    v2=(p_b[0], p_b[1], bandeau_h),
                    v3=(p_a[0], p_a[1], bandeau_h),
                ))
        _add_building("pierre_kerb", bandeau_quads)
        print(f"  + {len(bandeau_quads)} bandeau béton quads (pierre_kerb)")

    # Trees : real positions from OpenStreetMap (natural=tree). We do NOT
    # synthesize tree positions — if OSM has no trees mapped on this
    # street, the render shows none (rule : respect cadastre/data, never
    # invent street furniture).
    tree_positions: list[tuple] = []
    # Lamp posts : real positions from OSM (highway=street_lamp).
    lamp_positions: list[tuple] = []

    # iter #316 — JARDIN TREES RE-ENABLED.
    # With the silhouette mask + re-composite architecture (iter #302+),
    # the jardin trees live in the Blender voirie zone of the composite —
    # they're rendered as actual 3D cylinder+sphere meshes by Blender, then
    # passed through unchanged. The FLUX cn_img2img only sees them as
    # depth-locked structure ; the re-composite restores their Blender
    # rendering on the non-silhouette zone. No more ghost-blob risk.
    # User explicitly wanted visible jardin/herbe/grass — bigger canopy
    # so trees read as TREES not blob.
    JARDIN_INSET = 1.5
    JARDIN_TREE_H = 6.0
    JARDIN_TREE_CANOPY_R = 3.0    # iter #319 — much bigger canopy for clearly visible jardin trees from oblique camera
    APT_SPACING = 8.0   # fewer trees, bigger each
    bxs_fp = [p[0] for p in real_building_ring]
    bys_fp = [p[1] for p in real_building_ring]
    bminx, bmaxx = min(bxs_fp), max(bxs_fp)
    bminy, bmaxy = min(bys_fp), max(bys_fp)
    for side in voirie_sides:
        s = side.lower()
        if s.startswith(("sud", "s")):
            length = bmaxx - bminx
            n = max(1, int(length // APT_SPACING))
            for k in range(n):
                t = (k + 0.5) / n
                tx_j = bminx + t * length
                ty_j = bminy - JARDIN_INSET
                tree_positions.append((tx_j, ty_j, JARDIN_TREE_H, JARDIN_TREE_CANOPY_R))
        elif s.startswith(("nord", "n")):
            length = bmaxx - bminx
            n = max(1, int(length // APT_SPACING))
            for k in range(n):
                t = (k + 0.5) / n
                tx_j = bminx + t * length
                ty_j = bmaxy + JARDIN_INSET
                tree_positions.append((tx_j, ty_j, JARDIN_TREE_H, JARDIN_TREE_CANOPY_R))
        elif s.startswith(("est", "e")):
            length = bmaxy - bminy
            n = max(1, int(length // APT_SPACING))
            for k in range(n):
                t = (k + 0.5) / n
                tx_j = bmaxx + JARDIN_INSET
                ty_j = bminy + t * length
                tree_positions.append((tx_j, ty_j, JARDIN_TREE_H, JARDIN_TREE_CANOPY_R))
        elif s.startswith(("ouest", "o", "w")):
            length = bmaxy - bminy
            n = max(1, int(length // APT_SPACING))
            for k in range(n):
                t = (k + 0.5) / n
                tx_j = bminx - JARDIN_INSET
                ty_j = bminy + t * length
                tree_positions.append((tx_j, ty_j, JARDIN_TREE_H, JARDIN_TREE_CANOPY_R))
    print(f"  + {len(tree_positions)} jardin trees re-enabled (canopy 1.4m for visible tree volume)")

    # Windows : recessed openings on every storey of every voirie facade.
    # rdc_windows_quads emits 3 quads per window in this order:
    #   inner face (verre) → top reveal (enduit) → bottom reveal (enduit)
    # We call it once per storey and Z-offset, then split by index mod 3.
    def _shift_z(quads, dz):
        out = []
        for q in quads:
            out.append(Quad(
                v0=(q.v0[0], q.v0[1], q.v0[2] + dz),
                v1=(q.v1[0], q.v1[1], q.v1[2] + dz),
                v2=(q.v2[0], q.v2[1], q.v2[2] + dz),
                v3=(q.v3[0], q.v3[1], q.v3[2] + dz),
            ))
        return out

    storeys: list[tuple[float, float, float]] = []   # (z_floor, sill_offset, h_window)
    storeys.append((0.0, 0.9, 1.6))                  # RDC : sill 0.9, win 1.6
    for i in range(1, niveaux):
        z_floor_i = h_rdc + (i - 1) * h_etage
        # On upper floors with continuous balcons in front of the facade,
        # the window must sit behind the balcon parapet → sill 0.2, hw 1.8.
        storeys.append((z_floor_i, 0.2, 1.8))

    all_window_quads_verre: list = []
    all_window_quads_reveal: list = []
    for z_floor, sill, hw in storeys:
        # recess_depth_m NEGATIVE → window quad protrudes 3 cm OUTWARD from
        # the facade plane (visible decal). With positive recess, the verre
        # would be hidden BEHIND the continuous facade quad and never render.
        floor_quads = rdc_windows_quads(
            real_building_ring, voirie_sides,
            hauteur_rdc_m=h_rdc if z_floor == 0.0 else h_etage,
            window_width_m=1.5, window_height_m=hw,
            window_pitch_m=2.6, sill_height_m=sill,
            recess_depth_m=-0.03,
        )
        floor_quads = _shift_z(floor_quads, z_floor)
        for k, q in enumerate(floor_quads):
            if k % 3 == 0:
                all_window_quads_verre.append(q)
            # Skip the lintel/sill reveals — they'd be sticking outward
            # which looks ugly. The flush window face is enough.
    _add_building("verre", all_window_quads_verre)
    print(f"  + {len(all_window_quads_verre)} window faces "
          f"({len(storeys)} storeys × {len(voirie_sides)} sides)")

    toiture_info = model["envelope"].get("toiture") or {}
    setback = _polygon_inset(real_building_ring, 1.5)
    if toiture_info.get("accessible") and len(setback) >= 3:
        _add_building("balcon_concrete", rooftop_terrace_quads(setback, h))

    # Toit terrasse végétalisée : si toiture.vegetalisee=True, ajouter
    # un tapis de végétation au sommet du bâtiment. Visible from oblique
    # camera angles. Inset par 0.3m pour laisser un parapet/acrotère
    # béton tout autour.
    if toiture_info.get("vegetalisee"):
        green_roof_polygon = _polygon_inset(real_building_ring, 0.4)
        if len(green_roof_polygon) >= 3:
            # Triangulate the polygon and emit quads at z = h_total + 0.05
            # (slightly above the building roof quad).
            _xs_r = [p[0] for p in green_roof_polygon]
            _ys_r = [p[1] for p in green_roof_polygon]
            # For an L-shape, emit a single quad covering bbox of inset
            # ring (the roof can't be a "triangle fan" without proper
            # triangulation; bbox cover is approximate but works visually).
            green_roof_quads: list = []
            # Use the inset polygon vertices to form a roof — split into
            # triangle-fan from first vertex. Each triangle is a 3-vertex
            # quad (duplicate last point) at z = h_total + 0.05.
            v0_pt = green_roof_polygon[0]
            for i in range(1, len(green_roof_polygon) - 1):
                v1_pt = green_roof_polygon[i]
                v2_pt = green_roof_polygon[i + 1]
                green_roof_quads.append(Quad(
                    v0=(v0_pt[0], v0_pt[1], h + 0.05),
                    v1=(v1_pt[0], v1_pt[1], h + 0.05),
                    v2=(v2_pt[0], v2_pt[1], h + 0.05),
                    v3=(v2_pt[0], v2_pt[1], h + 0.05),
                ))
            _add_building("vegetation", green_roof_quads)
            print(f"  + {len(green_roof_quads)} green roof tris (toit terrasse vegetalisée)")

    # Acrotère (parapet) au bord du toit : bandeau béton 0.6m sur tout
    # le pourtour du building, visible profile depuis camera oblique.
    if toiture_info.get("type") == "terrasse":
        acrotere_h = 0.6
        for i in range(len(real_building_ring)):
            a = real_building_ring[i]
            b = real_building_ring[(i + 1) % len(real_building_ring)]
            if (a[0] - b[0])**2 + (a[1] - b[1])**2 < 0.25:
                continue
            # Two-sided wall : outer + inner face
            ex = b[0] - a[0]; ey = b[1] - a[1]
            eL = (ex*ex + ey*ey)**0.5 or 1.0
            nx_a = ey/eL; ny_a = -ex/eL
            thick = 0.15
            for sign in (-1.0, +1.0):
                px = nx_a * thick * sign
                py = ny_a * thick * sign
                _add_building("balcon_concrete", [Quad(
                    v0=(a[0]+px, a[1]+py, h),
                    v1=(b[0]+px, b[1]+py, h),
                    v2=(b[0]+px, b[1]+py, h + acrotere_h),
                    v3=(a[0]+px, a[1]+py, h + acrotere_h),
                )])
        print(f"  + acrotère 0.6m bandeau béton autour du toit")

    # 4a) Default natural ground (vegetation/jardin neutre) below the
    # camera frustum — fills the void left by the camera looking at
    # angles where the parcel/road doesn't reach. We use VEGETATION as
    # the default natural background (parks, residential gardens,
    # courtyards, untiled ground), NOT asphalt. The real BDTopo road
    # quads layer on top at z=0.05 (chaussée) and z=0.22 (trottoir).
    # This honours "implantation réelle" : asphalt only where BDTopo
    # cadastre says so, vegetation elsewhere.
    # Far ground = terre_neutre (sandy-grey natural earth/courtyard).
    # Distinct from pavers_concrete so the trottoir stands out as a real
    # sidewalk and the road quad chaussée+trottoir are clearly readable.
    _add("terre_neutre",
         far_ground_quad(parc_pts, radius_m=120.0, elevation_m=-0.05,
                         patch_size_m=8.0, jitter_m=0.0,
                         camera_pos_xy=(cam.position[0], cam.position[1]),
                         camera_target_xy=(cam.target[0], cam.target[1])))

    # 4) Voisinage BDTopo
    try:
        with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{project_id}") as r:
            proj = json.load(r)
        address = proj.get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
        origin = geocode_address(address)
        cx_local = sum(p[0] for p in parc_pts) / len(parc_pts)
        cy_local = sum(p[1] for p in parc_pts) / len(parc_pts)
        feats = fetch_voisins_bdtopo(origin, radius_m=180.0)
        voisins = voisins_to_local_polygons(
            feats, origin, (cx_local, cy_local),
            skip_overlap_with=real_building_ring,
            camera_pos_xy=(cam.position[0], cam.position[1]),
            block_camera_sight=True,
            max_distance_m=100.0, min_height_m=4.0, max_height_m=18.0,
        )
        # Filter voisins that overlap with synthetic roads (south + east
        # extensions). Voisins are at real BDTopo positions, but our
        # synthetic roads are placed arbitrarily based on building bbox.
        # Where they overlap, the voisin appears "on the road" (= bloc
        # bizarre à gauche the user complained about).
        from src.scene_mesh import _extrude_simple
        # Road bounding boxes (extension 30m past building bbox)
        road_bbox: list[tuple[float, float, float, float]] = []
        road_total_w = 5.0 + 1.5   # chaussée + trottoir
        for side in voirie_sides:
            s = side.lower()
            if s.startswith(("sud", "s")):
                road_bbox.append((
                    min(_bxs) - _bmargin - 30.0, max(_bxs) + _bmargin + 30.0,
                    min(_bys) - _bmargin - road_total_w, min(_bys) - _bmargin,
                ))
            elif s.startswith(("est", "e")):
                road_bbox.append((
                    max(_bxs) + _bmargin, max(_bxs) + _bmargin + road_total_w,
                    min(_bys) - _bmargin - 30.0, max(_bys) + _bmargin + 30.0,
                ))
            elif s.startswith(("nord", "n")):
                road_bbox.append((
                    min(_bxs) - _bmargin - 30.0, max(_bxs) + _bmargin + 30.0,
                    max(_bys) + _bmargin, max(_bys) + _bmargin + road_total_w,
                ))
            elif s.startswith(("ouest", "o", "w")):
                road_bbox.append((
                    min(_bxs) - _bmargin - road_total_w, min(_bxs) - _bmargin,
                    min(_bys) - _bmargin - 30.0, max(_bys) + _bmargin + 30.0,
                ))

        def _voisin_on_road(v_fp_local) -> bool:
            """True if voisin polygon overlaps any road bbox."""
            vxs = [p[0] for p in v_fp_local]; vys = [p[1] for p in v_fp_local]
            v_minx, v_maxx = min(vxs), max(vxs)
            v_miny, v_maxy = min(vys), max(vys)
            for rx0, rx1, ry0, ry1 in road_bbox:
                if v_maxx < rx0 or v_minx > rx1: continue
                if v_maxy < ry0 or v_miny > ry1: continue
                return True
            return False

        skipped_on_road = 0
        for v_fp, v_h in voisins:
            if _voisin_on_road(v_fp):
                skipped_on_road += 1
                continue
            quads = _extrude_simple(v_fp, v_h)
            _add("voisin", quads)
        print(f"  voisins skipped (on synthetic road) : {skipped_on_road}")

        # 5) Roads : SYNTHETIC voirie-based roads, adjacent to adjusted_parc.
        # iter #320 — REAL SCALE : trottoir 2.5m (was 1.5m) = vrai trottoir
        # parisien banlieue chic. chaussée stays 5m (residential lane).
        chaussee_qs, trottoir_qs, lane_qs = synthetic_voirie_roads_quads(
            adjusted_parc, voirie_sides,
            chaussee_width_m=5.0,
            trottoir_width_m=2.5,
            extension_m=60.0,
        )
        _add("asphalte", chaussee_qs)
        _add("pavers_concrete", trottoir_qs)
        _add("road_paint_white", lane_qs)
        print(f"  synthetic roads : {len(chaussee_qs)} chaussee + "
              f"{len(trottoir_qs)} trottoir + {len(lane_qs)} lane dashes")

        # 6) Real OSM trees (natural=tree) within 200 m of the address.
        # Earlier filter was 150m which missed trees on this street.
        try:
            osm_trees_latlng = fetch_osm_trees(origin, radius_m=200.0)
            print(f"OSM trees found : {len(osm_trees_latlng)} (natural=tree)")
            # Cone-of-sight filter : only keep trees broadly in front of
            # camera (within ±60° of view direction) and within 80m.
            cam_xy = (cam.position[0], cam.position[1])
            tgt_xy = (cam.target[0], cam.target[1])
            fdx = tgt_xy[0] - cam_xy[0]; fdy = tgt_xy[1] - cam_xy[1]
            fL = (fdx * fdx + fdy * fdy) ** 0.5 or 1.0
            fdx /= fL; fdy /= fL
            for tlat, tlng in osm_trees_latlng:
                tdx, tdy = wgs84_to_local(tlat, tlng, origin)
                # FIX 2026-05-11 : roads use (cx + dx, cy + dy) shift,
                # trees used to use (dx - cx, dy - cy) → INVERSE OFFSET,
                # 2×cx error ≈ 33m so trees fell on road. Align with roads.
                tx_loc = cx_local + tdx
                ty_loc = cy_local + tdy
                # Skip trees that fall ON the road/trottoir (synthetic
                # voirie extends ~6.5m past adjusted_parc on voirie sides).
                # Use adjusted_parc bbox for collision check.
                tree_on_road = False
                for side in voirie_sides:
                    s = side.lower()
                    if s.startswith(("sud", "s")) and ty_loc < min(_bys) - _bmargin:
                        tree_on_road = True; break
                    if s.startswith(("nord", "n")) and ty_loc > max(_bys) + _bmargin:
                        tree_on_road = True; break
                    if s.startswith(("est", "e")) and tx_loc > max(_bxs) + _bmargin:
                        tree_on_road = True; break
                    if s.startswith(("ouest", "o", "w")) and tx_loc < min(_bxs) - _bmargin:
                        tree_on_road = True; break
                if tree_on_road:
                    continue
                cam_dx = tx_loc - cam_xy[0]
                cam_dy = ty_loc - cam_xy[1]
                cam_dist = (cam_dx * cam_dx + cam_dy * cam_dy) ** 0.5
                if cam_dist > 80.0 or cam_dist < 3.0:
                    continue
                if cam_dist > 0:
                    dot = (cam_dx * fdx + cam_dy * fdy) / cam_dist
                    if dot < 0.4:
                        continue
                tree_positions.append((tx_loc, ty_loc, 5.0, 1.6))
            print(f"  + {len(tree_positions)} trees in camera frustum")
        except Exception as e:
            print(f"!! OSM tree fetch failed ({e}) — no trees rendered")

        # 7) Real OSM street lamps (highway=street_lamp + man_made=street_lamp)
        # within 150 m. Same rule : real positions only.
        try:
            osm_lamps_latlng = fetch_osm_street_lamps(origin, radius_m=150.0)
            print(f"OSM street lamps found : {len(osm_lamps_latlng)}")
            for llat, llng in osm_lamps_latlng:
                ldx, ldy = wgs84_to_local(llat, llng, origin)
                lx_loc = ldx - cx_local
                ly_loc = ldy - cy_local
                cam_dx = lx_loc - cam.position[0]
                cam_dy = ly_loc - cam.position[1]
                cam_dist = (cam_dx * cam_dx + cam_dy * cam_dy) ** 0.5
                if cam_dist > 80.0 or cam_dist < 3.0:
                    continue
                lamp_positions.append((lx_loc, ly_loc))
            print(f"  + {len(lamp_positions)} lamps in render frustum")
        except Exception as e:
            print(f"!! OSM street lamp fetch failed ({e}) — no lamps rendered")
    except Exception as e:
        print(f"!! BDTopo voisins/roads fetch failed ({e})")

    print(f"\nQuads by material :")
    total = 0
    for m, qs in quads_by_mat.items():
        print(f"  {m:20s} {len(qs):5d} quads")
        total += len(qs)
    print(f"  {'TOTAL':20s} {total:5d} quads\n")

    # Render via Blender.
    bp = BlenderPipeline()
    print(f"→ Blender Cycles render preset={preset} samples={samples} …")
    png = bp.render_from_quads.remote(
        quads_by_material=quads_by_mat,
        camera_pos=tuple(cam.position),
        camera_target=tuple(cam.target),
        camera_fov_deg=cam.fov_deg,
        sun_direction=(0.4, -0.6, 0.7),
        width=width, height=height, samples=samples,
        tree_positions=tree_positions,
        lamp_positions=lamp_positions,
        photoreal=photoreal,
        adaptive_threshold=adaptive_threshold,
    )
    # Save to /tmp for fast local access (used by FLUX finish pipeline).
    out = Path(f"/tmp/blender_{preset}_{seed}.png")
    out.write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out}")

    # ── PHASE 2 : USD export (renderer-agnostic, feeds future UE5 path) ──
    # Every Blender render also produces a .usda scene file that UE5 can
    # import directly. This is the bridge from our BM-driven scene graph
    # to UE5 + Lumen + Megascans + Speedtree. Zero overhead for the
    # current Blender path ; gives the UE5 pipeline a free input as soon
    # as the cloud infra is online.
    try:
        from src.scene_to_usd import export_scene_to_usda
        usd_out = Path(f"/tmp/blender_{preset}_{seed}.usda")
        export_scene_to_usda(
            quads_by_material=quads_by_mat,
            camera_position=tuple(cam.position),
            camera_target=tuple(cam.target),
            camera_fov_deg=cam.fov_deg,
            sun_direction=(0.4, -0.6, 0.7),
            sun_energy=5.0,
            output_path=usd_out,
        )
        print(f"✓ USD scene exported → {usd_out} ({usd_out.stat().st_size:,} bytes)")
        # Also persist in refs/baselines for the UE5 pipeline to consume later.
        try:
            from pathlib import Path as _P
            usd_persist_dir = _P(__file__).resolve().parent.parent.parent.parent / "refs" / "renders"
            usd_persist_dir.mkdir(parents=True, exist_ok=True)
            import os as _os3, datetime as _dt3
            _iter_tag = _os3.environ.get("BLENDER_ITER", "")
            _iter_part = f"_iter{_iter_tag}" if _iter_tag else ""
            _ts = _dt3.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            usd_persist_path = usd_persist_dir / f"{_ts}{_iter_part}_scene_{preset}_seed{seed}.usda"
            usd_persist_path.write_text(usd_out.read_text())
            print(f"✓ USD scene persisted → {usd_persist_path}")
        except Exception as _eu_persist:
            print(f"  !! USD persist failed ({_eu_persist}) — kept /tmp copy only")
    except Exception as _eu:
        print(f"!! USD export failed ({_eu}) — Blender render saved anyway")

    # iter #302 — 2ND PASS : SILHOUETTE MASK
    # Only the main-building quads, pure white emission on black background.
    # The FLUX endpoint reads this mask to know EXACTLY which pixels are
    # "our building" vs everything else (voirie, voisin, sky, ground). This
    # replaces the depth-based heuristic that produced holes under building
    # + ghost transparency. Architecture-level fix : no more ambiguity.
    print(f"\n→ Blender SILHOUETTE pass (building quads only, black bg) …")
    bld_total = sum(len(qs) for qs in building_quads_by_mat.values())
    print(f"  building quads : {bld_total} (vs full scene {total})")
    png_silhouette = bp.render_from_quads.remote(
        quads_by_material=building_quads_by_mat,
        camera_pos=tuple(cam.position),
        camera_target=tuple(cam.target),
        camera_fov_deg=cam.fov_deg,
        width=width, height=height,
        samples=16,         # silhouette = binary mask, samples don't matter
        silhouette_mode=True,
    )
    silhouette_out = Path(f"/tmp/blender_silhouette_{preset}_{seed}.png")
    silhouette_out.write_bytes(png_silhouette)
    print(f"✓ silhouette mask saved {len(png_silhouette):,} bytes → {silhouette_out}")

    # ALSO save to persistent refs/renders/ with timestamp so renders
    # survive macOS /tmp clear (reboot, etc). Filename has date + iter
    # marker if BLENDER_ITER env var is set, else just date + preset.
    import os as _os
    import datetime as _dt
    persist_dir = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "renders"
    persist_dir.mkdir(parents=True, exist_ok=True)
    iter_tag = _os.environ.get("BLENDER_ITER", "")
    iter_part = f"_iter{iter_tag}" if iter_tag else ""
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    persist_path = persist_dir / f"{ts}{iter_part}_blender_{preset}_seed{seed}.png"
    persist_path.write_bytes(png)
    print(f"✓ persisted → {persist_path}")
    # Auto-regen gallery so the new render appears immediately.
    try:
        import subprocess as _sp
        gallery_script = persist_dir.parent.parent / "scripts" / "gen_render_gallery.py"
        if gallery_script.exists():
            _sp.run(["python3", str(gallery_script)],
                    capture_output=True, text=True, check=True, timeout=15)
            print(f"  → gallery refreshed : {persist_dir / 'index.html'}")
    except Exception as _e:
        print(f"  !! gallery regen failed ({_e})")


@app.local_entrypoint()
def main(
    project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
    preset: str = "rue_se_eloignee",
    seed: int = 11,
    width: int = 1024,
    height: int = 1024,
    samples: int = 128,
    test_only: bool = False,
    photoreal: bool = False,
    adaptive_threshold: float = 0.01,   # validated lossless (−41 % Cycles); 0 to force fixed
):
    """Render a single preset. Thin passthrough to `_render_one` — behaviour
    identical to before the batch refactor."""
    _render_one(
        project_id=project_id, preset=preset, seed=seed,
        width=width, height=height, samples=samples,
        test_only=test_only, photoreal=photoreal,
        adaptive_threshold=adaptive_threshold,
    )


@app.local_entrypoint()
def batch(
    project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
    presets: str = "junction_pov,rue_se_eloignee,oiseau_iso,angle_3_4",
    seed: int = 11,
    width: int = 1024,
    height: int = 1024,
    samples: int = 128,
    photoreal: bool = False,
    adaptive_threshold: float = 0.01,
):
    """Render SEVERAL presets of one project in a single Modal app session.

    Lossless vs N separate `modal run main` calls (same scene, same cameras →
    identical pixels). The win is operational : all presets run back-to-back in
    one session, so the Blender container is spun up ONCE and stays warm across
    the loop — no cold start re-paid when you render angles spread out over a
    review session. Use `main` for single/iterative renders, `batch` for the
    final angle set.

        modal run src/modal_blender_endpoint.py::batch \\
          --project-id <id> --presets "junction_pov,oiseau_iso,angle_3_4"
    """
    preset_list = [p.strip() for p in presets.split(",") if p.strip()]
    print(f"══ batch : {len(preset_list)} presets, one warm container ══")
    for i, preset in enumerate(preset_list, 1):
        print(f"\n── [{i}/{len(preset_list)}] preset={preset} ──")
        _render_one(
            project_id=project_id, preset=preset, seed=seed,
            width=width, height=height, samples=samples,
            test_only=False, photoreal=photoreal,
            adaptive_threshold=adaptive_threshold,
        )
    print(f"\n✓ batch complete — {len(preset_list)} presets rendered")


# ---------------------------------------------------------------------------
# iter #303 — minimal CLI : render from a JSON config (quads + camera).
# Used by the L building 6-options × 6-POVs fan-out for Nogent 80 Héros.
# Bypasses building_model API — geometry/cameras passed via JSON directly.
# Invoked via :
#   modal run src/modal_blender_endpoint.py::render_from_json_cli \
#     --config-path /abs/path/to/config.json --out-png /abs/path/to/render.png
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def render_from_json_cli(
    config_path: str,
    out_png: str,
    samples: int = 64,
    photoreal: bool = True,
):
    """Render one Cycles image from a JSON config file.

    JSON schema :
      {
        "quads_by_material": {<material>: [[ [x,y,z], [x,y,z], [x,y,z], [x,y,z] ], ...]},
        "camera_pos":  [x, y, z],
        "camera_target": [x, y, z],
        "camera_fov_deg": 45.0,
        "sun_direction": [0.4, -0.6, 0.7]
      }
    """
    import json as _json
    cfg = _json.loads(Path(config_path).read_text())
    quads_by_material = cfg["quads_by_material"]
    cam_pos = tuple(cfg["camera_pos"])
    cam_target = tuple(cfg["camera_target"])
    fov = float(cfg.get("camera_fov_deg", 45.0))
    sun = tuple(cfg.get("sun_direction", (0.4, -0.6, 0.7)))

    bp = BlenderPipeline()
    print(f"→ rendering from {config_path}")
    print(f"  materials: {list(quads_by_material.keys())}")
    print(f"  total quads: {sum(len(qs) for qs in quads_by_material.values())}")
    png = bp.render_from_quads.remote(
        quads_by_material=quads_by_material,
        camera_pos=cam_pos,
        camera_target=cam_target,
        camera_fov_deg=fov,
        sun_direction=sun,
        width=1024, height=1024,
        samples=samples,
        photoreal=photoreal,
        add_real_assets=True,
    )
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out}")
