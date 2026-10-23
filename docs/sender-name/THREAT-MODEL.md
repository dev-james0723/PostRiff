# Discord customer sender names: threat model and design note

Branch `claude/discord-rc2-sendername-20261023`, written 2026-10-23 against the RC2 integration line
(`5a94b4f2`, which contains the upstream sender-name commit `97b3956a`) and revised after the independent review (SNR-1 to
SNR-13, see `EVIDENCE.md` for the per-finding verdict). Production is out of scope of this document:
nothing here was run against Discord, Supabase, Vercel or GitHub; every Discord answer in the tests is synthetic.

How to read the evidence column: a test name is a test that exists in this branch and passes on its head. "Measured"
means the number comes from a test assertion or a command whose output is recorded in `EVIDENCE.md`; "inferred" means
reasoning from the code or from Discord's public documentation, not from a run against Discord.

## 1. Two features with different physics

| | Webhook sender name | Bot nickname |
| --- | --- | --- |
| What Discord shows | the `username` field of each execute-webhook call, for that one message | the bot member's nickname in one server, rendered by Discord at read time |
| Scope | one connection (one webhook, one channel) | every Rafii post by the one shared bot in that whole server |
| Frozen at approval? | yes: it is inside the wire content, so inside `wireDigest` | not in the wire (Discord renders the current nickname when a message is read), but Rafii freezes the nickname Discord last reported into the manifest at review and HOLDS the post at dispatch if Discord reports another (section 5.6) |
| Who else can change it | any member who may manage connections (it is a Rafii setting); Discord admins can edit or delete the webhook but cannot change what a message already says | the server's native administrators at any time, and any other Rafii workspace that installed the bot in the same server; through Rafii only the member whose Discord account installed it |
| Owner's rule | per-send override, no cross-customer pollution | only a server administrator with the right permission may authorize it, and different Rafii users must not overwrite each other |

The webhook path is made fully per-send and is the primary deliverable, but the webhook ROUTE itself stays off at opening
(`POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED`/`_QUALIFIED` unset), so it ships dark and the only part a customer can reach in Wave 1 is the
bot nickname. The bot nickname is built behind its own default-off switch with a cross-workspace guard (section 5); it is the
part that cannot be called passing as a whole (section 11).

## 2. Assets

1. The text a customer's community reads as "who sent this": a webhook's `username`, a bot's server nickname.
2. The integrity of one customer's output with respect to every other customer (no name of customer A in any request,
   message or setting of customer B).
3. The Discord application's standing: its global request ceiling and its invalid-request budget (10,000 per 10
   minutes before Discord bans the application's egress for everyone).
4. The webhook credential (a bearer secret) and the linked-identity credential; they must not reach a client, a log, an
   audit row or a fingerprint.
5. The approved-post guarantee: what the customer approved is exactly what is sent (wire digest).

## 3. Actors

| Actor | Capability assumed |
| --- | --- |
| Hostile customer | a real workspace member with `manage_connections`, authorizing its own connections; scripts the API; picks any name |
| Hostile Discord server owner/admin | owns a server where Rafii's bot is installed or a webhook exists; can rename the bot, delete webhooks, revoke the app, change role positions |
| Lower Rafii role | viewer, editor, approver or admin without being the authorizing member; or a member without `manage_connections` |
| Stale session | a bearer older than the step-up window, or one that was revoked |
| Second workspace in the same server | another customer whose authorizer also manages the same Discord server and installed the same shared bot there |
| Rafii operator | has database and deployment access; not defended against in code, but every setting change is audited without the text |

## 4. Webhook sender name: storage, binding, freezing, execution

### 4.1 Where it lives and what it is bound to

* Stored as `discordSenderName` on the connection's own channel record inside that workspace's state row (a different
  row per workspace, so a different row per customer), with a `discordSenderRevision` that changes on every save.
  `ChannelRecord` ids are unique per workspace and webhook, so the name is per connection.
