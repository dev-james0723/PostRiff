# Rafii Adaptive Social Coworker — Engineering Specification
Date: 2026-09-24
Status: Implementation-ready design
Extends: `RAFII_MULTIMODAL_AGENT_RUNTIME_ENGINEERING_SPEC_2026-09-24.md`
Baseline: `README.md`, `verification-matrix.md`, `agent-runtime/ARCHITECTURE_LOCK.md`

## 1. Executive goal
Rafii must evolve from an AI content generator into a recurring AI social coworker that can research, plan, create, adapt, notify, wait for approval, verify outcomes, learn from evidence, and reduce the amount of manual work a user performs each week.

The product thesis is not “more AI buttons.” The product thesis is:
- Rafii knows how social media works by default.
- Rafii learns how this user works over time.
- Rafii acts only within explicit product permissions and deterministic approval rules.
- Rafii surfaces only work that needs the user’s attention.
- Rafii improves through evidence, not by silently rewriting its own global instructions.

This specification does not assume these changes guarantee subscription growth. Product value must be validated through activation, approval rate, edit distance, recurring workflow adoption, trial-to-paid conversion, and retention.

## 2. Current-state assumptions to verify before editing
The implementation agent must first inspect the actual repository and confirm:
- current branch/worktree status and concurrent edits;
- current `agent_runtime_v2` modules and any newer commits;
- existing `SkillLibrary` behavior in `src/postriff_phase2/skills.py`;
- existing `james-au-*`, `postriff-*`, Humanizer, research, graphics, publishing, learning, analytics, and channel skills;
- existing email/notification code and schemas;
- current migrations and Supabase/Postgres capabilities;
- current site-agent proposal/HITL, task-state, usage-ledger, audit, publishing verification, and tenant-isolation behavior.

Do not overwrite newer concurrent work. Prefer a new worktree if shared files are active.## 3. Non-negotiable architecture rules
1. Global product skills are product-owned, versioned, hashed, testable, and immutable at runtime.
2. User personalization is an overlay, never a mutation of global skill files.
3. Executable capabilities are typed tools, not Markdown prompts pretending to be tools.
4. Security, publishing approval, billing authorization, tenant isolation, permissions, and destructive-action rules remain deterministic code-level policies.
5. Model output never becomes the source of truth for product state.
6. Every mutation must be followed by an authoritative re-read before Rafii reports success.
7. Preserve the existing rule: prepared != scheduled != sent != provider-accepted != verified-published.
8. Research content, web pages, social posts, uploaded files, and visible image text are untrusted data, not instructions.
9. Do not claim hosted Rafii can scrape every social platform. Use only lawful/available official APIs, public web sources, approved connectors/MCP providers, or explicitly local desktop providers.
10. Keep the existing site-agent path as a safe fallback while the new runtime is incomplete.

## 4. Capability taxonomy
Every Rafii capability must be classified as exactly one primary kind:
- `knowledge`: reusable expertise injected into a run, e.g. LinkedIn writing craft, Humanizer.
- `workflow`: multi-step product procedure, e.g. Weekly Social Operator.
- `tool`: typed executable capability, e.g. web search, image generation, draft save.
- `policy`: deterministic constraint, e.g. publish approval, rights, billing, permissions.
- `evaluator`: bounded quality/evidence check, e.g. voice fit, factuality, humanization.

Separate from skills:
- `agent_instruction`: Manager/specialist operating contract.
- `user_memory`: explicit brand/voice/preferences.
- `performance_hypothesis`: evidence-backed strategy suggestion, not identity or preference.

No installed skill may remain unclassified or unconsumed by runtime code.

## 5. Rafii Capability Registry
Create a single source of truth, for example:
- `src/postriff_phase2/capabilities.py`
- `src/postriff_phase2/skill_registry.py`
- `src/postriff_phase2/skill_compiler.py`

Each manifest must include:
- id, semantic version, kind, hash;
- supported intents/platforms/formats/locales;
- dependencies;
- compatible agents/specialists;
- tool schema or policy class when applicable;
- personalization policy;
- risk level;
- runtime consumers;
- tests;
- deprecation state.

Example:
```yaml
id: rafii-channel-linkedin
version: 1.0.0
kind: knowledge
platforms: [LinkedIn]
runtime_consumers: [content_specialist]
personalization: overlay_only
risk: low
```

