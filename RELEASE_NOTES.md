# リリースノート

[English](RELEASE_NOTES.en.md) · 日本語

## v1.1.1（修正候補 / Unreleased）

- IMAPソケットの接続・応答待ちに30秒のタイムアウトを設定。STARTTLS、ログイン、以後のIMAPコマンドにも適用します。総処理時間ではなく通信の待機時間です。
- 接続失敗時はLOGOUTを試さずソケットを破棄し、既存の最大3回再試行（10秒・30秒待機）へ戻します。終了時のLOGOUT失敗後もローカル接続を閉じます。
- TCP/初期応答、STARTTLS、ログインの段階ログを日英で追加。DB・通知状態・TTL・削除条件は変更しません。
- 無応答サーバーの初期応答待ち・STARTTLS・コマンド応答待ち、失敗後の切断と再接続を検証します。OSのDNS名前解決やサーバーが少量ずつ応答し続ける場合まで含む総時間制限ではありません。

## v1.1.0 — 2026-10-14

rc.2を所有者のQNAP Container Stationで2026-10-01から継続運用し、2026-10-14に問題なしと報告され、正式版へ移行しました。全環境・全機能の網羅的受入試験を意味するものではありません。

- rc.2の動作コード・依存関係・DB schema 2を維持します。
- 送信者の表示名とアドレスをTitleへ、件名と任意の本文プレビューをBodyへ表示。全表示OFFの従来表示を維持し、UTF-8 JSONで日本語Titleを送ります。
- 表示名とプレビューを取り込み時に保存。再送で元メールを再取得せず、フィルタはアドレスだけで判定します。
- init通知抑止、完全一致送信元フィルタ、TTL、共通ロック、安全待機、単一/config方式を含みます。
- schema 0/1からbackup付きで移行し、既存通知状態・TTL起点を保持。更新時にinitは不要です。
- 日本語・英語の導入、保守、通知、Docker、支援資料と紹介・プライバシー・利用条件ページを整備し、相互切り替えを追加しました。

**v1.0からの動作変更:** init由来の通常通知は中断再開後も抑止します。通知有効時の設定不正は処理を停止・待機させます。DB作成は明示initのみです。TTL未指定/0は無期限の従来互換、設定例は15分です。

**更新:** 停止 → 設定/token/data等の一式backup → 完全タグ1.1.0のpull → 停止中status → up。rc.2と正式版は同じschemaです。[MAINTENANCE.md](MAINTENANCE.md)を参照してください。

**検証:** rc.2で100件のオフライン回帰テストとamd64/arm64 Docker公開CIが成功。正式版の文書変更後もオフラインテスト・lint・公開対象検査を実行します。公開工程の実結果はGitHub Actionsを参照してください。

**既知の制限:** API成功からDB確定までの重複可能性、UIDPLUSなしでの削除競合、復旧通知の独立再送なし、run終了0が全件成功を保証しない点は維持します。本文プレビュー等を含むDB・backupは非公開にします。

## v1.1.0-rc.2 — 2026-10-01

詳細通知とschema 2を追加。所有者の実機で件名欠落時の代替表示、本文先頭の空白整理が確認され、その後の継続運用で問題なしと報告されています。

## v1.1.0-rc.1 — 2026-10-01

通知フィルタ・TTL、init抑止、DB移行、共通ロック、起動待機、単一/config方式を追加。送信元フィルタは所有者の実機確認済みです。

## v1.0.0 - 2026-09-30

初回正式リリースです。`main` は開発最新版、GitHub Releaseとタグは正式版として管理します。

### 公開版の概要

外部IMAPメールをGmailへ取り込む既存実装を基に、日本語・英語の表示、設定検証、Docker常駐サービス、導入資料、回帰テストを整備しました。取り込み・通知・削除の状態遷移とDBスキーマは維持しています。MIT Licenseで公開しています。

### 動作に影響する変更

1. **STARTTLS証明書検証**: `ssl.create_default_context()` を明示。信頼されない証明書・ホスト名不一致は接続失敗になります。社内CAを使う環境では信頼設定が必要です。
2. **設定検証と引数検証**: 必須IMAP値の欠落、無効な真偽値/ポート/削除猶予、0以下のlatest/UID、不正日付は早期エラーです。ポート未指定は143。削除猶予は1日以上です。
3. **INI補間を無効化**: パスワードの `%` をそのまま扱います。旧設定に `%%` や `%(name)s` がある場合は、実際のリテラル値へ直してください。
4. **削除無効化**: `delete_after_import=false` なら、以前登録した削除期限があってもcleanupを実行しません。期限そのものは変更しません。
5. **OAuth生成**: Gmail単独だった生成スクリプトに `drive.file` を追加し、既存クライアントが求めるスコープと一致させました。既存tokenは自動で置き換えません。
6. **コンテナCMD**: 単発runから同梱の常駐ループへ変更。単発は `python -m app.main run` をコマンド指定します。日次cleanupは成功時のみmarkerを原子的に保存します。
7. **表示と言語**: 本体が生成する文言はja/en選択で変わります。保存済みDB状態名・ラベル・メールは変えません。例では明示した英語ラベル、未設定では既存互換の「添付退避」を使います。

