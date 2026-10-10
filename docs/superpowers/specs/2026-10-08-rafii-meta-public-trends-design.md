# Rafii Meta Public Trend Intelligence — Engineering Specification (2026-10-08)

**Owner:** Rafii Trends / public discovery. **Branch:** `codex/rafii-meta-public-trends-20261008`. **Base:** `consumer-saas@94ca0dbd`.
**Status:** Approved user goal; design and access matrix only until exact Meta permissions and source rights are proved. **Do not claim live public coverage from code alone.**

## 1. Product objective

Support topic discovery and evidence-backed analysis across Instagram, Threads and Facebook **to the maximum lawful, officially authorized scope**. "All platforms" means implement separate provider families for each of the three, **not** a fictitious promise of every post on every network. Every observation, metric and UI result must state operation, sampling frame, freshness, known exclusions and right-to-process.

Keep three distinct lanes:
- **P — Public discovery:** third-party public posts/pages/hashtags found under Meta-approved discovery operations.
- **O — Owned analytics:** exact creator/Page content and native insights, supplied by user-authorized connections. This is NOT a public listening entitlement.
- **L — Licensed commercial coverage:** independently reviewed vendor feeds with network-specific processing, AI, retention, derivative and redistribution rights. Vendor marketing claims never count as verified coverage.

Research-only Meta Content Library must remain outside Rafii's commercial user-serving pipeline unless Meta independently grants an eligible, compatible use. Its API currently documents Facebook and Instagram public content; Threads is in the research UI.

## 2. Current verified repository facts

- `src/postriff_phase2/growth/trends/providers/registry.py` declares `threads:keyword_search` and `instagram:hashtag_discovery` **in the catalogue**, not a production runtime binding. A Facebook public-page discovery entry is currently absent.
- `src/postriff_phase2/growth/trends/providers/runtime.py` binds reviewed Bluesky/Mastodon/Web only at the examined base. Catalogue != connected provider.
- `src/postriff_phase2/providers.py` has Threads OAuth and Instagram Login for creator/owned use. The existing Instagram Login path **does not require a Facebook Page**; public hashtag search via Instagram Graph API with Facebook Login is a *different* integration. Never convert one into the other silently.
- `src/postriff_phase2/insights.py` supports native, **owned** Instagram/Threads insight reads with distinct per-platform metric definitions.
- `docs/design/growth-phase0/META-APP-REVIEW.md` explicitly says its existing review pack excludes public keyword and hashtag search. A new, separate Meta review request is mandatory.
- JEV exists as `src/postriff_phase2/growth/jev.py` and `growth/trends/judge.py` through AI Gateway, gated model enrichment; source ingestion, arithmetic, dedup and lifecycle remain separate local stages.
- Existing concurrent PRs #139 (Bluesky), #140 (Trends launch), #142 (Growth Studio) own their code paths. Do not overwrite or merge their work.

## 3. Reviewed operation matrix

| Provider operation | Official API or route | Required source capability | Trust/cost and coverage |
| --- | --- | --- | --- |
| Threads `keyword_search` | Threads Graph `GET /keyword_search` with `q`, `search_type=RECENT|TOP`, possible `search_mode=KEYWORD|TAG` | `threads_basic`, `threads_keyword_search` after exact App Review; authenticated permitted user, verified usable result fields | Bounded query/page/rate; sampled public results only, not whole network. |
| Threads `profile_posts` | Threads Graph `GET /profile_posts` for reviewed exact public username | `threads_basic`, `threads_profile_discovery` after exact review | Identity-specific sample only; no general public timeline claim. |
| Instagram `hashtag_discovery` | Facebook Graph `/ig_hashtag_search?user_id=...&q=...` then `/{hashtag-id}/recent_media|top_media` | Facebook Login-linked IG Professional account, `instagram_basic`, Instagram Public Content Access feature / App Review as applicable | Per-account distinct hashtag budget: documented 30 per rolling 7 days, to verify in current account. Some fields (e.g. poster username) can be unavailable. Not all posts. |
| Instagram `business_discovery` | Facebook Graph professional-account Business Discovery for an exact reviewed username | Facebook Login IG Professional token and appropriate business/metadata access | Professional business/creator profiles only, no ordinary personal accounts. |
| Facebook `page_public_posts` | Graph `/{page-id}/posts` or reviewed public Page discovery | Approved Page Public Content Access (PPCA), correct app/system user token and approved Page identifiers | Public, eligible Pages only. No personal feed or private/restricted Group access. |
| Facebook `page_owned_analytics` | Graph managed Page posts/insights | Page-role and `pages_read_engagement`/other operation-specific grants | **Owned** metrics, not PPCA-derived whole-network public counts. |
| Meta licensed feed | Reviewed third-party commercial network contract | Written lawful network + business use + transformation/AI/export/retention terms | Vendor-specific sampling and terms; no general unrestricted guarantee. |
| Meta Content Library | Qualified research restricted environment | Independent eligible research approval/use, controlled access | **NOT** automatically eligible for consumer SaaS ingestion or redistribution. |

