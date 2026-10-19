# Rafii × Discord — Personal Account Connection & Authorized Publishing

**Product Requirements Document · v1.0 · 19 October 2026**
**Owner:** James Au · **Product:** Rafii · **Engineering:** continuation of PostRiff PR #211
**Baseline inspected:** `63864bd6654f62a165c398ce4c493528aee6f501`
**Status:** implementation specification; not a certificate of completion or production readiness.

## 1. Executive decision / 核心產品決定

Rafii must let an eligible customer connect their own Discord account through Discord-controlled OAuth. Personal account connection must be a first-class product feature, not a hidden preliminary step inside “install a bot.” A connected account must remain useful and understandable even when the person does not administer a Discord server.

**Connecting a personal account does not authorize Rafii to publish messages as that ordinary Discord user.** The supported publishing identity is the authorized Rafii application/bot, or a separately authorized incoming webhook. A user-installed app can respond to permitted interactions as an app; it is not a general personal-account publishing credential. The product must say this before authorization and again at publishing review. [S1–S5]

James’s desired outcome has two distinct parts: (a) customers connect their own accounts without creating or supplying their own bots; (b) Rafii performs permitted publishing workflows on their behalf. Both belong in the product. The stronger wish—automatically appearing as the customer’s ordinary Discord account—is **not a promised capability** of the documented general OAuth/bot integration. No self-bot, copied session, password, personal user token, impersonating webhook, or automated Discord client is an acceptable implementation route. [S1, S2]

**Delivery order:** make the existing personal connection and bot publishing path clear, complete and verifiable first. Specify and separately qualify webhook publishing and user-installed interactions; do not disguise either as personal-user posting or silently replace the existing bot implementation. The full multi-mode vision remains open until those modes are implemented and independently accepted. A completed first delivery is not “everything is production ready.”

## 2. Problem and current evidence

### 2.1 Customer problems

Customers see a bot-centric connection flow and reasonably assume that Rafii cannot connect their Discord account. An identity-only OAuth success may conversely look like permission to publish as the customer. Someone who intentionally declines server-list access then reaches a server-picker error without a useful recovery path. Identity records currently have weaker main-page visibility than publishing-channel cards.

The solution must separate **who authorized Rafii**, **what resource is authorized**, **which identity sends a message**, and **which operation was approved**. These are four independent facts, not one “Connected” badge.

### 2.2 Source baseline verified on 19 October 2026

The inspected Mac worktree and GitHub PR #211 both identify head `63864bd6654f62a165c398ce4c493528aee6f501`. PR #211 was open, draft and unmerged at inspection. Its descriptive body still mentioned an older head; Git metadata takes precedence over stale prose.

Existing implementation already contains:

- Actor- and workspace-bound Discord identity OAuth, optional `guilds` scope, independently verified application/subject, and encrypted access/refresh-token custody.
- A distinct bot installation flow with exact guild selection and separately authorized channel destinations.
- Refresh, reconnect, local disconnect, authorization-generation fencing, frozen reviews, durable dispatch protections and provider-rate-limit handling.
- Personal identity controls inside the connection sheet; identity callback handling; bot/channel publishing and separate engagement-consent surfaces.
- Tests for OAuth lifecycle, server/destination permissions, installation reverification, publishing authorization and worker behavior.

These are **source observations**, not proof that each feature works for a fresh public customer on rafii.io. Earlier CI receipts qualify their own exact commits only. Private acceptance deployment, production deployment and current Git source must not be conflated.

### 2.3 Preserve existing work

Continue from the exact inspected candidate; do not restart from PR #197 or an old Discord branch. Preserve the existing source and production-candidate worktrees, their untracked evidence, other agents, prior reviews, drafts, jobs, secrets and unrelated providers. Use an additive owned extension when the release lane is concurrently occupied.

## 3. Outcomes and non-goals

### Required outcomes

**G1 — First-class personal connection.** From Channels, a person can find “Connect personal Discord account,” authorize only the requested official scopes, see their account afterward and manage its connection independently of a server card.

