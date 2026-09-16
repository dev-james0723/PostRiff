# Phase 2 architecture decision

2026-09-14 · local implementation plus hosted candidates · no deployment.

## Implemented locally

Keep React/Vite and Python. `scripts/postriff_phase2.py` runs the existing guarded loopback HTTP boundary with a `Phase2Store`, a separate SQLite database and a durable polling worker. Phase 1 onboarding, profile review, generalized skills, editing and exports remain reusable. Catalog capability controls whether the new Channels, Scheduling, artwork, trial and privacy UI appears.

Private workspace JSON is a versioned aggregate. Commands require an active device/session, workspace membership and a compare-and-swap revision. Review, approval and enqueue are one transaction. Each destination has its own immutable manifest, attempt history, lease and receipt. Worker submission happens outside the database transaction; an expired submitting lease enters reconciliation. Provider code never receives the user's full profile.

## Hosted candidate

Supabase Auth supplies the verified `auth.users.id`; Postgres supplies membership, private state and durable job storage; private Storage holds immutable originals/renditions/artwork. Vercel is the proposed web/API host. Durable Postgres jobs are the scheduling source of truth. A separately configured worker or authenticated scheduled runner must claim due jobs while the laptop is offline. Queue messages may wake workers, but cannot be the sole long-term schedule.

`WorkspaceRepository` defines authenticated reads and versioned commands. The SQLite implementation is active. `PostgresWorkspaceRepository` is implemented and tested against real disposable local PostgreSQL with the existing Phase 1 command engine, including membership, rollback and stale-revision rejection. Hosted authentication and provider request adapters are server-side candidates with injected transports. They are not mounted by the local launcher.

**Remaining integration:** compose the hosted callback/session routes, full Phase 2 command routing, private Storage lifecycle and remote worker around those candidates. The local worker currently operates SQLite; the hosted worker is not yet an implemented deployable service. This is implementation work, not merely a missing production screenshot.

## Trust boundaries

The browser can propose, review and submit an exact approval; it cannot choose the actor, authorize another workspace, mutate a manifest, operate the worker or enable a live provider with a Boolean. Service keys and provider tokens belong only in server secret storage. Providers receive minimum exact payloads. The image request uses constant abstract values; internal source IDs stay in workspace metadata. Local sample mode stays temporary and cannot create a trial.

The local auth fixture is intentionally not real authentication. Do not expose this launcher publicly. No founder browser session, private source, account token or installed skill is shared with customers.

## Official sources checked

Supabase documents membership-based [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [private Storage access](https://supabase.com/docs/guides/storage/security/access-control), and [server-side session verification](https://supabase.com/docs/guides/auth/server-side/advanced-guide). The candidate uses server verification rather than trusting editable metadata and keeps auth responses out of shared caches.

[Vercel Queues](https://vercel.com/docs/queues) documents delivery and retention constraints. Our inference is to retain durable schedules in Postgres and use bounded worker invocations, rather than holding a web request open until its schedule time.
