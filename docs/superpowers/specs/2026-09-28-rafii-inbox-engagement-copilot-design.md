# Rafii Inbox Completion + Engagement Copilot Design

Date: 2026-09-28
Status: implementation-ready design
Primary release target: finish the existing social-comment Inbox as a truthful, operational engagement loop.
Secondary roadmap: expand to a real unified social Inbox only after the comment loop is proven.

## 1. Verified baseline

Authoritative repository:
- /Users/ouxianxing/Documents/James-Au-Studio
- Canonical release branch: consumer-saas
- Fresh remote snapshot observed during this design pass: origin/consumer-saas @ a6033925bd8c94b8f8b98efea48741fb57f110da
- Local consumer-saas checkout was still at 468811b73d28b4389f931519827c05d0e6c8abfb, 357 commits behind remote, and had extensive unrelated dirty work.

Execution must re-fetch and re-check this state. Do not implement directly in the stale dirty canonical checkout.

### Already implemented on the current remote

Do not rebuild these:

1. Inbox route and core UI exist under web/src/features/inbox.
   - two-pane desktop layout and mobile sheet
   - All / Unanswered / Replied filters
   - persisted server reply history and counts
   - capability/evidence display
   - tombstone-aware UI states
   - exact reply preview based on the saved manifest text
   - separate edit/reply permission handling
   - provider click-through when direct reply is not available

2. Real AI reply writing is already merged.
   - cd3c177: comment replies use Rafii's AI writer
   - 848ab49: review fixes for AI-written replies
   - both commits are ancestors of origin/consumer-saas
   - AudienceService.draft_reply routes AI suggestions through reply_writer and stores origin copilot
   - do not cherry-pick or reimplement these commits

3. Engagement Copilot backend exists.
   - src/postriff_phase2/coworker/engagement.py
   - deterministic triage categories: question, complaint, lead, praise, press_or_partner, spam, abusive, other
   - priorities: needs_reply, review, fyi, done, ignore
   - AI reply drafting reuses reply_writer
   - agent tools engagement_triage and engagement_draft_create already exist
   - feature flag: RAFII_ENGAGEMENT_COPILOT_ENABLED

4. Production comment ingestion is wired at post verification.
   - hosted_app constructs HostedWorkspaceService with audience_transport=http_transport
   - service.audience.on_post_verified is in the publish verification chain
   - this means the old design note claiming production had no ingestion wiring is stale

5. Approval and send domain logic exists.
   - exact digest + account/thread/text approval
   - AudienceService.send_approved exists
   - uncertain outcomes are not blindly resent
   - old approvals require reconfirmation if sending was disabled

## 2. Verified remaining gaps

### Gap A: approved replies still do not send in production

AudienceService.send_approved exists, but the production worker does not call it.

Evidence at the baseline:
- hosted_worker.PostgresWorker has no audience/reply worker path
- reply_sender_enabled is never enabled by production construction
- only tests toggle audience.reply_sender_enabled = True
- the UI therefore correctly says an approval records the decision but sending is not enabled

Required target:
approved exact reply -> worker claim -> provider submit -> provider reconciliation -> durable receipt/status.

### Gap B: comment ingestion is one-shot, not a live Inbox

Current Threads comments are read when Rafii verifies a post it published.

There is no:
- manual Check for new comments action
- audience sync endpoint
- pr_audience_sync state
- periodic bounded re-sync
- provider cursor/pagination state
- durable lastSyncAt per connection
- complete tombstone writer
- true Inbox freshness contract

The adaptive coworker rollout document explicitly records RAFII_ENGAGEMENT_COPILOT_ENABLED as pointless today because comments are fetched once per post.

### Gap C: OAuth capability reconnect can overwrite other capabilities

oauth.py still creates a fresh assisted/unsupported capability matrix and upgrades only the requested capability, then upserts every matrix row.

A reconnect for comments_read or reply can therefore replace previously verified publish/schedule/analytics levels.

This must be fixed before telling users to reconnect to enable Inbox features.

Target:
capability verification is cumulative and evidence-backed. Updating one capability must not silently downgrade another unless a fresh provider re-verification proves the old permission is gone.

