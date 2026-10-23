# Customer Discord sender names: what the web UI needs from the backend

Author: web/UI engineer. Branch `claude/discord-rc2-sendername-ui-20261023`, based on the RC2 integration line `5a94b4f2` (contains upstream sender-name commit `97b3956a`).

History: the first version of this file (commit `f79f2f25`) was written before the backend contract existed. The backend agent published `docs/sender-name/UI-API-CONTRACT.md` (v2) on `claude/discord-rc2-sendername-20261023`; this file was rewritten against it and has now been re-read against the branch head `b03fc7ae` ("reviewer findings round 1"). **The contract document at that head is older than the code**: it was last changed in `e4cb8cbd`, and `b03fc7ae` changed behaviour the UI depends on (section 2). The UI follows the code at `b03fc7ae` and says so where the document disagrees.

What the owner's decision asks of the UI: users set the name, preview what Discord really shows, and are told clearly (and without error styling) when the bot nickname cannot be changed and why. Webhook names are per send. The bot nickname is shared by everyone who uses the bot in a server; if it cannot be made safe across workspaces it is isolated by a switch, and the UI shows that state honestly.

## 1. Needed from the backend

### 1.1 Required before the bot-nickname capability is switched on

**R1. The channel view must carry the nickname a review would freeze.** `campaigns._decide` (`b03fc7ae`, `campaigns.py` lines 788 to 791) refuses a Discord bot approval unless the request carries `discordBotNickname` equal to `frozen_bot_nickname(channel)[0]` (the last nickname the connection observed, or `null` when the bot has none). The web app builds that request from the channel view (`ChannelView`), exactly as it already sends `discordSenderName` for webhooks. `channels.py` (line 101) exposes `discordSenderName` for webhooks only and nothing for the bot, so the UI has no value to send. As soon as the bot-nickname capability is on and a connection has observed a nickname, every automation approval of a bot post is refused with `409 The Rafii bot's server nickname changed. Review it again.`

Requested: on the Discord entry of `GET /channels`, for installations, `discordBotNickname` (string or `null`; the same value `frozen_bot_nickname` returns, `null` while the capability is off or nothing is observed) and optionally `discordBotNicknameObservedAt` (epoch seconds). The UI already sends `discordBotNickname` in the approval when the field is present and omits it when it is absent (which is correct while the capability is off), shows it as "as last checked" in the schedule and approval previews, and shows the frozen value on approved manifests (`Manifest.discordBotNickname`).

**R2. The channel view's `discordSenderName` is the raw setting; the approval compares against the frozen one.** `_decide` compares the request's `discordSenderName` with `frozen_webhook_name(channel)`, which is `null` while the master switch is off, but `channels.py` returns the raw saved name. With the switch off and a saved name present, the UI sends the saved name and the approval is refused with `409 The webhook sender name changed. Review it again.` Requested: the channel view carries the value a review would freeze now (`frozen_webhook_name(channel)`), or an extra field with it. Not reachable at the opening (the webhook route is off), so this is needed before the webhook route opens.

### 1.2 The contract document needs to catch up with the code (`b03fc7ae`)

The UI is written to the code. These are in the code and missing from `UI-API-CONTRACT.md`:

| Item | In the code | What the UI does |
| --- | --- | --- |
| New unavailable reason `provider_unavailable` | `REASON_ORDER` third (after the two switches); HTTP 503 when it is the first reason; the request coordinator or the Discord rollout gates are not ready; only evaluated when both switches are on | State `provider_unavailable` with its own message: Rafii side, nothing for the customer to fix, Check again is offered |
| New error `discord_rate_delayed` | 429 with `retryAfterSeconds` (at least 1): the shared Discord request capacity has no room, nothing was changed | State `rate_delayed`, distinct from `rate_limited`, shows the wait and the clock time |
| `reset` in the POST body | `{fingerprint, confirmed: true, reset: true}` with no `name`; webhook only (a bot answers 400 `discord_sender_reset_unsupported`); success is the GET body with `saved: true` and `reset: true` | A "Use the webhook's own name" action on a webhook that has a custom name |
| `preview.queuedPostsFollowCurrentNickname` is gone | replaced by `preview.queuedBotPostsHoldIfNicknameChanges` (bot: true) | Bot preview says: an approved post is held, and nothing is sent, if the nickname is different when it is due. The old wording ("posts follow the current nickname") is no longer shown |
| A review freezes the bot nickname | manifest `discordBotNickname`; the dispatch preflight holds the post when Discord reports another nickname (`discord_bot_nickname_changed`, held, "Review the post again") | Notes in the preview, the schedule dialog and the editor; saving a new nickname warns that posts approved under the old one are held |
| Webhook names: any member who may manage connections | `authorizing()` is `True` for webhooks; `not_authorizing_member` now applies to the bot only | The `not_authorizing_member` copy is about the bot nickname and says webhook names are not affected |
| Provider flags | `providers[discord].discordModes.bot.nickname.enabled` and `.webhook.senderName.enabled` (`names_available`: master switch, nickname switch for bots, and provider readiness) | The card shows a one-line hint when a flag is `false`. `false` cannot tell "switched off" from "not ready", so the hint says "not available right now" and the dialog explains |
| Name rules: ZWJ and ZWNJ | A zero width joiner is accepted only between two symbols (emoji sequences, optionally with variation selectors and skin tones), a zero width non-joiner only between two letters or marks above U+024F (Persian, Indic and so on); anywhere else `control_or_format` | Mirrored exactly; new verdicts in the shared fixture |
| Audit log | the nickname PATCH carries `X-Audit-Log-Reason: Rafii shared bot nickname change (ref ...)` | The bot editor tells the person the server's audit log records the change as made by Rafii |
| Reconnect | the sender record (`discordSenderName`, revision, pending claim, observed nickname) is kept when a connection is re-saved; webhook names are carried across a re-created webhook | The UI promises nothing beyond what the GET says |

