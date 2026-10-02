# Integration evidence — 2026-10-01

Data mode and environment for each item:
- **Local items:** disposable PostgreSQL 17 on private ports on James's Mac, with synthetic identities and fixture providers.
- **CI items:** GitHub-hosted Ubuntu runners.
- **Preview items:** the Vercel preview, isolated to the staging project.

Nothing on this page is production or live-customer evidence.

## Branch

- `claude/rafii-product-growth-v2`, PR #87 (draft), base `fix/rafii-call-lifecycle-20260930`.
- The base is production `dcb5bcdc` (`dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL`, the rollback target).

Slice merges:

| Slice | Branch @ head | Migration |
|---|---|---|
| Results | `claude/rpg-results` @ `de727483` | 080 |
| Relationships | `claude/rpg-relationships` @ `d16e9652` | 081 |
| Visual packs | `claude/rpg-visual-pack` @ `c5c91d90` | 083 |
| Signature Series | `claude/rpg-series` @ `38abb86c` | none (D-021) |
| Raw intake | `claude/rpg-intake` @ `b6eac5e2` | 087 |
| Pricing web | `claude/rpg-pricing-web` @ `e8a68703` | — |
| Briefs / proof | `claude/rpg-loop` @ `7e4815ce` | 084 |

## CI (GitHub Actions)

| Head | Workflow | Result | Notes |
|---|---|---|---|
| `3a1d7b3a` | local release gates | failed | Copy gate: a piano placeholder in the first-week panel. Fixed in `7dc55c5f`. |
| `a42bd212` | browser scenes | failed | Web build: 4 × TS2345. Fixed in `41c4e9cf`. |
| `205b064d` | preview window | failed | oxlint: 14 errors. Fixed in `3c6e35bc`. |
| `205b064d` | release gates | failed | PG suite: a hard-coded macOS `psql` path; a stale follow-up payload assertion. Fixed in `3c6e35bc`. |
| `d2469a9f` | preview window acceptance | **passed** | Full typecheck + lint + preview tests (run 36934793626). |
| `d2469a9f` | release gates | Python, every PG group, web contracts, types/lint/isolated production build, copy audit, function archive: **passed**. Secret scan: failed. | 16 reviewed non-secrets, allowlisted in `6db0b877` (run 36934793624). |
| `d2469a9f` | browser scenes | Automations now **passes**. The growth harness step fails. | Next 16 refuses a second `next dev` in `web/`. The fix (`POSTRIFF_DIST_DIR`) is in progress in W-BROWSER (run 36934793633). |

## Vercel preview (`dpl_2xQHeEv1XfQenwPaWepNQFN59Lr6` @ `d2469a9f`, READY)

- `/pricing` renders the legacy catalog unchanged; `NEXT_PUBLIC_PRICING_CATALOG` is unset on the preview.
- `/post-doctor` renders.
- `GET /api/growth-features` returns `{"features": {"firstWeek": false}}`, because the preview flags are off.
- `GET /api/plans` returned 500. The runtime log shows `UndefinedColumn` on the staging-backed database, where 048 is not applied. Fixed in `c8ccf2a6`; the new group `postgres_pricing_catalog_pre048` fails without the fix.

## Local verification on the integrated branch

- Web node tests: 605/605. oxlint: 0 errors.
- Each slice's unit modules plus the affected modules were re-run after every merge.
- PG groups re-run against the integrated schema:
  - relationships (×3, against the real results slice)
  - results
  - first_week, growth_loop, briefs_proof
  - coworker, unified_notifications
  - credit / image / catalog groups
- Bounded reads (`postgres_growth_v2_bounded_reads`):
  - **Fixture:** 120 declared results and 120 follow-ups; 10 concurrent sessions; 50 samples per endpoint; through the real WSGI app.
  - **Result on the overloaded Mac (arm64):** every endpoint p95 ≤ 75 ms; pages capped at 50 rows.
  - **Not covered:** series, visual packs, uploads and proof had empty fixtures.
  - This is supporting evidence, not the staging SLO.

## Defects found by inspecting actual results (fixed)

- Creator image requests failed with misleading messages. They are now refused up front with `image_credits_unavailable` (D-026).
- The site agent could tell a Creator they had "0 writing batches". Plan facts now follow the billing mode.
- Follow-up reminder emails reused the "comments need a reply" template, with English-only titles. They now have a dedicated template in 4 locales.
- Marking a follow-up "won" required pasting a result ID. There is now a picker, or the result can be recorded in place.
- Switched-off features were queried from shared pages, producing a console 404 on every visit. A feature gate now prevents the requests.
- The anonymous Post Doctor offered the first week where the feature is off. The offer now appears only when the feature is on.
- Proof counted canceled approvals because of a `cancelled`/`canceled` spelling mismatch. This bug is present in production too.

## Later on 2026-10-01 / 2026-10-02 (after the review fixes)

- **Production moved** to `dpl_4F4d2CNxXqh37viSo2gTDBYZDb5c` @ `047d024e`, which includes Founder Admin #86/#88. This branch merged it in at `2a6c13ef`. PR #87 now targets `consumer-saas`.
- **Review rounds:**
  - The first whole-branch review used four reviewers.
  - The verification review of the fixes found 6 medium and 12 low issues.
  - All findings are fixed and merged, through `rpg-fix-relationships`, `rpg-fix-slices`, `rpg-fix-billing`, `rpg-fix-web-2` and the coordinator commits.
- **Local, on the merged branch:**
  - Python unit suite: 3,987 OK.
  - PostgreSQL groups: every group for the touched areas passes, including all eight Stripe-provider groups and the new pre-048, replay-limit, ended-legacy, re-enrollment and endpoint-privacy tests.
  - Web node tests: 819/819.
  - oxlint: 0 errors.
- **CI on `054feb10`:**
  - Release gates passed in full: Python, every PG group, web contracts, types/lint/isolated production build, copy audit, function archive, secret scan, dependency audits, and the real local browser/API/DB run.
  - Preview window, Founder Control and Founder admin browser passed.
- **CI on `ceff036c`:**
  - `Rafii browser scenes` passed in full (run 36956968532), including the Product Growth journeys.
  - Preview window, Founder Control and Founder admin browser passed.
  - Release gates were still running when recorded here.
- **Defects found by the browser journeys and fixed:**
  - no way into Follow-ups from an empty Inbox;
  - first-week posts the planner couldn't draft had no "write it yourself";
  - the no-conversation follow-up wording;
  - proof correction overflow at 768/390;
  - a reduced-motion pricing FAQ that stayed blurred (a hydration mismatch);
  - an ASCII colon in zh-Hant.
