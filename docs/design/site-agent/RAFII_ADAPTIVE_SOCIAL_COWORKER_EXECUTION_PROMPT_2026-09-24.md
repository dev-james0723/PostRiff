# Rafii Adaptive Social Coworker — Coding Agent Execution Prompt

You are the implementation agent for the Rafii Adaptive Social Coworker upgrade.

Work in:
`/Users/ouxianxing/Documents/James-Au-Studio-site-agent`

Primary engineering specification:
`docs/design/site-agent/RAFII_ADAPTIVE_SOCIAL_COWORKER_ENGINEERING_SPEC_2026-09-24.md`

Existing architecture that must be preserved and extended:
- `docs/design/site-agent/RAFII_MULTIMODAL_AGENT_RUNTIME_ENGINEERING_SPEC_2026-09-24.md`
- `docs/design/site-agent/README.md`
- `docs/design/site-agent/verification-matrix.md`
- `docs/design/site-agent/agent-runtime/ARCHITECTURE_LOCK.md`

Your job is to execute the specification, not merely review it or produce another plan.

## Operating rules
1. Read all governing files above in full before editing.
2. Read repository `AGENTS.md`, `CLAUDE.md`, and relevant nested instructions.
3. Inspect git status, branch, worktrees, origin, concurrent sessions, migrations, and uncommitted changes before touching shared files.
4. Protect concurrent work. Use a dedicated worktree if appropriate.
5. Do not rewrite the existing site-agent or Agent Runtime v2 architecture unless repository evidence proves a smaller compatible change is impossible.
6. Preserve tenant isolation, permissions, proposal/HITL behavior, usage ledger, audit, publishing reconciliation, and post-mutation verification.
7. Do not turn safety/approval/billing policies into optional prompt instructions.
8. Do not globalize James-specific identity, projects, preferences, tone, or visual style.
9. Do not claim a social platform is supported merely because a skill/adapter file exists.
10. Do not deploy, push, merge, perform production migrations, send real customer emails/pushes, publish real posts, or spend real money without explicit owner authorization.

Use Superpowers-style engineering discipline where available: discover first, make the smallest coherent plan, implement incrementally, add tests before/with behavior, debug from evidence, and verify every claimed result.## Required execution order

### WP0 — Repository discovery and architecture lock
Before code changes:
- inventory current `james-au-*`, `postriff-*`, Humanizer, Agent Reach/research, graphics, publishing, learning, analytics, notification/email, and Agent Runtime v2 code;
- identify duplicates, gaps, obsolete files, active runtime consumers, and unsafe James-specific material;
- inspect notification/email schemas and current migrations;
- inspect current live feature flags and worker/cron behavior;
- inspect concurrent worktrees and changed shared files.

Create:
`docs/design/site-agent/adaptive-social-coworker/ARCHITECTURE_LOCK.md`

It must document actual repo facts, deviations from the spec, exact files to touch, migration strategy, and conflict risks.

Do not proceed on assumptions contradicted by repository evidence.

### WP1 — Capability and Skill Registry
Implement the product-owned capability registry, skill manifests, compiler, runtime-consumer mapping, and CI enforcement.

Required outcomes:
- every default skill classified as knowledge/workflow/tool/policy/evaluator;
- every skill versioned and hashed;
- every tool typed and registered;
- every deterministic policy bound to code;
- no orphan skill files;
- run trace records selected skill ids/versions/hashes;
- migration ledger maps old James skills to generic Rafii capabilities.

Create a machine-readable registry and validation command/test.

### WP2 — Notification Core
Replace scattered direct feature-level notification sends with an event-driven notification layer.

Implement:
- notification event taxonomy;
- planner/policy;
- recipient and preference resolution;
- event/delivery/preferences/push-subscription persistence;
- dedupe/idempotency;
- quiet hours/timezone;
- immediate vs digest behavior;
- bounded retry and terminal/dead-letter states;
- in-app notification center API.

Preserve authoritative domain state even if notification delivery fails.### WP3 — Professional HTML Email and Web Push
Refactor email into reusable professional HTML templates with plain-text fallback.

Minimum templates:
- weekly content ready;
- approval required;
- publish failed;
- publish uncertain;
- reconnect channel;
- automation failed;
- weekly performance summary;
- opportunity detected;
- security alert;
- billing/trial/payment lifecycle.

