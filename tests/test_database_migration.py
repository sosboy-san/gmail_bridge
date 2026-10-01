"""Migration safety using the schema copied from the published v1.0.0 tag."""

import configparser
import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import locking, main, state

# Frozen SQL from v1.0.0: independent of the current schema builder.
LEGACY_SCHEMA = """
        CREATE TABLE IF NOT EXISTS messages (
            mailbox TEXT NOT NULL,
            uidvalidity TEXT NOT NULL,
            uid INTEGER NOT NULL,

            status TEXT NOT NULL DEFAULT 'pending',

            gmail_message_id TEXT,
            original_message_id TEXT,

            last_error TEXT,

            imported_at TEXT,
            completed_at TEXT,

            delete_after TEXT,
            imap_deleted INTEGER NOT NULL DEFAULT 0,
            imap_deleted_at TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            PRIMARY KEY (
                mailbox,
                uidvalidity,
                uid
            )
        )
    ;

        CREATE TABLE IF NOT EXISTS drive_files (
            mailbox TEXT NOT NULL,
            uidvalidity TEXT NOT NULL,
            uid INTEGER NOT NULL,

            attachment_index INTEGER NOT NULL,

            filename TEXT NOT NULL,
            content_type TEXT,
            sha256 TEXT NOT NULL,

            drive_file_id TEXT,
            drive_link TEXT,

            uploaded_at TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            PRIMARY KEY (
                mailbox,
                uidvalidity,
                uid,
                attachment_index
            )
        )
    ;

        CREATE TABLE IF NOT EXISTS mailbox_state (
            mailbox TEXT PRIMARY KEY,
            uidvalidity TEXT NOT NULL,
            initialized_at TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS notifications (
            mailbox TEXT NOT NULL,
            uidvalidity TEXT NOT NULL,
            uid INTEGER NOT NULL,

            provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',

            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sent_at TEXT,

            PRIMARY KEY (
                mailbox,
                uidvalidity,
                uid,
                provider
            )
        )
    ;

        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    
"""


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict('os.environ', {'BRIDGE_CONFIG_DIR': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path = self.root / 'data/state.db'

    def legacy(self):
        self.path.parent.mkdir()
        db = sqlite3.connect(self.path)
        db.executescript(LEGACY_SCHEMA)
        db.execute("INSERT INTO mailbox_state VALUES ('INBOX', '123', '2024-01-01T00:00:00+00:00')")
        for uid, imported, created, status in (
            (1, '2024-01-02T09:00:00+09:00', '2024-01-03T00:00:00+00:00', 'pending'),
            (2, None, '2024-01-04T00:00:00+00:00', 'sent'),
            (3, 'invalid', 'invalid', 'pending'),
            (4, 'invalid', '2024-01-05T00:00:00+00:00', 'pending'),
        ):
            db.execute("""INSERT INTO messages
                (mailbox, uidvalidity, uid, status, gmail_message_id, imported_at,
                 imap_deleted, delete_after, created_at, updated_at)
                VALUES ('INBOX', '123', ?, 'imported', 'synthetic-id', ?, 1,
                        '2024-02-01T00:00:00+00:00', ?, ?)""", (uid, imported, created, created))
            db.execute("""INSERT INTO notifications VALUES
                ('INBOX', '123', ?, 'ntfy', ?, 3, 'synthetic-error', ?, ?, NULL)""",
                       (uid, status, created, created))
        db.execute("INSERT INTO system_state VALUES ('imap_status', 'ok', '2024-01-01T00:00:00+00:00')")
        db.execute("""INSERT INTO drive_files VALUES
            ('INBOX', '123', 1, 0, 'synthetic.bin', 'application/octet-stream',
             'synthetic-hash', 'synthetic-drive-id', 'synthetic-link', NULL,
             '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')""")
        db.commit()
        db.close()

    def snapshot(self, path):
        with sqlite3.connect(path) as db:
            return {name: (list(db.execute(f'PRAGMA table_info({name})')),
                           list(db.execute(f'SELECT * FROM {name}')))
                    for name in ('messages', 'notifications', 'drive_files', 'mailbox_state', 'system_state')}

    def backups(self):
        return list((self.root / 'backups/db/migrations').glob('*.db'))

    def test_missing_database_only_explicit_init_can_create(self):
        with self.assertRaises(state.DatabaseMissing):
            state.connect()
        self.assertFalse(self.path.exists())
        with state.connect(create=True) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], state.SCHEMA_VERSION)
            with self.assertRaises(state.DatabaseUninitialized):
                state.require_initialized(db, 'INBOX')
            state.save_mailbox_state(db, 'INBOX', '123')
            state.require_initialized(db, 'INBOX')
        self.assertEqual(self.backups(), [])

    def test_migration_preserves_every_legacy_column_and_backup(self):
        self.legacy()
        before = self.snapshot(self.path)
        with state.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], state.SCHEMA_VERSION)
            stamps = [r[0] for r in db.execute('SELECT notification_imported_at FROM notifications ORDER BY uid')]
            self.assertEqual(stamps, ['2024-01-02T00:00:00+00:00',
                                     '2024-01-04T00:00:00+00:00', None,
                                     '2024-01-05T00:00:00+00:00'])
            self.assertTrue(all(r[0] is None for r in db.execute('SELECT notification_sender FROM messages')))
            for table, (columns, rows) in before.items():
                names = ', '.join(col[1] for col in columns)
                self.assertEqual([tuple(r) for r in db.execute(f'SELECT {names} FROM {table}')], rows)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.snapshot(backups[0]), before)
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0], 0)
        with state.connect() as db:
            state.set_system_state(db, 'imap_status', 'offline')
        self.assertEqual(len(self.backups()), 1)
        with state.connect() as db:
            self.assertEqual(db.execute('SELECT notification_imported_at FROM notifications WHERE uid=1').fetchone()[0], stamps[0])

    def test_partial_migration_failure_rolls_back_schema_and_rows(self):
        self.legacy()
        before = self.snapshot(self.path)

        def fail(db):
            db.execute('ALTER TABLE messages ADD COLUMN synthetic_partial TEXT')
            db.execute("UPDATE messages SET status='synthetic' WHERE uid=1")
            raise sqlite3.OperationalError('synthetic failure')

        with patch.object(state, '_add_notification_columns', side_effect=fail):
            with self.assertRaisesRegex(state.DatabaseError, 'DB_MIGRATION_ERROR'):
                state.connect()
        self.assertEqual(self.snapshot(self.path), before)
        self.assertEqual(len(self.backups()), 1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
        with state.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], state.SCHEMA_VERSION)
        self.assertEqual(len(self.backups()), 2)

    def test_backup_failure_does_not_start_migration(self):
        self.legacy()
        before = self.snapshot(self.path)
        with patch.object(state, '_migration_backup', side_effect=OSError('synthetic failure')):
            with self.assertRaises(state.DatabaseError):
                state.connect()
        self.assertEqual(self.snapshot(self.path), before)

    def test_empty_corrupt_unknown_and_future_database_are_never_initialized(self):
        self.path.parent.mkdir()
        for content in (b'', b'synthetic corrupt database'):
            self.path.write_bytes(content)
            with self.assertRaises(state.DatabaseError):
                state.connect(create=True)
            self.assertEqual(self.path.read_bytes(), content)
        self.path.unlink()
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE unknown (value TEXT)')
        before = self.path.read_bytes()
        with self.assertRaises(state.DatabaseError):
            state.connect(create=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        with state.connect(create=True) as db:
            db.execute('PRAGMA user_version=999')
        before = self.path.read_bytes()
        with self.assertRaises(state.DatabaseError):
            state.connect(create=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    def test_run_checks_database_before_imap_and_releases_lock(self):
        config = configparser.ConfigParser()
        config.read_dict({'imap': {'mailbox': 'INBOX'}})
        with patch.object(main, 'make_imap') as imap:
            with self.assertRaises(state.DatabaseMissing):
                main.command_run(SimpleNamespace(), config)
            imap.assert_not_called()
        self.assertFalse(self.path.exists())
        with state.connect(create=True):
            pass
        with patch.object(main, 'make_imap') as imap:
            with self.assertRaises(state.DatabaseUninitialized):
                main.command_run(SimpleNamespace(), config)
            imap.assert_not_called()
        with state.connect() as db:
            state.save_mailbox_state(db, 'INBOX', '123')

    def test_v01_processed_messages_are_preserved_and_migrated(self):
        self.path.parent.mkdir()
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE processed_messages
                (mailbox TEXT, uidvalidity TEXT, uid INTEGER, gmail_message_id TEXT, imported_at TEXT)""")
            db.execute("INSERT INTO processed_messages VALUES ('INBOX', '123', 9, 'synthetic-id', '2024-01-01T00:00:00+00:00')")
        with state.connect() as db:
            self.assertEqual(state.get_message(db, 'INBOX', '123', 9)['gmail_message_id'], 'synthetic-id')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM processed_messages').fetchone()[0], 1)
            self.assertIsNone(state.get_message(db, 'INBOX', '123', 9)['delete_after'])
            with self.assertRaises(state.DatabaseUninitialized):
                state.require_initialized(db, 'INBOX')

    def test_cleanup_refuses_uninitialized_database_before_imap(self):
        with state.connect(create=True):
            pass
        config = configparser.ConfigParser()
        config.read_dict({'imap': {'mailbox': 'INBOX', 'delete_after_import': 'true'}})
        with patch.object(main, 'make_imap') as imap:
            with self.assertRaises(state.DatabaseUninitialized):
                main.command_cleanup(SimpleNamespace(dry_run=False), config)
            imap.assert_not_called()

    def test_online_backup_includes_committed_wal_state(self):
        self.legacy()
        writer = sqlite3.connect(self.path)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE system_state SET value='offline'")
            writer.commit()
            with state.connect() as db:
                self.assertEqual(state.get_system_state(db, 'imap_status'), 'offline')
            with sqlite3.connect(self.backups()[0]) as backup:
                self.assertEqual(backup.execute('SELECT value FROM system_state').fetchone()[0], 'offline')
                self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            writer.close()

    @unittest.skipIf(locking.fcntl is None, 'Linux flock required')
    def test_commands_cannot_migrate_while_common_lock_is_held(self):
        self.legacy()
        before = self.snapshot(self.path)
        config = configparser.ConfigParser()
        config.read_dict({'imap': {'mailbox': 'INBOX', 'delete_after_import': 'true'}})
        stream = locking.acquire_lock()
        self.assertIsNotNone(stream)
        try:
            with patch.object(main, 'make_imap') as imap:
                for command in (main.command_init, main.command_cleanup, main.command_status):
                    with self.subTest(command=command.__name__), self.assertRaises(RuntimeError):
                        command(SimpleNamespace(), config)
                with contextlib.redirect_stdout(io.StringIO()):
                    main.command_run(SimpleNamespace(), config)
                imap.assert_not_called()
        finally:
            stream.close()
        self.assertEqual(self.snapshot(self.path), before)
        self.assertEqual(self.backups(), [])
