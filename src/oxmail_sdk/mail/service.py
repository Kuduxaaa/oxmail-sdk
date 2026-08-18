from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from ..auth import AuthService
from ..transport import HTTPTransport
from .attachments import Attachment
from .constants import DEFAULT_MAIL_COLUMNS, DEFAULT_SORT_COLUMN, INBOX_FOLDER
from .models import AddressLike, MailAddress, MailPage, OutgoingMessage, SendResult
from .serializer import LegacyMessageSerializer, MessageSerializer, legacy_multipart


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
