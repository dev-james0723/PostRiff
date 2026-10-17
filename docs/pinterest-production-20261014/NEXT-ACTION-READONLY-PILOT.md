# Exact next external approval — private read-only Trial

Prepared2026-10-17. **APPROVED 2026-10-17; partially executed.** Local sync approval is fulfilled and remains standing for same-type local syncs. Master mission separately gates production configuration, SQL, deployment and live consent; the following exact bundle was subsequently approved by the human APPROVE reply. Its scope is preserved below; this is not approval for unrelated new source.

## Targets and account

Existing Vercel project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, team `team_PgXY5VdAYKcsv0RLoDPHscNq`, origin `https://rafii.io`; canonical Supabase **postriff-phase2-private / buoyhkbodnhzngaotoel**. Pinterest app **1615884**. Proposed Rafii workspace **568699ad-d66e-42b8-a7f1-e86d0c35ab02**, actor **b167161d-37f4-4bc3-ae22-2482c982e5a0**, Pinterest **@jamesaucreates**. Duration **4hours from recorded activation UTC**, no automatic extension. No new project/org/database/subscription.

## Reviewed operation

1. Recheck live deployment/source, canonical database identity/schema/privileges, exact owner/account and registered callback. Stop on drift; use authorized local sync/cloud validation if baseline changed. Do not deploy an older source over newer runtime. Final source/CI must match [FINAL-RECEIPT](FINAL-RECEIPT.md); approval covers only this reviewed candidate plus same-type verified baseline sync, not unrelated new product changes.
2. Apply only additive `migrations/postriff/20261014_pinterest_rate_budgets.sql`, SHA256 **9a9b20f0e41ce5ba65c1bf013ed9e427e4b60237dc1e9130ac9043253f56fce4**, transactionally after metadata preflight. No bootstrap, other migration, user-data copy or bulk deletion. Table has hashed budget counters, FORCE RLS and bounded server DML; no browser access.
3. Install existing app1615884 credentials securely, correct callback origin, and configure the exact actor/account/expiry plus explicit official-API read-only selectors listed in [pilot candidate](READONLY-PILOT-CANDIDATE.md). Reuse current vault key. Do not rotate shared secrets. Credential absence/inaccessible secure transfer is a blocker, not permission to expose them.
4. Deploy the exact cloud-tested candidate once to the existing project; confirm immutable deployment and configuration. Coordinate with existing deploy owners and prevent a partially configured older runtime from serving the trial. Keep public/Agent/write gates off. No Git push or remote merge is included.
5. With the approved operator, open Pinterest's official OAuth consent; human completes actual consent. Execute only profile/boards token exchange, identity, board reads, refresh, reconnect and disconnect. Requests use `https://api.pinterest.com`, two read scopes and100requests/UTCday cap. Stop on unexpected identity, eligibility, quota, security or source drift. No unattended actions.
6. Preserve redacted receipts and run read-only isolation negatives. End early on request or at expiry; disconnect removes local custody/future authority. Changes to pause/restore only this pilot's reviewed flags are included; broad rollback/deletion/new charges remain excluded. Do not drop the quota table automatically.

## Effects and limits

Shared production hosting/config and one new server-only quota table change. Existing encrypted normal grant/OAuth/profile/audit records are written for only the approved tenant/account. This is a private real Trial, not public release; no Standard entitlement/production-readiness claim.

No Pin, board mutation, sections, analytics, Agent provider data, scheduling, public connections, Standard submission, new resources, billing changes or payment. Existing provider consent removal uses Pinterest settings if desired; Rafii claims local disconnection only.

The linked preflight records the state before activation. Subsequent [quota apply](evidence/pilot-quota-production-apply-20261017.json), [deployment](evidence/pilot-deployment-20261017.json) and [real OAuth](evidence/pilot-real-oauth-20261017.json) receipts supersede its absent-configuration state. Human approval covers the exact account/window above; no additional deployment of newly added product code is implied.

## Execution update — 2026-10-17

Quota applied and C4Aqh deployment promoted to rafii.io. Window **16:40:56Z–20:40:56Z**, expires **16:40:56 EDT**; no extension. Real official token exchange and business identity read-back PASS for @jamesaucreates. Pinterest reused existing consent; no fresh consent-screen demonstration. Boards/refresh NOT RUN. Disconnect returned403 and awaits the human authenticator sign-in at Rafii; reconnect NOT RUN. Local boards/manual-refresh remediation is a new candidate, not deployed under this already-used single-deployment approval. See [next release candidate](NEXT-ACTION-BOARDS-REFRESH.md).
