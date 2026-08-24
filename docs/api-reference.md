# API reference

Import paths at a glance:

```python
# package root — the everyday surface
from oxmail_sdk import (
    APIError,
    Attachment,
    AuthenticationError,
    BackgroundWatcher,
    Checkpoint,
    CheckpointStore,
    ClientClosedError,
    ClientConfig,
    ConfigurationError,
    Credentials,
    FailoverMailSource,
    FolderState,
    HTTPError,
    HTTPMailSource,
    IMAPConfig,
    IMAPError,
    IMAPMailSource,
    InboxWatcher,
    InvalidResponseError,
    JSONFileCheckpointStore,
    MailAddress,
    MailMessage,
    MailPage,
    MailSource,
    MemoryCheckpointStore,
    NotAuthenticatedError,
    OXMailClient,
    OXMailError,
    OutgoingMessage,
    RetryConfig,
    SendResult,
    SessionInfo,
    TimeoutConfig,
    TransportError,
    __version__,
)

# submodules — constants, helpers and the lower-level classes
from oxmail_sdk.mail import COLUMN_FIELDS, DEFAULT_MAIL_COLUMNS, INBOX_FOLDER
from oxmail_sdk.mail import MailService, mailbox_from_folder, parse_columns
from oxmail_sdk.mail.columns import COLUMN_ID, COLUMN_SUBJECT, FLAG_SEEN
from oxmail_sdk.auth import AuthService
from oxmail_sdk.imap import IMAPConnection, MailboxStatus
from oxmail_sdk.transport import HTTPTransport
```

## OXMailClient

Composition root. Owns the config, transport, `auth` and `mail` services.

```python
class OXMailClient:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        config: ClientConfig | None = None,
        session: Session | None = None,
    ) -> None: ...
```

| Member | Type / signature | Notes |
| --- | --- | --- |
| `config` | `ClientConfig` | the configuration in use |
| `auth` | `AuthService` | session lifecycle |
| `mail` | `MailService` | all mail operations |
| `transport` | `HTTPTransport` | raw HTTP escape hatch |
| `authenticated` | `bool` | is a session held? |
| `closed` | `bool` | has `close()` run? |
| `login(*, oxguard=True)` | `-> SessionInfo` | authenticate |
| `logout()` | `-> None` | end the server session |
| `close(*, logout=False)` | `-> None` | close the HTTP session |

Supports `with OXMailClient(...) as client:` — the exit closes the transport without logging out.

## MailService — `client.mail`

### Reading

```python
def examine(self, *, folder: str = "default0/INBOX") -> FolderState: ...

def recent(
    self,
    *,
    folder: str = "default0/INBOX",
    limit: int = 10,
    columns: str = DEFAULT_MAIL_COLUMNS,
) -> tuple[MailMessage, ...]: ...

def list_by_ids(
    self,
    ids: Iterable[str | int],
    *,
    folder: str = "default0/INBOX",
    columns: str = DEFAULT_MAIL_COLUMNS,
) -> tuple[MailMessage, ...]: ...

def list(
    self,
    *,
    folder: str = "default0/INBOX",
    offset: int = 0,
    limit: int = 50,
    category: str = "general",
    deleted: bool = True,
    sort_column: str = "661",
    order: str = "desc",
    timezone: str = "utc",
) -> MailPage: ...

def iter_messages(
    self,
    *,
    folder: str = "default0/INBOX",
    page_size: int = 50,
    max_messages: int | None = None,
    category: str = "general",
    deleted: bool = True,
) -> Iterator[Any]: ...

def get(
    self,
    mail_id: str | int,
    *,
    folder: str = "default0/INBOX",
    sanitize: bool = False,
    unseen: bool = False,
    max_size: int = 102_400,
    timezone: str = "utc",
) -> Mapping[str, Any]: ...
```

`list()` and `iter_messages()` return **raw column rows**; the others return parsed models. See
[Reading mail](reading.md).

### Watching

