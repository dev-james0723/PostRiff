# W-02 Discord lane: request budget per post

Status: analysis for an independent reviewer. **Nothing here is implemented.** Each candidate below says what the
check it touches defends against, whether a cheaper form still defends against it, and what it would do to the
requests per post and to the section 4 lateness. Some candidates keep the permission witness and the grant check
exactly as they are; this document marks those as equivalent. Others would change what a check guarantees; this
document marks those as **not equivalent** and leaves them to the reviewer. The application ceiling stays at the
reviewed 25 requests per second. No candidate raises it.

Code references are to the W-02 tree `62f68c56d5d04cd90d2b0668501226408a5d4a73`. Its `src/` is identical to the
current head `d80d6eaf678591b3818f384f6d9c9ed92c6dc474`. "Measured" means a capacity receipt says so. "Inference" marks
a model or an argument.

## 1. The arithmetic that binds

Section 4 asks for 5,000 posts due in the same minute with lateness P50 ≤ 12 min, P95 ≤ 25 and max ≤ 40. Every post
needs its own requests, and the application may send at most C requests per second. With r requests per post
(overheads included), the k-th post is sent about k·r/C seconds after the burst starts. So:

- P50 ≈ 2,500·r/C, P95 ≈ 4,750·r/C, max ≈ 5,000·r/C (seconds), plus the first-create delay, measured at about 0.1 min.
- At C = 25: P50 ≤ 12 min needs r ≤ **7.14**. P95 ≤ 25 needs r ≤ 7.86. The max ≤ 40 needs r ≤ 11.97. **P50 binds.**
  This matches the coordinator's figure of 7.2. At r = 7 the P50 is 11.7 min (no margin). At r = 9.3 it is 15.5 min
  (fail).

**The effective ceiling is below 25 (inference from the code, to be confirmed by the GitHub-hosted S1 receipt).**
The application row of the coordinator is a window of 1 s that restarts at the first request after the last one
expired (`rate_limits.py` `_roll`, lines 547-557). At each restart it allows `cap − pending` new admissions, and
`_pending` (lines 504-512) counts every admission that is still `sent` (in flight, not yet observed) or `uncertain`,
plus unexpired `reserved` or `sealed` permits. A request in flight across a window restart is therefore charged in
two windows. By Little's law the sustained admission rate is about C/(1 + d), where d is the mean time from admission
to observation (the Discord answer plus the observe transaction):

- d = 0.1 s gives 22.7 requests/s;
- d = 0.2 s gives **20.8 requests/s**, which needs r ≤ 5.95 for P50 ≤ 12;
- d = 0.3 s gives 19.2 requests/s.

This is conservative, not unsafe. It does not stop a trailing second above 25 either: up to 27 were seen in the
coordinator's own table. A separate agent is making the ceiling exact (sliding). That change decides how in-flight
requests are charged, so it decides whether 25 or about 21 is the real budget. Section 5 gives both columns.

## 2. The ledger: every Discord request of one post on the real path

One post takes two claims of its workspace: the claim that sends it, and a later claim that reads it back. The read-back
is due 5 s after the create (`hosted_worker.py:871`) but waits for its workspace's turn (section 4.2).

| # | Request | Credential | Where | What it proves |
|---|---|---|---|---|
| 1 | `GET /oauth2/@me` | the person's bearer | `OAuthService.discord_grant_for_worker` (`oauth.py:1131`) → `DiscordConnections.installation_identity` (`discord/oauth.py:532`) → `_fresh_identity` fast path (`:403-424`) → `verified_authorization` (`:135-150`) | the person still authorizes Rafii (token not revoked), it is the same Discord user, the same application, with the required scopes. The code says: "Local expiry is not proof that Discord still authorizes this user." |
| 2 | `GET /guilds/{g}` | bot | `authorize_destination` → `destinations` (`social_connectors.py:661-699`, line 670) | the server, its owner and its roles' permissions |
| 3 | `GET /guilds/{g}/members/{bot}` | bot | `_member_roles` (`:612-613`), line 675 | the bot is still a member, and its roles |
| 4 | `GET /guilds/{g}/members/{person}` | bot | line 679 | the person is still a member, their roles; the person must have MANAGE_GUILD (line 682) |
| 5 | `GET /guilds/{g}/channels` | bot | line 684 | the target channel exists, is text or announcement, and its permission overwrites. Together with 2-4: the bot has VIEW, SEND and READ_HISTORY, and the person has VIEW and SEND, in that channel at send time (lines 686-693, 718-723) |
| 6 | `POST /channels/{c}/messages` | bot, with a publish permit bound to the sealed intent | `_submit_discord` (`hosted_social.py:429-505`) | the create; the answer must carry the channel, the exact content and the bot as author (lines 479-494), else `uncertain` |
| 7 | `GET /channels/{c}/messages/{m}` | bot | `reconcile_discord` (`hosted_social.py:517-575`, line 558) | read-back by id: same id, channel, author (and `bot: true`), exact content, no `@everyone`, no user or role mentions, reply reference (lines 563-569) → `verified` |

Requests 1-5 are the preflight (`prepare_discord_dispatch`, `hosted_social.py:362-391`). They run outside SQL locks,
**before** the create is admitted. Per process, not per post:

