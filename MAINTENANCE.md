# 更新・保守・障害復旧（v1.1）

対象はDocker Hub `sosboy/gmail-bridge` の公開後のv1.1 / RCです。v1.1.0-rc.1も正式v1.1.0も現在未公開です。実環境の削除を無効にした状態で確認してください。導入は [INSTALL.md](INSTALL.md)、通知は [NOTIFICATIONS.md](NOTIFICATIONS.md)。

## v1.0系から更新する順序

1. 正本GitHubの対象タグのRelease Notesと設定例を確認し、現在のイメージの完全タグ・digest、Compose、環境変数、UID/GID、ホスト保存先を記録します。mainは開発版であり、正式配布の代用ではありません。
2. `docker compose stop` で常駐を停止します。別の単発init/run/cleanup、同じDBを使用するコンテナやタスクもすべて止め、処理終了を確認します。
3. ホストの**設定、token、data全体、backups、logs、Compose、ローカル.env**を非公開の別フォルダ／NASスナップショットへ保存します。DB本体だけでなくSQLite付随ファイルも含む停止時点の一式を保持し、backupの読み取りと容量を確認します。credentialsはPC側で別途保管します。
4. 初回更新は旧方式を維持することを推奨します。`docker-compose.image.example.yml` を利用し、`BRIDGE_CONFIG_DIR` は未指定のまま、マウント元を既存のものに合わせます。`.env` の `BRIDGE_VERSION` だけを公開済みの完全タグへ変更します（RCなら `1.1.0-rc.1`、先頭vなし）。既存config/token/DBを新しい例で上書きしません。
5. `docker compose config --quiet`、`docker compose pull` を実行します。旧版を戻せるようイメージを保持します。**更新時にinitは実行しません。**
6. 常駐を停止したまま `docker compose run --rm gmail-bridge python -m app.main status` を実行します。既存DBの検証と必要なmigrationが行われ、ローカル状態を表示します。statusは新規DBを作らず、IMAP/Gmailへ接続しません。失敗した場合はupせず、下記の障害対応へ進みます。
7. migration専用backup、既存mailbox・初期化状態・メッセージ件数を確認し、`docker compose up -d`。ログ、新着の通常取り込み、token更新、バックアップ作成を確認します。日次cleanup記録も同じdataに保持されます。削除の再有効化は保存内容を確認してから行います。

RCから正式版への移行も同じ順序です。同じホスト保存先とComposeを使用し、完全タグを `1.1.0` へ変更します。schema変更がなければ再migrationやinitはありません。浮動タグlatest / 1 / 1.1は意図せず別版へ進むため、保守には完全タグを推奨します。

## 旧マウントから単一/configへ移す場合

バージョン更新と保存方式変更を別作業にすると切り分けやすくなります。

- 全プロセス停止と上記の一式backupを先に実施します。
- 新しい専用フォルダへconfig.ini、token.json、通知フィルタ（使用時）、data全体、backups、logsを**コピー**します。初期化済みdataを残したまま移し、空のdataへ切り替えません。
- token_file、sender_filter_fileが旧 `/app` の絶対パスなら新ルート内の相対パスに直します。アカウントやmailboxは変更しません。
- `docker-compose.config.image.example.yml` を使い、コピー先1フォルダを `/config` にマウント。`BRIDGE_CONFIG_DIR=/config` とUID/GID・TZ・完全バージョンを確認します。旧個別マウントを併用せず、旧サービスは起動しません。
- 停止状態のstatusで既存件数・初期化状態を確認してから起動します。確認が終わるまで旧保存先を保管します。**initで移行しないでください。**

## DB migrationとbackup

アプリ版v1.1とDB版は別です。DBは `PRAGMA user_version` で管理し、現在のschemaは1、既存v1.0は0です。

既存DBのintegrity_checkと既知schemaを検証 → SQLite backup APIで専用backup → transaction内で追加・既存状態維持 → schema検証と版更新 → commit、の順で自動移行します。migrationはinitを呼びません。失敗時はtransactionをrollbackし、既存schema・状態を保持して待機します。backup作成に失敗した場合もmigrationを続行しません。

| backup | 保存先（新方式） | 用途・保持 |
| --- | --- | --- |
| 更新前の手動一式 | 利用者が選ぶ非公開の別フォルダ | 設定/token/data等も含むrollback用。移行専用DBだけでは代用不可 |
| migration専用 | /config/backups/db/migrations/state_before_schema_1_日時_識別子.db | 移行前DB。日次ローテーション対象外、保管・容量は利用者が管理 |
| 日次DB | /config/backups/db/state_YYYY-MM-DD.db | UTC日付、SQLite backup API、integrity_check、最新14ファイル |

旧方式は `/app/backups/...` です。稼働中state.dbだけの単純コピーは使いません。backupには送信元・件名・メールID・通知状態等が入り得るため非公開にします。

