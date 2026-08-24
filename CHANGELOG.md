# Changelog

All notable changes to this project will be documented here.

## Unreleased

- Inbox watching: `client.mail.watch()` with a blocking iterator and a `background()` worker thread.
- IMAP backend with IDLE as the primary source, so new mail arrives as a server push.
- HTTP `mail?action=examine` polling as the fallback source; idle polls cost one ~160 byte request.
- Automatic failover between backends (`backend="auto"`) with periodic recovery of the primary.
- `IMAPConfig` on `ClientConfig`, with the IMAP host derived from `base_url` by default.
- `MailMessage` model with parsed headers, IMAP flag helpers and optional body/attachment fetch.
- Checkpoint persistence (`MemoryCheckpointStore`, `JSONFileCheckpointStore`, `CheckpointStore`
  protocol) for restart-safe polling without duplicates.
- Automatic re-authentication on expired sessions via `AuthService.run_with_session_retry`.
- `MailService.examine`, `MailService.list_by_ids` and `MailService.recent`.
- Full documentation under `docs/`: guides, recipes, testing notes and an API reference.

## 0.1.0 - 2026-08-18

- Initial PyPI-ready release.
- Open-Xchange login and optional OX Guard initialization.
- Mail listing, pagination, retrieval, HTML/plain-text send, CC/BCC and attachments.
- Safe retry policy for idempotent reads only.
- Typed package marker and explicit SDK exception hierarchy.
- Separation of concerns across auth, mail, serialization, transport and configuration layers.
