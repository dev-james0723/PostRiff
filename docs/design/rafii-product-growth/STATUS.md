# RAFII Product Growth v2 — status

States: `not_started → implemented → local_verified → staging_verified → production_deployed → production_verified`,
plus `blocked` / `failed` / `not_run` with a reason. Data mode (`demo|synthetic|live`) is separate from environment
(`local|staging|production`). A requirement is never marked done because a document changed. "local_verified" below
means: focused unit tests + disposable PostgreSQL 17 groups on a private port, synthetic providers, Python 3.12, on the
integrated branch unless a row says "worker branch". Web TypeScript is checked only in CI on this machine (D-017).

Last update: 2026-10-01 · branch `claude/rafii-product-growth-v2` · PR #87 (draft, base `consumer-saas`) · integrated head `ceff036c`; production `dpl_4F4d2CNxXqh37viSo2gTDBYZDb5c` @ `047d024e` merged in (`2a6c13ef`).

## Program gates

| Gate | State | Evidence |
|---|---|---|
| G0.1 integration map | local_verified | `DECISIONS.md` D-001…D-007; production `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` @ `dcb5bcdc` |
| Pricing v2 + Inbox v1 merged | local_verified | merges `8726adbd`, `575caaf9` |
| Slices merged | 7 of 7 | results `de727483`, relationships `d16e9652`, visual pack `c5c91d90`, series `38abb86c`, intake `b6eac5e2`, pricing web `e8a68703`, briefs/proof `7e4815ce` |
| Local unit + web node tests | passed | slice and affected modules after each merge; web node 605/605; oxlint 0 errors |
| PR #87 CI on `6db0b877` | **release gates passed in full** (Python 3,128+ tests, every PG group, web contracts, types/lint/isolated production build, copy audit, function archive, secret scan, dependency audits, real local browser/API/DB integration — run 36937116339); preview window passed; browser scenes fail only at the growth harness start (below) |
| PR #87 CI on `d2469a9f` | typecheck + lint + preview window: **passed**; browser scenes: Automations now passes, but the growth harness step fails because Next 16 refuses a second `next dev` in `web/` (W-BROWSER fixing via `POSTRIFF_DIST_DIR`); release gates: running | GitHub Actions runs 36934793626, 36934793633, 36934793624 |
| Vercel preview | `dpl_2xQHeEv1XfQenwPaWepNQFN59Lr6` @ `d2469a9f` READY (staging-isolated); pricing page legacy and unchanged; `/api/growth-features` → `{"firstWeek": false}`; found and fixed `/api/plans` 500 on a pre-048 database (`c8ccf2a6`) | `vercel curl`, runtime log `UndefinedColumn` |
| Whole-branch review | completed, fixed, and the fixes re-reviewed (6 medium / 12 low found in the fixes, all fixed: `84a52f4a`, `rpg-fix-web-2` `8b7da243`, `5471accb`) — first review: billing 2 high/5 medium/4 low; backend 3 medium/9 low; web 3 high/29 medium/~50 low; briefs/proof 3 medium/4 low. Fix branches merged: `claude/rpg-fix-relationships` (`763ef98e`), `claude/rpg-fix-slices` (`bb0fad5c`), `claude/rpg-fix-billing` (`dbb2f7e4`), plus coordinator follow-ups (080 owner-only endpoint, ended-legacy offer, credits-aware catalog, D-029) | merged head `8b04c02a`: unit 3,984 OK; PG groups for every touched area pass; web node 795/795; oxlint 0 errors |
| Browser journeys for slices (AC37/AC39) | **passed on the integrated head** `ceff036c`: `Rafii browser scenes` run 36956968532 green (Chromium + WebKit, every scene); growth journeys 200 checks / 0 failures / 0 warnings on `claude/rpg-browser` run 36955698601 — first week, results, follow-ups, series, visual packs, intake, proof, brief, pricing v2 at 1440/768/390, EN + zh-Hant, keyboard-only step, axe (no serious/critical), no horizontal scroll. Not run: Creator credits (no managed-credit path in the harness), brief item actions (no seeded evidence), zh-Hant pricing (English-only page) | `web/tests/growth-v2-browser.cjs` |

## Requirements

