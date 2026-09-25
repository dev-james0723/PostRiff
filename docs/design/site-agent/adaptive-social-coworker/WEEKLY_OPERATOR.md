# Weekly Social Operator contract (spec §12; architecture lock W1)

The code is in `coworker/weekly_operator.py` (pure state logic) and `coworker/service.py` (orchestration). The HTTP contract is in [API.md](API.md).

## Recipe (`state.coworker.weekly.recipes[]`, at most 5 per workspace; owner-level, because it authorises recurring paid drafting)

| Field | Values |
|---|---|
| `name`, `goals[]` (1–5) | text |
| `destinations[]` | `{channelId (a connected account in this workspace), platform, account, language, postsPerWeek 0–7}`, at most 28 posts a week |
| `contentMix` | `{contentType: weight}` |
| `campaignIds`, `sourceIds` | existing ids only |
| `planningDay` 0–6 (Monday = 0), `planningHour` 0–23, `timeZone` (IANA) | when the cron prepares next week |
| `voiceMode` | `neutral` or `personalized` (needs the existing voice-sample consent) |
| `reviewPolicy` | always `review`. The Weekly Operator never publishes by itself |
| `expectImages`, `useResearch` | booleans |
| `maxCostUsdMicroPerWeek` | 0–50 USD; checked before every slot against the week's own run costs in the usage ledger |
| `model` | the writer route, optional (the workspace default otherwise) |
| `status`, `version`, `createdBy`, `createdAt`, `updatedAt` | managed |

## Week (`state.coworker.weekly.weeks[]`, the last 12 kept)

The week id is deterministic: a hash of the recipe id and the Monday.

