# Restore hazard drill: a point-in-time restore and Discord posting

Status: **done, local drill** (2026-10-23). Branch `claude/discord-restore-drill-20261023`, on top of the W-02 head
`62f68c56`. Owner reply 14 asked for credible, repeatable evidence on backups, "including the risk of duplicate Discord
posts" after a restore (M-03 section 6). This is that evidence for the duplicate part, measured on throw-away local
PostgreSQL 16 clusters and an in-process mock Discord. **Nothing touched Production, Supabase, Vercel or the real Discord
API.** Every id and text is synthetic. Facts are marked [measured] (this drill), [code] (read from the repository at
this commit) or [inference].

## 1. Answer

1. **The hypothesis holds** [measured]. Restored to a point after the posts were approved and before the first send,
   the same application code (provider, shared request coordinator, worker, W-02 lane loops) pointed at the restored
   database and at the same Discord created a second copy of **44 of the 46** messages customers had already seen
   (24 of 24 affected tenants; 20 tenants got two duplicates each, 4 got one). The two that were not resent were held
   because their one-hour approval had ended before the resume.
2. **What protected and what did not** [measured + code]. In the restored database every post was `scheduled` with no
   intent, no receipt, no lease and no coordinator admission: all four protections were rewound, so none fired. What
   did fire: **approval expiry** (posts whose approval ended before the resume are held, never sent late), and, in a
   restore point inside the sending run, **intents and receipts committed before that point** (those posts were
   reconciled by read-back and never resent). **Outside the database**, Discord's `enforce_nonce` would return the
   first message instead of creating a second one, but only within "the past few minutes" (Discord's documentation);
   modelled with a 15-minute window, 43 of 44 duplicates disappeared (scenario A2). A Supabase restore takes longer than
   that window, so this does not protect a real restore [inference].
3. **The procedure works** [measured]. Hold the restored database first and prove it; nothing is sent under the hold
   (4 lane loops stopped with `operator_hold`, the minute cron claimed nothing, 0 Discord requests); reconcile; lift.
   Result: **0 duplicates**; 43 posts matched to their existing message and verified by the product's own read-back
   without a create; 6 ambiguous posts held for human review; the 5 posts that could not have been sent before the
   restore were sent exactly once. A second reconciliation wrote nothing.
4. **Three things in the current guidance would still let duplicates through** [measured]:
   - The runbook's hold is an `UPDATE` that can match **no row**: the policy row only exists after the coordinator's
     first request, so in a database restored to before it the hold sets nothing, and the first request creates the
     row unheld. Drill: `UPDATE 0`, then 14 duplicates in 6 seconds. The tool's `hold --set` proves the hold and
     `--create-missing` inserts the row already held (0 sends).
   - **The hold lives in the database**: an in-place restore rewinds it, and a hold set after the database is back
     races the cron. Drill: 3 duplicates in the 3 seconds before the hold, all from lane invocations started after the
     database came back. Restoring elsewhere and holding before the application can reach it gave 0; promoting a build
     whose rate policy does not parse before the restore (a stop outside the database) gave 0.
   - **Turning the W-02 lane flag off is not a stop** (the minute cron takes Discord back on the frozen path) [code],
     and the **kill switch** or turning rate limits off **hold every due post and mark every destination "verification
     required"** [code; the same path the W-02 test `test_recovery_after_rate_limits_were_off_keeps_the_frozen_holds`
     measures], so every customer would have to verify and approve again.
5. **What the procedure cannot catch** [measured]: a post the customer **cancelled after the restore point** is
   scheduled again in the restored database with a valid approval; Discord cannot show a cancellation, so the tool
   cannot either, and the post was sent (scenarios A and B). Approvals, edits and disconnections after the restore point
   are lost the same way. A message **deleted by a moderator** cannot be told apart from one never sent: it is held for
   review, never resent, but also never confirmed.

## 2. What was run

