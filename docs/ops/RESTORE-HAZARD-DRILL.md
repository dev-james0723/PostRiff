# Restore hazard drill: a point-in-time restore and Discord posting

Status: **done, local drill** (2026-10-23). Branch `claude/discord-restore-drill-20261023`, on top of the W-02 head
`62f68c56`. Owner reply 14 asked for credible, repeatable evidence on backups, "including the risk of duplicate Discord
posts" after a restore (M-03 section 6). This is that evidence for the duplicate part, measured on throw-away local
PostgreSQL 16 clusters and an in-process mock Discord. **Nothing touched Production, Supabase, Vercel or the real Discord
API; no application file changed.** Every id and text is synthetic. Facts are marked [measured] (this drill), [code]
(read from the repository at this commit) or [inference].

## 1. Answer

1. **The hypothesis holds** [measured]. Restored to a point after the posts were approved and before the first send,
   the same application code (provider, shared request coordinator, worker, W-02 lane loops) pointed at the restored
   database and at the same Discord created a second copy of **43 of the 46** messages customers had already seen
   (24 tenants: 19 got two duplicates, 5 got one). Of the other three, two were held because their one-hour approval
   had ended before the resume and one was held after repeated 429 answers to its reads (the W-02 read-retry limit; inferred from its event and `release_discord_unsent`). At scale: **200 of 200**
   (100 tenants, two duplicates each).
