# Rafii Growth Loop Engineering Spec
Date: 2026-09-26
Status: APPROVED FOR ENGINEERING HANDOFF
Project: Rafii / PostRiff
Verified target worktree: /Users/ouxianxing/Documents/James-Au-Studio-growth
Verified branch at handoff preparation: claude/growth-phase0
Verified baseline HEAD: 677d49c

## 0. Decision

Rafii's next product phase is not "more AI features."

The product should turn its existing capabilities into one durable subscription loop:

Growth Goal
→ Weekly Operator
→ Create / adapt
→ Review
→ Publish
→ Measure
→ Experiment
→ Learn
→ Prepare next week
→ Prove value

The customer-facing paid value proposition should move away from:

> AI writing in your voice.

Toward:

> Rafii runs your social growth loop every week. You review what matters. It learns what works.

This is a product-integration program. Reuse existing primitives before adding new systems.

## 1. Current building blocks to preserve and reuse

The repo already contains production or near-production primitives for:

- Weekly Social Operator
- One Source → Full Campaign
- Social Listening / Opportunities
- Engagement Copilot / Inbox reply drafting
- Adaptive preference learning and memory overlays
- Performance hypotheses
- Analytics
- Notification core, email, push, digests
- "What needs my attention?"
- Automations
- Queue / approvals / scheduling / verified publishing receipts
- Brand and voice memory
- Time Back
- Growth instrumentation
- Research Broker
- FactPack / source provenance
- Creative planning
- Agent Runtime / site-agent work

Do not replace these with parallel implementations.

## 2. Collision / concurrency rule

At handoff time this worktree contains unrelated untracked work:

- docs/design/growth-phase0/
- src/postriff_phase2/growth/
- tests/test_growth_calibration.py
- tests/test_growth_jev.py
- tests/test_growth_judgments.py
- tests/test_growth_questions.py
- tests/test_growth_router.py

Treat all of this as active work owned by another session until inspected.

Rules:

1. Never delete, reset, rename, overwrite, stash or mass-format those files.
2. Inspect and reconcile before adding any overlapping growth/JEV/Radar code.
3. Prefer adapters into existing growth intelligence over a second scoring system.
4. If current work conflicts with this spec, preserve both and document the conflict before deciding.
5. Do not claim a migration number from memory. Re-audit migration numbers across relevant local and remote refs immediately before adding a migration.

Known numbering context is potentially contested by concurrent branches, therefore migration assignment must be derived from the live repo state, not this document.

## 3. Product north star

Primary candidate:

> Weekly accepted or published artifacts per active workspace with low edit distance, tied to a user-declared growth goal.

Supporting retention signals:

- weekly_return_rate
- weekly_operator_enabled
- weekly_plan_reviewed
- prepared_to_published_rate
- draft_approval_rate
- median_edit_distance
- experiment_completion_rate
- goal_progress_coverage
- weekly_proof_open_rate
- notification_to_action_rate
- automation_retention
- trial_to_paid
- paid_retention_30d / 60d / 90d
- Time Back

Do not optimize for raw generation count.

## 4. P0-A: Growth Goal / Outcome OS

### 4.1 User job

A workspace should be able to answer:

1. What outcome am I trying to improve?
2. What is the baseline?
3. What is the target?
4. What is Rafii doing this week to help?
5. What changed?
6. What needs my attention?

### 4.2 Supported goal types

Initial types:

- follower_growth
- views_or_reach
- engagement
- leads
- newsletter_subscribers
- sales_or_conversions
- consistency
- authority

Use only metrics that can be truthfully supported by available platform/account data.

A workspace may select one primary goal and optional secondary indicators.

### 4.3 Growth goal record

Create a workspace-scoped, auditable GrowthGoal entity with at minimum:

- id
- workspace_id
- name
- goal_type
- primary_metric
- target_value
- baseline_value
- baseline_at
- target_at
- platform/account scope
- provider_metric_definition
- current_value
- current_value_at
- coverage
- confidence
- source/provider
- created_by
- created_at
- updated_at
- status: active | paused | achieved | archived

If exact progress cannot be read, current_value must be null and coverage must explain why.

Never substitute a modeled estimate for a provider-reported follower/view/lead figure without labeling it as an estimate.

