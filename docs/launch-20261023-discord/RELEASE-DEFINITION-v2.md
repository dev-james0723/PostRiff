# RELEASE DEFINITION v2: open to every new customer, no allowlist

Written 2026-10-23 about 03:10Z after the owner's message (`AUTHORIZATION-RECORD.md`, reply 12). It replaces the "controlled acceptance on D1" framing. **Release status: NO-GO.** Nothing is promoted, `rafii.io` still serves the old build, and the full opening is not scheduled until every gate below has evidence.

## 1. The deliverable and what counts as done

The owner's standard, in the owner's words: a **new customer needs no manual allowlisting and can connect and use the Discord features of this release by themselves**. A dark build, an invitation, a tester allowlist, a green CI run, a READY build or deployed code do **not** count. If something blocks it, fix what can be fixed, then list the remaining problems; do not substitute a dark build for the goal.

Dark builds and tester sessions remain as **verification steps** on the way, never as the delivery.

## 2. Gates before the full opening (each needs evidence in the ledger)

| Gate | Evidence | Who | State |
|---|---|---|---|
| G1 Final release SHA frozen, exact-SHA CI green on every workflow | `RC-RECEIPT.md` | agent | RC1 `2a5a523d` done; the final SHA is RC2 (RC1 plus W-02) if capacity needs it, see G5 |
| G2 Independent AI security review of the **final** SHA, with the security-fix evidence | review report, finding-by-finding closure | agent | not started (the 2026-10-20 review is for an older SHA) |
| G3 Real flow with the approved tester account and content: consent, destination authorization, immediate publish, schedule, pause or cancel, revoke and reconnect (X-02 to X-06; at most the three messages already approved, text approved by the owner at that moment) | `RC-RECEIPT.md` section 5 | owner + agent | waits for a promoted build |
| G4 Isolation: two accounts A and B, **both directions, reads and writes**, denied with **no side effects**, on the hosted build; the write tests the original script lacked are added; no waiver, no deferral | probe script and receipt | agent (+ accounts) | script being built, accounts needed |
| G5 Capacity: 5,000 posts due in the same minute meet the latency standard in section 4, on an architecture consistent with production | capacity receipt | agent + owner (Depot) | RC1 cannot pass (7 to 14 hours); W-02 simulated about 23 minutes; W-02 is in independent review |
| G6 People and data: H-07 filled with real names, hours, alert entry and a stop and rollback method that works with the Mac offline; M-03 filled from the real project | `APPROVAL-PACKET-2.md`, section 6 here | owner + agent | M-03 partly read, H-07 open |
| G7 Fresh-customer acceptance **on the opened production**: a brand-new ordinary workspace with no Discord history and no allowlist connects, authorizes a destination, publishes now, schedules, pauses or cancels, reconnects and disconnects | receipt | owner + agent | after opening |

Open means: `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*` (or an equivalent setting) in effect on the serving Production deployment, server cap 10,000, Direct publishing reviewed flag on. Because the gate value lives on the build command today, a later build that omits it would silently close Discord again; making the open setting durable (a project variable) is a separate step that needs the owner's yes.

## 3. Release scope

Production project `postriff-phase2-private` and its production database only. W-02 stays a separate branch until it is accepted. **If G5 needs W-02 (it does, by arithmetic), the release waits for W-02 to be accepted, integrated and the version re-frozen; the formal full opening then uses that new frozen SHA.** D1 and the approvals that name SHA `2a5a523d` do not carry over to RC2; RC2 needs its own builds and approvals.

## 4. Capacity standard (written first, as the owner asked; proposed, for the owner to accept or tighten)

Scenario: 5,000 scheduled posts, spread over about 2,000 workspaces, all due in the same minute T, one of them a "hot" workspace with 3,000 of the posts in a second run. Measured on the same architecture as production (the Vercel cron shards and the lane, the shared request coordinator, a PostgreSQL of the same major version and comparable size, a mock Discord with 50 to 150 ms latency and a hard ceiling), not only in-process.

| Measure | Acceptable |
|---|---|
| Lateness from T (sent minus due) | median at most 12 min, 95th percentile at most 25 min, maximum at most 40 min (the approval lives 60 min) |
| Duplicates | 0 |
| Sent after the approval expired | 0 (held for a fresh approval instead) |
| Requests above the policy ceiling in any trailing second | 0 |
| Fairness | a workspace with at most 5 posts due is fully sent within 15 min even while the hot workspace has 3,000 due |
| Held or lost posts | 0 below 13,000 due in one minute; above that a stated, bounded number held for a fresh approval |
| Database | peak connections at most 70% of the pooler limit; no statement timeouts |
| Drain time | reported for 5,000 (target about 25 min at 25 requests per second and six requests per post) |

