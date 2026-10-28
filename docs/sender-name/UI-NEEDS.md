# Customer Discord sender names: what the web UI needs from the backend

Author: web/UI engineer. Branch `claude/discord-rc2-sendername-ui-20261023`, based on the RC2 integration line `5a94b4f2` (contains upstream sender-name commit `97b3956a`).

History: the first version of this file (commit `f79f2f25`) was written before the backend contract existed. The backend agent published `docs/sender-name/UI-API-CONTRACT.md` (v2) on `claude/discord-rc2-sendername-20261023`. This file was rewritten against it twice and has now been read against the branch head `7866c73b`, whose contract text was brought up to the code (`0724868e` and later). The UI follows the contract at that head; read the contract at the branch head, not here, for anything the backend may have changed since.

What the owner's decision asks of the UI: users set the name, preview what Discord really shows, and are told clearly (and without error styling) when the bot nickname cannot be changed and why. Webhook names are per send. The bot nickname is shared by everyone who uses the bot in a server; if it cannot be made safe across workspaces it is isolated by a switch, and the UI shows that state honestly.

## 1. Needed from the backend

### 1.1 R1: the nickname an automation approval has to echo has no source in the UI

`campaigns._decide` (`campaigns.py`, lines 788 to 791 at `7866c73b`) refuses a Discord bot approval from an automation run unless the request carries `discordBotNickname` equal to what a review would freeze now (`frozen_bot_nickname(channel)[0]`: the last nickname the connection observed, `null` when the bot has none). The contract says the same ("Automation approvals carry the name or nickname the person saw: `discordSenderName` for a webhook, `discordBotNickname` for a bot"). For a webhook the UI has the value: the channel view carries `discordSenderName`. For a bot it has none: the channel view deliberately carries no bot nickname (a backend test asserts it), the editor's GET returns `observedName` (nickname, else the bot's global name or username, which cannot be told apart from "no nickname"), and the run item carries nothing.

Effect: while the nickname capability is off (the default, and the opening) nothing is frozen, the approval carries no nickname, and the comparison passes. Once the capability is on and a connection has observed a nickname, every automation approval of a bot post is refused with `409 The Rafii bot's server nickname changed. Review it again.`, because the UI cannot send the value.

Needed before the nickname capability is switched on, one of: (a) a carrier for the value in the data the approval dialog already has (for example a field on the run item for a Discord bot target, `discordBotNickname`, string or `null`, absent when nothing would be recorded), or (b) the server fills the value in itself for this check, since the dispatch preflight already holds a post whose nickname differs. The UI already sends `discordBotNickname` in the approval when the channel view has the field, and omits it otherwise; that plumbing is inert until a carrier exists (`ChannelView.discordBotNickname` in `web/src/lib/api/types.ts`; if the carrier is the run item, the UI needs a one-line change to read it there).

### 1.2 R2: the webhook name the approval compares against

`_decide` compares the request's `discordSenderName` with `frozen_webhook_name(channel)`, which is `null` while the master switch is off, but the channel view returns the raw saved name. With the switch off and a saved name present, the UI sends the saved name and the approval is refused with `409 The webhook sender name changed. Review it again.` Needed: the channel view carries the value a review would freeze now, or an extra field with it. Not reachable at the opening (the webhook route is off); needed before the webhook route opens.

## 2. The contract, item by item, and what the UI does

All of these are in the contract text at `7866c73b`; this table is only the UI's side of them.

| Contract item | What the UI does |
| --- | --- |
| Provider view: `discordModes.bot.nickname.enabled`, `discordModes.webhook.senderName.enabled` (switches and readiness folded together) | When a flag is `false` the card has no editor: its button says "Why can't I change this?" and a one-line note under it says it is not available right now (for a bot, also that the nickname is shared by everyone who uses the bot in the server). No request is made until the person presses it; then one GET (which makes no Discord request) shows the exact reason. `false` cannot tell "switched off" from "not ready", so the note claims no cause. |
| `feature` in every GET body | Remembered for the page session; any other card of the same kind then gets the same button and note. |
| `unavailable[].code`, 10 stable codes | One state per code, each with its own message in three languages and a stable test id `discord-sender-state-<code>`. |
| POST refusals: `discord_sender_write_unconfirmed` ("may have changed"), `discord_sender_write_refused` ("unchanged, nothing waits"), `discord_sender_edit_pending`, `discord_rate_delayed`, `rate_limited`, `discord_sender_name_required` (the only stale code), 503 `provider_unavailable`, `discord_connection_required` (409 reconnect, 503 provider paused) | Own states: `write_unconfirmed`, `write_refused`, `edit_pending` (countdown), `rate_delayed` and `rate_limited` (both with their wait), `stale`, `provider_unavailable`, `reconnect_required`. No state ever resends a write; "Check again" and "Reload" are reads. |
| `reset: true` (webhook only) | "Use the webhook's own name" on a webhook that has a custom name; never offered for a bot. |
| `preview.queuedBotPostsHoldIfNicknameChanges`, `manifest.discordBotNickname`, hold at dispatch | The bot preview says an approved post is held, and nothing is sent, if Discord shows another nickname when it is due; the editor warns before saving that posts approved under the old nickname will be held. Review cards show the recorded nickname (or "no nickname"). Nothing is claimed where nothing is recorded. |
| Who may edit: any member with `manage_connections` edits a webhook name; only the installing member changes a bot nickname | `not_authorizing_member` is bot copy, and says webhook names are not affected. The card control is not rendered at all for a member without `manage_connections`. |
| Held posts after the master switch goes off | The webhook read-only view says a post approved with a custom name stays held after the feature is back on until the person acts on it in the queue. |
| Name rules including zero width joiners | Mirrored exactly; 116 shared verdicts (section 5). |
| `X-Audit-Log-Reason` on the nickname PATCH | The UI makes no claim about Discord's audit log: whether Discord logs a member's change to its own nickname is not known here (owner check 13 in `UI-ACCEPTANCE.md`). |
| Reconnect keeps the saved name | The UI promises nothing beyond what the GET says. |

