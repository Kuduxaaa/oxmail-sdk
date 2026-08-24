# Authentication

## Logging in

```python
client = OXMailClient("me@example.com", "secret")
session = client.login()

session.session     # session token (hidden from repr)
session.user        # login name reported by the server
session.user_id     # numeric user id
session.context_id  # numeric context id
session.locale      # locale reported by the server
```

`login()` performs the App Suite `login` request and, by default, an OX Guard initialization call.
On deployments without OX Guard, or when you do not need it, skip that second round trip:

```python
client.login(oxguard=False)
```

If OX Guard authentication fails the SDK rolls the session back (a best-effort remote logout,
falling back to clearing local state) and raises `AuthenticationError`, so you never end up holding
a half-initialised session.

## Session lifecycle

```python
client.authenticated          # bool: is a session token held locally?
client.auth.token             # the raw token; raises NotAuthenticatedError if not logged in
client.auth.session_info      # SessionInfo | None
```

| Call | Effect |
| --- | --- |
| `client.login()` | Authenticate and store the session. |
| `client.auth.ensure_authenticated()` | Return the current session, logging in only if there is none. |
| `client.auth.refresh()` | Drop the local session and log in again with the same options. |
| `client.logout()` | Tell the server to end the session, then clear it locally. |
| `client.auth.clear_local_session()` | Forget the session locally without contacting the server. |
| `client.close()` | Close the HTTP session; add `logout=True` to log out first. |

`ensure_authenticated()` remembers the `oxguard` flag from your last `login()` call, so implicit
logins behave exactly like your explicit one.

## Automatic re-authentication

Open-Xchange expires idle sessions and answers with an `SES-*` error code (for example
`SES-0203 Your session expired`). Rather than sprinkling retries through your code, wrap a call:

```python
messages = client.auth.run_with_session_retry(
    lambda: client.mail.recent(limit=20)
)
```

`run_with_session_retry` logs in when there is no session, runs the operation, and on a session
error re-authenticates **once** and retries. Any other `APIError` propagates untouched.

The inbox watcher already routes every HTTP call through this helper, so a long-running watcher
survives session expiry without any code from you. See [Watching the inbox](watching.md).

To detect the condition yourself:

```python
from oxmail_sdk import APIError

try:
    client.mail.list(limit=10)
except APIError as exc:
    if exc.session_expired:      # True for any SES-* code
        client.auth.refresh()
```

## IMAP credentials

The IMAP backend authenticates separately, with the same username and password you passed to the
client (`client.auth.credentials`). No extra configuration is needed; if IMAP login fails, the
watcher falls back to HTTP polling and logs a warning.

## Keeping secrets out of logs

- `Credentials.__repr__` and `SessionInfo.__repr__` never print the password or token.
- Request logging redacts `session`, `password`, `token` and `access_token` parameters.
- Nothing is written to disk by the SDK except the checkpoint file you explicitly configure, which
  contains only UIDs and folder state — never message content or credentials.

Enable debug logging safely:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("oxmail_sdk").setLevel(logging.DEBUG)
```

## Multiple accounts

One client per account; they share nothing:

```python
clients = {}
for username, password in accounts:
    client = OXMailClient(username, password)
    client.login(oxguard=False)
    clients[username] = client
```

For watching several accounts at once, see the multi-account recipe in [Recipes](recipes.md).
