# Uninstall

English · [日本語](UNINSTALL.md)


Run `docker compose down`, or stop/remove the application in Container Station. Disable any separate scheduler. Bind-mounted host files remain after container removal.

For later reinstallation, privately retain config, credentials, token, the complete state directory, and backups. Losing the database loses deduplication history and can cause duplicate imports. `init --from-now` deliberately ignores all currently existing mail, including mail not yet imported.

For complete removal, revoke this OAuth application's access from your Google account, remove its dedicated OAuth client if no longer needed, revoke dedicated ntfy tokens/subscriptions, and delete only the verified Bridge-specific host paths and image. Consider NAS snapshots and external backups separately.

Imported Gmail messages and Drive attachments are not removed automatically. Deleting Drive files breaks fallback links. Source mail already deleted by cleanup is not restored by uninstalling.
