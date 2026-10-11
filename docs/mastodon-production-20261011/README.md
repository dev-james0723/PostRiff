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
- Existing Channels card account reads and human-reviewed action journal: posts, profile, timelines, notifications, bookmarks, favourites, lists, preferences, mutes/blocks, local trends, native schedules; favourite/boost/bookmark/follow/mute/block inverses; owned-post edit/delete; profile text/settings; list management; text-only native create/reschedule/cancel.
- Persist exact account/target/content digest with actor and ten-minute expiry. Commit claim before external action; concurrent/repeated confirmations do not resend. Recheck current membership and exact unrevoked credential before dispatch. Per-account and per-instance request caps. Treat ambiguous outcomes as uncertain, and distinguish provider acceptance, verified deletion and pending native schedules.
- Existing unified publish/calendar path gains Mastodon visibility, warning, sensitive media, reply/quote target and polls, verified video selection, fresh instance limits before dispatch, SHA256 idempotency keys and approved media integrity checks. Stop automatic re-upload when processing remains inconclusive.
- Existing Brand Brain writing pipeline, legacy drafting/automation routing, Agent Chat and Automation builder destination pickers accept Mastodon drafts. Agent SDK tools identify the exact connected account, return explicitly requested public/unlisted numeric engagement observations, or save unapproved action previews linking to Channels. No Agent tool approves or executes external actions, reads private notification bodies, or grants automation authority.
- Analytics identifies latest-40 coverage, instance-local observations, unknown historical trends and unavailable impressions/reach/demographics. Followers-only/direct bodies are excluded from model-facing analytics. Action bodies purge on disconnect and on later activity after seven days; a scheduled retention sweep remains open.

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

**External input needed:** exact two authorized account handles, signed-in OAuth authorization by their owner, and authorization to publish/edit/delete clearly labelled acceptance test posts. No passwords or tokens should be pasted into chat. Asked in this conversation; no reply received as of preparation. Local ORC browser inventory returned MCP internal error; no signed-in live browser state was inspected.

## Engineering work still open before production

- Verified audio publication from the normalized Library and multiple attachments in the unified approval/composer path. Current unified path supports one image or one verified video; the provider upload helper accepting multiple MIME types is not complete end-to-end support.
- Persisted media-upload checkpoint/resume beyond the bounded polling window, rather than a held manual review.
- Avatar/header uploads and the full supported profile preference surface.
- Private mention/reply suggestions with explicit per-purpose AI consent and retention safeguards.
- Complete thread planning/parent-ID chaining with exact approvals and child reconciliation.
- Historical engagement collection/trends and the existing central Analytics dashboard projection.
- Add Mastodon-specific regression evidence for the existing shared owner-authorized automation engine (`automation_plan.activate`, `automation_runs.build_items`/commit and `automation_edit` pause), then mandatory real automation acceptance. Reuse that engine instead of inventing a separate standing-authority system. Full management OAuth scope is not automation consent.
- Durable rate-reset/backoff scheduling shared by provider reads, writes and workers; current action path never automatically resends ambiguous writes.
- Streaming events, scheduled-post reconciliation into the unified calendar and periodic connection/instance health monitoring, including account-migration detection and reconnection guidance.
- Scheduled privacy-retention sweep; recovery of long-running action claims.
- Real 1,000+ concurrent-connected-user/queue stress validation. The current 1,000-context test uses 16 concurrent synthetic workers; it is not a 1,000-simultaneous-user production capacity claim.
- Complete release security review and all required live acceptance before changing public execution gates, applying production migration 113, merging or deploying rafii.io. Candidate source review is in `security-review.md`; it records remaining risks and does not certify production.

## Cloud validation

All Node/Python suites, PostgreSQL, production builds and browser automation execute on Depot/JCB. Local work is restricted to edits, Git, syntax/JSON inspection and log/artifact recovery. No local dependency installation or heavyweight validation.

Run scoped validation from the actual worktree with `.james-cloud-build.mastodon.json`. The JCB controller currently uses a single generated workflow path and `setup --force` updates both the root config and workflow. Before setup, back up those two files; restore their original contents after the scoped run. Do not replace the repository’s unrelated default YouTube mapping when committing this candidate. No deployment workflow is used.

Passed scoped cloud run `bj8165qq6b` (JCB exit 0): 267 Python contracts, seven disposable SQL action/isolation tests, migration replay/upgrade/restore checks, 24 selected web contracts, lint, typecheck, production build and application browser journeys at 1440/390/320px. The automation regression exposed and repaired a missing Mastodon entry in the legacy drafting/platform picker; it verifies separate account destinations, pausing and refusal of auto-publish activation without a standing grant. It does not demonstrate live generated content or worker publication. SQL and browser providers are explicitly synthetic. The final run includes unique per-form field IDs and analytics ID/timestamp sanitization. Evidence and exact limitations are recorded in `validation.json`.

## Official sources checked

- [OAuth tokens and PKCE](https://docs.joinmastodon.org/client/token/)
- [OAuth methods](https://docs.joinmastodon.org/methods/oauth/)
- [Application registration](https://docs.joinmastodon.org/methods/apps/)
- [OAuth scopes](https://docs.joinmastodon.org/api/oauth-scopes/)
- [Statuses](https://docs.joinmastodon.org/methods/statuses/)
- [Native scheduled statuses](https://docs.joinmastodon.org/methods/scheduled_statuses/)
- [Rate limits](https://docs.joinmastodon.org/api/rate-limits/)

Publication to one instance does not guarantee immediate Fediverse distribution. No administrator scopes are requested.
