# Testing your integration

You do not need a server — or a network — to test code built on this SDK.

## Build message fixtures directly

`MailMessage` is a frozen dataclass with two constructors, so fixtures are one line:

```python
from datetime import UTC, datetime

from oxmail_sdk import MailAddress, MailMessage

message = MailMessage(
    id="42",
    folder="default0/INBOX",
    subject="Invoice 2026-08",
    sender=MailAddress("billing@example.com", "Billing"),
    received_at=datetime(2026, 8, 24, 9, 30, tzinfo=UTC),
    flags=32,          # \Seen
    has_attachment=True,
)

assert message.seen and not message.unread
```

From a field mapping (the shape both backends produce):

```python
message = MailMessage.from_mapping(
    {
        "id": "42",
        "folder_id": "default0/INBOX",
        "subject": "Hello",
        "from": [["Ann", "ann@example.com"]],
        "received_date": 1_787_536_476_000,   # epoch millis
        "flags": 0,
    }
)
```

With a body attached:

```python
message = message.with_detail(
    {
        "attachments": [
            {"content_type": "text/plain", "content": "plain body", "disp": "inline"},
            {"content_type": "text/html", "content": "<b>rich</b>", "disp": "inline"},
            {"content_type": "application/pdf", "disp": "attachment", "filename": "a.pdf"},
        ]
    }
)

assert message.body == "<b>rich</b>"
assert [part["filename"] for part in message.attachments] == ["a.pdf"]
```

## Fake the backend, not the network

`MailSource` is a small protocol — implement it and the watcher runs entirely in memory. This is how
the SDK tests itself:

```python
from oxmail_sdk import InboxWatcher, MailMessage
from oxmail_sdk.mail import FolderState


class FakeSource:
    name = "fake"

    def __init__(self):
        self._messages: dict[str, MailMessage] = {}
        self._next_id = 1

    def deliver(self, subject: str) -> str:
        uid = str(self._next_id)
        self._messages[uid] = MailMessage.from_mapping({"id": uid, "subject": subject})
        self._next_id += 1
        return uid

    # -- MailSource protocol ------------------------------------------
    def open(self) -> None: ...

    def close(self) -> None: ...

    def state(self) -> FolderState:
        return FolderState(validity="v1", next_id=self._next_id, total=len(self._messages))

    def fetch(self, ids):
        return tuple(self._messages[uid] for uid in ids if uid in self._messages)

    def fetch_detail(self, message, *, mark_seen):
        return None

    def recent(self, limit):
        return tuple(list(self._messages.values())[-limit:])

    def wait(self, timeout, stop) -> bool:
        return True


def test_only_new_mail_is_delivered():
    source = FakeSource()
    source.deliver("already there")
    watcher = InboxWatcher(source, key="test", interval=0.01)

    assert watcher.poll() == ()                    # the baseline never replays

    source.deliver("first")
    assert [m.subject for m in watcher.poll()] == ["first"]
    assert watcher.poll() == ()                    # and never delivers twice
```

The same fake drives the iterator, so handler code can be tested end to end without a socket:

```python
def test_handler_receives_every_message():
    source, seen = FakeSource(), []
    watcher = InboxWatcher(source, key="test", interval=0.01)
    watcher.poll()
    source.deliver("ping")

    for message in watcher:
        seen.append(message.subject)
        watcher.stop()

    assert seen == ["ping"]
```

## Mock the transport for HTTP-level tests

When you want to assert the exact request the SDK makes, replace the transport methods:

```python
from unittest.mock import Mock

from requests import Session

from oxmail_sdk.auth import AuthService, Credentials
from oxmail_sdk.config import ClientConfig
from oxmail_sdk.mail.service import MailService
from oxmail_sdk.transport import HTTPTransport


def make_service():
    transport = HTTPTransport(ClientConfig(), session=Session())
    auth = AuthService(transport, Credentials("user@example.com", "secret"))
    transport.request_json = Mock(return_value={"session": "token"})
    auth.login(oxguard=False)
    return transport, auth, MailService(transport, auth)


def test_recent_requests_the_inbox():
    transport, _auth, service = make_service()
    transport.request_json = Mock(return_value={"data": []})

    service.recent(limit=5)

    params = transport.request_json.call_args.kwargs["params"]
    assert params["action"] == "all"
    assert params["limit"] == "0,5"
```

Always pin `backend="http"` in tests that go through `MailService.watch()`, otherwise the default
`auto` backend will try to open a real IMAP connection:

```python
watcher = service.watch(interval=1, backend="http")
```

## Checkpoint stores in tests

`JSONFileCheckpointStore` works with pytest's `tmp_path`, and an in-memory store needs no setup:

```python
from oxmail_sdk import JSONFileCheckpointStore, MemoryCheckpointStore
from oxmail_sdk.mail import Checkpoint


def test_state_survives_a_restart(tmp_path):
    path = tmp_path / "state.json"
    JSONFileCheckpointStore(path).save("key", Checkpoint(validity="v1", next_id=12))

    reloaded = JSONFileCheckpointStore(path).load("key")
    assert reloaded.next_id == 12


def test_memory_store_is_empty_at_first():
    assert MemoryCheckpointStore().load("key") is None
```

## Testing against a real server

Keep live tests separate and opt-in:

```python
import os

import pytest

live = pytest.mark.skipif(
    not os.environ.get("OX_LIVE_TESTS"),
    reason="set OX_LIVE_TESTS=1 to run tests against a real account",
)


@live
def test_send_and_receive_roundtrip():
    from oxmail_sdk import OXMailClient

    with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
        client.login(oxguard=False)
        watcher = client.mail.watch(backend="imap")
        watcher.poll()                                  # baseline

        subject = f"roundtrip {os.urandom(4).hex()}"
        client.mail.send_simple(to=client.auth.username, subject=subject, body="hi")

        seen = []
        watcher.on_error = lambda exc: watcher.stop()
        for message in watcher:
            seen.append(message.subject)
            watcher.stop()

        assert subject in seen
```

Send to the account itself so the test needs no second mailbox, and give delivery a generous
timeout — mail servers are allowed to take a few seconds.

## Running the SDK's own checks

```bash
python -m pytest -q
python -m ruff check src tests examples
python -m mypy src
```
