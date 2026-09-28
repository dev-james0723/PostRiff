# Shared inbound Rafii release — 2026-09-28

Status: release in progress, explicitly authorized by the user to push and deploy. This receipt will record actual migration, merged source and production verification separately.

Candidate: shared +16055978162 with a fresh, single-use five-minute web sign-in code selecting the user/workspace/conversation. The code is never retained in plaintext. Caller ID does not authenticate the account. Existing agent permissions, credits and publication approvals apply.

Includes the released Dial client-identification fix and removal of the fixed six-manual-call limit (PR #49), plus the required Live greeting delegation field and persistent media-failure status (PR #50). Their live audio acceptance is separate from this release's synthetic regression checks.

Migration 042 is additive and checksum-pinned at `78a23c99f1b876426fa4aa5193da67f2e9941901baee89502004ae84f9131554`. Its one-off runner verifies the production project, prerequisites and canonical schema, uses an advisory lock and one transaction, refuses partial/drifted schema, and verifies RLS/grants before commit. Local PostgreSQL rehearsal passed plan, apply, rollback on shape mismatch, idempotent rerun and partial-state refusal. Runner/evidence: `inbound-042/`.

The runner is executed only as a non-aliased Vercel production build, which intentionally fails after reporting its result. It cannot replace or serve the app. Only schema metadata and approved non-secret phone flags are logged. No credential is exported. Supabase connector is linked to a different project and is not used.

Pending: production preflight/apply, exact release CI, merge, deployment/flag activation, authenticated UI/API checks. No new paid call, SMS or model test is authorized in this thread.