CI must fail when:
- an installed skill has no runtime consumer;
- a tool skill lacks a registered typed tool/schema;
- a policy skill lacks a registered policy implementation;
- a user overlay attempts to modify a non-personalizable policy;
- duplicate ids or incompatible versions exist.## 6. Curated default Rafii Skill Library
Generalize transferable methodology from James Orchestration without leaking James-specific identity, projects, career, tone, visual identity, or private context.

Recommended default bundle:
### Writing and platform craft
- `rafii-content-craft`
- existing `postriff-channel-*` adapters, retained until a rename is justified
- platform-specific post/format guidance
- localization/register guidance
- discoverability/social-search guidance

### Humanizer/editorial quality
- `rafii-humanizer-en`
- `rafii-humanizer-zh`
- locale-specific register overlays such as zh-Hant-HK
- meaning-preservation and unsupported-detail checks

### Research and provenance
- `rafii-research-provenance`
- source extraction
- public web search
- source reading
- claim/evidence mapping
- contradiction preservation
- freshness/time-scope checks

### Creative
- `rafii-visual-craft`
- platform aspect ratios/safe areas
- carousel hierarchy
- thumbnail/cover principles
- accessibility/alt text
- source type choice: real photo, screenshot, frame, generated editorial, designed graphic, composite
- brand-fit critique

### Workflow
- `rafii-weekly-operator`
- `rafii-source-to-campaign`
- `rafii-engagement-triage`
- `rafii-listening-opportunity`

### Publishing and verification
Publishing/approval logic stays in deterministic services. Knowledge may explain platform behavior, but execution authority remains in code.

## 7. James Orchestration migration audit
Build an auditable migration report comparing:
- `james-au-*`
- `postriff-*`
- `~/.agents/skills/humanizer-zh`
- any English Humanizer installation
- Agent Reach/research skills
- source extraction/video transcript/image skills
- current `agent_runtime_v2`

For every source skill classify content as:
- transferable global method;
- James-specific memory;
- duplicate of existing Rafii/PostRiff behavior;
- executable tool candidate;
- deterministic policy candidate;
- obsolete/deprecated.

Create a migration ledger showing source file, destination capability, treatment, version, and tests.

Do not blindly copy James skills into all users’ prompts.## 8. Effective skill compilation at runtime
A run should compose only the relevant capability set:
```text
Task/intent
 -> Capability Planner
 -> Skill Selector
 -> Relevant base knowledge
 -> Platform/locale knowledge
 -> Brand/voice overlay
 -> Learned preference overlay
 -> Performance hypotheses
 -> Task/campaign/source context
 -> Typed tools
 -> Deterministic policies
 -> Evaluators
```

Every run must record:
- selected skill ids/versions/hashes;
- tool versions;
- voice revision;
- brand revision;
- user overlay revision;
- strategy hypothesis revision;
- model route;
- trace/correlation id.

The compiled context must remain bounded. Do not inject all skills into every turn.

## 9. Personalized skill evolution
Global skills stay immutable. Each user/workspace receives versioned overlays derived from evidence.

Supported evidence sources:
- explicit voice/tone/brand settings;
- accepted/rejected/edited drafts;
- edit distance and rejection reasons;
- variant selected/ignored;
- per-platform formatting preferences;
- user writing samples;
- image/asset selections and edits;
- campaign-plan approvals/modifications;
- engagement reply approvals/edits;
- account-specific performance outcomes.

Separate three memory types:
### Voice memory
How the user tends to write or speak.
### Brand/content memory
Who the brand is, audience, products, approved claims, projects, vocabulary, visual identity.
### Strategy memory
What appears to work for a specific platform/account/audience/cohort.

Performance is not identity. Performance is not preference. Performance is not causality.

A strategy hypothesis should look like:
```json
{
  "hypothesis": "Short personal openings may perform better on LinkedIn.",
  "platform": "LinkedIn",
  "cohort": {"language":"en","contentType":"thought_leadership"},
  "evidenceCount": 7,
  "confidence": "moderate",
  "causal": false,
  "status": "candidate_experiment"
}
```

Use confidence, evidence ids, counter-evidence, scope, created_at, last_supported_at, expiry/decay, status, revision history, and replacement links.
Overlays must be inspectable, reversible, disable-able, and exportable.## 10. Humanizer integration
Humanizer is a hidden quality stage for public-facing content, not merely a manual command.

