# Security

English · [日本語](SECURITY.md)


Publish only the source, catalogs, examples, tests, container definitions, and documentation. `python tools/check_release.py --archive` exports an explicit file set; it excludes local environments, runtime state and private configuration. Extract the archive into a fresh directory before creating your first commit.

Review account details, personal/company names, OAuth credentials/tokens, ntfy topics/tokens, Drive links/IDs, NAS paths, logs, databases, backups and real-mail fixtures. The scanner is heuristic and cannot prove the absence of arbitrary secrets. It reports locations and types rather than matched values. Gitignore does not remove secrets already in history.

Use the staged changes using git status, git diff --cached and git ls-files to inspect staged content locally. Create a **Private** repository first, using `gh repo create ... --private` if desired. Check CI and complete live acceptance testing. Only the owner should change visibility to Public after final inspection of files, history and artifacts. See RELEASE_NOTES.en.md for validation results.

If a secret leaks, revoke/rotate it and then address history and artifacts. Never attach unredacted email, tokens, or logs to public issues. Gmail and Drive receive email content; protect local runtime data and use appropriate organizational authorization.


The entire /config folder is private. It holds settings, writable tokens, database metadata including sender names/previews even when display is off, backups and logs. Optional notification detail sends selected mail metadata to ntfy; protect topics/ACLs. Filters do not authenticate senders.
