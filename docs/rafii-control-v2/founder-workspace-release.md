# Founder workspace implementation and release receipt — 2026-09-30

**State: implemented and verified on disposable PostgreSQL; source upload and hosted qualification pending. This is not a production-readiness claim.**

This is the continuation of the authoritative Control v2 application, not a separate prototype. The current user request explicitly authorizes implementation, commit/push and release through review. Earlier milestone instructions holding source upload are historical. It does not authorize unreviewed hosted migrations, privileged account enrollment, new provider spend or live customer messages.

## Source and coordination

- Scoped branch: `codex/rafii-founder-completion-20260930`, base `c16747efcaa298a05477d1fda680d23cb9108dad`.
- Original Control branch/worktree and the unrelated dirty consumer checkout were preserved. No stash, reset, clean or unrelated edits were absorbed.
- Founder Home `861e20d1f2b5da519d6b21810b4a7642ca55ac93` was integrated from its committed source. Its exact checks/receipts, trust regressions, deadline handling and terminal audit remain under Advanced → Delivery overview. Migration 052 remains its reservation; the business workspace uses 053.
- The duplicate implementation chat ceded ownership and retained its clean checkout. No competing Home implementation was written.
- Existing foundation PR: https://github.com/dev-james0723/PostRiff/pull/83 (draft, head `be140fd`; it does not contain these changes). Source staging has succeeded; no new PR, new commit or deployment has yet been created.
- Git metadata resides in the preserved sibling checkout. The initial scoped `git add` failed outside this chat's writable roots. A subsequent reviewed escalation succeeded and the scoped files are staged. No permission workaround was used; there was no recorded automatic approval rejection.

## What changed

The everyday workspace now uses Home, Customers, Workspaces, Billing & credits, Support, Product and Connections. Advanced retains the existing diagnostic/evidence tools. Home has a few canonical counts, an attention queue, next actions and recent admin activity. Responsive navigation, native keyboard-accessible details, explicit loading/empty/error states and a single connection-readiness page replace everyday diagnostic clutter.

Demo is unmistakably labeled. Its linked fictional customers/workspaces/subscriptions/payments/usage/tickets/activity use the same screens and query/action boundary as Live. Each verified founder has separate persistent Demo JSON under RLS in the existing Control schema. Rename, simulated payment, request resolution/reopening and reset have locked revisions, UUID replay handling and append-only content-free action records. No Demo action changes canonical Rafii rows, contacts a provider, sends a message or charges money. Live never falls back to Demo.

Live reads fixed column-allowlisted views of the canonical Rafii tables. Customer/workspace names, ownership, membership counts, subscription terms/status, usage and data-request metadata preserve the existing contracts. Payment receipts are conditional on the actual credit-order schema. Search/status filters and 50-row pagination query the database globally; direct record lookup and linked workspace names work beyond the old 200-row snapshot cap. Search input is literal and parameterized. Missing schemas/privileges and read failures produce explicit safe errors. Home counts use the complete dataset; its short attention list prioritizes billing issues.

The only new canonical write is an approved test-workspace name change. It requires the existing verified AAL2 founder session, fresh MFA, `workspaces.test.rename`, an expiring exact operator/workspace/environment grant, a current revision and a UUID request ID. A restricted database function updates only the workspace name, preserves private state, increments the canonical revision and durably records the action before acknowledgement. Retry returns the same result; stale/conflicting requests fail. Pending account deletion, revocation, missing grants and reader-role invocation are denied. No hosted capability or grant was activated.

Required Live gaps are explicit on Connections: missing payment schema, credit balance/definitions and approved support ticket access. Usage ledger entries are not described as a credit balance. Live Support currently exposes canonical data-request metadata, not ticket conversations or outbound replies. No new financial definition or support database was invented. Demo rejects free-text audit targets and unused action values. The CI workflow aligns the browser install/cache path, includes 052/053 triggers and builds the exact-content archive.

## Verification

| Check | Result / evidence |
|---|---|
| Backend/database/security | 97 passed, zero skipped, on a fresh disposable native PostgreSQL cluster; 049/051/052/053 applied twice |
| Canonical integration | Created fictional records through `pr_bootstrap` and `PostgresWorkspaceRepository.command`; exact rows appear in Control; UI rename reflects in `PostgresWorkspaceRepository.get`, then is restored |
| Retry/privacy/authorization | Stable replay and action count; private canary excluded; session reader denied canonical body reads; unapproved/stale/revoked/non-founder/unauthenticated requests rejected |
| Search and pagination | 205 additional fictional customer rows; 50-row pages do not overlap; record beyond original cap found; linked names and literal injection-shaped search verified |
| Frontend contracts | 8 passed, zero failed |
| Typecheck / lint / production build | Passed; lint zero errors and warnings; Node 24 / Next 16.3.5 production build |
| Business browser | Real Next → Python → restricted PostgreSQL; 1440 and 390px, every destination, filters/details, Demo mutations/reset, Live isolation, canonical rename/reflection/restore, keyboard/axe, logout/CSRF and explicit 503 passed |
| Preserved Founder Home browser | 390/768/1440px; 9 axe checks with zero violations; receipt/checks/chart/table and loading/empty/stale/partial/503/429/query selection passed |
| Function deployment artifact | Actual Vercel Python builder archive: 933 files, 8,554,159 bytes; SHA-256 `4f1220a6ba6ccc8fa24587bb2d066a62fbc13e03eb8ace3b5e117bd695f861dc`; all 49 packaged source files match exact input hashes; allowlist excludes tests, secrets and consumer runtime |

