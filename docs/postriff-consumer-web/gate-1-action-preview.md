# Gate 1 — exact action preview: migrations 004→007, env, deploy

**State: preview only. Nothing below has been executed.** Approval is per-step; I will stop after each step's verification and report before the next.

## Targets (exact)
- Supabase project **`buoyhkbodnhzngaotoel`** (us-east-1) — the same project that already holds 001+002 (`docs/postriff-phase-2/external-action-preview.md:8`). Migration 003 was never applied hosted; it is **not** part of this gate.
- Vercel project **`jamesau0723-6572s-projects/postriff-phase2-private`** (linked in `.vercel/project.json`); production alias `https://postriff-phase2-private.vercel.app`.
- Nothing else. No provider app, no OAuth grant, no post, no charge, no email.

## Pre-checks (read-only, I run first)
1. `vercel env ls` — confirm the five existing names are present (`POSTRIFF_SUPABASE_URL`, `POSTRIFF_SUPABASE_PUBLISHABLE_KEY`, `POSTRIFF_DATABASE_URL`, `POSTRIFF_SUPABASE_SECRET_KEY`, `CRON_SECRET`). Values are never printed.
2. Against the live DB via the pooled DSN: `SELECT tablename FROM pg_tables WHERE tablename LIKE 'pr_%'` → expect the 15 tables from 001+002 and **none** of 004–007 (`pr_invitations`, `pr_conversations`, `pr_oauth_transactions`, `pr_plan_terms`…). If any exist, stop and report.
3. `.venv/bin/python scripts/check_postriff_hosted_preflight.py` (structure/env-name preflight; prints names only).

## Step A — apply migrations (additive; each file is one transaction)
```bash
# DSN is pulled to a temp file from Vercel env and deleted afterwards; never echoed.
for f in 004_consumer_web_tenancy 005_consumer_web_ideas 006_consumer_web_channels 007_consumer_web_billing; do
  psql "$POSTRIFF_DATABASE_URL" -v ON_ERROR_STOP=1 -q -f migrations/postriff/$f.sql
done
```
Expected result: 25 new `pr_*` tables (40 total), no data rows except the seeded `pr_plan_terms` (4, all `proposed`) and `pr_metric_definitions` (12). Existing rows untouched; owner memberships backfilled with all four permission flags = true (there is one owner row today at most, synthetic users were deleted).

Verification: re-run the pre-check query; `SELECT count(*) FROM pr_plan_terms` → 4; `SELECT role, can_publish FROM pr_memberships` → owners true.

Rollback (only if you ask; not automatic): the `drop table` lists in receipts C/D/B plus the 004 constraint restore in receipt A, in reverse order 007→004. No customer data exists in these tables at that point.

## Step B — set two environment variables (Production + Preview)
```bash
KEY=$(.venv/bin/python -c "from postriff_phase2.oauth import CredentialVault;print(CredentialVault.generate_key())")   # generated locally, shown to no one
printf '%s' "$KEY" | vercel env add POSTRIFF_CREDENTIAL_KEY production
printf '%s' "$KEY" | vercel env add POSTRIFF_CREDENTIAL_KEY preview
printf 'https://postriff-phase2-private.vercel.app' | vercel env add POSTRIFF_PUBLIC_BASE_URL production
```
Notes: the same key in preview and production is deliberate for this private beta (one vault); rotate later with the custom domain. `POSTRIFF_PUBLIC_BASE_URL` on preview is omitted so preview deployments cannot start OAuth. **No provider client IDs are set** — adapters stay unmounted, the worker stays `DisabledHostedSocial`, and `/api/workspaces/{id}/channels` lists no providers.

## Step C — deploy
```bash
vercel deploy            # preview URL first
# verify, then:
vercel deploy --prod     # promotes to https://postriff-phase2-private.vercel.app
```
Build inputs already in place: `requirements.txt` (adds `cryptography==50.0.1`), `vercel.json` unchanged, web bundle from `npm run build:hosted` (Vercel builds it; 626 kB advisory).

Verification on the preview URL, then production:
- `GET /api/health` → `configured: true`
- `GET /api/catalog` → `authMode: "supabase"` (never `dev`)
- `GET /api/ideas/models` → only `deterministic-preview` qualified
- `GET /api/tools` → `publicInvokeEnabled: false`
- `GET /api/cron/worker` with the cron secret → `externalExecution: false`
- `.venv/bin/python scripts/validate_postriff_hosted_preview.py <url>` — creates two **synthetic** Supabase users, runs the lifecycle, deletes them (same script and cleanup as Phase 2).
- Browser: sign in with a real email OTP as **me?** — no: signing in with your identity is your action; I will only run the synthetic validation. You then sign in yourself on a phone.

## What this gate does NOT do
No provider app, OAuth consent, publication, model call, image generation, payment, email to anyone, MFA change, domain change, or founder-data import. After it, the product on the URL is exactly what you clicked locally, with real Supabase identity instead of the dev shim and with **no connectable providers yet** (Stage 2 of `sellable-saas-plan.md`).

## Time
~20 minutes of execution plus your two approvals (after pre-checks; after preview verification).
