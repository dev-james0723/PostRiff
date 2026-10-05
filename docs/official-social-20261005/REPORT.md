# Rafii official social integration — 2026-10-05

**Verdict: engineering candidate validated in cloud; NOT PRODUCTION READY.** Eight providers have 205 granular capability rows. Zero rows have new real-provider E2E evidence in this task. No new OAuth grant, social publication, provider-review submission, production configuration, Git push, merge or deployment happened.

This report describes the candidate source, not the previously deployed Rafii application. Existing connection history is not evidence for newly implemented formats, permissions or approval state.

## Evidence and delivery

- [Capability matrix JSON](capability-matrix.json) and [CSV](capability-matrix.csv): method, permission group/scopes, alternative valid grants, product, account prerequisite, review requirement, implementation, real E2E, scheduling and limitation for every row.
- [Official audit](OFFICIAL-AUDIT.md), [primary-source index](sources.json), [live E2E matrix](live-e2e-matrix.json), [operator runbook](OPERATIONS.md).
- [Cloud receipts](evidence/cloud-receipts.json), [synthetic browser receipt](evidence/browser-receipt.json), [desktop](evidence/social-1280.png), [mobile](evidence/social-390.png).
- [Delivery state](DELIVERY.json) records the final local commit and external release state without implying a deployment.

## Implementation and authorization

Initial OAuth requests identity/account selection only. Previously explicitly enabled groups survive a reconnect; unrelated groups are not added. Publishing, community management, analytics, commerce, monetary data and messaging are separate intents. Each API operation checks actual token grants. Restricted LinkedIn scopes are withheld unless operator-owned permission approval is recorded. The Instagram Login Insights permission is withheld until its current primary contract can be verified.

Each capability independently requires official support, app/product approval, actual grant, destination eligibility, implementation and real E2E. Server-owned evidence binds app ID, account ID, destination ID, exact grant hash and implementation revision; fixtures cannot qualify a row as READY. There is no new LinkedIn/Threads/Instagram/Facebook “Full Access” state.

Publishing reuses Rafii OAuth, composer, library, manifests, worker, receipts and audit storage. Media IDs, containers, upload assets, post/person/organization URNs and resulting provider references survive reconciliation. Reviewed native actions use an immutable preview and approval, membership checks and durable intent. Unknown mutation outcomes stop automatic resubmission. Rate/processing/provider failures are surfaced without inventing publication success.

## Actual permissions and platform approval

**New actual scopes requested: none. New actual scopes granted: none.** The matrix lists implementable scope requirements, not an observed grant. Current account types, Page tasks, organization roles, access tiers, monetary eligibility and app-review states remain unverified. Environment variable names are not approval evidence.

Read-only production environment inspection found client-ID/secret variable names for LinkedIn, Instagram, Facebook, X, YouTube and TikTok. Threads and Pinterest client pairs were absent. Values were not pulled. This does not establish valid credentials or approved products. This process had no provider client credential pairs. No new official-social enable flag was observed in production.

## LinkedIn closeout

1. **APIs/products:** OpenID Connect; Share on LinkedIn; versioned Posts, Images, Videos, Documents; Community Management comments/reactions; organization ACL/authorization; member creator post analytics and organization statistics/video analytics. Headers use `LinkedIn-Version: 202609` and Rest.li 2.0.0.
2. **Permissions:** initial `openid profile`; member publishing `w_member_social`. Separate approved groups cover `rw_organization_admin`, `r_organization_admin`, `w_organization_social`, `r_organization_social`, `r/w_organization_social_feed`, `r/w_member_social_feed`, `r_member_postAnalytics` and restricted `r_member_social`. Required combinations appear per row. None newly requested/granted live.
3. **Review state:** OIDC/Share product enablement unverified; Community Management Development/Standard and restricted permissions unverified. Historical member reading: **BLOCKED — LINKEDIN APPROVAL**.
4. **Member capabilities:** identity; text/link/image/video/PDF/multi-image/poll publishing; commentary edit/delete; comments/replies/reactions and analytics adapters with separate permissions. No read privilege is inferred from member write.
5. **Organization capabilities:** separate destination selection/discovery and fresh authorization. Content writes use organization authorization; feed reads/writes use verified ACL roles and corresponding feed scopes. Organization existence alone grants nothing. Organization posts, community actions, share/follower/Page/video statistics have individual rows.
6. **Post types:** text, link/article URL card, image, multi-image, video, PDF and poll. Celebration creation is unsupported. An ArticleContent URL card does not author an article/newsletter.
7. **Scheduling:** Rafii worker; no audited public native scheduling contract for these posts. Approved payload/media/time are immutable; grant and role are rechecked.
8. **Comments/replies:** provider-native operations; nested parent comment URN and root activity/share/UGC identifiers preserved. Community Management approval and real feed grants required. Read/write role sets differ.
9. **Analytics:** native member post counters with valid date/query aggregation; organization share/follower/Page/video endpoints. Organic document analytics stays **OFFICIAL AUDIT UNAVAILABLE**. No fake reach or substitution of advertising metrics.
10. **Restricted capabilities:** historical member read; member feed/community and organization products; eligibility-specific analytics. Article/newsletter authoring: **UNSUPPORTED BY OFFICIAL API** for audited public contracts.
11. **Real E2E:** every requested case is NOT_RUN; see the live matrix. Ordinary member and eligible organization were not available through an authorized live session.
12. **Blockers:** app/product approvals, actual grants, destination roles, credential validity and live execution evidence. Member image processing can be held when the available write grant cannot confirm `AVAILABLE` even after the documented legacy GET fallback.
13. **Production verdict:** **NOT PRODUCTION READY**. Engineering adapters are present; no claim of LinkedIn approval or real E2E.

