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

## D. Compensating control when no human covers the night: a stop that does not need a person

**The independent review of `8e76afdd` and the Release Captain advise against automating the database hold**, and this memo now agrees: the hold itself strands posts. Measured on the merged head `d864f25f` (disposable PostgreSQL, real worker and coordinator, mock Discord; `PHONE-RUNBOOK.md`):

- while a Discord-claiming worker runs under the hold (the lane flag off or not ready, the RC1 build after a rollback, a customer's "post now"), each created post's read-back burns a check per claim and is **parked for 24 hours** after the fifth, although the message is in Discord; the lift does not bring it back;
- a post needs **a new approval from about 55 minutes after its own scheduled time**, so a hold through the night turns the morning's queue into re-approvals;
- the hold lives in the database, so a restore rewinds it.

What remains of option D, as owner decisions, none of them on by default:

| | |
|---|---|
| D1. Automatic database hold (`src/rafii_control/oncall/autohold.py`, flag `RAFII_ONCALL_AUTO_HOLD_ENABLED`, off) | Kept in code only so the owner can choose it with the facts above. If chosen, it engages only on `CROSS_TENANT_PROBE_FAILED` (a confirmed isolation failure), never on probing (a refusal is the gate working), runs the runbook's own `HOLD_ON`, which must return a row, reads it back, opens its own P0 and never lifts the hold. A false positive pauses Discord for everyone until a person lifts it. It is an automated write to the Production database, so enabling it is a Production change. |
| D2. The Discord-paused build, prepared in advance | The serving SHA staged with a rate policy that does not parse: every process refuses Discord requests before sending, nothing is held, parked or marked uncertain, and it survives a restore (the restore lane's drill, `RESTORE-RUNBOOK-PROPOSAL.md` 4.J, a proposal not in force). It needs a person to promote it (a Production operation), so it is not automatic; it is the lever a woken person should prefer when the lane does not own Discord. Packet 3 row 12b prepares it. |
| D3. Smaller exposure instead of a stop | Open with a smaller server cap, or keep the canary gate, until night cover exists (a business decision). |

**Who lifts any stop:** only a person, the Release Captain or the Primary on the captain's word. Cost class of D1 to D3: none beyond a staged build.

## Recommendation [advice]

1. **Before the public opening:** the owner names a Primary and a Backup and says honestly whether P0 is covered at night. If not, H-07 is **BLOCKED** (see `H07-EVIDENCE.md` for the rule).
2. **Fastest path to VERIFIED:** **B with C**. A paging service gives calls, rotations, acknowledgement and an outside heartbeat on day one; the GitHub watchdog is a second, free-ish dead-man's switch. Cost: a per-responder subscription.
3. **No new vendor:** **A with C**. Use this branch's engine with the existing push, e-mail and phone integrations. It needs the P0 call-policy change reviewed, the migration applied and the adapters built; it shares fate with the application, so C is mandatory.
4. **While nights are not truly covered:** prepare D2 (the paused build) so a woken person has a stop that strands nothing, and decide D3. D1 (an automatic database hold) is not recommended: it strands posts (see D).
5. If neither a night person nor D is acceptable, the alternatives are:
   - open only with a smaller server cap, accepting the night risk for a limited audience;
   - delay the public opening until a Backup exists (for example in another time zone).

   These are business decisions; the agent will not make them.
