# M-03: backups, restore points, RPO and RTO of the Production database

First written 2026-10-23 about 04:45Z under owner reply 13; **rewritten about 05:05Z under reply 14** (autonomous audit: establish credible, repeatable evidence by the safest read-only methods, without asking for screenshots first, and never record an inference as verified). **Nothing was changed and no restore was attempted.** No project id, key or customer value is in this file.

**Correction to what I told the owner earlier today:** I wrote that the archiving cadence made point-in-time recovery "probable". Supabase's own documentation says the opposite once the project's compute size is taken into account (section 3). The current best reading is that PITR is **not** enabled and the project has the platform's daily backups.

## 1. Methods compared

| Method | Available here? | What it can tell | Verdict |
|---|---|---|---|
| Supabase Management API `GET /v1/projects/{ref}/database/backups` (the call that returns the backup list, `pitr_enabled`, and the earliest and latest physical backup dates) | **No**: it needs a personal access token for the owner's account. Those tokens are not scoped (a token that can list backups can also delete a project), so the agent will not ask for one | definitive | not usable without a credential the agent should not hold |
| Supabase MCP tools (project, organization, SQL, logs, docs) | Yes, read-only | project facts, database settings and statistics, official documentation; **no tool lists backups or add-ons** | used |
| Supabase CLI | No login, no token | would need the same token | not usable |
| Authorized browser on the owner's Mac (dashboard Backups page) | **No: the paired MacBook has been offline since 2026-10-22 14:52Z** | would be definitive | unavailable now; usable if the Mac comes online (read-only, no clicks that change anything) |
| Read-only SQL on the database itself (`pg_settings`, `pg_stat_archiver`, the archive status directory) | Yes | whether continuous archiving is configured and current; **not** whether the PITR add-on is bought | used |
| Official documentation (Supabase docs search tool) | Yes | what the observed settings imply | used |

## 2. What was read from the database (2026-10-23, 04:23Z and 04:53Z)

| Fact | Value |
|---|---|
| Project | `postriff-phase2-private`, us-east-1, healthy, PostgreSQL 17.6.1.166, 237 MB, created 2026-09-15 |
| Organization plan | Pro |
| Archiving | `archive_mode` on; **`archive_command` = Supabase's `admin-mgr wal-push` writing to the WAL-G log directory** (so the archive goes through Supabase's WAL-G tooling, not a no-op); `archive_timeout` 120 s; 16 MB segments; `wal_compression` zstd; `data_checksums` on |
| Archiver state | **26,579 segments archived, 0 failed**, last archived segment at 04:53:06Z, **0 segments waiting** (`.ready` files), the current segment is the one after the last archived [certain] |
| Compute class | `max_connections` 60, `shared_buffers` about 224 MB, `effective_cache_size` about 384 MB, `work_mem` about 2 MB |
| Application path | through Supavisor (Supabase's transaction pooler); the role's default `statement_timeout` is 120 s |

## 3. What the documentation says (Supabase documentation, read through the docs search tool on 2026-10-23)

- Pro projects get **daily backups**, kept **7 days**; all projects on Postgres 15.8.1.079 and newer use the **physical backup** process (this project is on 17.6).
- **PITR is a paid add-on and "projects that want to use PITR must also use at least a Small compute add-on".** With PITR the daily backups stop ("if you enable PITR, we will no longer take daily backups"); WAL files are archived by WAL-G every two minutes, so the worst-case RPO is two minutes. Prices in the documentation: about US$100 a month for a 7-day window (US$200 for 14, US$400 for 28), not covered by the spend cap; the documentation's own example adds a Small compute at about US$15 a month, with US$10 of compute credits.
- Compute sizes: **Nano and Micro have 60 direct connections and 200 pooler connections; Small has 90 and 400.**
- A restore makes the project **inaccessible**; the downtime grows with database size; the restore replaces the database in place. Restoring to a new project is a separate feature (a new, billable project).

## 4. Reading of the evidence

1. **Compute is Nano or Micro class** [documented table vs the observed 60 connections; likely Micro because it is a Pro project]. The connection limit can be hard-coded by a custom setting, so this is strong but not absolute.
2. **PITR is therefore very probably not enabled** [Likely]: it requires at least Small compute. The WAL archiving seen above is **not evidence of PITR**: all physical-backup projects archive WAL through WAL-G, and the two-minute `archive_timeout` is the platform's setting. (This reverses my earlier reading.)
3. **Daily physical backups probably exist** [platform default for a Pro project; documented, not observed]: the archive pipeline feeding them is demonstrably healthy [certain], but no tool shows a backup entry.
4. **Not verified by any available method:** that the PITR add-on is off; the list and dates of the daily backups; the time of the latest backup; that a restore would work. These stay **UNVERIFIED**.

## 5. RPO and RTO under the probable state, and the other state

| | Daily backups only (probable) | PITR on (improbable) |
|---|---|---|
| RPO | up to about 24 hours: every connection, consent, schedule and approval made since the last daily backup | about 2 minutes (documented) |
| Restore points | the 7 daily backups | any minute within the chosen window |
| RTO | the project is down while a physical backup is restored; for a 237 MB database [guessing] about 10 to 30 minutes including platform overhead; the documentation gives no figure | similar plus WAL replay |
| Who acts | the owner presses Restore in the dashboard (the agent never restores; Production restores need a separate approval) | same |

Assessment [advice]: for a controlled start, daily-only is survivable (customers can reconnect and re-schedule); for a public opening to thousands of workspaces a 24-hour RPO is weak, and it interacts badly with the duplicate-send hazard below. Decision for the owner, with no action now: enable PITR (needs at least Small compute: about US$100 plus about US$5 net a month per the documentation, to be confirmed on the billing page), or accept daily backups and add a second copy the agent cannot create (a scheduled logical export needs a database credential the owner would create). Nothing is bought.

## 6. The restore hazard that is specific to this product: duplicate sends

A restore rewinds the database. A Discord post **sent after the restore point** then looks unsent, and while its approval is still valid the worker would send it again. The duplicate protection lives in the database (intents, leases, the coordinator's admissions), so a rewind removes it for the rewound interval. For any restore: (1) before it, set the operator hold and, if possible, turn the Discord lane flag off; (2) the hold lives in the database too, so set it again immediately after the restore, before the application can run the worker; (3) reconcile the rewound interval against the destination channels; (4) lift the hold only on the Release Captain's word. **This is being drilled in isolation** (a real point-in-time recovery of a throwaway PostgreSQL with the mock Discord), see `RC2-EVIDENCE-PACKET.md`; until the drill has a receipt the hazard is documented, not proven.

## 7. What the owner would have to do, if the agent cannot get the evidence itself

Smallest possible ask, **no screenshot**: one sentence back, read from Supabase, Database, Backups: "the Point in Time tab says X" (it either offers to enable PITR or shows a recovery window) and "Scheduled backups lists N entries, the newest dated D". If the paired Mac comes online, the agent reads that page itself (read-only) and asks nothing.

## 8. Status

M-03 stays **BLOCKED_EXTERNAL** (the facts that matter are not visible to any permitted tool), with a narrowed question and a probable answer (no PITR, daily backups). Nothing here is recorded as verified beyond section 2 and the documentation quotes in section 3.