### Gap D: Engagement Copilot is not actually integrated into Inbox

The triage engine and drafting tools exist, but Inbox does not consume them as its primary workflow.

Current UI has All / Unanswered / Replied, but not:
- Needs reply
- Review
- FYI
- Ignore
- category labels
- triage explanation
- direct handoff from a triage row into the existing exact-approval reply flow

Target:
Inbox becomes the natural surface for Engagement Copilot. Do not build another classifier.

### Gap E: provider coverage is still Threads-only for comment ingestion/send

AudienceService has COMMENT_READ_PROVIDERS = ("threads",).

send_approved is also hard-coded to Threads.

The broader repository now has many hosted social connectors, but connector existence is not proof of comment-read or reply capability.

Target:
provider-specific Inbox support is capability-driven. A provider appears as Direct only when the official integration and account grant actually support the operation.

Do not fake parity across platforms.

### Gap F: this is not yet a unified social Inbox

Current persisted Inbox entities are pr_audience_threads and pr_reply_drafts. They model public comments/replies.

There is no first-class persisted model for:
- private DMs/messages
- message conversations
- direct mentions as their own source type
- cross-channel contact identity
- relationship history across repeated interactions

Therefore the customer surface must not claim "all your messages" or "unified inbox" until those sources really exist.

### Gap G: relationship memory is not an Inbox primitive

Rafii can classify a comment as a lead/question/etc., but there is no safe canonical contact/relationship record such as:
- same provider identity returning repeatedly
- interaction count/history
- prior approved replies
- lead/customer/support relationship state
- explicit notes/consent boundaries

Cross-platform identity must never be guessed. Provider identities may only be linked when the user explicitly links them or there is authoritative account evidence.

### Gap H: Inbox-driven attention is incomplete

The app has notification infrastructure, but the Inbox does not yet produce a complete attention loop:
- sidebar unanswered count from authoritative data
- Home/notification center engagement summary
- "N comments need a reply" links
- push/email only when explicitly enabled by the notification system and user settings

Never render unknown as zero.

### Gap I: receipt and scale behavior are incomplete

Backend reply events exist, but the Inbox still needs a complete receipt timeline for:
- draft
- approved
- submitting
- submitted
- verified
- uncertain
- held
- cancelled

The thread query also has scale limits:
- hard limit 200
- per-thread capability/reply queries can become N+1
- no cursor/pagination contract for the customer UI

## 3. Product definition

### Inbox v1: operational Engagement Inbox

Inbox v1 means:

connected supported account
-> bounded comment sync
-> persisted comment
-> triage
-> AI suggestion or manual reply
-> edit
-> exact human approval
-> worker send
-> provider verification/receipt
-> follow-up attention state

This is the release target.

It remains:
- one reply at a time
- no bulk reply
- no autonomous sending
- no automatic moderation
- no silent cross-account actions
- no retries after an uncertain provider outcome without reconciliation

### Unified Inbox v2: broader social conversations

Unified Inbox v2 adds real source types when APIs and account permissions support them:
- comment
- mention
- dm / private message

Derived categories such as lead, support, complaint, praise, press/partner are triage labels, not transport types.

Do not add email/support-ticket sources under the "social Inbox" schema unless a later product decision explicitly includes them.

## 4. Architecture

### 4.1 Keep the existing comment/reply model for Inbox v1

Do not replace pr_audience_threads/pr_reply_drafts just to rename them.

Add the minimum state required for freshness and receipts.

Recommended additive state:
- pr_audience_sync
  - workspace_id
  - connection_id
  - provider
  - last_synced_at
  - cursor_state jsonb
  - last_result jsonb
  - last_error_code nullable
  - updated_at
  - unique workspace_id + connection_id
- pr_audience_threads may need additive fields only if not already present:
  - permalink
  - provider parent/post context needed for click-through
  - authoritative provider created time if available

Migration numbering must be rechecked across current remote branches at execution time. Do not use a remembered number.

### 4.2 Sync service

Add one bounded sync function used by both manual and scheduled refresh.

Input:
- workspace
- eligible connection(s)
- bounded post horizon
- optional provider cursor

