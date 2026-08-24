# Sending mail

Two entry points, same wire format:

- `client.mail.send_simple(...)` — keyword arguments, best for everyday sending.
- `client.mail.send(message, attachments=...)` — takes an `OutgoingMessage`, best when the message
  is built elsewhere (a queue payload, a template renderer, a test fixture).

## send_simple

```python
result = client.mail.send_simple(
    to="recipient@example.com",
    subject="Weekly report",
    body="<p>Attached below.</p>",
    html=True,                       # False sends text/plain
    cc=["manager@example.com"],
    bcc=("archive@example.com",),
    sender_name="Reporting Bot",     # display name on the From header
    priority=3,                      # 1 highest … 5 lowest
    attachments=(),
)
```

`to`, `cc` and `bcc` accept a single address or any sequence, as plain strings or `MailAddress`
objects. At least one recipient across the three fields is required.

```python
from oxmail_sdk import MailAddress

client.mail.send_simple(
    to=[MailAddress("john@example.com", "John Doe"), "team@example.com"],
    subject="Hi",
    body="Plain text body",
    html=False,
)
```

The `From` address is always the authenticated account; `sender_name` only sets the display name.

## OutgoingMessage

```python
from oxmail_sdk import MailAddress, OutgoingMessage

message = OutgoingMessage(
    to=(MailAddress("john@example.com", "John"),),
    cc=("manager@example.com",),
    bcc=(),
    subject="Production mail",
    body="<p>Hello John.</p>",
    html=True,
    sender_name="Ops",
    priority=3,
)

result = client.mail.send(message)
```

Validation happens at construction: no recipients at all raises `ValueError`, as does a `priority`
outside 1–5. `MailAddress` rejects anything without an `@`.

Because it is a frozen dataclass, variants are cheap:

```python
from dataclasses import replace

for recipient in recipients:
    client.mail.send(replace(message, to=(recipient,)))
```

## Attachments

```python
from oxmail_sdk import Attachment

client.mail.send_simple(
    to="recipient@example.com",
    subject="Report",
    body="<p>See attached.</p>",
    attachments=[
        Attachment.from_path("./report.pdf"),
        Attachment.from_bytes(b"id,name\n1,test\n", filename="data.csv"),
    ],
)
```

| Constructor | Use it for | Notes |
| --- | --- | --- |
| `Attachment.from_path(path, filename=None, content_type=None)` | files on disk | raises `ValueError` if the path is not a file; the file is streamed, never loaded whole |
| `Attachment.from_bytes(data, filename=..., content_type=None)` | generated content | keeps the bytes in memory |

The content type is guessed from the filename and falls back to `application/octet-stream`. Pass
`content_type=` to override it. File handles are opened only for the duration of the request and
always closed, including on failure.

## Reading the result

```python
result = client.mail.send_simple(to="a@example.com", subject="Hi", body="Hello")

result.successful         # True for 2xx
result.status_code        # HTTP status
result.server_reference   # e.g. "default0/Sent/2" – where the server filed the copy
result.data               # parsed response payload
result.response_text      # raw body, handy when the server answers with HTML-wrapped JSON
```

Open-Xchange sometimes answers the legacy send endpoint with HTML-wrapped JSON; the SDK parses both
shapes, so `result.data` is a mapping either way.

## Error handling

```python
from oxmail_sdk import APIError, HTTPError, OXMailError, TransportError

try:
    client.mail.send_simple(to="a@example.com", subject="Hi", body="Hello")
except APIError as exc:            # the server understood and refused
    print("refused:", exc.code, exc.message)
except HTTPError as exc:           # non-2xx status
    print("http", exc.status_code, exc.response_preview)
except TransportError as exc:      # DNS, TLS, timeout, connection reset
    print("network:", exc)
except OXMailError as exc:         # anything else from the SDK
    print("sdk:", exc)
```

**Sends are never retried automatically.** The retry policy covers idempotent methods only, so a
`TransportError` on send means "unknown outcome" — check the Sent folder before resending if
duplicates matter:

```python
sent = client.mail.recent(folder="default0/Sent", limit=5)
already = any(message.subject == subject for message in sent)
```

## Replying to a message

The SDK does not build reply headers for you; construct the message yourself from a watched or
fetched `MailMessage`:

```python
def reply_to(client, message, body: str) -> None:
    if message.sender is None:
        return
    subject = message.subject
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    client.mail.send_simple(to=message.sender.email, subject=subject, body=body)
```

A complete auto-responder is in [Recipes](recipes.md).