**G2 — Honest capabilities.** An identity record never grants publish/schedule capability and never appears as a selectable publishing destination. The customer sees “Account connected; publishing needs a separate authorized destination.”

**G3 — Authorized server publishing.** A customer with the necessary Discord server authority can use Rafii’s application, select the exact server and channel, review a message, and approve bot-authored delivery or Rafii-managed scheduling without creating their own bot.

**G4 — Complete lifecycle.** Reconnect, missing-scope recovery, expired credentials, permission removal, cancel, revocation and uncertain outcomes have explicit states and recoverable next actions.

**G5 — Additional official modes.** Incoming webhook and user-installed interaction modes have distinct grant, execution, sender and acceptance contracts. They are unavailable in the product until their implementation and external qualification exist.

**G6 — Public evidence.** Public readiness requires independent fresh-customer OAuth, real permitted operations, security/tenant isolation, unattended scheduling where claimed, production provenance and a verified rollback—not merely synthetic tests.

### Explicit non-goals

No posting as a normal Discord account using extracted user credentials; no arbitrary personal or group-DM automation; no global private-message or full-history access promise; no bypass of server permissions; no claim of personal-user authorship through a matching webhook avatar/name; no native Discord scheduling claim where Rafii’s scheduler performs the timing; no invented analytics; no replacement of customer approval with an agent’s judgment. [S1–S8]

## 4. People, roles and authority

**Ordinary customer:** has a Rafii workspace and the existing `manage_connections` permission. May connect their own Discord identity without Discord server-management privileges. Absence of a manageable server is not an identity-connection failure.

**Server manager:** additionally meets Discord’s applicable management and channel-permission requirements. Can install Rafii and authorize a bounded destination, but installation does not itself approve a message.

**Author/reviewer:** follows Rafii’s existing draft and publication-role policy. Draft authorship, connection ownership and publication approval are not interchangeable.

**Workspace administrator:** can manage the workspace under the existing membership model. An administrator must not receive another member’s private bearer tokens or automatically inherit that member’s identity consent.

**Rafii release owner:** approves qualified public release. Engineering authorization permits reversible implementation, testing and normal feature-branch work; it does not silently expand existing provider-send, production-release or spending boundaries.

## 5. Connection and capability matrix

| Mode | Customer action | Credential / grant | Message sender | Unattended scheduling | Availability rule |
|---|---|---|---|---|---|
| Personal identity | Connect own account with official OAuth | `identify`; optional `guilds` | None | No | Existing identity implementation plus first-class UI and explicit non-publishing contract |
| Server bot | Authorize Rafii in an eligible server; separately authorize channels | Bot installation plus bound personal authorization, application credential and exact destination | Rafii bot/application | Rafii scheduler, after frozen approval and current permissions | Existing runtime retained; actual release gates still apply |
| Incoming webhook | Separate OAuth channel authorization | `webhook.incoming`; encrypted webhook secret | Authorized webhook/application identity | Rafii scheduler, only with separate webhook dispatch implementation | Must remain unavailable until full custody/worker/reconciliation qualification |
| User-installed app | Install app to own Discord account and invoke supported commands | `applications.commands` user installation and signed interaction context | App interaction response | Not a durable, arbitrary scheduling grant | Must remain unavailable until portal configuration, command registration and signed endpoint acceptance |
| Post as ordinary user | Not offered | No supported general grant in this product | Ordinary user identity | No | Explicitly unsupported; never relabeled as another mode |

“Direct” describes a real authorized API execution path, **not** personal-user authorship. Identity OAuth alone must never produce a Direct publish badge. A shared bot installation does not grant every Rafii workspace access to that server. [S1–S5]

## 6. Information architecture and interface requirements

### 6.1 Channels main page

Add a distinct **Personal Discord accounts** section when Discord connections V2 is present, or when the response already contains the actor’s linked Discord identities. Keep existing server/channel cards intact.

The section contains a clear primary connection button and account records with display name, account ID, stored connection state and server-discovery consent. Render account names as text; wrap long names/IDs; never trust provider names as HTML. Explain that these are identity connections, not publishing destinations. Provide an explicit management entry to the existing connection sheet rather than duplicating OAuth handlers.

