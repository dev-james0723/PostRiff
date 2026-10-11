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
- Analytics collects only native public/unlisted favourites, boosts and replies through the existing metric scheduler; private/direct/foreign/reblog rows are excluded. Settled observations/reads retain 90 days and exact action bodies seven days, with bounded worker sweeps and disconnect deletion. The account drawer and central Analytics bind history to the current credential/instance; unavailable impressions/reach/demographics are never invented.
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

## Engineering and release work still open

- Complete metadata/website-attribution and version-gated avatar/header descriptions; explicit keep/clear default-language behavior and server-advertised profile limits.
- Tighten single-post/native publication read-back to all approved reply/language/poll/quote/sensitive fields; verify unavailable grant handling safely defers an unsent operation.
- Put read admission ahead of network-backed OAuth verification; prove exhausted SQL quotas cause zero provider calls.
- Mastodon-specific actual SQL/worker regression evidence for the existing Automations engine: default approval, explicit owner standing grant, independent destinations and pause fencing. Full management OAuth is not automation authority.
- Purpose-specific private mention/reply AI consent and retention safeguards; no private bodies enter models or broad Analytics by default.
- All real acceptance A–E, real health/streaming and media/owned edit/delete/native/managed schedule verification on two independently hosted accounts, actual returned URLs.
- Required release CI on the final commit, independent review of remaining candidate risks, isolated staging and authorized production migrations/gates. Apply no production change until mission criteria pass.

## Cloud evidence

Use `.james-cloud-build.mastodon.json` with JCB from this actual worktree. Back up/restore `.james-cloud-build.json` and `.depot/workflows/james-cloud-build.yml` around scoped setup; never commit the unrelated default mapping replacement. Cloud source transport includes the safe dirty patch and does not require a push for validation. Local work remains file edits, metadata and Git; no local Node/build/database/browser suites.

Latest fully retained baseline is `d3c05ncb96`: 463 Python, 21 Mastodon SQL, 35 web contracts, Library/migration regressions, lint/typecheck/build and synthetic Channels/profile browser at 1440/390/320. The capacity proof measures 1,000 simultaneous pending requests backed by 1,000 encrypted tenant identities, bounded to 32 SQL operations. 400 requests were admitted and 600 deferred; actual peak SQL connections 31. The shared worker claimed 40 distinct tenants from 2,000 already accepted native-readback jobs. No provider was called. This is disposable SQL/synthetic-request evidence; it does not claim 1,000 physical database connections or production HTTP load.

Latest retained phase7 run `blvhrhvvwn` passes 467 Python, 22 Mastodon SQL, 35 web contracts, Library/migration regressions, lint/typecheck/build and actual Channels/profile/Queue browser at 1440/390/320. Queue journeys cover thread, two described decoded images, normalized Library WAV and accepted pending native schedule followed by unique media-bound publication without another write. They use the actual shared approval/SQL/worker paths with explicitly synthetic responses and advanced fixture clock. Official CI artifact storage retains the 19 proof files plus SHA256 manifest. Runs `txxsvh7tmk` and `vcd1n5pwck` returned exit0 but lost terminal evidence; they are superseded for acceptance evidence, not silently described as a full Queue pass.

Phase7 also repairs bounded shared DNS admission and one absolute request deadline, a scrollable Queue dialog, missing native Queue option support, and SQL savepoint isolation of the optional insights callback. A real PostgreSQL division-by-zero regression confirms publication receipts survive a failed optional hook and repeated completion cannot call the hook again.

Broad GitHub CI passes on committed `9f4690ab24d8296ecaefad75ff1b39ff8ae9281b`: local gates, Agent UI/browser, native learning/browser, Growth Studio, Scenes, Document Runtime, Library and Founder. That result does not cover uncommitted phase7. Vercel branch output is a preview. Real acceptance remains NOT_RUN; migrations113–115, public provider gates and rafii.io production remain unchanged. Exact receipts and observations belong in `validation.json`.

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
