# ALERT CHANNELS and the dead-man's switch (H-07)

Written 2026-10-23 for owner reply 13 ("alerts ... and the real on-call hours and alert-receiving channels confirmed before public"); owner reply 15 then adopted the on-call policy as the target (`H07-POLICY-MAP.md`, `H07-OPTIONS.md`). **Nothing here is configured, enabled or changed in Production by this branch; H-07 is BLOCKED until a named Primary and Backup cover P0 at night and the real tests pass (`H07-EVIDENCE.md`).** What exists in code is marked as such; what is only designed says so.

## 1. What the repository can already deliver to a person

| Channel | Code that exists | What it needs (names only) | Reaches the owner with the Mac offline? |
|---|---|---|---|
| Founder incident centre (in-app) | `rafii_control/founder_incidents.py`, `founder_cron.py` (a stage of `/api/cron/worker`, every minute) | `RAFII_CONTROL_ENABLED`, `RAFII_CONTROL_SESSION_DSN`, `RAFII_CONTROL_READER_DSN`, `RAFII_CONTROL_ENVIRONMENT`; migrations 055 and 067 | only when someone opens Founder Control: not a pager |
| Founder e-mail | `founder_notifications.py` through the shared outbox (`notifications/delivery.py`) | the above plus `RAFII_NOTIFICATIONS_V2_ENABLED`, `RESEND_API_KEY`, `EMAIL_FROM`, `RAFII_FOUNDER_EMAIL_ENABLED`, and the founder contact policy with live delivery and the `email` channel on | yes (phone mail app); critical and security notices break quiet hours |
| Founder web push | same path, `notifications/push.py` | the above plus `RAFII_WEB_PUSH_ENABLED`, `POSTRIFF_VAPID_PUBLIC_KEY`, `POSTRIFF_VAPID_PRIVATE_KEY`, `POSTRIFF_VAPID_SUBJECT`, `RAFII_FOUNDER_PUSH_ENABLED`, a push subscription from the owner's phone browser | yes, while that subscription lives |
| Founder phone call | `founder_contact.py` through `PhoneService` (only for an open, unacknowledged **critical** incident) | `RAFII_FOUNDER_CALLS_ENABLED`, `RAFII_PHONE_*` and the provider credentials (`TWILIO_*` or the dial provider), `RAFII_FOUNDER_OPS_WORKSPACE_ID`, a verified number, a daily budget | yes; costs per call; daily and concurrency caps |
| GitHub Actions failure notice | `.github/workflows/founder-watchdog.yml` every 10 minutes, `founder_sources.watchdog_main` | repository secret `RAFII_WATCHDOG_DSN` (a read-only login in role `rafii_control_watchdog`, migration 066); without it the job passes with a "not configured" notice | yes (GitHub e-mail or mobile app, to the user who last changed the schedule); independent of Vercel |
| Scheduled Claude check-in | a session the owner's account schedules (not code in this repository) | the Supabase and Vercel connectors, read-only use | yes, as a push in the Claude app; best effort |

Today's detectors in that pipeline are `publish_failure_rate` (all platforms, from notification events), `source_silence`, `cost_anomaly` and `payment_failure_spike`; none of them is Discord-specific. Which of the names above are set in Production is not visible to this lane (the owner's `vercel env ls` shows names).

## 2. What this branch implements, and why delivery is not wired

Implemented: the protected read-only payload `GET /api/ops/discord/health` (cron secret), its SQL twin `docs/ops/discord-ops-snapshot.sql`, the rules and thresholds (`scripts/discord_ops_check.py`, `docs/ops/discord-alert-thresholds.json`, 47 alert ids), the cross-tenant log line `security.cross_tenant_denied`, the phone runbook and the isolated drills; and, off and not wired, the on-call engine `src/rafii_control/oncall/` (routing, escalation, acknowledgement, audit, heartbeat; migration 140, not applied) with fake providers only. **Not implemented: any delivery to a person.** The one channel that pages (founder incidents, then e-mail, push and a call) cannot take a new detector without (a) a migration, because `rafii_control.founder_incidents.detector` has a CHECK listing the four detectors above, (b) a line in `rafii_control/slices.py`, which this lane may not edit, and (c) a reviewed decision on phone-call cost. A flag alone would not have made it work, so it is a proposal (section 3).

Signals not yet covered: the cross-tenant line is written only by the membership gate (the uniform 403, the probe's
"workspace-scope" style). The 404 and 409 object-binding refusals (another tenant's connection, identity, job or OAuth
state named from one's own workspace: `_member_grant` and the callback binding in `oauth.py`, `read_credential` and the
identity lookups in `discord/oauth.py`) are spread over several security-sensitive sites and also answer ordinary stale
screens, so they were not touched; the proposal is the same capped, id-free line at each site with its own event name,
reviewed with the final SHA. Until then those probes are visible only as 4xx counts by route family
(`CROSS_TENANT_DISCORD_4XX`) and in the Q-05 probe's own receipts.

## 3. The minimal set that works with the Mac offline (recommendation)

