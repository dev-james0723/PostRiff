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
reviewer. Dependency: the coordinator rewrite on another branch changes how such rows are released, so the "no reviewed
procedure" wording above will change with it; this branch does not touch that rule (its own change covers only a
permit an embargo or hold blocked before it was used, never an admission that was sent).

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
policy (`scripts/discord_rate_policy.py`) and the owner's capacity run.

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

