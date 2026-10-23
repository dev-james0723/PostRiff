# Customer Discord sender names: what the web UI needs from the backend, and how contract v2 answered it

Author: web/UI engineer. Branch `claude/discord-rc2-sendername-ui-20261023`, based on the RC2 integration line `5a94b4f2` (contains upstream sender-name commit `97b3956a`).

History: the first version of this file (commit `f79f2f25`) was written before the backend contract existed. The backend agent then published `docs/sender-name/UI-API-CONTRACT.md` (v2) on `claude/discord-rc2-sendername-20261023`; this file was read against it at that branch's head `1c61a4a7` and rewritten. The UI is built against v2. Read the contract at the branch head, not here, for anything the backend may have corrected since.

What the owner's decision asks of the UI: users set the name, preview what Discord really shows, and are told clearly (and without error styling) when the bot nickname cannot be changed and why. Webhook names are per send. The bot nickname is shared by everyone who uses the bot in a server; if it cannot be made safe across workspaces it is isolated by a switch, and the UI shows that state honestly.

## 1. How each original need was answered

| Original need | Contract v2 | What the UI does with it |
| --- | --- | --- |
| Refusals the UI can tell apart (the old code `discord_sender_name_required` covered everything) | `unavailable[].code` on a GET, `reasons[].code` on a refused POST, `reason` on a 400, distinct `code` per other case | One state per code, each with its own message in English, Traditional Chinese and Simplified Chinese and a stable test id `discord-sender-state-<code>`. 15 states, listed in `UI-ACCEPTANCE.md`. |
| Say whether editing is possible on the GET | `editable`, `unavailable[]` (server-ordered, may hold several) | Read-only view: name shown, field read-only, Save `aria-disabled` with its reason, one panel per listed reason in the server's order. No retry, no polling. |
| When a held change can be checked again | `retryAfterSeconds` on `edit_pending` and `rate_limited` | Shown as a wait and a clock time; "Check again" stays `aria-disabled` until then and wakes up by itself. |
| Stale save | 409 `discord_sender_name_required` (the only stale code) | `stale` state, Reload (a read), the next save uses the new fingerprint. |
| Name rules, the same messages as the server | `rules`, 400 `discord_sender_name_invalid` + `reason` | The browser applies the same ten rules in the server's order before saving (shared fixture, section 4); one message per rule; the server's `reason` is shown if it disagrees. |
| Preview facts | `preview.badge`, `audience`, `queuedPostsKeepApprovedName`, `queuedPostsFollowCurrentNickname`, `nameSource`, `observedName`, `observedAt`, `externalChange` | Badge text, which note is drawn, "as last checked" wording, a notice when someone else renamed the bot ("Rafii does not own this name"). |
| Bot nickname in the channel view | not provided | Still needed, see 2.2. |
| Switches before opening the dialog | only `feature` in the GET body | Still needed, see 2.1. |

Fields the UI reads and needs no change for: `connectionId, senderKind, scope, guildId, name, maxLength, fingerprint, state`, `Manifest.discordSenderName`, `ChannelView.discordSenderName` (webhook only), `RunItemDecision.discordSenderName`.

## 2. Still needed

### 2.1 The two switches on the connections page, without a request per card

The default state at the opening is both switches OFF (`feature.senderNames`, `feature.botNickname`), and every installation card shows an "Edit sender name" button. Today the card cannot know the switches before a dialog is opened, and the GET is throttled (12 per 10 minutes per connection, 40 per workspace), so the page must not read every card.

Requested, optional, no throttle, no Discord read: on the Discord entry of `GET /channels` `providers[]`, the same object the GET already returns as `feature`:

```json
"discordSenderNames": { "senderNames": false, "botNickname": false }
```

The UI already understands it (`ProviderView.discordSenderNames`): when a switch is off for the connection's kind it adds one line under the button ("Changing the sender name is switched off for now. Open Edit sender name to see why.") and keeps the button, which opens the read-only explanation. It also remembers, for the page session, the `feature` object of any GET it has already made and applies it to the other cards the same way. Without the provider field, the first card a person opens teaches the page.

### 2.2 The last observed bot nickname on the channel view

`channels.py` returns `discordSenderName` for webhooks only. The schedule dialog and the review cards therefore show a bot post's author as the generic label "Server bot" and say that Discord shows whatever nickname the bot has when the post is sent. Wanted, optional: for installations, the last nickname Rafii observed and when (`discordSenderName`, `discordSenderObservedAt`). The UI would then show that name with "as last checked". It never shows a made-up bot name.

## 3. Findings in the backend (not UI work; for the backend agent and the captain)

1. A lone UTF-16 surrogate in a name makes `name_problem` raise instead of answering: `name.encode('utf-16-le')` raises `UnicodeEncodeError` before the `control_or_format` test is reached, so a crafted POST (`"name": "a\ud800b"`) is a server error, not a 400. Reproduce: `name_problem('lone\ud800surrogate', 'bot')` at `1c61a4a7`. The editor never sends such a name (it refuses it as `control_or_format` first).
2. The contract table lists `sender_names_disabled` as applying to webhooks, the code applies it first to both kinds: a bot with the master switch off gets `sender_names_disabled`, never `bot_nickname_disabled`. The UI handles both; the copy for `sender_names_disabled` is written for both kinds.
3. `nickname_authority_other_workspace` means NEITHER workspace may change the nickname while both have the server connected. The owner's wording ("another workspace manages the nickname") describes a different rule. The UI copy states the implemented behaviour: another workspace also uses this server's bot, so Rafii lets no workspace change the shared nickname; the other workspace is never named.
4. `maxLength` is documented in code points but the server also keeps UTF-16 units within it (an emoji counts 2). The editor's counter shows the binding count (UTF-16 units) so it never disagrees with the server.
5. `rate_limited` always carries `retryAfterSeconds: 60`; the UI shows it as sent.

## 4. Known divergences between the editor's rules and the server's

* The editor copies `sender_names.name_problem`; `web/tests/fixtures/discord-sender-name-verdicts.json` holds 96 verdicts generated by running the real function (commit `1c61a4a7`), `tests/test_discord_sender_name_ui_contract.py` re-checks them against the server module (skipped, with a message, on a tree that does not have `name_problem` yet; run on the merged tree), and `web/tests/discord-sender-name.test.cjs` checks the editor against the same file.
* The reserved-word comparison was also compared code point by code point against the server's folding (every Unicode code point, both implementations). One range differs: 36 Unicode 16 characters (U+1CCD6 to U+1CCF9, outlined Latin letters and digits) that this browser engine folds to ASCII and the server's older Unicode tables do not. For those the editor is stricter than the server (it refuses a name the server would accept). Nothing the server refuses is accepted by the editor.
* The server remains the authority. If it disagrees, its `reason` is shown and the form stays (the fingerprint is still valid because nothing was sent to Discord).
