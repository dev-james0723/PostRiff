# Rafii Inbox Completion + Engagement Copilot Implementation Plan

> For coding agents: use superpowers:subagent-driven-development when available, otherwise superpowers:executing-plans. Follow TDD, preserve unrelated work, and do not implement in the dirty canonical checkout.

Goal: finish Rafii's existing social-comment Inbox as a real operational engagement loop: refresh comments, triage them, draft with the already-merged AI writer, approve exact text, send through a bounded worker when explicitly enabled, reconcile provider outcomes, and show durable receipts. Do not pretend Rafii has a unified DM Inbox yet.

Architecture: preserve pr_audience_threads, pr_reply_drafts, reply_writer, coworker/engagement.py, existing capability levels, existing notification infrastructure and the current Inbox UI. Add only the missing freshness/worker/receipt integration. Unified DM/mention storage is a later phase and is not required for Inbox v1.

Spec: docs/superpowers/specs/2026-09-28-rafii-inbox-engagement-copilot-design.md

## Verified planning snapshot

Research pass refreshed remote refs and observed:
- origin/consumer-saas = a6033925bd8c94b8f8b98efea48741fb57f110da
- local consumer-saas = 468811b73d28b4389f931519827c05d0e6c8abfb
- local checkout was 357 commits behind remote and heavily dirty
- cd3c177 and 848ab49 AI-reply commits are already ancestors of origin/consumer-saas
- production on_post_verified comment ingestion is already wired
- COMMENT_READ_PROVIDERS is still Threads-only
- send_approved exists but no production worker calls it
- production never enables reply_sender_enabled
- no audience sync endpoint/table exists
- Engagement Copilot backend exists but its rollout doc says it is currently pointless because it is not integrated with a live-refresh Inbox
- OAuth capability matrix replacement behavior is still present

Execution-time repo state wins over this snapshot.

## Global constraints

- Read AGENTS.md and CLAUDE.md first.
- Run Token Pilot lifecycle required by those files.
- Fetch origin before deciding what is missing.
- Re-check the canonical release branch and default branch.
- Never reset, clean, stash or overwrite the shared dirty checkout.
- Use superpowers:using-git-worktrees to create/reuse an isolated worktree from the current origin/consumer-saas.
- Do not cherry-pick cd3c177 or 848ab49 unless fresh graph inspection proves they disappeared from the real release branch.
- Do not build a second AI reply writer.
- Do not build a second engagement classifier.
- Do not build a second notification system.
- Do not activate live social reply sending as part of local implementation.
- Do not perform real social mutations in automated tests.
- Keep exact human approval for every outbound reply.
- Unknown provider outcome is not success and is never an automatic retry.
- Every production-code task uses RED -> GREEN -> REFACTOR.
- Re-check migration numbers across current refs immediately before adding a migration.
- Do not fill an old numeric migration gap merely because it is free; use the project's current migration convention.
- Do not modify unrelated billing, pricing, auth, phone, growth or publishing behavior.
- Do not claim unified DMs/mentions are shipped in Inbox v1.

---

## Task 0: Isolate from the stale dirty canonical checkout

Files: no product edits.

- [ ] Read AGENTS.md, CLAUDE.md, the design spec, and this plan.
- [ ] Fetch origin and record current origin/consumer-saas SHA.
- [ ] Verify whether consumer-saas is still the canonical release/default branch.
- [ ] Inspect git status and all worktrees.
- [ ] Confirm whether the three new Inbox planning docs are uncommitted in the dirty canonical checkout.
- [ ] Create a clean isolated worktree from the actual current origin/consumer-saas, for example branch codex/rafii-inbox-v1.
- [ ] Copy the design, plan and handoff docs into the isolated worktree if they are not yet present in the base commit.
- [ ] Hash/compare copied planning files.
- [ ] Inspect current migration prefixes across local and origin refs.
- [ ] Record current Inbox baseline files and tests.
- [ ] Run a focused baseline before edits:
  - tests/phase2/postgres_audience.py
  - tests/test_postriff_audience_contract.py
  - tests/test_reply_writer.py
  - relevant coworker engagement portion of tests/phase2/postgres_coworker.py
  - current web Inbox tests, if any
  - TypeScript no-emit
