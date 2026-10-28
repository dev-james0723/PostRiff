# H-07 POLICY MAP: the owner's on-call policy against the code that exists

The owner adopted the on-call policy in reply 15 (`AUTHORIZATION-RECORD.md`) **as a target, not as a fact**. This page maps every line of it to what the repository does today. Line numbers are from the RC2 integration line `5a94b4f2`, which is the base of this branch. Status words: **EXISTS** (the code does it, behind its flags), **PARTIAL**, **MISSING**, **CONFLICTS** (the code does something the policy forbids). Nothing here is configured in Production; every external channel below is off by default.

## 1. Coverage and people

| # | Policy line | What the code does today (file:line) | Status |
|---|---|---|---|
| 1 | P0 Critical 24/7, weekends and holidays | The founder incident pipeline runs as a stage of the minute cron when `RAFII_CONTROL_ENABLED` is set (`founder_cron.py:116-141`, flag at `:119`). Critical notices break the founder's quiet hours (`founder_notifications.py:55`, `:245`). **But** a phone call is refused inside quiet hours, which default to 22:00 to 08:00 (`founder_contact.py:53-55`, `:189-191`). Calls also stop at 2 a day (`:192-193`). And the consumer planner that every founder notice passes through defers a critical push until the person's own quiet hours end, because only `security` breaks them there (`notifications/planner.py:123`, `:163`; `notifications/catalog.py:57`). | CONFLICTS |
| 2 | Routine handling every day 09:00 to 23:00 America/New_York | Quiet hours exist per operator (founder preferences, default 22:00 to 08:00 in `America/Indiana/Indianapolis`: `founder_notifications.py:69-70`, `live_metrics.py:24`). There is no duty-hours concept, no acknowledgement deadline and no holiday rule. | PARTIAL |
| 3 | Outside those hours monitoring continues; P0 goes to the person on call | Monitoring continues: the minute cron and the 10-minute watchdog (`.github/workflows/founder-watchdog.yml:11`). There is no "person on call": every notice goes to every active founder (`founder_notifications.py:390-407`, recipients from `founder_contact.py:543-547`, at most 10, `founder_notifications.py:68`). | MISSING |
| 4 | A Primary and a Backup are named, and someone actually receives | `founder_operators()` returns every active founder with no role and no schedule (`founder_contact.py:543-547`). A call goes to **one** operator per incident: the attempt key is the purpose and the incident, not the person (`founder_contact.py:70-74`, `:214-220`), so the second founder in the loop at `founder_cron.py:399-400` gets the first one's attempt back. | MISSING |

## 2. Channels

| # | Policy line | What the code does today (file:line) | Status |
|---|---|---|---|
| 5 | Push is the main immediate channel | Web push through the shared outbox (`founder_notifications.py:336-359`, `notifications/planner.py:149-164`, `notifications/push.py`). It needs all of: `RAFII_FOUNDER_PUSH_ENABLED`, `RAFII_WEB_PUSH_ENABLED`, `RAFII_NOTIFICATIONS_V2_ENABLED`, VAPID keys, a subscription from the person's browser, and live delivery plus the `push` channel in the founder contact policy (`founder_notifications.py:227-237`). Push is deferred in the person's quiet hours (`planner.py:163`) and silenced by a mute (`planner.py:122`, `:154`). The only delivery evidence is that the push service accepted it. | PARTIAL (gated, off) |
| 6 | E-mail records the incident, its status and its outcome | E-mail goes out when an incident opens (critical: immediately; warning: in the digest) and when it recovers (digest only) (`founder_incidents.py:35-40`, `founder_notifications.py:212-224`). Acknowledgement and escalation are not e-mailed, and the outcome is only a "recovered" digest line. Delivery goes through Resend with retries (`notifications/delivery.py:24-31`, `:84-90`). | PARTIAL |
| 7 | A phone call is the P0 escalation | `founder_contact.PhoneCalls` through `PhoneService` (`founder_contact.py:354-435`), only for an open, unacknowledged critical incident (`founder_incidents.py:209-211`). The call is placed **at the first tick, not after 5 minutes** (`founder_cron.py:398-400`). It is refused in quiet hours (`founder_contact.py:189-191`), after 2 calls a day (`:192-193`), while another call is active (`:194-195`) and without an approved daily budget (`:184-188`), and happens at most once per incident (`:214-220`). The destination is only the operator's own verified phone row (`:65-67`). | CONFLICTS |

## 3. Escalation, deduplication, suppression, acknowledgement, audit