## Threads closeout

Official Threads API uses its own `v1.0`, not the Facebook Graph version. Identity requests `threads_basic`; publishing adds `threads_content_publish`. Insights, reading replies, managing replies, deletion, mentions and locations separately require `threads_manage_insights`, `threads_read_replies`, `threads_manage_replies`, `threads_delete`, `threads_manage_mentions` and `threads_location_tagging`.

Implemented formats include text/image/video/ordered carousel, reply, quote/repost, poll, long text attachment, ghost post, Tenor GIF attachment, spoilers, reply approvals, mentions/links and location tagging. Child processing, ordered parent creation, parent readiness and final publication are separate transitions. A container is never a published receipt. Native replies preserve root/parent; reply management and Insights use actual grant checks and native provenance. No verified post-edit method is exposed; delete is separately permissioned.

Scheduling is Rafii-managed. Long-lived exchange/refresh and quota reads are implemented; the current publishing-limit response governs capacity. Meta Threads use case/Advanced Access, ordinary account eligibility, actual scopes, long-lived refresh and all live cases are **unverified / NOT_RUN**. **NOT PRODUCTION READY**.

## Instagram closeout

Selected path: Instagram API with Instagram Login for professional Creator/Business accounts; no Facebook Page is required by this path. Initial basic identity/media uses `instagram_business_basic`; publishing and comments use separate `instagram_business_content_publish` and `instagram_business_manage_comments` intents. Messaging is separately modeled and unimplemented for this release.

Implemented image, carousel, Reel and eligible Business Story publishing includes create → processing → ready → publish request → canonical media readback. Media IDs/permalinks survive receipts; Story expiry is distinct from failure. Captions and allowed options are validated; video processing failures do not become success. Comments list/replies/hide/delete operate with native IDs. Scheduling is Rafii-managed with fresh token/account verification and no replay after unknown publish.

**Insights, account insights and Reel insights are blocked by the unavailable primary Instagram Login permission/metric audit.** There is defensive adapter code, but this group is not offered for OAuth and requests stop before provider dispatch. Meta returned 429; official SDK method presence cannot prove login-path permission. Editing/deletion remains audit-unavailable. Location/product tagging is excluded by the audited Instagram Login collection; a separate reviewed API path would require a separate audit/implementation. Current account type, Advanced Access and app review are not verified. Every live case is NOT_RUN. **NOT PRODUCTION READY**.

## Facebook closeout

Facebook Login for Business plus Graph `v26.0` manages selected Pages. Personal timeline publishing is unsupported. `/me/accounts` discovery and fresh Page tasks are checked; Page tokens and app-secret proof remain server-side. Initial discovery uses `pages_show_list` and the required read scope; publishing adds `pages_manage_posts`. Community groups use `pages_read_engagement`, `pages_read_user_content` and, only for writes/moderation, `pages_manage_engagement`. Insights adds `read_insights`; `pages_messaging` is a separate, unimplemented Messenger intent.

Implemented Page text/link/photo/multi-photo/video/Reel/Story lifecycle, comments/replies/moderation, engagement reads, native insights and edit/delete. Supported feed text/link/photo scheduling uses provider-native scheduling in the validated future window; other implemented video/Reel/Story paths use Rafii workers. Page permission/task is rechecked before writes. Story upload readiness is not publication; canonical `PUBLISHED`/`ARCHIVED` and published fields distinguish publication/expiry.

No current Page task/token validity, Business Login configuration, Meta Advanced Access or review was proven. Required permissions and native metrics remain endpoint/account specific. All ordinary Page E2E cases are NOT_RUN. **NOT PRODUCTION READY**.

## X closeout

OAuth 2 PKCE initial groups contain `users.read tweet.read offline.access`; publishing intentionally adds `tweet.write` and `media.write`. Implemented official v2 post creation supports text, reply, quote, threads, images/multi-image, GIF, video, poll, media metadata/alt text, edit/delete, repost, post/conversation reads and native public/authorized metrics. Long video processing is polled. Rafii scheduling uses the same immutable worker.

