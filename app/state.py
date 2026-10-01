import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.i18n import t
from app.paths import runtime_path

DB_PATH = Path("data/state.db")


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat()


SCHEMA_VERSION = 2  # Independent of the application release version.


class DatabaseError(RuntimeError):
    """An existing database is unsafe to use; never replace or initialize it."""


class DatabaseMissing(RuntimeError):
    """No database exists. Only an explicit init may create one."""


class DatabaseUninitialized(RuntimeError):
    """The database is valid, but the selected mailbox has not completed init."""


def require_initialized(conn, mailbox):
    if get_mailbox_state(conn, mailbox) is None:
        raise DatabaseUninitialized('[WAITING_FOR_INIT] Mailbox has not completed initialization.')


def _create_legacy_schema(conn):
    # -------------------------------------------------
    # v0.2 メインメッセージテーブル
    # -------------------------------------------------
    conn.execute("""
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
    """)

    # -------------------------------------------------
    # Driveへ退避した添付ファイル
    #
    # 1メールに複数添付があっても
    # 1添付 = 1レコードとして管理する
    # -------------------------------------------------
    conn.execute("""
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
    """)

    # -------------------------------------------------
    # mailbox状態
    # -------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mailbox_state (
            mailbox TEXT PRIMARY KEY,
            uidvalidity TEXT NOT NULL,
            initialized_at TEXT NOT NULL
        )
    """)

    # -------------------------------------------------
    # 通知状態
    #
    # メール転送処理とは独立して管理する。
    # 通知失敗がGmail importやIMAP削除に
    # 影響しないようにする。
    # -------------------------------------------------
    conn.execute("""
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
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)



def _schema_signature(conn, table):
    return {row[1]: (row[2].upper(), row[3], row[4], row[5])
            for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _expected_schema(version):
    reference = sqlite3.connect(':memory:')
    try:
        _create_legacy_schema(reference)
        if version >= 1:
            _add_notification_columns(reference)
        if version >= 2:
            _add_notification_detail_columns(reference)
        return {table: _schema_signature(reference, table) for table in
                ('messages', 'drive_files', 'mailbox_state', 'notifications', 'system_state')}
    finally:
        reference.close()


def _validate_schema(conn, version):
    expected = _expected_schema(version)
    actual = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )}
    if actual - (set(expected) | {'processed_messages'}):
        raise DatabaseError('[DB_ERROR] Unrecognized database tables.')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger', 'view') LIMIT 1").fetchone():
        raise DatabaseError('[DB_ERROR] Unrecognized database triggers or views.')
    if 'processed_messages' in actual:
        required = {'mailbox', 'uidvalidity', 'uid', 'gmail_message_id', 'imported_at'}
        if not required.issubset(_schema_signature(conn, 'processed_messages')):
            raise DatabaseError('[DB_ERROR] Unrecognized legacy database schema.')
    for table, signature in expected.items():
        if version == 0 and 'processed_messages' in actual and table not in actual:
            continue
        if _schema_signature(conn, table) != signature:
            raise DatabaseError('[DB_ERROR] Unrecognized database schema.')


def _add_notification_columns(conn):
    conn.execute('ALTER TABLE messages ADD COLUMN notification_sender TEXT')
    conn.execute('ALTER TABLE messages ADD COLUMN notification_subject TEXT')
    conn.execute('ALTER TABLE messages ADD COLUMN notification_imported_at TEXT')
    conn.execute("ALTER TABLE messages ADD COLUMN import_origin TEXT NOT NULL DEFAULT 'unknown'")
    conn.execute('ALTER TABLE notifications ADD COLUMN notification_imported_at TEXT')
    # Preserve historical timestamps. Never substitute migration time.
    conn.create_function('_historical_timestamp', 1, _historical_timestamp)
    try:
        conn.execute('UPDATE messages SET notification_imported_at = _historical_timestamp(imported_at)')
        conn.execute("""
            UPDATE notifications SET notification_imported_at = COALESCE(
                (SELECT messages.notification_imported_at FROM messages
                 WHERE messages.mailbox = notifications.mailbox
                   AND messages.uidvalidity = notifications.uidvalidity
                   AND messages.uid = notifications.uid), _historical_timestamp(created_at))
        """)
    finally:
        conn.create_function('_historical_timestamp', 1, None)