* Written only by `POST .../discord-sender-name`, which requires: a verified session (`403` otherwise), workspace
  permission `manage_connections` (ANY member with it: the name is a Rafii setting; the member who authorized the webhook
  must still hold it, which `validate_webhook` re-checks), a fresh sign-in (`assert_fresh`), the sensitive-`connections`
  security gate, a live credential whose authorization generation, scopes, application, webhook id, channel and linked
  user all match the card, and the exact-state fingerprint of the form the person saw. `{"reset": true}` removes the name.
* The fingerprint is 64 hex: 32 for the Rafii-side state (workspace, member, card fields including the authorization
  generation and the saved name and revision, the credential row and generation, the identity link) and 32 for the name the
  person saw. The webhook's own token is not an input. The state half is checked before any Discord request is made.

### 4.2 Freezing

`freeze_manifest` copies the name of THAT connection's record into the manifest at review, validated, and only while the
master switch is on. The name becomes part of `wire_content` (field `username`), therefore of `wireDigest`,
`deliveryDigest`, `operationDigest`, the publication id and the approval digest. Approving a review keeps the name the
review showed even if the setting changes in between (`test_discord_sender_name_wire.py::test_an_approval_keeps_the_name_its_review_showed`).
Automation items bind the name inside the original human decision (`campaigns._decide`), and the queue commit re-freezes
from that decision, never from the live setting (`publisher.commit` with `approved_campaign_channel`).

### 4.3 Execution

`HostedSocial._submit_discord` builds the execute body from `wire_content(manifest)`: exactly
`{content, allowed_mentions: {parse: []}, flags: 4}` plus `username` when the manifest carries one. Nothing else reads a
name: not the channel record, not an environment variable, not a module global. Both schedulers run this same method
(the lane subclasses the worker; there is no second send path).

| Property | Proof |
| --- | --- |
| The body of every create has exactly the keys above and the manifest's own `username` | `test_discord_sender_name_wire.py::test_switch_by_setting_matrix_from_review_to_wire` |
| 24 tenants at once (named and unnamed), one create each, each carries only its own name and no other customer's name appears anywhere in its request | `::test_concurrent_creates_each_carry_exactly_their_own_name` |
| Editing every tenant's setting in a tight loop while their approved posts are created changes nothing on the wire | `::test_creates_race_with_settings_edits_and_still_carry_the_approved_names` |
| Nothing mutable or process-global is consulted at execution (the settings reader, the freezer and the custody check are replaced by functions that fail if called) | `::test_nothing_mutable_or_process_global_is_consulted_when_executing` |
| Real PostgreSQL, the W-02 lane with 4 concurrent loops: 6 named webhooks, 4 unnamed, 4 bot installations, 2 posts each; each execute carries its own name, none carries another's | `test_discord_sender_name_postgres.py::LaneAndWorkerOnPostgres::test_the_lane_sends_named_unnamed_and_bot_posts_each_under_exactly_its_own_name` |
| The minute-tick worker (`PostgresWorker.step`, the path with the lane off), same assertions | `::test_the_minute_tick_worker_path_with_the_lane_off_sends_the_same_exact_names` |
| A worker without the fenced lease protocol cannot dispatch Discord on a migrated database at all (so the frozen RC1 worker can only hold named posts) | `::test_a_worker_without_the_fenced_lease_protocol_cannot_dispatch_discord_at_all` |
| Lane loops over mixed data (the second name of this row is the former "legacy worker" wording; both loops are fenced workers) | `::test_two_lane_processes_and_a_legacy_worker_together_never_cross_names` |

### 4.4 What happens when things change after approval

