from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class OXMailError(Exception):
    """Base exception for all SDK-defined failures."""


class ConfigurationError(OXMailError):
    """Raised when client configuration is invalid."""


class ClientClosedError(OXMailError):
    """Raised when an operation is attempted after the client is closed."""


class NotAuthenticatedError(OXMailError):
    """Raised when an authenticated operation is attempted before login."""


class AuthenticationError(OXMailError):
    """Raised when Open-Xchange rejects authentication."""


class TransportError(OXMailError):
    """Raised for DNS, connection, TLS, timeout, and other transport failures."""


@dataclass(slots=True)
class HTTPError(OXMailError):
    status_code: int
    method: str
    url: str
    response_preview: str = ""

    def __str__(self) -> str:
        suffix = f": {self.response_preview}" if self.response_preview else ""
        return f"HTTP {self.status_code} for {self.method} {self.url}{suffix}"


@dataclass(slots=True)
class InvalidResponseError(OXMailError):
    message: str
    response_preview: str = ""

    def __str__(self) -> str:
        suffix = f": {self.response_preview}" if self.response_preview else ""
        return f"{self.message}{suffix}"


@dataclass(slots=True)
class APIError(OXMailError):
    message: str
    error_id: str | None = None
    code: str | None = None
    category: str | None = None
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> APIError:
        message = str(
            payload.get("error")
            or payload.get("error_desc")
            or "Open-Xchange API error"
        )
        return cls(
            message=message,
            error_id=_optional_str(payload.get("error_id")),
            code=_optional_str(payload.get("code")),
            category=_optional_str(payload.get("category")),
            raw=dict(payload),
        )

    def __str__(self) -> str:
        details: list[str] = []
        if self.error_id:
            details.append(f"error_id={self.error_id}")
        if self.code:
            details.append(f"code={self.code}")
        if self.category:
            details.append(f"category={self.category}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{self.message}{suffix}"


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
