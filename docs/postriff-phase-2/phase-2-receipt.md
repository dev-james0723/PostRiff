# Phase 2 receipt

**Phase 2 incomplete — the local foundation and hosted production lifecycle are validated; live image generation and live social-provider qualification remain.**

2026-09-14. Your instruction to move on was recorded as an explicit local Phase 2 exception. **No invitations were sent. Phase 0 remains incomplete (0/5 full interviews).**

## Delivered locally

- Separate [Phase 2 runtime](http://127.0.0.1:4328/) and private database, preserving the existing alpha data.
- Google/email sign-in fixtures, expiring sessions, linked recovery, export/deletion and a one-time 14-day Studio/Assist trial contract.
- Reviewed artwork brief, consent, up to three procedural previews, saved selection/focal point and deletion. No image model was called.
- Channels with separate identity/capability states; decoded-image/source/timezone preflight; exact immutable approvals; durable per-account jobs and receipts.
- List, Calendar and Kanban views with verified, failed and uncertain synthetic outcomes. Recovery does not blindly resubmit uncertain work.
- Additive Supabase RLS/Storage schema, PostgreSQL repository, hosted logout/deletion tombstones and server-side provider request candidates.
- Workspace-specific content types, optional 11-type Creator pack, ten formats, four creation paths, exact proposal review, preflight-bound manifests, and private versioned templates.
- Hosted WSGI composition with Supabase PKCE session verification, private immutable media storage, and a PostgreSQL cron worker candidate.
- Vercel Services manifest, Python entrypoint/runtime pins, safe environment template, hosted Pillow media decoder and secret-safe deployment preflight.

## Hosted Preview

The approved [hosted deployment package](hosted-deployment-preparation.md) is live on a protected Vercel Preview at `https://postriff-phase2-private-i09esnd9x-jamesau0723-6572s-projects.vercel.app`. Deployment `dpl_3oFbMAJBfJBP7nfJrijADGonPtdX` is Ready. Supabase project `buoyhkbodnhzngaotoel` is healthy in `us-east-1`; the additive migration produced 13 forced-RLS tables and the private `postriff-private` bucket. All five runtime values are Preview-only.

The lifecycle upgrade is live on a newer protected Preview at `https://postriff-phase2-private-qednj2wbi-jamesau0723-6572s-projects.vercel.app`. Deployment `dpl_CFRFBACsLDGmfFcmTiqRvN83HKX7` is Ready. Migration 002 adds two forced-RLS, service-only lifecycle tables and trial replay protection. The expanded hosted test passed refresh, same-workspace restore, private export, logout and refresh-token denial, account deletion and tombstone retention. Cleanup removed both temporary Auth users and all synthetic rows; current synthetic user, revocation and tombstone counts are zero.

Production deployment `dpl_3cA573dgFvhXipWn4KxjfZLe6tY4` is Ready at `https://postriff-phase2-private.vercel.app`. All five runtime values are configured with their intended Production visibility. Vercel registered `GET /api/cron/worker` at `* * * * *`; five successive scheduled invocations on the final deployment returned HTTP 200. The complete two-user Production exercise passed again after the final hosted-label correction: session refresh, same-workspace restoration, private export, tenant/media isolation, mutation, media deletion, logout/refresh denial, account deletion, tombstone retention and fail-closed remote worker execution. Cleanup removed both temporary Auth users and database rows. The visible Production interface now truthfully identifies itself as a hosted private beta. Evidence: [production lifecycle validation](evidence/production-lifecycle-validation.jsonl), [cron logs](evidence/production-cron-logs.txt) and [production promotion status](evidence/production-promotion-status.json).

Deployment attempt `dpl_BXPa5ddTYxVNmsmgx7AbnC4uA2NA` failed before readiness because local `.phase3-build-venv` and desktop artifacts entered the Python bundle. The upload and function boundaries now exclude those artifacts plus `vendor`; the successful replacement uploaded 22.4 kB of changed source and produced a 19.61 MB Python function.

Two synthetic users proved distinct workspace bootstrap, own-workspace access, 403 cross-workspace isolation, durable mutation, private media upload/read/delete and 403 cross-media isolation. Cron authentication returned 401 without a secret and the authorized worker stayed fail-closed with `externalExecution: false`. Validation removed all synthetic database rows and both temporary Auth users.

An initial source upload was interrupted before the final `.vercelignore` boundary was added. It created no deployment record. The successful deployment used the verified 89-file exclusion-bounded source set, but retention of partial content-addressed chunks from the interrupted attempt was not independently verifiable. The local `broker.key` has not been rotated because rotation could invalidate existing local vault data and was outside this deployment approval.

## Validation

**146 Python tests + 72 frontend tests passed**, along with TypeScript, hosted Vite build and the remote Production build. The safety suite covers revoked approvers, viewer writes, stale manifests, cancellation during rate limits, malformed receipts and secret-safe provider exceptions. The pinned Pillow hosted decoder was exercised against a real RGBA PNG and produced a metadata-free JPEG rendition. Two-user local PostgreSQL RLS/Storage policy checks passed. The real local PostgreSQL repository passed persistence, membership, rollback, stale-revision, viewer-write and worker crash-recovery tests. Desktop/mobile UI checks cover the type library, Creator pack, guided proposal, workspace type selection, preservation notice and private-template save. Git validation is unavailable because the installed tree has no Git metadata; scoped backups/hashes/diff are supplied. The hosted Vite build has one non-blocking 589 kB pre-gzip chunk advisory.

[Acceptance ledger](acceptance-results.md) · [hosted preparation evidence](evidence/hosted-preparation-results.json) · [content-type increment](content-type-template-results.md) · [source diff](evidence/source-diff.patch) · [browser evidence](evidence/browser-results.json)

## Remaining Phase 2 work

Hosted refresh, session revocation, export, account deletion, private media and one-minute worker cadence pass the synthetic Production exercise. LinkedIn image upload/reconciliation and Instagram container/publication evidence contracts are implemented and tested locally; provider-specific hosted OAuth/token storage/refresh/revocation, hosted transport and live qualification remain unfinished. Live image-model execution also remains unfinished.

The approved `$0.08` Vercel AI Gateway project-budget command was attempted once. Vercel rejected it before mutation because project budgets have a `$1` minimum; a follow-up listing confirmed zero project budgets. No image request was sent and no charge occurred. The live callback tunnel was replaced with `https://look-constant-majority-nitrogen.trycloudflare.com/callback`; the local Studio service and tunnel boundary are healthy. The Meta callback is allowlisted, the Instagram tester invite is accepted, and local Studio OAuth now verifies `@jamesaucreates` as a Media Creator with the requested scopes. A read-only identity and publishing-quota test returned `publish_ready`; no Instagram post was submitted. This is a local Studio grant and route check, while hosted PostRiff still has no Instagram or LinkedIn grant. LinkedIn remains locally verified as James Au with `w_member_social`. Evidence: [external gate attempt](evidence/external-gate-attempt.json).

A free Supabase project, protected Vercel Preview and configured production deployment were created under the approved scope. No new real OAuth consent, email/SMS, image charge, customer-data upload, real social publication or billing action occurred. [External-action preview](external-action-preview.md) records the executed foundation and unresolved provider actions.

## Resume and boundaries

Start/restart locally with `python3 scripts/postriff_phase2.py`. Build with `cd studio/web && npx vite build --config vite.alpha.config.ts`. The browser demonstration uses a fictional workshop. The running local worker requires this Python process and laptop; it is not live cloud scheduling. The disposable PostgreSQL validation server is stopped after checks.

Continue with the failed integration rows in the acceptance ledger. **Do not start Phase 3 yet.** Phase 4 billing and production metering remain out of scope. Customer-demand claims still require the missing real research.
