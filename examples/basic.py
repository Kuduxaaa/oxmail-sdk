from __future__ import annotations

import os

from oxmail_sdk import Attachment, OXMailClient


def main() -> None:
    with OXMailClient(
        username=os.environ["OX_USERNAME"],
        password=os.environ["OX_PASSWORD"],
    ) as client:
        session = client.login()
        print(f"Logged in as: {session.user or 'unknown'}")

        page = client.mail.list(limit=10)
        print(f"Inbox rows: {len(page)}")

        result = client.mail.send_simple(
            to=os.environ["OX_TEST_RECIPIENT"],
            subject="SDK test",
            body="<p>Production SDK test.</p>",
            attachments=(
                Attachment.from_bytes(
                    b"hello\n",
                    filename="hello.txt",
                    content_type="text/plain",
                ),
            ),
        )
        print(f"Send HTTP status: {result.status_code}")


if __name__ == "__main__":
    main()
