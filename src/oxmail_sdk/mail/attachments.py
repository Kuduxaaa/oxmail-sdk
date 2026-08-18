from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class Attachment:
    """File attachment backed by either a filesystem path or in-memory bytes."""

    filename: str
    content_type: str
    path: Path | None = None
    data: bytes | None = None

    def __post_init__(self) -> None:
        if (self.path is None) == (self.data is None):
            raise ValueError("attachment must have exactly one of path or data")
        if not self.filename.strip():
            raise ValueError("attachment filename cannot be empty")
        if not self.content_type.strip():
            raise ValueError("attachment content_type cannot be empty")

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> Attachment:
        file_path = Path(path)
        if not file_path.is_file():
            raise ValueError(f"attachment path is not a file: {file_path}")
        resolved_name = filename or file_path.name
        guessed = mimetypes.guess_type(resolved_name)[0] or "application/octet-stream"
        return cls(
            filename=resolved_name,
            content_type=content_type or guessed,
            path=file_path,
        )

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        filename: str,
        content_type: str | None = None,
    ) -> Attachment:
        guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return cls(
            filename=filename,
            content_type=content_type or guessed,
            data=data,
        )

    def open(self) -> BinaryIO:
        if self.path is not None:
            return self.path.open("rb")
        return BytesIO(self.data if self.data is not None else b"")
