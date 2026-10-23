# OWNER DECISIONS PENDING (living document; none of them blocks today's engineering)

Kept by the Release Captain. Written 2026-10-23 about 07:30Z, after owner reply 15. Nothing here is a request for approval of a Production operation (those are in `APPROVAL-PACKET-3-DRAFT.md`, not yet submitted). These are choices only the owner can make. Each says what I would choose, the strongest argument against it, the biggest risk, what would change my mind, and whether it can be undone. The release state is **NO-GO** until gates G1 to G7 all have evidence.

Labels: [Certain] measured or read exactly; [Likely] strong inference; [Guessing] needs a fact I do not have.

## D-1. Customer Discord sender names at the opening (the scope of owner reply 15, part A)

- **Fact [Certain].** Launch decision 2 (made by me under the owner's delegation) keeps the webhook route OFF for the opening: bot route only, the two webhook flags unset. A per-send webhook sender name therefore ships dark. The only customer-reachable part of the feature at the opening is the **bot nickname**, which Discord stores once per server. The independent review found it not ready (another workspace in the same server, or any admin, can overwrite it; approvals do not freeze it). The sender-name agents are building per-server authority (a single installation, the observed nickname frozen into the approval and checked at dispatch, an audit reason) behind its own switch, default off.
- **I would choose:** keep the webhook route off; turn the bot nickname on only if the per-server authority passes its own independent review; otherwise report the feature as built, reviewed and dark, and say plainly that customers cannot set a sender name at the opening.
- **Strongest argument against:** customers will ask for names on day one and you asked for the feature in RC2. Opening the webhook route would give per-send names with no shared-nickname problem.
- **Biggest risk of my choice:** the feature you asked for is not usable at launch.
- **Risk of the alternative:** the webhook mode has never run against real Discord, needs its own qualification flag and its own tester session, and whether a webhook-only install counts toward Discord's 100-server rule is undocumented (`W-03-webhook-server-limit.md`). It adds a second mode to the opening.
- **What would change my mind:** the tester session shows webhook mode works end to end and the 100-server question is answered; or most customers turn out unable to add a bot.
- **Reversible:** yes, by flags, but only on a new build.
- **Needed by:** before the RC2 freeze (it changes what is frozen).

## D-2. Capacity (gate G5): how far to go if the equivalent changes are not enough

- **Fact [Certain / Likely].** On a GitHub-hosted runner the lane misses your standard as built (5,000 posts due in one minute: median 17.19 / p95 36.79 / maximum 40.73 minutes against 12 / 25 / 40). The independent review's model says that the changes that keep every check as it is (the lane works the whole minute, exact sliding ceiling charged once, a longer create-permit life, queue position kept on a system release) reach a median of about 11.3 to 11.6 minutes: a pass with a margin of 3 to 6% [Likely], not with room to spare. **Correction after the 1023d runs (10:05Z):** on that 4-vCPU runner the lane saturates at 16 to 19 requests a second whatever the duty cycle, the loop budget or the policy (100 a second gives the same), and the same code gave a median of 17.19 minutes in one run and 13.79 in another. So the runner cannot show whether the standard holds at 25 a second, and the reviewer's thin margin is a model, not a measurement. The answer has to come from a larger machine (the planned Depot run) after the correctness defects are fixed (leaked admissions, stuck route, permit expiry, trailing seconds above 25).
- **I would choose:** fix the correctness defects and build the equivalent package first, then measure on a larger machine (Depot, which needs your approval of its cost). Ask you about the options below only if the measured median margin there is under 15%.
- **If asked, the options ranked by how much they change what the system checks:** (1) charge the person's own `GET /oauth2/@me` to a separate bearer budget while the bot stays at 25 a second (median about 9.5; redefines the written "all credentials" budget); (2) raise the ceiling to 30 with the exact window and a wire margin (median about 9.4; the bot would average about 25 to 26 a second, about half of Discord's 50; your reply 13 says any raise needs a re-review); (3) drop the bot's own membership read (median about 9.5; weakens a pre-check); (4) up to 3 posts per claim (median about 5.7; a protocol change). TTL caches: not recommended.
- **Strongest argument against waiting:** every re-measure costs hours and a thin margin may fail again on Vercel and Supabase, which the sandbox does not reproduce (the round trip and the Micro compute).
- **Biggest risk of waiting:** the Depot run happens late and fails on a thin margin.
- **What would change my mind:** a measured packing under 0.9 after the rewrite, or a measured Vercel to Supabase round trip above 4 ms (the coordinator lock alone then caps below 25 a second).
- **Reversible:** each option is a code or configuration change on a new build.
- **Needed by:** only when the measured margin is known.

