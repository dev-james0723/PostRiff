# Sender names and the W-02 capacity harness

For the capacity agent. Branch `claude/discord-rc2-sendername-20261023`. Measured means a test on this branch asserts the
number (the test is named); inferred means reasoning from the code. Nothing here was run against Discord, only
against the repository's disposable PostgreSQL (16 locally, CI uses 17) and an in-process mock Discord.

## 1. What a sender name adds to a send

| | Extra Discord requests per post | Extra workspace transactions | Extra bytes |
| --- | --- | --- | --- |
| Webhook post with a custom name | **0** (measured) | **0** | one `username` string (at most 80 characters) in the execute body and in the job's manifest |
| Webhook post without a name | 0 | 0 | none (byte-identical to RC1) |
| Bot post with the nickname capability on | **0** (measured) | **0** | one `discordBotNickname` string (at most 32 characters) in the manifest |
| Bot post with the capability off | 0 | 0 | none |

* Webhook: `tests/test_discord_sender_name_postgres.py::LaneAndWorkerOnPostgres::test_a_name_adds_no_request_to_a_webhook_post`
  runs one named and one unnamed webhook tenant through the real worker on PostgreSQL and asserts the multiset of Discord
  requests is identical. The username rides in the body of the one create the post already makes.
* Bot: `tests/test_discord_sender_name_wire.py::BotNicknameInTheApproval::test_the_freeze_adds_no_discord_request_to_a_bot_post`
  asserts equal request counts with the capability on and off. The nickname is taken from the bot-member response the
  destination check already reads (`destinations()` reads `GET /guilds/{id}/members/{bot}` for its roles; the same payload carries
  `nick`), so nothing new is requested at dispatch.
  The same holds on the W-02 lane against PostgreSQL: `LaneAndWorkerOnPostgres::test_a_frozen_bot_nickname_adds_no_request_to_a_bot_post` compares the request multiset of a bot post
  with and without a frozen nickname. A bot post approved under a nickname that Discord no longer reports is held at dispatch before any create
  (`::test_a_bot_post_approved_under_one_nickname_is_held_when_the_server_nickname_changed`): one request fewer, never more.
* A frozen webhook name or bot nickname costs nothing at claim time: `job_authorized` and the digests only read the manifest.

### Request shape of one webhook post (measured, single thread, coordinator on, bot identity cache warm)

