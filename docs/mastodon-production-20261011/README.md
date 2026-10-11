# Rafii Mastodon production candidate — 2026-10-11

Execution state: **candidate; production acceptance NOT RUN; NOT DEPLOYED**.

Worktree: `/Users/ouxianxing/Documents/Open Claw/rafii-mastodon-production`.
Branch: `codex/rafii-mastodon-production-20261011`.
Base: `b7b9b3ee94f89a80b1d80826226584d214b17847` (`origin/consumer-saas`).

## Candidate implemented

- Arbitrary compatible public HTTPS instance domains/account handles, strict URL validation, all-answer public DNS checks, pinned TLS connections, no redirects, bounded JSON and request timeouts.
- Instance API version/configuration discovery; modern OAuth metadata origin validation; S256 PKCE on 4.3+, conservative compatibility for older Mastodon. Pixelfed keeps its separate existing authorization contract.
- Per-instance application registration cache with encrypted credentials, binding to redirect/scopes/website and database advisory locking. Encrypted account token envelope includes the instance; app scopes cannot expand token scopes. No assumed refresh token.
- Force account selection, instance-qualified verified account identity, configurable read/publish/profile/interaction/full management scopes, one-time OAuth callback claim before exchange.
- Existing Channels card account reads and human-reviewed action journal: posts, profile, timelines, notifications, bookmarks, favourites, lists, preferences, mutes/blocks, local trends, native schedules; favourite/boost/bookmark/follow/mute/block inverses; owned-post edit/delete; profile text/settings and immutable avatar/header uploads; list management; text-only native create/reschedule/cancel.
- Persist exact account/target/content digest with actor and ten-minute expiry. Commit claim before external action; concurrent/repeated confirmations do not resend. Recheck current membership and exact unrevoked credential before dispatch. Per-account and per-instance request caps. Treat ambiguous outcomes as uncertain, and distinguish provider acceptance, verified deletion and pending native schedules.
- Existing unified publish/calendar path gains Mastodon visibility, warning, sensitive media, reply/quote target and polls, verified video selection, fresh instance limits before dispatch, SHA256 idempotency keys and approved media integrity checks. Stop automatic re-upload when processing remains inconclusive.
- Existing Brand Brain writing pipeline, legacy drafting/automation routing, Agent Chat and Automation builder destination pickers accept Mastodon drafts. Agent SDK tools identify the exact connected account, return explicitly requested public/unlisted numeric engagement observations, or save unapproved action previews linking to Channels. No Agent tool approves or executes external actions, reads private notification bodies, or grants automation authority.
- Analytics collects only native public/unlisted favourites, boosts and replies through the existing metric scheduler; private/direct/foreign/reblog rows are excluded. Settled observations/reads retain 90 days and exact action bodies seven days, with bounded worker sweeps and disconnect deletion. The account drawer still needs the historical central-dashboard projection; unavailable impressions/reach/demographics are never invented.
- Unified approval supports up to four independently described, rights-confirmed images or one verified video/audio. Normalized Library audio freezes tenant-owned hash/object/etag metadata, rechecks approval/worker custody, and blocks deletion during dispatch.
- One exact existing Queue review freezes up to ten thread parts. Each child uses its saved preceding post ID, a distinct approved idempotency key, committed intent before dispatch, current identity and unchanged parent checks; unknown writes never resend. Every saved part must be read back before the whole thread verifies. The Agent prepares an unapproved Queue review and does not acknowledge warnings or grant publication authority. Rafii-managed threads only; native scheduling plus thread is rejected before dispatch.
- Existing worker progress durably checkpoints media intent and accepted IDs, upload processing, Retry-After/reset/exponential cooldown and status acceptance. Known uploads resume by ID; uncertain upload/status writes never resend. Correct bounded private audio/video reads and exact instance-qualified publication URLs are enforced.
- Unified native scheduling uses the existing queue, commits accepted schedule IDs and verifies scheduled settings/media. Pending native schedules remain processing; absence alone never proves publication. Media schedules reconcile only a unique exact owned post.
- Agent post-freeze extensions declare explicit-request-only behavior, localized public titles and no mutation retries while preserving frozen baseline contracts.