2. **What protected and what did not** [measured + code]. In the restored database every post was `scheduled` with no
   intent, no receipt, no lease and no coordinator admission: all four protections were rewound, so none fired. What
   did fire: **approval expiry** (a post whose approval ended before the resume is held, never sent late) and, for a
   restore point inside the sending run, **intents and receipts committed before that point** (those posts were
   reconciled by read-back and never resent). **Outside the database**, Discord's `enforce_nonce` returns the first
   message instead of creating a second one, but only within "the past few minutes" (Discord's documentation). Modelled
   with a 15-minute window, 43 of the 44 resends returned the first message; the one exception was the post a moderator
   had deleted (scenario A2). A Supabase restore, plus detecting the problem and deciding on it, takes longer than that
   window, so it does not protect a real restore [inference].
3. **The procedure works** [measured]. Hold the restored database first and prove it; nothing is sent under the hold
   (4 lane loops stopped with `operator_hold`, the minute cron claimed nothing, 0 Discord requests); reconcile; lift.
   Result: **0 duplicates**; 43 posts matched to their existing message and verified by the product's own read-back
   without a create; 6 ambiguous posts held for human review; the 5 posts that were not sent before the restore were
   sent exactly once. A second reconciliation wrote nothing. Also 0 duplicates for a restore point in the middle of the
   sending run, for one placed while a worker held a lease, and for 200 posts.
4. **Three things in the current guidance would still let duplicates through** [measured]:
   - The runbook's hold is an `UPDATE` that can match **no row**: the policy row only exists after the coordinator's
     first request, so in a database restored to before it the hold sets nothing, and the first request creates the
     row unheld. Drill: `UPDATE 0`, then 14 duplicates in 6 seconds. The tool's `hold --set` proves the hold, and
     `--create-missing` inserts the row already held (0 sends).
   - **The hold lives in the database**: an in-place restore rewinds it, and a hold set after the database is back
     races the cron. With the hold set 3 seconds after the database was back, five runs gave 14, 4, 3, 10 and 0
     duplicates. Restoring elsewhere and holding before the application can reach it gave 0 in five runs; promoting
     before the restore a build whose rate policy does not parse (a stop that does not live in the database) gave 0 in
     four runs.
   - **Turning the W-02 lane flag off is not a stop** (the minute cron takes Discord back on the frozen path) [code],
     and the **kill switch** or turning rate limits off **hold every due post and mark every destination
     "verification required"** [code; the path the W-02 test
     `test_recovery_after_rate_limits_were_off_keeps_the_frozen_holds` measures], so every customer would have to
     verify and approve again.
5. **What the procedure cannot catch** [measured]: a post the customer **cancelled after the restore point** is
   scheduled again in the restored database with a valid approval; Discord cannot show a cancellation, so the tool
   cannot either, and the post was sent (scenarios A and B). Approvals, edits and disconnections after the restore point
   are lost the same way. A message **deleted by a moderator** cannot be told apart from one never sent: it is held for
   review, never resent, but also never confirmed.
6. **The drill caught a bug in the first version of the tool** [measured]; it is fixed and covered by a regression test
   and by a deterministic drill scenario (section 7).

## 2. What was run

| Item | Value |
|---|---|
| Code | this branch; application code unchanged (nothing under `src/`, `web/` or `migrations/` changed) |
| PostgreSQL | 16.15, local clusters under the session scratchpad, 127.0.0.1 only; started inside a user namespace mapped to the `postgres` uid (PostgreSQL refuses to run as root; the root-only scratchpad stays reachable) |
| Schema | `tests/phase2/rls.sql` and migrations 124, 126, 128, as in the W-02 real-PostgreSQL tests |
| Archiving | `wal_level=replica`, `archive_mode=on`, `archive_command` = copy into a local archive directory, `archive_timeout=2s`, 1 MB WAL segments (16 MB, gzip-compressed, in the timing run) |
| Base backup | `pg_basebackup -X stream -c fast` at T_base, **before any post was approved or sent** |
| Restore | copy of the base backup into a **new** data directory, `restore_command` from the archive, `recovery_target_time`, `recovery_target_timeline='current'`, `recovery_target_action='promote'`, started on another port; the original cluster and the base backup are never written |
| Discord | `RestoreMockDiscord` (`tests/discord_restore_fixture.py`): the W-02 mock plus snowflake ids that encode creation time, channel history (`GET /channels/{id}/messages?limit=50`, `before=`), deletion by a moderator, edits, other authors, and an optional nonce window |
| Application | `DiscordProvider` with the shared PostgreSQL coordinator and a reviewed policy, `HostedSocial`, `PostgresWorker`, `discord.lane.run` with 4 loops (6 in the scale run); billing is the only boundary replaced (as in W-02) |
| Machine | shared 4-core container; load average 10 to 36 during the runs (other agents) |

Commands (each run rebuilds everything from nothing and removes its clusters, base backups and archives at the end):

```
export POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin
nice -n 10 python scripts/discord_restore_drill.py --phases core,midrun,holdrow,liveswap,reconscale --tenants 20 --posts 2 --results <file>
nice -n 10 python scripts/discord_restore_drill.py --phases core,midrun --skip-core-scenarios --results <file>   # + the leased restore point
nice -n 10 python scripts/discord_restore_drill.py --phases timing --results <file>                              # local timing
nice -n 10 python scripts/discord_restore_drill.py --phases core --tenants 100 --posts 2 --loops 6 --no-edges --skip-a2 --results <file>
python scripts/discord_restore_drill.py --summary <file>                                                          # the counts below
python -m unittest tests.test_discord_restore_reconcile
```

Runs quoted here: canonical run at commit `015d6f7a` (after the fix in section 7), the leased restore point at
`073a9212`, timing at `da90c267`, scale at `9aca6dc2`; later commits changed only the drill's cleanup, options and
this record. A full canonical run takes about 11 minutes on this machine.

**The first timeline** [measured, canonical run]: 20 main tenants with 2 approved posts each, due now, plus 13
edge-case tenants (section 4): 55 posts in all. Base backup, then the approvals, then **restore point T_r** (1.5 s
after the last approval commit and 1.5 s before the lane started), then one approval in an existing workspace (after
T_r), then the lane sent everything due: 47 messages in Discord in 40 s. A moderator then deleted one message and
someone edited one; users posted chatter and one user posted the exact text of a Rafii post; one customer cancelled a
queued post with the product's own cancel command. Then the operator hold in the original database (M-03 step 1) at
T_end, the archive was flushed (0 archive failures) and the original cluster stopped. Each scenario restored a fresh
copy to its restore point (0.9 to 2.2 s locally; the log shows `recovery stopping before commit of transaction ...`
at the first transaction after the target) and checked by SQL before any worker ran. At T_r: 54 jobs, all
`scheduled`, none with an intent or a provider reference, 51 with a still-valid approval (the other 3 are the expiring
edge cases), the policy row present and unheld, no publish admission.

## 3. Results per scenario

"Seen" = posts customers saw before the restore (first timeline). "Duplicate" = a second message for a post customers
already saw. Canonical run unless marked.

| Scenario | Posts (seen) | Duplicates | Held | Sent exactly once in total | Verdict |
|---|---|---|---|---|---|
| **A** hazard: restored to T_r, same code and Discord, no precaution | 54 (46) | **43** (24 tenants) | 4 | 10 | hypothesis **confirmed** |
| **A2** as A, Discord dedupes nonces for 15 minutes (a replay inside Discord's window) | 54 (46) | 1 (the moderator-deleted post) | 4 | 51 | nonce protects only a fast replay |
| **B** procedure: verified hold, reconcile, lift | 54 (46) | **0** | 6 | 51 | **PASS** |
| **mid-A** restore point in the middle of the sending run (23 of 47 creates before it), no precaution | 55 (47) | **20** (15 tenants) | 5 | 32 | hazard confirmed for the rewound half |
| **mid-B** same restore point, procedure | 55 (47) | **0** | 2 | 52 | **PASS** |
| **lease-A** restore point between a post's claim and its seal (leased, not sealed), no precaution | 55 (47) | **25**, including the moderator-deleted post | 4 | 28 | hazard confirmed |
| **lease-B** same restore point, procedure (fixed tool) | 55 (47) | **0**; the deleted post held | 4 | 52 | **PASS** |
| **holdrow** restored database with no policy row, runbook `UPDATE` | 54 | **14** in 6 s (`UPDATE 0`) | 0 | n/a | current runbook step **FAILS** |
| **holdrow** same, the tool's `hold --set --create-missing` | 54 | **0** (4 loops stopped `operator_hold`) | 0 | n/a | **PASS** |
| **liveswap in place** (section 5), hold 3 s after the database is back | 12 + 30 trickle | 14, 4, 3, 10, 0 in five runs | | | **FAILS** (race) |
| **liveswap hold first** | 12 + 30 trickle | 0 in five runs | | | **PASS** |
| **liveswap paused build** | 12 + 30 trickle | 0 in four runs | | | **PASS** |
| **scale A**: 100 tenants x 2 posts, main tenants only, 6 loops, no precaution | 200 (200) | **200** (every tenant 2) | 0 | 0 | hazard confirmed |
| **scale B**: same, procedure | 200 (200) | **0** (200 matched and verified by read-back, 0 creates) | 0 | 200 | **PASS** |

Scenario B in detail [measured]:

- Before any worker: `hold --set` reported `updated 1, held true`. Four lane loops stopped with `operator_hold`
  (0 claims), the minute cron (lane flag on) claimed nothing, 0 Discord requests, 0 creates.
- Reconciliation dry-run (counts only): 43 matched, 6 ambiguous, 5 not sent; 66 channels read (32 with unresolved
  jobs, the rest authorized destinations read only to count unclaimed bot messages), 67 Discord reads, 1 unclaimed bot
  message (the post approved after T_r). Apply: the same decisions, 49 jobs written (43 receipts, 6 holds), 177 reads
  (each match is re-read by id just before the write). Second apply: 0 written.
- After the lift: 48 posts verified by the product's read-back (`verification: provider_lookup`); 5 creates (4 later
  posts and the cancelled one), each exactly once; 0 duplicates. The restored coordinator recorded 5 observed publish
  admissions, one per real create, and none for the 43 matched posts.

## 4. Edge cases

| Case | First timeline | A: no precaution | B: procedure | Verdict |
|---|---|---|---|---|
| Message **deleted by a moderator** in the rewound interval | sent, then deleted | resent: the deleted post came back | not in history and due in the interval: **held** (`due_in_interval_not_found`), never resent | PASS (held, as required) |
| First-timeline create **`uncertain`, Discord had accepted it** (answer lost) | message exists, job `uncertain` | resent (duplicate) | matched to the existing message, verified by read-back | PASS |
| First-timeline create **`uncertain`, never reached Discord** | no message, job `uncertain` | sent for the first time (the old timeline's "never resend" was rewound) | due in the interval, not found: **held** | PASS (fail-safe) |
| **Two identical texts** to one channel at different times (one sent, one due after the interval) | 1 message | first resent, second sent: 3 identical messages | both share the one candidate: **both held** (`shared_candidate`) | PASS (ambiguity held) |
| Restore point **in the middle of the sending run** | 23 of 47 creates before it | 20 duplicates; 3 posts with a sealed intent became `uncertain` (`Expired Discord intent requires reconciliation; never repost`): the product's own protection, where it was not rewound | 0 duplicates: 23 matched, 4 sealed ones resolved by their message id, 1 twin held | PASS |
| Restore point **while a worker held a post's lease, before its seal** (run 9, 0.875 s window) | sent, then deleted by a moderator | resent | **held** (the lease holder could have sent it; section 7) | PASS (after the fix) |
| **Approval expired** meanwhile, post was sent | sent | **held** by the product (`needs a current human approval`): not resent, but shown as unposted | matched, verified by read-back: shown as posted | PASS |
| **Approval expired** meanwhile, post never sent (its server refused the bot) | held in the old timeline | held, never sent late | held, never sent late | PASS |
| **Edited** bot message in the window | sent, then edited | resent | partial match: **held** | PASS |
| A user posts the **exact text** of a Rafii post | n/a | n/a | ignored (the author is not the bot); the post matched its own message | PASS |
| Post **cancelled** by the customer after the restore point (product's own cancel command) | cancelled, never sent | **sent** | **sent** (`not_sent`: Discord cannot show a cancellation) | **FAIL by design**: needs the human step |
| Post **approved after** the restore point in an existing workspace | sent | not in the restored database: not resent | not in the restored database; its message is counted as 1 unclaimed bot message for the human review | PASS (counted; the customer must not approve it again) |
| Restore while the **lane flag is on and loops run** | section 5 | | | |

## 5. A restore under running loops (`liveswap`)

[measured] A cron starts a lane invocation every second (the real cron starts 12 shards once a minute), each on a
fresh provider (a cold function instance); 12 posts are due and 30 more trickle in every 3 seconds. Then the database
is replaced at the same address (immediate stop, restore to the restore point, start on the same port), the way an
in-place restore swaps the database under a running application.

| Order | Duplicates in five runs | Notes |
|---|---|---|
| In place, hold 3 s after the database is back | 14, 4, 3, 10, 0 | a race: it depends on what the loops are doing when the database returns |
| Restored elsewhere, held, then given the address | 0, 0, 0, 0, 0 | the application never sees the restored database unheld |
| Paused build promoted before the restore, in place, hold 3 s after, normal build again, reconcile, lift | 0, 0, 0, 0 (four runs) | the paused build's invocations stopped with `coordinator_unavailable`; its minute cron claimed and pushed back 21 due posts without sending (one run); after reconcile and lift, 0 duplicates |

**What loops started before the restore do** [measured + code]. The database factory opens a new connection per
transaction, so a loop's next transaction reaches whatever answers at that address. In one run 6 loops were alive
across the swap and made **9 creates after the database came back: 8 of that run's 10 duplicates** came from
invocations started before the restore. A loop whose transaction hits the downtime ends with `OperationalError`; one
connected while the restored server was still recovering and failed with `ReadOnlySqlTransaction`; the next cron tick
starts a new one. Nothing in the process knows the database changed. A loop's in-flight claimed job is safe: its next
fenced write fails the lease check against the restored row (`owns()`), and a create already past `consume()` is written
into the restored row as a late receipt that the next claim adopts (`Late Discord receipt retained`) [code]. A process
whose coordinator observation failed during the swap marks itself degraded and stops its own loops until it restarts
(`rate_coordinator_degraded`) [code].

## 6. What protection fired, from the product's own records

| Protection | Lives in | Scenario A (restored before any send) | mid-A (restored mid-run) |
|---|---|---|---|
| Dispatch intent (sealed before every POST) | workspace row | rewound: 0 of 54 jobs had one at T_r; 50 new intents, one per resend | fired for the 3 sealed at the restore point (`never repost`) |
| Discord receipt / provider reference | workspace row | rewound | fired: the 20 posts with a reference were verified by read-back, not resent |
| Lease (one live Discord lease per workspace) | workspace row | rewound | leases from the old timeline expired and were recovered as designed |
| Coordinator admissions (each create admitted once) | `pr_discord_request_admissions` | rewound: the restored coordinator admitted every resend again (50 observed publish admissions) | rewound in-flight requests stay "sent, never answered" (W-02 M5) |
| `uncertain` state (never resend) | workspace row | rewound | fired for the 2 uncertain at the restore point |
| Approval expiry (one hour after the scheduled time) | the frozen manifest | **fired**: 2 held, never sent late | fired |
| Operator hold | `pr_discord_rate_state` | rewound (unheld) | rewound |
| Discord `enforce_nonce` (same nonce per approval) | Discord, outside the database | would fire within its window only (A2) | same |

## 7. The reconciliation tool

`scripts/discord_restore_reconcile.py` (stdlib and psycopg). Subcommands: `status`, `hold --set [--create-missing
--application-id ID]`, `hold --lift --confirm`, `reconcile --restore-point T --interval-end T [--dry-run|--apply]
--live`. It reads Discord with GET only, in the product's request shapes: `GET /users/@me` (the bot), `GET
/channels/{id}/messages?limit=50` paged with `before=` back to the restore point (at most `--max-pages`, default 20),
and `GET /channels/{id}/messages/{id}` (the read-back shape the sender uses) to re-check each match just before
writing. It paces itself (`--pace`, default 0.25 s), obeys 429 retry hints and stops after 50 invalid answers. It reads
the channel of every unresolved job and, best effort, every other authorized destination channel (only to count
unclaimed bot messages; an unreadable one never stops the run).

**Rules** (fail-safe: when unsure it holds, never sends). Scope: every Discord job not `verified`/`failed`/`canceled`
with no provider reference and no receipt carrying a message id.

| Evidence for the job | Decision | Write |
|---|---|---|
| Exactly one message in the target channel from the frozen bot (`author.bot`), content SHA-256 equal to the approved text's (the text's wire digest must equal the frozen `wireDigest`), no mentions or attachments, never edited, created at or after T_r minus 5 s, claimed by no other job and owned by no job | `matched` | receipt in `record_receipt`'s shape, `providerReference`, state `uncertain`, the adoption event, `nextAt` now; the product's read-back then sets `verified` |
| The same, for a job with a sealed intent or an in-flight state (the product never resends it) | `resolved` | the same; anything else leaves it untouched |
| Several candidates; a candidate shared by several jobs; a near match (equal after whitespace/case folding, or with mentions/attachments, or any edited bot message in the window); a channel it cannot read; history that does not reach T_r within the page limit; a different bot identity; a media, webhook or reply post; a text that does not match its frozen wire digest | `ambiguous` | state `held`, reason, event, `nextAction` |
| No candidate, and the post could have been sent inside [T_r, interval end] while its approval was valid (from `nextAt`; a lease does not delay it) | `ambiguous` (`due_in_interval_not_found`: maybe deleted) | `held` |
| No candidate, readable complete history, and the post could not have been sent inside the interval | `not_sent` | none: the product sends it once (or holds it if its approval expired) |

Writes happen per workspace under `SELECT ... FOR UPDATE`, skip any job whose decision-relevant fields changed since
the read (a fingerprint), and update with the revision fence the worker uses. `--apply` refuses unless the hold is in
effect.

**These are direct writes to job rows**, and the incident runbook (4.G) says not to edit job rows by hand. Why: there is
no product command that attaches a receipt found outside a worker step, or that holds a job on an operator's decision.
The product's own adoption path (the late-receipt block in `PostgresWorker._claim`) writes exactly these fields
(`providerReference`, state `uncertain`, an event) but runs only inside a worker claim and cannot reach a held job. So
the tool writes those same fields, reviewed and fenced, and leaves `verified` to the product's read-back
(`HostedSocial.reconcile_discord`, `PostgresWorker.complete`), which also restores the side records a verification
writes (learning signal, publish outcome event) that the restore rewound. Considered and not chosen: calling
`PostgresWorker.complete()` with a synthetic claim so that `record_receipt` appends the receipt and the next claim
adopts it. That uses more product code, but it is not atomic with the tool's unchanged-job check, cannot reach a held
job, and leaves the job `scheduled` (so `assert_no_unresolved_repeat` would not yet block a re-approval) until a worker
claims it.

**A bug the drill caught in the first version of the tool** [measured]. In one mid-run restore (run 6), a worker held a
post's lease at the restore point; it sent the post, a moderator then deleted the message, and the lease ran past the
interval end. The first rule took `max(nextAt, leaseUntil)` as the earliest moment the post could have been sent, so
it judged the post "not sent", and after the lift the product posted it again: **1 duplicate**. The lease holder may
send at any moment of its lease; the earliest moment is `nextAt`. Fixed in commit `015d6f7a` with a regression test
(`test_regression_a_post_leased_past_the_interval_end_and_then_deleted_is_held_not_resent`) and a drill scenario that
places the restore point inside that window on purpose (lease-A and lease-B above). The scale run predates the fix but
cannot be affected: its restore point is before any claim, so no job had a lease.

**Failure modes** [inference from the rules, the unit tests and the drill]:

- A wrong `--interval-end` only matters for a deleted message (an existing message is always found). Too early, and a
  post deleted by a moderator but due after the given end is resent. Advice: T_hold + 300 s.
- A false match needs another bot message with the identical text in the same channel after T_r that no job owns:
  for example a post approved after T_r by another workspace connected to the same channel. The job is then marked sent
  and its own post never goes out (a missed post, not a duplicate).
- It reads only channels the restored database knows. Workspaces connected after T_r are invisible to it.
- History beyond `--max-pages` pages, channels it cannot read, and a removed read permission all end in `held`, so a
  busy channel can hold many posts for review.
- Real Discord may differ from the mock in message fields (`type`, `flags`, embeds added to links, trimmed whitespace):
  any difference becomes a near match or no match, so it holds; it cannot become a send.
- A held post does not block a new approval of the same text (`assert_no_unresolved_repeat` ignores held jobs without
  an intent) [code]: the human review must say not to approve it again.
- It must run while the hold is in effect; it refuses `--apply` otherwise. Under the hold the product's own read-back is
  refused too, so verification happens only after the lift.

Tests: `tests/test_discord_restore_reconcile.py`: 40 unit tests (rules, ambiguity, idempotency, the lease regression,
the reader, the command line) and one real-PostgreSQL end-to-end test (base backup, sends, point-in-time restore,
verified hold, reconcile, second reconcile writing nothing, lift, zero duplicates, the revision fence, the missing
policy row). The real-PostgreSQL test skips without `POSTRIFF_PG_BIN`, like the W-02 tests.

## 8. Local timings

**LOCAL figures on this shared 4-core container (load average 15 to 22 from other agents during the runs), local
disk, PostgreSQL 16. They are not Supabase's and do not predict its downtime** [measured].

| Measurement | Value |
|---|---|
| Database padded to | 244 MB (`pg_database_size`; Production is 237 MB per M-03) |
| Base backup (`pg_basebackup -X stream -c fast`) | 2.9 s |
| "A day of WAL" | 720 forced switches of 16 MB segments (M-03: `archive_timeout` 120 s, about 700 segments archived a day), each after 20 workspace-row updates; archive compressed with gzip: 214 MB; LSN span 11.25 GB, most of it the empty tails of forced switches |
| Restore to the last commit (copy the base backup, replay all 720 segments from the archive with `gzip -dc`, promote) | **197 s** wall (copy 1.7 s) |
| Restored database | 301 MB |
| Reconciliation, 1,000 posts in 200 channels, all already in Discord | dry-run 0.27 s (401 reads); apply **17.2 s** (1,401 reads: 1 identity, 400 history pages for 200 job channels and 200 destination-only channels, 1,000 re-reads by id; 1,000 jobs written) |
| Reconciliation against the real Discord API [inference] | dominated by its pacing: at the default 0.25 s per request, about 1,400 reads take **about 6 minutes per 1,000 posts**, plus any 429 waits |

M-03 guessed 10 to 30 minutes of Supabase downtime for a 237 MB restore; nothing here confirms or refutes that guess.
What the local figure shows: replaying a day of mostly idle WAL is per-segment work (720 fetches and decompressions),
not data volume.

## 9. Product observations

1. [measured] The runbook's hold can silently do nothing (`UPDATE 0` when the policy row does not exist yet).
2. [measured] The hold, the intents, the receipts and the coordinator's admissions are all rewound by a restore; only
   approval expiry and Discord's short nonce window are outside it.
3. [measured] Approval expiry turns posts that were really published into `held: needs a current human approval`; a
   customer who approves one again posts it twice. The tool marks them verified instead.
4. [code] Turning the lane flag off is not a stop; the kill switch and rate-limits-off are destructive stops; a rate
   policy that does not parse is a non-destructive stop that does not live in the database (W-02 recovery tests show
   the queue waits and then drains exactly once; drill liveswap paused build).
5. [measured] After a restore point inside a sending run, the restored coordinator keeps the requests that were in
   flight as "sent, never answered" (W-02 monitoring M5); read-backs waited on them ("awaiting shared capacity"), and a
   read-back of the moderator-deleted message (404) opened a circuit on that channel's read route until the policy
   expires (`observe()` sets `circuit_until` to the policy's expiry on a 403 or 404) [code]. Nothing was resent; those
   posts stay `provider_accepted` until an operator reviews the admissions, and there is no reviewed procedure for that
   yet (W-02 OPEN-QUESTIONS Q3).
6. [code] An `uncertain` Discord job without a message id can never be resolved by the product (`reconcile_discord`
   needs `providerReference`); after five checks it is parked for 24 hours. The tool resolves it when it finds exactly
   one message.
7. [measured] A restore revives cancellations made after the restore point (the cancelled post was sent in A and B);
   nothing in the product or in Discord shows them.
8. [code] Discord's nonce (`sha256(idempotencyKey)[:25]`, `enforce_nonce: true`) is per approval, so a replay within
   Discord's window returns the first message, and the product then verifies that message by read-back (A2).
9. [code, not drilled] A restore also rewinds rotated OAuth tokens. A person's Discord refresh token that rotated after
   the restore point is stale in the restored database; the next refresh is refused by Discord and the product then
   requires the person to reconnect (`reconnect_required()` in `discord/oauth.py`, deliberately not retried because a
   rotating token may be spent). The bot token, which posts, is not stored in the database and is not affected.
10. [code, not drilled] A restored database also brings back destinations disconnected and grants revoked after the
    restore point (both live in the workspace row and `pr_encrypted_credentials`); while the bot is still in that
    server, the worker could post to a destination the customer had disconnected. Same class as the cancellation, and
    it needs the same human step.

## 10. What this drill does not prove

- **Supabase's restore mechanics**: whether PITR is enabled at all (M-03 says probably not), how long the project is
  unavailable, whether connections are refused while it restores, whether the application reconnects to the same
  address immediately afterwards, how WAL-G fetches and replays, and whether "restore to a new project" is available on
  this plan. The drill restored with PostgreSQL's own `recovery_target_time` on a local cluster.
- **The real Discord API**: the exact nonce window and what it returns when the first message was deleted (the mock
  creates a new message), history pagination limits and the rate limits of `GET .../messages`, the exact message fields,
  AutoMod, and whether a moderator's deletion leaves any trace the bot can read.
- **Timing**: the local figures are on a shared, loaded 4-core container with local disk; Supabase restores on other
  hardware, fetches WAL over the network and adds platform overhead.
- **Vercel**: the cron cadence (one start per shard per minute, not every second), warm instances that keep a degraded
  coordinator, how quickly a promote reaches every instance, and the paused build itself (modelled by what the product
  does at startup when the policy does not parse, not by a real build).
- **Production data**: synthetic tenants, posts and channels; production's workspaces, approvals, channel activity,
  write volume and the Supavisor pooler were not involved.
- **Customer behaviour in the rewound interval** beyond the cancellation and the late approval drilled here, and the
  refresh-token and disconnection effects in section 9, which are read from the code only.

## 11. Reproduce

The commands in section 2. Results files contain synthetic ids only; they were kept in the session scratchpad and
deleted with the clusters after the drill. The proposed runbook text is in `docs/ops/RESTORE-RUNBOOK-PROPOSAL.md`.
