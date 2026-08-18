from __future__ import annotations

from requests import Session

from .auth import AuthService, Credentials, SessionInfo
from .config import ClientConfig
from .mail import MailService
from .transport import HTTPTransport


class OXMailClient:
    """Composition root for the SDK.

    The client wires services together; domain logic lives in the individual
    auth/mail services and HTTP behavior lives in the transport layer.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        config: ClientConfig | None = None,
        session: Session | None = None,
    ) -> None:
        self.config = config or ClientConfig()
        self.transport = HTTPTransport(self.config, session=session)
        self.auth = AuthService(
            self.transport,
            Credentials(username=username, password=password),
        )
        self.mail = MailService(self.transport, self.auth)
        self._closed = False

    @property
    def authenticated(self) -> bool:
        return self.auth.authenticated

    @property
    def closed(self) -> bool:
        return self._closed

    def login(self, *, oxguard: bool = True) -> SessionInfo:
        return self.auth.login(oxguard=oxguard)

    def logout(self) -> None:
        self.auth.logout()

    def close(self, *, logout: bool = False) -> None:
        if self._closed:
            return
        try:
            if logout and self.auth.authenticated:
                self.auth.logout()
        finally:
            self.transport.close()
            self._closed = True

    def __enter__(self) -> OXMailClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