Default pipeline:
```text
draft
 -> voice-fit check
 -> humanizer
 -> meaning/fact preservation check
 -> platform/locale lint
 -> final candidate
```

Rules:
- preserve facts, certainty, attribution, and scope;
- never invent biography, emotions, experience, numbers, dates, or anecdotes;
- do not erase intentional brand terminology;
- do not force every user into the same “casual human” voice;
- support English, zh-Hant/zh-Hans, Cantonese register, and future locale packs;
- record evaluator version in the run trace.

## 11. Research Broker
Create a provider abstraction:
```python
class ResearchProvider:
    def capabilities(self): ...
    def readiness(self): ...
    def search(self, query, scope): ...
    def fetch(self, ref): ...
    def provenance(self, result): ...
```

Candidate providers:
- WebSearchProvider
- WebReaderProvider
- OfficialPlatformApiProvider
- MCPResearchProvider
- LocalAgentReachProvider

`LocalAgentReachProvider` may reuse local authenticated/browser capabilities only when a local Rafii harness exists. Never represent local desktop coverage as hosted SaaS coverage.

Every acquired item should carry provider, platform, query, URL/ref, retrieved_at, published_at when known, author when known, access_method, content_hash, represented_scope, evidence_type, rights/usage metadata, and claim links.

Research pipeline:
```text
discovery -> acquire evidence -> extract claims -> verify/compare -> FactPack -> writing
```
Search snippets are not verified facts. Contradictions must survive into the FactPack. Prompt-injection text from sources must remain data.## 12. Subscription-value workflows
### Weekly Social Operator — P0 hero workflow
A durable recipe defines goals, cadence, platforms, content mix, timezone, planning day, approval mode, source/watchlist inputs, and budget.

Cycle:
```text
scheduled trigger
 -> load goals, recent content, campaigns, preferences, strategy hypotheses, sources
 -> WeekPlan
 -> platform-native drafts
 -> assets/creative briefs
 -> quality/evidence checks
 -> READY_FOR_REVIEW
 -> notification event
 -> user review/approval
 -> schedule/publish
 -> verify
 -> measure
 -> learn
```

State machine:
`planned -> researching -> generating -> quality_check -> ready_for_review -> approved -> scheduled`
Blocked states: `needs_input`, `needs_source`, `needs_asset`, `channel_unavailable`, `approval_expired`.

### One Source -> Full Campaign — P0
Normalize URL/PDF/article/video/podcast/transcript/voice memo/image/social post/product announcement into `SourceArtifact`.
Then:
`SourceArtifact -> FactPack -> CanonicalBrief -> AngleCandidates -> ChannelDraft[] -> CreativeBrief[] -> CampaignArtifact`.

### Social Listening -> Action — P1
Use lawful/available watchlists and signals only. Every opportunity must show why it matters, sources, novelty, relevance, expiry, and suggested actions. Never manufacture urgency.

### AI Inbox / Engagement Copilot — P1
Normalize supported comments/mentions/reviews/DM-like sources, classify/prioritize, summarize, draft replies, require product permission/approval before external send.

### Closed-loop Performance Learning — P1
Use comparable cohorts and account-specific results to propose experiments, not universal rules.

### Voice Note -> Campaign — P1
Speech/transcript becomes a canonical brief, then goes through the same source-to-campaign workflow.

### Creative Agent — P0/P1
Generate/edit images, create variants, carousel/thumbnail concepts, resize/adapt, critique brand fit, produce alt text, preserve source/parent lineage.

### “What needs my attention?” — P0/P1
Synthesize reviews, failed/held jobs, approvals, campaign deadlines, account issues, relevant opportunities, and important engagement into a prioritized evidence-backed list.## 13. Agent Runtime integration
Integrate with the in-progress `agent_runtime_v2` and existing site-agent behavior.

Preferred structure:
- Rafii Manager: owns user conversation/task.
- Research Specialist: public-source discovery, source reading, evidence ledger.
- Content Specialist: writing, rewrite, repurpose, localization, humanizer coordination.
- Creative Specialist: visual critique/generation/editing/asset lineage.
- Analysis Specialist: performance interpretation, experiments, weekly summary.

