# PostRiff SaaS Product and Architecture Specification

**Status:** Reviewable product and architecture candidate. This document does not authorize implementation, deployment, billing, customer onboarding, OAuth review submission, publication, or reply execution.

**Date:** 2026-09-14

**Product:** PostRiff

**Working promise:** One idea. Each channel, in its own voice.

**Positioning candidate:** A multilingual AI social studio that turns one well-informed idea into native content for every important audience.

**Related designs:**

- `docs/superpowers/specs/2026-09-14-postriff-product-design.md`
- `docs/superpowers/specs/2026-09-14-postriff-content-type-template-system.md`

## 1. Executive decision

PostRiff should evolve into a cloud-hosted, multi-tenant SaaS with an optional desktop companion named **PostRiff Bridge**.

The current laptop-hosted Studio and a private Tailscale connection remain valuable as **PostRiff Remote**, the founder alpha and local development environment. It must not become the customer-facing production architecture. A paying customer should be able to sign in from a mobile or desktop browser, create content, connect supported accounts, schedule posts, review analytics, and manage audience conversations without James's laptop being online.

PostRiff Cloud owns:

- Customer identity, workspaces, roles, subscriptions, and entitlements.
- Conversations, briefs, post variants, assets, schedules, analytics, and audience state.
- The PostRiff Agent, skill routing, approved Python tools, and media generation.
- Official API-based social connections and durable execution.
- Exact approvals, idempotency, provider reconciliation, and per-destination receipts.

PostRiff Bridge is optional and owns only capabilities that genuinely require a customer-controlled device, such as private local files or a browser-only session. The Bridge connects outbound to PostRiff Cloud; customers never expose a local port to the public internet.

## 2. Product boundary

### PostRiff is

- A cloud product for solo creators and small creative teams.
- A source-aware, multilingual content creation and distribution workspace.
- A conversational agent paired with channel-native editing and preview.
- A durable scheduler and capability-aware connector layer.
- A cross-channel analytics and community interface where provider access allows it.
- A human-approved system of action with explicit receipts.

### PostRiff is not

- A resale of James's personal Codex or ChatGPT session.
- A public tunnel into the founder's laptop.
- A generic terminal or unrestricted Python execution service.
- A promise to publish to every catalogued platform.
- A system that silently replies, moderates, spends money, or publishes on behalf of a user.
- A substitute for provider OAuth consent, app review, policy compliance, or capability verification.

## 3. Commercial hypothesis

### Initial customer

The first customer profile is a solo creator, educator, artist, founder, or small media operator who:

- Publishes in more than one language or cultural context.
- Adapts one core idea across multiple networks.
- Values thoughtful, sourced content over high-volume generic posting.
- Wants AI assistance but retains final control of voice and publication.
- Is overwhelmed by fragmented schedulers, channel setup, and technical instructions.

### Primary job to be done

> Help me turn a source, thought, or piece of media into credible native posts for the right channels, review them confidently, and publish or schedule them without managing several disconnected tools.

### Differentiation

PostRiff should compete on:

1. One canonical brief with genuine platform-native variants.
2. Multilingual and culturally differentiated writing workflows.
3. A Codex-like persistent agent that can research, use approved skills, and create media.
4. Transparent capability/readiness and exact action approval.
5. A calm interface centered on Ideas, not a large template or settings catalog.

The launch message should not lead with “33 channels.” A large catalog is not useful if permissions, scheduling, analytics, or comments are unavailable. The credible promise is fewer supported channels with reliable, clearly described capabilities.

## 4. Product modes

| Mode | User | Hosting | Purpose | Availability dependency |
|---|---|---|---|---|
| PostRiff Remote | Founder/internal operator | Local laptop through private Tailscale access | Dogfood, development, connector experiments | Laptop must be on, awake, online, and running PostRiff |
| PostRiff Cloud | Paying customers | Managed cloud | Primary SaaS experience | Independent of founder laptop |
| PostRiff Bridge | Customer with local-only needs | Customer desktop companion | Private files and reviewed browser-only capabilities | That customer's enrolled device must be online for Bridge jobs |

Remote and Cloud use the same visual product language and domain contracts. They do not share customer secrets, databases, or execution authority.

## 5. Customer-facing information architecture

PostRiff Cloud retains exactly six primary destinations:

1. Dashboard
2. Ideas
3. Scheduling
4. Channels
5. Analytics
6. Audience

Workspace switcher, team management, billing, usage, settings, audit/receipts, Bridge devices, help, export, and account security live in the account/utility menu. They are not primary destinations.

### Navigation behavior

- Desktop: collapsible left sidebar with all six destinations.
- Mobile: Dashboard, Ideas, Scheduling, and Audience plus `More` for Channels and Analytics.
- Workspace identity remains visible in the header.
- Global `Create` opens Ideas with an optional source/channel context.
- A customer never sees infrastructure terms such as worker, queue, tenant, OAuth scope, app-server, or sandbox unless they open an Advanced diagnostic view.

## 6. Core customer journeys

### 6.1 Signup to first valuable draft

1. User creates an account and verifies identity.
2. User creates or accepts a workspace.
3. PostRiff asks one compact onboarding sequence: role, primary channels, languages, voice/source preferences, and first goal.
4. User may skip channel connection and start with a draft.
5. Ideas opens with one suggested task appropriate to the onboarding answer.
6. The PostRiff Agent creates a canonical brief and at least one previewable variant.
7. The user sees value before being asked to understand provider setup.

### 6.2 Connect a channel

