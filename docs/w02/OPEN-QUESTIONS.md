# W-02 open questions for the owner

Each needs a decision before or during W-02 rollout. None blocks the branch as built: the lane is off by default and
changes nothing until its flag is set on a new, separately approved build. Labels: [measured] on the local real-PostgreSQL
run; [simulated] from the fake-clock model; [reasoned] from the code.

## Decide before turning the lane on

**Q1. Approval lifetime against queue length.** A Discord approval expires one hour after the post's scheduled time
(`store.py`: `expiresAt = timing.timestamp + 3600`). A post that cannot be sent before then is held for a fresh approval,
never sent late [measured: test (d)]. With today's six requests per post and the 25 per second policy, about 13,000 posts
due in the same minute can go out inside that hour; the rest are held [simulated]. Options: keep one hour and accept holds
at very large bursts; lengthen it for Discord (for example scheduled time plus three hours; changes what an approval
means, needs the PRD owner); or spread the peak (Q8).

**Q2. Requests per post: six, not two.** The plan assumed two requests per post (create and read-back). The code makes six
on the bot path: four permission reads before every create (the server, the bot's membership, the linked person's
membership, the channel list), the create, and the read-back [reasoned from `social_connectors.py`, measured 6.1 to 6.3
per verified post]. That triples every drain time in the plan. Options, each needing its own qualification: cache the
permission evidence per server for a short time; read only the channel and the bot's membership; one request per post
(read back only when the create is uncertain; out of W-02 scope, changes the PRD A09 evidence design).

**Q3. Requests in flight when a process dies.** If a function stops between a request's admission and its answer (a
crash, an out-of-memory kill, an infrastructure fault), the coordinator keeps that admission counted in every later
window until someone reviews it (its documented conservative rule). Effects: one slot of the application budget is
lost per dead request; on a route whose limits were not learned yet (the first request to that route for that server or
channel) the route's single probe stays spent, so later posts to that channel wait unsent until review; a dead create
also leaves its job 'uncertain' for manual reconciliation [measured: tests (a), the cold-route test]. Nothing is ever
sent twice. That wait is not idle [measured, rollback run]: every claim of such a post is refused and released for
about a second (the unknown-route window), by the minute cron and by lane loops alike, and each churn adds three events
to the job (113 claims in 60 s for two posts, with the minute cron ticking every 0.2 s), so the job's history and the
workspace row grow, and every churn writes the workspace, until the admission is reviewed. There is no reviewed
procedure to release such a row today. More concurrent loops mean more requests in
flight at any instant, so W-02 raises the exposure. Options: a reviewed operator procedure (monitor M5 finds the rows);
or an automatic release of unanswered reads after a fixed age (a read that left two minutes ago cannot still be using a
one-second window), creates only after their job is reconciled. This is a coordinator change and needs the coordinator's
reviewer. **Since changed (limiter branch):** such a row stops counting after its scope's window plus 30 seconds, whoever
reviews it, and stays `sent` or `uncertain` as evidence; a read that failed is resolved at once. A dead create still leaves
its job `uncertain` for manual reconciliation.

**Q4. What the operator hold does to a post mid-handoff.** Setting the hold also blocks every reserved-but-unused create
permit (existing coordinator rule). A loop that had sealed a post's intent but not yet sent it records the post as
'uncertain' though nothing was sent; it then waits for manual review [measured: test (e), at most one per loop]. Accept
(the hold is an emergency brake), or have such a post recorded as provably unsent (a protocol change). Since changed, for
the hold and for an embargo alike (AS-BUILT.md, "A permit an embargo blocks before it is used"): when consume() refuses the blocked
permit before any transport, the post is proven unsent and released, and a reserved permit blocked before sealing is a
rate wait instead of a hold; a process that dies between sealing and sending still leaves its post 'uncertain'.

**Q5. How many shards, and their cost.** The branch adds 12 cron entries (`/api/cron/discord-worker/0` to `/11`), so
Vercel starts 12 invocations every minute whether or not there is work: about 17,000 a day, 520,000 a month. With the flag
off each answers after the cron-secret check, without the runtime or the database. With the flag on and nothing due each
opens one connection for one statement and stops (none when the lane cannot run). With work due, each runs up to 50 seconds. 12 loops keep 25 requests per second
busy at a per-request latency up to about 0.3 seconds [simulated]; 16 for 50 per second. Choose K, and whether the cron
entries ship in the build before the flag is turned on (they cost invocations from the first minute).