1. **Primary pager: founder incidents.** A founder cron stage `discord_ops` (flag `RAFII_DISCORD_OPS_ALERTS_ENABLED`, default off) runs `discord.ops.snapshot()` in process (no HTTP, no secret) and the evaluator each minute; each `page` alert opens or refreshes a **critical** incident (detector `discord_ops`, scope the alert id), each `warn` a **warning**; a cleared alert resolves its episode. The existing routing then does the rest: critical means immediate e-mail and push, outside quiet hours too, and a phone call if nobody acknowledges; warnings go in-app and to the daily digest.
2. **Dead-man's switch outside Vercel: a Discord watchdog workflow**, modelled on `founder-watchdog.yml`: every 10 minutes, a read-only database login runs the SQL twin, `discord_ops_check.py evaluate` fails the job on any `page` (GitHub notifies), and the job also fails when the query cannot run. It does not depend on the Vercel crons, the function, or the founder pipeline it watches.
3. **Agent check-in (best effort, explicitly not 24/7 cover):** within the confirmed on-call hours, a scheduled session every 30 minutes runs the SQL twin through the Supabase connector (read-only), reads the last 15 minutes of Vercel runtime logs for `discord.lane.completed`, `discord.lane.lagging` and `security.cross_tenant_denied` lines, evaluates with `--logs` and `--previous` (so it notifies on new and cleared alerts only), and sends a push to the owner on a page, with the alert id and the runbook row. It never lifts a hold and changes nothing in Production; a missed run, an expired connector login or a usage limit means silence, which is why it is the third layer, not the first.

Never give `CRON_SECRET` to an external uptime monitor: it also starts the worker and the 12 shards. The designed alternative (review finding M9, migration 141, **not applied**): `SELECT public.pr_discord_ops_snapshot()` through a dedicated login that can execute that one function and read no table; applying it and creating the login are owner steps (`H07-EVIDENCE.md` section 6).

## 4. The dead-man's switch: how the absence of alerts is detected

Each layer watches the one below it, so silence is never trusted:

| Layer | Watches | Detects | Misses |
|---|---|---|---|
| Founder stage (proposed) | the Discord lane, the coordinator, the configuration | every rule of `discord_ops_check.py`; `SILENT_HALT_NO_PROGRESS` when due work has no claim and no admission for 3 minutes | itself, when the minute cron stops |
| `founder-watchdog.yml` (exists; needs `RAFII_WATCHDOG_DSN`) | the founder cron heartbeat row (`source_health.cron`, stamped every minute) | the minute cron, or the founder stage, not running for 10 minutes | the shards; a database it cannot reach shows as a failure, which is right |
| Discord watchdog workflow (proposed) | the database itself, without Vercel | the Discord rules from the SQL twin, every 10 minutes | process-only facts (gate, cap, flags); GitHub can delay or drop scheduled runs under load (and disables schedules in a public repository after 60 days without activity) |
| On-call engine heartbeat (built, off) | the engine itself (`rafii_control.oncall_heartbeat`, migration 140) | a watchdog reading only that row (`rafii_control_watchdog`) fails when it is older than 180 s, a P0 is unacknowledged past the whole chain, the roster cannot carry P0, or deliveries failed (`engine.heartbeat_alerts`) | the evaluator below it, which the engine's own `SILENT_HALT_*` rules watch |
| Daily all-clear (proposed, owner habit) | all of the above | the founder digest e-mail (or the check-in's daily summary) arriving at a fixed hour; **a missing all-clear is itself the alarm** | anything shorter than a day |

Heartbeat rule for the owner: if neither the daily digest nor the check-in summary arrived by the agreed hour, treat it as an incident and open the phone runbook's `SNAPSHOT` statement.

## 5. What the owner decides or configures (nothing is done until then)

| Item | Owner's action | Cost | Privacy |
|---|---|---|---|
| On-call hours | reply 15 set the target: P0 24/7, routine handling 09:00 to 23:00 America/New_York every day. Name the Primary and Backup who carry it, and say honestly whether nights are covered (`H07-EVIDENCE.md`) | none | none |
| Channels | choose e-mail, push and/or a call for critical; set the founder contact policy's live delivery (Founder Control, step-up) | e-mail cents, push free, calls per minute | notices carry fixed titles, counts and a link; never customer content |
| Production variables for the chosen channels | approve the names in section 1 (each change needs a build; reply 13 requires item-by-item approval) | a build each | none |
| Phone push subscription, verified number, ops workspace | from the owner's phone | none | the owner's own number only |
| Watchdog secrets | create the read-only login for `RAFII_WATCHDOG_DSN`; for the proposed Discord watchdog, a second read-only login limited to the five tables the SQL twin reads (a reviewed migration) | GitHub Actions minutes | the login can read counts only through those tables' columns; never printed |
| The proposed founder stage and its migration | approve the design in sections 3 and 4 for the final SHA | review time | counts and codes only |
| Thresholds | confirm or change `docs/ops/discord-alert-thresholds.json`; every run names its phase (`--phase canary`, then `open`) | none | none |
| A stop that survives a restore | approve preparing the Discord-paused staged build (`PHONE-RUNBOOK.md` lever 2; the restore lane's `RESTORE-RUNBOOK-PROPOSAL.md` 4.J, a proposal not in force) | build minutes | none |
| Check-in schedule | approve the agent's scheduled check-in for the on-call hours | the owner's plan usage | read-only aggregates |
