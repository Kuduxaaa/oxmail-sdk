# oxmail-sdk documentation

Typed Python SDK for Open-Xchange (App Suite) mail: log in, send, read, and watch a mailbox for
new messages over IMAP IDLE with automatic HTTP fallback.

## Start here

| I want to… | Read |
| --- | --- |
| install the SDK and send my first mail | [Getting started](getting-started.md) |
| point the client at my server, tune timeouts, retries, IMAP | [Configuration](configuration.md) |
| understand sessions, OX Guard, re-authentication | [Authentication](authentication.md) |
| send HTML/plain mail, CC/BCC, attachments | [Sending mail](sending.md) |
| list, paginate, fetch messages and bodies | [Reading mail](reading.md) |
| react to new mail as it arrives | [Watching the inbox](watching.md) |
| handle failures correctly | [Errors and reliability](errors.md) |
| copy a working solution | [Recipes](recipes.md) |
| unit-test my code without a server | [Testing](testing.md) |
| look up a signature | [API reference](api-reference.md) |

## The 60-second version

```python
from oxmail_sdk import OXMailClient

with OXMailClient("me@example.com", "secret") as client:
    client.login()

    client.mail.send_simple(
        to="someone@example.com",
        subject="Hello",
        body="<p>Hello from Python.</p>",
    )

    for message in client.mail.watch():          # IMAP IDLE, HTTP polling as fallback
        print(message.sender, message.subject)
```

## Mental model

```text
OXMailClient            composition root; owns config, transport, auth, mail
├── .auth               AuthService   – login / OX Guard / logout / session refresh
├── .mail               MailService   – list, get, send, examine, watch
│   └── .watch(...)     InboxWatcher  – new-mail loop over a MailSource
│         ├── IMAPMailSource      primary: IMAP IDLE push
│         └── HTTPMailSource      fallback: mail?action=examine polling
└── .transport          HTTPTransport – requests session, retries, error mapping
```

Three facts worth internalising:

1. **Message ids are IMAP UIDs.** The `id` you get from the HTTP API is the same number IMAP uses,
   so both backends agree on identity and state written by one is understood by the other.
2. **Folders are Open-Xchange folder ids** (`default0/INBOX`), translated to IMAP mailboxes
   (`INBOX`) internally.
3. **Nothing is fetched until something changed.** The watcher compares a cheap folder fingerprint
   (UIDVALIDITY + next UID + counters) before asking for a single header.

## Requirements

- Python 3.11+
- `requests`, `urllib3` (installed automatically)
- IMAP is optional: without it the SDK falls back to HTTP polling on its own.
