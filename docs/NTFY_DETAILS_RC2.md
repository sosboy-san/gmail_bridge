# ntfy詳細通知（rc.2候補・未公開）

`include_sender`・`include_subject`・`include_preview` の既定値はすべてfalse。

| 設定 | ON | OFF |
| --- | --- | --- |
| include_sender | Titleに表示名 <アドレス>。表示名なしはアドレスのみ、アドレスなしは送信者不明 | TitleはGmail Bridge |
| include_subject | Body先頭行に件名。欠落は件名なし | Body先頭行は新着メールが1件あります |
| include_preview | Body次行に本文プレビュー。欠落は省略 | 行を省略 |

全項目OFFは従来表示を維持。項目を別の位置へ繰り上げない。
各項目は改行・タブを空白へ置換し、制御文字を除去、空白を整理して200文字以内に制限。
送信元フィルタは表示名を含まない元アドレスのみで判定する。

元メールからtext/plainを優先して本文を抽出する。HTMLのみは標準HTMLParserでタグとscript/styleを除き、外部資源を取得しない。添付と添付メールは除外。
本文全体の保存は行わず、短いプレビューと表示名をGmail import成功直後にDBへ保存する。表示OFFでも保存するため、後から表示設定を変更して再送できる。通知再送のためのIMAP再取得は行わない。
通常import・Drive fallbackとも元メールのメタデータを保存し、同じ通知登録・送信処理を使用する。

ntfy送信はサーバーのルートURLへUTF-8 JSONでPOSTする。topic/title/message/clickはJSON、Bearer認証はHTTPヘッダー。既存のtimeoutと成功判定を維持。

DB schema 2はmessagesにnotification_sender_nameとnotification_previewを追加。schema 0/1から検証済みbackup後にトランザクション移行し、失敗時はrollback。既存の通知状態・試行回数・日時・TTL起点を保持する。旧データの新項目はNULLとし元メールを再取得しない。
schema 2はRC1では開けない。戻す場合は対応する更新前backupを復元する。

RC1のtag・Release・Dockerイメージは変更しない。この実装は未公開。
