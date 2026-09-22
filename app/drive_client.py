from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.i18n import t
from app.oauth import SCOPES


class DriveClient:

    def __init__(self, token_file):
        self.token_file = token_file
        self.service = None

    def connect(self):
        creds = Credentials.from_authorized_user_file(
            self.token_file,
            SCOPES
        )

        if creds.expired and creds.refresh_token:
            print(t('drive_client.connect.1'))
            creds.refresh(Request())

            with open(
                self.token_file,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(creds.to_json())

        if not creds.valid:
            raise RuntimeError(
                t('drive_client.connect.2')
            )

        self.service = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        )

    def get_or_create_folder(
        self,
        folder_name,
        parent_id=None,
    ):
        """
        アプリが利用するDriveフォルダを取得。
        見つからなければ作成する。

        共有設定は変更しないため非公開のまま。
        """

        escaped_name = folder_name.replace(
            "'",
            "\\'"
        )

        query_parts = [
            f"name = '{escaped_name}'",
            "mimeType = "
            "'application/vnd.google-apps.folder'",
            "trashed = false",
        ]

        if parent_id:
            query_parts.append(
                f"'{parent_id}' in parents"
            )

        query = " and ".join(query_parts)

        result = (
            self.service
            .files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name)",
                pageSize=10,
            )
            .execute()
        )

        files = result.get("files", [])

        if files:
            return files[0]["id"]

        print(
            t('drive_client.get_or_create_folder.1', v0=f'{folder_name}')
        )

        metadata = {
            "name": folder_name,
            "mimeType":
                "application/vnd.google-apps.folder",
        }

        if parent_id:
            metadata["parents"] = [
                parent_id
            ]

        created = (
            self.service
            .files()
            .create(
                body=metadata,
                fields="id,name",
            )
            .execute()
        )

        return created["id"]

    def upload_file(
        self,
        file_path,
        folder_id=None,
        drive_name=None,
        mimetype=None,
    ):
        """
        ローカルファイルをDriveへ保存。

        戻り値:
        {
            "id": ...,
            "name": ...,
            "webViewLink": ...
        }
        """

        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(
                t('drive_client.upload_file.1', v0=f'{file_path}')
            )

        if drive_name is None:
            drive_name = file_path.name

        metadata = {
            "name": drive_name
        }

        if folder_id:
            metadata["parents"] = [
                folder_id
            ]

        media = MediaFileUpload(
            str(file_path),
            mimetype=mimetype,
            resumable=True,
        )

        result = (
            self.service
            .files()
            .create(
                body=metadata,
                media_body=media,
                fields=(
                    "id,"
                    "name,"
                    "webViewLink,"
                    "size"
                ),
            )
            .execute()
        )

        if not result.get("webViewLink"):
            # 念のため作成後に再取得
            result = (
                self.service
                .files()
                .get(
                    fileId=result["id"],
                    fields=(
                        "id,"
                        "name,"
                        "webViewLink,"
                        "size"
                    ),
                )
                .execute()
            )

        return result