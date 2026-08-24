from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from .columns import (
    FLAG_ANSWERED,
    FLAG_DELETED,
    FLAG_DRAFT,
    FLAG_FLAGGED,
    FLAG_FORWARDED,
    FLAG_RECENT,
    FLAG_SEEN,
    row_to_mapping,
)
from .models import MailAddress


@dataclass(frozen=True, slots=True)
class MailMessage:
    """A parsed mail header, optionally carrying the fetched body."""

    id: str
    folder: str
    subject: str
    sender: MailAddress | None = None
    to: tuple[MailAddress, ...] = ()
    cc: tuple[MailAddress, ...] = ()
    bcc: tuple[MailAddress, ...] = ()
    received_at: datetime | None = None
    sent_at: datetime | None = None
    size: int | None = None
    priority: int | None = None
    flags: int = 0
    color_label: int | None = None
    has_attachment: bool = False
    content_type: str | None = None
    preview: str | None = None
    user_flags: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)
    detail: Mapping[str, Any] | None = field(default=None, repr=False)

    # -- flag helpers -----------------------------------------------------
    @property
    def seen(self) -> bool:
        return bool(self.flags & FLAG_SEEN)

    @property
    def unread(self) -> bool:
        return not self.seen

    @property
    def answered(self) -> bool:
        return bool(self.flags & FLAG_ANSWERED)

    @property
    def deleted(self) -> bool:
        return bool(self.flags & FLAG_DELETED)

    @property
    def draft(self) -> bool:
        return bool(self.flags & FLAG_DRAFT)

    @property
    def flagged(self) -> bool:
        return bool(self.flags & FLAG_FLAGGED)

    @property
    def forwarded(self) -> bool:
        return bool(self.flags & FLAG_FORWARDED)

    @property
    def recent(self) -> bool:
        return bool(self.flags & FLAG_RECENT)

    # -- body helpers -----------------------------------------------------
    @property
    def fetched(self) -> bool:
        return self.detail is not None

    @property
    def html(self) -> str | None:
        return self._body_part("text/html")

    @property
    def text(self) -> str | None:
        return self._body_part("text/plain")

    @property
    def body(self) -> str | None:
        """Preferred body content: HTML when present, plain text otherwise."""

        return self.html or self.text

    @property
    def attachments(self) -> tuple[Mapping[str, Any], ...]:
        """Non-inline attachment parts from the fetched detail payload."""

        return tuple(
            part for part in self._parts() if str(part.get("disp", "")).lower() == "attachment"
        )

    def with_detail(self, detail: Mapping[str, Any]) -> MailMessage:
        return replace(self, detail=detail)

    def _parts(self) -> tuple[Mapping[str, Any], ...]:
        if not isinstance(self.detail, Mapping):
            return ()
        parts = self.detail.get("attachments")
        if not isinstance(parts, Sequence):
            return ()
        return tuple(part for part in parts if isinstance(part, Mapping))

    def _body_part(self, content_type: str) -> str | None:
        for part in self._parts():
            if str(part.get("content_type", "")).lower().startswith(content_type):
                content = part.get("content")
                if isinstance(content, str):
                    return content
        return None

    # -- construction -----------------------------------------------------
    @classmethod
    def from_row(
        cls,
        columns: tuple[str, ...],
        row: Any,
        *,
        default_folder: str = "",
    ) -> MailMessage:
        return cls.from_mapping(row_to_mapping(columns, row), default_folder=default_folder)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        default_folder: str = "",
    ) -> MailMessage:
        senders = _addresses(payload.get("from"))
        return cls(
            id=str(payload.get("id", "")),
            folder=str(payload.get("folder_id") or default_folder),
            subject=_text(payload.get("subject")) or "",
            sender=senders[0] if senders else None,
            to=_addresses(payload.get("to")),
            cc=_addresses(payload.get("cc")),
            bcc=_addresses(payload.get("bcc")),
            received_at=_timestamp(payload.get("received_date") or payload.get("date")),
            sent_at=_timestamp(payload.get("sent_date")),
            size=_int_or_none(payload.get("size")),
            priority=_int_or_none(payload.get("priority")),
            flags=_int_or_none(payload.get("flags")) or 0,
            color_label=_int_or_none(payload.get("color_label")),
            has_attachment=bool(payload.get("attachment")),
            content_type=_text(payload.get("content_type")),
            preview=_text(payload.get("text_preview")),
            user_flags=tuple(
                str(flag) for flag in payload.get("user_flags") or () if flag is not None
            ),
            raw=dict(payload),
        )


def _addresses(value: Any) -> tuple[MailAddress, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    parsed: list[MailAddress] = []
    for entry in value:
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)):
            continue
        pair = list(entry)
        email = _text(pair[1]) if len(pair) > 1 else None
        if not email or "@" not in email:
            continue
        parsed.append(MailAddress(email=email, name=_text(pair[0]) if pair else None))
    return tuple(parsed)


def _timestamp(value: Any) -> datetime | None:
    milliseconds = _int_or_none(value)
    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
