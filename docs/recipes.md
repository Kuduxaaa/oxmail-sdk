# Recipes

Complete, copy-pasteable solutions. Each one runs as written, given valid credentials.

- [Notify a webhook on every new mail](#notify-a-webhook-on-every-new-mail)
- [Auto-responder that cannot loop](#auto-responder-that-cannot-loop)
- [Download attachments to disk](#download-attachments-to-disk)
- [Ticket ingestion daemon](#ticket-ingestion-daemon)
- [Cron-style one-shot check](#cron-style-one-shot-check)
- [Watch several accounts at once](#watch-several-accounts-at-once)
- [Unread badge and health check](#unread-badge-and-health-check)
- [Daily digest](#daily-digest)
- [Send a report with an attachment](#send-a-report-with-an-attachment)
- [Run as a systemd service](#run-as-a-systemd-service)

## Notify a webhook on every new mail

```python
import os

import requests

from oxmail_sdk import JSONFileCheckpointStore, OXMailClient

WEBHOOK = os.environ["WEBHOOK_URL"]


def notify(message) -> None:
    requests.post(
        WEBHOOK,
        json={
            "id": message.id,
            "from": message.sender.email if message.sender else None,
            "subject": message.subject,
            "received_at": message.received_at.isoformat() if message.received_at else None,
            "preview": (message.text or message.html or "")[:280],
        },
        timeout=10,
    )


with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
    client.login(oxguard=False)
    watcher = client.mail.watch(
        fetch_body=True,
        store=JSONFileCheckpointStore("state.json"),
    )
    for message in watcher:
        notify(message)
```

The checkpoint file means a restart resumes where it stopped, so a webhook receiver never misses a
message and never sees one twice.

## Auto-responder that cannot loop

The two failure modes of every auto-responder: replying to yourself, and replying to bulk mail.
Both are cheap to prevent.

```python
import os

from oxmail_sdk import JSONFileCheckpointStore, OXMailClient

ME = os.environ["OX_USERNAME"].lower()
BODY = "<p>Thanks — we received your message and will reply within one business day.</p>"


def should_reply(message) -> bool:
    if message.sender is None or message.draft:
        return False
    sender = message.sender.email.lower()
    if sender == ME:                                    # never answer yourself
        return False
    if any(flag.lower() == "$autoreplied" for flag in message.user_flags):
        return False
    headers = (message.detail or {}).get("headers", {})
    bulk = {"list-id", "list-unsubscribe", "auto-submitted", "precedence"}
    return not (bulk & {key.lower() for key in headers})


with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
    client.login(oxguard=False)

    watcher = client.mail.watch(
        fetch_body=True,                                 # needed for the header check
        store=JSONFileCheckpointStore("autoreply.json"),
    )
    for message in watcher:
        if not should_reply(message):
            continue
        subject = message.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        client.mail.send_simple(to=message.sender.email, subject=subject, body=BODY)
```

The checkpoint store is what stops a restart from re-answering old mail.

## Download attachments to disk

`message.attachments` carries metadata; the bytes come from the Open-Xchange attachment endpoint.
Fetch the message payload first so the part ids match the ones you ask for:

```python
from pathlib import Path


def save_attachments(client, mail_id: str, folder: str = "default0/INBOX") -> list[Path]:
    payload = client.mail.get(mail_id, unseen=True)["data"]
    saved: list[Path] = []

    for part in payload.get("attachments", []):
        if part.get("disp") != "attachment":
            continue
        response = client.transport.request(
            "GET",
            "mail",
            params={
                "action": "attachment",
                "folder": folder,
                "id": mail_id,
                "attachment": part["id"],
                "delivery": "download",
                "session": client.auth.token,
            },
        )
        target = Path("downloads") / f"{mail_id}-{part.get('filename', part['id'])}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        saved.append(target)

    return saved
```

Wire it into a watcher:

```python
for message in client.mail.watch():
    if message.has_attachment:
        print(save_attachments(client, message.id))
```

Inline parts (`disp == "inline"`) are the body itself — `message.html` and `message.text` already
give you those without a second request.

## Ticket ingestion daemon

A long-running service: persistent state, graceful shutdown, structured logging, and processing that
never blocks the watch loop.

```python
import logging
import os
import queue
import signal
import threading

from oxmail_sdk import JSONFileCheckpointStore, OXMailClient

log = logging.getLogger("ingest")
work: queue.Queue = queue.Queue(maxsize=1000)
stop = threading.Event()


def worker() -> None:
    while not stop.is_set():
        try:
            message = work.get(timeout=1)
        except queue.Empty:
            continue
        try:
            create_ticket(                       # your code
                external_id=message.id,
                sender=message.sender.email if message.sender else "unknown",
                subject=message.subject,
                body=message.text or message.html or "",
            )
        except Exception:
            log.exception("failed to ingest message %s", message.id)
        finally:
            work.task_done()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    threading.Thread(target=worker, name="ingest-worker", daemon=True).start()

    with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
        client.login(oxguard=False)
        watcher = client.mail.watch(
            fetch_body=True,
            store=JSONFileCheckpointStore("/var/lib/ingest/inbox.json"),
        )
        with watcher.background(on_message=work.put, on_error=lambda exc: log.warning("%s", exc)):
            log.info("watching over %s", watcher.backend)
            stop.wait()
        log.info("stopped; %d queued items remain", work.qsize())


if __name__ == "__main__":
    main()
```

## Cron-style one-shot check

No daemon, no IDLE — one HTTP check per run, state carried in a file:

```python
import os
import sys

from oxmail_sdk import JSONFileCheckpointStore, OXMailClient

with OXMailClient(os.environ["OX_USERNAME"], os.environ["OX_PASSWORD"]) as client:
    client.login(oxguard=False)
    watcher = client.mail.watch(
        backend="http",
        store=JSONFileCheckpointStore(os.path.expanduser("~/.cache/oxmail-cron.json")),
    )
    new = watcher.poll()

for message in new:
    print(f"{message.id}\t{message.sender}\t{message.subject}")

sys.exit(0 if new else 1)     # exit 1 = nothing new, useful in shell pipelines
```

```cron
*/5 * * * * /usr/bin/python3 /opt/check_mail.py >> /var/log/check_mail.log 2>&1
```

## Watch several accounts at once

```python
import threading

from oxmail_sdk import JSONFileCheckpointStore, OXMailClient

STORE = JSONFileCheckpointStore("accounts.json")     # shared file, one key per account


def start(username: str, password: str):
    client = OXMailClient(username, password)
    client.login(oxguard=False)
    watcher = client.mail.watch(store=STORE, key=f"{username}|inbox")
    background = watcher.background(
        on_message=lambda message, who=username: print(who, message.subject),
        name=f"watch-{username}",
    )
    return client, background.start()


handles = [start(user, secret) for user, secret in accounts]
try:
    threading.Event().wait()
finally:
    for client, background in handles:
        background.stop()
        client.close()
```

`JSONFileCheckpointStore` serialises its writes with a lock, so sharing one file across watcher
threads is safe.

## Unread badge and health check

```python
def mailbox_status(client) -> dict:
    state = client.mail.examine()
    return {"total": state.total, "unread": state.unread, "next_uid": state.next_id}
```

One ~160 byte request — cheap enough for a `/healthz` endpoint or a status bar refreshed every few
seconds.

```python
from oxmail_sdk import IMAPError

def imap_reachable(client) -> bool:
    source = client.mail.source(backend="imap")
    try:
        source.open()
        return True
    except IMAPError:
        return False
    finally:
        source.close()
```

## Daily digest

```python
from datetime import UTC, datetime, timedelta

def digest(client, hours: int = 24, limit: int = 200) -> list[str]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    lines = []
    for message in client.mail.recent(limit=limit):
        if message.received_at and message.received_at >= since:
            sender = message.sender.email if message.sender else "unknown"
            lines.append(f"{message.received_at:%H:%M} {sender:<32} {message.subject}")
    return lines


client.mail.send_simple(
    to="me@example.com",
    subject=f"Inbox digest {datetime.now(UTC):%Y-%m-%d}",
    body="<pre>" + "\n".join(digest(client)) + "</pre>",
)
```

## Send a report with an attachment

```python
import csv
import io

from oxmail_sdk import Attachment

buffer = io.StringIO()
writer = csv.writer(buffer)
writer.writerow(["date", "signups"])
writer.writerows(rows)

client.mail.send_simple(
    to=["team@example.com"],
    cc="manager@example.com",
    subject="Daily signups",
    body="<p>Numbers attached.</p>",
    sender_name="Reporting Bot",
    attachments=[
        Attachment.from_bytes(buffer.getvalue().encode("utf-8"), filename="signups.csv"),
    ],
)
```

## Run as a systemd service

```ini
# /etc/systemd/system/oxmail-ingest.service
[Unit]
Description=Open-Xchange inbox ingestion
After=network-online.target

[Service]
Type=simple
User=oxmail
Environment=OX_USERNAME=bot@example.com
EnvironmentFile=/etc/oxmail-ingest.env      # OX_PASSWORD lives here, mode 0600
WorkingDirectory=/opt/oxmail-ingest
ExecStart=/opt/oxmail-ingest/.venv/bin/python -m ingest
Restart=always
RestartSec=5
StateDirectory=oxmail-ingest                # /var/lib/oxmail-ingest for the checkpoint file

[Install]
WantedBy=multi-user.target
```

The daemon handles `SIGTERM` (see the ingestion recipe), so `systemctl stop` shuts the watcher down
cleanly and the checkpoint file makes the restart lossless.