A week has `weekOf` (a Monday in the recipe's zone), `isoWeek`, `state`, `blockedReason`, `slots[]`, `history[]`, `conversationId`, `readyAt` and `costBudgetUsdMicro`.

Each slot has `id` (deterministic), `day`, `localTime`, `timeZone`, `platform`, `account`, `language`, `channelId`, `contentType`, `goal`, `angle`, `sourceIds`, `status`, `reason`, `question`, `answer`, `variantId`, `runId`, `quality`, `creative` and `attempt`.

**States.**

```text
planned → researching → generating → quality_check → ready_for_review → approved → scheduled
blocked: needs_input · needs_source · needs_asset · channel_unavailable · approval_expired
```

`weekly_operator.transition` refuses any other move, for example `generating → approved` or `planned → scheduled`.

**Slot statuses.**

| Group | Statuses |
|---|---|
| Before drafting | planned, needs_source, needs_input (with one precise `question`), needs_asset (with a creative brief), channel_unavailable (with a reason) |
| Draft and quality | drafted, then ready or needs_revision (the meaning check flagged an unsupported number, name, anecdote or feeling) |
| The person's decision | accepted, or rejected (skip or reject) |
| Read back from Queue | in_queue, approved, scheduled, published (only when the job is `verified`), failed, approval_expired |

## Cycle

1. **Trigger.** The cron runs `weekly_cron` for each active recipe whose planning moment for next week has passed in its own time zone. A person can also press "Prepare next week" (`POST weekly/recipes/{id}/prepare`, at edit level). The cron acts as the recipe's owner through a private capability (`automation_runs.principal_repository`), never through an HTTP credential, and each transaction re-checks that membership.
2. **Plan** (`plan_week`, deterministic).
   - Slots are spread over the week.
   - The content mix is weighted round-robin, offset per platform.
   - Sources are the recipe's approved sources, falling back to the workspace's approved sources, assigned in turn.
   - A disconnected or expired account makes its slots `channel_unavailable`.
   - A personal content type (a reflection or behind-the-scenes post) asks one question (`needs_input`).
   - A slot with no approved source is `needs_source`.
3. **Draft.** One writing run per slot through `IdeasService.turn`, followed by `apply(separate=True, tag={weekPlanId, slotId})`.
   - The slot brief is `material`: data, never instructions. So the pipeline treats the run as a drafting request, and never as an automation, a schedule or a memory.
   - The idempotency key is `weekly:{week}:{slot}:{attempt}`, so repeating a prepare never duplicates a draft.
   - The run's skills include `rafii-weekly-operator`, always, and the Humanizer pack for each language when the route's budget allows it; an omission is recorded.
   - The ledger reserve and settle, source policy, voice consent and learning capture are all the pipeline's own.
4. **Quality.** For each drafted slot:
   - `humanizer.evaluate` runs (voice fit, synthetic-writing clusters, lint) and its version is recorded;
   - the meaning check runs against the slot's approved facts;
   - `creative.plan_assets` runs for visual-first platforms when `expectImages` is set, giving a `needs_asset` with a brief if no approved asset exists.
5. **Settle.** The week becomes `ready_for_review` when every slot is ready, needs revision or is blocked with a reason. If nothing is reviewable, the week takes its dominant blocked state.
   - `campaign.week_ready` is emitted once. It is deduped as `week_ready:{week}`, both in the same transaction and by the detector.
   - A blocked week emits `campaign.blocked`, deduped per week and state.
   - The growth event `weekly_plan.ready` is recorded.
6. **Review** (`/app/weekly`). The slot actions are:
   - `accept`: hands the draft to Queue → Drafts;
   - `redo`: a new attempt with a new idempotency key;
   - `skip` or `reject`;
   - `answer`: for needs_input or needs_source, back to planned.

   Rafii never approves or schedules. The person confirms the uncertainty review, prepares the exact review and approves in Queue, through `p2_variant_review → p2_review → p2_approve`, with the approver's permission.
7. **Read-back** (`sync_from_queue`).
   - The slot status follows real reviews and jobs on its draft.
   - The week becomes `approved` when every active slot has been approved in Queue, and `scheduled` when every approved slot has a publishing job.
   - `published` only follows a `verified` job.
   - A stale review before approval gives `approval_expired`, and one expired approval moves the whole week to `approval_expired` (with its reason), whatever the other posts did. Renewing or skipping it returns the week to review.
8. **Measure and learn.** Verified posts feed performance hypotheses (WP8). Edits and decisions feed preference learning.

## Truthfulness

- The week says "scheduled" only when jobs exist, and "published" only when a job is `verified`.
- A writer failure puts the slot in `needs_input` with the reason, never in "done".
- A budget stop is `needs_input`, with the reason "This week's writing budget is used up". A $0 limit plans the week but never starts a paid writer run ("The weekly drafting limit is $0 …"). A run with no recorded cost counts at its usage-ledger reservation, else $0.05; only a run that made no model call is free.
- The quality record says what the meaning check compared the draft with (`meaningBasis`: approved facts, the person's own answer, or `none`). With `none` the page says "Facts not checked" instead of "checked".
- Answering a question in a week already in review reopens it (`generating`), so the next preparation drafts that post.
- The `weekly_plan_prepare` agent tool drafts at most 2 posts per call (the next call continues), refuses when the turn has under 100 s left, and records as changed only the drafts that call created and read back. The cron starts a paid writer run only when 95 s of its budget remain.
- Any member can open a week; only an editor's read saves the Queue read-back.

## Verified locally (PG W01–W07)

- **Recipes.** Only an owner can save a recipe.
- **End to end.** Preparing a week produced 3 slots, 3 drafts, tagged variants, quality records, one `campaign.week_ready` event, and the `rafii-weekly-operator` skill in every run.
- **Idempotency.** Preparing again changed nothing.
- **Queue read-back.** Accept, then Queue, gave `in_queue`; the approver's approval then gave `scheduled`, and no job was published.
- **Blocked states.** `needs_input` with one question, which answering unblocked, and `campaign.blocked`.
- **Answer after review.** In a week already `ready_for_review`, answering a waiting post's question moves the week back to `generating`, and the next preparation drafts that post (W07). Before this fix the post stayed `planned` for good; the browser QA found it.
- **Cron.** The cron prepared a due recipe as its owner, and turning the flag off stopped it.