## D-3. What the normal-load promise is

- **Fact [Certain].** The draft "250 posts due a minute across all customers, 95% within 2 minutes" (my own draft, not yet adopted by you) fails in measurement: S0-250 gives 27.3 / 59.0 / 95.5% within 2 / 5 / 15 minutes; S0-100 passes. The lane sustains about 146 a minute today and, by the reviewer's model, about 205 at best.
- **I would choose:** adopt 100 posts a minute as the promised normal load now, keep 250 as a measured capacity figure, and revisit after the package is measured.
- **Strongest argument against:** it lowers a promise. **Answer:** it was a draft derived from a wrong premise (six requests, a fully usable ceiling); your accepted standard, the 5,000-post spike, is not touched.
- **Biggest risk:** none for safety; it only sets customer expectations.
- **Reversible:** yes. **Needed by:** before any customer-facing copy.

## D-4. What a workspace may queue, and the wording of the large-tenant scenario (S2)

- **Fact [Certain].** A workspace with 3,000 approved Discord posts has a 15.7 MB state document; each whole-document transaction takes about 3 s, so the lane could not send even one of its posts (0 of 3,000 in 50 minutes; they were held at approval expiry, none lost, none duplicated). 300 posts would still move about one post per 3 to 5 seconds. One Discord channel allows only 5 creates per 5 s, so 3,000 posts to one channel need at least 50 minutes at any ceiling.
- **I would choose:** (a) accept the whole-document design for RC2 and document the limit; (b) a per-workspace ceiling on queued posts or state size, so one tenant cannot grow its document without bound (a number to be set from the 100 / 300 / 1,000 measurements); (c) the S2 wording below.
- **S2 wording proposed by the capacity agent (a question; the standard is not changed):** small workspaces (at most 5 posts) all sent within 15 minutes while the large workspace has due posts (unchanged); lost = 0 for every post (a post is lost if it never reaches a terminal state, is created twice, or ends uncertain without a create attempt); held at approval expiry is reported, not failed, but only within the physical bound of one create per second per channel; a new measure: the large workspace's create rate while it has due posts must be at least 80% of one per second per channel it posts to (zero sends fails); lateness lines apply to the small workspaces only.
- **Strongest argument against:** the hot tenant is still a customer. **Answer:** a post held at expiry is shown as "approve again", never lost; the real fix (a different state design) is not an RC2 change.
- **Biggest risk:** a large customer at launch sees most of a big queue held. **What would change my mind:** the measurements show the break at a number real customers reach.
- **Needed by:** before the freeze (the ceiling is code).

## D-5. Production settings that change what existing customers get (WB-1, SC-1)

- **WB-1.** Two project variables set on 2026-10-23 (`POSTRIFF_WORKER_MAX_JOBS=25`, `POSTRIFF_WORKER_MAX_SECONDS=40`) reach every provider's minute worker on any new build. **I would remove both before the RC2 build** (back to 10 jobs, 20 s) [Likely]: with the lane on, the minute tick excludes Discord, so they help no Discord post. Strongest argument against: faster bursts for other providers. Risk of keeping: unmeasured extra database and function load. Reversible: yes.
- **SC-1.** The candidate carries non-Discord changes from the same line. I would ship the security, crash and accessibility fixes (dependency bumps, billing storage crash fix, composer dictation fix, wording) and **strip or consciously accept** "Save as draft" (`manual_draft_create`, about 170 lines, a new feature every editor sees, found uncapped by the isolation review), the review-without-entitlement change, the schedule-dialog rework, and two wording changes (list in `docs/RC2-SHARED-PATH-FIXES.md` on the fixes branch). Strongest argument against stripping: they are already in the line the staged build was made from and were tested. Needed by: the freeze.