1. User selects a supported provider and the capability they want: publish, analytics, or comments.
2. PostRiff explains in one sentence what permission will be requested.
3. User completes the provider's OAuth flow.
4. PostRiff verifies identity, granted scopes, token persistence/expiry behavior, and capability-specific readiness.
5. User confirms the exact account.
6. The card shows separate Post, Schedule, Analytics, and Comments capability states.

### 6.3 Source to multi-channel post

1. User supplies a URL, document, media asset, transcript, or idea.
2. The agent records sources, verified facts, user viewpoint, audience, language, and goal in a canonical brief.
3. User selects explicit accounts or a saved channel group.
4. Skills generate native channel variants and media candidates.
5. User reviews previews and resolves smart preflight issues.
6. Schedule or Publish opens an exact action preview.
7. Approval binds account IDs, variant revisions, media hashes, timing, and action.
8. Durable workers execute only supported destinations.
9. Results remain separate per destination: not attempted, blocked, submitted, published, verified, or failed.

### 6.4 Comment to reply

1. Audience ingests a supported comment or mention.
2. User sees the original post and available thread context.
3. User writes manually or requests an AI draft/improvement.
4. Platform writing skills adapt tone and constraints.
5. Send Reply confirms exact account, thread, and final text.
6. Execution and verification are recorded separately.

### 6.5 Bridge-assisted action

1. PostRiff identifies that an attachment or channel capability needs a Bridge.
2. User selects an enrolled device and sees whether it is online.
3. Cloud creates a signed, least-capability job.
4. Bridge displays or processes the job inside an isolated boundary.
5. Actions requiring representation still require the same PostRiff approval manifest.
6. If the device is offline, the job remains waiting or expires; it is not described as completed.

## 7. Deployment topology

```text
Web / Mobile PWA
       │
CDN + WAF + TLS
       │
PostRiff Web/API
       ├──────── Authentication and Billing
       ├──────── Managed PostgreSQL
       ├──────── Object Storage
       ├──────── Durable Job Queue
       ├──────── Agent Event Stream
       │
       ├── Agent Worker Pool
       │      ├─ OpenAI runtime adapter
       │      ├─ Skill registry
       │      ├─ Python tool runner
       │      └─ Media jobs
       │
       ├── Connector Worker Pool
       │      ├─ OAuth/token service
       │      ├─ Publish/schedule adapters
       │      ├─ Analytics ingestion
       │      └─ Audience ingestion/replies
       │
       └── Bridge Gateway
              ↑ outbound authenticated connection
         Optional customer device
```

### Service boundaries

| Service | Responsibility | Must not do |
|---|---|---|
| Web/API | Sessions, authorization, validation, domain API | Hold long-running jobs in request processes |
| Agent service | Conversations, model calls, safe tool orchestration | Publish, reply, moderate, or access raw provider tokens |
| Python tool runner | Execute versioned product tools in isolation | Run arbitrary customer shell commands |
| Connector service | Provider OAuth and capability-specific API calls | Generate content or infer approval |
| Scheduler | Durable due-time/lease handling | Retry uncertain submissions without reconciliation |
| Billing service | Subscription and entitlement state | Authorize a social action merely because payment is valid |
| Bridge gateway | Device enrollment and signed jobs | Expose customer machines to inbound public traffic |

## 8. Tenancy and workspace model

### Tenant unit

`Workspace` is the data and billing tenant. Every customer-owned record carries a non-null `workspace_id` or belongs to a globally reviewed catalog.

### Roles

| Role | Typical user | Rights |
|---|---|---|
| Owner | Solo creator/founder | Billing, workspace deletion, members, connections, all editorial approvals |
| Admin | Operations lead | Members, channels, settings, editorial work; no ownership transfer or final billing control |
| Editor | Writer/creator | Sources, conversations, drafts, variants, media; cannot publish without separate permission |
| Approver | Brand/client lead | Review and approve permitted schedules, publications, and replies |
| Viewer | Analyst/client observer | Read-only content, scheduling, analytics, audience, and receipts |

A membership may carry explicit action permissions in addition to role. `can_publish`, `can_reply`, `can_moderate`, and `can_manage_connections` remain separate.

### Isolation rules

- Database queries require workspace context and enforce it both in the service layer and database policies.
- Object keys are workspace-scoped and delivered through short-lived signed URLs.
- Job payloads contain a workspace ID and are re-authorized when claimed.
- Agent retrieval cannot search across workspaces.
- Provider tokens are encrypted under workspace/account-specific metadata and never exposed to agent workers.
- Support impersonation is absent from the initial product. Future support access requires explicit customer consent, time-bound elevation, and immutable audit.
- Cross-workspace aggregates contain no content or identity detail unless separately anonymized and approved.

## 9. Authentication and account security

### Customer authentication

- Secure server-side session cookies: HttpOnly, Secure, and appropriate SameSite policy.
- Verified email plus passkey or MFA enrollment option.
- Step-up authentication for workspace deletion, billing changes, token export/revocation, and sensitive representational actions according to risk policy.
- Device/session list with remote logout.
- Login throttling, suspicious-session detection, and recovery controls.
- Invitations expire, bind to workspace/role, and cannot be replayed.

### Service authentication

- Separate machine identities for API, agent, connector, scheduler, billing, and Bridge gateway.
- Least-privilege database and secret access per service.
- Rotatable credentials stored in a managed secret system.
- Production API keys never enter browser bundles, mobile storage, logs, prompts, or customer-visible error messages.

## 10. PostRiff Agent and Codex strategy

### 10.1 Product experience

The customer sees the PostRiff Agent: a persistent Codex-like conversation with Quick, Standard, and Deep reasoning; Drafting, Research, and PostRiff Workspace access profiles; attachments; skill selection; progress cards; media generation; variants; and previews.

