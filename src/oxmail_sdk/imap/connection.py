from __future__ import annotations

import imaplib
import logging
import re
import select
import ssl
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..exceptions import IMAPError
from .config import IMAPConfig
from .parsing import HEADER_FIELDS, header_row, parse_fetch_items, rfc822_to_detail

logger = logging.getLogger(__name__)

_STATUS_ITEMS = "(MESSAGES UNSEEN UIDNEXT UIDVALIDITY)"
_STATUS_RE = re.compile(r"(\w+)\s+(\d+)")
_READ_SLICE = 1.0


@dataclass(frozen=True, slots=True)
class MailboxStatus:
    """Result of an IMAP ``STATUS`` command."""

    uidvalidity: str | None
    uidnext: int
    messages: int
    unseen: int


class IMAPConnection:
    """Thin imaplib wrapper: connect, select, status, fetch and IDLE.

    A connection is owned by one thread; the watcher never shares it.
    """

    def __init__(
        self,
        config: IMAPConfig,
        *,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._config = config
        self._host = host
        self._username = username
        self._password = password
        self._imap: imaplib.IMAP4 | None = None
        self._mailbox: str | None = None
        self._readonly = True

    # -- lifecycle --------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._imap is not None

    @property
    def host(self) -> str:
        return self._host

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self._imap.capabilities) if self._imap else ()

    @property
    def supports_idle(self) -> bool:
        return "IDLE" in self.capabilities

    def connect(self) -> None:
        if self._imap is not None:
            return
        try:
            if self._config.use_ssl:
                context = ssl.create_default_context()
                if not self._config.verify_tls:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                    self._host,
                    self._config.port,
                    ssl_context=context,
                    timeout=self._config.timeout,
                )
            else:
                client = imaplib.IMAP4(self._host, self._config.port, timeout=self._config.timeout)
            client.login(self._username, self._password)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise IMAPError(f"IMAP connection to {self._host} failed: {exc}") from exc

        self._imap = client
        self._mailbox = None
        logger.debug("IMAP connected to %s as %s", self._host, self._username)

    def close(self) -> None:
        client, self._imap = self._imap, None
        self._mailbox = None
        if client is None:
            return
        try:
            if client.state == "SELECTED":
                client.close()
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            logger.debug("IMAP logout failed; dropping the socket", exc_info=True)

    # -- commands ---------------------------------------------------------
    def select(self, mailbox: str, *, readonly: bool = True) -> MailboxStatus:
        client = self._require()
        if self._mailbox != mailbox or self._readonly != readonly:
            typ, data = self._run(client.select, mailbox, readonly)
            if typ != "OK":
                raise IMAPError(f"cannot select mailbox {mailbox!r}: {_first(data)}")
            self._mailbox = mailbox
            self._readonly = readonly
        return self.status(mailbox)

    def status(self, mailbox: str) -> MailboxStatus:
        client = self._require()
        typ, data = self._run(client.status, mailbox, _STATUS_ITEMS)
        if typ != "OK" or not data:
            raise IMAPError(f"STATUS failed for {mailbox!r}: {_first(data)}")

        text = _first(data)
        values = {key.upper(): int(value) for key, value in _STATUS_RE.findall(text)}
        return MailboxStatus(
            uidvalidity=str(values["UIDVALIDITY"]) if "UIDVALIDITY" in values else None,
            uidnext=values.get("UIDNEXT", 0),
            messages=values.get("MESSAGES", 0),
            unseen=values.get("UNSEEN", 0),
        )

    def fetch_headers(self, uids: Sequence[str], *, folder: str) -> tuple[dict[str, Any], ...]:
        """Fetch envelope data for the given UIDs, skipping any that vanished."""

        if not uids:
            return ()
        client = self._require()
        fields = " ".join(HEADER_FIELDS)
        typ, data = self._run(
            client.uid,
            "FETCH",
            ",".join(uids),
            f"(UID FLAGS RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER.FIELDS ({fields})])",
        )
        if typ != "OK":
            raise IMAPError(f"UID FETCH failed: {_first(data)}")

        rows = []
        for prefix, literal in parse_fetch_items(data):
            row = header_row(prefix, literal, folder=folder)
            if row is not None:
                rows.append(row)
        return tuple(rows)

    def fetch_detail(
        self,
        uid: str,
        *,
        folder: str,
        peek: bool = True,
    ) -> dict[str, Any] | None:
        """Fetch one full message and shape it like the HTTP ``get`` payload."""

        client = self._require()
        section = "BODY.PEEK[]" if peek else "BODY[]"
        typ, data = self._run(client.uid, "FETCH", uid, f"({section})")
        if typ != "OK":
            raise IMAPError(f"UID FETCH {uid} failed: {_first(data)}")

        for _prefix, literal in parse_fetch_items(data):
            if literal:
                return rfc822_to_detail(literal, folder=folder, uid=uid)
        return None

    def idle(self, timeout: float, stop: threading.Event) -> bool:
        """Block in IDLE until the server reports activity, or the timeout expires.

        Returns ``True`` when the mailbox may have changed.
        """

        client = self._require()
        if not self.supports_idle:
            return not stop.wait(timeout)

        tag = client._new_tag()  # noqa: SLF001 - imaplib exposes no public IDLE
        try:
            client.send(tag + b" IDLE\r\n")
            response = client.readline()
        except (OSError, imaplib.IMAP4.error) as exc:
            raise IMAPError(f"IDLE could not be started: {exc}") from exc
        if not response.startswith(b"+"):
            raise IMAPError(f"server refused IDLE: {response!r}")

        try:
            return self._idle_wait(client, timeout, stop)
        finally:
            self._idle_done(client, tag)

    # -- internals --------------------------------------------------------
    def _idle_wait(self, client: imaplib.IMAP4, timeout: float, stop: threading.Event) -> bool:
        remaining = timeout
        while remaining > 0 and not stop.is_set():
            slice_seconds = min(_READ_SLICE, remaining)
            remaining -= slice_seconds
            if not _readable(client.sock, slice_seconds):
                continue
            try:
                line = client.readline()
            except (OSError, imaplib.IMAP4.error) as exc:
                raise IMAPError(f"IDLE connection lost: {exc}") from exc
            if not line:
                raise IMAPError("IDLE connection closed by the server")
            logger.debug("IDLE notification: %s", line.strip())
            return True
        return False

    def _idle_done(self, client: imaplib.IMAP4, tag: bytes) -> None:
        try:
            client.send(b"DONE\r\n")
            while True:
                line = client.readline()
                if not line or line.startswith(tag):
                    break
        except (OSError, imaplib.IMAP4.error) as exc:
            self.close()
            raise IMAPError(f"could not leave IDLE: {exc}") from exc

    def _require(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise IMAPError("IMAP connection is not open")
        return self._imap

    def _run(self, command: Any, *args: Any) -> tuple[str, list[Any]]:
        try:
            typ, data = command(*args)
        except (OSError, imaplib.IMAP4.error) as exc:
            self.close()
            raise IMAPError(f"IMAP command failed: {exc}") from exc
        return typ, list(data)


def _readable(sock: Any, timeout: float) -> bool:
    if isinstance(sock, ssl.SSLSocket) and sock.pending():
        return True
    try:
        ready, _, _ = select.select([sock], [], [], timeout)
    except (OSError, ValueError) as exc:
        raise IMAPError(f"IDLE socket is not usable: {exc}") from exc
    return bool(ready)


def _first(data: Sequence[Any]) -> str:
    for entry in data:
        if isinstance(entry, bytes):
            return entry.decode("utf-8", "replace")
        if isinstance(entry, str):
            return entry
    return ""