- [ ] Record pre-existing failures separately. Do not repair unrelated failures silently.

Acceptance:
- clean isolated worktree
- exact release base recorded
- no unrelated canonical edits touched

---

## Task 1: Freeze what is already implemented and prevent regression/reimplementation

Files:
- primarily tests and planning receipt
- only modify production code if a fresh regression is proven

Purpose:
make the agent prove that current remote already contains the AI writer and Engagement Copilot before changing Inbox.

- [ ] Write/extend a focused contract test proving AudienceService AI suggestion delegates to reply_writer and stores origin copilot.
- [ ] Prove the fixed deterministic starter is not the current AI path.
- [ ] Prove Engagement Copilot triage categories and priorities still exist.
- [ ] Prove engagement_draft_create saves a draft and does not send.
- [ ] Prove exact reply preview contains the saved manifest text.
- [ ] Prove old approvals with requiresReconfirmation cannot be replayed.
- [ ] If these are already covered, cite the existing tests instead of duplicating them.

Acceptance:
- no duplicate AI implementation
- no duplicate triage implementation
- plan proceeds from the actual current architecture

---

## Task 2: Fix cumulative OAuth capability verification

Likely files:
- src/postriff_phase2/oauth.py
- tests focused on OAuth/capabilities under tests/ and tests/phase2/
- web connect flow only if the server contract requires a small change

Problem:
current _capabilities builds a fresh matrix around one requested capability and complete() upserts the whole matrix.

Required invariant:
verifying one capability must not silently downgrade unrelated previously verified capabilities.

RED tests:
- [ ] publish Direct -> verify comments_read -> publish remains Direct
- [ ] comments_read Direct -> verify reply -> both remain Direct
- [ ] analytics Direct -> verify publish -> analytics remains Direct
- [ ] fresh scope inspection proving a permission was removed may downgrade that capability with evidence
- [ ] revoked credential may downgrade all affected non-identity capabilities according to current security rules

Implementation:
- [ ] Read existing pr_channel_capabilities for the connection before constructing the post-auth matrix.
- [ ] Merge verified existing rows as the starting point where still valid.
- [ ] Update only capabilities whose evidence was actually refreshed, plus identity and any explicitly coupled publish/schedule state.
- [ ] Preserve capabilityVersion/verifiedAt semantics.
- [ ] Audit before/after levels for changed capabilities.
- [ ] Keep fail-closed behavior when provider scope inspection returns unknown.

Do not:
- infer Direct from requested scopes alone
- turn Assisted/Unsupported into Direct without verified account/provider evidence

Acceptance:
- reconnecting for Inbox never breaks working publishing by construction
- downgrade still occurs when real scope re-verification proves loss

Suggested commit:
fix(oauth): preserve verified capabilities across reconnects

---

## Task 3: Add bounded durable comment sync

Likely files:
- new migration with execution-time next free prefix
- src/postriff_phase2/audience.py
- src/postriff_phase2/hosted_app.py
- tests/phase2/postgres_audience.py
- tests/phase2/rls.sql
- tests/test_postriff_audience_contract.py
- web/src/lib/api/types.ts
- web/src/lib/api/client.ts
- web/src/lib/api/hooks.ts

### 3A. Schema

Add the minimum additive sync state.

Recommended:
pr_audience_sync:
- workspace_id
- connection_id
- provider
- last_synced_at
- cursor_state jsonb
- last_result jsonb
- last_error_code nullable
- created_at
- updated_at
- unique(workspace_id, connection_id)

Add only verified missing fields to pr_audience_threads, for example permalink.

- [ ] RLS follows current workspace-member read / server-write policy.
- [ ] migration fresh apply, upgrade apply and replay/idempotency tests.
- [ ] no destructive rewrite of historical reply rows.

### 3B. Sync service

Create one sync implementation used by manual and scheduled refresh.

