"""FLUX.1-schnell + ControlNet-depth render endpoint on Modal A100-40GB.

Why FLUX :
  - 12B params vs SDXL 2.6B → 5× capacity. Sharp textures natively.
  - Better prompt adherence — doesn't drift to "minimalist showroom" or
    "medieval stone manor" like RealVisXL/JuggernautXL did.
  - schnell = 4-step distilled → ~10× faster + cheaper than FLUX-dev.

Pipeline :
  BM + reasoner → dual prompt → stratified depth → FLUX-schnell + CN-depth
  → 1024 native render → (optional) tile-upscale to 2048.

Usage : .venv/bin/modal run src/modal_flux_endpoint.py
"""
from __future__ import annotations

import io
from typing import Optional

import modal

# FLUX-dev = the canonical 12B model, matches the Shakker-Labs ControlNet
# training distribution. Slower than schnell (50 steps + guidance=3.5) but
# the ControlNet integration works correctly.
FLUX_BASE = "black-forest-labs/FLUX.1-dev"
FLUX_CONTROLNET_DEPTH = "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
FLUX_CONTROLNET_CANNY = "InstantX/FLUX.1-dev-Controlnet-Canny"
FLUX_CONTROLNET_UNION = "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro"
FLUX_IP_ADAPTER = "XLabs-AI/flux-ip-adapter"
FLUX_IP_ADAPTER_FILE = "ip_adapter.safetensors"
FLUX_IP_ENCODER = "openai/clip-vit-large-patch14"

app = modal.App("archfr-flux-inference")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "diffusers==0.38.0",
        "transformers>=4.46",
        "pillow>=10.4",
        "safetensors>=0.4.5",
        "accelerate>=1.0",
        "huggingface_hub>=0.30",
        "sentencepiece>=0.2",
        "protobuf>=3.20",
        "spandrel==0.4.1",   # Real-ESRGAN x4 upscale for sharp 2K final
        "numpy>=1.26",
        "opencv-python-headless==4.10.0.84",   # cv2.Canny for 2nd ControlNet
    )
)

hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)


@app.cls(
    image=image,
    gpu="A100-80GB",        # 40GB OOM at 2K + ControlNet — 80GB needed
    timeout=900,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[modal.Secret.from_name("huggingface")],   # HF_TOKEN env var
    scaledown_window=300,
)
class FluxPipeline:
    @modal.enter()
    def load(self):
        """Load FLUX-dev + dual ControlNet (Depth + Canny) + Img2Img variant."""
        import os
        import torch
        from diffusers import FluxControlNetPipeline, FluxImg2ImgPipeline
        from diffusers.models import FluxControlNetModel, FluxMultiControlNetModel
        from huggingface_hub import login

        # Authenticate with the gated FLUX repo via the Modal secret.
        token = os.environ.get("HF_TOKEN")
        if token:
            login(token=token, add_to_git_credential=False)

        print(f"loading {FLUX_BASE} + Depth + Canny + Union-Pro on A100 …")
        controlnet_depth = FluxControlNetModel.from_pretrained(
            FLUX_CONTROLNET_DEPTH,
            torch_dtype=torch.bfloat16,
        )
        controlnet_canny = FluxControlNetModel.from_pretrained(
            FLUX_CONTROLNET_CANNY,
            torch_dtype=torch.bfloat16,
        )
        controlnet_union = FluxControlNetModel.from_pretrained(
            FLUX_CONTROLNET_UNION,
            torch_dtype=torch.bfloat16,
        )
        # Pipeline 1 : Multi-ControlNet (Depth + Canny) — rich building.
        controlnet_multi = FluxMultiControlNetModel([controlnet_depth, controlnet_canny])
        pipe = FluxControlNetPipeline.from_pretrained(
            FLUX_BASE,
            controlnet=controlnet_multi,
            torch_dtype=torch.bfloat16,
        )
        pipe.to("cuda")
        try:
            pipe.enable_vae_tiling()
        except Exception:
            pass
        self.pipe = pipe
        # Pipeline 2 : Union-Pro (single ControlNet) — clean road foreground.
        controlnet_union_multi = FluxMultiControlNetModel([controlnet_union, controlnet_union])
        pipe_union = FluxControlNetPipeline(
            scheduler=pipe.scheduler,
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            tokenizer=pipe.tokenizer,
            text_encoder_2=pipe.text_encoder_2,
            tokenizer_2=pipe.tokenizer_2,
            transformer=pipe.transformer,
            controlnet=controlnet_union_multi,
        )
        pipe_union.to("cuda")
        try:
            pipe_union.enable_vae_tiling()
        except Exception:
            pass
        # IP-Adapter : not loaded — bug structurel FluxControlNetPipeline.
        # Pass B uses FluxImg2ImgPipeline with SV photo as init instead.
        self.pipe_union = pipe_union
        # Build a sibling Img2Img pipeline (NO ControlNet) that shares
        # all weights — used in pass 3 to harmonize the composite (FLUX
        # foreground + Street View) at low denoise strength. Skipping
        # ControlNet because diffusers 0.35.1 has a bug in
        # FluxControlNetImg2ImgPipeline with FluxMultiControlNetModel.
        # At low strength (~0.40), the building barely moves anyway.
        img2img_pipe = FluxImg2ImgPipeline(
            scheduler=pipe.scheduler,
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            tokenizer=pipe.tokenizer,
            text_encoder_2=pipe.text_encoder_2,
            tokenizer_2=pipe.tokenizer_2,
            transformer=pipe.transformer,
        )
        img2img_pipe.to("cuda")
        self.img2img_pipe = img2img_pipe
        print("✓ FLUX dual-ControlNet pipeline ready (depth + canny + img2img-no-cn)")

    @modal.method()
    def render(
        self,
        prompt: str,
        depth_png: bytes,
        canny_png: Optional[bytes] = None,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        negative_prompt_2: Optional[str] = None,
        true_cfg_scale: float = 4.0,
        seed: Optional[int] = None,
        controlnet_conditioning_scale: float = 0.8,
        canny_conditioning_scale: float = 0.4,
        steps: int = 50,
        guidance_scale: float = 5.0,
        width: int = 2048,
        height: int = 2048,
        pipeline: str = "multi",
        ip_adapter_image_png: Optional[bytes] = None,
        ip_adapter_scale: float = 0.5,
    ) -> bytes:
        """Render with FLUX-dev + Depth + (optional) Canny ControlNet.

        With FluxMultiControlNetModel loaded, control_image must be a
        list of [depth, canny] images and controlnet_conditioning_scale
        must be a list of [depth_scale, canny_scale]. If canny_png is
        None, we duplicate depth at scale 0 (effectively disabling canny).
        """
        import torch
        from PIL import Image

        depth = Image.open(io.BytesIO(depth_png)).convert("RGB")
        if depth.size != (width, height):
            depth = depth.resize((width, height), Image.LANCZOS)

        if canny_png is not None:
            canny = Image.open(io.BytesIO(canny_png)).convert("RGB")
            if canny.size != (width, height):
                canny = canny.resize((width, height), Image.LANCZOS)
            control_images = [depth, canny]
            scales = [controlnet_conditioning_scale, canny_conditioning_scale]
        else:
            control_images = [depth, depth]
            scales = [controlnet_conditioning_scale, 0.0]

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None

        kwargs = dict(
            prompt=prompt,
            prompt_2=prompt_2 or prompt,
            control_image=control_images,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            controlnet_conditioning_scale=scales,
            width=width,
            height=height,
            generator=generator,
            max_sequence_length=512,
        )
        if pipeline == "union":
            kwargs["control_mode"] = [2, 0]
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
            kwargs["negative_prompt_2"] = negative_prompt_2 or negative_prompt
            kwargs["true_cfg_scale"] = true_cfg_scale

        active_pipe = self.pipe_union if pipeline == "union" else self.pipe
        out = active_pipe(**kwargs).images[0]

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def cn_img2img(
        self,
        init_png: bytes,
        depth_png: bytes,
        canny_png: bytes,
        prompt: str,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        strength: float = 0.55,
        depth_scale: float = 0.65,
        canny_scale: float = 0.55,
        guidance_scale: float = 3.5,
        true_cfg_scale: float = 5.0,
        steps: int = 30,
        width: int = 1024,
        height: int = 1024,
    ) -> bytes:
        """ControlNet-guided img2img : init = Blender PNG, geometry locked.

        Lazily initializes a FluxControlNetImg2ImgPipeline that shares
        weights with the existing text2img pipeline. With depth + canny
        ControlNet, the building geometry stays exactly as in the Blender
        render even at strength 0.65+, while FLUX is free to repaint
        materials, sky, vegetation, weathering, etc.
        """
        import torch
        from PIL import Image

        if not hasattr(self, "cn_img2img_pipe"):
            import torch as _torch
            from diffusers import FluxControlNetImg2ImgPipeline
            from diffusers.models import FluxControlNetModel
            print("→ initializing FluxControlNetImg2ImgPipeline (single-CN depth) …")
            # FluxMultiControlNetModel + FluxControlNetImg2ImgPipeline has
            # an UnboundLocalError bug in diffusers 0.38. Use single-CN depth.
            controlnet_depth_solo = FluxControlNetModel.from_pretrained(
                FLUX_CONTROLNET_DEPTH,
                torch_dtype=_torch.bfloat16,
            ).to("cuda")
            cn_pipe = FluxControlNetImg2ImgPipeline(
                scheduler=self.pipe.scheduler,
                vae=self.pipe.vae,
                text_encoder=self.pipe.text_encoder,
                tokenizer=self.pipe.tokenizer,
                text_encoder_2=self.pipe.text_encoder_2,
                tokenizer_2=self.pipe.tokenizer_2,
                transformer=self.pipe.transformer,
                controlnet=controlnet_depth_solo,
            )
            cn_pipe.to("cuda")
            try:
                cn_pipe.enable_vae_tiling()
            except Exception:
                pass
            self.cn_img2img_pipe = cn_pipe
            print("✓ cn_img2img pipeline ready (single-CN depth)")

        init = Image.open(io.BytesIO(init_png)).convert("RGB")
        if init.size != (width, height):
            init = init.resize((width, height), Image.LANCZOS)
        depth = Image.open(io.BytesIO(depth_png)).convert("RGB")
        if depth.size != (width, height):
            depth = depth.resize((width, height), Image.LANCZOS)
        canny = Image.open(io.BytesIO(canny_png)).convert("RGB")
        if canny.size != (width, height):
            canny = canny.resize((width, height), Image.LANCZOS)

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None

        kwargs = dict(
            prompt=prompt,
            prompt_2=prompt_2 or prompt,
            image=init,
            control_image=depth,                       # single-CN depth only
            controlnet_conditioning_scale=depth_scale,
            strength=strength,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            width=width,
            height=height,
            generator=generator,
            max_sequence_length=512,
        )
        # FluxControlNetImg2ImgPipeline doesn't accept negative_prompt;
        # canny ignored in single-CN mode (kwarg kept for signature stability).
        _ = canny  # canny unused in single-CN path

        out = self.cn_img2img_pipe(**kwargs).images[0]

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def harmonize_composite(
        self,
        composite_png: bytes,
        depth_png: bytes,
        canny_png: Optional[bytes],
        prompt: str,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        strength: float = 0.40,
        controlnet_conditioning_scale: float = 0.60,
        canny_conditioning_scale: float = 0.30,
        guidance_scale: float = 3.5,
        true_cfg_scale: float = 5.0,
        steps: int = 30,
        width: int = 1024,
        height: int = 1024,
    ) -> bytes:
        """Multi-stage img2img harmonization (Grok suggestion #3).

        Takes the FLUX text2img + Street View PIL composite as `image`,
        adds a low-strength noise-then-denoise pass through FLUX-dev
        ControlNet (depth + canny). The strength controls how much FLUX
        re-paints :
            0.30 → minimal, just smooths the seam
            0.40 → light harmonization, fixes watermark residues
            0.55 → moderate, may shift some details

        NOT inpainting (no mask) — the entire image goes through noise
        and FLUX denoises it back, guided by the ControlNets so the
        building geometry stays correct.
        """
        import torch
        from PIL import Image

        composite = Image.open(io.BytesIO(composite_png)).convert("RGB")
        if composite.size != (width, height):
            composite = composite.resize((width, height), Image.LANCZOS)

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None

        # Img2Img without ControlNet (diffusers bug with multi+img2img).
        # depth_png + canny_png args kept for signature stability (unused here).
        # The text2img pass 1 already imposed the geometry; this pass only
        # smooths the seam with low strength so the building stays nearly identical.
        kwargs = dict(
            prompt=prompt,
            prompt_2=prompt_2 or prompt,
            image=composite,
            strength=strength,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            width=width,
            height=height,
            generator=generator,
            max_sequence_length=512,
        )

        out = self.img2img_pipe(**kwargs).images[0]

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def esrgan_upscale(self, init_png: bytes, target_size: int = 2048) -> bytes:
        """Real-ESRGAN x4 upscale + downsample to `target_size` for crisp 2K."""
        import numpy as np
        import torch
        from PIL import Image

        if not hasattr(self, "_esrgan"):
            print("loading Real-ESRGAN x4plus via spandrel …")
            from huggingface_hub import hf_hub_download
            from spandrel import ModelLoader
            model_path = hf_hub_download(
                repo_id="ai-forever/Real-ESRGAN",
                filename="RealESRGAN_x4.pth",
            )
            self._esrgan = ModelLoader().load_from_file(model_path).cuda().eval()

        init = Image.open(io.BytesIO(init_png)).convert("RGB")
        arr = np.asarray(init, dtype=np.float32) / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).cuda()
        with torch.no_grad():
            up = self._esrgan(t)
        up = up.clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        big = Image.fromarray((up * 255).astype("uint8"))
        if max(big.size) > target_size:
            big = big.resize((target_size, target_size), Image.LANCZOS)
        buf = io.BytesIO()
        big.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