def _add_notification_detail_columns(conn):
    conn.execute('ALTER TABLE messages ADD COLUMN notification_sender_name TEXT')
    conn.execute('ALTER TABLE messages ADD COLUMN notification_preview TEXT')


def _historical_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def _migration_backup(conn):
    directory = runtime_path('backups/db/migrations')
    directory.mkdir(parents=True, exist_ok=True)
    name = f"state_before_schema_{SCHEMA_VERSION}_{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}.db"
    destination = directory / name
    temporary = destination.with_suffix('.tmp')
    try:
        backup = sqlite3.connect(temporary)
        try:
            conn.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise DatabaseError('[DB_MIGRATION_ERROR] Backup integrity check failed.')
        finally:
            backup.close()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def connect(*, create=False):
    """Open validated state; command callers hold the common Bridge lock.

    create=True is reserved for explicit init (and isolated test setup).
    Existing files, including empty files, are never treated as new databases.
    """
    db_path = runtime_path(DB_PATH)
    exists = db_path.exists()
    if not exists and not create:
        raise DatabaseMissing('[WAITING_FOR_INIT] Database does not exist; run init explicitly.')
    if exists and (not db_path.is_file() or db_path.stat().st_size == 0):
        raise DatabaseError('[DB_ERROR] Existing database is empty or is not a regular file.')
    if not exists:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        uri = db_path.resolve().as_uri() + ('?mode=rw' if exists else '?mode=rwc')
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise DatabaseError('[DB_ERROR] Database integrity check failed.')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise DatabaseError('[DB_ERROR] Unsupported database schema version.')
        if not exists:
            conn.execute('BEGIN IMMEDIATE')
            _create_legacy_schema(conn)
            _add_notification_columns(conn)
            _add_notification_detail_columns(conn)
            conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            conn.commit()
        elif version < SCHEMA_VERSION:
            _validate_schema(conn, version)
            try:
                _migration_backup(conn)
                conn.execute('BEGIN IMMEDIATE')
                if version == 0:
                    _create_legacy_schema(conn)
                    migrate_v01(conn, commit=False)
                    _add_notification_columns(conn)
                _add_notification_detail_columns(conn)
                _validate_schema(conn, SCHEMA_VERSION)
                conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
                conn.commit()
            except Exception:
                conn.rollback()
                raise DatabaseError('[DB_MIGRATION_ERROR] Backup or migration failed; original schema and state retained.') from None
        else:
            _validate_schema(conn, SCHEMA_VERSION)
        return conn
    except (sqlite3.Error, OSError):
        if conn is not None:
            conn.close()
        raise DatabaseError('[DB_ERROR] Database could not be opened, validated or backed up.') from None
    except BaseException:
        if conn is not None:
            conn.close()
        raise


def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def migrate_v01(conn, *, commit=True):
    """
    v0.1 processed_messages -> v0.2 messages

    Gmail Message IDあり:
        imported

    Gmail Message IDなし:
        ignored

    INSERT済みのUIDは触らないため、
    connect()のたびに実行されても安全。
    """

    if not table_exists(
        conn,
        "processed_messages"
    ):
        return

    rows = conn.execute("""
        SELECT
            mailbox,
            uidvalidity,
            uid,
            gmail_message_id,
            imported_at
        FROM processed_messages
    """).fetchall()

    if not rows:
        return

    migrated = 0

    for row in rows:

        exists = conn.execute(
            """
            SELECT 1
            FROM messages
            WHERE mailbox = ?
              AND uidvalidity = ?
              AND uid = ?
            """,
            (
                row["mailbox"],
                row["uidvalidity"],
                row["uid"],
            ),
        ).fetchone()

        if exists:
            continue

        now = utc_now_iso()

        if row["gmail_message_id"]:
            status = "imported"
            imported_at = row["imported_at"]
            completed_at = row["imported_at"]

        else:
            status = "ignored"
            imported_at = None
            completed_at = row["imported_at"]

        # v0.1メールは移行しただけでは
        # 自動削除対象にしない
        delete_after = None

        conn.execute(
            """
            INSERT INTO messages (
                mailbox,
                uidvalidity,
                uid,
                status,
                gmail_message_id,
                imported_at,
                completed_at,
                delete_after,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["mailbox"],
                row["uidvalidity"],
                row["uid"],
                status,
                row["gmail_message_id"],
                imported_at,
                completed_at,
                delete_after,
                now,
                now,
            ),
        )

        migrated += 1

    if commit:
        conn.commit()

    if migrated and commit:
        print(
            t('state.migrate_v01.1', v0=f'{migrated}')
        )


# =====================================================
# Message state
# =====================================================

def get_message(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    return conn.execute(
        """
        SELECT *
        FROM messages
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            mailbox,
            uidvalidity,
            uid,
        ),
    ).fetchone()


