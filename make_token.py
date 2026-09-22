"""Run on a trusted desktop with a browser; transfer token.json privately."""

import argparse
import os
import sys
from pathlib import Path

from app.config import configure_language
from app.i18n import argparse_text, available_languages, t
from app.oauth import SCOPES


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _ = pre.parse_known_args()
    configure_language(known.lang)
    argparse._ = argparse_text
    parser = argparse.ArgumentParser(description=t("oauth.description"))
    parser.add_argument("--lang", choices=available_languages(), help=t("cli.language"))
    parser.add_argument("--credentials", default="credentials.json", help=t("oauth.credentials"))
    parser.add_argument("--token", default="token.json", help=t("oauth.token"))
    parser.add_argument("--force", action="store_true", help=t("oauth.force"))
    args = parser.parse_args()
    token = Path(args.token)
    if token.exists() and not args.force:
        parser.error(t("oauth.exists"))
    if not Path(args.credentials).is_file():
        parser.error(t("oauth.missing"))
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if args.force else os.O_EXCL)
    descriptor = os.open(token, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(creds.to_json())
    print(t("oauth.created", path=token))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(t("oauth.failed"), file=sys.stderr)
        sys.exit(1)