Fresh official OpenAPI exposes Article draft/publish authoring. Therefore Articles are **documented and implemented through reviewed native action contracts**, with account/product access still unverified. Rafii's standard composer retains its 280-character policy; long-post/Article account eligibility is not inferred from the consumer UI. DM, likes/bookmarks/follows are not silently enabled; DM is separately modeled and unimplemented.

Actual X tier, balance/credits, account entitlements and scopes are unknown. All metered requests, including identity reads, require an operator-owned explicit connection budget, endpoint allowlist and durable per-request cost ceiling reservation. Reservations survive unknown effects; they are not a provider invoice or a live credit balance. Quote creation is restricted to X Enterprise by the current create-post documentation and held before media/cost requests unless matching Enterprise product proof exists. Article requests use the official blocks/entities schema and optional cover_media. No budget was approved and no paid X request was executed. All live tests including exhaustion are NOT_RUN. **NOT PRODUCTION READY**.

## YouTube closeout

Data API v3, Analytics v2, Reporting v1 and Live Streaming are implemented. Initial channel/media read uses `youtube.readonly`; upload uses `youtube.upload`; management/comments/captions/live use `youtube.force-ssl` when needed. Thumbnails accept upload or force-ssl. Analytics `yt-analytics.readonly`, monetary `yt-analytics-monetary.readonly` and memberships `youtube.channel-memberships.creator` are separate intents.

Resumable upload persists encrypted session URLs and reconciles byte offsets before recovery. Upload completion is followed by processing/playability/readback. Videos and Shorts use normal upload; current Shorts eligibility is validated independently. YouTube-native future `publishAt` scheduling uses private status. Public/unlisted visibility requires the separate verified project compliance gate. Metadata/localizations/Made for Kids/altered-content disclosure/subscriber notifications, thumbnails/captions, playlists and podcast playlist actions are implemented. Comment threads/replies/moderation, Analytics/Shorts metrics and Reporting jobs/reports are provider-native. Owned CSV report download is bounded to 512 KiB and 500 displayed rows with hash/truncation/provenance; large report export is not implemented.

Live broadcasts and streams remain separate resources with bind/transition/schedule; live chat read/write/moderation uses official REST. gRPC streaming chat is not implemented. Advanced live/podcast/caption/membership/report/Article/commerce operations currently have API review/approval contracts rather than complete consumer editors. Community Posts: **UNSUPPORTED BY OFFICIAL API**. OAuth verification, project quota, public-upload audit, channel/membership/monetization/live eligibility and all live tests remain unverified. **Implementation candidate validated; Google approval readiness and production readiness not established.**

## TikTok closeout

Login Kit, Content Posting Direct Post/Upload and Display API are used; Research API is not used as creator management. Identity `user.info.basic`, publishing `video.publish`, upload/inbox `video.upload`, owned media `video.list` are separate groups. Current creator privacy, duration and interaction capabilities are obtained before direct posts; privacy has no invented default and exact consent/disclosures are frozen into review.

Implemented video file/verified-URL Direct Post, verified-URL photo Direct Post, video file/URL inbox and photo inbox; cover timestamp/photo-cover order, AI disclosures and photo auto-music where exposed; best-effort URL transfer cancellation with its own immutable approved action. Init/transfer/native status and rejection/visibility reconciliation remain distinct. Inbox acceptance requires creator completion and is not publication. URL domains must be verified explicitly. Public Publishing: **BLOCKED — TIKTOK AUDIT** without matching audited-app proof. Interrupted file transfers are fenced as unknown and reconciled by publish ID; durable per-chunk continuation is not implemented, so recovery may require provider/manual reconciliation rather than a fresh post.

Display reads are implemented. No audited general public creator comments/replies/analytics/edit/delete contract is exposed. Scheduling is Rafii-managed; inbox scheduling schedules a handoff, not the creator's final publication. Audit/approved scopes/domain ownership/account settings/current posting limits and all live tests are unverified. **NOT PRODUCTION READY**.

## Pinterest closeout

Official API v5 with business-account identity, Boards/Sections, image/video Pins, Pin CRUD, title/description/link/alt text and destination assignment. Initial identity `user_accounts:read`; board/Pin reads and writes are progressive `boards:read/write`, `pins:read/write`. Video media registration/S3 transfer/status success precedes Pin create. Unknown create outcomes stop replay. Scheduling is Rafii-managed.

Pin/account/video analytics, Trends and separately authorized ad-account audience insights use native endpoints and reporting context. Commerce is separate `catalogs:read/write`, merchant eligibility and product tags. Implemented commerce subset: credential-free RETAIL feed CRUD/ingestion and product-group CRUD; protected feeds, hotel/creative catalogs and batch item mutation are outside the implemented flow. Product tags require eligible product Pin IDs. No official comment/reply management is claimed from engagement counts.

