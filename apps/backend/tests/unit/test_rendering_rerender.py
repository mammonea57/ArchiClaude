import pytest
from pytest_httpx import HTTPXMock

from core.rendering.rerender_provider import ReRenderProvider


@pytest.mark.asyncio
async def test_upload_image(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("RERENDER_API_KEY", "test-key")
    httpx_mock.add_response(
        url="https://api.rerenderai.com/api/enterprise/upload",
        method="POST",
        json={"id": "img_abc123"},
    )
    provider = ReRenderProvider(api_key="test-key")
    image_id = await provider.upload_image(image_bytes=b"fake png", name="test.png")
    assert image_id == "img_abc123"


@pytest.mark.asyncio
async def test_start_render(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("RERENDER_API_KEY", "test-key")
    httpx_mock.add_response(
        url="https://api.rerenderai.com/api/enterprise/render",
        method="POST",
        json={"id": "render_xyz"},
    )
    provider = ReRenderProvider(api_key="test-key")
    job_id = await provider.start_render(
        base_image_id="base1",
        mask_image_id="mask1",
        normal_image_id="normal1",
        depth_image_id="depth1",
        prompt="white building",
        seed=42,
    )
    assert job_id == "render_xyz"


@pytest.mark.asyncio
async def test_get_render_status_done(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("RERENDER_API_KEY", "test-key")
    httpx_mock.add_response(
        url="https://api.rerenderai.com/api/enterprise/render/xyz",
        method="GET",
        json={"status": "done", "result_url": "https://cdn.rerender.com/r.jpg"},
    )
    provider = ReRenderProvider(api_key="test-key")
    status = await provider.get_render_status("xyz")
    assert status["status"] == "done"
    assert status["result_url"] == "https://cdn.rerender.com/r.jpg"


@pytest.mark.asyncio
async def test_get_render_status_pending(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("RERENDER_API_KEY", "test-key")
    httpx_mock.add_response(
        url="https://api.rerenderai.com/api/enterprise/render/xyz",
        method="GET",
        json={"status": "pending"},
    )
    provider = ReRenderProvider(api_key="test-key")
    status = await provider.get_render_status("xyz")
    assert status["status"] == "pending"


@pytest.mark.asyncio
async def test_get_credits_unlimited(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("RERENDER_API_KEY", "test-key")
    httpx_mock.add_response(
        url="https://api.rerenderai.com/api/enterprise/status",
        method="GET",
        json={"credits": -1},
    )
    provider = ReRenderProvider(api_key="test-key")
    remaining = await provider.get_account_credits()
    assert remaining == -1


@pytest.mark.asyncio
async def test_no_api_key_returns_none_credits(monkeypatch):
    monkeypatch.delenv("RERENDER_API_KEY", raising=False)
    provider = ReRenderProvider(api_key="")
    # Implementation should return -2 (or similar sentinel) when no key
    remaining = await provider.get_account_credits()
    assert remaining < 0
