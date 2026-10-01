# リリースノート / Release notes

## v1.1.0（開発中・未公開 / Unreleased）

- **initの通常メール通知を停止**: `--all / --latest / --since / --uid` による取り込みは通常ntfy通知を生成しません。選択UIDのinit由来を保存し、中断後にrunで再開しても抑止します。v1.0.0からの意図的な動作変更です。既存DBの移行でinitを実行することはありません。
- **通知内容と対象を選択**: 送信元アドレス・件名は個別に表示可能（既定false）。off / allowlist / blocklist / combinedのモードで、アドレス・ドメインの完全一致を使用します。combinedでは除外優先。正規表現やサブドメインの自動一致はありません。
- **通知の鮮度**: `ttl_minutes` 未指定／0は従来互換の無期限再試行。新しい設定例では15分を推奨値として明示します。TTLはGmail API成功時に保存する専用UTC時刻から計算し、通知はsent / suppressed / expiredから復活しません。
- **DBと常駐運用**: 専用バックアップ付きのトランザクション移行、共通ロック、明示的なinitのみのDB作成、安全待機・設定修正後の復帰を追加。空・破損・未知のDBは異常として停止します。
- **設定エラー**: 通知が有効な場合の無効なprovider / topic / URLや、有効な送信元フィルタのファイル不正もサービスの待機／停止対象です。通知だけに異常を閉じ込めて取り込みを継続する旧挙動からの変更です。無効な通知／offのフィルタではリストファイルを読みません。
- **保存先**: `BRIDGE_CONFIG_DIR` 指定時はその配下だけを使用し、旧パスへfallbackしません。未指定時は従来方式です。

- **配布・運用資料**: 旧個別マウントを維持し、v1.1向け単一/configのbuild/pull用Composeを追加。新方式はバージョン明示必須。定常運用で不要なcredentialsマウントを削除。初回安全待機→Console init→自動復帰、更新前一式backup、migration、rollback、通知・障害対応を日本語資料へ反映しました。
- **RC配布準備**: vMAJOR.MINOR.PATCH-rc.Nを公開ワークフローで受け付け、RCは完全タグのみ、正式版のlatest/major/minorは更新しません。v1.1.0-rc.1は未作成・未公開です。
- **Phase 5検証**: 全94件のオフラインテスト、lint、公開前チェック、4種類のCompose構造の静的確認を実施。DockerなしのためDocker compose config・build・実動作は未検証。環境へのDocker導入は行っていません。英語資料の全面整備は仕様確定後に実施します。

**Validation status:** Phase 5 Compose and Japanese installation/upgrade/maintenance documentation are complete. Static/offline validation only; Docker/QNAP acceptance tests and the complete English documentation revision remain pending. No v1.1.0 tag, GitHub Release or Docker Hub image has been published.

**Behavior changes for existing users:** init imports no longer create ordinary ntfy notifications, including messages later resumed by run. Notification-specific configuration errors now stop/defer service operations when that feature is enabled. Database creation is reserved for explicit init. These changes are intentional; schema migration never performs init.

**Notification compatibility:** sender/subject display defaults to false and filtering defaults to off. An omitted `ttl_minutes` or explicit zero preserves unlimited retries; the new example recommends 15 minutes. Exact address/domain rules are case insensitive, combined mode gives block rules priority, and subdomains must be listed explicitly. Operational outage/recovery alerts remain separate from ordinary sender filters and TTL; invalid current configuration blocks sending either kind of alert.

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
