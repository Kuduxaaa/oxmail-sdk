from __future__ import annotations

from unittest.mock import Mock

from conftest import make_auth
from requests import Response

from oxmail_sdk.mail import Attachment, OutgoingMessage
from oxmail_sdk.mail.service import MailService


def _authenticate(transport, auth) -> None:
    transport.request_json = Mock(  # type: ignore[method-assign]
        return_value={"session": "token", "user": "user@example.com"}
    )
    auth.login(oxguard=False)


def test_send_uses_legacy_multipart_fields() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        response = Response()
        response.status_code = 200
        response._content = b"{}"
        transport.request_relaxed_json = Mock(  # type: ignore[method-assign]
            return_value=(response, {})
        )

        service = MailService(transport, auth)
        result = service.send(
            OutgoingMessage(
                to=("dest@example.com",),
                subject="subject",
                body="body",
                html=False,
            ),
            attachments=(Attachment.from_bytes(b"abc", filename="a.txt"),),
        )

        assert result.successful
        kwargs = transport.request_relaxed_json.call_args.kwargs
        assert kwargs["params"]["action"] == "new"
        assert kwargs["files"][0][0] == "json_0"
        assert kwargs["files"][1][0] == "file_0"
    finally:
        transport.close()


def test_send_simple_normalizes_single_recipient() -> None:
    transport, auth = make_auth()
    try:
        _authenticate(transport, auth)
        response = Response()
        response.status_code = 200
        response._content = b"{}"
        transport.request_relaxed_json = Mock(  # type: ignore[method-assign]
            return_value=(response, {})
        )

        service = MailService(transport, auth)
        result = service.send_simple(
            to="dest@example.com",
            subject="subject",
            body="body",
        )

        assert result.status_code == 200
    finally:
        transport.close()
