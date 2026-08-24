from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ..exceptions import ConfigurationError

DEFAULT_IMAP_PORT = 993
DEFAULT_IMAP_HOST_PREFIX = "imap."


@dataclass(frozen=True, slots=True)
class IMAPConfig:
    """Connection settings for the IMAP backend.

    ``host`` defaults to the API host with an ``imap.`` prefix, which is how
    Open-Xchange deployments usually expose their mail store.
    """

    host: str | None = None
    port: int = DEFAULT_IMAP_PORT
    use_ssl: bool = True
    verify_tls: bool = True
    timeout: float = 20.0
    idle_refresh: float = 540.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.port < 65536:
            raise ConfigurationError("imap port must be between 1 and 65535")
        if self.timeout <= 0:
            raise ConfigurationError("imap timeout must be greater than zero")
        if self.idle_refresh <= 0:
            raise ConfigurationError("imap idle_refresh must be greater than zero")
        if self.host is not None:
            host = self.host.strip()
            if not host:
                raise ConfigurationError("imap host cannot be empty")
            object.__setattr__(self, "host", host)

    def resolve_host(self, base_url: str) -> str:
        """Return the configured host, or derive one from the API base URL."""

        if self.host:
            return self.host
        netloc = urlsplit(base_url).netloc.split("@")[-1].split(":")[0]
        if not netloc:
            raise ConfigurationError("cannot derive an imap host from base_url")
        if netloc.startswith(("imap.", "mail.")):
            return netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return f"{DEFAULT_IMAP_HOST_PREFIX}{netloc}"
