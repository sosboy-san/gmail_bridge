# 公開用整理の記録

## 方針

実運用済みのコピーを元に、取り込み・通知・削除の状態遷移とDBスキーマを維持して公開用の整備を行いました。本番NASには接続していません。初回ローカル整理後、所有者が作成したPrivateリポジトリへGitHub連携APIでコミットとmainブランチへの反映を行い、GitHub Actionsを確認しました。公開状態は変更していません。

## 変更ファイル

| ファイル | 変更内容 |
| --- | --- |
| app/main.py | 文言の翻訳参照、設定ローダー分離、重複通知判定の統一、未使用import除去、引数検証、Windowsでのhelp/status、削除無効設定の尊重 |
| app/imap_client.py | 表示の翻訳参照、STARTTLS証明書検証の明示。取得・削除フローは維持 |
| app/gmail_client.py / app/drive_client.py | 表示の翻訳参照、OAuthスコープ定義の共通化 |
| app/mime_fallback.py | 案内・検証エラーの翻訳参照、未使用import除去。MIME組み立てフローは維持 |
| app/notification_service.py / app/ntfy_client.py | 通知本文・診断の翻訳参照。独立した通知状態を維持 |
| app/state.py | 表示の翻訳参照、重複importと上書きされていた旧get_pending_notifications定義の除去、バックアップ保持のコメント修正 |
| app/config.py（新規） | UTF-8 INI、必須値と型の確認、秘密値を含めない設定エラー、言語選択 |
| app/i18n.py / app/locales/ja.json / app/locales/en.json（新規） | JSON翻訳カタログ、自動言語検出、英語fallback、CLIとntfy・fallback本文の翻訳 |
| app/oauth.py（新規） | 両クライアント・トークン生成で共通のスコープ |
| app/service.py（新規） | 既存運用のrun/日次cleanup/60秒待機を同梱。cleanup成功時だけ完了日を保存 |
| make_token.py | mainガード、GmailとDrive両方の権限、翻訳、既存tokenの上書き保護 |
| Dockerfile / .dockerignore | 常駐CMD、依存整合性検査、許可リスト方式のCOPY対象 |
| docker-compose.example.yml / config.example.ini（新規） | 汎用パス、永続マウント、再起動、秘密値が空の設定例 |
| .gitignore / .gitattributes / pyproject.toml（新規） | 秘密情報と実行データの除外、改行・静的検査の設定 |
| tests/test_regressions.py / tests/test_container.py / requirements-dev.txt（新規） | 外部接続なしの回帰テスト、コンテナのTZと日付境界の検証、検査ツールの固定版 |
| tools/check_release.py（新規） | 公開対象の構文・翻訳・Compose構造・秘密情報の簡易検査、配布ZIP作成 |
| .github/workflows/ci.yml（新規） | Linux上の検証とDockerビルド |
| README.md / INSTALL.md / UNINSTALL.md / TROUBLESHOOTING.md / CONTRIBUTING.md / SECURITY.md / RELEASE_NOTES.md（新規） | 日英の概要、導入、運用、削除、翻訳、公開手順、検証記録 |
| LICENSE（新規） | 所有者の指定によるMIT License。個人名は記載しない |

`requirements.txt` の実運用版固定バージョン、`app/__init__.py` は変更していません。作業用 `.venv/`・`.release-work/`・各キャッシュは公開対象外で、配布ZIPにも含めません。

## 動作に影響する変更

1. **STARTTLS証明書検証**: `ssl.create_default_context()` を明示。信頼されない証明書・ホスト名不一致は接続失敗になります。社内CAを使う環境では信頼設定が必要です。
2. **設定検証と引数検証**: 必須IMAP値の欠落、無効な真偽値/ポート/削除猶予、0以下のlatest/UID、不正日付は早期エラーです。ポート未指定は143。削除猶予は1日以上です。
3. **INI補間を無効化**: パスワードの `%` をそのまま扱います。旧設定に `%%` や `%(name)s` がある場合は、実際のリテラル値へ直してください。
4. **削除無効化**: `delete_after_import=false` なら、以前登録した削除期限があってもcleanupを実行しません。期限そのものは変更しません。
5. **OAuth生成**: Gmail単独だった生成スクリプトに `drive.file` を追加し、既存クライアントが求めるスコープと一致させました。既存tokenは自動で置き換えません。
6. **コンテナCMD**: 単発runから同梱の常駐ループへ変更。単発は `python -m app.main run` をコマンド指定します。日次cleanupは成功時のみmarkerを原子的に保存します。
7. **表示と言語**: 本体が生成する文言はja/en選択で変わります。保存済みDB状態名・ラベル・メールは変えません。例では明示した英語ラベル、未設定では既存互換の「添付退避」を使います。

Gmail取り込み後の通知失敗で再importしない処理、通常/fallbackのpending再開、最大3回の接続試行、障害通知抑制と復旧検出、UIDVALIDITY/UID/Deletedフラグによる削除ガードは維持しています。重複していた通知取得関数は実際に有効だった後側の定義を残しました。

## 検証結果

