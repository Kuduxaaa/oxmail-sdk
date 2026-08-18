from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import requests
from requests import Response

from ..exceptions import APIError, InvalidResponseError

JsonObject = dict[str, Any]


def parse_json_object(response: Response) -> JsonObject:
    """Parse a strict JSON-object response and surface OX API errors."""

    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise InvalidResponseError(
            "server returned non-JSON data",
            response_preview(response.text),
        ) from exc

    return _validate_payload(payload)


def parse_relaxed_json_object(response: Response) -> JsonObject:
    """Parse normal, empty, or legacy HTML-wrapped JSON responses."""

    text = response.text.strip()
    if not text:
        return {}

    payload: Any
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(
                "could not parse Open-Xchange response",
                response_preview(text),
            ) from exc

    return _validate_payload(payload)


def response_preview(text: str, max_chars: int = 500) -> str:
    compact = " ".join(text.split())
    return compact[:max_chars]


def _validate_payload(payload: Any) -> JsonObject:
    if not isinstance(payload, dict):
        raise InvalidResponseError(
            f"expected JSON object, got {type(payload).__name__}"
        )
    _raise_api_error(payload)
    return payload


def _raise_api_error(payload: Mapping[str, Any]) -> None:
    if payload.get("error") or payload.get("error_id"):
        raise APIError.from_payload(payload)
