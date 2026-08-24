from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Sequence

from .message import MailMessage
from .sources import MailSource
from .state import (
    DEFAULT_SEEN_HISTORY,
    Checkpoint,
    CheckpointStore,
    FolderState,
    MemoryCheckpointStore,
)

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 15.0
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ERROR_DELAY = 300.0

ErrorHandler = Callable[[BaseException], None]
MessageHandler = Callable[[MailMessage], None]


class InboxWatcher:
    """Watches a folder for newly delivered mail.

    The watcher is backend agnostic: the IMAP source pushes changes over IDLE,
    while the HTTP source polls ``mail?action=examine``. Either way an idle
    period costs nothing more than one parked connection or one small request,
    and headers are fetched only for the UIDs that really appeared.

    Iterate over the watcher to consume new mail on the calling thread, or call
    :meth:`background` to run the same loop on a worker thread.
    """

    def __init__(
        self,
        source: MailSource,
        *,
        key: str,
        interval: float = DEFAULT_INTERVAL,
        fetch_body: bool = False,
        mark_seen: bool = False,
        include_existing: bool = False,
        backlog_limit: int = 10,
        store: CheckpointStore | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        seen_history: int = DEFAULT_SEEN_HISTORY,
        on_error: ErrorHandler | None = None,
        max_error_delay: float = DEFAULT_MAX_ERROR_DELAY,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be greater than zero")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        if backlog_limit < 0:
            raise ValueError("backlog_limit cannot be negative")

        self._source = source
        self._key = key
        self._interval = interval
        self._fetch_body = fetch_body
        self._mark_seen = mark_seen
        self._include_existing = include_existing
        self._backlog_limit = backlog_limit
        self._store: CheckpointStore = store or MemoryCheckpointStore()
        self._batch_size = batch_size
        self._seen_history = seen_history
        self._max_error_delay = max_error_delay
        self._state: FolderState | None = None
        self._opened = False
        self._stop = threading.Event()

        #: Optional error hook; when set, iteration survives failed polls.
        self.on_error: ErrorHandler | None = on_error

    # -- introspection ----------------------------------------------------
    @property
    def source(self) -> MailSource:
        return self._source

    @property
    def backend(self) -> str:
        """Name of the backend currently serving this watcher."""

        return self._source.name

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def key(self) -> str:
        return self._key

    @property
    def state(self) -> FolderState | None:
        """Folder state observed during the most recent poll."""

        return self._state

    @property
    def checkpoint(self) -> Checkpoint | None:
        return self._store.load(self._key)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # -- control ----------------------------------------------------------
    def stop(self) -> None:
        """Ask an in-flight iteration to finish after the current message."""

        self._stop.set()

    def close(self) -> None:
        """Stop the loop and release the backend connection."""

        self._stop.set()
        if self._opened:
            self._opened = False
            self._source.close()

    def reset(self) -> None:
        """Forget the stored checkpoint; the next poll re-establishes a baseline."""

        self._store.save(self._key, Checkpoint())
        self._state = None

    def __enter__(self) -> InboxWatcher:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # -- polling ----------------------------------------------------------
    def poll(self) -> tuple[MailMessage, ...]:
        """Run exactly one check and return the messages discovered by it."""

        self._open()
        state = self._source.state()
        self._state = state
        checkpoint = self._store.load(self._key)

        if checkpoint is None or not checkpoint.fingerprint:
            return self._bootstrap(state)

        if checkpoint.validity and state.validity and checkpoint.validity != state.validity:
            logger.warning(
                "UIDVALIDITY changed (%s -> %s); rebuilding the baseline",
                checkpoint.validity,
                state.validity,
            )
            return self._bootstrap(state)

        if checkpoint.fingerprint == state.fingerprint:
            return ()

        messages = self._fetch_new(checkpoint, state)
        seen = checkpoint.remember(
            (message.id for message in messages),
            history=self._seen_history,
        )
        self._save(state, seen)
        return messages

    def __iter__(self) -> Iterator[MailMessage]:
        self._stop.clear()
        failures = 0
        while not self._stop.is_set():
            try:
                messages = self.poll()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                if not self._handle_error(exc, failures + 1):
                    break
                failures += 1
                continue

            failures = 0
            for message in messages:
                if self._stop.is_set():
                    return
                yield message

            if self._stop.is_set():
                break

            try:
                self._source.wait(self._interval, self._stop)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                if not self._handle_error(exc, failures + 1):
                    break
                failures += 1

    def background(
        self,
        *,
        on_message: MessageHandler | None = None,
        on_error: ErrorHandler | None = None,
        name: str = "oxmail-inbox-watcher",
        daemon: bool = True,
    ) -> BackgroundWatcher:
        """Wrap this watcher in a worker thread."""

        return BackgroundWatcher(
            self,
            on_message=on_message,
            on_error=on_error,
            name=name,
            daemon=daemon,
        )

    # -- internals --------------------------------------------------------
    def _handle_error(self, exc: Exception, failures: int) -> bool:
        """Report a failed cycle; return False when iteration should stop."""

        handler = self.on_error
        if handler is None:
            raise exc
        handler(exc)
        return not self._stop.wait(self._error_delay(failures))

    def _open(self) -> None:
        if self._opened:
            return
        self._source.open()
        self._opened = True

    def _bootstrap(self, state: FolderState) -> tuple[MailMessage, ...]:
        backlog: tuple[MailMessage, ...] = ()
        if self._include_existing and self._backlog_limit:
            backlog = self._with_bodies(self._source.recent(self._backlog_limit))
        self._save(state, tuple(message.id for message in backlog))
        return backlog

    def _fetch_new(self, checkpoint: Checkpoint, state: FolderState) -> tuple[MailMessage, ...]:
        known = set(checkpoint.seen_ids)
        candidates = [
            str(uid) for uid in range(checkpoint.next_id, state.next_id) if str(uid) not in known
        ]
        if not candidates:
            return ()

        found: list[MailMessage] = []
        for chunk in _chunks(candidates, self._batch_size):
            found.extend(self._source.fetch(chunk))
        found.sort(key=_sort_key)
        return self._with_bodies(tuple(found))

    def _with_bodies(self, messages: tuple[MailMessage, ...]) -> tuple[MailMessage, ...]:
        if not self._fetch_body or not messages:
            return messages

        detailed: list[MailMessage] = []
        for message in messages:
            detail = self._source.fetch_detail(message, mark_seen=self._mark_seen)
            detailed.append(message.with_detail(detail) if detail is not None else message)
        return tuple(detailed)

    def _save(self, state: FolderState, seen_ids: Sequence[str]) -> None:
        self._store.save(
            self._key,
            Checkpoint(
                validity=state.validity,
                next_id=state.next_id,
                fingerprint=state.fingerprint,
                seen_ids=tuple(seen_ids),
            ),
        )

    def _error_delay(self, failures: int) -> float:
        return min(self._interval * float(1 << min(failures, 6)), self._max_error_delay)


class BackgroundWatcher:
    """Runs an :class:`InboxWatcher` loop on a worker thread."""

    def __init__(
        self,
        watcher: InboxWatcher,
        *,
        on_message: MessageHandler | None = None,
        on_error: ErrorHandler | None = None,
        name: str = "oxmail-inbox-watcher",
        daemon: bool = True,
    ) -> None:
        self._watcher = watcher
        self._on_message = on_message
        self._name = name
        self._daemon = daemon
        self._thread: threading.Thread | None = None
        self._watcher.on_error = on_error or _log_error

    @property
    def watcher(self) -> InboxWatcher:
        return self._watcher

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> BackgroundWatcher:
        if self.running:
            return self
        thread = threading.Thread(target=self._run, name=self._name, daemon=self._daemon)
        self._thread = thread
        thread.start()
        return self

    def stop(self, *, timeout: float | None = 10.0) -> None:
        self._watcher.stop()
        self.join(timeout=timeout)
        self._thread = None
        self._watcher.close()

    def join(self, *, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def __enter__(self) -> BackgroundWatcher:
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def _run(self) -> None:
        for message in self._watcher:
            if self._on_message is None:
                continue
            try:
                self._on_message(message)
            except Exception:
                logger.exception("inbox watcher handler failed for message id=%s", message.id)


def _log_error(exc: BaseException) -> None:
    logger.warning("inbox watch failed: %s", exc)


def _chunks(values: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _sort_key(message: MailMessage) -> tuple[int, str]:
    try:
        return (int(message.id), message.id)
    except ValueError:
        return (0, message.id)
