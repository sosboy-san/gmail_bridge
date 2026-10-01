import argparse
import sys
import tempfile
import time
from datetime import datetime, timedelta

from app.i18n import t

try:
    import fcntl
except ImportError:  # Help/status and offline tests can also run on Windows.
    fcntl = None

from app.config import configure_language, load_config, validate_runtime_files
from app.drive_client import DriveClient
from app.gmail_client import (
    GmailClient,
    InvalidAttachmentError,
)
from app.i18n import argparse_text, available_languages
from app.imap_client import ImapClient
from app.locking import acquire_lock, locked_command
from app.mime_fallback import (
    build_fallback_message,
    extract_attachments,
    get_original_message_id,
    save_attachment_temp,
    validate_fallback_message,
)
from app.notification_metadata import notification_metadata
from app.notification_service import (
    send_pending_notifications,
)
from app.ntfy_client import NtfyClient
from app.paths import runtime_path
from app.state import (
    all_drive_files_uploaded,
    backup_database,
    count_by_status,
    count_processed,
    drive_file_is_uploaded,
    ensure_drive_file,
    ensure_message,
    ensure_notification,
    get_delete_candidates,
    get_drive_files,
    get_mailbox_state,
    get_message,
    get_system_state,
    is_processed,
    mark_drive_fallback,
    mark_drive_file_uploaded,
    mark_drive_uploaded,
    mark_drive_uploading,
    mark_fallback_gmail_imported_pending,
    mark_gmail_imported_pending,
    mark_ignored,
    mark_imap_deleted,
    mark_imported,
    mark_retry,
    require_initialized,
    save_mailbox_state,
    set_system_state,
    utc_now_iso,
)
from app.state import (
    connect as state_connect,
)


class TeeOutput:
    """
    print出力を
    画面とログファイルの両方へ流す。
    """

    def __init__(
        self,
        terminal,
        log_file,
    ):
        self.terminal = terminal
        self.log_file = log_file

    def write(
        self,
        message,
    ):
        self.terminal.write(
            message
        )

        self.log_file.write(
            message
        )

        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def isatty(self):
        return self.terminal.isatty()


def cleanup_old_logs(
    log_dir,
    keep_days=30,
):
    cutoff = (
        datetime.now()
        - timedelta(
            days=keep_days
        )
    )

    for path in log_dir.glob(
        "gmail_bridge_*.log"
    ):
        try:
            modified = datetime.fromtimestamp(
                path.stat().st_mtime
            )

            if modified < cutoff:
                path.unlink()

        except Exception as e:
            print(
                t('main.cleanup_old_logs.1', v0=f'{path}', v1=f'{e}')
            )


def start_run_logging(
    log_dir="logs",
    keep_days=30,
):
    """
    runの標準出力・標準エラーを
    日別ログへ保存する。
    """

    log_dir = runtime_path(log_dir)

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    cleanup_old_logs(
        log_dir,
        keep_days=keep_days,
    )

    date_text = datetime.now().strftime(
        "%Y-%m-%d"
    )

    log_path = (
        log_dir
        / f"gmail_bridge_{date_text}.log"
    )

    log_file = open(
        log_path,
        "a",
        encoding="utf-8",
        buffering=1,
    )

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    sys.stdout = TeeOutput(
        original_stdout,
        log_file,
    )

    sys.stderr = TeeOutput(
        original_stderr,
        log_file,
    )

    print()
    print(
        "=" * 60
    )
    print(
        t('main.start_run_logging.1', v0=f"{datetime.now().isoformat(timespec='seconds')}")
    )

    return (
        log_file,
        original_stdout,
        original_stderr,
    )


def stop_run_logging(
    log_file,
    original_stdout,
    original_stderr,
):
    print(
        t('main.stop_run_logging.1', v0=f"{datetime.now().isoformat(timespec='seconds')}")
    )

    sys.stdout = original_stdout
    sys.stderr = original_stderr

    log_file.close()

def acquire_run_lock():
    return acquire_lock()

def get_mailbox(config):
    return config.get(
        "imap",
        "mailbox",
        fallback="INBOX",
    )


def get_source_label(config):
    label = config.get(
        "imap",
        "label",
        fallback="",
    ).strip()

    if label:
        return label

    return config["imap"]["user"]


def get_fallback_label(config):
    return config.get(
        "gmail",
        "fallback_label",
        fallback=t('main.get_fallback_label.2'),
    ).strip() or t('main.get_fallback_label.1')

