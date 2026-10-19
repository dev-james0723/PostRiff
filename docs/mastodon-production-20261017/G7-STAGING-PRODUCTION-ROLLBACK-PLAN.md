# G7 — Staging without rafii.io domain cutover (NO DEPLOY AUTHORIZED)
Date: 2026-10-17 · Vercel project: postriff-phase2-private / prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L

## Actual Deployment Identity Read-Only

- rafii.io and www.rafii.io are verified; www redirects to rafii.io. The current rafii.io lookup returned READY Deployment dpl_2tFM29HomWyWcrzTqTtikWN6Pvti at https://postriff-phase2-private-gvudra5h2-jamesau0723-6572s-projects.vercel.app. Its connector metadata did NOT establish an immutable source commit.
- The latest **production-target** deployment list entry is dpl_7pc5Px6UnDfWpp73yvBXH1CGZDhn, READY, associated with PR #197 merge SHA 3efe6c2fd0c83e19395546c53aa71dd7ba02fa3b. It is NOT proof that rafii.io is aliased to this build; nor is it the Mastodon release candidate.
- Existing staging domain postriff-phase2-private-staging.vercel.app is associated with branch staging. Its isolation from Production backend, auth and Storage is NOT independently verified. Do not rely on this just because it says staging.

## Two-stage architecture; MUST preserve isolation

**A. Preview functional E2E — owner-only, isolated data:**
- After exact approval, use a reviewed Preview/staging environment with **separate** Supabase Auth, Storage, DB, encryption key and redirect origin; no Production key is copied or exposed. Never use staging database as Rafii Production.
- Do not reuse capydffkqjjdtbxphkgy (2026-10-13 Mastodon isolated preview, 65 migration records) as proof of backup or production schema parity; it is a preview, not an independently restored latest Production backup. Confirm lifecycle, cost and safe ownership before using.
- Stage owner-login OAuth via its own fixed HTTPS callback origin (server dynamically registers app binding). Test two independently administered Mastodon servers one account at a time, *only after user explicitly approves each grant*; no automated social write. Verify credentials never included in logs/screenshots.
- Review all egress: deployment preview URL, Vercel middleware/function on-demand cron, background workers, webhook callback endpoints. The existence of a preview URL alone doesn't make DB writes safe.

**B. Real Production-built artifact without domain switch — after independent approvals:**
- Supported Vercel method: prepare verified immutable source, protected reviewers + environment reviewers, verify exact project ID/team ID and audit runtime variables, create a production-target deployment with an explicit no-alias setting (--prod --skip-domain), then test its Deployment URL BEFORE promoting. Do not execute these commands during G7.
- Crucial: --skip-domain **only prevents custom-domain reassignment**. It does **not** disable Production environment variables, DB connections, background jobs, provider calls, or credentials. Use an explicit fail-closed configuration, tested migration/backup readiness and careful hosted endpoint allowlisting. Do not perform Mastodon OAuth, publish or destructive operations against a staging URL unexpectedly bound to Production.
- Archive exact source SHA, build artifact hash, Vercel Deployment ID/URL, target and domains, all nonsecret provider flags and isolated DB *identity only* (never secret values).
- Require operator review of stale and active alias differences (dpl_2t vs dpl_7pc); re-query immediately before proposed promotion.
- No automatic promotion via Git Integration, PR preview, branch update or deploy hooks until review and billing behavior are controlled. A new production-build *without alias* is still an external state change requiring separate approval.

## Release order (each is a separate consent gate)

1. Protected code review and backend migration SQL security; complete verified Production backup plus **independent Restore receipt**.
2. Review and separately approve exact 131/132/133 transaction on buoyhkbodnhzngaotoel with lock safety, custom SHA ledger updates, then verify RLS and existing Threads/Instagram continuity.
3. Owner-only provider OAuth acceptance (two independent Mastodon instances), token storage and revocation, zero real posts.
4. Explicit staged Deployment ID and no-domain step, then exact final promotion decision after QA and rollback simulation.
5. Limited invited Connect Beta, then separate Public Connect expansion. Publishing/scheduling flags must remain OFF until real approved effects pass.

## Rollback / data custody

- Document active rafii.io Deployment ID immediately before any external operation. Initial candidate fallback is dpl_2tFM29HomWyWcrzTqTtikWN6Pvti, but re-validate eligibility and alias before choosing it as rollback target.
- On problem: block **new** Mastodon OAuth through a reviewed feature gate, unassign or rollback an approved deployment to previously verified build. Never delete or down-migrate 131–133, never wipe credentials or existing unrelated platform connections.
- Stopping Rafii dispatch **cannot cancel provider-native pending schedules**. Reconcile their exact IDs and gain separate authorizations for cancellations. No real Mastodon schedule exists as of G7 verified 0 active Mastodon credentials, but re-query at release time.
- Investigate customer OAuth after rollback: whether old code can safely ignore retained Mastodon credentials. Notify affected customers only after human approval.

**G7 status:** Plan only; staging/production deployment NOT executed; rafii.io assignment unchanged by G7.
