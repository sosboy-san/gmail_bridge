# Contributing

English · [日本語](CONTRIBUTING.md)

## Development checks

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app make_token.py tests tools
python -m ruff check app make_token.py tests tools
python -m unittest discover -s tests -v
python tools/check_release.py
BRIDGE_VERSION=1.1.0 docker compose -f docker-compose.config.image.example.yml config --quiet
docker build -t gmail-bridge:check .
```


Use Python 3.12 and the commands here. Tests use synthetic messages, temporary databases and mocked clients; they need no service credentials. CI also validates Compose and builds the Linux image. Linux-specific flock and timezone checks are skipped on Windows and tested on Linux.

To add a language, copy `en.json` to a new language-code filename and translate values without changing keys, placeholders, or HTML. `argparse.*` entries use percent-format placeholders; other messages use braces. ntfy titles are sent as UTF-8 JSON. Keep legacy default fallback-label entries unchanged because they identify stored labels. New catalogs are discovered automatically and missing keys fall back to English.

Preserve the separate import and notification states, pending Gmail-ID recovery, and all IMAP deletion guards. External error strings, database states, protocol commands and original mail are not translated. Test schema or workflow changes with existing state and interruption scenarios. Dependency upgrades should be reviewed separately from behavior changes.

Keep Japanese and English document peers synchronized. HTML language navigation must preserve the current page role.