def ensure_message(
    conn,
    mailbox,
    uidvalidity,
    uid,
    *, import_origin=None, commit=True,
):
    if import_origin not in (None, 'unknown', 'run', 'init'):
        raise ValueError('Invalid import origin.')
    now = utc_now_iso()

    conn.execute(
        """
        INSERT OR IGNORE INTO messages (
            mailbox,
            uidvalidity,
            uid,
            status,
            created_at,
            updated_at,
            import_origin
        )
        VALUES (?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            mailbox,
            uidvalidity,
            uid,
            now,
            now,
            import_origin or "unknown",
        ),
    )

    if import_origin is not None:
        if import_origin == 'init':
            conn.execute("""UPDATE messages SET import_origin = 'init'
                WHERE mailbox = ? AND uidvalidity = ? AND uid = ?
                  AND status NOT IN ('imported', 'drive_fallback', 'ignored')""",
                         (mailbox, uidvalidity, uid))
        else:
            conn.execute("""UPDATE messages SET import_origin = ?
                WHERE mailbox = ? AND uidvalidity = ? AND uid = ?
                  AND import_origin = 'unknown' AND notification_imported_at IS NULL""",
                         (import_origin, mailbox, uidvalidity, uid))
    if commit:
        conn.commit()


def is_processed(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    row = get_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    if not row:
        return False

    return row["status"] in (
        "imported",
        "drive_fallback",
        "ignored",
    )


def mark_imported(
    conn,
    mailbox,
    uidvalidity,
    uid,
    gmail_message_id,
    original_message_id=None,
    delete_delay_days=7,
    *, commit=True,
):
    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
        commit=False,
    )

    now = utc_now()
    now_iso = now.isoformat()

    delete_after = (
        now
        + timedelta(
            days=delete_delay_days
        )
    ).isoformat()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'imported',
            gmail_message_id = ?,
            original_message_id = ?,
            imported_at = ?,
            completed_at = ?,
            delete_after = ?,
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            gmail_message_id,
            original_message_id,
            now_iso,
            now_iso,
            delete_after,
            now_iso,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    if commit:
        conn.commit()


def mark_drive_uploading(
    conn,
    mailbox,
    uidvalidity,
    uid,
    original_message_id=None,
):
    """
    Gmailが添付を拒否し、
    Drive fallbackへ入ったことを記録。
    """

    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'drive_uploading',
            original_message_id =
                COALESCE(
                    ?,
                    original_message_id
                ),
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            original_message_id,
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()


def mark_drive_uploaded(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    """
    全添付のDriveアップロードが
    完了した状態。
    """

    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'drive_uploaded',
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()

def mark_gmail_imported_pending(
    conn,
    mailbox,
    uidvalidity,
    uid,
    gmail_message_id,
    original_message_id=None,
    *, sender=None, subject=None, sender_name=None, preview=None, imported_at=None,
):
    """
    通常メールのGmail import自体は成功したが、
    ラベル付与などの最終処理がまだの状態。

    Gmail IDを即座に保存することで、
    import直後にプロセスが停止しても
    再importを防ぐ。
    """

    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = imported_at or utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            notification_sender = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_sender END,
            notification_sender_name = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_sender_name END,
            notification_preview = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_preview END,
            notification_subject = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_subject END,
            notification_imported_at = COALESCE(notification_imported_at, ?),
            status = 'gmail_imported_pending',
            gmail_message_id = ?,
            original_message_id =
                COALESCE(
                    ?,
                    original_message_id
                ),
            imported_at =
                COALESCE(
                    imported_at,
                    ?
                ),
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            sender,
            sender_name,
            preview,
            subject,
            now,
            gmail_message_id,
            original_message_id,
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()

def mark_fallback_gmail_imported_pending(
    conn,
    mailbox,
    uidvalidity,
    uid,
    gmail_message_id,
    *, sender=None, subject=None, sender_name=None, preview=None, imported_at=None,
):
    """
    Drive fallback版メールのGmail importは
    成功したが、ラベル付与などがまだの状態。
    """

    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = imported_at or utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            notification_sender = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_sender END,
            notification_sender_name = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_sender_name END,
            notification_preview = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_preview END,
            notification_subject = CASE WHEN notification_imported_at IS NULL THEN ? ELSE notification_subject END,
            notification_imported_at = COALESCE(notification_imported_at, ?),
            status = 'fallback_gmail_imported_pending',
            gmail_message_id = ?,
            imported_at =
                COALESCE(
                    imported_at,
                    ?
                ),
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            sender,
            sender_name,
            preview,
            subject,
            now,
            gmail_message_id,
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()

def mark_drive_fallback(
    conn,
    mailbox,
    uidvalidity,
    uid,
    gmail_message_id,
    delete_delay_days=7,
    *, commit=True,
):
    """
    Driveへの添付保存と、
    Gmail軽量版importの両方が成功。
    """

    row = get_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    if not row:
        raise RuntimeError(
            t('state.mark_drive_fallback.1')
        )

    drive_files = get_drive_files(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    if not drive_files:
        raise RuntimeError(
            t('state.mark_drive_fallback.2')
        )

    for drive_file in drive_files:
        if not drive_file["drive_file_id"]:
            raise RuntimeError(
                t('state.mark_drive_fallback.3')
            )

        if not drive_file["drive_link"]:
            raise RuntimeError(
                t('state.mark_drive_fallback.4')
            )

    now = utc_now()
    now_iso = now.isoformat()

    delete_after = (
        now
        + timedelta(
            days=delete_delay_days
        )
    ).isoformat()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'drive_fallback',
            gmail_message_id = ?,
            imported_at = ?,
            completed_at = ?,
            delete_after = ?,
            last_error = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            gmail_message_id,
            now_iso,
            now_iso,
            delete_after,
            now_iso,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    if commit:
        conn.commit()


def mark_retry(
    conn,
    mailbox,
    uidvalidity,
    uid,
    error,
):
    """
    一時エラー。

    Drive情報は消さない。
    途中までアップロード済みなら、
    次回そこから再開できる。
    """

    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'retry',
            last_error = ?,
            delete_after = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            str(error),
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()


def mark_ignored(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    ensure_message(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            status = 'ignored',
            completed_at = ?,
            delete_after = NULL,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()


# =====================================================
# Drive attachment state
# =====================================================

def ensure_drive_file(
    conn,
    mailbox,
    uidvalidity,
    uid,
    attachment_index,
    filename,
    content_type,
    sha256,
):
    """
    添付1個をDBへ登録。

    同じUID + attachment_indexが
    すでに存在する場合は上書きしない。
    """

    now = utc_now_iso()

    conn.execute(
        """
        INSERT OR IGNORE INTO drive_files (
            mailbox,
            uidvalidity,
            uid,
            attachment_index,
            filename,
            content_type,
            sha256,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mailbox,
            uidvalidity,
            uid,
            attachment_index,
            filename,
            content_type,
            sha256,
            now,
            now,
        ),
    )

    conn.commit()


