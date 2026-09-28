# Rafii Inbox Completion + Engagement Copilot Worker Handoff — 2026-09-28

You are taking ownership of Rafii's Inbox v1 operational-completion work.

This is an implementation handoff for an isolated coding worktree. Do not stop after writing another audit or another plan. Implement the saved plan through local/disposable/synthetic verification and focused commits.

This handoff does NOT authorize:
- editing the shared dirty canonical checkout
- merging to consumer-saas
- pushing a release branch
- production deployment
- production migration
- enabling live social reply sending
- real provider reply mutation

Those remain separate release/activation actions.

## Authoritative repository

/Users/ouxianxing/Documents/James-Au-Studio

Canonical release branch observed after a fresh fetch:
consumer-saas

Fresh remote snapshot at handoff creation:
origin/consumer-saas = a6033925bd8c94b8f8b98efea48741fb57f110da

Local shared checkout at handoff creation:
consumer-saas = 468811b73d28b4389f931519827c05d0e6c8abfb

It was 357 commits behind remote and had extensive unrelated dirty work.

RECHECK ALL OF THIS before editing. Remote state may have advanced.

## Read these first

Treat these as the implementation contract:

1. /Users/ouxianxing/Documents/James-Au-Studio/docs/superpowers/specs/2026-09-28-rafii-inbox-engagement-copilot-design.md
2. /Users/ouxianxing/Documents/James-Au-Studio/docs/superpowers/plans/2026-09-28-rafii-inbox-engagement-copilot.md
3. /Users/ouxianxing/Documents/James-Au-Studio/AGENTS.md
4. /Users/ouxianxing/Documents/James-Au-Studio/CLAUDE.md

The spec/plan/handoff were created in the already-dirty shared checkout and may be uncommitted. Read them from those absolute paths before leaving the shared checkout.

After creating the isolated implementation worktree, copy the three Inbox planning artifacts into the same relative docs/superpowers paths in the worktree, verify their hashes/content, and make them the first documentation commit if they are not already present in the base.

Do not delete, reset, stash or overwrite the originals in the shared checkout.

## Mandatory setup

1. Run the Token Pilot resume flow required by AGENTS.md/CLAUDE.md.
2. Fetch origin.
3. Re-check the actual canonical/default release branch.
4. Inspect branch, HEAD, status and all worktrees.
5. Use superpowers:using-git-worktrees.
6. Create/reuse a clean isolated worktree from the current origin/consumer-saas.
7. Re-check migration prefixes across current refs.
8. Establish the focused Inbox baseline before edits.

Do not implement in /Users/ouxianxing/Documents/James-Au-Studio while it is the dirty shared checkout.

## Important: several things are already done

Do NOT rebuild or cherry-pick them blindly.

### AI replies are already merged

These commits were confirmed ancestors of the current remote release branch:
- cd3c177 — feat(replies): comment replies are written by Rafii's AI writer, never fixed text
- 848ab49 — fix(replies): review fixes for AI-written replies

Current AudienceService.draft_reply uses reply_writer and stores AI suggestions as origin copilot.

If your fresh graph still contains those commits, do not reimplement them.

### Engagement Copilot backend already exists

Reuse:
- src/postriff_phase2/coworker/engagement.py
- engagement_triage agent tool
- engagement_draft_create agent tool
- RAFII_ENGAGEMENT_COPILOT_ENABLED

It already classifies:
question, complaint, lead, praise, press_or_partner, spam, abusive, other

It already prioritizes:
needs_reply, review, fyi, done, ignore

Do not create a second classifier.

### Production post-verification ingestion is already wired

Current remote hosted_app builds HostedWorkspaceService with audience_transport=http_transport and places service.audience.on_post_verified in the verified-publication callback chain.

Do not waste time "fixing" the old stale issue that said production had no audience transport.

## Actual blockers you must solve

### 1. Capability reconnect corruption

oauth.py still rebuilds a fresh capability matrix around one requested capability and upserts all rows.

Fix capability updates so verifying comments_read/reply does not destroy a valid publish/analytics state.

This is first because telling users to reconnect for Inbox before fixing it can silently damage publishing capability.

### 2. Inbox is not continuously fresh

Current comments are read at post verification.

Build the bounded durable sync contract from the plan:
- manual refresh
- durable lastSyncAt
- pagination/cursor bounds
- scheduled refresh using the same implementation
- truthful provider errors/cooldown
- idempotent upsert
- safe tombstone semantics

### 3. Approved replies never reach a production worker

AudienceService.send_approved exists but is not called by hosted_worker.

Build the fenced worker path and explicit feature flag:
RAFII_INBOX_REPLY_SEND_ENABLED

Default it off.

Old approvals recorded while sending was off must never replay automatically.

### 4. Engagement Copilot is not first-class in Inbox

Expose the existing triage in the Inbox:
- Needs reply
- Review
- FYI
- category
- why
- age/freshness
- existing AI suggestion -> edit -> exact approval path

Do not call anything urgent by default.

### 5. Receipts/freshness/attention are incomplete

Add:
- Check for new comments
- server lastSyncAt
- durable reply receipt timeline
- authoritative Inbox attention count
- existing in-app notification integration where appropriate

