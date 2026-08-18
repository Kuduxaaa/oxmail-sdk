from .attachments import Attachment
from .constants import INBOX_FOLDER
from .models import AddressLike, MailAddress, MailPage, OutgoingMessage, SendResult
from .service import MailService

__all__ = [
    "AddressLike",
    "Attachment",
    "INBOX_FOLDER",
    "MailAddress",
    "MailPage",
    "MailService",
    "OutgoingMessage",
    "SendResult",
]