13 GET + 1 POST = 14 requests for a webhook post, named or not: `GET /oauth2/applications/@me` 1, `GET /users/@me` 1,
`GET /guilds/{id}` 2, `GET /guilds/{id}/members/{id}` 4, `GET /guilds/{id}/channels` 2, `GET /webhooks/{id}/{token}` 2,
`POST /webhooks/{id}/{token}?wait=true` 1, `GET /webhooks/{id}/{token}/messages/{id}` 1. The webhook destination check
(`webhooks.verify`) runs twice per post, once before the create and once in the read-back, which makes a webhook post
about twice a bot post (the ledger's figure for a bot post is 7). That is existing behaviour, independent of names; it matters
for sizing only if the webhook route opens (Wave 1 keeps `POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED` unset).

## 2. The settings routes (an edit is not a post)

Exact cost of one call, measured in `tests/test_discord_sender_name_routes.py::Fanout::test_exact_cost_of_each_route` (coordinator off, so the
bot identity is read uncached: 2 requests; with the coordinator on the 60-second identity cache makes it 0 or 2). "Transactions" are
workspace transactions with a bearer verification; in production each is one `getUser` HTTPS call and two database connections.

| Call | Discord requests | Workspace transactions |
| --- | --- | --- |
| `GET` webhook settings | 1 (`GET /webhooks/{id}/{token}`) | 2 |
| `POST` webhook name (save or reset) | 1 | 3 |
| `GET` bot nickname settings | 5 cold, 3 warm (server, authorizer's roles, bot member; identity x2 when cold) | 2 |
| `POST` bot nickname | 6 GET + 1 PATCH cold; 4 GET + 1 PATCH warm | 7 |
| Any refusal found without Discord (switch off, not the authorizer, bad name, stale form, throttle) | 0 | 1 |

Before this branch (upstream, measured by the independent reviewer on the same code paths): bot GET about 9 to 11 reads and 19 transactions,
bot POST 11 to 13 requests and 26 transactions, plus a state write and audit row on every GET. The reduction is: no per-read consent guard (one custody
transaction before and one after the reads), no `reverify_*` in the settings routes, the two bot-member reads folded into one.

Throttles (existing `pr_auth_throttle`, counted before any Discord request, 10-minute fixed window): per connection 12 reads and 6 writes,
per workspace 40 reads and 15 writes. Worst case for one bot connection in one window (cold identity): 12 reads x 5 requests = 60, plus 6 writes x 7 requests
(6 GET + 1 PATCH) = 42, so 102 requests per 600 seconds, about 0.17 requests per second. If all 90 connections that the Wave 1 plan allows did that at the
same moment, the total would be 90 x 102 = 9,180 requests per 600 seconds, about 15 per second on average. That sits inside the 50 per second application
ceiling but is not free, and the per-workspace limits (40 reads and 15 writes) cut it further for a workspace that owns several connections.
These calls compete for the same application window as posts (they are admitted by the shared coordinator like every other read). A capacity run that
models customers editing names should add this load explicitly rather than assume it is negligible. These figures are arithmetic from the measured per-call costs
and the throttle constants, not a measured load test.

## 3. What the harness must add for a 5,000-post run with sender names

The harness in `tests/discord_lane_fixture.py` builds bot installations only, and its cluster does not apply migration 131. Add:

1. **Schema**: apply `migrations/postriff/131_discord_interactions.sql` (and 098 for the authorization generation column) to the disposable
   cluster. Without 131 the coordinator's CHECK constraint refuses every webhook admission (`credential_kind` must allow `'webhook'`) and
   the lane reports the posts as `rate_delayed` releases forever. This is how it showed up here: 20 of 20 webhook jobs stayed `scheduled`.
2. **Flags** (read at request time): `POSTRIFF_DISCORD_SENDER_NAMES_ENABLED=true` (unset is OFF in every environment), for nickname runs
   `POSTRIFF_DISCORD_BOT_NICKNAME_ENABLED=true`; on the provider object `webhook_v1_enabled = True` besides the usual v2 and rate flags.
3. **Mock Discord**, following `WebhookDiscord` in `tests/test_discord_sender_name_postgres.py`:
   * `POST /webhooks/{id}/{token}?wait=true` (strip the query string before routing) answers a message with `id`, `channel_id`, `webhook_id`,
     `author: {id: <webhook id>, bot: true, username: <body.username, else the webhook's own name>}`, `content`, `mentions: []`,
     `mention_roles: []`, `mention_everyone: false`, `attachments: []`, `embeds: []`; record the body whole; give it a bucket (5 per 5 seconds per webhook
     like the bot create is a fair model) with the usual `x-ratelimit-*` headers;
   * `GET /webhooks/{id}/{token}` -> `{id, application_id, guild_id, channel_id, type: 1, name}`; `GET /webhooks/{id}/{token}/messages/{id}`;
   * for nickname runs, return `nick` in `GET /guilds/{id}/members/{bot}` and let a test change it mid-run.
4. **Tenants**: webhook tenants with their own server, channel, webhook id and credential (generate the credential at run time, never a literal),
   and a grant whose session has `kind: 'webhook'` (see `Tenant.grant()` in `tests/discord_sender_name_fixture.py`). Approve with the real review and approval
   commands so the name is frozen the way production freezes it. Mix: named (every tenant a distinct name, none a substring of another, none a reserved word),
   unnamed, bot with and without a frozen nickname.
5. **Assertions** (the tests above show each):
   * exactly one execute per approved post, counted by webhook id; the body's keys are `{content, allowed_mentions, flags}` plus `username` exactly when that tenant has a name;
   * `username` equals the tenant's own name; the created message's `author.username` equals it; no other tenant's name occurs anywhere in a request;
   * every job ends `verified`; no 429 attributable to the name; the request shape per post equals the unnamed one;
   * switch off mid-run: named jobs end `held` with no execute and no sealed intent, unnamed and bot jobs are unaffected, and switching back on does not resend a held job;
   * bot nickname changed mid-run (capability on, nickname frozen): the affected jobs end `held` with event text naming the nickname, nothing posted.
6. **Scale**: a name adds no per-post cost, so the 5,000-post throughput and the 7-per-post (bot) / 14-per-post (webhook) request budgets are unchanged by it; do not scale the settings-route load
   with the post count, scale it with the number of connections (section 2).

## 4. Facts about the lane that the sender-name tests rely on

* A worker without the fenced lease protocol cannot dispatch Discord on a database with migration 128 (`CheckViolation: Discord requires the current fenced worker protocol`), so the
  "legacy path" that exists on a migrated database is `PostgresWorker.step()` with `discord_workers=True` (the minute cron with the lane off). The tests run both that and the lane
  (`test_the_minute_tick_worker_path_with_the_lane_off_sends_the_same_exact_names`, `test_the_lane_sends_named_unnamed_and_bot_posts_each_under_exactly_its_own_name`).
* Measured on this machine under load 20 to 30 with 4 cores: the 28-post mixed lane test takes 45 s; the 70-post three-way test about 60 s.
