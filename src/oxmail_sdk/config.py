from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ._version import __version__
from .exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class TimeoutConfig:
    """Connect/read timeout configuration passed to requests."""

    connect: float = 10.0
    read: float = 30.0

    def __post_init__(self) -> None:
        if self.connect <= 0 or self.read <= 0:
            raise ConfigurationError("timeout values must be greater than zero")

    @property
    def requests_value(self) -> tuple[float, float]:
        return self.connect, self.read


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry policy for safe HTTP methods only."""

    total: int = 3
    backoff_factor: float = 0.5
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504)

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ConfigurationError("retry total cannot be negative")
        if self.backoff_factor < 0:
            raise ConfigurationError("retry backoff_factor cannot be negative")


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Immutable SDK configuration."""

    base_url: str = "https://ultamail.com/appsuite/api"
    locale: str = "en_US"
    client_name: str = "open-xchange-appsuite"
    client_version: str = "8.51.3"
    user_agent: str = f"oxmail-sdk/{__version__}"
    verify_tls: bool | str = True
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    retries: RetryConfig = field(default_factory=RetryConfig)
    pool_connections: int = 10
    pool_maxsize: int = 10

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/")
        parts = urlsplit(normalized)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ConfigurationError("base_url must be an absolute http(s) URL")
        if not self.locale:
            raise ConfigurationError("locale cannot be empty")
        if self.pool_connections <= 0 or self.pool_maxsize <= 0:
            raise ConfigurationError("connection pool sizes must be greater than zero")
        object.__setattr__(self, "base_url", normalized)

    @property
    def origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def referer(self) -> str:
        return f"{self.origin}/appsuite/"