**Q6. A one-hour approval also bounds a single busy workspace.** A workspace sends one post at a time (one live Discord
lease per workspace, the existing fairness rule), and Discord allows about five creates per channel per five seconds. A
customer with 1,000 posts due in one minute therefore needs at least 1,000 sequential steps, roughly 20 to 40 minutes, even
when every other loop is idle [reasoned]. Keep (fair, simple) or allow a few in flight per workspace (a protocol change).

## Decide later

**Q7. A higher request policy.** Discord's documented global limit is 50 requests per second per bot; the reviewed policy
uses 25 so that two adjacent fixed windows stay inside it. Moving to 50 halves drain times (5,000 posts: about 23 to about
12 minutes at six requests per post [simulated]) but leaves no margin for the shared egress addresses. Needs a new reviewed
policy (`scripts/discord_rate_policy.py`) and the owner's capacity run. Mechanics, as built on the limiter branch: the
policy tool refuses an `app_capacity` above half the bot limit (25), a renewal can only tighten the stored cap while the
previous policy is valid (the stored expiry is the latest of all), and the exact window no longer needs the "two adjacent
windows" margin. A reviewed raise therefore needs (1) the tool's ceiling changed and reviewed, (2) the new policy, and (3) an
operator updating the application row's `limit_count`; none of the three happens by accident.

**Q8. Scheduled-time jitter (Phase 1b, not built).** A backend-only random offset of up to two minutes on the stored
scheduled time turns a top-of-the-minute spike into a two-minute plateau. It changes what the customer sees ("sent between
09:30 and 09:32"), so it needs schedule-dialog copy before it is honest; not started in this branch.

**Q9. Ask Discord for a higher limit** once traffic justifies it (large verified bots can ask); the only way past 50 per
second on the bot token.

**Q10. Webhook mode.** Whether webhook sends count against the bot's global limit is unverified (the docs hosts did not
resolve from this sandbox). If they do not, webhook mode is a burst-relief path. Needs a documentation check and its own
qualification.

**Q11. A dedicated always-on worker.** One small process reading the same queue avoids cron minute boundaries and cold
starts. New infrastructure and cost.

**Q12. Hot channels and preflight cost.** When a channel's create window is full, the create permit is refused after the
four permission reads, so each refused post spends four reads again in the next window (the existing step order reserves
the create permit last) [reasoned; seen in the one-channel test]. Bounded by one workspace, one post at a time. Reserving
the create permit before the permission reads would avoid it; that is a protocol change.

**Q13. The minute worker with the worker flag off and migration 128 installed.** Found by the independent review of the
send path: with `POSTRIFF_DISCORD_WORKER_V1_ENABLED` unset or mistyped, the minute worker claims a due Discord post the old
way, migration 128's guard refuses it (CheckViolation) and the whole claim aborts on every attempt for every provider
[reasoned and reproduced by the review]. Built: the hosted preflight now fails a build with any Discord feature flag on and
the worker flag not 1 or true. Not built, because it touches the frozen path: a reactive guard in `PostgresWorker.claim`
(react to that one CheckViolation, claim again without Discord for the rest of the process, count it, log one WARNING;
`FlagOffIsTheFrozenBase` stays green, the minute worker would then leave Discord posts unsent instead of raising).
Decide whether to build it (AS-BUILT, "The worker flag and migration 128").