Customers do not see raw CLI flags, shell output, hidden reasoning, system prompts, provider keys, or filesystem paths.

### 10.2 Runtime abstraction

Define a stable product-owned interface:

```text
AgentRuntime
  startConversation
  resumeConversation
  startTurn
  cancelRun
  streamSafeEvents
  listSupportedModels
  listSupportedReasoning
```

Recommended runtime policy:

- **Cloud baseline:** a server-side OpenAI API runtime using a PostRiff project/service identity, with model/tool calls metered to the customer's PostRiff workspace.
- **Qualified cloud option:** a version-pinned Codex app-server runtime only after commercial terms, headless authentication, versioning, isolation, observability, and failure recovery are explicitly qualified.
- **Local/Bridge option:** the existing version-qualified Codex CLI pattern for founder use and reviewed device-local tasks.

PostRiff features must not depend directly on a private CLI event schema. Runtime events are translated into PostRiff's safe event contract.

### 10.3 API credentials

- Never use James's personal ChatGPT/Codex session as the credential for paying customers.
- Never ship an OpenAI key to the browser, mobile PWA, or Bridge UI.
- Use a production OpenAI project/service account and server-side secret storage.
- Attribute model and media usage to workspace, user, conversation, run, and feature.
- Support quota, budget, and model-policy changes without changing customer data.
- A future bring-your-own-key mode is a separate product decision with its own encrypted storage, validation, support, and billing semantics.

### 10.4 Safe event contract

Only these event families reach the client:

```text
run.started
progress.updated
source.added
artifact.created
message.delta
message.completed
warning.created
action.proposed
run.completed
run.failed
run.cancelled
```

No hidden chain-of-thought or arbitrary runtime event payload is forwarded.

## 11. Skills and Python tool system

### 11.1 Skill registry

Skills are versioned product resources with:

- Stable ID and semantic version.
- Human-readable name and purpose.
- Supported content patterns/platforms/languages.
- Required tool capabilities.
- Input/output schema.
- Source hash and release state.
- Deprecation/replacement metadata.
- Evaluation and regression fixtures.

The Skills picker may list all customer-available skills, but the agent loads only the relevant subset for a turn. Auto-routing shows the chosen skill family in plain language and allows a manual override.

### 11.2 Python tools

Existing Python modules should be refactored behind structured product tools. A tool definition includes:

- Stable tool name and version.
- JSON input/output schemas.
- Maximum duration, memory, CPU, network, and artifact size.
- Read/write roots.
- Required secrets, supplied only by the broker and never in prompts.
- Cost class.
- External-effect classification.
- Idempotency behavior.
- Audit-safe result summary.

Example tools:

```text
source.extract
source.research
brief.create
variants.generate
variants.translate
media.generate_image
media.create_renditions
post.preflight
analytics.compare
audience.draft_reply
delivery.prepare_manifest
```

### 11.3 Runner isolation

Each tool job receives:

- An immutable tool/runtime image.
- A fresh temporary workspace.
- Only explicitly attached or generated files.
- No other tenant mount.
- Network disabled by default and allowlisted per tool.
- Short-lived scoped credentials when required.
- CPU, memory, wall-time, process, and output limits.
- Cancellation and cleanup.
- Artifact scanning and declared media validation.

Arbitrary shell, package installation, host filesystem access, and unreviewed dynamic code are not customer features.

### 11.4 Tool-effect classes

| Class | Example | Default behavior |
|---|---|---|
| Read | Extract uploaded PDF, read stored analytics | Allowed within workspace entitlement |
| Creative write | Create draft, image candidate, translation | Allowed; result remains a candidate |
| Workspace mutation | Save variant, attach asset | Revision-checked and audited |
| Paid generation | Premium model/image/video call | Consume included credits or require overage authorization |
| External representation | Publish, reply, moderate | Never available as a direct agent tool; dedicated approval/executor only |
| Destructive | Delete workspace, purge media, revoke connection | Dedicated UI, step-up auth, recoverability/retention policy |

## 12. Channel integration architecture

### 12.1 Capability levels

Every provider/account capability is classified independently:

| Level | Meaning |
|---|---|
| Direct | Official API supports the capability and production app/scopes are verified |
| Assisted | PostRiff can export or hand off a draft but does not claim execution |
| Bridge | A customer-enrolled device may perform a reviewed browser/local workflow |
| Unsupported | Capability is unavailable and no workaround is represented as direct support |

Capabilities tracked separately:

`identity`, `publish`, `schedule`, `analytics`, `comments_read`, `reply`, `moderate`, `media_types`, and `webhooks`.

### 12.2 OAuth

- PostRiff registers its own production developer application per provider.
- Each customer authorizes their own account and requested scopes.
- Use public HTTPS callback URLs owned by PostRiff Cloud.
- Bind OAuth state to workspace, user, intended provider, intended capability, redirect, and expiration.
- Use PKCE/DPoP where provider support and reviewed integration call for it.
- Request incremental scopes at the moment a customer enables a capability.
- Encrypt refresh/access tokens and provider account identifiers.
- Validate account identity after token exchange and ask the user to confirm the destination.
- Token refresh, expiry, revocation, and scope drift update capability state.
- Disconnect revokes remotely when supported and removes local execution access.

### 12.3 Provider review gates

A connector is public only after:

1. Official documentation and terms are reviewed.
2. Required app/product/scopes are configured.
3. Provider review/audit is approved where required.
4. OAuth and token persistence are validated with non-founder test accounts.
5. Capability-specific read/write tests pass.
6. Error, rate-limit, revocation, duplicate, and partial-success paths pass.
7. Customer-facing permission and privacy copy is complete.
8. Production monitoring and disable switch exist.