def get_force_not_spam(config):
    return config.getboolean(
        "gmail",
        "force_not_spam",
        fallback=False,
    )

def notification_enabled(config):
    return config.getboolean(
        "notification",
        "enabled",
        fallback=False,
    )


def get_notification_provider(config):
    return config.get(
        "notification",
        "provider",
        fallback="ntfy",
    ).strip() or "ntfy"


def queue_notification(
    db,
    config,
    mailbox,
    uidvalidity,
    uid,
    *, commit=True,
):
    """
    Gmailへの保存が成功したメールを
    通知待ちとして登録する。

    通知OFFの場合は何もしない。
    """

    if not notification_enabled(config):
        return

    provider = get_notification_provider(
        config
    )

    ensure_notification(
        db,
        mailbox,
        uidvalidity,
        uid,
        provider,
        commit=commit,
    )

def get_delete_delay_days(config):
    enabled = config.getboolean(
        "imap",
        "delete_after_import",
        fallback=False,
    )

    if not enabled:
        # 現在のstate APIではNoneを受けないので、
        # 非削除設定時は十分遠い日付にするのではなく、
        # main側で確定後にNULLへ戻す。
        return None

    return config.getint(
        "imap",
        "delete_delay_days",
        fallback=7,
    )


def make_imap(config):
    return ImapClient(
        config["imap"]["host"],
        config.getint("imap", "port", fallback=143),
        config["imap"]["user"],
        config["imap"]["password"],
    )


def make_gmail(config):
    token_file = config.get(
        "gmail",
        "token_file",
        fallback="token.json",
    )

    gmail = GmailClient(runtime_path(token_file))
    gmail.connect()

    return gmail


def make_drive(config):
    token_file = config.get(
        "gmail",
        "token_file",
        fallback="token.json",
    )

    drive = DriveClient(runtime_path(token_file))
    drive.connect()

    return drive

def make_ntfy(config):
    section = config["notification"]

    return NtfyClient(
        section.get(
            "server_url",
            "https://ntfy.sh",
        ),
        section["topic"],
        token=section.get(
            "token",
            "",
        ),
    )

def send_system_notification(
    config,
    message,
    title="Gmail Bridge",
    *, config_loader=None,
):
    """
    システム障害・復旧通知。

    通知失敗でBridge本体を停止させない。
    """
    if config_loader is not None:
        config = config_loader()
    if not notification_enabled(config):
        print(
            t('main.send_system_notification.1')
        )
        return False

    provider = get_notification_provider(
        config
    )

    if provider != "ntfy":
        print(
            t('main.send_system_notification.2', v0=f'{provider}')
        )
        return False

    try:
        client = make_ntfy(config)

        client.send(
            message,
            title=title,
        )

        return True

    except Exception as e:
        print(
            t('main.send_system_notification.3', v0=f'{e}')
        )
        return False


def connect_imap_with_retry(
    imap,
    attempts=3,
):
    """
    IMAP接続を最大attempts回試す。

    成功:
        Noneを返す

    全失敗:
        最後の例外をraiseする
    """
    last_error = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        try:
            print(
                t('main.connect_imap_with_retry.1', v0=f'{attempt}', v1=f'{attempts}')
            )

            imap.connect()

            return

        except Exception as e:
            last_error = e

            print(
                t('main.connect_imap_with_retry.2', v0=f'{attempt}', v1=f'{attempts}', v2=f'{e}')
            )

            try:
                imap.close()
            except Exception:
                pass

            if attempt < attempts:
                wait_seconds = (
                    10
                    if attempt == 1
                    else 30
                )

                print(
                    t('main.connect_imap_with_retry.3', v0=f'{wait_seconds}')
                )

                time.sleep(
                    wait_seconds
                )

    raise last_error


def handle_imap_connection_failure(
    db,
    config,
    error,
):
    """
    IMAP接続が全リトライ失敗した場合の処理。

    down:
        障害通知済み

    down_unnotified:
        障害通知に失敗したため、
        次回runでも通知を再試行する
    """
    previous = get_system_state(
        db,
        "imap_status",
        "unknown",
    )

    # すでに通知済みの障害なら
    # 毎回通知しない
    if previous == "down":
        return

    sent = send_system_notification(
        config,
        (
            t('main.handle_imap_connection_failure.1', v0=f'{error}')
        ),
        title=t("system.alert_title"),
        config_loader=load_config,
    )

    if sent:
        set_system_state(
            db,
            "imap_status",
            "down",
        )

        print(
            t('main.handle_imap_connection_failure.2')
        )

    else:
        set_system_state(
            db,
            "imap_status",
            "down_unnotified",
        )