**Q14. What a paused Discord does to read-backs.** A paused Discord (kill switch, authorization off) now releases creates
unsent and demotes nothing (AS-BUILT, "A paused Discord is a wait"), and the lane claims nothing while paused. An existing
rule is unchanged: a read-back (reconciliation) of an already created post that meets a disabled execution is completed
`uncertain` ("The original Discord application is unavailable. Keep the receipt for manual review."), and five such checks
push it to a one-day wait. Neither the lane nor, since the K1 churn fix, the minute tick claims anything while Discord is
paused (`tick()` passes `exclude_discord=True`), so only a scoped claim can still reach that rule and the read-back is
made after the pause. Open: whether a scoped claim (a person's "post now") should wait too; today it reaches the
preflight, which refuses with the pause, and the post is released unsent for a minute.

**Q15. An exact split of creates and read-backs for monitoring.** The lag warning tells them apart in the report's sample
and treats the projection's lag (one `next_at` per workspace, migration 126) as a create's unless the sample shows
read-backs waiting. An exact split over every workspace, and the same split in the ops health payload (which reads the
projection), needs two columns in the projection (a new migration, not made). Without one, the oldest due `next_at` among
workspaces with `last_claimed_at = 0` is an exact create lag for workspaces the lane never served.

**Q16. Admissions are never purged.** Every request writes one row to `pr_discord_request_admissions` (the permit, then its
outcome) and nothing deletes it. Measured on PostgreSQL 16 with the real coordinator (1,500 reads): 2.6 KB of heap per
admission (the insert and the observation's update each leave a version until vacuum) plus its indexes, 1.5 KB when the routes
are learned and 3.9 KB when every request is a new resource (the GIN index on `scope_keys` holds a key per cold route): 3.7 to
6.5 KB. At the reviewed 25 a second that is 2.16 million rows and 8 to 14 GB a day (250 to 440 GB over the policy's 31 days);
at one a second 86,400 rows and 0.32 to 0.56 GB a day. The coordinator needs a read's row only until it is answered and its
slot has freed (the window and 0.1 s, or 30 s more if it was never answered); the ops snapshot reads the newest 2,048; a
publication's row is the audit trail. The service role may SELECT, INSERT and UPDATE these tables, not DELETE (migrations 124
and 125). The application's connection is not that role if the preview preflight (`deployment.py`: user `postgres`, or
`postgres.<project>` through the pooler) also holds in production, and the table owner needs no grant. Not checked (no
Production access): `SELECT current_user, has_table_privilege(current_user,'public.pr_discord_request_admissions','DELETE')`
from the application's own session. Options: a periodic delete, in small batches, of rows that are `NOT is_publish`, `observed`
or `blocked` and older than an hour (at 25 a second the table then stays near 90,000 rows, 0.3 to 0.6 GB); daily partitions
dropped after two days (a migration); or a ring of the last 25 wire times in the application row, which puts a write on the
hottest row at every consume and loses the per-request record. Nothing is built; a grant would be a migration.

**Q17. A hold and a read-back (built, 1fe434c7).** A read admitted under a hold (the operator's, a held credential or a held
route) used to raise `RateCoordinatorUnavailable`, which the read-back of a created post (`hosted_social`, the `except
RateDelayed` branch) did not treat as a deferral: the answer was `uncertain`, the check was not refunded and the worker came
back in 5 s, so five attempts (about 25 s of hold) parked the post for a day ("Manual provider review required"; the ops
review's H1/E1). Now `_reserve` raises `RateDelayed(300, cause='hold', scope='embargo')` for a read; `_discord_http` makes it a
`ReadAdmissionDelayed`, the read-back answers with a deferral that refunds the check and the post is tried again in five
minutes, however long the hold lasts. A create is still unavailable. Pinned by `ReadsUnderAHold`, `PolicyAndHold` and the
randomized model, and end to end on PostgreSQL by `test_discord_hold_readback_postgres` (eight claims under the hold, one per
five minutes: still `provider_accepted`, no check spent, nothing sent; verified after the release). What else it touches: the
direct reads of a request now answer 429 `discord_rate_delayed` where they answered 503 `discord_rate_coordinator_unavailable`
during a hold, and the web copy differs ("Discord is busy right now ... try again in a minute" for `rateDelayed`, where
`coordinatorUnavailable` said "Connecting to Discord is paused for a moment ... try again later"; `web/src/lib/channels/
discord-refusal.ts`). The callers: the connect flow (`DiscordProvider.identity`, the guild and member lookups), the destination
list (`destinations`), the installation re-verification and connect (`discord/oauth.py`), the webhook set-up reads
(`discord/webhooks.py`), the message-content check (`discord/message_content.py`), the reply reads (`discord/engagement.py`) and
the sender-name page (`discord/sender_names.py`); in the worker the create's preflight reads release the post unsent for five
minutes as before. A hold on the credential or a route now defers a read-back for ever (every five minutes) instead of parking
it after five checks; the hold is an operator's to lift. The ops drills (PostgreSQL, merged with the alerts branch at e79df41d)
move only in what they record: 15 drills, only D3 fails, before and after (the guard, Q18). The alerts branch's runbook text that says
read-backs are parked for 24 hours when a Discord-claiming worker runs under the hold, and the lift being "at once" for that
reason, describes the old behaviour.

**Q18. Giving back part of the guard's 9 percent (not built).** The slot headroom (`SLOT_GUARD_SECONDS`, 0.1 s) caps steady
admissions at 25 / 1.1 = 22.7 a second. At about 7.1 requests a post the median line of the 5,000-post run (2,500 posts in 12
minutes) needs about 24.8 a second with perfect packing, so the guard alone costs 9 percent against a modelled margin of 3 to
6. What it buys: no closed second of ARRIVALS above 25 while the admission-to-wire spread stays inside it. Two facts frame
every option. A guard g costs g/(1+g) of the ceiling (0.06 s: 5.7 percent, 0.03 s: 2.9, 0.02 s: 2.0). And 24.8 sustained under a
ceiling of 25 leaves 0.8 percent, about 8 ms of spread: no guard meets both "24.8 sustained" and "never above 25 in a closed
second"; only a smaller spread (pacing) or a higher cap can. (A side effect to know: the ops alert RATE_APP_BUDGET_SPENT fires at
95 percent of the nominal ceiling over a minute (`saturation_warn` 0.95), and a saturated application now reaches 90.9 percent, so
it can never fire and the drill D3 of the alerts branch fails. That branch must divide by the achievable ceiling, capacity x 60
/ (window + min(guard, window / 10)), or lower the threshold to 0.85, which turns the drill green; it belongs to that branch.)
The options, cheapest first, with the risk of each:

1. A guard sized from the measured spread. The capacity harness reports the admission-to-arrival wire jitter on the hosted runner
   (p99.9). Set the guard to about twice what it shows: one constant and its pin (`ShippedConstants`), no schema, no `Permit`
   field. 30 ms of spread gives 0.06 s. Risk: the tail decides, not the typical case. A cold connection (a TLS set-up is 100 to
   300 ms), a garbage-collection pause or a busy machine arrives later than the guard allows and puts a 26th request into a
   second; Discord answers it with a global 429, the coordinator embargoes the global scope for its Retry-After (about a second,
   so the overshoot repairs itself) and the 429 counts toward the invalid-request budget (2,000 reviewed of Discord's 10,000 in
   ten minutes). A tail rarer than a few a minute is harmless; a heavier one needs a bigger guard.
2. Keep the connection warm. Most of the spread is connection set-up: `http_transport` opens a new TLS connection per request.
   A kept-alive connection per process removes the 100 to 300 ms tail, which shrinks the spread the guard must cover and the
   latency of every post, with no change to the ceiling logic. Risk: it changes the transport every provider shares (timeouts,
   no redirects, the response cap), a reused connection the platform closed while the function was frozen, and the rule that a
   create is never sent twice must survive a retry on a dead connection (it must not retry). Do it first if the harness shows
   the spread is the handshake.
3. The owner's option: a policy cap with the guard inside it. Set `app_capacity` so that capacity / (1 + guard) is the rate
   wanted: 28 with the 0.1 s guard gives 25.45 sustained and at most 28 in a closed second while the spread is inside the guard.
   No code change except the policy tool's refusal above 25 (`judge()`), but the reviewed number and the acceptance measure
   change from "no second above 25 at the mock" to "no second above 28". Discord's own limit is 50, so 28 is 56 percent of it
   instead of 50. Risk: the margin the reviewers chose shrinks, and a spread beyond the guard overshoots 28, not 25. It is the
   only option that meets 24.8 sustained at all.
4. Pacing at the wire. The permit carries a send time and the transport waits for it, so the arrival spread becomes the
   sleeper's jitter (milliseconds) and the guard can shrink to about 10 ms. Risk: the highest. The `Permit` has a frozen
   seven-field shape that the sender claim rebuilds from its stored id and expiry (a new field changes that contract and the
   claim documents); a sleep in every request path (up to the guard's size, billed function time); two clocks to reconcile (the
   database's stamps against the process's); and it does not bound bunching: a process that stalls and then sends several late
   requests at once arrives above the ceiling anyway unless it also holds a local token bucket. Not before 1 to 3 are measured.

Suggested order: measure the spread on the hosted runner; warm the connection if it is the handshake (2); set the guard from the
new spread (1); only if the median line still needs more, the owner decides on the cap (3).

**Q19. Booking: a place in line instead of a lottery for the freed slot (built, P2: ca106be8, 9c35bda1, cdab6c98).** The hosted
S1 run of 3dac3ccf (5,000 posts, 12 shards, 25 a second) was slower than every earlier estimate: median 19.77, p95 37.87 and
longest 43.52 minutes against 12, 25 and 40, with 8.95 requests and 18.6 reservation lock statements a post and 4,714 releases of
a claimed post. The cause is the way a full window is polled. A refused read slept the time it was quoted and asked again; at a
saturated window about six of the 12 shards woke for the same freed slot, one won, and a read that lost three times (the 1 s
deadline) released its whole post and threw away the one to five preflight reads it had completed (8,655 requests, 1.73 a post,
all of them slots of the same budget). Lock statements are the price of the lottery, releases its waste. Booking replaces it:
inside `rate_limits.booking()` (the lane sets it around the preflight reads, the create permit and the read-back, and nowhere
else) a caller that finds the window full is stored at the earliest exact slot after every wire time already stored, if that is
within one second, and waits for it after the commit with no lock held; the ceiling rule is unchanged, only a wire time may lie
ahead of the clock. The rule, the gate, the row, the counters and the tests are in AS-BUILT.md, "Booking".

Measured and modelled, per post. The measurements are local: the real coordinator, provider and lane steps on a disposable
PostgreSQL 16, 12 threads standing for the 12 shards, an in-process mock Discord (50 to 150 ms), a 2 ms relay on every statement,
the application window kept full (a cap of 14 or 18 is what this four-core box can saturate), 60 s after 25 s of warm-up, two runs
each. The model is the discrete-event model (`des.py`, five seeds, the same parameters) fitted to the hosted S1 run, not to
these. Cells are measured / model.

| per post | cap 14 before | cap 14 after | cap 18 before | cap 18 after |
|---|---|---|---|---|
| posts a minute | 74 / 55 | 107 / 108 | 102 / 74 | 137 / 132 |
| passes (preflight and create attempts) | 2.45 / 5.9 | 0.89 / 0.97 | 2.18 / 5.0 | 0.92 / 1.00 |
| requests at Discord | 9.6 / 14.4 | 6.46 / 6.5 | 9.0 / 13.1 | 6.64 / 7.0 |
| reservation attempts (refused and admitted) | 23.5 / 42.6 | 6.45 / 6.46 | 19.6 / 36.6 | 6.64 / 6.93 |
| reservation lock statements | 29.2 / n.a. | 12.0 / n.a. | 25.3 / n.a. | 12.3 / n.a. |
| releases of a claimed post | 1.90 / 5.0 | 0.00 / 0.00 | 1.48 / 4.0 | 0.00 / 0.00 |
| bookings, and the seconds waited in them | none | 6.4, 4.0 s | none | 6.6, 3.0 s |

The model is right about booking (posts a minute within 4 percent, attempts and requests within 6) and too pessimistic about
polling at these small caps: its lottery is harsher than the real one (the five seeds range from 34 to 62 posts a minute at cap
14). The lock statements are not modelled: the model counts attempts, and this fixture, which meets every server for the first
time, adds a seeding statement to most of them (the hosted S1 run implies about 1.06 statements per attempt). Nothing went over the
cap at the mock, nothing was posted twice, in either tree.

The hosted S1 shape (12 shards, 25 a second, claim 0.8 s: the model's calibration), per post:

| | S1 measured, before | model, before | model, after | expected on the S1 shape, after |
|---|---|---|---|---|
| posts a minute | 126.5 | 144 | 174 | 150 to 158 |
| requests at Discord | 8.95 | 8.8 | 7.0 | 7.0 |
| reservation lock statements | 18.6 | 16.6 (attempts) | 7.0 (attempts) | 7.5 to 8 |
| releases of a claimed post | 0.94 (4,714) | 1.13 | 0 | 0 |
| passes | 1.75 (8,730) | 2.0 | 1.0 | 1.0 |

The expected column applies the model's ratio (1.21 in posts a minute) to the measurement: median line 16.3 minutes, p95 31, longest
about 36, against 19.77, 37.87 and 43.52 and a plan of 12, 25 and 40; the 56-second duty cycle (`POSTRIFF_DISCORD_PARALLEL_WORKER_MAX_SECONDS`
50 to 56) would add 12 percent of loop time to that again. With 24 shards the model gives 96 posts a minute, 45 attempts and 6.2 releases a post
for polling, and 182, 7.1 and 0 for booking. On this box the thread model at 24 threads is bound by its own lock queue and Python
process, not by the window (caps 26 and 36: 163 to 173 posts a minute and 18 to 19.5 requests a second, almost no refusals, in both trees), so
it cannot show the difference; the measurement that counts at 24 is the capacity run. (Its first attempts failed for a reason worth
knowing: every synthetic tenant of `discord_lane_fixture.py` shares one Discord user id, so the identity read of every tenant takes
one route-bucket row `FOR UPDATE`, and at 24 threads the queue behind it passed the coordinator's 2 s lock timeout and the provider
failed closed. The capacity harness gives each tenant its own person and does not have this; production has a user per tenant.)

The exactness probe with 24 threads at a cap of 25 (`tests/discord_ceiling_probe.py`, the same fixture as before, 8 s a cell, no
added delay and 100 ms of it): reservation lock statements per admission 3.56 and 3.53 without booking, 1.65 and 1.74 with it;
creates in the cell 14 and 14, 31 and 31 (the creates are not starved when the reads are booked too); refused reservations 111 and
102, 13 and 18; busiest closed second of wire stamps 25 and 25 (the cap), 24 and 24 (cap less the web reserve); arrivals above 25
in a second at the mock 0 in all four; admissions 22.2 and 22.1 a second without booking, 20.4 and 20.7 with it (the reserve slot,
and 24 callers against a horizon of about 21 that refuses the rest).

What to know before relying on it.

- **What it does not change.** The requests per post (about 7 on the bot path: Q2), the guard (0.1 s: Q18) and the ceiling (22.7 a
  second). At 7.0 requests and 22.7 a second the floor is 194 posts a minute, so 2,500 posts take 12.9 minutes at best: booking
  takes the lane from the lottery to that floor's neighbourhood, not below it. Its gains stack with a smaller guard (Q18) and with
  not charging the bearer call: each is a separate decision.
- **The horizon holds about (cap - 1) / 1.1 loops** (one booking each): 21 at the reviewed 25, so 12 loops fit and 24 are at the
  edge. A caller beyond the horizon is refused and polls as before booking, plus the cost of the refusal; with a cap of 10 for 12
  loops (measured) that is a little worse than before. Raising the shard count past 12 needs a cap to match; the shard count stays
  12.
- **The evidence behind a create grows older.** The permission reads come first in a pass and each may wait up to a second, so the
  create leaves later [simulated, median age of the reads at the create: 1.3 s to 2.3 s at 12 loops, 2.2 s to 5.7 s at 24; no
  bound in code]. The approval, the lease and the fences are rechecked at the seal as before.
- **One slot of every window is kept for callers that cannot wait** (`IMMEDIATE_RESERVE`): a web request never finds the window
  full of bookings. It costs 1 of 25 at saturation (4 percent). With 5 web reads a second [simulated], 84 percent of them were
  admitted while the lane polled and 99 to 100 percent are with booking (their 90th-percentile latency 0.36 s to 0.55 s).
- **What can happen during a wait.** A process that dies leaves the booked read stored `sent` with a wire time ahead: it is never
  sent, keeps its slot for the window plus 30 s (31 s) and then stops counting, at most one per shard (12 of 25 at the very worst).
  A hold, an embargo or an open circuit that begins during a wait of 25 ms or more is found by the read's last look just before it
  is sent (one statement, no lock): the read is closed unsent and the post waits as for a refusal at admission; a booked create is
  stopped by the existing block of unused permits at seal or consume. What can still leave after an embargo begins is what could
  before: the time between that look (or the commit, for a wait under 25 ms) and the wire. The F429 and B4 tests are unchanged and
  pass.
- **Operators see a different `remaining`.** The application row now stores the slots bookings may still fill and when a booking is
  possible again, so with a busy lane it stays high and falls to 0 only when the horizon is full and callers are refused again;
  `lane.outlook` is unchanged and waits only then. Any reading of the row's `remainingRatio` or `resetSeconds` as
  "the window is nearly spent" is now wrong: use `coordinator.booking` (below). The most a saturated lane sends is (cap - 1) /
  1.1 a second, 21.8 of 25 (87 percent of the nominal ceiling, 96 of the 22.7 that the guard alone allows); the alert on a spent
  budget (`saturation_warn`, Q18) must divide by that.
- **Fields.** The lane's `bookedWaits` (bookings) and `bookedSeconds` (their total wait) in the invocation result and the
  `discord.lane.completed` line; the health payload's `coordinator.booking`: `bookAheadSeconds`, `aheadNow`, `horizonSeconds`,
  `bookedReads60s`, `bookedReadWaitSeconds60s`, `meanBookedReadWaitSeconds60s`, `maxBookedReadWaitSeconds60s`.
- **Off.** The lane flag (the minute worker never books), or `BOOK_AHEAD_SECONDS = 0` in a build.
