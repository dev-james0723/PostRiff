# Discord sender names: UI / API contract (v2)

Status: contract written first (2026-10-23), implementation follows on branch `claude/discord-rc2-sendername-20261023`.
Anything below that the implementation cannot honour will be corrected here in the same commit that changes it; the UI
agent should read the branch head, not an older copy. Every field and code in this file is covered by a test named in
`EVIDENCE.md` once the corresponding commit lands.

All v1 fields of the upstream branch (`connectionId, senderKind, scope, guildId, name, maxLength, fingerprint, state`) and
the upstream error code `discord_sender_edit_pending` keep their meaning. v2 only adds.

## Routes (unchanged paths)

```
GET  /api/workspaces/{workspace}/channels/{connection}/discord-sender-name
POST /api/workspaces/{workspace}/channels/{connection}/discord-sender-name
```

* Bearer session only (an API token is refused for the POST by the security gate). POST needs the usual app guard header
  and a fresh sign-in (step-up window); the GET does not.
* Roles: the signed-in member needs workspace permission `manage_connections`. A member without it gets `403 permission_denied`
  (same body as a foreign or non-existent workspace): hide the control.
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

  "name": "…" | null,                     // v1 field: the name Discord shows for the next message (= effectiveName)
  "effectiveName": "…" | null,
  "nameSource": "saved_override" | "webhook_default" | "observed_nickname" | "bot_username" | "none",
  "savedName": "…" | null,                // webhook: the override Rafii freezes into future reviews. bot: the nickname Rafii last set (or null)
  "observedName": "…" | null,             // what Discord itself reported at observedAt (webhook: the webhook's own name; bot: the member nickname or username)
  "observedAt": 1800000000.0 | null,      // null when no provider read was made (see "No provider read" below)
  "externalChange": false,                // bot only: observedName differs from savedName, i.e. someone else (a server admin, Discord, another tool) renamed the bot

  "fingerprint": "64 hex",                // send back unchanged with a POST; any state change makes it stale
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
| `sender_names_disabled` | webhook | the server-side switch for webhook sender names is off | read-only; say names are not available yet |
| `bot_nickname_disabled` | bot | the nickname capability is isolated by its own switch (default off) | read-only; say server nicknames are not available yet |
| `not_authorizing_member` | both | you are not the member who authorized this connection; only that member can change its sender | read-only; name the rule, not the person |
| `session_reverification_required` | both | your sign-in is older than the step-up window; a save would be refused (`step_up_required`) | offer sign-in again, then reload |
| `person_missing_manage_nicknames` | bot | the Discord account that authorized this server no longer has Manage Nicknames, Administrator or ownership there | explain it is a Discord server permission |
| `person_role_below_bot` | bot | that Discord account is not the server owner and its highest role is not above the bot's role (Discord's role hierarchy) | same |
| `bot_missing_change_nickname` | bot | the Rafii bot lacks the Change Nickname permission (or Administrator) in that server | tell a server admin to grant it, then reload |
| `nickname_authority_other_workspace` | bot | another Rafii workspace also has this server connected; Rafii changes the shared nickname from neither workspace | read-only; no identifier is ever given |
| `edit_pending` | bot | an earlier nickname write has an unknown outcome; `retryAfterSeconds` says when a reload may check it | disable the form, show the countdown |

Order of the list is the evaluation order above. `editable` is `false` whenever the list is not empty.

### No provider read

The server makes no Discord request (so `observedAt` is `null`, `observedName` is `null` and `effectiveName` falls back to
`savedName` for a webhook or `null` for a bot) when the answer is already known without one: `sender_names_disabled`,
`bot_nickname_disabled`, `not_authorizing_member`. The page must render these as read-only states and must not retry.

### GET errors

| HTTP | `code` | meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | no or expired session |
| 403 | `permission_denied` | not a member of that workspace, workspace does not exist, or the role lacks `manage_connections`. One response for all three. |
| 404 | `not_found` | that connection does not exist in this workspace, is revoked, or is not a Discord connection. One response for all four. A connection id of another workspace is "does not exist". |
| 409 | `discord_connection_required` | the stored authorization no longer matches (reconnect needed) |
| 409 | `discord_sender_edit_pending` | a nickname write has an unknown outcome; `retryAfterSeconds` (number) says when a reload may reconcile it |
| 429 | `rate_limited` | throttle; `retryAfterSeconds` |
| 502/503 | `upstream_error` / `service_unavailable` | Discord did not answer; nothing changed; retry later |

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
| 409 | `discord_sender_name_required` | | **stale settings**: the fingerprint no longer matches (another save, a reconnect, a permission change, or a different member state). Reload with a GET and review again. | none |
| 409 | `discord_sender_edit_pending` | `retryAfterSeconds` | bot: a write with an unknown outcome is unresolved; a GET after the deadline reconciles it | none until reconciled |
| 409 | `discord_connection_required` | | reconnect the connection first | none |
| 429 | `rate_limited` | `retryAfterSeconds` | throttle | none |

Every denial above leaves Rafii state, the Discord side and the audit log unchanged. `discord_sender_name_required` is
the only stale-settings code; do not infer staleness from any other.

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
