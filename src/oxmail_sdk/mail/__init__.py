from .attachments import Attachment
from .columns import COLUMN_FIELDS, parse_columns
from .constants import DEFAULT_MAIL_COLUMNS, INBOX_FOLDER
from .message import MailMessage
from .models import AddressLike, MailAddress, MailPage, OutgoingMessage, SendResult
from .service import MailService
from .sources import (
    FailoverMailSource,
    HTTPMailSource,
    IMAPMailSource,
    MailSource,
    mailbox_from_folder,
)
from .state import (
    Checkpoint,
    CheckpointStore,
    FolderState,
    JSONFileCheckpointStore,
    MemoryCheckpointStore,
)
from .watch import BackgroundWatcher, InboxWatcher

__all__ = [
    "AddressLike",
    "Attachment",
    "BackgroundWatcher",
    "COLUMN_FIELDS",
    "Checkpoint",
    "CheckpointStore",
    "DEFAULT_MAIL_COLUMNS",
    "FailoverMailSource",
    "FolderState",
    "HTTPMailSource",
    "IMAPMailSource",
    "INBOX_FOLDER",
    "InboxWatcher",
    "JSONFileCheckpointStore",
    "MailAddress",
    "MailMessage",
    "MailPage",
    "MailService",
    "MailSource",
    "MemoryCheckpointStore",
    "OutgoingMessage",
    "SendResult",
    "mailbox_from_folder",
    "parse_columns",
]
