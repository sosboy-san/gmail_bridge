import hashlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import make_msgid
from pathlib import Path

from app.i18n import t


def parse_message(raw_email):
    return BytesParser(
        policy=policy.default
    ).parsebytes(raw_email)


def get_original_message_id(raw_email):
    msg = parse_message(raw_email)

    value = msg.get("Message-ID")

    if value:
        return str(value)

    return None


def safe_filename(filename, index):
    """
    Drive/一時ファイル用のファイル名。

    元の添付ファイル名は可能な限り維持する。
    """

    if not filename:
        return f"attachment-{index}"

    filename = str(filename)

    # パスとして解釈されないようにする
    filename = filename.replace("/", "_")
    filename = filename.replace("\\", "_")

    return filename


def extract_attachments(raw_email):
    """
    添付ファイルを抽出する。

    戻り値:
    [
        {
            "index": 1,
            "filename": "...zip",
            "content_type": "application/zip",
            "data": b"...",
            "sha256": "..."
        }
    ]
    """

    msg = parse_message(raw_email)

    attachments = []
    index = 0

    for part in msg.walk():

        if part.is_multipart():
            continue

        disposition = part.get_content_disposition()
        filename = part.get_filename()

        # attachment指定、またはfilename付きの
        # MIME partを添付として扱う
        if (
            disposition != "attachment"
            and not filename
        ):
            continue

        index += 1

        data = part.get_payload(
            decode=True
        )

        if data is None:
            data = b""

        filename = safe_filename(
            filename,
            index
        )

        attachments.append({
            "index": index,
            "filename": filename,
            "content_type":
                part.get_content_type(),
            "data": data,
            "sha256":
                hashlib.sha256(data).hexdigest(),
        })

    return attachments


def save_attachment_temp(
    attachment,
    temp_dir,
):
    """
    Driveへアップロードするため
    添付を一時ファイルへ保存。
    """

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = attachment["filename"]

    # 同名ファイル衝突防止
    temp_name = (
        f"{attachment['index']:02d}_"
        f"{filename}"
    )

    path = temp_dir / temp_name

    with open(path, "wb") as f:
        f.write(
            attachment["data"]
        )

    return path


def _copy_headers(
    source,
    target,
    original_message_id,
):
    """
    fallbackメールのヘッダを構築する。

    From / To / Cc / Reply-To / Subject / Date は
    emailパッケージで解析済みの値から再構築する。

    MIME関連ヘッダやDKIM署名など、
    メール加工後には無効になるヘッダは引き継がない。
    """

    # -------------------------------------------------
    # まず通常ヘッダをコピー
    #
    # 主要ヘッダは後で解析済み値から設定するので
    # ここでは除外する。
    # -------------------------------------------------

    important_headers = {
        "from",
        "to",
        "cc",
        "reply-to",
        "subject",
        "date",
    }

    skip_headers = {
        "content-type",
        "content-transfer-encoding",
        "mime-version",
        "content-disposition",
        "message-id",

        # 本文を変更するので元署名は無効
        "dkim-signature",

        # Gmailへの再import時には不要
        "return-path",
        
        # fallback版を元メールのスレッドへ
        # 強制的に関連付けない
        "in-reply-to",
        "references",
    }

    for name, value in source.raw_items():

        lower_name = name.lower()

        if lower_name in important_headers:
            continue

        if lower_name in skip_headers:
            continue

        try:
            target[name] = value
        except (ValueError, TypeError):
            # 再構築できない補助ヘッダは
            # fallbackメールでは無視する
            pass

    # -------------------------------------------------
    # 主要ヘッダ
    #
    # source.get() はpolicy.defaultで解析された
    # ヘッダオブジェクトを返す。
    # str() にすることでUnicodeを含めて
    # 新しいEmailMessageへ安全に設定する。
    # -------------------------------------------------

    for header_name in (
        "From",
        "To",
        "Cc",
        "Reply-To",
        "Subject",
        "Date",
    ):
        value = source.get(header_name)

        if value is None:
            continue

        value = str(value).strip()

        if not value:
            continue

        try:
            target[header_name] = value
        except (ValueError, TypeError) as e:
            raise RuntimeError(
                t('mime_fallback._copy_headers.1', v0=f'{header_name}', v1=f'{e}')
            )

    # -------------------------------------------------
    # Message-ID
    #
    # fallback版は内容を変更しているので
    # 元Message-IDをそのまま使わない。
    # -------------------------------------------------

    target["Message-ID"] = make_msgid(
        idstring="gmail-imap-bridge"
    )

    target[
        "X-Gmail-Bridge-Fallback"
    ] = "drive"

    if original_message_id:
        target[
            "X-Gmail-Bridge-Original-Message-ID"
        ] = original_message_id