Gmail取り込み後の通知失敗で再importしない処理、通常/fallbackのpending再開、最大3回の接続試行、障害通知抑制と復旧検出、UIDVALIDITY/UID/Deletedフラグによる削除ガードは維持しています。重複していた通知取得関数は実際に有効だった後側の定義を残しました。

### 検証状況

#### 自動検証

[公開ページ追加時のLinux CI](https://github.com/sosboy-san/gmail_bridge/actions/runs/36658743979)（コミット `12bbd50bd4983dde72437b54b5e230949b998a44`）は成功しています。最新の実行結果は [GitHub Actions](https://github.com/sosboy-san/gmail_bridge/actions) を参照してください。

- 依存関係整合性、Python構文・import、Ruff静的検査。
- Linux上で32件のオフラインテスト。通知だけの再送、pending再開、IMAP再試行、障害・復旧通知、UIDVALIDITY/UIDによる削除ガードなどを検証。
- Compose構文検証、Python 3.12 slimイメージのDockerビルド、イメージ内CLI起動。
- 完成イメージ内でタイムゾーン継承・東京午前0時のcleanup切替を2件追加検証。
- 公開ファイル一覧、翻訳カタログとプレースホルダ、秘密情報のパターン検査。

テストは架空データとモックを使用し、実サービスの認証情報は不要です。WindowsではLinux固有のflock・タイムゾーン検証がスキップされます。対応するLinux CIで検証します。

#### 実機確認とその範囲

所有者から、公開版を基にしたQNAP Container Station環境で初期化・起動ができたこと、および期限切れOAuthトークンの交換後に取り込みが再開したことが報告されています。これは所有者の環境での確認であり、全機能・全環境の受け入れ試験が完了したという意味ではありません。

導入先では次を確認してください。

- 通常取り込み、Drive fallback、本文・添付名・リンク・ラベル・既読状態。
- 通知失敗時に再importせず通知だけ再送すること。
- IMAP障害時の再試行・通知抑制・復旧通知。
- OAuthの継続更新、ファイル権限、保存容量。
- 専用の試験メールによるcleanupのdry-runと期限到来後削除。
- コンテナ・NAS再起動後の復帰と永続データの保持。

本番メールを対象にする前に、削除を無効にした設定で試験してください。

### コンテナ運用

常駐ループはDockerのCMDが起動する `app.service` に一本化しています。Composeで追加のループを指定しないでください。cleanup成功時のみ完了日を保存します。OSのtzdataを明示導入し、Composeの既定タイムゾーンはAsia/Tokyoです。DBの日時はUTCで記録します。

### 既知の制限

API成功とローカルDB確定の間のクラッシュによる重複可能性、UIDPLUS非対応での他クライアントとのEXPUNGE競合、復旧通知失敗時にその通知だけを再送しない点、個別取り込み失敗でもrunが終了コード0になる点は残っています。日次バックアップ保持は最新14ファイルであり、厳密な14暦日ではありません。詳細はREADMEとTROUBLESHOOTINGを参照してください。

### 配布と公開対象

`python tools/check_release.py --archive` は許可リストの公開ファイルだけをZIPへ含め、SHA-256を出力します。実設定、認証情報、実機用 `test/`、DB、ログ、バックアップ、作業用ファイルは対象外です。パターン検査は秘密情報の不存在を完全に保証するものではありません。[SECURITY.md](SECURITY.md) も参照してください。

### English

This release adds localization, configuration validation, a container service, documentation and offline regression tests while preserving the message/notification state machine and database schema. The linked Linux CI passed 32 tests, Compose validation, a real Docker build, CLI startup and two additional timezone checks inside the image.

The owner reported successful initialization/startup on QNAP Container Station and resumed imports after replacing an expired OAuth token. This is limited deployment evidence, not comprehensive acceptance testing. Verify import/fallback, notification retries, outage recovery, cleanup, persistent storage and restart behavior in your own environment. Linux-specific checks are skipped on Windows and covered by Linux CI.

Known limitations include possible duplicates between remote success and local commit, EXPUNGE races without UIDPLUS, no dedicated retry of failed recovery notifications, and a zero run exit code despite individual message failures. Production dependencies remain pinned. See the installation and troubleshooting guides before deployment.