When the provider is paused/unavailable, show the state and keep actionable paths disabled as appropriate; never hide existing identity records solely because new connections are temporarily paused. Do not display other members’ identity records.

### 6.2 Connection sheet

Provide separately labeled choices for personal-account linking and server authorization. The identity choice must explicitly say it does not install a bot or authorize publishing as the user. Default identity scope is `identify`; server discovery is an optional, unchecked permission.

When a linked identity lacks `guilds`, do not perform a predictably failing server-list request. Show “Server-list permission is needed” and an explicit reconnect-with-server-selection action. That action prepares the appropriate checkbox/identity selection; it **does not** grant the scope or click Discord’s consent page. The customer still reviews and authorizes the OAuth request.

Prevent changing mode/account/server while a request is being prepared. A stale successful response must not populate a different account’s or workspace’s server picker. Reset selection and stale errors when changing the relevant account or mode.

### 6.3 After OAuth callback

Identity success: “Personal Discord account connected,” followed by a statement that publishing as the user is not authorized and server/channel authorization is separate. Navigate to the Channels identity section; do not scroll toward a nonexistent publishing-channel card.

Bot installation success: identify the server, then prompt for channel authorization. Do not claim a message can be published before destination authorization and a current review.

Discord missing scopes: publishing remains **unavailable**, not “Assisted” or “Post as you.” Preserve unrelated providers’ behavior.

### 6.4 Composer and review

A review must make the eventual sender explicit: Rafii bot or authorized webhook, never the authorizing ordinary user. Show exact server/channel/thread, message text/media, local timezone, UTC instant, approval scope and current capability state. Identity records cannot enter the destination picker.

## 7. Core user journeys

### J1 — Customer without server-management privileges

Open Channels → Connect personal Discord account → review `identify` only → authorize on Discord → callback verifies state, actor, workspace, app and subject → encrypted storage → Channels shows the linked identity. No bot installation, server enumeration, provider post, draft approval or publishing job occurs. An empty list of manageable servers is not a failed identity connection.

### J2 — Connect then choose a server

From the linked identity, choose server authorization. If server discovery was declined, present the explicit scope-upgrade path. After customer consent, list only eligible manageable servers from that identity, choose one exactly, run bot installation, and separately choose/authorize an effective channel. Revalidate access before dispatch.

### J3 — Prepare and schedule

Create or select a draft → choose authorized bot destination → preview exact sender/content/destination/time → approve the frozen review → create one bound job → Rafii scheduler executes when due under current grant and durable ownership. Read back the provider message and persist a sanitized delivery receipt. This journey must be tested separately from a manual exact-job dispatch.

### J4 — Reconnect a changed or expired identity

Offer reconnect on the specific identity, pin expected Discord subject, and refuse an unexpected subject in the reconnect operation. Existing dependent installation/destination authority is invalidated by consent-generation changes according to the current model. Do not restore publishing solely because a new identity token was obtained; reverify the dependent resource.

### J5 — Disconnect

Show that local disconnect holds dependent future publishing and does not uninstall a shared bot from the Discord server. Apply existing fresh-session and membership checks. Hold only affected Discord work; preserve other members, workspaces, providers and the shared scheduler. Provider-level grant revocation, when separately requested, must disclose its broader effects. [S1]

## 8. Authorization and scope requirements

| Operation | Minimum product request / verification | Prohibited inference |
|---|---|---|
| Identity connection | `identify`; exact subject/application/actor/workspace verification | Identity consent is publishing authority |
| Optional server discovery | Explicit `guilds` consent and paginated eligible list | Guild membership alone means server management |
| Bot installation | Bound identity, exact guild, bot installation consent, current application/bot membership | `bot` must always appear in bearer introspection as a user scope |
| Text channel publishing | Effective channel permissions, destination consent, current publication approval | Administrator permission is the default request |
| Delivery verification | Current permission to read the relevant message / equivalent supported receipt | Accepted HTTP request means verified delivery |
| Media / embeds | Relevant current permissions and supported payload constraints | Text-only permission authorizes every media type |
| Broader channel content | Applicable Discord access plus separate customer consent | Bot installation grants every message or full history |
| Incoming webhook | Separate official grant and exact channel/webhook binding | User Install creates or authorizes a webhook automatically |
| Interaction response | Valid signature, app/installation/user/context binding and supported response window | Interaction token is a reusable scheduler token |