A packaging-harness defect was also repaired: using its input directory as builder output silently truncated source files. Separate build/input directories and exact ZIP-content hashes now prevent that false-positive artifact qualification. Earlier milestone artifact receipts are preserved as historical records, not reused as current proof. All identities in this evidence are synthetic; the database and canonical repository are real. Hosted Supabase password/TOTP login and the designated real account have not been exercised. Error acceptance deliberately injects a 503 in one browser check; actual permission failure is also separately proven in PostgreSQL. Canceled Next speculative prefetches are counted separately from unexpected request failures, which are zero.

Evidence: `evidence/business-workspace/verification.json`, `browser.json`, `database-final.log`, `database-and-browser.log`, `next-build.log`, `control-artifact.json`, `engineering/browser-results.json`, `engineering/observed-journey.json`. Desktop/mobile screenshots: `founder-demo-1440.png`, `founder-demo-390.png`, `founder-live-local-1440.png`, `founder-live-local-390.png`. `workflow.webm` records the actual local synthetic browser journey; it is not a hosted recording.

Reproduce with the existing Python/Node/PostgreSQL/dependency runtimes:

```sh
PLAYWRIGHT_BROWSERS_PATH=/absolute/path/to/control-browsers .control-venv/bin/python scripts/rafii_control_pg.py --browser
# Optional preserved Home acceptance, with an approved read-only capture:
PLAYWRIGHT_BROWSERS_PATH=/absolute/path/to/control-browsers .control-venv/bin/python scripts/rafii_control_pg.py --browser --home-browser --capture /absolute/path/to/allowlisted-check-capture.json --evidence-dir /absolute/path/to/fresh-evidence
npm --prefix control-web test
npm --prefix control-web run typecheck
npm --prefix control-web run lint
RAFII_CONTROL_ENABLED=1 RAFII_CONTROL_ORIGIN=http://localhost:4549 npm --prefix control-web run build
```

## Deployment observation and exact remaining work

The currently observed consumer production is READY at https://postriff-phase2-private-k55gtq11j-jamesau0723-6572s-projects.vercel.app, commit `1acd88a8b77c5e8a3f2b877dd927e755c2900a56`. It is the consumer deployment, not this Control workspace. A read-only GitHub comparison confirms the consumer target is 16 commits ahead of the original integration base, affecting only conversation-preview files and their checks. Its migration directory contains no numbered 049/051/052/053 files; this is source coverage, not hosted migration history. A listing of the connected Vercel team's 20 projects found no dedicated Control project. The available Supabase connector exposes only an unrelated project and cannot read Rafii's migration history. Marketplace categories/discovery failed with `fetch failed`; no integration was installed or switched.

1. Git staging permission is resolved. Reconcile the latest `consumer-saas` release base, run affected integration/release checks, commit/push scoped source and open/attach the review PR. Do not overwrite the concurrent consumer release or automatically merge the foundation draft.
2. Complete the reviewable `founder-workspace-staging-candidate.json`: approved dedicated Control project/team/origin and distinct staging/production identity refs, restricted session/reader DSNs and matching public sign-in configuration. Install values in the secure environment store, never chat. No consumer/service-role/provider secret is admitted to Control.
3. Read actual hosted migration history and approve only the missing pinned 049/051/052/053 steps plus restricted login/operator enrollment. The migrations are candidates only; no hosted apply occurred. Qualify role memberships, certificates, dataset binding, AAL2, routing and rollback before enabling Control.
4. Resolve required credit-balance qualification and Live support-source/scope. The panel does not conceal these incomplete workflows behind optional labels or fake values.
5. Verify deployed login/logout, every destination and non-founder rejection. The designated owner-approved account is `jamesau0723@gmail.com`. Resolve its verified UUID and exact test workspace, grant only the expiring scoped rename permission, record original name/revision, rename through Control, verify back in Rafii, restore and verify again. Capture deployed screenshots/recording/evidence and then assess promotion through the established process.

Intended Control routes after the origin is approved: `/sign-in`, `/control/command`, `/control/command?mode=demo`, `/control/customers`, `/control/workspaces`, `/control/billing`, `/control/support`, `/control/product`, `/control/settings`, `/control/advanced`. Login uses the designated founder's existing password and enrolled authenticator code. There is no synthetic login or Demo bypass on a hosted deployment. No usable deployed Control URL or production-readiness proof is available yet.

No real account was read or changed, no hosted migration/configuration/integration was enabled, and no provider charge, message or paid-model call occurred.
