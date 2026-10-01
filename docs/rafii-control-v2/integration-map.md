# Current integration map and baseline

Implementation base: `consumer-saas` at `d91660b7936a5158b820914107306ad4a1e51c2d`, verified against successful provider release records before worktree creation. Canonical checkout remained at `468811b73d28b4389f931519827c05d0e6c8abfb` with 525 changed paths at inspection. Active worktrees/branches were inspected without absorbing their changes. Migration 049 was unclaimed in inspected refs/worktrees before commit; 047 and 048 remain reserved for existing work.

| Existing authority | Reuse in Control | Activation state |
|---|---|---|
| Supabase auth and existing identity helpers | `SupabaseSessionCandidate`, verified claims and redirect denial; canonical tombstones/revocations | Server verification implemented; hosted journey not run |
| Profiles, workspace memberships and subscriptions | Read-only column projections of canonical rows | Disposable PostgreSQL verified; no real accounts read or modified |
| Stripe/billing and immutable credits | Preserve canonical accounting; pure financial golden kernels only | No provider credential, new webhook writer, refund or ledger mutation |
| Agent runtime v2 typed contracts | Founder-specific read/proposal registry and result shape | Deterministic local intelligence; paid model and customer context absent |
| Notifications | Preserve existing notification service as future sender authority | No email/push/audience dispatch introduced |
| Sentry, GitHub Actions and Vercel | Read-model schema/source-health/stage foundation and existing release gates | Read-only preflight records observed; no live ingestion or code dispatch connected |
| Existing Next/React/TanStack/Recharts/Rafii CSS | Separate frontend with in-memory founder cache and accessible table alternatives | Production-mode local synthetic browser verified |
| Existing PostgreSQL/RLS and consumer release tooling | Disposable schema, full regression groups, source-bound receipts and actual function builder | Local only; no production DSN/migration/deployment |

The observed production deployment was Ready: `dpl_uwCTSjT1Tr56yftdvGy5xp9ny2uP` on `postriff-phase2-private`, with existing Next/Python/phone services and worker cron. This was a provider metadata observation, not an authenticated production acceptance journey. Base release evidence: GitHub Actions runs [36623516044](https://github.com/dev-james0723/PostRiff/actions/runs/36623516044) and [36623634575](https://github.com/dev-james0723/PostRiff/actions/runs/36623634575).

Control has its own allowlisted deployment configuration and no cron. The existing consumer deployment excludes all Control runtime/UI/configuration source. Actual local function archives verify this separation. A dedicated Control project and qualified staging authority remain missing; deployment is not inferred from packaging.
