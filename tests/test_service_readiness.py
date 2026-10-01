"""Local startup, Console init and recovery; remote traffic is prohibited."""

import contextlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import config, i18n, locking, main, service, state


class LocalServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': str(self.root), 'BRIDGE_LANGUAGE': 'en'})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(i18n.set_language, 'ja')
        i18n.set_language('en')
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('No network'))
        network.start()
        self.addCleanup(network.stop)
        self.output = io.StringIO()
        output = contextlib.redirect_stdout(self.output)
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.reporter = service.StatusReporter()
        self.write_config()
        self.write_token()

    def write_config(self, extra=''):
        (self.root / 'config.ini').write_text(
            '[imap]\nhost=imap.example.invalid\nuser=synthetic\npassword=100%synthetic\n'
            'delete_after_import=false\n[notification]\nenabled=false\n' + extra,
            encoding='utf-8')

    def write_token(self):
        (self.root / 'token.json').write_text(json.dumps({
            'client_id': 'synthetic', 'client_secret': 'synthetic', 'refresh_token': 'synthetic',
        }), encoding='utf-8')

    def initialize(self):
        db = state.connect(create=True)
        try:
            state.save_mailbox_state(db, 'INBOX', '123')
        finally:
            db.close()

    def cycle(self):
        return service.run_cycle(self.reporter)



