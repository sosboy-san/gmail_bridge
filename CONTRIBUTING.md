# 保守・翻訳 / Contributing

## 開発確認

Python 3.12で、専用の仮想環境を使います。テストは架空のメールと一時DB、モックを使い、実際のIMAP/Gmail/Drive/ntfyへ接続しません。

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app make_token.py tests tools
python -m ruff check app make_token.py tests tools
python -m unittest discover -s tests -v
python tools/check_release.py
docker compose -f docker-compose.example.yml config --quiet
BRIDGE_VERSION=1.1.0-rc.1 docker compose -f docker-compose.config.image.example.yml config --quiet
docker compose -f docker-compose.config.example.yml config --quiet
docker build -t gmail-bridge:check .
docker run --rm gmail-bridge:check python -m app.main --lang en --help
```

GitHub Actionsは同じオフラインテストとDockerビルドをLinux上で実行します。テスト用OAuthトークンやリポジトリSecretsの登録は不要です。WindowsではLinux固有のflock・タイムゾーン検証をskipし、Linux CIで検証します。CI成功は実サービス接続・NAS運用確認の代わりにはなりません。

## 翻訳の追加

1. `app/locales/en.json` をコピーし、言語コードのファイル名（例: `fr.json`）にします。
2. キーは変えず値だけを翻訳します。`{v0}`、`{v1}`などのプレースホルダとHTMLタグを維持します。`{v0}`の内容は対応する呼び出し箇所を参照してください。
3. `argparse.`で始まるキーはPython argparse用です。`%(name)s`、`%s`、`%r`などの形式を維持します。これらは通常の `{name}` 形式とは異なります。
4. `system.alert_title` と `system.recovery_title` はntfyのHTTP Titleヘッダ用です。現状の送信方式に合わせASCIIで記述してください。
5. `main.get_fallback_label.*` は保存済みラベル互換のため全言語で同じ既定値を保持してください。通常はconfigで明示したラベルを使います。
6. 回帰テストと `--lang 新言語 --help` を確認します。ファイルを追加するだけでCLIの候補に現れます。欠けたキーは英語にfallbackしますが、同梱カタログは全キーを翻訳してテストを通してください。

表示文言だけを翻訳し、DBのstatus、設定キー、API・IMAPコマンド、メールヘッダ名、元メール本文を翻訳しないでください。言語切り替えは過去のログや保存済みfallbackメールを書き換えません。

## 変更時の境界

Gmail importと通知の状態は独立です。通知失敗を理由にmessagesの完了状態を取り消さないでください。pending状態のGmail IDがある場合はimportではなく確定処理から再開します。UIDVALIDITY不一致、対象UID不在、対象外Deleted検出時の削除停止を維持してください。

DBスキーマや状態遷移、削除挙動を変える場合は、既存DBと異常終了からの復旧を含む検証を追加してください。依存パッケージは既存環境の固定版を維持しています。更新は別変更としてCI・実接続を確認します。

## English

Use Python 3.12 and the commands above. Tests use synthetic messages, temporary databases and mocked clients; they need no service credentials. CI also validates Compose and builds the Linux image. Linux-specific flock and timezone checks are skipped on Windows and tested on Linux.

To add a language, copy `en.json` to a new language-code filename and translate values without changing keys, placeholders, or HTML. `argparse.*` entries use percent-format placeholders; other messages use braces. Keep ntfy Title translations ASCII. Keep legacy default fallback-label entries unchanged because they identify stored labels. New catalogs are discovered automatically and missing keys fall back to English.

Preserve the separate import and notification states, pending Gmail-ID recovery, and all IMAP deletion guards. External error strings, database states, protocol commands and original mail are not translated. Test schema or workflow changes with existing state and interruption scenarios. Dependency upgrades should be reviewed separately from behavior changes.

## v1.1保守の入口

GitHubを正本として [MAINTENANCE.md](MAINTENANCE.md) の手順を使用します。RC配布は [DOCKER_RELEASE.md](DOCKER_RELEASE.md)。initとmigrationを分離し、TTLの専用UTC時刻と通知の終端状態を維持します。Dockerのない環境は静的確認のみと記録し、環境にDockerを導入して代替しません。英語資料の全面整備は仕様確定後の別工程です。
