from __future__ import annotations

from requests import Response, Session

from oxmail_sdk.config import ClientConfig
from oxmail_sdk.exceptions import APIError
from oxmail_sdk.transport import HTTPTransport
from oxmail_sdk.transport.parsing import parse_json_object, parse_relaxed_json_object


def _response(body: bytes, *, status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response._content = body
    response.headers["Content-Type"] = "application/json"
    return response


def test_relaxed_parser_accepts_empty_send_response() -> None:
    assert parse_relaxed_json_object(_response(b"")) == {}


def test_parser_raises_api_error() -> None:
    try:
        parse_json_object(_response(b'{"error":"bad"}'))
    except APIError as exc:
        assert str(exc) == "bad"
    else:
        raise AssertionError("APIError was not raised")


def test_transport_does_not_set_global_content_type() -> None:
    transport = HTTPTransport(ClientConfig(), session=Session())
    try:
        assert "Content-Type" not in transport.session.headers
    finally:
        transport.close()
