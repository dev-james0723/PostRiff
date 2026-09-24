# FINAL capability matrix — 2026-09-24

Candidate: `/Users/ouxianxing/Documents/James-Au-Studio-launch-20260923`. Status words: `LOCAL_VERIFIED` (synthetic
transport / disposable PostgreSQL / local browser), `IMPLEMENTED_UNVERIFIED`, `NOT_RUN` (no live call was made),
`NOT_IMPLEMENTED`. Nothing here was run against a real model provider, a real social account or real money.

## 1. Operations that reach a model or a paid tool (FINAL-04)

Default gateway: Vercel AI Gateway, OpenAI-compatible endpoints. Every gateway request below sends
`providerOptions.gateway.only` = the list for that model in `POSTRIFF_MODEL_PROVIDERS`, or the model maker's own
slug by default (routing *and fallbacks* stay inside it; no model fallback is sent). The serving provider and
gateway cost are read from `providerMetadata`/`provider_metadata` when present; an answer served outside the list
is not used and its known cost is booked. Where exactly the live response carries that metadata is not verified.

| Operation | Runtime / endpoint | Model (default, env) | Egress class and consent scope | Cost source and pricing version | Credits / allowance | Evidence | Live |
|---|---|---|---|---|---|---|---|
| First draft (Home quick start) | `ServerModelRuntime` → `/v1/chat/completions` | `anthropic/claude-sonnet-5` (`POSTRIFF_MODEL_ID`, `POSTRIFF_MODELS`) | cloud; the typed thought (after "Use this text", required by the server), sources with cloud consent, memory files only if an owner allowed sharing, voice only with "Writing like me" + approved voice | gateway cost → `usage.cost` → tokens × price table (`priceBasis`: `configured` or `defaults-2026-09-23`, not checked against the gateway price list) | quote before approval (estimate + ceiling), reserve, settle actual ≤ approved maximum; unknown → operator reconciliation | `test_final_gateway_routing` (6), `test_final_runtime_failures` (7), `postgres_final_idempotency`, `postgres_final_credit_estimate`, `postgres_final_unknown_usage`, browser run on 4462 (synthetic writer) | NOT_RUN |
| Follow-up turn (Conversation) | same | same, or the conversation's chosen writer | same | same | same; a resend with the same key replays | `web/tests/credit-turn.test.cjs` (11) | NOT_RUN |
| Deep mode (draft + critique/revise) | same, 2 calls | same | same | same; ceiling now 2 × `max_tokens` for the re-read draft | ceiling e.g. 30.7 credits for a 2-destination Sonnet draft | `test_final_deep_ceiling` (2) | NOT_RUN |
| Personalized voice drafting | same | same | adds the approved voice profile and permitted voice samples for the exact route | same | same | existing voice tests + `postgres_voice_*` | NOT_RUN |
| Voice analysis | `ServerModelRuntime._call` via `voice_ai.analyze` | chosen analysis model | raw sample text to the exact route the person ticked; never fine-tuning | same (voice path rounds with `ceil`, see gaps) | writing allowance / metered usage within approved budgets | existing voice-analysis tests | NOT_RUN |
| Image generation | `GatewayImageRuntime` → `/v1/images/generations` | `openai/gpt-image-2.5-flare` (`POSTRIFF_IMAGE_MODEL`) | the image prompt only | `usage.cost` → gateway metadata cost; estimate `POSTRIFF_IMAGE_ESTIMATE_USD_MICRO` (100,000) | media credit; refused-outside-list image returns the credit and books the known cost | `test_final_image_routing` (4), `postgres_final_image_routing` (2) | NOT_RUN (that the images route honours `gateway.only` is unverified) |
| Preference-learning extraction | `learning_model.GatewayCall` → `/v1/chat/completions`, or the person's Claude CLI on the API host | `anthropic/claude-haiku-4.5` | owner-allowed learning events only | `usage.cost` → gateway cost (exact) → tokens × default price | platform budget (`provider='learning'`), unknown on failure | `test_final_learning_routing` (4), existing learning tests | NOT_RUN |
| Web research | Exa MCP search + Jina Reader | n/a | search query derived from the message; public pages; only after the owner allows web research (`POSTRIFF_RESEARCH=0` turns it off) | **not metered** (gap) | none | existing research tests | NOT_RUN |
| Campaign occurrence | campaign worker → the drafting runtime | the route confirmed on the task (`deterministic-preview` = $0) | the campaign's confirmed destination, language and voice | as drafting | as drafting, with the task's maximum; worker credit authority fixed | `postgres_final_campaign_destinations` (4) | NOT_RUN |
| Deterministic preview | fixture, no model | `deterministic-preview` | none | $0 | none | labelled "Synthetic writer: not a model-quality result" in the UI | n/a |
| CLI writers (Claude Code / Codex) | local CLI on the API host | the person's subscription | cloud via the CLI vendor; same consent checks | PostRiff records $0; no credits | none (not double-counted) | existing CLI tests; normal users never see install steps (FINAL-04) | NOT_RUN |

## 2. Accounts × operations × formats (FINAL-09)

Official documentation re-checked 2026-09-24 (read-only; Meta pages show no "last updated" date, LinkedIn pages
carry `ms.date`). "Implemented" means the hosted worker has the code path; every cell is `NOT_RUN` live.

