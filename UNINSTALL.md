# アンインストール / Uninstall

## まず停止する

```bash
docker compose down
```

Container StationのUIで管理している場合は該当アプリケーション／コンテナを停止・削除します。別途作ったcronやタスクがある場合は無効にします。Compose例のbind mountは、コンテナを削除してもホスト側に残ります。

## データを残す場合

新方式では専用configフォルダ全体（通知フィルタ、data内cleanup記録、backups、logsを含む）を保管します。再導入する可能性があるなら、`config.ini`、`token.json`、`credentials.json`、`data/`、`backups/` を非公開の場所に保持します。ログが必要なら `logs/` も保管します。トークン・メール情報を含むので、保管先のアクセス権を制限してください。

SQLite状態を失うと、再導入時にGmailへの取り込み済み判定ができず、重複が起こり得ます。新着だけにする再初期化は `init --from-now` ですが、未取り込みの既存メールも無視する操作なので、対象を確認してから実行します。

## 完全に削除する場合

1. [Googleアカウントの接続済みアプリ](https://myaccount.google.com/connections) で、このOAuthアプリのアクセス権を取り消します。不要になった自分のOAuthクライアントもCloud Consoleで削除できます。他の用途と共有しているプロジェクト全体を誤って削除しないでください。
2. ntfy側の専用トークン、topicの購読、必要ならアクセス設定を削除します。
3. ホスト上のこのBridge専用の設定・OAuthファイル・data・backups・logsを、パスを確認して削除します。NASのスナップショットや別バックアップも残る場合があります。
4. 不要な `gmail-bridge:local` イメージと公開用コードを削除します。他アプリのDocker volumeやイメージを一括削除する必要はありません。

**この手順は、Gmailへ取り込んだメールやDrive上の添付を削除しません。** 必要ならGoogle側で個別に確認して削除してください。Drive添付を削除すると、fallbackメールのリンク先が失われます。cleanupで元IMAPから削除済みのメールは、このアプリのアンインストールでは復元されません。

## English

Run `docker compose down`, or stop/remove the application in Container Station. Disable any separate scheduler. Bind-mounted host files remain after container removal.

For later reinstallation, privately retain config, credentials, token, the complete state directory, and backups. Losing the database loses deduplication history and can cause duplicate imports. `init --from-now` deliberately ignores all currently existing mail, including mail not yet imported.

For complete removal, revoke this OAuth application's access from your Google account, remove its dedicated OAuth client if no longer needed, revoke dedicated ntfy tokens/subscriptions, and delete only the verified Bridge-specific host paths and image. Consider NAS snapshots and external backups separately.

Imported Gmail messages and Drive attachments are not removed automatically. Deleting Drive files breaks fallback links. Source mail already deleted by cleanup is not restored by uninstalling.