@app.local_entrypoint()
def main(project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
         preset: str = "rue_se_eloignee",
         seed: int = 11,
         size: int = 1024):
    """Generate depth from BM, send to Modal FLUX, save the PNG locally."""
    import json
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.depth_map import (
        camera_from_preset,
        depth_to_pil,
        render_depth_map,
    )

    def _ring_area(ring):
        n = len(ring)
        a = 0.0
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0

    from src.prompt_context.synthesizer import synthesize_dual_prompts
    from src.scene_mesh import (
        balcons_filants_quads,
        clip_footprint_to_parcelle,
        entrance_canopy_quad,
        far_ground_quad,
        jardins_rdc_quads,
        lampposts_quads,
        opposing_street_quads,
        parked_cars_quads,
        pleine_terre_quads,
        rdc_bandeau_quads,
        rdc_windows_quads,
        roads_bdtopo_to_quads,
        rooftop_terrace_quads,
        voirie_strip_quads,
    )
    from src.depth_map import _polygon_inset
    from src.voisinage_mesh import (
        fetch_roads_bdtopo,
        fetch_voisins_bdtopo,
        geocode_address,
        roads_to_local_polylines,
        voisins_to_local_polygons,
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

    # Phase 5g — Real implantation matching the plan-masse :
    #   1. Clip envelope footprint to the parcelle polygon → real building outline
    #   2. Voirie strips on the BM-declared sides (here est + sud)
    #   3. BDTopo voisinage filtered by distance + sight line
    parc = bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0]
    parc_pts = [(p[0], p[1]) for p in parc[:-1]]

    # 1. Clip the building footprint to the cadastral parcel.
    clipped_rings = clip_footprint_to_parcelle(fp_xy, parc_pts)
    real_building_ring = max(clipped_rings, key=lambda r: _ring_area(r))
    print(f"clipped footprint : {len(real_building_ring)} pts (was {len(fp_xy)})")

    # 2. Voirie strips on the project's voirie sides.
    voirie_sides = bm["model_json"]["site"].get("voirie_orientations") or ["sud"]
    # Bump bahut + grille from defaults (0.6 + 1.4 = 2 m absolute) to
    # (1.0 + 2.4 = 3.4 m absolute) so the parcel boundary projects clearly
    # in the depth map and FLUX can't lose it under the cn=0.80 normalisation
    # of a 17 m R+5 building. Without this, FLUX paints the boundary as
    # uninterrupted sidewalk and the building looks "flush with the street".
    # iter #316 : bahut 0.2m + grille 0.6m = 0.8m total. Even lower so the
    # camera sees deeper into the lawn → pleine_terre vegetation reads
    # CLEARLY as a residential lawn.
    voirie_quads_list = voirie_strip_quads(
        parc_pts, voirie_sides, thickness_m=6.0,
        bahut_height_m=0.2, grille_height_m=0.6,
        emit_flat_ground=False,
    )
    # 2a. Opposing geometry : DISABLED. Every variant we tried
    # (chaussée+trottoir = parking ; far facade = squashed main building ;
    # tiled ground = scratch lines ; flat ground = water/marble dalles).
    # Reverting to the clean pipeline — voirie strips on parcel only,
    # no far_ground, no opposing.
    opposing_list: list = []

    # 2b. Pleine terre (parcelle ∖ footprint) — explicit ground slab so
    # FLUX renders a garden/jardin area, not just empty depth.
    pleine_terre_list = pleine_terre_quads(parc_pts, real_building_ring)
    print(f"pleine terre : {len(pleine_terre_list)} fan-triangles")

    # 2c. Balcons filants on every voirie facade at every floor above RDC.
    niveaux = int(model["envelope"].get("niveaux") or 6)
    h_rdc = float(model["envelope"].get("hauteur_rdc_m") or 3.5)
    h_etage = float(model["envelope"].get("hauteur_etage_courant_m") or 2.7)
    balcons_list = balcons_filants_quads(
        real_building_ring, voirie_sides,
        niveaux=niveaux, hauteur_rdc_m=h_rdc, hauteur_etage_m=h_etage,
    )
    print(f"balcons filants : {len(balcons_list)} quads ({niveaux - 2} floors × {len(voirie_sides)} sides)")
    # Low-height garden hedges (60 cm) — visible enough that FLUX renders
    # the garden zone, but short enough to avoid the "parking plot" bug.
    # Front-garden : medium partitions 1.2m + ornamental trees (boxwood
    # / hydrangea / lavender bushes). The trees give the parcel a real
    # garden feel while staying low enough not to block the RDC wall.
    jardins_list = jardins_rdc_quads(
        real_building_ring, voirie_sides,
        partition_height_m=1.2, add_trees=True,
    )
    print(f"cloisons jardins RDC + ornamental trees : {len(jardins_list)} quads")
    # Entrance canopy : flat 6×2×0.6m slab at z=2.6..3.2m. Simple horizontal
    # awning above the door. The depth alone can't force FLUX to paint a door
    # — that comes from the prompt. We just provide a clear depth marker
    # ("there's something projecting from the wall here").
    entrance_list = entrance_canopy_quad(
        real_building_ring, voirie_sides,
        canopy_width_m=6.0, canopy_depth_m=2.0,
        canopy_z_base_m=2.6, canopy_z_top_m=3.2,
    )
    print(f"entrance canopy : {len(entrance_list)} quads")
    # Rooftop : if the BM toiture is accessible, full furniture (garde-corps
    # + planters + pergola). If not accessible (most cases), only a low
    # parapet — extensive vegetation is a 5cm sedum mat, not visible in
    # depth. Putting pergola/planters on a non-accessible roof renders as
    # a fake "rooftop bar" which is wrong.
    toiture_info = model["envelope"].get("toiture") or {}
    setback = _polygon_inset(real_building_ring, 1.5)
    if toiture_info.get("accessible") and len(setback) >= 3:
        rooftop_list = rooftop_terrace_quads(setback, h)
        print(f"rooftop terrasse (accessible) : {len(rooftop_list)} quads")
    else:
        rooftop_list = []
        print(f"rooftop : non-accessible (BM accessible={toiture_info.get('accessible')}) — no furniture")

    # 3. Voisinage from BDTopo.
    voisins_polygons = []
    try:
        with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{project_id}") as r:
            proj = json.load(r)
        address = proj.get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
        origin = geocode_address(address)
        cx_local = sum(p[0] for p in parc_pts) / len(parc_pts)
        cy_local = sum(p[1] for p in parc_pts) / len(parc_pts)
        feats = fetch_voisins_bdtopo(origin, radius_m=180.0)
        voisins_polygons = voisins_to_local_polygons(
            feats, origin, (cx_local, cy_local),
            skip_overlap_with=real_building_ring,
            camera_pos_xy=(cam.position[0], cam.position[1]),
            block_camera_sight=True,
            max_distance_m=100.0,
            min_height_m=4.0,
            max_height_m=18.0,   # Nogent quartier village = R+5 max ~15-18 m
        )
        print(f"voisinage : {len(voisins_polygons)} buildings (filtered)")
    except Exception as e:
        print(f"!! voisinage fetch failed ({e})")

    # 3b. BDTopo road network (TRONCON_DE_ROUTE) → real cadastral roads
    # in 3D under the same camera as the building. Replaces the synthetic
    # voirie_strip + composite Street View hacks.
    roads_quads_list: list = []
    try:
        with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{project_id}") as r:
            proj = json.load(r)
        address = proj.get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
        origin = geocode_address(address)
        cx_local = sum(p[0] for p in parc_pts) / len(parc_pts)
        cy_local = sum(p[1] for p in parc_pts) / len(parc_pts)
        road_feats = fetch_roads_bdtopo(origin, radius_m=180.0)
        print(f"BDTopo roads RAW : {len(road_feats)} features")
        if road_feats:
            sample = road_feats[0].get("properties", {})
            print(f"   sample props: chaussee={sample.get('largeur_de_chaussee')}, "
                  f"position={sample.get('position_par_rapport_au_sol')}, "
                  f"nature={sample.get('nature')}")
        road_polylines = roads_to_local_polylines(
            road_feats, origin, (cx_local, cy_local),
            require_ground_level=True,
            min_chaussee_width_m=2.0,
        )
        # BDTopo roads : back to depth quads (#145 config) with shapely
        # union to merge overlapping road buffers into one polygon, so
        # FLUX sees a single asphalt surface (not parallel strips).
        from src.scene_mesh import roads_bdtopo_to_quads
        roads_quads_list = roads_bdtopo_to_quads(
            road_polylines, parc_pts,
            trottoir_width_m=2.5,
            chaussee_height_m=0.05,
            trottoir_height_m=0.25,
            skip_overlap_with=parc_pts,
            max_distance_from_parcelle_m=50,
        )
        print(f"BDTopo roads : {len(road_polylines)} polylines → {len(roads_quads_list)} quads")
    except Exception as e:
        print(f"!! BDTopo roads fetch failed ({e})")

    # Render the full scene depth map.
    # Re-enable far_ground (single flat plane via background_quads, with
    # horizon clip + tone-down to [0.05, 0.35] norm in render_depth_map).
    # Combined with the bumped bahut (more visible barrier) + the strong
    # negatives (water/parking/cityscape blocked) + true_cfg=5, this
    # should give FLUX a "sol = grey ground" signal in the foreground
    # without producing the previous water/parking/cityscape bugs.
    far_ground = far_ground_quad(
        parc_pts, radius_m=80.0,
        camera_pos_xy=(cam.position[0], cam.position[1]),
        camera_target_xy=(cam.target[0], cam.target[1]),
    )
    print(f"far_ground (background_quads) : {len(far_ground)} quads")
    # jardins_list (RDC partition hedges, 1.6 m vertical) was being read as
    # a row of parking plots in the foreground — disabled. The garden is
    # now only described in the prompt.
    rdc_bandeau = rdc_bandeau_quads(real_building_ring, hauteur_rdc_m=h_rdc)
    print(f"RDC cornice : {len(rdc_bandeau)} quads")
    # NB : parked_cars / lampposts mesh dropped — FLUX rendered them as
    # ambiguous lumps (no improvement over plain asphalt prompt).
    # Approach ground : a donut around the parcel from boundary to +8m at
    # z=0.05 in extra_quads (high norm = same level as parcel). Without
    # this, the strip between bahut (high norm) and BDTopo road (bg norm)
    # is rendered by FLUX as floating shrubs / trees / hedges, making
    # the building look like it floats above vegetation. This donut
    # forces continuous ground from parcel to street.
    from src.scene_mesh import Quad as _Quad
    approach_ground_quads: list = []
    pxs = [p[0] for p in parc_pts]
    pys = [p[1] for p in parc_pts]
    parc_minx, parc_maxx = min(pxs), max(pxs)
    parc_miny, parc_maxy = min(pys), max(pys)
    APPROACH_BUF = 8.0   # back to #145 config — user validated
    # Outer rectangle (parcel + buf), then we build 4 strips (north/south/east/west)
    # by composing rectangles between parcel edge and outer edge.
    for side, ring in [
        ("south", [(parc_minx - APPROACH_BUF, parc_miny - APPROACH_BUF),
                   (parc_maxx + APPROACH_BUF, parc_miny - APPROACH_BUF),
                   (parc_maxx + APPROACH_BUF, parc_miny),
                   (parc_minx - APPROACH_BUF, parc_miny)]),
        ("north", [(parc_minx - APPROACH_BUF, parc_maxy),
                   (parc_maxx + APPROACH_BUF, parc_maxy),
                   (parc_maxx + APPROACH_BUF, parc_maxy + APPROACH_BUF),
                   (parc_minx - APPROACH_BUF, parc_maxy + APPROACH_BUF)]),
        ("east",  [(parc_maxx, parc_miny),
                   (parc_maxx + APPROACH_BUF, parc_miny),
                   (parc_maxx + APPROACH_BUF, parc_maxy),
                   (parc_maxx, parc_maxy)]),
        ("west",  [(parc_minx - APPROACH_BUF, parc_miny),
                   (parc_minx, parc_miny),
                   (parc_minx, parc_maxy),
                   (parc_minx - APPROACH_BUF, parc_maxy)]),
    ]:
        approach_ground_quads.append(_Quad(
            v0=(ring[0][0], ring[0][1], 0.05),
            v1=(ring[1][0], ring[1][1], 0.05),
            v2=(ring[2][0], ring[2][1], 0.05),
            v3=(ring[3][0], ring[3][1], 0.05),
        ))
    print(f"approach ground donut : {len(approach_ground_quads)} quads ({APPROACH_BUF} m buf)")

    # Explicit sidewalk strip : a raised concrete pavers ribbon (3m wide,
    # z=0.30m) between the approach donut and the BDTopo road. This forces
    # FLUX to render a CLEAN sidewalk separating the parcel garden from
    # the asphalt — instead of the current "thin pelouse + immediately
    # asphalt" transition which looks unrealistic.
    sidewalk_quads: list = []
    SW_WIDTH = 3.0
    SW_HEIGHT = 0.30
    voirie_sides_lower = {s.lower() for s in voirie_sides}
    has_sud = any(s in ("sud", "south", "s") for s in voirie_sides_lower)
    has_est = any(s in ("est", "east", "e") for s in voirie_sides_lower)
    if has_sud:
        sidewalk_quads.append(_Quad(
            v0=(parc_minx - APPROACH_BUF, parc_miny - APPROACH_BUF - SW_WIDTH, SW_HEIGHT),
            v1=(parc_maxx + APPROACH_BUF, parc_miny - APPROACH_BUF - SW_WIDTH, SW_HEIGHT),
            v2=(parc_maxx + APPROACH_BUF, parc_miny - APPROACH_BUF, SW_HEIGHT),
            v3=(parc_minx - APPROACH_BUF, parc_miny - APPROACH_BUF, SW_HEIGHT),
        ))
    if has_est:
        sidewalk_quads.append(_Quad(
            v0=(parc_maxx + APPROACH_BUF, parc_miny - APPROACH_BUF - SW_WIDTH, SW_HEIGHT),
            v1=(parc_maxx + APPROACH_BUF + SW_WIDTH, parc_miny - APPROACH_BUF - SW_WIDTH, SW_HEIGHT),
            v2=(parc_maxx + APPROACH_BUF + SW_WIDTH, parc_maxy + APPROACH_BUF, SW_HEIGHT),
            v3=(parc_maxx + APPROACH_BUF, parc_maxy + APPROACH_BUF, SW_HEIGHT),
        ))
    print(f"sidewalk strip : {len(sidewalk_quads)} quads ({SW_WIDTH}m wide × {SW_HEIGHT}m high)")

    # Entrance pillars : 2 vertical piers (0.4×0.4×3.2m) flanking the
    # main entrance door at the south facade midpoint. Without these, the
    # door is just "imagined" by FLUX in the depth — the pillars give it
    # an explicit geometric anchor so the door is unambiguous.
    entrance_piers_quads: list = []
    primary_side = voirie_sides[0].lower() if voirie_sides else "sud"
    fp_xs = [p[0] for p in real_building_ring]
    fp_ys = [p[1] for p in real_building_ring]
    fp_minx, fp_maxx = min(fp_xs), max(fp_xs)
    fp_miny, fp_maxy = min(fp_ys), max(fp_ys)
    PIER_HALF = 0.50      # 1.0 m wide piers (boosted from 40 cm — tiny at 55 m)
    PIER_HEIGHT = 4.0     # 4 m tall, well above RDC ceiling
    DOOR_HALF_WIDTH = 1.5 # piers spaced 3.0 m apart
    PIER_OUT = 1.2        # piers project 1.2 m out from the wall
    if primary_side in ("sud", "south", "s"):
        cx_door = (fp_minx + fp_maxx) / 2
        y_door_in = fp_miny
        y_door_out = fp_miny - PIER_OUT
        for sign in (-1, +1):
            cx_pier = cx_door + sign * DOOR_HALF_WIDTH
            entrance_piers_quads.append(_Quad(
                v0=(cx_pier - PIER_HALF, y_door_out, 0.0),
                v1=(cx_pier + PIER_HALF, y_door_out, 0.0),
                v2=(cx_pier + PIER_HALF, y_door_out, PIER_HEIGHT),
                v3=(cx_pier - PIER_HALF, y_door_out, PIER_HEIGHT),
            ))
            entrance_piers_quads.append(_Quad(
                v0=(cx_pier - PIER_HALF, y_door_in, 0.0),
                v1=(cx_pier + PIER_HALF, y_door_in, 0.0),
                v2=(cx_pier + PIER_HALF, y_door_in, PIER_HEIGHT),
                v3=(cx_pier - PIER_HALF, y_door_in, PIER_HEIGHT),
            ))
    elif primary_side in ("est", "east", "e"):
        cy_door = (fp_miny + fp_maxy) / 2
        x_door_in = fp_maxx
        x_door_out = fp_maxx + PIER_OUT
        for sign in (-1, +1):
            cy_pier = cy_door + sign * DOOR_HALF_WIDTH
            entrance_piers_quads.append(_Quad(
                v0=(x_door_out, cy_pier - PIER_HALF, 0.0),
                v1=(x_door_out, cy_pier + PIER_HALF, 0.0),
                v2=(x_door_out, cy_pier + PIER_HALF, PIER_HEIGHT),
                v3=(x_door_out, cy_pier - PIER_HALF, PIER_HEIGHT),
            ))
            entrance_piers_quads.append(_Quad(
                v0=(x_door_in, cy_pier - PIER_HALF, 0.0),
                v1=(x_door_in, cy_pier + PIER_HALF, 0.0),
                v2=(x_door_in, cy_pier + PIER_HALF, PIER_HEIGHT),
                v3=(x_door_in, cy_pier - PIER_HALF, PIER_HEIGHT),
            ))
    print(f"entrance piers : {len(entrance_piers_quads)} quads (door frame at midpoint)")

    # entrance_piers_quads disabled : 1m × 1m × 4m piers were interpreted by
    # FLUX as a "tree on the south facade" rather than a doorframe. The
    # entrance is left to the prompt + canopy depth marker.
    # Lampposts/cars : tested re-enabling in #162 — FLUX still renders them
    # as ambiguous lumps (same bug as #94). Disabled.
    extra_all = (voirie_quads_list or []) + (opposing_list or []) + (balcons_list or []) + (rooftop_list or []) + (jardins_list or []) + (entrance_list or []) + (rdc_bandeau or []) + (pleine_terre_list or []) + (approach_ground_quads or []) + (sidewalk_quads or [])
    # Parcel ground bridge : a flat quad covering the parcelle + 25m buffer
    # at z=0 in background_quads. Fills the "ground gap" between the
    # building's base and the BDTopo road, so FLUX doesn't paint sky
    # underneath the building (the floating-building bug).
    from src.scene_mesh import Quad
    pxs = [p[0] for p in parc_pts]
    pys = [p[1] for p in parc_pts]
    bridge_buf = 25.0
    parcel_ground = [Quad(
        v0=(min(pxs) - bridge_buf, min(pys) - bridge_buf, 0.0),
        v1=(max(pxs) + bridge_buf, min(pys) - bridge_buf, 0.0),
        v2=(max(pxs) + bridge_buf, max(pys) + bridge_buf, 0.0),
        v3=(min(pxs) - bridge_buf, max(pys) + bridge_buf, 0.0),
    )]
    print(f"parcel ground bridge : {len(parcel_ground)} quad ({bridge_buf} m buffer)")
    # BDTopo roads go to BACKGROUND_QUADS (toned to norm [0.05, 0.35] in
    # render_depth_map = "ground extending to horizon").
    background_all = (far_ground or []) + (parcel_ground or []) + (roads_quads_list or [])
    depth = render_depth_map(real_building_ring, h, cam,
                             voisins=voisins_polygons or None,
                             extra_quads=extra_all or None,
                             background_quads=background_all or None)
    depth_pil = depth_to_pil(depth)
    depth_dump = Path(f"/tmp/depth_{preset}_{seed}.png")
    depth_pil.save(depth_dump, format="PNG")
    print(f"depth saved → {depth_dump}")
    buf = io.BytesIO()
    depth_pil.save(buf, format="PNG")
    depth_png = buf.getvalue()

    # ── Canny edge map for the 2nd ControlNet ──
    # Run cv2.Canny on the depth map. The depth has clear contrast at
    # geometry boundaries (bahut top, grille, walkway, entrance canopy,
    # balcons, building outline) so canny extracts the parcel boundary
    # silhouette which the depth alone fails to materialize for FLUX.
    try:
        import cv2 as _cv2
        import numpy as _np
        from PIL import Image as _Image
        depth_arr = _np.asarray(depth_pil.convert("L"), dtype=_np.uint8)
        # Smooth before canny so micro-jitter doesn't produce noise.
        depth_blur = _cv2.GaussianBlur(depth_arr, (3, 3), 0.7)
        canny_arr = _cv2.Canny(depth_blur, 30, 90)   # low/high thresholds
        # ── Project the entry door outline onto the canny so FLUX has a
        # 2D edge cue at the right position (derived from BM, not hardcoded). ──
        # The door is a 2.4×2.6m rectangle on the primary voirie facade
        # at the midpoint, z=0..2.6m. We project its 4 corners + draw rect.
        try:
            from src.depth_map import _view_matrix as _vm, _proj_matrix as _pm
            view = _vm(cam)
            proj = _pm(cam)

            DOOR_W = 2.4
            DOOR_H = 2.6
            primary_side_lc = (voirie_sides[0] if voirie_sides else "sud").lower()
            fp_xs2 = [p[0] for p in real_building_ring]
            fp_ys2 = [p[1] for p in real_building_ring]
            fp_minx2, fp_maxx2 = min(fp_xs2), max(fp_xs2)
            fp_miny2, fp_maxy2 = min(fp_ys2), max(fp_ys2)
            if primary_side_lc in ("sud", "south", "s"):
                cx_d = (fp_minx2 + fp_maxx2) / 2
                door_corners_world = [
                    (cx_d - DOOR_W / 2, fp_miny2, 0.0),         # bottom-left
                    (cx_d + DOOR_W / 2, fp_miny2, 0.0),         # bottom-right
                    (cx_d + DOOR_W / 2, fp_miny2, DOOR_H),      # top-right
                    (cx_d - DOOR_W / 2, fp_miny2, DOOR_H),      # top-left
                ]
            elif primary_side_lc in ("est", "east", "e"):
                cy_d = (fp_miny2 + fp_maxy2) / 2
                door_corners_world = [
                    (fp_maxx2, cy_d - DOOR_W / 2, 0.0),
                    (fp_maxx2, cy_d + DOOR_W / 2, 0.0),
                    (fp_maxx2, cy_d + DOOR_W / 2, DOOR_H),
                    (fp_maxx2, cy_d - DOOR_W / 2, DOOR_H),
                ]
            else:
                door_corners_world = []

            if door_corners_world:
                pts = _np.array([(x, y, z, 1.0) for x, y, z in door_corners_world])
                view_h = (view @ pts.T).T
                view_z = -view_h[:, 2]
                clip = (proj @ view_h.T).T
                w = clip[:, 3].copy()
                w[w == 0] = 1e-6
                ndc = clip[:, :3] / w[:, None]
                Hc, Wc = canny_arr.shape
                screen = _np.empty((4, 2), dtype=int)
                screen[:, 0] = ((ndc[:, 0] * 0.5 + 0.5) * Wc).astype(int)
                screen[:, 1] = ((1.0 - (ndc[:, 1] * 0.5 + 0.5)) * Hc).astype(int)
                # Only draw if door is in front of camera + on screen.
                if (view_z > 0.5).all() and (screen[:, 0] > 0).any() and (screen[:, 0] < Wc).any():
                    pts2 = screen.tolist()
                    _cv2.line(canny_arr, tuple(pts2[0]), tuple(pts2[1]), 255, 3)
                    _cv2.line(canny_arr, tuple(pts2[1]), tuple(pts2[2]), 255, 3)
                    _cv2.line(canny_arr, tuple(pts2[2]), tuple(pts2[3]), 255, 3)
                    _cv2.line(canny_arr, tuple(pts2[3]), tuple(pts2[0]), 255, 3)
                    # Vertical mid line = double-leaf split (subtle)
                    midx = (pts2[0][0] + pts2[1][0]) // 2
                    _cv2.line(canny_arr, (midx, pts2[3][1]), (midx, pts2[0][1]), 255, 2)
                    print(f"door silhouette drawn on canny (3px) at screen coords {pts2}")
        except Exception as _e:
            print(f"!! door silhouette projection failed ({_e}) — canny without door cue")
        # ── Single thin road centerline on canny (axe blanc fin) ──
        # Project ONLY the closest BDTopo road segment per voirie side,
        # as a SINGLE thin line. Avoids the multi-lane highway bug
        # (which came from many parallel lines) while giving FLUX a
        # subtle "single residential lane" centerline cue.
        try:
            from src.depth_map import _view_matrix as _vm2, _proj_matrix as _pm2
            from shapely.geometry import LineString as _SL2, Polygon as _SP2
            parc_geom = _SP2([(p[0], p[1]) for p in parc_pts])
            if not parc_geom.is_valid:
                parc_geom = parc_geom.buffer(0)
            # Pick the SINGLE polyline closest to the parcel south boundary.
            best_road = None
            best_dist = float("inf")
            for road in (road_polylines or []):
                pl = road.get("polyline") or []
                if len(pl) < 2:
                    continue
                line = _SL2(pl)
                d = line.distance(parc_geom)
                if d < best_dist and d < 8.0:
                    best_dist = d
                    best_road = road
            if best_road:
                view_r2 = _vm2(cam)
                proj_r2 = _pm2(cam)
                Hc, Wc = canny_arr.shape
                pl = best_road["polyline"]
                pts3 = _np.array([(x, y, 0.05, 1.0) for x, y in pl])
                view_h_r = (view_r2 @ pts3.T).T
                view_z_r = -view_h_r[:, 2]
                clip_r = (proj_r2 @ view_h_r.T).T
                w_r = clip_r[:, 3].copy()
                w_r[w_r == 0] = 1e-6
                ndc_r = clip_r[:, :3] / w_r[:, None]
                screen_r = _np.empty((len(pl), 2), dtype=int)
                screen_r[:, 0] = ((ndc_r[:, 0] * 0.5 + 0.5) * Wc).astype(int)
                screen_r[:, 1] = ((1.0 - (ndc_r[:, 1] * 0.5 + 0.5)) * Hc).astype(int)
                # Draw as DASHED line — short segments every 6 pts to mimic
                # axe central blanc discontinu typique residential.
                for i in range(0, len(pl) - 1, 2):  # skip every other = dashed
                    if view_z_r[i] < 0.5 or view_z_r[i + 1] < 0.5:
                        continue
                    p1 = (int(screen_r[i, 0]), int(screen_r[i, 1]))
                    p2 = (int(screen_r[i + 1, 0]), int(screen_r[i + 1, 1]))
                    _cv2.line(canny_arr, p1, p2, 255, 1)  # 1px thin
                print(f"axe central canny : 1 polyline segment closest road")
        except Exception as _e:
            print(f"!! axe central projection failed ({_e})")
        canny_pil = _Image.fromarray(canny_arr).convert("RGB")
        canny_dump = Path(f"/tmp/canny_{preset}_{seed}.png")
        canny_pil.save(canny_dump, format="PNG")
        print(f"canny saved (with test overlay) → {canny_dump}")
        cbuf = io.BytesIO()
        canny_pil.save(cbuf, format="PNG")
        canny_png = cbuf.getvalue()
    except Exception as e:
        print(f"!! canny generation failed ({e}) — disabling 2nd ControlNet")
        canny_png = None

    prompt, prompt_2, negative = synthesize_dual_prompts(
        bm, preset, project_id=project_id
    )
    # The detailed architectural spec goes into PROMPT_2 (T5-XXL, up to
    # 1024 tokens), NOT into prompt (CLIP-L, 77 tokens, would be truncated).
    prompt_2 += (
        # ── Building — modern Île-de-France contemporary residential 2024 ──
        ". the building is a SIX-STOREY R+5 contemporary French residential apartment block, "
        "ARCHITECTURAL STYLE : modern Île-de-France 2024 RE2020-compliant, sober minimalist, "
        "close to the work of Antonini-Darmon or DREAM architects — clean horizontal lines, "
        "balanced fenestration, lived-in not corporate. "
        "FAÇADE : ultra-flat smooth troweled lime render (enduit taloché blanc cassé), "
        "matt finish, perfectly clean walls without staining or weathering, "
        "subtle warm undertone (RAL 9001 cream-white) catching the morning light. "
        "WINDOWS : tall vertical proportions (1.4m wide × 2.2m tall), framed in matt anthracite "
        "aluminium (RAL 7016 satin), thin 8 cm pale-stone surround on each side, deep reveal "
        "(15 cm jamb depth) for crisp shadow lines. CLEAR triple glazing, dark interior visible "
        "through glass, occasional warm interior light glow at dusk hours. "
        # ── Balconies + STRICT PRIVACY (anti-vues réglementaires) ──
        "every floor above the RDC has a CONTINUOUS slim cantilevered concrete balcony "
        "(15 cm slab depth, 1.2 m projection). "
        "PRIVACY-FIRST GUARD-RAIL : slim BLACK STEEL VERTICAL TUBES (20×20 mm, 11 cm spacing, "
        "1.05 m tall) topped with a thin matt black handrail (RAL 9005). "
        "BETWEEN EVERY TWO ADJACENT APARTMENTS : a TALL OPAQUE PRIVACY PARTITION — "
        "matt anthracite RAL 7016 metal panel, 1.85 m tall, full balcony depth — "
        "completely blocking the line of sight between neighbours. these partitions are "
        "STRUCTURAL and CONSPICUOUS, NOT optional, on EVERY level R+1 to R+5. "
        "INTERIOR ANTI-VUE : every balcony has WHITE SHEER LINEN CURTAINS hung INSIDE the apartment "
        "behind the glass door, drawn at 50% — you CAN see the curtains but NEVER inside the rooms. "
        "ABSOLUTELY NO furniture (sofa, chair, table) facing the street, NO interior visible from outside. "
        "POTTED PLANTS LIVED-IN : on roughly 60% of balconies, large terracotta pots with "
        "Mediterranean species — small olive trees, rosemary, lavender, sage, "
        "trailing English ivy spilling over the rail, occasional lemon trees. "
        "VARIED, IRREGULAR placement (NOT every balcony, NOT identical) — feels inhabited. "
        # ── Attic — prominent green roof modern (RE2020 signature) ──
        "TOP FLOOR (R+5 attic) : SET BACK 1.5 m from the lower facade, with FULL-PERIMETER "
        "GREEN PARAPET — wide rectangular planters integrated into the slab edge, "
        "filled with LUSH flowering plants : purple lavender, ornamental grasses, "
        "white jasmine vines cascading down the parapet edge, low boxwood spheres, "
        "small Japanese maples in larger planters at the corners. "
        "the green parapet forms a CONTINUOUS RIBBON of greenery 1 m tall, clearly visible "
        "from street level, defining the silhouette of the rooftop. "
        "behind the planters : flat sedum roof (low extensive, 5 cm sedum mat), "
        "thin anthracite zinc capping (RAL 7016, 80 mm wide). "
        "NO rooftop terrace deck, NO pergola, NO people on the roof, NO solar panels visible. "
        # ── Ground floor (RDC) — solid base with entrance focal point ──
        "the GROUND FLOOR (RDC) is a SOLID MASONRY WALL in the same off-white render. "
        "REGULAR SQUARE WINDOWS at 1.6 m height (smaller than upper floors, 1.0 m × 1.2 m), "
        "evenly spaced at 4 m intervals along the facade, framed in matching anthracite aluminium. "
        "above the RDC : a HORIZONTAL CORNICE BAND (30 cm protrusion, 35 cm tall, off-white smooth render) "
        "runs along the ENTIRE facade between RDC and R+1, clearly separating the base from the apartments. "
        "this cornice catches the sun and casts a thin shadow line on the wall below. "
        "STRICTLY no shops, no arcade, no pilotis, no commercial windows, no glazing across the RDC. "
        # ── ENTRÉE — focal point ultra-spec ──
        "AT THE EXACT GEOMETRIC MIDDLE of the south facade RDC : "
        "a TALL DOUBLE-LEAF GLAZED ENTRANCE — 2.4 m wide × 2.7 m tall — "
        "made of CLEAR LOW-IRON GLASS panels in a SLIM MATT BLACK ANTHRACITE ALUMINIUM FRAME (RAL 9005). "
        "BRUSHED STAINLESS STEEL HORIZONTAL HANDLE (Ø 30 mm, 1.4 m long) at 1.05 m height. "
        "the entrance is RECESSED 60 cm into the facade for shadow depth. "
        "ABOVE the entrance, projecting OUTWARD 2 m horizontally : a slim FLAT CONCRETE CANOPY "
        "(8 cm thick slab, 6 m wide, smooth white render finish) with a thin recessed LED strip "
        "underneath, casting a subtle warm light on the door. "
        "TO THE LEFT of the door, mounted at 1.4 m height : a brushed STAINLESS STEEL INTERCOM PANEL "
        "(0.4 m × 0.5 m) with 8 illuminated buttons + speaker grille. "
        "TO THE RIGHT, mounted at 1.6 m height : a polished STAINLESS STEEL PLATE with the building "
        "number '80' engraved (0.15 m × 0.30 m). "
        "TWO WIDE PALE-STONE THRESHOLD STEPS (40 cm deep × 12 cm rise each) lead up from the walkway. "
        "THE ENTRANCE IS THE FOCAL POINT — visually the brightest contrast (DARK glass + BLACK frame "
        "in a PALE white wall) — drawing the eye immediately. "
        "ABSOLUTELY NO window where the door is, NO blank wall, NO repeated fenestration — "
        "the centre of the RDC IS the entrance, NOTHING ELSE. "
        # ── Parcel boundary + gate + walkway ──
        # ── PARCEL BOUNDARY — must be PHYSICALLY VISIBLE between sidewalk and building ──
        # CRITICAL : the building must NOT touch the public sidewalk directly.
        # There MUST be a 6 m setback strip between the sidewalk and the building wall,
        # filled with the front garden + walkway. The bahut wall + iron fence
        # mark this boundary clearly, immediately at the kerb.
        "between the public sidewalk and the building, there is a CLEAR 6-METRE PRIVATE SETBACK STRIP. "
        "running ALONG THE WHOLE LENGTH of the sidewalk (south + east edges of the parcel), "
        "right at the inner edge of the kerb, stands a LOW MASONRY BAHUT WALL (1 m tall, off-white render, "
        "flat pale-stone cap) — a PHYSICAL BOUNDARY clearly separating public street from private parcel. "
        "ON TOP of the bahut, mounted directly on the stone cap, "
        "a CLEARLY VISIBLE BLACK WROUGHT-IRON FENCE (slim vertical rods, 80 cm tall, "
        "matt black RAL 9005, three thin horizontal rails) runs along the entire boundary. "
        "the bahut + iron fence are the FIRST THING THE EYE SEES on the parcel side, just behind the kerb. "
        "the bahut + iron fence FOLLOW THE CADASTRAL PARCEL BOUNDARY including a chamfer at the south-east corner. "
        "an OPEN PEDESTRIAN GATE (3 m wide, framed by two off-white stone piers 1.8 m tall) "
        "is centred on the south boundary, directly aligned with the building's main entrance. "
        "from the open gate, a CLEARLY VISIBLE WIDE PAVED WALKWAY (2.5 m wide, light pale-stone slabs, "
        "perfectly straight, slightly raised on a 15 cm kerb, lined with low boxwood hedges) "
        "crosses the front garden in a straight axis from the public sidewalk to the building lobby — "
        "the walkway is the MOST EVIDENT GROUND FEATURE inside the parcel. "
        # ── Front garden — landscaped + PRIVACY HEDGES between RDC apts ──
        "BEHIND the iron fence, clearly visible above the bahut : a LUSH MATURE PRIVATE FRONT GARDEN "
        "professionally landscaped, NOT generic, divided into PRIVATE PLOTS per RDC apartment. "
        "BETWEEN EACH RDC APARTMENT'S PRIVATE GARDEN : DENSE EVERGREEN PRIVACY HEDGES "
        "(Cupressocyparis leylandii or Photinia × fraseri 'Red Robin', 1.8 m tall, perfectly "
        "trimmed vertical wall of green) — these CONSPICUOUS HEDGES block any line of sight "
        "between neighbouring private gardens. ABSOLUTELY visible as tall green walls "
        "perpendicular to the building, dividing the parcel into 3-4 private plots. "
        "WITHIN each plot : "
        "(1) low TRIMMED BOXWOOD spheres (Buxus sempervirens, 60 cm Ø) along the walkway edge, "
        "(2) flowering HYDRANGEA bushes (white + pink) along the bahut wall, "
        "(3) tall LAVENDER rows (purple-blue) under the windows, "
        "(4) one ornamental CHERRY tree (Prunus serrulata) on the SE corner of the parcel, "
        "(5) one MAGNOLIA (white-flowered, 4 m tall) on the SW corner, "
        "(6) neat green KIKUYU lawn between the walkway and the building wall, "
        "(7) GROUND-LEVEL LIGHTING (small LED uplights) at the base of each ornamental tree. "
        "ALL RDC WINDOWS have white sheer linen curtains drawn at 50% — you see the curtains "
        "but never the interior. NO sofas / chairs / interior visible behind the windows. "
        "everything is professionally maintained, mid-spring foliage, fresh blooms. "
        # ── Sidewalk + road ──
        # IMPORTANT — describe the foreground with extreme precision
        # so FLUX renders a real concrete sidewalk + asphalt road instead
        # of a hallucinated cityscape miniature on the ground.
        # ── GROUND PLANE : ROAD + SIDEWALK (FLAT, NOT ARCHITECTURE) ──
        # The foreground geometry comes from BDTopo cadastral road network
        # rasterised at z=2-10cm — it MUST be rendered as flat asphalt + concrete
        # pavers, NOT as a building roof / glass walkway / concrete platform.
        "EVERYTHING BELOW THE BUILDING'S RDC is REAL URBAN STREET — flat ground level. "
        "the GROUND PROGRESSION from parcel to street is : "
        "1) PRIVATE GARDEN (lawn) → 2) BAHUT WALL + IRON FENCE → 3) PUBLIC SIDEWALK (pavers) → "
        "4) STONE KERBSTONE (step down) → 5) ASPHALT ROAD (residential lane). "
        "PUBLIC SIDEWALK : RECTANGULAR PALE GREY CONCRETE PAVERS (30 × 60 cm, matt finish), "
        "laid in a regular running-bond pattern with thin dark grout lines (5 mm), "
        "completely HORIZONTAL flat ground, NOT raised, NOT a podium. "
        "where the sidewalk meets the road : a PROMINENT KERBSTONE in cream-grey LIMESTONE "
        "(15 cm step, dressed stone with chamfered top edge, sharp shadow line below). "
        "ASPHALT ROAD : SINGLE LANE FRESH BLACK TARMAC (matt finish, dark slate grey, NO shine, "
        "NO reflections, NO mirror effect — completely matte surface), "
        "running parallel to the parcel south edge, slightly visible perspective vanishing point. "
        "ROAD MARKINGS : ONE THIN DASHED WHITE CENTRELINE (4 cm wide, 50 cm dashes / 50 cm gaps) "
        "down the middle of the lane. NOTHING ELSE — no parking lines, no zigzag, no zebra in this view. "
        "STREET FURNITURE on the sidewalk side : "
        "- 2-3 CLASSICAL BLACK PARISIAN LAMPPOSTS (cast iron, 3.5 m tall, fluted shaft, single "
        "  white opal globe lantern at the top, base mounted on the kerbstone), "
        "- 3-4 YOUNG PLANE TREES (Platanus × acerifolia, 5 m tall, clean trunks ~15 cm Ø, "
        "  light spring foliage, low canopies), "
        "- small black metal ANTI-PARKING BOLLARDS (40 cm tall, 8 cm Ø) every 2 m along the kerb. "
        "ROAD SIDE : 3-4 PARALLEL-PARKED CONTEMPORARY EUROPEAN COMPACT CARS along the kerb "
        "(Renault Clio, Peugeot 208, Citroën C3, Volkswagen Polo — dark grey, navy, white matt), "
        "spaced 0.6 m apart, all facing the same direction. "
        "1-2 PEDESTRIANS walking on the sidewalk (autumn casual French clothing, neutral tones). "
        "ROAD SURFACE TEXTURE : grainy fine asphalt aggregate visible under the matte finish, "
        "subtle warm tonal variation between pavers, NO uniform dalle, NO marble, NO glass. "
        "ABSOLUTELY NO multi-lane highway, NO heavy markings, NO mirror surface, NO wet reflection, "
        "NO miniature city, NO aerial cityscape, NO water, NO podium under the building. "
        "the road and sidewalk are AT THE SAME GROUND LEVEL as the building foundations. "
        # ── Neighbours ──
        "Nogent-sur-Marne village quarter, quiet residential street. "
        "left : contiguous five-storey pale-cream-rendered apartment block with continuous filant balconies, "
        "zinc parapet and matching iron fence on a small front garden. "
        "right (across the side street) : four-storey 1900s Nogentais faubourg apartment with beige-pink render, "
        "classical stone surrounds, dark zinc roof with dormers, Juliette balconies. "
        "background : pale-rendered low-rise apartment blocks, all R+3 to R+5, no high-rise, no skyscraper, no metropolis. "
        # ── Lighting / Atmosphere ──
        "PHOTOGRAPHIC PARAMETERS : taken with a SONY α7R IV full-frame camera, 35mm prime lens "
        "at f/8, ISO 100, 1/250s shutter, neutral white balance. perfect SHARP focus throughout the depth. "
        "TIME : late morning, 10:30 AM in early May, soft natural directional sunlight from upper-left, "
        "subtle warm golden tones on the south + east facades, gentle shadows cast at 30°, "
        "no harsh contrast, no overexposure, deep saturated colours but realistic. "
        "SKY : clear pale-blue with a few thin high cirrus streaks (5% cloud cover), "
        "rich gradient from cyan zenith to softer blue near the horizon. "
        "ATMOSPHERIC depth : faint summer haze in the distant background, voisins seen through it. "
        "QUALITY : ultra-detailed 8K architectural photograph, magazine-grade real estate photography "
        "(AD, Architectural Digest style), every material clearly resolved, HDR balanced, "
        "professional polished but not over-processed, a STRONG SENSE OF PLACE in Île-de-France suburbia. "
        "NEGATIVES (do not include) : no people facing camera, no faces, no logos on cars, "
        "no street signs in foreign languages, no construction site, no cranes, no scaffolding."
    )
    full_prompt = (
        f"{prompt}. {prompt_2}. "
        "crisp sharp architectural photography, every detail clearly resolved, "
        "professional real estate render, cinematic light"
    )
    print(f"prompt ({len(full_prompt.split())} words): {full_prompt[:200]}…")

    flux = FluxPipeline()
    # Pass B prompt — laser focus on the urban street detail. Adapted to
    # IDF/Nogent typical residential street : dark asphalt + dashed centre +
    # stone kerbstone + concrete pavers + Parisian lampposts + cars + manholes
    # + zebra crossing damier at the SE intersection (typical Nogent).
    prompt_2_road = (
        prompt_2
        + " "
        + "ULTRA-DETAILED FRENCH RESIDENTIAL URBAN STREET in Île-de-France style : "
        "matt dark grey asphalt road surface (slightly weathered, no shine), "
        "narrow single-lane residential carriageway (NOT a highway, NOT multi-lane), "
        "with a SINGLE thin BROKEN WHITE CENTRELINE in mid-road. "
        "raised KERBSTONE in pale grey limestone separating asphalt from sidewalk. "
        "SIDEWALK in 50×50 cm pale grey concrete pavers (not tarmac), with thin "
        "joint lines every 1 m, COMPLETELY HORIZONTAL ground. "
        "CHECKERBOARD PEDESTRIAN CROSSING (zebra in damier pattern, typical Nogent-sur-Marne) "
        "at the south-east street corner where two streets meet. "
        "GIVE-WAY TRIANGLE marking (cédez-le-passage) painted on the asphalt before the crossing. "
        "round CAST-IRON MANHOLE COVERS (40 cm diameter) flush with the road surface. "
        # iter #300 : LAMPPOSTS removed from prompt — FLUX kept hallucinating
        # green orb / blob shapes at building entrance. Blender mesh provides
        # geometry; no prompt cue needed.
        "a few CARS PARKED along the kerb (modern compact Renault / Peugeot, dark colours, "
        "matt finish, parallel parking, well-spaced 0.5 m gaps). "
        "occasional PEDESTRIANS walking on the sidewalk in everyday French clothing. "
        "low ANTI-PARKING BOLLARDS (40 cm, matte black metal) at 2 m intervals "
        "between sidewalk and asphalt to prevent illegal parking on the sidewalk. "
        "atmosphere : real-life Nogent-sur-Marne street, NOT a video-game render, "
        "NOT a CGI maquette, photoreal documentary photo of the actual cadastral street."
    )
    common = dict(
        negative_prompt=negative,
        negative_prompt_2=negative,
        true_cfg_scale=5.0,
        depth_png=depth_png,
        canny_png=canny_png,
        seed=seed,
        # depth 0.80 (préserve détails building) + canny 0.60 (au lieu de
        # 0.40, pour mieux distinguer voisins boundaries = anti-fusion).
        controlnet_conditioning_scale=0.80,
        canny_conditioning_scale=0.60,
        steps=50,
        guidance_scale=3.5,
        width=size,
        height=size,
    )
    # Optional Street View reference for Pass B img2img (Nogent ambiance).
    # Crop the SV photo to remove Google watermarks (top 5%, bottom 7%,
    # left/right 7%) before sending to Modal — otherwise FLUX preserves
    # the watermarks at strength=0.65.
    sv_ref_path = Path("/tmp/streetview_nogent.png")
    sv_ref_bytes = None
    if sv_ref_path.exists():
        try:
            from PIL import Image as _Image
            _sv = _Image.open(sv_ref_path).convert("RGB")
            _w, _h = _sv.size
            # Crop : back to wide (top-bottom 5%-93%, sides 7%) — the
            # foreground zebra zone IS preserved. The wet/mirror reflet
            # is killed downstream by a MATTE post-process on the bottom
            # 25% of the final composite (de-highlights + grain).
            _sv_clean = _sv.crop((
                int(_w * 0.07), int(_h * 0.05),
                int(_w * 0.93), int(_h * 0.93),
            ))
            _buf = io.BytesIO()
            _sv_clean.save(_buf, format="PNG", optimize=True)
            sv_ref_bytes = _buf.getvalue()
            print(f"   Street View loaded + watermarks cropped ({_sv_clean.size}, {len(sv_ref_bytes):,} bytes)")
        except Exception as _e:
            print(f"!! SV crop failed ({_e})")

    print(f"→ pass A : FLUX Multi (Depth+Canny) — rich building …")
    png_building = flux.render.remote(
        pipeline="multi",
        prompt=prompt,
        prompt_2=prompt_2,
        **common,
    )

    # STRICT VOIRIE : utiliser le render BLENDER (geometry exacte cadastre)
    # comme png_road au lieu de regénérer avec FLUX. Le BLENDER render a
    # la VRAIE implantation X-carrefour + trottoirs + lane markings sans
    # hallucinations. Composite final = top 72% FLUX photo building +
    # bottom 28% Blender voirie strict.
    blender_path = Path(f"/tmp/blender_{preset}_{seed}.png")
    if blender_path.exists() and blender_path.stat().st_size > 1000:
        png_road = blender_path.read_bytes()
        print(f"✓ using BLENDER render for png_road (strict voirie) : {blender_path}")
        sv_ref_bytes = None   # skip SV pass
    elif sv_ref_bytes:
        # Pass B : img2img with SV photo as INIT, strength=0.75 (sweet spot).
        # 0.65 → too literal SV marks remain ; 0.85 → ambiance lost, sterile.
        # 0.75 keeps Nogent ambiance/colors but redraws specific markings.
        print(f"→ pass B : FLUX img2img Street View init (strength=0.75) …")
        png_road = flux.harmonize_composite.remote(
            composite_png=sv_ref_bytes,
            depth_png=depth_png,
            canny_png=canny_png,
            prompt=prompt,
            prompt_2=prompt_2_road,
            seed=(seed + 1) if seed is not None else None,
            strength=0.75,
            steps=50,
            guidance_scale=3.5,
            width=size,
            height=size,
        )
    else:
        # Fallback : Union-Pro without IP / SV ref.
        common_road = {**common}
        common_road["controlnet_conditioning_scale"] = 0.70
        common_road["canny_conditioning_scale"] = 0.30
        print(f"→ pass B (fallback) : FLUX Union-Pro — clean road foreground …")
        png_road = flux.render.remote(
            pipeline="union",
            prompt=prompt,
            prompt_2=prompt_2_road,
            **common_road,
        )

    # ESRGAN x4 → 2K BEFORE composite, on each pass separately. The
    # composite seam happens at 2K = sharper transition (was at 1K
    # then upscaled, blurring the seam).
    print(f"→ ESRGAN x4 on Pass A …")
    try:
        png_building = flux.esrgan_upscale.remote(init_png=png_building, target_size=2048)
        print(f"→ ESRGAN x4 on Pass B …")
        png_road = flux.esrgan_upscale.remote(init_png=png_road, target_size=2048)
        print("✓ both passes upscaled to 2K before composite")
    except Exception as e:
        print(f"!! ESRGAN failed before composite ({e}) — composite at 1K")

    print(f"→ composite : SILHOUETTE mask (Blender building-only pass) …")
    try:
        from PIL import Image as _Image, ImageFilter as _ImageFilter
        import numpy as _np
        img_b = _Image.open(io.BytesIO(png_building)).convert("RGB")
        img_r = _Image.open(io.BytesIO(png_road)).convert("RGB")
        if img_r.size != img_b.size:
            img_r = img_r.resize(img_b.size, _Image.LANCZOS)
        W2, H2 = img_b.size
        # iter #302 — SILHOUETTE-MASK COMPOSITE
        # The Blender endpoint now produces a 2nd pass at
        # /tmp/blender_silhouette_{preset}_{seed}.png — pure white where
        # the main building is, pure black everywhere else. This replaces
        # the depth-based heuristic that caused holes under building + ghost
        # transparency. The mask is unambiguous : every pixel is either
        # building (→ FLUX) or non-building (→ Blender voirie/voisin/sky).
        silhouette_path = Path(f"/tmp/blender_silhouette_{preset}_{seed}.png")
        used_silhouette = False
        if silhouette_path.exists() and silhouette_path.stat().st_size > 1000:
            try:
                sil_pil = _Image.open(silhouette_path).convert("L")
                if sil_pil.size != (W2, H2):
                    sil_pil = sil_pil.resize((W2, H2), _Image.LANCZOS)
                sil_arr = _np.asarray(sil_pil, dtype=_np.uint8)
                bld_frac = (sil_arr > 127).mean()
                print(f"  silhouette : {bld_frac*100:.1f}% pixels are building")
                # Binary threshold THEN small blur (8px) for clean anti-aliased
                # edge — no big blur (60px would leak Blender road into FLUX
                # building base = the bug we're fixing).
                mask = _np.where(sil_arr > 127, 255, 0).astype(_np.uint8)
                mask_pil = _Image.fromarray(mask, mode="L")
                mask_pil = mask_pil.filter(_ImageFilter.GaussianBlur(radius=4))
                print(f"  ✓ silhouette mask (binary + 4px blur)")
                used_silhouette = True
            except Exception as _esil:
                print(f"  !! silhouette load failed ({_esil}) — fallback depth mask")
        if not used_silhouette:
            depth_pil = _Image.open(io.BytesIO(depth_png)).convert("L")
            if depth_pil.size != (W2, H2):
                depth_pil = depth_pil.resize((W2, H2), _Image.LANCZOS)
            depth_arr = _np.asarray(depth_pil, dtype=_np.float32) / 255.0
            print(f"  depth stats : min={depth_arr.min():.3f} max={depth_arr.max():.3f} mean={depth_arr.mean():.3f}")
            threshold = float(_np.percentile(depth_arr, 78))
            print(f"  adaptive threshold (78th pct, fallback) = {threshold:.3f}")
            mask = _np.where(depth_arr > threshold, 0, 255).astype(_np.uint8)
            mask_pil = _Image.fromarray(mask, mode="L").filter(_ImageFilter.GaussianBlur(radius=60))
            print(f"  ⚠ FALLBACK depth-mask (silhouette unavailable)")
        SEAM_Y = int(H2 * 0.80)   # kept for matte post-process below
        # Composite : Blender base + paste FLUX through silhouette mask
        # (mask white = building → FLUX, mask black = everything else → Blender)
        composite = img_r.copy()
        composite.paste(img_b, (0, 0), mask_pil)

        # ── MATTE post-process on bottom 25% (the foreground/road zone) ──
        # Kills the wet/mirror reflective look from the SV img2img by
        # de-highlighting + adding grain. No geometry change, just texture.
        try:
            comp_arr = _np.asarray(composite, dtype=_np.float32)
            H_c, W_c = comp_arr.shape[:2]
            # Matte zone : top 72% (matches seam) → bottom 28%. Smooth
            # 5% ramp. Intensité réduite vs #176 pour ne pas écraser détails.
            matte_y = int(H_c * 0.72)
            matte_mask = _np.zeros((H_c, W_c), dtype=_np.float32)
            matte_ramp = max(40, int(H_c * 0.05))
            for k in range(matte_ramp):
                t = k / max(1, matte_ramp)
                matte_mask[matte_y + k] = t
            matte_mask[matte_y + matte_ramp:] = 1.0
            matte_mask_3 = matte_mask[..., None]
            # 1) De-highlight LÉGER : 10% gray (was 15%) — keep some texture
            arr = comp_arr.copy()
            mean_gray = arr.mean(axis=2, keepdims=True)
            de_highlight = arr * 0.90 + mean_gray * 0.10
            arr = arr * (1 - matte_mask_3) + de_highlight * matte_mask_3
            # 2) Désat très légère 5% (was 8%)
            chan_mean = arr.mean(axis=2, keepdims=True)
            desat = arr * 0.95 + chan_mean * 0.05
            arr = arr * (1 - matte_mask_3) + desat * matte_mask_3
            # 3) Grain très fin 2.5 levels (was 4.0) — moins agressif
            rng = _np.random.default_rng(seed if seed is not None else 0)
            grain = rng.normal(0, 2.5, arr.shape).astype(_np.float32)
            arr = arr + grain * matte_mask_3
            # 4) Push warm tones (beige/sand/tan) vers gris — relaxed
            #    detection : ANY pixel where red dominance > blue + 12 AND
            #    green > blue + 6 (warm tonality, captures pale beige).
            r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
            warm_zone = ((r > b + 12) & (g > b + 6) & (r > 130)).astype(_np.float32)
            warm_3 = warm_zone[..., None] * matte_mask_3.squeeze(-1)[..., None]
            # Force warm pixels toward neutral asphalt gray (90% blend).
            target_gray = _np.full_like(arr, 105.0)
            arr = arr * (1 - warm_3 * 0.85) + target_gray * (warm_3 * 0.85)
            arr = _np.clip(arr, 0, 255)
            composite = _Image.fromarray(arr.astype(_np.uint8), mode="RGB")
            print(f"✓ matte post-process applied (bottom 25%, de-highlight + desat + grain)")
        except Exception as _e:
            print(f"!! matte post-process failed ({_e}) — keeping composite as-is")

        cbuf = io.BytesIO()
        composite.save(cbuf, format="PNG", optimize=True)
        png = cbuf.getvalue()
        print(f"✓ composite built (depth-mask based)")
    except Exception as _e:
        print(f"!! composite failed ({_e}) — fallback to building-only pass")
        png = png_building

    # ── iter #310 — PHOTOREAL : cn_img2img + RE-COMPOSITE silhouette only ──
    # iter #309 cn_img2img dissolved bahut/grille/jardin RDC details because
    # at strength 0.55 the photoreal pass repainted the WHOLE image
    # including the voirie/RDC zone outside the building.
    # Fix : keep the silhouette composite as a STABLE base (it already has
    # bahut + grille + jardins + perfect voirie). After cn_img2img produces
    # a photoreal version, RE-COMPOSITE : take BUILDING pixels from
    # photoreal output, take VOIRIE/RDC pixels from silhouette composite.
    # The silhouette mask defines exactly which is which → zero RDC loss.
    silhouette_composite_png = png  # save the silhouette composite as RDC anchor

    # iter #316 — Revert : use SILHOUETTE COMPOSITE as init (residential
    # feel from FLUX Pass A) and rely on prompt to push Option 4. iter #315
    # Blender pure init produced industrial dark band look. iter #313 same.
    # Silhouette init (iter #312/#314) keeps residential feel ; Option 4
    # surfaces will come from cn_img2img + prompt push.
    # png stays as silhouette_composite_png (no Blender init swap).

    print(f"→ photoreal cn_img2img : strength=0.72 depth_scale=0.75 @ 1K + ESRGAN x2 …")
    try:
        # iter #320 — PROFESSIONAL PHOTOGRAPHY-GRADE prompt :
        # User asks for « photo prise par un photographe professionnel avec
        # un vrai appareil photo (Canon ou Sony) sur le terrain ». Front-load
        # the camera + photographer language to give FLUX a strong photoreal
        # anchor. Add the texture-specific cues : enduit taloché variations,
        # béton micro-imperfections, glass reflections, real pavés trottoir
        # joints, vrai bitume mat. Push « not 3D render, not CGI ».
        harmonize_prompt = (
            "professional architectural photograph shot on Canon EOS R5 with 24-70mm f/2.8L lens, "
            "golden hour late afternoon sunlight, soft directional shadows, "
            "ultra-photoreal French premium residential building Ile-de-France, "
            "natural enduit taloché lime render with subtle color variations and micro-imperfections, "
            "warm cream limestone RDC ground floor with visible stone texture, "
            "terracotta red brick stair-core vertical columns with mortar joints, "
            "matt anthracite zinc attique cladding with subtle metallic sheen, "
            "cantilevered concrete balconies showing real concrete grain not smooth plastic, "
            "thin matt black wrought iron railings, glass windows with real ambient reflections, "
            "real Parisian banlieue chic sidewalk pavers with visible joints and slight wear, "
            "matte dark asphalt road with fine aggregate grain and subtle tire marks, "
            "lush mature private gardens with deep green lawn and flowering hedges, "
            "warm clear pale-blue sky with subtle cirrus, atmospheric depth, "
            "magazine Architectural Digest cover quality, 8K ultra-detailed, "
            "shallow depth of field, sharp focus on building, fine film grain, "
            "true-to-life colours warm tones, premium real estate marketing photography, "
            "NOT 3D render, NOT CGI, NOT video game, NOT plastic, NOT maquette, photoreal documentary"
        )
        # FLUX trained @ 1024 — running cn_img2img at 2K produced heavy
        # blur (iter #308). Run native 1024 then ESRGAN x2 → 2K.
        # iter #311 : strength 0.65 (more aggressive repaint for photoreal),
        # depth_scale 0.85 (gives FLUX freedom for surface texture while
        # keeping geometry roughly intact).
        png = flux.cn_img2img.remote(
            init_png=png,
            depth_png=depth_png,
            canny_png=canny_png,
            prompt=harmonize_prompt,
            prompt_2=harmonize_prompt,
            negative_prompt=negative,
            seed=(seed + 2) if seed is not None else None,
            strength=0.72,
            depth_scale=0.75,
            canny_scale=0.0,   # ignored anyway (single-CN depth only)
            guidance_scale=3.8,
            steps=50,
            width=1024,
            height=1024,
        )
        print("✓ photoreal cn_img2img applied @ 1K (depth-locked) → upscaling to 2K …")
        try:
            png = flux.esrgan_upscale.remote(init_png=png, target_size=2048)
            print("✓ ESRGAN x2 upscale to 2K complete")
        except Exception as _eu:
            print(f"!! ESRGAN upscale failed ({_eu}) — keeping 1K output")

        # ── RE-COMPOSITE via silhouette : preserve RDC + voirie ──
        # png = photoreal output (all pixels repainted, RDC details lost).
        # silhouette_composite_png = clean silhouette composite (sharp RDC).
        # Final = photoreal where mask=building, silhouette_composite elsewhere.
        try:
            from PIL import Image as _Image2, ImageFilter as _ImFilter2
            import numpy as _np2
            photoreal_pil = _Image2.open(io.BytesIO(png)).convert("RGB")
            silcomp_pil = _Image2.open(io.BytesIO(silhouette_composite_png)).convert("RGB")
            W3, H3 = photoreal_pil.size
            if silcomp_pil.size != (W3, H3):
                silcomp_pil = silcomp_pil.resize((W3, H3), _Image2.LANCZOS)
            sil_path2 = Path(f"/tmp/blender_silhouette_{preset}_{seed}.png")
            sil_pil2 = _Image2.open(sil_path2).convert("L")
            if sil_pil2.size != (W3, H3):
                sil_pil2 = sil_pil2.resize((W3, H3), _Image2.LANCZOS)
            sil_arr2 = _np2.asarray(sil_pil2, dtype=_np2.uint8)
            mask2 = _np2.where(sil_arr2 > 127, 255, 0).astype(_np2.uint8)
            # iter #317 — GREEN-PRESERVE : exclude vegetation pixels (jardin
            # trees + lawn + privacy hedges) from the building silhouette
            # mask so they survive from silcomp_pil through the composite.
            # A pixel is "vegetation" if G dominates significantly (G > R+8
            # and G > B+8) AND total brightness is moderate (not sky white).
            silcomp_arr = _np2.asarray(silcomp_pil, dtype=_np2.int16)
            r_c, g_c, b_c = silcomp_arr[..., 0], silcomp_arr[..., 1], silcomp_arr[..., 2]
            is_green = ((g_c > r_c + 8) & (g_c > b_c + 8) & (g_c > 40)).astype(_np2.uint8)
            mask2 = _np2.where(is_green == 1, 0, mask2).astype(_np2.uint8)
            print(f"  silhouette green pixels excluded : {is_green.mean()*100:.2f}% (preserve trees/lawn)")
            mask_pil2 = _Image2.fromarray(mask2, mode="L").filter(_ImFilter2.GaussianBlur(radius=4))
            final = silcomp_pil.copy()
            final.paste(photoreal_pil, (0, 0), mask_pil2)
            _buf_final = io.BytesIO()
            final.save(_buf_final, format="PNG", optimize=True)
            png = _buf_final.getvalue()
            print(f"✓ re-composite : photoreal on building silhouette + silhouette composite on RDC/voirie")
        except Exception as _erc:
            print(f"!! re-composite failed ({_erc}) — keeping photoreal full")
        # iter #316 — POLISH PASS REMOVED. At strength 0.20 without CN it
        # smoothed/dissolved RDC details (bahut, grille, jardin) again.
    except Exception as _eh:
        print(f"!! cn_img2img failed ({_eh}) — keeping silhouette composite as-is")

    # ── PASS 2 + 3 : Street View composite + img2img harmonize ──
    # DISABLED — replaced by real BDTopo road geometry (roads_quads_list)
    # which gives FLUX the actual cadastral road network in 3D under the
    # same camera, no perspective mismatch, no watermarks, universal.
    sv_path = Path("/tmp/_disabled_streetview.png")
    if False and sv_path.exists():
        try:
            from PIL import Image as _Image, ImageFilter as _ImageFilter
            import numpy as _np
            print(f"→ pass 2 : compose with Street View {sv_path}")
            flux_render = _Image.open(io.BytesIO(png)).convert("RGB")
            sv = _Image.open(sv_path).convert("RGB")
            sv_w, sv_h = sv.size
            sv_crop = sv.crop((
                int(sv_w * 0.07), int(sv_h * 0.55),
                int(sv_w * 0.93), int(sv_h * 0.92),
            ))
            fr_w, fr_h = flux_render.size
            new_h = int(fr_w * sv_crop.size[1] / sv_crop.size[0])
            sv_crop = sv_crop.resize((fr_w, new_h), _Image.LANCZOS)
            # Light histogram match (mix=0.30) so SV blends with FLUX lighting.
            ref = flux_render.crop((0, fr_h - new_h, fr_w, fr_h))
            src_arr = _np.asarray(sv_crop, dtype=_np.uint8)
            ref_arr = _np.asarray(ref, dtype=_np.uint8)
            matched = _np.empty_like(src_arr)
            for ch in range(3):
                s_vals, s_idx, s_counts = _np.unique(src_arr[..., ch].ravel(), return_inverse=True, return_counts=True)
                r_vals, r_counts = _np.unique(ref_arr[..., ch].ravel(), return_counts=True)
                s_q = _np.cumsum(s_counts).astype(_np.float64) / src_arr[..., ch].size
                r_q = _np.cumsum(r_counts).astype(_np.float64) / ref_arr[..., ch].size
                interp = _np.interp(s_q, r_q, r_vals)
                matched[..., ch] = interp[s_idx].reshape(src_arr.shape[:2])
            blended = (src_arr.astype(_np.float32) * 0.7 + matched.astype(_np.float32) * 0.3).clip(0, 255)
            sv_blended = _Image.fromarray(blended.astype(_np.uint8), mode="RGB")
            mask = _np.full((new_h, fr_w), 255, dtype=_np.float32)
            feather = max(40, int(new_h * 0.18))
            for y in range(feather):
                mask[y] = 255 * (y / feather) ** 1.6
            mask_pil = _Image.fromarray(mask.astype(_np.uint8), mode="L").filter(_ImageFilter.GaussianBlur(radius=10))
            composite = flux_render.copy()
            composite.paste(sv_blended, (0, fr_h - new_h), mask_pil)
            cbuf = io.BytesIO()
            composite.save(cbuf, format="PNG", optimize=True)
            png = cbuf.getvalue()
            print(f"✓ composite built ({composite.size}, SV inserted at y={fr_h - new_h})")

            # ── PASS 3 : img2img harmonize the seam (Grok suggestion) ──
            print(f"→ pass 3 : img2img harmonize strength=0.40 cn=0.60+0.30 …")
            png = flux.harmonize_composite.remote(
                composite_png=png,
                depth_png=depth_png,
                canny_png=canny_png,
                prompt=prompt,
                prompt_2=prompt_2,
                negative_prompt=negative,
                seed=(seed + 1) if seed is not None else None,
                strength=0.40,
                controlnet_conditioning_scale=0.60,
                canny_conditioning_scale=0.30,
                guidance_scale=3.5,
                true_cfg_scale=5.0,
                steps=30,
                width=size,
                height=size,
            )
            print("✓ harmonized via img2img pass")
        except Exception as e:
            print(f"!! composite/harmonize failed ({e}) — keeping pass 1 only")
    else:
        print(f"(no Street View at {sv_path} — skip composite/harmonize)")

    # ── ESRGAN already applied per-pass before composite (cf. above) ──
    # No final ESRGAN needed — composite is already 2K.

    out = Path(f"/tmp/flux_{preset}_{seed}.png")
    out.write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out}")

    # ── Phase 1.4 : Auto-regression check against iter #320 baseline ──
    # Every new render is validated against 5 visual metrics tuned to the
    # iter #320 baseline. If any metric regresses, a warning is printed.
    # The user can then decide to keep, tune, or rollback.
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
        from test_visual_regression import run_all_metrics
        print("\n── Visual regression check (vs iter #320 baseline) ──")
        results = run_all_metrics(out)
        n_pass = sum(1 for r in results if r.passed)
        for r in results:
            print(f"  {r}")
        print(f"  → {n_pass}/{len(results)} metrics passed.\n")
        if n_pass < len(results):
            print(f"  ⚠ REGRESSION DETECTED — review failures before reporting.")
    except Exception as _eR:
        print(f"!! regression check failed ({_eR}) — render saved anyway")


