import time
from datetime import datetime

from app.config import load_config, validate_notifications
from app.i18n import t
from app.notification_metadata import display_text
from app.ntfy_client import NtfyClient
from app.state import (
    get_pending_notifications,
    get_system_state,
    mark_notification_failed,
    mark_notification_sent,
    mark_notification_terminal,
    set_system_state,
    utc_now,
)


def make_ntfy_client(config):
    """
    config.ini から ntfy client を作成する。
    """

    server_url = config.get(
        "notification",
        "server_url",
        fallback="https://ntfy.sh",
    ).strip()

    topic = config.get(
        "notification",
        "topic",
        fallback="",
    ).strip()

    token = config.get(
        "notification",
        "token",
        fallback="",
    ).strip()

    if not topic:
        raise RuntimeError(
            t('notification_service.make_ntfy_client.1')
        )

    return NtfyClient(
        server_url=server_url,
        topic=topic,
        token=token or None,
    )


def _expired(row, minutes):
    if minutes == 0:
        return False
    try:
        stamp = datetime.fromisoformat(row['notification_imported_at'])
        if stamp.tzinfo is None:
            return True
        return (utc_now() - stamp).total_seconds() >= minutes * 60
    except (TypeError, ValueError, OverflowError):
        return True


def sender_allowed(sender, settings):
    mode = settings.sender_filter_mode
    if mode == 'off':
        return True
    if not sender or sender.count('@') != 1:
        return False
    address = sender.lower()
    domain = address.rsplit('@', 1)[1]
    blocked = address in settings.block_addresses or domain in settings.block_domains
    allowed = address in settings.allow_addresses or domain in settings.allow_domains
    if mode == 'blocklist':
        return not blocked
    if mode == 'allowlist':
        return allowed
    return allowed and not blocked


def _finish(db, row, status, reason):
    mark_notification_terminal(db, row['mailbox'], row['uidvalidity'], row['uid'],
                               row['provider'], status, reason)
    key = 'notification.expired' if status == 'expired' else 'notification.skipped'
    print(t(key, reason=reason))


def _body(row, settings):
    lines = [t('notification_service.send_pending_notifications.4')]
    if settings.include_sender and row['notification_sender']:
        lines.append(t('notification.sender', value=display_text(row['notification_sender'])))
    if settings.include_subject and row['notification_subject']:
        lines.append(t('notification.subject', value=display_text(row['notification_subject'])))
    return '\n'.join(lines)


def send_pending_notifications(db, config=None, *, config_loader=load_config):
    """Revalidate latest settings before sends; notifications never re-import mail.

    Bound network work per opportunity and stop on first transport failure.
    Terminal classification continues without network even after that failure.
    """
    config = config_loader()
    settings = getattr(config, 'notification_settings', None) or validate_notifications(config)
    result = {'sent': 0, 'failed': 0}
    if not settings.enabled:
        return result
    if not config.has_option('notification', 'ttl_minutes') and not get_system_state(
            db, 'notification_legacy_ttl_logged', ''):
        print(t('notification.legacy_ttl'))
        set_system_state(db, 'notification_legacy_ttl_logged', '1')
    rows = get_pending_notifications(db, provider='ntfy')
    started = time.monotonic()
    network_failed = False
    requests = 0
    for row in rows:
        config = config_loader()
        settings = getattr(config, 'notification_settings', None) or validate_notifications(config)
        if not settings.enabled:
            break
        if _expired(row, settings.ttl_minutes):
            _finish(db, row, 'expired', 'ttl_exceeded_or_unknown_timestamp')
            continue
        if not sender_allowed(row['notification_sender'], settings):
            reason = 'sender_not_determined' if not row['notification_sender'] else 'sender_filter'
            _finish(db, row, 'suppressed', reason)
            continue
        if network_failed or requests >= 10 or time.monotonic() - started >= 30:
            continue
        # Settings and TTL above were checked immediately before this send.
        try:
            requests += 1
            client = make_ntfy_client(config)
            client.send(title='Gmail Bridge', message=_body(row, settings))
        except Exception:
            mark_notification_failed(db, row['mailbox'], row['uidvalidity'], row['uid'],
                                     'ntfy', 'ntfy_send_failed')
            result['failed'] += 1
            network_failed = True
            print(t('notification.send_failed'))
        else:
            mark_notification_sent(db, row['mailbox'], row['uidvalidity'], row['uid'], 'ntfy')
            result['sent'] += 1
            print(t('notification_service.send_pending_notifications.3',
                    v0=row['mailbox'], v1=row['uid']))
    return result
