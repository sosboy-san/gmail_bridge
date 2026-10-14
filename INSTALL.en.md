# Installation — v1.1.0

English · [日本語](INSTALL.md)

For an existing deployment, use [Maintenance](MAINTENANCE.en.md), not init. Keep test and production state separate.

## 1. Requirements

Docker Engine with Compose v2 or QNAP Container Station; a STARTTLS-capable IMAP server; a Google account with Gmail/Drive access; and a trusted desktop with Python 3.12 and a browser for OAuth. Create a dedicated writable host directory for persistent state. Use the examples from the exact release tag in the canonical repository.

## 2. Create your own Google OAuth token

1. Create your own project in [Google Cloud Console](https://console.cloud.google.com/) and enable Gmail API and Google Drive API.
2. Configure the OAuth consent screen. For an External app in Testing, add the destination Google account as a test user.
3. Create a **Desktop app** OAuth client, download its JSON and save it as `credentials.json` on your desktop.
4. From the release source directory, run:

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python make_token.py --lang en
```

Complete browser authentication with the destination Google account. Copy the resulting `token.json` securely to the host/NAS. Do not perform desktop loopback authorization inside a headless NAS. Replacing an existing token requires `--force`; importing the script does not authenticate.

Scopes are `https://mail.google.com/` (broad Gmail access) and `https://www.googleapis.com/auth/drive.file`. Existing tokens without Drive scope need renewed consent. The application does not make Drive files public. See Google's [desktop OAuth guidance](https://developers.google.com/identity/protocols/oauth2/native-app) and [token-expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration). With this scope set, External/Testing refresh tokens normally expire after seven days. Check consent publishing status, organization policy and applicable review requirements before continuous operation; repository visibility is unrelated.

## 3. Prepare persistent storage

```bash
cp docker-compose.config.image.example.yml docker-compose.yml
mkdir -p config/data config/backups config/logs
cp config.example.ini config/config.ini
# Securely copy your desktop-generated token to config/token.json.
# Only needed when sender filtering is enabled:
cp notification_senders.example.ini config/notification_senders.ini
```

Edit `config/config.ini` as UTF-8. Set `[imap] host`, `user`, `password`, and `[general] language = en`. Write `%` literally, without quotes or inline comments. Replace old escaped `%%` with the actual password character. Initially keep source deletion and notifications disabled.

| Setting | Default / meaning |
| --- | --- |
| imap.port / mailbox | 143 / INBOX; STARTTLS only |
| imap.label | IMAP user if omitted/empty; example: IMAP-Bridge |
| imap.delete_after_import / delete_delay_days | false / 7; delay must be at least 1 day |
| gmail.token_file | token.json; writable for refresh |
| gmail.fallback_label | Legacy Japanese label if omitted; example: Attachments-in-Drive; language never renames existing labels |
| gmail.force_not_spam | false; removes SPAM, does not add INBOX |
| drive.folder | Gmail-IMAP-Bridge; folder name, not ID |
| notification.enabled | false; see [Notifications](NOTIFICATIONS.en.md) |

Create a local `.env` next to Compose:

```dotenv
BRIDGE_VERSION=1.1.0
BRIDGE_UID=1000
BRIDGE_GID=1000
TZ=Asia/Tokyo
BRIDGE_HOST_CONFIG_DIR=./config
```

Use your actual service user's UID/GID (`id -u` / `id -g` on Linux) and preferred timezone. Docker versions have no leading `v`. Grant the service user read/write access throughout the dedicated folder; restrict secrets (for example files 600 and directories 700). Check QNAP ACLs or Windows Docker Desktop host sharing separately. `/config` must be writable for token refresh.

## 4. Start, then explicitly initialize

```bash
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose logs --tail=100 -f gmail-bridge
```

With valid configuration but no initialized DB, expect `WAITING_FOR_INIT`. Waiting does not fetch/delete mail, and initialization is never automatic. Invalid required settings show `CONFIG_ERROR` first. Do not create an empty `state.db`. Token validation follows DB readiness, so the waiting message alone does not validate OAuth.

Choose your initial treatment of existing mail:

| Init option | Effect |
| --- | --- |
| --from-now | Record all current UIDs as ignored; start with future arrivals |
| --all | Import all current mail without ordinary ntfy notifications |
| --since YYYY-MM-DD | Import IMAP SINCE-selected mail |
| --latest N / --uid UID | Import latest N / one UID; positive integers |
| --dry-run | Inspect selected mail without Gmail/Drive writes; DB creation/migration can still occur |
| --yes | Skip interactive confirmation for multiple imports |

```bash
docker compose exec gmail-bridge python -m app.main --lang en init --from-now
docker compose exec gmail-bridge python -m app.main --lang en status
```

In QNAP Container Station, open the running container's Console in `/app` (start `sh` if needed) and enter only `python -m app.main ...`, without the host `docker compose exec` prefix. Keep the container CMD unchanged. The waiting service releases its lock; init takes the shared lock. After init finishes, the next check resumes normal operation with `CONFIG_OK`. The loop waits 60 seconds after processing, rather than running on an exact minute schedule.

**Partial init does not ignore unselected old messages.** A later run can import and notify those messages. Choose `--all` to import all old mail silently or `--from-now` to ignore all existing mail. Test imports in a separate mailbox/database. `--from-now` also changes existing records to ignored: never use it for an upgrade, migration or ordinary restart.

## 5. Compose layouts and QNAP

| Example | Purpose |
| --- | --- |
| docker-compose.config.image.example.yml | v1.1+ Hub image, single /config, exact version required |
| docker-compose.config.example.yml | Source build, single /config |
| docker-compose.image.example.yml | Legacy separate /app mounts, default image 1.0.0; set BRIDGE_VERSION explicitly when upgrading |
| docker-compose.example.yml | Source build with legacy mounts |

The `/config` folder contains `config.ini`, `token.json`, optional `notification_senders.ini`, `data/` (DB, sidecars, lock, cleanup marker), `backups/` and `logs/`. Code stays at `/app`. With `BRIDGE_CONFIG_DIR=/config`, runtime files use only that root; no legacy fallback occurs. Prefer relative token/filter paths within the root; update old absolute `/app` paths. Never mix layouts or share one DB across services.

For QNAP, mount one pre-created dedicated host folder at `/config` and set `BRIDGE_CONFIG_DIR=/config`, UID/GID and TZ. Do not add a command, entrypoint or legacy while-loop. UI support varies by Container Station version. `credentials.json` is only needed on the OAuth desktop, not mounted at runtime. Bind sources must exist; examples disable automatic creation of missing host paths.

Container recreation preserves state when the same host path is used. Compose defaults to Asia/Tokyo; the image alone defaults to Etc/UTC. Cleanup dates/logs use container local time; DB timestamps and daily backup dates use UTC. Retain the latest 14 daily DB files; remove run logs older than 30 days by modification time. Migration backups are excluded from daily rotation.

## Next

[Upgrade/recovery](MAINTENANCE.en.md) · [Notifications](NOTIFICATIONS.en.md) · [Docker distribution](DOCKER_RELEASE.en.md)
