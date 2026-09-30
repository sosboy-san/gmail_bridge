# 導入 / Installation

検証環境と本番環境で `data/` を共有しないでください。検証には専用メールボックスと専用Googleアカウントを推奨します。

## 1. 前提

- Linuxコンテナを実行できるDocker EngineとDocker Compose v2、またはQNAP Container Station。
- STARTTLS対応のIMAPサーバー、ログイン情報。サーバー証明書のホスト名・信頼チェーンが正しいこと。
- GmailとGoogle Driveを利用できるGoogleアカウント。組織アカウントは管理者のAPI利用制限も確認します。
- OAuth初回認証用のPython 3.12とブラウザを使えるPC。
- ホスト側に設定、トークン、DB、バックアップ、ログを保持できる専用ディレクトリ。

## 2. Google OAuthの準備

1. [Google Cloud Console](https://console.cloud.google.com/) で自分のプロジェクトを作成し、Gmail APIとGoogle Drive APIを有効にします。
2. Google Auth Platform / OAuth同意画面でアプリ情報と対象ユーザーを設定します。ExternalでTestingを使う間は、認証するアカウントをテストユーザーに追加します。
3. OAuthクライアントを **Desktop app / デスクトップアプリ** として作成し、JSONをダウンロードして `credentials.json` としてPC上に保存します。
4. 以下をPC上で実行します。認証するGoogleアカウントが取り込み先です。

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShellの場合: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python make_token.py --lang ja
```

ブラウザが開き、ローカルループバックへの応答で認証が完了します。ヘッドレスNAS内でこの手順を無理に実行せず、PC上で作成した `token.json` を安全な方法でNASへ転送します。既存トークンの置き換えは `--force` が必要です。スクリプトをimportしただけでは認証しません。

スコープは既存クライアントと同じ `https://mail.google.com/` と `https://www.googleapis.com/auth/drive.file` です。前者は広いGmail権限なので、同意内容を確認してください。既存トークンにDrive権限がなければ、このスクリプトで再認証します。アプリはDrive共有権限を公開へ変更しません。

Desktop appのループバック方式については [Google公式手順](https://developers.google.com/identity/protocols/oauth2/native-app) を参照してください。ExternalかつTestingの同意画面では、このスコープ構成のリフレッシュトークンは通常7日で期限切れになります。継続運用前に同意画面の公開状態・組織のポリシー・必要な審査を確認してください。これはGitHubリポジトリのPrivate/Publicとは別の設定です。[Googleのトークン有効期限説明](https://developers.google.com/identity/protocols/oauth2#expiration)

## 3. 設定

```bash
cp config.example.ini config.ini
cp docker-compose.example.yml docker-compose.yml
mkdir -p data backups logs
```

`config.ini` はUTF-8で編集します。IMAPのhost、user、passwordは空欄を埋めます。パスワードの `%` はそのまま記入し、引用符で囲みません。以前の設定で `%%` にエスケープしていた場合は `%` へ戻してください。インラインコメントは値の後ろに書かないでください。

| セクション・項目 | 意味・既定値 |
| --- | --- |
| general.language | ja（既定）/ en。CLI > BRIDGE_LANGUAGE > INIの順で優先 |
| imap.host / user / password | 必須。空欄を許可せず、エラーには値を表示しない |
| imap.port | 143。STARTTLS方式。993番を指定しても暗黙TLSには切り替わらない |
| imap.mailbox | INBOX。状態はmailboxとUIDVALIDITYとUIDで管理 |
| imap.label | 出所ラベル。未指定・空欄ならuserの値を使用。例ではIMAP-Bridge |
| imap.delete_after_import | false。trueで取り込み完了時に削除期限を記録。falseなら既存期限のcleanupも停止 |
| imap.delete_delay_days | 7。1以上の整数。変更しても記録済みの期限は書き換えない |
| gmail.token_file | token.json。自動更新するため書き込み権限が必要 |
| gmail.fallback_label | 例ではAttachments-in-Drive。未設定時は既存互換の「添付退避」で、言語を変えても同名を維持 |
| gmail.force_not_spam | false。trueならSPAMラベルを解除。INBOXラベル追加の機能ではない |
| drive.folder | Gmail-IMAP-Bridge。フォルダ名でありIDではない。添付拒否時に自動fallback |
| notification.enabled | false。trueにする前にntfyの送受信・アクセス制御を確認 |
| notification.provider | ntfyのみ |
| notification.server_url | https://ntfy.sh または自分のntfyサーバーURL |
| notification.topic | 有効化時に必要。実topicは公開しない |
| notification.token | 必要な場合のBearer token。実tokenは公開しない |

通知は「新着メールが1件あります」という本文です。メール本文や件名は通常通知に含めません。IMAP障害通知には接続エラーの文字列が含まれるので、公開topicは使わないでください。ntfyの購読側も同じtopic・必要な認証で設定します。topicの推測困難さだけに依存せず、可能なら読み書きを認証で保護します。

保持設定は現状コードの固定値です。架空のINI項目は追加していません。DBはUTC日付ごとに1回、最新14ファイルを保持します（稼働しなかった日があると14暦日より長く残ります）。runログはローカル日付で保存し、更新時刻が30日より古いログをrun開始時に削除します。cleanupはコンテナのローカル日付で1日1回成功するまで試行します。

## 4. Docker Compose

以下はLinuxホスト用の例です。設定とトークンを作成してからビルドします。Composeの例はファイルがない場合に空ディレクトリを自動作成しない設定です。

```bash
# 使用するホストユーザーのUID/GID。QNAPでは実際の専用ユーザーに合わせる。
export BRIDGE_UID=$(id -u)
export BRIDGE_GID=$(id -g)
chmod 600 config.ini credentials.json token.json
chmod 700 data backups logs
docker compose config --quiet
docker compose build
docker compose run --rm gmail-bridge python -m app.main --lang ja init --latest 1 --dry-run
docker compose run --rm gmail-bridge python -m app.main --lang ja init --latest 1
docker compose run --rm gmail-bridge python -m app.main status
```

ホストのユーザーを環境変数に設定しているため、そのユーザーが3つのディレクトリとtoken.jsonへ書き込めることを確認します。次回のCompose実行でも同じ値になるよう、必要ならローカルの `.env` に保存します（Git管理対象外）。Windows Docker Desktopでは共有ディレクトリのアクセス権を確認し、POSIX chmodの代わりにホスト側ACLで秘密情報を保護します。

初期化方針を決めます。選択した範囲だけのinitは、**範囲外をignoredにしません**。たとえば `--latest 1` の後に通常runを開始すると、残りの未処理の過去メールも対象になります。

| コマンド | 動作 |
| --- | --- |
| init --from-now | 現在存在する全UIDをignoredとして保存。以後到着分から開始 |
| init --all | 現在の全メールを取り込む |
| init --since YYYY-MM-DD | 指定日以降をIMAP SINCEで検索して取り込む |
| init --latest N | 最新N通を取り込む（Nは1以上） |
| init --uid UID | 1つのUIDを取り込む |
| init … --dry-run | Gmail・Driveへ送らず対象確認。DBの作成・スキーマ移行は起こり得る |
| init … --yes | 複数メール取り込みの確認を省略。既定ではy/yes入力が必要 |
| run | 初期化済みmailboxの全未処理UIDを取り込み、pending通知を送る |
| run --uid UID | 指定UIDだけを処理。取り込み完了済みならスキップ |
| run --dry-run | 取得・表示のみ。DBバックアップ、ログ、IMAP障害/復旧通知は動くため完全無副作用ではない |
| status | ローカルDBの集計と初期化状態。接続監視ではなく、初回はDBを作成する |
| cleanup --dry-run | 削除有効時、期限到来候補を表示。メールを削除しない |
| cleanup | 期限到来した取り込み完了メールを安全確認後に削除。失敗時は非ゼロ終了 |

新着だけにする場合、試験取り込みが完了した後、常駐停止中に `init --from-now` を実行します。**既存レコードもignoredへ更新するため、本稼働中の再初期化には使わないでください。** 意図した初期化を完了したら常駐を開始します。

```bash
docker compose run --rm gmail-bridge python -m app.main init --from-now
docker compose up -d
docker compose logs --tail=100 -f gmail-bridge
```

コンテナ内の作業ディレクトリは `/app`。既定CMDは `python -m app.service` で、run → 必要ならcleanup → 60秒待機を繰り返します。処理時間が加わるので厳密な毎分実行ではありません。`restart: unless-stopped` によりDocker起動後に復帰します。ただし手動停止したコンテナは勝手には再開しません。[Compose公式仕様](https://docs.docker.com/reference/compose-file/services/)

**常駐ループの責任はイメージのCMDだけが持ちます。** 公開用Composeには `command:` / `entrypoint:` を指定しません。旧QNAP設定から移行する際は、ComposeやContainer Stationのコマンド欄に残っている `while true ...` を外して、イメージの既定CMDを使ってください。`restart:` はプロセス終了後の再起動設定であり、毎分のループではありません。

DockerfileでOSの `tzdata` を明示的に導入し、ビルド中に `TZ=Asia/Tokyo` で「UTC 15:00が翌日00:00になる」ことを検査します。名前付きのTZはOSのタイムゾーンデータを使います。[Python公式説明](https://docs.python.org/3.12/library/time.html#time.tzset)

Compose例の既定はAsia/Tokyo、イメージ単体の既定はEtc/UTCです。ホストのTZが自動的にコピーされるわけではありません。`${TZ:-Asia/Tokyo}` はシェルや `.env` のTZで上書きされるため、実際の設定とコンテナ時刻を以下で確認してください。日本時間なら `Asia/Tokyo` と `+09:00` が表示されます。

```bash
docker compose config
docker compose run --rm gmail-bridge python -c "import os; from datetime import datetime; print(os.environ.get('TZ')); print(datetime.now().astimezone().isoformat())"
```

cleanup完了日とrunログの日付は、このコンテナのローカル時間です。SQLite内の日時と日次DBバックアップは従来どおりUTCです。CIではビルドしたslimイメージ内でも、子プロセスのTZ継承と日本時間の午前0時でのcleanup日付切り替えを検証します。

手動init・cleanupや設定変更は `docker compose stop` 後に実施し、終わったら `docker compose up -d`。Gmail保存・Driveリンクを確認してから削除を有効にし、まず `cleanup --dry-run` を確認します。cleanupはIMAP側を削除するもので、Gmail・Drive側は削除しません。

## 5. 永続化とQNAP Container Station

| ホスト側 | コンテナ側 | アクセス |
| --- | --- | --- |
| config.ini | /app/config.ini | 読み取り専用 |
| credentials.json | /app/credentials.json | 読み取り専用。定常運用の実装は読み込まないので、OAuthをPCで完了した後はマウントを省略可能 |
| token.json | /app/token.json | 読み書き（refresh時に更新） |
| data/ | /app/data | 読み書き。state.db・ロック・cleanup完了日 |
| backups/ | /app/backups | 読み書き。backups/db/へ日次保存 |
| logs/ | /app/logs | 読み書き。runログ |

QNAPでは専用共有フォルダを用意し、この公開コードと上表の実ファイル・ディレクトリを置きます。既存の本番共有フォルダは検証用に使わないでください。

1. Container StationでLinuxコンテナを動かせる機種・CPUアーキテクチャであることを確認します。ソースから、そのNASのアーキテクチャ向けにイメージをビルドします。別マシンで作る場合は同じアーキテクチャのイメージを転送します。
2. SSHで共有フォルダに移動して上記Compose手順を使うか、Container Stationのアプリケーション作成機能でComposeを登録します。UIやCompose対応範囲はContainer Stationの版によって異なります。
3. UIが相対パスのビルドやマウントを解決できない場合、先に `gmail-bridge:local` をNASへ読み込み、Composeの `build` 行を外し、各sourceを自分の共有フォルダの絶対パスに変更します。特定NAS名や共有フォルダ名への依存はありません。
4. コンテナのユーザーUID/GID、作業ディレクトリ `/app`、6つの永続マウント、再起動ポリシー、TZを確認します。専用ユーザーに必要なフォルダ書き込み権限を与えます。
5. 常駐を起動する前に、一時コンテナ／単発実行でinitを完了します。UIでコマンドを指定する場合も `python -m app.main init --from-now` など同じCLIを使用します。
6. 常駐開始後、NAS/Container Station再起動後の復帰、token更新、ログ・DB・バックアップの永続化を実機で確認します。

## 6. 更新と復元

常駐を停止してから、設定・token・data・backupsを非公開の場所へバックアップします。コードだけ更新して再ビルド・再作成します。DBのスキーマは既存のままで、既存コピーの移行処理も残しています。

SQLiteの稼働中ファイルを単純コピーする代わりに、生成済みのbackup APIによるバックアップを使うか、全プロセス停止後にdata全体をコピーします。古いDBを戻すと、そのバックアップ以降のGmail取り込みを再試行して重複する可能性があります。復元後は自動runを開始する前にGmailとDB状態を照合してください。

## English

Use Python 3.12 and Linux containers. IMAP must support STARTTLS, usually on port 143, with a valid server certificate. Port 993 implicit TLS and IMAP OAuth are not implemented. Use separate test accounts and state directories for acceptance testing.

1. Create your own Google Cloud project. Enable Gmail API and Google Drive API. Configure the consent screen/audience and add your account as a test user if applicable. Create a **Desktop app** OAuth client and save its downloaded JSON as `credentials.json` on a trusted desktop.
2. Create a Python virtual environment, install `requirements.txt`, and run `python make_token.py --lang en`. A browser completes the loopback flow. Securely transfer `token.json` to the host. This requests the existing full Gmail scope plus `drive.file`; regenerate old Gmail-only tokens. Testing-mode external consent screens normally issue a refresh token valid for seven days for these scopes; check the official Google links above before continuous use.
3. Copy the configuration and Compose examples as shown above. Fill in IMAP host/user/password, set `[general] language = en`, and initially leave deletion and notifications disabled. Values are literal, including `%`; no shell expansion or INI interpolation occurs. Notification provider is ntfy only; configure a protected topic and bearer token as needed. Drive folder is a name, not an ID.
4. Create `data`, `backups`, and `logs`. Ensure the selected container UID/GID can write those directories and `token.json`; protect credential files from other host users. Config and credentials mounts are read-only. Credentials are not used during normal operation and that mount may be omitted after desktop authorization. No credentials are built into the image.
5. Run `docker compose config --quiet`, `docker compose build`, then the one-off init preview and test commands above, using `--lang en` before `init`. Inspect Gmail contents, labels, source read/unread state, and Drive access before proceeding.
6. Choose `init --from-now` to ignore current mail or `init --all` to import it. `--since`, `--latest`, and `--uid` import subsets but do not ignore other old messages; a subsequent run picks up all remaining unprocessed mail. Do not rerun `--from-now` against a live database: it also marks existing records ignored. `--yes` skips bulk confirmation.
7. Start `docker compose up -d`. The service runs a cycle, performs cleanup if it has not succeeded today, and waits 60 seconds. Failed cleanup does not update the marker. Stop the service before manual init/cleanup or configuration changes. Enable deletion only after verifying copies and `cleanup --dry-run`.

`run` imports pending mail and retries notifications; `status` reports local database counts and initialization, not service health; `cleanup` deletes expired successfully imported source messages after UIDVALIDITY/UID checks. Dry-run avoids Gmail import/Drive uploads/deletion, but may create/migrate the database. Run dry-run also writes logs/backups and may send IMAP outage/recovery alerts. Init queues new-mail notifications; a later run sends them.

Deletion delay defaults to 7 days, must be positive, and does not rewrite existing deadlines. Turning deletion off suspends existing schedules too. The example sets explicit source/fallback labels; omitted fallback label retains the original Japanese label for compatibility regardless of UI language. Forced SPAM removal does not force the INBOX label.

For QNAP, use a dedicated share and the same six mounts listed above, `/app` working directory, a writable dedicated user, and restart policy. Build for the NAS architecture. If Container Station cannot resolve relative build contexts, load a prebuilt matching image, remove `build`, and use your own absolute share paths for mounts. No specific QNAP path is required. Verify restart recovery on the actual NAS.

The image CMD is the sole owner of the persistent loop. Do not override it with a Compose `command`/`entrypoint` or an old Container Station shell loop. The image explicitly installs system tzdata and checks Tokyo's midnight conversion during build. Compose defaults to Asia/Tokyo, whereas the bare image defaults to Etc/UTC; shell/.env TZ can override the Compose example. Use the time-check command above to verify `Asia/Tokyo` and `+09:00`. CI additionally tests TZ inheritance and the cleanup date boundary inside the built slim image. Database timestamps and backup dates remain UTC.

Daily database backups use UTC dates and retain the newest 14 files; run logs use local dates and a 30-day modification-time cutoff. Cleanup uses the container local date. These are fixed operational values, not extra INI options. Stop all processes before restoring state; an older backup can cause duplicates for messages imported after its timestamp.
