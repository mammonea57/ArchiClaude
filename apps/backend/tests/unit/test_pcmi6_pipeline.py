from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.rendering.pcmi6_pipeline import (
    build_prompt,
    generate_pcmi6_render,
)


def test_build_prompt_single_material():
    materials = {"facade": "enduit_blanc_lisse"}
    prompt = build_prompt(materials_config=materials, camera_config={})
    assert "white smooth stucco walls" in prompt
    assert "modern residential building" in prompt
    assert "photorealistic" in prompt or "architectural photography" in prompt


def test_build_prompt_multiple_materials():
    materials = {"facade": "enduit_blanc_lisse", "toiture": "tuile_plate_idf_rouge"}
    prompt = build_prompt(materials_config=materials, camera_config={})
    assert "white smooth stucco walls" in prompt
    # Tuile: we expect the red tile prompt to be included
    assert "tile" in prompt.lower() or "tuile" in prompt.lower()


def test_build_prompt_unknown_material_skipped():
    materials = {"facade": "inexistant_material"}
    prompt = build_prompt(materials_config=materials, camera_config={})
    # Should still produce a valid prompt
    assert "modern residential building" in prompt


@pytest.mark.asyncio
async def test_generate_render_success():
    """End-to-end mock: upload -> render -> poll -> download -> QC."""
    provider = MagicMock()
    provider.upload_image = AsyncMock(side_effect=["photo_id", "mask_id", "normal_id", "depth_id"])
    provider.start_render = AsyncMock(return_value="render_job_1")
    provider.get_render_status = AsyncMock(return_value={
        "status": "done",
        "result_url": "https://cdn.example.com/result.jpg",
    })

    # Mock download
    with (
        patch(
            "core.rendering.pcmi6_pipeline._download_bytes",
            new_callable=AsyncMock,
            return_value=b"\x89PNG" + b"\x00" * 100,
        ),
        patch("core.rendering.pcmi6_pipeline.compute_mask_iou", return_value=0.9),
    ):
        result = await generate_pcmi6_render(
            photo_bytes=b"photo",
            mask_bytes=b"mask",
            normal_bytes=b"normal",
            depth_bytes=b"depth",
            materials_config={"facade": "enduit_blanc_lisse"},
            camera_config={"lat": 48.85, "lng": 2.35, "heading": 90},
            provider=provider,
            seed=42,
        )

    assert result["render_bytes"] == b"\x89PNG" + b"\x00" * 100
    assert result["iou_score"] == 0.9
    assert result["seed"] == 42
    assert "prompt" in result
