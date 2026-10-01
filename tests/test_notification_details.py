import json
import os
import sqlite3
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from test_regressions import IsolatedTest

from app import state
from app.notification_metadata import notification_details
from app.ntfy_client import NtfyClient


class DetailTests(IsolatedTest):
    def test_plain_preferred_and_named_sender(self):
        mail = EmailMessage()
        mail['From'] = '山田太郎 <a@example.com>'
        mail['Subject'] = '件名'
        mail.set_content('本文\n続き')
        mail.add_alternative('<p>HTML</p>', subtype='html')
        mail.add_attachment('秘密の添付', filename='secret.txt')
        self.assertEqual(notification_details(mail.as_bytes()),
                         ('a@example.com', '件名', '山田太郎', '本文 続き'))

    def test_html_only_and_truncation(self):
        mail = EmailMessage()
        mail.set_content('<style>secret</style><script>secret</script><p>A&amp;B</p><p>C</p>', subtype='html')
        self.assertEqual(notification_details(mail.as_bytes())[3], 'A&B C')
        mail.set_content('長' * 300)
        self.assertEqual(len(notification_details(mail.as_bytes())[3]), 200)

    def test_json_transport(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch('urllib.request.urlopen', return_value=response) as send:
            NtfyClient('https://example.invalid/prefix', 'topic', token='synthetic').send(
                '件名\n本文', title='山田太郎', click_url='https://example.invalid/mail')
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.invalid/prefix/')
        self.assertEqual(json.loads(request.data), {'topic': 'topic', 'title': '山田太郎',
                         'message': '件名\n本文', 'click': 'https://example.invalid/mail'})
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic')
        self.assertIsNone(request.get_header('Title'))

    def make_rc1(self):
        path = self.directory / 'data/state.db'
        path.parent.mkdir()
        db = sqlite3.connect(path)
        state._create_legacy_schema(db)
        state._add_notification_columns(db)
        db.execute('PRAGMA user_version=1')
        db.row_factory = sqlite3.Row
        state.ensure_message(db, 'INBOX', '123', 1, import_origin='run')
        db.execute("UPDATE messages SET gmail_message_id='id', notification_sender='a@example.com', notification_imported_at='2026-01-01T00:00:00+00:00'")
        db.commit()
        state.mark_imported(db, 'INBOX', '123', 1, 'id')
        state.ensure_notification(db, 'INBOX', '123', 1, 'ntfy')
        state.mark_notification_failed(db, 'INBOX', '123', 1, 'ntfy', 'failure')
        before = dict(db.execute('SELECT * FROM notifications').fetchone())
        db.close()
        return path, before

    def test_rc1_migration_preserves_notification(self):
        with patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': str(self.directory)}):
            _, before = self.make_rc1()
            db = state.connect()
            self.addCleanup(db.close)
            self.assertEqual(dict(db.execute('SELECT * FROM notifications').fetchone()), before)
            row = state.get_message(db, 'INBOX', '123', 1)
            self.assertIsNone(row['notification_preview'])
            self.assertEqual(row['notification_imported_at'], before['notification_imported_at'])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(len(list(self.directory.glob('backups/db/migrations/*.db'))), 1)

    def test_rc1_migration_rollback(self):
        with patch.dict(os.environ, {'BRIDGE_CONFIG_DIR': str(self.directory)}):
            path, before = self.make_rc1()
            original = state._add_notification_detail_columns
            def fail(db):
                original(db)
                raise RuntimeError('synthetic failure')
            with patch.object(state, '_add_notification_detail_columns', side_effect=fail):
                with self.assertRaises(state.DatabaseError):
                    state.connect()
            db = sqlite3.connect(path)
            self.addCleanup(db.close)
            db.row_factory = sqlite3.Row
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(dict(db.execute('SELECT * FROM notifications').fetchone()), before)
            self.assertNotIn('notification_preview', state._schema_signature(db, 'messages'))
