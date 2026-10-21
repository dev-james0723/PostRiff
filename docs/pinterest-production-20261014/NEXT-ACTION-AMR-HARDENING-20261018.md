# Exact next approval — authentication hardening candidate

Prepared 2026-10-18T15:59:06.975577+00:00. Source **e40f3869df6143c30c7b53f774598e25b9809c12**, LOCAL ONLY. Current live product remains66c5cedd /5Z6. Existing CI/build/promotion budgets are exhausted; this is a distinct new source and needs its own applicable approval.

The five-file candidate fixes a reproduced sensitive-action freshness defect, updates its regression expectation, adds seven targeted controls, registers them plus existing Agent permission tests in the established cloud script, and corrects only Pinterest public notes. All providers using the shared sensitive-action gate are affected: routine token issuance no longer substitutes for sign-in/MFA. The600-second limit, verified identity, MFA, OAuth scopes, credentials and production flags are unchanged. Users with stale sign-ins must authenticate normally.

## Proposed bounded operation

1. One sanitized **JCB test** run from this exact isolated worktree, using `scripts/cloud-pinterest-release-delta-validation.sh`. It covers the new controls, shared hosted/auth and Agent permissions, existing Pinterest tests, disposable PostgreSQL, frontend typecheck/lint/build and synthetic browser checks. Existing three temporary routing mappings may be set to this script and must be restored byte-for-byte. No push, production secrets, provider traffic, release workflow or new resources. **8vCPU;45minutes; one submission; no automatic retry. Compute spending ceiling US$1.08; existing-plan cache/test-result charges additional and not yet measured.** If pricing/configuration cannot fit this reviewed ceiling, stop rather than enlarge it.
2. **Only if that exact candidate passes**, one Vercel build without initial domain assignment and one qualified promotion to existing rafii.io. Keep canonical postriff-phase2-private/buoyhkbodnhzngaotoel, App1615884, exact private policy and four scopes,3services/cron/Node24/API300s/phone660s. Reuse credentials through secure handling only. No project-env edit, SQL, public flags, new resources or subscription. Existing-plan Vercel charges remain unverified. Verify actual uploaded source hashes, live source compatibility, alias/project target, health and own snapshot before/after promotion; stop on concurrent production/config drift.

This proposal grants **zero Pin creates, schedules, board writes, Standard submissions or public enablement**. The original private policy expires **18Oct14:00EDT /18:00UTC**, unchanged. Do not start work that cannot safely finish within its authorized window; no expired helper or old budget may be reused. A fresh approval must name any extended time or changed policy separately.

## Acceptance and rollback

Cloud results for the new revision are NOT RUN. Local red/green evidence is in [the candidate receipt](evidence/auth-freshness-candidate-20261018.json). New deployed checks must prove normal fresh sign-in still authorizes the intended action and stale AMR fails, without exposing credentials or attempting a live bypass. Prior immutable image and scoped provider evidence remain valid for their original inputs.

If a new deployment fails qualification, do not promote. If a promoted artifact regresses, pause only this policy's future actions and, after shared compatibility checks, promote existing **5Z6 /66c5cedd** without rebuild. Preserve all receipts, immutable image, journal/quota and database state. That rollback retains the newly documented freshness defect; keep public access closed and pursue a corrected candidate. No destructive SQL or Pin deletion.

Pin publication and time-specific scheduling remain separate concrete approvals in NEXT-ACTION-REAL-PINS-20261018.md. Submission requires the final actual video and policy package review. No new approval has been inferred from this document.

## Actual execution update — 2026-10-18T16:45:48.491862+00:00

Human approvedCI+conditionaldeployment. Initial33ws CI failedfixture; separately approved5213recovery kg26 PASS. Runtimee40unchanged; conditional build/promotion unused. No additional deployment approval needed for this same runtime/scope. Protected human masked Copy still needed.