| Event | Behaviour | Proof |
| --- | --- | --- |
| The setting is changed | already-reviewed and approved posts keep the name they were approved with; only later reviews use the new one | `::test_a_name_changed_after_approval_never_reaches_the_wire_or_the_readback` |
| A legacy approval without an override | byte-identical wire to RC1 (no `username`), same digest as RC1 computes, still authorized by RC1 | `::test_an_approval_without_an_override_is_byte_identical_to_rc1` |
| The master switch goes off after approval | a post that carries a frozen name is HELD in the preflight with nothing sent and no intent sealed (event "Discord custom sender names are switched off; nothing was posted."); posts without a name, bot posts and every receipt check are unaffected. It is never stripped of its name and never sent under the webhook's own name, because its approval covers exactly that content. Switching back on does not resend a held approval: it stays held | `::test_a_held_named_post_is_never_stripped_or_sent_under_another_name`, `::test_switching_off_after_the_create_never_blocks_the_receipt_check`, `test_discord_sender_name_postgres.py::...::test_switching_the_feature_off_holds_only_the_named_posts_and_they_stay_held_when_it_returns` |
| The switch is off when a post is REVIEWED | no name is frozen: the post goes out under the webhook's own name, which is what the review shows | matrix test above |
| The connection is reconnected | a reconnect by the same member creates a new webhook and a new connection id; the Rafii-side name is carried to it (new revision), the old connection is revoked and its approvals are not authorized (new authorization generation). A first connection starts without a name | `::test_reconnect_with_a_new_authorization_generation_blocks_the_old_approval`, `test_discord_sender_name_claims.py::WebhookReconnect` |
| The webhook is deleted in Discord | before the run: the preflight fails, nothing is sent; during the run: Discord's 404 on the create is one rejected create (held, evidence `rejected`), never retried | `::test_webhook_deleted_before_the_run_sends_nothing`, `::test_webhook_deleted_during_the_run_is_one_rejected_create_never_retried` |
| The stored name is missing | the webhook's own name is used and the manifest carries no name | `::test_missing_name_uses_the_webhooks_own_name_and_says_so_in_the_manifest` |
| The stored name is invalid (corrupted, or fails today's rules) | the review fails (no manifest, so nothing to approve); a frozen name that stops validating is refused in the preflight before any request. It is held, never sent under another name | `::test_an_invalid_stored_name_holds_the_review_and_nothing_is_sent_under_any_name`, `::test_a_frozen_name_that_stops_validating_is_held_before_any_request` |
| Rollback to the frozen RC1 worker | RC1 builds the wire without the name; its digest cannot equal the approved one, so RC1 treats the approval as not current and holds it. Approvals without a name keep working on RC1 | `::test_rollback_to_the_frozen_rc1_worker_holds_every_named_manifest_and_only_those` (against the pinned RC1 `authorization.py` in `tests/phase2/fixtures/`) |
| The provider rewrites the name (collapses spaces, strips a character) | the created message is read back with the author name and compared to the frozen name: a mismatch is `uncertain`, accepted, never retried. Space tricks are refused at save time so that ordinary names are unchanged | `::test_a_provider_that_rewrites_the_name_is_not_verified_and_is_not_retried` |
| Discord answers 400 for a name | a rejected create, nothing resubmitted automatically | `::test_provider_400_for_a_name_is_a_rejected_create_not_an_uncertain_one` |

## 5. Bot nickname across tenants

### 5.1 Can two workspaces hold the same server? (measured from the code)

Yes. `pr_encrypted_credentials` is keyed `(workspace_id, connection_id)` and an installation's id is
`stable_id('install', workspace, application, guild)`: one per workspace and server, with no uniqueness across
workspaces. `launch_gate.py` says so in as many words ("a server that already has a bot credential row ... starting it
again, from this or another workspace, must not need a second [slot]"; `shared_remote = True`: "every workspace
connected to that server shares" the one bot). Starting an installation needs only the identity's `owner`,
`ADMINISTRATOR` or `MANAGE_GUILD` on the server, which is weaker than the permission needed to rename the bot
(`MANAGE_NICKNAMES`). So two workspaces whose authorizers both manage one server can both hold an installation, and
nothing in RC2 before this branch stopped both from writing the one nickname: the last PATCH won.

### 5.2 The options, as decided

| Option | Verdict |
| --- | --- |
| (ii) A migration adding a per-server lease table | **Not needed and not written.** It would be a Production database change that needs the owner's separate approval. It would add one capability the chosen design lacks (the first workspace keeps authority when a second arrives) and costs a migration, a Production change and a new failure mode (a lease stranded by a crash). Recorded here so the owner can ask for it. |
| (iii) Isolation only | **Applied as the default state**: `POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED` is off everywhere unless the exact string `true`. With it off the routes answer `bot_nickname_disabled`, make no Discord request and write nothing. This is the shipping position until live acceptance has been done. |
| (i) No migration: write only while this is the server's only live bot installation | **Chosen, built, tested.** `DiscordConnections.nickname_contenders` counts the OTHER unrevoked bot installation rows for the same server in `pr_encrypted_credentials` (any workspace) and the nickname is writable only when the count is 0. |

### 5.3 Why (i) is exclusive (and what the guild lock adds)

The argument needs no lock. Let `cA`, `cB` be the commit instants of the two installation rows becoming live, and `tA`, `tB` the instants of their
final guards (the last check before the Discord write, after rate admission). A workspace can only write after its own
row is live, so `cA < tA` and `cB < tB`. A passes only if B's row is not visible at `tA`, which needs `tA < cB`; B passes only
if `tB < cA`. Together `cA < tA < cB < tB < cA`, a contradiction, so at least one of the two is refused by the guard.
The row a reconnect brings back (`revoked_at` set to NULL by the upsert) is the same event. The argument needs only
READ COMMITTED reads of committed rows. It is exercised with real threads against PostgreSQL in
`test_discord_sender_name_postgres.py::RoutesOnPostgres::test_two_workspaces_racing_for_one_server_never_both_write_a_nickname`
(10 rounds, a reconnect racing a write: never more than one PATCH, and the second workspace never writes) and by
the sequencing tests in `test_discord_sender_name_routes.py::SharedServer`.

Review finding SNR-1a asked for a server-level lock taken by the installation path as well. It is there, as an ordering aid and
not as the proof: both the authority check and `save_installation` take a transaction-scoped advisory lock keyed by
application and server (`pg_advisory_xact_lock(hashtextextended('rafii.discord.nickname:<app>:<guild>', 0))`), released at
commit, never held across Discord IO, with one global lock order (workspace row, credential rows, this lock) so two workspaces
cannot deadlock. It makes "the installation commits strictly before or strictly after the check" literally true instead of only
true by the contradiction above. No table, no migration. Proof on PostgreSQL:
`ClaimFlowOnPostgres::test_the_guild_lock_orders_the_authority_check_after_a_concurrent_installation` (a check that starts while an
installation holds the lock waits, then sees the installation's row); in memory:
`test_discord_sender_name_routes.py::SharedServer` and the lock-statement assertion in the settings fixture.

Consequences, stated plainly:

* When two workspaces hold the server, NEITHER may change the nickname (a symmetric lock). The visible reason is
  `nickname_authority_other_workspace`: "another Rafii workspace also has this server connected". No identifier, name,
  count, time or order is disclosed.
* The lock is released by what already releases an installation: a disconnect, an identity loss or a revoked
  credential sets `revoked_at`, and the other workspace's next check sees count 0. Nothing is stored that can be stranded.
* A stale but unrevoked installation (the bot was kicked, the workspace is abandoned) keeps the lock closed. That fails
  closed. An operator can list the holders of a server with
  `SELECT workspace_id, connection_id, revoked_at FROM public.pr_encrypted_credentials WHERE provider='discord' AND provider_account_id=<server id> AND 'bot' = ANY(scopes)`
  and revoke a stale row through the normal disconnect.
* A guild admin who has their own Rafii workspace can lock the nickname for another workspace of the same server by
  installing there. They can already rename the bot natively, so this removes no capability they did not have.

### 5.4 Who may authorize (Discord-level restrictions)

Every nickname edit re-reads, with the bot token and through the shared request coordinator, immediately before the
write: the server and its roles, the authorizing person's member roles, the bot's member roles and nickname. The edit is
refused unless: the person is the server owner, or holds `MANAGE_NICKNAMES` or `ADMINISTRATOR`, **and** (unless owner) their
highest role is strictly above the bot's highest role (Discord's own hierarchy rule, which Administrator does not waive);
and the bot holds `CHANGE_NICKNAME` or `ADMINISTRATOR`. A person who only has Manage Server (enough to install the bot)
cannot rename it. The bot is never asked to change anything but its own nickname in that server
(`PATCH /guilds/{id}/members/@me`; the transport refuses the call without a guard and refuses the guard on any other route).
Only the member whose Discord account installed the bot may edit it (`authorizing`); every other member sees it read-only.
Each write carries `X-Audit-Log-Reason: Rafii shared bot nickname change (ref <16 hex>)`, a one-way hash of application,
server and workspace, so a server administrator reading the server's audit log can tell a Rafii change from a person's and
quote the reference to Rafii; it names no workspace, person or customer text (`BotNicknameInTheApproval` audit-reason test and
`ClaimFlowOnPostgres::test_a_successful_write_leaves_one_observed_admission_no_claim_and_an_audit_reason_for_the_server`).

### 5.5 What remains impossible

* Discord has no compare-and-set on a nickname. Native administrators (Manage Nicknames above the bot's role, or the
  owner) can rename the bot at any moment, and Rafii cannot stop or order that. The product therefore shows the
  nickname Discord reports (`observedName`), flags `externalChange` when it differs from the one Rafii last set, and
  never claims ownership.
* A post already sent is displayed under whatever the nickname is when Discord renders it; Rafii can only hold a queued post
  whose approved nickname no longer matches (5.6), and a rename between that check and the create is still possible (one request
  apart).
* The check is between Rafii writers only. An external tool using the same bot token would not be seen.
* The bot is not installed with `CHANGE_NICKNAME` (the install permission set is View Channel, Send Messages, Attach
  Files and Read Message History). A server admin has to grant it; until then the reason is `bot_missing_change_nickname`.

### 5.6 The nickname in the approval (SNR-1b)

When both switches are on, a review records the nickname Discord last reported for the bot member (read by the member verify
actions and by this connection's own verified write) as `manifest.discordBotNickname` (`null` = no nickname). It is not part of the
wire or any digest, so RC1 still authorizes such an approval. At dispatch `prepare_discord_dispatch` compares it with the nickname
the destination check just read (the same bot-member request that already supplies the roles, so zero extra requests) and HOLDS the
post, nothing sent, no intent sealed, when they differ (`discord_bot_nickname_changed`, event "The Rafii bot's server nickname is no
longer the one this post was approved under. Nothing was posted."). Automation decisions bind the nickname the person saw like they
bind a webhook name; because the frozen nickname is part of the publication id (though not of the wire), switching the capability off
between an automation decision and its queue commit makes the commit ask for a new approval (`discord_approval_required`). Proof: `test_discord_sender_name_wire.py::BotNicknameInTheApproval`, and on the lane
`LaneAndWorkerOnPostgres::test_a_bot_post_approved_under_one_nickname_is_held_when_the_server_nickname_changed` and
`::test_a_frozen_bot_nickname_adds_no_request_to_a_bot_post`.

## 6. Concurrency

| Case | Control | Proof |
| --- | --- | --- |
| Two members edit at once | webhook: any manager may edit, the second form is stale; bot: only the installing member can write, any other manager gets `not_authorizing_member` with no Discord request | `test_discord_sender_name_routes.py::Roles::test_any_connection_manager_edits_a_webhook_name_but_only_the_authorizer_edits_the_bot_nickname` |
| Two tabs of the same member | the second form's fingerprint is stale: `discord_sender_name_required`, no write | `::Freshness::test_two_tabs_of_the_same_member_cannot_both_save` |
| Replay of an old fingerprint | same, refused before any Discord request | `::Freshness::test_an_old_fingerprint_cannot_be_replayed` |
| Edit racing a send | the send uses its frozen manifest; the edit changes only later reviews | wire tests above |
| Edit racing an approval | the approval keeps the name its review showed | `test_discord_sender_name_wire.py::test_an_approval_keeps_the_name_its_review_showed` |
| A lease taken over mid-send | the new owner sends from the same manifest, so the same bytes; an unresolved create is never re-posted (existing P0/W-02 rules); the read-back compares the frozen name | W-02 lease tests (existing) plus the read-back tests above |
| Ambiguous nickname write | an exclusive claim (with the coordinator admission id) is committed before the write; further edits stop until a read after the 2-minute deadline reconciles it. A write PROVEN unsent (final guard refused, coordinator delay or error before the transport, an admission blocked) or REFUSED by Discord (4xx) frees the claim at once with its own code; only a lost response, a transport failure or an unconfirmed answer keeps it. A reconnect keeps the claim. After a bot-token rotation the claim waits 15 minutes for the coordinator, then is abandoned and audited | `test_discord_sender_name_claims.py::{UnsentWrites,ObservedRefusal,LostResponses,Reconnect}`, `ClaimFlowOnPostgres` (real coordinator) |
| Two workspaces writing one server | section 5.3 | `::SharedServer` and the PostgreSQL race test |

## 7. Name abuse

One rule set, enforced by the server (the UI may pre-check) on save and again, for webhook names, whenever the wire is
built: length 1 to 80 (webhook) or 32 (bot) in code points and also in UTF-16 units; NFC; no surrounding space; no control, format,
bidi, zero-width, tag, private-use or unassigned code points (two exceptions real text needs: a zero-width joiner only between symbols of one emoji sequence, a zero-width non-joiner only between letters of a script that uses it, never between Latin letters); only single ASCII spaces inside; no characters that render
as nothing (Hangul fillers, Braille blank, combining marks alone); none of `@ # : ``` < >`; no `www.` link text; and no
reserved word after folding.

| Threat | Control | Test |
| --- | --- | --- |
| `discord`, `clyde` (Discord's own rule for webhook names) in any case, for webhook AND bot names | refused | `test_discord_sender_name_rules.py::Refused` |
| homoglyphs: Cyrillic or Greek look-alikes, full-width letters, accents, separators, leetspeak (`d1scord`, `d i s c o r d`) | the reserved-word comparison folds NFKD, strips marks, maps a compact confusables set, drops separators and tries both `1` readings | `::Refused` |
| `everyone`, `here` as the whole name | refused | `::Refused` |
| impersonating the product (`rafii`, `postriff` anywhere) | refused. This is a policy choice, one tuple (`_RESERVED_PARTS`), easy to change | `::Refused` |
| impersonating another customer | not preventable and not attempted: names are self-asserted, exactly as with any Discord webhook, and a name is only ever shown in the customer's own channel. A uniqueness check would itself leak other customers' names, so none is made | n/a (accepted) |
| mention syntax (`@everyone`, `<@id>`, `<@&id>`, `<#id>`), markdown links, URLs | the characters are refused, and independently every execute carries `allowed_mentions: {parse: []}`; Discord does not render markdown or links in an author line. A name cannot ping | `::test_a_name_cannot_ping_or_link`, `test_discord_sender_name_wire.py::test_content_that_mentions_everyone_still_cannot_ping` |
| control, format, bidi override, zero-width, tag characters | refused | `::Refused` |
| empty after normalization, blank-looking names | refused (`empty`, `invisible`) | `::Refused` |
| a name Discord would collapse (double spaces, no-break and ideographic spaces) | refused at save, so the read-back of an approved post still equals the approved name; the read-back itself compares after Unicode NFC and whitespace canonicalisation (`names_equivalent`), not byte for byte | `::Refused`, `test_discord_sender_name_rules.py::ReadBack::test_equal_and_normalised_names_match` |
| rules tightened later | queued posts whose frozen name no longer validates are held in the preflight, nothing sent | `::test_a_frozen_name_that_stops_validating_is_held_before_any_request` |

Not covered, honestly: Discord applies further private anti-abuse rules to names ("rules and restrictions not shared"),
and its exact webhook-override rules were not observable here. A name Discord rejects at send time comes back as a 400,
becomes a rejected create (held; nothing resubmitted) and is a reason for a live acceptance step before the feature is switched on.

## 8. The invalid-request budget

Discord counts 401, 403 and 429 (not shared-scope) responses toward 10,000 per 10 minutes for the whole application; the
coordinator keeps an `invalid` row that debits one per such response and blocks when it is spent.

* A nickname PATCH without `CHANGE_NICKNAME` would be a 403. It is not sent: the permission preflight is read first and the
  route answers `bot_missing_change_nickname` with reads only (`::BotPermissions`).
* The one race left is a permission removed between the preflight read and the write. A 403 there is one invalid request,
  and the coordinator then opens the circuit of that route for that server (the `403/404` branch of `observe()`
  sets the route row's circuit to the policy's expiry), so a second attempt is refused locally. The blast radius of a
  hostile admin is therefore about one invalid request per server per policy period, and servers are capped (90 in
  production). Burning 10,000 would need 10,000 servers. Measured: no code path makes a second PATCH after a refusal
  (`ObservedRefusal::test_a_discord_refusal_releases_the_claim_has_its_own_code_and_is_never_retried`, and on the real coordinator
  `ClaimFlowOnPostgres::test_a_refusal_by_discord_releases_the_claim_and_never_replays_the_write`). The side effect of that circuit
  is the reviewer's measured finding SNR-5: it stays open for the policy lifetime, so the customer who then fixes the permission
  is told `discord_rate_delayed` until it expires. That is the coordinator's behaviour (`rate_limits.py`, not modified here);
  `REQUESTS-TO-RATE-LIMITER.md` R4 asks for a short circuit on this one route.
* Webhook executes with a bad name are 400s, which do not count. A deleted webhook is a 404 on a webhook credential, which
  does count (`webhook_invalid`), once, and then the webhook's circuit is open.
* Added by this branch: per-connection throttles (12 reads, 6 writes per 10 minutes) and per-workspace throttles (40
  and 15), counted in the existing `pr_auth_throttle` table before any provider request. A throttled request makes no Discord
  call (`::Switches::test_reads_are_throttled_per_connection_and_a_throttled_read_makes_no_discord_request`), and so a loop of
  settings page views cannot take the application's shared request budget from other customers' posts.
* The settings page no longer re-verifies the connection (upstream's GET called `reverify_webhook`, which writes state and an audit
  event on every page view and marks the connection unverified on any transient Discord error, holding its scheduled posts).
  Only the explicit verify actions do that now. Measured cost of one call (`Fanout::test_exact_cost_of_each_route`): bot GET 5 Discord
  requests cold and 2 workspace transactions (upstream: about 9 to 11 reads and 19 transactions), bot POST 6 reads and 1 write and 7
  transactions (upstream 11 to 13 requests, 26 transactions); webhook GET 1 request, POST 1 request.
* Validation, the throttles and the shared-coordinator readiness gate (`provider_unavailable`) all run before any provider request,
  so an invalid name, a throttled loop or a coordinator that cannot admit requests costs Discord nothing
  (`test_discord_sender_name_claims.py::ReadyGate`, `::Bodies`).
* A lost nickname write whose admission can never be matched again (bot token rotated) leaves one `uncertain` admission that
  the coordinator counts as pending without an age bound; the reviewer measured the application window going from 25 to 24.
  `REQUESTS-TO-RATE-LIMITER.md` R2/R3 ask for the token-independent reconcile and the age bound; until then it is one rate slot per
  such event, characterised by `ClaimFlowOnPostgres::test_after_a_bot_token_rotation_the_admission_is_retired_by_id_if_offered_and_otherwise_stays_an_orphan`.

## 9. Information leaks

| Question | Answer | Test |
| --- | --- | --- |
| Does a refusal reveal that a workspace or connection of another customer exists? | No. A foreign, non-existent and malformed workspace id get the same `403 permission_denied "Workspace unavailable."`. Another workspace's connection id, a non-existent id and a malformed id inside your own workspace get the same `404 not_found`. Malformed ids never reach the database as a typed value (workspace ids are checked before any SQL; connection ids are matched against a pattern). | `::CrossTenant`, `RoutesOnPostgres::test_cross_tenant_matrix_on_the_real_repository_and_sql` (injection strings, 5,000-character ids) |
| Does any response contain another customer's name, id, guild, channel, webhook or credential? | No, and the webhook token is never returned, never an input of the fingerprint and never audited | `::test_a_tenants_names_and_ids_never_appear_in_the_other_tenants_responses` |
| What does the audit trail hold? | event kind, actor, connection id, sender kind, scope, server id. Never the name. The server's OWN audit log gets a one-way reference (section 5.4). | `RoutesOnPostgres::test_save_replay_stale_session_and_role_refusals_on_real_rows` |
| The one cross-workspace fact | `nickname_authority_other_workspace` tells an authorized member that some other Rafii workspace also has THEIR OWN server connected. No identifier, no number. Both workspaces see the same thing. | `::SharedServer` |
| Do refusals leave traces? | No state change in any workspace, no audit event and no Discord request, for every refusal in the matrix (the snapshot of states, audit, credentials and the Discord side is compared before and after) | `::CrossTenant`, `::Roles`, `::Bodies` |

## 10. Authentication, roles and the sensitive-action gate

Covered by `test_discord_sender_name_routes.py` (in-memory store with the real route, custody, membership and throttle code)
and `test_discord_sender_name_postgres.py::RoutesOnPostgres` (the real repository and SQL): both directions between two
workspaces for every pairing of workspace id and connection id; viewer, editor, approver (all `403 permission_denied`);
an admin or an editor with `can_manage_connections` who is not the bot's installer (read-only for the bot nickname,
`not_authorizing_member`; allowed for a webhook name);
removed and deleted members (the foreign-workspace answer); an authorizer who lost access (`discord_connection_required`);
blocked and deleting accounts; stale sessions (read allowed, write `step_up_required`); the application guard header and the
`connections` security gate through the real router; malformed bodies; replay.

## 11. Exceptions and residual risks

1. **Bot nickname is isolated by default (off) and is not claimed to pass as a whole.** The code path is built and tested
   against a synthetic Discord and a real PostgreSQL, but no real Discord server has been used: whether the bot's
   `CHANGE_NICKNAME`, the hierarchy rule and the nickname verification behave as modelled is unverified until a live
   acceptance in a disposable server.
2. Webhook sender names were never exercised against real Discord either, and the webhook route is dark in Wave 1: the field's
   acceptance, Discord's sanitising of `username`, and the author name in the read-back are modelled. Live acceptance (one
   separately approved post whose observed sender equals the preview) is still required before that route opens.
3. Migration 131 (admission credential kind `webhook`) is required in Production for any webhook execute; it is part of the
   Discord candidate, not of this branch. Without it the coordinator refuses every webhook request (the lane shows
   `rate_delayed` releases). The shared W-02 lane fixture does not apply 131; `CAPACITY-NOTES.md` says what the capacity harness must add.
4. A symmetric lock means a second workspace in the same server disables nickname editing for the first. Chosen over a
   first-come lease to avoid a Production migration; revisit if the owner wants the first workspace to keep authority.
5. Rollback to RC1: an approved post that carries a custom webhook name is held by RC1 (its digest differs), and a NEW approval made
   under RC1 silently drops the name, because RC1 ignores the setting (SNR-9). Rolling back with the feature live therefore changes what
   customers' future posts are called without any message; this must be said in the rollback instructions.
6. The nickname held-at-dispatch rule needs the connection to have observed the nickname at least once (a member verify action
   or its own write); a connection that never has records no frozen nickname and is not held for it.
7. The coordinator limits listed in `REQUESTS-TO-RATE-LIMITER.md` (R2 to R4) are not decided by this branch; each has a tested fallback.
8. The reserved-word and confusables logic is a compact heuristic, not the full Unicode confusables table.
9. Operator access to the database is outside this model.
