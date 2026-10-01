# ntfy通知設定（v1.1）

メール取り込みは確実性優先、通常通知は鮮度優先です。通知の失敗・抑止・期限切れでGmailの取り込み完了状態を取り消しません。この資料はapp/config.py、notification_metadata.py、notification_service.py、main.py、state.pyの実装に対応します。

## 設定例と既定値

```ini
[notification]
enabled = true
provider = ntfy
server_url = https://ntfy.sh
topic =
token =
include_sender = false
include_subject = false
sender_filter_mode = off
sender_filter_file = notification_senders.ini
ttl_minutes = 15
```

topicは自分の保護されたtopicを設定します。tokenはサーバーで必要ならBearer tokenを指定します。有効なのにtopic等が不足している例をそのまま運用しないでください。

| キー | 未指定時 | 意味 |
| --- | --- | --- |
| enabled | false | 通常通知と障害/復旧通知の有効化 |
| provider | ntfy | ntfyのみ |
| server_url | https://ntfy.sh | 利用するntfyサーバー |
| topic / token | 空 | topicは有効化時必須、tokenは認証に応じて使用 |
| include_sender / include_subject | false / false | 通常通知への送信元/件名表示 |
| sender_filter_mode | off | off / allowlist / blocklist / combined |
| sender_filter_file | notification_senders.ini | 有効な送信元フィルタのINI。保存ルート内を指定 |
| ttl_minutes | 0 | 0または未指定は無期限。新規設定例は15分。負数・非整数は設定エラー |

通知本体は固定の新着文に、選択した項目だけを追加します。送信元はFromの**メールアドレスのみ**、表示名は含みません。件名と送信元はUTF-8で各200文字以内、省略時は末尾に…を付けます。改行・制御文字は除去し、欠落項目は省略します。メール本文は送りません。HTTP TitleはASCIIのGmail Bridgeです。

元メールのヘッダを既存の取得処理で解析し、Gmail API成功時点でsender/subjectと通知用UTC時刻をDBに保存します。通知のためだけに元メールを再取得しません。Fromがない、不正、複数アドレスなど、一意に判定できない場合はフィルタ有効時にsuppressedとなります。offなら送信元がなくても固定文で通知できます。

sender/subject表示は認証のないtopicでも情報を公開し得るため、既定falseです。送信元フィルタはFrom文字列の選別であり、送信者の認証・なりすまし防止ではありません。TLS、ACL、購読認証、reverse proxy等は利用者のntfyサーバー側で管理します。

## 許可・除外リスト

```ini
[allowlist]
addresses =
    customer@example.com
domains =
    partner.example.com

[blocklist]
addresses =
    newsletter@partner.example.com
domains =
    advertising.example.com
```

外部ファイルをnotification_senders.iniとして保存します。1行1アドレスまたはドメインです。domainsには@を付けず、ドメインだけを記載します。大文字小文字は区別せず、アドレス・ドメインの**完全一致**のみです。正規表現・ワイルドカードは使えません。example.comはmail.example.comに一致しません。サブドメインは明示登録します。

| モード | 通知条件 | 空リスト |
| --- | --- | --- |
| off | 全件 | ファイルを読まない |
| allowlist | 許可に一致 | allowが空なら通知なし |
| blocklist | 除外に一致しない | blockが空なら判定可能な全送信元 |
| combined | 除外に一致せず許可に一致 | allowが空なら通知なし |

**combinedでは除外優先**です。個別アドレスを許可しても、そのドメインが除外されていれば通知しません。allowlistモードは許可だけ、blocklistモードは除外だけを使います。例の空リストをそのままallowlistで使うと通知されません。

通知無効またはoffではリストファイルを読みません。有効なフィルタでのファイル欠落、未知section/key、不正な記述はCONFIG_ERRORとなり新規処理を停止・待機します。不正設定をoffへfallbackしません。修正後に次周期で復帰します。

## TTLと通知状態

TTLは**Gmail API成功確認時の専用UTC時刻**から測ります。ラベル処理・再試行・DB更新で起点を上書きしません。初回送信時や元メールのDateは起点ではありません。15分指定なら、取り込み成功から15分に達した未送信通知はexpiredです。

| 状態 | 意味 |
| --- | --- |
| pending | 未送信。現在の設定/TTLで再判定できる |
| sent | ntfy送信成功 |
| suppressed | 送信元条件等により意図的に送らなかった |
| expired | 期限切れ。異常ではなく正常な終了状態 |

pendingから他3状態へ進み、sent / suppressed / expiredは後の設定変更でも復活しません。**既存configでTTL未指定、または0なら従来互換の無期限再送**です。未指定の場合はDBごとに一度だけNOTIFICATION_CONFIGの情報ログを出します。長期障害後の大量通知を避けたい場合は15を明示してください。15でもTTL内に大量の新着があれば複数通知は発生します。まとめ通知やquiet hoursはありません。

送信機会では最新の完全な設定を読み、通知有効性を確認 → TTL → フィルタ → ntfy送信、の順に判定します。各通知の直前にも再読込します。設定不正ではその処理を止めるため、不正INIを無視して期限判定だけ進める仕様ではありません。

通知失敗はpendingを維持し、Gmail状態に影響しません。通知を無効にしている間は新たにキュー登録せず、既存pendingは残ります。再有効化時は現在のTTLとフィルタで判定します。IMAP接続・UIDVALIDITY確認が成功してから通知処理に入るため、IMAP障害中の通常通知再送は待ちます。

## init、Drive fallback、大量取り込み、旧DB

- init由来の通常通知は生成しません。選択したUIDの由来を保存するため、途中で中断しrunで再開しても抑止します。Drive fallbackでも同じです。これはv1.0からの意図的な変更です。
- 部分initの対象外に残った過去メールは、後のrunで通常取り込み・通常通知の対象になり得ます。全過去メールを通知せず取り込むにはinit --allを使います。
- 通常importとDrive fallbackは同じ通知登録経路を使用し、最終取り込み状態と通知登録を同じDB transactionで確定します。fallback通知も元メールの送信元・件名を使います。
- runの大量取り込み中は5件処理または30秒経過後、バッチ末尾にも通知機会を設けます。1回の機会で最大10送信要求、30秒の開始予算です。個々の通信timeoutがあるため厳密な30秒以内完了を保証しません。最初の通信失敗後はその機会の送信を止め、バッチ内は30秒の再試行待ちを置きます。取り込みと通知処理は並列ではありません。
- v1.0 DBのsender/subjectは元メール再取得で補完しません。フィルタoffなら固定文、onでsender不明ならsuppressed。表示を有効にしても欠落項目は省略します。
- 旧DBのTTL時刻は有効なimported_at、なければ通知created_atから移行し、migration現在時刻へ更新しません。時刻不明の旧pendingは正のTTLではexpired、無期限なら送信可能です。旧レコードのinit由来が不明な場合は推測で抑止せず、既存通知状態を維持します。

障害・復旧通知は通常通知のsender/subject、送信元フィルタ、TTLの対象外です。enabledには従い、現在設定が不正なら送信しません。既存の復旧通知失敗は独立して再送されない仕様を維持しています。
