# Rafii — Meta Public Trends & JEV: Production Product Requirements

**Product:** Rafii Trends / Growth Studio
**Date:** 2026-10-09 (America/Indiana/Indianapolis)
**Version:** 1.0 — engineering handoff
**Status:** Requested / design-ready, **not** three-network production-ready
**Engineering branch:** `codex/rafii-meta-public-trends-20261008`, Draft PR #143
**Authoritative Engineering Spec:** `docs/superpowers/specs/2026-10-08-rafii-meta-public-trends-design.md`
**Execution Plan:** `docs/superpowers/plans/2026-10-08-rafii-meta-public-trends.md`

## 1. Product goal

Give creators a source-backed, permissioned view of emerging topics across **Instagram, Threads and Facebook**, connecting those public signals to their own-account performance and content-planning opportunities through Rafii's existing Trend Pipeline and optional JEV semantic analysis. Users must be able to distinguish what Rafii **observed**, what a metric **measures**, what the system **inferred**, and what an AI **suggested**.

**Important non-goal:** Claiming access to all Meta posts or a complete cross-platform population. Ordinary commercial APIs do not grant unrestricted Facebook personal feed, Instagram personal accounts, protected groups, and all Threads posts. Use the maximum **approved, documented, relevant** coverage. Transparency is part of the product.

## 2. Personas and outcomes

- **Creator:** Discover candidate themes from allowed public sources, compare to their permitted own-account insights, open individual source examples, and save ideas for future posts.
- **Agency/team:** Research public conversations for client brands with workspace-permission isolation, auditable source lineage and appropriate seat/role scopes.
- **Founder / Trust Operations:** See each platform's app review, token/scope, rate/budget, freshness and deletion status. Change rollout only with explicit operator authority.
- **Meta App Review tester:** See a real user-controlled search for the exact capability, matching consent, returned third-party public results, and privacy/data deletion UX.

## 3. Feature acceptance contracts

### P0 — Source admission and correctness

**P0.1** Three distinct feature types: Threads public keyword search, Instagram hashtag discovery through a separately approved professional account / Facebook Login, and Facebook public Page content under PPCA. OAuth login/publishing/owned-insights grants **cannot** implicitly unlock a public source. Access checks run at scheduling, dispatch, write and render.

**P0.2** For every source show `implemented`, `runtime_bound`, `app_reviewed`, `verified_scope_or_feature`, `live_read_verified`, `stored_and_processed`, `production_ui_verified` separately. Only proven statuses may be shown as such. Unknown = unavailable, not zero.

**P0.3** Each API call is bounded and provider-host-pinned; pagination uses a validated cursor, never a provider-supplied URL. Access tokens never appear in logs or URLs. No scraping, session farming, research API commercial repurposing or bypass of permission denials.

**P0.4** Durable quota and retry records, including Instagram's current **provider-confirmed** rolling distinct-hashtag limit; no job proceeds if the versioned quota rule/current allowed use cannot be established. Rate-limited/blocked != native count zero.

**P0.5** Policy-specific permissions for retrieve, store raw, store metrics, display, derive, cross-source combine, model processing, retention and deletion. Default deny. User opt-in, location rules, workspace RLS and source lifecycle honored.

### P1 — Public discovery UX and intelligence

**P1.1** Users choose exact keyword, hashtag or public Page within verified quota; see sample size, source, query, earliest/latest source timestamp, retrieval timestamp, and completeness/coverage disclaimer.

**P1.2** Each topic cluster has evidence-linked examples. Dedup on native item, revisions and author identity only if returned. No fabricated count, author, entity, demographic, reach or virality probability.

**P1.3** Run comparable within-source time windows for sampled mention rate and trend momentum; confidence supported by actual sample size, distinct authors when known, freshness, coverage and method qualification. Cross-network averages require a documented comparable calibration and independent permission. **No simple sum of Instagram reach + Threads views + Facebook likes**.

**P1.4** A model-eligible evidence pack may invoke JEV for a subset of defined typed judgments — semantic label, cluster merge, cultural context, brand fit, originality, risk. JEV does not acquire provider data or make metric facts. AI-generated ideas remain `interpretation_only`, with model/qualification/cost attribution.

**P1.5** Allow saving a qualified trend to Ideas or Growth Studio, keeping public-sample and owned-post performance as separate panels.

### P2 — Coverage extension

**P2.1** Threads public-profile discovery and Instagram Business Discovery, only under separately verified current entitlement.

