from uuid import uuid4

from core.flags import FeatureFlag, is_enabled


def test_flag_disabled_by_default() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[],
    )
    assert is_enabled(flag, user_id=None) is False


def test_flag_enabled_globally_returns_true_for_any_user() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[],
    )
    assert is_enabled(flag, user_id=None) is True
    assert is_enabled(flag, user_id=uuid4()) is True


def test_flag_enabled_for_specific_user() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[user_id],
    )
    assert is_enabled(flag, user_id=user_id) is True
    assert is_enabled(flag, user_id=other_user_id) is False
    assert is_enabled(flag, user_id=None) is False


def test_flag_global_wins_over_user_list() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[uuid4()],
    )
    assert is_enabled(flag, user_id=None) is True
