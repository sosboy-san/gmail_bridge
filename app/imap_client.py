import imaplib
import ssl
from email import policy
from email.parser import BytesParser

from app.i18n import t


class ImapClient:

    def __init__(self, host, port, user, password):
        self.host = host
        self.port = port
        self.user = user
        self.password = password

        self.imap = None
        self.current_mailbox = None
        self.readonly = True

    def connect(self):
        self.imap = imaplib.IMAP4(
            self.host,
            self.port
        )

        self.imap.starttls(ssl_context=ssl.create_default_context())

        self.imap.login(
            self.user,
            self.password
        )

    def close(self):
        if self.imap:
            try:
                self.imap.logout()
            except Exception:
                pass

            self.imap = None

    def select_mailbox(
        self,
        mailbox="INBOX",
        readonly=True,
    ):
        status, data = self.imap.select(
            mailbox,
            readonly=readonly
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.select_mailbox.1', v0=f'{mailbox}')
            )

        self.current_mailbox = mailbox
        self.readonly = readonly

        response = self.imap.response(
            "UIDVALIDITY"
        )

        if not response or not response[1]:
            raise RuntimeError(
                t('imap_client.select_mailbox.2')
            )

        uidvalidity = response[1][0]

        if isinstance(uidvalidity, bytes):
            uidvalidity = uidvalidity.decode()

        return uidvalidity

    def search_all_uids(self):
        status, data = self.imap.uid(
            "search",
            None,
            "ALL"
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.search_all_uids.1')
            )

        return [
            int(uid)
            for uid in data[0].split()
        ]

    def search_since(self, date):
        imap_date = date.strftime(
            "%d-%b-%Y"
        )

        status, data = self.imap.uid(
            "search",
            None,
            "SINCE",
            imap_date
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.search_since.1')
            )

        return [
            int(uid)
            for uid in data[0].split()
        ]

    def uid_exists(self, uid):
        """
        指定UIDが現在のメールボックスに
        存在するか確認。
        """

        status, data = self.imap.uid(
            "search",
            None,
            "UID",
            str(uid)
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.uid_exists.1', v0=f'{uid}')
            )

        found = [
            int(value)
            for value in data[0].split()
        ]

        return uid in found

    def fetch_raw(self, uid):
        status, data = self.imap.uid(
            "fetch",
            str(uid),
            "(BODY.PEEK[])"
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.fetch_raw.2', v0=f'{uid}')
            )

        for item in data:
            if isinstance(item, tuple):
                return item[1]

        raise RuntimeError(
            t('imap_client.fetch_raw.1', v0=f'{uid}')
        )

    def is_seen(self, uid):
        """
        IMAP上で既読かどうかを返す。

        True  = \\Seen あり
        False = \\Seen なし
        """

        status, data = self.imap.uid(
            "fetch",
            str(uid),
            "(FLAGS)",
        )

        if status != "OK":
            raise RuntimeError(
                t('imap_client.is_seen.2', v0=f'{uid}')
            )

        for item in data:
            if isinstance(item, bytes):
                text = item.decode(
                    "utf-8",
                    errors="replace",
                )

                if "FLAGS" in text:
                    return "\\Seen" in text

        raise RuntimeError(
            t('imap_client.is_seen.1', v0=f'{uid}')
        )

    def delete_uid(
        self,
        mailbox,
        expected_uidvalidity,
        uid,
    ):
        """
        指定UIDを可能な限り安全に削除する。

        UIDPLUS対応:
            UID EXPUNGEを使用。

        UIDPLUS非対応:
            通常EXPUNGEを使用するが、
            EXPUNGE直前に \\Deleted が
            対象UIDだけであることを確認する。

        注意:
            UIDPLUS非対応では、
            最終確認からEXPUNGEまでのごく短時間に
            他クライアントが別メールへ \\Deleted を
            付ける競合を完全には排除できない。
        """

        actual_uidvalidity = self.select_mailbox(
            mailbox,
            readonly=False,
        )

        try:
            if (
                str(actual_uidvalidity)
                != str(expected_uidvalidity)
            ):
                raise RuntimeError(
                    t('imap_client.delete_uid.1', v0=f'{expected_uidvalidity}', v1=f'{actual_uidvalidity}')
                )

            if not self.uid_exists(uid):
                return False

            capabilities = {
                cap.decode().upper()
                if isinstance(cap, bytes)
                else str(cap).upper()
                for cap in self.imap.capabilities
            }

            # -----------------------------------------
            # UIDPLUS対応サーバー
            # -----------------------------------------
            if "UIDPLUS" in capabilities:

                status, _ = self.imap.uid(
                    "store",
                    str(uid),
                    "+FLAGS.SILENT",
                    r"(\Deleted)",
                )

                if status != "OK":
                    raise RuntimeError(
                        t('imap_client.delete_uid.9', v0=f'{uid}')
                    )

                status, _ = self.imap.uid(
                    "EXPUNGE",
                    str(uid),
                )

                if status != "OK":
                    try:
                        self.imap.uid(
                            "store",
                            str(uid),
                            "-FLAGS.SILENT",
                            r"(\Deleted)",
                        )
                    except Exception:
                        pass

                    raise RuntimeError(
                        t('imap_client.delete_uid.10', v0=f'{uid}')
                    )

                if self.uid_exists(uid):
                    raise RuntimeError(
                        t('imap_client.delete_uid.11', v0=f'{uid}')
                    )

                return True

            # -----------------------------------------
            # UIDPLUS非対応サーバー
            # -----------------------------------------

            # まず既存の \Deleted がないことを確認
            status, data = self.imap.uid(
                "search",
                None,
                "DELETED",
            )

            if status != "OK":
                raise RuntimeError(
                    t('imap_client.delete_uid.2')
                )

            deleted_before = {
                int(value)
                for value in data[0].split()
            }

            if deleted_before:
                raise RuntimeError(
                    t('imap_client.delete_uid.3', v0=f'{sorted(deleted_before)}')
                )

            # 対象UIDだけに \Deleted を付ける
            status, _ = self.imap.uid(
                "store",
                str(uid),
                "+FLAGS.SILENT",
                r"(\Deleted)",
            )

            if status != "OK":
                raise RuntimeError(
                    t('imap_client.delete_uid.4', v0=f'{uid}')
                )

            # EXPUNGE直前にもう一度確認
            status, data = self.imap.uid(
                "search",
                None,
                "DELETED",
            )

            if status != "OK":
                try:
                    self.imap.uid(
                        "store",
                        str(uid),
                        "-FLAGS.SILENT",
                        r"(\Deleted)",
                    )
                except Exception:
                    pass

                raise RuntimeError(
                    t('imap_client.delete_uid.5')
                )

            deleted_after = {
                int(value)
                for value in data[0].split()
            }

            if deleted_after != {uid}:
                try:
                    self.imap.uid(
                        "store",
                        str(uid),
                        "-FLAGS.SILENT",
                        r"(\Deleted)",
                    )
                except Exception:
                    pass

                raise RuntimeError(
                    t('imap_client.delete_uid.6', v0=f'{sorted(deleted_after)}')
                )

            # この時点で \Deleted は対象UIDだけ
            status, _ = self.imap.expunge()

            if status != "OK":
                try:
                    if self.uid_exists(uid):
                        self.imap.uid(
                            "store",
                            str(uid),
                            "-FLAGS.SILENT",
                            r"(\Deleted)",
                        )
                except Exception:
                    pass

                raise RuntimeError(
                    t('imap_client.delete_uid.7', v0=f'{uid}')
                )

            # 本当に対象UIDが消えたか確認
            if self.uid_exists(uid):
                raise RuntimeError(
                    t('imap_client.delete_uid.8', v0=f'{uid}')
                )

            return True

        finally:
            # 後続処理が誤って書き込み可能状態を
            # 引き継がないようreadonlyへ戻す
            try:
                self.select_mailbox(
                    mailbox,
                    readonly=True,
                )
            except Exception:
                pass

    @staticmethod
    def get_summary(raw_email):
        msg = BytesParser(
            policy=policy.default
        ).parsebytes(raw_email)

        return {
            "from": str(
                msg.get("From", "")
            ),
            "subject": str(
                msg.get("Subject", "")
            ),
            "date": str(
                msg.get("Date", "")
            ),
        }
