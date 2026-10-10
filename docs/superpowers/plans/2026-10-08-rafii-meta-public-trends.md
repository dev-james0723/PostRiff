# Meta Public Trends Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans; TDD red→green per task. The user's goal is authorized, but Meta App Review/OAuth, privacy rights, optional spend, production database admissions and destructive actions still require their respective independent gates.

**Goal:** Build safe read-only Instagram, Threads and Facebook public discovery adapters and truthful Trends/JEV integration, then qualify each against approved Meta access.

**Architecture:** Reuse existing `growth/trends/providers/base.py`, policy/registry/worker, encrypted existing OAuth service, and JEV enrichment. Source ingestion is independent of owned analytics, model processing and commercial licensing. Only the selected, reviewed operation can be activated; no admin console or UI filter is evidence of live public data.

**Tech Stack:** Python stdlib/pytest or unittest, existing Postgres/Supabase schema (later admitted migration only), Next.js, JCB/Depot cloud CI.

**Spec:** `docs/superpowers/specs/2026-10-08-rafii-meta-public-trends-design.md`

## Global Constraints

- Preserve active PR #139 Bluesky ingestion, #140 Trends launch, #142 Growth Studio; do not edit their worktrees or force merge.
- The prior Instagram-Login OAuth path needs no Page for **owned** data. Add distinct Facebook-Login professional Instagram pathway for public hashtag discovery; no silent migration or OAuth scope mixing.
- Network access disabled by default; never fetch until current Meta approval, connection account, app role/feature and consent are proved.
- Never use social scraping, research-only data or unlicensed APIs to evade limits/approval.
- Per operation rights, bounded bytes/items/pages/dollars/quotas, tenant isolation, deletion and dynamic freshness.
- A single `Graph` API `200` without admitted permission and stored evidence does not certify a working source.
- Never treat selected hashtags, Pages, public profiles or keywords as all-user whole-network population.
- No client-visible tokens, provider errors, or unbounded external URLs.
- Existing JEV evaluation is interpretive and optional; no real model call unless current right to LLM-process source text and bounded reservation exists.
- Existing deployment must not be overwritten while other release PRs are under integration.

## Review focus

1. Unapproved/expired/foreign workspace OAuth token or feature must prevent **all** external calls.
2. Paging link and source URL are provider-controlled data, not destinations for further HTTP.
3. Missing author/insight fields remain unknown. No fake social totals or score.
4. Different operation/region/tenant entitlements do not share raw rows or tokens.
5. Deletion/revocation, token expiry and data retention must invalidate displayed results.

---

### Task 1 — Meta public capability contract + immutable app-review matrix
Files: Create `src/postriff_phase2/growth/trends/providers/meta_public.py`, `tests/test_trend_meta_public.py`.
Interfaces: three distinct `ProviderCapability` objects (`threads:keyword_search`, `instagram:hashtag_discovery`, `facebook:page_public_posts`), each immutable (provider, operation, version, endpoint, protocol, credential class, required verified grants, max items/bytes/time, non-monetary quota type).
- [ ] Write a failing synthetic test: all exact independent operations fail closed if unreviewed or granted only creator/owned scopes.
- [ ] Run targeted red test with no networking, then implement three constructors; prove no default secrets or network.
- [ ] Add platform-specific approval manifest table and prove false cross-provider reuse is impossible.
- [ ] Targeted tests pass (report counts, SHA, command, source version).

### Task 2 — Threads official keyword search
Files: `meta_public.py`, `tests/test_trend_meta_public.py`.
Interface: `collect_threads_keyword(*, policy: SourcePolicy, token: str, query: str, received_at: str, available_at: str, coverage_epoch: str, limit: int, quota_reserve: Callable, cursor: dict|None=None, transport=None) -> Batch`.
- [ ] Fail-first tests: required `threads_basic` and `threads_keyword_search`; denied feature/consent; token never in query URL; pagination only by cursor token; TOP/RECENT explicitly labeled; malformed response quarantine; unknown author not invented; duplicates collapse.
- [ ] Build one bounded `GET https://graph.threads.net/{reviewed_version}/keyword_search` with pinned fields, safe authorization header, `search_type`, controlled query and timeouts.
- [ ] Write exact per-result availability/retrieval/time basis, provenance, revisions and rights.
- [ ] Never fetch provider `paging.next` URL; no HTTP retry inside adapter.

