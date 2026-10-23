# Customer Discord sender names: what the web UI needs from the backend

Author: web/UI engineer. Branch `claude/discord-rc2-sendername-ui-20261023`, based on the RC2 integration line `5a94b4f2` (contains upstream sender-name commit `97b3956a`).

Status: written before the backend contract (`docs/sender-name/UI-API-CONTRACT.md` on `claude/discord-rc2-sendername-20261023`) existed. Nothing below is agreed yet. The UI is built so that every item is optional: when a field or code is missing it falls back to the coarse behaviour in section 6 and says so honestly (it never invents a reason). When the contract lands, section 8 is replaced by a reconciliation table (UI name, backend name, status).

The owner's decision this serves (verbatim intent): users set the name, preview what Discord really shows, and are told clearly when the bot nickname cannot be changed. Webhook names are per send and come first. If the bot nickname cannot be made safe across workspaces it is isolated by a switch, and the UI must show that state honestly (not a broken form).

## 1. What the UI already reads and needs no change

| Where | Field | Used for |
| --- | --- | --- |
| `GET/POST /channels/{id}/discord-sender-name` | `connectionId, senderKind ('bot'|'webhook'), scope, guildId, name, maxLength (80 or 32), fingerprint, state` | editor, limit, stale-save guard |
| `ChannelView` (`GET /channels`) | `discordConnectionKind`, `discordSenderName` (webhook only today) | card line, schedule and review preview |
| `Manifest` | `senderKind`, `discordSenderName` (frozen webhook name) | review preview |
| `RunItemDecision` | `discordSenderName` | automation history |
| Errors | `ApiError.status`, `ApiError.code`, `ApiError.message`, `nextAction` | recovery |

Existing codes the UI already understands: `discord_sender_edit_pending` (ambiguous write), `step_up_required` and `security_step_up_required` (fresh session), `discord_sender_name_required` (everything else).

## 2. The problem: refusals are not machine readable

In `sender_names.py` every refusal goes through `fail()`, which always uses the code `discord_sender_name_required` with status 400, 401, 403, 404 or 409. The UI therefore cannot tell these apart:

* "not the member who authorized this connection" (403) vs "authorizer lacks Manage Nicknames or the bot lacks Change Nickname" (403, one combined message for two different causes) vs "this workspace cannot change sender settings" (403)
* "settings changed since you opened the editor" (409 fingerprint or competing claim) vs "reconnect this connection" (409) vs "Discord returned a different bot" (409)
* a rejected name (400) vs a missing shared-server confirmation (400)

The messages are English prose and must never be parsed. Section 3 asks for stable codes.

## 3. Needed from the backend

### 3.1 Error body: `reason`, `retryAt`, `issue`

Non-2xx body, in addition to `error` and `code`:

```json
{ "error": "...", "code": "discord_sender_name_unavailable", "reason": "member_lacks_manage_nicknames" }
{ "error": "...", "code": "discord_sender_name_stale" }
{ "error": "...", "code": "discord_sender_edit_pending", "retryAt": 1792750000 }
{ "error": "...", "code": "discord_sender_name_invalid", "issue": "reserved_word" }
{ "error": "...", "code": "discord_sender_shared_unconfirmed" }
```

* `retryAt` is epoch seconds: the claim's `expiresAt` (today `clock + 120`). It lets the UI say when the next check is possible. Without it the UI says "about two minutes".
* `issue` is one of `empty | surrounding_space | too_long | not_nfc | control_character | reserved_word`. The UI validates locally with the same rules before sending (limit counted in Unicode code points, `NFC`, categories `C*` plus U+2028/U+2029, webhook names may not contain `discord` or `clyde` after case folding), so `issue` is only needed when the server disagrees with the browser.
* `reason` values (the whole vocabulary the UI renders; unknown values render the generic "failed" state):