## Version matrix (capability detection; live behavior unverified)

| Feature | <2.7 | 2.7+ | 2.8+ | 3.5+ | 4.3+ | 4.5+ |
|---|---|---|---|---|---|---|
| Basic authorization code / instance-qualified account | compatible APIs required | same | same | same | same | same |
| S256 PKCE | not assumed | not assumed | not assumed | not assumed | detected/version fallback | detected/version fallback |
| Native scheduling | disabled | available if server permits | same | same | same | same |
| Polls | disabled | disabled | supported with server limits | same | same | same |
| Post edits | disabled | disabled | disabled | supported | same | same |
| Quote posts | disabled | disabled | disabled | disabled | disabled | supported if permitted |

Limits, supported formats and scope support are determined by the instance. Version flags alone do not prove real execution or compatibility with every fork. Native status scheduling is distinct from Rafii’s managed calendar and does not prove publication or federation delivery.

## Mandatory acceptance still NOT RUN

A: real login, OAuth authorize/verify/disconnect/reconnect on two independently hosted instances.
B: real media publication, actual returned post URLs, owned edit/delete and deletion verification on both instances.
C: native and Rafii-managed scheduled publication, provider read-back and Rafii state update.
D: authorized Brand Brain generation, approval policy, automation execution, pause and no further actions.
E: independent account destinations and revocation isolation.

**External input needed:** exact two authorized account handles, signed-in OAuth authorization by their owner, and authorization to publish/edit/delete clearly labelled acceptance test posts. No passwords or tokens should be pasted into chat. Asked in this conversation; no reply received as of preparation. Native ORC browser routing recovered after specifying the Mac target. Read-only inspection confirmed signed-in rafii.io Channels; no Mastodon owner authorization or real acceptance was performed.

## Engineering work still open before production

- Expand profile metadata/attribution UI and newly introduced server preferences when supported; avatar/header, text, locked/bot/discoverable/hide/indexable and default privacy/sensitive/language/quote preferences now have checked exact action support. Images use a conservative 2 MB cap and existing private Library storage.
- Private mention/reply suggestions with explicit per-purpose AI consent and retention safeguards.
- Add dedicated application-browser Queue thread/media/native journeys. The durable thread publisher and Agent review-only planning now pass synthetic Python/SQL contracts; real thread acceptance remains NOT_RUN.
- Live-enable and verify numeric history collection only after release gates pass. Central Analytics now binds Mastodon observations to the current credential/instance and native count names; account/Agent history projects up to 500 readings over 90 days for currently public/unlisted posts in the latest 40. It stores no private bodies or unavailable reach.
- Add Mastodon-specific regression evidence for the existing shared owner-authorized automation engine (`automation_plan.activate`, `automation_runs.build_items`/commit and `automation_edit` pause), then mandatory real automation acceptance. Reuse that engine instead of inventing a separate standing-authority system. Full management OAuth scope is not automation consent.
- Extend supported read scheduling only where needed; exact account action previews never automatically resend ambiguous writes. Periodic health now runs at most one due connection through the existing worker, with service-only leases, jitter/backoff, exact credential fencing and account migration/suspension/revocation safeguards.
- Dedicated application-browser coverage of the new Queue multi-image/audio/native controls and live media/native reconciliation evidence.
- Real-instance health and streaming acceptance. Periodic account checks, exact native reschedule/cancel synchronization and bounded foreground SSE pass cloud contracts/SQL/browser checks. SSE windows may miss events; notifications remain the backfill path. Private excerpts stay out of AI/Analytics.
- Production HTTP/fleet load acceptance. The cloud simulation now measures 1,000 concurrent connected-user requests backed by 1,000 encrypted identities and actual SQL admission: 400 admitted,600 deferred,31 peak SQL connections with a bound of32. Real Queue selection claims40 distinct tenants from2,000 seeded native-readback jobs. This is not a1,000-HTTP-connection or live-publication claim.
- Complete release security review and all required live acceptance before changing public execution gates, applying production migrations 113/114/115, merging or deploying rafii.io. Candidate source review is in `security-review.md`; it records remaining risks and does not certify production.

