from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from ..auth import AuthService
from ..exceptions import IMAPError, OXMailError
from ..imap import IMAPConfig, IMAPConnection
from .constants import DEFAULT_MAIL_COLUMNS, INBOX_FOLDER
from .message import MailMessage
from .state import FolderState

if TYPE_CHECKING:
    from .service import MailService

logger = logging.getLogger(__name__)

DEFAULT_RECOVER_AFTER = 300.0

T = TypeVar("T")


def mailbox_from_folder(folder: str) -> str:
    """Translate an Open-Xchange folder id (``default0/INBOX``) to an IMAP mailbox."""

    parts = folder.split("/", 1)
    if len(parts) == 2 and parts[0].startswith("default"):
        return parts[1]
    return folder


class MailSource(Protocol):
    """Backend used by the watcher to observe a folder."""

    @property
    def name(self) -> str:
        """Short backend identifier, e.g. ``imap`` or ``http``."""

    def open(self) -> None:
        """Prepare the backend; raise if it is unusable."""

    def close(self) -> None:
        """Release any resources held by the backend."""

    def state(self) -> FolderState:
        """Return the current folder state (UIDVALIDITY, next UID, counters)."""

    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]:
        """Fetch headers for the given ids; missing ids are skipped."""

    def fetch_detail(self, message: MailMessage, *, mark_seen: bool) -> Mapping[str, Any] | None:
        """Fetch the full body for one message."""

    def recent(self, limit: int) -> tuple[MailMessage, ...]:
        """Return the newest messages of the folder, oldest first."""

    def wait(self, timeout: float, stop: threading.Event) -> bool:
        """Block until the folder may have changed, or the timeout expires."""


class HTTPMailSource:
    """Fallback backend: Open-Xchange HTTP API with ``action=examine`` polling."""

    name = "http"

    def __init__(
        self,
        service: MailService,
        auth: AuthService,
        *,
        folder: str = INBOX_FOLDER,
        columns: str = DEFAULT_MAIL_COLUMNS,
    ) -> None:
        self._service = service
        self._auth = auth
        self._folder = folder
        self._columns = columns

    def open(self) -> None:
        self._auth.ensure_authenticated()

    def close(self) -> None:
        return None

    def state(self) -> FolderState:
        return self._call(lambda: self._service.examine(folder=self._folder))

    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]:
        return self._call(
            lambda: self._service.list_by_ids(ids, folder=self._folder, columns=self._columns)
        )

    def fetch_detail(self, message: MailMessage, *, mark_seen: bool) -> Mapping[str, Any] | None:
        payload = self._call(
            lambda: self._service.get(message.id, folder=self._folder, unseen=not mark_seen)
        )
        data = payload.get("data")
        return data if isinstance(data, Mapping) else None

    def recent(self, limit: int) -> tuple[MailMessage, ...]:
        return self._call(
            lambda: self._service.recent(
                folder=self._folder,
                limit=limit,
                columns=self._columns,
            )
        )

    def wait(self, timeout: float, stop: threading.Event) -> bool:
        return not stop.wait(timeout)

    def _call(self, operation: Callable[[], T]) -> T:
        return self._auth.run_with_session_retry(operation)


class IMAPMailSource:
    """Primary backend: IMAP with IDLE, so new mail arrives as a server push."""

    name = "imap"

    def __init__(
        self,
        connection: IMAPConnection,
        *,
        folder: str = INBOX_FOLDER,
        mailbox: str | None = None,
        idle_refresh: float = 540.0,
        readonly: bool = True,
    ) -> None:
        self._connection = connection
        self._folder = folder
        self._mailbox = mailbox or mailbox_from_folder(folder)
        self._idle_refresh = idle_refresh
        self._readonly = readonly

    @classmethod
    def from_config(
        cls,
        config: IMAPConfig,
        auth: AuthService,
        *,
        host: str,
        folder: str = INBOX_FOLDER,
        readonly: bool = True,
    ) -> IMAPMailSource:
        credentials = auth.credentials
        connection = IMAPConnection(
            config,
            host=host,
            username=credentials.username,
            password=credentials.password,
        )
        return cls(
            connection,
            folder=folder,
            idle_refresh=config.idle_refresh,
            readonly=readonly,
        )

    @property
    def connection(self) -> IMAPConnection:
        return self._connection

    def open(self) -> None:
        self._connection.connect()
        self._connection.select(self._mailbox, readonly=self._readonly)

    def close(self) -> None:
        self._connection.close()

    def state(self) -> FolderState:
        status = self._ready().status(self._mailbox)
        return FolderState(
            validity=status.uidvalidity,
            total=status.messages,
            unread=status.unseen,
            next_id=status.uidnext,
        )

    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]:
        rows = self._ready().fetch_headers(tuple(ids), folder=self._folder)
        return tuple(MailMessage.from_mapping(row, default_folder=self._folder) for row in rows)

    def fetch_detail(self, message: MailMessage, *, mark_seen: bool) -> Mapping[str, Any] | None:
        return self._ready().fetch_detail(
            message.id,
            folder=self._folder,
            peek=not mark_seen,
        )

    def recent(self, limit: int) -> tuple[MailMessage, ...]:
        state = self.state()
        first = max(1, state.next_id - limit)
        ids = [str(uid) for uid in range(first, state.next_id)]
        messages = list(self.fetch(ids))
        messages.sort(key=_uid_key)
        return tuple(messages[-limit:])

    def wait(self, timeout: float, stop: threading.Event) -> bool:
        """Park in IDLE until the server pushes, re-issuing IDLE periodically.

        New mail arrives as a push, so the watcher interval only acts as a
        lower bound for the safety-net check; IDLE is held for at least one
        ``idle_refresh`` window.
        """

        deadline = time.monotonic() + max(timeout, self._idle_refresh)
        connection = self._ready()
        while not stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if connection.idle(min(remaining, self._idle_refresh), stop):
                return True
        return False

    def _ready(self) -> IMAPConnection:
        if not self._connection.connected:
            self.open()
        return self._connection