def get_drive_file(
    conn,
    mailbox,
    uidvalidity,
    uid,
    attachment_index,
):
    return conn.execute(
        """
        SELECT *
        FROM drive_files
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
          AND attachment_index = ?
        """,
        (
            mailbox,
            uidvalidity,
            uid,
            attachment_index,
        ),
    ).fetchone()


def get_drive_files(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    return conn.execute(
        """
        SELECT *
        FROM drive_files
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        ORDER BY attachment_index
        """,
        (
            mailbox,
            uidvalidity,
            uid,
        ),
    ).fetchall()


def mark_drive_file_uploaded(
    conn,
    mailbox,
    uidvalidity,
    uid,
    attachment_index,
    drive_file_id,
    drive_link,
):
    """
    添付1個のDrive保存が成功した直後に
    呼び出す。

    このcommitが済めば、その後QNAPが
    落ちても同じ添付を再アップロードしない。
    """

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE drive_files
        SET
            drive_file_id = ?,
            drive_link = ?,
            uploaded_at = ?,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
          AND attachment_index = ?
        """,
        (
            drive_file_id,
            drive_link,
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
            attachment_index,
        ),
    )

    conn.commit()


def drive_file_is_uploaded(
    conn,
    mailbox,
    uidvalidity,
    uid,
    attachment_index,
    sha256=None,
):
    """
    添付が既にDrive保存済みか確認。

    sha256が渡された場合、
    DB上の添付と現在の添付が同一であることも
    確認する。
    """

    row = get_drive_file(
        conn,
        mailbox,
        uidvalidity,
        uid,
        attachment_index,
    )

    if not row:
        return False

    if sha256 is not None:
        if row["sha256"] != sha256:
            return False

    return bool(
        row["drive_file_id"]
        and row["drive_link"]
    )


def all_drive_files_uploaded(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    rows = get_drive_files(
        conn,
        mailbox,
        uidvalidity,
        uid,
    )

    if not rows:
        return False

    return all(
        row["drive_file_id"]
        and row["drive_link"]
        for row in rows
    )

# =====================================================
# Notification state
# =====================================================

def ensure_notification(
    conn,
    mailbox,
    uidvalidity,
    uid,
    provider,
    *, commit=True,
):
    """
    通知待ちを登録する。

    同じメール + provider がすでに存在する場合は
    何も変更しない。
    """

    message = get_message(conn, mailbox, uidvalidity, uid)
    if message is not None and message['import_origin'] == 'init':
        return
    imported_at = message['notification_imported_at'] if message is not None else None
    now = utc_now_iso()

    conn.execute(
        """
        INSERT OR IGNORE INTO notifications (
            mailbox,
            uidvalidity,
            uid,
            provider,
            status,
            attempts,
            created_at,
            updated_at,
            notification_imported_at
        )
        VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        """,
        (
            mailbox,
            uidvalidity,
            uid,
            provider,
            now,
            now,
            imported_at,
        ),
    )

    if commit:
        conn.commit()
def mark_notification_sent(
    conn,
    mailbox,
    uidvalidity,
    uid,
    provider,
):
    """
    通知送信成功を記録する。
    """

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE notifications
        SET
            status = 'sent',
            attempts = attempts + 1,
            last_error = NULL,
            sent_at = ?,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
          AND provider = ?
          AND status = 'pending'
        """,
        (
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
            provider,
        ),
    )

    conn.commit()

