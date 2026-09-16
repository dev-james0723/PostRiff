# Connector audit and launch selection (official docs read 2026-09-15)

**Method:** a research agent fetched current official developer documentation only (learn.microsoft.com/linkedin, developers.facebook.com, docs.x.com, developers.google.com/youtube, developers.tiktok.com, developers.pinterest.com, atproto.com/docs.bsky.app, docs.joinmastodon.org). 79 URLs were read; the full URL table and per-provider findings are preserved below. Pinterest and Bluesky reference pages were JS-rendered/empty and their facts come from official-domain snippets + the atproto spec: **re-verify in a browser before build**. Facebook's scheduling window is stated inconsistently on two official pages (30 vs 75 days).

**Rule applied (architecture §12.3, D9):** catalog presence is never launch evidence; a connector is public only after its own review gate passes with non-founder test accounts. A local James Au Studio grant is not a cloud customer grant.

## Summary matrix

| Provider | Direct publish (official, 3rd-party app) | Native schedule | Review gate | OAuth / tokens | Post analytics | Comments/reply | Cost | Recovery |
|---|---|---|---|---|---|---|---|---|
| LinkedIn member | text, image, video, multi-image via `POST /rest/posts` or self-serve `ugcPosts`; no organic carousel | no | **self-serve** for `w_member_social` (Share on LinkedIn); org/analytics/comments need Community Management API (legal entity, screencast) | auth code (no PKCE), 60-day access, **refresh only for MDP partners** → 60-day re-auth | member analytics needs CM API scope | restricted | free | `201` + `x-restli-id`; `GET /rest/posts/{urn}`; no idempotency key |
| Instagram professional | image/video/Reels/Stories/carousel ≤10, container → `media_publish`, 100/24h | no | **Meta App Review + Business Verification** | auth code; 60-day long-lived, refreshable | `GET /{media}/insights` reach/views/likes/comments/saves/shares | read + reply | free | container `status_code`; no idempotency key |
| Threads | text/image/video/carousel 2–20, container → `threads_publish`, 250/24h | no | **Meta App Review** (Threads use case); no Business Verification statement found | auth code; 1h → 60-day, refreshable | views/likes/replies/reposts/quotes/shares | read + reply + hide | free | container status; `GET /{media}`; no idempotency key |
| Facebook Pages | feed/photos/videos/Reels, multi-photo | **yes** (`scheduled_publish_time`) | App Review + Business Verification | 60-day user; Page tokens don't expire | insights (deprecations ≥v25) | yes | free | `{id}`; drafts; resumable upload |
| X | text + media | no | none, but **every call billed** ($0.015/post, $0.005/read) | auth code + PKCE, 2h access, refresh | public + own-post metrics | replies via paid search | **paid** | `GET /2/tweets/:id` |
| YouTube | `videos.insert` | **yes** (`publishAt`) | **compliance audit** before public uploads; 100 uploads/day | auth code, refresh; 7-day refresh expiry while Testing | Analytics API | yes | free, quota | `videos.list` status |
| TikTok | video/photo Direct Post | no | **audit**; unaudited = private-only, 5 users | auth code; 24h access, 365d refresh | Display API counts | **none** for 3rd parties | free | `publish/status/fetch` |
| Pinterest | pins (image/video/carousel) | no | Trial = sandbox-only; **Standard review** | auth code; 30d + continuous refresh | pin analytics | none | free | `GET /v5/pins/{id}` (unverified page) |
| Bluesky | text/images/video via `createRecord` | no | **none** (self-registered client) | auth code + PKCE + PAR + **DPoP**, 15–30 min access, 2-week refresh | counts only (no impressions) | thread + reply | free | client-chosen `rkey` → idempotent create |
| Mastodon | text/media/polls | **yes** (`scheduled_at`) | none (per-instance app) | auth code + PKCE; non-expiring tokens | counts only | yes | free | **`Idempotency-Key` header** |

## Selection (Decision D12)

