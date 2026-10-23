# RC2 shared-path fixes: regressions in code existing customers use

Owner's condition (reply 13, `docs/launch-20261023-discord/AUTHORIZATION-RECORD.md`): while Discord is switched off for
them, existing Production customers see no observable regression or side effect from the candidate. The customer
impact inventory (`docs/CUSTOMER-IMPACT-INVENTORY.md`, merged here from `claude/discord-impact-20261023 @9f1946cf`)
found the regressions below; this branch fixes them. Facts first; *inference* marks what was read but not run.

| | |
|---|---|
| Branch | `claude/discord-rc2-fixes-20261023` |
| Base | the W-02 head `150ab4fa` (RC1 `2a5a523d` + the W-02 lane); later merged W-02 `4a776000` (test-only) and `820d8c7d` (RC2-1 in `lane.py`, W-02 tests), and the impact branch `9f1946cf` (docs, scripts and tests only) |
| Live | `c5fc1fd1` (`dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`) |
| Head tested | `60ca222d` (the last production-code fix is `2ca119ad`; after `60ca222d` only documentation changed) |
| Method | every fix has tests that fail on `150ab4fa` and pass here; where a behaviour exists on live, the same probe or scenario runs with the live tree (`git archive c5fc1fd1`) and with this tree and the records are compared. No network, no Production access, nothing deployed |

## Summary

| Fix | Severity | Commit | Production code changed | Tests failing on `150ab4fa`, passing here | Live comparison |
|---|---|---|---|---|---|
| FB-1 Facebook Page approvals | HIGH | `9c044aa7` | `store.py` (-2), `oauth.py` (-16) | 9 offline (11 failures with subtests) and 4 of 7 on PostgreSQL | identical to live, offline and on PostgreSQL |
| CH-1 Channels read | MEDIUM | `4d41a86a` | `oauth.py` (+6 -1) | 1 offline (2 subtests), 1 on PostgreSQL (4 subtests) | identical to live for workspaces without Discord links |
| PR-1 interactions route | LOW | `741daa4b` (supersedes `651e1899`) | `hosted_app.py`, `discord/interactions.py` (+25 -13) | 3 (8 failures + 1 error) | same log level, status class and no runtime as live; status 404 where live says 403 |
| UI-1 Personal Discord accounts | MEDIUM-LOW | `3d331c41` | `channels-view.tsx`, `discord-personal-account.ts` (+14 -2) | 3 of 4 web tests | not applicable (live has no such section) |
| ENV-1 pool settings | LOW | `ad6f26ad` | `hosted_app.py`, `postgres_pool.py` (+38 -6) | 3 of 4 (8 errors with subtests) | live has no pool; the API stays up as on live |
| Cron Authorization on non-ASCII headers (independent review) | LOW, pre-existing | `2ca119ad` | `hosted_app.py` (+8 -2) | 2 of 3 (7 failures), also on the live tree | an improvement over live (live answers 500) |
| Impact suites merged, FB-1 and CH-1 as guards | | `7c8734cf`, `604417d2`, `b9b1383b` | none | 3 guards fail with `IMPACT_RC_REV=150ab4fa` | the impact agent's live-versus-candidate suite: 32 tests OK |
| Synthetic credentials generated at run time (offline secret scan, rule P2-SEC-CI-04) | | `438b5816`, `5c7531dc`, `60ca222d` | none (tests only) | the scan: 8 unexpected findings before `438b5816`, none on `60ca222d` | not applicable; the tests behave as before |

## FB-1: Facebook Page posts approved exactly as on live (`9c044aa7`)

