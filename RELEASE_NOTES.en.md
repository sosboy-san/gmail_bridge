# Release notes

English · [日本語](RELEASE_NOTES.md)

## v1.1.1 — 2026-10-29

- Apply a 30-second socket timeout to IMAP connection/read waits, including greeting, STARTTLS, login and subsequent commands. This is an inactivity bound, not a total batch deadline.
- Discard failed/partial connections without protocol LOGOUT before retry. Preserve the existing three-attempt policy and 10/30-second waits. Close local resources even after logout fails.
- Add localized connection-stage logs without changing DB, notification states/TTL or deletion guards.
- Regression coverage uses silent loopback peers for greeting, STARTTLS and command waits, plus cleanup and reconnect cases. OS DNS resolution and continuously trickling responses are outside this total-time guarantee.

Validation: 107 offline tests, Ruff, compile/dependency/publication checks and amd64/arm64 image tests passed. On October 29, 2026, I deployed v1.1.1 on my QNAP Container Station and confirmed that it is running. Schema 2 and configuration remain compatible; do not repeat init.

## v1.1.0 — 2026-10-14

I promoted rc.2 after continuously operating it on my QNAP Container Station since October 1 and confirming no problems. This is deployment evidence for that environment, not comprehensive acceptance of all features/environments.

Runtime code, dependencies and schema 2 remain identical to rc.2. This release adds paired Japanese/English guides, website pages and Docker Hub documentation. Detailed notifications put sender name/address in Title, subject first and optional preview second in Body. UTF-8 JSON supports Japanese titles. Metadata is stored at import time; retries never refetch original mail. Filtering uses email addresses only.

v1.1 includes init notification suppression (including resumed imports), exact sender filtering, TTL, shared locks, safe startup waiting, explicit-init-only DB creation and single /config storage. Invalid enabled notification settings defer operations. Omitted/zero TTL remains unlimited; examples recommend 15 minutes. Schema 0/1 migration uses a dedicated backup and preserves notification states and TTL origins. rc.2 already uses schema 2.

Upgrade: stop all processes, back up the entire deployment, set exact version 1.1.0, pull, run stopped status and start. **Do not run init.** See [Maintenance](MAINTENANCE.en.md).

Validation: rc.2 passed 100 offline regression tests and amd64/arm64 publication CI. Offline tests, lint and publication-file checks are rerun after documentation changes; consult GitHub Actions for actual stable publication results.

Known limitations remain: duplicates in the remote-success/local-commit crash window, EXPUNGE races without UIDPLUS, no independent recovery-alert retry, and zero run exit not guaranteeing all-message success. Keep databases/backups containing previews private.

## v1.1.0-rc.2 — 2026-10-01

Added persisted sender names/previews and schema 2. Owner confirmed missing-subject fallback and leading whitespace normalization, followed by problem-free continued operation.

## v1.1.0-rc.1 — 2026-10-01

Added sender filters/TTL, init suppression, migrations, shared locking, startup waiting and single /config storage. Owner confirmed sender filtering.

## v1.0.0 — 2026-09-30

Initial stable release: localized CLI, validated configuration, certificate-verified STARTTLS, literal INI passwords, Gmail/Drive OAuth helper, container service and offline checks. I confirmed startup on my QNAP and resumed imports after token replacement. Historical details and CI evidence are retained in the [Japanese release history](RELEASE_NOTES.md).
