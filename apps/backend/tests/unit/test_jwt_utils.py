import pytest
import time
from uuid import uuid4
from core.auth.jwt_utils import emit_jwt, decode_jwt, JWTError


def test_emit_and_decode_jwt():
    uid = uuid4()
    wid = uuid4()
    token = emit_jwt(user_id=uid, email="u@test.fr", workspace_id=wid, secret="secret1")
    payload = decode_jwt(token, secret="secret1")
    assert payload["sub"] == str(uid)
    assert payload["email"] == "u@test.fr"
    assert payload["workspace_id"] == str(wid)


def test_decode_wrong_secret_fails():
    token = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="good")
    with pytest.raises(JWTError):
        decode_jwt(token, secret="bad")


def test_decode_expired_fails():
    token = emit_jwt(
        user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(),
        secret="s", expires_in_seconds=-1,
    )
    with pytest.raises(JWTError):
        decode_jwt(token, secret="s")


def test_default_expiry_7_days():
    token = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="s")
    payload = decode_jwt(token, secret="s")
    now = int(time.time())
    assert payload["exp"] - now > 6 * 86400
    assert payload["exp"] - now <= 7 * 86400 + 10


def test_needs_refresh_when_less_than_24h():
    from core.auth.jwt_utils import needs_refresh
    token = emit_jwt(
        user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(),
        secret="s", expires_in_seconds=3600,
    )
    assert needs_refresh(token, secret="s") is True

    token2 = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="s")
    assert needs_refresh(token2, secret="s") is False