| Request | Credential | Where | Cost |
|---|---|---|---|
| `GET /oauth2/applications/@me` and `GET /users/@me` | bot | `_bot_identity` (`social_connectors.py:638-660`), cached 60 s per process | each lane invocation is a fresh process of at most 50 s, so each makes the pair once: 12 shards × 2 = 24 requests a minute (F429 measured 156 pairs, about 12 a minute), about 0.11 per post at 3.5 posts/s |

The step order is in `hosted_worker.py:1196-1232`: claim → preflight (1-5) → renew lease → **reserve the create**
(`reserve_discord_send`, `hosted_social.py:393-415`) → seal the intent → renew lease → create. The step releases the
job unsent (`discord/worker.py:100-130`, `nextAt = now + cooldown`) in three cases:

- the create's admission is denied (`RateDelayed`);
- a preflight read is denied for more than 1 s (`social_connectors.py:415-444`);
- the create permit expires before the seal or before the consume. A permit lives at most until the end of the current
  application window. In S1 this was the only cause (section 4.1).

The **next claim runs the whole preflight again.**

**Measured:**

| Source | Requests per verified post | Breakdown |
|---|---|---|
| GitHub-hosted smoke, run 39904592955 (tree 62f68c56, harness 920991d6, 30 posts; as reported by the coordinator) | 10.3 | members 3.0, `/oauth2/@me` 1.5, guild 1.5, channels 1.5, create 1.0, read-back 1.0, bot identity 0.4 + 0.4 |
| Sandbox smoke runs, tree 62f68c56 (30 posts each) | 10.5 and 10.8 | the same shape: preflight 1.53 and 1.6 passes per post |
| Sandbox F429, tree 62f68c56 (1,000 one-post workspaces, injected 429s, machine load 8 to 14: **not throughput evidence**) | 12.5 per verified, 10.2 per sent | preflight passes per sent post: one pass 621, two passes 229, three passes 37 (mean 1.34) |

So today the preflight runs 1.34 to 1.6 times per post, and that repetition is the largest overhead. The S1, S2 and
S0 receipts on the GitHub-hosted runner (harness 22e3257e) will give the same ledger at scale. Every receipt now has a
request-ledger table that separates the essential path from the overhead.

**Ideal minimum with every check per post, at send time: 7 requests** (6 in the send claim, 1 in the read-back
claim), plus about 0.11 for the bot identity. Section 5 rounds this to 7.12. Getting below 7 needs one of two things: a check covers more than one
post (sections 4.5 and 4.6, not equivalent), or the read-back is dropped (section 4.4).

## 3. Grant custody in the measurement

The capacity harness runs the application's real grant path against the mock Discord: OAuthService →
DiscordConnections.installation_identity → `GET /oauth2/@me` with the person's bearer. It does not use the lane
fixture's `Grants` stub (`tests/discord_lane_fixture.py`), which hides request 1. Every receipt states the measured
count: for example "1430 identity checks answered for 887 sent posts (real path)". Below one check per sent post, the
receipt would say so.

## 4. Candidates

### 4.1 One preflight per sent post: keep the create permit alive until it is used (first; corrected)