Catalog presence is never launch evidence.

## 13. Scheduling, publication, and receipts

### Durable schedule model

- Store intended local time, IANA timezone, resolved UTC time, timezone database version, and content snapshot revision.
- Detect nonexistent/ambiguous daylight-saving times.
- Scheduler claims jobs with a lease; expired leases are reconciled before re-claim.
- Content/account changes invalidate approval.
- A schedule may include several destinations, but execution and status remain per destination.

### Approval manifest

Every publish/schedule/reply approval binds:

- Workspace and approving member.
- Action type.
- Exact provider/account IDs and customer-visible handles.
- Canonical item and variant revisions.
- Ordered media IDs and cryptographic hashes.
- Alt text and provider options.
- Timing/timezone.
- Preflight snapshot hash.
- Expiration and idempotency key.

The final button states the exact action, such as `Schedule 6 posts` or `Send this reply as @account`.

### Execution states

```text
not_attempted
blocked
queued
leased
submitting
submitted
published
verified
failed
needs_reconciliation
cancelled
```

An HTTP success, upload token, provider job ID, preview, or schedule record is not automatically a verified publication. Each provider adapter defines evidence required for every state.

### Retry policy

- Safe pre-submission failures may retry within bounded policy.
- Uncertain submissions enter `needs_reconciliation`.
- Reconcile provider status before any retry that could duplicate a post or reply.
- Customer-visible receipts disclose every attempted destination and result.
- Manual override/retry is a fresh action with its own idempotency key and, when content/timing changes, fresh approval.

## 14. Media and source storage

### Storage model

- Original uploads and generated assets live in workspace-scoped object storage.
- Metadata and provenance live in PostgreSQL.
- Downloads/previews use short-lived signed URLs.
- Media processing produces immutable renditions linked to the source.
- Customer deletion follows retention and recovery policy; legal/security holds are explicit exceptions.

### Provenance

Record:

- Uploader/generator and workspace.
- Source URL/document reference where relevant.
- Prompt, model/provider, version, and timestamp for generated media.
- Transformation chain: crop, resize, compression, subtitle, or format conversion.
- Rights/attribution declaration when required.
- AI-generation label requirements by destination.
- Alt text and accessibility status.

### Limits

Plan entitlements control storage and generation usage. Platform preflight separately enforces format, duration, dimensions, size, aspect ratio, and count. A plan allowing a large file does not imply a provider accepts it.

## 15. Analytics

### Data contract

Store native metric observations with:

- Workspace, account, post, provider, and metric name.
- Native definition/version.
- Value, unit, observation time, and coverage interval.
- Source endpoint/import and ingestion time.
- Availability/error state.
- Provider post identity and verification state.

### Cross-channel summary

Organize available metrics into:

- Attention: impressions, views, and reach where defined.
- Resonance: reactions, comments, replies, shares, reposts, quotes, and saves.
- Conversion: link clicks, profile visits, follows, and subscribers.
- Depth: watch time, average view duration, and completion.
- Audience health: total audience and net growth.

Rules:

- Missing is `Unavailable`, never zero.
- Do not claim cross-platform reach is unique people.
- Preserve native metric names in detail views.
- Derived rates disclose numerator and denominator.
- Comparison requires compatible cohorts.
- Fewer than three comparable posts yields an insufficient-sample message.
- Billing tier controls retention/export depth, not metric truth.

## 16. Audience

### Ingestion

Use provider webhooks where stable and polling where permitted. Track cursor/checkpoint per account and capability. Deduplicate provider events. Preserve deletions/tombstones when required without retaining disallowed content.

### Reply behavior

- Manual replies are always available when the provider supports reply and the user's role permits it.
- AI drafts use post/thread context, account voice, language, and relevant platform skill.
- AI never sends by default.
- Exact reply approval confirms account, thread, final text, and any media.
- Bulk/automatic reply is a separate later automation product with explicit limits and authorization.
- Delete, hide, report, restrict, and block are distinct moderation actions.

### Customer trust

- Show source post and available thread context.
- Label AI-generated suggestions.
- Keep the user's original reply until a proposed improvement is accepted.
- Allow saved replies and workspace voice guidance without silently modifying global skill definitions.

## 17. Billing, plans, and entitlements

### Billing principles

- Bill the workspace, not an individual browser session.
- Use server-verified subscription state and idempotent billing webhooks.
- Separate recurring entitlement from metered usage.
- Maintain an internal immutable usage ledger reconciled with the billing provider.
- Do not expose billing-provider secrets to the client.
- Cancellation, failed payment, grace period, downgrade, export, and deletion have explicit state transitions.
- Billing entitlement never substitutes for action approval or provider readiness.

### Initial packaging hypothesis

| Plan | Intended customer | Entitlement shape |
|---|---|---|
| Trial | New solo creator | One member, limited connected accounts, bounded AI/media credits, watermark-free real previews, conservative publication allowance |
| Creator | Solo professional | One member, core direct connectors, scheduling, standard analytics/audience retention, monthly AI/media allowance |
| Pro | Creator plus collaborator | Several members, more accounts, approvals, higher usage/storage, PostRiff Bridge, extended history/export |
| Studio | Small agency/media team | Multiple client workspaces, granular roles, higher limits, consolidated billing and support controls |

Exact prices and numeric allowances are set after founder-alpha usage measurement and interviews with the first design partners. Do not offer unlimited AI or generated media before unit economics are measured.

### Metered dimensions

