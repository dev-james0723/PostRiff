# PostRiff Cloud — remaining jobs to a sellable SaaS

**Date:** 2026-09-16 · **Baseline:** everything in `consumer-web-release-receipt.md` (code complete and locally verified for the §27 scope; zero external gates opened). This plan lists only what is still missing, in dependency order, with who can do it and what "done" means. Effort is a rough founder-time estimate, not a promise.

## Stage 0 — Put the real thing on a URL (you + me, ~1 day)
| # | Job | Owner | Done when |
|---|---|---|---|
| 0.1 | Apply migrations 004→007 to Supabase `buoyhkbodnhzngaotoel` (see the gate-1 action preview) | you approve, I run | `scripts/check_postriff_hosted_preflight.py` passes against the live DB; `\dt public.pr_*` lists 40 tables |
| 0.2 | Set Vercel env: `POSTRIFF_CREDENTIAL_KEY` (generated), `POSTRIFF_PUBLIC_BASE_URL` | you approve, I run | `/api/health` → `configured: true` after deploy |
| 0.3 | Deploy web + API to a **preview** URL, then promote | you approve, I run | `validate_postriff_hosted_preview.py` synthetic run passes |
| 0.4 | Enable MFA/passkey in Supabase Auth; confirm email templates/sender domain | you (dashboard) | sign-up with a non-founder email works from a phone on cellular |
| 0.5 | Custom domain + TLS on Vercel (e.g. `app.postriff.com`) | you | HTTPS callback URL is final — providers need it before app review |

## Stage 1 — Real writing (the product's core value) (~1–2 weeks incl. waiting)
| # | Job | Owner | Done when |
|---|---|---|---|
| 1.1 | Choose the server-side model route: Vercel AI Gateway (recommended: one key, per-model cost, no provider lock-in) or a direct OpenAI project key | you | account + key exist; monthly budget set (Gateway needs ≥$1) |
| 1.2 | Implement `ServerModelRuntime` behind `AgentRuntime` (already stubbed as `server-openai`, `qualified: false`): structured JSON output, 60 kB context, 45 s timeout, ≤2 attempts, price quote → reservation → settle | me | unit + PG tests; `list_supported_models` reports it qualified; Standard reasoning available |
| 1.3 | Per-source **cloud egress consent** UI (the `egressConsent: ["cloud"]` switch already enforced by `project_context`) | me | a source without consent is excluded from a cloud run, visibly |
| 1.4 | Quality pass: 10 real sources × EN/繁中, compare with fixture; tune prompt/skills | you + me | you accept ≥8/10 first drafts as "useful without heavy editing" (improvement SPEC target) |
| 1.5 | Image generation: keep blocked until 1.1 budget ≥ provider minimum; then wire `media.generate_image` through the credits gate | me | one generated candidate stored with provenance + AI label |

## Stage 2 — Real channels (external reviews dominate) (~2–6 weeks, mostly waiting)
| # | Job | Owner | Done when |
|---|---|---|---|
| 2.1 | LinkedIn: create PostRiff app, add "Share on LinkedIn" product, register `https://<domain>/api/oauth/linkedin/callback`; set `POSTRIFF_OAUTH_LINKEDIN_CLIENT_ID/SECRET` | you | non-founder test member connects and a text post publishes + reconciles → then `_REVIEWED=true` |
| 2.2 | Meta app (Threads use case): App Review for publish/insights/replies scopes; privacy policy URL, app icon, screencast | you (+ me for copy/screencast) | review approved; same end-to-end test → `_REVIEWED=true` |
| 2.3 | Instagram: Business Verification → App Review (`content_publish`, `manage_insights`, `manage_comments`) | you | same |
| 2.4 | LinkedIn image upload path (candidate code exists) + Threads/IG image containers via signed URLs | me | image post verified on each |
| 2.5 | Connector monitoring + kill switch: per-provider feature flag, OAuth failure/scope-drift counters | me | flag disables a provider without hiding receipts |
| 2.6 | Optional no-review alternate: Bluesky (PKCE+PAR+DPoP) if a Meta review stalls | me | — |

## Stage 3 — Money, legal, support (~2–3 weeks)
| # | Job | Owner | Done when |
|---|---|---|---|
| 3.1 | Payment provider: run Vercel Marketplace discovery (`vercel:marketplace` skill), pick (Stripe via Marketplace is the default candidate), review tax/refund/cancel terms | you decide, I implement adapter | webhook signature/replay tests pass against the live provider's test mode |
| 3.2 | Decide plan terms: flip chosen `pr_plan_terms` rows from `proposed` → `active` (Studio $19 / Assist $39 are still proposals) | you | `Usage & Plan` shows an active price; checkout works in test mode |
| 3.3 | Privacy notice, ToS, DPA/subprocessors, retention, tax — qualified review | lawyer/accountant | signed-off documents linked from the app |
| 3.4 | Support paths as pages: account recovery, payment issues, export/deletion, disconnect, failed publication; support inbox | me + you | each path has a working page and a receipt |
| 3.5 | Deletion/backup drill on real Supabase incl. Storage (DB backups exclude Storage) | me | restore drill receipt with RPO/RTO measured |

## Stage 4 — Reliability & polish before charging (~1–2 weeks)
| # | Job | Owner | Done when |
|---|---|---|---|
| 4.1 | Customer-visible status/incident surface + analytics freshness; sanitized logs policy; runbooks | me | status page + 3 runbooks (OAuth drift, stuck job, budget stop) |
| 4.2 | Calendar grid, `Schedule N posts` aggregate approval, compact preflight control + remaining preflight rules, document/image attachment in Ideas, Dashboard four cards | me | browser-verified desktop + mobile |
| 4.3 | Automated a11y (axe) + Lighthouse PWA pass; real-device install; push permission UI | me | reports saved in evidence |
| 4.4 | Rate limiting on all routes; dependency scanning in CI; secrets rotation drill (`POSTRIFF_CREDENTIAL_KEY` rotation → re-auth path) | me | — |

## Stage 5 — Evidence before "paid beta live" (design partners) (~4 weeks)
| # | Job | Owner | Done when |
|---|---|---|---|
| 5.1 | 3 ICP creators, each with one real licensed source, timed end-to-end; watch for self-initiated return within 7 days (improvement ECONOMICS.md) | you | 2 of 3 return unprompted |
| 5.2 | Then 10 users × 4 weeks: activation ≥60%, D7 ≥50% (candidate targets), n/d recorded | you | metric contract met or plan revised |
| 5.3 | Observed end-to-end journey with the founder laptop **off**, second workspace isolation, phone on cellular | you + me | receipt |
| 5.4 | Decide launch: only when Stages 1–4 gates are green and 5.1–5.2 evidence exists | you | "paid beta live" claimable |

## Explicitly out of scope until after paid beta
All 33 channels; automatic/bulk replies and moderation; agency/client hierarchy; PostRiff Bridge/desktop; native apps; cross-platform unique reach; unlimited generation.

## Critical path
0 → 1.1/1.2 and 2.1/2.2 can run in parallel → 3.1–3.3 in parallel with 2.x waiting periods → 4 → 5. The two long poles are **Meta reviews** and **legal review**; start both in week 1.
