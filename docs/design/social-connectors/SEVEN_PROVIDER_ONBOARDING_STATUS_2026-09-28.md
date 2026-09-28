# Seven social connectors: execution and onboarding receipt

Baseline: `release/rafii-consolidation-20260928` at `bdf5c9f`; it contains the Wave 4A, 4B and 4C connector work from PRs #59, #61 and #63. `consumer-saas` at `a603392` is an ancestor. PR #67 is open; the canonical checkout has unrelated changes and was not edited.

Production origin: `https://postriff-phase2-private.vercel.app`. The homepage, privacy, terms, data deletion and contact pages returned HTTP 200 on 2026-09-28. The fixed callback route was verified in `OAuthService.callback_uri`: `https://postriff-phase2-private.vercel.app/api/oauth/{provider}/callback`. No provider reviewed/live-test flag was enabled in this branch.

## Registration material ready for the provider consoles

App name: **Rafii**. Purpose: let a person connect their own social account, review an exact post in Rafii, approve that post, and receive provider-confirmed publication status where an official API grants that capability. Public URLs: [home](https://postriff-phase2-private.vercel.app), [privacy](https://postriff-phase2-private.vercel.app/privacy), [terms](https://postriff-phase2-private.vercel.app/terms), [data deletion](https://postriff-phase2-private.vercel.app/data-deletion), [contact](https://postriff-phase2-private.vercel.app/contact). This packet is a candidate for each portal's actual form; it is not a submitted application.

| Portal | Fixed callback or method | Minimum current request | Review evidence still needed |
| --- | --- | --- | --- |
| Douyin | `/api/oauth/douyin/callback` | `user_info`; separately `video.create.bind` and `posting.behavior` for approved write/read-back | Signed-in app, scope product approval, provider-specific demo and controlled video test |
| Kuaishou | `/api/oauth/kuaishou/callback` | `user_info`; separately `user_video_publish` and `user_video_info` | Signed-in app, scope approval, secure HTTPS upload-gateway contract and controlled video test |
| Reddit | `/api/oauth/reddit/callback` for identity only | identity grant only; every posting User Action remains manual | James's Developer Terms acceptance, reviewed app/user-action permission |
| Google Business Profile | `/api/oauth/google_business_profile/callback` | `openid`, `profile`, `business.manage` | An eligible managed verified business/location, Google API project approval and controlled location-specific post |
| Pixelfed | Dynamic app registration on a chosen public instance; callback `/api/oauth/pixelfed/callback` | `read`; separately `write` on a qualified instance | Chosen instance, account consent, compatible write/read-back test |
| Weibo | No hosted callback registered | No hosted scopes requested | Verified multi-user official OAuth contract beyond CLI/operator access |
| Zhihu | No hosted callback registered | No hosted scopes requested | Official production OAuth/read and separate write contracts |

| Provider | Existing Wave 4 implementation | Engineering delta | External prerequisite | Final state |
| --- | --- | --- | --- | --- |
| Weibo | Gated catalogue contract; no hosted OAuth | Keep hosted connection disabled; document operator CLI as separate diagnostic | Official multi-user web OAuth app contract, identity verification, any credit decision | BLOCKED_EXTERNAL |
| Douyin | Identity OAuth, refresh and grant-scope extraction | Video upload/create/reconciliation, scope-specific connection and bounded media | App permission for `video.create.bind` (current official create endpoint), approved OAuth, controlled write test | BLOCKED_EXTERNAL |
| Kuaishou | Identity OAuth, refresh and grant-scope extraction | Video upload/publish/reconciliation, scope-specific connection and bounded media | `user_video_publish` app approval, approved OAuth, controlled write test | BLOCKED_EXTERNAL |
| Reddit | Identity OAuth, refresh/revoke and review gate | Explicit manual User Action UX; no background publisher | Reviewed Devvit/User Actions contract for Rafii | BLOCKED_EXTERNAL |
| Google Business Profile | OAuth, account/location discovery and a location picker | Ensure selected location is the named destination; Local Posts Update/Event/Offer publisher and lookup | Google project Business Profile API approval, managed verified location, controlled write test | BLOCKED_EXTERNAL |
| Zhihu | Catalogue gate only; no guessed OAuth endpoints | Keep publish unavailable; connect/read only after exact production contract | Provider's approved OAuth/read contract and separate written production write contract | BLOCKED_EXTERNAL |
| Pixelfed | Per-instance probe, dynamic app registration, PKCE, encrypted client data in grant, identity OAuth | Write-scoped connection, media/status execution, per-instance compatibility and read-back | Eligible instance and controlled OAuth/write acceptance before any Direct claim | BLOCKED_EXTERNAL |

`BLOCKED_EXTERNAL` here means no provider is production qualified. No public test post is authorized by this receipt. No `REVIEWED`, `PUBLISH_APPROVED`, `PUBLISH_LIVE_TESTED`, or `QUALIFIED_INSTANCES` runtime value was enabled.

## Transition log

- 2026-09-28: Reconciled Git and PR state. No connector registration or production credential installation observed yet. Portal work and engineering in progress on isolated branch `codex/rafii-seven-hosted-connectors`.
- 2026-09-28: Implemented hosted publisher candidates for Douyin, Kuaishou, Business Profile, and Pixelfed; approved MP4/cover manifests, Business Profile post options and location choice, per-instance TLS/DNS pinning, bounded media reads and uploads, and conservative reconciliation. These are local engineering paths, not live provider approval.
- 2026-09-28: Douyin developer portal reaches phone/email login requiring a provider code. Kuaishou portal reaches phone verification or app QR login. No app or credentials were created.
- 2026-09-28: Google Cloud project `rafii-509720` has Rafii OAuth branding in Testing and one existing YouTube client. The Business Profile API is not available in its API library. The signed-in Business Profile dashboard shows zero businesses and zero verified locations. Google requires an account managing a verified eligible location before its API access application. No location was selected or invented.
- 2026-09-28: Reddit Developer Platform is signed in as `Ok-External401`; developer registration stops on the explicit Developer Terms and Developer Funds Terms acceptance screen at `https://developers.reddit.com/new/terms`. James must review and accept these terms himself before app registration. This does not waive Reddit's separate API/User Actions approval.
- 2026-09-28: Weibo Open Platform shows a sequence of developer verification, app creation, assisted integration testing, and review. The browser was not signed in to developer verification; the developer link returned to the public homepage. Weibo CLI/paid commercial APIs remain separate from a multi-user hosted OAuth contract.
- 2026-09-28: `open.zhihu.com` was blocked by this browser before its portal could be inspected. No official production write contract was verified. Zhihu remains disabled for hosted OAuth and publishing.
- 2026-09-28: `pixelfed.social` is reachable and displays an account login form; no Pixelfed account was available in the current session. Rafii's dynamic OAuth registration requires a user's chosen instance and actual account consent, followed by a controlled instance-specific compatibility/write check.
- 2026-09-28: A read-only call through Rafii's DNS-pinned transport to `pixelfed.social` passed the public instance probe and reported `3.5.3 (compatible; Pixelfed 0.14.3)`. This is instance identity evidence only; OAuth consent, image/status compatibility and account-specific write remain untested.

## Local validation and release boundary

- Python domain/security suite: 2,936 tests passed, 259 skipped (synthetic provider transports; no live post).
- Wave 4 focused suite: 33 passed after the final connector edits.
- Disposable PostgreSQL: `postgres_channels`, `postgres_instagram_lifecycle`, and `postgres_safety` passed. These cover encrypted grants, OAuth/RLS boundaries, scope downgrade and lifecycle safety. The full runner was attempted with the correct test environment but the host ran out of disk space during a later temporary cluster, so the full gate remains `validation_unavailable: ENOSPC` locally.
- Frontend: Node 24 typecheck passed; lint found zero errors and zero warnings; 456 Node contract tests passed. Isolated `npm ci` completed. Node 24 webpack production build passed. The default Turbopack build did not pass locally because the host ran out of disk space during its cache/build and reported an async panic.
- Local browser: `ui-simplification-browser.cjs` passed 64 checks against a real locally built Next app and disposable PostgreSQL harness, including shared connection status and no page/console errors. No authenticated provider OAuth/browser callback test could run without approved apps and grants.
- Secret scan: `consumer_ready_secrets.py` passed: 2,132 files, 456 known findings, zero unexpected findings.
- No provider app was registered, no provider credential was issued or installed, no review was submitted, no runtime approval flag was enabled, no live provider authorization or public post occurred. This branch is a candidate for CI review, not a production release.
- After reconciling the newer `consumer-saas` head, the full Python suite passed 2,952 tests (261 skipped), Node 24 typecheck and zero-warning lint passed, and focused growth-beta/performance tests passed. Draft PR #70 contains the merge resolution and is pending CI.