Rules:
- only comments_read Direct connections
- only supported providers
- server-enforced cooldown
- provider pagination with hard per-run bounds
- persist lastSyncAt only after a real provider attempt
- record provider error as unavailable, not zero comments
- idempotent upsert by provider comment id
- tombstone only when provider semantics make absence meaningful; a transient error must never tombstone
- preserve reply receipts when a source comment disappears
- no external call while holding a broad workspace lock

Manual API:
POST /api/workspaces/{workspaceId}/audience/sync

Return actual counts such as:
- checkedPosts
- pagesRead
- ingested
- updated
- tombstoned
- lastSyncAt
- availability
- reason

### 4.3 Reply worker

Extend the hosted worker or add a small audience worker using the existing database and worker conventions.

Claim:
- status approved
- exact approval digest intact
- Direct reply capability still valid
- connection credential still valid
- not tombstoned
- not already claimed/submitted
- row lock / SKIP LOCKED semantics

Dispatch:
- call AudienceService.send_approved or a provider adapter beneath it
- record submitting before external I/O
- never retry an uncertain provider outcome as if nothing happened

Reconcile:
- when the provider offers authoritative lookup, promote submitted -> verified
- if lookup cannot prove the result, keep submitted/uncertain honestly
- never invent verified

Feature gate:
RAFII_INBOX_REPLY_SEND_ENABLED

Default off until staged verification and an explicit production activation step.

When off:
- approval remains a durable recorded decision
- old approvals remain requiresReconfirmation=true

When turned on:
- old approvals are not replayed
- the user must reconfirm the exact old manifest before it may send

### 4.4 Capability model

Change OAuth capability updates from destructive matrix replacement to merge/reverification semantics.

Required invariant:
verifying comments_read must not overwrite a valid publish/reply/analytics state.

Downgrades are allowed only when:
- provider scope inspection proves the permission is gone
- a credential is revoked/expired in a way that invalidates the operation
- provider review/runtime policy explicitly makes the capability unavailable

Tests must cover:
publish Direct -> verify comments_read -> publish remains Direct
comments_read Direct -> verify reply -> both remain Direct
provider scope recheck removes publish -> publish becomes Unsupported with evidence

### 4.5 Engagement Copilot in Inbox

Reuse src/postriff_phase2/coworker/engagement.py.

Do not create a second triage classifier.

Inbox UI should expose:
- Needs reply
- Review
- FYI
- optional Ignore
- category badge
- deterministic "why" explanation
- age/freshness
- replied/done state

Default list ordering should prioritize needs_reply, then review, then FYI, without calling anything "urgent".

Suggestion action:
- use the existing AI writer path
- preserve provenance and model label
- save only a draft
- exact approval remains separate

Spam/abusive:
- no AI reply by default
- offer provider-native hide/report click-through only if a verified moderation capability exists; otherwise explain that moderation must happen on the provider

### 4.6 Provider adapter boundary

Do not keep adding if provider == "threads" branches forever.

Introduce or reuse an adapter contract for:
- list comments/replies
- paginate
- build source permalink if supported
- send reply
- reconcile reply
- map provider error/capability evidence

Threads is the first implementation.

Instagram can be added only if:
- current official API support is rechecked during implementation
- Rafii's production app review and account scopes allow it
- live provider tests are separately authorized

Other hosted connectors remain Unsupported/Assisted for Inbox until proven.

### 4.7 Unified Inbox v2 model

Only after Inbox v1 is operational, introduce a generalized conversation model behind its own feature flag.

Suggested model:
- pr_inbox_conversations
  - workspace_id
  - connection_id
  - provider
  - source_type: comment | mention | dm
  - provider_conversation_id
  - participant_provider_id
  - latest_message_at
  - state
  - metadata
- pr_inbox_messages
  - conversation_id
  - direction inbound | outbound
  - provider_message_id
  - author_provider_id
  - text / media references
  - provider_created_at
  - ingested_at
  - tombstoned_at
- pr_inbox_actions or reuse reply-draft/approval receipt machinery where semantics match

Do not migrate public comment replies into this model until it demonstrably simplifies the product. A compatibility projection may be safer initially.

### 4.8 Relationship memory