Unknown must never render as zero.

### 6. Inbox reads do not scale cleanly

Remove the N+1 pattern and add a bounded pagination/cursor contract.

### 7. Provider logic needs an adapter boundary

Keep Threads as the first proven provider.

Do not mark Instagram or other hosted connectors as Inbox Direct simply because their account connector exists.

Check current official provider API/support and Rafii app-review state before adding another provider.

## Threads-only fact you must preserve honestly

At handoff creation:
AudienceService.COMMENT_READ_PROVIDERS = ("threads",)

send_approved is also Threads-specific.

Therefore Inbox v1 may ship as a Threads operational Inbox before other networks are added.

The UI must expose capability evidence rather than promising universal support.

## Production/live-send boundary

Local/disposable/synthetic implementation is authorized by this handoff when it is actually invoked for execution.

You MAY:
- edit code in the isolated worktree
- add additive migrations to source
- run disposable PostgreSQL migrations/tests
- use synthetic provider transports
- run local browser tests
- run build/typecheck/lint
- make focused local commits
- write an activation runbook

You MUST NOT under this handoff:
- send a real social reply
- enable RAFII_INBOX_REPLY_SEND_ENABLED in production
- apply a migration to production
- alter live OAuth/provider app settings
- deploy production
- merge to consumer-saas
- push a release branch
- bulk reply/moderate
- enable a provider capability without evidence

If live provider access is needed to prove a read-only integration, prepare the exact staged smoke and report the external requirement. Do not silently cross the boundary.

## Required execution order

Follow the saved implementation plan in order:

Task 0
- isolated worktree and baseline

Task 1
- prove existing AI/triage architecture; no duplicate work

Task 2
- cumulative OAuth capability verification

Task 3
- durable bounded comment sync

Task 4
- fenced approved-reply worker

Task 5
- Engagement Copilot in Inbox

Task 6
- freshness, receipt and attention UX

Task 7
- query batching/pagination

Task 8
- provider adapter boundary

Task 9
- rollout/activation docs

Task 10
- full verification

Do not jump to Instagram/DM work before the Threads v1 loop is verified.

## TDD and concurrency

Use RED -> GREEN -> REFACTOR.

Important concurrency/idempotency cases:
- two reply workers compete for one approved draft
- worker crash before provider call
- worker crash after provider call
- provider returns inconclusive result
- old approval existed before sender activation
- capability revoked between preview and dispatch
- comment tombstoned between approval and dispatch
- manual sync and cron sync overlap
- provider pagination repeats an item
- workspace/connection removed during sync

No duplicate send is acceptable.

## Provider I/O rule

External comment/message content is untrusted data.

Never allow a comment to:
- change system/agent instructions
- select tools outside the approved path
- bypass permission checks
- trigger sending by itself

AI reply suggestions are drafts only.

## Verification

At minimum, run fresh:
- focused audience tests
- audience transport contract tests
- reply_writer tests
- coworker engagement tests
- OAuth capability regression tests
- worker concurrency/idempotency tests
- migration fresh/upgrade/replay/RLS tests
- current required Python suite
- current required PostgreSQL suite
- web unit/contract tests
- TypeScript no-emit
- lint
- production build
- browser Inbox journey at 1440x900, 768x1024, 430x932 and 390x844
- WebKit/Safari-class mobile-sensitive check
- reduced-motion check
- secret scan
- migration prefix uniqueness

Browser journeys must cover:
- comments loaded
- manual sync success
- provider sync error
- triage filters
- AI suggestion
- edit
- exact preview
- approve with sender off
- synthetic send enabled
- receipt progression
- uncertain outcome with no resend
- unsupported provider click-through
- mobile sheet/back behavior
- permission variants

Check browser console and failed network requests.

## Completion report

Return:

1. Isolated branch/worktree and exact base/current HEAD.
2. Commits made by plan task.
3. Files changed.
4. Migration added, exact prefix and checksum.
5. Focused test commands/results.
6. Full backend/DB/web/build results.
7. Browser matrix results and physical/emulated disclosure.
8. Capability regression evidence.
9. Worker concurrency/idempotency evidence.
10. Synthetic provider send/reconcile evidence.
11. Any provider support assumptions that remain unverified.
12. Deferred items.
13. Explicit state:
   - Inbox v1 source implementation
   - local/disposable DB
   - synthetic provider transport
   - preview/staging provider read
   - live social reply mutation
   - production migration
   - production send flag
   - production deployment
14. Exact activation runbook path.

Do not report "done" because the UI renders.

Inbox v1 is only locally implementation-complete when the full loop is verified under synthetic provider transport and the live-send boundary remains explicit.

## Unified Inbox v2 boundary

Do NOT expand this implementation branch into DMs/mentions unless a new task explicitly authorizes v2 after Inbox v1 is complete.

The design spec contains the v2 direction:
- source types comment / mention / dm
- generalized conversation/message model
- provider-local relationship memory
- no guessed cross-platform identity

For now, keep the customer promise honest: this is Rafii's Inbox for supported comments/replies, with Engagement Copilot.
