"""Read config without interpolation or leaking secret values in diagnostics."""

import configparser
import os
from pathlib import Path

from app.i18n import set_language, t


class ConfigError(ValueError):
    pass


def read_config(path="config.ini", required=True):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with Path(path).open(encoding="utf-8-sig") as stream:
            config.read_file(stream)
    except FileNotFoundError:
        if required:
            raise ConfigError(t("main.load_config.1")) from None
    except (configparser.Error, UnicodeError, OSError):
        raise ConfigError(t("config.invalid_file")) from None
    return config


def configure_language(language=None):
    set_language(language or os.environ.get("BRIDGE_LANGUAGE", "ja"))
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
    ):
        try:
            config.getboolean(section, option, fallback=False)
        except ValueError:
            raise ConfigError(t("config.invalid_option", section=section, option=option)) from None
    # Notification-specific failures remain isolated in notification_service.
    return config
