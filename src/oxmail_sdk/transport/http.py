from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import ClientConfig
from ..exceptions import ClientClosedError, HTTPError, TransportError
from .parsing import JsonObject, parse_json_object, parse_relaxed_json_object, response_preview

logger = logging.getLogger(__name__)

_SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SENSITIVE_PARAM_KEYS = frozenset({"session", "password", "token", "access_token"})


class HTTPTransport:
    """HTTP-only layer: headers, cookies, pooling, retries, and response status."""

    def __init__(self, config: ClientConfig, *, session: Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        self._closed = False
        self._configure_session()

    @property
    def closed(self) -> bool:
        return self._closed

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        json_body: Any = None,
        files: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        if self._closed:
            raise ClientClosedError("HTTP transport is closed")

        verb = method.upper()
        url = self._url(path)
        started = time.monotonic()
        logger.debug("OX request %s %s params=%s", verb, url, _redact(params or {}))

        try:
            response = self.session.request(
                method=verb,
                url=url,
                params=params,
                data=data,
                json=json_body,
                files=files,
                headers=headers,
                timeout=self.config.timeout.requests_value,
                verify=self.config.verify_tls,
            )
        except requests.RequestException as exc:
            raise TransportError(f"request failed for {verb} {url}: {exc}") from exc
        finally:
            logger.debug(
                "OX request %s %s finished in %.3fs",
                verb,
                url,
                time.monotonic() - started,
            )

        if response.status_code >= 400:
            raise HTTPError(
                status_code=response.status_code,
                method=verb,
                url=response.url,
                response_preview=response_preview(response.text),
            )
        return response

    def request_json(self, method: str, path: str, **kwargs: Any) -> JsonObject:
        return parse_json_object(self.request(method, path, **kwargs))

    def request_relaxed_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> tuple[Response, JsonObject]:
        response = self.request(method, path, **kwargs)
        return response, parse_relaxed_json_object(response)

    def close(self) -> None:
        if self._closed:
            return
        self.session.close()
        self._closed = True

    def _configure_session(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": self.config.origin,
                "Referer": self.config.referer,
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
            }
        )

        retry = Retry(
            total=self.config.retries.total,
            connect=self.config.retries.total,
            read=self.config.retries.total,
            status=self.config.retries.total,
            backoff_factor=self.config.retries.backoff_factor,
            status_forcelist=self.config.retries.status_forcelist,
            allowed_methods=_SAFE_RETRY_METHODS,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=self.config.pool_connections,
            pool_maxsize=self.config.pool_maxsize,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.config.base_url}/{path.lstrip('/')}"


def _redact(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "<redacted>" if key.lower() in _SENSITIVE_PARAM_KEYS else value
        for key, value in params.items()
    }
