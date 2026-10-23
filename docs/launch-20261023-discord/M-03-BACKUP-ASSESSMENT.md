# M-03: backups, restore points, RPO and RTO of the Production database

Written 2026-10-23 about 04:45Z under owner reply 13 (decision 3: read what the authorized tools can read; if something cannot be read, give the owner the simplest dashboard steps; **do not change the Production database and do not run a destructive restore**; if there is no point-in-time recovery, assess the risk and the alternatives). **Nothing was changed and no restore was attempted.** No project id, key or customer value is in this file.

## 1. What was read (read-only, 2026-10-23 04:23Z)

| Fact | Value | How known |
|---|---|---|
| Project | `postriff-phase2-private`, us-east-1, healthy, PostgreSQL 17.6, created 2026-09-15 | Supabase project read |
| Organization plan | Pro | Supabase organization read (earlier today) |
| Database size | 237 MB | catalog |
| Compute | the smallest tier: `max_connections` 60, `shared_buffers` 224 MB, `work_mem` about 2 MB [likely: Micro] | settings |
| WAL archiving | `archive_mode` on, **`archive_timeout` 120 seconds**, `wal_level` logical, 16 MB segments; **26,564 segments archived, 0 failed, the last one 04:23:04Z when the clock read 04:23:54Z** | `pg_settings`, `pg_stat_archiver` [certain] |
| Application path | through Supavisor (Supabase's transaction pooler); `statement_timeout` for the application role 120 s | connection list, settings |
| Replication slots | none; not in recovery (this is the primary) | catalog |

What the archiving numbers mean: a segment is cut and archived every two minutes whether or not it is full, and the newest archived segment is under a minute old. That is exactly the cadence Supabase describes for point-in-time recovery (an archive interval of two minutes, so a recovery point objective of about two minutes) [likely]. It is **not proof** that the PITR add-on is bought: archiving can be on for other reasons, and no available tool shows the add-on, the restore-point list, or the earliest and latest recoverable time.

## 2. What cannot be read, and the four screenshots that settle it

No tool in this session lists backups, add-ons or restore points. The owner can settle it in about three minutes on a phone; four screenshots, no changes, nothing to click except to open pages:

1. Supabase dashboard, project `postriff-phase2-private`, **Database, Backups, "Scheduled backups"**: the list of daily backups with dates (and whether the page says the retention is 7 days).
2. The same page, **"Point in time"** tab: either a window ("earliest" and "latest" restore point, in UTC) or an offer to enable it. Please do **not** press Restore or Enable.
3. **Project Settings, Compute and Disk**: the compute size shown (Micro, Small, and so on) and the disk size.
4. **Organization (the account name at the top left), Billing**: the subscription page with the line items (Pro plan, compute, and any "Point in Time Recovery" add-on).

## 3. Assessment, in the two possible worlds

| | PITR on [probable] | Daily backups only |
|---|---|---|
| Recovery point objective (data lost in the worst case) | about 2 minutes (the archive interval) | up to 24 hours: every connection, consent, schedule and approval made since the last daily backup |
| Latest restorable time | within about 2 minutes of "now" | the time of the last daily backup |
| Recovery time objective (project offline while restoring) | [guessing] 10 to 45 minutes for 237 MB: a base backup restore plus replay of up to a day of quiet WAL; the dashboard shows progress | [guessing] similar, shorter replay |
| Restore procedure | Dashboard, Database, Backups, Point in time, choose a UTC time, start; the project is unavailable until it finishes; the restore replaces the database in place | Dashboard, Database, Backups, Scheduled backups, Restore; in place, same outage |
| Who decides | the owner presses it; the agent never restores | same |

Honest reading for launch: with PITR a bad deployment, a bad migration or a mistaken bulk change can be rewound to minutes before it; with daily backups only, the same event can erase a day of customer consents and schedules. Customers can reconnect and re-schedule, so daily-only is survivable for a controlled start, but it is **weak for a public opening to thousands of workspaces**. Recommendation [advice, not a fact]: if the screenshots show no PITR, enabling it before stage 5c is worth its monthly cost (the owner's purchase decision; confirm the price on the billing page, I do not state one); nothing is bought automatically.

## 4. The restore hazard that is specific to this product: duplicate sends

A restore rewinds the database to an earlier moment. A Discord post that was **sent after that moment** then looks unsent in the restored database, and while its approval is still valid the worker would send it **again**. The product's duplicate protection lives in the database (intents, leases, the coordinator's admissions), so a rewind removes it for the rewound interval. Therefore, for any restore:

1. **Before the restore:** set the operator hold on the shared request coordinator (`RELEASE-DEFINITION-v2.md` section 7) and, if the build allows, turn the Discord lane flag off. The hold is itself in the database, so it must be set again **immediately after** the restore, before the application is allowed to run the worker (the restored database may not contain it).
2. **After the restore, with the hold on:** reconcile Discord work in the rewound interval (jobs that the old timeline sent are visible in the destination channels; the worker must not run until each is marked sent or held), then lift the hold only on the Release Captain's word.
3. The restore is a last resort; most incidents are repaired forward (re-approve, re-schedule, fix the cause).

This is the reason the stop method must work with the Mac offline and why the hold is checked first in every ladder.

## 5. Alternatives if there is no PITR (each is a decision for the owner, none is done)

| Option | What it gives | Cost and catch |
|---|---|---|
| Enable PITR (7-day window) | RPO about 2 minutes, restore to any minute in the window | monthly add-on price; a project restart is not required [verify on the billing page] |
| Keep daily backups, add a scheduled logical export of the few critical tables (connections, consent and approval records, jobs) to storage the owner controls | a second copy outside the project, independent of Supabase | needs a database credential and a storage credential: new credentials are the owner's to create, so the agent will not make them |
| Use a separate database branch for risky changes (Supabase branching) | protects migrations, not data | not a backup |
| Do nothing | nothing | the 24-hour exposure above |

## 6. Status

M-03 stays **BLOCKED_EXTERNAL** until the four screenshots exist. The probable state (PITR on) is **not recorded as fact**. RPO and RTO above are estimates; the RTO figures are [guessing] until a restore is rehearsed on a disposable copy by the owner, which is not asked for now.
