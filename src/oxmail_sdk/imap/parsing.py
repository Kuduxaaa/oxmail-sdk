from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from email import message_from_bytes, utils
from email.header import decode_header, make_header
from email.message import Message
from typing import Any

#: IMAP system flag -> Open-Xchange flag bit, so both backends expose one model.
FLAG_BITS: Mapping[str, int] = {
    "\\answered": 1,
    "\\deleted": 2,
    "\\draft": 4,
    "\\flagged": 8,
    "\\recent": 16,
    "\\seen": 32,
    "$forwarded": 128,
    "\\forwarded": 128,
}

_ATTACHMENT_FLAGS = frozenset({"$hasattachment"})
_NO_ATTACHMENT_FLAGS = frozenset({"$hasnoattachment"})

_UID_RE = re.compile(rb"\bUID\s+(\d+)")
_SIZE_RE = re.compile(rb"\bRFC822\.SIZE\s+(\d+)")
_FLAGS_RE = re.compile(rb"\bFLAGS\s+\(([^)]*)\)")
_INTERNALDATE_RE = re.compile(rb'\bINTERNALDATE\s+"([^"]+)"')

HEADER_FIELDS = (
    "FROM",
    "TO",
    "CC",
    "BCC",
    "SUBJECT",
    "DATE",
    "CONTENT-TYPE",
    "X-PRIORITY",
    "IMPORTANCE",
    "MESSAGE-ID",
)


def flags_to_bits(flags: Iterable[str]) -> tuple[int, tuple[str, ...]]:
    """Split IMAP flags into an Open-Xchange bitmask plus the user flags."""

    bits = 0
    user_flags: list[str] = []
    for flag in flags:
        normalized = flag.strip()
        if not normalized:
            continue
        bit = FLAG_BITS.get(normalized.lower())
        if bit is None:
            user_flags.append(normalized)
        else:
            bits |= bit
    return bits, tuple(user_flags)


def parse_fetch_items(data: Sequence[Any]) -> tuple[tuple[bytes, bytes], ...]:
    """Pair each FETCH attribute block with its literal payload."""

    items: list[tuple[bytes, bytes]] = []
    for entry in data:
        if isinstance(entry, tuple) and len(entry) >= 2:
            prefix = entry[0] if isinstance(entry[0], bytes) else b""
            literal = entry[1] if isinstance(entry[1], bytes) else b""
            items.append((prefix, literal))
        elif isinstance(entry, bytes) and _UID_RE.search(entry):
            items.append((entry, b""))
    return tuple(items)


def header_row(prefix: bytes, literal: bytes, *, folder: str) -> dict[str, Any] | None:
    """Turn one FETCH response into the field mapping used by ``MailMessage``."""

    uid_match = _UID_RE.search(prefix)
    if uid_match is None:
        return None

    flag_match = _FLAGS_RE.search(prefix)
    raw_flags = flag_match.group(1).decode("ascii", "replace").split() if flag_match else []
    bits, user_flags = flags_to_bits(raw_flags)

    size_match = _SIZE_RE.search(prefix)
    internaldate_match = _INTERNALDATE_RE.search(prefix)
    headers = _parse_headers(literal)

    lowered = {flag.lower() for flag in user_flags}
    has_attachment = bool(lowered & _ATTACHMENT_FLAGS)
    if not has_attachment and not (lowered & _NO_ATTACHMENT_FLAGS):
        has_attachment = "multipart/mixed" in (headers.get("content-type") or "").lower()

    received = (
        _internaldate_to_millis(internaldate_match.group(1).decode("ascii", "replace"))
        if internaldate_match
        else None
    )
    sent = _date_to_millis(headers.get("date"))

    return {
        "id": uid_match.group(1).decode("ascii"),
        "folder_id": folder,
        "from": _addresses(headers.get("from")),
        "to": _addresses(headers.get("to")),
        "cc": _addresses(headers.get("cc")),
        "bcc": _addresses(headers.get("bcc")),
        "subject": _decode(headers.get("subject")),
        "received_date": received if received is not None else sent,
        "sent_date": sent,
        "size": int(size_match.group(1)) if size_match else None,
        "flags": bits,
        "user_flags": list(user_flags),
        "attachment": has_attachment,
        "content_type": headers.get("content-type"),
        "priority": _priority(headers),
    }


def rfc822_to_detail(raw: bytes, *, folder: str, uid: str) -> dict[str, Any]:
    """Render a raw message into the same detail shape the HTTP backend returns."""

    parsed = message_from_bytes(raw)
    attachments: list[dict[str, Any]] = []
    for index, part in enumerate(_walk_parts(parsed), start=1):
        attachments.append(_part_to_attachment(part, str(index)))

    return {
        "id": uid,
        "folder_id": folder,
        "subject": _decode(parsed.get("Subject")),
        "from": _addresses(parsed.get("From")),
        "to": _addresses(parsed.get("To")),
        "cc": _addresses(parsed.get("Cc")),
        "headers": {key.lower(): _decode(value) for key, value in parsed.items()},
        "attachments": attachments,
        "size": len(raw),
    }


def _walk_parts(message: Message) -> list[Message]:
    if not message.is_multipart():
        return [message]
    return [part for part in message.walk() if not part.is_multipart()]


def _part_to_attachment(part: Message, index: str) -> dict[str, Any]:
    content_type = part.get_content_type()
    disposition = (part.get_content_disposition() or "inline").lower()
    filename = part.get_filename()
    if filename:
        filename = _decode(filename)

    entry: dict[str, Any] = {
        "id": index,
        "content_type": content_type,
        "disp": "attachment" if disposition == "attachment" else "inline",
    }
    if filename:
        entry["filename"] = filename

    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        entry["size"] = len(payload)
        if content_type.startswith("text/") and disposition != "attachment":
            charset = part.get_content_charset() or "utf-8"
            entry["content"] = payload.decode(charset, "replace")
    return entry


def _parse_headers(literal: bytes) -> dict[str, str]:
    if not literal:
        return {}
    parsed = message_from_bytes(literal)
    return {key.lower(): value for key, value in parsed.items()}


def _addresses(value: str | None) -> list[list[str | None]]:
    if not value:
        return []
    pairs: list[list[str | None]] = []
    for name, email in utils.getaddresses([value]):
        if not email or "@" not in email:
            continue
        pairs.append([_decode(name), email])
    return pairs


def _decode(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(make_header(decode_header(value))).strip() or None
    except (UnicodeDecodeError, LookupError, ValueError):
        return value.strip() or None


def _internaldate_to_millis(value: str) -> int | None:
    """Convert an IMAP INTERNALDATE (``24-Aug-2026 02:01:06 +0000``) to epoch millis."""

    text = value.replace('"', "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%d-%b-%Y %H:%M:%S %z")
    except ValueError:
        return _date_to_millis(text)
    return int(parsed.timestamp() * 1000)


def _date_to_millis(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return int(parsed.timestamp() * 1000)


def _priority(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("x-priority") or headers.get("importance")
    if not raw:
        return None
    text = raw.strip().split()[0].strip("()")
    try:
        return max(1, min(5, int(text)))
    except ValueError:
        return {"high": 1, "normal": 3, "low": 5}.get(text.lower())