def clear_delete_after(
    db,
    mailbox,
    uidvalidity,
    uid,
    *, commit=True,
):
    db.execute(
        """
        UPDATE messages
        SET delete_after = NULL
        WHERE mailbox = ?
          AND uidvalidity = ?
          AND uid = ?
        """,
        (
            mailbox,
            uidvalidity,
            uid,
        ),
    )
    if commit:
        db.commit()

def print_message(uid, summary):
    print(
        t('main.print_message.1', v0=f'{uid}', v1=f"{summary['date']}", v2=f"{summary['from']}", v3=f"{summary['subject']}")
    )

def finalize_normal(
    gmail,
    db,
    config,
    mailbox,
    uidvalidity,
    uid,
    gmail_id,
    original_message_id,
    source_seen,
):
    """
    Gmail import後の通常ルートを確定する。
    """

    source_label = get_source_label(
        config
    )

    gmail.apply_source_label(
        gmail_id,
        source_label,
    )
    
    if not source_seen:
        gmail.mark_unread(
            gmail_id,
        )

    if get_force_not_spam(config):
        gmail.remove_label(
            gmail_id,
            "SPAM",
        )

    delay = get_delete_delay_days(
        config
    )

    # Final mail state and the single notification registration commit together.
    with db:
        mark_imported(
            db, mailbox, uidvalidity, uid, gmail_id,
            original_message_id,
            delete_delay_days=delay if delay is not None else 7,
            commit=False,
        )
        if delay is None:
            clear_delete_after(db, mailbox, uidvalidity, uid, commit=False)
        queue_notification(db, config, mailbox, uidvalidity, uid, commit=False)

def finalize_fallback(
    gmail,
    db,
    config,
    mailbox,
    uidvalidity,
    uid,
    gmail_id,
    source_seen,
):
    """
    Gmail軽量版import後の
    Drive fallbackルートを確定する。
    """

    source_label = get_source_label(
        config
    )

    fallback_label = get_fallback_label(
        config
    )

    gmail.apply_source_label(
        gmail_id,
        source_label,
    )

    gmail.apply_source_label(
        gmail_id,
        fallback_label,
    )
    
    if not source_seen:
        gmail.mark_unread(
            gmail_id,
        )

    if get_force_not_spam(config):
        gmail.remove_label(
            gmail_id,
            "SPAM",
        )

    delay = get_delete_delay_days(
        config
    )

    # Final mail state and the single notification registration commit together.
    with db:
        mark_drive_fallback(
            db, mailbox, uidvalidity, uid, gmail_id,
            delete_delay_days=delay if delay is not None else 7,
            commit=False,
        )
        if delay is None:
            clear_delete_after(db, mailbox, uidvalidity, uid, commit=False)
        queue_notification(db, config, mailbox, uidvalidity, uid, commit=False)

