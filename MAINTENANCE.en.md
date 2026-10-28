# Upgrades, maintenance and recovery — v1.1.1

English · [日本語](MAINTENANCE.md)

## Upgrade from v1.0 or rc.2

1. Read the target release notes. Record your current exact image version/digest, Compose, environment, UID/GID and host paths.
2. Stop the service with `docker compose stop`. Stop all other init/run/cleanup processes, containers and scheduled tasks using this database, and wait for them to finish.
3. Privately back up **configuration, token, the complete data directory (including SQLite sidecars), backups, logs, Compose and local .env** from the stopped deployment. Verify readability and free space. Keep desktop credentials separately.
4. Keep the current mount layout for the first upgrade. Change only `BRIDGE_VERSION=1.1.1` in `.env`; do not replace existing configuration/token/database with examples. With legacy mounts, leave BRIDGE_CONFIG_DIR unset.
5. Run `docker compose config --quiet` and `docker compose pull`. Retain the previous image for rollback. **Never run init during an upgrade.**
6. While the service remains stopped, validate local state:

```bash
docker compose run --rm gmail-bridge python -m app.main --lang en status
```

Status checks the existing DB and performs required migration, without creating a new DB or connecting to IMAP/Gmail. If it fails, do not start the service.

7. Check the migration backup if created, mailbox identity, initialization state and message count. Run `docker compose up -d` and inspect logs, new imports, token refresh and daily backups. Re-enable deletion only after verifying the retained data.

rc.2 already uses schema 2, so promotion to v1.1.1 needs no new migration or init when the same state is retained. Use exact image tags; latest/major/minor can change later. `docker compose restart` does not install a new image; pull followed by up recreates the container.

## Move legacy mounts to /config

Separate a version upgrade from a storage-layout change. Stop all processes and make a complete backup first. **Copy** config.ini, token.json, filter file if used, all of data, backups and logs into a new dedicated folder; preserve initialized state. Convert old absolute `/app` token/filter paths to relative paths inside the new root. Keep account/mailbox identities unchanged.

Use docker-compose.config.image.example.yml with one writable `/config` mount and BRIDGE_CONFIG_DIR=/config. Verify UID/GID, TZ and exact version. Do not combine old mounts or start the old service. Run stopped status and compare state/counts before startup. Keep the old folder until verified. Init is not a migration tool.

## Database migrations and backups

Schema uses `PRAGMA user_version`: v1.0 is 0, rc.1 is 1, rc.2/v1.1.1 is 2. Existing DB integrity/schema is checked; a dedicated SQLite backup is created; additions and version update occur transactionally. Existing import/notification states and notification TTL origins are preserved. Schema 2 adds sender display name and preview; old missing fields are not fetched from IMAP. Failure rolls back and stops migration, including failure to create a backup.

| Backup | /config path / purpose |
| --- | --- |
| Manual complete backup | Private location chosen by operator; required for whole-deployment rollback |
| Migration backup | backups/db/migrations/state_before_schema_2_TIMESTAMP_ID.db; not daily-rotated |
| Daily SQLite backup | backups/db/state_YYYY-MM-DD.db; UTC date, integrity checked, latest 14 files |

Legacy paths are under `/app/backups`. Do not simply copy a live state.db. Backups can contain addresses, names, subjects, previews, IDs and notification states; keep them private.

## Rollback and restore

Stop all processes; preserve the problem state separately. Choose configuration and DB compatible with the target application version. There is no automatic schema downgrade; reverting to v1.0 requires the complete pre-upgrade snapshot. Do not mix state.db/WAL/SHM from different points in time. Restore compatible files and verify permissions, tokens, Compose, environment and image version. For v1.1, validate with stopped status before startup.

Restoring SQLite does not roll back Gmail/Drive or restore deleted source mail. Reconcile remote messages saved after the snapshot; lost deduplication records may cause duplicate imports. Do not delete a damaged DB or use init --from-now to conceal an error. Without a suitable backup, establish a recovery plan by reconciling source and Gmail data.

## Service diagnostics

| State | Action |
| --- | --- |
| CONFIG_ERROR | Fix UTF-8 INI, required values, modes/TTL/filter paths. Invalid enabled notification settings also defer operations |
| Missing/invalid OAuth file | Check configured path, mounts and permissions; replace valid desktop-generated token while stopped |
| WAITING_FOR_INIT | New installation: explicit init. Existing installation: investigate missing/wrong mount or lost DB first |
| DB_ERROR | Empty/corrupt/unknown database; stop, preserve and restore compatible state |
| DB_MIGRATION_ERROR | Check capacity and DB/backup permissions; preserve state, fix cause and retry |
| WAITING_FOR_LOCK | Wait for current process; never remove an active lock |
| CONFIG_OK | Local readiness only; does not prove remote API authentication or all-message success |
| RUN_FAILED / CLEANUP_FAILED / SERVICE_ERROR | Inspect logs and next cycle; nonzero run exit prevents that cycle's cleanup |

The service remains running and rechecks after a 60-second post-processing wait. Repeated identical waiting reasons are not logged repeatedly. Fixing configuration resumes operations. Readiness is rechecked before cleanup; only successful cleanup updates data/last_cleanup_date.

Settings are reread at processing boundaries and before notifications. Changing connection/token paths stops the current batch and rebuilds clients next cycle. Replace OAuth files while stopped. A legacy individual file bind may retain the old inode after an editor replaces a file; recreate the container if needed.

Known limits: zero run exit is not a guarantee of full success; some existing IMAP failures return after alerting. Check failed counts and actual imports. Pending ordinary notifications wait for successful IMAP/UIDVALIDITY checks. Failed recovery alerts are not independently retried.

## Development workflow

Use GitHub as canonical source, isolate edits and synthetic tests, review the diff, run tests/lint/release checks and Compose validation, then commit/push within authorized scope. CI and both architectures precede release. Owner QNAP acceptance precedes stable promotion. Historical Phase documents describe their original stage, not current release status.