Requirements:
- responsive and accessible;
- dark-mode tolerant;
- localized subject/preheader/body;
- safe HTML escaping;
- one primary CTA/deep link;
- template version recorded;
- provider idempotency;
- webhook signature/replay verification;
- bounce/complaint/delivery state reconciliation;
- production sender-domain deliverability runbook.

Implement web push with explicit opt-in, service worker, subscribe/unsubscribe/revocation, minimal payloads, grouping, and deep-link click behavior.

### WP4 — Adaptive Skill Overlays
Generalize Humanizer and James methodology into safe default Rafii skills while preserving global immutability.

Implement:
- user voice/brand/platform overlays;
- explicit vs inferred preference semantics;
- evidence ids and counter-evidence;
- confidence;
- scope by platform/language/format/audience where applicable;
- expiry/decay;
- revision history and supersession;
- inspect/disable/reset/export controls;
- expanded learning signals for accepted, edited, rejected, ignored variants and creative selections.

Do not let a user or model directly rewrite global skill Markdown.

Performance observations must create hypotheses/experiments, not silently alter voice.

### WP5 — Weekly Social Operator
Implement the durable weekly recipe and end-to-end workflow:
goal/cadence/content mix/timezone/planning day -> research/context -> WeekPlan -> drafts/assets -> quality checks -> ready_for_review -> notification -> review/approval -> schedule/publish -> verify -> measure -> learn.

Integrate with existing campaign, queue, approval, automation, usage, and publishing services rather than duplicating them.

Emit one deduplicated `campaign.week_ready` event when the week becomes ready for review.

Build the task-oriented review UI. Do not make this another generic “generate” page.### WP6 — Source-to-Campaign and Research Broker
Implement normalized `SourceArtifact`, `FactPack`, `CanonicalBrief`, angle candidates, channel drafts, and creative briefs.

Implement ResearchProvider abstraction for public web, reader, official platform APIs, approved MCP/connectors, and optional local Agent Reach.

Rules:
- local authenticated desktop coverage must never masquerade as hosted coverage;
- search snippets are not verified facts;
- contradictory evidence survives;
- source provenance/freshness/scope is preserved;
- retrieved prompt-injection text remains untrusted data;
- research egress honors existing consent/policy.

### WP7 — Creative Agent
Implement/bind vision critique, image generation/editing, variants, carousel/thumbnail concepts, resizing/adaptation, brand-fit critique, alt text, and non-destructive asset lineage.

Reuse the existing asset and usage/approval architecture.

### WP8 — Performance Learning
Implement comparable-cohort performance observations, strategy hypotheses, experiments, and weekly performance summaries.

Preserve:
- unavailable != zero;
- correlation != causation;
- insufficient sample size remains insufficient;
- one viral post does not become a global rule.

Expose “why Rafii suggested this” with evidence and confidence.

### WP9 — Listening and Engagement
Implement lawful/available watchlists/opportunity detection and supported inbox/comment/mention/review/DM-like normalization.

Triage and draft responses. External replies remain subject to existing permissions/approval.

Do not manufacture urgency. Opportunity notification requires deterministic thresholds, freshness, non-duplication, available sources, and user preference.

### WP10 — Agent Runtime convergence
Bind the new registry, specialists, tools, overlays, notifications, and task state into the existing Agent Runtime v2.

Prefer:
- Rafii Manager;
- Research Specialist;
- Content Specialist;
- Creative Specialist;
- Analysis Specialist.

Keep publishing, notifications, policy, billing, memory, proposal/HITL, and authoritative state services deterministic.

Preserve one conversation/task model across text, voice, images, notifications, and approval.

### WP11 — Growth instrumentation and rollout
Instrument the product hypotheses and feature cohorts before calling the release complete.

Track at minimum:
- time_to_first_approved_post;
- weekly_operator_enabled;
- weekly_plan_reviewed;
- draft_approval_rate;
- median_edit_distance;
- prepared_to_published_rate;
- research_to_campaign_rate;
- notification open/click/action/mute/unsubscribe;
- weekly return;
- automation retention;
- trial_to_paid;
- 30/60/90-day paid retention.

Add A/B infrastructure for positioning/workflow experiments without hard-coding a claim that the treatment must win.## Acceptance requirements

### Skill/platform integrity
- No James-specific private identity/preferences are present in default user prompts.
- Every default skill has kind, version, hash, consumer, tests.
- No orphan skill passes CI.
- Policies cannot be overridden by user overlays.
- Effective run metadata explains which global skills, user overlays, strategy hypotheses, tools, and model route were used.

