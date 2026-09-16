# Phase 2 migration and coexistence

No founder-data migration was performed. The additive hosted schema was applied only to the new approved Supabase Preview project `buoyhkbodnhzngaotoel`.

## Local state

The original alpha remains at `~/Library/Application Support/PostRiffFounderAlpha/alpha.sqlite3`. Phase 2 uses `~/Library/Application Support/PostRiffPhase2/local.sqlite3`. New auth challenge, session, identity and trial-grant tables are additive inside that separate file. Files are private to the OS account. The demo contains fictional workshop data only. The launcher neither reads nor uploads the founder-alpha database.

## Postgres candidate

[001_phase2.sql](../../migrations/postriff/001_phase2.sql) creates prefixed profiles, workspaces, memberships, trials, voice profiles, skills, sources, assets, devices, channels, approvals, jobs and receipts. A non-exposed helper schema supplies membership checks. All public tables enable and force RLS. Browser roles have scoped reads; writes and bootstrap are service-only. The bootstrap transaction serializes per verified user and preserves one trial grant.

The private bucket is `postriff-private`. Object paths begin with the workspace UUID. Browser overwrite/upload policies are absent; the eventual trusted Storage service must verify membership, decode media and issue bounded delivery URLs.

The migration was tested against a disposable PostgreSQL instance and then applied to the new Supabase project. Hosted verification found 13 `pr_*` tables with forced RLS and the private bucket. Two synthetic Supabase users passed workspace and media isolation before their database rows and Auth identities were removed. The PostgreSQL repository test used UTF-8 client encoding and psycopg 3.3.5 in the workspace virtual environment; no global Python package was installed.

## Remaining ordered hosted application

1. Exercise callback, recovery, session revocation and export on the protected Preview with synthetic identities.
2. Resolve production callback domains, deployment access, worker cadence and any paid-plan ceiling.
3. Configure only separately approved auth and social providers and qualify their current scopes/capabilities.
4. Run exact synthetic provider contracts before any real destination manifest.
5. Review the production deployment and cron candidate before promotion or any separately approved live post.

Founder imports require a separate preview naming exact records. Never import the entire SQLite file or raw local-only fields. Rebuild approvals and entitlements on the destination; imported text cannot carry publishing authorization.

## Rollback

Stop the new runner, disable the candidate deployment and revoke its secrets. Restore scoped source files from `evidence/pre-phase2/` only if reverting the implementation is desired. The original alpha database needs no rollback. On a fresh disposable hosted project, remove the candidate bucket/objects and prefixed tables only after verifying they contain no retained user data. Do not run a destructive down migration automatically. Trial tombstones must survive ordinary workspace deletion to prevent grant renewal.
