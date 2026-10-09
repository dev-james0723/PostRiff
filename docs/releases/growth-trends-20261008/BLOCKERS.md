# Blockers and action packet (James)

Updated 2026-10-09 ~01:30Z. Engineering on all three lanes continues while these
are open. Each item states the exact scope, the minimum action, the known cost
ceiling and what happens if it is not approved.

## P0-1 Production-change permission for this session (critical path)

This session's auto-mode classifier refuses production-changing actions (it
already refused preparing the production migration step). Without one of the
options below I can finish code, tests, PRs and CI, but cannot ship.

Needed actions, all additive and reversible:
1. Apply migrations to Supabase `buoyhkbodnhzngaotoel` (Supabase MCP
   `apply_migration`), each with a ledger row pinned to its sha256:
   - `037_growth_phase1.sql` (7e9be37e…) + `038_growth_closed_loop.sql`
     (ac6e52d5…): 11 empty Growth tables, forced RLS, service role only.
     Currently deployed code only touches them when they exist, and then only
     empty tables (checked in source).
   - `103_feature_enrollments.sql` (b3b8b681…): 1 empty table, forced RLS.
2. Merge the release PRs into `consumer-saas` (Vercel auto-deploys production
   from it in about 3 minutes). Order: lane A first, then the integrated
   Growth/Trends PR.
3. Set production env vars (no spend by themselves) and redeploy:
   `POSTRIFF_GROWTH=1`, `POSTRIFF_POSTMORTEM=1`, `POSTRIFF_AUDIENCE_MINER=1`,
   `POSTRIFF_GENOME=1`, `RAFII_TREND_SELF_SERVE_ENABLED=1`,
   `RAFII_TREND_SELF_SERVE_MAX_WORKSPACES=<P0-4>`,
   `POSTRIFF_METRIC_SELF_SERVE_ENABLED=1`,
   `POSTRIFF_METRIC_SELF_SERVE_MAX_WORKSPACES=<P0-4>`.
   Never touched: `POSTRIFF_RADAR` (different feature), allowlist wildcards, caps.

Minimum action: reply "approve production steps 1–3 for this task" (or add an
allow rule for this session), or run the exact commands I hand over.
If not approved: everything stays a verified candidate, not a release (A10).

## P0-2 Trends shared corpus rights review (ordinary users)

Today the only Bluesky source policy is scoped to the founder workspace with
`share_across_workspaces=deny`, and ACTIVATION.md requires a separate rights
review before any shared-scope use. Ordinary workspaces can only see trend
evidence through a reviewed `shared:` scope policy that allows
`share_across_workspaces` (plus a contract row listing that operation).

Minimum action: approve or decline one reviewed shared-scope Bluesky
`live_sample` policy (same public Jetstream source, unmetered, $0, same
retention and deletion rules), recorded with you as reviewer.
If declined: enrolled ordinary workspaces see an honest "source rights pending"
state and no trend list. Trends for ordinary users stays BLOCKED (A1).

## P0-3 Growth daily spend caps (paid review and audience analysis)

`POSTRIFF_GROWTH_DAILY_USD_CAP` (global) and
`POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP` (per workspace) are unset, so paid
Growth actions fail closed. Code worst case per workspace per day: result
reviews 10 × $0.20 + audience runs 2 × $0.80 = $3.60. Proposal: global
US$10/day, per workspace US$4/day. Owner consent is still required for each
workspace.
If not approved: Results/Audience reading, windows, consent and enrollment work;
"Review this result" and "Analyze audience" show "not configured" (A7 partial).

## P0-4 Self-serve cohort size

Proposal: initial cap of 10 workspaces each for Trends and Growth measurement.
Both are zero-spend reads. Switching a feature off un-admits enrolled workspaces
immediately.

## P1-5 Ordinary-user test account

Production has 5 workspaces, each with a single owner, and no editors or
viewers. For the non-founder journey and the owner/editor/viewer checks I need
either:
(a) a non-founder account you create, plus an editor and a viewer invite into
    its workspace; or
(b) permission for me to sign up a QA account on rafii.io with a Gmail alias
    (`hinsingau.pianist+rafii-qa1@gmail.com`) and read its sign-in code through
    the connected Gmail.
Without either: role and tenancy are proven in CI (disposable Postgres plus
browser harness) and with the founder's second, non-allowlisted workspace only.
The live ordinary-user journey stays UNVERIFIED.

## P1-6 One publish-linked Instagram proof post

Publish-linked t0/1h readings need one real Rafii publication. Needed: the
exact account (the founder's Instagram, the only one with Direct analytics) and
the exact post content you approve. The 24h and 7d windows will be honestly
"not due yet" at launch.
Without it: the publish-linked chain stays UNVERIFIED live. CI proof and the
existing history-import readings still show.

## External, not solvable by launch (informational)

- Meta App Review Advanced Access for `instagram_business_manage_insights` and
  `instagram_business_manage_comments`: ordinary Instagram users cannot get
  native readings or comments until this is approved (package prepared
  2026-09-25, never submitted).
- Threads OAuth client ID and secret are not configured in production.
- iPhone Safari real-device check needs your phone (no enrolled device).
- Optional: model-angle budgets for enrolled workspaces. Default is no;
  user-written angles save to Ideas with no spend.

## Not doing (no authorization needed or deliberately left alone)

- No manual cursor reset; the code fix re-anchors with an explicit gap.
- The 344 stale Bluesky observations are left to the scheduled retention purge
  (2026-10-11T01:19Z); no early destructive purge.
- No wildcard allowlists, no RLS changes, no consent on anyone's behalf.
