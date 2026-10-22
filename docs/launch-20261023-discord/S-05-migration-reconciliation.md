# S-05 Migration ledger reconciliation (production vs release candidate)

Read 2026-10-22 ~19:45 UTC with Supabase `list_migrations` on the production project (read-only; nothing applied). Compared with `migrations/postriff/` of the merged release candidate (`claude/discord-launch-rc-20261023`, which contains the live line `c5fc1fd1` and the Discord line `b960bfe0`).

## Result

**Nothing has to be applied for the Discord launch.** Every Discord migration the candidate ships is already in the production ledger, in the order the files expect, and the structure of those tables was checked against the migration SQL by the private database audit (RLS and FORCE RLS on, `anon` has no grants, `authenticated` has no access to the Discord, credential or OAuth tables, `service_role` has the grants the migrations give it).

| Group | Migrations | Status |
|---|---|---|
| Discord | 124 `discord_rate_limits`, 125 `discord_service_grants`, 126 `discord_worker_projection`, 128 `discord_lease_protocol_fence`, 131 `discord_interactions` | In the ledger (131 applied 2026-10-21 16:11Z). Candidate files match. |
| Shared with the live line | 088 to 107, 116/117, 119 to 123, 127, 129, 130, 134, the three dated Pinterest files | In the ledger. Candidate files match. |
| In the candidate, NOT in the ledger | 108 `agent_tasks`, 109 `agent_permissions`, 110 `agent_observability`, 111 `agent_release_gates`, 112 `library_metadata_changes` | Parity with the live build, which ships the same files and runs without them (the features behind them are not enabled in production). Not a Discord item. Do not apply as part of this launch. |
| In the ledger, NOT in the candidate | `private_request_capture` (20261005), `113_x_request_admission`, `mastodon_management_after_134_20261022` | Applied from other lanes' branches. Additive; nothing in the candidate reads them. Their SQL lives on those lanes' branches (not touched). |
| Retired numbers | Mastodon 131 to 133 | Absent from the candidate and from the ledger. They must never be applied: 131 is the Discord interactions migration. |

## What this means

- AUTH-8 (rehearse migrations on staging) is not needed for correctness. It would only serve to rehearse the break-glass SQL and the cap query on a database with the Discord tables; staging ends at 130 and has none. Recommended: do not use it for this launch.
- A rollback to `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg` needs no schema change; the old build ignores the Discord tables.
- Duplicate version prefixes in the file names (`20261017_*`) are the pairs of migration and rollback files that both lines already carry.

## Checks the release candidate keeps

`scripts/rc_superset_proof.py` fails if any migration file of the live line disappears from the candidate (`migrations` check: 0 problems on `d4572f68`).
