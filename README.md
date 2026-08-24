# oxmail-sdk

Typed, object-oriented Python SDK for the Open-Xchange mail endpoints used by App Suite deployments.

> This SDK currently targets the authentication and mail flows that have been verified in the
> target Open-Xchange deployment. It does not claim complete coverage of the entire App Suite API.

## Documentation

Full guides live in [docs/](docs/README.md):

| Guide | Contents |
| --- | --- |
| [Getting started](docs/getting-started.md) | install, first script, mental model |
| [Configuration](docs/configuration.md) | `ClientConfig`, timeouts, retries, IMAP settings |
| [Authentication](docs/authentication.md) | sessions, OX Guard, automatic re-authentication |
| [Sending mail](docs/sending.md) | HTML/plain, CC/BCC, attachments, send results |
| [Reading mail](docs/reading.md) | listing, pagination, bodies, `MailMessage` |
| [Watching the inbox](docs/watching.md) | IMAP IDLE, HTTP fallback, checkpoints |
| [Errors and reliability](docs/errors.md) | exception hierarchy, retry semantics, logging |
| [Recipes](docs/recipes.md) | webhooks, auto-responder, ingestion daemon, cron, systemd |
| [Testing](docs/testing.md) | fixtures, fake backends, mocked transport |
| [API reference](docs/api-reference.md) | every public signature |

## Architecture

The package follows separation of concerns:

```text
oxmail_sdk/
├── client.py                  # composition root / public client
├── config.py                  # immutable runtime configuration
├── exceptions.py              # SDK exception hierarchy
├── auth/
│   ├── models.py              # credentials + session DTOs
│   └── service.py             # login / guard / logout lifecycle
├── mail/
│   ├── attachments.py         # attachment sources
│   ├── columns.py             # OX column ids, field names, IMAP flags
│   ├── constants.py           # mail endpoint constants
│   ├── message.py             # parsed message model (headers + body)
│   ├── models.py              # mail DTOs
│   ├── serializer.py          # OX wire-format + multipart serialization
│   ├── service.py             # mail use-cases
│   ├── sources.py             # IMAP / HTTP backends + failover
│   ├── state.py               # folder state + checkpoint persistence
│   └── watch.py               # inbox watching (iterator + worker thread)
├── imap/
│   ├── config.py              # IMAP connection settings
│   ├── connection.py          # imaplib wrapper: select, status, fetch, IDLE
│   └── parsing.py             # IMAP/RFC822 -> SDK model conversion
└── transport/
    ├── http.py                # requests session, pooling, retries, HTTP status
    └── parsing.py             # response parsing + OX API errors
```

`OXMailClient` only wires these pieces together. Mail business logic does not live in the HTTP
transport, and HTTP/multipart details do not live in the public client.

## Requirements

- Python 3.11+
- `requests`
- `urllib3`

## Install

From PyPI after release:

```bash
python -m pip install oxmail-sdk
```

For local development:

```bash
python -m pip install -e '.[dev]'
```

## Basic usage

```python
import os

from oxmail_sdk import OXMailClient

with OXMailClient(
    username=os.environ["OX_USERNAME"],
    password=os.environ["OX_PASSWORD"],
) as client:
    session = client.login()
    print(session.user)

    result = client.mail.send_simple(
        to="recipient@example.com",
        subject="Hello",
        body="<p>Hello from Python.</p>",
    )
    print(result.status_code)
```

## Attachments

```python
from oxmail_sdk import Attachment

result = client.mail.send_simple(
    to=["a@example.com", "b@example.com"],
    subject="Report",
    body="<p>Attached.</p>",
    attachments=[Attachment.from_path("./report.pdf")],
)
```

In-memory attachments are also supported:

```python
attachment = Attachment.from_bytes(
    b"hello\n",
    filename="hello.txt",
    content_type="text/plain",
)
```

## Structured messages

```python
from oxmail_sdk import MailAddress, OutgoingMessage

message = OutgoingMessage(
    to=(MailAddress("john@example.com", "John"),),
    cc=("manager@example.com",),
    subject="Production mail",
    body="<p>Hello John.</p>",
    html=True,
)

result = client.mail.send(message)
```

## Inbox and message retrieval

```python
page = client.mail.list(limit=50)
for row in page:
    print(row)

message = client.mail.get("47")
print(message)
```

Automatic pagination:

```python
for row in client.mail.iter_messages(page_size=100, max_messages=500):
    print(row)
```

## Inbox watching

`client.mail.watch()` delivers new mail as it arrives. Two backends serve the same API: IMAP with
`IDLE` (primary, push, zero idle cost) and HTTP `mail?action=examine` polling (fallback, one ~160
byte request per interval). `backend="auto"` runs IMAP and fails over to HTTP automatically.

```python
for message in client.mail.watch():
    print(message.id, message.sender, message.subject, message.received_at)
```

```python
watcher = client.mail.watch(fetch_body=True).background(
    on_message=lambda message: print("new mail:", message.subject),
)
watcher.start()
...
watcher.stop()
```

Because Open-Xchange mail ids are IMAP UIDs, both backends produce identical message ids and share
their checkpoints, so a failover never replays or drops a message.

```python
from oxmail_sdk import JSONFileCheckpointStore

watcher = client.mail.watch(
    backend="auto",                                        # or "imap" / "http"
    fetch_body=True,                                       # download bodies; peeks by default
    store=JSONFileCheckpointStore("inbox-state.json"),     # resume across restarts
)
```

Full details — backend selection, bodies and attachments, checkpoint stores, failover, error
handling and tuning — are in [docs/watching.md](docs/watching.md).

## Custom configuration

```python
from oxmail_sdk import ClientConfig, OXMailClient, RetryConfig, TimeoutConfig

config = ClientConfig(
    base_url="https://mail.example.com/appsuite/api",
    timeout=TimeoutConfig(connect=5, read=45),
    retries=RetryConfig(total=4, backoff_factor=0.5),
)

client = OXMailClient("user@example.com", "secret", config=config)
```

## Retry policy

Only safe methods (`GET`, `HEAD`, `OPTIONS`) are automatically retried. Login and mail-send `POST`
requests are intentionally not retried because a lost response after a successful send could
otherwise produce duplicate messages.

## Logging and secrets

The package uses standard-library `logging`. It does not intentionally log request bodies, and
known sensitive query parameters are redacted. `Credentials.password` and `SessionInfo.session`
are also excluded from dataclass `repr()` output.

Never commit real credentials or session cookies.

## Development checks

```bash
python -m pytest
python -m ruff check .
python -m mypy src/oxmail_sdk
python -m build
python -m twine check dist/*
```

## TestPyPI

Build first:

```bash
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*
```

Then upload to TestPyPI:

```bash
python -m twine upload --repository testpypi dist/*
```

## PyPI

Manual upload:

```bash
python -m twine upload dist/*
```

For CI/CD, the repository includes a GitHub Actions Trusted Publishing workflow. Configure the
matching Trusted Publisher in PyPI before running the release workflow.
