from uuid import UUID, uuid4

import pytest

from core.flags import FeatureFlag, is_enabled


@pytest.mark.asyncio
async def test_flag_disabled_by_default() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[],
    )
    assert await is_enabled(flag, user_id=None) is False


@pytest.mark.asyncio
async def test_flag_enabled_globally_returns_true_for_any_user() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[],
    )
    assert await is_enabled(flag, user_id=None) is True
    assert await is_enabled(flag, user_id=uuid4()) is True


@pytest.mark.asyncio
async def test_flag_enabled_for_specific_user() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[user_id],
    )
    assert await is_enabled(flag, user_id=user_id) is True
    assert await is_enabled(flag, user_id=other_user_id) is False
    assert await is_enabled(flag, user_id=None) is False


@pytest.mark.asyncio
async def test_flag_global_wins_over_user_list() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[uuid4()],
    )
    assert await is_enabled(flag, user_id=None) is True