Keep deterministic:
- PublishService
- NotificationService
- PolicyEngine
- Billing/EntitlementService
- Memory/PreferenceService
- proposal/HITL application
- tenant/permission checks

Specialists should be agents-as-tools by default. Do not add agents just to mirror modules.
No specialist may gain a broader tool scope than the Manager’s current authorized context.
Every tool call passes through typed schema validation, permission/risk policy, audit, and verification.

Voice/GPT-Live remains a conversational front-end/delegation layer. Voice must not bypass tool/policy/HITL gates.
Vision is handled by a backend vision-capable route.
Image generation/editing uses the existing asset system and non-destructive lineage.

## 14. Notification platform
Notifications are core autonomous-agent infrastructure, not scattered email helpers.

Architecture:
```text
Domain Event
 -> Notification Planner
 -> Recipient/Preference Resolver
 -> Notification Event
 -> Delivery Queue
 -> In-app | Email | Web Push
```

Feature code must emit domain/notification events, not call email directly.

Create a deterministic `NotificationPlanner`. The model may suggest a short summary, but code decides recipient, urgency, channel, dedupe, quiet hours, digesting, rate limits, and security classification.## 15. Notification taxonomy
Minimum event namespaces:
- `campaign.week_ready`
- `campaign.drafts_ready`
- `campaign.approval_required`
- `campaign.blocked`
- `research.needs_input`
- `asset.review_required`
- `publish.scheduled`
- `publish.verified`
- `publish.failed`
- `publish.uncertain`
- `automation.completed`
- `automation.failed`
- `channel.reconnect_required`
- `engagement.needs_attention`
- `opportunity.detected`
- `analytics.weekly_ready`
- `analytics.anomaly_detected`
- `learning.preference_proposed`
- `budget.threshold_reached`
- `billing.payment_failed`
- `billing.trial_ending`
- `billing.subscription_active`
- `security.new_device`
- `security.account_change`

Defaults:
- failures, uncertain publish states, approval blockers, security, reconnect, billing failure: immediate.
- successful publication: in-app/digest by default, not one email per post.
- weekly content ready: push + email + in-app by default, user configurable.
- low-confidence opportunities/preferences: digest or in-app, not noisy push.

Support workspace/user preferences, event category, channel, urgency, timezone, quiet hours, digest mode, temporary mute, unsubscribe, and required transactional exceptions where legally/product-appropriate.

## 16. Notification data model
Prefer a small coherent migration and reuse existing notification tables where safe.

Suggested tables:
- `pr_notification_events`: event id, workspace, event_type, entity_type/id, severity, payload, dedupe_key, grouping_key, occurred_at, expires_at.
- `pr_notification_deliveries`: event, user, channel, status, attempts, provider ref, idempotency key, retry time, sent/delivered/failed times, failure class.
- `pr_notification_preferences`: workspace/user/category, in_app, email_mode, push_mode, digest_mode, quiet_hours, timezone.
- `pr_push_subscriptions`: user/device, encrypted endpoint/keys, created/last_seen/revoked.

Enforce tenant isolation/RLS and uniqueness for `(event_id,user_id,channel)`.

Use a durable Postgres-native queue where available; avoid introducing Redis/Kafka solely for notifications.
Retry transient failures with bounded exponential backoff and dead-letter/terminal states.
Email/push failure must never roll back authoritative domain work.## 17. Professional HTML email system
Keep a plain-text fallback, but user-facing email should be professionally designed HTML.

Create reusable components such as:
- EmailShell
- Preheader
- BrandHeader
- ContextLabel
- Headline
- PrimaryCard
- MetricsRow
- StatusPill
- PrimaryCTA
- SecondaryAction
- Footer / notification settings / privacy

Required templates:
- weekly content ready
- approval required
- publish failed
- publish uncertain
- reconnect channel
- automation failed
- weekly performance report
- opportunity detected
- security alert
- trial/payment/subscription lifecycle

Requirements:
- responsive;
- accessible semantic HTML;
- strong text contrast;
- dark-mode tolerant;
- localized subject/preheader/body;
- one obvious primary CTA with deep link;
- minimal private data in subject/preheader;
- HTML escaping;
- plain-text fallback;
- deterministic template versioning;
- screenshot/render tests.

Retain the current email provider if already integrated, but add provider-level idempotency, webhook verification, bounce/complaint/delivery state ingestion, and provider event reconciliation.
Implement SPF/DKIM/DMARC operational documentation and health checks for the production sender domain.

