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
preflight, which refuses with the pause, and the post is released unsent for a minute. A missing or unusable coordinator is a
different state from this pause and is not covered by it (Q20); its read-back is a wait, not an `uncertain` (AS-BUILT, "A
read-back waits for the coordinator").

**Q15. An exact split of creates and read-backs for monitoring.** The lag warning tells them apart in the report's sample
and treats the projection's lag (one `next_at` per workspace, migration 126) as a create's unless the sample shows
read-backs waiting. An exact split over every workspace, and the same split in the ops health payload (which reads the
projection), needs two columns in the projection (a new migration, not made). Without one, the oldest due `next_at` among
workspaces with `last_claimed_at = 0` is an exact create lag for workspaces the lane never served.

**Q16. Retention of the coordinator's admissions (built, e6aa7db8; migration 142 written, not applied).** Every request writes one
row to `pr_discord_request_admissions` (the permit, then its outcome) and nothing deleted any. First measured on PostgreSQL 16 with
the real coordinator (1,500 reads, before any vacuum): 3.7 to 6.5 KB a request with its indexes. Vacuumed, the sizes are smaller
(the rows built as the real code builds them, indexes included): a read 2.4 KB (1.0 heap, 1.4 indexes), a publication 3.4 KB (1.6
and 1.7). At the 23.8 requests a second the reviewed 25 sustains with the guard of 0.05 s that is 2.06 million rows and about 5.2 GB
a day, 160 GB over the policy's 31 days; at the nominal 25, 2.16 million and 5.5 GB (the unvacuumed figures would say 8 to 14 GB). The coordinator needs a read's row only
until it is answered and its slot has freed (the window and 0.05 s, or 30 s more if it was never answered); the ops snapshot reads
the newest 20,000; a publication's row is the audit trail for two days (the owner's approved window; first drafted as one).