def upload_fallback_attachments(
    drive,
    db,
    config,
    mailbox,
    uidvalidity,
    uid,
    raw,
):
    """
    Gmailが拒否したメールの添付を
    Driveへ退避する。

    添付ごとにDBへ即commitするので、
    途中停止してもアップロード済み添付を
    再利用できる。
    """

    attachments = extract_attachments(
        raw
    )

    if not attachments:
        raise RuntimeError(
            t('main.upload_fallback_attachments.1')
        )

    original_message_id = (
        get_original_message_id(raw)
    )

    mark_drive_uploading(
        db,
        mailbox,
        uidvalidity,
        uid,
        original_message_id,
    )

    folder_name = config.get(
        "drive",
        "folder",
        fallback="Gmail-IMAP-Bridge",
    )

    folder_id = drive.get_or_create_folder(
        folder_name
    )

    with tempfile.TemporaryDirectory(
        prefix="gmail_bridge_"
    ) as temp_dir:

        for attachment in attachments:

            index = attachment["index"]

            ensure_drive_file(
                db,
                mailbox,
                uidvalidity,
                uid,
                index,
                attachment["filename"],
                attachment["content_type"],
                attachment["sha256"],
            )

            if drive_file_is_uploaded(
                db,
                mailbox,
                uidvalidity,
                uid,
                index,
                attachment["sha256"],
            ):
                print(
                    t('main.upload_fallback_attachments.5', v0=f'{index}')
                )
                continue

            temp_path = save_attachment_temp(
                attachment,
                temp_dir,
            )

            print(
                t('main.upload_fallback_attachments.3', v0=f"{attachment['filename']}")
            )

            result = drive.upload_file(
                temp_path,
                folder_id=folder_id,
                drive_name=attachment[
                    "filename"
                ],
                mimetype=attachment[
                    "content_type"
                ],
            )

            drive_id = result.get("id")
            drive_link = result.get(
                "webViewLink"
            )

            if not drive_id:
                raise RuntimeError(
                    t('main.upload_fallback_attachments.6')
                )

            if not drive_link:
                raise RuntimeError(
                    t('main.upload_fallback_attachments.7')
                )

            mark_drive_file_uploaded(
                db,
                mailbox,
                uidvalidity,
                uid,
                index,
                drive_id,
                drive_link,
            )

            print(
                t('main.upload_fallback_attachments.4', v0=f'{drive_id}')
            )

    if not all_drive_files_uploaded(
        db,
        mailbox,
        uidvalidity,
        uid,
    ):
        raise RuntimeError(
            t('main.upload_fallback_attachments.2')
        )

    mark_drive_uploaded(
        db,
        mailbox,
        uidvalidity,
        uid,
    )


def make_drive_files_for_mime(
    db,
    mailbox,
    uidvalidity,
    uid,
):
    rows = get_drive_files(
        db,
        mailbox,
        uidvalidity,
        uid,
    )

    result = []

    for row in rows:
        if (
            not row["drive_file_id"]
            or not row["drive_link"]
        ):
            raise RuntimeError(
                t('main.make_drive_files_for_mime.1')
            )

        result.append({
            "name": row["filename"],
            "id": row["drive_file_id"],
            "webViewLink":
                row["drive_link"],
        })

    return result


