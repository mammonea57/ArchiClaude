"""RenderProvider Protocol — abstraction for AI rendering backends.

Implementations: ReRenderProvider (v1), InternalSDXLProvider (post-v1).
The rest of the codebase depends on this Protocol, not on any specific provider.
"""
from __future__ import annotations

from typing import Literal, Protocol


class RenderProvider(Protocol):
    """Interface for AI rendering providers."""

    async def upload_image(
        self,
        *,
        image_bytes: bytes,
        name: str,
        content_type: str = "image/png",
    ) -> str:
        """Upload an image to the provider. Returns provider-side image_id."""
        ...

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
        """Start a render job. Returns provider render_job_id."""
        ...

    async def get_render_status(self, render_job_id: str) -> dict:
        """Returns {status: 'pending'|'done'|'failed', result_url?: str, error?: str}."""
        ...

    async def get_account_credits(self) -> int:
        """Return remaining credits (or -1 for unlimited)."""
        ...
