from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MailAddress:
    email: str
    name: str | None = None

    def __post_init__(self) -> None:
        email = self.email.strip()
        if not email or "@" not in email:
            raise ValueError(f"invalid email address: {self.email!r}")
        object.__setattr__(self, "email", email)
        if self.name is not None:
            name = self.name.strip()
            object.__setattr__(self, "name", name or None)

    @classmethod
    def coerce(cls, value: MailAddress | str) -> MailAddress:
        if isinstance(value, MailAddress):
            return value
        return cls(email=value)


AddressLike = MailAddress | str


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    to: Sequence[AddressLike]
    subject: str
    body: str
    html: bool = True
    cc: Sequence[AddressLike] = field(default_factory=tuple)
    bcc: Sequence[AddressLike] = field(default_factory=tuple)
    sender_name: str | None = None
    priority: int = 3

    def __post_init__(self) -> None:
        if not self.to and not self.cc and not self.bcc:
            raise ValueError("at least one recipient is required")
        if not 1 <= self.priority <= 5:
            raise ValueError("priority must be between 1 and 5")


@dataclass(frozen=True, slots=True)
class MailPage:
    items: tuple[Any, ...]
    raw: Mapping[str, Any]
    offset: int
    limit: int

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.items)


@dataclass(frozen=True, slots=True)
class SendResult:
    status_code: int
    data: Mapping[str, Any]
    response_text: str = ""

    @property
    def successful(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def server_reference(self) -> str | None:
        value = self.data.get("data")
        return None if value is None else str(value)
