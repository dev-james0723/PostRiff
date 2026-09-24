# Raffi orchestration — contracts (2026-09-24)

Implements `docs/Raffi_Intelligent_Content_Automation_Orchestration_Prompt_2026-09-24.md` (canonical checkout) on
`rafii-v9-integration`. It extends the existing Automations engine (`campaigns.py`, `campaign_worker.py`,
`planning_store.py`). It adds no scheduler, no new table and no migration. New fields live in the workspace JSON
(`state.raffi.campaignPlanning`) and in the jsonb `body` of the 018 projection. Projected columns keep their
CHECK-constrained values.

Publishing happens only through the Phase 2 chain: variant review → source use → `build_manifest` → review →
approve → job → the hosted worker's `_approved` re-check. The automation never writes a job itself.

## 1. Automation (task) — authorityVersion 3

A v3 task is today's v2 task plus the following fields.

- `workflow` (part of the authorized definition: `DEFINITION_V3 = DEFINITION + ("workflow",)`). It is `null` for a
  drafts-only automation built in the Automations builder. Otherwise it is:

```jsonc
{
  "version": 1,
  "policy": "auto" | "review" | "drafts" | null,     // null = not chosen yet → cannot activate
  "stages": {
    "generate": When,                                   // research + drafting
    "review":   When | null,                            // when the person is told drafts are ready (review policy)
    "publish":  When | null                             // null for policy "drafts"
  },
  "research": null | {
    "query": str, "about": str,                         // what to look for
    "domains": ["bbc.co.uk", ...],                      // allowed publisher hosts (subdomains included); [] = any reputable
    "publications": str,                                // the person's words ("reputable science publications")
    "urls": [str],                                      // supplied links, read first
    "recencyDays": int (1..60, default 7),
    "minScore": float (0.3..0.9, default 0.55),         // the bar a candidate must clear
    "onNothing": "skip" | "draft_without",              // default skip: no filler
    "quote": null | {"about": str}                      // find a quote; attribution must be verified before it is called verified
  },
  "content": {"task": "post|reflection|quote|summary|update|announcement|promotion|education|thread|recap|tip|story|question", "instructions": str},
  "platformNotes": {"X": "shorter, sharper", "LinkedIn": "fuller"}   // per-platform adaptation asked for
}
```

  `When` is one of the following. Weekday specs resolve to the first such local time strictly after generation.
  The other specs resolve against the anchor.

  - `{"at":"anchor"}`
  - `{"at":"generate"}` (review only)
  - `{"asap":true}` (generate, once only)
  - `{"minutesOffset":int}`
  - `{"dayOffset":int,"localTime":"HH:MM"}`
  - `{"weekday":"Saturday","localTime":"18:00"}`

- `schedule` gains two forms:
  - `{"kind":"once","date":"YYYY-MM-DD","localTime":"HH:MM","timeZone":tz}`
  - weekly `slots`: `{"weekdays":[...],"localTime":"HH:MM","slots":[{"weekday":"Monday","localTime":"09:00"},...],"timeZone":tz}`.
    When `slots` is present it wins, and `weekdays` and `localTime` mirror the first slot for older readers.
- `intent`: the person's request, clipped to 600 characters (display and explanation only; not in the digest).
- `publishAuthority`: `{grantedBy, grantedAt, definitionDigest, sourceUse: bool}`. It is set only when an owner
  activates an `auto` workflow with `publishAuthority: {confirmed: true}`. `sourceUse` means the owner allowed posts
  built on sources that Raffi found to publish without a per-source review.
