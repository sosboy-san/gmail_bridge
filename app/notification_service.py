from app.i18n import t
from app.ntfy_client import NtfyClient
from app.state import (
    get_pending_notifications,
    mark_notification_failed,
    mark_notification_sent,
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


def send_pending_notifications(
    db,
    config,
):
    """
    pending状態の通知を送信する。

    通知失敗はメール本体の処理には影響させない。
    失敗した通知はpendingのまま残し、
    次回再試行できるようにする。
    """

    enabled = config.getboolean(
        "notification",
        "enabled",
        fallback=False,
    )

    if not enabled:
        return {
            "sent": 0,
            "failed": 0,
        }

    provider = config.get(
        "notification",
        "provider",
        fallback="ntfy",
    ).strip().lower()

    if provider != "ntfy":
        print(
            t('notification_service.send_pending_notifications.1', v0=f'{provider}')
        )
        return {
            "sent": 0,
            "failed": 0,
        }

    try:
        client = make_ntfy_client(config)

    except Exception as e:
        print(
            t('notification_service.send_pending_notifications.2', v0=f'{e}')
        )
        return {
            "sent": 0,
            "failed": 0,
        }

    rows = get_pending_notifications(
        db,
        provider="ntfy",
    )

    sent = 0
    failed = 0

    for row in rows:
        mailbox = row["mailbox"]
        uidvalidity = row["uidvalidity"]
        uid = row["uid"]

        try:
            client.send(
                title="Gmail Bridge",
                message=t('notification_service.send_pending_notifications.4'),
            )

            mark_notification_sent(
                db,
                mailbox,
                uidvalidity,
                uid,
                "ntfy",
            )

            sent += 1

            print(
                t('notification_service.send_pending_notifications.3', v0=f'{mailbox}', v1=f'{uid}')
            )

        except Exception as e:
            mark_notification_failed(
                db,
                mailbox,
                uidvalidity,
                uid,
                "ntfy",
                e,
            )

            failed += 1

            print(
                t('notification_service.send_pending_notifications.5', v0=f'{mailbox}', v1=f'{uid}', v2=f'{e}')
            )

    return {
        "sent": sent,
        "failed": failed,
    }