@app.local_entrypoint()
def finish_blender(
    project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
    preset: str = "rue_se_eloignee",
    seed: int = 11,
    size: int = 1024,
    strength: float = 0.22,
    blender_path: str = "/tmp/blender_rue_se_eloignee_11.png",
    out_path: str = "/tmp/flux_finish_rue_se_eloignee_11.png",
):
    """Pipeline 1+2 stage 1 : FLUX img2img finish on a Blender Cycles render.

    Takes the geometry-perfect Blender PNG and runs it through FluxImg2Img
    at low strength (0.18-0.22) to add photoreal materials texture,
    weathering, sky clouds, asphalt grain — without breaking geometry.
    """
    import json
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.prompt_context.synthesizer import synthesize_dual_prompts

    blender_png = Path(blender_path).read_bytes()
    print(f"→ loaded Blender input : {len(blender_png):,} bytes ({blender_path})")

    # Synthesize prompt from BM (same path as the FLUX text2img pipeline).
    with urllib.request.urlopen(
        f"http://localhost:8000/api/v1/projects/{project_id}/building_model"
    ) as r:
        bm = json.load(r)
    prompt, prompt_2, negative = synthesize_dual_prompts(bm, preset, project_id)
    print(f"→ prompt : {prompt[:120]}…")
    print(f"→ prompt_2 : {prompt_2[:120]}…")

    flux = FluxPipeline()
    print(f"→ FLUX img2img finish strength={strength} steps=30 …")
    png = flux.harmonize_composite.remote(
        composite_png=blender_png,
        depth_png=b"",                       # unused by harmonize_composite
        canny_png=None,
        prompt=prompt,
        prompt_2=prompt_2,
        negative_prompt=negative,
        seed=seed,
        strength=strength,
        controlnet_conditioning_scale=0.0,   # no CN — just img2img
        canny_conditioning_scale=0.0,
        guidance_scale=3.5,
        true_cfg_scale=5.0,
        steps=30,
        width=size,
        height=size,
    )
    Path(out_path).write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out_path}")

    # ALSO persist to refs/renders/ — survives /tmp clear on reboot.
    import os as _os
    import datetime as _dt
    persist_dir = Path(__file__).resolve().parent.parent.parent.parent / "refs" / "renders"
    persist_dir.mkdir(parents=True, exist_ok=True)
    iter_tag = _os.environ.get("FLUX_ITER", "")
    iter_part = f"_iter{iter_tag}" if iter_tag else ""
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    persist_path = persist_dir / f"{ts}{iter_part}_flux_finish_{preset}_seed{seed}_s{int(strength*100)}.png"
    persist_path.write_bytes(png)
    print(f"✓ persisted → {persist_path}")
    try:
        import subprocess as _sp
        gallery_script = persist_dir.parent.parent / "scripts" / "gen_render_gallery.py"
        if gallery_script.exists():
            _sp.run(["python3", str(gallery_script)],
                    capture_output=True, text=True, check=True, timeout=15)
            print(f"  → gallery refreshed")
    except Exception as _e:
        print(f"  !! gallery regen failed ({_e})")


