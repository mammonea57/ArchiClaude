"""PCMI6 render pipeline — orchestrates upload, render, poll, QC, retry."""
from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from core.rendering.materials_catalog import get_material
from core.rendering.provider import RenderProvider
from core.rendering.quality_check import compute_mask_iou

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 30  # 60s total
IOU_THRESHOLD = 0.8
MAX_RETRY_ATTEMPTS = 3


def build_prompt(
    *,
    materials_config: dict[str, str],
    camera_config: dict,
) -> str:
    """Build ReRender prompt from materials config."""
    parts = ["modern residential building"]

    for surface, material_id in materials_config.items():
        mat = get_material(material_id)
        if mat is None:
            continue
        parts.append(f"{surface}: {mat.prompt_en}")

    parts.append("natural daylight, soft shadows")
    parts.append("realistic urban context, detailed, high quality, architectural photography")

    return ", ".join(parts)


async def _download_bytes(url: str) -> bytes:
    """Download bytes from a URL."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _poll_render(provider: RenderProvider, job_id: str) -> dict:
    """Poll render status until done or failed (max 60s)."""
    for _ in range(MAX_POLL_ATTEMPTS):
        status = await provider.get_render_status(job_id)
        if status.get("status") == "done":
            return status
        if status.get("status") == "failed":
            raise RuntimeError(f"Render failed: {status.get('error')}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Render timeout after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s")


async def _generate_once(
    *,
    photo_id: str,
    mask_id: str,
    normal_id: str,
    depth_id: str,
    prompt: str,
    seed: int,
    provider: RenderProvider,
) -> dict:
    """One attempt: start render + poll + download."""
    job_id = await provider.start_render(
        base_image_id=photo_id,
        mask_image_id=mask_id,
        normal_image_id=normal_id,
        depth_image_id=depth_id,
        prompt=prompt,
        seed=seed,
    )

    status = await _poll_render(provider, job_id)
    result_url = status["result_url"]
    render_bytes = await _download_bytes(result_url)

    return {
        "render_bytes": render_bytes,
        "result_url": result_url,
        "job_id": job_id,
        "seed": seed,
    }


async def generate_pcmi6_render(
    *,
    photo_bytes: bytes,
    mask_bytes: bytes,
    normal_bytes: bytes,
    depth_bytes: bytes,
    materials_config: dict[str, str],
    camera_config: dict,
    provider: RenderProvider,
    seed: int | None = None,
) -> dict:
    """Full PCMI6 render pipeline.

    Returns dict with: render_bytes, iou_score, seed, prompt, result_url,
    attempts, duration_ms.
    """
    t0 = time.perf_counter()

    # 1. Upload all 4 layers
    photo_id = await provider.upload_image(image_bytes=photo_bytes, name="base.png")
    mask_id = await provider.upload_image(image_bytes=mask_bytes, name="mask.png")
    normal_id = await provider.upload_image(image_bytes=normal_bytes, name="normal.png")
    depth_id = await provider.upload_image(image_bytes=depth_bytes, name="depth.png")

    # 2. Build prompt
    prompt = build_prompt(materials_config=materials_config, camera_config=camera_config)

    # 3. Render with retry on low IoU
    best_result = None
    best_iou = -1.0
    attempts = 0

    for attempt in range(MAX_RETRY_ATTEMPTS):
        attempts += 1
        current_seed = seed if (seed is not None and attempt == 0) else random.randint(1, 999999)

        result = await _generate_once(
            photo_id=photo_id,
            mask_id=mask_id,
            normal_id=normal_id,
            depth_id=depth_id,
            prompt=prompt,
            seed=current_seed,
            provider=provider,
        )
        iou = compute_mask_iou(rendered_bytes=result["render_bytes"], mask_bytes=mask_bytes)

        if iou >= IOU_THRESHOLD:
            best_result = result
            best_iou = iou
            break

        if iou > best_iou:
            best_iou = iou
            best_result = result

        logger.info(f"Attempt {attempt + 1} IoU={iou:.2f} < {IOU_THRESHOLD}, retrying...")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    assert best_result is not None  # always set after at least 1 attempt
    return {
        "render_bytes": best_result["render_bytes"],
        "result_url": best_result["result_url"],
        "job_id": best_result["job_id"],
        "iou_score": best_iou,
        "seed": best_result["seed"],
        "prompt": prompt,
        "attempts": attempts,
        "duration_ms": elapsed_ms,
    }