**Correction (after the independent review, `scratchpad/review-budget/NOTES.md`, addendum A.1 and A.4).** The first
version of this section said a step was released because its create's admission was **refused**, and proposed a post
gate (A1') or a bundle (A1). The S1 receipt shows the mechanism is different. The reviewer derived it, and I have
checked it against the same files:

- **No reservation was refused in S1.** The coordinator's table has 39,902 admissions against 39,249 requests at the
  mock. The 653 extra are the create permits of the 653 wasted passes: 114 ended `reserved` (lane counter
  `rateDelayed` 114) and 539 ended `blocked`. 39,902 = 5,653 passes × 6 + 5,000 read-backs + 984 identity requests,
  exactly.
- **Every wasted pass ran all five preflight reads** and then lost its create permit to **expiry**. A permit expires at
  the end of the current application window (`_reserve`, `rate_limits.py:631-633`: the expiry is the minimum of the
  permit time-to-live, every capped row's reset, and the lease), so it lives at most about 1 s.
  - 17% of the waste died before the seal: the seal found the permit expired, and the post was released unsent.
  - 83% died between the seal and the consume: `abandon_expired_publish` marked them `blocked`, and the post was
    released unsent.
- So a post gate does nothing, because there are no refused reservations to avoid. A bundle reserved before the
  preflight (p50 1.94 s) would expire almost every time, which is worse.

**What the preflight defends against** is unchanged: sending when the grant was revoked, the bot or the person lost
access, the channel is gone, or the person is no longer a server manager. It must hold **at send time**.

**Candidates that address the measured mechanism (the reviewer's F1, F5 and F2; all three equivalent):**

- **F1. Permit lifetime independent of the window end.** For the application scope, a create permit lives
  min(permit TTL, lease or approval deadline) instead of until the end of the current window. **Equivalent:**
  - it is accounting only;
  - the live guard at consume still re-checks the lease, the approval, the grant and the destination;
  - an unexpired reserved or sealed permit is still counted as pending at the next window restart, so a late consume
    cannot exceed the cap.
  - The reviewer prefers 2-3 s. A 1 s window-length lifetime would still lose 1-3% (inference).
- **F5. Drop the second lease renewal before the POST** (`hosted_worker.py:1274`). The seal has just extended the lease
  to 45 s, and consume's live guard repeats every check of the renewal later, with the lock held. The extra
  whole-document transaction adds no authorization. **Equivalent.** It removes one read-modify-write of the workspace
  document per post, and it shortens the seal-to-consume interval in which 83% of the permits died. For a 15 MB
  workspace document (section 7.6) that interval is seconds.
- **F2. Keep the queue position on a system-caused release.** This is 4.1b below.

**Effect (the reviewer's calibrated model, S1 layout, today's rate):** removing the waste is worth P50 −2.0 min, P95
−6.2 and max −8.2. The median part is the 653 repeated passes (3,918 admissions, 9.8% of all); the tail part is the
requeue. **A2** (reuse the evidence on a re-claim) is not useful today: the re-claim comes a median 729 s later, so a
10 s freshness window never applies.

### 4.1b A released-unsent job keeps its place (the reviewer's F2; no request saved; the tail)

**What happens today.**

- A claim stamps `lastDispatchedAt = now` on the job (`hosted_worker.py:688`) and moves the workspace cursor
  (`:722-723`), both before the preflight.
- When the step is then released unsent, both stamps stay. In S1 the cause was a permit that expired (4.1).
- Inside a workspace, jobs are taken by `lastDispatchedAt` ascending (`:552`; nothing else in `src/` reads the field),
  and workspaces are taken by their cursor. So the released post sorts behind its workspace's never-claimed posts, and
  the workspace has used its turn.

Measured on S1 (section 7.2): the 1,304 posts of the 503 workspaces with a release had a median lateness of 26.6 min,
p95 39.8 and max 40.7, against 15.3 / 30.6 / 32.6 for the others. Every post later than 32.6 min was among them.

**Candidate (with the reviewer's scoping).** On a release whose cause is system-wide (`rate_scope_kind` application or
permit), restore both the job's `lastDispatchedAt` and the workspace cursor, and make the retry eligible at once. Keep
today's penalty in three cases:
- releases caused by one tenant's own resource: a learned or unknown route or channel window, or an embargo scoped to
  one server;
- `preflight_transient`;
- any job after a per-job cap of 3 restorations.

**Restoring only the job's stamp does almost nothing** (model: max 40.4 instead of 40.5). The workspace's next claim
then takes a due read-back and uses up the turn.

**Fairness argument (from the review, which I agree with):**

1. The round robin (`hosted_worker.py:471-473`) bounds each tenant's completed work per round. A claim released
   unsent completed no work. Counting it as the tenant's turn charges the tenant for a system event.
2. Today 25% of the S1 tenants (503 of 2,000), chosen at random by permit timing, saw their median lateness doubled.
   That is itself unfair.
3. A restored turn cannot let a tenant exceed its share. It still gets at most one successful create claim per
   round, and the extra claim retries the same job. That retry is bounded by `ratePermitRetries` (at most 8, then
   held), `rateReadRetries` and the cooldown.
4. Only ordering metadata changes. **Equivalent**, with no request saved.

**Effect (the reviewer's model, today's rate):** P95 36.7 → 34.5 and max 40.5 → 36.5, with P50 unchanged. It
recovers about two thirds of the requeue tail. With F1 and F5 most releases disappear; F2 keeps the remaining ones from
costing rounds.

### 4.2 Claim order: the read-back waits for a full pass over the backlog (customer-visible)

**Fact.** The Discord claim (`hosted_worker.py:57-60`) orders by `hint.last_claimed_at, w.id`: a round robin over
workspaces. After its create, a workspace has just been claimed, so its read-back (due 5 s later) waits behind every
workspace not yet served in this pass.

Measured in the sandbox F429 run (1,000 one-post workspaces):

- 478 creates and 0 read-backs at T+6 min;
- create to verified read-back: median 5.9 min, max 7.6 min;
- 276 of 1,000 posts were sent but not confirmed when the last create happened.

In S1 at 5,000 posts, a post sent in the first minute would show as not yet confirmed for most of the burst
(inference).

**What the order defends.** Fairness between tenants: a small tenant is not starved by a large one (the S2 measure).
The order of creates is the fairness property. The read-back is the second half of a post already sent.

**Candidate.** Claim a workspace whose read-back is due ahead of workspaces that only have new creates, with fairness
between tenants kept for the creates. For example, order by (a verification is due, `last_claimed_at`), or serve due
verifications from their own small share. **No extra request:** every read-back is made either way.

**But the lateness moves.** Today the burst's creates run first, at about r − 1 requests per post, and the read-backs
come after. Serving read-backs as they fall due spends their requests during the burst, so creates go at r requests
per post. The P50 lateness rises by about r/(r − 1): at r = 7.12 and 25 requests/s, from 10.3 to 12.0 min. So the
section 4 lateness gets **worse** while time-to-verified becomes about lateness + 5 s.

A middle form keeps both inside bounds: give due read-backs at most one request in eight, or serve a read-back first
only once it has waited more than X minutes. The receipts now show both sides: time to verified next to lateness, and
the posts unverified at the last create. That trade-off is for the reviewer, with section 5's numbers.

### 4.3 Discovery admissions on routes without a server: a product-level fact

**Fact (code).** The coordinator learns a route's Discord bucket per (credential identity, route, major parameter)
(`_map`, `rate_limits.py:357-373`). Until that row has a bucket, every request on it also needs a discovery admission
shared by that identity and major: one per `unknown_window_seconds`, which is 1 s (`_keys`, lines 375-390). The
provider waits at most 1 s for a read admission and then raises `ReadAdmissionDelayed` (no request was sent).

The bot's own routes, `GET /users/@me` and `GET /oauth2/applications/@me`, have no major. Every process shares them.
Several fresh processes asking at the same moment meet a 1-per-second admission. That killed a seeding process on the
GitHub-hosted runner (reproduced here). For the lane it means a delayed step, not a failure: the step is released
unsent with a short cooldown (`discord/worker.py:100-130`).

**Does the production steady state meet it again after the routes are learned? No.** Facts from the code:

- the route-to-bucket row is only ever set (`rate_limits.py:904-905`). No code path clears it, and nothing prunes
  `pr_discord_route_buckets`; only the test fixture truncates it;
- the bot's identity key is `digest('bot:' + application id)`, not the token (`RequestIdentity.make`, lines 265-273).
  A bot token rotation keeps every learned route;
- a new reviewed policy revision re-caps only the policy, invalid and discovery scope rows (`_roll`, lines 537-546).
  It does not clear the learned routes, so a cold start of the 12 shards on a new policy revision does not meet
  discovery on routes already learned.

It does meet discovery in these cases:

- **once per new (route, major)**: each new server's first preflight read, and each new channel's first create and
  first read-back. These are per server or per channel, so there is no contention across tenants;
- on the bot's own routes only when the table is empty: the first deployment, a database restored to before the first
  learning, or a new application id;
- the person's `GET /oauth2/@me` is keyed by the Discord user id when it is known, so it is learned once per person.

Not exercised by the harness (inference): the mock answers the bot identity routes with a bucket of 1,000 per second.
Real Discord's bucket for them is unknown. If it is small, the 12 cold shard processes at each minute boundary could be
delayed on a learned route as well. That is a minute-boundary latency, not a discovery problem, and section 4.8
removes it.

### 4.4 No read-back when the create's answer proves the message (request 7)

**What the read-back defends against.**

1. The create answer is accepted with fewer checks than the read-back. The create check (`hosted_social.py:490-494`)
   compares channel, content and author id. The read-back (lines 563-569) also requires `author.bot`,
   `mention_everyone == false`, `mentions == []` and `mention_roles == []`.
2. It shows that the message still exists at least 5 s after the create.
3. `verified` means "found by id" in the product. That is a promise to the customer.

**Cheaper form.** Apply the read-back's full field checks to the create answer. Discord's create answer is the stored
message object, the same serialization a GET returns, over the same authenticated connection. Then mark the post
verified from the create receipt.

**Equivalent for (1)** once the create check takes all of the read-back's fields. **Not equivalent for (2) and (3).**
It no longer shows that the message survived its first seconds, for example deleted by a moderator or a moderation
bot. AutoMod blocks happen at create, as a 4xx, so they are already covered. If the product's "verified" must mean
"seen after the fact", this is not equivalent and stays a reviewer decision.

**Effect:** −1 request per post (7.1 → 6.1). Predicted with A: 10.3 / 19.5 / 20.5 min at 25 requests/s, and
12.3 / 23.4 / 24.6 at 20.8 (P50 just over).

### 4.5 The grant check once per workspace per claim (request 1)

**What it defends against.** The person revoked Rafii in Discord, the token was invalidated, the identity changed, or
scopes were reduced, between approval and send.

**Cheaper form.** If one claim sends several due posts of the same workspace (today a claim sends one), check once per
claim, with the claim's lease (seconds) as the bound. That is equivalent to "at send time" within the claim's duration.
**Not equivalent in the strict sense:** the second post's check is up to one lease older.

It needs batched claims, and a batch must be capped (for example 3 posts per claim) to keep the S2 fairness. The
saving is (k − 1)/k of a request per post: 0.6 at the S1 layout of 2.5 posts per workspace. A one-post workspace saves
nothing.

**Effect** with A: 6.5 per post → 11.0 / 20.7 / 21.8 min at 25 requests/s.

### 4.6 Server-level reads once per server with a short TTL (requests 2, 3, 5; request 4 is per person)

**What they defend against.** The server's roles, the bot's membership or roles, and the target channel's overwrites
changed since the last post: a permission removed, a channel deleted, the bot kicked.

**Cheaper form.** Cache them per server for a TTL (for example 30 s), or once per claim of several posts as in 4.5.
**Not equivalent:** the witness becomes "within TTL of send time". For the bot side Discord itself refuses a create
without permission, with a 403. But 403s count toward Discord's invalid-request limit (10,000 per 10 minutes, then a
Cloudflare ban of the egress IP), so the preflight also keeps invalid requests away. The person's side (request 4)
must stay per post or per claim.

**Effect.** It depends on posts per server per TTL. In S1 a workspace's posts are claimed one per pass, minutes apart,
so a 30 s TTL almost never hits. In S2's hot server (3,000 posts) every post after the first would skip 3 reads, but
that tenant is capped anyway by Discord's 5 creates per 5 s per channel.

**Per claim** together with 4.5 (2.5 posts per claim): 4.1 per post → 7.0 / 13.1 / 13.8 min. This changes what the
witness guarantees, so it needs the reviewer.

### 4.7 Collapse the four permission reads (requests 2-5) into fewer

**No equivalent collapse exists.** The witness needs:

- the server's role permissions and owner (2);
- the bot's roles (3);
- the person's roles (4);
- the channel's overwrites (5).

Discord's bot API has no endpoint that returns a member's effective channel permissions. Interactions carry them, but
the lane does not run in an interaction. `GET /channels/{c}` could replace the channel list (5) with the single channel
(a smaller answer), but it is still one request. Dropping 3 turns a lost bot permission into a 403 create (an invalid
request), which is not equivalent (4.6). The 4 reads are the minimum for an exact per-send witness of both the bot and
the person.

### 4.8 The bot identity pair once per minute for all processes (per process today)

**What it defends against.** The bot token in use belongs to the reviewed application and to a bot user, not to a
swapped token. Today each process caches the pair for 60 s.

**Cheaper form.** Keep the result in the database for 60 s, keyed by (application id, token digest). Each process reads
it in its first transaction and asks Discord only when it is older than 60 s. **Equivalent:** the bound stays "at most
60 s old", and the token digest in the key still catches a swapped token.

**Effect:** about −0.11 per post at scale, and it removes the minute-boundary burst of 24 requests on two routes
(section 4.3). Predicted with A: 11.8 / 22.3 / 23.5 min.

### 4.9 Charge an in-flight request in one window only (accounting, not requests)

Described in section 1. **Equivalent** for "at most 25 admissions per window": a request admitted in window k counts in
window k. Whether it also protects a trailing second, the separate sliding-window work must settle. **Effect:** the
usable budget goes from about 25/(1 + d) back to 25. At d = 0.2 s that is 20.8 → 25, worth as much as 1.2 requests per
post at r = 7. **Not a request reduction**, and nothing here proposes raising 25.

### 4.10 Charge the person's bearer call to a budget of its own (built: the owner's D-2 option 1, limiter head 0658c58b)

**What it defends against.** Nothing: it changes no check. Request 1 (`GET /oauth2/@me`, section 4.5) still runs for every post
at send time with the person's own bearer, and nothing about what it proves changes. Only the window it is charged to does.

**The change.** The written budget was 25 requests a second across every credential. The owner redefined it (reply 16,
AUTHORIZATION-RECORD.md): bot-token requests at most 25 a second, the person's bearer calls budgeted separately. Request 1 is
the only bearer call of an ordinary post (a token refresh, about weekly per identity, adds two; the interactive flows and the
dark reply and webhook paths make others; OPEN-QUESTIONS Q21 lists every call site). It is now charged to a second exact sliding
window of its own, 10 a second in the reviewed policy (the lane needs 4.0 a second of them at the bot's full rate), with the same
guard, booking and proof as the application window. The other six requests of the post (requests 2 to 7) stay on the bot's 25.
`SafetyPolicy` carries `bearer_capacity` and `bearer_window_seconds`, both or neither; a policy without them is what it was and
is the way back. The policy tool refuses a bearer budget above 10 a second.

**Equivalent or not.** Equivalent for every check. The bot's 25 a second, its exactness and its guard are untouched; the new
ceiling is on the calls Discord's global limit for the bot does not count. It does redefine the written "all credentials" budget,
which is why it needed the owner.

**Effect.** 6 charged requests per post instead of 7. With the section 1 formula, P50 = 2,500·r/C: at C = 25 that is 10.0 minutes
instead of 11.7; at the exact ceiling of 23.8 a second (guard 0.05) 10.5 instead of 12.3 (the ideal minimum of section 2 becomes 6
bot requests plus 1 bearer). In the limiter's model of the lane (12 shards, claim 0.8 s, five seeds) booking with guard 0.05 and one
budget gives 179.0 posts a minute and booking with the bearer budget 195.1, 7.04 requests a post, 0 releases; on the S1 shape that
is about 172 posts a minute, a median of 14.5 minutes, p95 27.6, longest about 32 (OPEN-QUESTIONS Q21; a model, to be measured). The
gain is the grant check no longer waiting for a bookable slot of the bot's window.

## 5. Predicted lateness for 5,000 posts due at once

Model (inference): the policy binds throughout the burst, so the lane sustains the budget, which the GitHub-hosted S1
must confirm. Read-backs are interleaved, which is conservative; deferring them, as today's claim order does in a
first pass, lowers each figure by 1.7 / 3.2 / 3.3 min at 25 requests/s and by 2.0 / 3.8 / 4.0 min at 20.8. The first
create is at T + 0.1 min, and every post is sent once.

| Case | requests/post | P50 / P95 / max at 25 requests/s (min) | at 25/(1+0.2) = 20.8 requests/s (min) | posts/s at 25 |
|---|---|---|---|---|
| today, small-scale ledger (GitHub smoke 10.3/post, identity pair 0.8) | 10.30 | 17.3 / 32.7 / 34.4 | 20.7 / 39.2 / 41.3 | 2.43 |
| today at scale, 1.5 preflight passes per post (smoke share) | 9.62 | 16.1 / 30.6 / 32.2 | 19.3 / 36.7 / 38.6 | 2.60 |
| today at scale, 1.34 passes per post (sandbox F429 share) | 8.82 | 14.8 / 28.0 / 29.5 | 17.7 / 33.6 / 35.4 | 2.83 |
| **A** (4.1): one preflight per sent post | 7.12 | 12.0 / 22.6 / 23.8 | 14.3 / 27.2 / 28.6 | 3.51 |
| A + 4.8 (bot identity shared) | 7.01 | 11.8 / 22.3 / 23.5 | 14.1 / 26.7 / 28.1 | 3.57 |
| A + 4.4 (no read-back) | 6.12 | 10.3 / 19.5 / 20.5 | 12.3 / 23.4 / 24.6 | 4.08 |
| A + 4.5 (grant check per claim of 2.5 posts) | 6.52 | 11.0 / 20.7 / 21.8 | 13.1 / 24.9 / 26.2 | 3.83 |
| A + 4.4 + 4.5 | 5.52 | 9.3 / 17.6 / 18.5 | 11.1 / 21.1 / 22.2 | 4.53 |
| A + 4.5 + 4.6 (grant check and witness per claim of 2.5 posts) | 4.12 | 7.0 / 13.1 / 13.8 | 8.3 / 15.8 / 16.6 | 6.07 |
| A + 4.4 + 4.5 + 4.6 | 3.12 | 5.3 / 10.0 / 10.5 | 6.3 / 12.0 / 12.6 | 8.01 |

Section 4 limits: P50 ≤ 12, P95 ≤ 25, max ≤ 40.

**Reading the table (inference):**

- Only the equivalent changes (A with 4.8) reach P50 ≤ 12, with no margin, and only if the full 25 requests/s is
  usable (4.9, or the sliding-window work charging in-flight requests once).
- At the effective 20.8 requests/s, every combination that keeps all checks per post at send time misses P50.
- Margin under that budget needs at least one non-equivalent change: 4.4, or 4.5 with batched claims.
- The choice between them is the reviewer's. Nothing here proposes raising 25.

## 6. What the measured runs must confirm

- **Requests per post at scale**, from the S1/S2/S0 receipts' ledger: how often the preflight repeats under the policy
  limit, rather than under machine load as in the sandbox.
- **Achieved requests per second while the policy binds**, and the admission-to-observation time d. Both are visible
  in the receipts' mock log and the coordinator's admission table. They decide which column of section 5 applies.
- **Whether the lane's 12 loops can sustain 25 requests/s at all** (the lock benchmark, profile `lockbench`). If the
  loops or the coordinator lock top out below the budget, every row above moves right.

## 7. Measured on the GitHub-hosted runner (requests 1023b)

Tree `d80d6eaf` (the same `src/` as 62f68c56), harness 22e3257e, standard ubuntu-24.04 runner (4 vCPU), PostgreSQL 17
behind PgBouncer (pool 20) with 2 ms per round trip, the fixed-window coordinator. Figures are from the artifacts,
re-analysed with this branch's analysis (`analyze` on the downloaded run directory). They are facts unless marked.

### 7.1 S1: 5,000 posts due at T in 2,000 workspaces (1,000 with 2 posts, 1,000 with 3)

**Against the standard:**

- Lateness median 17.19 min, p95 36.79 and max 40.73: all three **FAIL**.
- 0 duplicates, 0 creates after expiry, 0 misroutes, 0 429s.
- Policy ceiling **FAIL**: 856 requests had more than 25 others in their trailing second. The peak was 29 at the
  mock; the coordinator's own table shows 29 in a trailing second and **28 in one calendar second**. So a calendar
  second is not bounded by 25 either; the sandbox F429 run had shown at most 25.
- All 5,000 verified. Pool demand 0.60 of 20. 0 statement timeouts.

**Requests:**

- 7.850 per verified post: essential 7.000; repeated preflight 0.653 (653 passes without a create, in 503 workspaces);
  bot identity pair 0.197.
- Only the plateau decides the median. From T to the first read-back at T+24.6 min, the mock processed 24,215
  requests for 3,588 creates: **6.749 requests per created post**. Read-backs are served after the creates.

**Pacing (verified against the coordinator's decomposition):**

- In the plateau, the lane sends from second 6 to second 51 of each minute. Seconds 0-3 average 0 requests, seconds
  4-5 average 0.8 and 4.0, and seconds 52-59 together average under 6. **Duty cycle 78%** (1,898 of 2,436 seconds of
  the busy period had at least 5 requests).
- The cause is in the code and the configuration. Each shard's loop has a budget of 50 s (`DEFAULT_SECONDS`,
  `lane.py`). Each invocation builds its runtime inside the request (cold), and its first Discord request comes about
  5 s after the cron time.
- **Active-window rate:** seconds 7-51 averaged 21.2 requests/s, 85% of 25. Over every second with at least 5 requests
  of the plateau it was 20.9/s, 84%.
- **Plateau average:** 16.4 requests/s.
- These three numbers reproduce the median. 8 s + 2,500 × 6.749 / (0.78 × 20.9) = **17.35 min** (inference) against
  17.19 measured.
- So at 6.75 requests per created post, P50 ≤ 12 min needs duty cycle × packing ≥ 0.95. Neither lever alone is
  enough, and the request count matters as much.

### 7.2 The tail of S1 (minutes 33 to 40): who used the requests

| Minutes after T | Creates/min | Read-backs/min | Grant checks/min | Witness reads/min | Requests/s |
|---|---|---|---|---|---|
| 0-23 | 132-152 | 0 | 159-166 | 636-664 | 15.9-16.7 |
| 24-32 | 101-124 | 35-221 | 115-152 | 460-608 | 15.3-15.8 |
| 33-40 | 44-67 | 356-553 | 51-78 | 204-312 | 12.9-16.1 |

**Read-backs take most of the tail.** 8 to 9 of the 14.7 requests per second go to read-backs, each step making one
Discord request. The request rate itself drops, probably because a read-back step spends most of its time in
database transactions (claim, lease, reconcile, record) rather than in Discord (inference).

**The creates of the tail are posts pushed back by a release.** Created in minutes 33-40 are first and second posts
(p0, p1) of their workspaces, 30 to 40 minutes late. The trace of workspace 257:

1. At T+75 s its first post's preflight ran, and no create followed: released.
2. At T+811 s its second post was created.
3. At T+1,527 s its third post was created.
4. Only at T+1,986 s was the released first post created (33 min late).
5. The three read-backs followed at T+2,183, 2,304 and 2,411 s.

The mechanism, from the code:

- a claim stamps `lastDispatchedAt = now` on the job it takes (`hosted_worker.py:688`), including a job that is then
  released unsent;
- inside a workspace, jobs are taken by `lastDispatchedAt` ascending (`hosted_worker.py:552`), so a released post sorts
  behind every post of its workspace that was never claimed;
- a workspace gets one job per claim, and claims go round robin over workspaces (`ORDER BY hint.last_claimed_at`,
  `hosted_worker.py:57-60`). At S1's pace a round is about 12 to 14 minutes, and each position a post loses in its
  workspace costs it a round.

Measured effect:

| Posts | Count | Lateness median | p95 | max |
|---|---|---|---|---|
| in the 503 workspaces with a release | 1,304 | 26.6 min | 39.8 | 40.7 |
| in the other workspaces | 3,696 | 15.3 min | 30.6 | 32.6 |

**Every post later than 32.6 min was in a workspace with a release.** This is lane behaviour, not a harness artefact:
the harness only sets the layout (2.5 posts per workspace, the same due minute), and production would order the same
way. So candidate 4.1 (one preflight per sent post) would also remove the S1 tail beyond about 33 min (inference).
The release itself is the trigger; the requeue behind the workspace's never-claimed posts is what makes it cost
rounds.

### 7.3 Read-back delay: create to verified median 18.15 min, p95 30.13, max 32.43

The same three rules decide it:

- the round robin over workspaces;
- inside a workspace, never-claimed jobs first (`lastDispatchedAt` 0), so every new post of a workspace is created
  before any of its read-backs;
- one job per claim.

A workspace with k posts reaches its first read-back only in round k + 1. The read-back's due time (5 s after the
create, `hosted_worker.py:871`) makes it eligible but gives it no priority. Due time to verified read-back: median
35.63 min, p95 40.26. Only 9 posts were still unverified at the last create, because the tail served read-backs.

**Is it intended?** The comments at `hosted_worker.py:471-473` give the intent of the tenant order, fairness: "a busy
tenant cannot monopolize every chunk lease by sorting before others". No comment addresses the read-back latency. In a
burst, a customer sees the post in Discord while Rafii shows it as sent and not yet confirmed (`provider_accepted`) for
18 to 30 minutes. Candidate 4.2 in this document trades that against the lateness.

### 7.4 Lock benchmark (profile `lockbench`, same runner type)

Admissions per second: one reserve plus one observe transaction per request.

| Configuration | 1 process | 4 | 12 | 24 |
|---|---|---|---|---|
| learned routes, no policy limit, 0 ms round trip | 68.5 | 128.3 | 129.2 | 119.2 |
| the same, 2 ms | 10.6 | 31.9 | 42.4 | 47.4 |
| the same, 5 ms | 4.2 | 14.1 | 20.5 | 23.2 |
| 2 ms with a 120 ms Discord answer between reserve and observe | | | 24.6 | 30.6 |
| cold routes, 2 ms | 9.7 | 22.4 | 24.4 | |
| the reviewed 25/s policy, 2 ms | | | 23.4 (95 delayed) | 24.9 (277 delayed) |

At 12 processes and 2 ms, reserve took p50 153 ms and p95 291 ms, and observe 122 and 213. That is queueing on the
application row lock, against 39 and 56 ms with one process.

**Answer to "is the lock the limiter at 25/s" (inference from these numbers):**

- **At 2 ms per round trip it is the main latency contributor, not a hard ceiling.** The coordinator alone admits 42
  to 47 per second back to back. With a Discord answer between admission and observation, 12 loops get only 24.6/s,
  because each request spends about 300 to 400 ms in the two transactions. The lane's other step transactions (claim,
  lease, seal, record) come on top, which fits the 20.9/s measured in S1's active seconds.
- **At 5 ms the lock becomes the ceiling:** 20.5/s at 12 processes, 23.2/s at 24, below 25 with no policy at all.
- So the real database round trip from Vercel to Supabase decides it, and it was not measured. More loops raise the
  ceiling (24 processes: 30.6/s with a Discord answer) at the price of longer queues (reserve p95 614 ms).
- The live deployment runs in Vercel iad1 and the production Supabase project in us-east-1, which are co-located
  (fact from the coordinator). That makes the 2 ms case the plausible one and the 5 ms case a stress test. The real
  round trip, through Supavisor with TLS, remains to be measured on Depot or Production.

### 7.5 What would move the S1 median (inference from 7.1 to 7.4)

P50 ≈ 2,500 × r / (25 × duty × packing):

| Lever | duty | packing | r | P50 (min) |
|---|---|---|---|---|
| today | 0.78 | 0.84 | 6.75 | 17.2 |
| loop budget 58 s (S1-lane58) | about 0.92 | 0.84 | 6.75 | about 14.6 |
| budget 70 s, or warm with 58 s (S1-lane70, S1-warm) | about 0.98 | 0.84 | 6.75 | about 13.7 |
| plus one preflight per sent post (4.1) | 0.98 | 0.84 | about 6.1 | about 12.4 |
| plus charge-once accounting (4.9) | 0.98 | about 0.95 | about 6.1 | about 10.9 |

P95 and max depend mostly on the release requeue (7.2). 4.1 (F1 and F5) removes most releases; 4.1b (F2) removes
the requeue for the rest. The `s1levers` profile (S1 as control, S1-lane58, S1-lane70, S1-warm) measures the
duty-cycle rows alone. No code changes. The reviewer's calibrated ladder predicts duty about 0.97 for a loop budget of
58 or 70 s, and P50 about 14.0 / P95 29.0 / max 32.0 with today's waste.

### 7.6 S2: a workspace with 3,000 due posts sends nothing (lane defect D3)

On the runner the 3,000-post workspace sent **0** posts in 50 minutes. Its 3,000 posts ended as follows:

- 2,998 held at approval expiry. Of these, 134 had been released "Await Discord shared rate budget; no POST occurred".
- 2 uncertain with a sealed intent and no create at the mock (w0-p24, w0-p132).

The 1,999 small workspaces were all served by 17.18 min, against at most 15 min.

**Measured (sandbox reproduction with the same seeding code):**

- The hot workspace's document is **15.7 MB of JSON text** (5.9 MB stored). A 1-post workspace is about 14.5 KB.
- One read-modify-write of the hot document took 2.7-3.0 s at load 30: SELECT and decode 0.4-0.6 s, dumps 0.2 s,
  UPDATE 2.1 s. A small workspace takes 12-55 ms.
- On the runner, the state UPDATE peaked at 4.57 s (`pg_stat_statements`).

**Mechanism (code):**

- The create permit lives at most to the end of the current application window (4.1).
- The seal and the second lease renewal each read and rewrite the whole document (`authorize_dispatch`,
  `hosted_worker.py:906-940`; `renew_discord_lease` at `:1274`), and each takes longer than any window remainder.
- So every attempt died: 134 before the seal and 2 after it.
- The workspace is served one leased job at a time (`in_flight`, `discord/worker.py:75-78`), so the other 11 loops
  idled: claimMisses 3,158, idleWaits 2,516.
- Each claim also sorts and scans all 3,000 jobs (`:552`, `:574`).

F1 and F5 (4.1) remove the window-end death. The document size remains: one post per step at seconds per transaction,
so the profile `s2sizes` (hot workspace of 100, 300 and 1,000 posts) measures where this design stops keeping up. A
single channel physically allows about one create per second, so 3,000 posts in one channel need at least 50 minutes
at any ceiling; how S2 is judged for the hot workspace is a question for the owner.

### 7.7 Admissions that are never observed hold budget forever (lane defects D1 and D2)

- **Mechanism.** `consume()` marks a create `sent` before the POST (`rate_limits.py:700-704`), and a read is inserted
  `sent`. If `observe()` then fails, the row stays `sent`; a lock timeout of 2 s is enough. `_pending` counts `sent`
  and `uncertain` admissions with no age bound (`:507-511`), and every window restart gives cap minus pending. Each
  such admission therefore takes one slot of the 25 and one slot of its route, permanently.
- **Fdb on the runner.**
  - The run ended with exactly **25** `sent` admissions.
  - Creates went 152, 101, 50 and 1 per minute, then 0 for 37 minutes, and 1,195 posts waited "Await Discord shared
    rate budget".
  - The database log shows 689 + 119 lock timeouts in the coordinator's statements.
- **Fcrash.**
  - 4 kills during a landed create left 4 `sent` admissions.
  - Each was its channel's first create, on a route still unknown and so capped at 1, which locked those channels.
  - 5 sibling posts were held at approval expiry.
- **Elsewhere.** F5xx left 6 `uncertain` and S2 1 `sent`. Every receipt now states these by state, as the launch gate
  requires. An age bound must make them self-healing (the limiter work).

