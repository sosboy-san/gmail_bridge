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

## 3. v1.1の新規導入（Docker Hub / QNAP）

この節はv1.1向けです。**v1.1.0 / v1.1.0-rc.1はまだ未公開**です。以下のpull手順は対象タグの公開後に使用します。現在の正式版v1.0.0は旧方式Composeを使い、常駐開始前に単発initを完了してください。v1.0.0は `/config` 方式に対応していません。

GitHub `sosboy-san/gmail_bridge` を正本とし、対象タグに含まれる設定例・Compose・導入資料を取得します。作業フォルダの古いコピーを更新元にしないでください。

```bash
cp docker-compose.config.image.example.yml docker-compose.yml
mkdir -p config/data config/backups config/logs
cp config.example.ini config/config.ini
# PCで作成したtoken.jsonを安全な方法でconfig/token.jsonへ転送する。
# フィルタを使う場合だけ作成・編集する。
cp notification_senders.example.ini config/notification_senders.ini
```

`config/config.ini` をUTF-8で編集し、必須の `[imap] host / user / password` を設定します。パスワードの `%` はそのまま書き、引用符や値の後ろのインラインコメントは付けません。以前の `%%` は実際の `%` へ戻します。最初は削除・通知を無効にします。

| 設定 | コード上の既定値・注意 |
| --- | --- |
| general.language | ja。CLI > BRIDGE_LANGUAGE > INIの順で優先 |
| imap.port / mailbox | 143 / INBOX。STARTTLS専用 |
| imap.label | 未指定・空欄ならIMAP user。設定例はIMAP-Bridge |
| imap.delete_after_import / delete_delay_days | false / 7（1以上）。falseは既存削除予定も停止。変更しても記録済み期限は不変 |
| gmail.token_file | token.json。refreshで更新するため読み書き必須 |
| gmail.fallback_label | 未指定時は「添付退避」。例はAttachments-in-Drive。言語で既存ラベルを変更しない |
| gmail.force_not_spam | false。SPAM解除のみで、INBOX追加ではない |
| drive.folder | Gmail-IMAP-Bridge。フォルダ名でありIDではない |
| notification.enabled | false。詳細は [NOTIFICATIONS.md](NOTIFICATIONS.md) |

Composeに対応するローカル `.env` で、**公開済みの完全バージョン**を指定します。Dockerタグには先頭の `v` を付けません。以下はRC公開後の例であり、公開済みであることを意味しません。

```dotenv
BRIDGE_VERSION=1.1.0-rc.1
BRIDGE_UID=1000
BRIDGE_GID=1000
TZ=Asia/Tokyo
BRIDGE_HOST_CONFIG_DIR=./config
```

UID/GIDは実際の専用ユーザーに合わせます。Linuxでは `id -u` / `id -g` で確認し、そのユーザーにconfig全体の必要な読み書き権限を与えます。秘密ファイルは他ユーザーから読めない権限（例:ファイル600、専用ディレクトリ700）にします。QNAPでは共有フォルダのACLも確認します。Windows Docker DesktopではホストACLと共有設定を使います。トークン更新に備え `/config` は読み書きマウントです。

```bash
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose logs --tail=100 -f gmail-bridge
```

設定が正しくDBがない場合は `[WAITING_FOR_INIT]` を確認します。**自動initはありません。待機中はメール取得・削除を開始しません。** 必須設定が不正なら先に `[CONFIG_ERROR]` となります。空の `state.db` を自分で作らないでください。OAuth確認はDB準備後に行われるため、初期化待ちの表示だけではtokenの正常性は保証されません。

## 4. Consoleから明示的にinit

Container Stationで起動済みコンテナのConsoleを開き、作業ディレクトリ `/app` で次を実行します。ホストSSHからは `docker compose exec` を使います。Consoleでシェルが必要な場合は `sh` を起動してください。サービスのCMDは上書きしません。

```bash
# 過去メールを取り込まず、以後の新着から開始する初回導入例。
docker compose exec gmail-bridge python -m app.main init --from-now
# 初期化後のローカルDB確認。ロック競合時は処理終了を待って再実行。
docker compose exec gmail-bridge python -m app.main status
```

Console内では `python -m app.main init --from-now` の部分だけを入力します。待機中はロックが解放されているためinitできます。init中は共通ロックにより常駐処理が待機します。完了後、次の確認周期で `[CONFIG_OK]` となり通常運転へ自動復帰します。処理終了後の待機は60秒で、厳密な毎分実行ではありません。

| コマンド | 初回の過去メールの扱い |
| --- | --- |
| init --from-now | 現在の全UIDをignoredとして保存。取り込まず新着から開始 |
| init --all | 現在の全メールを取り込む。通常ntfy通知は生成しない |
| init --since YYYY-MM-DD | IMAP SINCEで選択したメールを取り込む |
| init --latest N / --uid UID | 最新N件 / 1件を取り込む（正の整数） |
| init … --dry-run | Gmail・Driveへ送らず対象を確認。ただしDB作成・migrationは起こり得る |
| init … --yes | 複数メール取り込み時の対話確認を省略 |

