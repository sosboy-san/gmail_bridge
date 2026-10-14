# ntfy notifications — v1.1.0

English · [日本語](NOTIFICATIONS.md)

Mail import completion and notification delivery are independent. Failure, suppression or expiry never undo a successful Gmail import.

## Configuration

```ini
[notification]
enabled = true
provider = ntfy
server_url = https://ntfy.sh
topic =
token =
include_sender = false
include_subject = false
include_preview = false
sender_filter_mode = off
sender_filter_file = notification_senders.ini
ttl_minutes = 15
```

Set your own protected topic before enabling notifications. A token is optional according to server authentication. Missing required topic/invalid provider, URL, TTL or enabled filter is a configuration error; the example above is not ready to send until configured.

Defaults: enabled=false, provider=ntfy, server_url=https://ntfy.sh, empty topic/token, all three display switches=false, sender_filter_mode=off, sender_filter_file=notification_senders.ini. **Omitted ttl_minutes or zero means unlimited retries**; the new example explicitly recommends 15 minutes. Negative/noninteger TTL is invalid.

## Fixed positions and fallback text

| Field | Enabled | Disabled / missing |
| --- | --- | --- |
| Title | Sender: display name <address>, or address alone | Disabled: Gmail Bridge. Missing: Unknown sender (送信者不明 in Japanese) |
| Body first line | Subject | Disabled: the generic new-mail message. Missing: No subject (件名なし in Japanese) |
| Body second line | Optional preview | Disabled or missing: omitted |

Other fields never move into Title. All display switches off retains the legacy Gmail Bridge title and generic message. Each field has whitespace/control characters normalized and is limited to 200 characters with an ellipsis for truncation. UTF-8 JSON safely carries non-ASCII titles; they are not put directly in an HTTP header.

Sender address, display name, subject and preview are stored when mail is imported, **even when display is disabled**. Plain text is preferred; HTML-only messages use minimal standard-library text extraction. Attachments/attached messages and script/style content are excluded. There is no additional HTML parser dependency and no original-mail IMAP refetch on notification retry. Normal import and Drive fallback share registration and use original metadata.

Metadata and previews in SQLite/backups are private mail data. Enabling display sends the selected content to your configured ntfy server; protect its topic, ACLs, TLS and subscriptions. Sender filtering is selection based on From, not sender authentication or spoofing protection.

## Sender rules

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

Save as notification_senders.ini under the configured storage root. One address/domain per line; domains omit @. Matching is case-insensitive and exact, using **only the email address**, never the display name. No wildcard/regex or automatic subdomain matching: example.com does not match mail.example.com.

| Mode | Rule | Empty lists |
| --- | --- | --- |
| off | All senders | File not read |
| allowlist | Allowed match | Empty allow means none |
| blocklist | No blocked match | Empty block allows all determinable senders |
| combined | Allowed and not blocked | Empty allow means none; block always wins |

With filters enabled, missing/malformed/ambiguous From is suppressed. Missing filter file, unknown section/key or invalid syntax causes CONFIG_ERROR and defers new operations; invalid settings never silently become off. Disabled notifications or off mode do not read the file.

## TTL and states

TTL starts at the dedicated UTC timestamp saved on **Gmail API success**, not mail Date, first notification attempt, later label finalization or migration time. At the configured age, an unsent notification expires.

pending becomes sent (delivery succeeded), suppressed (excluded) or expired (TTL reached). Terminal states never revive after settings change. Failure keeps only the notification pending. Notifications disabled at import create no new queue entries; older pending entries remain and are reevaluated when enabled.

Before each send, reread and validate current settings, then check enabled, TTL, sender rules and send. Invalid configuration stops processing rather than advancing expiry with invalid settings. Omitted TTL logs a one-time compatibility message per DB. Positive TTL with an unknown old timestamp expires the notification; unlimited TTL permits sending. There is no grouped notification or quiet-hours feature.

Ordinary retries run only after IMAP connection/UIDVALIDITY checks succeed, even when there is no new mail. During large imports, opportunities occur after five processed messages or 30 seconds and at batch end; each opportunity permits up to ten requests and a 30-second start budget. Network timeouts mean completion can exceed 30 seconds. The first transport failure stops network requests for that opportunity; a 30-second retry wait applies within the batch. Import and notification processing are not parallel.

## Init and old databases

Init-selected UIDs never create ordinary notifications, even when interrupted and resumed by run, including fallback. Partial init leaves unselected old mail for later ordinary run/import/notification. Use init --all to import all existing mail silently or --from-now to ignore it.

Final import state and notification registration share a DB transaction. Schema migration preserves current notification states and TTL origins. Existing TTL uses valid imported_at, otherwise notification created_at; it never resets to migration time. Missing old sender/name/preview fields remain missing without remote refetch; display uses the table's fallback, and enabled sender filters suppress unknown addresses. Unknown old init provenance is not guessed.

Operational outage/recovery alerts are outside ordinary display/filter/TTL rules, but respect enabled and valid current configuration. Failed recovery alerts have no independent retry queue.
