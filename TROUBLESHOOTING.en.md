# Troubleshooting

English · [日本語](TROUBLESHOOTING.md)


Check mounts, `/app` working directory, required INI fields, UTF-8, and file permissions first. Tokens and runtime directories must be writable by the container user. Windows needs a Linux container for run's flock. Do not remove an active lock file.

IMAP uses STARTTLS with certificate verification, not implicit TLS on port 993. Fix certificates/trust or mount an appropriate CA bundle rather than disabling verification. Connection failure triggers three attempts; the next run retries. A changed UIDVALIDITY intentionally stops processing. Reconcile source mail and Gmail before any reinitialization; never just overwrite the recorded UIDVALIDITY.

For OAuth failures, check consent-screen Testing expiry, revoked access, organization policies, and clock. Generate a new token on a trusted desktop and replace it while the service is stopped. Drive fallback requires both APIs enabled and a token containing `drive.file`. Only attachment-related Gmail rejection triggers fallback; other API failures remain retryable. Drive links require the correct account and permissions.

Notification failures keep imported mail finalized and leave only the notification pending. Retry occurs during a later run, even with no new mail, but only after IMAP connection and UIDVALIDITY checks succeed. Outage alerts are suppressed after successful delivery. The existing recovery path records `ok` even when the recovery alert fails; recovery alerts are not independently queued. Mail imported while notifications are disabled does not create notifications; older pending notifications remain.

Cleanup requires enabled deletion and an expired recorded deadline. Disabling deletion also suspends existing schedules. Missing UIDs are deliberately left unconfirmed. On non-UIDPLUS servers, unrelated Deleted flags abort EXPUNGE. Failed cleanup never advances the daily marker. Inspect a dry-run while the service is stopped before retrying manually.

Run logs contain mail metadata and must remain private; other commands appear in container logs. Backups retain the latest 14 daily files, not strictly 14 calendar days. A zero run exit code or a running container does not guarantee all messages succeeded: inspect failure counts and state. DB restore or remote-success/local-commit crashes can still cause duplicate import.


For v1.1 startup states, DB migration failure and recovery, see [Maintenance](MAINTENANCE.en.md). WAITING_FOR_INIT is expected only for a new uninitialized installation; investigate paths/state loss on upgrades before using init. Notification TTL can expire pending entries; see [Notifications](NOTIFICATIONS.en.md).
