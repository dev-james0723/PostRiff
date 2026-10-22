# Bluesky synthetic load and capacity (D1, C5, D3)

Run: JCB on Depot, run ID `td07wtg4xp`, exit 0, 2026-10-22 ~05:35Z, runner depot-ubuntu-24.04-16, disposable PostgreSQL 16. Script `tests/phase2/postgres_bluesky_launch.py`.

| Check | Result |
| --- | --- |
| Two concurrent callers on one expired grant | 1 refresh call; both received the rotated token; rotation stored in the same transaction |
| Definitive refusal (invalid_grant) | grant marked non-renewing; ciphertext and expiry untouched |
| Outage (503) | grant untouched, still renewing |
| 997 tenants renewing at once, 32 SQL workers, fake endpoint 50 ms | 0 failures; p95 76.8 ms (td07wtg4xp), 62.3 ms (z7bvzfctkm) |
| Burst of 1,000 connect starts against the site-wide cap | 300 admitted, 700 deferred with "Too many attempts. Wait a minute and try again." |

## What this does not prove

- Not an HTTP load test of the deployed candidate, and no fake authorization server was driven over the network. `productionHttpLoadAcceptance=false`.
- No real Bluesky account or provider call. `realAccountAcceptance=false`.
- Function concurrency on Vercel and the per-process DNS guard (`net_guard` allows 8 concurrent DNS lookups per instance, then answers 503) were not exercised. The adapter's one jittered retry covers a single 503.

## Capacity notes

- Connect: 300 Bluesky starts per minute site-wide (18,000 per hour) plus the existing 20 per 10 minutes per workspace. Raise `BLUESKY_STARTS_PER_MINUTE` in code if launch traffic needs more.
- Publishing (stretch only): `POSTRIFF_WORKER_MAX_JOBS` defaults to 10 and `POSTRIFF_WORKER_MAX_SECONDS` to 20, with one cron per minute: about 14,400 jobs a day for all platforms together. Neither variable is set in production. A job here takes well under a second of database time; raising the job count is an environment change for James.
- Trial plan: 2 connected accounts and 1 member per new workspace (`pr_plan_terms` trial v1).
