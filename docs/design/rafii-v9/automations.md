# Automations (Phase 1): hub and builder on the existing campaign engine

Status: implemented on `rafii-v9-integration`, verified locally (see Verification). Not deployed.

## What it is

An automation prepares drafts on a schedule for the accounts a person chooses. It never schedules or
publishes: every run writes drafts into a conversation that waits for review, exactly like Home.
Built on the existing campaign engine (`campaigns.py`, `campaign_worker.py`, migration 018 tables);
no SQL or table change.

- **Hub** `/app/automations` (`web/src/features/automations/automations-view.tsx`): summary (active,
  needs you, drafts this week, next run), weekly budget ceiling, one card per automation (schedule,
  destinations, content type, writer, next and last run, run history, owner actions), briefs without a
  schedule, cancelled list. Sidebar: Create → Automations (`g a`).
- **Builder** (`automation-builder.tsx`), four steps in one dialog:
  1. What: name, brief, audience, event date and venue, content type from the Content Library (or
     general writing), optional sources.
  2. When: any weekdays, a time, a time zone, and a preview of the next three runs (also in the
     viewer's own time when the zones differ).
  3. Where: accounts or folders through Channel Bloom, one or more languages per account; platform
     rows when no account is connected. Up to 10 drafts a run.
  4. Review: writer, reasoning, cost limit per run, weekly budget, summary, then Save as draft or
     (owners) Save and activate.
- **Home** keeps Rafii suggestions and replaces the old campaign form with a compact Automations
  panel. A suggestion that points at a campaign opens that brief in the builder.

## Commands (single mutation channel)

| action | who | effect |
|---|---|---|
| `raffi_recurrence_save` | edit | Create (optionally on an existing `campaignId`) or edit an automation. Validates schedule (weekdays, HH:MM, IANA zone), destinations (supported platform, known language, live account on that platform, 1–10), content type (offered in this workspace, current version), sources (active, not voice samples), writer (not the legacy `local-cli`), reasoning, cost limit (0–$10). Any change to what would be drafted returns it to `draft`, versions it, re-digests it and cancels pending runs; renaming keeps its status. |
| `raffi_recurrence_activate` | owner | Requires the event facts, live accounts and an offered content type; recomputes the next run from now (a draft saved last week never fires immediately). |
| `raffi_recurrence_pause` / `resume` / `cancel` | owner | Unchanged. |

The authorized definition (`definitionDigest`, authority version 2) covers campaign version, schedule,
destinations, content type, writer, reasoning, sources and cost limit. Display fields (name, folder
label, account labels, content label) are outside it.

## Worker

- Drafts every activated destination in one run (one draft per account and language), with the
  automation's own content type, not the one Home has selected.
- Channels, languages, times or "remember…" phrases inside the brief stay text: they never re-route
  drafts, create a schedule plan or become memory.
- An account disconnected since activation is skipped with a note on the run and in the conversation;
  with none left the run is held and the automation pauses (`destinations_unavailable`).
- Unchanged guarantees: cost limit checked before any provider call, lease and idempotency per run,
  more than a day late is missed (not caught up), owner authority re-checked, never a publish job.
- Conversation title: "<name> · <local date>".

## Verification

See the Verification table in this file's commit message and `evidence/automations/<browser>/report.json`.

- Python unit: `tests/test_postriff_campaigns.py` (13): weekdays, save create/edit/refusals, rename vs
  definition change, activation rules, existing briefs, disconnected accounts, content-type override.
- PostgreSQL: `tests/phase2/postgres_consumer_campaign_worker.py`: two accounts in one run with the
  automation's content type, brief text stays data (no Instagram, no plan, no memory), disconnected
  account skipped with a note, none left → paused, plus the existing lease/idempotency/cost cases.
- Node: `web/src/features/automations/schedule.test.cjs` (5): the preview matches the server,
  including the spring gap and autumn repeat.
- Browser: `web/tests/rafii-automations.cjs` (Chromium; real input, real API, real worker via the
  harness cron): build → activate → scheduled minute → drafts for both accounts → edit returns to draft
  → activate / pause / resume → Home panel → cancel; phone layout; axe on the builder and hub.

## Limitations (Phase 1)

- One schedule per automation (several weekdays, one time). Monthly or date-relative schedules
  (countdowns) and templates are Phase 2.
- The run digest ("drafts ready" notification) is Phase 2; today the hub, Home panel and conversation
  list show new drafts.
- The worker still claims one workspace per cron tick (batching is Phase 2).
- The budget view shows the configured ceiling, not measured spend per automation.