## Cloud validation

All Node/Python suites, PostgreSQL, production builds and browser automation execute on Depot/JCB. Local work is restricted to edits, Git, syntax/JSON inspection and log/artifact recovery. No local dependency installation or heavyweight validation.

Run scoped validation from the actual worktree with `.james-cloud-build.mastodon.json`. The JCB controller currently uses a single generated workflow path and `setup --force` updates both the root config and workflow. Before setup, back up those two files; restore their original contents after the scoped run. Do not replace the repository’s unrelated default YouTube mapping when committing this candidate. No deployment workflow is used.

Passed scoped cloud run `fww642glg2` (JCB exit 0; dirty-source fingerprint recorded): 457 Python contracts, 15 disposable SQL action/isolation/media/profile/history/retention tests, Library database/lifecycle regressions, migration replay/upgrade/restore checks, 34 selected web contracts, lint, typecheck, production build and application browser journeys at 1440/390/320px. The automation regression exposed and repaired a missing Mastodon entry in the legacy drafting/platform picker; it verifies separate account destinations, pausing and refusal of auto-publish activation without a standing grant. It does not demonstrate live generated content or worker publication. SQL and browser providers are explicitly synthetic. The run adds durable thread fault/cancellation/parent/readback/Agent planning contracts, thread receipt UI, dedicated profile screenshots, selected-profile-field/default-privacy browser approval, tenant/hash-bound profile image SQL, central/history instance isolation, native-calendar publication time, Mastodon verified-link contracts and native read cooldowns. Queue media UI coverage is still open. Broader GitHub CI now passes Agent UI browser on 744b66ec; document-runtime fails on an unreachable LibreOffice mirror and local-gates was still running at last observation. This is not a full CI pass. The final run includes unique per-form field IDs and analytics ID/timestamp sanitization. Evidence and exact limitations are recorded in `validation.json`.

## Official sources checked

- [Profile updates and versioned preferences](https://docs.joinmastodon.org/methods/accounts/#update_credentials)
- [OAuth tokens and PKCE](https://docs.joinmastodon.org/client/token/)
- [OAuth methods](https://docs.joinmastodon.org/methods/oauth/)
- [Application registration](https://docs.joinmastodon.org/methods/apps/)
- [OAuth scopes](https://docs.joinmastodon.org/api/oauth-scopes/)
- [Statuses](https://docs.joinmastodon.org/methods/statuses/)
- [Media upload and asynchronous processing](https://docs.joinmastodon.org/methods/media/)
- [Native scheduled statuses](https://docs.joinmastodon.org/methods/scheduled_statuses/)
- [Rate limits](https://docs.joinmastodon.org/api/rate-limits/)

Publication to one instance does not guarantee immediate Fediverse distribution. No administrator scopes are requested.

Latest candidate validation: JCB `rmn14j4fcw` (exit 0), 457 Python / 17 Mastodon SQL / 35 web contracts, lint/typecheck/production build and synthetic browser at 1440/390/320. Native schedule amendment preserves the original approval and fences old worker leases; SSE rechecks current authorization before returning private excerpts. Real A–E acceptance remains NOT_RUN.

Latest candidate validation: JCB `d3c05ncb96` (exit0),463 Python /21 Mastodon SQL /35 web contracts plus1000-user SQL simulation and full synthetic application browser. Peak pending requests1000,SQL connections31,request p95 775.662ms;40 distinct tenants claimed with p95 8.299ms. Health never follows a migrated-account URL or transfers an approval. Production migrations113–115 remain unapplied.
