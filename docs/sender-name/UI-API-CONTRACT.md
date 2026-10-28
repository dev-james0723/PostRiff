# Discord sender names: UI / API contract (v2)

Status: implemented on branch `claude/discord-rc2-sendername-20261023`; this text was written first and then corrected to what
the code does. The UI agent should read the branch head, not an older copy. Every field and code below is asserted by
`tests/test_discord_sender_name_routes.py` (shape, codes, reasons), `..._claims.py` (claim, refusal and gate codes),
`..._wire.py` (what reaches Discord) and `..._postgres.py` (the same against PostgreSQL).

All v1 fields of the upstream branch (`connectionId, senderKind, scope, guildId, name, maxLength, fingerprint, state`) and
the upstream error code `discord_sender_edit_pending` keep their meaning. v2 only adds, with the exceptions listed under
"Changes since the first v2 text".

**Wave 1 reality.** The webhook route (`POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED` / `_QUALIFIED`) is off at opening, so no webhook
connection can be created and the webhook name ships dark. The bot nickname capability is its own switch and is OFF by default
(`POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED`): until it is turned on a bot nickname is not editable. A webhook name additionally needs the master
switch (`POSTRIFF_DISCORD_SENDER_NAMES_ENABLED`, on only for the exact string `true`, unset is off in every environment) and the webhook route. Show the control only when the provider
view says it is available (next section).

## Is the feature available at all? (provider view)

The channels response (`GET /api/workspaces/{workspace}/channels`, key `providers`, the entry with `id: "discord"`) carries, under `discordModes`:

```jsonc
"discordModes": {
  "bot":     { "senderKind": "bot",     "nickname":   { "enabled": false } },
  "webhook": { "senderKind": "webhook", "enabled": false, "senderName": { "enabled": false } }
}
```

`bot.nickname.enabled` / `webhook.senderName.enabled` are true only when the master switch is on, (bot) the nickname switch is
on, and the shared request coordinator can admit requests (the same gate the routes use; for the webhook also the webhook route).
When false, do not render the editor and do not call the routes. A route called anyway answers with the reasons below and makes no
Discord request.

## The channels view: the sender a review would freeze now

Each Discord row of `GET /api/workspaces/{workspace}/channels` carries two sender fields. Both are computed for the request from the
connection's own record and the switches, as the value a review of that connection would freeze right now (the very function an
automation approval is checked against), so what a page shows and what it echoes cannot disagree:

| field | webhook connection | bot installation |
| --- | --- | --- |
| `discordSenderName` | the saved, validated name while the master switch is on; `null` when none is saved, the feature is off, or the stored name no longer validates (a review or approval then says why, with `discord_sender_name_invalid`) | `null` |
| `discordBotNickname` | absent | present only while the master switch AND the nickname capability are on and this connection has observed the server's nickname: a string, or `null` meaning "the bot has no nickname". Absent when a review would freeze nothing |

Nothing else of the sender record is exposed: not when the nickname was observed, not an edit in progress. The settings route below
still shows the saved name (`savedName`) whatever the switches say.