```python
def watch(
    self,
    *,
    folder: str = "default0/INBOX",
    interval: float = 15.0,
    backend: str = "auto",
    columns: str = DEFAULT_MAIL_COLUMNS,
    fetch_body: bool = False,
    mark_seen: bool = False,
    include_existing: bool = False,
    backlog_limit: int = 10,
    store: CheckpointStore | None = None,
    key: str | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    recover_after: float = 300.0,
) -> InboxWatcher: ...

def source(
    self,
    *,
    folder: str = "default0/INBOX",
    backend: str = "auto",
    columns: str = DEFAULT_MAIL_COLUMNS,
    mark_seen: bool = False,
    recover_after: float = 300.0,
) -> MailSource: ...
```

`backend` is `"auto"`, `"imap"` or `"http"`; anything else raises `ValueError`.

### Sending

```python
def send(
    self,
    message: OutgoingMessage,
    *,
    attachments: Sequence[Attachment] = (),
) -> SendResult: ...

def send_simple(
    self,
    *,
    to: AddressLike | Sequence[AddressLike],
    subject: str,
    body: str,
    html: bool = True,
    cc: AddressLike | Sequence[AddressLike] | None = None,
    bcc: AddressLike | Sequence[AddressLike] | None = None,
    sender_name: str | None = None,
    priority: int = 3,
    attachments: Sequence[Attachment] = (),
) -> SendResult: ...
```

## AuthService — `client.auth`

| Member | Type / signature |
| --- | --- |
| `username` | `str` |
| `credentials` | `Credentials` |
| `authenticated` | `bool` |
| `session_info` | `SessionInfo \| None` |
| `token` | `str` — raises `NotAuthenticatedError` when absent |
| `login(*, oxguard=True)` | `-> SessionInfo` |
| `ensure_authenticated()` | `-> SessionInfo` |
| `refresh()` | `-> SessionInfo` |
| `run_with_session_retry(operation)` | `Callable[[], T] -> T` |
| `authenticate_oxguard()` | `-> dict[str, Any]` |
| `logout()` | `-> None` |
| `clear_local_session()` | `-> None` |

## InboxWatcher

```python
class InboxWatcher:
    def __init__(
        self,
        source: MailSource,
        *,
        key: str,
        interval: float = 15.0,
        fetch_body: bool = False,
        mark_seen: bool = False,
        include_existing: bool = False,
        backlog_limit: int = 10,
        store: CheckpointStore | None = None,
        batch_size: int = 100,
        seen_history: int = 500,
        on_error: Callable[[BaseException], None] | None = None,
        max_error_delay: float = 300.0,
    ) -> None: ...
```

| Member | Type / signature | Notes |
| --- | --- | --- |
| `poll()` | `-> tuple[MailMessage, ...]` | one check |
| `__iter__()` | `-> Iterator[MailMessage]` | blocking loop |
| `background(*, on_message=None, on_error=None, name=..., daemon=True)` | `-> BackgroundWatcher` | |
| `stop()` | `-> None` | end the loop |
| `close()` | `-> None` | stop and release the backend |
| `reset()` | `-> None` | forget the checkpoint |
| `source` | `MailSource` | the backend object |
| `backend` | `str` | `"imap"` or `"http"` right now |
| `state` | `FolderState \| None` | last observed state |
| `checkpoint` | `Checkpoint \| None` | stored progress |
| `interval`, `key`, `stopped` | `float`, `str`, `bool` | |
| `on_error` | settable attribute | installing one makes iteration resilient |

Context manager: `with client.mail.watch() as watcher:` closes it on exit.

## BackgroundWatcher

```python
class BackgroundWatcher:
    def __init__(
        self,
        watcher: InboxWatcher,
        *,
        on_message: Callable[[MailMessage], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        name: str = "oxmail-inbox-watcher",
        daemon: bool = True,
    ) -> None: ...
```