| Account | Operation | Formats implemented | Scopes requested | Official constraint (2026-09-24) | Our handling | Local evidence |
|---|---|---|---|---|---|---|
| LinkedIn member | Identity | — | `openid profile` | OIDC `/v2/userinfo` (`sub`) | identity + token introspection | provider tests |
| LinkedIn member | Publish / schedule | text post (member) | `w_member_social` (open, self-serve "Share on LinkedIn") | Posts API `POST /rest/posts`, URN in `x-restli-id`; `Linkedin-Version` required (we send `202609`, supported to 2027-09-15); commentary is **little text** — reserved `\| { } @ [ ] ( ) < > # \ * _ ~` must be escaped | **Fixed today**: commentary is escaped (`little_text`), a word hashtag stays a hashtag; read-back compares the plain rendering (`little_plain`) | `test_final_linkedin_little_text` (2), `test_postriff_providers` |
| LinkedIn member | Image post | helpers only | — | Images API `initializeUpload` + PUT; image URN in `content.media.id` | `NOT_IMPLEMENTED` in the hosted worker (UI says so) | — |
| LinkedIn member | Read back / history | — | `r_member_social` | restricted, approved users only (closed to new requests per the FAQ checked 2026-09-21) | without it a published post is `uncertain` until checked manually; history import unavailable | worker tests |
| Threads profile | Identity / publish / schedule | text (≤500), one image (JPEG/PNG, ≤8 MB) | `threads_basic threads_content_publish` | non-testers need App Review + published app; 250 posts / 24 h; container then publish (~30 s wait); **>5 links fail** (from 2025-12-22); emojis count as UTF-8 bytes | **Fixed today**: a review with >5 links is refused with the reason; the 500 limit counts characters, not emoji bytes (gap) | `test_final_threads_links` (2), Threads container/reconcile tests |
| Threads profile | Insights / replies read / reply | — | `threads_manage_insights`, `threads_read_replies`, `threads_manage_replies` | same App Review rule | insights read once at verification; comments read once | existing tests |
| Instagram professional | Publish / schedule | one image + caption | `instagram_business_basic instagram_business_content_publish` | JPEG only; 8 MB; 4:5–1.91:1; width 320–1440; caption 2,200 / 30 hashtags; container expires in 24 h; publish limit **50 or 100 per 24 h (Meta's two pages disagree)**; Advanced Access (App Review + Business Verification) for accounts without an app role | every upload is re-encoded to a JPEG rendition; aspect ratio checked; width over 1440 not checked (live behaviour unverified); reels/stories/carousel `NOT_IMPLEMENTED` | `postgres_instagram_lifecycle` (15 cases) |
| Instagram professional | Own media (voice samples) | — | `instagram_business_basic` | up to 10K recent items, no stories | owned-posts picker (read-only, separate analysis consent) | social-learning tests |
| 30 directory platforms under "Desktop companion" (小紅書, Bilibili, 知乎, … X, Facebook Pages, YouTube, TikTok, …) | Publish | — | — | no API route used by this release (some have no third-party publishing API; X bills every call) | `NOT_IMPLEMENTED`: the companion is "Not available yet"; drafts can be exported | — |

OAuth success with a developer or tester account does not mean every customer can connect: Meta requires App
Review (and for Instagram Business Verification) before users without an app role can grant these permissions,
and LinkedIn's `r_member_social` is not available to new apps.

## 3. Review / publish reliability (FINAL-09)

Exact approval binds, in `store.build_manifest`: workspace, approver, brand digest, speaker and voice revision,
style revision, account (`channelId`, `providerAccountId`), platform and operation, variant id and content
revision, content type/format/preflight/skill routes, text and language, media (id, hash, source hash, MIME,
bytes, size, alt, rights), resolved local time + time zone + fold, capability version/scopes/verification, limits
version, acknowledged warnings, brief revision, source digest and voice-source digest; the root digest keys the
job. A draft written for one account cannot be approved for another (FINAL-02).

Local evidence (synthetic providers): manifest tampering and approval idempotency; duplicate review → existing
job; fresh review after cancel → new key; crash before/after submit never duplicates; `uncertain` reconciles
without resubmitting; revoked or read-only approver held at claim; cancel vs rate-limit race; incomplete
publication evidence rejected; source/voice change forces a new review; bulk approvals atomic
(`test_postriff_phase2*`, `test_postriff_safety_regressions`, `tests/phase2/postgres_safety.py`,
`postgres_repository.py`, `postgres_instagram_lifecycle.py`). Publishing idempotency (manifest root key) and
credit idempotency (request fingerprint + key) are separate records and both are tested.

## 4. Live publishing acceptance package — `BLOCKED_EXTERNAL` (awaiting authorization)

Not run. What a first live check would need, once the owner authorizes it:

| Item | Proposal |
|---|---|
| Accounts | the owner's own LinkedIn member profile (Share on LinkedIn, app 263833009) and own Threads profile added as a Threads Tester; Instagram only after the professional account has an app role |
| Content | one short caption per account in English and one in Traditional Chinese (HK), containing parentheses, `@`, a hashtag and one link (to prove little-text escaping and link handling); one JPEG for Threads |
| Format | LinkedIn text post; Threads text post, then one single-image post |
| Timing | scheduled 10 minutes ahead in Asia/Hong_Kong, through the Queue's exact approval |
| Expected result | LinkedIn: `x-restli-id` URN, receipt `uncertain` → manual check of `https://www.linkedin.com/feed/update/<urn>/` (no `r_member_social`); Threads: media id + `permalink` lookup → `verified` |
| Rollback | delete each post in the platform app after the check; record the permalink and deletion time |
| Budget | no model cost needed (deterministic preview draft); no money involved |