def _extract_body(msg):
    """
    元メールから本文を取得。

    text/plain と text/html を
    可能な限り保持する。
    """

    plain = None
    html = None

    if not msg.is_multipart():

        content_type = msg.get_content_type()

        try:
            content = msg.get_content()
        except Exception:
            content = ""

        if content_type == "text/html":
            html = str(content)
        else:
            plain = str(content)

        return plain, html

    for part in msg.walk():

        if part.is_multipart():
            continue

        if (
            part.get_content_disposition()
            == "attachment"
        ):
            continue

        # filename付きpartも添付扱い
        if part.get_filename():
            continue

        content_type = (
            part.get_content_type()
        )

        if content_type not in (
            "text/plain",
            "text/html",
        ):
            continue

        try:
            content = part.get_content()
        except Exception:
            continue

        if (
            content_type == "text/plain"
            and plain is None
        ):
            plain = str(content)

        elif (
            content_type == "text/html"
            and html is None
        ):
            html = str(content)

    return plain, html


def _make_plain_notice(drive_files):
    lines = [
        "",
        "",
        "----------------------------------------",
        t('mime_fallback._make_plain_notice.1'),
        "",
        t('mime_fallback._make_plain_notice.2'),
        t('mime_fallback._make_plain_notice.3'),
        "",
    ]

    for item in drive_files:
        lines.append(
            t('mime_fallback._make_plain_notice.4', v0=f"{item['name']}")
        )
        lines.append(
            f"Drive: {item['webViewLink']}"
        )
        lines.append("")

    lines.extend([
        t('mime_fallback._make_plain_notice.5'),
        "----------------------------------------",
    ])

    return "\n".join(lines)


def _escape_html(text):
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _make_html_notice(drive_files):
    rows = []

    for item in drive_files:
        name = _escape_html(
            item["name"]
        )

        link = _escape_html(
            item["webViewLink"]
        )

        rows.append(
            t('mime_fallback._make_html_notice.2', v0=f'{name}', v1=f'{link}')
        )

    items = "\n".join(rows)

    return t('mime_fallback._make_html_notice.1', v0=f'{items}')


def build_fallback_message(
    raw_email,
    drive_files,
):
    """
    添付を持たないGmail用コピーを作る。

    元本文 + Driveリンク。
    """

    source = parse_message(
        raw_email
    )

    original_message_id = (
        str(source.get("Message-ID"))
        if source.get("Message-ID")
        else None
    )

    target = EmailMessage(
        policy=policy.SMTP
    )

    _copy_headers(
        source,
        target,
        original_message_id,
    )

    plain, html = _extract_body(
        source
    )

    plain_notice = _make_plain_notice(
        drive_files
    )

    html_notice = _make_html_notice(
        drive_files
    )

    if plain is None and html is None:
        target.set_content(
            plain_notice
        )

    elif plain is not None:
        target.set_content(
            plain + plain_notice
        )

        if html is not None:
            target.add_alternative(
                html + html_notice,
                subtype="html"
            )

    else:
        # HTML本文しかない場合でも
        # text/plain版を用意する
        target.set_content(
            t('mime_fallback.build_fallback_message.1')
            + plain_notice
        )

        target.add_alternative(
            html + html_notice,
            subtype="html"
        )

    return target.as_bytes(
        policy=policy.SMTP
    )
    
def validate_fallback_message(raw_email):
    """
    Gmailへ送る前のfallbackメールを検証する。
    """

    msg = BytesParser(
        policy=policy.default
    ).parsebytes(raw_email)

    errors = []

    if not msg.get("From"):
        errors.append(t('mime_fallback.validate_fallback_message.1'))

    if not msg.get("Subject"):
        errors.append(t('mime_fallback.validate_fallback_message.2'))

    if not msg.get("Date"):
        errors.append(t('mime_fallback.validate_fallback_message.3'))

    if not msg.get("Message-ID"):
        errors.append(t('mime_fallback.validate_fallback_message.4'))

    if (
        msg.get("X-Gmail-Bridge-Fallback")
        != "drive"
    ):
        errors.append(
            t('mime_fallback.validate_fallback_message.5')
        )

    if errors:
        raise RuntimeError(
            t('mime_fallback.validate_fallback_message.6')
            + ", ".join(errors)
        )

    return {
        "from": str(
            msg.get("From", "")
        ),
        "to": str(
            msg.get("To", "")
        ),
        "cc": str(
            msg.get("Cc", "")
        ),
        "date": str(
            msg.get("Date", "")
        ),
        "subject": str(
            msg.get("Subject", "")
        ),
        "message_id": str(
            msg.get("Message-ID", "")
        ),
    }    