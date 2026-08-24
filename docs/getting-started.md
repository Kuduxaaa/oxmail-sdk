# Getting started

## Install

```bash
python -m pip install oxmail-sdk
```

From a checkout, with the development extras:

```bash
python -m pip install -e '.[dev]'
```

## Your first script

```python
import os

from oxmail_sdk import OXMailClient

with OXMailClient(
    username=os.environ["OX_USERNAME"],
    password=os.environ["OX_PASSWORD"],
) as client:
    session = client.login()
    print("logged in as", session.user)

    result = client.mail.send_simple(
        to="recipient@example.com",
        subject="Hello",
        body="<p>Hello from Python.</p>",
    )
    print("sent:", result.successful, result.server_reference)
```

`OXMailClient` is a context manager: leaving the `with` block closes the HTTP session. It does
**not** log out of the server by default, because sessions are often reused across processes. Call
`client.close(logout=True)` (or `client.logout()`) when you do want the server session dropped.

## Credentials

The constructor takes the username and password directly. Keep them out of source control — read
them from the environment, a secret manager, or a config file your deployment provides.

```python
client = OXMailClient(username="me@example.com", password="secret")
```

The password lives only inside `Credentials`, whose `repr()` hides it, and session tokens are
redacted from logs. See [Authentication](authentication.md).

## Pointing at your server

The default `base_url` is `https://ultamail.com/appsuite/api`. Override it for your deployment:

```python
from oxmail_sdk import ClientConfig, OXMailClient

client = OXMailClient(
    username="me@example.com",
    password="secret",
    config=ClientConfig(base_url="https://mail.example.com/appsuite/api"),
)
```

The IMAP host is derived from that URL (`mail.example.com` → `imap.example.com`) unless you set one
explicitly. Full details in [Configuration](configuration.md).

## What to do next

- **Send** mail with attachments, CC/BCC and priorities → [Sending mail](sending.md)
- **Read** the inbox, paginate, download bodies → [Reading mail](reading.md)
- **React** to new mail as it arrives → [Watching the inbox](watching.md)

## A complete, realistic example

Log in, print the ten newest messages, then watch for new ones until interrupted:

```python
import os

from oxmail_sdk import OXMailClient

with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
    client.login()

    for message in client.mail.recent(limit=10):
        mark = " " if message.seen else "*"
        print(f"{mark} #{message.id:>5} {message.received_at:%Y-%m-%d %H:%M} {message.subject}")

    print("waiting for new mail; Ctrl+C to stop")
    try:
        for message in client.mail.watch(fetch_body=True):
            print(f"NEW #{message.id} from {message.sender}: {message.subject}")
            print((message.text or message.html or "")[:200])
    except KeyboardInterrupt:
        pass
```