- Model input/output usage by model class.
- Image/video generation jobs.
- Transcription/extraction minutes or pages where cost-bearing.
- Stored media and bandwidth.
- Connected accounts.
- Active members.
- Scheduled/published actions where provider/support cost justifies it.

The customer sees understandable credits/allowances, remaining usage, reset date, and overage behavior before a cost-bearing action.

## 18. Mobile and PWA experience

The initial customer app is a responsive installable PWA, not separate native applications.

### Mobile priorities

- Fast Ideas chat and attachment capture.
- Platform preview and variant switching.
- Approval and schedule confirmation.
- Audience triage and replies.
- Dashboard alerts and connection status.
- Offline-tolerant viewing of recently loaded drafts where safe.

### Mobile rules

- Four primary bottom-nav items plus More.
- 44 × 44 px minimum targets.
- No desktop three-pane layout squeezed into a phone; use Chat/Edit/Preview segments.
- Upload from camera, photo library, Files, and share sheet where browser support permits.
- Push notifications require an explicit user gesture/permission and are limited to useful events: approval requested, publication failed, Bridge offline for a due job, or reply attention.
- A notification opens the exact resource but does not execute its action.

Native iOS/Android apps are considered after PWA usage demonstrates a need for deeper share-sheet, media, notification, or background behavior.

## 19. PostRiff Bridge

### Purpose

Bridge provides customer-controlled capabilities without making the customer's device a public server.

### Enrollment

1. Workspace Owner/Admin creates a one-time device enrollment code.
2. Desktop app exchanges it for a device identity and scoped certificate/key pair.
3. User names the device and selects allowed capability families.
4. Cloud displays device status, version, last seen, capabilities, and revoke control.
5. Sensitive capability additions require re-enrollment or explicit step-up approval.

### Connection model

- Bridge establishes an outbound TLS connection or bounded long poll.
- Cloud never opens an inbound customer port.
- Jobs are signed, short-lived, workspace-bound, capability-bound, and non-replayable.
- Bridge validates signature, version, capability, expiry, workspace, and local policy before execution.
- Results are signed and contain sanitized receipts/artifacts.
- Device secrets stay in OS-protected storage.

### Offline behavior

- Cloud features not requiring Bridge remain available.
- Bridge jobs show `Waiting for device`, not queued/published.
- A due job that cannot meet its window becomes `Needs review`; it does not silently catch up.
- Cloud does not route one customer's Bridge job to another device or workspace.

### Browser-only connectors

Browser automation is a compatibility tier, not equivalent to an official API. Each provider route must be reviewed for policy, reliability, selectors, session isolation, verification evidence, and recovery. Customer browser profiles are isolated per workspace/account and never uploaded wholesale to cloud storage.

## 20. Suggested data model

### Identity and commercial

```text
users
workspaces
workspace_memberships
roles_and_permissions
sessions
invitations
subscriptions
entitlements
usage_ledger
billing_events
```

### Content and agent

```text
conversations
messages
attachments
agent_runs
agent_events
skill_releases
tool_releases
content_items
canonical_briefs
post_variants
variant_revisions
media_assets
media_renditions
preflight_issues
channel_groups
```

### Providers and execution

```text
provider_apps
channel_connections
channel_capabilities
oauth_transactions
encrypted_credentials
schedules
action_proposals
approval_manifests
execution_jobs
execution_attempts
execution_receipts
provider_webhook_events
```

### Insights and community

```text
metric_definitions
metric_observations
provider_posts
audience_threads
audience_messages
reply_drafts
moderation_actions
ingestion_checkpoints
```

### Bridge and operations

```text
bridge_devices
bridge_capabilities
bridge_jobs
bridge_receipts
audit_events
support_events
data_exports
deletion_requests
```

All tenant-owned tables include workspace identity, creation/update times, and domain-specific revision/idempotency fields. Global catalogs never contain customer secrets.

## 21. API surface

### Accounts and workspaces

```text
POST     /api/auth/*
GET/POST /api/workspaces
GET/PATCH /api/workspaces/{id}
GET/POST /api/workspaces/{id}/members
POST     /api/workspaces/{id}/invitations
GET      /api/workspaces/{id}/usage
GET      /api/workspaces/{id}/subscription
```

### Ideas and content

```text
GET/POST /api/workspaces/{id}/ideas/conversations
POST     /api/workspaces/{id}/ideas/conversations/{conversationId}/turns
GET      /api/workspaces/{id}/ideas/runs/{runId}/events
POST     /api/workspaces/{id}/ideas/runs/{runId}/cancel
POST     /api/workspaces/{id}/attachments
GET/PUT  /api/workspaces/{id}/content/{contentId}
POST     /api/workspaces/{id}/content/{contentId}/variants
POST     /api/workspaces/{id}/content/{contentId}/preflight
POST     /api/workspaces/{id}/content/{contentId}/action-preview
```

### Channels and execution

```text
GET      /api/workspaces/{id}/channels
POST     /api/workspaces/{id}/channels/{provider}/oauth/start
GET      /api/oauth/{provider}/callback
POST     /api/workspaces/{id}/channels/{connectionId}/verify
DELETE   /api/workspaces/{id}/channels/{connectionId}
POST     /api/workspaces/{id}/content/{contentId}/schedule
POST     /api/workspaces/{id}/content/{contentId}/publish
GET      /api/workspaces/{id}/executions/{executionId}
```

### Analytics and Audience

```text
GET      /api/workspaces/{id}/analytics/summary
GET      /api/workspaces/{id}/analytics/posts
GET      /api/workspaces/{id}/audience/threads
POST     /api/workspaces/{id}/audience/threads/{threadId}/reply-drafts
POST     /api/workspaces/{id}/audience/threads/{threadId}/reply-preview
POST     /api/workspaces/{id}/audience/threads/{threadId}/reply
```

