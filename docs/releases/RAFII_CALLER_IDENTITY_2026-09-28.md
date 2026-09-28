# Rafii Phone caller identity release — 2026-09-28

Status: production migration and application deployment complete. The user approved all three Agent Pairing Code recordings, commit, push, deployment and the separately gated production migration 045. Supported-device passkey acceptance remains pending.

Release branch: `codex/rafii-phone-caller-identity`, rebased on the currently deployed `origin/consumer-saas` at `a25bb459b7676bdaec8c007c9f6096ac45a8ed3b`. The original voice-opening worktree was not modified.

Migration `045_phone_caller_identity.sql` is additive and checksum-pinned at `1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014`. The runner at `caller-identity-045/migrate_045.py` defaults to read-only, validates the exact production Vercel and Supabase targets, uses an advisory lock and one transaction for apply, verifies columns, constraints, indexes, forced RLS, policies and grants, records the ledger checksum when available, and refuses a partial schema. The local disposable-PostgreSQL rehearsal passed plan, apply, idempotent rerun and partial-state refusal.

Deployment ordering is strict: migration 045 must verify and commit before the application is promoted. The application directly reads the new caller-routing and challenge tables, so deploying first would break trusted-caller lookup and Phone Settings.

The production read-only migration preflight passed in intentionally non-promotable Vercel build `dpl_FBQ86bBT5A9ZiSrLVsjc361Q8LQ8`: the exact Supabase target and ledger were verified, all three 045 objects were absent, and no partial schema was found. No database write was requested and no production alias was assigned. See `caller-identity-045/preflight.log`.

Before migration, production advanced concurrently to deployment `dpl_6jiaa4cqvdYwkhehXuTMXVNMouxb` from commit `a25bb45`. The release was rebased again before any database write. Final overlap, registry, PostgreSQL, TypeScript, lint, build and virtual-WebAuthn gates passed on that base. `rafii.policy.notification-planning` was correctly bumped to 1.2.1 and relocked for the new caller-verification notification event.

Production migration apply passed in intentionally non-promotable build `dpl_85gLw6w9td2aQfnKN8ThuewDYdFW`. The transaction verified and committed checksum `1d672f5df62ae9209671d1b8505fe3729a6e6713e22a840b8db8edb0f76e1014`. Independent read-only post-verification `dpl_FGjURJEoB8MCXvukojxjivosfYXh` found all three objects present and the canonical schema intact. Neither migration bundle received a production alias.

Application source commit `c40a6ed2d646a78d11af00bd02e8e31c784a0f43` deployed as `dpl_6yakiSj9QEFjF2yeeocD6aPgxGmB`, reached READY, and owns `https://postriff-phase2-private.vercel.app`. The production build included `/app/phone/verify-call`. Public smoke passed: `/api/health` returned 200/configured; the status page returned 200; unauthenticated call-challenge and trusted-caller requests returned 401; and the protected verification page redirected to sign-in.

Pending release evidence: authenticated production Phone Settings and user-operated supported-device passkey flow. The available in-app browser had no production login session and stopped at sign-in. No real paid call was placed, and no merge was performed.
