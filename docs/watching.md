# Watching the inbox

`client.mail.watch()` gives you new mail as it arrives. It returns an `InboxWatcher`, which you can
consume in three ways:

```python
watcher = client.mail.watch()

for message in watcher:            # 1. blocking iterator
    ...

watcher.background(on_message=cb)  # 2. worker thread
watcher.poll()                     # 3. one check, inside your own scheduler
```

## How it detects new mail

Two backends implement the same contract:

| Backend | Detection | Idle cost | Latency |
| --- | --- | --- | --- |
| `imap` (primary) | IMAP `IDLE` — the server pushes as soon as a message lands | one parked connection, IDLE re-issued every `idle_refresh` | immediate |
| `http` (fallback) | polls `mail?action=examine` and compares the folder fingerprint | one ~160 byte request per `interval` | up to one interval |

Once a change is signalled, both backends compare `UIDVALIDITY` + next UID + counters against the
stored checkpoint and fetch headers **only for the UIDs that actually appeared**. A busy mailbox
costs one small fetch per batch of new mail; a quiet one costs nothing.

The default `backend="auto"` runs IMAP as primary and falls back to HTTP polling if IMAP is
unreachable, retrying IMAP after `recover_after` seconds.

```python
client.mail.watch(backend="auto")   # default: IMAP, HTTP failover
client.mail.watch(backend="imap")   # IDLE only; errors surface instead of degrading
client.mail.watch(backend="http")   # polling only
```

`watcher.backend` reports which source is serving right now, so you can log or expose it:

```python
print("watching over", watcher.backend)   # "imap" or "http"
```

Because Open-Xchange mail ids *are* IMAP UIDs, both backends produce the same message ids and
understand each other's checkpoints — a failover mid-run never replays or drops a message.

## 1. Blocking iterator

```python
for message in client.mail.watch():
    print(message.id, message.sender, message.subject)
    if some_condition:
        break          # leaving the loop stops the watcher
```

The loop blocks between messages, costs nothing while idle, and yields messages oldest first.
Call `watcher.stop()` from another thread (or a signal handler) to end it cleanly, and
`watcher.close()` to release the IMAP connection. `InboxWatcher` is a context manager:

```python
with client.mail.watch() as watcher:
    for message in watcher:
        handle(message)
```

By default an exception ends the loop by propagating. Set `on_error` to keep watching instead:

```python
watcher = client.mail.watch(on_error=lambda exc: log.warning("watch failed: %s", exc))
```

With a handler installed the watcher retries with an exponential backoff — `interval`, doubling per
consecutive failure, capped at `max_error_delay` (300 s) — and resets to normal on the first success.

## 2. Worker thread

```python
def on_message(message):
    print("new mail:", message.subject)

watcher = client.mail.watch().background(on_message=on_message)
watcher.start()
...
watcher.stop()             # stops the loop, joins the thread, closes the connection
```

Or as a context manager:

```python
with client.mail.watch().background(on_message=on_message):
    run_the_rest_of_my_app()
```

Details worth knowing:

- The thread is a daemon by default (`daemon=False` to keep the process alive for it).
- `on_message` runs on the worker thread. Exceptions inside it are logged and the loop continues —
  one bad message never kills the watcher.
- Failures of the watch loop itself go to `on_error`, which defaults to a warning log, so a
  background watcher is resilient out of the box.
- `watcher.running` tells you whether the thread is alive; `join(timeout=...)` waits for it.
- Keep handlers short. Hand long work to a queue:

```python
import queue

work = queue.Queue()
watcher = client.mail.watch().background(on_message=work.put)
```

## 3. Manual polling

```python
watcher = client.mail.watch(backend="http")

while True:
    for message in watcher.poll():    # exactly one check, no sleeping
        handle(message)
    my_scheduler.sleep(60)
```

`poll()` is what the loop calls internally: it opens the backend if needed, compares state, fetches
what is new, and updates the checkpoint. Use it inside cron jobs, Celery beats, or an existing
event loop.

## The first poll

On the very first check the watcher records a **baseline** and returns nothing, so starting up never
floods you with the existing mailbox. To see recent history at startup:

```python
client.mail.watch(include_existing=True, backlog_limit=25)
```

The backlog is emitted oldest first, then normal watching continues.

## Fetching bodies

```python
for message in client.mail.watch(fetch_body=True):
    print(message.subject)
    print(message.text or message.html)
    for part in message.attachments:
        print(part.get("filename"), part["content_type"])
```

`fetch_body=True` downloads the full message for every new mail — `BODY.PEEK[]` over IMAP,
`action=get` over HTTP — and both are normalised into the same `detail` shape, so `message.html`,
`message.text` and `message.attachments` behave identically on either backend.

**Read marks:** the fetch peeks by default, leaving messages unread. Pass `mark_seen=True` to let
the read mark stick (over IMAP this also selects the mailbox read-write):