| Req | State | Code / tests | Next step |
|---|---|---|---|
| R-COM-01 catalog & legacy | local_verified | backend Tasks 1–6; web: one catalog module equal to `contracts/pricing-catalog-v2.json` (`postgres_pricing_catalog_contract`, `pricing-catalog.test.mjs`), v2 pages behind `NEXT_PUBLIC_PRICING_CATALOG=v2`, legacy copy pinned | CI typecheck/build; live Stripe activation is James's |
| R-COM-02 one cost authority | local_verified | Radar, Weekly slots and now Growth AI (credit bridge `761e0d95`: quote → reserve → settle once; `postgres_growth_free_preview_v2` credit-bridge tests ×3) + web confirmation before a Creator Growth run (`94dfc9cb`) | browser check of the confirmation on preview |
| R-COM-03 Free boundary | local_verified | 1 Post Doctor check + 1 recent-20 Genome per workspace lifetime; no Radar paid I/O; no AI drafting in Weekly/first week | platform-preview policy needs James's approval |
| R-COM-04 consistent promises | local_verified | one catalog projection for public/app/checkout; top-ups unsellable; no "trial" language under v2; JSON-LD only for purchasable offers; in-app billing by `billingMode` | CI build; remaining legacy wording listed in `evidence/pricing-legacy-audit.md` (image "media credit" hint, site-agent billing help) |
| R-FWR-01 continuation | local_verified | `postgres_first_week` AC06/AC07, `growth-v2-continuation.test.mjs` | browser on preview/staging |
| R-FWR-02 guided first week | local_verified | AC08 tests | live paid drafting needs an authorized workspace |
| R-FWR-03 resume/approvals | local_verified | AC09/AC10 tests | browser |
| R-FWR-04 raw intake | local_verified (text PDF, SRT/VTT, synthetic transcriber); audio `blocked` | `source_uploads/*`, migration 087; `postgres_source_uploads` (108 checks, worker branch), 14 node tests | transcription route needs James's provider/model/budget approval (D-014); bucket `rafii-source-uploads` must be created before release |
| R-REL-01/02 | local_verified | migration 081; `postgres_relationships`, `_reply`, `_migration` re-run against the integrated results slice; won picks or records a declared result (`f9987a36`); follow-up email localized in 4 locales | browser (390/768/1440, keyboard) |
| R-OUT-01..03 | local_verified | migration 080; `postgres_results` (25), signing/model unit tests, webhook contract | live first-party connection needs a customer endpoint |
| R-SER-01/02 | local_verified (worker branch PG; unit on integrated) | series in workspace planning state, projected to `pr_campaigns` (no migration 082, D-021); `postgres_series` (8 checks) | integrated PG run in CI; browser |
| R-VIS-01..03 | local_verified (export path); queue handoff `blocked` | migration 083; Pillow + bundled Noto Sans TC; `postgres_visual_packs` (AC22/AC23); publisher guard refuses multi-image jobs | a publisher must be verified for carousels before queueing (CAROUSEL_VERIFIED empty) |
| R-BRF-01/02, R-PROOF-01/02 | local_verified | migration 084; `postgres_briefs_proof` (17 groups, AC24–AC27, AC34) re-run on the integrated branch with the real results/visual-pack modules; unit 405 OK; web gated by `briefs`/`proof` | browser journeys; staging |
| R-ENG-01/02 | local_verified | `growth_v2_routes` (dispatch/public/cron); 9 slice tools registered through `growth_v2_agent_tools` (voice parity, scopes); array schemas declare items | per-slice browser coverage |
| R-ENG-03 | local_verified (disposable) | migrations 080, 081, 083, 084, 087 additive with forced RLS; `rls.sql` loads them in order; 082 unused (D-021); pre-048 readers guarded (`postgres_pricing_catalog_pre048`) | runner `scripts/product_growth_release_migrate.py` pins all eight files (not executed) |
| R-MET-01 dictionary | local_verified | `metric_definitions.py`; 20 Founder catalog rows generated by `scripts/growth_metric_contract.py` in Founder's own vocabulary; checked read-only by Founder Control's main-checkout session against PR #88 (no id collisions) | PR #88 owner appends the rows to `catalogs/metrics.json` (not `metrics.d/`) |
| R-MET-02 paid conversion | local_verified | cash-paid from history, refund-adjusted variants, `test_metric_definitions`, `postgres_growth_fleet_v2` | `dataState=partial` until `pr_invoices` (Founder P1) lands |
| R-MET-03 events/costs | implemented | one taxonomy (`growth_events`); emitted by first week, results (ingested/reversed), relationships (followup_outcome), series (episode_accepted), visual pack (accepted/exported); intake emits audit rows only | briefs/proof events with W-LOOP; cost lineage via Founder `business_usage_v2` |
| R-NFR-01..04 | partially verified locally | trust boundaries, consent/retention and bounded jobs covered by slice PG groups; features never queried while off (growth-features gate); a11y lint clean | browser a11y/layout journeys (W-BROWSER); p95 bounded-read measurement needs staging (blocked on migrations) |

## Live blockers (exact owner action)

| Blocker | Effect | Owner action |
|---|---|---|
| Production deploy authority for this branch (contains Pricing v2 / Inbox v1) | No production deploy | James: explicit superseding permission naming the deploy (D-007) |
| Production migrations 047, 048, 050, 080, 081, 083, 087 | New tables absent in production | James: approve each one-off sha-pinned runner |
| Supabase Storage bucket `rafii-source-uploads` (private, ≤30 MB, PDF/WAV/MP3/M4A/OGG) | Raw intake reports storage unavailable | James: approve creating the bucket in staging, then production |
| Free platform-preview budget (`POSTRIFF_GROWTH_PLATFORM_PREVIEW`) | Free first-value runs refuse before paid I/O | James: approve the policy JSON (route, caps) |
| Live Stripe Prices / Creator checkout | No new paid sale | James: live commercial activation per the Pricing v2 runbook |
| Founder P1 `pr_invoices` (057) | Paid metrics `partial` | Founder P1 session (PR #88) |
| Transcription route for raw audio | Audio intake refused before upload | James: approve provider/model + budget |
| Verified multi-image publisher | Carousels export only; never queued | Engineering + a provider verification run, then James's activation |
| Creator use of the main Rafii agent | Text/browser agent turns have no credit authority under v2, so every Creator turn would be refused | Product decision (per-turn or per-conversation credit limit) + engineering, before Creator activation |
| Tracking-link destinations (D-027) | Any workspace could front any HTTPS site from Rafii's domain | James: choose verified domains, an interstitial, or accept with abuse reporting |
| Failed Free preview attempt (D-008) | A platform-side failure still uses up the one free check | James: keep the anti-abuse rule or release on platform failure |
| Founder migrations 049, 051–070 | Not applied anywhere; our runner refuses unreviewed pending files | Founder owner applies first, or James approves a combined set (D-028) |
| Image pricing in plan credits (D-026) | Creator images refused with `image_credits_unavailable` | James / Pricing owner: decide the image credit rate and quote basis before Creator activation |
