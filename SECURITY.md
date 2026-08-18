# Security

## Credentials

Do not hard-code mailbox passwords, session IDs, API tokens, or cookies in source code.
Load secrets from environment variables or a dedicated secret manager.

## Logging

The SDK does not intentionally log request bodies. Known sensitive query parameters such as
`session`, `password`, and `token` are redacted by the HTTP transport logger.

## TLS

TLS certificate verification is enabled by default. Disable it only in controlled test
environments.

## Reporting

Before publishing this project publicly, replace this section with the security-contact or
private vulnerability-reporting process you want users to follow.
