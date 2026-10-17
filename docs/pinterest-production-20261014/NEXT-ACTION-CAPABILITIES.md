# Exact next approval — tested capability candidate, flags remain closed

Prepared2026-10-17. **PENDING APPROVAL. No deployment/migration/activation is authorized by this document.**

Reviewed product source **e2e5169ff19ac268c0a0ad06994f67b41f69f949**, branch `codex/rafii-pinterest-production-prep-20261014`. [Diff](evidence/capabilities-candidate.patch) · [Cloud PASS](evidence/capabilities-validation-20261017.json) · [3302 input hashes](evidence/capabilities-source-hashes-20261017.json). JCB **qd2tzg2hn0**, remote/controller0,178.406s,463Python/51Node/7PG17.11 scripts/typecheck/lint36warnings0errors/build/synthetic browser. No full-project CI claim.

## Proposed single action

One new-source deployment and promotion to **https://rafii.io**, existing Vercel **prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L / team_PgXY5VdAYKcsv0RLoDPHscNq**. Canonical Supabase remains **postriff-phase2-private / buoyhkbodnhzngaotoel**. No new organization/project/database/subscription/payment or Git push.

This source corrects Pinterest's Rafii server-scheduling metadata, implements disabled native analytics through existing custody/metric workers and explains comment/reply API absence. The current account is disconnected. Deployment would install code and truthful capability explanations; **it does not grant publishing/analytics or make every capability Direct**.

Reuse existing app1615884 credentials and vault securely in deployment-only config, without logging/retaining/resetting shared secrets. Preserve the same original read-only actor/workspace/username and **1792269656 /20:40:56Z /16:40:56EDT** expiry; do not extend it. Keep all public/review/policy/Agent gates closed and `POSTRIFF_PINTEREST_ANALYTICS_ENABLED` absent/0. Preserve three services,300sAPI/660sphone timeouts and minute worker cron. Project-wide environment unchanged. Stop if expiry passes or current live source/config drifts; do not silently substitute another release.

Before promotion: fresh current-live qualification (last observed **dpl_sFLeor16mBEwc8NoNc49sxvFP1AP READY**), bound project/config check, deployed source file hashes, services/cron and health. No additional live OAuth or provider data operation is needed. After promotion verify exact deployment/source and flag-off connection UI. Do not relabel the synthetic/browser results as live feature acceptance.

## Excluded from this approval

No hosted SQL, metric feature activation, new consent/scopes/account access, Pin/board/section write, analytics provider call, actual schedule, Agent provider-data, Standard submission, public connections/canary/release or broad rollback. A real Pin still requires its own account/board/content/time/visibility/action approval. Current account returned0boards, so no destination is selected. The original read-only pilot is already complete and is not extended/reopened by this code proposal.

## Later separately reviewed analytics migration

Forward `20261017_pinterest_metric_reads.sql` SHA256 **a01f47d11595c42665c7aa2f1bfec41b6f0a23935ca5b4d58e639577cba8dbd7**; rollback SHA256 **dd9ab063275b8b2f15ec09a3f55daf1379238c7e8967e837faa6255de8c2baa2**. Disposable application/reapplication/empty rollback and data-preservation refusal PASS. **NOT APPLIED to production and not included above.** Actual activation also needs provider/release/policy authorization, three native read scopes, non-read-only custody, metric global/workspace gates and validated schema. No public release before Standard and production acceptance.