Use Discord’s current documented values and returned capability evidence rather than hard-coded assumptions about evolving limits. Do not ask for email, friends, DMs or privileged intents as collateral to identity linking. [S1, S3–S8]

## 9. Server-owned identity presentation contract

The public identity response is a projection, not the credential record. Preserve compatible existing keys (`id`, `account`, `userId`, `status`, `expiresAt`, `discoverGuilds`) and add explicit non-authority fields:

```json
{
  "connectionKind": "identity",
  "senderKind": "none",
  "canPublish": false,
  "canSchedule": false,
  "postAsPersonalUser": false,
  "capabilityReason": "discord_identity_only"
}
```

These values are computed server-side, never copied from stored or submitted “capability” fields. Filter by **both** current workspace and authorizing member. Missing authentication fails closed. Never project bearer/refresh tokens, vault key identifiers, encrypted envelopes, transient claims, private grant generations or arbitrary provider response fields.

`status=linked` is the stored identity-link state, not proof that live provider access was checked at render time. Freshness and credential refresh remain server responsibilities. The UI must not manufacture current permission from a stale cached identity record.

OAuth-start identity permission explanations must reflect the exact requested scope set. Successful identity callback metadata can carry the same non-publishing contract. Existing bot capability structures remain unchanged.

## 10. Existing architecture and integration points

Reuse `src/postriff_phase2/discord/oauth.py` for identity/install lifecycle; `authorization.py` and the existing worker path for publication authority; `engagement.py` for separately consented conversations. Preserve vault, repository transactions, RLS, authorization generations, idempotency and audit mechanisms.

Current observed API paths include:

- `POST /api/workspaces/{workspace}/channels/discord/oauth/start` — capability `identity` or `publish`, with corresponding explicit Discord purpose.
- Existing authenticated OAuth completion and Discord callback path — consume the existing transaction rather than inventing a client-only connection record.
- `GET /api/workspaces/{workspace}/discord/identities/{identity}/guilds` — existing server discovery used by the connection sheet.
- `POST /api/workspaces/{workspace}/discord/identities/{identity}/disconnect` — existing local disconnect.
- `POST /api/workspaces/{workspace}/jobs/{job}/execute` — exact approved-job dispatch; **not** an unattended scheduler test.

The extension should be additive and need no database migration merely to expose identity presentation metadata. Any new webhook/interaction runtime requires a separate reviewed schema/API delta; proposed APIs must be labeled proposed until implemented.

## 11. Security and lifecycle invariants

**S-AUTH:** authenticate the Rafii session and enforce existing membership/role policy at every entry point. Preserve state single-use, expiry and nonce binding; validate application and Discord subject independently of client input. Treat issuer/PKCE improvements as source-reviewed compatibility work, not an excuse to invalidate an in-progress approved callback without reconciliation.

**S-TENANT:** no identity, server, destination, queue job, review or receipt can cross workspace/member boundaries through a guessed identifier. Tests must exercise another member in the same workspace, another workspace for the same member, and malformed records.

**S-CUSTODY:** access/refresh/webhook tokens stay encrypted server-side; no browser storage, URL logging, general files or chat output. Never gather a personal Discord session token. Sanitize provider error bodies and authorization URLs in receipts.

**S-GENERATION:** reconnect/revoke invalidates appropriate dependents; asynchronous success cannot overwrite a newer denial. Refresh under the same legitimate grant preserves the existing generation semantics. A rotating-token exchange with uncertain outcome must not blindly retry.

**S-INTENT:** granting a connection is distinct from approving content. Exact approval binds sender, target, payload and time. Every mutation has the existing audit and idempotency protection. Content or target changes require a new review.