Weighing verified direct publish, a realistic review path for a small startup, media support, analytics feasibility, cost, and reconciliation behavior:

1. **LinkedIn (member posting only)** — self-serve `w_member_social`, text/image/video/multi-image, GET-by-URN reconciliation. Existing PostRiff request/classifier candidates already target this (`src/postriff_phase2/provider_candidates.py`). Constraints carried into the product: no refresh tokens → the connection card shows a 60-day re-authorization date; organization posting, member analytics, and comments are **Assisted/Unsupported** at launch (Community Management API is a separate legal-entity gate).
2. **Threads** — free, container-based publish with a status endpoint, insights and reply APIs, refreshable 60-day tokens; the only Meta gate found is App Review for the Threads use case.
3. **Instagram professional** — same Meta app family as Threads; image/carousel publish with `content_publishing_limit`, insights, comments. Gate is heavier (**Business Verification**), so it ships after Threads under the same app.

**Alternate if a Meta review stalls:** Bluesky (no review, free, idempotent `rkey`), at the cost of implementing PAR + DPoP and accepting engagement-count-only analytics.

**Deferred with reasons:** X (per-call billing on every publish/read), Facebook Pages (Business Verification + shrinking insights), YouTube (compliance audit + 100/day cap; video-first), TikTok (private-only until audit, no comments API), Pinterest (sandbox until Standard review), Mastodon (per-instance registration; excellent recovery semantics — cheap add-on later).

## External gates (nothing here is executed by this work)

| Gate | Owner | Needed for |
|---|---|---|
| Create PostRiff's own LinkedIn app; confirm "Share on LinkedIn" product + `w_member_social` on the production app; register `https://<postriff-domain>/api/oauth/linkedin/callback` | founder | LinkedIn Direct publish |
| Create/confirm PostRiff Meta app with Threads use case; submit **App Review** for `threads_content_publish`, `threads_manage_insights`, `threads_read_replies`, `threads_manage_replies` | founder + Meta | Threads Direct publish/insights/replies |
| Meta **Business Verification** + App Review for `instagram_business_content_publish`, `instagram_business_manage_insights`, `instagram_business_manage_comments` | founder + Meta | Instagram Direct |
| Non-founder test accounts per provider for end-to-end qualification | founder | §12.3 gate 4 |
| `POSTRIFF_CREDENTIAL_KEY` (Fernet), `POSTRIFF_PUBLIC_BASE_URL`, per-provider `POSTRIFF_OAUTH_<ID>_CLIENT_ID/CLIENT_SECRET`, and `POSTRIFF_OAUTH_<ID>_REVIEWED=true` only after the review passes | founder | mounting an adapter in production |

Until a provider's gate passes, its adapter reports `productionReviewed: false`, publish is **Assisted** (export only), and the Channels card says so.

## Product consequences recorded
- Scheduling is client-side for all three: PostRiff workers execute at the approved instant (existing lease/reconciliation model). Schedule capability = **Assisted** in the matrix ("scheduled by PostRiff workers").
- None of the three offers an idempotency key: the existing manifest idempotency + reconciliation-before-retry remains the duplicate defense; LinkedIn reconciles by URN, Threads/Instagram by container status then media lookup.
- Rate limits to encode in preflight: Instagram 100 posts/24h, Threads 250/24h, LinkedIn 150 requests/member/day.

---

## Per-provider findings (verbatim from the audit, condensed)

### LinkedIn
Publish: `POST /rest/posts` text/image/video/document/article/MultiImage/poll; organic carousel not supported; legacy `POST /v2/ugcPosts` member-only. Scheduling: none (`lifecycleState` only `PUBLISHED` on create). Gating: member posting self-serve; org/analytics = Community Management API (legal entity, business email, Page super-admin, Development tier 500 calls/app/24h, Standard tier needs screencast). OAuth: auth code, HTTPS redirect, 60-day access, refresh only for MDP partners. Analytics: org `organizationalEntityShareStatistics` (`rw_organization_admin`); member `r_member_postAnalytics` (CM API, ≥202506). Comments: `socialActions/{urn}/comments`; `r_member_social_feed` restricted. Rate: 150 req/member/day, 100k/app/day. Recovery: `201` + `x-restli-id`; `GET /rest/posts/{urn}?viewContext=AUTHOR`; `PUBLISH_REQUESTED`/`PUBLISH_FAILED` states.

