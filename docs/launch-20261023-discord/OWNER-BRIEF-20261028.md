# Owner brief, 2026-10-28 (one page; the long version is `OWNER-DECISIONS-PENDING.md`)

> **Superseded (00:01Z on 2026-10-29):** the current state is `LEAN-PLAN-20261028.md` (what is decided and cut) and `APPROVAL-PACKET-3-DRAFT.md` (the Production steps for the frozen RC2 `abca8b71`, section 0 filled). The text below is the 2026-10-28 morning situation and is kept as history.

> **Answered 14:17Z on 2026-10-28 by reply 16 ("I approve all"):** items 1 to 4 below are decided as recommended; production operations, the on-call details (item 5) and the last items (6) are not covered. See `AUTHORIZATION-RECORD.md`.

Release state: **NO-GO** (gates G1 to G7 are not all green). Nothing in Production has been built, promoted, changed or messaged. `rafii.io` still points to `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`. Engineering continues; every Production operation still needs your explicit approval (Packet 3, not yet submitted).

## What happened since 2026-10-23

- The account's weekly usage limit stopped all agents from 11:05Z on 2026-10-23 until 05:00Z on 2026-10-28 (4 days 18 hours). No data was lost. Pace since: at most three or four agents at once.
- Delivered and independently reviewed: identity/consent/isolation fixes (G2a), the parallel Discord lane follow-ups (W-02), the shared request coordinator rewrite (exact 25-a-second ceiling, booking), customer sender names (backend and UI), the H-07 alert pipeline fixes, the Q-05 isolation probe with sender-name cases (146 of 146 pass locally). Each has fail-before tests.
- Production read-only check: the retention DELETE for the coordinator's records needs no new grant (the pooled app role is the table owner).

## Decisions I need from you (ranked)

1. **D-12 (urgent if anyone is about to promote):** do not promote any candidate that contains Discord RC1 (`2a5a523d`), including `claude/mastodon-scale-on-live-20261027` and the staged D1. I reproduced FB-1 on it: Facebook Page posts cannot be approved and approved ones are held. Use the isolated dependency hotfix (PR #225) instead of merging RC1. Reply: agree / disagree.
2. **D-2 option (1) and D-16 (the capacity standard, gate G5):** hosted measurement of the rewritten coordinator was 19.77 / 37.87 / 43.52 minutes against 12 / 25 / 40 (request amplification, now fixed by booking; model after the fix: about 16 / 31 / 36). The 12-minute median is reachable only if three things are all used: (a) a lane that works nearly the whole minute (a build setting, no decision needed), (b) a slot guard of 0.05 s instead of 0.1 s (D-16: read "25 a second" as the coordinator's own stamp; Discord's real limit is 50), (c) charging the person's own `GET /oauth2/@me` to a separate bearer budget while the bot stays at 25 (D-2 option 1). Even then the margin is about 0 to 5%. Reply: approve (c) and (b) / approve neither (then I report the best figures under the written budget).
3. **D-4 and D-14 (code constants, needed before the freeze):** a workspace may have at most **300** due Discord posts queued (measured: 292 of 300 sent in the hour; 236 of 1,000); the coordinator keeps read records **1 hour** and create records **48 hours** (otherwise the database grows 4 to 7 GB a day at the promised normal load). Reply: accept / change the numbers.
4. **D-1 and D-11 (defaults I keep unless you object):** customer sender names ship built, reviewed and OFF; at the opening customers see no sender-name editing (webhook route dark, nickname switch off). Seven customer-visible behaviours of the security fixes are listed in D-11 (a removed admin's installs are revoked, Discord reads are throttled, Save-as-draft is capped, at most 30 servers per workspace).
5. **H-07 (people, not code):** primary and backup on-call names, e-mail addresses, mobile numbers, which phones receive push, a phone channel, and whether night cover exists. Without them H-07 stays BLOCKED by computation. Also M-03: one sentence from Supabase, Database, Backups (Point in Time tab and Scheduled backups list).
6. **Later, last, minimal:** public and private test channel ids and a time slot (tester session), two throw-away accounts A and B with short-lived sign-in codes (hosted isolation run), and the Packet 3 approvals.

## What I will do without asking (inside your delegation)

Keep fixing and reviewing on non-Production branches; rehearse the integration (two known merge conflicts, both resolved by keeping both sides; the integrated tree's secret scan passes); measure again on the hosted runner; prepare Packet 3. I will not build, promote, set variables, touch the database, send real Discord messages or spend money without your item-by-item approval.
