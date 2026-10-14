"""Read config without interpolation or leaking secret values in diagnostics."""

import configparser
import json
import os
import re
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.headerregistry import Address
from urllib.parse import urlsplit

from app.i18n import set_language, t
from app.paths import runtime_path


class ConfigError(ValueError):
    def __init__(self, message):
        super().__init__(f'[CONFIG_ERROR] {message}')


def read_config(path="config.ini", required=True):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with runtime_path(path).open(encoding="utf-8-sig") as stream:
            config.read_file(stream)
    except FileNotFoundError:
        if required:
            raise ConfigError(t("main.load_config.1")) from None
    except (configparser.Error, UnicodeError, OSError):
        raise ConfigError(t("config.invalid_file")) from None
    return config


def configure_language(language=None, *, config=None):
    set_language(language or os.environ.get("BRIDGE_LANGUAGE", "ja"))
    if config is None:
        config = read_config(required=False)
    set_language(language or os.environ.get("BRIDGE_LANGUAGE") or config.get(
        "general", "language", fallback="ja"
    ))


def load_config():
    config = read_config()
    for section, option in (("imap", "host"), ("imap", "user"), ("imap", "password")):
        if not config.get(section, option, fallback="").strip():
            raise ConfigError(t("config.required", section=section, option=option))
    for section, option, default, minimum, maximum in (
        ("imap", "port", 143, 1, 65535),
        ("imap", "delete_delay_days", 7, 1, None),
    ):
        try:
            value = config.getint(section, option, fallback=default)
        except ValueError:
            raise ConfigError(t("config.invalid_option", section=section, option=option)) from None
        if value < minimum or (maximum is not None and value > maximum):
            raise ConfigError(t("config.invalid_option", section=section, option=option))
    for section, option in (
        ("imap", "delete_after_import"), ("gmail", "force_not_spam"),
        ("notification", "enabled"),
        ("notification", "include_sender"), ("notification", "include_subject"),
        ("notification", "include_preview"),
    ):
        try:
            config.getboolean(section, option, fallback=False)
        except ValueError:
            raise ConfigError(t("config.invalid_option", section=section, option=option)) from None
    runtime_path(config.get('gmail', 'token_file', fallback='token.json'))
    config.notification_settings = validate_notifications(config)
    return config


@dataclass(frozen=True)
class NotificationSettings:
    enabled: bool
    include_sender: bool
    include_subject: bool
    sender_filter_mode: str
    ttl_minutes: int
    include_preview: bool = False
    allow_addresses: frozenset = frozenset()
    allow_domains: frozenset = frozenset()
    block_addresses: frozenset = frozenset()
    block_domains: frozenset = frozenset()


def _invalid_notification(option):
    return ConfigError(t('config.invalid_option', section='notification', option=option))


def _valid_domain(value):
    try:
        ascii_domain = value.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    return (len(ascii_domain) <= 253 and all(
        re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
        for label in ascii_domain.split('.')))


def _sender_values(config, section, option):
    values = set()
    for line in config.get(section, option, fallback='').splitlines():
        value = line.strip()
        if not value:
            continue
        if option == 'domains':
            valid = _valid_domain(value)
        else:
            try:
                address = Address(addr_spec=value)
                valid = (value.count('@') == 1 and address.username and
                         _valid_domain(address.domain) and not any(
                             char.isspace() or ord(char) < 32 or ord(char) == 127
                             for char in value) and not any(char in value for char in '<>,;'))
            except (ValueError, HeaderParseError):
                valid = False
        if not valid:
            raise ConfigError(t('config.invalid_sender_file'))
        values.add(value.lower())
    return frozenset(values)


def validate_notifications(config):
    enabled = config.getboolean('notification', 'enabled', fallback=False)
    mode = config.get('notification', 'sender_filter_mode', fallback='off').strip().lower()
    if mode not in ('off', 'allowlist', 'blocklist', 'combined'):
        raise _invalid_notification('sender_filter_mode')
    try:
        ttl = config.getint('notification', 'ttl_minutes', fallback=0)
    except ValueError:
        raise _invalid_notification('ttl_minutes') from None
    if ttl < 0:
        raise _invalid_notification('ttl_minutes')
    if enabled:
        if config.get('notification', 'provider', fallback='ntfy').strip().lower() != 'ntfy':
            raise _invalid_notification('provider')
        topic = config.get('notification', 'topic', fallback='').strip()
        if not topic or any(char.isspace() or ord(char) < 32 or ord(char) == 127
                            or char in '/\\?#' for char in topic):
            raise _invalid_notification('topic')
        token = config.get('notification', 'token', fallback='').strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in token):
            raise _invalid_notification('token')
        try:
            raw_url = config.get('notification', 'server_url', fallback='https://ntfy.sh').strip()
            url = urlsplit(raw_url)
            valid = (url.scheme in ('http', 'https') and url.hostname and
                     not url.username and not url.password and not url.query and
                     not url.fragment and not any(char.isspace() or ord(char) < 32 or ord(char) == 127
                                                  for char in raw_url))
            # Force validation of malformed port/bracket syntax without a network request.
            port = url.port
            valid = valid and (port is None or 1 <= port <= 65535)
        except ValueError:
            valid = False
        if not valid:
            raise _invalid_notification('server_url')
    values = {}
    # Disabled notifications and filter off never open the separate list file.
    if enabled and mode != 'off':
        path = config.get('notification', 'sender_filter_file', fallback='notification_senders.ini').strip()
        if not path:
            raise _invalid_notification('sender_filter_file')
        lists = configparser.ConfigParser(interpolation=None)
        try:
            with runtime_path(path).open(encoding='utf-8-sig') as stream:
                lists.read_file(stream)
        except (configparser.Error, UnicodeError, OSError):
            raise ConfigError(t('config.invalid_sender_file')) from None
        if lists.defaults() or set(lists.sections()) - {'allowlist', 'blocklist'}:
            raise ConfigError(t('config.invalid_sender_file'))
        for section, prefix in (('allowlist', 'allow'), ('blocklist', 'block')):
            if lists.has_section(section) and set(lists[section]) - {'addresses', 'domains'}:
                raise ConfigError(t('config.invalid_sender_file'))
            for option in ('addresses', 'domains'):
                values[f'{prefix}_{option}'] = _sender_values(lists, section, option)
    return NotificationSettings(
        enabled=enabled,
        include_sender=config.getboolean('notification', 'include_sender', fallback=False),
        include_subject=config.getboolean('notification', 'include_subject', fallback=False),
        include_preview=config.getboolean('notification', 'include_preview', fallback=False),
        sender_filter_mode=mode, ttl_minutes=ttl, **values,
    )


def validate_runtime_files(config):
    """Validate local OAuth material only; do not authenticate or refresh it."""
    path = runtime_path(config.get('gmail', 'token_file', fallback='token.json'))
    try:
        # Refresh needs write access; opening r+ checks it without changing bytes.
        with path.open('r+', encoding='utf-8') as stream:
            token = json.load(stream)
        if not isinstance(token, dict) or not all(
                isinstance(token.get(key), str) and token[key].strip()
                for key in ('client_id', 'client_secret', 'refresh_token')):
            raise ValueError
    except (OSError, ValueError, UnicodeError):
        raise ConfigError(t('config.invalid_token_file')) from None
