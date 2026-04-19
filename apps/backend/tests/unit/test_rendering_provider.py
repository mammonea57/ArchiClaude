"""Verify ReRenderProvider satisfies RenderProvider Protocol."""
from core.rendering.provider import RenderProvider
from core.rendering.rerender_provider import ReRenderProvider


def test_rerender_is_render_provider():
    provider: RenderProvider = ReRenderProvider(api_key="test")
    # If this type assignment passes type checking at runtime,
    # ReRender implements the Protocol.
    assert hasattr(provider, "upload_image")
    assert hasattr(provider, "start_render")
    assert hasattr(provider, "get_render_status")
    assert hasattr(provider, "get_account_credits")