**S-BOUNDARY:** shared bot presence is not tenant authorization; disconnect does not uninstall another customer’s shared integration. Never pause all providers to test one Discord operation.

**S-TRUTH:** unsupported, unavailable, expired, paused, unverified and denied are different states. No success badge may be inferred from UI input, a fixture, a READY deployment or old-head CI.

## 12. Publishing, scheduling and uncertainty

The bot execution path remains the primary direct-publishing implementation. Reuse the existing frozen manifest and worker lease/protocol fence; do not fork a second ad-hoc HTTP sender for tests or optional modes.

Before delivery, recheck current workspace role, consent, identity, installation, channel, grant generation, approved payload, due time, cancellation and sender. Use `allowed_mentions.parse=[]` by default; mention changes are reviewable payload changes. Fail closed on removed access.

Scheduling means Rafii executes later; it is not a Discord-native scheduled-post feature. Test genuinely unattended due-time execution separately from manually invoking the exact-job endpoint. Preserve IANA timezone and UTC, including daylight-saving transitions, ambiguous/nonexistent local times and a review crossing its deadline.

Rate limits follow current provider bucket/retry information. Distinguish a definitive pre-send rejection from an unknown post-send outcome. Timeouts or transport failure after submission require reconciliation before retry; do not promise universal exactly-once delivery when the provider cannot prove it. Cancellation cannot retroactively unsend an already delivered message. [S6–S8]

## 13. Incoming webhook mode — complete future implementation contract

**Purpose:** permit authorized channel publishing without claiming personal-account authorship. This is a distinct publishing mode, not a fallback hidden behind “Post as you.”

Use official `webhook.incoming` authorization-code flow, its channel picker and the returned verified webhook/channel identity. Bind the transaction to member/workspace/application/purpose; store the webhook token in the existing vault under a distinct credential kind. Never accept arbitrary user-supplied URLs as trusted execution targets. Restrict requests to the exact documented Discord API origin/path and verify IDs. [S1, S3]

A webhook destination records workspace, authorizer, application, webhook ID, guild/channel, status, authorization generation and permitted operations; no secret is exposed publicly. Namespace IDs so a webhook cannot collide with a bot installation or identity record. Creation and later sending are independently approved operations.

Integrate webhook sends into the same review/job/worker framework with sender kind in the digest. Use `wait=true`, validate returned message and destination, then fetch the message where supported. A 204 without a verifiable receipt is not proof of delivery. Retry only when supported reconciliation establishes safety. [S3]

Allow only declared text/embed/media/thread capabilities, after exact permission and payload checks. A webhook display-name/avatar override must not masquerade as verified personal authorship. Forum/media thread creation or auto-unarchive is an explicit additional effect. Do not claim full inbox, arbitrary replies, moderation or analytics merely because a webhook can send.

**Acceptance:** denied/wrong-channel callback, cross-tenant replay, wrong credential kind, secret redaction, generation change, revoke, duplicate/uncertain send, thread effects, real approved message/readback and scheduled/canceled execution. Until these pass and rollout is approved, the UI must say unavailable and offer no operative webhook-connect button.

## 14. User-installed application — complete future implementation contract

**Purpose:** let a customer use Rafii’s supported Discord commands in authorized contexts without administering a server. User installation is independent of both identity OAuth and server bot installation. [S4, S5]

Configure User Install in the Discord Developer Portal and the applicable default installation scopes/contexts; register exact commands and versions. Do not claim that any `/rafii` command exists before actual registration. A suggested initial feature is opening a private draft/review workflow—not silently publishing arbitrary content.

Receive interactions on a bounded HTTPS endpoint. Verify the Ed25519 signature against the raw request body and timestamp; reject invalid signatures, malformed content, wrong app, replay and unauthorized installation owner/context. Resolve the Discord subject to an explicitly linked Rafii member/workspace; never infer workspace from a text parameter alone.

Respect Discord’s initial-response and follow-up-token windows. Defer only through a supported interaction response; keep work within the authorized context. Expired interaction tokens must never become durable scheduled-publishing credentials. App responses remain app-authored. Sensitive drafts should be private/ephemeral by default where supported. [S5]