### 4.4 Home integration

Home should show one compact "Growth" surface before generic analytics.

Required states:

- no goal: one CTA to set a goal
- goal configured + data available
- goal configured + partial data
- goal configured + unavailable provider metric
- achieved
- paused

The surface should show:

- goal
- target date
- baseline → current → target
- change in the current reporting window
- one sentence explaining data coverage
- Rafii's current weekly plan contribution
- next user action when one is required

Do not create a new dashboard maze.

### 4.5 Goal-aware planning

Weekly Operator may read the active GrowthGoal as strategy context.

It may use it to:

- choose among approved content goals
- prioritize experiments
- prioritize source/campaign opportunities
- select which metric appears in recaps

It must not:

- invent platform access
- bypass user-configured content constraints
- publish automatically
- turn a weak correlation into a strategy rule

## 5. P0-B: Growth Lab

Growth Lab turns the existing performance-hypothesis layer into an inspectable experiment loop.

### 5.1 State machine

candidate
→ proposed
→ accepted
→ preparing
→ running
→ measuring
→ complete

Terminal / alternate states:

- dismissed
- rejected
- insufficient_data
- invalidated
- expired
- cancelled

### 5.2 Experiment definition

Each experiment records:

- hypothesis id / revision
- workspace
- platform
- account
- language
- content type
- metric definition
- control factor
- variant factor
- eligibility rules
- sample requirement
- start/end window
- source posts
- generated variants
- publishing job ids
- observations
- confounders / limitations
- result
- evidence ids
- status
- owner decision

### 5.3 Minimum evidence policy

Continue the existing conservative hypothesis philosophy.

Requirements:

- compare like-for-like cohorts
- use medians or another robust statistic where appropriate
- minimum sample before a result
- no early "winner" label
- no causal language
- show missing or asymmetric data
- preserve counter-evidence

Example acceptable copy:

> Across 12 comparable posts, the short-opening variant had a 24% higher median comment rate. This is evidence for this account, not proof that the opening caused the difference.

### 5.4 User actions

For a candidate:

- Run experiment
- Dismiss
- Not now

For an active experiment:

- See design
- See posts
- Stop experiment

For a result:

- Use as a planning preference
- Run another test
- Keep as hypothesis only
- Reject result

"Use as planning preference" should create a strategy-level instruction/hypothesis, not silently mutate voice identity.

### 5.5 JEV / Radar integration

Do not make a generic "viral score 0–100" the central product.

If current growth/JEV work provides judgments, similarity search, creator genome, post doctor or Radar signals, expose them as:

- preflight evidence
- candidate hypotheses
- competitor/context evidence
- experiment inputs

They do not override the user's own measured performance.

JEV or model judgments are not ground truth and must not be displayed as calibrated probabilities unless a separate calibration contract exists.

## 6. P0-C: Weekly Proof of Value

Every week Rafii should make the subscription value visible.

### 6.1 Weekly recap

Build from authoritative events only.

Eligible modules:

- posts prepared
- posts approved
- posts verified published
- campaigns created
- Time Back, with existing estimate/personalized/measured confidence
- meaningful performance changes
- experiments completed / still running
- engagement items handled
- opportunities acted on
- next week's work already prepared
- goal progress when coverage exists

Do not count:

- failed publishing
- unused drafts
- suggestions that were never acted on
- unverified external outcomes

### 6.2 Monthly "Rafii is getting better" recap

Show longitudinal learning, including:

- median edit distance trend
- approval rate trend
- accepted preference learnings
- recurring workflows completed
- experiments run
- hypotheses supported / rejected
- active goal progress
- Time Back
- publishing consistency

If there is insufficient history, say so rather than fabricating a trend.

### 6.3 Delivery

Reuse NotificationService.

Surfaces:

- in-app
- email
- push deep-link where enabled

Add/extend event types only if required. Prefer existing digest and analytics event infrastructure.

Default: weekly digest, non-noisy, user configurable.

## 7. P1-A: Evergreen Compounder

### 7.1 Purpose

Turn historically successful content into a compounding asset library.

### 7.2 Eligibility

A post may become an evergreen candidate when:

- publishing is verified
- metrics are available
- its performance is meaningfully above the account-specific comparable baseline
- sufficient time has passed
- it is not dependent on expired news / dates / offers
- its facts still have valid provenance
- it is not a one-post anomaly without supporting evidence

