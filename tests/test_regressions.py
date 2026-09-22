"""Offline safety tests: synthetic messages, temporary SQLite, mocked services."""

import configparser
import contextlib
import importlib
import io
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from app import config as configuration
from app import i18n, main, mime_fallback, notification_service, service, state
from app.gmail_client import GmailClient, InvalidAttachmentError
from app.imap_client import ImapClient

ROOT = Path(__file__).resolve().parents[1]


def settings():
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({
        'imap': {'host': 'imap.example.invalid', 'user': 'test-user',
                 'password': 'synthetic-test-value', 'port': '143',
                 'delete_after_import': 'false', 'delete_delay_days': '7', 'label': 'Test'},
        'notification': {'enabled': 'true', 'provider': 'ntfy', 'topic': 'synthetic-test-topic'},
        'gmail': {'fallback_label': 'Test-Fallback'},
    })
    return config


def sample_mail(attachment=False):
    message = EmailMessage()
    message['From'] = 'sender@example.invalid'
    message['To'] = 'recipient@example.invalid'
    message['Subject'] = 'Synthetic test'
    message['Date'] = 'Mon, 01 Jan 2024 00:00:00 +0000'
    message['Message-ID'] = '<synthetic@example.invalid>'
    message.set_content('Synthetic body')
    message.add_alternative('<p>Synthetic body</p>', subtype='html')
    if attachment:
        message.add_attachment(b'not an executable', maintype='application',
                               subtype='octet-stream', filename='synthetic.bin')
    return message.as_bytes()


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.addCleanup(i18n.set_language, 'ja')
        i18n.set_language('en')
        # Fail rather than accidentally making a real connection.
        self.network = patch.object(socket, 'create_connection', side_effect=AssertionError('No network'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)


class StateFlowTests(IsolatedTest):
    def setUp(self):
        super().setUp()
        db_path = patch.object(state, 'DB_PATH', self.directory / 'state.db')
        db_path.start()
        self.addCleanup(db_path.stop)
        self.db = state.connect()
        self.addCleanup(self.db.close)
        self.config = settings()
        self.imap = MagicMock()
        self.imap.fetch_raw.return_value = sample_mail()
        self.imap.is_seen.return_value = False
        self.imap.get_summary.side_effect = ImapClient.get_summary
        self.gmail = MagicMock()
        self.gmail.import_message.return_value = 'synthetic-gmail-id'

    def process(self, uid=1, drive=None):
        return main.process_uid(self.imap, self.gmail, drive, self.db,
                                self.config, 'INBOX', '123', uid)

    def test_notification_failure_does_not_repeat_import(self):
        self.assertEqual(self.process(), 'imported')
        self.gmail.mark_unread.assert_called_once()
        with patch.object(notification_service, 'make_ntfy_client') as factory:
            factory.return_value.send.side_effect = OSError('synthetic outage')
            self.assertEqual(notification_service.send_pending_notifications(self.db, self.config),
                             {'sent': 0, 'failed': 1})
            self.assertEqual(len(state.get_pending_notifications(self.db)), 1)
            self.assertEqual(self.process(), 'skipped')
            factory.return_value.send.side_effect = None
            self.assertEqual(notification_service.send_pending_notifications(self.db, self.config),
                             {'sent': 1, 'failed': 0})
        self.gmail.import_message.assert_called_once()
        self.assertTrue(state.is_processed(self.db, 'INBOX', '123', 1))
        self.assertEqual(state.get_pending_notifications(self.db), [])

    def test_pending_import_resumes_after_label_failure(self):
        self.gmail.apply_source_label.side_effect = OSError('synthetic label failure')
        self.assertEqual(self.process(), 'failed')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['status'],
                         'gmail_imported_pending')
        self.gmail.apply_source_label.side_effect = None
        self.assertEqual(self.process(), 'imported')
        self.gmail.import_message.assert_called_once()

    def test_fallback_pending_resumes_without_reupload_or_reimport(self):
        self.imap.fetch_raw.return_value = sample_mail(attachment=True)
        self.gmail.import_message.side_effect = [InvalidAttachmentError(), 'synthetic-fallback-id']
        self.gmail.apply_source_label.side_effect = OSError('synthetic label failure')
        drive = MagicMock()
        drive.upload_file.return_value = {
            'id': 'synthetic-drive-id', 'webViewLink': 'https://drive.example.invalid/synthetic',
        }
        self.assertEqual(self.process(drive=drive), 'failed')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['status'],
                         'fallback_gmail_imported_pending')
        self.gmail.apply_source_label.side_effect = None
        self.assertEqual(self.process(drive=drive), 'fallback')
        self.assertEqual(self.gmail.import_message.call_count, 2)
        drive.upload_file.assert_called_once()
        self.assertEqual(len(state.get_pending_notifications(self.db)), 1)

    def test_seen_source_is_not_marked_unread(self):
        self.imap.is_seen.return_value = True
        self.assertEqual(self.process(), 'imported')
        self.gmail.mark_unread.assert_not_called()

    def test_notification_initialization_failure_preserves_import(self):
        self.process()
        self.config['notification']['topic'] = ''
        notification_service.send_pending_notifications(self.db, self.config)
        self.assertEqual(self.process(), 'skipped')
        self.assertEqual(len(state.get_pending_notifications(self.db)), 1)

    def test_only_finalized_expired_messages_are_deletion_candidates(self):
        self.process()
        self.assertEqual(state.get_delete_candidates(self.db), [])
        self.config['imap']['delete_after_import'] = 'true'
        self.process(uid=2)
        self.assertEqual(state.get_delete_candidates(self.db), [])
        self.db.execute("UPDATE messages SET delete_after='2000-01-01T00:00:00+00:00' WHERE uid=2")
        state.ensure_message(self.db, 'INBOX', '123', 3)
        state.mark_gmail_imported_pending(self.db, 'INBOX', '123', 3, 'synthetic-pending', None)
        self.assertEqual([r['uid'] for r in state.get_delete_candidates(self.db)], [2])

    def test_outage_notification_deduplicates_and_retries_failed_alert(self):
        with patch.object(main, 'send_system_notification', side_effect=[False, True]) as send:
            main.handle_imap_connection_failure(self.db, self.config, OSError('synthetic'))
            self.assertEqual(state.get_system_state(self.db, 'imap_status'), 'down_unnotified')
            main.handle_imap_connection_failure(self.db, self.config, OSError('synthetic'))
            main.handle_imap_connection_failure(self.db, self.config, OSError('synthetic'))
            self.assertEqual(send.call_count, 2)
            self.assertEqual(state.get_system_state(self.db, 'imap_status'), 'down')

    def test_recovery_notifies_then_restores_ok(self):
        state.save_mailbox_state(self.db, 'INBOX', '123')
        state.set_system_state(self.db, 'imap_status', 'down')
        self.imap.select_mailbox.return_value = '123'
        self.imap.search_all_uids.return_value = []
        args = SimpleNamespace(uid=None, dry_run=False)
        # Separate DB connection because command_run owns and closes it.
        with patch.object(main, 'acquire_run_lock', return_value=MagicMock()), \
                patch.object(main, 'fcntl', MagicMock()), \
                patch.object(main, 'make_imap', return_value=self.imap), \
                patch.object(main, 'backup_database', return_value=None), \
                patch.object(main, 'send_system_notification', return_value=True) as send:
            main.command_run(args, self.config)
            main.command_run(args, self.config)
        send.assert_called_once()
        self.assertEqual(state.get_system_state(self.db, 'imap_status'), 'ok')

    def test_run_rejects_uidvalidity_change(self):
        state.save_mailbox_state(self.db, 'INBOX', '123')
        self.imap.select_mailbox.return_value = '999'
        with patch.object(main, 'acquire_run_lock', return_value=MagicMock()), \
                patch.object(main, 'fcntl', MagicMock()), \
                patch.object(main, 'make_imap', return_value=self.imap), \
                patch.object(main, 'backup_database', return_value=None), \
                self.assertRaisesRegex(RuntimeError, 'UIDVALIDITY'):
            main.command_run(SimpleNamespace(uid=None, dry_run=False), self.config)
        self.imap.fetch_raw.assert_not_called()

    def test_cleanup_failure_is_not_marked_deleted(self):
        self.config['imap']['delete_after_import'] = 'true'
        self.process()
        self.db.execute("UPDATE messages SET delete_after='2000-01-01T00:00:00+00:00'")
        self.db.commit()
        self.imap.delete_uid.return_value = False
        with patch.object(main, 'make_imap', return_value=self.imap), self.assertRaises(RuntimeError):
            main.command_cleanup(SimpleNamespace(dry_run=False), self.config)
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['imap_deleted'], 0)

    def test_cleanup_disabled_never_connects(self):
        with patch.object(main, 'make_imap') as make:
            main.command_cleanup(SimpleNamespace(dry_run=False), self.config)
        make.assert_not_called()

    def test_backup_is_readable_and_once_daily(self):
        self.process()
        directory = self.directory / 'backups'
        path = state.backup_database(self.db, directory)
        self.assertIsNone(state.backup_database(self.db, directory))
        with contextlib.closing(sqlite3.connect(path)) as backup:
            self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM messages').fetchone()[0], 1)


