from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..exceptions import APIError, AuthenticationError, NotAuthenticatedError
from ..transport import HTTPTransport
from .models import Credentials, SessionInfo

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AuthService:
    """Authentication/session lifecycle only."""

    def __init__(self, transport: HTTPTransport, credentials: Credentials) -> None:
        self._transport = transport
        self._credentials = credentials
        self._session_info: SessionInfo | None = None
        self._oxguard = True

    @property
    def username(self) -> str:
        return self._credentials.username

    @property
    def credentials(self) -> Credentials:
        """Credentials used for this session, for backends that authenticate separately."""

        return self._credentials

    @property
    def authenticated(self) -> bool:
        return self._session_info is not None

    @property
    def session_info(self) -> SessionInfo | None:
        return self._session_info

    @property
    def token(self) -> str:
        if self._session_info is None:
            raise NotAuthenticatedError("not authenticated; call client.login() first")
        return self._session_info.session

    def login(self, *, oxguard: bool = True) -> SessionInfo:
        self._oxguard = oxguard
        try:
            payload = self._transport.request_json(
                "POST",
                "login",
                data={
                    "action": "login",
                    "name": self._credentials.username,
                    "password": self._credentials.password,
                    "locale": self._transport.config.locale,
                    "client": self._transport.config.client_name,
                    "version": self._transport.config.client_version,
                    "timeout": "10000",
                    "rampup": "false",
                    "staySignedIn": "true",
                },
            )
            info = SessionInfo.from_payload(payload)
        except (APIError, ValueError) as exc:
            raise AuthenticationError(f"login failed: {exc}") from exc

        self._session_info = info
        if not oxguard:
            return info

        try:
            self.authenticate_oxguard()
        except Exception:
            # Best-effort remote cleanup while preserving the original Guard error.
            try:
                self.logout()
            except Exception:
                self.clear_local_session()
            raise
        return info

    def ensure_authenticated(self) -> SessionInfo:
        """Return the current session, logging in on first use."""

        if self._session_info is not None:
            return self._session_info
        return self.login(oxguard=self._oxguard)

    def refresh(self) -> SessionInfo:
        """Drop the local session and log in again with the same options."""

        self.clear_local_session()
        return self.login(oxguard=self._oxguard)

    def run_with_session_retry(self, operation: Callable[[], T]) -> T:
        """Run ``operation``, re-logging in once if the session expired."""

        self.ensure_authenticated()
        try:
            return operation()
        except (APIError, NotAuthenticatedError) as exc:
            if isinstance(exc, APIError) and not exc.session_expired:
                raise
            logger.info("session rejected by Open-Xchange; re-authenticating")
            self.refresh()
            return operation()

    def authenticate_oxguard(self) -> dict[str, Any]:
        try:
            return self._transport.request_json(
                "POST",
                "oxguard/login",
                params={
                    "action": "login",
                    "time": str(int(time.time() * 1000)),
                    "type": "pgp",
                    "session": self.token,
                },
                json_body={
                    "encr_password": "",
                    "lang": self._transport.config.locale,
                    "email": self._credentials.username,
                    "type": "pgp",
                },
            )
        except APIError as exc:
            raise AuthenticationError(f"OX Guard authentication failed: {exc}") from exc

    def logout(self) -> None:
        if self._session_info is None:
            return
        token = self._session_info.session
        try:
            self._transport.request_json(
                "GET",
                "login",
                params={"action": "logout", "session": token},
            )
        finally:
            self.clear_local_session()

    def clear_local_session(self) -> None:
        """Forget local authentication state without a remote logout request."""

        self._session_info = None
        self._transport.session.cookies.clear()