## 18. Web Push
Implement explicit opt-in browser push:
- service worker;
- `Notification.requestPermission()`;
- `PushManager.subscribe()`;
- server storage of encrypted subscription data;
- revocation/unsubscribe flow;
- minimal lock-screen payload;
- deep-link on click;
- grouping/tagging;
- expiration handling.

Do not put full draft text, private messages, sensitive analytics, or secret data in push payloads.
If a native app is added later, add APNs/FCM transport adapters behind the same NotificationService contract.## 19. Product UX
Avoid feature bloat. Organize around jobs:
- Home: “What needs my attention?” + next major task.
- Rafii panel: natural task-oriented conversation.
- Weekly-ready experience: one review surface for next week’s plan.
- Queue: approval/problem states, not generic AI outputs.
- Notification center: actionable items with clear state and deep links.
- Personalization controls: inspect, accept, edit, disable, or reset learned preferences.
- “Why Rafii suggested this”: show evidence, source scope, and whether it is explicit preference vs inferred pattern vs performance hypothesis.
- Skill transparency: optional/debug-level, not a wall of internal skill names for ordinary users.
- Keep one conversation/task model across text, voice, images, and notifications.

## 20. APIs and jobs
Likely endpoints, adapted to existing patterns:
- notification preferences CRUD;
- push subscribe/unsubscribe;
- notification center list/read/action;
- provider webhook for email delivery state;
- Weekly Operator recipe CRUD;
- generate/review weekly plan;
- source intake and source-to-campaign;
- research/watchlist/opportunity;
- user overlay/preferences inspect/disable;
- performance hypotheses list/accept/reject;
- skill registry diagnostics in admin/dev only.

Background jobs:
- notification delivery worker;
- notification digest builder;
- Weekly Operator planner;
- learning sweep;
- performance observation;
- watchlist/listening fetchers where supported;
- retry/reconciliation jobs.

All jobs require idempotency keys, bounded leases, retry policies, audit records, and correlation ids.## 21. Security, privacy, and consent
Preserve and extend:
- tenant isolation on every data/tool path;
- server-held credentials;
- no raw provider secrets in prompts or logs;
- proposal digest and permission re-check on apply;
- prompt-injection boundaries for web/social/uploaded/image text;
- cloud-memory/egress consent;
- rights/provenance for assets;
- notification payload minimization;
- encrypted push subscription secrets;
- webhook signature verification and replay defense;
- retention/deletion behavior for notifications, evidence, overlays, and research artifacts;
- no cross-user or cross-workspace learning;
- no performance inference converted into sensitive personal attributes.

User-specific skill evolution must be reversible and auditable.

## 22. Observability
One trace/correlation id should link:
- user request or scheduled trigger;
- capability/skill selection;
- Manager/specialist runs;
- tool calls;
- research evidence;
- proposal/HITL;
- mutations and verification reads;
- notification event/delivery;
- publishing receipts;
- analytics/learning signals;
- usage/cost.

Record skill versions/hashes, tool versions, model routes, latency, retries, guardrail trips, notification outcomes, and final product state.
Never log secrets or full sensitive notification payloads unnecessarily.## 23. Product/growth instrumentation
Track:
- time_to_first_approved_post
- weekly_operator_enabled
- weekly_plan_reviewed
- draft_approval_rate
- median_edit_distance
- prepared_to_published_rate
- research_to_campaign_rate
- notification_open_rate
- notification_click_rate
- notification_to_action_rate
- notification_mute/unsubscribe_rate
- weekly_return_rate
- automation retention
- trial_to_paid
- 30/60/90-day paid retention
- feature/cohort attribution

Useful north-star candidate:
“Weekly accepted/published artifacts per active workspace with low edit distance.”

A/B test at minimum:
A: “AI social media manager — generate better posts.”
B: “Rafii is your AI social coworker — it prepares next week, you review what matters.”

Do not optimize for raw generation count.

## 24. Implementation phases
### WP0 — Discovery and architecture lock
Audit actual repo, worktrees, migrations, skills, Humanizer, Agent Reach, notification/email code, current Agent Runtime v2. Produce a migration/capability ledger. No product behavior changes.

