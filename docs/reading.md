# Reading mail

Five ways to read, from cheapest to richest:

| Call | Returns | Use it for |
| --- | --- | --- |
| `mail.examine()` | `FolderState` | "did anything change?" — ~160 bytes |
| `mail.recent(limit=10)` | `tuple[MailMessage, ...]` | the newest N messages, parsed |
| `mail.list_by_ids([...])` | `tuple[MailMessage, ...]` | specific ids, parsed |
| `mail.list(...)` / `mail.iter_messages(...)` | raw column rows | pagination over a whole folder |
| `mail.get(id)` | raw payload with body | one message including its body and parts |

## Folders

Folders are Open-Xchange folder ids. The inbox is `default0/INBOX`, exported as `INBOX_FOLDER`:

```python
from oxmail_sdk.mail import INBOX_FOLDER

client.mail.recent(folder=INBOX_FOLDER)
client.mail.recent(folder="default0/Sent")
```

Typical ids on an App Suite account: `default0/INBOX`, `default0/Sent`, `default0/Drafts`,
`default0/Trash`, `default0/Junk`, plus nested ones like `default0/INBOX/Work`. The exact names come
from the server.

## The newest messages

```python
for message in client.mail.recent(limit=10):
    print(message.id, message.subject, message.received_at)
```

Returned **oldest first**, so appending them to a list or a UI keeps chronological order.

## Specific messages by id

```python
messages = client.mail.list_by_ids(["1042", "1043", 1044])
```

Ids that no longer exist are silently skipped — the result may be shorter than the input, which
makes this safe to call with a UID range after a gap.

## Paginating a whole folder

`list()` returns a `MailPage` of **raw column rows** exactly as Open-Xchange sends them:

```python
page = client.mail.list(limit=50, offset=0, order="desc")

len(page)        # number of rows
page.offset      # echoed request offset
page.limit       # echoed request limit
page.raw         # the untouched response payload
for row in page: # each row is a list of column values
    print(row)
```

Parse those rows into the same model the rest of the SDK uses:

```python
from oxmail_sdk import MailMessage
from oxmail_sdk.mail import DEFAULT_MAIL_COLUMNS, INBOX_FOLDER, parse_columns

columns = parse_columns(DEFAULT_MAIL_COLUMNS)
messages = [
    MailMessage.from_row(columns, row, default_folder=INBOX_FOLDER)
    for row in client.mail.list(limit=50)
]
```

`iter_messages()` pages automatically and yields raw rows:

```python
for row in client.mail.iter_messages(page_size=100, max_messages=500):
    ...
```

Both accept `folder`, `category` (default `general`) and `deleted`; `list()` additionally accepts
`sort_column`, `order` (`asc`/`desc`) and `timezone`.

## One message with its body

```python
payload = client.mail.get("1042")
data = payload["data"]

data["subject"]
data["unread"]
for part in data["attachments"]:
    print(part["content_type"], part.get("disp"), part.get("size"))
```

Useful arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `folder` | `default0/INBOX` | folder the id belongs to |
| `unseen` | `False` | `True` peeks: the message stays unread |
| `sanitize` | `False` | let the server sanitize HTML |
| `max_size` | `102400` | truncation limit for the body |
| `timezone` | `utc` | timezone for date fields |

To get the same rich object the watcher hands you:

```python
from oxmail_sdk import MailMessage

payload = client.mail.get("1042", unseen=True)
message = MailMessage.from_mapping(payload["data"]).with_detail(payload["data"])

print(message.subject, message.html or message.text)
```

## MailMessage

The parsed model produced by `recent()`, `list_by_ids()`, the watcher, and the conversions above.

**Headers**

| Attribute | Type | Notes |
| --- | --- | --- |
| `id` | `str` | Open-Xchange mail id — the same number as the IMAP UID |
| `folder` | `str` | folder id the message lives in |
| `subject` | `str` | decoded, `""` when absent |
| `sender` | `MailAddress \| None` | first `From` address |
| `to` / `cc` / `bcc` | `tuple[MailAddress, ...]` | parsed recipients |
| `received_at` / `sent_at` | `datetime \| None` | timezone-aware, UTC |
| `size` | `int \| None` | bytes |
| `priority` | `int \| None` | 1 highest … 5 lowest |
| `has_attachment` | `bool` | |
| `content_type` | `str \| None` | top-level MIME type |
| `preview` | `str \| None` | server-side text preview, when available |
| `color_label` | `int \| None` | App Suite colour flag |
| `user_flags` | `tuple[str, ...]` | IMAP keywords such as `$Forwarded` |
| `raw` | `Mapping` | untouched field mapping |
| `detail` | `Mapping \| None` | full payload once the body was fetched |

**Flags** — `flags` is the Open-Xchange bitmask; use the helpers instead of masking by hand:

```python
message.unread      # not seen
message.seen
message.answered
message.flagged
message.draft
message.deleted
message.forwarded
message.recent
```

**Body** — populated when `detail` is present (`fetch_body=True`, or `with_detail(...)`):

```python
message.fetched      # bool: is the body loaded?
message.html         # first text/html part, or None
message.text         # first text/plain part, or None
message.body         # html or text, whichever exists
message.attachments  # tuple of non-inline parts
```

Attachment parts are mappings with `content_type`, `disp`, `size` and usually `filename`:

```python
for part in message.attachments:
    print(part.get("filename"), part["content_type"], part.get("size"))
```

Saving attachment bytes is a separate download; see the recipe in [Recipes](recipes.md).

## Folder state without listing anything

```python
state = client.mail.examine()

state.total       # message count
state.unread      # unread count
state.next_id     # next UID the server will assign
state.validity    # UIDVALIDITY: changes only when the folder is recreated
state.modseq      # server modification sequence, when provided
state.fingerprint # cheap change key; equal fingerprints mean nothing changed
```

This is the primitive the HTTP watcher polls. It is also the cheapest way to render an unread badge:

```python
def unread_count(client) -> int:
    return client.mail.examine().unread
```

## Choosing columns

`recent()` and `list_by_ids()` accept a `columns` string of Open-Xchange column ids. The default
(`DEFAULT_MAIL_COLUMNS`) covers everything `MailMessage` exposes. Request fewer for large sweeps:

```python
from oxmail_sdk.mail.columns import COLUMN_FROM, COLUMN_ID, COLUMN_RECEIVED_DATE, COLUMN_SUBJECT

lean = ",".join((COLUMN_ID, COLUMN_FROM, COLUMN_SUBJECT, COLUMN_RECEIVED_DATE))
messages = client.mail.recent(limit=200, columns=lean)
```

Fields you did not request are simply absent from the model (`None`, `0` or empty). The mapping from
column id to field name is `oxmail_sdk.mail.COLUMN_FIELDS`.
