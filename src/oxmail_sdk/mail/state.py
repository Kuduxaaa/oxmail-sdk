from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

DEFAULT_SEEN_HISTORY = 500


@dataclass(frozen=True, slots=True)
class FolderState:
    """Snapshot returned by ``mail?action=examine`` for a single folder."""

    validity: str | None = None
    modseq: str | None = None
    total: int = 0
    unread: int = 0
    next_id: int = 0
    token: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> FolderState:
        data = payload.get("data") if "data" in payload else payload
        if not isinstance(data, Mapping):
            raise ValueError("examine response does not contain a state object")
        return cls(
            validity=_str_or_none(data.get("validity")),
            modseq=_str_or_none(data.get("modseq")),
            total=_int(data.get("total")),
            unread=_int(data.get("unread")),
            next_id=_int(data.get("next")),
            token=_str_or_none(data.get("token")),
        )

    @property
    def fingerprint(self) -> str:
        """Cheap equality key: changes whenever the folder changes."""

        if self.token:
            return self.token
        return f"{self.validity}:{self.modseq}:{self.total}:{self.unread}:{self.next_id}"


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Everything the watcher must remember between polls (and between runs)."""

    validity: str | None = None
    next_id: int = 0
    fingerprint: str | None = None
    seen_ids: tuple[str, ...] = ()

    def remember(
        self,
        ids: Iterable[str],
        *,
        history: int = DEFAULT_SEEN_HISTORY,
    ) -> tuple[str, ...]:
        known = list(self.seen_ids)
        existing = set(known)
        for value in ids:
            if value not in existing:
                known.append(value)
                existing.add(value)
        return tuple(known[-history:]) if history > 0 else tuple(known)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validity": self.validity,
            "next_id": self.next_id,
            "fingerprint": self.fingerprint,
            "seen_ids": list(self.seen_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Checkpoint:
        seen = payload.get("seen_ids")
        return cls(
            validity=_str_or_none(payload.get("validity")),
            next_id=_int(payload.get("next_id")),
            fingerprint=_str_or_none(payload.get("fingerprint")),
            seen_ids=tuple(str(value) for value in seen) if isinstance(seen, list) else (),
        )


@runtime_checkable
class CheckpointStore(Protocol):
    """Pluggable persistence for watcher checkpoints."""

    def load(self, key: str) -> Checkpoint | None: ...

    def save(self, key: str, checkpoint: Checkpoint) -> None: ...


@dataclass(slots=True)
class MemoryCheckpointStore:
    """Default store: state lives for the lifetime of the process."""

    _entries: dict[str, Checkpoint] = field(default_factory=dict)

    def load(self, key: str) -> Checkpoint | None:
        return self._entries.get(key)

    def save(self, key: str, checkpoint: Checkpoint) -> None:
        self._entries[key] = checkpoint


class JSONFileCheckpointStore:
    """Store checkpoints in a single JSON file so restarts resume cleanly."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self, key: str) -> Checkpoint | None:
        with self._lock:
            entry = self._read().get(key)
        return Checkpoint.from_dict(entry) if isinstance(entry, Mapping) else None

    def save(self, key: str, checkpoint: Checkpoint) -> None:
        with self._lock:
            entries = self._read()
            entries[key] = checkpoint.to_dict()
            self._write(entries)

    def _read(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, entries: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(entries, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
