from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        username = self.username.strip()
        if not username:
            raise ValueError("username cannot be empty")
        if not self.password:
            raise ValueError("password cannot be empty")
        object.__setattr__(self, "username", username)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session: str = field(repr=False)
    user: str | None = None
    user_id: int | None = None
    context_id: int | None = None
    locale: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SessionInfo:
        token = payload.get("session")
        if not isinstance(token, str) or not token:
            raise ValueError("login response does not contain a valid session token")
        return cls(
            session=token,
            user=_str_or_none(payload.get("user")),
            user_id=_int_or_none(payload.get("user_id")),
            context_id=_int_or_none(payload.get("context_id")),
            locale=_str_or_none(payload.get("locale")),
        )


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