Built: `SharedPostgresBudget.purge_settled()` deletes, a bounded batch at a time, what the coordinator can no longer count and
nothing else. Reads (`NOT is_publish`) that are `observed` or `blocked` and were reserved more than an hour ago, publications the
same after two days, and nothing that settled in the last ten minutes (a late reconciliation of an old row finds it again). Never an
unresolved row (`reserved`, `sealed`, `sent`, `uncertain`: the evidence a person reviews, an expired unused permit included),
never a scope row (windows, embargoes, circuits, holds), never another application's. 2,000 rows a statement, oldest first, `FOR
UPDATE SKIP LOCKED`, three rounds a call, one purger at a time (a transaction-level advisory lock; the others return `busy`),
`lock_timeout` 1 s, `statement_timeout` 5 s, one short transaction a round; it never takes the application row's lock or a scope
lock, so a reservation never waits for it and it never delays one; idempotent; it never raises: the outcome says `ok`, `busy`,
`denied`, `timeout` or `error` with the exception class only. Its cutoff is `now()`, not `clock_timestamp()` (a volatile function
cannot bound an index scan: a call with nothing to do walked every young row, 66 ms at 50,000, instead of none). The lane asks once
its loop is over, when the invocation had work, at most once a minute in a process, no flag (`discord.lane.retention` at INFO when
it deleted, at WARNING when it could not; counts, status and class only); an idle shard still opens one connection for one
statement and purges nothing. The health payload's `coordinator.retention` shows `retentionSeconds`, the two oldest settled ages
(far past the retention, three times, means the purge is not running or cannot delete), row estimates, `rowsDeletedTotal` and the
last vacuum.

Sizes with retention (measured; rows updated when they settle and deleted when they age out, with vacuums as autovacuum would):
4.4 to 8.6 KB for each live read and 5.6 to 12.8 KB for each live publication, the dead versions that updates and deletes leave
until vacuum included (the low end with frequent vacuums, the high end with one every three batches of a fifth of the table). The table then
holds the last hour of reads and the last two days of publications. At 100 posts a minute (6 reads and a publication a post) that
is 36,000 reads and 288,000 publications, 1.8 to 4.0 GB; at the ceiling of 23.8 a second (3.4 posts) 73,000 and 587,000, 3.6 to 8.1
GB; nine tenths of it is the publications, so `PURGE_PUBLICATION_SECONDS` is the knob (each day costs 0.8 to 1.8 GB at 100 posts a
minute; with one day the figures were 1.0 to 2.2 GB and 1.9 to 4.2 GB). One million synthetic rows (84 percent reads, 14 percent publications, half of each past its retention, 2 percent
unresolved; 2,468 MB with indexes): a call, three rounds of 2,000 reads, takes 0.21 s (71 ms a round) against the 5 s statement
timeout; the other 646,000 eligible rows go in 16.2 s (about 40,000 a second); a call with nothing to do 27 ms (a connection and two
index probes); 200,000 rows, the test default, 0.28 to 0.32 s and 15 to 24 ms. The partial index of migration 142
(`pr_discord_admission_purge`, settled rows only) costs 32 bytes a row and is what the purge walks; without it the purge scans.

Not checked (no Production access): the privilege. The service role may SELECT, INSERT and UPDATE these tables, not DELETE
(migrations 124 and 125), and the application's connection is not that role if the preview preflight (`deployment.py`: user
`postgres`, or `postgres.<project>` through the pooler) also holds in production; the table owner needs no grant. Run
`SELECT current_user, has_table_privilege(current_user,'public.pr_discord_request_admissions','DELETE')` from the application's own
session. Without DELETE the purge reports `denied` (a WARNING a minute) and deletes nothing, the table grows as before and
`oldestSettledReadAgeSeconds` keeps rising; the owner's fix is `GRANT DELETE ON public.pr_discord_request_admissions TO
service_role` (its policy already allows every command) or the owner role. Apply migration 142 first when the table is small (a
plain CREATE INDEX takes a SHARE lock for the build); on a large table use the CONCURRENTLY form in its header.

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

**Q18. The slot guard (the owner's D-16: 0.05 s; built).** The slot headroom (`SLOT_GUARD_SECONDS`) was 0.1 s. It capped steady
admissions at 25 / 1.1 = 22.7 a second, 9.1 percent under the 25, against a median line (2,500 posts in 12 minutes at about 7.1
requests a post) that needs about 24.8 a second with perfect packing. The owner's reading of "25 requests a second" (D-16): the
coordinator never admits more than 25 stamped requests in any sliding second (exact, pinned by the randomized brute-force count
and the 24-thread tests), arrival at Discord is REPORTED (the probe's peak and share of arrivals above 25 in their trailing
second, the capacity harness's wire jitter) and is not a failure, and stays far under Discord's real limit of 50. The guard is now
0.05 s. A guard g costs g/(1+g) of the ceiling: 4.8 percent, 23.8 a second sustained (22.9 with the web slot kept back, Q19), where
0.1 s cost 9.1. Measured with the 24-thread probe on the new guard (cap 25, the mock answers in 100 ms): the busiest closed second
of wire stamps is 25 (24 when the lane books), exactly the cap, with no added delay and with 50, 100 and 300 ms of it; at the mock,
with up to 100 ms of added delay (wire delay p99.9 up to 127 ms) no arrival saw more than 25 in its trailing second (peak 25, 24
when booking), with 300 ms 1 to 3 of about 190 did (0.5 to 1.6 percent, peak 26), as at 0.1 s. What 24.8 sustained under a ceiling
of 25 would leave is 0.8 percent, about 8 ms of spread: no guard meets both "24.8 sustained" and "never above 25 in a closed second
at Discord"; only a smaller spread (pacing, option 4) or a higher cap (option 3) can. (The ops alert RATE_APP_BUDGET_SPENT fires at
95 percent of the nominal ceiling over a minute (`saturation_warn` 0.95); a saturated application reaches 95.2 percent without the
web slot kept back and 91.4 with the lane booking, so it has to divide by the achievable ceiling, capacity x 60 / (window +
min(guard, window / 10)); the alerts branch reads the guard from the build, so nothing there changes with this constant.)
The options as they were put to the owner, cheapest first (1 is what was chosen), with the risk of each:

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

Suggested order, as it stands: the guard from the spread (1) is done at 0.05 s; measure the spread on the hosted runner and warm the
connection if it is the handshake (2); only if the median line still needs more, the owner decides on the cap (3).

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
50 to 56) would add 12 percent of loop time to that again. With the guard at 0.05 s (D-16) the model gives, for 12 shards: polling
155 posts a minute, 8.5 requests, 15.2 attempts, 0.93 releases; booking 179, 7.0, 7.0, 0. The expectation for S1 from booking and
the new guard together is the model's ratio 179 / 143.6 = 1.25 on the measured 126.5: 157 posts a minute, median line 15.9 minutes,
p95 30, longest about 35 (the floor at 7 requests and 23.8 a second is 12.3 minutes). With 24 shards the model gives, at 0.1 s, 96
posts a minute, 45 attempts and 6.2 releases a post for polling, and 182, 7.1 and 0 for booking (at 0.05 s: 104 and 192). On this box the thread model at 24 threads is bound by its own lock queue and Python
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

- **What it does not change.** The requests per post (about 7 on the bot path: Q2) and the ceiling: 23.8 a second with the guard
  of 0.05 s (the owner's D-16, Q18; the measurements and model runs below were made with the 0.1 s that preceded it, 22.7 a second,
  and the S1 expectation was recomputed for 0.05 s). At 7.0 requests and 23.8 a second the floor is 204 posts a minute, so 2,500
  posts take 12.3 minutes at best: booking takes the lane from the lottery to that floor's neighbourhood, not below it. Its
  gains stack with the smaller guard (done) and with not charging the bearer call (a separate class, below in AS-BUILT).
- **The horizon holds about (cap - 1) / 1.05 loops** (1.1 with the former guard; one booking each, fewer while create permits are
  outstanding): 22 at the reviewed 25, so 12 loops fit with room and 24 are at the edge. Below it the lane does not degrade a little. A pass is a run of
  requests, each of which can be refused at the horizon; a pass refused part-way is released, its reads are wasted, and the next
  pass books them again. Posts a minute before / after booking with 12 loops (the thread model on PostgreSQL, one run each, two
  at 14 and 18): cap 8 33 / 12.5, cap 10 54 / 36, cap 12 56 / 83, cap 14 74 / 107, cap 16 71 / 119, cap 18 102 / 137. Booking
  wins from a budget of 12 (a horizon of 10 for 12 loops) and loses below 10; at cap 8 it made 22 requests and 12.7 passes for
  each post that polling made in 12.5 and 5.6. With few loops the same edge: 4 loops at a cap of 4 (horizon 2.7) took 216 s for
  12 posts, polling 60 s; 3 loops at a cap of 4 finished 4 posts in 295 s at 202 requests each; 4 loops at a cap of 5 took 63 s
  against 36 s, at 6 22 s against 24 s, at 8 15.5 s against 18.4 s. The ceiling is exact in all of them (never above the cap at
  the mock, nothing posted twice): the loss is posts, not safety. The reviewed 25 with 12 shards has twice the room. Guards:
  `scripts/discord_rate_policy.py` warns (`lane_booking`) when the budget is under 1.5 a second for each shard (18), M8 shows a
  full horizon, and the lane flag off or a build with `BOOK_AHEAD_SECONDS = 0` returns to polling. Raising the shard count past 12
  needs a cap to match; the shard count stays 12. Not built: a lane that stops booking by itself when its own passes keep being
  refused at the horizon.
- **The evidence behind a create grows older.** The permission reads come first in a pass and each may wait up to a second, so the
  create leaves later [simulated, median age of the reads at the create: 1.3 s to 2.3 s at 12 loops, 2.2 s to 5.7 s at 24; no
  bound in code]. The approval, the lease and the fences are rechecked at the seal as before.
- **One slot of every window is kept for callers that cannot wait** (`IMMEDIATE_RESERVE`): a web request never finds the window
  full of bookings. It costs 1 of 25 at saturation (4 percent). With 5 web reads a second [simulated], 84 percent of them were
  admitted while the lane polled and 99 to 100 percent are with booking (their 90th-percentile latency 0.36 s to 0.55 s). That
  holds for a web rate far below the budget. The independent review measured what the reserve is: a guaranteed minimum, not a
  share. While the lane saturates the window, all web traffic together gets about reserve / 1.05 admissions a second, so four web
  threads asking about 20 times a second were admitted 40 percent of the time at reserve 1, 74 percent at 2 and 88 percent at 4,
  and a call that needs several reads (the destination picker and the verification make 4 to 6) completed 4 to 10 percent of the
  time under heavy demand and 33 percent under light demand at reserve 1 (one 5-read call needs 5 of the 0.9 admissions a
  second). A reserve of 3 costs the lane about 4 percent of its ceiling per slot, and the loops, not the window, bind the lane at
  about 21.8 a second, so 3 would bind at 20.95. The four web calls that make such a series (the channel list, choosing a channel,
  the re-check, the last step of a connection) now book like the lane (`rate_limits.web_reads`; AS-BUILT, "Web calls that read
  several times"): measured with twelve loops, three threads asking back to back completed 25 to 28 percent immediate and 89 booked,
  in about 2.5 s, and the lane paid what they used (creates down 10, reads 11 percent). The price is that a workspace's web reads
  now take a turn in the line instead of only the slack, bounded by G2a's per-workspace read throttle (at most about 40 percent of
  the window for a workspace at the extreme). A reserve of 2 instead would cost 1 a second of the 22.9.
- **What can happen during a wait.** A process that dies leaves the booked read stored `sent` with a wire time ahead: it is never
  sent, keeps its slot for the window plus 30 s (31 s) and then stops counting, at most one per shard (12 of 25 at the very worst).
  A hold, an embargo or an open circuit that begins during a wait of 25 ms or more is found by the read's last look just before it
  is sent (one statement, no lock): the read is closed unsent and the post waits as for a refusal at admission; a booked create's
  permit is stopped by the same look at `consume()` (it was said to be stopped by the existing block of unused permits, which
  `observe()` applies only when some answer is observed: the independent review found a permit consumed after the runbook's hold,
  G2E-B-16, fixed; AS-BUILT "Consume looks too"). What can still leave after an embargo begins is what
  could before: the time between that look (or the commit, for a wait under 25 ms) and the wire. The F429 and B4 tests are unchanged
  and pass.
- **What the application row's `remaining` means now.** It is the room the booked horizon still has, as of the last admission (a
  refusal writes nothing): the cap, less the held, less `IMMEDIATE_RESERVE`, less the permits still to be used (each counts in every
  window, as for a booking), less the other wire times that still hold their slot when the horizon ends, one `BOOK_AHEAD_SECONDS`
  from then. It is 0 exactly when a booking of the whole horizon would be refused; `resetSeconds` is then how long until it would
  not be, and 0.0 while there is room. The first version counted only the wire times up to now, which a saturated lane always
  fills: the first hosted run (S1 of 02fd679b) read `remaining` 0 in 21 of 35 busy health readings with the horizon never full,
  and the alert guidance below would have fired on a lane that was working. Now a lane that fills the budget shows the horizon
  about half full, not empty: its twelve loops hold at most twelve bookings at once of the 24 the horizon takes, so `remaining`
  should read about 11 of 25 [from the count; S2 will show it] and 0 only when callers are being refused. `lane.outlook` is
  unchanged and waits only then. A stored 0 whose `resetSeconds` is 0.0 is old (nothing has been admitted since): nothing is
  pending. Booking time and refusals are in `coordinator.booking` (below). The most a saturated lane sends is (cap - 1) / 1.05 a
  second, 22.9 of 25 (91 percent of the nominal ceiling, 96 of the 23.8 that the guard alone allows); the alert on a spent
  budget (`saturation_warn`, Q18) must divide by that.
- **Fields.** The lane's `bookedWaits` (bookings) and `bookedSeconds` (their total wait) in the invocation result and the
  `discord.lane.completed` line; the health payload's `coordinator.booking`: `bookAheadSeconds`, `aheadNow`, `horizonSeconds`,
  `bookedReads60s`, `bookedReadWaitSeconds60s`, `meanBookedReadWaitSeconds60s`, `maxBookedReadWaitSeconds60s`.
- **Off.** The lane flag (the minute worker never books), or `BOOK_AHEAD_SECONDS = 0` in a build.

**Q20. A missing coordinator is not a pause (the lane side of the ops review's N-1; not built).** The read-back of a created post
now waits when the coordinator cannot admit a request (AS-BUILT, "A read-back waits for the coordinator"): that was the harm, a
created post made `uncertain` and parked for a day by the runbook's second lever. What remains is a question of the lane's own
definition of a pause. `lane.paused()` asks the provider's flags (execution disabled, authorization off) and K1 keeps the lane and
the minute tick from claiming anything while it is true. A build without a usable coordinator is not a pause by that definition:
`OAuthService` (`oauth.py`) attaches the reviewed policy after `runtime_from_environment`, and when it does not parse leaves no
limiter and marks it degraded, while authorization stays on; with no policy set it leaves an inert coordinator whose policy is
None. Only `runtime_from_environment`'s own failure, or rate limits off, turns authorization off. The lane suite's
`unable('no coordinator')` and the earlier table row of AS-BUILT assumed the second; the reviewer's probe found the first. In that
state the lane stops (`coordinator_unavailable`) and the minute tick keeps the frozen path: it claims every Discord post, releases
those not yet created for five minutes (one claim, one release and an attempt each, as the K1 re-review measured for a pause at
one minute: about 280 attempts and 860 events a day per due post at five) and, since N-1, defers the read-back of each created one
(one event per claim, 288 a day). Nothing is lost, nothing is posted, no check is spent. To stop the claims altogether the lane
side would count a missing or policy-less coordinator as a pause: in `lane.paused()`, `provider.rate_v1_enabled and
(limiter is None or limiter.policy is None)`, one expression, with the lane suite's case changed to the state `OAuthService`
leaves (limiter None, degraded, authorization on) and `FlagOffIsTheFrozenBase` unchanged (it pins states that do not pause). An
expired policy would stay a release for five minutes, as documented, unless the owner wants that quiet too. That is W-02's code
(`lane.paused()` and its suite); the N-1 fix does not touch it.

**Q21. The bearer budget: the person's own bearer calls on a window of their own (the owner's D-2 option 1; built, 0658c58b).** The
written budget was "25 requests a second across every credential". Of the 7 requests a post costs, 6 are made with the bot token and
1, the grant check `GET /oauth2/@me`, with the person's own OAuth bearer, which does not touch the bot's global limit. The owner's
reply 16 (AUTHORIZATION-RECORD.md, "I approve all") redefines the budget: bot-token requests at most 25 a second, the person's
bearer calls budgeted separately. Nothing about what is checked changed; only which window the request is charged to.

- **Every call site of a request authorized with a user bearer** (all reach the coordinator through `DiscordProvider._discord_http`
  with `credential_kind='user'`; `tests/test_discord_rate_bearer.py::CallSites` drives the real helpers and checks the row each is
  charged to).
  In the lane's path: (1) the grant check, `GET /oauth2/@me`, once per preflight (`HostedSocial.prepare_discord_dispatch` →
  `OAuthService.discord_grant_for_worker` → `DiscordConnections.installation_identity` → `_fresh_identity`, fast path →
  `verified_authorization`): request 1 of the 7, the only bearer call of an ordinary post. (2) When the person's access token is
  within a minute of its expiry (about once a week per identity) the same step first refreshes it: `POST /oauth2/token` (made with
  the client secret, so not a bearer call: it stays in the application budget) and then, with the new token, `verified_user`:
  `GET /oauth2/@me` and `GET /users/@me`. (3) A reply (engagement) and a webhook send run the grant check again before their
  read-back or verification (`reconcile_discord`, `engagement.py:230`), and the webhook authorizer adds `GET /oauth2/@me` and
  `GET /users/@me/guilds?limit=200` (`webhooks.owner_permissions`): both are dark (flags off, never run against real Discord).
  Outside the lane, interactive only: the callback's token exchange verifies with `/oauth2/@me` and `/users/@me`; the server list
  (`user_guilds`: `/users/@me/guilds`, five pages at most) when an installation starts or the dashboard lists servers; the older
  `DiscordProvider.exchange` (`/users/@me`). Not bearer calls, so not moved: the bot's reads and creates (`bot`), the client secret's
  `/oauth2/token` and `/oauth2/token/revoke` (`oauth`) and a webhook's execute and read (`webhook`, the secret is in the URL).
- **What was built.** `SafetyPolicy` gains `bearer_capacity` and `bearer_window_seconds`, both or neither. Without the pair the policy
  parses as before and the bearer calls stay in the application budget, so the policy in force today is still valid and the way
  back is to issue one (`discord_rate_policy.py generate --no-bearer`). With it, a request of kind `user` is charged to a second row
  (scope key `01:`; its kind is `policy`, so no schema changes and no migration) whose window counts only those admissions, and every
  other credential to the application row (`00:`), whose window then counts those alone. Both are exact sliding windows with the
  same guard (0.05 s), the same booking, the same slot kept for callers that cannot wait, the same published `remaining`/`reset`
  and the same randomized brute-force proof, on each class's own wire times. A bearer request also locks the application row (it
  sorts first) to see its hold and embargo without being charged: the runbook's stop, `UPDATE ... SET manual_hold = true WHERE kind
  = 'policy'`, sets both rows and stops both classes, and a hold on the bearer row alone stops only the bearer calls. One statement
  reads the newest admissions of both classes and the class picks its own from them (a filter inside the scan would read the whole
  history of a class that has been quiet).
- **Why 10 a second.** The lane makes one bearer call for every 6 bot requests of a post, so at the bot's full rate (23.8 stamped a
  second) it needs 4.0 a second of them. The bearer budget has 10: 2.5 times that, with (10 - 1) / 1.05 = 8.6 a second of bookings
  (one slot of the ten stays for a web caller, as for the bot), so twelve loops that all open a step at the same instant wait about
  a second for their grant check once, and the bearer horizon does not fill at the lane's steady 4 a second. A smaller budget saves
  nothing the lane can use (the model gives the same posts a minute from 8 up); a larger one is a raise nobody asked for. We hold
  no figure from Discord for bearer calls; their route limits are learned per user from the headers like every other route, and the
  invalid-request budget (401, 403, 429 outside a shared limit) stays one budget for the whole egress address, whichever class made
  the request. The policy tool
  refuses a bearer budget above 10 a second as a FAIL (a raise is a new review), warns when the two together pass 80 percent of the
  bot limit or when 10 is lowered below what the lane needs, and says what a policy without the pair leaves out. As for the bot, a
  renewal can only tighten the stored row; a deliberate raise is an operator's UPDATE of `limit_count` on the `01:` row.
- **Per post.** 6 requests with the bot token (four reads, the create and the read-back; charged to 25 a second) and 1 with the bearer
  (the grant check; charged to 10): 7.0, and 7.2 with the bot identity pair (S1 measured 7.18).
- **What it changes, in the model of Q19** (12 shards, claim 0.8 s, five seeds; the model is the thread-and-event model fitted to S1).
  Booking with guard 0.05 s and one budget: 179.0 posts a minute, 7.0 requests, 20.9 a second. With the bearer budget: 195.1 posts a
  minute, 7.04 requests (6.04 bot, 1.0 bearer), 22.9 a second in all (19.6 the bot's, 3.3 the bearer's), 7.0 lock statements, 0
  releases. The gain is the grant check no longer waiting for a bookable slot of the bot's window (booked waits 4.5 a post fall to
  3.4), not more bot requests: the bot class stays under its own ceiling. On the S1 shape, with the model's ratio on the measured
  126.5 posts a minute (195.1 / 143.6 = 1.36): 172 posts a minute, median line 14.5 minutes, p95 27.6, longest about 32, against
  the plan's 12 / 25 / 40 (the floor at 6 bot requests and 23.8 a second is 10.5 minutes; with one budget it was 12.3). With the
  56-second lane, 12 percent more loop time: about 13.0 / 24.7 / 29. [model; the capacity run measures it] A model run with a
  bearer budget of 6 gave 219 posts a minute, an artifact of how twelve loops fall into step that I could not explain and do not rely
  on; 8, 10, 15 and 25 give 195 to 197.
- **For the monitors (names).** Health payload: `config.policy.bearerCapacity` and `bearerWindowSeconds` (null without a bearer
  budget); `coordinator.guards.bearer` (present only with a bearer budget) with the fields of `guards.policy` (`present`, `hold`,
  `blocked`, `circuit`, `embargoSeconds`, `remaining`, `limit`, `windowSeconds`, `remainingRatio`, `resetSeconds`,
  `unchangedSeconds`, `policyDaysLeft`); `coordinator.traffic.admissions60s` is now the bot's class alone while a bearer budget
  exists and `coordinator.traffic.bearerAdmissions60s` the bearer's, so `saturation_warn` divides the first by the application
  capacity as before and a second alert divides the second by `bearerCapacity` (the SQL twin, `docs/ops/discord-ops-snapshot.sql`, says the same;
  a real-PostgreSQL test compares them). `remaining` is the room of each horizon, 0 when its class would be refused.
  `monitoring.sql` M3 and M6 give each class.
- **What is not covered.** The webhook mode's own sends (kind `webhook`) stay in the application budget; whether they count toward
  Discord's global limit is Q10. A bearer call that Discord rate limits (429 with scope `user`) embargoes that user's route as any
  route; nothing is added for it. Interactive callers keep their behaviour in both classes (an immediate answer or a refusal with
  the exact wait, one slot of each window kept free for them).

**Q22. Where the round trips under the application row's lock come from, and what cutting them would gain (the independent
review's NEW-1 (c); analysis only, nothing built).** The review measured 21.5 admissions a second at 0 ms of statement latency,
13.2 at 5 ms, about 8 at 10 and about 4 at 20 (`poc/pg_mix.py --rtt-ms`), inferred 12 to 15 serialized round trips per admission,
and noted that the median of G5 rests on an assumed 2 ms. The numbers below were taken on this shared box (load 3 to 6 on 4
cores), so the fixed part is larger than a quiet machine's; the slopes and the shape are what to read.

- **The round trips** (learned route, an ordinary GET; counted with a statement logger on this head). A reservation is 7: three
  before the lock (the timeouts' `set_config`, the route map, the seed of missing rows), the lock statement (`FOR UPDATE` on the
  application, credential, global and route rows) and three under it: `tick` (the clock and the newest wires of the window), the
  store (the changed state rows and the admission, already one statement, `_store_and_insert`) and COMMIT. An ordinary answer's
  observation is 12: five before the lock, the lock statement (`FOR SHARE` on the guards, `FOR UPDATE` on the route rows) and six
  under it: the admission row with the clock, the pending admissions of the alias, the store of the route rows, the mapping with
  the admissions that join the alias, the admission's outcome and COMMIT (7 on a cold route, which adds the pending count). That
  is 19 round trips an admission, 9 of them under a lock; the 10 before it cost the caller latency, not throughput.
- **What the 9 cost** (one client behind a TCP stand-in for the pooler that splits the latency between the two directions; median
  of 40 calls; from the return of the lock statement to the return of COMMIT, in ms):

  | latency, ms | 0 | 2 | 5 | 10 | 20 |
  |---|---|---|---|---|---|
  | a reservation holds the lock | 8.3 | 23.2 | 41.4 | 59.2 | 101.0 |
  | an observation holds it | 8.9 | 32.2 | 56.5 | 84.0 | 148.8 |

  Between 10 and 20 ms each millisecond of latency adds 4.2 to a reservation's hold and 6.5 to an observation's: 3 and 6
  statements, and a COMMIT that costs more than a statement (the log flush and the pooler's wait for the server; not separated).
  An admission therefore holds the lock for 10.8 round trips plus a fixed 17 ms, and 1000 / (17 + 10.8 x latency) gives 26, 14,
  8 and 4 admissions a second at 2, 5, 10 and 20 ms, against the review's 13.2, about 8 and about 4 with 12 to 24 loops. That is the
  review's "12 to 15 round trips": 10.8 plus a fixed part that is large against 5 ms and small against 20. The lane needs 22.9
  admissions a second (Q21), which leaves 43.7 ms for a reservation and its observation: the lock is the limit above about 2.4 ms.
- **What could leave the lock or merge** (a what-if: the harness waives the latency of the statements that would be merged into
  another; 12 booking loops in one process, cap 25, two 12-second rounds each; admissions a second):

  | | round trips | 2 ms | 5 ms | 10 ms |
  |---|---|---|---|---|
  | as built | 10.8 | 20.3, 20.9 | 13.9, 13.4 | 7.8, 7.7 |
  | (a) read the admission row and the alias's pending admissions in one statement | 9.8 | 21.4, 22.0 | 14.9, 14.5 | 8.6, 9.2 |
  | (b) and write the route rows, the mapping and the outcome in one | 7.8 | 22.2, 22.1 | 17.2, 17.0 | 10.4, 10.9 |
  | (c) and send COMMIT in the same flight as the last statement | 5.8 | 22.0, 22.2 | 21.2 (the other round hit a lock timeout) | 13.3, 14.1 |

  The model predicts 14.1, 15.2, 17.9 and 21.7 at 5 ms and 8.0, 8.7, 10.5 and 13.3 at 10: within 5 percent. At 2 ms the window
  itself (about 22 a second) is the limit once the lock is cut, and the lock as built costs 6 to 9 percent of it. Not movable: the
  lock statement, `tick` (the window is read under the lock) and the stores; the seed and the route map are already before the
  lock; a reservation's `tick` and store cannot merge, because Python decides the slot between them. (a) and (b) have a precedent
  in `_store_and_insert`; the difficulty is that the observation's writes are checked one rowcount at a time and the mapping
  statement and the outcome update can reach the same row (a permit that joins the alias in the observation that maps it), so a
  merge needs a CASE per row and a RETURNING list: a rewrite of the statements the reviewers have just read. (c) is valid only if
  the last statement is harmless when its guard fails, and it needs a pooler that pipelines (not tried against Supavisor).
  The lever is the observation's SHARE lock, 6.5 of the 10.8 round trips: without it a section is a reservation's 4.2 and the
  model gives 34 admissions a second at 5 ms and 20 at 10. What a hold, an embargo and the exclusive retry rely on it for is a
  design review of its own.
- **Where the lane stands.** The section may be 43.7 ms for 22.9 admissions a second. As built that allows a latency of 2.4 ms,
  with (a) and (b) 3.4, with (a) to (c) 4.6, without the observation's lock about 8. The earlier PostRiff deployment records name
  Vercel `iad1` (`docs/design/social-trend-intelligence/production-baseline.json`) and Supabase `us-east-1`
  (`docs/postriff-phase-2/hosted-deployment-preparation.md`), the same metro, so 1 to 3 ms through the transaction pooler is
  likely, but nobody has measured it and I could not check how production is placed. At 2 ms the lock and the window are about
  equally tight; above 3 the lane is lock-bound: 14 admissions a second at 5 ms, 2 posts a second, about 119 posts a minute
  against the model's 195.
- **Recommendation: not built.** (a) and (b) gain 24 percent at 5 ms, 7 percent at 2, and rewrite the hottest statements after
  the review has read them. First measure the per-statement latency from a lane function to the pooler (the capacity run's own, or
  five `SELECT 1` and a COMMIT in the health snapshot, p50 and max: about 20 read-only lines in `ops.snapshot`, offered, not
  built). At 2 ms or less leave everything as it is; between 2.4 and 4.6 build (a), then (b); above 5 the observation's lock has to
  go. A slow lock is only a lower rate: the ceiling is a property of the stamps, not of the lock, and since NEW-1 a lock timeout
  is a 1.5-second wait for the caller, not a release of the post for 300 seconds.
- **NEW-1 under the load that exposed it** (24 loops, 20 ms, +100 ms to connect, 12 seconds; the review: 4 of 4 runs ended with
  `rate_coordinator_degraded`, 3 to 358 fast-fail errors, 4.0 to 4.8 admissions a second). On this head: 0 of 2 degraded, 0 and 1
  errors (one lock timeout in a direct `observe` of the harness, which the provider would have asked again), 4.5 and 4.7
  admissions a second, 8 and 12 reservations told to wait 1.5 s. The rate is the same, because the lock sets it; what changed is
  what a timeout means.
