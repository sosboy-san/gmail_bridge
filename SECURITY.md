# 公開前の確認 / Security and publication

## 公開対象と秘密情報

公開対象はソース、翻訳、設定例、Docker定義、テスト、ドキュメントです。`tools/check_release.py --archive` は明示した公開ファイルだけをZIPへ入れます。作業用の仮想環境や検査用退避ファイルは入りません。ZIPを別の空フォルダに展開してGitの初回コミットを作ると、実運用データとの混入を避けられます。

`.gitignore` は未追跡ファイルを除外するもので、過去にコミットした秘密情報は消せません。`.dockerignore` は許可したアプリコードと翻訳・依存一覧だけをビルド対象にします。Dockerfileは設定や認証情報をCOPYしません。

公開前に所有者が次を最終確認してください。

- メールアドレス、IMAPホスト・ユーザー名・パスワード、個人名、会社名。
- OAuth client ID/secret、credentials.json、token.json、refresh/access token。
- ntfy topic・token・独自サーバーURL、Drive ID・共有リンク、NAS名・共有フォルダ・固有パス。
- DB、ログ、バックアップ、添付、メール原文、実メールを使ったテストfixture、画像・画面キャプチャ。
- Gitの全履歴、タグ、ブランチ、GitHub Actionsの出力・artifact、リリース添付。

自動検査は典型的なキー・メールアドレス・Drive URL・パスのパターンを検出しますが、任意の個人名や短いtopic・パスワードを完全には判定できません。候補の値そのものは出力せずファイル名・行・種類だけを表示します。公開対象に実データがなくても、後から編集した内容は再点検が必要です。

## 自分のコピーをGitHubへ公開する場合

1. `python tools/check_release.py --archive` で作ったZIPを、実運用ファイルのない新しいフォルダへ展開します。`LICENSE` の著作権表記を確認します。
2. そのフォルダで以下を実行し、ステージされたファイルを自分の端末で確認します。diffをチャットや公開Issueへ貼る必要はありません。

```bash
git init -b main
git add .
git status --short
git diff --cached --stat
git diff --cached
git ls-files
git check-ignore config.ini credentials.json token.json data/state.db logs/test.log
```

3. ファイル一覧と差分に実データがなければ初回コミットします。

```bash
git commit -m "Prepare Gmail Bridge public release"
```

4. GitHubの新規リポジトリ作成画面で **Private** を選びます。既存のREADMEやLICENSEを自動作成せず、画面に表示される自分のPrivateリポジトリURLをremoteに設定し、pushします。GitHub CLIを使う場合も必ず `--private` を付けます。

```bash
gh repo create gmail-bridge --private --source=. --remote=origin --push
```

5. Private上でCI（構文、lint、回帰テスト、Compose、Docker build）の成功を確認します。GitHub Actionsの出力にも実設定を出さないでください。
6. [RELEASE_NOTES.md](RELEASE_NOTES.md) の実接続・QNAP確認を終え、リポジトリ内と全履歴を最終点検します。
7. **所有者が最終確認した後にだけ** GitHubのVisibilityをPublicへ変更します。確認結果は [RELEASE_NOTES.md](RELEASE_NOTES.md) を参照してください。

## 漏えいに気づいた場合

公開削除だけでなく、該当IMAPパスワード、OAuth権限とトークン、ntfy token/topic等を失効・変更します。そのうえで履歴・artifact等の残存を確認します。公開Issueには実メールやトークンを貼らず、伏せた再現手順を使ってください。

本プロジェクトはメール内容をGmailへ、fallback時は添付をDriveへ送ります。取り込みログにはメールメタデータが含まれます。APIトークン、DB、ログ、バックアップはアクセスを制限して管理してください。IMAP証明書検証とcleanupの安全ガードは無効化しないでください。

## English

Publish only the source, catalogs, examples, tests, container definitions, and documentation. `python tools/check_release.py --archive` exports an explicit file set; it excludes local environments, runtime state and private configuration. Extract the archive into a fresh directory before creating your first commit.

Review account details, personal/company names, OAuth credentials/tokens, ntfy topics/tokens, Drive links/IDs, NAS paths, logs, databases, backups and real-mail fixtures. The scanner is heuristic and cannot prove the absence of arbitrary secrets. It reports locations and types rather than matched values. Gitignore does not remove secrets already in history.

Use the Git commands above to inspect staged content locally. Create a **Private** repository first, using `gh repo create ... --private` if desired. Check CI and complete live acceptance testing. Only the owner should change visibility to Public after final inspection of files, history and artifacts. See RELEASE_NOTES.md for validation results.

If a secret leaks, revoke/rotate it and then address history and artifacts. Never attach unredacted email, tokens, or logs to public issues. Gmail and Drive receive email content; protect local runtime data and use appropriate organizational authorization.

## v1.1の保存・通知

単一/configには秘密設定、更新可能なtoken、DB（送信元・件名を含む）、backup、logsをまとめて保存します。フォルダ全体を非公開にし、GitHubや公開添付へ置かないでください。sender/subject表示は既定falseです。送信元フィルタはFrom文字列の選別であり、送信者認証ではありません。ntfyの認証・ACLは利用者が管理します。RCは完全タグのみを公開しlatestを更新しません。設定・認証ファイルはイメージへCOPYしません。