class FailoverMailSource:
    """Runs the primary backend, falling back to a secondary one when it fails.

    After ``recover_after`` seconds the primary is retried, so a transient IMAP
    outage does not pin the watcher to HTTP polling forever.
    """

    def __init__(
        self,
        primary: MailSource,
        fallback: MailSource,
        *,
        recover_after: float = DEFAULT_RECOVER_AFTER,
        on_switch: Callable[[str, BaseException | None], None] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._recover_after = recover_after
        self._on_switch = on_switch
        self._active: MailSource = primary
        self._degraded_at: float | None = None

    @property
    def name(self) -> str:
        return self._active.name

    @property
    def active(self) -> MailSource:
        return self._active

    @property
    def degraded(self) -> bool:
        return self._active is self._fallback

    def open(self) -> None:
        try:
            self._primary.open()
            self._use(self._primary, None)
        except (OXMailError, OSError) as exc:
            self._degrade(exc)

    def close(self) -> None:
        for source in (self._primary, self._fallback):
            try:
                source.close()
            except Exception:  # noqa: BLE001 - closing must not mask the real error
                logger.debug("closing %s source failed", source.name, exc_info=True)

    def state(self) -> FolderState:
        return self._guard(lambda source: source.state())

    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]:
        return self._guard(lambda source: source.fetch(ids))

    def fetch_detail(self, message: MailMessage, *, mark_seen: bool) -> Mapping[str, Any] | None:
        return self._guard(lambda source: source.fetch_detail(message, mark_seen=mark_seen))

    def recent(self, limit: int) -> tuple[MailMessage, ...]:
        return self._guard(lambda source: source.recent(limit))

    def wait(self, timeout: float, stop: threading.Event) -> bool:
        self._maybe_recover()
        return self._guard(lambda source: source.wait(timeout, stop))

    def _guard(self, operation: Callable[[MailSource], T]) -> T:
        try:
            return operation(self._active)
        except (IMAPError, OSError) as exc:
            if self._active is self._fallback:
                raise
            self._degrade(exc)
            return operation(self._active)

    def _degrade(self, exc: BaseException) -> None:
        logger.warning(
            "%s backend unavailable (%s); falling back to %s",
            self._primary.name,
            exc,
            self._fallback.name,
        )
        try:
            self._primary.close()
        except Exception:  # noqa: BLE001 - the primary is already broken
            logger.debug("closing the primary source failed", exc_info=True)
        self._fallback.open()
        self._degraded_at = time.monotonic()
        self._use(self._fallback, exc)

    def _maybe_recover(self) -> None:
        if self._degraded_at is None or self._active is self._primary:
            return
        if time.monotonic() - self._degraded_at < self._recover_after:
            return
        try:
            self._primary.open()
        except (OXMailError, OSError) as exc:
            logger.debug("%s backend still unavailable: %s", self._primary.name, exc)
            self._degraded_at = time.monotonic()
            return
        logger.info("%s backend recovered", self._primary.name)
        self._degraded_at = None
        self._use(self._primary, None)

    def _use(self, source: MailSource, exc: BaseException | None) -> None:
        changed = source is not self._active
        self._active = source
        if changed and self._on_switch is not None:
            self._on_switch(source.name, exc)


def _uid_key(message: MailMessage) -> tuple[int, str]:
    try:
        return (int(message.id), message.id)
    except ValueError:
        return (0, message.id)