### 7.3 Actions

Possible derivatives:

- refreshed original-platform post
- cross-platform rewrite
- carousel
- short-video outline / script
- thread
- newsletter seed
- sequel
- campaign

Every derivative must retain:

- parent lineage
- approved facts
- source references
- asset lineage
- transformation reason

## 8. P1-B: Audience Relationship Memory

Extend Inbox from message triage to continuity of relationship.

### 8.1 Contact record

Workspace scoped, conservative, non-sensitive:

- provider
- provider contact id when available
- public display name / handle
- first seen
- last seen
- interaction count
- supported interaction types
- user-authored notes
- prior reply history
- relationship tags chosen by the user or from non-sensitive deterministic categories
- potential follow-up state

Do not infer sensitive personal traits.

Do not create identity joins across platforms unless the user explicitly links them or the platform provides a reliable shared identity.

### 8.2 Useful states

Examples:

- recurring engager
- unanswered question
- potential customer inquiry
- partner / press inquiry
- prior collaborator
- follow-up requested

Keep these inspectable and editable.

### 8.3 Product behavior

Inbox may surface:

> This person has interacted 5 times in the last 30 days and previously asked about pricing.

Then offer:

- Review history
- Draft reply
- Add note
- Remind me / follow up

No automated DM/send without existing approval and permission gates.

## 9. P1-C: Competitor + Content Whitespace Radar

This feature must reuse the active growth/JEV/Radar program where possible.

### 9.1 User job

Follow a bounded set of competitors, creators, brands or topics and answer:

- What is changing?
- What content patterns are appearing?
- What questions are audiences asking?
- What is everybody covering?
- What useful angle is underserved?
- What should I consider making next?

### 9.2 Evidence

Every item must preserve:

- source
- retrieval method
- retrieved_at
- published_at when available
- platform
- author/account
- rights/usage constraints
- content hash where applicable
- evidence scope

Respect provider/API constraints and terms.

### 9.3 Whitespace output

A whitespace opportunity must contain:

- theme
- evidence set
- why it is relevant to this workspace
- saturation / repetition evidence
- missing angle or unanswered question
- freshness
- confidence
- expiry
- suggested content action

No manufactured urgency.

### 9.4 Action

One action should be able to feed the existing Source → Campaign or Ideas workflow.

Avoid a dead-end "Act on it → go somewhere else and start over" pattern.

## 10. UX architecture

Do not add six new top-level navigation items.

Preferred integration:

### Home
- Growth Goal
- What needs my attention?
- current weekly plan
- proof-of-value snapshot

### Weekly
- week plan
- opportunities / radar
- active experiments relevant to next week

### Analytics
- goal progress
- Growth Lab
- proof-of-value history
- Time Back

### Inbox
- engagement triage
- relationship continuity

### Library
- evergreen candidates
- derivatives / lineage

### Personalization
- voice
- brand
- accepted planning preferences / strategy hypotheses

## 11. Subscription packaging

Current public plan copy that sells "AI writing in your voice" undersells the product.

Do not change live price or activate billing terms without explicit commercial authorization.

Prepare copy and entitlement architecture so the paid tier can communicate:

- weekly planning
- goal-aware strategy
- performance learning
- experiments
- proof of value
- content compounding
- relationship continuity

Do not hide basic data export, safety, approvals or account control behind premium gates.

The pricing page should sell recurring outcomes, not "100 AI batches" as the hero benefit.

## 12. Instrumentation

Add product events sufficient to answer:

Activation:
- growth_goal.created
- weekly_operator.enabled
- first_week.prepared
- first_week.reviewed
- first_verified_publish

Growth Lab:
- growth_experiment.proposed
- growth_experiment.started
- growth_experiment.completed
- growth_experiment.applied
- growth_experiment.dismissed

Proof:
- weekly_proof.generated
- weekly_proof.opened
- weekly_proof.acted
- monthly_proof.generated
- monthly_proof.opened

Compounder:
- evergreen.candidate
- evergreen.accepted
- evergreen.derivative_created
- evergreen.published

Relationship:
- audience_contact.revisited
- relationship_followup.created
- relationship_followup.completed