| Item | Value |
|---|---|
| Code | this branch; application code unchanged (no file under `src/`, `web/` or `migrations/` changed) |
| PostgreSQL | 16.15, local clusters under the session scratchpad, 127.0.0.1 only; started inside a user namespace mapped to the `postgres` uid (PostgreSQL refuses to run as root; the root-only scratchpad stays reachable) |
| Schema | `tests/phase2/rls.sql` and migrations 124, 126, 128, as in the W-02 real-PostgreSQL tests |
| Archiving | `wal_level=replica`, `archive_mode=on`, `archive_command` = copy into a local archive directory, `archive_timeout=2s`, 1 MB WAL segments (16 MB, compressed, in the timing run) |
| Base backup | `pg_basebackup -X stream -c fast` at T_base, **before any post was approved or sent** |
| Restore | copy of the base backup into a **new** data directory, `restore_command` from the archive, `recovery_target_time`, `recovery_target_timeline='current'`, `recovery_target_action='promote'`, started on another port; the original cluster and the base backup are never written |
| Discord | `RestoreMockDiscord` (`tests/discord_restore_fixture.py`): the W-02 mock plus snowflake ids that encode creation time, channel history (`GET /channels/{id}/messages?limit=50`, `before=`), deletion by a moderator, edits, other authors, and an optional nonce window |
| Application | `DiscordProvider` with the shared PostgreSQL coordinator and a reviewed policy, `HostedSocial`, `PostgresWorker`, `discord.lane.run` with 4 loops (8 in the scale run); billing is the only boundary replaced (as in W-02) |
| Machine | shared 4-core container; load average 10 to 17 during the runs (other agents) |

Commands (each run rebuilds everything from nothing and removes its clusters at the end):

```
POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin nice -n 10 python scripts/discord_restore_drill.py \
    --phases core,midrun,holdrow,liveswap,reconscale --tenants 20 --posts 2 --results <file>
nice -n 10 python scripts/discord_restore_drill.py --phases timing --results <file>         # local timing
nice -n 10 python scripts/discord_restore_drill.py --phases core --tenants 150 --posts 2 --loops 8 --results <file>
python scripts/discord_restore_drill.py --summary <file>                                     # the counts below
POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin python -m unittest tests.test_discord_restore_reconcile
```

