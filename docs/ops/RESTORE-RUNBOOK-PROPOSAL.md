# Proposed text for the restore section of the Discord incident runbook

**Status: proposal only.** It is not in force and does not edit `docs/launch-20261023-discord/RUNBOOK-INCIDENT.md`.
It is meant to become a new section 4.J there (and to replace the restore sentence in 4.H) once the owner adopts it.
Evidence: `docs/ops/RESTORE-HAZARD-DRILL.md` (a local drill on throw-away PostgreSQL clusters and a mock Discord; it does
not prove Supabase's restore mechanics or the real Discord API). Nothing here authorises a restore, a build, a promote,
an environment change or a Production database write; each still needs the owner's own approval.

---

### 4.J Database restore (point in time or daily backup)

**Why a restore needs its own procedure.** A restore rewinds the database. A Discord post sent after the restore point
looks unsent again, and while its approval is valid the worker creates it a second time: the duplicate protection
(dispatch intents, leases, the request coordinator's admissions) lives in the database and is rewound with it. In the
drill, the same code against a database restored to just before the first send created a second copy of 44 of the 46
messages customers had already seen; only posts whose approval had expired by then were held instead. The operator
hold (step 2) lives in the database too: a restore rewinds it, and a hold set after the restored database is back races
the cron (drill: 14 duplicates in the 3 seconds before the hold). Discord's own nonce de-duplication only covers "the past
few minutes", far shorter than a restore.

**Who.** The owner decides on a restore and presses Restore. The agent never restores. The Release Captain runs the
steps below, keeps the evidence (counts, states and ids only, section 3) and lifts holds only on the owner's word.

**Before the restore**

1. **Hold the current database, and prove it.** Run step 2 with `RETURNING`:
   `UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy' RETURNING scope_key;`
   It must return at least one row. **Zero rows means there is no hold**: the policy row is created by the coordinator's
   first request, so a database that never admitted one (or was restored to before it) has none, and the next request
   creates it unheld (drill: `UPDATE 0`, then 45 duplicates). Use the tool, which proves the result and can insert the row
   already held:
   `scripts/discord_restore_reconcile.py hold --set --create-missing --application-id <Discord application id> --dsn-env <VAR>`
   It must print `"held": true`. (If the current database cannot be reached, skip this step and note why.)
2. **Write down the interval end.** Right after the hold, `SELECT clock_timestamp();` is T_hold (UTC). The loops stop
   within one step after a hold, so the interval end for reconciliation is T_hold + 300 seconds (the function's maximum
   duration) unless the logs show every lane invocation ended with `stoppedBy: operator_hold`. If the hold could not be
   set, the interval end is the time the database stopped accepting writes, or the time of step 3 + 300 seconds.
3. **Promote the Discord-paused build and wait 5 minutes.** A stop that does not live in the database is needed across
   an in-place restore. Prepare it in advance as a staged candidate (`vercel deploy --prod --skip-domain`, same SHA as
   Production) whose `POSTRIFF_DISCORD_RATE_POLICY` is a value that does not parse (for example `paused-for-restore`):
   every process then has no request coordinator and refuses every Discord request before it is sent, whatever the
   database says. Due posts wait (the minute cron pushes each one back five minutes); nothing is held, failed or asked
   to be verified again (W-02 tests `test_recovery_after_the_coordinator_was_missing_drains_exactly_once`; drill
   `liveswap.paused_build`). Wait 5 minutes after the promote so no invocation of the normal build is still running.
   - Do **not** use the kill switch (step 3 of the ladder) or turn `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` off for
     this: both make the worker hold every due post and mark every destination "verification required", so every
     customer must verify and approve again.
   - Turning the W-02 lane flag off is **not** a stop: the minute cron then takes Discord back on the frozen path.
4. **Write down the restore point** T_r (UTC): the PITR target, or the time of the daily backup chosen.
5. *(If the current database is readable.)* Keep a private export (not in the repository) of the Discord jobs changed
   after T_r: workspace id, job id, state, provider reference. It helps the human review in step 9.

**The restore**

6. The owner restores. Prefer "restore to a new project" when it is available and approved: the application keeps the
   old database until it is switched, so steps 7 to 9 can be done before any worker can reach the restored data. For an
   in-place restore, the paused build of step 3 is what keeps the cron from sending while the database comes back.

**After the restore, before anything is lifted**

7. **Hold the restored database, and prove it** (as step 1, against the restored database; the hold of step 1 was
   rewound). It must print `"held": true`.
8. **Reconcile** (read-only against Discord; it writes only job rows of the restored database, under each workspace's
   row lock and revision fence, and refuses to write unless the hold is in effect):
   - `scripts/discord_restore_reconcile.py reconcile --live --dsn-env <VAR> --restore-point <T_r> --interval-end <step 2> --dry-run`
     prints counts only.
   - The same with `--apply --detail <private file>` (ids only, no text; keep it out of the repository).
   - The same with `--apply` again: it must report `"written": 0` (idempotent).
   What it decides, per Discord job the worker could still send or has not resolved:
   - **matched** (exactly one message in the destination channel from the bot of the frozen target, with exactly the
     approved text, no mentions or attachments, never edited, created after the restore point, claimed by no other job):
     the receipt is recorded and the job goes to `uncertain` with that message id. After the lift the product verifies it
     by reading that message back (`verified`, `provider_lookup`). It is never created again.
   - **ambiguous** (several candidates, a candidate two jobs share, a near match or an edited bot message, a channel it
     cannot read or whose history it cannot read back to the restore point, a changed bot identity, a media, webhook or
     reply post, or a post that was due inside the rewound interval and is not in the channel, which may be a message a
     moderator deleted): the job is `held` for human review. Never sent automatically.
   - **not sent** (complete channel history since the restore point shows no such message, and the post could not have
     been sent inside the interval): left as it is; the product sends it once if its approval is still valid and holds
     it if not.
   - Jobs with a sealed intent are never resent by the product; the tool only attaches their message id when it finds
     exactly one.
9. **Human review** (Release Captain with the owner):
   - Every held post: look at the channel. A post that is not there and should be posted needs the customer to approve
     it again; a post a moderator deleted stays held. Until a person has looked, nobody approves the same text again.
   - "Unclaimed bot messages" (counted by the tool) are posts approved after T_r: their approvals were lost with the
     restore. Tell those customers the post is already published and not to approve it again; the product cannot see the
     earlier copy and would post it twice.
   - Approvals, cancellations, edits and disconnections made after T_r are lost. A post a customer cancelled in that
     interval is scheduled again with a valid approval, and a destination disconnected in Rafii is authorised again;
     Discord cannot show either, so the tool cannot. Ask customers who acted after T_r to check their queue before the
     lift, or keep the hold until they have (owner's decision).
   - `docs/w02/monitoring.sql` M5: requests that were in flight at T_r stay "sent, never answered" in the restored
     database and keep their slots; a channel whose first request was in flight waits for review. There is no reviewed
     release procedure yet (W-02 OPEN-QUESTIONS Q3): record the count, do not edit those rows.
10. **Promote the normal build** again (valid policy). The database hold still stops every Discord request; check that
    each shard answers `stoppedBy: operator_hold`.
11. **Lift the hold only on the Release Captain's word:**
    `scripts/discord_restore_reconcile.py hold --lift --confirm --dsn-env <VAR>`.
    Watch for 15 minutes: matched jobs move from `uncertain` to `verified` without a new message; not-sent posts go out
    once; held posts stay held; no duplicate (monitoring Q1 and Q5, W-02 M1 to M7).
12. Ledger entry: T_r, T_hold, the restore's start and end, the tool's counts (dry-run, apply, second apply), the held
    count and its review, and the M5 count.

**Rules that do not change.** Never resend a delivery whose outcome is uncertain. "Do not edit job rows by hand" (4.G)
still holds: the reconciliation tool is the one reviewed exception, used only after a restore, only under a proven hold,
and only with the Release Captain present.

---

Replace the last sentence of 4.H with: "If a database restore is considered it is the owner's decision with the PITR
facts from M-03; restoring loses everything after the restore point, including credentials, OAuth state, approvals,
cancellations and the operator hold. Follow 4.J."
