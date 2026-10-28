# PHONE RUNBOOK: stop, close and roll back Discord with the Mac offline (H-07)

Everything here needs only a phone browser: the **Supabase dashboard SQL editor** (project `postriff-phase2-private`) and the **Vercel dashboard** (team `team_PgXY5VdAYKcsv0RLoDPHscNq`, project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`), or an agent using the same through its connectors. Alert ids (42) come from `scripts/discord_ops_check.py`; severities and thresholds from `docs/ops/discord-alert-thresholds.json`. Rules that never bend: stop first, investigate second; never resend an uncertain post; holds are set and lifted only with the Release Captain's authority; every action is written in the ledger with the time (UTC). Whoever acts tells the owner (James, Release Captain) at once. **This does not make H-07 VERIFIED**: who is on call and how alerts reach them is the owner's (`ALERT-CHANNELS.md`, `H07-EVIDENCE.md`).

Measurements quoted below are from disposable PostgreSQL 16 clusters with the real worker and coordinator and a mock Discord, on the merged head `d864f25f` (W-02 `5fc6cb21`); the probe outputs are in `REVIEW-8E76AFDD-EVIDENCE.md`. They are not Production observations.

## First: which worker owns Discord right now

Read the health payload (`/api/ops/discord/health`, or `SNAPSHOT` below without the process view): `lane.enabled` and `lane.ready`.

- **Lane flag on and ready**: the W-02 lane loops own Discord. Under a hold they stop before claiming anything; created posts keep their read-back budget and verify after the lift (measured).
- **Lane flag off, or on but not ready, or the RC1 build after a rollback**: the minute cron's frozen path owns Discord. Under a hold it still claims: each unsent post is pushed back 5 minutes. A created post awaiting its read-back depends on the build (payload `config.holdReadWaitSeconds`; the hold alert says which): **without the limiter's read wait (null: RC1 and every build before limiter `1fe434c7`) each claim burns one check; at the fifth claim (25 s on the drill clock, where the post comes due again 5 s after each claim; about 5 minutes at the minute cron's one claim a minute) the post is parked for 24 hours as "uncertain, manual provider review"**, although the message is in Discord, and the lift does not bring it back (measured, RC1 file `2a5a523d` included). With the read wait (300) a read under the hold waits 300 s and keeps its check, and the post verifies after the lift (measured on a scratch merge with the limiter: 8 claims under the hold, 0 checks spent, verified after `HOLD_OFF`). A customer's "post now" also claims through this path.

## The levers, fastest first

1. **Database hold** (seconds, no deploy, Release Captain's authority): `HOLD_ON` below, which must return a row. Every new Discord request (posts, read-backs, connects) is refused before it is sent. What it costs, measured:
   - Posts not yet sent are not lost while the hold is short: each claim pushes them back 5 minutes. **But an approval ends 1 hour after the post's own scheduled time, so a post becomes "held" (a person must approve it again) from about 55 minutes after its scheduled time**, counted from when it was due, not from when the hold started: posts already late lapse sooner. The lift does not revive a held post.
   - Created posts awaiting their read-back are parked for 24 hours when a Discord-claiming worker without the limiter's read wait runs during the hold (section above). With the lane owning Discord, or on a build with the read wait, they are not.
   - A permit reserved before the hold can still be used: at most the one step each running loop had in flight. A permit that the hold blocked after sealing is now proven unsent and retried (W-02 `466232ab`, `f525aa17`).
   - The hold lives in the database: a restore rewinds it (section "After any database restore").
   - Works only on a build with `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` (and, for login-token refreshes, commit `29bc8ab2` or later).
2. **Discord-paused build** (minutes; a staged build and a promote, so a Production operation for the owner): the serving SHA staged with `POSTRIFF_DISCORD_RATE_POLICY` set to a value that does not parse. Every process then has no coordinator and refuses Discord requests before sending, whatever the database says. It does not depend on the database, so it survives a restore. **It is not free.** Unsent posts wait (the minute cron pushes each back 5 minutes) and their approvals lapse from about 55 minutes after each post's scheduled time, as under the hold. **A created post awaiting its read-back is marked uncertain at the first claim, burns a check per claim, is parked for 24 hours at the fifth (about 5 minutes at one claim a minute) and stays parked when the normal build returns** (review N-1, measured with the reviewer's probe E5, `REVIEW-8E76AFDD-EVIDENCE.md` section 2). The code fix (a missing or degraded coordinator defers such a read instead of marking the post uncertain) is with the limiter lane and is **open**. Evidence for the rest is the restore lane's drill and W-02's recovery tests (`RESTORE-HAZARD-DRILL.md` on branch `claude/discord-restore-drill-20261023`), not a Vercel build; prepare it in advance as a staged candidate. While it serves, `RATE_POLICY` pages, and `SILENT_HALT_LANE_NOT_READY` with the lane flag on (the alerts cannot tell this deliberate stop from a broken policy); the backlog rules follow. Acknowledge them. It is not what the alerts call "Discord is paused" (execution or authorization off), which only warns.
3. **Close new connections only** (seconds): promote the **dark twin** of the serving SHA (its deployment id is in the release record). Existing connections and queued posts keep working.
4. **Roll back the serving build** (seconds, no rebuild): promote the previous production deployment (below).

**Not stops:** turning the W-02 lane flag off (the minute cron takes Discord back on the frozen path). **Destructive stops:** the kill switch (`POSTRIFF_OAUTH_DISCORD_DISABLED=true`, a build) and turning rate limits off both make the worker hold every due post and mark every destination "verification required", so every customer must verify and approve again. Use them only on the owner's decision.

## Symptom, first action, undo

| Symptom | Alert id (severity) | First action | Undo | Tell |
|---|---|---|---|---|
| Isolation is broken: the Q-05 probe fails, or cross-tenant data was seen | `CROSS_TENANT_PROBE_FAILED` (page), or confirmed exposure | `HOLD_ON`, then close new connections; keep the log lines (actor key only) | captain's word: `HOLD_OFF`, promote the open build | owner now; privacy path, RUNBOOK-INCIDENT 4.H |
| One member refused other workspaces many times, or a refusal on a Discord route | `CROSS_TENANT_PROBING` (warn 10, page 30 in 10 min), `CROSS_TENANT_DISCORD` (warn) | **no hold**: each refusal is the gate working, no data left. Find the actor key in the logs; check the isolation probe; a stale tab or old link is the usual cause | none | owner if it pages; hold only if the probe fails or exposure is confirmed |
| Posts may have reached Discord with no answer; a wrong or unapproved send | `DELIVERY_UNCERTAIN` (page at 3 in 15 min; warn while any is unresolved) | wrong or unapproved send: `HOLD_ON` (or the paused build when the lane does not own Discord); otherwise never resend and reconcile by read-back | `HOLD_OFF` after the cause is known | owner |
| Bot token rejected (401) | `DELIVERY_UNAUTHORIZED`, `RATE_CREDENTIAL_HOLD` (page) | `HOLD_ON` (stops a 401 storm); only the owner resets the token, then a new build | `HOLD_OFF` once the new build answers | owner (only the owner can rotate) |
| Near a Discord IP restriction | `RATE_INVALID_BUDGET` (page below 25%), `RATE_INVALID_REQUESTS` (page) | close new connections; if it keeps falling, `HOLD_ON` | promote the open build after the window resets and the cause is known | owner |
| Discord outage, 5xx, embargo | `DELIVERY_DISCORD_5XX`, `RATE_EMBARGO`, `RATE_ROUTE_CIRCUITS` (warn; embargo over 5 min pages) | nothing destructive: watch discordstatus.com, post the customer notice (RUNBOOK-INCIDENT 5). With the limiter's change a request that failed before any answer (our side or the network) also counts as a 503 here, so no Discord outage on the status page means look at our side; never roll back for this alone. On the limiter head a 403 also opens a route circuit: many at once usually mean the bot lost access to those servers (removed or permissions changed), which is the customers' side | none | owner, for information |
| Rate policy expiring or expired | `RATE_POLICY` (warn under 7 days, page under 1 or invalid) | renew: `scripts/discord_rate_policy.py generate`, owner sets the variable, a build and a promotion | none | owner (an environment change needs the owner's approval) |
| Work is due and nothing is claimed, admitted or created | `SILENT_HALT_NO_PROGRESS`, `SILENT_HALT_NO_CREATE`, `SILENT_HALT_NO_SHARDS`, `SILENT_HALT_LANE_NOT_READY` (page) | if it began after a promotion, roll back the serving build; otherwise read the payload's `lane.blocker` and `config` and fix the named cause | promote again | owner |
| The health payload does not answer, is malformed, or a section fails | `SILENT_HALT_HEALTH_UNANSWERED`, `SILENT_HALT_DATABASE` (page), `SILENT_HALT_SECTION` (warn, page when it persists) | open `https://rafii.io/api/health` and the Supabase and Vercel status pages; run `SNAPSHOT` below; roll back if it followed a promotion | as above | owner |
| Posts late | `BACKLOG_LAG` (warn above 15 min, page above 45; where the lane logs its split, creates late over 5 min warn and over 45 page, read-backs over 60 min warn only) | a declared burst drains in about 23 minutes and one busy workspace can need 40; past 45 treat it as a halt (row above), before approvals start lapsing at about 55. Read-backs a burst defers are not a halt | none | owner if it pages |
| Discord paused on the serving build: the kill switch, rate limits off (which turns authorization off), or a provider setting missing; lanes stop with `discord_paused` | `BACKLOG_LAG`, `SILENT_HALT_NO_PROGRESS`, `SILENT_HALT_NO_CREATE` at warn only, each message starting "Discord is paused"; the cause has its own alert (`CONFIG_KILL_SWITCH`, `CONFIG_FLAGS`, `CONFIG_REVIEWED`) | confirm with the owner that it is intended (the kill switch and rate limits off are destructive stops, the owner's decision); otherwise promote the recorded open build | promote the open build | owner |
| One workspace set aside after the claim could not read its document | `SILENT_HALT_QUARANTINE` (warn; the error class only) | nothing to stop: that workspace waits 300 s and is claimed again, every other one runs. If the same class keeps coming back, tell the W-02 lane with the class and the time; never edit the job by hand | none | W-02 lane, owner for information |
| Coordinator housekeeping behind | `RATE_RETENTION_BEHIND` (warn: settled rows older than three retention periods, many past retention, or a purge denied, timed out or failed) | nothing customer-facing; read `coordinator.retention` and the `discord.lane.retention` lines, tell the limiter lane. No manual delete on Production | none | limiter lane, owner for information |
| Approvals lapsing or posts failing | `DELIVERY_HELD_GROWTH`, `DELIVERY_FAILED_GROWTH` (warn) | read which posts became held or failed (founder notices); a lapse means re-approval by each customer | none | owner |
| A build without the open settings is serving | `CONFIG_GATE`, `CONFIG_CAP`, `CONFIG_REVIEWED`, `CONFIG_FLAGS` (page) | promote the recorded open build again; find which lane built the other | promote back | owner, and the lane that built it |
| Server cap filling | `CONFIG_CAP_USED` (warn 80%, page 90%) | compare with the Developer Portal count (RUNBOOK-LAUNCH 6) | none | owner decides the next cap |
| A hold is on | `SILENT_HALT_OPERATOR_HOLD` (warn) | ask the captain whether it should still be on: approvals lapse; read-backs wait on a build with the limiter's read wait (payload `config.holdReadWaitSeconds` is a number) and, off the lane, park on an older one (the alert says which) | `HOLD_OFF` on the captain's word | captain |

## The statements (paste into the Supabase SQL editor; each is one block)

```sql
-- H07:HOLD_ON  stop every Discord request (application-wide policy row); it must return a row
UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy' RETURNING kind, manual_hold;
```

**Zero rows returned means there is no hold.** The policy row is created by the coordinator's first request, so a database that never admitted one (or was restored to before it) has none, and the next request creates it unheld. Run `HOLD_INSERT` at once, then `HOLD_READBACK`.

```sql
-- H07:HOLD_OFF  resume, only on the Release Captain's word; it must return a row
UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE kind = 'policy' RETURNING kind, manual_hold;
```

```sql
-- H07:HOLD_READBACK  run after either statement, and again two minutes later
SELECT count(*) AS policy_rows,
       count(*) FILTER (WHERE manual_hold) AS held,
       (SELECT round(extract(epoch FROM now() - reserved_at)) FROM public.pr_discord_request_admissions
         ORDER BY request_seq DESC LIMIT 1) AS seconds_since_last_request
FROM public.pr_discord_rate_state WHERE kind = 'policy';
```

Healthy: `policy_rows 1, held 0`, and `seconds_since_last_request` small while posts are going out. Held: `policy_rows 1, held 1`, and `seconds_since_last_request` keeps growing (a step already in flight may finish; nothing new starts). `policy_rows 0`: no hold is possible by `UPDATE`; use `HOLD_INSERT`. **`policy_rows 2` with `held 1` two minutes after a `HOLD_INSERT`: the typed application id was wrong**, the coordinator created its own row unheld and posts are going out: run `HOLD_ON` (it holds every policy row) and read back again.

```sql
-- H07:HOLD_INSERT  only when HOLD_ON returned no row; replace the id between the quotes
INSERT INTO public.pr_discord_rate_state(scope_key, kind, limit_count, remaining, window_seconds, reset_at,
                                         manual_hold, policy_revision, policy_expires_at)
VALUES ('00:' || encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex'), 'policy', 1, 0, 1, now(),
        true, 'operator-hold', now())
ON CONFLICT (scope_key) DO UPDATE SET manual_hold = true;
```

```sql
-- H07:HOLD_KEYCHECK  after HOLD_INSERT: does the typed application id name the coordinator's own row? same id as above
SELECT count(*) FILTER (WHERE scope_key = '00:' || encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex')) AS typed_key_rows,
       count(*) AS policy_rows,
       (SELECT application_key = encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex')
          FROM public.pr_discord_request_admissions ORDER BY request_seq DESC LIMIT 1) AS latest_request_on_typed_key
FROM public.pr_discord_rate_state WHERE kind = 'policy';
```

The id is proven when `typed_key_rows = policy_rows = 1` and `latest_request_on_typed_key` is true (the coordinator's newest request used the same application key; one index read). Empty (no request ever admitted on this database): the proof is `policy_rows` still 1 two minutes after the cron ran. False, or `policy_rows 2`: the id is wrong; find it in the Developer Portal (General Information; it is public) and repeat.

```sql
-- H07:DRAIN_CHECK  before switching to an older worker. Complete, not sampled: due-work projection and admissions index
WITH due AS MATERIALIZED (
    SELECT w.state FROM public.pr_discord_worker_projection p
    JOIN public.pr_workspaces w ON w.id = p.workspace_id
    WHERE p.next_at IS NOT NULL
), jobs AS MATERIALIZED (
    SELECT j FROM due d
    CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(d.state #> '{phase2,jobs}') = 'array'
                                                 THEN d.state #> '{phase2,jobs}' ELSE '[]'::jsonb END) j
    WHERE j #>> '{manifest,platform}' = 'Discord'
), admissions AS MATERIALIZED (
    SELECT (SELECT count(*) FROM public.pr_discord_request_admissions
             WHERE state IN ('reserved', 'sealed') AND expires_at > clock_timestamp() AND is_publish)
         + (SELECT count(*) FROM public.pr_discord_request_admissions
             WHERE state = 'sent' AND is_publish AND sent_at > clock_timestamp() - interval '120 seconds') AS in_flight,
           (SELECT count(*) FROM public.pr_discord_request_admissions
             WHERE state = 'sent' AND is_publish AND sent_at <= clock_timestamp() - interval '120 seconds') AS stuck_sent,
           (SELECT count(*) FROM public.pr_discord_request_admissions WHERE state = 'uncertain' AND is_publish) AS uncertain
)
SELECT (SELECT count(*) FROM jobs WHERE j ->> 'leaseOwner' IS NOT NULL
          AND public.pr_discord_queue_number(j -> 'leaseUntil') > extract(epoch FROM clock_timestamp())) AS live_leases,
       a.in_flight AS publishes_in_flight,
       (SELECT count(*) FROM jobs WHERE j #>> '{discordWorker,stage}' = 'sealed') AS sealed_now,
       (SELECT count(*) FROM jobs WHERE j ->> 'state' = 'uncertain') AS uncertain_to_reconcile,
       a.stuck_sent AS stuck_sent_admissions,
       a.uncertain AS uncertain_admissions,
       (SELECT count(*) FROM jobs WHERE coalesce(j ->> 'state', '') NOT IN ('verified', 'failed', 'canceled', 'held')) AS non_terminal_jobs
FROM admissions a;
```

Counts only. It reads the state of the workspaces the due-work projection lists (those with Discord work not finished) and the admissions through their unresolved-state index, so it is complete at any number of workspaces. **Switch only at `live_leases 0` and `publishes_in_flight 0`.** `sealed_now`, `uncertain_to_reconcile` and the two admission counts are posts to reconcile by read-back, never to resend: the older worker never recreates a sealed or accepted post (W-02 rollback tests). `non_terminal_jobs` must be 0 for the `dpl_47SGx…` target only. A workspace whose Discord job has an unreadable `nextAt` or `leaseUntil` is left out of the projection, and out of this count; the W-02 lane does not claim it either.

`SNAPSHOT`: `docs/ops/discord-ops-snapshot.sql` is the whole health picture as one row of JSON (read-only, counts only), for when the protected route cannot be called from a phone (a browser cannot add its header).

## Roll back the serving build (no rebuild)

- **Phone:** Vercel dashboard, project, **Deployments**; open the deployment to return to (the release record names it: the previous production deployment, or for a code defect in Discord v2 `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`); menu (three dots), **Promote** (for a staged twin) or **Instant Rollback** (for a previous production deployment); confirm. Then open `https://rafii.io/api/health` and check `sourceRevision`; with the cron secret, `/api/ops/discord/health` shows `build.deploymentId`.
- **Agent or any logged-in machine:** `vercel promote <deployment url or id> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`, or `vercel rollback <deployment id> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`, or the Vercel connector's promote and rollback actions (the REST endpoints behind them are the project promote and rollback calls; confirm the exact path in the Vercel documentation before scripting it).
- Each promotion is a Production change that needs the owner's approval, except the abort steps the owner pre-authorised (AUTH-7: hold and dark-twin promotion). Promoting never rebuilds; environment changes reach only new builds.

## Before rolling back to an older worker: the order

0. **Before step 1, get the Release Captain's authority for both `HOLD_ON` and `HOLD_OFF`**: the lift in step 4 must follow the alias read-back without waiting for a second call, because the older worker claims Discord and, having no read wait, under the hold parks every created post's read-back for 24 hours, and approvals run out.
1. `HOLD_ON` (it must return a row; otherwise `HOLD_INSERT`, `HOLD_KEYCHECK`), then `HOLD_READBACK` (held 1).
2. Wait two minutes (a lease lasts 45 s; a step in flight finishes), then `DRAIN_CHECK`: **`live_leases 0` and `publishes_in_flight 0`** before switching.
3. Promote the older build; read back the alias (`sourceRevision`, `build.deploymentId`).
4. **At once** `HOLD_OFF` (it must return a row) and `HOLD_READBACK` (held 0); watch `BACKLOG_LAG` and `SILENT_HALT_NO_PROGRESS` clear and `DELIVERY_UNCERTAIN` stay where `DRAIN_CHECK` left it.

Alternative for steps 1 and 4, when it was staged in advance and the database cannot be trusted (a restore): the Discord-paused build (lever 2) instead of the database hold. It is a promote of its own, so the order becomes paused build, `DRAIN_CHECK`, older build, and it does not spare read-backs: while it serves, created posts awaiting their read-back are parked at the fifth claim (review N-1; the limiter lane's fix is open).

**The `dpl_47SGx…` target (no Discord v2 code) needs `non_terminal_jobs 0`, and the hold of step 1 stops jobs from finishing.** Decide before step 1, with the owner:
- **(a) Drain with the hold off** (posts are kept): stay on the current build without a hold and stop new Discord work at the source (close new connections with the dark twin; customers stop scheduling new Discord posts), run `DRAIN_CHECK` until `non_terminal_jobs 0`, then steps 1 to 4. It takes as long as the queue: hours if posts are scheduled ahead.
- **(b) Cancel the remaining Discord jobs** (fast; those posts are lost and each customer must be told): an owner decision and a customer notice; there is no reviewed bulk-cancel statement in this runbook, and job rows are never edited by hand (RUNBOOK-INCIDENT 4.G).
- Otherwise roll back to a v2 build (the previous production deployment) instead, which needs neither.

## After any database restore

A restore rewinds the database, and the duplicate protection (intents, leases, coordinator admissions) and **the hold itself** live in it: posts sent after the restore point look unsent and are sent again while their approvals last, and a hold set before the restore is gone. The restore lane's drill measured both (`RESTORE-HAZARD-DRILL.md`, branch `claude/discord-restore-drill-20261023`) and wrote a procedure, `RESTORE-RUNBOOK-PROPOSAL.md` section 4.J, **a proposal that is not in force** until the owner adopts it. Three points from it that this runbook already follows: a hold must prove itself (`HOLD_ON` returns a row, then `HOLD_READBACK`); the Discord-paused build (lever 2) is the stop that does not live in the database, so it is the one that survives an in-place restore (it still parks created posts awaiting their read-back, see lever 2); the kill switch and rate limits off are not the stop to use. Its reconciliation tool is not reviewed and writes job rows; no step here relies on it. The order this runbook supports without it: before the restore, the paused build and `HOLD_ON`; after it, before anything else runs, `HOLD_ON` again (or `HOLD_INSERT`, `HOLD_KEYCHECK`), reconcile every Discord post of the rewound interval against the destination channels by hand, then the normal build, then `HOLD_OFF` on the captain's word.

## Not covered

No 24/7 cover exists until the owner names it (`H07-EVIDENCE.md`). Not drilled on Production: the SQL editor from a phone, a real promotion or rollback, the paused build on Vercel, the Vercel log pipeline, real alert delivery (`DRILL-RECEIPT-ISOLATED.md` says what the isolated drills prove). The hold does nothing on a build with rate limits off; closing connections by promoting the dark twin assumes a build-level gate wins over a project variable, which is unproven (`DURABLE-OPEN-CONFIG-PROPOSAL.md` 3.3). A loop that stops between sealing a post and sending it leaves that post "uncertain" with no message id (W-02's own control test); only a person can reconcile it. The token reset, the policy renewal and the kill switch need the owner and a build. Rollback targets older than Vercel's deployment retention may no longer exist: check the target is listed before relying on it. Message deletion in Discord is the owner's decision only.