2026-09-22、Windows上のPython 3.12.14と、GitHub ActionsのUbuntu/Linux・Python 3.12で実施しました。[初回Linux CI実行結果](https://github.com/sosboy-san/gmail_bridge/actions/runs/35693704376)（コミット `f2894c61e5b263a5596922816f135431c49ad37a`）は全ステップ成功です。

| 検査 | 結果 |
| --- | --- |
| requirements.txtの固定依存を仮想環境へ導入 | 成功。固定バージョンは変更なし |
| pip check | 成功、依存関係の不整合なし |
| Python構文検査（compileall） | app、make_token、tests、toolsで成功 |
| 全appモジュールとmake_tokenのimport | 成功。OAuthや外部接続の副作用なし |
| Ruff（E4/E7/E9/F/I） | 成功。重複定義・未使用import等を確認 |
| 回帰テスト | Linux CIで32件すべて成功、skipなし。Windowsで未実施だったflockとTZ検証も成功 |
| 設定なし、不足、不正値、%入りパスワード、日英CLI | オフラインテストで確認 |
| 重要24関数の元コードとのAST比較 | 文言参照と同値の通知判定名を戻すと一致。取り込み・通知状態・削除ガードを含む |
| 翻訳キーとプレースホルダ、アプリ内の日本語表示リテラル残存 | 検査成功。日本語コメント・docstringは維持 |
| Compose | 構造検査とLinux CIでの `docker compose ... config --quiet` に成功 |
| Docker | Linux CIでpython:3.12-slimからの実ビルドとイメージ内CLI起動に成功 |
| コンテナのタイムゾーン | ビルド時の東京日付変換検査に成功。完成イメージ内の子プロセスTZ継承・東京午前0時のcleanup切り替え2件も成功 |
| 公開対象37ファイルの簡易秘密情報検査 | 典型的な実メールアドレス・OAuth情報・Driveリンク・NAS固有パスの検出なし。設定例の秘密値は空欄 |
| GitHub反映 | 新規Privateリポジトリのmainへ37ファイルを反映。リモートの全ファイルのblobハッシュがローカル公開対象と一致することを確認 |
| 実サービス・NAS | 未接続、未変更。下記の手動確認が必要 |

テストでは、通知失敗後もGmail import回数が増えないこと、ラベル失敗後の通常/fallback pending再開、既読/未読処理、IMAPの最大3回試行と待機、障害通知の抑制、復旧通知、UIDVALIDITY不一致、UID不在、UIDPLUSの対象限定EXPUNGE、非UIDPLUSでのDeleted検査とロールバック、cleanup失敗時の未確定、日次marker、SQLiteバックアップの整合性などを確認しています。

公開ZIPは `python tools/check_release.py --archive` で再生成できます。SHA-256はZIPと同じ場所の `.zip.sha256` に出力します。ZIP内には許可した37ファイルだけを含めます。自動検査で任意の個人名・秘密値が完全に排除されたことまでは保証できないので、所有者の最終レビューを残しています。

### 追加確認: 常駐ループとタイムゾーン

DockerfileのCMD（app.service）が常駐ループを所有し、公開用Composeにcommand/entrypointの上書きがないことを静的検査へ追加しました。旧ComposeやContainer Stationにあるシェルループは移行時に外す手順を追記しています。

slimの内容だけに依存せずOSのtzdataを明示導入し、ビルド時に東京の午前0時の日付変換を検査します。GitHub Actionsで実ビルドに成功し、完成イメージ内のTZ継承・午前0時をまたぐcleanup検証も成功しました。Windows上ではこれらLinux用2件はskipですが、Linux側ではskipなしです。取り込み・通知・削除の処理フローとUTCでのDB記録は変更していません。

## 手動で必要な受け入れ確認

- CIのLinux環境ではComposeとDockerビルド確認済み。実際に使うQNAPのCPU・Container Stationでもビルド／起動とマウント権限を確認すること。
- 専用メールで通常取り込み、添付拒否時のDrive fallback、本文・添付名・リンク・出所ラベル・未読状態を確認。
- ntfyを一時的に失敗させ、Gmailの件数が増えず通知だけ再送されること。
- IMAP到達不可→最大3回の試行→障害通知→重複抑制→復旧通知を実機確認。
- 証明書検証、OAuth更新とDrive権限、tokenファイルの書き込み権限を確認。
- 削除無効で試験を始め、DBとGmail/Driveを確認後に専用メールだけでcleanupのdry-runと期限到来後削除を確認。
- コンテナ停止/再起動、NAS再起動後の自動復帰、DB・ログ・バックアップ・cleanup完了日の永続化を確認。
- [SECURITY.md](SECURITY.md) の秘密情報チェックを終え、PrivateリポジトリでCIを通し、所有者が最終判断してからPublic化。

## 既存仕様として残した限界

API成功とローカルcommitの間のクラッシュによる重複可能性、UIDPLUS非対応での他クライアントとのEXPUNGE競合、復旧通知失敗時にその通知だけを再送しない点、個別取り込み失敗でもrunが終了コード0になる点は、大規模な状態設計変更を避けて残しています。日次バックアップ保持は最新14ファイルであり厳密な14暦日ではありません。詳細はREADMEとTROUBLESHOOTINGを参照してください。

## English

This preparation preserves the existing message/notification state machine and schema. Behavior changes are limited to verified STARTTLS, early configuration/argument validation, literal INI values, honoring disabled deletion for existing schedules, matching OAuth generation to Gmail+Drive client scopes, and bundling the existing service loop. Notifications and pending import recovery remain separate. The overridden duplicate notification query was removed; the effective implementation remains.

Pinned production dependencies are unchanged. GitHub Actions passed all 32 Linux tests, Compose validation, a real slim-image build, CLI startup, and two additional timezone checks inside the built image. The 37 release files were committed through the GitHub API to the owner's newly created Private repository. Visibility remains Private. Live Google/IMAP/ntfy and actual QNAP acceptance testing are still required. The owner selected the MIT License.