Official References:
- Meta Threads API / public search: https://www.postman.com/meta/threads/folder/u4wm9lw/discover-threads
- Meta Instagram APIs: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- Meta Graph API feature docs: https://developers.facebook.com/docs/features-reference
- Instagram hashtag reference: https://developers.facebook.com/docs/instagram-api/guides/hashtag-search
- Meta research restrictions: https://www.icpsr.umich.edu/sites/somar/meta-content-library
- Jev and structured decisions: https://vercel.com/changelog/ai-gateway-now-supports-typesafe-clients-and-http-api-for-jev

## 4. Data contract, fail-closed gates

Store no provider data unless all are true, checked **before call** and **before commit**:
1. Provider/operation/version is registered to an exact reviewed `ProviderCapability` + `SourcePolicy`.
2. Real source approval **including the precise Meta feature and scopes**, verified by app-token/scope diagnostics, with token bound to the right Rafii workspace and account.
3. Relevant workspaces and regions are entitled; consent, rate and spending caps are current. No automatic approval based on "connected to Facebook".
4. `retrieve`, `store_raw`, `store_metrics`, `llm_process`, `derive_metrics`, `display_excerpt`, `display_link`, `cross_source_combine` and `share_across_workspaces` are **independent**, explicit rights. Unknown => deny.
5. All post IDs, time basis, timestamps, coverage epoch, retrieval time, source policy/contract revision, revocation/deletion lifecycle and retention are stored.
6. Fields not returned by Meta remain `null/unavailable` (never 0). Never fabricate author identity or count from search rank.
7. Redirects, provider-supplied `paging.next` URLs, private IP URLs and user-supplied job endpoints are forbidden as request destinations. Use only pinned Graph hosts, cursor tokens and bounded fixed query builders.
8. Existing encrypted OAuth vault, rights-review and tenant-scoped service must be reused. Never place bearer/access tokens in URLs, logs, traces, model inputs, UI receipts or committed configs.
9. On 401/403/429, token expiry, quota failure, rights revocation and unavailable coverage, emit specific safe reason/status; avoid unbounded retries. Validate provider deletion/change and policy expiry.
10. The user-visible coverage claim is the actual **operation and sampled population**, not a platform-wide prevalence estimate.

## 5. Analysis architecture — JEV's actual responsibility

```text
Meta public discovery / owned analytics / licensed feed
   -> per-source policy + OAuth/PPCA/scope/rights/quota admission
   -> bounded provider acquisition / provenance + temporal storage
   -> normalization -> revision dedupe / revocation -> topic clustering
   -> comparable metric windows -> baselines -> velocity / acceleration
   -> sampled lifecycle candidate + inspectable confidence/support
   -> evidence pack (rights-current, digest, scope, max tokens)
   -> optional JEV typed semantic judgments via AIModelRouter
   -> optional separate chat model generates source-linked narrative/angles
   -> verified receipts + UI source coverage / unknowns + Growth Studio
```

- Deterministic Python computes measured counts, velocity and lifecycle support. JEV does NOT fetch data and does not produce factual historical counts.
- JEV typed tasks currently include: `cluster_merge_check`, `semantic_label_check`, `culture_classify`, `workspace_fit`, `originality`, `execution_risk`, `narrative_stance`, `genome_support`, `spread_mechanism`, `whitespace_support`, `draft_diagnostic`, `platform_fit`.
- JEV runtime: `typesafe-ai/jev` through `POST https://ai-gateway.vercel.sh/v1/evaluate`; task-specific routing/fallback, authorization, usage ledger, cache, and qualification checks apply. Native answer probabilities are **not** proven real-world outcome probabilities; cohort qualification must be earned.
- Semantic flags/policy can be off; a present code path does not demonstrate a production model call.
- Cross-platform scoring requires versioned denominator and representative sampling calibration. Do not sum native likes/reach/views from Meta networks as if definitions match.

## 6. Implementation boundaries and priorities

**M0:** Read-only, zero-credential request/response adapters with injected transports and synthetic tests, full rejection/cursor/rights test corpus. No source is bound to production registry solely by a module import.

**M1:** Threads first (narrow public keyword API); Meta App Review/demo pack, scope proof, valid token from existing vault, ingestion with complete retention and provenance. Enable only one canary workspace after actual permitted response.

**M2:** Instagram hashtag & Business Discovery, Facebook public Page PPCA; Facebook Login pathway **separate** from existing Page-free Instagram Login, full consent/app-review and provider-operation isolation.

**M3:** Licensed supplemental network source only after written terms; no uncontrolled scraping, personal-account extraction, Meta Research API commercial conversion, or paywall/login/captcha bypass.

**M4:** Post-admission production smoke: fresh per-platform accepted observations, not only API 200 or historical owned metrics; results -> metrics only where justified; JEV evaluated only on current permitted evidence; official demo user + independent ordinary-user validation.

No writes to production DB/config or live provider tokens, no new payment/approval or destructive action without the actual human/provider gate. Preserve active PRs and source health truth.

## 7. Completion criteria

For each network, report **implemented**, **runtime bound**, **app-approved**, **permission verified**, **live read verified**, **stored & pipeline processed**, **end-user UI verified** individually. "Meta three-platform complete" requires real representative, authorized fresh reads across all three, with exact limits disclosed; a missing right is BLOCKED, never marked PASS.