def process_uid(
    imap,
    gmail,
    drive,
    db,
    config,
    mailbox,
    uidvalidity,
    uid,
    dry_run=False,
    *, import_origin="run",
):
    """
    UID 1通を処理。

    return:
        imported
        fallback
        skipped
        failed
        dry-run
    """

    row = get_message(
        db,
        mailbox,
        uidvalidity,
        uid,
    )

    # 完全終了済み
    if row and row["status"] in (
        "imported",
        "drive_fallback",
        "ignored",
    ):
        return "skipped"

    try:
        raw = imap.fetch_raw(uid)
        source_seen = imap.is_seen(uid)
        summary = imap.get_summary(raw)

        print_message(
            uid,
            summary,
        )

        if dry_run:
            return "dry-run"

        ensure_message(
            db,
            mailbox,
            uidvalidity,
            uid,
            import_origin=import_origin,
        )

        sender, subject = notification_metadata(raw)

        original_message_id = (
            get_original_message_id(raw)
        )

        # ---------------------------------------------
        # 再起動復旧:
        # 通常Gmail import済み
        # ---------------------------------------------
        row = get_message(
            db,
            mailbox,
            uidvalidity,
            uid,
        )

        if (
            row
            and row["status"]
            == "gmail_imported_pending"
            and row["gmail_message_id"]
        ):
            gmail_id = row[
                "gmail_message_id"
            ]

            print(
                t('main.process_uid.2')
            )

            finalize_normal(
                gmail,
                db,
                config,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                (
                    row["original_message_id"]
                    or original_message_id
                ),
                source_seen,
            )

            print(
                t('main.process_uid.3', v0=f'{gmail_id}')
            )

            return "imported"

        # ---------------------------------------------
        # 再起動復旧:
        # fallback Gmail import済み
        # ---------------------------------------------
        if (
            row
            and row["status"]
            == "fallback_gmail_imported_pending"
            and row["gmail_message_id"]
        ):
            gmail_id = row[
                "gmail_message_id"
            ]

            print(
                t('main.process_uid.4')
            )

            finalize_fallback(
                gmail,
                db,
                config,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                source_seen,
            )

            print(
                t('main.process_uid.5', v0=f'{gmail_id}')
            )

            return "fallback"

        # ---------------------------------------------
        # 既にDriveまで終わっている場合
        # Gmail軽量版から再開
        # ---------------------------------------------
        if (
            row
            and row["status"]
            in (
                "drive_uploaded",
                "drive_uploading",
            )
        ):
            if not all_drive_files_uploaded(
                db,
                mailbox,
                uidvalidity,
                uid,
            ):
                if drive is None:
                    drive = make_drive(
                        config
                    )

                upload_fallback_attachments(
                    drive,
                    db,
                    config,
                    mailbox,
                    uidvalidity,
                    uid,
                    raw,
                )

            drive_files = (
                make_drive_files_for_mime(
                    db,
                    mailbox,
                    uidvalidity,
                    uid,
                )
            )

            fallback_raw = (
                build_fallback_message(
                    raw,
                    drive_files,
                )
            )
            validate_fallback_message(
               fallback_raw
            )

            gmail_id = gmail.import_message(
                fallback_raw
            )

            mark_fallback_gmail_imported_pending(
                db,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                sender=sender, subject=subject, imported_at=utc_now_iso(),
            )

            finalize_fallback(
                gmail,
                db,
                config,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                source_seen,
            )

            print(
                t('main.process_uid.6', v0=f'{gmail_id}')
            )

            return "fallback"

        # ---------------------------------------------
        # 通常 Gmail import
        # ---------------------------------------------
        try:
            gmail_id = gmail.import_message(
                raw
            )

        except InvalidAttachmentError:

            print(
                t('main.process_uid.8')
            )
            print(
                t('main.process_uid.9')
            )

            if drive is None:
                drive = make_drive(
                    config
                )

            upload_fallback_attachments(
                drive,
                db,
                config,
                mailbox,
                uidvalidity,
                uid,
                raw,
            )

            drive_files = (
                make_drive_files_for_mime(
                    db,
                    mailbox,
                    uidvalidity,
                    uid,
                )
            )

            fallback_raw = (
                build_fallback_message(
                    raw,
                    drive_files,
                )
            )
            validate_fallback_message(
                fallback_raw
            )

            gmail_id = gmail.import_message(
                fallback_raw
            )

            # Gmail成功直後にDBへ保存
            mark_fallback_gmail_imported_pending(
                db,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                sender=sender, subject=subject, imported_at=utc_now_iso(),
            )

            finalize_fallback(
                gmail,
                db,
                config,
                mailbox,
                uidvalidity,
                uid,
                gmail_id,
                source_seen,
            )

            print(
                t('main.process_uid.10', v0=f'{gmail_id}')
            )

            return "fallback"

        # ---------------------------------------------
        # 通常import成功
        # Gmail IDを即DBへ保存
        # ---------------------------------------------
        mark_gmail_imported_pending(
            db,
            mailbox,
            uidvalidity,
            uid,
            gmail_id,
            original_message_id,
            sender=sender, subject=subject, imported_at=utc_now_iso(),
        )

        finalize_normal(
            gmail,
            db,
            config,
            mailbox,
            uidvalidity,
            uid,
            gmail_id,
            original_message_id,
            source_seen,
        )

        print(
            t('main.process_uid.1', v0=f'{gmail_id}')
        )

        return "imported"

    except Exception as e:

        # Gmail import自体が既に成功している
        # pending状態をretryで潰さない。
        current = get_message(
            db,
            mailbox,
            uidvalidity,
            uid,
        )

        if not (
            current
            and current["status"] in (
                "gmail_imported_pending",
                "fallback_gmail_imported_pending",
            )
        ):
            mark_retry(
                db,
                mailbox,
                uidvalidity,
                uid,
                e,
            )

        print(
            t('main.process_uid.7', v0=f'{e}')
        )

        return "failed"


def _connection_settings(config):
    return tuple(config.get(section, option, fallback=default) for section, option, default in (
        ('imap', 'host', ''), ('imap', 'port', '143'), ('imap', 'user', ''),
        ('imap', 'password', ''), ('imap', 'mailbox', 'INBOX'),
        ('gmail', 'token_file', 'token.json'),
    ))


