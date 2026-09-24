# FINAL delivery — 2026-09-24

Machine-readable twin: `FINAL-DELIVERY.json`. Step-by-step record: `FINAL-LEDGER.md`. Nothing below used a real
model provider, a real social account, a real Stripe account, real money or a production database.

## Status by layer

| Layer | Status | Evidence |
|---|---|---|
| Code implemented | Done for FINAL-01…10 items listed in the ledger; open gaps below | `FINAL-LEDGER.md` |
| Local acceptance | `LOCAL_VERIFIED` on release snapshot r6 `d9573b5e…` (1,190 files) | tests table below, `evidence/final/r6/` |
| Canonical integrated | Yes — working tree only: 128 files (62 updated, 66 created) with pre-image checks at 08:54:30Z; canonical now equals r6 except `web/tsconfig.json`; no stage/commit/push/merge | `FINAL-MERGE-MANIFEST.json`, `evidence/final/r7-canonical/` |
| Live model verification | `NOT_RUN` | needs `FINAL-AUTHORIZATION.md` #1 |
| Stripe synthetic | `LOCAL_VERIFIED` (signed synthetic events; synthetic top-up in the browser) | `FINAL-BILLING-MATRIX.md` |
| Stripe Sandbox | `NOT_RUN` | #3 |
| Real payment | `NOT_RUN` | #4, #5 |
| Real publishing | `NOT_RUN` (package prepared) | `FINAL-CAPABILITY-MATRIX.md` §4, #6 |
| Production deployment | `NOT_RUN` | #9–#11 |

## Where the changes are

- Candidate `/Users/ouxianxing/Documents/James-Au-Studio-launch-20260923` (branch `codex/launch-audit-20260923`, HEAD `468811b`, uncommitted): all integration work, evidence and backups.
- Canonical `/Users/ouxianxing/Documents/James-Au-Studio` (branch `consumer-saas`, HEAD `468811b`, uncommitted): the 128 promoted files, these deliverables in `docs/launch-20260923/`, the canonical DB-suite output in `docs/launch-20260923/evidence/final-canonical-db-suite/`, and four local preview entries in `.claude/launch.json` (`launch-final-api`, `launch-final-api-legacy`, `launch-final-web`, `launch-final-web-prod`).
- Preserved: canonical's latest v9 design and the Automations hub, Analytics opt-in, font fallback and hydration fix that another session committed on `rafii-v9-integration` during this work (taken into the candidate first, merged three-way where both sides changed, every canonical line kept). Nothing was deleted from canonical except what the promotion replaced with a merged version; pre-images are saved.

## Tests (exact)

Release snapshot r6 (candidate) and canonical after promotion — same content:

| Suite | Candidate r6 | Canonical after promotion |
|---|---|---|
| Python `unittest discover -s tests` (`.venv`, `PYTHONPATH=src:tests`) | 689 tests, OK, exit 0, 0 skipped | 689 tests, OK, exit 0, 0 skipped |
| `tsc --noEmit --incremental false` | exit 0 | exit 0 |
| `npm run lint` (oxlint) | exit 0, 0 warnings, 0 errors | exit 0, 0 warnings, 0 errors |
| Node `--test` (31 files in `web/tests` + `web/src`) | 135 tests, 135 pass, 0 fail, 0 skipped, exit 0 | same |
| PostgreSQL (`launch_acceptance_db.py`, disposable, loopback) | 47/47 scripts exit 0, source unchanged | 47/47 exit 0, source unchanged (first attempt refused by the script's own rule that output stays in its repository; re-run with in-repo output) |
| Production build (`npm run build`, isolated copy, CI env) | exit 0, Next.js 16.3.5 Turbopack, no warnings | covered by r6 (identical sources) |
| Browser journey, legacy allowance | exit 0, 4 steps, 0 page errors, 0 failed requests, 0 serious/critical axe | covered by r6 |
| Browser journey, credits | exit 0, 6 steps (quote/reserve/settle 50→47, follow-up 47→44, top-up +1,000 once, never before payment), 0 page errors | covered by r6 |
| Route matrix (44 routes × 390/768/1024/1440 × light/dark, Chrome) | 352 captures, 0 overflow, 0 axe violations; named errors only: 16 × 500 `/app/account/api` (harness lacks migration 016), 8 × 404 not-found (expected), aborted Next.js prefetches | covered by r6 |

Earlier snapshots (r2, r4, r5) and why they were superseded are in the ledger (FINAL-11).

## Git, deployment and live actions

No commit, push, merge, deployment or production migration. No real model call, email, post, Stripe account
action or charge. Other sessions' servers (4331/3100 and others) were not stopped.

## Operator recovery (runbook)

- Health at a glance: `python3 scripts/ops_health_report.py --dsn <dsn>` (read-only; loopback unless `--confirm-host <host>`).
- Unknown model cost: check the gateway request log, then `scripts/reconcile_unknown_usage.py settle … --outcome failed|completed --actual-usd … --operator … --evidence …` (once per reservation; `failed` never charges).
- Payment event needing review: `scripts/credit_payment_inbox.py list|resolve` (resolving never moves money; refunds/credits are done in Stripe, then the verified event replays).
- `uncertain` publishing job: check the platform for the exact post before anything else; the worker never re-submits an uncertain job.
- Expired `processing` lease / overdue `scheduled` job: the cron or worker is not running — check `/api/cron/worker` and the Vercel cron.
- Budget past its stop line or still `candidate`: an owner raises/approves the cap (FINAL-AUTHORIZATION #2); paid tasks stay refused until then.
- Kill switches: `POSTRIFF_CREDITS_ENABLED=0`, `POSTRIFF_CREDIT_PURCHASES_ENABLED=0`, `POSTRIFF_RESEARCH=0`, connector pause, `POSTRIFF_MODEL_PROVIDERS` to narrow providers.

## Remaining gaps and how to unblock

| Gap | Unblock |
|---|---|
| Live gateway behaviour (routing restriction, metadata location, real usage shapes, zh-HK quality) | Approve #1 (15 drafting requests + 1 image + 1 voice analysis, cap US$3) |
| Paid drafting refused (budgets `candidate`) | Choose caps (#2) |
| Stripe live shapes, disputes, renewals | Stripe test-mode access (#3) |
| Prices, credit packs, monthly credits, refunds of spent credits, proration | Commercial decision (#4) |
| Legal facts; Terms for credits/renewal | Owner and counsel (#5) |
| Real publishing receipts, LinkedIn escaping on the live API, Threads limits | Approve #6 with own accounts |
| Rate limits, CSP/HSTS, research metering, voice rounding, kill-switch UX, Unknown-state UI, `charge.refund*`, Stripe API version pin, emoji byte counting, LinkedIn image posts | Engineering follow-ups (no external dependency) |
| Harness lacks migration 016 | Add `016_api_tokens.sql` to the dev harness schema |
| WebKit / 200% zoom / slow network / real phones | Next browser pass |
| Home content library length | Owner design decision |