| `reason` | Meaning | Who can fix it | Applies to |
| --- | --- | --- | --- |
| `feature_disabled` | Customer sender names are off for this environment or workspace | Rafii | both |
| `bot_nickname_disabled` | Bot nickname editing is isolated by the platform switch; webhook names still work | Rafii | bot |
| `not_authorizing_member` | The viewer is not the member who authorized this connection | that member | both |
| `member_lacks_manage_nicknames` | Live check: the authorizer has none of owner, Administrator, Manage Nicknames | a Discord server administrator | bot |
| `bot_lacks_change_nickname` | Live check: the bot has neither Administrator nor Change Nickname in this server | a Discord server administrator | bot |
| `nickname_managed_elsewhere` | Another Rafii workspace holds the nickname for this server's bot member. No identifier of that workspace may be sent. | nobody here | bot |
| `reconnect_required` | Credential, generation, scope or authorizing identity no longer match, or the connection is revoked | the authorizing member | both |

`discord_sender_name_stale` covers a fingerprint mismatch and a competing edit claim. `discord_sender_edit_pending` is unchanged except for `retryAt`.

### 3.2 `GET .../discord-sender-name`: say whether editing is possible

Add to the 200 body:

```json
"availability": { "editable": true }
"availability": { "editable": false, "reason": "bot_lacks_change_nickname" }
"availability": { "editable": false, "reason": "edit_pending", "retryAt": 1792750000 }
"nameSource": "discord" | "saved",
"checkedAt": 1792749700
```

Preferred: return 200 with `editable:false` whenever the current name could still be read (the editor then shows the name read-only next to the explanation). Acceptable: a 403/409 with `code` and `reason` from 3.1 and no profile. The UI handles both.

### 3.3 Provider flags (so the card and editor can explain before any round trip)

On the Discord entry of `GET /channels` `providers[]`:

```json
"discordSenderNames": {
  "webhook": { "enabled": true },
  "bot": { "enabled": false, "reason": "bot_nickname_disabled" }
}
```

`reason` is `feature_disabled` or `bot_nickname_disabled`. Absent means "unknown, find out on open".

### 3.4 Bot nickname on the channel view

`channels.py` returns `discordSenderName` only for webhooks (`None` for bots). For the schedule and review previews the UI would like, for bot connections, the last observed nickname and when it was observed:

```json
"discordSenderName": "Rafii", "discordSenderObservedAt": 1792749700
```

Without it the bot preview shows the generic label "Server bot" and says the nickname is whatever the bot has in this server when the post is sent. It never shows a made-up bot name. The nickname is not secret (every member of the server sees it).

## 4. Behaviour the UI relies on (please keep)

* `fingerprint` changes whenever anything the editor depends on changes, and a POST with an old fingerprint is refused before any provider write (already true).
* A GET never performs a provider write and a reload never retries a write (already true: `observe(reconcile=True)` only reads; the UI also never sends a second POST after an error).
* The two-minute ambiguity window is reported through `discord_sender_edit_pending`; the UI offers "Check again", which is a GET.

## 5. Not needed (and not wanted)

* The identity, name or id of any other workspace (`nickname_managed_elsewhere` must stay anonymous).
* Discord permission bitfields, role names or user ids in error bodies.

## 6. What the UI does today when the backend does not send the above

| Backend says | UI state |
| --- | --- |
| `discord_sender_edit_pending`, no `retryAt` | "still being confirmed", wait about two minutes, then Check again |
| `step_up_required` / `security_step_up_required` | "confirm it's you" with the sign-in-again button |
| 403 with no `reason` | "permission unclear": lists the three possible causes (authorizing member, Manage Nicknames, Change Nickname) |
| 409 or other with no `reason` | "could not be verified": Reload the current name, no retry |
| provider flag absent | opens the editor and decides from the GET |

## 7. Examples the synthetic harness will use (for the contract reconciliation)

One 200 body and one error per state in section 3.1, exactly as written there. If the contract uses other names, only `web/src/lib/channels/discord-sender-name.ts` (`classifySenderRefusal`, `classifySenderProfile`) changes.

## 8. Reconciliation with `UI-API-CONTRACT.md`

Not available yet at the time of writing (fetched `origin` at 2026-10-23 06:19Z; the backend branch was not published).