### Bridge

```text
POST     /api/workspaces/{id}/bridge/enrollment
GET      /api/workspaces/{id}/bridge/devices
PATCH    /api/workspaces/{id}/bridge/devices/{deviceId}
DELETE   /api/workspaces/{id}/bridge/devices/{deviceId}
POST     /api/workspaces/{id}/bridge/jobs
GET      /api/bridge/jobs/next
POST     /api/bridge/jobs/{jobId}/receipt
```

Every workspace route validates session, membership, permission, entitlement, resource ownership, expected revision, and relevant idempotency key. The server derives workspace context; it never trusts a body field alone.

## 22. Security, privacy, and compliance baseline

### Security controls

- Environment separation for development, staging, and production.
- Encrypted transport and managed certificates.
- Encryption at rest for database, object storage, backups, and logs where supported.
- Application-layer encryption for provider refresh tokens and sensitive Bridge material.
- Secret rotation and emergency connector disable controls.
- Tenant-bound authorization on every read and mutation.
- CSRF protection, secure cookies, content security policy, input validation, and output encoding.
- Upload type/size validation, malware scanning where appropriate, and untrusted-document handling.
- Rate limiting by IP, user, workspace, provider account, and operation.
- Immutable audit events for authentication, role, connection, approval, external action, billing, export, and deletion.
- Dependency, container, and infrastructure scanning in CI.
- Backup restore tests and incident-response runbooks.

### Privacy controls

- Privacy notice explains AI processing, social-provider access, analytics/comment ingestion, retention, Bridge behavior, and subprocessors.
- Data minimization: request only the scopes and content required for enabled features.
- Workspace export and deletion flows.
- Provider disconnect/revocation.
- Retention classes for drafts, generated media, logs, tokens, comments, analytics, receipts, and backups.
- Customer content is not exposed in cross-tenant telemetry.
- Support diagnostics are sanitized and bounded.

### Policy and content controls

- Customer confirms rights to uploaded and published content.
- Preserve citations and source provenance for research-based content.
- Support provider-required branded-content, privacy, music-rights, and AI-generated-content declarations.
- Add abuse controls for spam, impersonation, harassment, deceptive engagement, and coordinated automated replies.
- External actions remain attributable to a real customer workspace and approving member.

This candidate does not claim any legal certification or regulatory compliance. Privacy, terms, data processing, tax, and jurisdictional requirements require professional review before public sale.

## 23. Reliability and operations

### Reliability principles

- Request processes are stateless; durable work is recorded before execution.
- Every job is idempotent or has a reconciliation path.
- Dead-letter/needs-review states are customer-visible and actionable.
- Provider outages are isolated; one connector cannot block the entire schedule.
- Feature flags can disable a provider capability without hiding historical receipts.
- Deployments are backward-compatible with in-flight jobs and event streams.

### Observability

Monitor:

- API latency/error rate by route and workspace-safe cohort.
- Agent success, cancellation, timeout, token/media usage, and tool failure.
- Queue age, lease expiry, retries, reconciliation backlog, and duplicate prevention.
- OAuth success, scope drift, refresh failure, and revocation.
- Provider rate limits and action outcomes.
- Analytics/Audience ingestion freshness.
- Billing webhook processing and entitlement drift.
- Bridge online rate, version, job latency, and failure class.

Logs and traces use stable IDs and sanitized metadata; they do not record full prompts, post bodies, tokens, raw comments, or customer files by default.

### Customer-visible status

- Global status page for material incidents.
- In-product capability status per provider.
- Honest freshness timestamps for analytics and audience data.
- Precise incident language that separates queued, attempted, provider-accepted, published, and verified.

## 24. Customer onboarding and support

### Onboarding

- Let customers create value before requiring every connection.
- Ask one question at a time.
- Offer source-to-draft starter tasks based on role/language.
- Introduce channels only when the user wants preview, scheduling, analytics, or audience features.
- Show plain-language permission value and current capability.
- Provide a safe sample workspace that cannot publish.

### Support model

- Contextual help and provider-specific recovery guides.
- Customer-submitted diagnostic package contains selected sanitized metadata and requires explicit consent.
- Support can request a capability check but cannot read tokens or silently publish.
- Every support-relevant action has a receipt visible to the customer.
- Public launch requires support paths for billing, account recovery, data deletion, provider disconnection, and failed publication.

## 25. Migration from the current local Studio

### Preserve

- Six-destination PostRiff product design.
- Canonical brief and platform-native variant model.
- Skills and editorial workflows.
- Python content, research, analytics, media, and delivery logic after tool wrapping.
- Exact review, revision, idempotency, scheduling, and receipt concepts.
- Capability-specific channel status.
- Local-first Bridge option for private files/browser workflows.

### Replace or refactor

| Current local component | SaaS destination |
|---|---|
| Local SQLite | Managed PostgreSQL with tenant policies |
| Local asset blobs/files | Workspace-scoped object storage |
| Per-process localhost session | Cloud authentication, memberships, and secure sessions |
| Manual local service startup | Managed API and worker deployment |
| Local Codex personal session | Server-side production API/runtime identity |
| Direct Python module access | Versioned structured tool runner |
| Localhost OAuth callbacks | Provider-approved public HTTPS callbacks |
| Local delivery worker | Durable multi-tenant scheduler/connector workers |
| Browser-session connector | Official API, Assisted flow, or optional PostRiff Bridge |

### Customer import

