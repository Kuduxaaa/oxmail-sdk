from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from ..auth import AuthService
from ..transport import HTTPTransport
from .attachments import Attachment
from .columns import parse_columns
from .constants import DEFAULT_MAIL_COLUMNS, DEFAULT_SORT_COLUMN, INBOX_FOLDER
from .message import MailMessage
from .models import AddressLike, MailAddress, MailPage, OutgoingMessage, SendResult
from .serializer import LegacyMessageSerializer, MessageSerializer, legacy_multipart
from .sources import (
    DEFAULT_RECOVER_AFTER,
    FailoverMailSource,
    HTTPMailSource,
    IMAPMailSource,
    MailSource,
)
from .state import CheckpointStore, FolderState
from .watch import DEFAULT_INTERVAL, ErrorHandler, InboxWatcher


class MailService:
    """Mail use-cases only; transport and wire serialization are delegated."""

    def __init__(
        self,
        transport: HTTPTransport,
        auth: AuthService,
        *,
        serializer: MessageSerializer | None = None,
    ) -> None:
        self._transport = transport
        self._auth = auth
        self._serializer = serializer or LegacyMessageSerializer()

    def list(
        self,
        *,
        folder: str = INBOX_FOLDER,
        offset: int = 0,
        limit: int = 50,
        category: str = "general",
        deleted: bool = True,
        sort_column: str = DEFAULT_SORT_COLUMN,
        order: str = "desc",
        timezone: str = "utc",
    ) -> MailPage:
        _validate_page(offset, limit)
        if order not in {"asc", "desc"}:
            raise ValueError("order must be 'asc' or 'desc'")

        payload = self._transport.request_json(
            "GET",
            "mail",
            params={
                "action": "all",
                "folder": folder,
                "categoryid": category,
                "columns": DEFAULT_MAIL_COLUMNS,
                "sort": sort_column,
                "order": order,
                "timezone": timezone,
                "limit": f"{offset},{limit}",
                "deleted": str(deleted).lower(),
                "session": self._auth.token,
            },
        )
        data = payload.get("data")
        items = tuple(data) if isinstance(data, list) else tuple()
        return MailPage(items=items, raw=payload, offset=offset, limit=limit)

    def iter_messages(
        self,
        *,
        folder: str = INBOX_FOLDER,
        page_size: int = 50,
        max_messages: int | None = None,
        category: str = "general",
        deleted: bool = True,
    ) -> Iterator[Any]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero")
        if max_messages is not None and max_messages < 0:
            raise ValueError("max_messages cannot be negative")

        offset = 0
        yielded = 0
        while True:
            page = self.list(
                folder=folder,
                offset=offset,
                limit=page_size,
                category=category,
                deleted=deleted,
            )
            if not page.items:
                return
            for item in page.items:
                if max_messages is not None and yielded >= max_messages:
                    return
                yield item
                yielded += 1
            if len(page.items) < page_size:
                return
            offset += len(page.items)

    def get(
        self,
        mail_id: str | int,
        *,
        folder: str = INBOX_FOLDER,
        sanitize: bool = False,
        unseen: bool = False,
        max_size: int = 102_400,
        timezone: str = "utc",
    ) -> Mapping[str, Any]:
        if max_size <= 0:
            raise ValueError("max_size must be greater than zero")

        return self._transport.request_json(
            "GET",
            "mail",
            params={
                "action": "get",
                "timezone": timezone,
                "embedded": "false",
                "sanitize": str(sanitize).lower(),
                "folder": folder,
                "id": str(mail_id),
                "view": "html",
                "max_size": str(max_size),
                "process_plain_text": "false",
                "pregenerate_previews": "true",
                "unseen": str(unseen).lower(),
                "session": self._auth.token,
            },
        )

    def examine(self, *, folder: str = INBOX_FOLDER) -> FolderState:
        """Fetch the cheap folder state snapshot used for change detection.

        One call is ~160 bytes and carries UIDVALIDITY, MODSEQ, the next UID
        and the total/unread counters, so a poll loop never needs to list
        messages until something actually changed.
        """

        payload = self._transport.request_json(
            "GET",
            "mail",
            params={
                "action": "examine",
                "folder": folder,
                "session": self._auth.token,
            },
        )
        return FolderState.from_payload(payload)

    def list_by_ids(
        self,
        ids: Iterable[str | int],
        *,
        folder: str = INBOX_FOLDER,
        columns: str = DEFAULT_MAIL_COLUMNS,
    ) -> tuple[MailMessage, ...]:
        """Fetch specific messages by id; unknown ids are skipped by the server."""

        wanted = [str(value) for value in ids]
        if not wanted:
            return ()

        payload = self._transport.request_json(
            "PUT",
            "mail",
            params={
                "action": "list",
                "columns": columns,
                "session": self._auth.token,
            },
            json_body=[{"folder": folder, "id": value} for value in wanted],
        )
        return _rows_to_messages(payload.get("data"), columns, folder)

    def recent(
        self,
        *,
        folder: str = INBOX_FOLDER,
        limit: int = 10,
        columns: str = DEFAULT_MAIL_COLUMNS,
    ) -> tuple[MailMessage, ...]:
        """Return the newest messages of a folder, oldest first."""

        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        payload = self._transport.request_json(
            "GET",
            "mail",
            params={
                "action": "all",
                "folder": folder,
                "columns": columns,
                "sort": DEFAULT_SORT_COLUMN,
                "order": "desc",
                "timezone": "utc",
                "limit": f"0,{limit}",
                "session": self._auth.token,
            },
        )
        messages = _rows_to_messages(payload.get("data"), columns, folder)
        return tuple(reversed(messages))

    def watch(
        self,
        *,
        folder: str = INBOX_FOLDER,
        interval: float = DEFAULT_INTERVAL,
        backend: str = "auto",
        columns: str = DEFAULT_MAIL_COLUMNS,
        fetch_body: bool = False,
        mark_seen: bool = False,
        include_existing: bool = False,
        backlog_limit: int = 10,
        store: CheckpointStore | None = None,
        key: str | None = None,
        on_error: ErrorHandler | None = None,
        recover_after: float = DEFAULT_RECOVER_AFTER,
    ) -> InboxWatcher:
        """Create a watcher for new mail in ``folder``.

        ``backend`` selects the transport: ``"imap"`` uses IMAP IDLE, ``"http"``
        polls ``mail?action=examine``, and the default ``"auto"`` runs IMAP as
        the primary source with automatic failover to HTTP polling.

        Iterate over the result to consume messages on the calling thread, or
        call ``.background(on_message=...)`` to run the loop in a thread.
        """

        source = self.source(
            folder=folder,
            backend=backend,
            columns=columns,
            mark_seen=mark_seen,
            recover_after=recover_after,
        )
        return InboxWatcher(
            source,
            key=key or f"{self._auth.username}|{folder}",
            interval=interval,
            fetch_body=fetch_body,
            mark_seen=mark_seen,
            include_existing=include_existing,
            backlog_limit=backlog_limit,
            store=store,
            on_error=on_error,
        )

    def source(
        self,
        *,
        folder: str = INBOX_FOLDER,
        backend: str = "auto",
        columns: str = DEFAULT_MAIL_COLUMNS,
        mark_seen: bool = False,
        recover_after: float = DEFAULT_RECOVER_AFTER,
    ) -> MailSource:
        """Build the backend a watcher would use, without starting a loop."""

        if backend not in {"auto", "imap", "http"}:
            raise ValueError("backend must be 'auto', 'imap' or 'http'")

        config = self._transport.config
        http_source = HTTPMailSource(self, self._auth, folder=folder, columns=columns)
        if backend == "http" or (backend == "auto" and not config.imap.enabled):
            return http_source

        imap_source = IMAPMailSource.from_config(
            config.imap,
            self._auth,
            host=config.imap_host,
            folder=folder,
            readonly=not mark_seen,
        )
        if backend == "imap":
            return imap_source
        return FailoverMailSource(imap_source, http_source, recover_after=recover_after)

    def send(
        self,
        message: OutgoingMessage,
        *,
        attachments: Sequence[Attachment] = (),
    ) -> SendResult:
        payload = self._serializer.serialize(message, from_email=self._auth.username)

        with legacy_multipart(payload, attachments) as multipart:
            response, result = self._transport.request_relaxed_json(
                "POST",
                "mail",
                params={
                    "action": "new",
                    "lineWrapAfter": "0",
                    "force_json_response": "true",
                    "session": self._auth.token,
                },
                files=multipart,
            )

        return SendResult(
            status_code=response.status_code,
            data=result,
            response_text=response.text,
        )

    def send_simple(
        self,
        *,
        to: AddressLike | Sequence[AddressLike],
        subject: str,
        body: str,
        html: bool = True,
        cc: AddressLike | Sequence[AddressLike] | None = None,
        bcc: AddressLike | Sequence[AddressLike] | None = None,
        sender_name: str | None = None,
        priority: int = 3,
        attachments: Sequence[Attachment] = (),
    ) -> SendResult:
        message = OutgoingMessage(
            to=_as_addresses(to),
            cc=_as_addresses(cc),
            bcc=_as_addresses(bcc),
            subject=subject,
            body=body,
            html=html,
            sender_name=sender_name,
            priority=priority,
        )
        return self.send(message, attachments=attachments)


def _rows_to_messages(data: Any, columns: str, folder: str) -> tuple[MailMessage, ...]:
    if not isinstance(data, list):
        return ()
    parsed = parse_columns(columns)
    return tuple(
        MailMessage.from_row(parsed, row, default_folder=folder)
        for row in data
        if isinstance(row, (list, tuple))
    )


def _as_addresses(
    value: AddressLike | Sequence[AddressLike] | None,
) -> tuple[AddressLike, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, MailAddress)):
        return (value,)
    return tuple(value)


def _validate_page(offset: int, limit: int) -> None:
    if offset < 0:
        raise ValueError("offset cannot be negative")
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
