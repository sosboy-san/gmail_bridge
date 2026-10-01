# v1.1.0 Phase 5 記録

2026-10-01。Phase 1〜4の未commit差分を引き継ぎ、Compose / 導入・更新・保守資料を整備しました。アプリの新機能追加はありません。

## 変更

- 既存のbuild/pull Composeは個別/app方式を維持。定常運用で不要なcredentials.jsonマウントを削除。
- docker-compose.config.example.yml / docker-compose.config.image.example.ymlを追加。BRIDGE_CONFIG_DIR=/config、単一rw bind、ホスト保存先をBRIDGE_HOST_CONFIG_DIRで指定可能。Hub版はBRIDGE_VERSION必須でv1.0との誤組み合わせを回避。
- config配下に設定/token/フィルタ/data/backup/logsを永続化。cleanup日付とロックもdataに含める。イメージコードは/app。新旧fallbackなし。
- INSTALL.mdをv1.1の安全待機→明示Console init→次周期復帰へ更新。旧版は起動前initで区別。
- MAINTENANCE.mdに更新前一式backup、停止中statusによる検証とmigration、保存方式移行、rollback・復旧、異常別対応、GitHubを正本とするCloud Work保守手順を追加。
- NOTIFICATIONS.mdに実装から確認した設定キー/既定値、200文字表示、完全一致許可・除外、TTLと終端状態、init中断/fallback/旧DB、大量処理と再読込を記載。
- README / TROUBLESHOOTING / UNINSTALL / CONTRIBUTING / SECURITY / DOCKER_RELEASE / Release Notesを必要範囲で整合。英語の明確な矛盾は修正し、全面翻訳は別工程。
- Docker公開ワークフローにrc.N完全タグのみの配布経路を用意。正式版浮動タグはRCで変更しない。存在しないタグ・不正タグ・既存または新しい正式版以降のRCを拒否。選択タグのSHAからビルドする仕様と完全版上書き禁止を維持。
- CIに新ComposeのDocker compose configを追加。実際のワークフローのGitHub scriptと配布タグ選択shellをローカルの3テストで検証。
- 公開前チェックの明示ファイル一覧に新資料・全Phase記録を追加。/configの実データはgitignore、イメージCOPY対象外。

## 検証

- 全94件のオフラインテスト成功（既存91件＋配布ポリシー3件）。架空データ・モックのみ。
- Ruff、compileall、pip check、公開前チェック、git diff --check成功。
- PyYAMLによる4 Composeの解析、保存先・rw/ro・CMD非上書き・build/pull対応・必須バージョンの構造確認。ワークフローYAMLとshell構文の静的確認。
- config.example.ini / notification_senders.example.iniとconfig.py / paths.py / notification_service.py / metadata / main / service / stateから設定キー、既定値、周期、保存先、状態・TTLを照合。
- **静的確認済み / Docker実動作未検証。** Dockerコマンド/daemonはこの環境に存在しない。Dockerをインストールせず、Cloud Work環境を変更していない。Docker compose config / build / イメージ内実行は未実施。
- Nodeで公開タグポリシーを実行。イメージ内にNodeがない場合は該当2テストをskipし、host CIで検証する。

## RCへ進む条件・未検証

Phase 5の成果物はv1.1.0-rc.1作成工程へ渡せる状態です。RCはまだ存在しません。別指示によるcommit/push後、CIとamd64/arm64 Docker検証に合格してからRCタグ/Pre-release/Hub公開へ進みます。

残る確認: Docker Compose実構文展開・build・実行、Docker HubへのRC公開とdigest/manifest・浮動タグ不変、QNAP UI/ACL・Console init・永続化・NAS再起動、実OAuth更新、通常Gmail/Drive fallback・ntfy・TTL、実DBの更新/復旧・安全cleanup。全英語資料の整備も別工程です。QEMUはQNAP実機確認の代用ではありません。

既知の制限（未変更）: API成功とローカル保存のクラッシュ窓、旧backupからの復旧による重複、部分init対象外の過去メール通知、run exit 0が全成功を保証しないこと、IMAP不通時の通知待機、復旧通知失敗の独立再送なし。

commit / push / merge / tag / GitHub Release / Docker Hub push / latest更新は一切実施せず、Phase 5報告で停止します。作業差分はこの時点ではGitHubに保存されていません。