### Task 3 — Instagram Facebook-Login hashtag sample
Files: `meta_public.py`, `tests/test_trend_meta_public.py`, later connector wrapper.
Interface: `collect_instagram_hashtag(*, policy, token, ig_user_id, hashtag, quota_reserve, ...) -> Batch`.
- [ ] Fail-first separate login type, professional-account and Instagram Public Content Access review requirements.
- [ ] Reserve a durable distinct-hashtag 7-day capacity **before** the first request; fail closed if quota store unavailable. Never invent 30/7 day compliance via a process-local counter.
- [ ] Resolve `ig_hashtag_search` to numeric hash ID then fetch one bounded `recent_media` page. Do not trust supplied dynamic Graph URLs or a hashtag ID from another workspace/account.
- [ ] Returned username/authors unavailable => unknown. One account's Instagram Login owned insights must never automatically authorize this public operation.

### Task 4 — Facebook PPCA public Page observation
Files: `meta_public.py`, `tests/test_trend_meta_public.py`, separate reviewed page resolver.
Interface: `collect_facebook_page_posts(*, policy, app_token, reviewed_page_id, quota_reserve, ...) -> Batch`.
- [ ] Fail-first PPCA feature verification (not only `pages_show_list` or `pages_read_engagement`), approved Page id, private/age/geo restrictions, default-denied policy.
- [ ] Fixed `GET https://graph.facebook.com/{reviewed_version}/{page-id}/posts` only, paging as cursor, header token, bounded result fields; no personal-feed/groups calls.
- [ ] Store author as Page only when the Page ID is verified; timestamps and links validated; counters optional native fields with proper definition and scope.

### Task 5 — Registry/runtime + credential and quota binding
Files: `src/postriff_phase2/growth/trends/providers/runtime.py`, `registry.py`, `worker.py`, owned connector integration (exact file chosen after read). Tests: real worker admission and disposable Postgres tenancy.
- [ ] Build a server-owned connection resolver using existing encrypted workspace token vault, distinct FB and IG/Threads OAuth legs, no browser token or job-named secret source.
- [ ] Return `None` from binding when exact review proof or feature/scope/token is missing. Use reviewed contract protocol and operation-specific flags.
- [ ] Define quota reservation/failure accounting before external I/O; no attempts consumed for locally denied capacity.
- [ ] Align reviewer-approved retention, rights, store and license restrictions per operation. No automatic `cross_source_combine`.
- [ ] Adversarial tests for revocation, stale scopes, cross-tenant token and token-in-log. All green in JCB.

### Task 6 — Coverage + analysis integrity
Files: `web/src/features/trends` after rebasing / coordinating #140; `growth/trends/{metrics,momentum,lifecycle,confidence,judge}` only if needed. Tests source-filter/coverage/JEV synthetic evidence.
- [ ] Distinguish Public Sample / Hashtag Sample / Page Universe / Connected Analytics / Licensed Population.
- [ ] Coverage cards show source, as-of, sampling limits, denied permissions, unknown denominator, freshness and rights.
- [ ] Keep Meta native engagement types separate, compare only true same-definition/equivalent windows. JEV interpretations require consent+quota and are `interpretation_only` with calibration status.
- [ ] Empty or error: `Unavailable`/No qualified coverage rather than 'zero posts'.

### Task 7 — Meta App Review and onboarding package
Files: `docs/reviews/2026-10-08-meta-public-trends/README.md`, screencast script per operation, privacy copy and exact redirect checklist.
- [ ] Split new public access applications from existing owned analytics review: Threads `threads_keyword_search`/`threads_profile_discovery`; Instagram Facebook Login + Public Content Access; Facebook PPCA.
- [ ] Check app owner intended HINSINGAU and proposed Rafi Facebook Page against live console before assuming either exists; Page is not an all-network token.
- [ ] Record App mode, business verification, privacy/data deletion URLs, actual scopes and developer account grant without exposing credentials.
- [ ] A human authorizes/signs into Meta and submits the outward-facing review. No fake approval screenshot.

### Task 8 — Production acceptance
- [ ] Cloud typed tests, pytest/unittest, offline Meta denial suite, tenant/Postgres, next typecheck/lint/build and browser UI (desktop/mobile).
- [ ] CI green for actual PR head. No force merge amid competing #139/140/142 changes; safe rebase and reconciliation first.
- [ ] Staging with an actual permitted connected Meta account: fresh per-platform accepted observation, correct writer/reader provenance, explicit excluded population, source health, current rights and revocation test.
- [ ] If verified and user permissions/provider grants allow, deploy behind canary, exact production SHA and real authenticated UI smoke.
- [ ] If any necessary Meta approval is absent, leave that operation disabled. Report **BLOCKED_PROVIDER_REVIEW** with exact missing action and evidence; never claim three-platform production ready.

## Hand-off ownership

This plan owns **Meta public API admission and sources only**. #139 owns Bluesky; #140 owns Trends UX/enrollment; #142 owns Growth Studio owned-account analytics. Coordinate code before shared edits. A draft PR from this branch may ship inert source contracts but cannot grant or imply Meta rights.
