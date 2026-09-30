# Rafii Founder Control

This work adds a separate disabled-by-default founder boundary and read-only Control application from the same repository. It does not mount founder routes in the consumer deployment. The authoritative v2 design is `docs/superpowers/specs/2026-09-29-rafii-founder-control-center-v2-design.md`, SHA-256 `1ababaaff637a04be105fa41caf1eb57f071c1e57819eb39116c030fea993002`. Runtime catalogs and schemas are read directly from the supplied tech-pack; they are not reauthored elsewhere.

Current continuation: the everyday founder workspace, persistent isolated Demo, global record search/pagination and approved test rename path are locally database/browser verified. Founder Home's committed work is integrated under Advanced. See [the current release receipt](founder-workspace-release.md), [the secure staging candidate](founder-workspace-staging-candidate.json) and `evidence/business-workspace/verification.json`. Hosted qualification is pending. Earlier milestone receipts and counts below remain historical evidence.

## Local verification

Use Python 3.12, Node 24.15.0, PostgreSQL 17, the pinned root dev requirements and Control dependencies. No `.env` is loaded by the test runner. Provider credentials are removed from the child test environment.

```sh
PYTHONPATH=src:tests .control-venv/bin/python -m unittest discover -s tests/control -p 'test_*.py'
.control-venv/bin/python scripts/rafii_control_pg.py
PATH=/opt/homebrew/opt/node@24/bin:$PATH npm --prefix control-web test
PATH=/opt/homebrew/opt/node@24/bin:$PATH npm --prefix control-web run typecheck
PATH=/opt/homebrew/opt/node@24/bin:$PATH npm --prefix control-web run lint
PATH=/opt/homebrew/opt/node@24/bin:$PATH RAFII_CONTROL_ENABLED=1 RAFII_CONTROL_ORIGIN=http://localhost:4549 npm --prefix control-web run build
PLAYWRIGHT_BROWSERS_PATH="$PWD/.control-browsers" .control-venv/bin/python scripts/rafii_control_pg.py --browser
```

The PostgreSQL runner creates its own cluster on an available loopback port, applies the existing RLS harness plus 049, 051, 052 and 053 twice, runs the restricted-role tests, then removes only its own disposable cluster. Browser mode starts and terminates its own Next/WSGI children. Synthetic identity injection exists only under `tests/control/`; those files are excluded from the deployment candidate. The browser harness uses no paid model, email, push or financial provider.

## Separate deployment candidate

`scripts/rafii_control_package.py --output /absolute/fresh/directory` builds an allowlisted candidate and a hash manifest. It refuses an existing output directory. It copies `vercel.control.json` as the candidate's deployment configuration, preserves the existing Rafii CSS and pure auth/agent contracts, and includes only the required schemas/catalogs. The consumer `.vercelignore` excludes the entire Control runtime. No project link, deployment, production promotion or environment change is performed by packaging.

The separate project must use `RAFII_CONTROL_ENABLED=0` until its operators, roles, identity project, origin and data policy are qualified. The server origin must be exact; production requires an ops host. Set `RAFII_CONTROL_ENVIRONMENT` explicitly. An enabled Preview requires verified distinct staging/production Supabase project refs and the exact staging URL. Preview must never inherit production or consumer authority.

Enabling the deployment requires `RAFII_CONTROL_SESSION_DSN` and `RAFII_CONTROL_READER_DSN` for distinct, reviewed non-superuser logins with only their corresponding role memberships; `RAFII_CONTROL_SUPABASE_URL` and its publishable key; and matching public identity settings for the sign-in page. Non-local DSNs must bind to the declared environment's Supabase project, use `sslmode=verify-full` with reviewed certificate roots and port 5432 session mode, and reject redirect/options configuration. Pooler login names must carry the same project ref. Do not copy service-role, consumer database, Stripe, OpenAI or notification credentials. Role enrollment and an actual founder UUID binding require a separately reviewed operation. Migration 049 creates **no operators or credentials**. It must not be applied to production through a generic runner.

## Authority and data limits

Founder access requires a current server-owned operator UUID/capability/epoch, a server-verified Supabase AAL2 identity and a genuine MFA AMR timestamp within five minutes at exchange. Password/passkey/refresh `iat` is not step-up proof. The opaque founder cookie is host-only, HttpOnly, Secure and SameSite Strict; only its hash is stored. Each request checks operator status/epoch, environment, revocation, upstream tombstones/revocations, 30-minute idle and eight-hour absolute lifetime. Unsafe requests also require exact Origin and CSRF proof. Rate budgets and content-free audit events are persisted.

The analytical reader is separate from session persistence and ingestion. A non-login projection owner bypasses tenant RLS only while holding SELECT on explicit canonical safe columns; it has no customer body, credential, ledger mutation or login grant. It must never be granted to an application login. All Control tables force RLS, deny browser/service-role grants and use environment policies. The fixed identity function has an empty search path and restricted execute ACL. Reader transactions are read-only with a five-second timeout and capped rows.

Metric definitions are proposed in the authoritative pack. Their query foundation enforces named metric IDs, dimensions, native-currency separation, grain compatibility, bounded filters/timezones/intervals/output, and durable receipts. It currently returns unavailable values until reviewed source/policy qualification exists; it does not present zero or a synthetic figure as a production result. Golden definition kernels test annual/monthly normalization, cash movement deduplication and mature retention denominators without changing billing/accounting behavior. Analytical events retain event/receive/project times and deduplicate with conflict detection; historical replay produces no alerts. Canonical billing and immutable credits remain the sole financial authorities.

Founder Rafii has its own principal namespace, persisted runs and bounded read/proposal tool registry using existing agent contracts. Deterministic named reads are available; paid model generation, scheduled investigations, customer memory and effect executors are absent. Recommendation contracts preserve evidence, hypotheses, unknown impact, digest, measurement, approval and expiry. Engineering evidence keeps suspected/reproduced/candidate/checks/merge/deploy/production verification distinct; code-check dispatch and patch/deploy actions remain disabled.

The approved test-workspace rename requires fresh MFA, its own capability and an expiring exact grant. Migration 053 creates no live grants or enrollment. No refund, ban, deletion, deployment, migration, code write, unrestricted impersonation, raw SQL or plaintext secret viewer is mounted. Private customer content remains suppressed until a later scoped support-access implementation.

See `implementation-log.md`, `evidence/verification.json`, `security-review.md` and `spec-gap-review.md` for exact evidence and remaining gates. A local test or artifact is not a production deployment or an activated integration.