Where the UI differs from the contract's advice: the contract says "when false, do not render the editor and do not call the routes". The UI does not render the editor, and does not call the routes on its own; it does call the GET when the person presses "Why can't I change this?", because the owner's decision asks that the person is told why, with the reason the server knows, and that GET is documented as answering without any Discord request.

## 3. How each original need was answered

| Original need | Backend | What the UI does with it |
| --- | --- | --- |
| Refusals the UI can tell apart | `unavailable[].code` on a GET, `reasons[].code` on a refused POST, `reason` on a 400, distinct `code` per other case | One state per code. 19 blocked states plus the editable one, listed in `UI-ACCEPTANCE.md`. |
| Say whether editing is possible on the GET | `editable`, `unavailable[]` (server-ordered, may hold several) | Read-only view: name shown, field read-only, Save `aria-disabled` with its reason, one panel per listed reason in the server's order. No retry, no polling. |
| When a held change can be checked again | `retryAfterSeconds` on `edit_pending`, `rate_limited` and `discord_rate_delayed` | Shown as a wait and a clock time; "Check again" stays `aria-disabled` until then and wakes up by itself. |
| Stale save | 409 `discord_sender_name_required` | `stale` state, Reload (a read), the next save uses the new fingerprint. |
| Name rules, the same messages as the server | `rules`, 400 `discord_sender_name_invalid` + `reason` | The browser applies the same ten rules in the server's order before saving; one message per rule; the server's `reason` is shown if it disagrees, and the form stays. |
| Preview facts | `preview.badge`, `audience`, `queuedPostsKeepApprovedName`, `queuedBotPostsHoldIfNicknameChanges`, `nameSource`, `observedName`, `observedAt`, `externalChange` | Badge text, which note is drawn, "as last checked" wording, a notice when someone else renamed the bot ("Rafii does not own this name"). |
| The two switches on the connections page without a request per card | `providers[].discordModes.bot.nickname.enabled`, `.webhook.senderName.enabled` | Section 2, first row. |

## 4. Findings in the backend (not UI work; for the backend agent and the captain)

1. A lone UTF-16 surrogate in a name makes `name_problem` raise instead of answering: `name.encode('utf-16-le')` raises `UnicodeEncodeError` before the `control_or_format` test is reached, so a crafted POST (`"name": "a\ud800b"`) is a server error, not a 400. Still present at `7866c73b` (`name_problem('a\ud800b', 'webhook')`). The editor never sends such a name (it refuses it as `control_or_format` first).
2. `nickname_authority_other_workspace` means NEITHER workspace may change the nickname while both have the server connected. The owner's wording ("another workspace manages the nickname") describes a different rule. The UI copy states the implemented behaviour: another workspace also uses this server's bot, so Rafii lets no workspace change the shared nickname; the other workspace is never named.
3. `maxLength` is documented in code points but the server also keeps UTF-16 units within it (an emoji counts 2, a family emoji 8). The editor's counter shows the binding count (UTF-16 units) so it never disagrees with the server.
4. `rate_limited` carries `retryAfterSeconds: 60` as sent; the UI shows it as sent.
5. Saving a new bot nickname (in Rafii or natively in Discord) holds every bot post that was approved under the old one, at dispatch, until it is reviewed again. That is the intended safety, and the editor says so before the person saves; it also means a nickname change with a full queue can hold many posts at once. Nothing in the API tells the UI how many posts that would be, so the editor cannot say how many.
6. `provider_unavailable` and "switched off" both reach the card as `enabled: false`, so the card cannot name the cause. If the card should say which, the provider view would need the two switches separately.
7. The contract says the server's audit log shows each Rafii nickname change with a reason text. Discord may not write an audit entry when a member changes its own nickname (the bot does so through `PATCH /guilds/{id}/members/@me`); nothing here can show either way. Owner check 13.

## 5. Known divergences between the editor's rules and the server's

* The editor copies `sender_names.name_problem`; `web/tests/fixtures/discord-sender-name-verdicts.json` holds 116 verdicts generated by running the real function (backend `b03fc7ae`, unchanged at `7866c73b`), `tests/test_discord_sender_name_ui_contract.py` re-checks them against the server module and checks the reason order and the POST body keys (skipped, with a message, on a tree that does not have `name_problem` yet; run on the merged tree), and `web/tests/discord-sender-name.test.cjs` checks the editor against the same file.
* Unicode versions. Character categories come from the engine's Unicode tables: the browser's (Unicode 16.0 in Node 22 and current Chromium) and Python's (15.1.0 in the interpreter used here; the server's depends on its Python). Compared over every code point: 5,185 code points (all assigned only in Unicode 16.0) are control, format or unassigned for Python 15.1 and not for the browser, so the editor accepts a name with one of them and the server (if it runs Unicode 15.1) answers `control_or_format`; 36 Unicode 16 code points (U+1CCD6 to U+1CCF9, outlined Latin letters and digits) fold to ASCII in the browser and not in Python 15.1, so there the editor is stricter (it refuses a name the server would accept). Apart from these Unicode-version differences the editor and the server agree on every case of the shared fixture, and on the category tests and the reserved-word folding over every code point.
* The server remains the authority. If it disagrees, its `reason` is shown and the form stays (the fingerprint is still valid because nothing was sent to Discord).
