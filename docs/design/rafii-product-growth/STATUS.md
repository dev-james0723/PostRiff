# RAFII Product Growth v2 — status

States: `not_started → implemented → local_verified → staging_verified → production_deployed → production_verified`,
plus `blocked` / `failed` / `not_run` with a reason. Data mode (`demo|synthetic|live`) is separate from environment
(`local|staging|production`). A requirement is never marked done because a document changed.

Last update: 2026-10-01 · branch `claude/rafii-product-growth-v2` · PR #87 (draft).

## Program gates

| Gate | State | Evidence |
|---|---|---|
| G0.1 integration map | local_verified | `DECISIONS.md` D-001…D-007; production `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` @ `dcb5bcdc` re-read 2026-10-01 ~17:00Z |
| Base CI (production SHA) | passed (historical) | PR #84 `local-gates` + `scenes` green on `dcb5bcdc` (runs 36810557004/056) |
| Pricing v2 + Inbox v1 merged | local_verified | merges `8726adbd`, `575caaf9`; 87 focused tests; full unit suite 3,065 OK / 245 skipped (local, `.venv-growth`, 2026-10-01) |
| PR #87 CI on `d3825fbf` | failed → fixed | only failure `test_rafii_flag_fixes…credits_through_its_own_repository` (test double lacked Pricing v2 `ensure_entitlement`); fixed, rerun pending |

## Requirements

| Req | State | Code / tests | Next step |
|---|---|---|---|
| R-COM-01 catalog & legacy | implemented (backend) | Pricing v2 Tasks 1–4 (merged) | catalog API + UI (Task 6–8) |
| R-COM-02 one cost authority | implemented (backend, partial) | credit policy v2; Task 5 platform-funded ledger (`825e54b7`) | Growth/Weekly credit bridge |
| R-COM-03 Free boundary | implemented (partial) | Task 5 port: Free check + genome once per workspace, 24 PG tests | failed-attempt release, Radar gate |
| R-COM-04 consistent promises | not_started | — | `GET /api/plans`, public/app surfaces |
| R-FWR-01 continuation | not_started | — | `variant_import`, consent UI |
| R-FWR-02 guided first week | not_started | — | first-week resource |
| R-FWR-03 resume/approvals | not_started | — | checkpoint, revisions |
| R-FWR-04 raw intake | not_started | — | W-INTAKE |
| R-REL-01/02 | not_started | — | W-REL |
| R-OUT-01..03 | implemented (pure core) | `results/signing.py`, `results/model.py`; 21 unit tests | W-OUT (storage, receiver, links, UI) |
| R-SER-01/02 | not_started | — | W-SER |
| R-VIS-01..03 | not_started | — | W-VIS |
| R-BRF-01/02 | not_started | — | W-LOOP |
| R-PROOF-01/02 | not_started | — | W-LOOP |
| R-ENG-01/02 | implemented (scaffold) | `growth_v2_routes.py` wired in `hosted_app.py`; `web/src/lib/growth-v2/request.ts` | per-slice handlers |
| R-ENG-03 | not_started | migrations 080–089 reserved | per slice |
| R-MET-01 dictionary | in progress | `growth_events.py` taxonomy (aligned with Founder P1 writer); proposal agreed in shape by Founder P0 | `metric_definitions.py` |
| R-MET-02 paid conversion | not_started | defect confirmed (`coworker/growth.py:107-143`) | shared definitions + fleet relabel |
| R-MET-03 events/costs | implemented (helper) | `growth_events.py`, 5 unit tests | emit from each slice |
| R-NFR-01..04 | not_started | — | release gates |

## Live blockers (exact owner action)

| Blocker | Effect | Owner action |
|---|---|---|
| Production deploy authority for Pricing v2 / Inbox v1 code | No production deploy of this branch | James: explicit superseding permission naming the deploy (D-007) |
| Production migrations 047, 048, 050, 080–089 | New tables absent in production | James: approve each one-off sha-pinned runner |
| Free platform-preview budget (`POSTRIFF_GROWTH_PLATFORM_PREVIEW`) | Free first-value runs refuse before paid I/O | James: approve policy JSON (route, caps) |
| Live Stripe Prices / Creator checkout | No new paid sale | James: live commercial activation per Pricing v2 runbook |
| Founder P1 `pr_invoices` (057) | Paid metrics `partial` | Founder P1 session pushes `claude/founder-admin-p1p2` |
| Transcription route for raw audio | Audio intake `unsupported` | James: approve provider/model + budget |