def mark_notification_failed(
    conn,
    mailbox,
    uidvalidity,
    uid,
    provider,
    error,
):
    """
    通知送信失敗を記録する。

    メール本体のstatusには影響させない。
    """

    now = utc_now_iso()

    conn.execute(
        """
        UPDATE notifications
        SET
            status = 'pending',
            attempts = attempts + 1,
            last_error = ?,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
          AND provider = ?
          AND status = 'pending'
        """,
        (
            str(error),
            now,
            mailbox,
            uidvalidity,
            uid,
            provider,
        ),
    )

    conn.commit()

def mark_notification_terminal(conn, mailbox, uidvalidity, uid, provider, status, reason):
    if status not in ('suppressed', 'expired'):
        raise ValueError('Invalid notification terminal state.')
    conn.execute("""UPDATE notifications SET status = ?, last_error = ?, updated_at = ?
        WHERE mailbox = ? AND uidvalidity = ? AND uid = ? AND provider = ? AND status = 'pending'""",
                 (status, reason, utc_now_iso(), mailbox, uidvalidity, uid, provider))
    conn.commit()


def get_pending_notifications(conn, provider=None):
    return conn.execute("""
        SELECT notifications.*, messages.notification_sender, messages.notification_subject,
               messages.notification_sender_name, messages.notification_preview
        FROM notifications LEFT JOIN messages
          ON messages.mailbox = notifications.mailbox
         AND messages.uidvalidity = notifications.uidvalidity
         AND messages.uid = notifications.uid
        WHERE notifications.status = 'pending'
          AND (? IS NULL OR notifications.provider = ?)
        ORDER BY notifications.created_at
    """, (provider, provider)).fetchall()