Numbers that follow from the code today: six requests per post; the policy ceiling of 25 requests per second gives about 4 posts per second, so 5,000 posts need about 21 minutes at best. A tighter standard forces fewer requests per post or a higher reviewed ceiling (`docs/w02/OPEN-QUESTIONS.md` Q2 and Q7 on the W-02 branch).

## 5. Answers recorded from the owner (reply 12)

| Item | Decision | What remains |
|---|---|---|
| H-05 | James is Release Captain. The independent AI review must correspond to the final release SHA, with the security-fix evidence. After real-flow, isolation and capacity acceptance pass, the owner approves the full opening. The "only D1 controlled acceptance" positioning is deleted | review of the final SHA; the approval itself comes after G3 to G5 |
| Q-05 | No waiver and no deferral past opening: A/B both ways, reads and writes, no side effects, before the full opening; add the missing write tests | two accounts; probe script (in progress) |
| H-07 | Keep as a requirement: real operator, hours, alert entry, and a stop and rollback method that works with the Mac offline; unconfirmed stays open | the owner's names; section 7 here is the method |
| M-03 | Keep as a requirement: real backups, restore points, compute; PITR as it really is; assess sufficiency; no automatic purchase | restore-point times from the dashboard |
| H-03 | Reuse the tester workspace and complete the ids and time slot; add a brand-new ordinary workspace with no Discord history | the ids that only the owner has, the time slot, a new account |
| T0 and GO_TIME | Now the target time of the full opening; postponed if acceptance, capacity or on-call is incomplete; D1 READY is not delivery | no date is set |

## 6. M-03, what the tools can see (read-only, 2026-10-23 02:58Z)

Supabase organization plan: Pro. Project `postriff-phase2-private`, region us-east-1, PostgreSQL 17.6, healthy, 237 MB. **Compute is the smallest tier** (`max_connections` 60, `shared_buffers` 224 MB) [likely: this matches Micro]. Continuous WAL archiving is on with 26,520 segments and 0 failures, last at 02:58Z [certain], which is consistent with point-in-time recovery being available but does not prove it [guessing]. The Pro plan keeps daily backups for 7 days [likely]. **Not visible to any tool here:** whether the PITR add-on is purchased, the list of restore points and the earliest and latest recoverable time. The owner can read them on the dashboard (Database, Backups). Assessment: with daily backups only, the worst case is losing up to 24 hours of writes (new connections, schedules, approvals); with PITR it is minutes. Credentials can be re-authorized and posts re-scheduled, so a daily-only plan is survivable for a launch but weak once many customers schedule posts; PITR is the owner's purchase decision and is not bought automatically. The small compute is a capacity question for G5: it is measured, not assumed, and an upgrade is also the owner's decision.

## 7. Stop and rollback with the Mac offline (H-07 method, to be tested before the opening)

1. **Close Discord for everyone, fastest, no deploy:** set the operator hold on the shared request coordinator (the `manual_hold` field of the policy row); every Discord request is then refused before it is sent. Done by the agent through the database tool, or by the owner from a phone with the Supabase SQL editor and the one prepared statement in `RUNBOOK-INCIDENT.md`.
2. **Roll back the serving build:** the agent promotes the previous deployment through the Vercel API (seconds, no rebuild); the owner can do the same from the Vercel dashboard on a phone (Deployments, the previous production build, Instant Rollback).
3. **Stop new connections only:** promote the dark twin or the previous build, or set the build-level kill switch in the next build (slow).
4. Before any rollback to an older worker, set the hold and drain or reconcile in-flight Discord jobs.
All of these need no laptop. The statements and the tested sequence are recorded before the opening; a method that has not been run once is not accepted as H-07 evidence.

## 8. Critical path (no dates are promised; any failed gate postpones)

W-02 independent review and fixes → integrate RC2 → freeze and exact-SHA CI → independent security review of RC2 (and fixes, which means a new SHA and CI) → isolation probe on the hosted build → Depot capacity run → RC2 dark build, owner approval, tester session (G3) → open build, owner approval, promotion → fresh-customer acceptance (G7) → the owner's sign-off. The earliest conceivable finish is today if every step passes the first time and the owner is available for three short sessions; a failed review, a CI failure or a capacity miss moves it to tomorrow or later.