**The first timeline** [measured, canonical run]: 20 main tenants with 2 approved posts each, due now, plus 13
edge-case tenants (section 4); 55 posts in all. Base backup, then the approvals, then **restore point T_r** (1.5 s
after the last approval commit, 1.5 s before the lane started), then the lane sent everything due: 47 messages in
Discord. A moderator then deleted one message and someone edited one; users posted chatter and one user posted the
exact text of a Rafii post. Then the operator hold in the original database (M-03 step 1) at T_end, the archive was
flushed, and the original cluster stopped. Each scenario restored a fresh copy to T_r (about 1.5 s locally; the log
shows `recovery stopping before commit of transaction ...` at the first send's transaction) and checked by SQL before
any worker ran: 54 jobs, all `scheduled`, none with an intent or a provider reference, 51 with a still-valid approval
(the other 3 are the expiring edge cases), the policy row present and unheld, no publish admission.

## 3. Results per scenario

"Seen" = posts customers saw before the restore (first timeline). "Duplicate" = a second message for a post customers
already saw. "First sends" = posts never sent before. Counts from the canonical run unless marked.

| Scenario | Posts (seen) | Duplicates | Held | Sent exactly once in total | Verdict |
|---|---|---|---|---|---|
| **A** hazard: restored to T_r, same code and Discord, no precaution | 54 (46) | **44** (24 tenants) | 3 | 9 | hypothesis **confirmed** |
| **A2** as A, Discord dedupes nonces within 15 minutes (a replay inside Discord's window) | 54 (46) | 1 (the moderator-deleted post) | 4 | 51 | nonce protects only a fast replay |
| **B** procedure: verified hold, reconcile, lift | 54 (46) | **0** | 6 | 51 | **PASS** |
| **mid-A** restore point in the middle of the sending run (23 of 47 creates before it), no precaution | 55 (47) | **19** | 4 | 33 | hazard confirmed for the rewound half |
| **mid-B** same restore point, procedure | 55 (47) | **0** | 2 | 52 | **PASS** |
| **holdrow** restored database with no policy row, runbook `UPDATE` | 54 | **14** in 6 s (`UPDATE 0`) | 0 | n/a | current runbook step **FAILS** |
| **holdrow** same, the tool's `hold --set --create-missing` | 54 | **0** (lanes stopped `operator_hold`) | 0 | n/a | **PASS** |
| **liveswap in place**: database replaced at the same address under the running cron, hold 3 s after it is back | 12 + 30 trickle | see section 5 | | | **FAILS** (race) |
| **liveswap hold first**: restored elsewhere, held, then given the address | | 0 | | | **PASS** |
| **liveswap paused build**: build whose rate policy does not parse promoted before the restore, hold 3 s after | | 0 | | | **PASS** |
| **scale A**: 100 tenants x 2 posts, main tenants only, 6 loops, no precaution | 200 (200) | **200** (every tenant 2) | 0 | 0 | hazard confirmed at scale |
| **scale B**: same, procedure | 200 (200) | **0** (200 matched, verified by read-back, 0 creates) | 0 | 200 | **PASS** |

Scenario B in detail [measured]:

- Before any worker: `hold --set` reported `updated 1, held true`. Four lane loops stopped with `operator_hold`
  (0 claims), the minute cron (lane flag on) claimed nothing, 0 Discord requests, 0 creates.
- Reconciliation dry-run (counts only): 43 matched, 6 ambiguous, 5 not sent, 33 Discord reads. Apply: the same
  decisions, 49 jobs written (43 receipts, 6 holds), 109 reads (the matched messages are read again by id just before
  the write). Second apply: 0 written (idempotent).
- After the lift: 48 verified by the product's read-back (`verification: provider_lookup`), 5 creates (4 later posts
  and the cancelled one, each exactly once), 0 duplicates. The coordinator recorded 5 publish admissions in the restored
  database, one per real create, and none for the 43 matched posts.

## 4. Edge cases (canonical run)

| Case | First timeline | A: no precaution | B: procedure | Verdict |
|---|---|---|---|---|
| Message **deleted by a moderator** in the rewound interval | sent, then deleted | resent: the deleted post came back | not in history and due in the interval: **held** (`due_in_interval_not_found`), never resent | PASS (held, as required) |
| First-timeline create **`uncertain`, Discord had accepted it** (answer lost) | message exists, job `uncertain` | resent (duplicate) | matched to the existing message, verified by read-back | PASS |
| First-timeline create **`uncertain`, never reached Discord** | no message, job `uncertain` | sent for the first time (the old timeline's "never resend" was rewound) | due in the interval, not found: **held** | PASS (fail-safe) |
| **Two identical texts** to one channel at different times (one sent, one due after the interval) | 1 message | first resent, second sent: 3 identical messages | both share the one candidate: **both held** (`shared_candidate`) | PASS (ambiguity held) |
| Restore point **in the middle of the sending run** | 23 of 47 creates before it | 19 duplicates; 2 posts with a sealed intent became `uncertain` (`Expired Discord intent requires reconciliation; never repost`): the product's protection fired where it was not rewound | 0 duplicates: 21 matched, 3 sealed ones resolved by message id, 1 twin held | PASS |
| **Approval expired** meanwhile, post was sent | sent | **held** by the product (`needs a current human approval`): not resent, but shown as unposted | matched, verified by read-back: shown as posted | PASS |
| **Approval expired** meanwhile, post never sent (its server refused the bot) | held in the old timeline | held, never sent late | held (`due_in_interval_not_found`), never sent late | PASS |
| **Edited** bot message in the window | sent, then edited | resent | partial match: **held** | PASS |
| User posts the **exact text** of a Rafii post | n/a | n/a | ignored (author is not the bot): the post still matched its own message | PASS |
| Post **cancelled** by the customer after the restore point (product's own cancel command) | cancelled, never sent | **sent** | **sent** (`not_sent`: Discord cannot show a cancellation) | **FAIL by design**: needs the human step |
| Post **approved after** the restore point, existing workspace | sent | not in the restored database: not resent | not in the restored database: its message is counted as an unclaimed bot message for the human review | PASS (counted; customers must not approve it again) |
| Restore while the **lane flag is on and loops run** | see section 5 | | | |

## 5. A restore under running loops (`liveswap`)

[measured] The cron starts a lane invocation every second (the real cron starts 12 shards once a minute), each on a
fresh provider (a cold function instance); 12 posts are due and 30 more trickle in every 3 seconds. Then the database
is replaced at the same address (stop, restore to T_r, start on the same port), the way an in-place restore swaps
the database under a running application.

- **What loops started before the restore do** [measured + code]. The database connection factory opens a new
  connection per transaction, so a loop's next transaction reaches whatever answers at that address. A loop that is
  mid-transaction when the old database goes away ends with an `OperationalError` (the invocation fails; the next cron
  tick starts a new one). A loop that is sleeping across the swap (idle or rate wait) wakes up against the restored
  database and carries on claiming: nothing in the process knows the database changed. Its in-flight claimed job is
  safe: the next fenced write fails the lease check in the restored row (`owns()`), and a create already past
  `consume()` is recorded in the restored row as a late receipt, which the next claim adopts (`Late Discord receipt
  retained`) [code]. A process whose coordinator observation failed during the swap marks itself degraded and stops its
  own loops until it restarts (`rate_coordinator_degraded`) [code].
- **Counts**: see the liveswap table in the results (section 3); every duplicate in the in-place order came from lane
  invocations started after the database was back, before the hold.

## 6. What protection fired, from the product's own records

| Protection | Lives in | Scenario A (restored before any send) | mid-A (restored mid-run) |
|---|---|---|---|
| Dispatch intent (sealed before every POST) | workspace row | rewound: 0 of 54 jobs had one | fired for the 2 sealed at the restore point (`never repost`) |
| Discord receipt / provider reference | workspace row | rewound | fired: 21 posts with a reference were verified by read-back, not resent |
| Lease (one live Discord lease per workspace) | workspace row | rewound (no live lease) | expired leases recovered as designed |
| Coordinator admissions (each create admitted once) | `pr_discord_request_admissions` | rewound: 51 new publish admissions in the restored database | rewound in-flight requests stay "sent, never answered" (W-02 M5) |
| `uncertain` state (never resend) | workspace row | rewound | fired for the 2 uncertain at the restore point |
| Approval expiry (one hour after the scheduled time) | the frozen manifest | **fired**: 3 held, never sent late | fired |
| Operator hold | `pr_discord_rate_state` | rewound (unheld) | rewound |
| Discord `enforce_nonce` (same nonce per approval) | Discord, outside the database | would fire within its window only (A2) | same |

## 7. The reconciliation tool

`scripts/discord_restore_reconcile.py` (stdlib and psycopg). Subcommands: `status`, `hold --set [--create-missing
--application-id ID]`, `hold --lift --confirm`, `reconcile --restore-point T --interval-end T [--dry-run|--apply]
--live`. Reads Discord with GET only, in the product's request shapes: `GET /users/@me` (the bot), `GET
/channels/{id}/messages?limit=50` paged with `before=` back to the restore point (at most `--max-pages`, default 20),
and `GET /channels/{id}/messages/{id}` (the read-back shape the sender uses) to re-check each match just before
writing. Self-paced (`--pace`, default 0.25 s), obeys 429 retry hints, stops after 50 invalid answers. It reads the
channel of every unresolved job and, best effort, every other authorized destination channel (to count unclaimed bot
messages).

**Rules** (fail-safe: when unsure it holds, never sends). Scope: every Discord job not `verified`/`failed`/`canceled`
with no provider reference and no receipt carrying a message id.

| Evidence for the job | Decision | Write |
|---|---|---|
| Exactly one message in the target channel from the frozen bot (`author.bot`), content SHA-256 equal to the approved text's (the text's wire digest must equal the frozen `wireDigest`), no mentions or attachments, never edited, created at or after T_r minus 5 s, claimed by no other job and owned by no job | `matched` | receipt in `record_receipt`'s shape, `providerReference`, state `uncertain`, the adoption event, `nextAt` now; the product's read-back then sets `verified` |
| The same, for a job with a sealed intent (the product never resends it) | `resolved` | the same; anything else leaves it untouched |
| Several candidates; a candidate shared by several jobs; a near match (equal after whitespace/case folding, or with mentions/attachments, or any edited bot message in the window); a channel it cannot read; history that does not reach T_r within the page limit; a different bot identity; a media, webhook or reply post; a text that does not match its frozen wire digest | `ambiguous` | state `held`, reason, event, `nextAction` |
| No candidate, and the post could have been sent inside [T_r, interval end] while its approval was valid | `ambiguous` (`due_in_interval_not_found`: maybe deleted) | `held` |
| No candidate, readable complete history, and the post could not have been sent inside the interval | `not_sent` | none: the product sends it once (or holds it if its approval expired) |

Writes happen per workspace under `SELECT ... FOR UPDATE`, skip any job whose decision-relevant fields changed since
the read (fingerprint), and update with the revision fence the worker uses. `--apply` refuses unless the hold is in
effect. **These are direct writes to job rows** (runbook 4.G says not to edit job rows by hand): there is no product
command that attaches a receipt found outside a worker step or that holds a job on an operator's decision. The product's
own adoption path (the late-receipt block in `PostgresWorker._claim`) writes exactly these fields
(`providerReference`, state `uncertain`, an event) but runs only inside a worker claim and cannot reach a held job. So
the tool writes those same fields, reviewed and fenced, and leaves `verified` to the product's read-back
(`HostedSocial.reconcile_discord`, `PostgresWorker.complete`), which also restores the side records a verification
writes (learning signal, publish outcome event) that the restore rewound. Considered and not chosen: calling
`PostgresWorker.complete()` with a synthetic claim so that `record_receipt` appends the receipt and the next claim adopts
it. That uses more product code, but it is not atomic with the tool's unchanged-job check, cannot reach a held job, and
leaves the job `scheduled` (so `assert_no_unresolved_repeat` would not yet block a re-approval) until a worker claims it.

**A bug the drill caught in the first version of the tool** [measured]. In one mid-run restore (run 6), a worker held a
post's lease at the restore point; it sent the post, a moderator then deleted the message, and the lease ran past the
interval end. The first rule took `max(nextAt, leaseUntil)` as the earliest moment the post could have been sent, so
it judged the post "not sent", and after the lift the product posted it again: **1 duplicate**. The lease holder may
send at any moment of its lease; the earliest moment is `nextAt`. Fixed in commit `015d6f7a` with a regression test
(`test_regression_a_post_leased_past_the_interval_end_and_then_deleted_is_held_not_resent`); the canonical counts in
this record are from the run after the fix. The scale run predates the fix but cannot be affected: its restore point is
before any claim, so no job had a lease.

**Failure modes** [inference from the rules, the unit tests and the drill]:

- A wrong `--interval-end` only matters for a deleted message (an existing message is always found). Too early, and a
  post deleted by a moderator but due after the given end is resent. Default advice: T_hold + 300 s.
- A false match needs another bot message with the identical text in the same channel after T_r that no job owns: for
  example a post approved after T_r by another workspace connected to the same channel. The job is then marked sent and
  its own post never goes out (a missed post, not a duplicate).
- It reads only channels the restored database knows. Workspaces connected after T_r are invisible to it.
- History beyond `--max-pages` pages, channels it cannot read, and the bot's own read permission removed all end in
  `held`, so a busy channel can hold many posts for review.
- Real Discord may differ from the mock in message fields (`type`, `flags`, embeds added to links, trimmed whitespace):
  any difference becomes a near match or no match, so it holds; it cannot become a send.
- A held post does not block a new approval of the same text (`assert_no_unresolved_repeat` ignores held jobs without
  an intent) [code]: the human review must say not to approve it again.
- The tool must run while the hold is in effect; it refuses `--apply` otherwise. Under the hold, the product's own
  read-back is refused too, so verification happens only after the lift.

Unit tests: `tests/test_discord_restore_reconcile.py` (39 rules, idempotency, reader and command-line tests, plus one
real-PostgreSQL end-to-end test of base backup, sends, point-in-time restore, verified hold, reconcile, second
reconcile writing nothing, lift, zero duplicates, the revision fence, and the missing policy row; it skips without
`POSTRIFF_PG_BIN`).

## 8. Local timings

**LOCAL figures on this shared 4-core container (load average 15 to 17 from other agents during the run), local disk,
PostgreSQL 16. They are not Supabase's and do not predict its downtime** [measured].

| Measurement | Value |
|---|---|
| Database padded to | 244 MB (`pg_database_size`; Production is 237 MB per M-03) |
| Base backup (`pg_basebackup -X stream -c fast`) | 2.9 s |
| "A day of WAL" | 720 forced switches of 16 MB segments (M-03: `archive_timeout` 120 s, about 700 segments archived a day), each after 20 workspace-row updates; archive compressed with gzip: 214 MB; LSN span 11.25 GB, most of it the empty tails of forced switches |
| Restore to the last commit (copy base backup, replay all 720 segments from the archive with `gzip -dc`, promote) | **197 s** wall (copy 1.7 s) |
| Restored database | 301 MB |
| Reconciliation, 1,000 posts in 200 channels, all already in Discord | dry-run 0.44 s (201 reads); apply **10.7 s** (1,201 reads: 1 identity, 200 history pages, 1,000 re-reads by id; 1,000 jobs written) |
| Reconciliation against the real Discord API [inference] | dominated by its pacing: at the default 0.25 s per request, about 1,200 reads take **about 5 minutes per 1,000 posts**, plus any 429 waits; one extra history page per destination channel without a pending post |

M-03 guessed 10 to 30 minutes of Supabase downtime for a 237 MB restore; nothing here confirms or refutes that guess.
What the local figure does show: replaying a day of mostly idle WAL is per-segment work (720 fetches and
decompressions), not data volume.

## 9. Product observations

1. [measured] The runbook's hold can silently do nothing (`UPDATE 0` when the policy row does not exist yet).
2. [measured] The hold, the intents, the receipts and the coordinator's admissions are all rewound by a restore; only
   approval expiry and Discord's short nonce window are outside it.
3. [measured] Approval expiry turns posts that were really published into `held: needs a current human approval`; a
   customer who approves one again posts it twice. The tool marks them verified instead.
4. [code] Turning the lane flag off is not a stop; the kill switch and rate-limits-off are destructive stops; a rate
   policy that does not parse is a non-destructive stop that does not live in the database (W-02 recovery tests show
   the queue waits and then drains exactly once).
5. [measured] After a restore point inside a sending run, the restored coordinator keeps the requests that were in
   flight as "sent, never answered" (W-02 monitoring M5); two read-backs waited on them ("awaiting shared capacity")
   and one read-back of a deleted message opened a circuit on that channel's read route until the policy expires
   (`observe()` sets `circuit_until` to the policy's expiry on a 404) [code]. Nothing was resent; those posts stay
   `provider_accepted` until an operator reviews the admissions, and there is no reviewed procedure for that yet (W-02
   OPEN-QUESTIONS Q3).
6. [code] An `uncertain` Discord job without a message id can never be resolved by the product (`reconcile_discord`
   needs `providerReference`); after five checks it is parked for 24 hours. The tool resolves it when it finds exactly
   one message.
7. [measured] A restore revives cancellations, edits and disconnections made after the restore point; nothing in the
   product or in Discord shows them.
8. [code] Discord's nonce (`sha256(idempotencyKey)[:25]`, `enforce_nonce: true`) is per approval, so a replay within
   Discord's window returns the first message, and the product then verifies that message by read-back (A2).
9. [code, not drilled] A restore also rewinds rotated OAuth tokens. A person's Discord refresh token that rotated after
   the restore point is stale in the restored database; the next refresh is refused by Discord and the product then
   requires the person to reconnect (`reconnect_required()` in `discord/oauth.py`, deliberately not retried because a
   rotating token may be spent). The bot token, which posts, is not stored in the database and is not affected.
10. [code] A restored database also brings back disconnected destinations and revoked grants as of the restore point
    (both live in the workspace row and `pr_encrypted_credentials`); while the bot is still in that server, the worker
    could post to a destination the customer had disconnected after the restore point. This is the same class as the
    cancellation in section 4 and needs the same human step.

## 10. What this drill does not prove

- **Supabase's restore mechanics**: whether PITR is enabled at all (M-03 says probably not), how long the project is
  unavailable, whether connections are refused while it restores, whether the application reconnects to the same
  address immediately after, how WAL-G fetches and replays, and whether "restore to a new project" is available on this
  plan. The drill restored with PostgreSQL's own `recovery_target_time`.
- **The real Discord API**: the exact nonce window and what it returns when the first message was deleted (the mock
  creates a new message), history pagination limits and the rate limits of `GET .../messages`, the exact message
  fields, AutoMod, and whether moderators' deletions leave any trace the bot can read.
- **Timing**: the local figures are on a shared, loaded 4-core container with local disk; Supabase's restore runs on
  other hardware, fetches WAL over the network and adds platform overhead.
- **Vercel**: the cron cadence (one start per shard per minute, not every second), warm instances that keep a degraded
  coordinator, how quickly a promote reaches every instance, and the paused build itself (modelled here by what the
  product does at startup when the policy does not parse, not by a real build).
- **Production data**: synthetic tenants, posts and channels; production's real workspaces, approvals, channel
  activity, write volume and the Supavisor pooler were not involved.
- **Customer behaviour in the rewound interval** beyond the cancellation and the late approval drilled here.

## 11. Reproduce

The commands in section 2. The results JSON contains synthetic ids only; it is kept in the session scratchpad, not in
the repository. Each run deletes its clusters, base backups and archives at the end.