| Member | Signature |
| --- | --- |
| `start()` | `-> BackgroundWatcher` |
| `stop(*, timeout=10.0)` | `-> None` |
| `join(*, timeout=None)` | `-> None` |
| `running` | `bool` |
| `watcher` | `InboxWatcher` |

Also a context manager (`__enter__` starts, `__exit__` stops).

## MailSource protocol

Implemented by `IMAPMailSource`, `HTTPMailSource` and `FailoverMailSource`; implement it yourself
for tests or exotic backends.

```python
class MailSource(Protocol):
    name: str

    def open(self) -> None: ...
    def close(self) -> None: ...
    def state(self) -> FolderState: ...
    def fetch(self, ids: Sequence[str]) -> tuple[MailMessage, ...]: ...
    def fetch_detail(
        self, message: MailMessage, *, mark_seen: bool
    ) -> Mapping[str, Any] | None: ...
    def recent(self, limit: int) -> tuple[MailMessage, ...]: ...
    def wait(self, timeout: float, stop: threading.Event) -> bool: ...
```

### IMAPMailSource

```python
class IMAPMailSource:
    def __init__(
        self,
        connection: IMAPConnection,
        *,
        folder: str = "default0/INBOX",
        mailbox: str | None = None,
        idle_refresh: float = 540.0,
        readonly: bool = True,
    ) -> None: ...

    @classmethod
    def from_config(
        cls,
        config: IMAPConfig,
        auth: AuthService,
        *,
        host: str,
        folder: str = "default0/INBOX",
        readonly: bool = True,
    ) -> "IMAPMailSource": ...
```

Extra member: `connection` → the underlying `IMAPConnection`.

### HTTPMailSource

```python
class HTTPMailSource:
    def __init__(
        self,
        service: MailService,
        auth: AuthService,
        *,
        folder: str = "default0/INBOX",
        columns: str = DEFAULT_MAIL_COLUMNS,
    ) -> None: ...
```

### FailoverMailSource

```python
class FailoverMailSource:
    def __init__(
        self,
        primary: MailSource,
        fallback: MailSource,
        *,
        recover_after: float = 300.0,
        on_switch: Callable[[str, BaseException | None], None] | None = None,
    ) -> None: ...
```

Extra members: `active` (the source in use), `degraded` (`bool`).

## IMAPConnection

Low-level IMAP wrapper; single-threaded by design.

| Member | Signature |
| --- | --- |
| `IMAPConnection(config, *, host, username, password)` | constructor |
| `connect()` | `-> None` |
| `close()` | `-> None` |
| `select(mailbox, *, readonly=True)` | `-> MailboxStatus` |
| `status(mailbox)` | `-> MailboxStatus` |
| `fetch_headers(uids, *, folder)` | `-> tuple[dict[str, Any], ...]` |
| `fetch_detail(uid, *, folder, peek=True)` | `-> dict[str, Any] \| None` |
| `idle(timeout, stop)` | `-> bool` |
| `connected`, `host`, `capabilities`, `supports_idle` | properties |

`MailboxStatus(uidvalidity, uidnext, messages, unseen)`.

## Models

### MailMessage

Frozen dataclass. Fields: `id`, `folder`, `subject`, `sender`, `to`, `cc`, `bcc`, `received_at`,
`sent_at`, `size`, `priority`, `flags`, `color_label`, `has_attachment`, `content_type`, `preview`,
`user_flags`, `raw`, `detail`.

Properties: `seen`, `unread`, `answered`, `deleted`, `draft`, `flagged`, `forwarded`, `recent`,
`fetched`, `html`, `text`, `body`, `attachments`.

```python
MailMessage.from_mapping(payload, default_folder="")   # field mapping -> model
MailMessage.from_row(columns, row, default_folder="")  # positional column row -> model
message.with_detail(detail)                            # copy carrying a fetched body
```

### MailAddress

```python
MailAddress("john@example.com", "John Doe")
MailAddress.coerce("john@example.com")
```

