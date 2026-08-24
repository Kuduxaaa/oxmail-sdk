from __future__ import annotations

from collections.abc import Mapping

#: Wire column identifiers used by the Open-Xchange mail module.
COLUMN_COLOR_LABEL = "102"
COLUMN_ID = "600"
COLUMN_FOLDER_ID = "601"
COLUMN_HAS_ATTACHMENT = "602"
COLUMN_FROM = "603"
COLUMN_TO = "604"
COLUMN_CC = "605"
COLUMN_BCC = "606"
COLUMN_SUBJECT = "607"
COLUMN_SIZE = "608"
COLUMN_SENT_DATE = "609"
COLUMN_RECEIVED_DATE = "610"
COLUMN_FLAGS = "611"
COLUMN_PRIORITY = "614"
COLUMN_ACCOUNT_NAME = "652"
COLUMN_CONTENT_TYPE = "656"
COLUMN_DATE = "661"
COLUMN_TEXT_PREVIEW = "662"
COLUMN_USER_FLAGS = "668"

#: Stable field names for every column the SDK requests by default.
COLUMN_FIELDS: Mapping[str, str] = {
    COLUMN_COLOR_LABEL: "color_label",
    COLUMN_ID: "id",
    COLUMN_FOLDER_ID: "folder_id",
    COLUMN_HAS_ATTACHMENT: "attachment",
    COLUMN_FROM: "from",
    COLUMN_TO: "to",
    COLUMN_CC: "cc",
    COLUMN_BCC: "bcc",
    COLUMN_SUBJECT: "subject",
    COLUMN_SIZE: "size",
    COLUMN_SENT_DATE: "sent_date",
    COLUMN_RECEIVED_DATE: "received_date",
    COLUMN_FLAGS: "flags",
    COLUMN_PRIORITY: "priority",
    COLUMN_ACCOUNT_NAME: "account_name",
    COLUMN_CONTENT_TYPE: "content_type",
    COLUMN_DATE: "date",
    COLUMN_TEXT_PREVIEW: "text_preview",
    COLUMN_USER_FLAGS: "user_flags",
}

#: IMAP system flags as exposed through column 611.
FLAG_ANSWERED = 1
FLAG_DELETED = 2
FLAG_DRAFT = 4
FLAG_FLAGGED = 8
FLAG_RECENT = 16
FLAG_SEEN = 32
FLAG_USER = 64
FLAG_FORWARDED = 128


def columns_param(columns: tuple[str, ...]) -> str:
    return ",".join(columns)


def parse_columns(columns: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in columns.split(",") if part.strip())


def row_to_mapping(columns: tuple[str, ...], row: object) -> dict[str, object]:
    """Zip a positional column row into a field-name mapping."""

    if not isinstance(row, (list, tuple)):
        raise ValueError(f"expected a column row, got {type(row).__name__}")
    return {
        COLUMN_FIELDS.get(column, column): value
        for column, value in zip(columns, row, strict=False)
    }