RED tests:
- [ ] non-Direct comments_read connection causes zero provider calls
- [ ] unsupported provider causes zero provider calls
- [ ] Threads response inserts comments idempotently
- [ ] repeated page/cursor data does not duplicate rows
- [ ] pagination has a hard maximum
- [ ] lastSyncAt reflects a real attempt, not UI time
- [ ] provider 429/error records unavailable/reason without pretending zero
- [ ] transient error never tombstones comments
- [ ] tombstone occurs only under verified provider semantics
- [ ] comments on an already-replied thread preserve reply history
- [ ] no broad DB row lock is held during external HTTP

Manual route:
POST /api/workspaces/{workspaceId}/audience/sync

Return actual:
checkedPosts, pagesRead, ingested, updated, tombstoned, lastSyncAt, availability, reason.

Cooldown:
- server-enforced
- response includes remaining time/reason
- UI does not simulate success during cooldown

### 3C. Scheduled refresh

Reuse the same sync function from the existing worker/cron architecture.

- [ ] bounded number of workspaces/connections per tick
- [ ] only due Direct connections
- [ ] no per-minute full-table provider sweep
- [ ] no search/provider call while holding global workspace locks
- [ ] cron uses feature flag and documented interval

Suggested feature flag:
RAFII_INBOX_SYNC_ENABLED

Manual sync may be allowed independently if product wants explicit user action before cron rollout.

Acceptance:
- Inbox can become fresh after post verification
- refresh state survives reload
- no fake freshness

Suggested commit:
feat(inbox): add bounded durable comment sync

---

## Task 4: Wire the approved-reply worker without replay risk

Likely files:
- src/postriff_phase2/audience.py
- src/postriff_phase2/hosted_worker.py
- src/postriff_phase2/hosted.py
- src/postriff_phase2/hosted_app.py
- tests/phase2/postgres_audience.py
- focused worker tests

Feature flag:
RAFII_INBOX_REPLY_SEND_ENABLED
Default: off.

RED tests:
- [ ] with flag off, approved reply remains held and provider transport has zero calls
- [ ] turning flag on cannot send an approval recorded while sender was disabled
- [ ] explicit reconfirmation of the exact old manifest clears the old replay fence
- [ ] new approval while flag is on can be claimed once
- [ ] two concurrent workers cannot claim the same draft
- [ ] submitting is stored before provider I/O
- [ ] Threads successful container + publish -> submitted with provider reference
- [ ] 401/403 -> held with truthful reason
- [ ] inconclusive external outcome -> uncertain
- [ ] uncertain has no automatic resend
- [ ] digest mismatch -> held, zero provider calls
- [ ] revoked/non-Direct capability at dispatch -> no provider call
- [ ] tombstoned source -> no provider call
- [ ] crash after provider call cannot cause blind duplicate send

Worker design:
- SQL claim on approved reply rows
- row lock / SKIP LOCKED or equivalent current project pattern
- bounded replies per tick
- preserve existing publication worker behavior

Reconciliation:
- verify current official Threads API before implementing read-back
- if authoritative read-back exists, submitted -> verified only on proof
- if not, submitted remains submitted and UI copy must say provider accepted but Rafii has not re-read it
- never invent verified

Service construction:
- pass reply_sender_enabled from explicit server config/feature flag
- do not hardcode True
- do not enable in preview/test by accident

Acceptance:
- operational path exists
- default production activation remains off
- old approvals cannot be replayed

Suggested commit:
feat(inbox): add fenced reply worker and reconciliation

---

## Task 5: Integrate existing Engagement Copilot into Inbox

