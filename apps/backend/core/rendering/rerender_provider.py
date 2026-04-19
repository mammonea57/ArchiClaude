"""ReRender AI Enterprise API implementation of RenderProvider."""
from __future__ import annotations

import logging
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.rerenderai.com/api/enterprise"


class ReRenderProvider:
    """Implementation of RenderProvider using ReRender AI Enterprise API.

    Graceful degradation: returns sentinel values when no API key is configured.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._timeout = httpx.Timeout(60.0)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def upload_image(
        self,
        *,
        image_bytes: bytes,
        name: str,
        content_type: str = "image/png",
    ) -> str:
        if not self._api_key:
            raise RuntimeError("ReRender API key not configured")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            files = {"file": (name, image_bytes, content_type)}
            resp = await client.post(
                f"{BASE_URL}/upload",
                headers=self._headers(),
                files=files,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    async def start_render(
        self,
        *,
        base_image_id: str,
        mask_image_id: str | None = None,
        normal_image_id: str | None = None,
        depth_image_id: str | None = None,
        prompt: str,
        negative_prompt: str = "cartoon, sketch, blurry, low quality",
        creativity: float = 0.3,
        seed: int | None = None,
        style: str = "photorealistic_architectural",
        resolution: Literal["1024", "1536"] = "1024",
    ) -> str:
        if not self._api_key:
            raise RuntimeError("ReRender API key not configured")

        body: dict = {
            "base_image_id": base_image_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "creativity": creativity,
            "style": style,
            "resolution": resolution,
        }
        if mask_image_id:
            body["mask_image_id"] = mask_image_id
        if normal_image_id:
            body["normal_image_id"] = normal_image_id
        if depth_image_id:
            body["depth_image_id"] = depth_image_id
        if seed is not None:
            body["seed"] = seed

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{BASE_URL}/render",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    async def get_render_status(self, render_job_id: str) -> dict:
        if not self._api_key:
            return {"status": "failed", "error": "no api key"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{BASE_URL}/render/{render_job_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_account_credits(self) -> int:
        if not self._api_key:
            return -2  # sentinel: not configured

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.get(
                    f"{BASE_URL}/status",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return int(resp.json().get("credits", 0))
            except Exception:
                logger.warning("Failed to fetch ReRender credits")
                return -3  # sentinel: error
