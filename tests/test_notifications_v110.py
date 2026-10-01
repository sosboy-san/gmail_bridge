"""Notification freshness, privacy and import independence with synthetic mail."""

import contextlib
import io
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from test_regressions import IsolatedTest, sample_mail, settings

from app import config as configuration
from app import main, state
from app import notification_service as notifications
from app.config import NotificationSettings
from app.gmail_client import InvalidAttachmentError
from app.notification_metadata import display_text, notification_metadata

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class NotificationTest(IsolatedTest):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': str(self.directory)})
        env.start()
        self.addCleanup(env.stop)
        self.db = state.connect(create=True)
        self.addCleanup(self.db.close)
        self.config = settings()
        self.config['notification']['ttl_minutes'] = '15'
        self.imap = MagicMock()
        self.imap.fetch_raw.return_value = sample_mail()
        self.imap.is_seen.return_value = False
        self.imap.get_summary.return_value = {'date': '', 'from': '', 'subject': ''}
        self.gmail = MagicMock()
        self.gmail.import_message.return_value = 'synthetic-gmail-id'

    def process(self, uid=1, origin='run'):
        return main.process_uid(self.imap, self.gmail, None, self.db, self.config,
                                'INBOX', '123', uid, import_origin=origin)

    def queue(self, uid=1, stamp=NOW, sender='sender@example.com', subject='Synthetic subject'):
        state.ensure_message(self.db, 'INBOX', '123', uid, import_origin='run')
        state.mark_gmail_imported_pending(self.db, 'INBOX', '123', uid, 'synthetic-id',
                                         sender=sender, subject=subject,
                                         imported_at=stamp.isoformat() if stamp else None)
        state.mark_imported(self.db, 'INBOX', '123', uid, 'synthetic-id')
        if stamp is None:
            self.db.execute('UPDATE messages SET notification_imported_at=NULL WHERE uid=?', (uid,))
            self.db.commit()
        state.ensure_notification(self.db, 'INBOX', '123', uid, 'ntfy')

    def status(self, uid=1):
        return self.db.execute('SELECT status FROM notifications WHERE uid=?', (uid,)).fetchone()[0]

    def send(self, at=NOW, loader=None, error=None):
        with patch.object(notifications, 'utc_now', return_value=at), \
                patch.object(notifications, 'make_ntfy_client') as factory:
            factory.return_value.send.side_effect = error
            result = notifications.send_pending_notifications(
                self.db, self.config, config_loader=loader or (lambda: self.config))
            return result, factory.return_value.send.call_args_list

    def test_normal_and_fallback_save_original_metadata_and_queue_once(self):
        with patch.object(main, 'utc_now_iso', return_value=NOW.isoformat()):
            self.assertEqual(self.process(), 'imported')
        message = state.get_message(self.db, 'INBOX', '123', 1)
        self.assertEqual(message['notification_sender'], 'sender@example.invalid')
        self.assertEqual(message['notification_subject'], 'Synthetic test')
        self.assertEqual(message['notification_preview'], 'Synthetic body')
        self.assertEqual(message['notification_imported_at'], NOW.isoformat())
        self.assertEqual(len(state.get_pending_notifications(self.db)), 1)
        self.assertEqual(self.process(), 'skipped')
        self.assertEqual(self.gmail.import_message.call_count, 1)
        self.imap.fetch_raw.return_value = sample_mail(attachment=True)
        self.gmail.import_message.side_effect = [InvalidAttachmentError(), 'fallback-id']
        drive = MagicMock()
        drive.upload_file.return_value = {'id': 'synthetic-drive-id', 'webViewLink': 'synthetic-link'}
        with patch.object(main, 'make_drive', return_value=drive), \
                patch.object(main, 'utc_now_iso', return_value=NOW.isoformat()):
            self.assertEqual(self.process(2), 'fallback')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 2)['notification_sender'],
                         'sender@example.invalid')
        self.assertEqual(len(state.get_pending_notifications(self.db)), 2)
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 2)['notification_preview'], 'Synthetic body')

    def test_api_time_and_metadata_are_immutable_through_finalization_retry(self):
        self.gmail.apply_source_label.side_effect = RuntimeError('synthetic label failure')
        with patch.object(main, 'utc_now_iso', return_value=NOW.isoformat()):
            self.assertEqual(self.process(), 'failed')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['status'], 'gmail_imported_pending')
        self.assertEqual(state.get_pending_notifications(self.db), [])
        self.gmail.apply_source_label.side_effect = None
        self.imap.fetch_raw.return_value = sample_mail().replace(b'Synthetic test', b'Changed subject')
        with patch.object(main, 'utc_now_iso', return_value=(NOW + timedelta(hours=1)).isoformat()):
            self.assertEqual(self.process(), 'imported')
        row = state.get_message(self.db, 'INBOX', '123', 1)
        self.assertEqual(row['notification_imported_at'], NOW.isoformat())
        self.assertEqual(row['notification_subject'], 'Synthetic test')
        self.assertEqual(row['notification_preview'], 'Synthetic body')
        self.assertEqual(self.gmail.import_message.call_count, 1)
        self.assertEqual(self.send(NOW + timedelta(hours=1))[1], [])
        self.assertEqual(self.status(), 'expired')

    def test_final_state_and_notification_registration_roll_back_together(self):
        original = main.queue_notification

        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('synthetic queue failure')

        with patch.object(main, 'queue_notification', side_effect=fail_after_insert):
            self.assertEqual(self.process(), 'failed')
        row = state.get_message(self.db, 'INBOX', '123', 1)
        self.assertEqual(row['status'], 'gmail_imported_pending')
        self.assertIsNone(row['delete_after'])
        self.assertEqual(state.get_pending_notifications(self.db), [])
        self.assertEqual(self.process(), 'imported')
        self.assertEqual(self.gmail.import_message.call_count, 1)
        self.assertEqual(len(state.get_pending_notifications(self.db)), 1)

    def test_transport_failure_does_not_repeat_gmail_or_fetch_for_retry(self):
        with patch.object(main, 'utc_now_iso', return_value=NOW.isoformat()):
            self.process()
        fetched = self.imap.fetch_raw.call_count
        self.assertEqual(self.send(error=OSError('synthetic'))[0], {'sent': 0, 'failed': 1})
        self.assertEqual(self.status(), 'pending')
        self.assertEqual(self.send(NOW + timedelta(minutes=14))[0], {'sent': 1, 'failed': 0})
        self.assertEqual(self.status(), 'sent')
        self.assertEqual(self.imap.fetch_raw.call_count, fetched)
        self.assertEqual(self.gmail.import_message.call_count, 1)

    def test_ttl_boundary_expires_before_filter_and_never_resurrects(self):
        self.queue(sender=None)
        self.config['notification']['sender_filter_mode'] = 'allowlist'
        (self.directory / 'notification_senders.ini').write_text('[allowlist]\n', encoding='utf-8')
        self.assertEqual(self.send(NOW + timedelta(minutes=15))[1], [])
        self.assertEqual(self.status(), 'expired')
        self.config['notification']['sender_filter_mode'] = 'off'
        self.config['notification']['ttl_minutes'] = '0'
        state.ensure_notification(self.db, 'INBOX', '123', 1, 'ntfy')
        state.mark_notification_failed(self.db, 'INBOX', '123', 1, 'ntfy', 'synthetic')
        state.mark_notification_sent(self.db, 'INBOX', '123', 1, 'ntfy')
        self.assertEqual(self.send()[1], [])
        self.assertEqual(self.status(), 'expired')

    def test_long_outage_expires_all_backlog_without_recovery_burst(self):
        for uid in range(1, 21):
            self.queue(uid, NOW + timedelta(seconds=uid))
        result, calls = self.send(NOW + timedelta(minutes=45))
        self.assertEqual(result, {'sent': 0, 'failed': 0})
        self.assertEqual(calls, [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notifications WHERE status='expired'").fetchone()[0], 20)

    def test_unknown_legacy_timestamp_expires_only_when_ttl_enabled(self):
        self.queue(stamp=None, sender=None, subject=None)
        self.config['notification']['ttl_minutes'] = '0'
        self.assertEqual(self.send(NOW + timedelta(days=365))[0]['sent'], 1)
        self.queue(2, stamp=None)
        self.config['notification']['ttl_minutes'] = '15'
        self.send()
        self.assertEqual(self.status(2), 'expired')

    def test_legacy_unlimited_is_logged_once_per_database(self):
        self.config.remove_option('notification', 'ttl_minutes')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.send()
            self.send()
        self.assertEqual(output.getvalue().count('[NOTIFICATION_CONFIG]'), 1)
        self.assertEqual(state.get_system_state(self.db, 'notification_legacy_ttl_logged'), '1')

    def test_latest_rules_can_suppress_pending_and_never_revive_it(self):
        self.queue()
        self.config['notification']['sender_filter_mode'] = 'combined'
        path = self.directory / 'notification_senders.ini'
        path.write_text('[allowlist]\naddresses=sender@example.com\n'
                        '[blocklist]\ndomains=example.com\n', encoding='utf-8')
        self.assertEqual(self.send()[1], [])
        self.assertEqual(self.status(), 'suppressed')
        path.write_text('[allowlist]\naddresses=sender@example.com\n', encoding='utf-8')
        state.ensure_notification(self.db, 'INBOX', '123', 1, 'ntfy')
        state.mark_notification_failed(self.db, 'INBOX', '123', 1, 'ntfy', 'synthetic')
        self.assertEqual(self.send()[1], [])
        self.assertEqual(self.status(), 'suppressed')

    def test_config_error_leaves_pending_and_import_state_unchanged(self):
        self.queue()
        self.config['notification']['sender_filter_mode'] = 'allowlist'
        with self.assertRaises(configuration.ConfigError):
            self.send()
        self.assertEqual(self.status(), 'pending')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['status'], 'imported')

    def test_reload_between_notifications_honors_new_filter(self):
        self.queue(1)
        self.queue(2)
        (self.directory / 'notification_senders.ini').write_text('[allowlist]\n', encoding='utf-8')
        changed = settings()
        changed['notification']['sender_filter_mode'] = 'allowlist'
        loader = MagicMock(side_effect=[self.config, self.config, changed])
        self.assertEqual(self.send(loader=loader)[0]['sent'], 1)
        self.assertEqual(self.status(1), 'sent')
        self.assertEqual(self.status(2), 'suppressed')

    def test_flags_fixed_positions_and_missing_values(self):
        self.queue(subject='日本語')
        for sender in (False, True):
            for subject in (False, True):
                for preview in (False, True):
                    self.config['notification'].update(include_sender=str(sender), include_subject=str(subject), include_preview=str(preview))
                    row = state.get_pending_notifications(self.db)[0]
                    options = configuration.validate_notifications(self.config)
                    self.assertEqual(notifications._title(row, options), 'sender@example.com' if sender else 'Gmail Bridge')
                    self.assertEqual(notifications._body(row, options), '日本語' if subject else 'You have one new email')
        self.queue(2, sender=None, subject=None)
        row = state.get_pending_notifications(self.db)[1]
        options = configuration.validate_notifications(self.config)
        self.assertEqual(notifications._title(row, options), 'Unknown sender')
        self.assertEqual(notifications._body(row, options), 'No subject')

    def test_details_retry_uses_saved_metadata_without_imap(self):
        self.imap.fetch_raw.return_value = sample_mail().replace(b'sender@example.invalid', b'Display Name <sender@example.invalid>')
        with patch.object(main, 'utc_now_iso', return_value=NOW.isoformat()):
            self.assertEqual(self.process(), 'imported')
        self.config['notification'].update(include_sender='true', include_subject='true', include_preview='true')
        self.imap.reset_mock()
        self.assertEqual(self.send(error=RuntimeError('synthetic'))[0]['failed'], 1)
        result, calls = self.send()
        self.assertEqual(result['sent'], 1)
        self.assertEqual(calls[0].kwargs, {'title': 'Display Name <sender@example.invalid>', 'message': 'Synthetic test\nSynthetic body'})
        self.imap.fetch_raw.assert_not_called()
        self.config['notification'].update(include_sender='false', include_subject='false')
        row = state.get_pending_notifications(self.db)
        self.assertEqual(row, [])
        saved = state.get_message(self.db, 'INBOX', '123', 1)
        options = configuration.validate_notifications(self.config)
        self.assertEqual(notifications._body(saved, options), 'You have one new email\nSynthetic body')

    def test_invalid_and_missing_sender_suppresses_in_any_active_mode(self):
        path = self.directory / 'notification_senders.ini'
        path.write_text('[allowlist]\naddresses=sender@example.com\n', encoding='utf-8')
        for uid, mode in enumerate(('allowlist', 'blocklist', 'combined'), 1):
            self.queue(uid, sender=None)
            self.config['notification']['sender_filter_mode'] = mode
            self.send()
            self.assertEqual(self.status(uid), 'suppressed')
        self.queue(4, sender=None)
        self.config['notification']['sender_filter_mode'] = 'off'
        self.assertEqual(self.send()[0]['sent'], 1)

    def test_init_import_and_interrupted_resume_never_generate_notifications(self):
        self.assertEqual(self.process(origin='init'), 'imported')
        self.assertEqual(state.get_pending_notifications(self.db), [])
        state.ensure_message(self.db, 'INBOX', '123', 2, import_origin='run')
        self.gmail.apply_source_label.side_effect = RuntimeError('synthetic')
        self.assertEqual(self.process(2, 'init'), 'failed')
        self.gmail.apply_source_label.side_effect = None
        self.assertEqual(self.process(2, 'run'), 'imported')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 2)['import_origin'], 'init')
        self.assertEqual(state.get_pending_notifications(self.db), [])

    def test_selected_but_unprocessed_init_uid_keeps_origin_after_interrupt(self):
        calls = 0

        def stop_on_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            return 'failed'

        with patch.object(main, 'process_uid', side_effect=stop_on_second), self.assertRaises(KeyboardInterrupt):
            main.import_uids(self.imap, self.gmail, None, self.db, self.config, 'INBOX', '123',
                             [1, 2, 3], import_origin='init')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 3)['import_origin'], 'init')
        self.assertEqual(self.process(3, 'run'), 'imported')
        self.assertEqual(state.get_pending_notifications(self.db), [])

    def test_large_import_dispatches_notifications_before_end(self):
        positions = []
        with patch.object(main, 'process_uid', return_value='imported') as process, \
                patch.object(main, 'send_pending_notifications', side_effect=lambda *a, **k: positions.append(process.call_count)):
            main.import_uids(self.imap, self.gmail, None, self.db, self.config, 'INBOX', '123', range(12))
        self.assertEqual(positions, [5, 10, 12])

    def test_elapsed_time_dispatches_before_five_messages(self):
        clock = [0]
        positions = []

        def process(*args, **kwargs):
            clock[0] += 31
            return 'imported'

        with patch.object(main.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(main, 'process_uid', side_effect=process) as processed, \
                patch.object(main, 'send_pending_notifications', side_effect=lambda *a, **k: positions.append(processed.call_count)):
            main.import_uids(self.imap, self.gmail, None, self.db, self.config, 'INBOX', '123', range(3))
        self.assertEqual(positions, [1, 2, 3])

    def test_sender_filter_uses_full_address_while_display_is_truncated(self):
        sender = 'x' * 64 + '@' + 'a' * 63 + '.' + 'b' * 63 + '.example.com'
        self.queue(sender=sender)
        self.config['notification'].update({'sender_filter_mode': 'allowlist', 'include_sender': 'true'})
        (self.directory / 'notification_senders.ini').write_text('[allowlist]\naddresses=' + sender + '\n', encoding='utf-8')
        result, calls = self.send()
        self.assertEqual(result['sent'], 1)
        line = calls[0].kwargs['title']
        self.assertEqual(len(line), 200)
        self.assertTrue(line.endswith('…'))

    def test_network_budget_and_failure_stop_while_classification_continues(self):
        for uid in range(1, 16):
            self.queue(uid)
        self.assertEqual(len(self.send()[1]), 10)
        self.queue(16, NOW - timedelta(hours=1))
        result, calls = self.send(error=OSError('synthetic'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.status(16), 'expired')

    def test_bulk_import_continues_without_repeated_transport_timeouts(self):
        with patch.object(main, 'process_uid', return_value='imported') as process, \
                patch.object(main.time, 'monotonic', return_value=10), \
                patch.object(main, 'send_pending_notifications', return_value={'sent': 0, 'failed': 1}) as send:
            main.import_uids(self.imap, self.gmail, None, self.db, self.config, 'INBOX', '123', range(100))
        self.assertEqual(process.call_count, 100)
        self.assertEqual(send.call_count, 1)

    def test_system_alerts_bypass_filter_display_and_ttl(self):
        (self.directory / 'notification_senders.ini').write_text('[allowlist]\n', encoding='utf-8')
        self.config['notification'].update({'sender_filter_mode': 'allowlist', 'ttl_minutes': '1',
                                            'include_sender': 'true', 'include_subject': 'true'})
        with patch.object(main, 'make_ntfy') as factory:
            self.assertTrue(main.send_system_notification(self.config, 'Synthetic outage', 'Gmail Bridge Alert'))
            factory.return_value.send.assert_called_once_with('Synthetic outage', title='Gmail Bridge Alert')

    def test_system_alerts_also_stop_on_latest_configuration_error(self):
        loader = MagicMock(side_effect=configuration.ConfigError('Synthetic invalid settings'))
        with patch.object(main, 'make_ntfy') as factory, self.assertRaises(configuration.ConfigError):
            main.send_system_notification(self.config, 'Synthetic outage', config_loader=loader)
        factory.assert_not_called()

    def test_configuration_failure_before_next_uid_preserves_completed_import(self):
        loader = MagicMock(side_effect=[self.config, configuration.ConfigError('Synthetic invalid settings')])
        with self.assertRaises(configuration.ConfigError):
            main.import_uids(self.imap, self.gmail, None, self.db, self.config,
                             'INBOX', '123', [1, 2], config_loader=loader)
        self.assertEqual(self.gmail.import_message.call_count, 1)
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['status'], 'imported')
        self.assertIsNone(state.get_message(self.db, 'INBOX', '123', 2))

    def test_connection_change_stops_before_using_old_client_with_new_settings(self):
        changed = settings()
        changed['gmail']['token_file'] = 'different-token.json'
        with patch.object(main, 'process_uid') as process, self.assertRaisesRegex(RuntimeError, 'CONFIG_RESTART_REQUIRED'):
            main.import_uids(self.imap, self.gmail, None, self.db, self.config, 'INBOX', '123', [1],
                             config_loader=lambda: changed)
        process.assert_not_called()

    def test_default_loader_reads_current_files_before_each_send(self):
        self.queue()
        path = self.directory / 'config.ini'
        with path.open('w', encoding='utf-8') as stream:
            self.config.write(stream)
        with patch.object(notifications, 'utc_now', return_value=NOW), \
                patch.object(notifications, 'make_ntfy_client') as factory:
            notifications.send_pending_notifications(self.db)
            factory.return_value.send.assert_called_once()

    def test_init_fallback_generates_no_normal_notification(self):
        self.imap.fetch_raw.return_value = sample_mail(attachment=True)
        self.gmail.import_message.side_effect = [InvalidAttachmentError(), 'fallback-id']
        drive = MagicMock()
        drive.upload_file.return_value = {'id': 'synthetic-drive-id', 'webViewLink': 'synthetic-link'}
        with patch.object(main, 'make_drive', return_value=drive):
            self.assertEqual(self.process(origin='init'), 'fallback')
        self.assertEqual(state.get_message(self.db, 'INBOX', '123', 1)['import_origin'], 'init')
        self.assertEqual(state.get_pending_notifications(self.db), [])


class MetadataAndRuleTests(IsolatedTest):
    def test_metadata_utf8_subject_address_only_and_control_truncation(self):
        message = EmailMessage()
        message['From'] = 'Synthetic display <sender@example.com>'
        message['Subject'] = '日本語の件名'
        message.set_content('Private body must never appear in notification metadata')
        sender, subject = notification_metadata(message.as_bytes())
        self.assertEqual(sender, 'sender@example.com')
        self.assertEqual(subject, '日本語の件名')
        value = display_text('a\r\nb\x00c\x7f\u202e' + 'x' * 300)
        self.assertTrue(value.startswith('a bc'))
        self.assertEqual(len(value), 200)
        self.assertTrue(value.endswith('…'))

    def test_from_missing_invalid_multiple_headers_and_multiple_addresses(self):
        for header in (b'', b'From: invalid\r\n',
                       b'From: a@example.com, b@example.com\r\n',
                       b'From: a@example.com\r\nFrom: b@example.com\r\n',
                       b'From: bad@@example.com\r\n'):
            with self.subTest(header=header):
                sender, subject = notification_metadata(header + b'Subject: Synthetic\r\n\r\nbody')
                self.assertIsNone(sender)
                self.assertEqual(subject, 'Synthetic')

    def test_all_modes_exact_matching_case_empty_lists_subdomains_and_block_priority(self):
        common = dict(enabled=True, include_sender=False, include_subject=False, ttl_minutes=15)
        rules = dict(allow_addresses=frozenset({'user@example.com'}),
                     allow_domains=frozenset({'partner.example.com'}),
                     block_addresses=frozenset({'newsletter@partner.example.com'}),
                     block_domains=frozenset({'example.com'}))
        cases = [
            ('off', None, True), ('allowlist', 'USER@EXAMPLE.COM', True),
            ('allowlist', 'user@mail.example.com', False),
            ('allowlist', 'other@partner.example.com', True),
            ('allowlist', 'other@sub.partner.example.com', False),
            ('blocklist', 'user@example.com', False),
            ('blocklist', 'user@mail.example.com', True),
            ('combined', 'user@example.com', False),
            ('combined', 'other@partner.example.com', True),
            ('combined', 'newsletter@partner.example.com', False),
        ]
        for mode, sender, expected in cases:
            with self.subTest(mode=mode, sender=sender):
                cfg = NotificationSettings(sender_filter_mode=mode, **common, **rules)
                self.assertEqual(notifications.sender_allowed(sender, cfg), expected)
        for mode, expected in (('allowlist', False), ('combined', False), ('blocklist', True)):
            cfg = NotificationSettings(sender_filter_mode=mode, **common)
            self.assertEqual(notifications.sender_allowed('user@example.com', cfg), expected)
