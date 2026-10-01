"""Supervise safe startup and retry readiness after each 60-second wait."""

import os
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from app.config import (
    ConfigError,
    configure_language,
    load_config,
    validate_runtime_files,
)
from app.i18n import set_language, t
from app.locking import LockBusy, acquire_lock
from app.paths import runtime_path
from app.state import (
    DatabaseError,
    DatabaseMissing,
    DatabaseUninitialized,
    connect,
    require_initialized,
)

MARKER = Path("data/last_cleanup_date")
POLL_SECONDS = 60


class StatusReporter:
    """Report transitions once, rather than repeating identical waiting logs."""

    def __init__(self):
        self.previous = None

    def report(self, state, detail):
        current = (state, detail)
        if current != self.previous:
            print(f'[{state}] {detail}', flush=True)
            self.previous = current


def prepare_cycle():
    """Check local readiness under the init lock, without any remote traffic."""
    set_language(os.environ.get("BRIDGE_LANGUAGE", "ja"))
    config = load_config()
    configure_language(config=config)
    stream = acquire_lock()
    if stream is None:
        raise LockBusy(t('lock.busy'))
    try:
        db = connect()
        try:
            require_initialized(db, config.get('imap', 'mailbox', fallback='INBOX'))
            validate_runtime_files(config)
        finally:
            db.close()
    finally:
        stream.close()
    # Release before spawning commands; each command acquires the same lock
    # and validates its own current config/database again.
    return config


def run_cycle(reporter=None):
    reporter = reporter or StatusReporter()
    try:
        prepare_cycle()
        return _run_ready_cycle(reporter)
    except (DatabaseMissing, DatabaseUninitialized) as error:
        reporter.report('WAITING_FOR_INIT', _detail(error))
        return 'waiting_for_init'
    except DatabaseError as error:
        code = 'DB_MIGRATION_ERROR' if str(error).startswith('[DB_MIGRATION_ERROR]') else 'DB_ERROR'
        reporter.report(code, _detail(error))
        return 'db_error'
    except LockBusy as error:
        reporter.report('WAITING_FOR_LOCK', _detail(error))
        return 'waiting_for_lock'
    except (ConfigError, ValueError) as error:
        reporter.report('CONFIG_ERROR', _detail(error))
        return 'config_error'


def _run_ready_cycle(reporter):
    reporter.report('CONFIG_OK', t('service.ready'))
    result = subprocess.run([sys.executable, "-m", "app.main", "run"], check=False)
    if result.returncode != 0:
        reporter.report('RUN_FAILED', t('service.run_failed'))
        return 'run_failed'
    marker = runtime_path(MARKER)
    today = datetime.now().date().isoformat()
    previous = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if previous != today:
        # Recheck settings/DB/token under the lock before starting cleanup.
        # Do not mark cleanup complete if configuration changed or init began.
        prepare_cycle()
        result = subprocess.run([sys.executable, "-m", "app.main", "cleanup"], check=False)
        if result.returncode != 0:
            reporter.report('CLEANUP_FAILED', t('service.cleanup_failed'))
            return 'cleanup_failed'
        marker.parent.mkdir(parents=True, exist_ok=True)
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(today + "\n", encoding="utf-8")
        temporary.replace(marker)
    return 'ready'


def _detail(error):
    message = str(error)
    if message.startswith('[') and '] ' in message:
        return message.split('] ', 1)[1]
    return message


def main(stop=None):
    if stop is None:
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    reporter = StatusReporter()
    # Finish active children before stopping. Every retry reads fresh settings.
    while not stop.is_set():
        try:
            run_cycle(reporter)
        except (OSError, RuntimeError, ValueError):
            # OS/library errors can include user-configured paths or values.
            reporter.report('SERVICE_ERROR', t('service.retry_error'))
        stop.wait(POLL_SECONDS)
    print(t("service.stopped"), flush=True)


if __name__ == "__main__":
    main()
