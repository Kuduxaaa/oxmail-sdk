from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from conftest import make_auth

from oxmail_sdk.exceptions import APIError
from oxmail_sdk.mail import JSONFileCheckpointStore, MemoryCheckpointStore
from oxmail_sdk.mail.constants import DEFAULT_MAIL_COLUMNS
from oxmail_sdk.mail.message import MailMessage
from oxmail_sdk.mail.service import MailService
from oxmail_sdk.mail.state import Checkpoint, FolderState

COLUMNS = ("600", "601", "603", "607", "610", "611")


def _authenticate(transport, auth) -> None:
    transport.request_json = Mock(  # type: ignore[method-assign]
        return_value={"session": "token", "user": "user@example.com"}
    )
    auth.login(oxguard=False)


def _examine(*, modseq: str, next_id: int, total: int = 1, unread: int = 1, validity: str = "v1"):
    token = f"{validity}:{modseq}:{next_id}"
    return {
        "data": {
            "validity": validity,
            "modseq": modseq,
            "total": total,
            "unread": unread,
            "next": str(next_id),
            "token": token,
        }
    }


def _row(uid: str, subject: str = "hello", flags: int = 16) -> list[object]:
    return [
        uid,
        "default0/INBOX",
        [[None, "sender@example.com"]],
        subject,
        1_700_000_000_000,
        flags,
    ]


def test_folder_state_fingerprint_falls_back_to_counters() -> None:
    state = FolderState.from_payload(
        {"data": {"validity": "v1", "modseq": "7", "total": 3, "unread": 1, "next": "9"}}
    )
    assert state.next_id == 9
    assert state.token is None
    assert state.fingerprint == "v1:7:3:1:9"


def test_message_parses_columns_and_flags() -> None:
    message = MailMessage.from_row(COLUMNS, _row("8", "subject", flags=33))
    assert message.id == "8"
    assert message.sender is not None and message.sender.email == "sender@example.com"
    assert message.subject == "subject"
    assert message.received_at is not None
    assert message.seen and message.answered and not message.unread


def test_message_body_prefers_html_and_lists_attachments() -> None:
    message = MailMessage.from_row(COLUMNS, _row("8")).with_detail(
        {
            "attachments": [
                {"content_type": "text/plain", "content": "plain", "disp": "inline"},
                {"content_type": "text/html; charset=UTF-8", "content": "<b>x</b>"},
                {"content_type": "application/pdf", "disp": "attachment", "filename": "a.pdf"},
            ]
        }
    )
    assert message.fetched
    assert message.body == "<b>x</b>"
    assert message.text == "plain"
    assert len(message.attachments) == 1


def test_first_poll_only_establishes_a_baseline() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            return_value=_examine(modseq="5", next_id=8)
        )
        watcher = MailService(transport, auth).watch(interval=1, backend="http")

        assert watcher.poll() == ()
        checkpoint = watcher.checkpoint
        assert checkpoint is not None
        assert checkpoint.next_id == 8
        assert transport.request_json.call_count == 1
    finally:
        transport.close()


def test_unchanged_fingerprint_skips_the_listing_request() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            return_value=_examine(modseq="5", next_id=8)
        )
        watcher = MailService(transport, auth).watch(interval=1, backend="http")
        watcher.poll()

        assert watcher.poll() == ()
        assert transport.request_json.call_count == 2  # examine only, never a list
    finally:
        transport.close()


def test_new_uids_are_fetched_once_and_remembered() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        responses = [
            _examine(modseq="5", next_id=8),
            _examine(modseq="6", next_id=10, total=3, unread=2),
            {"data": [_row("9", "second"), _row("8", "first")]},
            _examine(modseq="6", next_id=10, total=3, unread=2),
        ]
        transport.request_json = Mock(side_effect=responses)  # type: ignore[method-assign]
        watcher = MailService(transport, auth).watch(
            interval=1, backend="http", columns=",".join(COLUMNS)
        )

        assert watcher.poll() == ()
        messages = watcher.poll()

        assert [message.id for message in messages] == ["8", "9"]
        list_call = transport.request_json.call_args_list[2]
        assert list_call.args[0] == "PUT"
        assert list_call.kwargs["params"]["action"] == "list"
        assert list_call.kwargs["json_body"] == [
            {"folder": "default0/INBOX", "id": "8"},
            {"folder": "default0/INBOX", "id": "9"},
        ]
        assert watcher.poll() == ()
    finally:
        transport.close()


