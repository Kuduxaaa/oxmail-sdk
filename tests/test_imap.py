from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from oxmail_sdk.config import ClientConfig
from oxmail_sdk.exceptions import ConfigurationError, IMAPError
from oxmail_sdk.imap.config import IMAPConfig
from oxmail_sdk.imap.parsing import flags_to_bits, header_row, parse_fetch_items, rfc822_to_detail
from oxmail_sdk.mail.message import MailMessage
from oxmail_sdk.mail.sources import FailoverMailSource, mailbox_from_folder
from oxmail_sdk.mail.state import FolderState
from oxmail_sdk.mail.watch import InboxWatcher

FETCH_PREFIX = (
    b"9 (UID 9 FLAGS (\\Seen $HasAttachment) RFC822.SIZE 4109 "
    b'INTERNALDATE "24-Aug-2026 02:01:06 +0000" BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {120}'
)
FETCH_HEADERS = (
    b"Date: Mon, 24 Aug 2026 02:01:04 +0000\r\n"
    b"From: =?utf-8?B?0JDQvdC90LA=?= <sender@example.com>\r\n"
    b"Subject: =?utf-8?B?4YOS4YOQ4YOV4YOQ?=\r\n\r\n"
)

RAW_MESSAGE = (
    b"Subject: hello\r\n"
    b"From: sender@example.com\r\n"
    b'Content-Type: multipart/mixed; boundary="b1"\r\n'
    b"\r\n"
    b"--b1\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"plain body\r\n"
    b"--b1\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n\r\n"
    b"<b>rich body</b>\r\n"
    b"--b1\r\n"
    b'Content-Type: application/pdf; name="a.pdf"\r\n'
    b'Content-Disposition: attachment; filename="a.pdf"\r\n\r\n'
    b"%PDF-1.4\r\n"
    b"--b1--\r\n"
)


class FakeSource:
    def __init__(self, name: str, *, fails: bool = False) -> None:
        self.name = name
        self.fails = fails
        self.opened = 0
        self.closed = 0
        self.waits = 0

    def open(self) -> None:
        self.opened += 1
        if self.fails:
            raise IMAPError(f"{self.name} is down")

    def close(self) -> None:
        self.closed += 1

    def state(self) -> FolderState:
        self._check()
        return FolderState(validity="v1", next_id=5, total=4, unread=1)

    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]:
        self._check()
        return tuple(
            MailMessage.from_mapping({"id": value, "subject": f"{self.name}-{value}"})
            for value in ids
        )

    def fetch_detail(self, message: MailMessage, *, mark_seen: bool) -> Mapping[str, Any] | None:
        self._check()
        return {"attachments": [{"content_type": "text/plain", "content": self.name}]}

    def recent(self, limit: int) -> tuple[MailMessage, ...]:
        self._check()
        return ()

    def wait(self, timeout: float, stop: threading.Event) -> bool:
        self.waits += 1
        self._check()
        return True

    def _check(self) -> None:
        if self.fails:
            raise IMAPError(f"{self.name} is down")


def test_imap_host_is_derived_from_the_api_base_url() -> None:
    assert ClientConfig().imap_host == "imap.ultamail.com"
    assert ClientConfig(base_url="https://www.example.org/api").imap_host == "imap.example.org"
    assert ClientConfig(base_url="https://imap.example.org/api").imap_host == "imap.example.org"
    assert IMAPConfig(host="mx.example.net").resolve_host("https://a.b/api") == "mx.example.net"


def test_invalid_imap_settings_are_rejected() -> None:
    with pytest.raises(ConfigurationError):
        IMAPConfig(port=0)
    with pytest.raises(ConfigurationError):
        IMAPConfig(timeout=0)
    with pytest.raises(ConfigurationError):
        IMAPConfig(host="  ")


def test_folder_ids_map_to_imap_mailboxes() -> None:
    assert mailbox_from_folder("default0/INBOX") == "INBOX"
    assert mailbox_from_folder("default0/INBOX/Work") == "INBOX/Work"
    assert mailbox_from_folder("INBOX") == "INBOX"


def test_imap_flags_map_onto_open_xchange_bits() -> None:
    bits, user_flags = flags_to_bits(["\\Seen", "\\Answered", "$Custom"])
    assert bits == 33
    assert user_flags == ("$Custom",)


def test_fetch_response_becomes_a_mail_message() -> None:
    items = parse_fetch_items([(FETCH_PREFIX, FETCH_HEADERS), b")"])
    assert len(items) == 1

    row = header_row(*items[0], folder="default0/INBOX")
    assert row is not None
    message = MailMessage.from_mapping(row)

    assert message.id == "9"
    assert message.folder == "default0/INBOX"
    assert message.subject == "გავა"
    assert message.sender is not None
    assert message.sender.email == "sender@example.com"
    assert message.sender.name == "Анна"
    assert message.seen and message.has_attachment
    assert message.size == 4109
    assert message.received_at is not None
    assert message.received_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-08-24 02:01:06"


def test_raw_message_detail_matches_the_http_shape() -> None:
    detail = rfc822_to_detail(RAW_MESSAGE, folder="default0/INBOX", uid="9")
    message = MailMessage.from_mapping({"id": "9"}).with_detail(detail)

    assert message.text == "plain body"
    assert message.html == "<b>rich body</b>"
    assert message.body == "<b>rich body</b>"
    assert [part["filename"] for part in message.attachments] == ["a.pdf"]


def test_failover_switches_to_the_fallback_backend() -> None:
    primary, fallback = FakeSource("imap", fails=True), FakeSource("http")
    switches: list[str] = []
    source = FailoverMailSource(
        primary,
        fallback,
        recover_after=1_000,
        on_switch=lambda name, exc: switches.append(name),
    )

    source.open()

    assert source.degraded
    assert source.name == "http"
    assert switches == ["http"]
    assert fallback.opened == 1
    assert source.state().next_id == 5
    assert [message.subject for message in source.fetch(["1"])] == ["http-1"]


def test_failover_survives_a_primary_that_breaks_mid_run() -> None:
    primary, fallback = FakeSource("imap"), FakeSource("http")
    source = FailoverMailSource(primary, fallback, recover_after=1_000)
    source.open()
    assert not source.degraded

    primary.fails = True
    messages = source.fetch(["7"])

    assert source.degraded
    assert [message.subject for message in messages] == ["http-7"]
    assert primary.closed == 1


def test_failover_retries_the_primary_after_the_recovery_window() -> None:
    primary, fallback = FakeSource("imap", fails=True), FakeSource("http")
    source = FailoverMailSource(primary, fallback, recover_after=0)
    source.open()
    assert source.degraded

    primary.fails = False
    source.wait(0.01, threading.Event())

    assert not source.degraded
    assert source.name == "imap"


def test_watcher_reports_and_closes_its_backend() -> None:
    source = FakeSource("imap")
    watcher = InboxWatcher(source, key="user|default0/INBOX", interval=1)

    assert watcher.backend == "imap"
    assert watcher.poll() == ()
    assert source.opened == 1

    watcher.close()
    assert source.closed == 1
    assert watcher.stopped