Radar:
- radar.opportunity_detected
- radar.opportunity_opened
- radar.opportunity_to_campaign

Track events, not private message/post bodies.

## 13. Technical architecture rules

1. Keep policy, approval, billing, tenancy and publishing deterministic.
2. Agents may suggest; deterministic services own mutation and permissions.
3. No specialist receives broader scope than the current authorized Manager context.
4. Use typed schemas at every tool boundary.
5. Reuse existing provenance and FactPack types.
6. Reuse NotificationService.
7. Reuse Queue and publishing receipts.
8. Reuse preference-learning overlays. Do not write strategy findings into voice identity.
9. Reuse existing analytics metric definitions.
10. Make every new state workspace-scoped and RLS protected.
11. Every mutation must have idempotency and a verification read.
12. No cross-workspace learning.
13. No real social publishing, billing activation, paid-provider blast, production migration or deployment without explicit owner authorization.

## 14. Migration rules

Before adding SQL:

- inspect every migration in the current worktree
- inspect migration numbers present in relevant local branches / worktrees
- inspect origin refs
- check active PR branches if available
- select a number that does not collide

Do not assume 026, 030, 031 or any remembered number is free.

Prefer the smallest coherent set of migrations.

Every new table must include:

- workspace ownership
- indexes required by the main queries
- RLS
- delete/retention behavior
- timestamps
- constraints preventing impossible states

## 15. Rollout order

### Slice 0 — Reconciliation
- inspect active growth-phase0/JEV work
- map it against this spec
- produce a short capability ledger
- no behavior changes

### Slice 1 — Growth Goal
- data model
- API/service
- Home integration
- analytics progress
- tests

### Slice 2 — Growth Lab
- experiment model
- hypothesis → experiment
- experiment UI
- measurement
- strategy decision
- tests

### Slice 3 — Weekly Proof of Value
- aggregation
- weekly/monthly view
- notification/email integration
- tests

P0 is complete here.

### Slice 4 — Evergreen Compounder
### Slice 5 — Audience Relationship Memory
### Slice 6 — Competitor / Whitespace Radar integration
### Slice 7 — Packaging copy + growth experiments

P1 may stay feature-flagged until provider coverage and product evidence are sufficient.

## 16. Acceptance criteria

P0 is accepted only when:

1. A workspace can create a truthful Growth Goal.
2. Home explains progress and coverage without opening Analytics.
3. Weekly Operator can read the goal as planning context without bypassing review.
4. A supported performance hypothesis can become a user-approved experiment.
5. An experiment can reach a measured result with evidence and limitations.
6. A result can influence planning only after explicit user decision.
7. Weekly Proof of Value is generated from authoritative events.
8. Time Back preserves existing confidence labels and accounting rules.
9. Email/in-app recap deep-links to the underlying evidence.
10. All new data is tenant-isolated and RLS tested.
11. Existing approval, publishing, billing and learning tests remain green.
12. No duplicate growth/JEV engine is introduced.
13. No unrelated untracked work is lost.
14. Browser QA passes in Chromium and WebKit.
15. Accessibility checks pass.
16. Production build passes.

## 17. Verification

Minimum:

- targeted Python unit tests
- PostgreSQL integration tests
- RLS/isolation tests
- web node tests
- TypeScript typecheck
- lint
- browser flows
- accessibility
- notification render tests where copy/template changes
- production build
- regression for existing Weekly Operator
- regression for existing adaptive learning
- regression for existing analytics
- regression for Time Back if integrated
- migration uniqueness check across relevant refs

Record the exact commands and results in the implementation handoff.

## 18. Non-goals

This phase is NOT:

- a redesign of every Rafii page
- a new generic analytics product
- a generic 0–100 viral score
- autonomous publishing without review
- an ad attribution platform
- a replacement for existing Weekly Operator
- a replacement for current JEV/growth work
- a second memory system
- a second notification system
- a mass scraping system

## 19. Product principle

Rafii becomes sticky when the value grows with time:

- it knows the user's goals
- it prepares the next week
- it measures what happened
- it tests hypotheses
- it learns approved strategy
- it compounds proven content
- it remembers useful audience context
- it shows the user what value was created

The subscription moat is the accumulated closed loop, not the text generator.
