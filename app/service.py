"""Container loop: run, successful daily cleanup, then wait 60 seconds."""

import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from app.config import configure_language
from app.i18n import t

MARKER = Path("data/last_cleanup_date")


def run_cycle():
    subprocess.run([sys.executable, "-m", "app.main", "run"], check=False)
    today = datetime.now().date().isoformat()
    previous = MARKER.read_text(encoding="utf-8").strip() if MARKER.exists() else ""
    if previous != today:
        result = subprocess.run([sys.executable, "-m", "app.main", "cleanup"], check=False)
        if result.returncode == 0:
            MARKER.parent.mkdir(parents=True, exist_ok=True)
            temporary = MARKER.with_suffix(".tmp")
            temporary.write_text(today + "\n", encoding="utf-8")
            temporary.replace(MARKER)


def main():
    configure_language()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    # Finish the active child first. Docker's stop_grace_period allows time to
    # commit local state; forced termination still relies on pending recovery.
    while not stop.is_set():
        try:
            run_cycle()
        except OSError as error:
            print(t("service.cycle_error", error=error), flush=True)
        stop.wait(60)
    print(t("service.stopped"), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(t("cli.error", error=error), file=sys.stderr)
        sys.exit(1)
