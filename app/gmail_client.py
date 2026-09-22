import base64

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.i18n import t
from app.oauth import SCOPES


class InvalidAttachmentError(Exception):
    """
    Gmailが添付ファイルを理由に
    メールを拒否した場合だけ発生させる例外。

    この例外を受けたmain側は
    Google Drive fallbackへ進む。
    """
    pass


class GmailClient:

    def __init__(self, token_file):
        self.token_file = token_file
        self.service = None

    def connect(self):
        creds = Credentials.from_authorized_user_file(
            self.token_file,
            SCOPES
        )

        if creds.expired and creds.refresh_token:
            print(t('gmail_client.connect.1'))
            creds.refresh(Request())

            with open(
                self.token_file,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(creds.to_json())

        if not creds.valid:
            raise RuntimeError(
                t('gmail_client.connect.2')
            )

        self.service = build(
            "gmail",
            "v1",
            credentials=creds,
            cache_discovery=False,
        )

    def import_message(self, raw_email):
        """
        RFC822原文をそのままGmailへimport。

        Invalid attachment の場合だけ
        InvalidAttachmentErrorへ変換する。
        """

        raw = base64.urlsafe_b64encode(
            raw_email
        ).decode("ascii")

        try:
            result = (
                self.service
                .users()
                .messages()
                .import_(
                    userId="me",
                    body={
                        "raw": raw
                    },
                    internalDateSource="dateHeader",
                )
                .execute()
            )

        except HttpError as e:

            if self._is_invalid_attachment(e):
                raise InvalidAttachmentError(
                    t('gmail_client.import_message.1')
                ) from e

            raise

        return result["id"]

    @staticmethod
    def _is_invalid_attachment(error):
        """
        Gmail APIのHTTP 400から
        Invalid attachment を判定。

        他の400エラーを誤って
        Drive fallbackへ送らないため、
        添付関連の場合だけTrue。
        """

        if getattr(error, "resp", None) is None:
            return False

        if error.resp.status != 400:
            return False

        content = getattr(
            error,
            "content",
            b""
        )

        if isinstance(content, bytes):
            text = content.decode(
                "utf-8",
                errors="replace"
            )
        else:
            text = str(content)

        text_lower = text.lower()

        return (
            "invalid attachment" in text_lower
            or (
                "invalidargument" in text_lower
                and "attachment" in text_lower
            )
        )

    def get_or_create_label(self, label_name):
        """
        Gmailラベルを取得。
        存在しなければ作成。
        """

        if not label_name:
            raise ValueError(
                t('gmail_client.get_or_create_label.2')
            )

        result = (
            self.service
            .users()
            .labels()
            .list(
                userId="me"
            )
            .execute()
        )

        for label in result.get(
            "labels",
            []
        ):
            if label.get("name") == label_name:
                return label["id"]

        print(
            t('gmail_client.get_or_create_label.1', v0=f'{label_name}')
        )

        created = (
            self.service
            .users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility":
                        "labelShow",
                    "messageListVisibility":
                        "show",
                },
            )
            .execute()
        )

        return created["id"]

    def add_label(
        self,
        gmail_message_id,
        label_id,
    ):
        """
        Gmailメッセージへラベル付与。
        """

        (
            self.service
            .users()
            .messages()
            .modify(
                userId="me",
                id=gmail_message_id,
                body={
                    "addLabelIds": [
                        label_id
                    ]
                },
            )
            .execute()
        )

    def mark_unread(
        self,
        gmail_message_id,
    ):
        self.add_label(
            gmail_message_id,
            "UNREAD",
        )

    def apply_source_label(
        self,
        gmail_message_id,
        label_name,
    ):
        """
        出所ラベルを必ず付与。
        """

        label_id = self.get_or_create_label(
            label_name
        )

        self.add_label(
            gmail_message_id,
            label_id
        )

        return label_id

    def remove_label(
        self,
        gmail_message_id,
        label_id,
    ):
        """
        Gmailメッセージからラベルを削除。
        """

        (
            self.service
            .users()
            .messages()
            .modify(
                userId="me",
                id=gmail_message_id,
                body={
                    "removeLabelIds": [
                        label_id
                    ]
                },
            )
            .execute()
        )