def import_uids(
    imap,
    gmail,
    drive,
    db,
    config,
    mailbox,
    uidvalidity,
    uids,
    dry_run=False,
    *, import_origin="run", config_loader=None,
):
    imported = 0
    fallback = 0
    skipped = 0
    failed = 0
    connection_settings = _connection_settings(config)

    if not dry_run and import_origin == 'init':
        with db:
            for uid in uids:
                ensure_message(db, mailbox, uidvalidity, uid, import_origin='init', commit=False)
    since_notifications = 0
    last_notifications = time.monotonic()
    next_notification = 0
    for uid in uids:
        if config_loader is not None:
            config = config_loader()
            if _connection_settings(config) != connection_settings:
                raise RuntimeError(t('config.connection_changed'))

        result = process_uid(
            imap,
            gmail,
            drive,
            db,
            config,
            mailbox,
            uidvalidity,
            uid,
            dry_run=dry_run,
            import_origin=import_origin,
        )

        if result == "imported":
            imported += 1

        elif result == "fallback":
            fallback += 1

        elif result == "skipped":
            skipped += 1

        elif result == "failed":
            failed += 1

        since_notifications += 1
        if not dry_run and import_origin != 'init' and time.monotonic() >= next_notification and (
                since_notifications >= 5 or time.monotonic() - last_notifications >= 30):
            result = send_pending_notifications(db, config, config_loader=config_loader or (lambda: config))
            since_notifications = 0
            last_notifications = time.monotonic()
            if result and result.get('failed'):
                next_notification = last_notifications + 30
    if not dry_run and import_origin != 'init' and since_notifications and time.monotonic() >= next_notification:
        send_pending_notifications(db, config, config_loader=config_loader or (lambda: config))

    print()
    print(
        t('main.import_uids.1', v0=f'{imported}', v1=f'{fallback}', v2=f'{skipped}', v3=f'{failed}')
    )


def confirm_bulk(count, yes=False):
    if yes:
        return

    answer = input(
        t('main.confirm_bulk.1', v0=f'{count}')
    )

    if answer.strip().lower() not in (
        "y",
        "yes",
    ):
        raise RuntimeError(
            t('main.confirm_bulk.2')
        )


@locked_command
def command_init(args, config):
    mailbox = get_mailbox(config)

    imap = make_imap(config)
    db = state_connect(create=True)

    try:
        print(t('main.command_init.1'))
        imap.connect()

        uidvalidity = imap.select_mailbox(
            mailbox,
            readonly=True,
        )

        print(
            t('main.command_init.2', v0=f'{mailbox}')
        )
        print(
            t('main.command_init.3', v0=f'{uidvalidity}')
        )

        all_uids = (
            imap.search_all_uids()
        )

        if args.from_now:

            print(
                t('main.command_init.5', v0=f'{len(all_uids)}')
            )

            if not args.dry_run:

                for uid in all_uids:
                    ensure_message(
                        db,
                        mailbox,
                        uidvalidity,
                        uid,
                    )

                    mark_ignored(
                        db,
                        mailbox,
                        uidvalidity,
                        uid,
                    )

                save_mailbox_state(
                    db,
                    mailbox,
                    uidvalidity,
                )

            print(
                t('main.command_init.6')
            )

            return

        if args.uid is not None:

            if args.uid not in all_uids:
                raise RuntimeError(
                    t('main.command_init.7', v0=f'{args.uid}', v1=f'{mailbox}')
                )

            uids = [args.uid]

        elif args.all:
            uids = all_uids

        elif args.latest is not None:
            uids = all_uids[
                -args.latest:
            ]

        elif args.since:
            date = datetime.strptime(
                args.since,
                "%Y-%m-%d",
            )

            uids = imap.search_since(
                date
            )

        else:
            raise RuntimeError(
                t('main.command_init.8')
            )

        print(
            t('main.command_init.4', v0=f'{len(uids)}')
        )

        if (
            len(uids) > 1
            and not args.dry_run
        ):
            confirm_bulk(
                len(uids),
                args.yes,
            )

        if args.dry_run:
            gmail = None
        else:
            with db:
                for uid in uids:
                    ensure_message(db, mailbox, uidvalidity, uid, import_origin='init', commit=False)
            gmail = make_gmail(
                config
            )

        import_uids(
            imap,
            gmail,
            None,
            db,
            config,
            mailbox,
            uidvalidity,
            uids,
            dry_run=args.dry_run,
            import_origin="init", config_loader=load_config,
        )

        if not args.dry_run:
            save_mailbox_state(
                db,
                mailbox,
                uidvalidity,
            )

    finally:
        imap.close()
        db.close()