### Instagram
Publish: JPEG images, video/Reels, Stories, carousel ≤10; two-step container; 100 posts/24h; `content_publishing_limit`; no native scheduling. Gating: App Review for Advanced Access; Business Verification mandatory. OAuth: short-lived → 60-day long-lived, refresh after 24h; scopes `instagram_business_basic/content_publish/manage_insights/manage_comments`. Analytics: `GET /{media}/insights`. Comments: read + `POST /{comment}/replies`. Rate: 4800 × impressions/24h. Recovery: container `status_code` (EXPIRED/ERROR/FINISHED/IN_PROGRESS/PUBLISHED, 24h expiry).

### Threads
Publish: text 500 chars, image 8 MB, video 1 GB/5 min, carousel 2–20; container → `threads_publish`; 250 posts + 1,000 replies/24h. Gating: App Review + published app for non-testers. OAuth: 1h → 60-day refreshable; scopes `threads_basic/content_publish/manage_insights/read_replies/manage_replies`. Analytics: views/likes/replies/reposts/quotes/shares. Comments: replies/conversation; reply via container `reply_to_id`. Recovery: container status; `GET /{media-id}`; `GET /{user}/threads`.

### Facebook Pages, X, YouTube, TikTok, Pinterest, Bluesky, Mastodon
See summary matrix; full findings in the audit transcript are reflected above. Key numbers: X post create $0.015, post reads $0.005, POST /2/tweets 100/15 min/user; YouTube 10,000 units/day, 100 `videos.insert`/day, uploads from unaudited projects forced private; TikTok unaudited private-only with 5 posting users/24h; Pinterest Trial 1,000 req/day sandbox; Bluesky 5,000 pts/h, create = 3 pts; Mastodon 300 req/5 min, `Idempotency-Key` 1h.

## URLs read (79)
LinkedIn: posts-api, authorization-code-flow, programmatic-refresh-tokens, community-management/getting-access (404), organizations/share-statistics, shares/comments-api, self-serve/share-on-linkedin, shares/images-api, community-management-app-review, increasing-access · Meta: instagram-platform/content-publishing, business-login, app-review, business-verification, instagram-platform/overview, instagram-api-with-instagram-login, facebook-login/security, instagram-platform/insights, comment-moderation, graph-api rate-limiting, ig-container, threads/posts, threads/overview, threads/get-started, threads/insights, threads/reply-moderation, threads/troubleshooting, threads/threads-media, pages-api/posts, page/feed, video-api/guides/publishing, get-long-lived, post/insights, insights, object/comments · X: creation-of-a-post, rate-limits, media-upload-chunked, pricing, about-x-api, oauth-2-0/authorization-code, data-dictionary, conversation-id, manage-tweets/introduction, lookup/introduction · YouTube: videos/insert, quota_and_compliance_audits, getting-started, oauth2/web-server, oauth2/native-app, analytics reports/query, videos/list, comments/insert · TikTok: content-posting-api-get-started, direct-post, get-video-status, content-sharing-guidelines, oauth-user-access-token-management, display-api-get-started, video-object, (research API comment specs) · Pinterest: pins-create (JS), media-create, rate-limits, access-tiers, set-up-authentication-and-authorization, oauth-token, pins-analytics · Bluesky/AT: create-post, advanced-guides/posts (empty), specs/oauth, oauth-improvements, rate-limits-pds-v3, specs/record-key · Mastodon: methods/statuses, methods/media, methods/apps, methods/oauth, api/rate-limits.
