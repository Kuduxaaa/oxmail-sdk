from __future__ import annotations

from requests import Session

from oxmail_sdk.auth import AuthService, Credentials
from oxmail_sdk.config import ClientConfig
from oxmail_sdk.transport import HTTPTransport


def make_auth() -> tuple[HTTPTransport, AuthService]:
    transport = HTTPTransport(ClientConfig(), session=Session())
    auth = AuthService(
        transport,
        Credentials(username="user@example.com", password="secret"),
    )
    return transport, auth