- Export drafts, briefs, variants, templates, and eligible assets from the local app.
- Import into a chosen workspace with conflict and size validation.
- Do not import provider tokens, raw browser profiles, local session secrets, or uncertain schedule state.
- Customers reconnect social accounts through PostRiff Cloud OAuth.
- Local delivery jobs import as drafts/history, not as approved cloud schedules.
- Import receipt reports every accepted, skipped, transformed, and rejected item.

## 26. Delivery phases

### Phase 0 — Founder Remote alpha

Goal: validate the product workflow with James as the only user.

- Mobile-responsive six-tab shell.
- Private Tailscale access through a dedicated remote gateway.
- Persistent Ideas conversation and approved local tools.
- Reliable previews, preflight, schedules, and receipts.
- Daily dogfooding and issue log.

Exit gate: the flow is valuable and stable for the founder, but remains explicitly local/private.

### Phase 1 — SaaS foundation

Goal: make the core tenant-safe before external users.

- Cloud authentication, workspaces, memberships, and roles.
- Managed PostgreSQL, object storage, job system, and secrets.
- Server-side OpenAI runtime abstraction, skill registry, and Python tool isolation.
- Tenant-scoped Ideas and content APIs.
- Usage ledger and entitlement engine without live charging.
- Security and tenant-isolation tests.

Exit gate: two synthetic tenants cannot access or affect each other under read, write, agent, object, job, and error paths.

### Phase 2 — Closed design-partner beta

Goal: prove customer value with a small manually supported group.

- Invite-only onboarding.
- Dashboard, Ideas, Scheduling, Channels.
- Two or three verified direct connectors selected from a live capability audit.
- Basic post-level analytics where supported.
- No browser automation required for the core promise.
- Manual support and usage/cost observation.

Exit gate: design partners repeatedly create, approve, and execute useful content with measured reliability and acceptable unit economics.

### Phase 3 — Paid beta

Goal: charge safely and learn retention.

- Production subscription provider and idempotent webhooks.
- Creator and Pro packaging.
- Usage/credit visibility and limits.
- Privacy, terms, export, deletion, recovery, and support flows.
- Provider app reviews and production scopes.
- Audience read/manual reply for verified providers.
- PostRiff Bridge private beta for carefully selected needs.

Exit gate: paying customers can self-serve core onboarding, understand limits, receive support, and leave/export/delete without manual database work.

### Phase 4 — Public launch

Goal: expand reliability and acquisition, not merely connector count.

- Public signup and abuse controls.
- Provider status/incident tooling.
- Expanded analytics and Audience capability.
- Additional direct connectors only after launch gates.
- Studio packaging and team approval workflows.
- PWA push notifications and polished mobile acquisition/onboarding.

### Phase 5 — Selective automation

Goal: add bounded recurring value after trust is established.

- Saved content recipes.
- Reusable channel groups and brand/voice profiles.
- Sufficient-data posting-time recommendations.
- Optional approval policies by action/risk.
- Carefully bounded auto-response or recurring workflows with clear pause, limits, audit, and revocation.

## 27. First sellable product scope

The first paid beta should include:

- Cloud signup and one workspace.
- Ideas conversation with URL/document/media attachments.
- Personalized content-type catalog, optional starter packs, guided type creation, and private/workspace reusable templates.
- Relevant skill routing and controlled Python tools.
- Canonical brief and at least two channel-native variants.
- Image generation/upload, alt text, and platform preview.
- Smart preflight.
- Calendar and list scheduling.
- Two or three verified direct social integrations.
- Exact publish/schedule approval and per-destination receipts.
- Basic post performance when provider data exists.
- Usage/credit meter, subscription state, export, disconnect, and account deletion.
- Responsive mobile PWA.

The first paid beta should not depend on:

- All 33 platforms.
- Fully automated replies.
- Agency/client hierarchy.
- Browser automation.
- Native mobile applications.
- Advanced attribution or cross-platform unique reach.
- Unlimited AI/media generation.

## 28. Acceptance criteria

### Tenant isolation

- Workspace A cannot enumerate, fetch, infer, mutate, stream, export, schedule, or execute Workspace B resources.
- Signed object URLs cannot cross workspace or outlive policy.
- Agent retrieval and tool mounts contain only selected workspace inputs.
- Job claims revalidate workspace and authorization.
- Error messages do not reveal resource existence across tenants.

### AI, skills, and tools

- No production model key exists in browser/mobile bundles.
- Usage is attributable to workspace, member, run, model, and tool.
- Relevant skills can be selected or auto-routed with version recorded.
- Python tools execute in isolated bounded jobs.
- Unknown/unreviewed skills or tools cannot be invoked by client-supplied IDs.
- Paid generation respects credits/overage policy before execution.
- No hidden reasoning or raw runtime event reaches the client.

### Channels

- Every connected account belongs to exactly one workspace unless explicitly reauthorized elsewhere.
- OAuth state, callback, account confirmation, scopes, token persistence, refresh, revocation, and capability verification are tested.
- Public capabilities reflect production app review state.
- Identity, publish, schedule, analytics, comments, reply, and moderation remain distinct.
- Unsupported or Bridge-only states are clear.

### Scheduling and external actions

- Schedules survive API/worker restarts.
- Timezone/DST behavior is tested.
- Content/account/timing changes invalidate approval.
- Duplicate prevention and uncertain-submission reconciliation are tested.
- Partial success remains per destination.
- Agent text cannot directly invoke publish, reply, moderation, connection, billing, or deletion.

### Billing

- Subscription webhooks are signature-verified, replay-safe, and idempotent.
- Entitlements cannot be self-increased by the client.
- Usage ledger reconciles with model/media/job events.
- Downgrade, grace period, cancellation, failed payment, export, and deletion behave consistently.
- Billing success never changes provider readiness or action approval.

