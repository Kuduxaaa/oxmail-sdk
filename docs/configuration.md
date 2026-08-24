# Configuration

Everything is configured through one immutable object, `ClientConfig`, passed to the client:

```python
from oxmail_sdk import ClientConfig, IMAPConfig, OXMailClient, RetryConfig, TimeoutConfig

config = ClientConfig(
    base_url="https://mail.example.com/appsuite/api",
    locale="en_US",
    verify_tls=True,
    timeout=TimeoutConfig(connect=5.0, read=30.0),
    retries=RetryConfig(total=5, backoff_factor=0.3),
    imap=IMAPConfig(host="imap.example.com", idle_refresh=540.0),
    pool_connections=10,
    pool_maxsize=10,
)

client = OXMailClient("me@example.com", "secret", config=config)
```

All config dataclasses are frozen and validated on construction: bad values raise
`ConfigurationError` immediately rather than failing on the first request.

## ClientConfig

| Field | Default | Meaning |
| --- | --- | --- |
| `base_url` | `https://ultamail.com/appsuite/api` | Absolute `http(s)` URL of the App Suite API. Trailing slashes are stripped. |
| `locale` | `en_US` | Sent with login; also used as the OX Guard language. |
| `client_name` | `open-xchange-appsuite` | Client identifier sent at login. |
| `client_version` | `8.51.3` | Client version sent at login. |
| `user_agent` | `oxmail-sdk/<version>` | `User-Agent` header. |
| `verify_tls` | `True` | `False` disables verification, or pass a CA bundle path. |
| `timeout` | `TimeoutConfig()` | Connect/read timeouts for HTTP. |
| `retries` | `RetryConfig()` | Retry policy for safe HTTP methods. |
| `imap` | `IMAPConfig()` | IMAP backend settings. |
| `pool_connections` / `pool_maxsize` | `10` / `10` | urllib3 connection pool sizing. |

Derived, read-only properties:

```python
config.origin      # "https://mail.example.com"
config.referer     # "https://mail.example.com/appsuite/"
config.imap_host   # "imap.example.com"
```

## TimeoutConfig

```python
TimeoutConfig(connect=10.0, read=30.0)
```

Both must be greater than zero. They apply to HTTP only; IMAP has its own timeout.

## RetryConfig

```python
RetryConfig(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
```

Retries are applied **only to idempotent methods** (`GET`, `HEAD`, `OPTIONS`). Sending mail is a
`POST` and is never retried automatically, so a message cannot be delivered twice by the SDK.
`Retry-After` headers are respected.

## IMAPConfig

```python
IMAPConfig(
    host=None,           # None -> derived from base_url
    port=993,
    use_ssl=True,
    verify_tls=True,
    timeout=20.0,
    idle_refresh=540.0,
    enabled=True,
)
```

- **`host`** — when `None`, the API host is used with an `imap.` prefix
  (`mail.example.com` → `imap.example.com`; a host already starting with `imap.`/`mail.` is used
  as-is; a leading `www.` is stripped).
- **`idle_refresh`** — how long a single IDLE command is held before being re-issued. Servers drop
  idle connections after ~30 minutes; 9 minutes is a safe default.
- **`enabled=False`** — pins `backend="auto"` to HTTP polling. Useful when IMAP is firewalled off
  and you would rather not pay for a failed connection attempt on every start.
- **`timeout`** — socket timeout for connect, login and command round-trips.

Check what the derivation produced before you deploy:

```pycon
>>> ClientConfig(base_url="https://webmail.corp.example/appsuite/api").imap_host
'imap.webmail.corp.example'
```

If that is wrong for your deployment, set `IMAPConfig(host=...)` explicitly.

## Configuring from the environment

```python
import os

from oxmail_sdk import ClientConfig, IMAPConfig, TimeoutConfig


def config_from_env() -> ClientConfig:
    return ClientConfig(
        base_url=os.environ.get("OX_BASE_URL", "https://ultamail.com/appsuite/api"),
        verify_tls=os.environ.get("OX_VERIFY_TLS", "1") != "0",
        timeout=TimeoutConfig(
            connect=float(os.environ.get("OX_CONNECT_TIMEOUT", "10")),
            read=float(os.environ.get("OX_READ_TIMEOUT", "30")),
        ),
        imap=IMAPConfig(
            host=os.environ.get("OX_IMAP_HOST") or None,
            port=int(os.environ.get("OX_IMAP_PORT", "993")),
            enabled=os.environ.get("OX_IMAP", "1") != "0",
        ),
    )
```

## Bringing your own `requests.Session`

Pass a pre-built session to reuse proxies, custom adapters or corporate TLS settings. The SDK still
applies its own headers and retry adapter to it:

```python
import requests

session = requests.Session()
session.proxies = {"https": "http://proxy.corp:3128"}

client = OXMailClient("me@example.com", "secret", session=session)
```

## Changing configuration later

`ClientConfig` is frozen — build a new one with `dataclasses.replace` and a new client:

```python
from dataclasses import replace

slower = replace(client.config, timeout=TimeoutConfig(connect=5, read=120))
patient_client = OXMailClient("me@example.com", "secret", config=slower)
```
