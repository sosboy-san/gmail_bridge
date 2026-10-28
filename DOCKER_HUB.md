# Gmail Bridge

[English](#english) · [日本語](#日本語)

## English

Self-hosted IMAP-to-Gmail bridge. Import company/domain mail into your own Gmail account and use Gmail filters, labels and search. Optional Google Drive attachment fallback and ntfy notifications.

**Stable: 1.1.1** · linux/amd64 and linux/arm64 · MIT

```bash
docker pull sosboy/gmail-bridge:1.1.1
```

Pulling the image is only the first step. Provide your own Google Cloud project and desktop OAuth token, configure STARTTLS IMAP, and mount persistent storage. Use [the English installation guide](https://github.com/sosboy-san/gmail_bridge/blob/main/INSTALL.en.md) and docker-compose.config.image.example.yml with BRIDGE_VERSION=1.1.1. Mount one writable host folder at /config and set BRIDGE_CONFIG_DIR=/config. Start, wait for WAITING_FOR_INIT, then explicitly initialize according to your choice of existing-mail handling. No automatic init occurs.

Existing deployments: stop → complete backup → pull → stopped status → up. **Never repeat init during upgrades.** [Upgrade/recovery guide](https://github.com/sosboy-san/gmail_bridge/blob/main/MAINTENANCE.en.md).

Set [general] language=en in config.ini for English runtime messages. Exact versions are recommended. Stable publishes 1.1.1 / 1.1 / 1 / latest; RC publishes only its exact tag. Old rc.1/rc.2 tags remain unchanged.

This is one-way import, not synchronization or an outbound mail service. STARTTLS only (normally port 143), one mailbox/account per state directory. Source cleanup is disabled by default. Drive links stay access-controlled. Notifications may send sender/subject/preview when explicitly enabled; protect ntfy topics. Keep config, tokens, DB, backups and logs private. Remote-success/local-state crash windows can still produce duplicates.

[Source and overview](https://github.com/sosboy-san/gmail_bridge/blob/main/README.en.md) · [Notifications](https://github.com/sosboy-san/gmail_bridge/blob/main/NOTIFICATIONS.en.md) · [Release notes](https://github.com/sosboy-san/gmail_bridge/blob/main/RELEASE_NOTES.en.md)

## 日本語

会社・独自ドメインのIMAPメールを、自分のGmailへ取り込むセルフホスト型Bridgeです。Gmailのフィルタ・ラベル・検索を使えます。添付拒否時のGoogle Drive退避とntfy通知に対応します。

**正式版: 1.1.1** · linux/amd64 / linux/arm64 · MIT

```bash
docker pull sosboy/gmail-bridge:1.1.1
```

取得だけでは使えません。自身のGoogle CloudプロジェクトとPCで作成したOAuth token、IMAP設定、永続保存先が必要です。[日本語の導入手順](https://github.com/sosboy-san/gmail_bridge/blob/main/INSTALL.md)に従い、単一/config方式のComposeとBRIDGE_VERSION=1.1.1を使います。起動後WAITING_FOR_INITを確認し、過去メールの扱いを選んでConsoleから明示initします。

既存環境の更新は、停止 → 一式backup → pull → 停止中status → upです。**更新でinitは実行しません。** [更新・復旧](https://github.com/sosboy-san/gmail_bridge/blob/main/MAINTENANCE.md)。rc.2から正式版も同じ手順です。

日本語表示は[general] language=ja。完全タグでの運用を推奨します。正式版は1.1.1 / 1.1 / 1 / latest、RCは完全タグだけです。

双方向同期・外部アドレスからの送信機能ではありません。STARTTLS専用、1設定につき1アカウント・1フォルダです。元メール削除は初期状態で無効。Driveを一般公開しません。通知表示を有効にすると送信者・件名・プレビューがntfyへ送られます。topicの保護と、設定/token/DB/backup/logsの非公開管理が必要です。API成功とDB確定の間には重複の可能性が残ります。

[概要](https://github.com/sosboy-san/gmail_bridge) · [通知](https://github.com/sosboy-san/gmail_bridge/blob/main/NOTIFICATIONS.md) · [リリースノート](https://github.com/sosboy-san/gmail_bridge/blob/main/RELEASE_NOTES.md)