**P2.2** Third-party licensed Meta data sources for broader coverage **only** with commercial permission and contract clauses covering the intended SaaS use, AI processing, derivatives, export, retention, territories, purpose and deletion. The research-only Meta Content Library path does not automatically qualify.

**P2.3** Source diagnostics, consent revoke, policy revoke, refresh expiry, and safe cleanup; no published AI results without the source's current rights.

## 4. User interaction flow

1. Trends → Public Sources: show per-network state and last verified sample; do not offer clickable working filters for unavailable sources.
2. Search a typed keyword/hashtag or a reviewed Page ID from user selection.
3. Rafii evaluates workspace/connection/token/feature/policy/quotas **before** external provider call.
4. If allowed: show bounded sampled posts with source links and method scope; record normalized provenance.
5. Run eligible local statistical analysis. Optional JEV on permissioned and size-bounded evidence, with cost reservation.
6. Show measured-vs-inferred-vs-AI layered results and ask user before any external publishing/side effects.
7. Disconnect/source deleted/permission revoked: invalidate dependent results; no stale source content persists in current views.

## 5. Operational requirements

- **Security:** authenticated workspace/tenant context; default deny; vault-backed tokens; no secret plaintext in work queue, client or Github; prevent SSRF and prompt-injection in third-party content.
- **Data:** immutable query/policy/contract versions; clear UTC event/received/available timestamps; source revisions/deletion keys; right-aware expiry and tombstones; no retention beyond source and vendor restrictions.
- **Reliability:** producer/consumer idempotency, bounded retries and circuit breakers; provider failures surface as explicit unavailability and are not silently replaced by prior observations.
- **Compliance:** actual Meta App Review and approved feature evidence; license/version-specific excerpt/model rights, data-deletion URL; do not expose private/public content from incompatible API contracts.
- **Cost:** use project quota ceilings, workspace quotas and bounded model usage; keep platform API quota units distinct from monetary model cost.
- **A11y/i18n:** owner-facing error/consent in accessible controls, at minimum existing English/Cantonese/Traditional Chinese labels; source caveats remain understandable.
- **Rollout:** flag off by default, isolated Preview, real authorized staging account, redacted provider receipt, scoped canary, rollback; don't mix concurrent PR #139, #140, #142.

## 6. Nonnegotiable gates / definition of done

| Gate | Required proof |
| --- | --- |
| Code | Source adapter + verified contracts + disabled-by-default binding |
| TDD | Failing synthetic test observed, then passing focused + cloud suite |
| App | Exact app ID/operation/feature approved in Meta portal, live—not copied sample text |
| OAuth | Real permitted account and audited current token scopes; user consent |
| Data | External permitted third-party *public* item received, scoped and stored with provenance |
| Trend | Nonfabricated sample analysis; change over comparable windows with unknowns |
| JEV | Model run only where source rights and bounded credits allow; typed interpretation and calibration clearly labeled |
| UI | Desktop/mobile with actual data and error/unavailable paths, screenshot + runtime/network evidence |
| Production | Exact merged SHA, deployment identity, live authorized read, revocation case, rollback evidence |

Any unproven app approval/third-party source marks that platform **BLOCKED_PROVIDER_APPROVAL**, not complete. No human password, access-token paste or bypass is an acceptable workaround.

## 7. Existing engineering and parallel ownership

- **PR #143** (this branch): initial three **inert** Meta public adapters; source tests; PRD/spec/plan/Meta review packet; NOT proven runtime enabled.
- **PR #139:** Bluesky ingestion recovery, including open lifecycle-marker review.
- **PR #140:** Trends readiness and UI.
- **PR #142:** Growth Studio / owned analytics.
- **Canonical production branch:** `consumer-saas`; always fetch current HEAD and reconcile before merge.

**Owner action checkpoint:** Meta business/App Review form, actual demo user and scopes; other automated engineering work can proceed independently of these approvals.

## 8. Direct links

- Draft PR: https://github.com/dev-james0723/PostRiff/pull/143
- Spec: `docs/superpowers/specs/2026-10-08-rafii-meta-public-trends-design.md`
- Plan: `docs/superpowers/plans/2026-10-08-rafii-meta-public-trends.md`
- Cantonese architecture: `docs/design/social-trend-intelligence/RAFII_META_JEV_TRENDS_LOGIC_2026-10-08.zh-Hant.md`
- Meta review pack: `docs/reviews/2026-10-08-meta-public-trends/README.md`
