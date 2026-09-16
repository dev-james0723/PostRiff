# Approval and durable state model

## Exact approval

`p2_review` runs preflight and stores a server-built immutable candidate. `p2_approve` requires its exact review ID/digest and an explicit confirmation. The trusted boundary supplies the actor and workspace. `p2_approve_many` records up to ten exact reviews and enqueues them atomically; one invalid review rolls back the whole batch. Replay cannot create duplicate jobs.

The manifest binds workspace, actor, brand ID/digest, speaker and voice revision, exact account/channel, operation, variant/revision, rendered text/language/payload digest, immutable media/rendition/source hashes, alt text, rights, original local time, IANA zone, DST fold, resolved UTC, capability/version/scopes/evidence, provider-limit version, acknowledged warnings, expiry and stable idempotency key.

Content, speaker, brand, media, account, language, source retraction, capability or operation changes make existing approvals unusable. Timing changes require a new manifest; an approval has no update endpoint. Unknowns require explicit author review that unsupported details were excluded, not an invented fact-verification claim. Subsequent edits require another draft review.

## Jobs and recovery

Drafts/reviews represent draft and needs_review. Durable destination records progress through approved, scheduled, claimed, submitting, provider_accepted, published and verified, or failed, uncertain, canceled and held. Every state event is timestamped and synthetic in this runtime.

A 30-second lease plus a fencing ID prevents concurrent workers from completing the same claim. Heartbeats extend the current owner's lease. Claim and submission intent are saved before the adapter call; the response is persisted afterward. A crash before submit can be reclaimed; a crash after submit/acceptance reconciles before any retry. Confirmed pre-acceptance rate limits have three bounded attempts. Inconclusive reconciliation is bounded and surfaces manual review; it never blindly resubmits.

Trial expiry, disconnected/expired/stale capability or changed approval holds future jobs. Reconnection and plan switching do not release held/overdue jobs. The user must review timing again. Before-claim cancellation makes no submission; during-submit cancellation records uncertainty and cannot promise recall. Each account retains separate attempts and classification, so partial results remain visible.

## Receipt and views

List, calendar-by-date and Kanban use the same records. Each receipt includes intended account/action, approved revision/time/zone/UTC, attempt timestamps, sanitized events, safe correlation ID, provider confirmation, PostRiff state, verification method/time and next action. Calendar and Kanban cannot mutate or bypass approval. There is no “published everywhere” summary.

SQLite transactions, process restart, lease recovery, heartbeat fencing, duplicates, partial failure and unknown outcomes are tested locally. A deployed Postgres worker and real provider reconciliation remain unfinished and unqualified; the local state machine is not proof of laptop-offline publishing.
