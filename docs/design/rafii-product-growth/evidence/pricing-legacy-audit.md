# Pricing v2 residual legacy-copy audit (W-PRICING-WEB, Tasks 7–9)

Branch `claude/rpg-pricing-web` (base `5b53186a`), 2026-10-01. PRD R-COM-04 / AC05; spec §13 and plan Task 9 ("re-run the
repository search … produce a residual-hit receipt explaining every intentional legacy occurrence").

## Searches

Run from the repository root (customer-facing web code first, then the whole repository):

```
grep -rn -i -E "writing ?batch|writingBatches|studio assist|US\$19|US\$39|\$19\b|\$39\b|\b1900\b|\b3900\b|after trial|14-day|two plans|top[- ]up|media credit" web/src
grep -rn -i "\btrial\b" web/src
grep -rIl -i "writing batch|studio assist|US\$19|US\$39|\$19/mo|\$39/mo|after trial|two plans" . --exclude-dir=node_modules --exclude-dir=.git
```

How a v2 workspace is kept away from legacy words: public pages pick their copy from `NEXT_PUBLIC_PRICING_CATALOG`
(`web/src/config/plans.ts` + `web/src/config/pricing-copy.ts`; `legacy` unless exactly `v2`); in-app surfaces branch on the
server's `billingMode` (`web/src/lib/billing/mode.ts`). `web/tests/pricing-surfaces.test.mjs`, `billing-mode.test.mjs`,
`billing-v2-ui.test.mjs` and `work-surfaces-v2.test.mjs` assert that the v2 branches contain none of these words.

## A. Legacy-only runtime copy (intentional: reached only by the legacy catalog or `legacy_allowances`)

| Location | Text | Reached only when |
|---|---|---|
| `web/src/config/plans.ts:38-85` (`plans`, `TRIAL`) | Studio US$19, Studio Assist US$39 (`priceCents` 1900/3900), "100 AI writing batches per month", 14-day trial | `NEXT_PUBLIC_PRICING_CATALOG` is not `v2` (today's catalog, unchanged until activation) |
| `web/src/config/pricing-copy.ts:59-137` (`LEGACY_PRICING_FAQ`, `afterTrial`, `legacyCopy`) | pricing hero/footnote/FAQ, "Two plans.", trial FAQ, CTA band, hero note, "Writing batches" preview stat, terms §6, sign-up trial picker ("$19/mo after trial", "Adds AI writing batches", "Start a free trial"), help "Allowances"/"Trial" | catalog `legacy` (`marketingCopy('legacy')`); `pricing-surfaces.test.mjs` pins it word for word to today's site |
| `web/src/config/pricing-copy.ts:139-160` (`legacyCompareRows`, `LEGACY_TRIAL_CARD`) | "AI writing batches / month", "Media credits / month", trial card | pricing page `LegacyPlans` only |
| `web/src/components/marketing/plan-card.tsx:45` | "Start {14}-day trial" | legacy `PlanCard`; v2 renders `V2PlanCardView` |
| `web/src/features/billing/allowances.tsx:219-224` | "AI writing batches", "Media credits" meters | billing view `legacy_allowances` branch; the v2 branches pass `only='capacity'`, which drops both |
| `web/src/features/billing/billing-copy.ts:18-39,174-180` | info panel "Trial", "Writing batches"; legacy plan-card allowance rows (`PLAN_ALLOWANCES`) | `infoContentFor('legacy_allowances')`; legacy plan list (`planListKind === 'legacy'`) |
| `web/src/features/billing/billing-model.ts:279` (`allowanceNote`) | "Needs a writing batch", "Used a media credit" ledger notes | `Ledger allowanceNotes={mode === 'legacy_allowances'}` (also the CSV column) |
| `web/src/lib/attention.ts:163,181` | "Trial ends in N days"; "Writing allowance used up" / "N writing batches left" | trial: not Free (`free_preview`); batches: `allowanceReminder` kind `batches` = legacy without a wallet |
| `web/src/features/ideas/ideas-view.tsx:94,109`; `capture-card.tsx:240`; `account/models/writing-now.tsx:29` | "No writing batches left", "N writing batches left …" | `writingAllowance(...).kind === 'batches'` (legacy only) |
| `web/src/features/account/models/catalog.ts:117`; `models-view.tsx:28` | "Writing batches" cost badge/line; models info | `costClassKey` → `batches` (legacy); v2 gets "Managed credits" / "Creator plan" |
| `web/src/features/account/notifications-view.tsx:29-30` | "Trial ending", "Trial ended" emails | hidden for `free_preview` / `managed_credits` |
| `web/src/features/account/profile-model.ts:28`; `workspace/audit/audit-model.ts:210,242-244` | "Studio Assist" plan name; "Started on a trial of …" | the workspace's own plan/audit event is legacy (a v2 Free workspace reads "Free" / "Started on Free.") |
| `web/src/features/coworker/notifications/labels.ts:24` | "Your trial is ending" | the `billing.trial_ending` event, emitted only for legacy trials |

## B. Contract fields and identifiers (not copy)

`web/src/lib/api/types.ts:1507` (`Entitlement.writingBatchesRemaining`), `LedgerEntry.chargeBatch`, `trialPlan`;
`web/src/config/plans.ts:171,183` (`writingBatches: 0`, `mediaCredits: 0` inside `V2_CATALOG` entitlements — they mirror
`GET /api/plans` exactly and are held to the contract fixture; no surface prints them); `web/src/lib/billing/mode.ts:203`
(reads `writingBatchesRemaining` only on the legacy branch); `web/src/types/index.ts:17` and `web/src/lib/auth/access.tsx`,
`web/src/lib/workspace/provider.tsx` (`'trial'` plan id); `web/src/lib/agent-runtime/commands.ts:152` ("media credits",
"top up" are search keywords that route a question to Usage & plan, not displayed text); the site-agent guide manifest
keywords (`web/src/lib/site-agent/guide-manifest.json:13`, twin of the API file; its summary is now mode-neutral).

## C. Comments, tests and fixtures

Doc comments that name the legacy path (e.g. `pricing/page.tsx:57`, `billing-mode`/`ledger` comments) and the web tests
(`web/tests/*.test.mjs`, browser scenes) that assert the legacy text stays unchanged or seed legacy fixtures. Python
fixtures in `tests/phase2/*` and `tests/test_postriff_plan_display.py` exercise legacy terms on purpose.

## D. Historical records

`migrations/postriff/007_consumer_web_billing.sql` and the `hosted-004-008.sql` bootstrap snapshot seed the legacy
`studio-v1`/`assist-v1`/`assist-bounded-v1` rows that existing subscribers still reconcile against (048 marks them
`catalog_state='legacy'`, never deleted). Design notes under `docs/` (postriff-app-update-plan, ui-simplification-audit,
launch-20260923, postriff-consumer-web, raffi-time-back, postriff-phase-*, superpowers spec/plan) are dated history.
`studio/web/src/founder/Cloud.tsx:155` is the founder's internal console, not a customer surface.

## E. Not changed here — remaining v2 risk (follow-ups, outside this slice's surfaces)

These are customer-visible and still speak batches or media credits to every workspace. They need an owner decision or
an API change, so they are reported rather than patched:

1. **Agent image hint** — `web/src/features/agent/conversation-view.tsx:732` ("Uses 1 media credit") and the `/image`
   slash-command description in `web/src/lib/agent-runtime/commands.ts:76`; API twins
   `src/postriff_phase2/agent_runtime_v2/{live.py:89, manager.py:85, commands.py:40}` and the image capability detail in
   `src/postriff_phase2/ideas.py:287`. Image availability is per deployment, not per plan: in credit mode the composer
   already disables the toggle, but a Free or CLI-writer workspace can still see the hint (the API then refuses before
   any provider call). Needs the v2 image pricing decision (spec §6.6: quote/reserve/settle in credits).
2. **Site-agent help and context (API)** — `src/postriff_phase2/site_agent/help/billing.md` ("Allowances, writing batches
   …", trial section) and `help/privacy-and-models.md:22`; `site_agent/compose.py:170,324-325` puts "writing batches
   left" into the agent's plan context, so the agent could tell a Creator workspace it has 0 batches. Needs a
   `billingMode`-aware rewrite on the API side.
3. **API error text** — `src/postriff_phase2/billing.py:194` "No media credits left in this plan." (legacy path; v2 image
   reservations are refused earlier by the credit authority).