```python
client.mail.watch(fetch_body=True, mark_seen=True)
```

## Surviving restarts

The default checkpoint store lives in memory: after a restart the watcher takes the current folder
state as its baseline, so mail that arrived while it was down is **not** replayed. To resume exactly
where you stopped, persist the checkpoint:

```python
from oxmail_sdk import JSONFileCheckpointStore

watcher = client.mail.watch(store=JSONFileCheckpointStore("/var/lib/myapp/inbox-state.json"))
```

The file holds only `UIDVALIDITY`, the next UID, the folder fingerprint and a bounded window of
already-delivered ids — no message content. Writes are atomic (temp file + rename) and a corrupt or
missing file degrades to "start fresh" rather than crashing.

Each watcher stores state under a key, `"<username>|<folder>"` by default. Override it when one
process watches several folders or accounts into the same file:

```python
client.mail.watch(folder="default0/INBOX/Work", key="work-inbox")
```

Inspect or reset it:

```python
watcher.checkpoint    # Checkpoint | None: validity, next_id, fingerprint, seen_ids
watcher.state         # FolderState from the most recent check
watcher.reset()       # forget the checkpoint; the next poll re-baselines
```

### Custom stores

Any object with `load(key) -> Checkpoint | None` and `save(key, checkpoint) -> None` works — the
`CheckpointStore` protocol. A Redis-backed example:

```python
import json

from oxmail_sdk.mail import Checkpoint


class RedisCheckpointStore:
    def __init__(self, redis, prefix="oxmail:"):
        self._redis = redis
        self._prefix = prefix

    def load(self, key):
        raw = self._redis.get(self._prefix + key)
        return Checkpoint.from_dict(json.loads(raw)) if raw else None

    def save(self, key, checkpoint):
        self._redis.set(self._prefix + key, json.dumps(checkpoint.to_dict()))
```

## When UIDVALIDITY changes

If the server recreates the folder, every UID becomes meaningless. The watcher notices the changed
`UIDVALIDITY`, logs a warning, and rebuilds its baseline instead of replaying the whole mailbox.

## Watching another folder

```python
client.mail.watch(folder="default0/INBOX/Support", key="support")
```

Over IMAP the folder id is translated to a mailbox name (`default0/INBOX/Support` → `INBOX/Support`).
One watcher covers one folder; start several for several folders.

## All options

`client.mail.watch(...)`:

| Argument | Default | Meaning |
| --- | --- | --- |
| `folder` | `default0/INBOX` | folder to watch |
| `backend` | `"auto"` | `"auto"`, `"imap"` or `"http"` |
| `interval` | `15.0` | HTTP poll period; on IMAP only a lower bound for the safety-net check |
| `fetch_body` | `False` | download the full message for each new mail |
| `mark_seen` | `False` | `True` lets the body fetch mark messages read |
| `include_existing` | `False` | emit a backlog on the first poll |
| `backlog_limit` | `10` | how many messages that backlog contains |
| `store` | in-memory | checkpoint persistence |
| `key` | `"<username>\|<folder>"` | checkpoint key |
| `columns` | `DEFAULT_MAIL_COLUMNS` | header columns for the HTTP backend |
| `on_error` | `None` | error hook; installing one makes iteration resilient |
| `recover_after` | `300.0` | seconds before a degraded `auto` watcher retries IMAP |

Lower-level knobs (`batch_size`, `seen_history`, `max_error_delay`) live on `InboxWatcher` itself.
Build one directly when you need them:

```python
from oxmail_sdk import InboxWatcher

source = client.mail.source(backend="auto")       # the same backend watch() would use
watcher = InboxWatcher(
    source,
    key="inbox",
    interval=30,
    batch_size=250,       # ids per fetch request
    seen_history=5_000,   # how many delivered ids to remember
    max_error_delay=60,   # cap on the error backoff
)
```

## Runtime behaviour

- **Session expiry** — HTTP calls are wrapped in `run_with_session_retry`, so an expired
  Open-Xchange session is renewed and the request retried once, transparently.
- **Dropped IMAP connections** — the source reconnects on the next cycle; if it keeps failing under
  `backend="auto"`, the watcher degrades to HTTP and periodically retries IMAP.
- **Threading** — one `InboxWatcher` drives one loop. Do not iterate the same watcher from two
  threads; create one watcher per thread instead. The `IMAPConnection` it owns is single-threaded
  by design.
- **Shutdown** — `stop()` interrupts an IDLE wait within a second; `close()` also releases the
  connection. `BackgroundWatcher.stop()` does both.

## Graceful shutdown

```python
import signal
import threading

stop = threading.Event()
signal.signal(signal.SIGINT, lambda *_: stop.set())
signal.signal(signal.SIGTERM, lambda *_: stop.set())

with client.mail.watch(fetch_body=True).background(on_message=handle):
    stop.wait()
```