class ServiceReadinessTests(LocalServiceTest):
    def test_missing_db_waits_and_console_init_recovers(self):
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(self.cycle(), 'waiting_for_init')
            self.assertEqual(self.cycle(), 'waiting_for_init')
            run.assert_not_called()
            self.assertFalse((self.root / 'data/state.db').exists())
            self.assertEqual(self.output.getvalue().count('[WAITING_FOR_INIT]'), 1)
            imap = MagicMock()
            imap.select_mailbox.return_value = '123'
            imap.search_all_uids.return_value = [1, 2]
            with patch.object(main, 'make_imap', return_value=imap):
                main.command_init(SimpleNamespace(from_now=True, dry_run=False), config.load_config())
            self.assertEqual(self.cycle(), 'ready')
            self.assertEqual(run.call_count, 2)
            self.assertTrue((self.root / 'data/last_cleanup_date').exists())
            self.assertIn('[CONFIG_OK]', self.output.getvalue())

    def test_valid_uninitialized_db_does_not_launch_commands(self):
        db = state.connect(create=True)
        db.close()
        with patch.object(service.subprocess, 'run') as run:
            self.assertEqual(self.cycle(), 'waiting_for_init')
            run.assert_not_called()
        self.initialize()
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        stream.close()

    def test_invalid_config_reloads_and_recovers_without_restart(self):
        self.initialize()
        (self.root / 'config.ini').write_text('synthetic-secret-invalid-ini', encoding='utf-8')
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(self.cycle(), 'config_error')
            self.assertEqual(self.cycle(), 'config_error')
            run.assert_not_called()
            self.assertEqual(self.output.getvalue().count('[CONFIG_ERROR]'), 1)
            self.assertNotIn('synthetic-secret', self.output.getvalue())
            self.write_config()
            self.assertEqual(self.cycle(), 'ready')
            self.assertEqual(run.call_count, 2)

    def test_corrupt_db_is_error_and_manual_restore_recovers(self):
        (self.root / 'data').mkdir()
        path = self.root / 'data/state.db'
        path.write_bytes(b'synthetic corruption')
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(self.cycle(), 'db_error')
            run.assert_not_called()
            self.assertEqual(path.read_bytes(), b'synthetic corruption')
            self.assertIn('[DB_ERROR]', self.output.getvalue())
            self.assertNotIn('[WAITING_FOR_INIT]', self.output.getvalue())
            # Operator restores a valid initialized DB; the supervisor never does so.
            path.unlink()
            self.initialize()
            self.assertEqual(self.cycle(), 'ready')

    def test_missing_or_malformed_token_blocks_children_without_leaking_values(self):
        self.initialize()
        path = self.root / 'token.json'
        for content in (None, 'synthetic-secret-invalid-json', '{"refresh_token": "synthetic-secret"}'):
            if content is None:
                path.unlink()
            else:
                path.write_text(content, encoding='utf-8')
            with patch.object(service.subprocess, 'run') as run:
                self.assertEqual(self.cycle(), 'config_error')
                run.assert_not_called()
        self.assertNotIn('synthetic-secret', self.output.getvalue())
        self.write_token()
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(self.cycle(), 'ready')

    @unittest.skipIf(locking.fcntl is None, 'Linux flock required')
    def test_init_lock_defers_cycle_and_release_recovers(self):
        self.initialize()
        stream = locking.acquire_lock()
        try:
            with patch.object(service.subprocess, 'run') as run:
                self.assertEqual(self.cycle(), 'waiting_for_lock')
                run.assert_not_called()
        finally:
            stream.close()
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            self.assertEqual(self.cycle(), 'ready')

    def test_run_failure_never_launches_cleanup_or_marks_it_complete(self):
        self.initialize()
        with patch.object(service.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            self.assertEqual(self.cycle(), 'run_failed')
            self.assertEqual(run.call_count, 1)
        self.assertFalse((self.root / 'data/last_cleanup_date').exists())

    def test_config_changed_during_run_prevents_cleanup(self):
        self.initialize()

        def finish_run(*args, **kwargs):
            self.write_config('ttl_minutes=-1\n')
            return SimpleNamespace(returncode=0)

        with patch.object(service.subprocess, 'run', side_effect=finish_run) as run:
            self.assertEqual(self.cycle(), 'config_error')
            self.assertEqual(run.call_count, 1)
        self.assertFalse((self.root / 'data/last_cleanup_date').exists())

    def test_supervisor_survives_local_error_then_next_cycle(self):
        stop = MagicMock()
        stop.is_set.side_effect = [False, False, True]
        with patch.object(service, 'run_cycle', side_effect=[OSError('synthetic-secret'), 'ready']) as cycle:
            service.main(stop)
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(stop.wait.call_count, 2)
        stop.wait.assert_called_with(60)
        self.assertIn('[SERVICE_ERROR]', self.output.getvalue())
        self.assertNotIn('synthetic-secret', self.output.getvalue())

    def test_migration_error_is_reported_and_lock_is_released(self):
        with patch.object(service, 'connect', side_effect=state.DatabaseError(
                '[DB_MIGRATION_ERROR] Migration could not complete.')), \
                patch.object(service.subprocess, 'run') as run:
            self.assertEqual(self.cycle(), 'db_error')
            run.assert_not_called()
        self.assertIn('[DB_MIGRATION_ERROR]', self.output.getvalue())
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        stream.close()


class NotificationConfigTests(LocalServiceTest):
    def test_filter_off_and_disabled_never_require_sender_file(self):
        for value in ('enabled=false\nsender_filter_mode=allowlist\n',
                      'enabled=true\ntopic=synthetic\nsender_filter_mode=off\n'):
            self.write_config()
            path = self.root / 'config.ini'
            text = path.read_text().replace('enabled=false\n', value)
            path.write_text(text, encoding='utf-8')
            self.assertIsNotNone(config.load_config().notification_settings)

    def test_active_filter_requires_valid_file_and_can_recover(self):
        self.write_config('sender_filter_mode=combined\n')
        path = self.root / 'config.ini'
        path.write_text(path.read_text().replace('enabled=false', 'enabled=true\ntopic=synthetic'), encoding='utf-8')
        with self.assertRaises(config.ConfigError):
            config.load_config()
        rules = self.root / 'notification_senders.ini'
        for value in ('synthetic-secret-invalid-ini', '[allowlist]\naddresses=bad@@example.com\n',
                      '[allowlist]\ndomains=*.example.com\n', '[allowlist]\naddress=a@example.com\n'):
            rules.write_text(value, encoding='utf-8')
            with self.assertRaises(config.ConfigError) as error:
                config.load_config()
            self.assertNotIn('synthetic-secret', str(error.exception))
        rules.write_text(('[allowlist]\naddresses=User@example.com\ndomains=Example.COM\n'
                         '[blocklist]\naddresses=news@example.com\n').replace('example.com', 'EXAMPLE.COM'), encoding='utf-8')
        settings = config.load_config().notification_settings
        self.assertEqual(settings.allow_addresses, frozenset({'user@example.com'}))
        self.assertEqual(settings.allow_domains, frozenset({'example.com'}))
        self.assertEqual(settings.block_addresses, frozenset({'news@example.com'}))

    def test_invalid_new_settings_are_rejected_and_legacy_defaults_preserved(self):
        for option in ('sender_filter_mode=typo', 'ttl_minutes=-1', 'ttl_minutes=abc',
                       'include_sender=typo', 'include_subject=typo'):
            self.write_config(option + '\n')
            with self.assertRaises(config.ConfigError):
                config.load_config()
        self.write_config()
        settings = config.load_config().notification_settings
        self.assertEqual(settings.ttl_minutes, 0)
        self.assertEqual(settings.sender_filter_mode, 'off')
        self.assertFalse(settings.include_sender)
        self.assertFalse(settings.include_subject)

    def test_active_ntfy_invalid_provider_topic_and_url_stop_configuration(self):
        for option in ('provider=unsupported\ntopic=synthetic', 'topic=',
                       'topic=synthetic/path',
                       'topic=synthetic\nserver_url=not-a-url',
                       'topic=synthetic\nserver_url=https://example.com:invalid',
                       'topic=synthetic\nserver_url=https://example.com?synthetic-secret',
                       'topic=synthetic\ntoken=synthetic\n    unexpected-line'):
            self.write_config(option + '\n')
            path = self.root / 'config.ini'
            path.write_text(path.read_text().replace('enabled=false', 'enabled=true'), encoding='utf-8')
            with self.assertRaises(config.ConfigError):
                config.load_config()
