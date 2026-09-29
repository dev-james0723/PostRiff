# Rafii Growth Loop — Coding Agent Handoff
Date: 2026-09-26

You are the implementation agent for the approved Rafii Growth Loop.

## Read first

1. Read:
   - docs/design/rafii-growth-loop/RAFII_GROWTH_LOOP_ENGINEERING_SPEC_2026-09-26.md
   - AGENTS.md / CLAUDE.md instructions that apply to this repo/worktree
2. Confirm the real repo root, branch, HEAD and git status before touching files.
3. Do not assume this handoff's recorded HEAD is still current.

## Critical concurrency warning

At handoff preparation, the verified worktree was:

- /Users/ouxianxing/Documents/James-Au-Studio-growth
- branch: claude/growth-phase0
- HEAD: 677d49c

It already contained unrelated untracked work:

- docs/design/growth-phase0/
- src/postriff_phase2/growth/
- tests/test_growth_calibration.py
- tests/test_growth_jev.py
- tests/test_growth_judgments.py
- tests/test_growth_questions.py
- tests/test_growth_router.py

Treat those files as active work from another session.

DO NOT:
- delete them
- reset them
- stash them
- overwrite them
- rename them
- mass-format them
- "clean up" the worktree

Inspect and reconcile them first.

## Objective for this implementation pass

Implement the P0 closed loop from the engineering spec:

1. Slice 0: reconciliation / capability ledger
2. Slice 1: Growth Goal / Outcome OS
3. Slice 2: Growth Lab
4. Slice 3: Weekly Proof of Value

P1 features remain approved roadmap items but are not required to complete this implementation pass unless a P1 primitive is already needed to avoid architectural duplication.

The P0 outcome must be:

Growth Goal
→ Weekly Operator
→ review / publish
→ measured outcome
→ experiment
→ approved learning
→ next week
→ Weekly Proof of Value

## Architecture constraints

Reuse existing systems. Do not create parallel replacements for:

- Weekly Operator
- performance hypotheses
- adaptive learning / overlays
- analytics metric definitions
- NotificationService / email / push
- Queue / approval / verified publishing
- Research Broker / provenance
- Time Back
- growth/JEV/Radar primitives already present in the worktree

JEV / model judgments can provide evidence or preflight judgments. They are not ground truth and must not become an unexplained 0–100 "viral probability."

Keep:
- policy deterministic
- approval deterministic
- publishing deterministic
- billing deterministic
- tenancy/RLS deterministic
- all strategy learning inspectable and reversible

Performance strategy must never silently mutate voice identity.

## Slice 0: mandatory reconciliation

Before product code:

1. Inspect the untracked growth-phase0 and growth/JEV files.
2. Inspect existing:
   - src/postriff_phase2/coworker/performance.py
   - src/postriff_phase2/coworker/weekly_operator.py
   - src/postriff_phase2/coworker/growth.py
   - adaptive learning / overlays
   - analytics UI/API
   - notifications
   - Time Back implementation/worktree history as available
3. Produce:
   - docs/design/rafii-growth-loop/CAPABILITY_LEDGER.md

For each Growth Loop requirement mark:
- already implemented
- partially implemented
- reusable primitive
- missing
- conflicting/in-progress

Do not begin a duplicate system where a reusable primitive exists.

## Migration rule

Before adding any migration:

- inspect migration numbers in this worktree
- inspect relevant local branches/worktrees
- inspect origin refs
- check active concurrent feature branches if available

Do not assume any remembered migration number is free.

If a new migration is needed, choose a verified non-colliding number and document the audit.

## Slice 1: Growth Goal

Implement a workspace-scoped GrowthGoal with truthful metric coverage.

Requirements:
- one active primary goal
- optional secondary indicators
- baseline / target / target date
- account/platform scope
- provider metric definition
- current value + timestamp
- explicit coverage/confidence/source
- null, not fake data, when metrics are unavailable
- auditability and tenant isolation

Add a compact Home Growth surface.

Home must answer:
- the goal
- baseline → current → target
- coverage
- what Rafii is doing this week
- the next user action if blocked

Weekly Operator may use the active goal as planning context but may not bypass existing review or user constraints.

## Slice 2: Growth Lab