## rollbackとbackupからの復旧

1. 常駐と全単発プロセスを停止し、現在の問題状態も別の非公開フォルダに保全します。
2. 戻すアプリ版に対応するDBと設定を選びます。**新schemaのDBをそのままv1.0へ渡すrollbackは保証しません。自動downgradeはありません。** v1.0へ戻す場合は更新前の一式snapshotを使用します。
3. 自動起動を停止した状態で、ホスト保存先に選んだ一式を復元します。異なる時点のstate.db / WAL / SHMを混ぜず、DBだけを戻す場合も停止確認のうえ既存dataを別保管し、選んだbackup DBと整合する状態にします。権限、token、Compose、環境変数、イメージ版も照合します。
4. v1.1で復旧する場合は、起動前に単発statusでDB検証・必要な再migrationを確認します。v1.0は対応する旧方式を使用します。復元DBの日時以降に実際のGmail/Driveで保存済みのメールとDBを照合し、重複の可能性を確認してから常駐を再開します。

backup復元はリモートのGmail/Driveを巻き戻しません。古いDBは取り込み済み判定を失い、再取り込み・重複が起こり得ます。削除済みIMAPメールもDB復元では戻りません。DB異常を直すためにDBを削除したり、init --from-nowで状態を作り直したりしないでください。適切なbackupがなければ元メール・Gmailを照合して復旧方針を決めます。

## 常駐ログと対応

| 表示・状況 | 利用者の確認・操作 |
| --- | --- |
| CONFIG_ERROR | UTF-8 INI、必須IMAP値、モード/TTL、フィルタファイル、保存先を修正。通知の設定不正も新規処理を停止する |
| OAuthファイル欠落/不正 | token_fileとマウント・権限を確認。DB準備後のローカル確認でCONFIG_ERROR。PCで作成した有効なJSONを配置する |
| WAITING_FOR_INIT | DBなし、または既知DBだがmailbox未初期化。新規導入時だけConsoleで明示init。更新時は先に誤マウントやDB紛失を調査 |
| DB_ERROR | 空DB・破損・未知schema/未知DB等。init待ちとは別。停止して保全し、整合するbackupから復旧 |
| DB_MIGRATION_ERROR | 空き容量、backup先とDBの権限、ログを確認。既存状態を保全し、原因修正後再確認。失敗時に空DBを作らない |
| WAITING_FOR_LOCK | init等の処理終了を待つ。稼働中のロックファイルを消さない |
| CONFIG_OK | ローカル準備が整った状態。API認証成功や全メールの取り込み成功を保証する表示ではない |
| RUN_FAILED / CLEANUP_FAILED / SERVICE_ERROR | コンテナログで原因を確認し、次周期を監視する。終了コード非ゼロのrun後はcleanupしない |

異常時も常駐サービスは維持され、処理終了後60秒ごとに再確認します。同じ状態・同じ理由の待機ログは繰り返しません。設定修正後はCONFIG_OKとなり復帰します。cleanup直前にも設定・DB・tokenを再確認し、成功時だけdata/last_cleanup_dateを更新します。

INIは次処理周期・次メール処理・通知送信直前に再確認します。不正設定は推測でoffへ置き換えません。IMAP接続設定やGmail tokenのパスが変わった場合は現バッチを止め、次周期で接続を作り直します。OAuthファイル交換は安全のため常駐停止中に行ってください。旧方式のファイルbindではエディタによるファイル置換が反映されない場合があるため、反映しなければコンテナを再作成して確認します。

`docker compose restart` は同じイメージで再起動する操作です。イメージ更新はpull後にupで再作成します。停止中・再作成中もホストの保存先を削除しません。token refresh、永続化、NAS再起動後の自動復帰を実機で確認してください。

**既知の制限:** run終了コード0は全メール成功を意味しません。既存実装ではIMAP接続失敗も通知後にreturnするため、サービスの「非ゼロrunならcleanupしない」判定で全障害を検出できるわけではありません。ログのfailed件数と新着取り込みを確認します。IMAP不通時はpending通常通知も待ち、復旧通知自体の失敗は独立キューで再送しません。これらは今回変更していません。

## Cloud Workでの今後の保守

GitHubから対象branch/tagを取得 → 差分とRelease Notes確認 → 独立した検証環境で編集 → 全テスト/lint/公開前チェック/Compose確認 → 差分レビュー → 指示を受けてcommit・push → CIと両CPUのDocker検証 → RC公開 → QNAPでpullして受入確認 → 正式Release、の順です。Local Workの作業フォルダや実運用データを更新元にしません。セッション終了前に未commit差分の保全方針を決め、未公開の作業がGitHubへ保存済みであると誤認しないでください。

Phase 5ではcommit・push・RC公開は行っていません。英語資料の全面整備は仕様確定後の別工程です。