Rejects addresses without `@`. `AddressLike = MailAddress | str`.

### OutgoingMessage

```python
OutgoingMessage(
    to=("a@example.com",),
    subject="Subject",
    body="<p>Body</p>",
    html=True,
    cc=(),
    bcc=(),
    sender_name=None,
    priority=3,
)
```

### Attachment

```python
Attachment.from_path("./report.pdf")                       # streamed from disk
Attachment.from_bytes(b"data", filename="data.csv")        # kept in memory
Attachment(filename="a.txt", content_type="text/plain", data=b"hi")
attachment.open()                                          # -> BinaryIO
```

Exactly one of `path` / `data` must be set.

### SendResult

Fields `status_code`, `data`, `response_text`; properties `successful`, `server_reference`.

### MailPage

Fields `items`, `raw`, `offset`, `limit`; supports `len()` and iteration over raw rows.

### SessionInfo

Fields `session` (hidden from `repr`), `user`, `user_id`, `context_id`, `locale`.

### FolderState

Fields `validity`, `modseq`, `total`, `unread`, `next_id`, `token`; property `fingerprint`;
classmethod `from_payload(payload)`.

### Checkpoint

Fields `validity`, `next_id`, `fingerprint`, `seen_ids`.

```python
checkpoint.remember(["12", "13"], history=500)   # -> new tuple of seen ids
checkpoint.to_dict()
Checkpoint.from_dict({"validity": "v1", "next_id": 12})
```

### Checkpoint stores

```python
MemoryCheckpointStore()
JSONFileCheckpointStore("inbox-state.json")
```

Both implement `CheckpointStore`: `load(key) -> Checkpoint | None`, `save(key, checkpoint) -> None`.

## Configuration

```python
ClientConfig(
    base_url="https://ultamail.com/appsuite/api",
    locale="en_US",
    client_name="open-xchange-appsuite",
    client_version="8.51.3",
    verify_tls=True,
    timeout=TimeoutConfig(connect=10.0, read=30.0),
    retries=RetryConfig(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504)),
    imap=IMAPConfig(
        host=None,
        port=993,
        use_ssl=True,
        verify_tls=True,
        timeout=20.0,
        idle_refresh=540.0,
        enabled=True,
    ),
    pool_connections=10,
    pool_maxsize=10,
)
```

`user_agent` defaults to `oxmail-sdk/<version>`. Properties on `ClientConfig`: `origin`, `referer`,
`imap_host`.

## Constants

| Name | Module | Value |
| --- | --- | --- |
| `INBOX_FOLDER` | `oxmail_sdk.mail` | `"default0/INBOX"` |
| `DEFAULT_MAIL_COLUMNS` | `oxmail_sdk.mail` | the 19 columns `MailMessage` understands |
| `COLUMN_FIELDS` | `oxmail_sdk.mail` | column id → field name mapping |
| `DEFAULT_INTERVAL` | `oxmail_sdk.mail.watch` | `15.0` |
| `DEFAULT_BATCH_SIZE` | `oxmail_sdk.mail.watch` | `100` |
| `DEFAULT_MAX_ERROR_DELAY` | `oxmail_sdk.mail.watch` | `300.0` |
| `DEFAULT_SEEN_HISTORY` | `oxmail_sdk.mail.state` | `500` |
| `DEFAULT_RECOVER_AFTER` | `oxmail_sdk.mail.sources` | `300.0` |
| `FLAG_SEEN`, `FLAG_ANSWERED`, … | `oxmail_sdk.mail.columns` | IMAP flag bits |

## Exceptions

```text
OXMailError
├── ConfigurationError
├── ClientClosedError
├── NotAuthenticatedError
├── AuthenticationError
├── TransportError
├── IMAPError
├── HTTPError(status_code, method, url, response_preview)
├── InvalidResponseError(message, response_preview)
└── APIError(message, error_id, code, category, raw)   – property: session_expired
```

See [Errors and reliability](errors.md).
