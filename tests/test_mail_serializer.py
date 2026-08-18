from __future__ import annotations

from oxmail_sdk.mail import MailAddress, OutgoingMessage
from oxmail_sdk.mail.serializer import LegacyMessageSerializer


def test_legacy_message_serialization() -> None:
    serializer = LegacyMessageSerializer()
    message = OutgoingMessage(
        to=(MailAddress("a@example.com", "A"),),
        subject="subject",
        body="<b>body</b>",
    )

    payload = serializer.serialize(message, from_email="sender@example.com")

    assert payload["from"] == [[None, "sender@example.com"]]
    assert payload["to"] == [["A", "a@example.com"]]
    assert payload["attachments"][0]["content_type"] == "text/html"
