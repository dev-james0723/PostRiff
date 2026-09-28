# Rafii Phone caller identity release — 2026-09-28

Status: release in progress. The user approved all three Agent Pairing Code recordings and explicitly authorized commit, push and deployment. Production migration 045 remains a separate action under the existing release boundary.

Release branch: `codex/rafii-phone-caller-identity`, rebased on `origin/consumer-saas` at `822f25d21138be18dbcd0eb7d3d2bcb1baff87cc`. The original voice-opening worktree was not modified.

Migration `045_phone_caller_identity.sql` is additive and checksum-pinned at `1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014`. The runner at `caller-identity-045/migrate_045.py` defaults to read-only, validates the exact production Vercel and Supabase targets, uses an advisory lock and one transaction for apply, verifies columns, constraints, indexes, forced RLS, policies and grants, records the ledger checksum when available, and refuses a partial schema. The local disposable-PostgreSQL rehearsal passed plan, apply, idempotent rerun and partial-state refusal.

Deployment ordering is strict: migration 045 must verify and commit before the application is promoted. The application directly reads the new caller-routing and challenge tables, so deploying first would break trusted-caller lookup and Phone Settings.

Pending release evidence: production read-only migration preflight, separately authorized production migration apply, exact-source Vercel deployment and alias verification, authenticated production smoke, and the user-operated supported-device passkey flow. No real paid call is part of this release authorization.