## 2. How each original need was answered

| Original need | Backend | What the UI does with it |
| --- | --- | --- |
| Refusals the UI can tell apart | `unavailable[].code` on a GET, `reasons[].code` on a refused POST, `reason` on a 400, distinct `code` per other case | One state per code, each with its own message in English, Traditional Chinese and Simplified Chinese and a stable test id `discord-sender-state-<code>`. 18 blocked states plus the editable one, listed in `UI-ACCEPTANCE.md`. |
| Say whether editing is possible on the GET | `editable`, `unavailable[]` (server-ordered, may hold several) | Read-only view: name shown, field read-only, Save `aria-disabled` with its reason, one panel per listed reason in the server's order. No retry, no polling. |
| When a held change can be checked again | `retryAfterSeconds` on `edit_pending`, `rate_limited` and `discord_rate_delayed` | Shown as a wait and a clock time; "Check again" stays `aria-disabled` until then and wakes up by itself. |
| Stale save | 409 `discord_sender_name_required` (the only stale code) | `stale` state, Reload (a read), the next save uses the new fingerprint. |
| Name rules, the same messages as the server | `rules`, 400 `discord_sender_name_invalid` + `reason` | The browser applies the same ten rules in the server's order before saving (shared fixture, section 4); one message per rule; the server's `reason` is shown if it disagrees. |
| Preview facts | `preview.badge`, `audience`, `queuedPostsKeepApprovedName`, `queuedBotPostsHoldIfNicknameChanges`, `nameSource`, `observedName`, `observedAt`, `externalChange` | Badge text, which note is drawn, "as last checked" wording, a notice when someone else renamed the bot ("Rafii does not own this name"). |
| The two switches on the connections page without a request per card | `providers[].discordModes.bot.nickname.enabled`, `.webhook.senderName.enabled` | Read from the provider view; also remembered from any GET already made in the page session (`feature`). |
| Bot nickname in the channel view | not provided | Still needed: see R1. |

Fields the UI reads and needs no change for: `connectionId, senderKind, scope, guildId, name, maxLength, fingerprint, state`, `Manifest.discordSenderName`, `RunItemDecision.discordSenderName`.

## 3. Findings in the backend (not UI work; for the backend agent and the captain)

1. A lone UTF-16 surrogate in a name makes `name_problem` raise instead of answering: `name.encode('utf-16-le')` raises `UnicodeEncodeError` before the `control_or_format` test is reached, so a crafted POST (`"name": "a\ud800b"`) is a server error, not a 400. Still present at `b03fc7ae` (`name_problem('a\ud800b', 'webhook')`). The editor never sends such a name (it refuses it as `control_or_format` first).
2. The contract table lists `sender_names_disabled` as applying to webhooks; the code applies it first to both kinds: a bot with the master switch off gets `sender_names_disabled`, never `bot_nickname_disabled`. The UI handles both; the copy for `sender_names_disabled` is written for both kinds.
3. `nickname_authority_other_workspace` means NEITHER workspace may change the nickname while both have the server connected. The owner's wording ("another workspace manages the nickname") describes a different rule. The UI copy states the implemented behaviour: another workspace also uses this server's bot, so Rafii lets no workspace change the shared nickname; the other workspace is never named.
4. `maxLength` is documented in code points but the server also keeps UTF-16 units within it (an emoji counts 2). The editor's counter shows the binding count (UTF-16 units) so it never disagrees with the server.
5. `rate_limited` always carries `retryAfterSeconds: 60`; the UI shows it as sent.
6. Saving a new bot nickname (in Rafii or natively in Discord) holds every bot post that was approved under the old one, at dispatch, until it is reviewed again. That is the intended safety, and the editor says so before the person saves; it also means a nickname change with a full queue can hold many posts at once. Nothing in the API tells the UI how many posts that would be, so the editor cannot say how many.
7. `provider_unavailable` and "switched off" both reach the card as `enabled: false`, so the card cannot name the cause. If the card should say which, the provider view would need the two switches separately (the shape the first version of this file asked for: `{senderNames, botNickname}`).

## 4. Known divergences between the editor's rules and the server's

* The editor copies `sender_names.name_problem`; `web/tests/fixtures/discord-sender-name-verdicts.json` holds the verdicts generated by running the real function (commit `b03fc7ae`), `tests/test_discord_sender_name_ui_contract.py` re-checks them against the server module (skipped, with a message, on a tree that does not have `name_problem` yet; run on the merged tree), and `web/tests/discord-sender-name.test.cjs` checks the editor against the same file.
* Unicode versions. Character categories come from the engine's Unicode tables: the browser's (Unicode 16.0 in Node 22 and current Chromium) and Python's (15.1.0 in the interpreter used here; the server's depends on its Python). Compared over every code point: 5,185 code points (all assigned only in Unicode 16.0) are control, format or unassigned for Python 15.1 and not for the browser, so the editor accepts a name with one of them and the server (if it runs Unicode 15.1) answers `control_or_format`; 36 Unicode 16 code points (U+1CCD6 to U+1CCF9, outlined Latin letters and digits) fold to ASCII in the browser and not in Python 15.1, so there the editor is stricter (it refuses a name the server would accept). Apart from these Unicode-version differences the editor and the server agree on every case of the shared fixture, and on the category tests and the reserved-word folding over every code point.
* The server remains the authority. If it disagrees, its `reason` is shown and the form stays (the fingerprint is still valid because nothing was sent to Discord).
