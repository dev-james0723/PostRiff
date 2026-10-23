# H-07 OPTIONS: how the on-call policy can be met

Reply 15 adopted the policy (`H07-POLICY-MAP.md`). This memo compares four ways to meet it. Effort figures are the agent's estimates of engineering time, labelled as such, not quotes. Costs are cost **classes**: no vendor is chosen here and no price is asserted as fact. Nothing in Production changes until the owner approves each item. **With no real 24/7 P0 person, H-07 is BLOCKED whichever option is chosen.** Option D reduces the harm in that case; it does not replace the person.

## A. Extend the in-app founder pipeline

**What it is.** The engine on this branch (`src/rafii_control/oncall/`) becomes a founder cron stage, behind `RAFII_ONCALL_ENGINE_ENABLED`, default off. Each minute it takes the evaluator's alerts and does five things:

- routes P0, P1 and P2 by the policy;
- deduplicates and suppresses (maintenance windows, dependent alerts, flapping, storm limits);
- runs the 5-minute and 10-minute escalation from a Primary and Backup roster, with America/New_York duty hours handled across daylight saving;
- records every step in an append-only audit;
- delivers through adapters to what already exists: push and e-mail through the founder outbox, calls through `PhoneService`.

Persistence is an additive migration (`migrations/postriff/140_rafii_control_oncall.sql`, **not applied**).

| | |
|---|---|
| Built here, isolated | The engine, policy, roster, hours, store (in memory and PostgreSQL), fake providers, automatic hold, and a drill with a receipt. |
| Still to build | Real adapters: push and e-mail through `founder_notifications.emit_outbox`, and a P0 call path that skips founder quiet hours and the daily cap of 2, **which is a policy change to review**. Also: acknowledge links signed into push and e-mail, a roster screen in Founder Control, the founder cron stage registration (one line in `rafii_control/slices.py`), and applying the migration. Estimate [guess]: 3 to 5 engineering days plus review. |
| Risk | **Shares fate with the application**: the same Vercel deployment, database and minute cron. If the cron stops or the database is down, nothing pages, so it needs option C or B as the dead-man's switch. Web push needs the person's browser subscription (on iPhone, the web app added to the home screen). Delivery evidence is only "accepted by the push service or the mail provider". |
| Cost class | Low. E-mail is the existing provider. Push is free. Calls use an existing provider integration (Twilio, Telnyx or Dial: per-minute charges and a number rental), which is a **paid service and needs the owner's approval**. |
| Owner must | Name the Primary and Backup. For each: verify a phone number in the ops workspace, subscribe push on the phone, give an e-mail address. Set the founder contact policy. Approve the flags, the migration, the call provider and its daily budget. |

## B. An external on-call and paging service, driven by the evaluator

**What it is.** A vendor-neutral adapter (`trigger`, `acknowledge`, `resolve`, each with a deduplication key, plus a heartbeat) sends the evaluator's alerts to a paging service. The vendor does schedules, rotations, the escalation policy, push, SMS and phone calls, acknowledgement from its own app, and the audit trail. A vendor "heartbeat" monitor pages when Rafii's check-ins **stop arriving**, which is the dead-man's switch, independent of Vercel and Supabase. Nothing beyond codes and counts leaves Rafii (no customer data).

| | |
|---|---|
| Effort [guess] | 1 to 2 days: the adapter (an HTTP POST from the founder cron stage and from the GitHub watchdog), a secret, and a test procedure. The engine on this branch can still do suppression and deduplication before sending, or leave them to the vendor. |
| Risk | A new data processor and an outbound dependency. The integration key is a secret to rotate. Vendor outages exist, but they are independent of Rafii's own. |
| Cost class | Paid, usually a subscription per user per month (tens of US dollars per responder for tiers that include calls, typically; some free tiers exist with limits). The owner picks and pays; the agent does not choose on authority. |
| Owner must | Choose the vendor; create the account and service; invite the Primary and Backup, each installing the vendor app on their phone and verifying a number; set the escalation policy to 0, 5 and 10 minutes; give the integration key and the heartbeat URL as secrets; approve the outbound calls. |

## C. Hybrid: a GitHub Actions scheduled watchdog as the independent dead-man's switch