Public responses, messages or external actions still require the user’s appropriate action/approval and target context. A user installation does not confer general channel history, server management, arbitrary DMs, a webhook grant or personal-user posting.

**Acceptance:** developer configuration readback, registered commands, real install, signed PING, signature rejection, ownership/context checks, replay handling, draft privacy, denial, removal and actual approved response. Until qualified, keep this mode unavailable; do not present speculative commands as live capabilities.

## 15. Accessibility, responsiveness and copy

Personal-account entry and status must be usable by keyboard, screen reader and touch. Use semantic section headings, actual buttons, accessible labels and visible focus; minimum practical touch targets should follow the existing Rafii control tokens. Wrap provider names/IDs and prevent horizontal overflow at 390px and desktop widths.

Use “Connect personal Discord account” for identity, “Authorize Discord server” for bot installation and “Authorize Discord channel” for destination consent. “Account connected” never appears alone next to an implied publish promise. Preserve the existing design system and all other platforms; no redesign of the whole Channels page is needed.

Avoid “Assisted” as an inaccurate Discord publish state after missing permission. Use direct wording: publishing is unavailable until separate authorization. Translation work must be tracked explicitly; an English-only patch is not proof of complete localization across Rafii’s supported locales.

## 16. Verification and acceptance matrix

| ID | Required evidence | Passing meaning |
|---|---|---|
| A01 | Identity-only start/callback regression | No bot scope, installation, capability grant or provider message |
| A02 | Public projection test | Exact workspace/member filtering; no secrets; fixed non-publishing metadata |
| A03 | Main-page component/browser test | Personal account connection visible without server cards |
| A04 | Missing `guilds` test | Explicit scope-upgrade choice; no failing discovery request fired automatically |
| A05 | Callback UX test | Identity-specific success; no implied personal publishing or Assisted mode |
| A06 | Existing bot regression suites | Installation, exact destination, grants and publication guards unchanged |
| A07 | Security tests | Replay, wrong actor/workspace/application/subject and revocation remain rejected |
| A08 | Authenticated real OAuth | Fresh customer links own account; correct callback and workspace identity observed |
| A09 | Authorized live message | Exact approved content, app/bot sender, target and one reconciled receipt |
| A10 | Real future scheduling/cancel | Unattended delivery and cancellation verified separately from manual dispatch |
| A11 | Desktop/mobile browser and accessibility | No overflow, reachable controls, no unexpected API mutation |
| A12 | Source/type/lint/CI | Results bind the exact release source; skipped tests explicitly named |
| A13 | Production provenance/rollback | Approved exact artifact, canonical DB, other-provider health, compatible rollback |
| A14 | Webhook acceptance from §13 | Full webhook mode only; not substituted with bot or identity evidence |
| A15 | User-install acceptance from §14 | Full interaction mode only; not substituted with OAuth identity evidence |

Each item has one of `VERIFIED`, `FAILED`, `NOT_RUN`, `BLOCKED_EXTERNAL`, `NOT_IMPLEMENTED` or `NOT_APPLICABLE`, plus source SHA, method, timestamp and evidence path. Do not turn missing evidence into a pass. Synthetic provider tests must explicitly say synthetic.

## 17. Observability, privacy and success measures

Record sanitized counts for identity starts/success/denial, discovery-scope repair, installation success, destination approval, exact-job outcomes, revocations and uncertainty reconciliation. Segment identity-only connection from publishing activation. Never put tokens, full authorization URLs, draft content or private provider metadata into analytics.

Proposed product measures are discoverability of personal-account connection, identity completion rate, eligible server activation rate, failed-scope-recovery rate and unauthorized/duplicate-send incidents. Establish measured baselines first; this PRD invents no conversion target, current success rate, cost saving or time estimate.

## 18. Rollout, budget and rollback

Canonical production is Vercel `postriff-phase2-private` and Supabase `buoyhkbodnhzngaotoel`. Never point production functionality at the old staging database. Preserve `git.deploymentEnabled=false`, project preview-disable settings, shared cron and active agents.