| # | Policy line | What the code does today (file:line) | Status |
|---|---|---|---|
| 8 | P0: push and e-mail at once | Critical: e-mail and push immediately (`founder_notifications.py:218-219`), still subject to items 5 and 6. | EXISTS (gated) |
| 9 | P0: phone call if not acknowledged within 5 minutes | No timer exists. The call is immediate and suppressed at night (item 7). | MISSING |
| 10 | P0: Backup if not acknowledged within 10 minutes | No Backup, and nothing is sent again (one call per incident). | MISSING |
| 11 | P1: push and e-mail; acknowledged within 15 minutes during duty hours | The nearest is `warning`: e-mail goes to the digest and there is no push (`founder_notifications.py:220-221`). No 15-minute deadline. | CONFLICTS |
| 12 | P2: e-mail or dashboard | `warning`: in-app plus the daily digest (`founder_notifications.py:220-221`, `:439-470`). | EXISTS (approximately) |
| 13 | Deduplication | One open episode per (detector, scope), refreshed rather than duplicated (`founder_incidents.py:155-197`). Notices are idempotent per (operator, environment, dedupe key) (`founder_notifications.py:309-322`, key at `:284`). The outbox has a unique (scope_key, dedupe_key) (`migrations/postriff/024_notification_core.sql:29`). | EXISTS |
| 14 | Alert suppression | Quiet hours (except critical), per-event channel preferences, the digest, rate limits (`catalog.py:59`: a critical push is exempt, `planner.py:156`, but a critical e-mail beyond 12 recent ones goes to the digest, `planner.py:136-137`), mute (`planner.py:122`). There are no maintenance windows, no suppression of dependent alerts and no damping of flapping. | PARTIAL |
| 15 | Incident acknowledgement | `POST /incidents/{id}/ack` (`rafii_control/http.py:266`) and the founder agent tool (`founder_tools.py:883`) call `acknowledge` (`founder_incidents.py:214-234`). It is bound to the version shown and cancels calls that are reserved but not yet dialled. `ACK_CHANNELS` lists `phone` (`:26`) but nothing acknowledges from a call, a push or an e-mail. | PARTIAL |
| 16 | Escalation | Only "critical leads to one call". There is no stepwise escalation and no priority change after opening (severity only rises, `founder_incidents.py:175`). | MISSING |
| 17 | Audit trail | Incident timeline: opened, updated, escalated, refreshed, resolved, acknowledged, `contact_*` (`founder_incidents.py:155-197`, `:355-366`); acknowledgements (`:368-373`); dial decisions in `admin_audit_log` (`founder_contact.py:238-247`); notice-centre rows with the state of each channel (`founder_notifications.py:309-322`); outbox delivery rows (`notifications/delivery.py`). Not recorded: who was on call, and why a step was skipped. | EXISTS for incidents and calls |

## 4. Inputs and the dead-man's switch

| # | Need | What exists (file:line) | Status |
|---|---|---|---|
| 18 | The Discord alerts (42 rule ids, `scripts/discord_ops_check.py`) feed the pipeline | Not connected. `rafii_control.founder_incidents.detector` has a CHECK of four values (`migrations/postriff/055_rafii_control_founder_contact.sql:63`), so a new detector needs an additive migration. | MISSING |
| 19 | The absence of alerts is detected | `founder-watchdog.yml` runs every 10 minutes (`:11`) and fails when the founder cron heartbeat is older than 600 s (`founder_sources.py:177`, `:185-206`, `:247-277`). It needs the repository secret `RAFII_WATCHDOG_DSN`. It notifies only through GitHub (e-mail or app; no call). | PARTIAL |

## 5. Paths that can silence a P0 at night today

All of these are default settings or a person's own settings, so they need no fault to happen:

1. Founder call quiet hours, 22:00 to 08:00 (`founder_contact.py:53-55`, `:189-191`).
2. The cap of 2 calls a day (`founder_contact.py:53-55`, `:192-193`).
3. One call per incident, to whichever founder comes first (`founder_contact.py:70-74`).
4. A critical push deferred until the person's own consumer quiet hours end (`notifications/planner.py:123`, `:163`; `catalog.py:57`).
5. A consumer mute (`planner.py:122`), or more than 12 recent e-mails, which sends a critical e-mail to the digest (`planner.py:136-137`).
6. No live delivery, or no channel, in the founder contact policy (both defaults: `founder_contact.py:53-55`; `founder_notifications.py:227-237`).
7. A flag unset: `RAFII_CONTROL_ENABLED`, `RAFII_FOUNDER_PUSH_ENABLED`, `RAFII_FOUNDER_EMAIL_ENABLED`, `RAFII_FOUNDER_CALLS_ENABLED`, `RAFII_NOTIFICATIONS_V2_ENABLED` or `RAFII_WEB_PUSH_ENABLED`.

The engine on this branch (`src/rafii_control/oncall/`) routes P0 around 1 to 5 by design: its own timers, a roster, no quiet hours for P0, and per-person, per-step idempotency. Items 6 and 7 are the owner's settings.

## 6. The 42 alert rules as P0, P1 and P2 (a proposal the owner edits)