**What it is.** A workflow like `founder-watchdog.yml` runs every 10 minutes from GitHub, not from Vercel. It reads `docs/ops/discord-ops-snapshot.sql` and the on-call heartbeat through a read-only database login, runs the evaluator, and **fails** on any P0 or on a stale heartbeat. GitHub then notifies.

| | |
|---|---|
| What GitHub notifications can do | E-mail, and a push from the GitHub mobile app, to **the user who last changed the workflow's cron line**, according to that person's notification settings. They are independent of Vercel, the application and the founder pipeline. |
| What they cannot do | No phone call. No escalation to a Backup. No acknowledgement (each failed run notifies again). No schedule-aware routing. Runs can be delayed or dropped when GitHub is busy; scheduled workflows run only on the default branch, and in a public repository are disabled after 60 days without activity. |
| Effort [guess] | Half a day: the workflow and an additive migration for a read-only role over the tables the SQL twin and the heartbeat read. |
| Cost class | GitHub Actions minutes. Every run bills at least a minute, so a 10-minute schedule is about 4,300 minutes a month on a private repository; whether that fits the plan's included minutes is on the owner's billing page [unverified]. The existing founder watchdog already runs at this cadence. |
| Owner must | Create the read-only login (a secret) and approve the role migration. Make sure the GitHub notification settings send failed workflow runs to the phone. |
| Combine with | A (in-app paging plus an outside watchdog) or B (where the vendor's heartbeat replaces it). |

## D. Compensating control when no human covers the night: the automatic hold

**What it is.** For the P0 classes where continuing is dangerous, the engine sets the operator hold itself: the same `HOLD_ON` statement as `PHONE-RUNBOOK.md`. Implemented here as `src/rafii_control/oncall/autohold.py`, flag `RAFII_ONCALL_AUTO_HOLD_ENABLED`, default off, drilled on a disposable database.

| | |
|---|---|
| Engages on | `CROSS_TENANT_PROBE_FAILED`, `CROSS_TENANT_PROBING` (page), `DELIVERY_UNCERTAIN` (page: duplicate-send suspicion), `RATE_INVALID_REQUESTS` and `RATE_INVALID_BUDGET` (page: an IP restriction would hit every customer). Runaway sending is already capped by the coordinator, and a duplicate shows up as `DELIVERY_UNCERTAIN`. |
| Never engages on | Backlog, silent halt, configuration or policy alerts: a hold makes them worse. **A hold longer than about an hour lets approvals expire**, so queued posts need re-approval; it must never be used for a backlog. |
| Consequences | Every new Discord request is refused for every customer: posts wait, reads and connects fail with "coordination unavailable". A create whose permit was reserved just before can still post (at most one step per running loop). Customers see delays. Nothing is deleted or resent. |
| Who lifts it | Only a person: the Release Captain, or the Primary on the captain's word, with `HOLD_OFF` and its read-back. **Never automatic.** The engine sends its own P0 (`ONCALL_AUTO_HOLD_ENGAGED`) and audits the decision. |
| Risk | A false positive pauses Discord for everyone until morning. The detection must therefore stay strict (page level only), and the owner accepts the trade-off explicitly. It is an automated write to the Production database (the service role the application already uses), so enabling it is a Production change needing approval. |
| Cost class | None. |

## Recommendation [advice]

1. **Before the public opening:** the owner names a Primary and a Backup and says honestly whether P0 is covered at night. If not, H-07 is **BLOCKED** (see `H07-EVIDENCE.md` for the rule).
2. **Fastest path to VERIFIED:** **B with C**. A paging service gives calls, rotations, acknowledgement and an outside heartbeat on day one; the GitHub watchdog is a second, free-ish dead-man's switch. Cost: a per-responder subscription.
3. **No new vendor:** **A with C**. Use this branch's engine with the existing push, e-mail and phone integrations. It needs the P0 call-policy change reviewed, the migration applied and the adapters built; it shares fate with the application, so C is mandatory.
4. **In every case, D** while nights are not truly covered: it limits the damage of the dangerous classes, at the price of a paused Discord until someone lifts the hold.
5. If neither a night person nor D is acceptable, the alternatives are:
   - open only with a smaller server cap, accepting the night risk for a limited audience;
   - delay the public opening until a Backup exists (for example in another time zone).

   These are business decisions; the agent will not make them.