**What was wrong (measured).** `Phase2Store.current()` returned False for every Facebook manifest unless
`manifest.destinationId == channel.destinationId`, and no code writes `manifest.destinationId` for Facebook. Every
Facebook review was born `stale`, approval was refused ("Review and explicitly approve this exact destination
manifest.", 409), and a Facebook post approved on the live build was held at the next `invalidate()` ("Approval,
capability or entitlement changed. Review timing and approve a new job; reconnection does not release this one."),
which ends every hosted command and every worker claim of the workspace. The Page choice
(`OAuthService.choose_destination`) also relabelled the channel to the Page, upserted nine capability rows (and could
clear `capabilityVerified`: it did in the probe, whose adapter is not marked reviewed), bumped the workspace revision
and ran `invalidate()`; live changes only the encrypted grant.

**Cause.** `381ac2d0` (2026-10-08, "preserve minimum Facebook connections", on the social-connection-recovery line,
never on the live line) had three coordinated pieces: freeze the chosen Page id into the manifest (and refuse a review
without a chosen Page) in `build_manifest`, check it in `current()`, record the Page id on the channel at Page choice.
The Discord line's squash `1791d6d1` (2026-10-15) took the last two, and `17e3844c` carried them into the candidate.
The live tree has none of the three (checked: no `destinationId` in live `store.py`; live `choose_destination` has no
Facebook branch), so there was no third piece to restore.

**Fix.** Both hunks removed (18 lines). Verified by diff against `c5fc1fd1`, function by function: `current()`,
`choose_destination()`, `_capabilities()` and `_member_grant()` now differ from live only in branches gated on
Discord (`platform == 'Discord'`, `adapter.id == 'discord'`, `operation == 'discord.reply'`), and the only
Facebook-specific line left in the whole `src/`+`api/` difference to live is in `connection_review.py`, a helper
called only from `discord/oauth.py` (guarded by `test_no_other_facebook_code_differs_from_live`).

**Tests.** `tests/test_rc2_shared_path_fixes.py` with the probe `tests/rc2_facebook_probe.py` (no database):
`FacebookApprovalUnchanged` (`test_a_facebook_page_review_is_current_and_approvable`,
`test_an_approved_facebook_post_survives_invalidate_and_the_worker_claim`,
`test_a_page_id_recorded_on_the_channel_changes_nothing`, `test_choosing_a_facebook_page_changes_only_the_grant`,
`test_no_facebook_branch_in_the_approval_check_or_the_page_choice`) and the differential `FacebookMatchesLive`
(`test_reviews_approvals_and_invalidation_are_identical_to_live`, `test_a_post_approved_on_live_is_kept_by_this_build`,
`test_choosing_a_facebook_page_is_identical_to_live`, `test_no_other_facebook_code_differs_from_live`): all 9 fail on
`150ab4fa`. On real PostgreSQL, `tests/test_rc2_shared_paths_postgres.py` with `tests/rc2_shared_path_scenario.py`
(adapted from the impact agent's scenario): a Facebook Page post prepared through the ordinary hosted commands, approved,
followed by one more hosted command and one minute tick of the worker (provider calls go to an in-memory Graph fake
that answers the permission list, the Page list and one feed create):

| Run | review | approval | after the next command | after one worker tick |
|---|---|---|---|---|
| live tree | `needs_review` | `scheduled` | `scheduled` | `provider_accepted`, "Facebook created the Page post; read-back pending", one POST to `/{page}/feed` |
| `150ab4fa` | `stale` | refused (409) | (no job) | (no job) |
| `150ab4fa`, post approved by the live tree | | `scheduled` | **`held`** | **`held`**, nothing sent |
| this branch, and the live-approved post | `needs_review` | `scheduled` | `scheduled` | identical to live |

`test_a_facebook_page_post_is_approved_as_on_live`, `test_the_next_hosted_command_keeps_the_approved_post_as_on_live`,
`test_the_worker_claims_and_sends_the_facebook_post_as_on_live` and
`test_a_facebook_post_approved_on_live_is_kept_and_sent_by_this_build` fail on `150ab4fa`. The impact agent's
`test_a_facebook_page_post_is_approvable_as_on_live` is now a guard (its `expectedFailure` removed in `604417d2`).

**Risk.** Low: Facebook returns to the live code paths. Not shipped: the Page binding of `381ac2d0` itself; shipping it
deliberately would need all three pieces, tests and a plan for the Page-less Facebook channels live created (they would
be refused at review until the person chooses a Page again).

## CH-1: no extra transaction on a Channels read (`4d41a86a`)

**What was wrong (measured).** With `POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED=true` (set in Production) and Discord
mounted, `OAuthService.channels()` called `discord_connections.public_identities()` for every workspace: a third
repository transaction (one more session verification, which in Production is one Supabase Auth `getUser` HTTPS call
plus a session-flag connection, *inference from `supabase_verifier`, which has no cache*; one more connection; a
`SELECT ... FOR UPDATE OF w` lock on the workspace row) to return `[]`.

**Fix.** `channels()` asks for the identity list only when the workspace state it already read (the snapshot) holds
Discord identity links; otherwise the list is `[]` without the read. For a workspace with links the call and its result
are exactly as before. *Inference*: a link added between the snapshot read and the former identity read is shown on the
next Channels read; the channel list itself has always come from the same snapshot.

**Measured** on real PostgreSQL, one Channels read (session verifications / connections / workspace-row transactions /
statements; the synthetic verifier opens no connection, Production adds one per verification):

| Workspace | live | `150ab4fa` | this branch |
|---|---|---|---|
| no Discord data | 2 / 2 / 2 / 7 | 3 / 3 / 3 / 8 | **2 / 2 / 2 / 7** |
| a linked Discord identity | 2 / 2 / 2 / 7 (no list) | 3 / 3 / 3 / 8 | 3 / 3 / 3 / 8, the identity listed unchanged |

**Tests.** `ChannelsReadAddsNoTransaction.test_a_workspace_without_discord_identity_links_costs_what_live_costs` and
`test_a_channels_read_without_discord_data_costs_what_live_costs` (PostgreSQL) fail on `150ab4fa`; the pins of
unchanged behaviour pass on both (`test_a_linked_identity_is_still_listed_through_its_own_read`,
`test_another_members_link_is_not_listed_as_before`, `test_connections_v2_off_reads_nothing_more`,
`test_a_workspace_with_a_linked_discord_identity_still_lists_it`). The impact agent's
`test_channels_read_opens_no_more_database_transactions_than_live` is a guard now, and its pin of the extra
transaction became `test_channels_read_runs_exactly_the_statements_live_runs`.

**Risk.** Low.

## PR-1: the interactions route while the feature is off (`741daa4b`)

**What was wrong (measured with `tests/rc2_interactions_probe.py`).** `POST /api/discord/interactions` is answered
before the bearer and origin checks. With the user-install flag unset RC1 answered 503
`discord_interaction_unavailable`, logged at ERROR and counted as 5xx; in a cold process it first started the hosted
runtime for the unauthenticated request. Live has no such route: the application guard answers 403 at INFO without the
runtime.

**Fix (the coordinator's choice: 404).** While the feature is off (the flag unset, Discord not mounted, or its kill
switch on) the route does not exist: every method, scheme and body answers 404 `not_found` (the answer a GET always
had), at INFO, decided before the runtime, a key, the body or the database is touched. A cold process reads
`POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED` with the provider registry's exact-string rule; a running one asks the mounted
adapter (`discord.interactions.enabled`); `receive()` repeats the check. With the feature on nothing changes: method,
HTTPS, content-type and size checks, signature verification (PING to PONG, a bad signature 401), the replay claim, and
503 for a missing or wrong interaction configuration. A first version answered 401 (`651e1899`), the status Discord's
endpoint verification expects for an unverified request; the coordinator chose 404.

| Case (POST unless noted) | live | `150ab4fa` | this branch |
|---|---|---|---|
| cold process, flag unset | 403, INFO, no runtime | 503, ERROR, runtime started | 404, INFO, no runtime |
| running, flag off / kill switch / Discord absent | 403, INFO | 503, ERROR | 404, INFO |
| GET, plain HTTP, `text/plain` | 401 or 403 (session or guard) | 404 / 400 / 415 | 404 |

**Trade-off (recorded in `route_unavailable()`).** Discord's endpoint verification and its routine checks expect 401
for a bad signature; an interactions URL left registered in the Discord portal while the feature is off may be flagged
or removed by Discord. Registering it is part of turning the feature on.

**Tests.** `DiscordInteractionsOffIsQuiet.test_every_off_state_is_a_quiet_404_without_the_runtime`,
`test_the_route_decides_on_and_off_exactly_as_the_adapter_flags_say` and
`DiscordInteractionsOffMatchesLiveLogging.test_same_log_level_status_class_and_no_runtime_as_live` fail on `150ab4fa`
(and the first two on `651e1899`); `test_on_keeps_signature_verification_and_reports_misconfiguration` pins the on
behaviour on both.

**Not changed (attention when turning the feature on).** The impact agent's scheme caveat: the route requires
`wsgi.url_scheme == 'https'`; if Vercel's Python runtime reports `http`, every Discord request would be refused 400
with the feature on (UNKNOWN; one POST to the staged build settles it).

## UI-1: Personal Discord accounts only where Discord is open or linked (`3d331c41`)

`channels-view.tsx` rendered the section whenever the Discord provider reported `discordConnectionsV2` (true in
Production): every member of every workspace saw "Personal Discord accounts", a disabled connect button and "New
connections are currently unavailable". The new helper `showDiscordPersonalAccounts` (in
`lib/channels/discord-personal-account.ts`) shows it only when the server's per-workspace gate verdict
`discordAccess.status` is `open` with the connections v2 flow on, or when the workspace already has linked identities
(they stay visible and manageable). A missing verdict counts as closed. The Connect sheet's closed-gate message (UI-2)
is unchanged. `web/tests/discord-personal-accounts-visibility.test.cjs` runs the helper (Node strips the types; the
`typescript` package is used when installed) and checks the wiring: 3 of its 4 tests fail on `150ab4fa`, the UI-2 pin
passes on both; with `discord-launch-gate.test.cjs`, 11 of 11 pass.

## ENV-1: pool settings never take the API down (`ad6f26ad`)

`runtime_from_environment` ran `int()` on `POSTRIFF_DB_POOL_MAX_CONNECTIONS` and `POSTRIFF_DB_POOL_MAX_WAITING` even
with the pool off, and `PooledPostgresFactory` refused out-of-range limits when it was on: either way one bad value
failed runtime construction and every runtime route answered 503. `hosted_app.pool_settings` now keeps the pool off
(fail-closed: one connection per transaction, as without the pool) when a limit is not a whole number within the
pool's own bounds (1-32, 1-256, one source in `postgres_pool.py`), and writes one WARNING per process,
`database.pool_settings_invalid`, naming the variables and whether the pool was requested, never the values. Valid
settings are used exactly as before. `PoolSettingsNeverTakeTheApiDown`: 3 of 4 error on `150ab4fa` (runtime
construction raises), the valid-settings pin passes on both.

## Cron Authorization on non-ASCII headers (independent review; `2ca119ad`)

`/api/cron/agent-tasks` and `/api/cron/worker` compared the header with `hmac.compare_digest` on `str`, which raises
`TypeError` for non-ASCII text (WSGI delivers header bytes as latin-1): an unauthenticated request answered 500 with an
ERROR line, on live too. Both now use the W-02 shard route's guard (refuse a secret or header that is not an ASCII
`str`, 401). `CronAuthorizationRefusesNonAsciiHeaders`: 2 of 3 fail on `150ab4fa` and on the live tree; the ASCII pin
passes on all. **Reported, not changed:** `/api/cron/worker` starts the runtime before it authenticates (live line 777,
`150ab4fa` line 843, here line 883); the runtime also supplies `self.cron_secret` there.