def command_run(args, config):
    lock_file = acquire_run_lock()

    if lock_file is None:
        print(
            t('main.command_run.1')
        )
        return

    imap = None
    db = None
    try:
        mailbox = get_mailbox(config)

        db = state_connect()
        require_initialized(db, mailbox)
        imap = make_imap(config)
    
        backup_path = backup_database(
            db,
            backup_dir="backups/db",
            keep_days=14,
        )

        if backup_path is not None:
            print(
                t('main.command_run.2', v0=f'{backup_path}')
            )

        try:
            connect_imap_with_retry(
                imap,
                attempts=3,
            )

        except Exception as e:
            handle_imap_connection_failure(
                db,
                config,
                e,
            )

            return

        previous_imap_status = get_system_state(
            db,
            "imap_status",
            "unknown",
        )

        if previous_imap_status in (
            "down",
            "down_unnotified",
        ):
            sent = send_system_notification(
                config,
                t('main.command_run.3'),
                title=t("system.recovery_title"),
                config_loader=load_config,
            )

            if sent:
                print(
                    t('main.command_run.8')
                )

        set_system_state(
            db,
            "imap_status",
            "ok",
        )

        uidvalidity = imap.select_mailbox(
            mailbox,
            readonly=True,
        )

        state = get_mailbox_state(
            db,
            mailbox,
        )

        if not state:
            raise RuntimeError(
                t('main.command_run.4')
            )

        saved_uidvalidity = state[0]

        if (
            str(saved_uidvalidity)
            != str(uidvalidity)
        ):
            raise RuntimeError(
                t('main.command_run.5')
            )

        all_uids = (
            imap.search_all_uids()
        )

        if args.uid is not None:

            if args.uid not in all_uids:
                raise RuntimeError(
                    t('main.command_run.9', v0=f'{args.uid}', v1=f'{mailbox}')
                )

            pending = [args.uid]

        else:
            pending = [
                uid
                for uid in all_uids
                if not is_processed(
                    db,
                    mailbox,
                    uidvalidity,
                    uid,
                )
            ]

        if args.uid is not None:
            print(
                t('main.command_run.6', v0=f'{len(pending)}')
            )
        else:
            print(
                t('main.command_run.7', v0=f'{len(pending)}')
            )

        if not pending:
            if not args.dry_run:
                notification_result = (
                    send_pending_notifications(
                        db,
                        config,
                    )
                )

                if (
                    notification_result["sent"]
                    or notification_result["failed"]
                ):
                    print(
                        t('main.command_run.11', v0=f"{notification_result['sent']}", v1=f"{notification_result['failed']}")
                    )

            return

        if args.dry_run:
            gmail = None
        else:
            gmail = make_gmail(
                config
            )

        import_uids(
            imap,
            gmail,
            None,
            db,
            config,
            mailbox,
            uidvalidity,
            pending,
            dry_run=args.dry_run,
            config_loader=load_config,
        )


    finally:
        try:
            if imap is not None:
                imap.close()
        finally:
            try:
                if db is not None:
                    db.close()
            finally:
                lock_file.close()

@locked_command
def command_cleanup(args, config):
    # Turning deletion off also suspends previously scheduled deletions.
    if not config.getboolean("imap", "delete_after_import", fallback=False):
        print(t("cleanup.disabled"))
        return

    db = state_connect()

    try:
        require_initialized(db, get_mailbox(config))
        candidates = get_delete_candidates(
            db
        )
        for candidate in candidates:
            require_initialized(db, candidate['mailbox'])

        print(
            t('main.command_cleanup.1', v0=f'{len(candidates)}')
        )

        if not candidates:
            return

        print()

        for row in candidates:
            print(
                t('main.command_cleanup.2', v0=f"{row['mailbox']}", v1=f"{row['uid']}", v2=f"{row['status']}", v3=f"{row['delete_after']}")
            )

        if args.dry_run:
            print()
            print(
                t('main.command_cleanup.3')
            )
            return

        imap = make_imap(config)

        try:
            print()
            print(t('main.command_cleanup.4'))
            imap.connect()

            deleted = 0
            failed = 0

            for row in candidates:
                mailbox = row["mailbox"]
                uidvalidity = row["uidvalidity"]
                uid = row["uid"]

                try:
                    print(
                        t('main.command_cleanup.7', v0=f'{mailbox}', v1=f'{uid}')
                    )

                    result = imap.delete_uid(
                        mailbox,
                        uidvalidity,
                        uid,
                    )

                    if result:
                        mark_imap_deleted(
                            db,
                            mailbox,
                            uidvalidity,
                            uid,
                        )

                        deleted += 1

                        print(
                            t('main.command_cleanup.8')
                        )

                    else:
                        # IMAP側に既に存在しない場合。
                        # DBを勝手に削除済みにはせず、
                        # 人間が確認できる状態で残す。
                        failed += 1

                        print(
                            t('main.command_cleanup.9')
                        )

                except Exception as e:
                    failed += 1

                    print(
                        t('main.command_cleanup.10', v0=f'{e}')
                    )

            print()
            print(
                t('main.command_cleanup.5', v0=f'{deleted}', v1=f'{failed}')
            )

            if failed > 0:
                raise RuntimeError(
                    t('main.command_cleanup.6', v0=f'{failed}')
                )

        finally:
            imap.close()

    finally:
        db.close()
        
