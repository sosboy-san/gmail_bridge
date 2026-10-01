# v1.1.0 Phase 2 実装記録（開発中）

この段階では正式リリースではありません。Phase 1の保存先・共通ロックに、DB検証と移行を追加しました。通知の表示・フィルタ・TTL判定は後続Phaseで実装します。

## DBを開く方針

- `state.connect()` は既存DBだけを開きます。DBなしは `DatabaseMissing` / `[WAITING_FOR_INIT]`。
- 明示的な `init` だけが `state.connect(create=True)` でDBを新規作成します。
- 有効なDBでも対象mailboxの初期化記録がなければ `DatabaseUninitialized` / `[WAITING_FOR_INIT]`。`run` と有効な `cleanup` はIMAP接続前に拒否します。`status` は未初期化の確認に使えます。
- 既存の空ファイル、破損、未知のテーブル・列構造・スキーマ番号は `DatabaseError` / `[DB_ERROR]`。init待ちとして扱わず、DBの置換や再初期化もしません。
- DB移行はmailboxの初期化とは独立しています。移行で初期化記録を追加・更新しません。

## スキーマと移行

アプリのリリース番号とは独立した `PRAGMA user_version = 1` を使用します。正式版v1.0.0のDBは `user_version = 0` です。今後、永続構造を変更する場合はスキーマ番号を進め、専用の移行を追加してください。

追加列:

| テーブル | 列 | 用途 |
| --- | --- | --- |
| messages | notification_sender | 通知用の送信元アドレス |
| messages | notification_subject | 通知用の件名 |
| messages | notification_imported_at | 通知TTL用の専用時刻 |
| messages | import_origin | init中断後の再開も含む取り込み経路の識別 |
| notifications | notification_imported_at | 通知の専用時刻 |

既存メールの送信元・件名はNULLのままです。元メールを再取得しません。旧DBの取り込み経路は特定できないため `unknown` とし、推測しません。新しい取り込みでこれらを記録する処理は後続Phaseで追加します。

移行前に構造・integrityを検証し、SQLiteのオンラインbackup APIで `backups/db/migrations/` に一意なバックアップを作成します。これは通常の日次バックアップとは別で、自動ローテーションの対象外です。WALに存在するcommit済みデータも含みます。

バックアップ成功後、`BEGIN IMMEDIATE` 内で追加列・旧時刻の引き継ぎ・移行後の構造検証・スキーマ番号更新を行い、commitします。失敗時はrollbackし、`[DB_MIGRATION_ERROR]` で停止します。バックアップ失敗時は移行を開始しません。

既存の通知専用時刻は、対応メールの有効な `imported_at`、次に通知の有効な `created_at` の順で採用します。タイムゾーン付きの時刻をUTCへ正規化し、両方不明ならNULLのままです。移行時刻では補いません。既存列・状態・削除予約・Drive情報は保持します。

既存v0.1の `processed_messages` 変換も同じトランザクションへ含めます。通常のCLI経由では、init/run/cleanup/statusの共通ロックを保持して検証・移行を行います。内部の `state.connect()` を新たな実行経路から呼ぶ場合も、必ず共通ロックを取得してください。

## 検証と残りの作業

正式版v1.0.0タグから固定したスキーマで、既存全列の保持、バックアップの読取・WAL反映、途中失敗のrollback、再試行、二重移行防止、DB異常の拒否、共通ロック競合を検証しました。

Phase 3では常駐サービスの待機・復帰と設定エラー処理を整えます。Phase 4では通知登録の一本化、成功時刻とメタデータの保存、init通知の抑止、フィルタ・TTL・終端状態を実装します。

実運用DBとDockerコンテナでの検証はまだ行っていません。commit/push/正式公開もこのPhaseの実施範囲に含みません。
