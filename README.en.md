# Gmail Bridge

English · [日本語](README.md)

Stable release: **[v1.1.0](https://github.com/sosboy-san/gmail_bridge/releases/tag/v1.1.0)** (2026-10-14).

Import external IMAP mail into your own Gmail account using the Gmail API. Keep Gmail as the place where you use filters, labels, search and archiving, rather than simply viewing separate accounts in one mail app. Self-host on Linux or Docker; the owner has reported problem-free rc.2 operation on QNAP Container Station before this stable release.

[Install](INSTALL.en.md) · [Upgrade and recovery](MAINTENANCE.en.md) · [Notifications](NOTIFICATIONS.en.md) · [Troubleshooting](TROUBLESHOOTING.en.md) · [Uninstall](UNINSTALL.en.md) · [Security](SECURITY.en.md)

## Features

- Fetch with IMAP `BODY.PEEK[]`, without marking source messages read. Reflect the source read/unread state at import time.
- Import the original message with `users.messages.import` and apply a source label. Gmail handles classification; filters that mark messages read can interact with Bridge's subsequent label/read-state updates, so test your rules.
- Only when Gmail rejects attachments, store attachments in Google Drive and import a reduced message with links. Drive sharing is not made public.
- Track mailbox, UIDVALIDITY, UID and Gmail IDs in SQLite. Resume pending finalization without repeating a successful import.
- Optional ntfy notifications with sender display name, subject and preview, exact sender filters and TTL. Retry notifications independently without fetching the original message again.
- Shared locking, safe startup waiting, explicit initialization, transactional database migrations with backups, daily backups and optional delayed source cleanup.

## Start with Docker

```bash
docker pull sosboy/gmail-bridge:1.1.0
```

Pulling alone does not configure the service. Follow [Installation](INSTALL.en.md) to create your own Google OAuth token, configure IMAP, mount persistent storage at `/config`, start the service and explicitly initialize it. For an existing deployment, follow [Maintenance](MAINTENANCE.en.md); **do not initialize again**.

Published image: [sosboy/gmail-bridge](https://hub.docker.com/r/sosboy/gmail-bridge), `linux/amd64` and `linux/arm64`. Use exact versions for controlled upgrades. Stable releases update minor/major/latest tags; RC tags remain separate and immutable. `main` is the development branch; deploy release tags.

## Runtime language

Set `[general] language = en`, `BRIDGE_LANGUAGE=en`, or `python -m app.main --lang en status`. Priority: CLI, environment, INI, default Japanese. Put `--lang` before the subcommand. Language changes do not translate original mail, stored labels, database states or external-library exceptions.

## Limits

- Linux with Python 3.12 or Linux containers. Windows can generate OAuth tokens and run offline checks; use Linux containers for the service's flock locking.
- STARTTLS (normally port 143); implicit TLS on 993 and IMAP OAuth are unsupported.
- One source account/mailbox and one Gmail account per configuration/state directory. No recursive folder traversal or bidirectional synchronization; sending from the external address is not provided.
- Remote API success followed by a crash before local commit can still cause duplicates. Restoring an old database can also cause re-imports.
- Source cleanup is disabled by default. On servers without UIDPLUS, another client's concurrent deletions can race with EXPUNGE.
- A running container or zero run exit code does not prove every message succeeded. Check logs and state. Recovery alerts have no independent retry queue.

## v1.1 behavior changes

Init imports do not create ordinary notifications, including selected messages resumed later by run. Enabled notification configuration errors now stop/defer operations. Only explicit init creates a database. Existing schema 0/1 databases migrate safely to schema 2; migration never initializes the mailbox. See [Release notes](RELEASE_NOTES.en.md).

## Development and license

See [Contributing](CONTRIBUTING.en.md) and [Docker publishing](DOCKER_RELEASE.en.md). Tests use synthetic data and mocked services. Protect settings, tokens, databases, backups and logs; never publish real mail or credentials.

[MIT License](LICENSE). Development, documentation and release preparation were supported with assistance from ChatGPT by OpenAI. This project is not affiliated with or endorsed by Google.
