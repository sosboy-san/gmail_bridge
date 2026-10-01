"""Runtime root isolation and command exclusion, without external services."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, locking, state
from app.paths import runtime_path


class RuntimePathsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': str(self.root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_legacy_paths_remain_unchanged(self):
        with patch.dict(os.environ):
            os.environ.pop('BRIDGE_CONFIG_DIR')
            self.assertEqual(runtime_path('data/state.db'), Path('data/state.db'))
            self.assertEqual(runtime_path(self.root), self.root)

    def test_config_and_database_use_selected_root(self):
        (self.root / 'config.ini').write_text('[test]\nvalue = selected\n', encoding='utf-8')
        self.assertEqual(config.read_config()['test']['value'], 'selected')
        db = state.connect(create=True)
        try:
            self.assertTrue((self.root / 'data/state.db').is_file())
            backup = state.backup_database(db)
            self.assertTrue(Path(backup).is_relative_to(self.root))
        finally:
            db.close()

    def test_missing_config_does_not_fall_back(self):
        with self.assertRaises(config.ConfigError):
            config.read_config()

    def test_invalid_roots_and_escape_are_rejected(self):
        for value in ('', str(self.root / 'missing')):
            with self.subTest(value=value), patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': value}):
                with self.assertRaisesRegex(ValueError, 'CONFIG_ERROR'):
                    runtime_path('config.ini')
        for value in ('../outside', self.root.parent / 'outside'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runtime_path(value)
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            runtime_path('escape/outside')

    @unittest.skipIf(locking.fcntl is None, 'Linux flock required')
    def test_lock_excludes_other_process_and_releases(self):
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        try:
            result = subprocess.run(
                [sys.executable, '-c',
                 'from app.locking import acquire_lock; s=acquire_lock(); '
                 'raise SystemExit(0 if s is None else 1)'],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            invoked = []

            @locking.locked_command
            def command():
                invoked.append(True)

            with self.assertRaises(RuntimeError):
                command()
            self.assertEqual(invoked, [])
        finally:
            stream.close()
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        stream.close()

    @unittest.skipIf(locking.fcntl is None, 'Linux flock required')
    def test_failed_command_releases_lock(self):
        @locking.locked_command
        def command():
            raise ValueError('synthetic failure')

        with self.assertRaisesRegex(ValueError, 'synthetic failure'):
            command()
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        stream.close()
