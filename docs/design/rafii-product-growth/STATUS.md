# RAFII Product Growth v2 — status

States: `not_started → implemented → local_verified → staging_verified → production_deployed → production_verified`,
plus `blocked` / `failed` / `not_run` with a reason. Data mode (`demo|synthetic|live`) is separate from environment
(`local|staging|production`). A requirement is never marked done because a document changed. "local_verified" below
means: focused unit tests + disposable PostgreSQL 17 groups on a private port, synthetic providers, Python 3.12.

Last update: 2026-10-01 · branch `claude/rafii-product-growth-v2` · PR #87 (draft) · coordinator HEAD `d880ad97` (local).

## Program gates

| Gate | State | Evidence |
|---|---|---|
| G0.1 integration map | local_verified | `DECISIONS.md` D-001…D-007; production `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` @ `dcb5bcdc` re-read ~17:00Z |
| Base CI (production SHA) | passed (historical) | PR #84 `local-gates` + `scenes` green on `dcb5bcdc` |
| Pricing v2 + Inbox v1 merged | local_verified | merges `8726adbd`, `575caaf9`; full unit suite 3,077 OK / 245 skipped (local) |
| PR #87 CI | first run failed (1 test double), fixed; later runs superseded by pushes; `3a1d7b3a` running | GitHub Actions `Rafii local release gates` |
| Vercel preview build | passed on `d3825fbf` | Vercel check on PR #87 (no database in Preview: build/static only) |
| Slice workers | running | results, relationships, visual pack, series, briefs/proof, intake, pricing web |

## Requirements

| Req | State | Code / tests | Next step |
|---|---|---|---|
| R-COM-01 catalog & legacy | local_verified (backend) | Tasks 1–4 merged; Task 6 `plan_pricing.public_catalog`, `GET /api/plans`, usage `billingMode`/filtered terms/variant price/Creator offer; `postgres_pricing_catalog_api_v2` (7), catalog 12, assignment 46, Free lifecycle 20 | UI (W-PRICING-WEB); live Stripe activation is James's |
| R-COM-02 one cost authority | local_verified (partial) | Task 5 platform-funded ledger; Radar always credits for managed plans; Weekly slots drafted against per-slot credit quotes; absorbed-over-max signal; `postgres_radar_plan_gate_v2` (4), `test_first_week_weekly_credits` (7), `postgres_credit_policy_v2` (15) | Growth AI for Creator still fails closed (`growth_credit_bridge_unavailable`) — v2-activation prerequisite, not yet built |
| R-COM-03 Free boundary | local_verified | Free: 1 Post Doctor check + 1 recent-20 Genome per workspace lifetime (24 PG tests); no Radar paid I/O; no AI drafting in Weekly/first week; a failed preview attempt consumes the preview (Pricing owner's anti-abuse rule, kept) | Platform-preview budget policy needs James's approval to run in production |
| R-COM-04 consistent promises | implemented (backend) | one catalog projection for public/app/checkout; top-ups unsellable (`postgres_topups_disabled_v2`, 3) | public/app UI + fixture contract (W-PRICING-WEB) |
| R-FWR-01 continuation | local_verified | `first_week/service.import_continuation` + web continuation module/dialog/import panel; `postgres_first_week` AC06/AC07 (4 tests), `web/tests/growth-v2-continuation.test.mjs` (5) | browser journey on preview/staging |
| R-FWR-02 guided first week | local_verified | plan without account (publishBlocker), accepted draft = post 1, Free manual writing, Creator per-slot quotes; AC08 tests | browser + live paid drafting (authorized workspace) |
| R-FWR-03 resume/approvals | local_verified | journey revision guard, frozen scope + reasoned changes, acceptance invalidated by edits, Queue read-back, assisted handoff never "published"; AC09/AC10 tests | browser |
| R-FWR-04 raw intake | in progress | W-INTAKE (087) | — |
| R-REL-01/02 | in progress | W-REL (081) | — |
| R-OUT-01..03 | in progress | core `results/signing.py`, `results/model.py` (21 unit tests); W-OUT (080) | — |
| R-SER-01/02 | in progress | W-SER (082) | — |
| R-VIS-01..03 | in progress | W-VIS (083) | — |
| R-BRF-01/02, R-PROOF-01/02 | in progress | W-LOOP (084) | — |
| R-ENG-01/02 | local_verified (scaffold) | `growth_v2_routes` (dispatch, public, cron) wired once; `growth_v2_agent_tools` registry hook; first-week typed tools (READ / CREATE_DRAFT / MUTATE_REVERSIBLE); routes test (5) | per-slice tools |
| R-ENG-03 | in progress | 080–089 reserved; additive/guarded on pre-048 schema (usage view) | each slice migration + replay tests |
| R-MET-01 dictionary | local_verified | `metric_definitions.py` (all `proposed_definition_not_activated`, Founder row shape); `growth_events.py` aligned with Founder P1 `product_events`; agreed in shape with the Founder P0 owner | register via Founder `metrics.d` when P1 lands |
| R-MET-02 paid conversion | local_verified | `growth.fleet` cash-paid from history (grants now, `pr_invoices` when 057 lands), refund-adjusted variants, status view renamed; `test_metric_definitions` (17 golden), `postgres_growth_fleet_v2` (2), coworker V07 | `dataState=partial` until Founder P1 pushes `pr_invoices` |
| R-MET-03 events/costs | implemented | event taxonomy; first-week emits continuation.claimed, draft.accepted, week.scope_approved/changed | slice events; cost lineage via Founder `business_usage_v2` |
| R-NFR-01..04 | not_run | — | release gates |

## Live blockers (exact owner action)

| Blocker | Effect | Owner action |
|---|---|---|
| Production deploy authority for this branch (contains Pricing v2 / Inbox v1) | No production deploy | James: explicit superseding permission naming the deploy (D-007) |
| Production migrations 047, 048, 050, 080–087 | New tables absent in production | James: approve each one-off sha-pinned runner |
| Free platform-preview budget (`POSTRIFF_GROWTH_PLATFORM_PREVIEW`) | Free first-value runs refuse before paid I/O | James: approve the policy JSON (route, caps) |
| Live Stripe Prices / Creator checkout | No new paid sale | James: live commercial activation per the Pricing v2 runbook |
| Founder P1 `pr_invoices` (057) | Paid metrics `partial` | Founder P1 session pushes `claude/founder-admin-p1p2` (agreed) |
| Transcription route for raw audio | Audio intake `unsupported` | James: approve provider/model + budget |
| Growth credit bridge (Creator Growth AI) | Creator Post Doctor/rewrite fail closed under v2 | Engineering (not started); required before v2 activation |
