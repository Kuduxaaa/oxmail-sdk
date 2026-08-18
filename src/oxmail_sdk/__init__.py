from ._version import __version__
from .auth import Credentials, SessionInfo
from .client import OXMailClient
from .config import ClientConfig, RetryConfig, TimeoutConfig
from .exceptions import (
    APIError,
    AuthenticationError,
    ClientClosedError,
    ConfigurationError,
    HTTPError,
    InvalidResponseError,
    NotAuthenticatedError,
    OXMailError,
    TransportError,
)
from .mail import Attachment, MailAddress, MailPage, OutgoingMessage, SendResult

__all__ = [
    "APIError",
    "Attachment",
    "AuthenticationError",
    "ClientClosedError",
    "ClientConfig",
    "ConfigurationError",
    "Credentials",
    "HTTPError",
    "InvalidResponseError",
    "MailAddress",
    "MailPage",
    "NotAuthenticatedError",
    "OutgoingMessage",
    "OXMailClient",
    "OXMailError",
    "RetryConfig",
    "SendResult",
    "SessionInfo",
    "TimeoutConfig",
    "TransportError",
    "__version__",
]
