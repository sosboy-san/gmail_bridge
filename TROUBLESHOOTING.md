# トラブルシューティング / Troubleshooting

## 設定・起動

- `config.ini が見つかりません`: `/app/config.ini` のファイルマウントと作業ディレクトリを確認します。例をコピーして実値を入力してください。
- `Required configuration` / 「設定が必要」: 表示されたセクションとキーを埋めます。パスワードは引用符で囲まず、`%`をそのまま書きます。
- INI構文エラー: UTF-8、`[section]`、`key = value`を確認します。秘密情報の行を表示しない設計です。
- 権限エラー: token.jsonとdata/backups/logsはコンテナのUID/GIDから書き込み可能にします。ファイルマウント元を誤ってディレクトリにしないでください。
- Windowsでrunが使えない: 二重起動防止にLinuxのflockを使います。Linuxコンテナで動かしてください。
- 既にrun実行中: 別プロセスの終了を待ちます。動いている間にロックファイルを消さないでください。ロックはプロセス終了で自動解放されます。

## IMAP

- 3回失敗: DNS、経路、ポート、STARTTLS対応、ユーザー名、パスワード、接続制限を確認します。既定の待機は10秒・30秒です。次のrunで再試行します。
- TLS証明書エラー: 本公開版は証明書とホスト名を検証します。正しいサーバー証明書を利用し、社内CAならそのCAをコンテナで信頼させます。専用CA bundleを読み取り専用でマウントし `SSL_CERT_FILE` で指定する方法もあります。検証無効化で回避しないでください。
- 993番で接続失敗: この実装はSTARTTLS専用です。サーバーが対応するSTARTTLSポートを指定します。
- 未初期化: v1.1のWAITING_FOR_INIT待機中にConsoleから明示initします。更新時に出た場合は先にマウント元と既存DBを確認します。
- UIDVALIDITY変更: mailboxの再作成・サーバー移行などを疑います。既存DBのUID対応が信頼できなくなったので停止しています。Gmailと元IMAPの保存状況を照合し、バックアップを取ってから再初期化方法を決めます。値だけをDBへ書き換えて回避しないでください。

## Gmail / Drive / OAuth

- `invalid_grant`や期限切れ: 同意画面のTesting状態、取り消した権限、アカウント制限、時計を確認し、PCで再認証します。新tokenは常駐停止中に配置します。
- Drive権限不足: 初期のmake_token.pyはGmailスコープだけでした。公開版で再認証し `drive.file` も許可してください。Gmail APIだけでなくDrive APIも有効にします。
- 添付拒否以外のエラー: 認証、容量、割当制限などは自動でDrive fallbackへ切り替えません。原因を直すとretry対象が次回処理されます。
- Driveリンクを開けない: 正しいGoogleアカウントと共有権限を確認します。本アプリはリンクを一般公開しません。
- 添付のない拒否メールや不完全なヘッダ: fallback対象添付を抽出できない場合や必須ヘッダ検証に失敗した場合は、完了扱いにせずエラーになります。
- Gmailで受信トレイに見えない: 出所ラベル、すべてのメール、迷惑メールを確認します。SPAM解除オプションはINBOXを追加する機能ではありません。

## 通知

Gmail保存後に通知が失敗しても、取り込み状態をretryへ戻しません。通知だけpendingに残ります。v1.1ではTTL内のみ再試行し、期限切れはexpired、除外はsuppressedになります。ntfyのURL、topic、token、アクセス制御、スマートフォンの購読を確認し、次のrunを待ちます。新着がなくてもpending通知を処理しますが、**IMAP接続・UIDVALIDITY確認より前には通知再送しない**ため、IMAP障害中はメール通知再送も待機します。

通知を無効にしている間に取り込んだメールはキューに積みません。過去に積んだpendingは残るので、有効に戻すと最新TTL・フィルタで再判定します。v1.1ではinit由来の通常通知を生成せず、中断後run再開でも抑止します。旧DBの既存通知は由来を推測して変更しません。

