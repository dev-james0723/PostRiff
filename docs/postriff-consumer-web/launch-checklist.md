# PostRiff — launch checklist (code complete → paid beta)

**Date:** 2026-09-16 · **Branch:** `consumer-saas` · **State:** everything below marked ✅ is implemented and verified locally (unit 229/229, PostgreSQL suites pass, `web/` builds 82 routes, browser-checked at desktop and 375 px). Items marked 🔑 can only be done by the founder because they need accounts, credentials, money or a signature.

## What is done (✅)

### Public site (`web/`, Next.js 16)
- Landing (`/`), pricing, channel directory + 33 channel pages, docs (5 guides), changelog, status, contact.
- Legal: privacy, terms, data deletion, security — grounded in `privacy.py`; visible “draft — pending legal review” banner driven by `LEGAL_REVIEW_STATUS` in `web/src/config/legal.ts`.
- SEO: metadata on every page, Open Graph + Twitter images, robots.txt, sitemap.xml (incl. channels and docs), web manifest, icons, JSON-LD.
- Honesty rules enforced: no fabricated social proof; hosted channels labelled “Assisted · review pending”; prices carry “introductory pricing” while plan terms are `proposed`.

### App (`/app/*`)
- Auth: Google + email one-time code (Supabase PKCE), callback route, session guard in `proxy.ts`, invitation acceptance (`/invite/[token]`).
- Shell: sidebar with grouped navigation and RBAC filtering (mirrors `permissions.py`), Cmd+K, workspace switcher, header, contextual info sidebar, dark mode + themes.
- Pages: Overview, Ideas, Calendar, Pipeline, Library, Channels (+ OAuth return), Queue (approvals + jobs), Analytics, Inbox, Members (invite/roles/grants), Roles, Audit log, Brand & voice, Profile (sessions), Notifications, Usage & plan (Stripe checkout/portal), Privacy & data (export/diagnostics/delete), API & integrations.

### API (Python, unchanged surface + new routes)
- Stripe: `POST /api/workspaces/{id}/billing/checkout` and `/portal`; signature-verified webhook with replay/out-of-order safety; plan availability gate (D3).
- Email (Resend): invitation, welcome, trial ending/ended, subscription activated, payment failed — deduped in `pr_notifications`; reminder sweep on the cron tick.
- Migration 008 (`provider_price_id`, `pr_notifications`).
- Origin guard honours `X-Forwarded-Host`.

### Verified end to end (dev harness)
Connect → voice → draft → schedule → approve → worker publish → verified → analytics, in the new app; see `receipts/consumer-saas-e2e.md` (two backend defects found and fixed on the way).