Actual Trial/Standard access, business/ad/merchant eligibility, scopes and limits are unknown; client credential names were absent in inspected production environment. Every live case is NOT_RUN. **NOT PRODUCTION READY**.

## Validation and JCB

JCB resolves to the existing internal **James Cloud Build Python control-layer CLI**, not a third-party package. `~/.local/bin/jcb` points to `/Users/ouxianxing/Documents/James-Cloud-Build/bin/jcb`; implementation is `scripts/jcb.py` and snapshot/cache/runner helpers. Source of truth: that repository's `PRD.md`, `ENGINEERING-SPEC.md`, `README.md`, and `docs/superpowers/plans/2026-10-05-cloud-build-worker.md` plus execution details. CLI/Depot were already installed. PATH was missing; using the existing binary and configuring Rafii's reviewed adapter repaired routing. The JCB source was not rewritten and no public package named jcb was installed.

Rafii's `.james-cloud-build.json` and generated `.depot/workflows/james-cloud-build.yml` submit dirty-source snapshots without a Git push. Explicit excludes omit unrelated media/docs/vendor and forbidden credential files; no local `.env` or home credential stores are uploaded. Heavy jobs run Linux on Depot. Local checks after the latest policy were limited to metadata/export, `git diff --check`, shell syntax and individual targeted units. Earlier local Python/SQL results predate the stricter policy and are not reused as the final cloud evidence.

| Cloud validation | Run ID | Result |
| --- | --- | --- |
| Full CI: frozen npm install, audit, lint, typecheck, 480 Node tests, 209 Python tests, 15 PostgreSQL lifecycle tests plus SQL safety assertions, Next production build | `gp922n7frg` | PASS, exit 0 |
| Synthetic Next/Playwright desktop 1280/mobile 390: granular state, native hierarchy, immutable approval, exactly one send, unknown prevents duplicate, overflow | `4kxl4rpwqh` | PASS, exit 0; both screenshots inspected |
| Backend after least-privilege refinements | `r0nwr4qjmg` | PASS, exit 0; 209 Python + 15 PostgreSQL |
| Final backend: TikTok transfer lifecycle and X Article/Enterprise contract refinements | `nd84zg5dg1` | PASS, exit 0; 216 Python + 15 PostgreSQL |

Full CI and browser evidence covers unchanged frontend/Next 16.3.6; the final backend change has its separate affected cloud check. Next was narrowly patched from 16.3.5 to 16.3.6 for the official critical advisory; final cloud npm audit reported zero vulnerabilities. No local dependency install, TypeScript suite, production build, browser suite or PostgreSQL suite substituted for cloud execution under the updated policy.

JCB tooling is usable. Its standard checkout cleanup logs an unrelated missing `.gitmodules` URL warning for the existing dirty vendor submodule; selected jobs still exit 0. No unrelated submodule repair was made. A custom artifact upload step was rejected by JCB's reviewed-workflow equality guard, then removed; synthetic screenshots were instead recovered from bounded cloud log exports. The guard was respected.

## Remaining gates and exact release state

**Tooling/documentation:** live browser inventory is `validation_unavailable` because browser request-header policy could not load (two attempts); no bypass was attempted. Instagram Login current Insights/edit/delete primary audit remains unavailable (429/empty official search). JCB itself has no remaining execution blocker. Token Pilot checkpoint was attempted with zero new entries but failed because the shared 256-entry registry is full; no other-session records were deleted. HANDOFF.md preserves task recovery. Large YouTube report export, streaming live-chat transport, durable TikTok chunk recovery and complete advanced consumer editors are stated implementation limits, not provider approvals.

**Provider/external:** valid client configuration, new actual OAuth grants, Meta/LinkedIn/Pinterest access reviews, TikTok audit and domain verification, Google OAuth/public-upload compliance, eligible ordinary accounts/organizations/Pages/channels, explicit X billing ceiling, and approved live test content/destinations. These are separate from JCB/CI. No external test content or destinations were approved for publication in this task.

**Git/release:** a scoped local commit is recorded in DELIVERY.json. No PR was created, no branch pushed, no merge or GitHub release CI was triggered, and this candidate was not deployed. Read-only Vercel inspection found an existing READY **preview** for `codex/jcb-cloud-validation-20261005` at SHA `2bd8917bd47bf2683d8c5d1c01b949db4fb4c952`; it is not this candidate and proves no production result. Production verification for these new capabilities: **NOT_RUN**.

The next release step is the concrete operator/live test plan in OPERATIONS.md and the exact cases in live-e2e-matrix.json. The overall objective remains blocked on external gates; cloud engineering validation alone does not complete it.