class ImapSafetyTests(IsolatedTest):
    def client(self):
        client = ImapClient('imap.example.invalid', 143, 'test', 'synthetic')
        client.imap = MagicMock()
        client.select_mailbox = MagicMock(return_value='123')
        return client

    def test_peek_and_seen_flags(self):
        client = self.client()
        client.imap.uid.side_effect = [('OK', [(b'1 (BODY[] {4}', b'mail')]),
                                       ('OK', [b'1 (FLAGS (\\Seen))'])]
        self.assertEqual(client.fetch_raw(1), b'mail')
        self.assertTrue(client.is_seen(1))
        self.assertEqual(client.imap.uid.call_args_list[0], call('fetch', '1', '(BODY.PEEK[])'))

    def test_starttls_verifies_certificate(self):
        with patch('app.imap_client.imaplib.IMAP4') as imap:
            ImapClient('imap.example.invalid', 143, 'test', 'synthetic').connect()
        context = imap.return_value.starttls.call_args.kwargs['ssl_context']
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_retry_three_attempts_and_waits(self):
        client = MagicMock()
        client.connect.side_effect = OSError('synthetic')
        with patch.object(main.time, 'sleep') as sleep, self.assertRaises(OSError):
            main.connect_imap_with_retry(client)
        self.assertEqual(client.connect.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(10), call(30)])
        self.assertEqual(client.close.call_count, 3)

    def test_uidvalidity_mismatch_never_deletes(self):
        client = self.client()
        with self.assertRaisesRegex(RuntimeError, 'UIDVALIDITY'):
            client.delete_uid('INBOX', '999', 1)
        client.imap.uid.assert_not_called()
        client.select_mailbox.assert_called_with('INBOX', readonly=True)

    def test_missing_uid_never_deletes(self):
        client = self.client()
        client.uid_exists = MagicMock(return_value=False)
        self.assertFalse(client.delete_uid('INBOX', '123', 1))
        client.imap.uid.assert_not_called()

    def test_uidplus_uses_targeted_expunge(self):
        client = self.client()
        client.imap.capabilities = (b'UIDPLUS',)
        client.uid_exists = MagicMock(side_effect=[True, False])
        client.imap.uid.return_value = ('OK', [])
        self.assertTrue(client.delete_uid('INBOX', '123', 1))
        self.assertIn(call('EXPUNGE', '1'), client.imap.uid.call_args_list)
        client.imap.expunge.assert_not_called()

    def test_non_uidplus_aborts_existing_deleted(self):
        client = self.client()
        client.imap.capabilities = ()
        client.uid_exists = MagicMock(return_value=True)
        client.imap.uid.return_value = ('OK', [b'2'])
        with self.assertRaises(RuntimeError):
            client.delete_uid('INBOX', '123', 1)
        client.imap.expunge.assert_not_called()
        self.assertEqual(client.imap.uid.call_count, 1)

    def test_non_uidplus_rechecks_and_rolls_back_unexpected_deleted(self):
        client = self.client()
        client.imap.capabilities = ()
        client.uid_exists = MagicMock(return_value=True)
        client.imap.uid.side_effect = [('OK', [b'']), ('OK', []), ('OK', [b'1 2']), ('OK', [])]
        with self.assertRaises(RuntimeError):
            client.delete_uid('INBOX', '123', 1)
        client.imap.expunge.assert_not_called()
        self.assertIn(call('store', '1', '-FLAGS.SILENT', r'(\Deleted)'),
                      client.imap.uid.call_args_list)


