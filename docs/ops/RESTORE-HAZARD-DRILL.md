# Restore hazard drill: what a database point-in-time restore does to Discord posting

Status: **IN PROGRESS** (work-in-progress commit; results are filled in by the drill run, nothing below is a result yet).

Scope: an isolated drill on throw-away local PostgreSQL 16 clusters and an in-process mock Discord. Nothing touches
Production, Supabase, Vercel or the real Discord API.

Question (M-03 section 6, owner reply 14): after a restore rewinds the database, does the worker send again a Discord
post that was already sent after the restore point, and which procedure prevents it?

Planned deliverables on branch `claude/discord-restore-drill-20261023`:

- `scripts/discord_restore_drill.py`: rebuilds everything from scratch (archived cluster, base backup, sends, point-in-time
  restore into a new data directory, scenarios A and B, edge cases, timings) and cleans up after itself.
- `scripts/discord_restore_reconcile.py`: the fail-safe reconciliation tool (read-only against Discord, dry-run mode).
- `tests/test_discord_restore_reconcile.py`: matching rules, ambiguity, idempotency, and a small real-PostgreSQL test.
- `docs/ops/RESTORE-RUNBOOK-PROPOSAL.md`: proposed text for the restore section of the incident runbook.