**部分initは範囲外をignoredにしません。** その後runは残りの過去メールも取り込み、それらは通常通知の対象になり得ます。全過去メールを通知せず取り込む場合は `init --all`、過去メールを無視する場合は `init --from-now` を選びます。試験取り込みは本番と異なるメールボックス・DBで行ってください。

`init --from-now` は既存レコードもignoredへ更新します。**更新・DB移行・通常の再起動でinitを実行しないでください。** 初期化済みの本番でinitや手動cleanupを行う場合は、常駐を停止して目的と対象を確認します。

## 5. 保存先とComposeの選択

| Compose例 | 用途 | 保存方式 |
| --- | --- | --- |
| docker-compose.config.image.example.yml | v1.1+をDocker Hubからpull。RCも同じ構成 | 単一 `/config`、バージョン指定必須 |
| docker-compose.config.example.yml | 正本から開発版をローカルビルド | 単一 `/config` |
| docker-compose.image.example.yml | 既存方式を維持する更新 / v1.0.0導入 | `/app` 配下へ個別マウント、既定1.0.0 |
| docker-compose.example.yml | 旧保存方式でソースビルド | `/app` 配下へ個別マウント |

| ホストの専用フォルダ内 | 新方式のコンテナ内 | 用途 |
| --- | --- | --- |
| config.ini | /config/config.ini | 設定 |
| token.json | /config/token.json | OAuth、refresh時に更新 |
| notification_senders.ini | /config/notification_senders.ini | 有効な送信元フィルタのみ必須 |
| data/ | /config/data/ | state.db、SQLite付随ファイル、gmail_bridge.lock、last_cleanup_date |
| backups/ | /config/backups/ | db/に日次backup、db/migrations/に移行専用backup |
| logs/ | /config/logs/ | runログ |

コードはイメージ内の `/app`。`BRIDGE_CONFIG_DIR=/config` を指定すると設定・token・DB・backup・ログ・cleanup記録はこの保存先だけを使用し、旧パスへfallbackしません。token_fileなどは配下の相対パスを推奨し、旧 `/app/token.json` の絶対パスは修正します。指定なしなら従来の作業ディレクトリ基準です。2方式を混在させず、同じDBを複数サービスで共有しないでください。

QNAPでは専用共有フォルダの絶対パスを `BRIDGE_HOST_CONFIG_DIR` またはvolumeのsourceへ指定し、**その1フォルダを `/config` へマウント**します。環境変数欄に `BRIDGE_CONFIG_DIR=/config`、UID/GID、TZを設定します。command / entrypoint / 古い `while true` ループは追加しません。UI・Composeの対応範囲は機種・Container Station版で実機確認が必要です。

`credentials.json` はPCでの初回OAuthに使い、定常運用のマウントには不要です。ホストの専用フォルダは先に作成します。Composeはマウント元欠落時のディレクトリ自動生成を禁止します。コンテナ再作成・イメージ更新でも、同じホスト保存先を指定すれば永続データは残ります。

ComposeのTZはAsia/Tokyo、イメージ単体はEtc/UTCです。cleanup完了日とログはコンテナのローカル日付、DB日時と日次backup日はUTCです。日次backupは最新14ファイル、runログは更新時刻で30日超を削除する固定仕様です。移行専用backupは日次ローテーションの対象外です。

## 6. 更新・復旧・通知

- [MAINTENANCE.md](MAINTENANCE.md): v1.0→v1.1、保存方式移行、backup、migration、rollback、障害復旧。
- [NOTIFICATIONS.md](NOTIFICATIONS.md): 通知内容、送信元フィルタ、TTL、状態とinit抑止。
- [DOCKER_RELEASE.md](DOCKER_RELEASE.md): RCと正式版の配布タグ、公開管理。

## English

The Japanese v1.1 instructions above are the current maintenance guide; a complete English revision is deferred until the v1.1 specification is finalized. v1.1 and its RC are not published yet.

Use desktop OAuth to create token.json; credentials.json is not needed at runtime. The new image Compose requires a published exact BRIDGE_VERSION without a leading v and mounts one writable host folder at /config with BRIDGE_CONFIG_DIR=/config. v1.0 does not support this layout; retain the legacy image Compose for v1.0.

For v1.1, start the container, confirm WAITING_FOR_INIT, then explicitly execute init through its console or docker compose exec. There is no automatic init. init imports do not queue ordinary notifications, including selected messages resumed by run. Partial init does not ignore unselected old mail. Never init during upgrades. See MAINTENANCE.md for stopped backups, schema migration and rollback; see NOTIFICATIONS.md for exact settings and TTL behavior.
