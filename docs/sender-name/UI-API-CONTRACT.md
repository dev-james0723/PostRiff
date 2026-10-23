# Discord sender names: UI / API contract (v2)

Status: implemented on branch `claude/discord-rc2-sendername-20261023` (this file was written first, then corrected to
what the code does; the UI agent should read the branch head, not an older copy). Every field and code below is asserted
by `tests/test_discord_sender_name_routes.py` (shape, codes, reasons) and `tests/test_discord_sender_name_postgres.py`.

All v1 fields of the upstream branch (`connectionId, senderKind, scope, guildId, name, maxLength, fingerprint, state`) and
the upstream error code `discord_sender_edit_pending` keep their meaning. v2 only adds.

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
* Throttle: GET 12 per 10 minutes and POST 6 per 10 minutes per connection (plus 40 and 15 per workspace). Over it:
  `429 rate_limited` with `retryAfterSeconds`. Do not poll: one GET when the dialog opens, one after a save.
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
  "maxLength": 80 | 32,                   // webhook 80, bot nickname 32 (Unicode code points; server also keeps UTF-16 units within the limit)
  "rules": { "minLength": 1, "maxLength": 80, "lengthUnit": "codepoints",
             "surroundingSpace": false, "forbiddenCharacters": ["@", "#", ":", "```", "<", ">"],
             "reservedWords": true, "singleSpacesOnly": true },

  "name": "…",                            // v1 field, always a string: effectiveName, else savedName, else "" (never null)
  "effectiveName": "…" | null,            // what Discord shows for the next message; null when no Discord read was made (see below)
  "nameSource": "saved_override" | "webhook_default" | "observed_nickname" | "bot_username" | "none",
  "savedName": "…" | null,                // webhook: the override Rafii freezes into future reviews. bot: the nickname Rafii last set (or null)
  "observedName": "…" | null,             // what Discord itself reported at observedAt (webhook: the webhook's own name; bot: the member nickname or username)
  "observedAt": 1800000000.0 | null,      // null when no provider read was made (see "No provider read" below)
  "externalChange": false,                // bot only: observedName differs from savedName, i.e. someone else (a server admin, Discord, another tool) renamed the bot

  "fingerprint": "64 hex",                // send back unchanged with a POST; any Rafii-side change (or, for a bot, a nickname Discord reports differently) makes it stale
  "feature": { "senderNames": true, "botNickname": false },   // server-side switches, as seen by this request
  "editable": true | false,
  "unavailable": [ { "code": "…" } ],     // empty exactly when editable is true; stable codes below; may carry extra fields
  "preview": {
    "currentDisplayName": "…" | null,     // what a post would show right now (null when unknown)
    "badge": "APP",                       // Discord shows the BOT/APP badge next to both webhook and bot senders
    "audience": "this_connection" | "everyone_in_server",
    "queuedPostsKeepApprovedName": true,  // webhook: posts already reviewed or approved keep the name they were approved with
    "queuedPostsFollowCurrentNickname": false // bot: Discord renders the nickname at read time, so queued posts follow the current nickname
  }
}
```

### `unavailable[].code` (all stable, snake_case; show copy per code, never the English message)

| code | applies to | meaning | UI |
| --- | --- | --- | --- |
| `sender_names_disabled` | both | the server-side master switch is off (it is also the default on hosted production until the release enables it) | read-only; say names are not available yet |
| `bot_nickname_disabled` | bot | the nickname capability is isolated by its own switch (default off everywhere); the master switch may be on | read-only; say server nicknames are not available yet |
| `not_authorizing_member` | both | you are not the member who authorized this connection; only that member can change its sender | read-only; name the rule, not the person |
| `session_reverification_required` | both | your sign-in is older than the step-up window; a save would be refused (`step_up_required`) | offer sign-in again, then reload |
| `person_missing_manage_nicknames` | bot | the Discord account that authorized this server no longer has Manage Nicknames, Administrator or ownership there | explain it is a Discord server permission |
| `person_role_below_bot` | bot | that Discord account is not the server owner and its highest role is not above the bot's role (Discord's role hierarchy) | same |
| `bot_missing_change_nickname` | bot | the Rafii bot lacks the Change Nickname permission (or Administrator) in that server | tell a server admin to grant it, then reload |
| `nickname_authority_other_workspace` | bot | another Rafii workspace also has this server connected; Rafii changes the shared nickname from neither workspace | read-only; no identifier is ever given |
| `edit_pending` | bot | an earlier nickname write has an unknown outcome and Discord was not read (a switch is off, or you are not the authorizer); `retryAfterSeconds` says when it can be checked. When Discord is read, the same situation is the `409 discord_sender_edit_pending` error below instead | disable the form, show the countdown |

Order of the list is the evaluation order above. `editable` is `false` whenever the list is not empty.

### No provider read

The server makes no Discord request (so `observedAt` and `observedName` are `null`, and `effectiveName` is `null`;
`name` falls back to `savedName` or `""`) when the answer is already known without one: any of `sender_names_disabled`,
`bot_nickname_disabled`, `not_authorizing_member`. `session_reverification_required` and `edit_pending` can accompany
them. The page must render these as read-only states and must not retry. In every other case the server reads Discord
(a webhook: its own resource, 1 request; a bot: the server, the bot member and the authorizer's roles).

### GET errors

| HTTP | `code` | meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | no or expired session |
| 403 | `permission_denied` | not a member of that workspace, workspace does not exist or is malformed, member removed or deleted (one body, "Workspace unavailable."), or the role lacks `manage_connections` |
| 404 | `not_found` | that connection does not exist in this workspace, is revoked, or is not a Discord connection. One response for all four. A connection id of another workspace is "does not exist". |
| 409 | `discord_connection_required` | the stored authorization no longer matches (reconnect needed) |
| 409 | `discord_sender_edit_pending` | a nickname write has an unknown outcome; `retryAfterSeconds` (number) says when a reload may reconcile it |
| 429 | `rate_limited` | throttle; `retryAfterSeconds` (60) |
| 409/502/503 | `discord_connection_required` / `upstream_error` / `service_unavailable` | Discord did not answer or no longer confirms the connection; nothing changed |

## POST

Request body (exactly these keys, nothing else):

```json
{ "name": "Acme Weekly", "fingerprint": "<from GET>", "confirmed": true, "sharedServerConfirmed": true }
```

`sharedServerConfirmed` is required (and only accepted as `true`) for `senderKind: "bot"`.

200: the same body as GET after the save, plus `"saved": true`. The `fingerprint` in it is the new one.

### POST errors (HTTP / `code` / extra fields)

| HTTP | `code` | extra | meaning | state change |
| --- | --- | --- | --- | --- |
| 400 | `discord_sender_name_invalid` | `reason`, `maxLength` | name rejected. `reason`: `not_text`, `empty`, `surrounding_space`, `too_long`, `not_normalized`, `control_or_format`, `invisible`, `spacing`, `forbidden_character`, `reserved_word`, `url_like` | none |
| 400 | `discord_sender_name_unconfirmed` | | `confirmed` is not `true`, `fingerprint` missing, or an unknown key was sent | none |
| 400 | `discord_sender_name_shared_unconfirmed` | | bot: `sharedServerConfirmed` is not `true` | none |
| 401 | `unauthenticated` | | | none |
| 403 | `permission_denied` | | not a member / foreign / unknown workspace / role lacks `manage_connections` | none |
| 403 | `step_up_required`, `security_step_up_required` | | sign in again, then retry with a fresh GET | none |
| 403 | `discord_sender_name_unavailable` | `reasons: [{code}]` | a person-bound reason from the table: `not_authorizing_member`, `person_missing_manage_nicknames`, `person_role_below_bot` | none |
| 404 | `not_found` | | connection unknown to this workspace (see GET) | none |
| 409 | `discord_sender_name_unavailable` | `reasons: [{code}]` | a state-bound reason: `sender_names_disabled`, `bot_nickname_disabled`, `bot_missing_change_nickname`, `nickname_authority_other_workspace` | none |
| 409 | `discord_sender_name_required` | | **stale settings**: the fingerprint no longer matches (another save, a reconnect, a permission change, a different member, a pending write, or a bot nickname Discord reports differently). Reload with a GET and review again. | none |
| 409 | `discord_sender_edit_pending` | `retryAfterSeconds` | bot: a write with an unknown outcome (timeout, lost response) is unresolved for up to 2 minutes; a GET after the deadline reads Discord and reconciles it. The POST itself can return this when its own write was not confirmed. | claim kept until reconciled |
| 409 | `discord_sender_write_unconfirmed` | | bot: Discord refused the write (permission lost between the check and the write, rate limit) or answered with something other than the requested nickname. A definite refusal frees the claim; reload and look at `unavailable` / `observedName` before trying again. | none for a definite refusal |
| 409 | `discord_connection_required` | | reconnect the connection first | none |
| 429 | `rate_limited` | `retryAfterSeconds` | throttle | none |

Every denial above leaves Rafii state (except the throttle counters), the Discord side and the audit log unchanged, and
issues no Discord request, except that a refusal found only after Discord was read (`bot_missing_change_nickname`,
`person_*`, `nickname_authority_other_workspace`) has made those reads (GETs only; never a write). Order of checks:
session, workspace, role, switches and authorizer, body shape and fingerprint (Rafii-side half), name rules, then the Discord
reads and their reasons. `discord_sender_name_required` is the only stale-settings code; do not infer staleness from any other.

## Behaviour the UI can rely on

* **Webhook name**: saved per connection and applied to posts reviewed after the save. A post already in review or
  approved keeps the name it was reviewed with (the review page shows `discordSenderName`; absent means the webhook's own
  name). Reconnecting a webhook creates a new connection with no saved name.
* **Switch off after approval**: a queued post that carries a custom name is held with nothing sent while the server
  switch is off (never sent under another name). The post's event line reads "Discord custom sender names are switched
  off; nothing was posted." Posts without a custom name are unaffected.
* **Bot nickname**: always shared by everyone using the bot in that server and by posts already queued. Discord server
  admins can rename the bot at any time, so show `observedName` and `externalChange`; never claim Rafii owns the name.
* Messages in `error` are English diagnostics and may change; branch on `code`, `reason`, `reasons[].code`.
* Nothing in any response contains another workspace's identifiers, names, counts or timings. The one cross-workspace
  fact is the boolean-like reason `nickname_authority_other_workspace`.
