# Milestone D receipt — Billing, privacy, Analytics, Audience

**Date:** 2026-09-16 · **State:** implemented and locally verified · **External state:** unchanged (no payment provider selected or contracted; no charge; no deployment; no hosted migration)

## What changed

| Path | Change |
|---|---|
| `migrations/postriff/007_consumer_web_billing.sql` | **new, additive.** `pr_plan_terms` (versioned decision records; seeded rows all `status='proposed'`), `pr_subscriptions`, `pr_entitlements`, `pr_usage_ledger` (append-only; service_role has insert+select only, no update/delete grant), `pr_budgets` (candidate warn/stop lines, the lock rows), `pr_billing_events` (unique provider+event id), `pr_data_requests`, `pr_metric_definitions` (Threads/Instagram native metrics, version `2026-09`, definition URLs), `pr_metric_observations` (CHECK: value present iff `available`), `pr_audience_threads`, `pr_reply_drafts`. |
| `src/postriff_phase2/billing.py` | **new.** `Ledger.reserve/settle/release` (lock budgets → check stop-lines and entitlement → idempotent reservation; completed consumes a batch; failed still books provider cost; unknown keeps the reservation as `estimated_unknown`), `usage_view`, `FixturePaymentProvider` (HMAC-signed, labelled fixture), `Billing.process_webhook` (signature, replay, out-of-order, unknown plan → rejected, entitlement reconciliation from terms), `lifecycle` (past_due → 7-day grace → cancelled; export always available). |
| `src/postriff_phase2/privacy.py` | **new.** Privacy notice (status: draft, requires legal review), retention classes, subprocessors, rights declaration, sanitized diagnostics (consent required, no content), `DataRequests` receipts. |
| `src/postriff_phase2/insights.py` | **new.** Native insight ingestion (server-only, Threads/Instagram), `Unavailable` never 0, rates with n/d, like-for-like cohort comparison, `< 3` → insufficient sample. |
| `src/postriff_phase2/audience.py` | **new.** Threads reply ingestion gated on Direct `comments_read`; manual or labelled AI-fixture reply drafts; exact reply approval manifest (account, thread, text digest) requiring `can_reply` + Direct `reply`; executor with separate submit/verify states. |
| `src/postriff_phase2/ideas.py` | Every turn reserves before execution and settles after (fixture: $0, no batch consumed); `events` returns the candidate artifact for preview. |
| `src/postriff_phase2/hosted_worker.py` | `on_verified` hook (insights/replies ingestion in the same transaction); container reference retained. |
| `src/postriff_phase2/hosted.py` / `hosted_app.py` | `usage`, `billing_webhook`, `data_request` (export receipt, diagnostics, retraction, deletion request), `analytics`; routes `GET …/usage|subscription`, `GET/POST …/data-requests`, `GET …/analytics/summary|posts`, `GET …/audience/threads`, reply-draft / preview / approve, `POST /api/billing/webhook`, `GET /api/privacy/notice`; catalog reports `authMode: dev` when the dev harness is mounted. |
| `tests/test_postriff_billing.py` (4), `tests/phase2/postgres_billing.py` (8 checks) | **new.** |

## Validation (observed)

| Check | Result |
|---|---|
| Python unit suite | **186 pass / 0 fail** |
| PG `postgres_billing.py` | **pass**, 8 checks: trial entitlement + proposed prices + stop-only overage; idempotent reserve, completed/failed/unknown semantics; stop-line and exhausted-entitlement 402 before execution; Ideas turn reserve/settle pair at $0 with no batch consumed; webhook signature/replay/stale/unknown-plan + entitlement reconcile + grace→cancelled keeps export; export/diagnostics receipts, consent required, no content; analytics/audience truthful limited states; ledger append-only even for service_role, budgets/billing events never browser-readable |
| PG regression (`repository`, `safety`, `isolation`, `ideas`, `channels`) on 004–007 | **all pass** |
| Browser (dev harness, real hosted code) | Usage & Plan surface renders trial entitlement, proposed plan terms, budget bar, ledger rows, data-request buttons; Analytics and Audience show explicit limited states with rules (see `receipts/milestone-e.md` for screenshots) |

`validation_unavailable`: live payment provider (none selected — selection requires Vercel Marketplace discovery and an explicit commercial decision; the fixture adapter is labelled); real tax/jurisdiction/refund constraints; real provider insights (no reviewed connector); customer-rights legal review (notice is a draft); backup-restore on real cloud storage.

## Decisions applied
- D3: prices are `pr_plan_terms` rows with `status='proposed'`; the UI labels them "proposed"; nothing charges.
- D5: Analytics/Audience ship as truthful limited surfaces.
- Improvement SPEC §6 cost contract: reserve → operation → commit → settle; unknown ≠ zero; candidate ceilings stored with `status='candidate'`.

## Remaining gates (none executed)
1. Choose a payment provider (Vercel Marketplace discovery + terms review) and implement its adapter behind `PaymentProvider`; live webhook endpoint secret in Vercel env.
2. Legal review of the privacy notice, terms, retention classes, and tax handling before any public sale.
3. Apply 007 to the hosted DB (after 004–006). Rollback: `drop table pr_reply_drafts, pr_audience_threads, pr_metric_observations, pr_metric_definitions, pr_data_requests, pr_billing_events, pr_budgets, pr_usage_ledger, pr_entitlements, pr_subscriptions, pr_plan_terms;`.

## Next concrete action
Milestone E receipt (in progress): shell, Ideas/Channels/Usage/Analytics/Audience screens, PWA, mobile pass.