### Mobile/PWA

- All six destinations are reachable at 390 × 844 without horizontal overflow.
- Ideas supports prompt, URL, document/image attachment, preview, and approval on mobile.
- Ideas supports browsing the personalized catalog, guided type creation, proposal review, and private-template reuse on mobile.
- Keyboard, screen-reader, focus, contrast, and reduced-motion acceptance pass.
- Push notifications require permission and never execute actions.
- Cellular-network acceptance is tested independently of the founder LAN.

### Bridge

- Enrollment is one-time, scoped, expiring, and auditable.
- Bridge makes only outbound connections.
- Device revoke prevents new jobs.
- Offline/expired jobs do not silently execute later.
- One workspace/device cannot claim another's job.
- Browser profiles and tokens do not enter agent prompts or cloud backups.

### Launch truthfulness

- Local preview is not reported as cloud deployment.
- Provider submission is not reported as verified publication.
- Design or passing tests are not reported as public launch.
- A catalogued connector is not reported as production-ready without its launch gate.
- Analytics freshness and missing data are visible.

## 29. Success metrics

### Activation

- Time from signup to first previewable native variant.
- Percentage connecting at least one verified channel.
- Percentage completing one approved schedule or publication.

### Product value

- Weekly workspaces creating a canonical brief.
- Variants accepted versus heavily rewritten.
- Posts scheduled/published per active workspace.
- Multi-language/platform workflows completed.
- Audience replies drafted and intentionally sent.

### Trust and quality

- Preflight issues resolved before action.
- Publication/reply success and verification rates per provider.
- Duplicate/uncertain submission rate.
- OAuth reconnection and scope-drift rate.
- Customer-cancelled agent/action rate.
- Support incidents involving incorrect account or content.

### Commercial

- Trial-to-paid conversion.
- Paid workspace retention.
- Gross margin after model, media, storage, bandwidth, provider, and support costs.
- Usage distribution by plan.
- Expansion from Creator to Pro/Studio.

No metric should reward spam volume, unreviewed automation, or misleading engagement behavior.

## 30. Principal risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Building all connectors before product fit | Delays value and creates brittle support surface | Launch with two or three verified direct connectors |
| Cross-tenant data leak | Critical trust/security failure | Defense-in-depth tenant checks, isolation tests, scoped storage/jobs |
| AI cost exceeds plan revenue | Unsustainable unit economics | Usage ledger, quotas, model routing, no unlimited tier |
| Personal Codex credential used in production | Security, billing, support, and governance failure | Server-side production API project/service identity |
| Provider review rejected or delayed | Feature unavailable | Capability-aware roadmap, Assisted mode, no false launch promise |
| Duplicate publication/reply | Reputational harm | Idempotency, immutable manifest, reconciliation-before-retry |
| Browser automation becomes core | Reliability/policy/support burden | Official API first; Bridge optional and explicitly labeled |
| Too much setup copy returns | User overwhelm | Progressive disclosure and one-next-step copy rules |
| Mobile approval becomes accidental | External harm | Clear action summary, step-up auth, no notification execution |
| Analytics combines incompatible metrics | Misleading customer decisions | Native definitions, completeness, like-for-like comparisons |

## 31. Decisions required before implementation planning

The implementation plan should be created only after review of these choices:

1. Confirm the initial customer: solo creators first, not agencies first.
2. Confirm PostRiff Remote is founder alpha only.
3. Confirm PostRiff Cloud is the paying-customer runtime.
4. Confirm PostRiff Bridge is optional and not required for the initial core promise.
5. Select two or three launch connectors from a current provider capability/app-review audit.
6. Choose the production cloud/runtime vendors and data region.
7. Choose the server-side OpenAI runtime baseline and complete commercial/security qualification.
8. Confirm initial plan packaging; set prices and numeric limits after design-partner evidence.
9. Define retention/export/deletion policy with legal review.
10. Decide whether Analytics and Audience are beta requirements or transparent limited previews at first sale.

## 32. Evidence and current-source notes

The following current documentation informed this candidate:

- [OpenAI API key safety](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety%2525252525252523.class): production keys must remain server-side and must not be shared or embedded in browser/mobile clients.
- [OpenAI project API keys and service accounts](https://platform.openai.com/docs/api-reference/project-api-keys): project-scoped users/service identities support production credential separation and governance.
- [OpenAI Codex app-server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md): thread/turn/event primitives inform the Codex-like client architecture; commercial cloud use remains qualification-gated in this spec.
- [YouTube OAuth for server-side applications](https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps): each customer authorizes specific scopes; server applications securely retain authorized tokens and state.
- [TikTok Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-get-started): registered app, approved publish scope, user authorization, and provider audit are material production gates.
- [TikTok app registration and review](https://developers.tiktok.com/docs/en/getting-started-create-an-app): production products/scopes and verified URLs require provider review.
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve): appropriate for founder/private remote access while the origin device remains online; not the paying-customer SaaS runtime.
- [Buffer composer workflow](https://support.buffer.com/en-us/articles/scheduling-posts-4Qdld7giAZ), [Insights](https://support.buffer.com/en-us/articles/using-insights-in-buffer-x4gLauQU5a), and [Community](https://support.buffer.com/en-us/articles/using-community-in-buffer-jvTv4uQacA): reference patterns for per-network customization, lightweight analytics, and unified comment review.

All provider capabilities, terms, app-review requirements, usage limits, and API behavior must be re-verified when a connector enters implementation or public launch review.
