# PostRiff Cloud — consumer web release receipt (candidate, not a launch)

**Date:** 2026-09-16 · **Scope:** architecture spec §27 first sellable scope · **Verdict:** **not consumer-ready; not paid-beta live; not publicly launched.** All work is implemented and verified locally; every external gate remains open. This receipt says exactly what was observed and how.

## What was observed, and how

| Layer | Observed state | Evidence |
|---|---|---|
| Tenancy, roles, invitations, sessions, step-up, throttling | real code on disposable PostgreSQL, two-tenant negative suite | `receipts/milestone-a.md` |
| Ideas conversation, safe events, four-class source policy, tools registry, quick-start | real code; deterministic fixture runtime only (no model request, $0) | `receipts/milestone-b.md` |
| OAuth transactions, PKCE, encrypted custody, capability taxonomy, connector executor, multi-destination schedules | real code with provider doubles; no provider app exists | `receipts/milestone-c.md`, `connector-audit.md` |
| Entitlements, append-only ledger, budgets, webhooks, privacy, analytics, audience | real code; fixture payment provider labelled as such | `receipts/milestone-d.md` |
| Six-destination shell, Ideas/Channels/Usage/Analytics/Audience screens, PWA, mobile | real code, browser-verified on the **local dev harness** (real hosted code, synthetic identity/providers/storage) | `receipts/milestone-e.md` |

Test evidence (2026-09-16): Python **186/186**; PostgreSQL suites `repository`, `safety`, `isolation`, `ideas`, `channels`, `billing` and Phase-3 **all pass**; web **75/75**; `tsc` clean; hosted build OK. Source diff and hashes: `evidence/changed-files.json` (35 added, 19 modified), `evidence/source-diff.patch`, originals in `evidence/before/`.

## Classification of the §27 scope

| Item | Observed real | Synthetic / fixture | Blocked (external) | Unavailable |
|---|---|---|---|---|
| Cloud signup + workspace | code, PG | identity in dev harness | Supabase-observed signup on a deployment | — |
| Ideas + attachments | code, PG, browser | runtime is fixture | real model route (account/key/cost) | real-model quality |
| Catalog / packs / guided creation / templates | code, tests | — | — | mobile re-verification this pass |
| Skill routing + controlled tools | registry | — | isolated runner (platform) | — |
| Brief + ≥2 variants | code, PG, browser | fixture text | — | — |
| Image upload/generation, alt, preview | upload path, previews | — | generation cost gate / provider minimum | — |
| Smart preflight | blocker/warning model | — | — | full 16-rule set, compact control |
| Calendar + list scheduling | list, multi-destination API | — | — | calendar grid UI |
| 2–3 direct integrations | LinkedIn / Threads / Instagram code | provider doubles | provider apps, reviews, non-founder end-to-end | — |
| Exact approval + receipts | code, PG | hosted synthetic | real publication | — |
| Basic post performance | ingestion + screen | canned insights in dev | reviewed connector | — |
| Usage / subscription / export / disconnect / deletion | code, PG, browser | fixture payment provider | live provider, legal/tax | — |
| Responsive PWA | browser 375×812 + desktop | — | real device, cellular | automated a11y run |

## Gates that must be resolved before "paid beta live" (none executed by this work)
1. Apply migrations 004→007 to the hosted Supabase project (additive; rollback per receipt). Set `POSTRIFF_CREDENTIAL_KEY`, `POSTRIFF_PUBLIC_BASE_URL`. Deploy. Run `scripts/validate_postriff_hosted_preview.py`.
2. Qualify a server-side production model route (account, key custody, price quote, cost ceiling) — until then Quick/fixture only.
3. Create PostRiff's LinkedIn app; Meta app with Threads use case → App Review; Instagram Business Verification → App Review. Set client secrets; flip `_REVIEWED=true` only after a non-founder account publishes and reconciles end to end.
4. Select a payment provider (Vercel Marketplace discovery + terms), implement its adapter, configure webhook secret.
5. Qualified legal review of privacy notice, terms, retention, tax.
6. Observed end-to-end cloud journey with the founder laptop off, a second workspace, and a phone on cellular; MFA/passkey enabled in Auth settings.

## Known product gaps carried (not blockers to the gates above)
Calendar grid; `Schedule N posts` aggregate button; Dashboard four-card layout; document/image attachment UI in Ideas; compact preflight control + `tip` severity; status/incident surface; feature flags; backup-restore drill on real cloud storage; runbooks; push permission UI; support paths (account recovery, payment, failed publication) as customer-facing pages.

## Rollback / recovery
Hunk-level via `evidence/source-diff.patch` after verifying "after" hashes; delete added files listed in `evidence/changed-files.json`; rerun the unit suite and PG scripts. No schema was applied anywhere but disposable clusters.

## How to see it locally
```bash
cd /Users/ouxianxing/Documents/James-Au-Studio && (cd studio/web && npm run build:hosted) && LC_ALL=C .venv/bin/python scripts/postriff_dev_hosted.py --port 4331
```
Then open http://127.0.0.1:4331 → **Set up my agency** → **Enter dev workspace**. The dark banner marks everything synthetic.


## Dev API on your Mac: run it from a terminal, not the desktop app's Run button

The `postriff-api` entry in `.claude/launch.json` works for browsing the app, but a process the
Claude desktop app starts that way runs under the app's sandbox helper
(`Claude.app/Contents/Helpers/disclaimer`), which refuses outbound network connections. Web
research (Exa search, Jina Reader) then always fails with "Web search was unavailable", and the
agent drafts without facts. Start the API in Terminal instead:

```bash
cd /Users/ouxianxing/Documents/James-Au-Studio && LC_ALL=C POSTRIFF_DEV_WEB_ORIGIN=http://localhost:3100 .venv/bin/python scripts/postriff_dev_hosted.py --port 4331
```

Also note the harness recreates its disposable Postgres on every start, so a restart wipes the
dev workspace (voice, identity, sources, conversations); re-seed before drafting again.