Extend existing performance hypotheses into a user-approved experiment lifecycle.

Required lifecycle:
candidate
→ proposed
→ accepted
→ preparing
→ running
→ measuring
→ complete

Also support:
dismissed / rejected / insufficient_data / invalidated / expired / cancelled.

Requirements:
- like-for-like cohort controls
- explicit minimum sample
- no early winner claim
- robust statistic
- evidence and counter-evidence
- causal=false
- limitations shown
- user action required before a result influences future planning

Growth Lab should live primarily under Analytics, with only contextually relevant experiment summaries elsewhere.

If current growth/JEV work has Post Doctor / creator genome / Radar or related judgment primitives, integrate them as evidence/candidate-hypothesis inputs rather than creating another engine.

## Slice 3: Weekly Proof of Value

Generate a weekly value recap from authoritative data only.

Eligible:
- prepared posts
- approved posts
- verified published posts
- campaigns
- Time Back
- meaningful performance changes
- experiments
- engagement handled
- opportunities acted on
- next week prepared
- Growth Goal progress when actually covered

Do not count:
- unused drafts
- failed publishes
- unverified outcomes
- suggestions that were never acted on

Add a monthly "Rafii is getting better" summary only where sufficient history exists.

Reuse NotificationService and existing digest/email infrastructure.

## UX rule

Do not add a top-level nav item for every new capability.

Preferred:
- Home: Growth + attention + week + proof snapshot
- Weekly: plan + opportunities + relevant experiments
- Analytics: goal progress + Growth Lab + proof history + Time Back
- Inbox: existing engagement behavior
- Personalization: accepted strategy hypotheses separate from voice/brand identity

## Billing / packaging

Do not activate prices, change live billing terms, or charge users.

It is acceptable to prepare copy architecture so the paid value proposition can move from:
"AI writing in your voice"

to:
"Rafii runs your social growth loop every week. You review what matters. It learns what works."

Do not make "100 AI writing batches" the primary story if the UI copy touched by this work can truthfully explain recurring outcomes instead.

## Tests and verification

Do not weaken existing tests.

At minimum run and record:

- targeted Python tests for new services
- PostgreSQL integration tests for new state/tables/RLS
- growth/JEV tests that existed before your work
- Weekly Operator regressions
- adaptive learning regressions
- analytics regressions
- Time Back regressions if integrated
- notification tests if delivery/templates change
- web node tests
- TypeScript typecheck
- lint
- Chromium browser flow
- WebKit browser flow
- accessibility checks
- production build
- migration uniqueness audit

Add failure-path tests for:
- unavailable metric coverage
- insufficient experiment samples
- contradictory/counter evidence
- cross-workspace access
- duplicate/idempotent writes
- provider/notification failure
- missing Time Back data

## Product instrumentation

Implement or reuse events for:

- growth_goal.created
- growth_experiment.proposed
- growth_experiment.started
- growth_experiment.completed
- growth_experiment.applied
- growth_experiment.dismissed
- weekly_proof.generated
- weekly_proof.opened
- weekly_proof.acted
- monthly_proof.generated
- monthly_proof.opened

Do not put private content bodies into product-event payloads.

## Definition of done for this pass

P0 is done when:

1. Growth Goal works end-to-end with honest coverage.
2. Home makes goal progress understandable.
3. Weekly Operator can consume goal context safely.
4. Existing performance hypotheses can become user-approved experiments.
5. Experiments can reach a measured, evidence-backed result.
6. Strategy only changes after explicit user action.
7. Weekly Proof of Value is derived from authoritative state.
8. Existing Time Back semantics remain intact.
9. New state is workspace-isolated and RLS tested.
10. No duplicate JEV/growth engine exists.
11. No unrelated concurrent work is lost.
12. Browser/accessibility/build gates are green.

## Release boundary

For this task:
- implementation and local verification are allowed when the owner explicitly starts this handoff in a coding session
- do NOT merge
- do NOT push
- do NOT deploy
- do NOT run production migrations
- do NOT activate billing
- do NOT make real social posts

Stop after implementation + verified local evidence and report:
- files changed
- architecture decisions
- tests run/results
- unresolved blockers
- migration chosen and audit, if any
- what remains for P1