def test_uidvalidity_change_rebuilds_the_baseline_without_replaying() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            side_effect=[
                _examine(modseq="5", next_id=8, validity="v1"),
                _examine(modseq="1", next_id=4, validity="v2"),
            ]
        )
        watcher = MailService(transport, auth).watch(interval=1, backend="http")
        watcher.poll()

        assert watcher.poll() == ()
        checkpoint = watcher.checkpoint
        assert checkpoint is not None
        assert checkpoint.validity == "v2"
        assert checkpoint.next_id == 4
    finally:
        transport.close()


def test_expired_session_triggers_one_reauthentication() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        expired = APIError(message="session expired", code="SES-0203")
        transport.request_json = Mock(  # type: ignore[method-assign]
            side_effect=[
                expired,
                {"session": "fresh-token", "user": "user@example.com"},
                _examine(modseq="5", next_id=8),
            ]
        )
        watcher = MailService(transport, auth).watch(interval=1, backend="http")

        assert watcher.poll() == ()
        assert auth.token == "fresh-token"
        assert transport.request_json.call_args_list[1].args[1] == "login"
    finally:
        transport.close()


def test_iteration_stops_between_ticks() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            side_effect=[
                _examine(modseq="5", next_id=8),
                _examine(modseq="6", next_id=9),
                {"data": [_row("8")]},
            ]
        )
        watcher = MailService(transport, auth).watch(
            interval=0.01, backend="http", columns=",".join(COLUMNS)
        )

        seen = []
        for message in watcher:
            seen.append(message.id)
            watcher.stop()

        assert seen == ["8"]
    finally:
        transport.close()


def test_poll_errors_propagate_until_an_error_handler_is_set() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            side_effect=APIError(message="boom", code="MSG-0001")
        )
        watcher = MailService(transport, auth).watch(interval=0.01, backend="http")

        try:
            next(iter(watcher))
        except APIError as exc:
            assert exc.code == "MSG-0001"
        else:  # pragma: no cover - defensive
            raise AssertionError("APIError was not raised")

        errors: list[BaseException] = []
        watcher.on_error = lambda exc: (errors.append(exc), watcher.stop())[0]
        list(watcher)
        assert len(errors) == 1
    finally:
        transport.close()


def test_default_columns_are_requested_when_not_overridden() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        transport.request_json = Mock(  # type: ignore[method-assign]
            return_value={"data": []}
        )
        service = MailService(transport, auth)
        service.list_by_ids(["1"])

        params = transport.request_json.call_args.kwargs["params"]
        assert params["columns"] == DEFAULT_MAIL_COLUMNS
    finally:
        transport.close()


def test_checkpoint_history_is_bounded() -> None:
    checkpoint = Checkpoint(seen_ids=("1", "2", "3"))
    assert checkpoint.remember(["3", "4"], history=3) == ("2", "3", "4")


def test_memory_store_roundtrip() -> None:
    store = MemoryCheckpointStore()
    assert store.load("k") is None
    store.save("k", Checkpoint(validity="v1", next_id=3, fingerprint="f"))
    loaded = store.load("k")
    assert loaded is not None and loaded.next_id == 3


def test_json_file_store_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.json"
    JSONFileCheckpointStore(path).save(
        "user|default0/INBOX",
        Checkpoint(validity="v1", next_id=12, fingerprint="f", seen_ids=("11",)),
    )

    reloaded = JSONFileCheckpointStore(path).load("user|default0/INBOX")
    assert reloaded is not None
    assert reloaded.next_id == 12
    assert reloaded.seen_ids == ("11",)
    assert json.loads(path.read_text(encoding="utf-8"))["user|default0/INBOX"]["fingerprint"] == "f"


def test_json_file_store_ignores_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert JSONFileCheckpointStore(path).load("k") is None