# =====================================================
# IMAP deletion
# =====================================================

def get_delete_candidates(conn):
    """
    Gmail側への保存が完全に終了し、
    delete_afterを過ぎたものだけ返す。
    """

    now = utc_now_iso()

    return conn.execute(
        """
        SELECT *
        FROM messages
        WHERE status IN (
            'imported',
            'drive_fallback'
        )
          AND gmail_message_id IS NOT NULL
          AND completed_at IS NOT NULL
          AND delete_after IS NOT NULL
          AND delete_after <= ?
          AND imap_deleted = 0
        ORDER BY mailbox, uid
        """,
        (now,),
    ).fetchall()


def mark_imap_deleted(
    conn,
    mailbox,
    uidvalidity,
    uid,
):
    now = utc_now_iso()

    conn.execute(
        """
        UPDATE messages
        SET
            imap_deleted = 1,
            imap_deleted_at = ?,
            updated_at = ?
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            now,
            now,
            mailbox,
            uidvalidity,
            uid,
        ),
    )

    conn.commit()


# =====================================================
# Mailbox state
# =====================================================

def save_mailbox_state(
    conn,
    mailbox,
    uidvalidity,
):
    conn.execute(
        """
        INSERT OR REPLACE INTO mailbox_state (
            mailbox,
            uidvalidity,
            initialized_at
        )
        VALUES (?, ?, ?)
        """,
        (
            mailbox,
            uidvalidity,
            utc_now_iso(),
        ),
    )

    conn.commit()


def get_mailbox_state(
    conn,
    mailbox,
):
    return conn.execute(
        """
        SELECT
            uidvalidity,
            initialized_at
        FROM mailbox_state
        WHERE mailbox = ?
        """,
        (mailbox,),
    ).fetchone()


# =====================================================
# Status
# =====================================================

def count_processed(conn):
    return conn.execute(
        """
        SELECT COUNT(*)
        FROM messages
        WHERE status IN (
            'imported',
            'drive_fallback',
            'ignored'
        )
        """
    ).fetchone()[0]


def count_by_status(conn):
    rows = conn.execute(
        """
        SELECT
            status,
            COUNT(*) AS count
        FROM messages
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()

    return {
        row["status"]: row["count"]
        for row in rows
    }
def get_system_state(
    conn,
    key,
    default=None,
):
    row = conn.execute(
        """
        SELECT value
        FROM system_state
        WHERE key = ?
        """,
        (key,),
    ).fetchone()

    if row is None:
        return default

    return row["value"]

def set_system_state(
    conn,
    key,
    value,
):
    now = utc_now_iso()

    conn.execute(
        """
        INSERT INTO system_state (
            key,
            value,
            updated_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (
            key,
            value,
            now,
        ),
    )

    conn.commit()

def backup_database(
    conn,
    backup_dir="backups/db",
    keep_days=14,
):
    """
    SQLite DBを1日1回バックアップする。

    同じ日のバックアップが既にあれば何もしない。
    最新keep_days個の日次バックアップを保持する（未稼働日もあるため暦日数とは異なる）。
    """

    backup_dir = runtime_path(backup_dir)

    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now(
        timezone.utc
    )

    date_text = now.strftime(
        "%Y-%m-%d"
    )

    backup_path = (
        backup_dir
        / f"state_{date_text}.db"
    )

    # 今日分が既にあれば作らない
    if backup_path.exists():
        return None

    temp_path = (
        backup_dir
        / f".state_{date_text}.tmp"
    )

    if temp_path.exists():
        temp_path.unlink()

    backup_conn = sqlite3.connect(
        temp_path
    )

    try:
        conn.backup(
            backup_conn
        )

        check = backup_conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()

        if (
            not check
            or check[0] != "ok"
        ):
            raise RuntimeError(
                t('state.backup_database.1')
            )

    finally:
        backup_conn.close()

    temp_path.replace(
        backup_path
    )

    # 古いバックアップを削除
    backups = sorted(
        backup_dir.glob(
            "state_*.db"
        )
    )

    if len(backups) > keep_days:
        for old_path in backups[
            :-keep_days
        ]:
            old_path.unlink()

    return backup_path