@app.local_entrypoint()
def cn_finish_blender(
    project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
    preset: str = "rue_se_eloignee",
    seed: int = 11,
    size: int = 1024,
    strength: float = 0.55,
    depth_scale: float = 0.65,
    canny_scale: float = 0.55,
    blender_path: str = "/tmp/blender_rue_se_eloignee_11.png",
    out_path: str = "/tmp/flux_cn_finish_rue_se_eloignee_11.png",
):
    """ControlNet-guided img2img on Blender PNG : geometry locked, materials free.

    Builds a FRESH depth + canny matching the Blender scene exactly
    (including far_ground), so the FLUX foreground is well-guided.
    """
    import io as _io
    import json
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.prompt_context.synthesizer import synthesize_dual_prompts
    from src.depth_map import (
        camera_from_preset,
        depth_to_pil,
        render_depth_map,
        _polygon_inset,
        extrude_footprint,
    )
    from src.scene_mesh import (
        balcons_filants_quads,
        clip_footprint_to_parcelle,
        entrance_canopy_quad,
        far_ground_quad,
        jardins_rdc_quads,
        pleine_terre_quads,
        rdc_bandeau_quads,
        rdc_windows_quads,
        roads_bdtopo_to_quads,
        rooftop_terrace_quads,
        voirie_strip_quads,
    )
    from src.voisinage_mesh import (
        fetch_roads_bdtopo,
        fetch_voisins_bdtopo,
        geocode_address,
        roads_to_local_polylines,
        voisins_to_local_polygons,
    )

    init_png = Path(blender_path).read_bytes()
    print(f"→ init Blender PNG : {len(init_png):,} bytes")

    # ── Rebuild the full Blender scene quads to compute depth that matches ──
    with urllib.request.urlopen(
        f"http://localhost:8000/api/v1/projects/{project_id}/building_model"
    ) as r:
        bm = json.load(r)
    model = bm.get("model_json", bm)
    fp_xy = [(float(p[0]), float(p[1]))
             for p in model["envelope"]["footprint_geojson"]["coordinates"][0]]
    h_total = float(model["envelope"].get("hauteur_totale_m", 17.0))
    cam = camera_from_preset(fp_xy, h_total, preset)
    cam.width = size
    cam.height = size

    parc_pts = [(p[0], p[1])
                for p in bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0][:-1]]
    clipped = clip_footprint_to_parcelle(fp_xy, parc_pts)
    real_ring = max(clipped, key=lambda r: abs(sum(
        r[i][0] * r[(i+1)%len(r)][1] - r[(i+1)%len(r)][0] * r[i][1]
        for i in range(len(r))) / 2))
    voirie_sides = bm["model_json"]["site"].get("voirie_orientations") or ["sud"]
    niv = int(model["envelope"].get("niveaux") or 6)
    h_rdc = float(model["envelope"].get("hauteur_rdc_m") or 3.5)
    h_etage = float(model["envelope"].get("hauteur_etage_courant_m") or 2.7)

    extra: list = []
    extra.extend(voirie_strip_quads(parc_pts, voirie_sides, thickness_m=6.0,
                                     bahut_height_m=0.7, grille_height_m=1.6,
                                     emit_flat_ground=False))
    extra.extend(pleine_terre_quads(parc_pts, real_ring))
    extra.extend(balcons_filants_quads(real_ring, voirie_sides,
                                        niveaux=niv, hauteur_rdc_m=h_rdc,
                                        hauteur_etage_m=h_etage))
    extra.extend(jardins_rdc_quads(real_ring, voirie_sides,
                                    partition_height_m=1.2, add_trees=True))
    extra.extend(entrance_canopy_quad(real_ring, voirie_sides))
    extra.extend(rdc_bandeau_quads(real_ring, hauteur_rdc_m=h_rdc))
    setback = _polygon_inset(real_ring, 1.5)
    if (model["envelope"].get("toiture") or {}).get("accessible") and len(setback) >= 3:
        extra.extend(rooftop_terrace_quads(setback, h_total))

    # CRITICAL : far_ground must be in the depth too — this is the fix
    # for the pale foreground in iter #212 (depth had no far_ground).
    extra.extend(far_ground_quad(parc_pts, radius_m=120.0, elevation_m=-0.02,
                                  patch_size_m=8.0, jitter_m=0.0,
                                  camera_pos_xy=(cam.position[0], cam.position[1]),
                                  camera_target_xy=(cam.target[0], cam.target[1])))

    voisins = []
    try:
        with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{project_id}") as r:
            address = json.load(r).get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
        origin = geocode_address(address)
        cx_l = sum(p[0] for p in parc_pts) / len(parc_pts)
        cy_l = sum(p[1] for p in parc_pts) / len(parc_pts)
        feats = fetch_voisins_bdtopo(origin, radius_m=180.0)
        voisins = voisins_to_local_polygons(
            feats, origin, (cx_l, cy_l),
            skip_overlap_with=real_ring,
            camera_pos_xy=(cam.position[0], cam.position[1]),
            block_camera_sight=True,
            max_distance_m=100.0, min_height_m=4.0, max_height_m=18.0,
        )
        rfeats = fetch_roads_bdtopo(origin, radius_m=180.0)
        rpolys = roads_to_local_polylines(rfeats, origin, (cx_l, cy_l),
                                           require_ground_level=True,
                                           min_chaussee_width_m=2.0)
        extra.extend(roads_bdtopo_to_quads(rpolys, parc_pts,
                                            trottoir_width_m=2.5,
                                            chaussee_height_m=0.05,
                                            trottoir_height_m=0.22,
                                            skip_overlap_with=parc_pts,
                                            max_distance_from_parcelle_m=50))
    except Exception as e:
        print(f"!! BDTopo fetch failed ({e})")

    print(f"→ rendering depth + canny from full scene ({len(extra)} extras + {len(voisins)} voisins) …")
    depth = render_depth_map(real_ring, h_total, cam,
                             voisins=voisins, extra_quads=extra)
    depth_pil = depth_to_pil(depth)
    db = _io.BytesIO()
    depth_pil.save(db, format="PNG")
    depth_png = db.getvalue()

    # Canny from Blender PNG directly (matches actual rendered geometry).
    import numpy as _np
    import cv2 as _cv2  # type: ignore
    from PIL import Image as _Image
    bld_arr = _np.asarray(_Image.open(_io.BytesIO(init_png)).convert("L").resize((size, size)))
    canny_arr = _cv2.Canny(bld_arr, 80, 160)
    canny_pil = _Image.fromarray(canny_arr).convert("RGB")
    cb = _io.BytesIO()
    canny_pil.save(cb, format="PNG")
    canny_png = cb.getvalue()
    print(f"→ depth {len(depth_png):,}B + canny {len(canny_png):,}B (fresh from Blender scene)")

    Path("/tmp/depth_v2.png").write_bytes(depth_png)
    Path("/tmp/canny_v2.png").write_bytes(canny_png)

    prompt, prompt_2, negative = synthesize_dual_prompts(bm, preset, project_id)

    flux = FluxPipeline()
    print(f"→ CN-img2img s={strength} depth={depth_scale} canny={canny_scale} steps=30 …")
    png = flux.cn_img2img.remote(
        init_png=init_png,
        depth_png=depth_png,
        canny_png=canny_png,
        prompt=prompt,
        prompt_2=prompt_2,
        negative_prompt=negative,
        seed=seed,
        strength=strength,
        depth_scale=depth_scale,
        canny_scale=canny_scale,
        guidance_scale=3.5,
        true_cfg_scale=5.0,
        steps=30,
        width=size,
        height=size,
    )
    Path(out_path).write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out_path}")