@locked_command
def command_status(args, config):
    mailbox = get_mailbox(config)

    db = state_connect()

    try:
        state = get_mailbox_state(
            db,
            mailbox,
        )

        print(t('main.command_status.1'))
        print()

        print(
            t('main.command_status.2', v0=f'{mailbox}')
        )
        print(
            t('main.command_status.3', v0=f'{count_processed(db)}')
        )
        print(
            t('main.command_status.4', v0=f'{count_by_status(db)}')
        )

        if state:
            print(
                t('main.command_status.5', v0=f'{state[0]}')
            )
            print(
                t('main.command_status.6', v0=f'{state[1]}')
            )
        else:
            print(
                t('main.command_status.7')
            )

    finally:
        db.close()


def build_parser():
    argparse._ = argparse_text
    parser = argparse.ArgumentParser(
        description=t("cli.description")
    )
    parser.add_argument("--lang", choices=available_languages(), help=t("cli.language"))

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init = sub.add_parser(
        "init",
        help=t('main.build_parser.1'),
    )

    group = (
        init.add_mutually_exclusive_group(
            required=True
        )
    )

    group.add_argument(
        "--from-now",
        action="store_true",
        help=t('main.build_parser.2'),
    )

    group.add_argument(
        "--all",
        action="store_true",
        help=t('main.build_parser.3'),
    )

    group.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help=t('main.build_parser.4'),
    )

    group.add_argument(
        "--latest",
        type=int,
        metavar="N",
        help=t('main.build_parser.5'),
    )

    group.add_argument(
        "--uid",
        type=int,
        metavar="UID",
        help=t('main.build_parser.6'),
    )

    init.add_argument(
        "--dry-run",
        action="store_true",
        help=t('main.build_parser.7'),
    )

    init.add_argument(
        "--yes",
        action="store_true",
        help=t('main.build_parser.8'),
    )

    run = sub.add_parser(
        "run",
        help=t('main.build_parser.9'),
    )


    run.add_argument(
        "--uid",
        type=int,
        metavar="UID",
        help=t('main.build_parser.10'),
    )

    run.add_argument(
        "--dry-run",
        action="store_true",
        help=t('main.build_parser.11'),
    )

    sub.add_parser(
        "status",
        help=t('main.build_parser.12'),
    )

    cleanup = sub.add_parser(
        "cleanup",
        help=t('main.build_parser.13'),
    )

    cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help=t('main.build_parser.14'),
    )

    return parser


def main():
    language_parser = argparse.ArgumentParser(add_help=False)
    language_parser.add_argument("--lang")
    language_args, _ = language_parser.parse_known_args()
    configure_language(language_args.lang)
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "latest", None) is not None and args.latest < 1:
        parser.error(t("cli.positive_latest"))
    if getattr(args, "uid", None) is not None and args.uid < 1:
        parser.error(t("cli.positive_uid"))
    if getattr(args, "since", None):
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            parser.error(t("cli.invalid_date"))

    config = load_config()

    if args.command == "init":
        command_init(
            args,
            config,
        )

    elif args.command == "run":
        validate_runtime_files(config)
        (
            log_file,
            original_stdout,
            original_stderr,
        ) = start_run_logging()

        try:
            command_run(
                args,
                config,
            )

        finally:
            stop_run_logging(
                log_file,
                original_stdout,
                original_stderr,
            )

    elif args.command == "status":
        command_status(
            args,
            config,
        )
    elif args.command == "cleanup":
        command_cleanup(
            args,
            config,
        )    


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(t("cli.error", error=error), file=sys.stderr)
        sys.exit(1)