P0 means "wake someone at 3 a.m.": it is dangerous to continue, or every customer is affected now. P1 is handled in duty hours and acknowledged within 15 minutes. P2 is e-mail and the dashboard. The machine-readable copy is `docs/ops/h07-oncall-policy.json` (`priorities`). The first matching row wins; anything not listed falls back to: page is P1, warn is P2.

| Rule id | warn | page | Why |
|---|---|---|---|
| CROSS_TENANT_PROBE_FAILED | | **P0** | isolation is broken. No producer in this build (second review N-5): the Q-05 hosted run would write `security.probe`; until it does, this row never fires |
| CROSS_TENANT_PROBING | P1 | **P0** | active probing of other workspaces |
| CROSS_TENANT_DISCORD | P1 | | a refusal on a Discord route |
| CROSS_TENANT_DISCORD_4XX | P2 | | a superset of refusals; tune first |
| DELIVERY_UNCERTAIN | P1 | **P0** | duplicate or unknown sends (stop condition at 3) |
| DELIVERY_UNAUTHORIZED | | **P0** | bot token rejected or leaked |
| DELIVERY_SYSTEM_FAILURES | P1 | **P0** | many posts failing on our side |
| DELIVERY_STUCK_SENT | P1 | | needs reconciliation |
| DELIVERY_CUSTOMER_FAILURES | P2 | | the customers' server set-up |
| DELIVERY_DISCORD_5XX | P2 | | Discord outage; nothing destructive to do |
| DELIVERY_HELD_GROWTH | P1 | | approvals ran out: customers must approve again |
| DELIVERY_FAILED_GROWTH | P1 | | more posts failing than before |
| RATE_CREDENTIAL_HOLD | | **P0** | every Discord request refused |
| RATE_INVALID_REQUESTS | | **P0** | IP restriction danger for every customer |
| RATE_INVALID_BUDGET | P1 | **P0** | ban danger below 25% |
| RATE_POLICY | P1 | **P0** | expiry stops every request |
| RATE_EMBARGO | P2 | P1 | Discord-side; sleeps itself out |
| RATE_429 | P2 | P1 | coordinator should prevent |
| RATE_APP_BUDGET_SPENT | P2 | | expected in a declared burst |
| RATE_ROUTE_CIRCUITS | P2 | | Discord server errors, or 403 refusals (limiter head), on routes |
| RATE_RETENTION_BEHIND | P2 | | the coordinator's settled rows are not being purged; housekeeping, no customer effect |
| SILENT_HALT_NO_PROGRESS | P2 (only under a hold) | **P0** | nothing sends; approvals lapse after an hour |
| SILENT_HALT_NO_SHARDS | | **P0** | shard crons do not run |
| SILENT_HALT_LANE_NOT_READY | P1 | **P0** | page means no path can send |
| SILENT_HALT_HEALTH_UNANSWERED | | **P0** | monitoring is blind |
| SILENT_HALT_DATABASE | | **P0** | database unreachable |
| SILENT_HALT_PROJECTION | | **P0** | lane stops with "schema" |
| SILENT_HALT_OPERATOR_HOLD | P1 | | a hold is on: decide, approvals lapse |
| SILENT_HALT_LANE_STOPS | P2 | | abnormal shard stop reasons |
| SILENT_HALT_QUARANTINE | P1 | | a workspace set aside after its claim failed: that customer's posts wait, and the cause is a defect to report |
| SILENT_HALT_NO_CREATE | P1 | **P0** | work due and nothing reaches Discord for 30 minutes |
| SILENT_HALT_SECTION | P2 | P1 (persistent) | one payload section is blind |
| BACKLOG_LAG | P2 | P1 | lateness; the no-progress page covers a halt |
| CONFIG_GATE | | P1; **P0 when the gate is open in the canary phase** | an accidental public opening is a security event |
| CONFIG_FLAGS | | **P0** | Discord switches off: posts held |
| CONFIG_REVIEWED | | **P0** | publishing shows unsupported |
| CONFIG_CAP | | P1 | the 91st server refused |
| CONFIG_MISCONFIGURED | | P1 | fails closed |
| CONFIG_CAP_USED | P2 | P1 | decide the next cap |
| CONFIG_KILL_SWITCH | P1 | | expected only in an abort |
| CONFIG_BUILD | P1 | | the serving build is not the recorded one |
| CONFIG_LANE_FLAG | P2 | | expectation drift |

The engine adds rules about itself, all P0: `ONCALL_ROSTER_INVALID` (no Primary or no Backup), `ONCALL_DELIVERY_FAILED` (every channel failed for a step), `ONCALL_AUTO_HOLD_ENGAGED` (option D). It also writes a heartbeat that the external watchdog reads (`ONCALL_HEARTBEAT_STALE`, raised by the watchdog, not by the engine).
