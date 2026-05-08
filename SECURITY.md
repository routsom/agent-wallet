# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.x     | Yes       |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on the repository page.

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix

You will receive a response within 72 hours. We aim to release a patch
within 14 days of a confirmed report.

## Scope

This library never stores or transmits your provider API keys. The wallet
wraps a provider client but reads no credentials from it. The local SQLite
ledger at `~/.agent-wallet/ledger.db` stores only token counts, costs, and
wallet metadata — no API keys or message content.

If you discover that any version of agent-wallet inadvertently reads, logs,
or transmits API keys or message content, please report it immediately.
