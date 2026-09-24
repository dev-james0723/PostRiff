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

## Phase 2: templates, schedule types, "drafts ready", batching and spend

- **Schedule types.** Weekly (unchanged shape), monthly (`monthDays`: 1–31 or `last`; a day a month
  lacks runs on its last day) and countdown (`eventDate` + `daysBefore`, up to 8 steps, 0–90 days;
  finishes by itself after the last date; its date becomes the brief's date fact). Saving or activating
  a countdown whose dates have all passed is refused. Previews in the builder follow the server rules
  (node tests share the server's cases, including DST).
- **Templates** (`web/src/features/automations/templates.ts`): Weekly tip, Event countdown, Monthly
  recap. They only fill the builder; the text is general, never a particular person's details.
- **Recap context.** `include.recentPostsDays` (7–92, part of the activated definition): each run adds
  up to ten of this workspace's own published posts from that window as data. Countdown runs add the
  days left. The worker's fixed instruction says to use only what the data lists.
- **"Drafts ready".** In-app: runs nobody has opened count as "new" on the hub, the Home panel and the
  shared attention list (Home, Overview, sidebar badge); opening a run's drafts, or "Mark all as seen",
  records `seenAt` (`raffi_recurrence_seen`, edit). Email: a member's own opt-in per automation
  (`raffi_recurrence_watch`, any member; outside the definition) sends one email per run, deduplicated
  in `pr_notifications`, only while they are still an active member. Nothing is sent from the local
  harness (no mail transport).
- **Batching.** The cron entry prepares up to five due runs (any workspaces) within 90 seconds instead
  of one per minute.
- **Spend.** Each completed run records its writer's charge (`costUsdMicro`) and draft count. The hub
  shows spend this month per automation and in total, next to the ceiling: per-run limit × the most runs
  in a month (a weekly day can occur five times) or in the whole countdown.

## Phase 3: runs started by your own material

- **New material in Ideas** (`on_new_source`): each idea, note, link or document added after the
  automation is activated starts one run that reads that item as its source (usual consent rules).
  Items from before activation, or added while paused, never replay. At most `maxPerDay` runs in any
  24 hours (1–10); anything over the limit is skipped and counted, never saved for later.
- **Strong posts** (`on_strong_post`): a post published in the last 1–30 days whose conversation
  (Threads replies, Instagram comments) is clearly above comparable posts starts a follow-up run.
  Comparable means the analytics module's cohort (same provider, language, content type and metric
  definition) with at least three measured posts; "clearly" means top quarter, at least 1.5 times the
  median and at least two more. LinkedIn reports no such metric yet. The run receives the post and the
  observation in words, labelled as an observation, not a cause.
- **Evergreen** (`include.evergreen.minAgeDays`, 14–365, weekly/monthly/countdown only): each run
  refreshes one published post at least that old; the one that started the most conversation first
  (else the oldest), never the same post twice for that automation.
- **How it runs.** The cron entry first scans active triggers (only workspaces that have one; a scan
  that finds nothing new does not touch the workspace), queues events on the automation, then prepares
  due runs as before. Each event run is keyed by the event, so the same idea or post never runs twice.
- **Builder and hub.** "New idea" and "Strong post" sit beside Weekly, Monthly and Countdown, with the
  daily limit and look-back window; three templates (New idea → drafts, Follow up a strong post,
  Evergreen reshare). Run history names what started each run.
- **Not built: recordings.** The Library stores images only; there is no audio or video upload or
  transcription. A "new recording" trigger needs that pipeline first, which means choosing a
  transcription service (a paid-service decision) — left for the owner to decide.

## From a chat request: "every Tuesday, draft me …"

Asking Rafii on Home or in a conversation ("Set up an automation of drafting me a news article post in my
voice about AI for Science every Tuesday") sets up the automation instead of drafting once.

- **Reading the request.** A message with a recurrence or automation cue (every/each/twice a week/逢/每 …)
  is read by a small model on the same route the person already chose: their own Claude Code for a Claude
  Code writer, the managed gateway (Claude Haiku) for a managed writer, never for the preview writer. It
  decides "automation" or "draft" and names the days, time, topic, kind of post and voice. The prompt
  carries only the message, the date and the content-type catalog (no sources, memory or accounts). A
  managed call's cost is reserved in the usage ledger before it leaves and settled after; a stop-line or a
  failed call skips the reading, never the request. Without a model the deterministic reading decides
  (`intent.is_automation_request`, `automation_chat`): "about automation" is a topic, "my weekly recap" is
  one draft, "I practise every day, write about it" is a habit, not a schedule.
- **Saving it.** `automation_chat.create` fills the builder's fields (schedule, destinations from the
  composer, content type — installing the starter pack when only it has the type, as Home does — voice,
  attached references as context sources, the brand audience or a general default) and saves through
  `raffi_recurrence_save`, so every builder check applies. The model's reading is validated field by field;
  anything it leaves out or gets wrong falls back to the deterministic reading.
- **Turning it on.** An owner's request with a free writer is activated at once. A per-run spending limit
  (paid writers), missing facts (event briefs) or a request from someone who is not an owner leaves it
  waiting in the hub with the reason; nothing is invented for the person.
- **The reply.** Rafii answers in the conversation with what will happen and when; a card shows the
  schedule, first draft, destinations, kind of post, voice, references, what is left and what was assumed,
  with Pause, Edit (the builder), Undo (cancel) and Open Automations. On Home the card scrolls into view.
  The request is an instruction, so it is not stored as a source and nothing is drafted, scheduled or
  published.
- **Voice.** Automations carry `voiceMode` (part of the definition; the builder has "Write in my voice").
  A run whose writing samples are gone or not allowed for its writer drafts in a neutral voice and says so
  on the run, never a failed run.
- **Verified.** Unit: `tests/test_postriff_automation_chat.py`, `tests/test_postriff_intent.py`.
  PostgreSQL: `tests/phase2/postgres_chat_automation.py` (Home and conversation, non-owner, model reading
  metered, "just a draft", failed reading, plain drafting unchanged) and the voice scenario in
  `postgres_consumer_campaign_worker.py`. Browser: the `chat` scene in `web/tests/rafii-automations.cjs`
  (Chromium and WebKit: reply, saved definition, nothing drafted, 390px fit, hub, Undo, axe).

## Limitations

- Several times a day is not offered (runs prepare drafts; the posting time is chosen at approval).
- Measured spend covers completed runs only; a held run costs nothing by design.
- Trigger scans run on the one-minute cron, so a new idea is picked up within about a minute or two.
- A chat request with a paid writer always waits for the owner to choose a per-run spending limit; with
  credits enabled (FINAL-05, not on this branch), the request's credit limit could become that limit.
- The model reading of a request is not yet under the gateway provider-routing rules the candidate
  integration adds for drafting (FINAL-04); merge it into `request_model.call_for` when integrating.
