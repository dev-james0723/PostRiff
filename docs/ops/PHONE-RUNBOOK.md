# PHONE RUNBOOK: stop, close and roll back Discord with the Mac offline (H-07)

Everything here needs only a phone browser: the **Supabase dashboard SQL editor** (project `postriff-phase2-private`) and the **Vercel dashboard** (team `team_PgXY5VdAYKcsv0RLoDPHscNq`, project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`), or an agent using the same through its connectors. Alert ids come from `scripts/discord_ops_check.py`; severities and thresholds from `docs/ops/discord-alert-thresholds.json`. Rules that never bend: stop first, investigate second; never resend an uncertain post; holds are lifted only on the Release Captain's word; every action is written in the ledger with the time (UTC). Whoever acts tells the owner (James, Release Captain) at once. **This does not make H-07 VERIFIED**: the on-call hours and the alert channels are the owner's to confirm (`ALERT-CHANNELS.md`).

## The levers, fastest first

1. **Hold** (seconds, no deploy): the `HOLD_ON` statement below. Every Discord request (posts, reads, connects) is refused before it is sent; queued posts wait, nothing is lost. Approvals last an hour, so a hold longer than that means re-approvals. Works only on a build with `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED=true` (and, for login-token refreshes, commit `29bc8ab2` or later).
2. **Close new connections only** (seconds): promote the **dark twin** of the serving SHA (its deployment id is in the release record). Existing connections and queued posts keep working.
3. **Roll back the serving build** (seconds, no rebuild): promote the previous production deployment (below).
4. **Kill switch** (a build, about 3 minutes, needs the owner's approval): a twin with `POSTRIFF_OAUTH_DISCORD_DISABLED=true`.

## Symptom, first action, undo

| Symptom | Alert id (severity) | First action | Undo | Tell |
|---|---|---|---|---|
| Cross-tenant data seen, or one member refused other workspaces many times, or a failing isolation probe | `CROSS_TENANT_PROBING` (page), `CROSS_TENANT_PROBE_FAILED` (page), `CROSS_TENANT_DISCORD` (warn) | `HOLD_ON`, then close new connections; keep the log lines (actor key only) | captain's word: `HOLD_OFF`, promote the open build | owner now; privacy path, RUNBOOK-INCIDENT 4.H |
| Posts may have reached Discord with no answer; a wrong or unapproved send | `DELIVERY_UNCERTAIN` (page at 3) | `HOLD_ON`; never resend; reconcile by read-back only | `HOLD_OFF` after the cause is known | owner |
| Bot token rejected (401) | `DELIVERY_UNAUTHORIZED`, `RATE_CREDENTIAL_HOLD` (page) | `HOLD_ON` (stops a 401 storm); only the owner resets the token, then a new build | `HOLD_OFF` once the new build answers | owner (only the owner can rotate) |
| Near a Discord IP restriction | `RATE_INVALID_BUDGET` (page below 25%), `RATE_INVALID_REQUESTS` (page) | close new connections; if it keeps falling, `HOLD_ON` | promote the open build after the window resets and the cause is known | owner |
| Discord outage, 5xx, embargo | `DELIVERY_DISCORD_5XX`, `RATE_EMBARGO`, `RATE_ROUTE_CIRCUITS` (warn; embargo over 5 min pages) | nothing destructive: watch discordstatus.com, post the customer notice (RUNBOOK-INCIDENT 5) | none | owner, for information |
| Rate policy expiring or expired | `RATE_POLICY` (warn under 7 days, page under 1 or invalid) | renew: `scripts/discord_rate_policy.py generate`, owner sets the variable, a build and a promotion | none | owner (an environment change needs the owner's approval) |
| Work is due and nothing is claimed or sent | `SILENT_HALT_NO_PROGRESS`, `SILENT_HALT_NO_SHARDS`, `SILENT_HALT_LANE_NOT_READY` (page) | if it began after a promotion, roll back the serving build; otherwise read the payload's `lane.blocker` and `config` and fix the named cause | promote again | owner |
| The health payload does not answer | `SILENT_HALT_HEALTH_UNANSWERED`, `SILENT_HALT_DATABASE` (page) | open `https://rafii.io/api/health` and the Supabase and Vercel status pages; run `SNAPSHOT` below; roll back if it followed a promotion | as above | owner |
| Posts late | `BACKLOG_LAG` (warn above 5 min, page above 15) | was a burst declared? If not, treat as a halt (row above) | none | owner if it pages |
| A build without the open settings is serving | `CONFIG_GATE`, `CONFIG_CAP`, `CONFIG_REVIEWED`, `CONFIG_FLAGS` (page) | promote the recorded open build again; find which lane built the other | promote back | owner, and the lane that built it |
| Server cap filling | `CONFIG_CAP_USED` (warn 80%, page 90%) | compare with the Developer Portal count (RUNBOOK-LAUNCH 6) | none | owner decides the next cap |
| A hold is on | `SILENT_HALT_OPERATOR_HOLD` (warn) | ask the captain whether it should still be on | `HOLD_OFF` on the captain's word | captain |

## The statements (paste into the Supabase SQL editor; each is one block)

```sql
-- H07:HOLD_ON  stop every Discord request (application-wide policy row)
UPDATE public.pr_discord_rate_state SET manual_hold = true WHERE kind = 'policy';
```

```sql
-- H07:HOLD_OFF  resume, only on the Release Captain's word
UPDATE public.pr_discord_rate_state SET manual_hold = false WHERE kind = 'policy';
```

```sql
-- H07:HOLD_READBACK  run after either statement
SELECT count(*) AS policy_rows,
       count(*) FILTER (WHERE manual_hold) AS held,
       (SELECT round(extract(epoch FROM now() - reserved_at)) FROM public.pr_discord_request_admissions
         ORDER BY request_seq DESC LIMIT 1) AS seconds_since_last_request
FROM public.pr_discord_rate_state WHERE kind = 'policy';
```

Healthy: `policy_rows 1, held 0`, and `seconds_since_last_request` small while posts are going out. Held: `policy_rows 1, held 1`, and `seconds_since_last_request` keeps growing (run it again after two minutes; a step already in flight may finish, nothing new starts). **`policy_rows 0` means the hold cannot work by `UPDATE`** (no request was ever admitted on this database, for example after a restore to an early point): run `HOLD_INSERT` with the Discord application id (Developer Portal, General Information; it is public), then the read-back again.

```sql
-- H07:HOLD_INSERT  only when HOLD_READBACK shows policy_rows 0; replace the id between the quotes
INSERT INTO public.pr_discord_rate_state(scope_key, kind, limit_count, remaining, window_seconds, reset_at,
                                         manual_hold, policy_revision, policy_expires_at)
VALUES ('00:' || encode(sha256(convert_to('DISCORD_APPLICATION_ID', 'UTF8')), 'hex'), 'policy', 1, 0, 1, now(),
        true, 'operator-hold', now())
ON CONFLICT (scope_key) DO UPDATE SET manual_hold = true;
```

```sql
-- H07:DRAIN_CHECK  before rolling back to an older worker; also monitoring Q7 and M2
WITH sample AS MATERIALIZED (
    SELECT state FROM public.pr_workspaces
    WHERE state ? 'phase2' AND NOT state ? 'accountDeletion' AND NOT state ? 'accountBlock'
    ORDER BY id LIMIT 5000
), jobs AS MATERIALIZED (
    SELECT j FROM sample s CROSS JOIN LATERAL jsonb_array_elements(coalesce(s.state #> '{phase2,jobs}', '[]'::jsonb)) j
    WHERE j #>> '{manifest,platform}' = 'Discord'
)
SELECT count(*) FILTER (WHERE j ->> 'leaseOwner' IS NOT NULL
                          AND (j ->> 'leaseUntil')::double precision > extract(epoch FROM clock_timestamp())) AS live_leases,
       count(*) FILTER (WHERE j #>> '{discordWorker,stage}' = 'sealed') AS sealed_now,
       count(*) FILTER (WHERE j ->> 'state' = 'uncertain') AS uncertain_to_reconcile
FROM jobs;
```

`SNAPSHOT`: `docs/ops/discord-ops-snapshot.sql` is the whole health picture as one row of JSON (read-only, counts only), for when the protected route cannot be called from a phone (a browser cannot add its header).

## Roll back the serving build (no rebuild)

- **Phone:** Vercel dashboard, project, **Deployments**; open the deployment to return to (the release record names it: the previous production deployment, or for a code defect in Discord v2 `dpl_47SGxEqVXPtKMZWXt2kAE9C4ooRg`); menu (three dots), **Promote** (for a staged twin) or **Instant Rollback** (for a previous production deployment); confirm. Then open `https://rafii.io/api/health` and check `sourceRevision`; with the cron secret, `/api/ops/discord/health` shows `build.deploymentId`.
- **Agent or any logged-in machine:** `vercel promote <deployment url or id> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`, or `vercel rollback <deployment id> --scope team_PgXY5VdAYKcsv0RLoDPHscNq`, or the Vercel connector's promote and rollback actions (the REST endpoints behind them are the project promote and rollback calls; confirm the exact path in the Vercel documentation before scripting it).
- Each promotion is a Production change that needs the owner's approval, except the abort steps the owner pre-authorised (AUTH-7: hold and dark-twin promotion). Promoting never rebuilds; environment changes reach only new builds.

## Before rolling back to an older worker: the order

1. `HOLD_ON`, then `HOLD_READBACK` (held 1).
2. Wait two minutes (a lease lasts 45 s; a step in flight finishes), then `DRAIN_CHECK`: **`live_leases 0` and `sealed_now 0`** before switching. `uncertain_to_reconcile` is reconciled by read-back by either worker, never resent.
3. Promote the older build; read back the alias.
4. `HOLD_OFF` on the captain's word; `HOLD_READBACK` (held 0); watch `BACKLOG_LAG` and `SILENT_HALT_NO_PROGRESS` clear. The rollback to `dpl_47SGx…` (no Discord v2 code) additionally needs every Discord job terminal (monitoring Q7), because that build does not know the v2 manifests.

## After any database restore (M-03 section 6)

A restore rewinds the database, and the duplicate protection (intents, leases, coordinator admissions) lives in the database, so a post sent after the restore point looks unsent and would be sent again while its approval lasts. And **the hold is in the database too**, so the restore can remove it. Therefore: (1) before restoring, `HOLD_ON` and stop the senders outside the database (promote a kill-switch twin, or have the owner disable the project's cron jobs in Vercel settings); (2) **immediately after the restore, before any worker runs: `HOLD_ON` again, `HOLD_READBACK` must show held 1** (use `HOLD_INSERT` if it shows policy_rows 0); (3) reconcile every Discord post of the rewound interval against the destination channels; (4) re-enable the senders, then `HOLD_OFF` only on the captain's word. The restore drill itself is another lane's (`RC2-EVIDENCE-PACKET.md`); until it has a receipt this is documented, not proven.

## Not covered

No 24/7 cover exists: alerts reach a person only through the channels the owner configures (`ALERT-CHANNELS.md`), inside the hours the owner confirms. Not drilled on Production: the SQL editor from a phone, a real promotion or rollback, the Vercel log pipeline, real alert delivery (`DRILL-RECEIPT-ISOLATED.md` says what the isolated drills prove). The hold does nothing on a build with rate limits off; closing connections by promoting the dark twin assumes a build-level gate wins over a project variable, which is unproven (`DURABLE-OPEN-CONFIG-PROPOSAL.md` 3.3). The token reset, the policy renewal and the kill switch need the owner and a build. Rollback targets older than Vercel's deployment retention may no longer exist: check the target is listed before relying on it. Message deletion in Discord is the owner's decision only.
