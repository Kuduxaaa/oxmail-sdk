# Errors and reliability

## Exception hierarchy

Everything the SDK raises derives from `OXMailError`, so one `except` clause can contain it all.

```text
OXMailError
├── ConfigurationError      invalid ClientConfig / TimeoutConfig / RetryConfig / IMAPConfig
├── ClientClosedError       a request was attempted after close()
├── NotAuthenticatedError   an authenticated call was made before login()
├── AuthenticationError     the server rejected login or OX Guard
├── TransportError          DNS, connection, TLS or timeout failure
├── IMAPError               IMAP connect, login, command or IDLE failure
├── HTTPError               non-2xx HTTP status
├── InvalidResponseError    the response was not the JSON object we expected
└── APIError                the server answered with an Open-Xchange error payload
```

## Reading each exception

```python
from oxmail_sdk import APIError, HTTPError, InvalidResponseError

try:
    client.mail.list(limit=10)
except APIError as exc:
    exc.message         # human-readable message from the server
    exc.code            # e.g. "SES-0203", "MSG-0032"
    exc.category        # numeric category, as a string
    exc.error_id        # server-side correlation id, useful in support tickets
    exc.raw             # the full payload
    exc.session_expired # True for any SES-* code
except HTTPError as exc:
    exc.status_code, exc.method, exc.url, exc.response_preview
except InvalidResponseError as exc:
    exc.message, exc.response_preview
```

Response previews are truncated to 500 characters and whitespace-collapsed, so logging them is safe.

## What retries, and what does not

| Operation | Retried by the SDK? |
| --- | --- |
| `GET`/`HEAD`/`OPTIONS` requests | Yes — `RetryConfig(total=3)` with backoff, on 429/500/502/503/504, honouring `Retry-After` |
| `POST`/`PUT` (sending, `list_by_ids`) | No |
| A call that failed because the session expired | Yes, once, when wrapped in `run_with_session_retry` (the watcher always is) |
| A failed watch cycle | Yes, when `on_error` is set: backoff doubles per failure up to `max_error_delay` |
| IMAP connection loss under `backend="auto"` | Yes — degrade to HTTP polling, retry IMAP after `recover_after` |

Because sends are never retried, a `TransportError` from `send_simple` means *unknown outcome*, not
*not delivered*. Check the Sent folder before resending if duplicates would be a problem.

## Patterns that work

**Fail fast on configuration, tolerate the network.**

```python
from oxmail_sdk import ConfigurationError, OXMailError, TransportError

try:
    client = OXMailClient(username, password, config=config)
except ConfigurationError:
    raise            # a bug in your deployment; do not retry

try:
    client.login()
except TransportError:
    ...              # transient: retry with backoff
except OXMailError:
    raise            # credentials or server refusal: do not hammer
```

**Distinguish "expired" from "wrong".**

```python
from oxmail_sdk import APIError, AuthenticationError

try:
    messages = client.mail.recent()
except APIError as exc:
    if exc.session_expired:
        client.auth.refresh()
        messages = client.mail.recent()
    else:
        raise
except AuthenticationError:
    alert("credentials rejected")     # re-login will not help
```

**Keep a long-running watcher alive.**

```python
watcher = client.mail.watch(
    on_error=lambda exc: log.warning("watch cycle failed: %s", exc),
)
for message in watcher:
    handle(message)
```

Background watchers already install a logging `on_error`, so they survive failures by default.

**Do not swallow everything.** `except Exception: pass` around a watcher hides credential problems
forever. Log the exception type and let `AuthenticationError` reach a human.

## IMAP-specific failures

`IMAPError` covers unreachable hosts, refused logins, broken IDLE and closed connections. Under
`backend="auto"` you will normally only see it in the logs, because the watcher degrades to HTTP:

```text
WARNING oxmail_sdk.mail.sources: imap backend unavailable (...); falling back to http
```

Under `backend="imap"` it propagates instead, which is what you want when IMAP is a hard
requirement. To check IMAP reachability up front:

```python
from oxmail_sdk import IMAPError

source = client.mail.source(backend="imap")
try:
    source.open()
    print("IMAP ok:", source.connection.capabilities)
finally:
    source.close()
```

## Timeouts

- HTTP: `TimeoutConfig(connect, read)` — raised as `TransportError`.
- IMAP: `IMAPConfig(timeout=...)` for connect/login/commands — raised as `IMAPError`.
- IDLE is not bounded by that timeout; it is bounded by `idle_refresh`, and interrupted immediately
  by `watcher.stop()`.

## Logging

The SDK logs through the standard `logging` module and never prints. Useful loggers:

| Logger | What it reports |
| --- | --- |
| `oxmail_sdk.transport.http` | request method/URL/duration at DEBUG, with secrets redacted |
| `oxmail_sdk.auth.service` | re-authentication at INFO |
| `oxmail_sdk.mail.sources` | backend failover and recovery at WARNING/INFO |
| `oxmail_sdk.mail.watch` | watch-cycle failures and handler errors |
| `oxmail_sdk.imap.connection` | connect/IDLE details at DEBUG |

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("oxmail_sdk.mail.sources").setLevel(logging.DEBUG)
```