Likely files:
- web/src/features/inbox/*
- existing coworker client/hooks/types
- src/postriff_phase2/coworker/http.py only if contract shaping is needed
- tests/phase2/postgres_coworker.py
- web tests for Inbox

Do not create a new classifier.

Backend contract:
reuse coworker.engagement_triage and existing deterministic categories/priorities.

UI:
- [ ] add Needs reply
- [ ] add Review
- [ ] add FYI
- [ ] optional Ignore
- [ ] category badge
- [ ] priority explanation using existing why
- [ ] show freshness/age without calling anything urgent
- [ ] Replied/Done state maps to server reply history
- [ ] triage failure does not hide raw comments

Reply action:
- [ ] Suggest reply calls the already-merged AI writer path
- [ ] suggested draft retains provenance
- [ ] user can edit before review
- [ ] exact manifest text is what approval dialog shows
- [ ] approval is still one thread/account/text at a time

Spam/abusive:
- [ ] do not auto-generate a reply
- [ ] if moderation is not Direct, use provider click-through
- [ ] do not add pretend hide/report controls

Feature flag:
RAFII_ENGAGEMENT_COPILOT_ENABLED

After Inbox consumes the feature, update the rollout note so the flag is no longer described as screenless/pointless. Do not enable it in production merely because code exists.

Acceptance:
- Engagement Copilot has a first-class Inbox surface
- no second classification system
- no automatic send

Suggested commit:
feat(inbox): surface engagement copilot triage

---

## Task 6: Add Inbox freshness, receipt and attention UX

Likely files:
- web/src/features/inbox/inbox-view.tsx
- coverage-strip.tsx
- thread-list.tsx
- thread-detail.tsx
- reply-composer.tsx
- new reply-receipt.tsx if useful
- web/src/components/layout/* for optional count
- existing notification service/frontend
- web tests

Header:
- [ ] Checked <relative time> from server lastSyncAt
- [ ] Never checked when null
- [ ] Check for new comments button
- [ ] cooldown / provider error uses server reason
- [ ] no local fake timestamp

Receipt:
show reply.events / provider_reference with states:
- draft
- approved
- submitting
- submitted
- verified
- uncertain
- held
- cancelled

- [ ] uncertain has no Resend action
- [ ] provider reference copy control only when present
- [ ] old receipts survive reload
- [ ] status text matches backend truth

Counts/attention:
- [ ] authoritative needs-reply/unanswered count in Inbox
- [ ] optional sidebar count only when query data is known
- [ ] unknown never renders as 0
- [ ] in-app notification uses existing notification infrastructure
- [ ] dedupe one comment/event
- [ ] link notification to exact Inbox thread/filter

Do not add email/push delivery in this task unless the existing notification system is already enabled/configured and the user separately requests delivery rollout.

Accessibility:
- keyboard focus
- accessible names
- screen-reader status updates
- reduced motion
- 390 / 430 / 768 / 1440 responsive checks
- safe-area on mobile sheet
- no horizontal overflow

Suggested commit:
feat(inbox): add sync status receipts and attention states

---

## Task 7: Remove Inbox query scale traps

Likely files:
- src/postriff_phase2/audience.py
- web API types/hooks
- PostgreSQL tests

Current issues include:
- hard limit 200
- per-thread capability/reply lookups can become N+1

RED tests:
- [ ] thread response uses bounded query count independent of 200 thread rows
- [ ] counts are computed over authoritative eligible rows, not just current page
- [ ] cursor or page token returns next page deterministically
- [ ] sorting uses provider time when present and ingested time as fallback
- [ ] deleted/tombstoned filter semantics remain explicit

Implementation:
- join capability data once
- aggregate replies with lateral/JSON aggregate or a bounded second query
- add cursor pagination contract
- keep response backward-compatible where practical

Acceptance:
- no 200x capability query pattern
- large Inbox remains truthful and usable

Suggested commit:
perf(inbox): batch thread history and add pagination

---

## Task 8: Introduce a provider adapter boundary, keeping Threads first

Likely files:
- src/postriff_phase2/audience.py
- provider adapter modules discovered in current repo
- tests with synthetic transports

Goal:
replace growing hard-coded provider branches with a narrow Inbox adapter contract.

Adapter operations:
- list_comments
- paginate
- source_permalink
- send_reply
- reconcile_reply
- error/capability mapping

- [ ] Threads behavior remains unchanged under the adapter
- [ ] provider absence returns Unsupported without calling network
- [ ] capability evidence stays account-specific
- [ ] no provider gets Direct only because a general connector exists

Instagram:
- do not enable merely because scopes exist in code
- recheck current official API docs and current Meta production-review state at implementation time
- add only after synthetic tests and provider capability evidence
- real provider mutation requires separate authorization

Other networks:
keep Assisted/Unsupported until proven.

Suggested commit:
refactor(inbox): route engagement through provider adapters

---

## Task 9: Update rollout docs and create a v1 activation runbook

Files:
- docs/design/site-agent/adaptive-social-coworker/ROLLOUT.md
- relevant Inbox docs
- new release runbook under docs/superpowers/handoffs or project release docs

Document:
- current supported providers
- manual sync vs scheduled sync
- engagement flag
- reply send flag
- old-approval reconfirmation rule
- no-bulk/no-auto-send
- provider-specific limitations
- staging test procedure
- production activation steps
- rollback switches

Activation sequence:
1. code merged with send flag off
2. production migration applied through normal release gate
3. read-only/manual sync smoke
4. Engagement Copilot UI smoke
5. scheduled sync activation
6. inspect errors/duplicate counts
7. explicit owner approval for live reply sending
8. enable RAFII_INBOX_REPLY_SEND_ENABLED
9. reconfirm one exact reply
10. one controlled provider smoke if separately authorized
11. monitor receipt/provider logs
12. rollback send flag on anomaly

Do not execute steps 7-10 without new explicit authorization.

---

## Task 10: Full Inbox v1 verification

Run fresh project-standard gates plus targeted tests.

Backend:
- Python unit tests
- disposable PostgreSQL full suite or required current suite
- focused audience/coworker/reply writer/OAuth worker tests
- migration fresh/upgrade/replay
- migration prefix uniqueness

Web:
- Node/web contract tests
- TypeScript no-emit
- lint
- production build
- targeted Inbox browser tests

Browser matrix:
- 1440x900
- 768x1024
- 430x932
- 390x844
- WebKit/Safari-class check for mobile-sensitive behavior
- reduced motion
- light/dark if supported

User-critical browser paths:
1. load Inbox with known comments
2. manual refresh success
3. manual refresh provider error
4. triage filter
5. create AI suggestion
6. edit suggestion
7. exact approval preview
8. approval while send flag off
9. synthetic send flag on -> submitted/verified receipt
10. uncertain outcome -> no resend
11. provider Unsupported -> Reply on provider path
12. mobile open/back flow
13. permission variants

Runtime health:
- console errors
- failed network requests
- worker errors
- duplicate provider attempts
- DB constraint errors

Security:
- external comment cannot inject instructions into system behavior
- secret scan
- no tokens in logs/receipts
- cross-workspace thread/reply isolation
- permission downgrade during session handled safely

Final report must distinguish:
- source implementation
- local/disposable DB
- synthetic provider transport
- preview/staging read-only provider sync, if run
- live social reply mutation: NOT RUN unless separately authorized
- production send flag: OFF unless separately authorized

---

## Phase boundary: Unified Inbox v2

Do not implement DM/mention generalization in the same branch unless Inbox v1 is complete and a new task explicitly authorizes v2.

A follow-up v2 plan should:
- verify which providers expose real DM/mention APIs for Rafii's app/account types
- define pr_inbox_conversations/pr_inbox_messages or a compatibility projection
- preserve public comment history
- keep transport type separate from triage category
- start relationship memory provider-local
- require explicit evidence before cross-platform identity linking
- add per-source privacy/retention rules

The current v1 UI must continue to call itself Inbox/Comments honestly until those sources exist.

## Definition of done

This plan is complete when Rafii has a production-ready but default-safe Inbox v1 implementation in an isolated branch with:
- cumulative capability verification
- durable manual/scheduled comment sync
- authoritative freshness
- existing Engagement Copilot visible in Inbox
- existing AI writer reused
- fenced approved-reply worker
- exact receipt states
- no replay of old approvals
- no blind resend of uncertain outcomes
- batched/paginated thread reads
- provider adapter boundary
- full local/synthetic/browser verification
- explicit activation runbook

Completion does not mean live reply sending has been enabled.
