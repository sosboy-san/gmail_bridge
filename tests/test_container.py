"""Linux timezone integration tests, also executed inside the built image in CI."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main, service


@unittest.skipUnless(hasattr(time, 'tzset'), 'Requires Linux/POSIX timezone handling')
class ContainerTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'TZ': 'Asia/Tokyo'})
        self.environment.start()
        time.tzset()
        self.addCleanup(self.restore_timezone)

    def restore_timezone(self):
        self.environment.stop()
        time.tzset()

    def test_tokyo_offset_and_child_inheritance(self):
        self.assertEqual(datetime.now().astimezone().utcoffset(), timedelta(hours=9))
        result = subprocess.check_output([
            sys.executable, '-c',
            'from datetime import datetime, timezone; '
            'stamp = datetime(2024, 1, 1, 15, tzinfo=timezone.utc).timestamp(); '
            'print(datetime.fromtimestamp(stamp).isoformat())',
        ], text=True)
        self.assertEqual(result.strip(), '2024-01-02T00:00:00')

    def test_cleanup_rolls_over_at_tokyo_midnight(self):
        before = datetime(2024, 1, 1, 14, 59, tzinfo=timezone.utc).timestamp()
        after = datetime(2024, 1, 1, 15, 0, tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(service, 'prepare_cycle'), \
                patch.object(service, 'MARKER', Path(directory) / 'last_cleanup_date'), \
                patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                patch.object(service, 'datetime') as clock:
            clock.now.return_value = datetime.fromtimestamp(before)
            service.run_cycle()
            self.assertEqual(service.MARKER.read_text().strip(), '2024-01-01')
            clock.now.return_value = datetime.fromtimestamp(after)
            service.run_cycle()
            self.assertEqual(service.MARKER.read_text().strip(), '2024-01-02')
            service.run_cycle()
            self.assertEqual(run.call_count, 5)  # Three runs, two daily cleanups.
            self.assertEqual(main.datetime.fromtimestamp(after).date().isoformat(), '2024-01-02')


if __name__ == '__main__':
    unittest.main()