### WP1 — Capability/Skill Registry
Implement registry, manifests, compiler, runtime trace metadata, CI orphan-skill enforcement, James-to-Rafii migration tooling.

### WP2 — Notification Core
Implement notification events, planner, preferences, delivery ledger, queue/worker, in-app center, dedupe/idempotency, retries, quiet hours/digests.

### WP3 — Email + Push
Professional HTML templates, provider idempotency/webhooks, deliverability state, web push subscription/service worker/deep links.

### WP4 — Adaptive Skill Overlays
Humanizer integration, expanded learning signals, explicit/inferred preferences, confidence/evidence/decay, inspect/disable/reset UX.

### WP5 — Weekly Social Operator
Recipes, WeekPlan, generation/quality/review state machine, notifications, review UI, approval/scheduling integration.

### WP6 — Source-to-Campaign + Research Broker
Source normalization, FactPack, CanonicalBrief, provider abstraction, provenance ledger, research safety.

### WP7 — Creative Agent
Vision critique, generation/editing, variants, carousel/thumbnail workflows, asset lineage, alt text.

### WP8 — Performance Learning
Comparable cohorts, hypotheses, experiments, weekly report, evidence UI.

### WP9 — Listening + Engagement
Watchlists/opportunities, supported inbox normalization, triage, reply drafting, approvals.

### WP10 — Agent Runtime convergence
Bind Manager/specialists to registry/tools/policies, unify text/voice/image/task state, preserve fallback.

### WP11 — Growth experiments and rollout
Feature flags, cohorts, A/B instrumentation, activation/retention dashboards.## 25. Verification requirements
Do not weaken existing tests.

Required:
- Python unit tests;
- full PostgreSQL integration suite;
- schema/RLS tests;
- skill registry/manifest/hash tests;
- no-James-leakage fixtures;
- prompt-injection research tests;
- user-overlay isolation/reversibility tests;
- Humanizer meaning-preservation tests;
- notification planner, dedupe, quiet-hours, digest tests;
- retry/fault-injection: crash after claim, timeout, duplicate delivery, lost provider response, webhook replay;
- HTML email render/snapshot tests and links;
- push subscribe/unsubscribe/revocation tests;
- Chromium + WebKit browser QA;
- accessibility;
- site-agent scenarios/regressions;
- Agent Runtime evals;
- multilingual English/Cantonese/Mandarin/code-switching;
- voice/image cross-modal tests;
- performance/load tests;
- secret scan;
- production build.

Live-provider checks must be behind explicit opt-in credentials and budget guards. Do not perform real social posting, email blast, production migration, paid model/image call, push to real customers, deployment, merge, or production payment without explicit owner authorization.

## 26. Definition of done
The project is complete only when:
- every default skill is classified, versioned, hashed, consumed, and tested;
- no James-specific content can leak into another user;
- runtime traces show exactly which skills/tools/policies/user overlays influenced a run;
- security/approval remains deterministic;
- user preferences evolve without mutating global skills;
- performance creates hypotheses, not identity facts;
- Weekly Operator can prepare a full reviewable week end-to-end;
- Source-to-Campaign works through a canonical evidence-backed brief;
- notifications are event-driven, deduplicated, preference-aware, and actionable;
- professional HTML email and web push are working with safe fallback;
- all mutations are verified before success is claimed;
- research provenance and prompt-injection protections hold;
- notification and learning systems are auditable and reversible;
- tests/build/browser/security gates pass;
- product metrics can actually test the subscription/retention hypotheses.

## 27. Key research references
Primary engineering references used for this design:
- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- OpenAI Agents SDK HITL: https://openai.github.io/openai-agents-python/human_in_the_loop/
- OpenAI Agents SDK sessions: https://openai.github.io/openai-agents-python/sessions/
- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- MCP tools specification: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- Supabase Queues: https://supabase.com/docs/guides/queues
- Supabase Cron: https://supabase.com/docs/guides/cron
- Resend idempotency: https://resend.com/docs/dashboard/emails/idempotency-keys
- Resend webhooks: https://resend.com/docs/dashboard/webhooks/introduction
- W3C Push API: https://www.w3.org/TR/push-api/
- Notifications API: https://notifications.spec.whatwg.org/
- React Email design/component reference: https://react.email/docs/introduction

Competitive/product evidence should continue to be treated as directional evidence, not a guarantee of conversion. Validate Rafii with real cohort data.