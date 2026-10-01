# RAFII Product Growth v2 — decisions log

Program `RAFII-PRODUCT-GROWTH-v2`. Phases G0–G4 (not Founder P0/P1/P2). Newest last. Each entry: date, decision, reason, evidence.

## 2026-10-01 · G0.1 integration map

**D-001 · Integration base is the production SHA.**
Branch `claude/rafii-product-growth-v2` starts at `dcb5bcdcd76577835a6944f50310e25f16be9de8` (PR #84 head, branch `fix/rafii-call-lifecycle-20260930`).
Reason: production alias `postriff-phase2-private.vercel.app` → `dpl_HSmKDFfjkd8UCaoo2QfgerZUVwLL` (READY, source `cli`) serves that SHA, re-read 2026-10-01 ~17:00Z. `origin/consumer-saas` (`1acd88a8`) is 8 commits behind it, and the canonical local checkout (`d91660b7`) is older still. Basing on either would drop the voice/phone fixes.
Worktree: `/Users/ouxianxing/Documents/James-Au-Studio-product-growth`.

**D-002 · Pricing v2 is reused by merge, unchanged.**
`feat/rafii-pricing-credits-v2` @ `b862cf1f` (11 commits, local only, never pushed) merged cleanly as `8726adbd`. Its worktree (`~/.codex/worktrees/rafii-pricing-credits-v2`) holds staged, uncommitted Free-preview work last modified 2026-09-29 21:07 EDT; that worktree is not modified by this program. Whether that staged work is ported is decided separately (D-008).

**D-003 · Inbox v1 is reused by merge.**
`codex/rafii-inbox-v1-20260928` @ `cb4d5f6a` (6 commits, local only) merged as `575caaf9`. Four conflicts were resolved by keeping both sides:
- `hosted_app.py` / `scripts/postriff_dev_hosted.py`: production's Growth wiring and `pricing_from_environment` kwargs stay; Inbox switches (`RAFII_INBOX_SYNC_ENABLED`, `RAFII_INBOX_REPLY_SEND_ENABLED`, `RAFII_ENGAGEMENT_COPILOT_ENABLED`) and `audience=` on the worker are added.
- `oauth._capabilities`: production's positional `access_token` (used by `write_qualified` and the Business Profile destination call) stays sixth; Inbox's `existing` evidence becomes a keyword argument. `tests/test_inbox_oauth_capabilities.py` passes `existing=` by name.
- `inbox-view.tsx`: `GrowthEntry` stays above the new sync status bar.
Migration `047_inbox_operational_sync.sql` SHA-256 `bcb9be5b…a369553` matches the Inbox receipt.

**D-004 · Founder work is an adjacent, active owner.**
PR #86 (`claude/founder-admin-v2`, draft, based on the production SHA) was pushed at 2026-10-01 12:51:58 EDT and its worktree has ~80 uncommitted files. It is not merged here and its worktree is not touched. Shared metric definitions are agreed by message with its owner and recorded below; this program does not edit Founder contracts.

**D-005 · Migration numbers.**
Occupied or in flight: 047 (Inbox), 048 + 050 (Pricing v2), 049 + 051–060 + 062–068 (Founder; 061 unused, treated as Founder's). This program reserves **080–089** and records it in `docs/postriff-migration-numbering.md`. Hashes at reservation time: 048 `a36357de…792ba0`, 050 `f9aad0a0…b1e7d`.

**D-006 · Heavy work runs on Vercel preview / GitHub CI.**
At 12:53 EDT the Mac showed swap 94 %, load 21 on 12 cores and 7 `next-server` processes, above every local-resource limit. Local work is limited to focused Python unit tests and focused disposable-PostgreSQL groups; full builds, browser suites and whole-suite gates run in the PR's `Rafii local release gates` workflow and on Vercel previews.

**D-007 · Release authority.**
Pricing v2's handoff forbids production deployment, production DDL, live Stripe Prices and production checkout without a new explicit authorization; Inbox v1's receipt requires separate authorization for push/merge/release, production migration and live replies. The current request asks to deploy "within the applicable release authority", which the PRD (§2.3) says does not override a prior explicit prohibition. Therefore: push, PR and protected Preview are in scope; a production deploy containing Pricing v2 or Inbox v1 code, production migrations 047–050/080+, live Stripe, and live provider sends each need James's specific superseding permission, requested once with the exact action.

## 2026-10-01 · G0.2–G0.3 rulings

**D-008 · Port the staged Pricing Task 5 work, then fix it.** The staged Free-preview diff in the Pricing worktree applied unchanged (`825e54b7`, 24 PG + 4 unit tests green). Known defects fixed in follow-ups: a known-failed attempt must not consume the lifetime entitlement; a vacuous test assertion; Radar paid sources had no plan gate; Creator Growth AI failed closed (it goes through the credit quote/reserve/settle path instead). The anonymous public Post Doctor keeps its own existing allowance; continuation imports its already-obtained result and never grants or consumes a workspace entitlement.

**D-009 · Shared metric definitions (agreed in shape with the Founder P0 owner; financial activation stays with James).** Every metric this program adds is registered `proposed_definition_not_activated`; reuse Founder's `source_paid_conversion` for the 30-day cohort view; add `first_cash_paid_conversion` as the workspace-level event; rows use Founder's shape (`metricId, definitionVersion, interval, dimensions, value, unit, dataState, coverage{…}, sourceWatermark, sampleCount, reason, fixture, collectingSince, history`). Qualifying payment: invoice paid, livemode, amount_paid>0, subscription invoice (`subscription_create|cycle|update`); refunds/disputes feed a separately named refund-adjusted measure. Until the Founder P1 session pushes `pr_invoices` (057, branch `claude/founder-admin-p1p2`), paid metrics read `pr_credit_subscription_grants` with `dataState=partial`, reason `legacy_plan_invoices_not_recorded`. No second payment history. Cost attribution reads Founder's reservation lineage, not the `settle:` prefix. Fleet metrics needing workspace classifications are offered as a Control slice through the Founder owner; `growth.fleet` only gets the honest relabel and the shared pure definitions.

**D-010 · One event writer.** `growth_events.py` mirrors the Founder P1 `product_events` contract (enum properties `[a-z][a-z0-9_-]{0,39}`, listed counts, SAVEPOINT, never raises, dedupe `<event>:<entity>:<revision>`) and delegates to it when merged.

**D-011 · Route and client scaffolding.** One lazy dispatcher (`growth_v2_routes.py`) is wired into `hosted_app.py` once; slices add modules, never edit the shared application or shared web client. Web slices use `web/src/lib/growth-v2/request.ts`.

**D-012 · Flags, all default off.** `RAFII_FIRST_WEEK_ENABLED`, `RAFII_SOURCE_UPLOADS_ENABLED`, `RAFII_RELATIONSHIPS_ENABLED`, `RAFII_RESULTS_ENABLED`, `RAFII_SERIES_ENABLED`, `RAFII_VISUAL_PACK_ENABLED`, `RAFII_OPPORTUNITY_BRIEF_ENABLED`, `RAFII_PROOF_V2_ENABLED`. Turning one off stops admission of new work only (PRD §16.4).

**D-013 · Visual rendering is server-side.** Pillow (already pinned and deployed) with a bundled SIL-OFL Noto Sans TC font, so output bytes and hashes are deterministic and checks run inside the trusted boundary; the browser only edits and previews server-rendered PNGs.

**D-014 · Raw audio has no approved transcription route.** The only speech-to-text use today is phone sign-in digits, isolated by design. The intake adapter is built against a configurable route (`RAFII_TRANSCRIPTION_ROUTE`, unset by default) and reports audio as `unsupported` until James approves a provider, model and budget; tests use a labelled synthetic transcriber.

**D-015 · Local test environment.** A private venv `.venv-growth` (Python 3.12 as in `.python-version` and CI, `requirements-dev.txt`) replaces the shared canonical venv, which lacks `jsonschema`/`openai`. PostgreSQL groups run on private ports (coordinator 55871; slices 55881–55887).

**D-016 · "EN + zh-Hant" for changed flows.** The app has no UI-translation layer (`web/src/lib/locales` covers content languages only), so this program does not introduce one. Changed flows must accept, store, render and lay out English and Traditional Chinese content correctly (`lang` attributes, CJK-aware wrapping, the bundled TC font for rendered images) and are verified with both; UI chrome stays in the app's single language. Adding a translation framework would be a new design-system-level change outside the PRD.

**D-017 · Local typecheck deferred to CI while the Mac is saturated.** At 18:xx UTC the Mac showed swap 98 % and load 25 on 12 cores; `tsc --noEmit` for the web app is memory-heavy, so web typecheck, lint and build run in PR CI for every integrated slice.

## 2026-10-01 · Slice integration rulings

**D-018 · Results (G2-OUT).** Merged `de727483`; migration 080 sha256 `846d2be456661a7d012e603bd3bdea54b06b5af61f929820149aa53958e0ed1f`. Webhook secrets are per connection, shown once, stored only through the existing CredentialVault, rotated with a 24-hour grace. The three provenance classes are never summed; money stays per currency; association uses `rafii.result-link-association.v1` (30 days). Cross-slice reads go through `period_summary` and `get_declared`.

**D-019 · Relationships (G2-REL).** Merged `d16e9652`; migration 081 sha256 `0d2b181d1d81d2467afa862cc6ac32e42ddea0c8c2368c60b56d996e76f73a33`. "Won" needs a declared result of the same workspace (FK to 080). The card now lists the person's active declarations or records one in place; it never pre-selects (`f9987a36`). Replies use only the existing exact-approval Inbox path. Due follow-ups go through the existing detector → outbox with a dedicated `follow_up_due` email template in all four email locales and no English payload title (catalogue 2026-10-01.1, notification-planning policy 1.2.4). Links use the compact `u`+hex id form because the notification store's phone-number redaction corrupts some UUIDs; that redaction bug is pre-existing, pinned by `test_phone_caller_identity`, and not changed here.

**D-020 · Visual packs (G3-VIS).** Merged `c5c91d90`; migration 083 sha256 `3aedc1a4a7746489bd85f797e2c0c462a9ea927a77a8291a9dd08800d137955c`. The only handoff is the deterministic export. The publisher guard refuses any multi-image job until a provider is verified (`CAROUSEL_VERIFIED` empty), so `queued` and `verified_published` are never written. The fonts stay in both Python functions, because `visual_pack_export` renders and voice must have the same capability. That costs ~11.5 MB per function, well inside the limit.

**D-021 · Signature Series without migration 082.** Merged `38abb86c`. A series is a campaign of kind `series` in workspace planning state, projected to `pr_campaigns` by the existing `planning_store.sync`. That gives one revision and one transaction for sources, drafts, overlays and freshness gates, and no new production DDL. 082 stays unused and is not reassigned.

**D-022 · Language (amends D-016).** AC37 requires core flows to work in EN and zh-Hant. The slices ship feature-level English and Traditional Chinese copy modules (results, relationships, series, pricing in-app cards). Traditional Chinese is chosen only when the person's saved language is zh-Hant/zh-TW/zh-HK/zh-MO/yue. No translation framework is added, and app chrome outside these features stays English. Known effect: for those users, screens mix languages. A future app-wide i18n decision should absorb these modules. Content handling from D-016 still applies.

**D-023 · Raw intake (G1-INTAKE).** Merged `b6eac5e2`; migration 087 sha256 `0acc1a3fcb0865431f4de2e2114951b7cdff93bdedc808654a064e91b5647b65`; dependency `pypdf==6.19.0` (BSD-3, no sub-dependencies, pip-audit clean). Audio is refused before upload while no transcription route is registered, so no personal audio is stored for nothing (D-014). PDF text is parsed in a child process with no secrets and a 12 s cap. Source creation reuses the One Source pipeline, with review first. Retention: unfinished 30 days; the file and its text are deleted 30 days after source creation, or at once on failure, cancellation or retraction. The private bucket `rafii-source-uploads` must exist before activation.

**D-024 · Pricing web.** Merged `e8a68703`. `NEXT_PUBLIC_PRICING_CATALOG=v2` must be set in the same release as `POSTRIFF_PRICING_V2_ENABLED`. A usage response without `billingMode` is legacy. There is never a dead buy button. Known remaining legacy wording, listed in `evidence/pricing-legacy-audit.md`, is the agent image "1 media credit" hint, the site-agent billing help/context in writing batches, and one API error string. These need a v2 image-pricing decision before Creator activation. Legacy trial owners under v2 get no Creator offer until their trial ends.

**D-025 · Founder metric contract.** `contracts/founder-metrics-growth.json` is generated from `metric_definitions.DEFINITIONS` in Founder Control's catalog format: 20 definitions, all `proposed_definition_not_activated`. Founder-owned `source_paid_conversion` is referenced, not redefined. A unit test fails if the two drift. Registration in Founder's `metrics.d` is the Founder owner's step.

**D-026 · Images under plan credits: refused honestly until priced.** Pricing v2 credits are text-only (`textOnly`; the chat credit flow states "covers writing only"), and Creator has no media allowance. So every Creator image request failed, with a misleading message: "use the existing media plan", or "Turn off web research", or an unconfirmable "Confirm this task credit limit". Pricing images in credits is a commercial decision (rate, quote basis, Free exclusion), so it is not made here. A credit-plan image request is now refused on every path (turn, quote, direct image turn) with 402 `image_credits_unavailable`, "Images are not part of plan credits yet. Nothing was made or charged.", before any message, run, reservation or provider call (`postgres_growth_free_preview_v2`). The composer, `/image` description, agent prompts and site-agent help say the same per billing mode. Legacy plans are unchanged. Owner action: James/Pricing owner decides image pricing in credits before Creator activation.