**Approving an automation run item** (`raffi_run_decide`, a Discord item with a publish time): send `discordSenderName` (webhook; `null`
for none) or `discordBotNickname` (bot; send it exactly when the row has it, omit it when the row has none), copied from the row the
person was looking at. The server compares it with what a review would freeze at that moment and answers `409` ("The webhook sender name
changed. Review it again." or "The Rafii bot's server nickname changed. Review it again.") when it differs, because the person approved
something other than what is now current. The value is then bound by the approval digest (it is part of the publication id) and the
dispatch holds the post if Discord reports another nickname. The value belongs to the workspace's own connection: another workspace never
receives it, even for the same Discord server.

## Routes (unchanged paths)

```
GET  /api/workspaces/{workspace}/channels/{connection}/discord-sender-name
POST /api/workspaces/{workspace}/channels/{connection}/discord-sender-name
```

* Bearer session only (an API token is refused for the POST by the security gate). POST needs the usual app guard header
  and a fresh sign-in (step-up window); the GET does not.
* Roles: the signed-in member needs workspace permission `manage_connections` (owner, admin, or a non-viewer with the
  flag). A member without it gets `403 permission_denied`: hide the control. A non-member, a removed or deleted member, and a
  foreign or non-existent workspace id all get the same `403 permission_denied` with the message "Workspace unavailable.";
  branch on `code`, never on the message.
* **Who may edit**: a webhook name is a Rafii setting, so ANY member who may manage connections edits it (as long as the
  member who authorized the webhook still may). A bot nickname changes a shared Discord object, so ONLY the member whose Discord
  account installed the bot may change it; everybody else sees it read-only with `not_authorizing_member`.
* Throttle: GET 12 per 10 minutes and POST 6 per 10 minutes per connection (plus 40 and 15 per workspace). Over it:
  `429 rate_limited` with `retryAfterSeconds`, which is what is left of that fixed 10-minute window (1 to 600): a retry after it
  is counted afresh, a retry before it is refused again. Do not poll: one GET when the dialog opens, one after a save.
* **The GET is read-only.** It changes no Rafii state (apart from the throttle counters and settling an expired earlier write)
  and no Discord object. Cost of one call (docs/sender-name/CAPACITY-NOTES.md): webhook 1 Discord request, bot 5 cold / 3 warm.
* Server time unit: epoch seconds (float) everywhere.

## GET 200 body

```jsonc
{
  "contractVersion": 2,
  "connectionId": "discord-webhook-…" ,
  "senderKind": "webhook" | "bot",
  "scope": "connection" | "server",       // webhook: this one connection; bot: every Rafii post in the whole Discord server
  "guildId": "123…",                      // the customer's own server
  "state": "verified",                    // v1 field, always "verified" on 200
  "maxLength": 80 | 32,                   // webhook 80, bot nickname 32 (Unicode code points; the server also keeps UTF-16 units within the limit)
  "rules": { "minLength": 1, "maxLength": 80, "lengthUnit": "codepoints",
             "surroundingSpace": false, "forbiddenCharacters": ["@", "#", ":", "```", "<", ">"],
             "reservedWords": true, "singleSpacesOnly": true },    // reservedWords: webhook names may not contain "discord", "clyde", "rafii", "postriff" or be "everyone"/"here" (Discord's own username rules plus the product's names, after case, accent, look-alike and digit folding); bot nicknames only "rafii" and "postriff" (Discord restricts usernames, not server nicknames)

  "name": "…",                            // v1 field, always a string: effectiveName, else savedName, else "" (never null)
  "effectiveName": "…" | null,            // what Discord shows for the next message; null when no Discord read was made (see below), or a webhook has neither a saved name nor a name of its own
  "nameSource": "saved_override" | "webhook_default" | "observed_nickname" | "bot_username" | "none",
  "savedName": "…" | null,                // webhook: the override Rafii freezes into future reviews. bot: the nickname Rafii last set or observed (or null)
  "observedName": "…" | null,             // what Discord itself reported at observedAt (webhook: the webhook's own name, null when the webhook has none; bot: the member nickname or username)
  "observedAt": 1800000000.0 | null,      // null when no provider read was made
  "externalChange": false,                // bot only: observedName differs from savedName, i.e. someone else (a server admin, Discord, another tool) renamed the bot

  "fingerprint": "64 hex",                // send back unchanged with a POST; any Rafii-side change (or, for a bot, a nickname Discord reports differently) makes it stale
  "feature": { "senderNames": true, "botNickname": false },   // server-side switches, as seen by this request
  "editable": true | false,
  "unavailable": [ { "code": "…" } ],     // empty exactly when editable is true; stable codes below; may carry extra fields
  "preview": {
    "currentDisplayName": "…" | null,     // what a post would show right now (null when unknown): render this as the Discord preview
    "badge": "APP",                       // Discord shows the APP/BOT badge next to both webhook and bot senders
    "audience": "this_connection" | "everyone_in_server",
    "queuedPostsKeepApprovedName": true,         // webhook: posts already reviewed or approved keep the name they were approved with
    "queuedBotPostsHoldIfNicknameChanges": false // bot: a queued post approved under one server nickname is HELD (not sent) if Discord reports another
  }
}
```

### `unavailable[].code` (all stable, snake_case; show copy per code, never the English message)

| code | applies to | meaning | UI |
| --- | --- | --- | --- |
| `sender_names_disabled` | both | the server-side master switch is off (it is the default in every environment: only the exact string `true` turns it on, whatever `VERCEL_ENV` or `POSTRIFF_ENVIRONMENT` say) | read-only; say names are not available yet |
| `bot_nickname_disabled` | bot | the nickname capability is isolated by its own switch (default off everywhere); the master switch may be on | read-only; say server nicknames are not available yet |
| `provider_unavailable` | both | the shared Discord request coordinator cannot admit a request right now (not configured, degraded, or - webhook - the webhook route is off) | read-only; "temporarily unavailable"; do not retry in a loop |
| `not_authorizing_member` | bot | you are not the member who installed the bot in this server; only that member can change the nickname | read-only; name the rule, not the person |
| `session_reverification_required` | both | your sign-in is older than the step-up window; a save would be refused (`step_up_required`) | offer sign-in again, then reload |
| `person_missing_manage_nicknames` | bot | the Discord account that installed the bot no longer has Manage Nicknames, Administrator or ownership there | explain it is a Discord server permission |
| `person_role_below_bot` | bot | that Discord account is not the server owner and its highest role is not above the bot's role (Discord's role hierarchy) | same |
| `bot_missing_change_nickname` | bot | the Rafii bot lacks the Change Nickname permission (or Administrator) in that server | tell a server admin to grant it, then reload |
| `nickname_authority_other_workspace` | bot | another Rafii workspace also has this server connected; Rafii changes the shared nickname from neither workspace | read-only; no identifier is ever given |
| `edit_pending` | bot | an earlier nickname write has an unknown outcome and Discord was not read (a switch is off, the coordinator is unavailable, or you are not the authorizer); `retryAfterSeconds` says when it can be checked. When Discord is read, the same situation is the `409 discord_sender_edit_pending` error instead | disable the form, show the countdown |

Order of the list is the evaluation order above. `editable` is `false` whenever the list is not empty.

### No provider read

The server makes no Discord request (so `observedAt` and `observedName` are `null`, and `effectiveName` is `null`;
`name` falls back to `savedName` or `""`) when the answer is already known without one: any of `sender_names_disabled`,
`bot_nickname_disabled`, `provider_unavailable`, `not_authorizing_member`. `session_reverification_required` and `edit_pending`
can accompany them. The page must render these as read-only states and must not retry. In every other case the server reads
Discord (a webhook: its own resource, 1 request; a bot: the server, the installing member's roles, the bot member).

### GET errors

| HTTP | `code` | meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | no or expired session |
| 403 | `permission_denied` | not a member of that workspace, workspace does not exist or is malformed, member removed or deleted (one body, "Workspace unavailable."), or the role lacks `manage_connections` |
| 404 | `not_found` | that connection does not exist in this workspace, is revoked, or is not a Discord connection. One response for all four. A connection id of another workspace is "does not exist". |
| 409 | `discord_connection_required` | the stored authorization no longer matches (reconnect needed) |
| 409 | `discord_sender_edit_pending` | a nickname write has an unknown outcome; `retryAfterSeconds` (number) says when a reload may settle it (60 when the request coordinator cannot settle it yet) |
| 429 | `rate_limited` | throttle; `retryAfterSeconds` is what is left of the fixed 10-minute window (1 to 600) |
| 429 | `discord_rate_delayed` | the shared Discord request budget is momentarily used up; `retryAfterSeconds`; nothing was changed |
| 503 | `discord_rate_coordinator_unavailable` | the shared request coordinator failed after the readiness check passed (it is restarting or degraded); nothing was sent or changed; "temporarily unavailable", retry later, not in a loop |
| 409 | `discord_sender_evidence_invalid` | bot: Discord's answer about the server, the installing member's roles or the bot's permissions was incomplete or not usable (nothing was changed): reload once; if it persists, reconnect the installation |
| 503 | `discord_connection_required` | Discord is paused or connection authorization is not enabled for the whole provider (the same answer every Discord connection route gives) |
| 409/502/503 | `discord_connection_required` / `upstream_error` / `service_unavailable` | Discord did not answer or no longer confirms the connection (a webhook that is not the connected one is `discord_connection_required`: reconnect); nothing changed |

## POST

Request body (exactly these keys, nothing else):

```json
{ "name": "Acme Weekly", "fingerprint": "<from GET>", "confirmed": true, "sharedServerConfirmed": true }
```

* `sharedServerConfirmed` is required (and only accepted as `true`) for `senderKind: "bot"`.
* **Clear (webhook only)**: `{ "reset": true, "fingerprint": "<from GET>", "confirmed": true }` removes the saved name so the webhook's own
  name is used again for posts reviewed afterwards. `reset` is only accepted as `true` and never together with `name`. A bot
  nickname cannot be cleared from Rafii (`400 discord_sender_reset_unsupported`): the person chooses the nickname they want.

200: the same body as GET after the save, plus `"saved": true` (and `"reset": true` after a clear). The `fingerprint` in it is the new one.

### POST errors (HTTP / `code` / extra fields)

| HTTP | `code` | extra | meaning | state change |
| --- | --- | --- | --- | --- |
| 400 | `discord_sender_name_invalid` | `reason`, `maxLength` | name rejected before anything is read from Discord. `reason`: `not_text`, `empty`, `surrounding_space`, `too_long`, `not_normalized`, `control_or_format`, `invisible`, `spacing`, `forbidden_character`, `reserved_word`, `url_like` | none |
| 400 | `discord_sender_name_unconfirmed` | | `confirmed` is not `true`, `fingerprint` missing, `reset` is not `true`, `reset` sent with `name`, or an unknown key was sent | none |
| 400 | `discord_sender_name_shared_unconfirmed` | | bot: `sharedServerConfirmed` is not `true` | none |
| 400 | `discord_sender_reset_unsupported` | | bot: a nickname cannot be cleared | none |
| 401 | `unauthenticated` | | | none |
| 403 | `permission_denied` | | not a member / foreign / unknown workspace / role lacks `manage_connections` | none |
| 403 | `step_up_required`, `security_step_up_required` | | sign in again, then retry with a fresh GET | none |
| 403 | `discord_sender_name_unavailable` | `reasons: [{code}]` | a person-bound reason from the table: `not_authorizing_member`, `person_missing_manage_nicknames`, `person_role_below_bot` | none |
| 404 | `not_found` | | connection unknown to this workspace (see GET) | none |
| 409 | `discord_sender_name_unavailable` | `reasons: [{code}]` | a state-bound reason: `sender_names_disabled`, `bot_nickname_disabled`, `bot_missing_change_nickname`, `nickname_authority_other_workspace` | none |
| 503 | `discord_sender_name_unavailable` | `reasons: [{code: "provider_unavailable"}]` | the request coordinator cannot admit the write (also when it fails before the write is admitted); nothing was sent | none |
| 409 | `discord_sender_name_required` | | **stale settings**: the fingerprint no longer matches (another save, a reconnect, a permission change, a different member, a pending write, or a bot nickname Discord reports differently). Reload with a GET and review again. | none |
| 409 | `discord_sender_edit_pending` | `retryAfterSeconds` | bot: a write whose outcome is unknown (timeout, lost response) is unresolved for up to 2 minutes; a GET after the deadline reads Discord and settles it. The POST itself can return this when its own write was not confirmed. | claim kept until settled |
| 409 | `discord_sender_write_refused` | | bot: Discord answered the write with a client error other than 429 (permission lost between the check and the write, hierarchy). The nickname is unchanged and nothing waits: reload, look at `unavailable` / `observedName`, fix the permission, try again. Never retried by Rafii. | none (claim released) |
| 429 | `discord_sender_write_rate_limited` | `retryAfterSeconds` | bot: Discord answered the write with a rate limit. The nickname is unchanged and nothing waits; try again after `retryAfterSeconds`, which is Discord's own hint rounded up (its `retry_after`, else the `Retry-After` header; 60 when it gave none). Not a permission problem and never retried by Rafii. | none (claim released) |
| 409 | `discord_sender_evidence_invalid` | | bot: Discord's answer about the server, roles or permissions was not usable (as for GET); nothing was written | none |
| 503 | `discord_rate_coordinator_unavailable` | | the shared request coordinator failed after the readiness check passed; nothing was sent | none (a claim made for the write is released) |
| 409 | `discord_sender_write_unconfirmed` | | bot: Discord accepted the write but did not confirm the requested nickname, or the read-back failed. The nickname may have changed: reload before anything else. | claim kept until settled |
| 429 | `discord_rate_delayed` | `retryAfterSeconds` | the shared request budget was used up before the write; nothing was sent | none (claim released) |
| 409 | `discord_connection_required` | | reconnect the connection first | none |
| 429 | `rate_limited` | `retryAfterSeconds` | throttle; what is left of the fixed 10-minute window (1 to 600) | none |

Every denial above leaves Rafii state (except the throttle counters), the Discord side and the audit log unchanged, and
issues no Discord request, except that a refusal found only after Discord was read (`bot_missing_change_nickname`,
`person_*`, `nickname_authority_other_workspace`) has made those reads (GETs only; never a write). Order of checks:
body shape (400, independent of any workspace), session, workspace, role, throttle, switches and request coordinator and
authorizer, the Rafii-side half of the fingerprint, name rules, then the Discord reads and their reasons. `discord_sender_name_required` is the only stale-settings code; do not infer
staleness from any other.

## Behaviour the UI can rely on

* **Webhook name**: saved per connection and applied to posts reviewed after the save. A post already in review or approved keeps
  the name it was reviewed with (the review page shows `discordSenderName`; absent means the webhook's own name). A reconnect by
  the same member that creates the replacement webhook carries the saved name over (a new revision, the old connection stays revoked); a first
  connection starts without a name, and "clear" (above) removes it.
* **Switch off after approval**: a queued post that carries a custom name is held with nothing sent while the server switch is off
  (never sent under another name). The post's event line reads "Discord custom sender names are switched off; nothing was
  posted." Posts without a custom name are unaffected. Switching back on does not resend a held post: it stays held until the person acts on it in the queue.
* **Bot nickname**: always shared by everyone using the bot in that server. Discord server admins can rename the bot at any time, so
  show `observedName` and `externalChange`; never claim Rafii owns the name. When the nickname capability is on, a review freezes the nickname Discord
  last reported (`manifest.discordBotNickname`, `null` meaning "no nickname"); at dispatch the post is HELD, nothing sent, with the event
  line "The Rafii bot's server nickname is no longer the one this post was approved under. Nothing was posted." when Discord
  reports a different one. Posts approved while the capability was off carry no frozen nickname and are never held for it.
* **The freeze and the hold need a prior observation.** A review freezes a bot nickname only if this connection has already
  observed the server's nickname: from a member verification (the connection's verify action), from its own verified nickname
  write, or from a GET that settled an expired write. Installing the bot records none, so posts approved before the first observation
  carry no guard and are never held for a nickname change. Once an observation exists it is what every later review freezes: if a
  server admin renames the bot afterwards, the next dispatch fails closed (the post is held, `discord_bot_nickname_changed`) and
  re-reviewing freezes the same old value again until a member verification (or a successful save in the dialog) refreshes the
  observation. A page that offers the nickname editor should offer "Verify" once after the bot is connected and again after a
  `discord_bot_nickname_changed` hold. A verification that overlaps a save of the same connection answers
  `verification_unavailable` (nothing is extended): repeat it.
* **One writer per server**: Rafii changes a server's nickname from a workspace only while that workspace is the only live Rafii
  installation of the server. With two, both see `nickname_authority_other_workspace` and neither can write.
* **Audit log.** Every Rafii nickname write sends the audit-log reason "Rafii shared bot nickname change (ref xxxxxxxxxxxxxxxx)", where the
  reference is a one-way hash of the workspace and server and names no person. Whether Discord records an audit-log entry at all when a
  member changes its own nickname (the write is `PATCH /guilds/{id}/members/@me`), and whether it shows that reason, has NOT been
  observed: do not promise a customer an audit-log entry. Rafii's own audit event for the change (`discord.sender_name_updated`) is the
  record that exists.
* **Automation approvals** (recurring tasks) echo the sender the person was shown, taken from the channels view (next section):
  `discordSenderName` for a webhook, `discordBotNickname` for a bot. If it no longer matches what a review would freeze at that moment
  the approval is refused with 409 and must be redone.
* **A held post says why, in a code.** When the dispatch preflight holds a post because of its sender, the held event on the job is
  `{ "state": "held", "message": "<English text>", "reason": "<code>", ... }`. `discord_bot_nickname_changed`: Discord reports another
  nickname than the one the post was approved under (offer Verify, then a new review). `discord_sender_names_disabled`: the master switch
  is off, so a custom name is never sent; the post stays held until the person acts on it. Branch on `reason`, never on the text. Every
  other hold has no `reason`.
* Messages in `error` are English diagnostics and may change; branch on `code`, `reason`, `reasons[].code`.
* Nothing in any response contains another workspace's identifiers, names, counts or timings. The one cross-workspace fact is the
  boolean-like reason `nickname_authority_other_workspace`.

## Changes since the first v2 text

For the UI agent, because they could break a page built against the earlier text:

1. `preview.queuedPostsFollowCurrentNickname` is gone; the bot key is `preview.queuedBotPostsHoldIfNicknameChanges` (a queued bot post is held, not
   silently re-labelled, when the server nickname changes). The webhook key `queuedPostsKeepApprovedName` is unchanged.
2. `not_authorizing_member` applies to the bot only. Any member with `manage_connections` edits a webhook name.
3. New reason `provider_unavailable` (503 on a write) and new codes `discord_sender_write_refused`, `discord_sender_reset_unsupported`,
   `discord_rate_delayed` on POST. `discord_sender_write_unconfirmed` now means only "may have changed", never "refused".
4. New request body key `reset`. A webhook reconnect by the same member now keeps the saved name.
5. The GET no longer verifies the connection (it used to run the member-verification actions as a side effect), so a settings page can
   no longer flip a connection to unverified or write audit rows by being opened.

## Changes since f7075432 (delta review SNR2)

1. A name with an unpaired surrogate (JSON `"\ud800"`) is a `400 discord_sender_name_invalid` with `reason: control_or_format`, on both kinds
   (it used to be an unhandled server error).
2. The master switch is on only for the exact string `true`, in every environment; unset is off (it used to be on outside hosted
   production). The provider view and the `sender_names_disabled` reason follow it.
3. `retryAfterSeconds` of `429 rate_limited` is now the time left in the 10-minute window (1 to 600), not a constant 60.
4. New codes: `discord_sender_write_rate_limited` (429, `retryAfterSeconds`; a Discord 429 on the nickname write, no longer
   `discord_sender_write_refused`), `discord_sender_evidence_invalid` (409, bot), and the already existing
   `discord_rate_coordinator_unavailable` (503) is now documented for GET and POST.
5. A webhook with no name of its own: `observedName` is `null`, `nameSource` is `saved_override` or `none`, and the form works (it used to be
   a 502 `upstream_error`).
6. Reserved words: `discord`, `clyde`, `everyone` and `here` are refused in webhook names only; bot nicknames refuse the product's names only.

## Changes since 9f170585 (the web engineer's backend list R1 to R3)

1. **R1.** The channels view now carries `discordBotNickname` (a string, or `null` for "no nickname") while the master switch and the nickname
   capability are on and the connection has observed one; absent otherwise. A page copies it into an automation approval. Before, no field
   carried it and every such approval of a bot post was refused once the capability was on.
2. **R2.** `discordSenderName` in the channels view is the name a review would freeze now: `null` while the master switch is off or when a stored
   name no longer validates, instead of the raw saved setting. The settings route is unchanged.
3. **R3.** A post held for its sender has `reason` (`discord_bot_nickname_changed` or `discord_sender_names_disabled`) on the held event, next to
   the unchanged English `message`.
4. The audit-log statement is softened to what is known (see "Audit log").