### Notification integrity
- Same domain event cannot create duplicate user/channel deliveries after retries.
- Quiet hours/digests work across time zones and DST.
- Critical security/billing/publish-failure events follow deterministic policy.
- Successful routine events do not spam users.
- Email/push failures never roll back campaign/publishing/domain state.
- Unsubscribe/revocation is respected.
- Push payloads contain minimal safe information.
- Email templates have HTML and plain-text versions and valid deep links.

### Adaptive learning integrity
- Explicit user preferences outrank inferred ones within policy.
- Inferred preferences retain evidence and can expire/be disabled.
- LinkedIn preference does not blindly affect Instagram.
- Performance does not silently rewrite voice.
- Humanizer preserves facts/meaning and invents no personal details.
- Cross-user/workspace learning leakage is impossible.

### Agent/workflow integrity
- Weekly Operator completes safe independent steps and stops only at real approval/input gates.
- Source-to-Campaign preserves evidence through the canonical brief.
- Research source failures cannot be reported as successful retrieval.
- Every mutation is re-read before success is reported.
- prepared/scheduled/sent/provider-accepted/verified remain distinct states.
- Agent Runtime can fall back to the existing verified site-agent path when a new feature is disabled/unavailable.## Verification gates
Run and report exact commands/results for:
- full Python unit suite;
- full PostgreSQL integration suite;
- migrations/RLS;
- site-agent scenario matrix;
- new capability/skill registry tests;
- no-James-leakage tests;
- Humanizer meaning-preservation tests;
- research prompt-injection/provenance tests;
- notification planner/dedupe/quiet-hours/digest tests;
- email renderer/template/link/accessibility tests;
- email provider webhook/idempotency mocks;
- push subscribe/unsubscribe/revocation/service-worker browser tests;
- retry/fault-injection tests;
- Agent Runtime deterministic evals;
- English/Cantonese/Mandarin/code-switching;
- image/vision tests;
- voice/text cross-modal tests where applicable;
- TypeScript/typecheck;
- lint;
- production build;
- Chromium browser QA;
- WebKit browser QA;
- accessibility;
- secret scan;
- performance/load tests.

For live provider checks:
- require explicit opt-in;
- cap spend;
- use owner-approved test accounts only;
- clearly separate mocked/local verification from live verification.

Do not weaken tests to make them green.

## Feature flags and rollback
Introduce/extend flags so incomplete paths can be independently disabled, e.g.:
- `RAFII_SKILL_REGISTRY_V2_ENABLED`
- `RAFII_NOTIFICATIONS_V2_ENABLED`
- `RAFII_WEB_PUSH_ENABLED`
- `RAFII_WEEKLY_OPERATOR_ENABLED`
- `RAFII_RESEARCH_BROKER_ENABLED`
- `RAFII_ADAPTIVE_SKILLS_ENABLED`
- `RAFII_PERFORMANCE_LEARNING_ENABLED`
- `RAFII_LISTENING_ENABLED`

Migrations must be forward-safe and rollback/documentation must be provided. Avoid permanent parallel ledgers when a compatibility migration/view is enough.## Final deliverables
Create/update:
1. architecture-lock note;
2. implementation/migration ledger;
3. skill/capability registry;
4. James-to-Rafii migration audit;
5. notification event catalogue;
6. email template catalogue/previews;
7. schema/migrations;
8. source/research provenance contract;
9. adaptive learning contract;
10. feature-flag/rollout plan;
11. machine-readable verification results;
12. updated docs and handoff.

Final report must state:
- what is implemented;
- what is only locally verified;
- what was live verified;
- migrations created;
- exact test counts/results;
- new skill registry coverage and orphan count;
- notification template/event coverage;
- push/email provider status;
- remaining platform limitations;
- remaining PARTIAL items and exact reasons;
- concurrency/conflict risks;
- whether the branch is ready to merge;
- whether it is ready to deploy separately;
- explicit next action.

Do not report “done” because the code compiles. Completion requires the acceptance criteria and verification gates above.

Begin now with WP0 repository discovery and the architecture-lock note, then continue through the work packages without stopping for routine implementation choices. Stop only for a genuine external credential/access blocker, irreversible/destructive action, owner-only production authorization, or a real concurrent-work conflict that risks corrupting another session’s work.