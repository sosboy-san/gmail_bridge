"""UTF-8 JSON catalogs; new languages need no Python changes."""

import json
import re
from pathlib import Path

LOCALE_DIR = Path(__file__).with_name("locales")
_language = "ja"
_catalogs = {}


def available_languages():
    return sorted(path.stem for path in LOCALE_DIR.glob("*.json"))


def set_language(language):
    global _language
    language = language.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", language):
        language = "en"
    if language not in available_languages():
        language = language.split("_")[0]
    _language = language if language in available_languages() else "en"


def _catalog(language):
    if language not in _catalogs:
        _catalogs[language] = json.loads(
            (LOCALE_DIR / f"{language}.json").read_text(encoding="utf-8")
        )
    return _catalogs[language]


def t(key, **values):
    template = _catalog(_language).get(key, _catalog("en").get(key, key))
    return template.format(**values) if values else template


def argparse_text(message):
    """argparse uses %-formatting after translation, unlike application messages."""
    return _catalog(_language).get("argparse." + message, message)
