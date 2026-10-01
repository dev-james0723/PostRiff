# RAFII Product Growth v2 — status

States: `not_started → implemented → local_verified → staging_verified → production_deployed → production_verified`,
plus `blocked` / `failed` / `not_run` with a reason. Data mode (`demo|synthetic|live`) is separate from environment
(`local|staging|production`). A requirement is never marked done because a document changed. "local_verified" below
means: focused unit tests + disposable PostgreSQL 17 groups on a private port, synthetic providers, Python 3.12, on the
integrated branch unless a row says "worker branch". Web TypeScript is checked only in CI on this machine (D-017).

Last update: 2026-10-01 · branch `claude/rafii-product-growth-v2` · PR #87 (draft) · pushed HEAD `41c4e9cf`.

## Program gates

| Gate | State | Evidence |
|---|---|---|
| G0.1 integration map | local_verified | `DECISIONS.md` D-001…D-007; production `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` @ `dcb5bcdc` |
| Pricing v2 + Inbox v1 merged | local_verified | merges `8726adbd`, `575caaf9` |
| Slices merged | 6 of 7 | results `de727483`, relationships `d16e9652`, visual pack `c5c91d90`, series `38abb86c`, intake `b6eac5e2`, pricing web `e8a68703`; briefs/proof (W-LOOP) still in progress |
| Local unit suite (integrated) | passed at `7dc55c5f` (3,128 OK / 245 skipped); slice modules re-run after each merge (271 + 147 OK) | `.venv-growth`, Python 3.12 |
| Web node tests (integrated) | passed: 604/604 at `41c4e9cf` parent | `node --test --test-concurrency=1 web/tests/*` |
| PR #87 CI | `3a1d7b3a`: unit gate failed on a copy-gate hit (fixed `7dc55c5f`); `a42bd212`: web build failed on 4 TS2345 errors (fixed `41c4e9cf`); `41c4e9cf` running | GitHub Actions `Rafii local release gates`, `Rafii browser scenes` |
| Browser journeys | first-week journey added to `rafii-browser.yml`; other slices not yet in the harness | `web/tests/growth-v2-browser.cjs` |
| Vercel preview build | passed on `d3825fbf`; not re-run since the slice merges | Vercel check on PR #87 |

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
| R-BRF-01/02, R-PROOF-01/02 | in progress | W-LOOP (084) | integrate when reported |
| R-ENG-01/02 | local_verified | `growth_v2_routes` (dispatch/public/cron); 9 slice tools registered through `growth_v2_agent_tools` (voice parity, scopes); array schemas declare items | per-slice browser coverage |
| R-ENG-03 | local_verified (disposable) | migrations 080, 081, 083, 087 additive with forced RLS; `rls.sql` loads them in order; 082 unused (D-021) | sha-pinned release runner (prepared, not executed) |
| R-MET-01 dictionary | local_verified | `metric_definitions.py`; Founder-format contract `contracts/founder-metrics-growth.json` generated from it with a drift test (`6b5b0402`) | Founder owner registers the 20 definitions in `metrics.d` |
| R-MET-02 paid conversion | local_verified | cash-paid from history, refund-adjusted variants, `test_metric_definitions`, `postgres_growth_fleet_v2` | `dataState=partial` until `pr_invoices` (Founder P1) lands |
| R-MET-03 events/costs | implemented | one taxonomy (`growth_events`); emitted by first week, results (ingested/reversed), relationships (followup_outcome), series (episode_accepted), visual pack (accepted/exported); intake emits audit rows only | briefs/proof events with W-LOOP; cost lineage via Founder `business_usage_v2` |
| R-NFR-01..04 | not_run | — | release gates on staging |

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
| Image pricing in plan credits (D-026) | Creator images refused with `image_credits_unavailable` | James / Pricing owner: decide the image credit rate and quote basis before Creator activation |
