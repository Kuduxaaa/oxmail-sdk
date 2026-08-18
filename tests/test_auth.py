from __future__ import annotations

from unittest.mock import Mock

from conftest import make_auth

from oxmail_sdk.auth import Credentials


def test_credentials_hide_password_from_repr() -> None:
    credentials = Credentials("user@example.com", "super-secret")
    assert "super-secret" not in repr(credentials)


def test_login_without_guard() -> None:
    transport, auth = make_auth()
    try:
        transport.request_json = Mock(  # type: ignore[method-assign]
            return_value={
                "session": "token",
                "user": "user@example.com",
                "user_id": 1,
                "context_id": 2,
                "locale": "en_US",
            }
        )
        info = auth.login(oxguard=False)
        assert info.session == "token"
        assert auth.token == "token"
        assert "token" not in repr(info)
    finally:
        transport.close()