Develop/test/commit as an additive extension. Source-only fixes and documentation do not require a new Vercel deployment. Batch appropriate changes into one source-pinned candidate; do not repeatedly build per edit. No new paid provider, cloud build allowance, plan, secret reset or production flag is implied by this document.

A hosted release requires the actual release lane’s qualification and explicit release authority, not an old generic approval. Preserve the current rollback candidate and Discord lease-protocol fencing. Rollback must hold only new affected Discord admissions and reconcile in-flight/uncertain work; no global scheduler pause or unrelated-provider rollback.

## 19. Execution boundaries and real acceptance

James has asked for this PRD and direct implementation. Routine design/code/test/branch decisions should proceed without repeated approval questions. Continue useful independent engineering even while live acceptance is blocked.

Previously prepared draft/review data are immutable historical evidence. The old frozen proposed time `2026-10-19T03:00:00Z` is past; do not approve or silently retime it. A future provider-send approval must identify current content, sender, exact destination, time/review/digest and bounded operation count. It must not be invented from “continue engineering.”

A Discord authorization click reported by James is not proof of successful Rafii callback custody. Verify actual current callback outcome and workspace link through the supported authenticated flow before reusing it. Do not ask James to repeat login/authorization merely because a stale report lacks the receipt.

Public release, real messages, new third-party grants and additional spend retain their relevant human gates. A gated operation does not make unrelated code work impossible, but it prevents a truthful claim that the full customer goal is finished.

## 20. Delivery definition and decision log

**First delivery complete:** detailed PRD and implementation plan saved; additive personal-account presentation/management and honest capability contract implemented; missing-scope recovery and callback truthfulness fixed; exact-source applicable tests pass; remaining hosted/live/rollout conditions are documented.

**Bot customer release complete:** first delivery plus A08–A13 verified, existing publishing/engagement capability boundaries accurately represented and public release authorized and verified.

**Full multi-mode goal complete:** bot customer release plus separately implemented/qualified webhook and user-installed modes where included in the release; all declared customer capabilities work within official limits. A14/A15 cannot be checked merely because their specifications are written.

**Personal-user authorship:** remains unsupported unless Discord provides an applicable official capability for this product and the exact authorization is independently verified. A new official scope/access program with demonstrated Rafii eligibility would change that decision; a third-party claim, extracted token or matching avatar would not.

Decisions: retain existing architecture; make account connection first-class; identity grant is always non-publishing; bot is the first practical delivery mode; webhook/user installation remain separate scoped engineering and qualification tasks; no redundant safety-checkpoint loop for reversible work; no fabricated finish at a human gate.

## 21. Official source register

Checked 19 October 2026. Source documents explain provider constraints; the feature design and acceptance requirements above are Rafii product decisions.

- **S1 — OAuth2 / grants / scopes:** https://docs.discord.com/developers/topics/oauth2
- **S2 — Automated user accounts / self-bots:** https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots
- **S3 — Incoming webhooks and execution:** https://docs.discord.com/developers/resources/webhook
- **S4 — User-installable application tutorial:** https://docs.discord.com/developers/tutorials/developing-a-user-installable-app
- **S5 — Receiving and responding to interactions:** https://docs.discord.com/developers/interactions/receiving-and-responding
- **S6 — Message resource and operations:** https://docs.discord.com/developers/resources/message
- **S7 — Effective permissions:** https://docs.discord.com/developers/topics/permissions
- **S8 — Rate limits:** https://docs.discord.com/developers/topics/rate-limits

## 22. Engineering evidence references

Inspected source: `src/postriff_phase2/discord/oauth.py`, existing Discord lifecycle tests, `web/src/features/channels/connect-sheet.tsx`, `connect-return.tsx`, Channels wiring and API identity types at the baseline SHA above.

Existing Mac handoff root: `/Users/ouxianxing/Documents/Rafii-Discord-Repair-20261018/`. Read current receipts rather than treating historical STATUS prose as a live observation. The execution plan, verification report, patch and new commit receipt accompany this PRD; their statuses supersede planning assumptions only for the exact changes actually verified.