- `pausedUntil` (epoch): a pause with `until` resumes automatically at that time (the worker's advance sweep).
- `deletedAt` / `deletedBy`: a delete is a cancel plus hiding from lists. Run history is kept for audit.
- `lastAnchorAt`: the latest anchor already claimed. The same anchor is never claimed twice (no duplicates on edit).

`nextOccurrence.scheduledFor` is the next **generation** instant (`workflow.next_run`), and `nextOccurrence.anchorAt`
is its anchor. For v3 tasks, `task.nextPublish` is the local ISO time of the next publish (display only).

## 2. Run (occurrence) — body fields for v3

The projected `state` is still pending|running|completed|failed|held|missed|cancelled. `lifecycle.projected(run)`
derives it. The body adds:

```jsonc
{
  "anchorAt": epoch, "policy": "auto|review|drafts",
  "stages": {"generateAt": epoch, "reviewAt": epoch|null, "publishAt": epoch|null, "local": {"generate": iso, "review": iso|null, "publish": iso|null}},
  "lifecycle": "planned|researching|drafting|drafted|skipped|source_unavailable|failed",   // run-level (generation) stage
  "research": null | {"query": str, "domains": [...], "candidates": [{"url","title","host","published","score","reasons":[...]}],
                       "chosen": null | {"url","title","host","published","score","sourceId"}, "decision": "chosen|nothing_worth|unavailable|skipped_by_rule",
                       "reason": str, "quote": null | {"text","author","verified": bool, "hosts":[...]}},
  "skills": [{"skill": "schedule_trigger|research|source_validation|read_url|relevance|brand_brain|voice|write|platform_adaptation|quality_check|approval_gate|schedule|publish|notify", "status": "done|skipped|failed|waiting", "at": epoch, "detail": str}],
  "items": [Item], "history": [{"at": epoch, "event": str, "detail": str, "actor": "raffi"|userId}],
  "notices": {"reviewSentAt": epoch|null, "expiredSentAt": epoch|null, "disconnectedSentAt": epoch|null}
}
```

`Item` (one per destination):

```jsonc
{
  "key": "<platform>|<channelId or ''>|<language>", "platform": str, "channelId": str|null, "account": str, "language": str,
  "variantId": str|null, "variantRevision": int|null, "textDigest": str|null,
  "state": ItemState, "reason": str|null,                // plain-language reason for alternate states
  "publishAt": epoch|null, "capability": {"publish": bool, "reason": str},   // snapshot at generation, refreshed by the sweep
  "decision": null | {"decision": "approve|reject|revise", "by": userId, "at": epoch, "note": str,
                      "variantRevision": int, "textDigest": str, "excludedUnknowns": [...], "acknowledgedWarnings": [...], "sourceUse": [{"sourceId","factsDigest"}]},
  "approvedVia": null | "human" | "owner_preauthorization",
  "reviewId": str|null, "jobId": str|null, "attempts": int, "lastError": str|null
}
```

## 3. Lifecycle (shared: `lifecycle.py`, `web/src/lib/automation-lifecycle.ts`, vectors in `tests/fixtures/automation_lifecycle.json`)

- RUN_STAGES: `planned → researching → drafting → drafted`. The alternates are `skipped`, `source_unavailable` and `failed`.
- ITEM_STATES: `ready_for_review → approved → scheduled → publishing → published`. The alternates are
  `needs_revision`, `rejected`, `skipped`, `failed`, `platform_disconnected` and `approval_expired`.
- A policy `auto` item that passes every safety check goes `approved` (via `owner_preauthorization`) → `scheduled` at commit.
  An unsafe auto item is **downgraded** to `ready_for_review`, with the reason.
- A policy `drafts` item is `ready_for_review` with `publishAt = null`. It never moves on by itself.
- `status(run)` (what the UI shows):
  - before drafting, the run lifecycle;
  - when drafted, it is derived from the items by the priority `publishing, scheduled, approved, ready_for_review,
    needs_revision, platform_disconnected, failed, approval_expired, published, rejected, skipped`.
  - `attention(run)` is true when any item is in `needs_revision|platform_disconnected|failed|approval_expired` or
    in `ready_for_review` with a publish time.
- Allowed item transitions (`TRANSITIONS`), enforced by `lifecycle.move(item, to)`:
  - ready_for_review → approved | rejected | needs_revision | approval_expired | platform_disconnected | skipped
  - needs_revision → ready_for_review | rejected | approval_expired | skipped
  - approved → scheduled | ready_for_review | approval_expired | platform_disconnected | failed | skipped
  - scheduled → publishing | published | failed | platform_disconnected | skipped
  - publishing → published | failed
  - platform_disconnected → approved | ready_for_review | approval_expired | failed | skipped
  - published, rejected, approval_expired, failed, skipped are terminal
- Job → item: scheduled|approved|claimed → `scheduled`; submitting|processing|provider_accepted|published|uncertain →
  `publishing`; verified → `published`; failed → `failed`; canceled → `skipped` (reason: cancelled); held →
  `platform_disconnected` if the channel is not "Ready for posting", else `failed`, with the job's last event message.

## 4. Actions (hosted commands; `permissions.ACTION_CLASSES`)

| action | class | payload |
|---|---|---|
| `raffi_recurrence_save` | edit | today's payload plus `workflow`, `intent`, and `schedule` in `once`/`slots` form |
| `raffi_recurrence_activate` | owner | `{taskId, confirmed:true, publishAuthority?: {confirmed:true, sourceUse?:bool}}`. It is required for policy `auto`, and a missing one is refused with code `publish_authority_required`. |
| `raffi_recurrence_pause` | owner | `{taskId, until?: epoch}` |
| `raffi_recurrence_resume` | owner | `{taskId, confirmed:true}` |
| `raffi_recurrence_cancel` | owner | `{taskId, confirmed:true, delete?: true}` |
| `raffi_run_decide` | approve | `{occurrenceId, itemKey, decision:"approve"\|"reject"\|"revise", confirmed:true, note?, variantRevision, excludedUnknowns, acknowledgedWarnings, sourceUse:[{sourceId,factsDigest}]}` |
| `raffi_run_commit` | approve | worker-only in practice, `{occurrenceId, itemKey}`. It runs variant review, source use, review and approve atomically as the principal (§5). |

`raffi_run_decide` rules:
- the item must be `ready_for_review` or `needs_revision` (or `platform_disconnected` for approve);
- the variant revision and text must equal the payload;
- `excludedUnknowns` must equal the variant's unknowns, and `acknowledgedWarnings` must equal its warnings;
- every `rewrite_approval` source on the variant must be listed with its current facts digest;
- the item must be before its `publishAt`, otherwise the item becomes `approval_expired` (409 `approval_expired`).

Silence never approves. A policy `review` item never reaches `approved` without this action.

## 5. Commit (`publisher.py`, used by the worker's advance sweep)

The sweep runs every cron minute. When an `approved` item reaches `publishAt − COMMIT_LEAD` (30 minutes), or
immediately when `publishAt` is closer than that, it does the following:

1. **Capability check** (`capabilities.publish_route(...)`): the platform has a hosted publisher (LinkedIn, Threads,
   Instagram), the provider is production-reviewed and not paused, live transport is mounted, the channel is
   connected and not revoked, the capability is `Direct`, and the billing plan can publish. If any check fails, the
   item becomes `platform_disconnected` (a connection problem) or `failed` (anything else), with the reason and a
   notice. Nothing is faked.
2. **Server-side re-verification** (`OAuthService.reverify_for_worker`) so the channel is "Ready for posting".
3. **One `repository.command`** as the approving principal, running `raffi_run_commit`. That principal is the
   human who approved; for `owner_preauthorization` it is `publishAuthority.grantedBy`, and its class is re-checked
   in the command. The command:
   - runs `variant_review` (the recorded exclusions);
   - runs `source_use_approve` (the recorded facts digests, or `sourceUse` standing authority);
   - runs `p2_review` at `publishAt` (the manifest time is `max(publishAt, now+120)`);
   - runs `p2_approve` with `{automation: {taskId, occurrenceId, itemKey, approvedVia}}` stored on the job;
   - dedupes: an item that already has a live job is never committed twice.
   Billing (`require_publishing`) runs as the after-hook.
4. Later sweeps map the job state onto the item (§3).
5. A failure keeps the approved draft. A retryable failure is tried again on the next sweep, up to 3 attempts, then
   the item becomes `failed`.

Auto-publish safety: an auto item is committed only when all of these hold:
- the variant has no unknowns;
- every warning is one of `AUTO_ACKNOWLEDGEABLE`: the web-research note, allowed only with `sourceUse`, and the
  neutral-voice fallback note;
- every third-party source is covered by the `sourceUse` standing authority;
- any quote is verified;
- the text fits the platform limit;
- Instagram has an image.
Otherwise the item is downgraded to `ready_for_review` with the reason, and a review notice is sent.

## 6. Reading a request (`workflow_parse.py`, deterministic; `request_model.py`, model)

Both return the same **Reading**:

```jsonc
{
  "action": "draft" | "automation" | "edit" | "explain",
  "automation": null | {
    "name": str, "topic": str, "goal": str,
    "schedule": {"kind":"once","date":"YYYY-MM-DD","localTime":"HH:MM"} | {"kind":"weekly","slots":[{"weekday","localTime"}]}
              | {"kind":"monthly","monthDays":[1..31|"last"],"localTime":"HH:MM"},
    "timeRole": "publish" | "generate",                  // what the named time means ("post at 2 PM" = publish)
    "stages": {"generate": When|null, "review": When|null, "publish": When|null},
    "policy": "auto" | "review" | "drafts" | null,
    "platforms": [str],                                  // as named; unsupported ones are kept to say so honestly
    "research": null | {query, about, domains, publications, urls, recencyDays, onNothing, quote},
    "content": {"task", "instructions"}, "platformNotes": {...},
    "voice": bool, "contentTypeId": str|null, "formatId": str|null, "assumptions": [str]
  },
  "edit": null | {"target": {"name": str|null}, "changes": [Change]},
  "explain": null | {"question": str, "target": {"name": str|null}, "about": "why_posted|source|not_published|status|next"},
  "tier": "light" | "strong"
}
```

`Change` is one of the following:

- `{"op":"move","stage":"auto|publish|generate|review","weekdays"?:[...],"localTime"?:"HH:MM","date"?:"YYYY-MM-DD"}`
- `{"op":"remove_platform","platform"}` or `{"op":"add_platform","platform"}`
- `{"op":"sources","domains":[...],"publications":str}`
- `{"op":"policy","policy"}`
- `{"op":"pause","days"?:int,"until"?:"YYYY-MM-DD"}`, `{"op":"resume"}` or `{"op":"delete"}`
- `{"op":"topic","topic"}`, `{"op":"instructions","text"}` or `{"op":"voice","voice":bool}`

Model routing (hidden from users):
- `request_model.tier(text)` picks `light` (Haiku) for short single-clause requests.
- It picks `strong` (gateway `anthropic/claude-sonnet-5`; Claude Code CLI `sonnet`) when a request has several
  stages, conditions, source constraints, several platforms or schedules, or edits an existing automation.
- Both tiers are metered like today (reserve before, settle after), fall back to the deterministic reading, and
  record the tier on the message.

## 7. Chat turn (Home / conversation)

`intent` routes a message to one of four paths: create, edit, explain, or answer a pending question.

- **Create.**
  - Parse the message into a Reading.
  - Complete the workflow: defaults, time role, the capability snapshot for each platform.
  - Save it with `raffi_recurrence_save`.
  - Then, if the policy is missing, ask one question with quick replies (`Publish automatically`,
    `Send for my approval first`, `Just prepare drafts`).
  - Otherwise, if the policy is `review` and no review time is known and the publish time is the anchor, ask when
    the drafts should be ready (`The day before`, `The same morning`, `2 hours before`).
  - Otherwise activate it (owner) and confirm in plain words. The confirmation says what runs when, what publishes
    where, and which platforms cannot publish yet and why.
- **Pending question.** The conversation's last assistant message carries `automation.pending = {taskId, question:
  "policy"|"review_time"}`. The next message, or a quick reply sent as a normal turn, answers it and edits the same
  task (no duplicate).
- **Edit.** Resolve the target in this order: the automation discussed in this conversation, then a name match, then
  the single active automation. Apply the changes with a full-payload `raffi_recurrence_save`, which keeps the same
  task id. Re-activate it when the owner made the change. Open runs are re-timed and removed destinations are
  skipped (`campaigns.retime_open_runs`). Confirm the new behaviour.
- **Explain.** Answer from run history: the trigger, the sources, the skills, who approved, the publish time and
  result, and why something was not published.
- **Card** (`message.automation`) carries the following:
  - today's fields;
  - `workflow`, `policy`, and `stages` in plain words (`plan: [{step, when, text}]`);
  - `platforms: [{platform, account?, canPublish, reason}]`;
  - `pending`, `quickReplies: [str]`, `runs` (the latest three with their status), `tier` (not shown);
  - `explain` (for explain turns).

## 8. File ownership (parallel work)

| owner | files |
|---|---|
| core (lead) | `workflow.py`, `campaigns.py`, `lifecycle.py`, `capabilities.py`, `publisher.py`, `campaign_worker.py`, `workflow_parse.py`, `automation_chat.py`, `automation_edit.py`, `automation_explain.py`, `ideas.py`, `permissions.py`, `hosted.py`, `hosted_app.py`, `email.py`, tests `test_postriff_orchestration*.py`, `tests/phase2/postgres_orchestration.py` |
| research agent | `automation_research.py`, `tests/test_postriff_automation_research.py` |
| platforms agent | `agent_runtime.py` (PLATFORMS), `contracts.py` (LIMITS), `generation.py`, `intent.py` platform aliases only, the web platform constant, platform tests |
| model agent | `request_model.py`, `tests/test_postriff_request_model*.py` |
| oauth agent | `oauth.py` (`reverify_for_worker`), `tests/phase2/postgres_reverify.py` |
| frontend agent | `web/src/lib/automation-lifecycle.ts` + test, `web/src/lib/api/types.ts`, chat card, hub run history, builder `workflow` passthrough, Home quick replies |

## 9. Implementation notes (as built, 2026-09-24)

These are the rules the adversarial reviews tightened, and the behaviour a reader needs beyond §1–§8.

- **Consent to auto-publish.** Auto-publish is granted only by an owner, only by the "Publish automatically" quick
  reply or explicit, non-negated wording (`workflow_parse.explicit_auto`; "don't publish automatically" and "what does
  this automation do?" never count), and only for the exact definition. `automation_plan.activate(grant=…)` is the only
  place chat grants it. An owner's later chat edit carries their own grant over unchanged, never widening
  `sourceUse`. A different owner's edit leaves the automation waiting for their confirmation.
- **Draft binding.** Every approval, human or standing, is for one draft revision and text digest. `publisher.commit`
  refuses (and the sweep returns the post to review) when the draft, its pending update, its sources' facts or its
  warnings changed, and re-runs `auto_blockers` for standing approvals. A standing grant is re-checked as **owner**:
  once the grantor is no longer an owner, posts wait for approval. A commit is accepted only from 30 minutes before the
  publish time until an hour after it (`not_due` otherwise).
- **Instagram** is never promised for text automations (`capabilities` code `needs_image`).
- **Routing.** Without a model reading, a message is an edit or a "why?" question only when it names an automation, says
  "automation", or points at the one the conversation is about; a request to write something now ("pause before the
  chorus — write a post about that") is always drafted. Replies to Rafii's questions must be short and are never a
  drafting request. A message naming different times for different channels keeps the per-channel scheduling plan, and
  so does posting what is already drafted ("post this at 4 PM"). Messages that name an existing automation are read by
  the strong model.
- **Timing.**
  - A review can come before the anchor ("the evening before").
  - The stage order is checked on every weekly slot, on a year of monthly dates and on every countdown day, with one
    hour of slack for DST.
  - A run whose publish time passed while PostRiff was down is skipped, never drafted just to expire. A window missed
    while its post is still ahead is drafted late. A new automation starts at its next drafting time.
- **Edits.** A one-time automation stays editable after its run started: the run follows the new time and no second run
  is made. A moved run is re-anchored no earlier than now. Draft-only items never gain a publish time. Switching to
  drafts-only withdraws a publish approval.
- **Sweep.**
  - It selects only workspaces with actionable items (a publish time or a job), in random order, so nobody is starved.
  - A post blocked by a held job is re-queued if its account is reconnected in time, otherwise it fails at its time.
  - A request to approve again after a voided approval is a new notice.

## 10. Validation (2026-09-24)

| check | result |
|---|---|
| Python unit suite (`unittest discover`) | 740 OK (644 before this work) |
| PostgreSQL suite (`scripts/postriff_pg_suite.py`, fresh cluster per script) | 37 scripts, 0 failed; `postgres_orchestration.py` covers acceptance A–G |
| Web: `tsc --noEmit`, `oxlint src`, node tests | clean, 0 warnings, 106/106 |
| `next build` (production) | exit 0 |
| Browser, Chromium against the local harness: `rafii-automations.cjs --only=chat,orchestrate` | 25/25, 0 console errors, axe clean, 390px fit |
| Browser: `rafii-menu-close.cjs` (menu closes after choosing a page, phone and desktop) | 4/4; fails 2/4 without the fix |
| Adversarial reviews (publish authority; correctness and generalization) | every finding fixed, with regression tests in `tests/test_postriff_orchestration.py` |
