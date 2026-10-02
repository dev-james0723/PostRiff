# G0 code map (2026-10-01, base `575caaf9`)

Condensed from five read-only maps of the integration branch. Anchors are `path:line` at that commit; re-check before
editing. Findings that change scope are marked **⚠**.

## Pricing v2 (R-COM)
- Done (merged): catalog schema 048 + variants/assignments (`plan_pricing.py`), versioned credit policy
  (`credit_meter.py`, `credit_wallet.py`), server-owned Creator variants + Stripe mapping (`billing.py:360-391`,
  `billing_stripe.py`), Free fallback lifecycle 050 (`free_lifecycle.py`, `hosted.py:757-791`). Extensive PG tests.
- Task 5 (Free cost boundary) was staged-only; ported as `825e54b7` (24 PG + 4 unit tests pass).
- **⚠** Before the port, Growth bypassed the ledger: Free got 10 checks + 1 genome + 1 rewrite *per day*
  (`growth/service.py:276-321`). Radar has no plan gate (`radar/service.py:123-176`).
- Not started: billing modes, filtered catalog API, effective variant price, all web surfaces (public pages are static
  legacy copy in `web/src/config/plans.ts:31-78`; in-app surfaces show legacy batches), top-up contract, telemetry,
  runbook, verification. `usage_view` returns hidden Starter/Studio and legacy terms and the plan price instead of the
  variant price.

## First value / first week (R-FWR)
- Anonymous Post Doctor (`public-post-doctor.tsx`, `POST /api/post-doctor` → `growth/service.py:698-717`): stores no
  draft text; keeps a qualitative result 24 h (`pr_public_checks`). **⚠** Model usage rows keep an unkeyed SHA-256 of
  the draft indefinitely (`growth/post_doctor.py:263`, `growth/judgments.py:96-102`).
- `next` survives OAuth, email code and MFA in the same tab (`web/src/lib/auth/navigation.ts:5-9`); email magic links
  would lose it (no `emailRedirectTo`).
- **⚠** No free "save my own text as a draft" command: drafts are created only by paid writer runs (`ideas.py:1864`).
- `source` action caps text at 20,000 chars and refuses duplicates (`postriff_alpha/domain.py:285-313`).
- Weekly Operator: deterministic recipes/weeks/slots, blocked states, Queue read-back (`coworker/weekly_operator.py`),
  item review (`coworker/service.py:438-479`). **⚠** No credit-quote path: with an active credit policy every drafted
  slot would fail 402 (`coworker/service.py:293-320`). Recipes require a connected account and owner role.
- No raw audio or PDF ingestion anywhere; `source_intake.normalize` requires pre-extracted text and silently truncates
  at 60,000. Large-upload precedent: signed-URL `video_uploads.py`; durable job precedent: `growth/trends/jobs.py`.

## Relationships / results (R-REL, R-OUT)
- Inbox v1: `pr_audience_threads` (no `unique(workspace_id,id)`), `pr_reply_drafts` approval jsonb, exact-digest
  approval and fenced worker (`audience.py:147-209`, `audience_worker.py`).
- Attention is recomputed on read, no storage/dismiss (`coworker/attention.py`); notifications `catalog.py` +
  `planner.py` (quiet hours, DST, digest, mute/unsubscribe).
- No tracking links, no business-result store, no first-party receiver. Webhook verifiers (Stripe, Xiaohongshu, Svix)
  dedupe but never compare a conflicting payload; all webhook secrets are global env vars (no rotation).

## Series / visual (R-SER, R-VIS)
- Evergreen: `campaigns.evergreen_post` (verified, ≥minAgeDays, not used by *this* task); no cross-task cooldown.
- Overlays: `MEMORY_TYPES=("voice","brand")`; evergreen writer does not read overlays.
- Creative plan already specifies 1080×1350 six-slide carousels with safe areas (`coworker/creative.py:19-35,104-107`).
- No renderer, no CJK font, storage forces JPEG (`hosted_storage.py:23`), manifest takes one asset (`store.py:354-447`).
  **⚠** Threads and Instagram publishers take `media[0]` without a guard (`hosted_social.py:732-766`), so extra media
  would be silently dropped if a multi-media job ever reached them.

## Briefs / proof / metrics (R-BRF, R-PROOF, R-MET)
- Opportunity sources: Radar v1 (paid capable), Social Trend Intelligence (stored-only ≤3 pool), Listening.
- Proof: `growth_loop.generate_proof` returns an existing proof unchanged (no revisions), UTC periods, no watermark or
  timezone; Time Back confidence is `estimated|personalized|measured` (no `reported`).
- **⚠** `coworker/growth.py:107-143` `fleet()` counts any non-trial status as conversion and today's status as
  retention; Stripe `trialing` maps to `active` (`billing_stripe.py:35`).
- Payment history: none beyond credit-plan grants (`pr_credit_subscription_grants`, 022) and refunds/disputes by
  payment intent. Founder P1 owns the in-flight `pr_invoices`/`pr_subscription_events` (057) and `product_events.py`.