## Synthetic credentials at run time (`438b5816`, `5c7531dc`, `60ca222d`)

The offline source scan (`scripts/consumer_ready_secrets.py`) reported 8 unexpected findings before `438b5816`, all in
test files this branch added or merged from the impact branch: 6 `Secret Keyword` (synthetic Discord client secrets,
Supabase keys, a PDF owner password) and 2 `Basic Auth Credentials` (database URLs with a user and password, never
connected) in `impact_scenario.py`, `rc2_shared_path_scenario.py`, `test_customer_impact_dependencies.py`,
`test_impact_compare.py` and `test_rc2_shared_path_fixes.py`. Following rule P2-SEC-CI-04, no scanner exception or
allowlist entry was added. Every credential-shaped value in the files this branch added or merged is now made per run
as `'synthetic-' + secrets.token_hex(12)` (through a `synthetic()` helper, so no literal follows a secret keyword; a
random Fernet key where one is needed), including values the scanner does not flag (bot, page, user and session
tokens, cron secrets, the capture test's bearer header and the fake builds' session cookie, the non-ASCII cron header
and secret, whose first character stays non-ASCII). Database URLs carry no user or password. Values two builds or two
processes must share are generated once per process (`test_impact_compare.SYNTHETIC`, the scenario's handoff file).
The tests behave as before: the same failures on `150ab4fa` and the live tree, and a negative control with cookie
redaction disabled fails on the generated cookie value.

## Half-carried changes in the integration (17e3844c, d4572f68) and where they came from

Method (read-only, git objects): (1) for each non-Discord file `17e3844c` changed, every line the repair branch head it
squashed (`ecbb9e36`) had and its base `7dc95e2e` lacked, attributed by `git blame` and checked in `17e3844c`;
(2) every distinctive line RC1 adds to live in the 49 non-Discord source files (2,264 lines), attributed to the oldest
commit on any branch that added it, then that commit's whole patch checked line by line against RC1 and live;
(3) `scripts/rc_superset_proof.py --base 7dc95e2e` for the merge.

Findings:

1. `17e3844c` itself carried its source faithfully (one schedule-dialog line of `c305e52f` dropped). The partial
   carries happened earlier, in `1791d6d1` (2026-10-15), the squash that brought non-Discord pieces of other lines onto
   the Discord release branch; `17e3844c` then carried them into the candidate.
2. `381ac2d0` (Facebook trio): FB-1, fixed. The same commit's preview-dispatch machinery (`worker_binding`,
   `previewDispatchPending`, `_invalidate_owned`, `execute_job`, the `/jobs/<id>/execute` route, the web "Publish
   approved post" button) was carried without its `hosted_app.py` wiring, so `worker_binding` is never set: dormant.
   Visible traces: `workerBinding: null` in every workspace read (inventory API-1), the execute route answers only
   Discord jobs (API-6), Facebook/Business Profile destination-picker wording (UI-8). Its `_capabilities` Page checks
   and Facebook adapter changes were not carried (consistent with live).
3. `6037ff7c` (2026-10-05, official social workflows): `nativeScheduleAt` readers carried (the approval's `nextAt`,
   the worker's `native_scheduled` branch and an extra `!= 'native_scheduled'` condition) without the writer: dead code
   (no manifest has `nativeScheduleAt`; `normalize_result` never yields that state). Behaviour equals live.
4. `7e48c1f3` (2026-10-11): LinkedIn re-verification at claim carried as `linkedin_reverify = False` without the code
   that sets it: dead code; behaviour equals live.
5. `4e69d899` (2026-10-08, LinkedIn accepted receipts): the web half of `publication-receipt.tsx` carried, the server
   half not. The status text "Accepted by LinkedIn. Publication is not API verified; confirm it on LinkedIn. Do not
   resubmit." shows for a LinkedIn post while it is `provider_accepted` (live writes that state at submit and the next
   worker step reconciles it, usually to `uncertain` without `r_member_social`): observable for about a minute per post,
   a correction to the inventory's UI-21. Not changed (SC-1 list below).
6. `6d6346f8` (founder unlimited entitlements): only TypeScript type fields carried; no runtime effect.
7. `7d803d40`, `afda8f51` (public connection review gate): `connection_review.py` carried, called only by the Discord
   connect path; its Facebook branch never runs. Inert.
8. `d4572f68` (merge of live into the Discord line): with base `7dc95e2e` the superset proof lists 29 live lines
   rewritten (4 per-branch `vercel.json` entries, 13 in `connect-sheet.tsx`, 7 in `connect-return.tsx`, 3 in
   `hosted_worker.py`, 2 in `oauth.py`). Each was read: the request-generation guard is applied to every provider under
   a new name, the transaction-bound different-account check is kept for every non-Discord provider, Discord is added
   to two provider tuples, the `native_scheduled` condition is inert (3), and `record_published` takes the completion's
   own clock reading instead of a second one in the same transaction. No live behaviour lost (*inference*; the impact
   agent's measured shared-path equality supports it).

Analysis scripts and outputs: scratch only (`halfcarry.py`, `origins.py`, `commit_lines.py`), not committed.

## Analyses (no code)

**WB-1 (worker budget).** `configured_worker_limits()` is byte-identical on live and here: `POSTRIFF_WORKER_MAX_JOBS`
(default 10, cap 25) and `POSTRIFF_WORKER_MAX_SECONDS` (default 20, cap 45) bound every minute tick for every provider.
25 and 40 were set project-wide on 2026-10-23 for Discord's bursts. With the W-02 lane on, the minute tick runs with
`exclude_discord=True`, so the budget serves only the other providers; with the lane off, Discord is gated to the
tester and its volume is negligible. Effect of keeping 25/40 on the other providers (*inference from the tick code*): up
to 2.5 times the steps a minute (a post takes about two: submit, then read-back about a minute later; so roughly 5 to
12 posts a minute in a burst), up to twice the function time a minute, and proportionally more provider and database
calls in bursts; per-provider daily limits are still checked at approval. Rollback: promoting `dpl_47SG` keeps the
10/20 it was built with; any rebuild (live or RC2) reads 25/40; the frozen worker reads the same names. Recommendation:
remove the two variables before the RC2 build (back to 10/20) so the minute worker treats every other provider exactly
as live and every rollback path has the same budget; if faster bursts for all providers are wanted, keep 25/40 as an
explicit all-provider decision. An intermediate value has no measurement behind it. This is a Production setting: only
with the owner's approval, and it reaches new deployments only.

**BG-1 (idle minute tick).** Accepted as LOW by the coordinator (2026-10-23): 4 connections and 11 statements a minute
when idle (live 1 and 3). A probe of `pr_discord_worker_projection` folded into the generic claim would bring it to
about 1 and 4, but changes the flag-off path that W-02's frozen-base test pins byte for byte.

**RC2-1 (W-02 shards).** An idle shard with the lane flag on opens 4 connections for 7 statements (projection check,
coordinator rows, a claim miss, the soonest-due read): about 69,000 connections a day before any Discord post. Proposal
sent to the coordinator and routed to the W-02 fix agent: keep the pure readiness check first (the WARNING signal for a
broken configuration stays), then one connection with one statement (the soonest-due read, an undefined table meaning
`schema`), and stop `idle` before the coordinator read and the claim when nothing is due within the idle horizon. The
lane claims only through `hint.next_at <= now`, so no claimable work is skipped. Idle cost: 1 connection, 1 statement.
Options (d) and (e) (crons only once the flag is on; fewer shards when idle) were rejected. The W-02 agent implemented
it in `820d8c7d` (merged here in `45352b92`); measured by the impact suite: an idle shard now opens 1 connection for 1
statement (its pin updated in this branch).

**SC-1 (non-Discord changes riding in the candidate).** For the owner; sizes are the lines a strip would touch.

| Item | Origin | Recommendation | Strip size |
|---|---|---|---|
| UI-13 composer keeps dictation and autofill input | `f54d103b` | ship (a fix) | 27 lines in two components and a test |
| UI-14 billing Storage line no longer crashes | `63864bd6` | ship (a crash fix) | 7 lines and a test |
| UI-15 workspace switcher accessible name | `09b3ab8a` | ship | 1 line |
| UI-16 history import "Requesting import…" | `171a73de` | ship (wording, 9 languages) | 11 lines |
| UI-3 connect tiles locked while a start is in flight | Discord connect-sheet rework | ship (prevents a double start); not separable from the Discord request-generation guard without touching the Discord flow | about 15 of the 197 changed lines in `connect-sheet.tsx` (estimate) |
| DEP-5 Pillow 13.0.0 | `21f3d961` (security, dependency audit) | ship (the impact suite renders 15 customer images identically) | 1 line, but reopens the audit finding |
| DEP-6 pypdf 6.21.1 | `0bce18dd` (four advisories) | ship | 1 line, reopens the advisories |
| DEP-7 psycopg-pool 3.3.3 | pool (inert while off) | ship | 1 line plus the pool module |
| API-1 `workerBinding: null` in workspace reads | `381ac2d0` machinery | ship (inert) | about 10 lines in `hosted.py` (estimate) and the dormant preview code it feeds |
| UI-12 / API-9 "Save as draft" (`manual_draft_create`) | `edcdf286`, `4fdc09c3` | owner decision: a new feature every editor sees | about 170 lines (`manual_drafts.py` 100, `hosted.py` about 8 (estimate), `permissions.py` 1, `home-view.tsx` 47, API types) plus `tests/test_manual_drafts.py` |
| API-8 review preparation without the publishing entitlement | `ea59babb` | owner decision (a workspace without a plan now meets the refusal at approval, not at review) | 1 line plus `tests/test_passive_review_billing.py` (152) |
| UI-10 schedule dialog native selects, UTC line, one-second clock, option text | `06f4f13c` (a Discord P0 fix) | owner decision; entangled with the Discord destination select and the P0 browser test | revert of about 80 lines in `schedule-dialog.tsx` and 24 in `discord-p0-browser.cjs`, then redo the Discord select |
| UI-8 Facebook/Business Profile picker wording | `381ac2d0` via `1791d6d1` | strip for exact parity (or accept) | 3 to 4 lines in `destination-picker.tsx` (the strings sit in ternaries shared with Discord) |
| UI-21 LinkedIn accepted-receipt text | web half of `4e69d899` | strip (its server half was never carried; the text claims a state live does not keep) | about 6 lines in `publication-receipt.tsx` (estimate) |

## Not changed, and why

- BG-1 (accepted LOW), RC2-1 (W-02 owner), WB-1 (a Production setting; owner), SC-1 items (owner's list), the dormant
  preview-dispatch machinery (inert in Production; removing it touches the worker claim code the Discord lane shares).
- `/api/cron/worker` runtime-before-authentication (reported only, as asked).
- The PR-1 scheme caveat with the feature on (unknown; verify on the staged build before turning user install on).
- `tests/phase2/postgres_discord_connections.py` was not run: it refuses to run outside the separately approved cloud
  harness (`CI=true` and the fence), and that guard was respected; the Discord-link Channels read is covered by
  `test_a_workspace_with_a_linked_discord_identity_still_lists_it` on PostgreSQL instead.
- Web typecheck, lint and the browser harnesses were not run: this checkout has no `node_modules` (the 34 web unit
  tests that need `typescript`, `react` or other packages fail identically on `150ab4fa` and here).
- The impact branch `claude/discord-impact-20261023 @9f1946cf` itself still has the literal credential values (another
  agent's branch); this branch carries the corrected copies of its tests.

## Test runs on `60ca222d`

All on a detached copy of `60ca222d` (scratch worktree), Python 3.13 venv with psycopg, PostgreSQL 16 binaries, no
network. Receipts are kept in the session scratchpad, not in the repository.

| Run | Command | Result |
|---|---|---|
| Offline source secret scan (local-gates step) | `PYTHONPATH=src:tests python scripts/consumer_ready_secrets.py` | status PASS: 3,384 files, 965 findings, every one matched by the repository's existing review rules (none added), 0 unexpected (before `438b5816`: 973 findings, 8 unexpected) |
| Fenced Discord suite, as the qualification workflow runs it | `CI=true PYTHONPATH=scripts/linkedin_test_fence:src:tests RAFII_DISCORD_SYNTHETIC_FENCE=1 python -m unittest discover -s tests -p 'test_discord*.py'` | 577 tests OK, 49 skipped (the real-PostgreSQL tests stand down under the fence); fence receipt: 0 unexpected transport attempts, 0 real provider requests |
| This branch's suites and the impact suites, real PostgreSQL | `POSTRIFF_PG_BIN=... python -m unittest test_rc2_shared_path_fixes test_rc2_shared_paths_postgres test_customer_impact_shared_paths test_impact_compare test_customer_impact_dependencies` | 63 tests OK, none skipped (24, 7, 19, 11 and 2 by module) |
| Web unit tests | `cd web && node --test tests/*.test.mjs tests/*.test.cjs src/lib/locales/core.test.mjs` (Node 22, no `node_modules`) | 752 tests, 718 pass, 34 fail; the 34 are the same set as on `150ab4fa` (they need `typescript`, `react` or other packages this checkout lacks); the 4 UI-1 tests and the 7 launch-gate tests pass |
| Full repository discover | `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'` (without `POSTRIFF_PG_BIN`, as the RC1 receipt's 6,141/391 count) | 6,308 tests OK, 455 skipped (529 s) |

Failing-before receipts (each test file copied onto a detached `150ab4fa`, or the live tree, and run there): FB-1, CH-1,
PR-1 and ENV-1 offline tests (`all-offline-base-150ab4fa*.log`, `env1-base-150ab4fa.log`), the PostgreSQL proof
(`pg-base-150ab4fa.log`, with the record summary `pg-summary.txt`), the impact guards with `IMPACT_RC_REV=150ab4fa`
(`impact-guards-on-150ab4fa.log`), the UI-1 web test (3 of 4 fail), the cron guard on `150ab4fa` and on the live tree
(`cron-guard-base-150ab4fa.log`; with the run-time cron values of `60ca222d`:
`cron-guard-runtime-credentials-base-and-live.log`, the same 2 of 3 tests and 7 failures), and the 404 tests on the 401
head `651e1899` (`pr1-404-on-651e1899.log`).
