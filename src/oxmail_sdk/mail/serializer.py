from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from typing import Any, Protocol

from .attachments import Attachment
from .models import AddressLike, MailAddress, OutgoingMessage

MultipartItem = tuple[str, tuple[Any, ...]]


class MessageSerializer(Protocol):
    """Wire serializer contract used by MailService."""

    def serialize(self, message: OutgoingMessage, *, from_email: str) -> dict[str, Any]: ...


class LegacyMessageSerializer:
    """Serialize OutgoingMessage to the legacy Open-Xchange mail payload."""

    def serialize(self, message: OutgoingMessage, *, from_email: str) -> dict[str, Any]:
        return {
            "from": [[message.sender_name, from_email]],
            "to": _addresses(message.to),
            "cc": _addresses(message.cc),
            "bcc": _addresses(message.bcc),
            "subject": message.subject,
            "priority": message.priority,
            "attachments": [
                {
                    "content_type": "text/html" if message.html else "text/plain",
                    "content": message.body,
                    "disp": "inline",
                }
            ],
        }


@contextmanager
def legacy_multipart(
    payload: dict[str, Any],
    attachments: Sequence[Attachment],
) -> Iterator[list[MultipartItem]]:
    """Build requests-compatible multipart data and own file handle lifetimes."""

    with ExitStack() as stack:
        parts: list[MultipartItem] = [
            ("json_0", (None, json.dumps(payload, ensure_ascii=False)))
        ]
        for index, attachment in enumerate(attachments):
            file_obj = stack.enter_context(attachment.open())
            parts.append(
                (
                    f"file_{index}",
                    (attachment.filename, file_obj, attachment.content_type),
                )
            )
        yield parts


def _addresses(values: Sequence[AddressLike]) -> list[list[str | None]]:
    result: list[list[str | None]] = []
    for value in values:
        address = MailAddress.coerce(value)
        result.append([address.name, address.email])
    return result