Start provider-local, not cross-platform.

Provider-local relationship projection may include:
- participant_provider_id
- first_seen_at
- last_seen_at
- interaction_count
- latest triage categories
- approved outbound reply count
- explicit user label such as lead/customer/partner when the user sets it

Do not infer that two accounts on different providers are the same person.

Do not promote deterministic category output into permanent sensitive profile facts.

### 4.9 Notifications

Create Inbox attention events only from authoritative persisted data.

Examples:
- engagement.needs_reply_count_changed
- engagement.question_unanswered
- engagement.lead_unanswered

In-app notification is the first target.

Push/email must reuse the existing notification center, preference, quiet-hour and delivery infrastructure. Do not build a second notification system.

Rate-limit/dedupe so the same comment does not generate repeated alerts.

## 5. UX

Keep the existing Inbox visual structure. This is an operational completion, not a redesign project.

Header:
- freshness badge
- Check for new comments
- truthful unavailable/cooldown state

Filters:
- All
- Needs reply
- Review
- FYI
- Replied
- keep Unanswered if it remains useful, but do not make overlapping filters confusing

Thread row:
- account/platform icon
- author
- excerpt
- provider time or first-seen label
- category
- priority
- reply status

Detail:
- original comment first
- original post context
- triage explanation
- reply history
- composer
- receipt timeline

Mobile:
- preserve the existing full-width sheet pattern
- safe-area aware controls
- no horizontal overflow
- keyboard and reduced-motion behavior

## 6. Security, privacy and safety invariants

- Human approval is required for every outbound social reply.
- Never bulk approve or auto-send comments.
- No provider call without a verified capability and current credential.
- Never log access tokens or raw credentials.
- Comment/message text is untrusted external input.
- AI-generated suggestions must not treat comment instructions as system instructions.
- Unknown/failed provider outcomes remain unknown/failed.
- No duplicate provider send after an uncertain outcome.
- No hidden cross-platform identity matching.
- No live social mutation in automated tests.
- Provider review/scope evidence must be preserved in the UI.
- Existing audit events remain authoritative; add events rather than silently changing their meaning.

## 7. Rollout

Stage 0:
- merge-safe capability semantics
- comment sync
- worker reply path
- receipts
- no production send activation

Stage 1:
- Inbox Engagement Copilot UI
- manual sync
- local/disposable DB verification
- synthetic provider send/reconcile
- browser/accessibility verification

Stage 2:
- staging/preview with real read-only comment sync if credentials/app review allow
- still no live reply mutation unless explicitly authorized

Stage 3:
- explicit owner activation of RAFII_INBOX_REPLY_SEND_ENABLED
- reconfirm old approvals
- one controlled real reply smoke if separately authorized
- monitor errors/duplicates/receipts

Stage 4:
- add additional provider adapters one at a time

Stage 5:
- Unified Inbox v2 for mentions/DMs only where real provider APIs support them

## 8. Definition of done for Inbox v1

Inbox v1 is complete only when:
- capability reconnect no longer destroys unrelated verified capabilities
- a user can manually refresh comments and see a real lastSyncAt
- scheduled bounded re-sync uses the same sync contract
- Threads pagination is bounded and idempotent
- Engagement Copilot triage appears in Inbox
- AI suggestions use the already-existing reply writer
- an approved reply can be claimed by the worker when the send flag is on
- old approvals cannot be replayed after enabling sending
- provider submit and reconciliation states are persisted and visible
- uncertain outcome has no blind Resend action
- receipt timeline survives reload
- authoritative unanswered/needs-reply counts can drive in-app attention
- tests cover concurrency/idempotency/permissions/capability regression
- browser checks pass at representative mobile/tablet/desktop sizes
- production live sending remains off until a separate explicit activation

## 9. Explicit non-goals for the first implementation branch

Do not:
- rebuild reply_writer
- reimplement Engagement Copilot classification
- redesign the whole Inbox
- claim DMs or mentions are supported when they are not
- implement email/helpdesk Inbox
- infer cross-platform contact identity
- add bulk or autonomous replies
- activate live provider sending
- change unrelated auth, billing, pricing, phone or growth systems