### Deployment status (2026-09-16)
- **Preview deployed** from commit `dfedbae`+: https://postriff-phase2-private-ibjrdxss2-jamesau0723-6572s-projects.vercel.app (Vercel deployment protection applies to anonymous requests). Verified through the protection bypass: `/api/health` → `configured: true`; `/api/catalog` → `authMode: supabase`; `/api/ideas/models` → only `deterministic-preview` qualified; public routes and `robots.txt` serve.
- **Vercel env set**: `POSTRIFF_CREDENTIAL_KEY` (production + preview, sensitive), `POSTRIFF_PUBLIC_BASE_URL` and `NEXT_PUBLIC_APP_URL` (production, `https://postriff-phase2-private.vercel.app`), `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (production + preview).
- **Migrations 004 → 008 applied** on Supabase project `buoyhkbodnhzngaotoel` (org dfestival.office@gmail.com) through the SQL editor in the founder's Chrome session (`hosted-004-008.sql`, "Success. No rows returned"). Verified in the same editor: 41 `pr_*` tables, `pr_plan_terms` = 4 rows (all `proposed`), `pr_notifications` = 0, `pr_metric_definitions` = 12.
- **Production promoted**: https://postriff-phase2-private.vercel.app (`vercel deploy --prod` from a clean export of `bcf2d8f`).
- **2026-09-16, second release** from a clean export of `eb527b3` (model choice + cloud consent + draft editing + first-run checklist; agent chat Home, intent router, Claude Code route, memory files): preview https://postriff-phase2-private-j06uy6cqi-jamesau0723-6572s-projects.vercel.app verified, then `vercel deploy --prod` → production `dpl_GgQGML76yiYYev7DwWsoZ59q5fPE` aliased to https://postriff-phase2-private.vercel.app. Verified on production through `vercel curl`: `/api/health` → `configured: true`; `/api/catalog` → `authMode: supabase`; `/api/ideas/models` → only `deterministic-preview` qualified, no CLI agents reported; `/`, `/auth/sign-in`, `/pricing` 200; `/app/*` → 307 to `/auth/sign-in?next=…`. Python suite at that commit: 268 tests OK. Not applied: no new migration was needed (schema still 001–002 + 004–008).

## Founder-only gates (🔑), in order

| # | Gate | Where | Done when |
|---|---|---|---|
| 1 | ✅ Migrations 004 → 008 applied to the hosted Supabase project | `migrations/postriff/hosted-004-008.sql` | `scripts/check_postriff_hosted_preflight.py` passes against the live DB |
| 2 | ✅ Vercel env for the API: `POSTRIFF_CREDENTIAL_KEY`, `POSTRIFF_PUBLIC_BASE_URL`, `CRON_SECRET` | Vercel → postriff_api | `/api/health` → `configured: true` (verified on preview) |
| 3 | ✅ Vercel env for the web app: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_APP_URL` (optional Sentry vars) | Vercel → postriff_web | sign-in page renders in Supabase mode on the preview URL |
| 4 | Custom domain + TLS; set `POSTRIFF_PUBLIC_BASE_URL` / `NEXT_PUBLIC_APP_URL` to it | Vercel | providers get the final HTTPS callback |
| 5 | Supabase Auth: enable Google provider, email OTP template, MFA/passkey | Supabase dashboard | non-founder signs up from a phone |
| 6 | Stripe: products + prices, customer portal, webhook, env vars; flip plan terms to `active` with `provider_price_id` | `docs/postriff-consumer-web/billing-and-email.md` | test-mode checkout completes and `Usage & plan` shows the live plan |
| 7 | Resend: verified domain, `RESEND_API_KEY`, `EMAIL_FROM` | same doc | invitation email arrives |
| 8 | Provider apps: LinkedIn app (`w_member_social`), Meta app (Threads use case → App Review; Instagram Business Verification + App Review). Privacy/terms/data-deletion URLs are now live for the forms. Record a 60–90 s screencast of connect → draft → approve → publish. | provider consoles | `POSTRIFF_OAUTH_<ID>_REVIEWED=true` only after a non-founder account publishes end to end |
| 9 | Legal review of privacy, terms, data deletion (jurisdiction, refund policy, transfer mechanism); then set `LEGAL_REVIEW_STATUS = 'reviewed'` and confirm `LEGAL_CONTACT_EMAIL` / `supportEmail` | counsel; `web/src/config/legal.ts`, `web/src/config/site.ts` | banner removed |
| 10 | Model route for real writing (Vercel AI Gateway recommended) — until then drafts are the deterministic preview | `sellable-saas-plan.md` Stage 1 | `/api/ideas/models` reports a qualified model |
| 11 | Sentry DSN (optional) and product analytics review (`@vercel/analytics` is wired) | Vercel | errors visible |
| 12 | Design-partner evidence before calling it “paid beta live” | `sellable-saas-plan.md` Stage 5 | 2 of 3 partners return unprompted |

## How to run it locally
```bash
# API on a disposable PostgreSQL (real hosted code, simulated identity)
LC_ALL=C .venv/bin/python scripts/postriff_dev_hosted.py --port 4331
# Web (proxies /api to 4331)
cd web && npm run dev -- -p 3100
```
Then open http://localhost:3100 — the sign-in page offers “Enter dev workspace”.

## Known gaps carried (not blockers for the gates above)
- Public API keys, MCP server, n8n node: documented as roadmap on `/app/account/api`; not built.
- Desktop companion for the 30 local channels: not built; pages say so without dates.
- Analytics and Inbox show real limited states; real data needs a reviewed connector.
- Preflight rule set, document/image attachments in Ideas, push notifications: unchanged from the founder alpha.
