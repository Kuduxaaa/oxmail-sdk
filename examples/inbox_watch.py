from __future__ import annotations

import logging
import os
import signal
import threading

from oxmail_sdk import JSONFileCheckpointStore, MailMessage, OXMailClient


def on_message(message: MailMessage) -> None:
    sender = message.sender.email if message.sender else "unknown"
    received = message.received_at.isoformat() if message.received_at else "?"
    print(f"[{received}] {sender}: {message.subject}")
    if message.fetched:
        body = message.text or message.html or ""
        print(f"  {len(body)} chars, {len(message.attachments)} attachment(s)")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    with OXMailClient(
        username=os.environ["OX_USERNAME"],
        password=os.environ["OX_PASSWORD"],
    ) as client:
        client.login()

        watcher = client.mail.watch(
            backend="auto",  # IMAP IDLE, falling back to HTTP polling
            interval=10,
            fetch_body=True,
            store=JSONFileCheckpointStore("inbox-state.json"),
        )

        with watcher.background(on_message=on_message):
            print(f"Watching for new mail over {watcher.backend}; Ctrl+C to stop.")
            stop.wait()

        state = watcher.state
        if state is not None:
            print(f"Final state: {state.unread} unread of {state.total}")


if __name__ == "__main__":
    main()