class PackagingTests(IsolatedTest):
    def test_catalog_keys_placeholders_and_all_messages_render(self):
        english = json.loads((ROOT / 'app/locales/en.json').read_text(encoding='utf-8'))
        for language in i18n.available_languages():
            catalog = json.loads((ROOT / f'app/locales/{language}.json').read_text(encoding='utf-8'))
            self.assertEqual(set(catalog), set(english))
            i18n.set_language(language)
            for key, value in catalog.items():
                if key.startswith('argparse.'):
                    continue
                placeholders = {name for _, name, _, _ in Formatter().parse(value) if name}
                self.assertEqual(placeholders, {name for _, name, _, _ in
                                               Formatter().parse(english[key]) if name}, key)
                i18n.t(key, **dict.fromkeys(placeholders, 'synthetic'))

    def test_unknown_language_falls_back_to_english(self):
        i18n.set_language('../../missing')
        self.assertEqual(i18n.t('cli.error', error='synthetic'), 'Error: synthetic')

    def test_fallback_mime_in_both_languages(self):
        for language in ('ja', 'en'):
            i18n.set_language(language)
            raw = mime_fallback.build_fallback_message(sample_mail(True), [{
                'name': '<synthetic>.bin', 'webViewLink': 'https://drive.example.invalid/a?x=1&y=2',
            }])
            mime_fallback.validate_fallback_message(raw)
            message = mime_fallback.parse_message(raw)
            self.assertEqual(list(message.iter_attachments()), [])
            self.assertIn('Synthetic body', message.get_body(('plain',)).get_content())
            html = message.get_body(('html',)).get_content()
            self.assertIn('&lt;synthetic&gt;', html)
            self.assertIn('&amp;', html)
            self.assertNotEqual(message['Message-ID'], '<synthetic@example.invalid>')

    def test_importing_token_helper_has_no_side_effects(self):
        with patch('google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file') as flow:
            importlib.import_module('make_token')
        flow.assert_not_called()

    def test_config_missing_and_blank_and_percent_password(self):
        with contextlib.chdir(self.directory):
            with self.assertRaises(configuration.ConfigError):
                configuration.load_config()
            path = self.directory / 'config.ini'
            path.write_text('[imap]\nhost =\n', encoding='utf-8')
            with self.assertRaisesRegex(configuration.ConfigError, 'host'):
                configuration.load_config()
            path.write_text('[imap]\nhost=imap.example.invalid\nuser=test\npassword=100%synthetic\n',
                            encoding='utf-8')
            self.assertEqual(configuration.load_config()['imap']['password'], '100%synthetic')
            with path.open('a', encoding='utf-8') as stream:
                stream.write('delete_delay_days=-1\n')
            with self.assertRaises(configuration.ConfigError):
                configuration.load_config()

    def test_config_error_does_not_expose_line(self):
        path = self.directory / 'config.ini'
        path.write_text('synthetic-secret-without-section', encoding='utf-8')
        with self.assertRaises(configuration.ConfigError) as error:
            configuration.read_config(path)
        self.assertNotIn('synthetic-secret', str(error.exception))

    def test_cli_missing_config_and_invalid_arguments(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8')
        for language in ('ja', 'en'):
            command = [sys.executable, '-m', 'app.main', '--lang', language]
            result = subprocess.run(command + ['--help'], cwd=self.directory, env=env,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0)
            result = subprocess.run(command + ['status'], cwd=self.directory, env=env,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 1)
            self.assertIn('config.ini', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            result = subprocess.run(command + ['init', '--latest', '0'], cwd=self.directory, env=env,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2)

    def test_cleanup_marker_only_after_success_and_retry_next_cycle(self):
        with patch.object(service, 'MARKER', self.directory / 'last_cleanup_date'), \
                patch.object(service.subprocess, 'run') as run:
            run.side_effect = [SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)]
            service.run_cycle()
            self.assertFalse(service.MARKER.exists())
            run.side_effect = [SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)]
            service.run_cycle()
            self.assertTrue(service.MARKER.exists())
            run.side_effect = [SimpleNamespace(returncode=0)]
            service.run_cycle()
            self.assertEqual(run.call_count, 5)

    @unittest.skipIf(main.fcntl is None, 'Real flock requires Linux; exercised by CI')
    def test_real_flock_excludes_independent_lock_handle(self):
        with contextlib.chdir(self.directory):
            lock = main.acquire_run_lock()
            self.assertIsNotNone(lock)
            try:
                self.assertIsNone(main.acquire_run_lock())
            finally:
                lock.close()
            lock = main.acquire_run_lock()
            self.assertIsNotNone(lock)
            lock.close()

    def test_gmail_raw_import_and_attachment_classifier(self):
        gmail = GmailClient('unused')
        gmail.service = MagicMock()
        gmail.service.users.return_value.messages.return_value.import_.return_value.execute.return_value = {'id': 'synthetic'}
        self.assertEqual(gmail.import_message(b'raw'), 'synthetic')
        arguments = gmail.service.users.return_value.messages.return_value.import_.call_args.kwargs
        self.assertEqual(arguments['body']['raw'], 'cmF3')
        self.assertEqual(arguments['internalDateSource'], 'dateHeader')
        for status, content, expected in [(400, b'Invalid attachment', True),
                                           (400, b'invalidArgument attachment', True),
                                           (400, b'Invalid header', False),
                                           (403, b'Invalid attachment', False)]:
            error = SimpleNamespace(resp=SimpleNamespace(status=status), content=content)
            self.assertEqual(gmail._is_invalid_attachment(error), expected)


if __name__ == '__main__':
    unittest.main()