## D-6. H-07 on-call (your reply 15, part B): the staffing reality

- **Fact [Certain].** No one is on call today, no notification has ever been delivered to a person, and the formal policy (P0 handled 24/7 by a named Primary and Backup, phone after 5 minutes unacknowledged, Backup after 10) cannot be marked VERIFIED without real people and a real end-to-end test. The independent review of the ops tooling found its break-glass runbook and alert rules unsafe as written; fixes are in progress.
- **I would choose:** keep H-07 **BLOCKED** until the staffing exists. If real 24/7 cover is not possible, the executable alternatives (from the alerts agent's `H07-OPTIONS`, when delivered) are: open only inside an attended window with a low initial server cap raised in steps as monitoring stays clean; automatic protective actions only for narrow, well-understood P0 classes (the hold has side effects, so it is not set automatically); a paid on-call service; or wait.
- **Strongest argument against waiting:** you may not be able to staff 24/7 at launch. **Biggest risk of opening without cover:** an overnight incident (a ban, a duplicate storm, a lockout) runs for hours.
- **What I need from you for H-07:** Primary and Backup names, e-mail addresses, mobile numbers, which phones receive push, and a phone channel; real tests send real notifications to real people and are Production operations that need your explicit approval.

## D-7. A lower initial server cap (a staged opening)

- **Fact.** Reply 12 asked for no allowlist and a cap of 10,000. The early reviews found classes of failure whose cost grows with the number of connected customers (a Cloudflare incident revoking every identity it touches; one tenant degrading the shared window).
- **I would choose:** keep "open to all", but start with a lower cap (for example a few hundred servers) and raise it in steps while monitoring stays clean. This needs no code. Strongest argument against: customers beyond the cap meet "capacity reached" on day one. Biggest risk of not doing it: a launch-day defect hits everyone at once. Reversible: yes (a build variable).

## D-8. Supabase: backups and the restore procedure (M-03)

- **Need from you:** one sentence from Supabase, Database, Backups: what the Point in Time tab says and what Scheduled backups lists. With point-in-time recovery very probably off, a restore means the last daily backup, a rewind of up to a day.
- **Fact [Certain, local drill].** Without a verified hold a restore re-created 43 of the 46 posts customers had already seen (200 of 200 at scale); with the proposed procedure (verified hold, reconcile, lift) it re-created none. The procedure and its reconciliation tool (which writes job rows) are proposals, not reviewed, not adopted.
- **I would choose:** adopt the procedure only after an independent review of the tool; prepare a Discord-paused staged build (a Production build, so a Packet 3 row); decide whether to buy point-in-time recovery (a compute upgrade and a price you must confirm).

## D-9. Capacity on the real database

- **Fact.** Every capacity receipt uses a throw-away PostgreSQL on the test machine at 2 ms. Production runs on the smallest Supabase compute behind Supavisor with TLS; the lock benchmark shows the coordinator lock turns into a ceiling at about 4 ms.
- **I would propose** one run against the existing `rafii-consumer-staging` Supabase project (same region as production) with synthetic data in a throw-away schema, or a Supabase branch (a new cost). It needs you to put one connection secret into a GitHub Environment (I cannot) and to confirm that project's compute class matches production's. The Depot run (paid) should come after it.

## D-10. Things I need only at the end

- Public and private test channel ids and a time slot for the tester session (G3); two throw-away accounts A and B and short-lived sign-in codes, asked last, with minimal steps (G4 hosted); the approvals listed in Packet 3 (the Production builds, promotions, variables, real messages); the decision on the paid Depot run and its cost ceiling.