障害通知は成功後に繰り返し送りません。失敗した障害通知は次回接続失敗時にも再試行します。既存実装では、**復旧通知の送信に失敗しても接続状態はokへ戻り、その復旧通知自体は再送しません**。通常メールのpending通知とは別の仕様です。

## cleanup・ログ・バックアップ

- 削除が動かない: delete_after_import、記録済みの期限、取り込みの完了状態、UIDVALIDITYを確認します。falseは既存予定も停止します。有効化しても過去に期限なしで取り込んだレコードへ期限を追加しません。
- 「UIDが存在しません」: 本アプリでは勝手に削除済み扱いにせず、再試行候補として残します。他クライアントの削除・移動を確認してください。
- 他の `\Deleted` を検出: UIDPLUS非対応時の安全停止です。他クライアントの動作を確認し、無関係なメールをEXPUNGEしないようにしてください。
- cleanup失敗: 非ゼロ終了のため日次完了日は更新しません。次周期でも再試行します。
- 既に今日のcleanup成功済み: 設定を有効化しても通常は次の日に処理します。すぐ確認したい場合は常駐停止後に手動で `cleanup --dry-run` から実行します。
- ログ: `logs/gmail_bridge_YYYY-MM-DD.log` はrunのみです。init、cleanup、常駐ループ自体の出力はコンテナログ側を確認します。件名・差出人・ファイル名・ID・エラー情報を含むので公開しないでください。
- バックアップ: `backups/db/state_YYYY-MM-DD.db` はSQLite backup APIで作成しintegrity_check後に確定します。暦日14日ではなく最新14ファイルを保持します。

runの終了コード0は、すべてのメールの成功を保証しません。既存挙動として個別メールの失敗件数を出力して継続し、接続失敗も通知後にreturnします。コンテナが稼働中であることだけで健全性を判断せず、ログのfailed件数、state、実際の新着取り込みを確認します。

v1.1のCONFIG_ERROR / DB_ERROR / DB_MIGRATION_ERROR、OAuth欠落、backup・rollbackの操作は [MAINTENANCE.md](MAINTENANCE.md) を参照してください。空・破損・未知DBはinit待ちではなく異常です。

## English

Check mounts, `/app` working directory, required INI fields, UTF-8, and file permissions first. Tokens and runtime directories must be writable by the container user. Windows needs a Linux container for run's flock. Do not remove an active lock file.

IMAP uses STARTTLS with certificate verification, not implicit TLS on port 993. Fix certificates/trust or mount an appropriate CA bundle rather than disabling verification. Connection failure triggers three attempts; the next run retries. A changed UIDVALIDITY intentionally stops processing. Reconcile source mail and Gmail before any reinitialization; never just overwrite the recorded UIDVALIDITY.

For OAuth failures, check consent-screen Testing expiry, revoked access, organization policies, and clock. Generate a new token on a trusted desktop and replace it while the service is stopped. Drive fallback requires both APIs enabled and a token containing `drive.file`. Only attachment-related Gmail rejection triggers fallback; other API failures remain retryable. Drive links require the correct account and permissions.

Notification failures keep imported mail finalized and leave only the notification pending. Retry occurs during a later run, even with no new mail, but only after IMAP connection and UIDVALIDITY checks succeed. Outage alerts are suppressed after successful delivery. The existing recovery path records `ok` even when the recovery alert fails; recovery alerts are not independently queued. Mail imported while notifications are disabled does not create notifications; older pending notifications remain.

Cleanup requires enabled deletion and an expired recorded deadline. Disabling deletion also suspends existing schedules. Missing UIDs are deliberately left unconfirmed. On non-UIDPLUS servers, unrelated Deleted flags abort EXPUNGE. Failed cleanup never advances the daily marker. Inspect a dry-run while the service is stopped before retrying manually.

Run logs contain mail metadata and must remain private; other commands appear in container logs. Backups retain the latest 14 daily files, not strictly 14 calendar days. A zero run exit code or a running container does not guarantee all messages succeeded: inspect failure counts and state. DB restore or remote-success/local-commit crashes can still cause duplicate import.
