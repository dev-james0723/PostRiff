# R0 domain map — J01 Draft studio, J02 Calendar/publishing, J03 Universal Library (lanes D/E)

- **Baseline:** worktree `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`, HEAD `3da806f0` (merge of PR #133), branch `claude/rafii-openui-production-20261008`. All paths below are relative to that root.
- **Method:** read-only `rg`/`sed`/`git`/`gh pr view|diff`. No builds, no tests run, no product files modified.
- **Legend:** **[V]** = verified code fact at the cited line. **[I]** = inference or recommendation, not yet a code fact. **[GAP]** = missing adapter, mismatch or risk that an implementer must close.

---

## 0. Cross-cutting facts every J01–J03 adapter depends on

### 0.1 Where workspace data lives [V]
- **One JSONB document per workspace:** `public.pr_workspaces.state` plus an integer `public.pr_workspaces.revision`. The read happens in `PostgresWorkspaceRepository.transaction()` (`src/postriff_phase2/hosted.py:112-138`), which runs `SELECT w.revision,w.state,<member cols> … FOR UPDATE OF w`. It joins `pr_memberships` (status `active`) and `pr_profiles` (not deleted). A foreign or nonexistent workspace raises the same `AlphaError("Workspace unavailable.", 403)`, so the two cases cannot be told apart. API tokens resolve through `api_tokens`. The agent routes refuse API tokens: `agent_runtime_v2/api_guard.require_session_token`, called from `agent_runtime_v2/http.py:49`.
- **Writes:** `PostgresWorkspaceRepository.command(workspace_id, token, revision, trusted_command, requirement="edit", step_up=False, audit_event=None, after=None)` (`hosted.py:150-171`). It:
  - checks `require(membership, requirement)`;
  - raises `409 workspace_revision_conflict` when the `revision` argument differs from the stored revision;
  - runs `trusted_command(deepcopy(state), principal)` (application code, never a client patch);
  - runs `UPDATE … revision=revision+1`;
  - writes `audit()` to `public.pr_audit_events` in the same transaction;
  - runs `self.effects` hooks, then `after(cur,state,principal)`.
- **Generic browser command route:** `POST /api/workspaces/{w}/actions` with body `{action, payload, expectedRevision}` (`hosted_app.py:987-1002`). It reaches `HostedWorkspaceService.mutate` (`hosted.py:762`) and then `repository.mutate` (`hosted.py:173`). The permission class comes from `permissions.classify(action)`.
- **Snapshot read:** `GET /api/workspaces/{w}` reaches `HostedWorkspaceService.get` (`hosted.py:759`) and then `commands.present(state, revision)`. The web Calendar, Queue and Pipeline all read this snapshot. React Query key: `keys.snapshot(workspaceId)`.
- **Library rows are outside the JSON document:** `public.pr_library_assets`, `pr_library_chunks`, `pr_library_labels`, `pr_library_collections` and `pr_library_collection_items` (migrations `093`, `094`, `095`, `096`). All five tables use RLS `service_only` with force-RLS. Tenant isolation is enforced in application code with `workspace_id=%s` predicates inside the membership transaction. Do not try to "prove" RLS with the service role.

### 0.2 Permission classes [V] (`src/postriff_phase2/permissions.py:15-24`)

| Class | Granted to |
|---|---|
| `read` | all roles |
| `edit` | owner, admin, editor |
| `approve` | owner, approver, or flag `can_publish` |
| `manage_connections` | owner, admin, or flag `can_manage_connections` |
| `owner` | owner only |

- `ACTION_CLASSES` (`:27-54`): `p2_review`, `p2_approve` and `p2_cancel` are `approve`; any action not listed is `edit`. Step-up actions are listed at `:57`.
- `Membership.allows(requirement)` is at `:74`; `require()` is at `:92`.

### 0.3 Existing agent gate to reuse for UI actions/queries [V]
- **Tool registry:** `agent_runtime_v2/tool_adapter.REGISTRY` (`tool_adapter.py:51`). `register(spec, schema, label)` is at `:54`.
- **The single gate:** `execute(ctx, tool, args, *, scope=frozenset|None, agent=None)` (`tool_adapter.py:96-137`), in this order:
  1. scope check;
  2. tenant check (founder vs workspace);
  3. voice parity;
  4. `ctx.membership.allows(spec.permission)`;
  5. cancellation, for anything that is not READ;
  6. strict schema check `_check_schema`;
  7. executor;
  8. typed `{ok:false, code, error}` results.
- **Context:** `RafiiRunContext` (`agent_runtime_v2/context.py:84-130`). Required fields: `service, workspace_id, token, principal, membership, conversation_id, trace_id`; optional `zone, writer_model, run_id, now, config, …`. `ctx.workspace()` re-reads the member on every call and refuses a principal mismatch (`context.py:132-142`).
  - Precedent for building one outside a Manager turn: `agent_runtime_v2/commands.direct()` (`commands.py:139-146`).
- **Effect classes** (`agent_runtime_v2/contracts.py:18-21`): `READ`, `CREATE_DRAFT`, `MUTATE_REVERSIBLE` and `PREPARE_EXTERNAL` are allowed; `EXTERNAL_EFFECT`, `DESTRUCTIVE` and `SECRET` are forbidden at `ToolSpec.__post_init__` (`:58-64`). `PREPARE_EXTERNAL` must have `approval=True`.
- **Site read tools:** `site_agent/tools.CATALOG` (`site_agent/tools.py:30-98`), run via `site_tools.run(tool_id, args, Context)` (`:155-172`). It does fail-closed schema validation, `REQUIREMENT` role checks (default `read`) and redacted views.
  - Mounted as agent tools by `register_site_tools()` (`tool_adapter.py:399-415`), using the name map `_SITE_NAMES` (`:226-242`).
  - Precedent for running a site read tool from an HTTP route without a model: `SiteAgentService.search()` (`site_agent/service.py:1173ff`). It opens `repository.transaction`, calls `require(member,'read')`, builds `tools.Context(state=ideas._state(row), membership, principal, workspace_id, cur, service, now, page={}, model_id=None, zone=None)` and calls `tools.run(...)`.
- **Result envelope** of every site read: `site_agent/contracts.result()` (`site_agent/contracts.py:144-148`) returns `{ok, verified, observedAt(ISO Z), source, data, warnings, nextActions}`. `ok` is not the same as `verified`.

### 0.4 Where proposals and answers are stored [V]
- **Agent answers** are `public.pr_messages` rows (`role='assistant'`) with `body = {text, runId, siteAgent:{…, blocks, proposals, refs, …}, agent:{…, pendingApprovals}}`. They are written by `AgentRuntimeService._persist()` (`agent_runtime_v2/service.py:862-896`), which also updates `public.pr_agent_runs.artifact/usage/status`.
- **Proposals exist only on an assistant message:** `body.siteAgent.proposals[]`, rendered as a `proposal_diff` block.
  - Lookup: `SiteAgentService._proposal_row()` (`site_agent/service.py:1060-1073`) requires `messageId + conversationId + proposalId` with `workspace_id` and `role='assistant'`.
  - Update: `_store_proposal()` at `:1075`.
- **[GAP] Consequence:** a proposal prepared from a UI action outside a Manager turn has no message to live on. `tool_adapter.execute(schedule_propose)` only appends to the in-memory `ctx.ledger.proposals` (`domain_tools.py:151-158`). D must persist it onto an assistant message, or the original apply/dismiss endpoints cannot find it. See decision D-2.
- **Ordered references** for "the second one": `body.siteAgent.refs` `[{type,id,title}]`, resolved by `site_agent/references.resolve(text, page_entity, history)` (`site_agent/references.py:1-40`). `TYPE_WORDS` covers draft, job, campaign, automation and source only. It has **no `asset`/library type** [GAP for J03 ordinals]. Image ordinals use `creative.conversation_images`.

### 0.5 Time zones [V]
- **The turn's zone is client-supplied:** the agent turn payload's `timeZone` goes through `intent.safe_zone()` (`intent.py:157-165`), which accepts a valid IANA zone and otherwise uses `DEFAULT_ZONE="UTC"` (`intent.py:25`). It becomes `ctx.zone`.
- **Persisted user preference:** `pr_profiles.time_zone`, read and written by `hosted.py:798-853`.
- **Job and review timing:** `manifest.timing` comes from `contracts.resolve_time(local, zone, fold, now)` (`src/postriff_phase2/contracts.py:71-89`) and returns `{local, timeZone, fold, utc, timestamp, tzdb}`. It refuses nonexistent DST times, asks for `fold` on ambiguous ones, and refuses past times.
- **[GAP]** Scheduling proposals never pass `fold` (`site_agent/proposals._review_payload`, `proposals.py:89-95`). An ambiguous DST local time is therefore refused, not resolved. The UI cannot offer a first/second-occurrence choice without a contract change.
- **Date parsing is deterministic:** `domain_tools.resolve_when(text, now, zone)` (`domain_tools.py:128-141`) accepts `YYYY-MM-DDTHH:MM` directly or parses words via `site_agent/timeframe.parse` plus `workflow_parse._time_in`.

---

## J01 — Draft and platform studio

### J01.1 Records and fields [V]
- **Drafts:** `state.variants[]` (JSON). They are created in `IdeasService.apply()` (`ideas.py:1871ff`). A new variant (`ideas.py` ≈ line 1955, `variant = {**values, "id": uid(), "revision": 1, …}`) carries:
  - identity and content: `id`, `revision` (int, from 1), `revisions[] {revision,text,origin,at}`, `platform`, `language`, `channelId?`, `text`, `openings[]`, `selectedOpening`;
  - sources and voice: `sourceIds[]`, `voiceSourceIds[]`, `voiceBindings[]`, `voiceRevision`, `styleRevision`, `briefRevision`, `speakerId`;
  - review state: `unknowns[]`, `warnings[]`, `needsReview`, `blockedByRetraction`, `customized`, `localPreferences`, `rejected?` (set aside);
  - provenance: `provenance {runId, contextDigest, policyEpoch, model, derivedFrom?}`, `automation? {taskId}`;
  - content type: `contentTypeId/Version`, `formatId`, `media?`.
- **Pending rewrite:** `variant.proposedUpdate = {…values, baseVariantRevision}`, written when a rework targets an unscheduled draft (`ideas.py` ≈ line 1946). Accepting it uses action `accept_update` (`postriff_alpha/domain.py:387-404`). Acceptance is refused as stale unless `briefRevision`, `voiceRevision` and `baseVariantRevision` all still match.
- **"Scheduled/committed" is not a draft field.** A draft counts as committed when some `state.phase2.jobs[]` entry has `manifest.variantId == draft.id` and `state ∉ {canceled, failed}` (`domain_tools.py:536`; `site_agent/tools.draft_get` `:488`).
- **Writer used:** `variant.provenance.model`. Workspace default writer: `writer_defaults.settings(state)["model"]` (`writer_defaults.py:17-23`; changing it is owner-only action `writer_defaults`).
- **Platform universe mismatch [GAP]:**
  - `contracts.LIMITS` has 22 platforms: Bilibili, Bluesky, Discord, Douyin, Facebook, Google Business Profile, Instagram, Kuaishou, LINE OA, LinkedIn, Mastodon, Pinterest, Pixelfed, Reddit, Telegram, Threads, TikTok, Weibo, X, Xiaohongshu, YouTube, Zhihu.
  - The agent tools `draft_create`/`draft_rewrite` allow only `PLATFORMS = ("LinkedIn","Instagram","Threads","X","Xiaohongshu")` (`domain_tools.py:31`, `:442`, `:486`).
  - Result: an adaptation to any other platform is refused by the schema.

### J01.2 Read functions (exact signatures) [V]

| Purpose | Function | Notes |
|---|---|---|
| One draft | `site_agent/tools.draft_get(ctx, draftId)` (`tools.py:484-498`); agent name `draft_get` | Returns `draftId, platform, language, account, revision, characters, limit, overLimit, unknowns≤6, warnings≤6, needsReview, blockedByRetraction, setAside, hasProposedUpdate, scheduled[≤3 job views], fromAutomation, text[:1500], textTruncated`. **[GAP] text is cut at 1,500 characters while drafts allow 20,000** (`domain.py` `clean(…,20000)`). An edit form must never be seeded from this text. Use the snapshot `state.variants[i].text` or a new full-text query. |
| List/search drafts | `site_agent/reads.content_search(ctx, query, kinds=None, platform=None, since=None, until=None, label=None)` (`reads.py:154-259`); agent `content_search` | An empty query with `kinds=["draft"]` gives a newest-first listing capped at **10**; a word search is capped at **12**. **[GAP]** Too small for a compare/table journey (contract page = 50/100). Needs a paged `drafts.list` adapter over `state.variants`. |
| Evidence / lineage | `agent_runtime_v2/graph.neighbours(state, kind, ident)` (`graph.py:37-175`); agent `relationships` | Draft edges: `derived_from` source (`draft.sourceIds`), `derived_from`/`adapted_as` draft (`provenance.derivedFrom`), `belongs_to_campaign`, `created_by_automation`, `reviewed_as`/`scheduled_as`/`published_as`. Every edge names its `via` field. Max 60 edges. |
| Voice fit | `site_agent/reads.voice_check(ctx, draftId=None, text=None, platform=None)` (`reads.py:568`); agent `voice_check` | Returns measured, heuristic or needs-a-writer findings. |
| Selected-entity status | `reads.entity_status(ctx, type, id)` (`reads.py:522`); agent `entity_status` | |
| Writers available | `site_agent/tools.models_summary(ctx)` (`tools.py:589`); agent `models_summary` | |
| Brand / voice profile | `reads.brand_summary(ctx)` (`:60`), `reads.voice_profile(ctx, platform=None)` (`:86`) | |
| Campaign membership | `domain_tools.campaign_items(ctx,args)` (`domain_tools.py:349-375`); `reads.campaign_membership(ctx,type,id)` (`reads.py:608`) | |
| Picker (posts) | `reads.picker_search(ctx, query="", categories=None, limit=8)` (`reads.py:695-779`) | `limit ≤ 12`. Returns label/sublabel only. |

### J01.3 Write / prepare paths [V]

| Action | Existing path (reuse) | Permission | Revision / idempotency | Verification |
|---|---|---|---|---|
| **Edit unscheduled draft text** | Agent tool `draft_edit` (`domain_tools.py:526-549`): `repository.command(…, change, requirement='edit', audit_event=('agent.draft_edited', id, {'via':'rafii_agent'}))`, where `change` refuses committed drafts (`409 draft_committed`) and calls `commands(state, principal, 'variant_edit', {variantId, variantRevision, text})`. | `edit` | `variant_edit` refuses `variantRevision != v.revision` with `409 draft_revision_conflict` (`postriff_alpha/domain.py:407-410`). The workspace revision comes from `ctx.snapshot()["revision"]`. **No idempotency key.** A replay after success hits the draft-revision conflict instead of returning the original result **[GAP for contract §5 "same idempotency result"]**. **No retry** on an unrelated `workspace_revision_conflict` (unlike `_link_command` `:284-293`) **[GAP]**. | Re-read: `saved.text == expected && saved.revision == rev+1 && needsReview` (`:545`). Side effects: `HostedPhase2Commands.__call__` sets `needsReview=True` and restores `unknowns` (`hosted.py:289-292`); `engine.invalidate(state)` makes open reviews stale; `variant_edit` sets `proposedUpdate = None`, which **discards a pending rewrite**, so the UI must warn. |
| Same edit via browser route (current Pipeline UI) | `POST /api/workspaces/{w}/actions` with `{action:'variant_edit', payload:{variantId, variantRevision, text}, expectedRevision}` (`web/src/features/pipeline/edit-draft-dialog.tsx:39,65`) | `edit` | Same as above | No committed-draft refusal on this route **[I: prefer the `draft_edit` tool path for GenUI]**. |
| **Rewrite / shorten / adapt** | Agent tool `draft_rewrite` (`domain_tools.py:482-522`), then `_writing_run()` (`:400-428`), then `ideas.turn(workspace_id, token, conversation_id, request)` (paid writer; reserves credits `ledger.reserve(…"text_model"…)` at `ideas.py:1463`), then `ideas.apply(…, separate=False)`. | `edit` (ToolSpec `CREATE_DRAFT`) | `idempotencyKey = "agent-rewrite:" + sha256(trace_id\|draftId\|instruction\|platform)[:40]`, so it is **bound to the turn's `trace_id`**. `ideas.turn` replays an identical key+fingerprint from the original run (`ideas.py:1300-1311`). | Outcome is either `proposed_update` (same draft, current text unchanged, verified when `text == before`) or `new_draft` (different platform: new variant with `provenance.derivedFrom`). Raises `202 writer_pending` while running and `502 writer_failed` on failure. |
| New drafts | Agent tool `draft_create` (`domain_tools.py:438-479`) | `edit` | `agent-draft:` key bound to `trace_id` | Re-read variants where `provenance.runId == run_id` |
| Accept a waiting rewrite | Action `accept_update` `{variantId}` via `/actions` (`domain.py:387-404`); used by `web/src/features/queue/schedule-dialog.tsx:237` | `edit` | Stale unless brief, voice and base revisions all match | Draft revision +1, `proposedUpdate` cleared |
| Choose opening | Action `opening` `{variantId, index 0..2}` (`domain.py:419-428`) | `edit` | Bumps revision | |
| Slash commands (`/rewrite`, `/translate`, `/repurpose`, `/hashtags`) | `agent_runtime_v2/commands.INSTRUCTIONS` (`commands.py:19-46`); turn payload `command:{name,args}` parsed by `commands.parse` (`:55-67`) | Through the Manager | Normal turn | Normal turn |

### J01.4 Writer / voice selection [V]
- **Writer:** the agent turn payload `model` becomes `ctx.writer_model` (`agent_runtime_v2/service.py:470`). `_writing_run` sets `request["model"] = ctx.writer_model` (`domain_tools.py:406-407`). With no model, Auto resolves through `ideas.resolve_writer()` and `writer_defaults`. A paused run keeps `pendingRun.writerModel` (`service.py:1002`, `:1053`). The writer is preserved.
- **Voice:** **[GAP — J01 requirement "preserve user-selected writer/voice"]**
  - `ideas.turn` writes in personalized voice only when `payload["voiceMode"] == "personalized"` (`ideas.py:1655-1662`; default `"neutral"`), with optional `voiceSourceIds`.
  - The agent runtime **never forwards `voiceMode`/`voiceSourceIds`**: no reference anywhere in `agent_runtime_v2/` or `web/src/lib/agent-runtime/types.ts`.
  - Every agent-made draft and rewrite is therefore neutral voice. A fix is required in the turn payload, then `RafiiRunContext`, then the `_writing_run` request. This crosses B/D/A-owned files; see decision D-5.

### J01.5 Existing tests to extend [V]
- `tests/test_agent_runtime.py` (1454 lines): schedule-proposal verification `:260`, proposal-apply pause `:593`.
- `tests/phase2/postgres_agent_runtime.py` (1611 lines): `fresh_draft()` `:1048`, `schedule_proposal()` `:1059`, decide/again-denied `:1130-1136`, HTTP `approvals/decide` `:1190`.
- Web: `web/tests/site-agent.test.cjs`, `site-agent-browser.cjs`, `agent-runtime-browser.cjs`.
- **No existing test** covers `draft_edit` via a non-turn caller, committed-draft refusal from UI, or the 1,500-character truncation hazard.

### J01.6 Thin adapter the UiQuery/UiAction layer must call [I]
- **`query: drafts.list`** (new, D)
  - Runs in a `repository.transaction` with `require(member,'read')`.
  - Iterates `state.variants`, excluding `rejected` unless requested.
  - Projects `{draftId, platform, language, account (via channel), revision, characters, limit (LIMITS[platform].characters), overLimit, needsReview, hasProposedUpdate, committed(bool), committedJobState, sourceCount, warningsCount, unknownsCount, writerModel (provenance.model), createdAt(run time via _run_times), excerpt≤160}`.
  - Opaque cursor; page 50, max 100.
  - **Never include full text in the model projection.**
- **`query: draft.read`**
  - Wraps `site_tools.run('draft.get', {draftId}, Context)` for metadata.
  - Adds a **browser-only** `fullText` from the same snapshot, bound to `revision`, for the edit form.
  - The `revision` must be returned and echoed into the action binding's target revision.
- **`query: draft.evidence`**
  - `graph.neighbours(state,'draft',id)`, plus source titles and approved-fact counts from `state.sources` (after `source_policy.stamp`), plus `voice_check`.
- **`action: draft.edit`**
  - Build a `RafiiRunContext` for the artifact's conversation (principal from the transaction, `trace_id = contracts.new_trace_id()`, `run_id = artifact.runId`, `zone`).
  - Call `tool_adapter.execute(ctx, REGISTRY['draft_edit'], {draftId, revision, text}, scope=frozenset({'draft_edit'}))`.
  - Wrap it with D's durable idempotency record (key + input digest gives the stored `UiActionResultV1`), plus one retry on `workspace_revision_conflict` only.
  - `verified` comes from the tool's re-read.
  - `changedRefs=[draft:id]`; `invalidationKeys=[snapshot, drafts.list, draft.read:id]`.
- **`action: draft.rewrite` / `draft.adapt`:** see D-4. Recommended: **continue the conversation** with an agent turn `POST /api/workspaces/{w}/agent/turns` carrying:
  - `command:{name:'rewrite'|'translate'|'repurpose', args}`;
  - `references:[{kind:'post', id:draftId, role:'rework'}]` (chip shape `turn_references.parse`, `turn_references.py:135-171`);
  - the conversation's `model` (writer);
  - [after D-5] `voiceMode`.

  This keeps Manager authority, the credit admission plan, the writer choice and follow-up context. A direct `execute(draft_rewrite)` from a UI action is possible but is a paid writer call outside the turn's admission plan, so it would need B to reserve against the original turn budget.
- Selection of drafts ("compare the selected two") is interaction context only; it is never approval. Record `{artifactId, revision, entity refs in displayed order}` into `siteAgent.refs`-compatible structure (see D-6).

---

## J02 — Calendar and publishing operations

### J02.1 Records [V]
- **Reviews (awaiting approval):** `state.phase2.reviews[]` with `{id, status ('needs_review'|'approved'|'stale'|…), manifest{variantId, channelId, account, platform, payload{text,language}, timing{local,timeZone,fold,utc,timestamp,tzdb}, expiresAt, …}, digest, jobId?}`. The manifest is built by `store.py:418-423` (`resolve_time`; `expiresAt = timing.timestamp + 3600`).
- **Jobs (approved and queued):** `state.phase2.jobs[]` with `{id, manifest (copy of review manifest), approvalDigest, approvedAt, approvedBy, state, events[], attempts[], nextAt, cancelRequested, scheduleId, providerReference?, automation?}` (`store.py:315`).
  - Job states and plain meanings: `site_agent/tools.JOB_STATES` (`tools.py:208-223`).
  - `WAITING=("approved","scheduled","claimed")`, `IN_FLIGHT`, `ATTENTION=("held","failed","uncertain")` (`:224-226`).
- **Automation-planned items:** `campaigns._root(state)["occurrences"][].items[] {publishAt, state, platform, account, channelId, jobId?}`.
- **Status buckets:** `calendar_status(kind, state)` and `calendar_status_counts(entries)` (`tools.py:230-269`) give `scheduled | awaiting_approval | in_flight | failed_held_uncertain | published | verified | unknown`. Unknown is never folded into scheduled and never reported as zero.
- **Web mirrors:** `web/src/features/calendar/calendar-kinds.ts` (`KINDS`, `KIND_META`, `WAITING_STATES`, `IN_FLIGHT_STATES`); live refresh in `use-calendar-live.ts` (`LIVE_REFRESH_MS=30_000`, skipped when hidden).

### J02.2 Read functions [V]

| Purpose | Function | Bounds / caveats |
|---|---|---|
| Calendar range | `site_agent/reads.calendar_range(ctx, start=None, end=None, label=None, platform=None)` (`reads.py:301-341`); agent `calendar_range`; schema `start/end` epoch numbers | Defaults to "this week" in `ctx.zone`. `days[]` capped at 62. **Entries shown capped at 30** (`total` is complete). Each shown entry has only `kind,id,state,title,platform,account,when(local string),href,status`: **no epoch/ISO instant and no per-entry zone [GAP]**. Derived observations carry their rule: `emptyDays`, `closeTogether` (same account `< CLOSE_SECONDS = 2h`, `reads.py:22`), `similarText` (≥ 60% shared words). |
| Raw range entries | `reads._entries(ctx, start, end, zone)` (`reads.py:262-291`) | Complete and sorted. Has `at` epoch, `channelId`, text. Private helper; the best base for a paged agenda/week adapter. |
| Queue status | `site_agent/tools.queue_summary(ctx)` (`tools.py:442-459`); agent `queue_summary` | Lists truncated: waiting ≤ 6, upcoming ≤ 5, attention ≤ 5, recent ≤ 3. `statusCounts` and `unknownStates` are complete. `draftsUnscheduled` count. |
| One job/review | `tools.job_get(ctx, jobId)` (`tools.py:462-481`) | A job has `timeline[-8:]`, `excerpt`, `timeZone`, `publishAt(local)`. A review has an expired/stale meaning. |
| Publishing results | `reads.publishing_summary(ctx, start=None, end=None, label=None)` (`reads.py:453`) | |
| Reviews | `reads.reviews_list(ctx)` (`reads.py:423`) | |
| Open proposals | `agent_runtime_v2/approvals.open_proposals(cur, workspace_id, conversation_id, now)` (`approvals.py:52-62`); agent `pending_approvals` | Scans the latest 40 assistant answers in that conversation |

### J02.3 Prepare reschedule / schedule — existing proposal machinery [V]
- **Tool:** `domain_tools.schedule_propose` (`domain_tools.py:161-225`). `ToolSpec(PREPARE_EXTERNAL, permission "approve", approval=True, idempotent=False, audit="post.review_prepared_by_proposal")`. Args: `{draftId?|jobId?, when, assetId?, alt?, stepId?}`.
  - Resolves `when` via `resolve_when`.
  - Refuses without the `approve` permission.
  - Requires an unambiguous non-revoked channel (it never picks one: `needs_account`).
  - Instagram needs an image, with alt text required.
- **Builder:** `site_agent/proposals.build_schedule(state, *, variant, channel, local_time, zone, actor, now, commands, job=None, accept_update=False, media=None, picked=None)` (`proposals.py:120-185`).
  - Dry-runs `p2_cancel` (when moving a job), `accept_update`, `p2_variant_review` and `p2_review` **on a deepcopy**.
  - Proposal types `schedule_draft | reschedule_post`.
  - Fields: `variantId, variantRevision, channelId, localTime, timeZone, jobId, acknowledgedWarnings, acceptUpdate{runId,textDigest}?, confirmReview{excludedUnknowns}?, media?, summary[], preview{before,after}, before{variantRevision,jobState}, requiredPermission:'approve', needsEdit, createdBy, createdAt, expiresAt=now+TTL_SECONDS (24 h, :22), text, digest`.
  - Digest: `proposal_digest(proposal)` (`proposals.py:42-49`) over `type, taskId, changes, before, createdBy, variantId, variantRevision, channelId, localTime, timeZone, jobId, acknowledgedWarnings`, plus `acceptUpdate`, `confirmReview` and `media` when present. **`summary` is not in the digest.**
  - Only a job in `WAITING_JOBS=("approved","scheduled","claimed")` can be moved (`:38-39`, `:130-131`).
- **Collision warnings [GAP]:** `build_schedule` does **not** check collisions with existing posts on the same account. The only collision logic is `calendar_range.derived.closeTogether` over existing entries. A "target slot conflicts" check needs a thin adapter using `reads._entries` and `CLOSE_SECONDS` for the target channel within ±2 h, excluding the job being moved. It should be stated as a derived observation with its rule.
- **Check / apply:**
  - `proposals.check(proposal, *, digest_value, now)` (`:188-195`): `409 proposal_closed | proposal_expired | proposal_digest`.
  - `proposals.apply(state, proposal, *, actor, now, owner, paid, zone, commands, can_approve, can_edit)` (`:198-234`): `409 proposal_stale` on draft-revision change, rewrite change or job no longer waiting. It runs the real `p2_cancel / accept_update / p2_variant_review / p2_review`. The result is a **review waiting for approval**, never a publication.
- **Browser view:** `proposals.view(proposal, now)` (`:237-244`). It hides `createdBy`, and a lapsed open proposal shows as `expired`.

### J02.4 The ORIGINAL apply/dismiss endpoints (approvals decide) [V]
1. **`POST /api/workspaces/{w}/site-agent/proposals/apply`** and **`/dismiss`** (`hosted_app.py:421-426`).
   - Apply calls `SiteAgentService.apply_proposal(workspace_id, token, payload)` (`site_agent/service.py:1082-1144`) with body `{messageId, conversationId, proposalId, digest, expectedRevision, timeZone?}`. It:
     - requires `approve` (scheduling) or `edit` (automation), plus `edit` when `needsEdit`;
     - runs `proposals.check`;
     - calls `repository.command(…, expectedRevision, …, after=…)`. The `after` hook re-locks the message, re-checks digest/expiry, re-checks owner/edit roles from `pr_memberships`, runs `billing.require_publishing(cur, …)` (plan gate), stores `status='applied'` + `result`, and audits `post.review_prepared_by_proposal` / `automation.changed_by_proposal`;
     - on `proposal_stale`/`proposal_expired`, marks the proposal `superseded`/`expired`.
   - **Double-click:** the second apply gets `409 proposal_closed` (status-transition idempotency).
   - Dismiss calls `dismiss_proposal` (`:1146-1155`); it is idempotent for a non-open proposal.
   - **Used today** by the native `ProposalCard` in `web/src/features/site-agent/answer.tsx:403-470`. That card retries once on `workspace_revision_conflict` and on a lost reply says "may already have been applied" and refreshes. It is rendered for `proposal_diff` blocks in `SiteAgentAnswer` (`answer.tsx:95-118`), and is shared by the full chat (`features/agent/conversation-view.tsx:595`) and the panel (`features/site-agent/chat.tsx:555`).
2. **`POST /api/workspaces/{w}/agent/approvals/decide`** (`agent_runtime_v2/http.py:73-74`), handled by `service.decide(runtime, w, token, payload)` (`agent_runtime_v2/service.py:1187-1202`) and then `approvals.decide(service, w, token, *, conversation_id, message_id, proposal_id, digest, decision, zone=None)` (`approvals.py:136-163`).
   - Body: `{conversationId, messageId, proposalId, digest, decision:'apply'|'dismiss', timeZone?}`.
   - Wraps (1) and re-reads its own `expectedRevision` (one retry on `workspace_revision_conflict`).
   - Then `verify_applied(state, proposal)` (`approvals.py:102-133`), which checks that a review exists for the exact variant, local time and channel, that `status=='needs_review'`, the image, and that the old job is canceled.
   - Then `_resolve_task_steps` and the resume of a paused SDK run. Returns `{outcome, verified, checks, proposal, result, speakableSummary}`.
   - Web client: `createAgentApi().decide` (`web/src/lib/agent-runtime/client.ts:64-65`). There is currently no visual caller; it serves the voice/server path.
   - **[I] Recommended native confirm target:** (2), because it alone yields `verified` and re-read `checks` that map to `UiActionResultV1.verified`. The visual must stay the native ProposalCard surface (D-3).
- **Spoken binding:** `approvals.bind(cur, w, conversation, now)` (`approvals.py:73-99`; `BIND_WINDOW_SECONDS=600`). It works only for the proposal presented in the **latest** answer. Where a GenUI-prepared proposal is stored therefore changes voice "yes" behaviour (D-2).

### J02.5 Existing tests [V]
- `tests/test_site_agent.py`: `test_calendar_card_reads_range_and_queue_state` `:237`, `test_calendar_and_queue_expose_exact_distinct_status_counts` `:293`, `test_foreign_ids_are_not_found` `:310`, `test_calendar_answer_is_a_typed_read_only_card` `:380`, `test_stale_expired_and_tampered_proposals_are_refused` `:649`.
- `tests/test_agent_runtime.py`: `test_schedule_proposal_verified_against_the_review` `:260`, `test_calendar_evidence_keeps_the_typed_read_only_card` `:483`.
- `tests/phase2/postgres_agent_runtime.py`: S-MOD2/S-MOD3/S-MOD5 (`:1078-1110`), decide + double apply denied `:1130-1136`, cross-workspace decide denied `:774`.
- `tests/phase2/postgres_site_agent.py`, `postgres_site_agent_scenarios.py`.
- Web: `web/tests/calendar-card.test.cjs`, `calendar-card-browser.cjs`.

### J02.6 Thin adapters [I]
- **`query: calendar.agenda`**
  - Args: `{start(ISO date), end(ISO date), zone (IANA, validated with safe_zone), platform?, channelId?, cursor?}`.
  - Range ≤ 366 days per contract. Keep the day buckets at the existing ≤ 62-day bound, or document the widened bound.
  - Uses `reads._entries` (complete) and paginates entries 50/100.
  - Each entry: `{kind, id, state, status (calendar_status), platform, account, channelId, atUtc (ISO), local (in requested zone), jobZone (manifest.timing.timeZone), fromAutomation, href}`.
  - Plus `calendar_status_counts` over the **whole** range, `unknownStates`, and derived observations with rules (reuse `calendar_range`'s `derived` block computation).
  - `asOf = observedAt`.
- **`query: queue.status`**
  - `tools.queue_summary` gives counts; for full lists, page jobs and reviews directly with `_job_view(ctx, job)`.
- **`query: schedule.slot_check`** (new, D)
  - Args: `{draftId|jobId, local, zone, channelId?}`.
  - Calls `resolve_time` for validity, DST and past-time errors as the app phrases them.
  - Finds same-account entries within `CLOSE_SECONDS`.
  - Read only; it creates nothing.
- **`action: schedule.prepare`** (prepares only)
  - Build a `RafiiRunContext`, then call `tool_adapter.execute(ctx, REGISTRY['schedule_propose'], {draftId|jobId, when:'YYYY-MM-DDTHH:MM', assetId?, alt?}, scope=frozenset({'schedule_propose'}))` with `ctx.zone` = the user-chosen zone.
  - On `ok` with `ctx.ledger.proposals[-1]`, persist it to an assistant message in the same conversation (D-2). Return `outcome:'prepared', verified:true (proposal stored and re-read), proposalRef=proposalId, receiptRef=messageId`.
  - **Never** call apply from GenUI.
  - Durable idempotency: same key gives the same `proposalId` (`schedule_propose` is `idempotent=False`, so a replay would otherwise create a second proposal).
- **Apply/dismiss:** native only, through D-3. GenUI may show "needs your review" state; the native card shows the precise target, `localTime (timeZone)`, summary, expiry and warnings.

---

## J03 — Universal Library / Living Archive

### J03.1 Two physical stores [V]
1. **Normalized files** (documents, audio, generic files): `public.pr_library_assets`.
   - Columns:
     - identity: `id uuid`, `workspace_id`, `created_by`, `original_filename`, `display_title`, `title_source`;
     - descriptive: `summary`, `tags[]`, `kind ('document'|'file'|'audio')`, `mime`, `extension`, `bytes ≤ 50 MiB`, `sha256`;
     - storage: `bucket`, `object_name '^[0-9a-f]{32}\.[a-z0-9]{1,12}$'`, `etag`;
     - statuses: `processing_status (pending|queued|processing|ready|failed|unsupported|duplicate|deleting)`, `analysis_status`, `indexing_status`, `extraction_error`;
     - `provenance jsonb`, `token_expires_at`, `attempts`, `lease_token`, `lease_expires_at`, `next_attempt_at`;
     - `duplicate_of`, `transcription_status (not_applicable|unavailable|ready)`, `source_id text`, `created_at`, `updated_at`.
   - Chunks: `pr_library_chunks(asset_id, workspace_id, ordinal, text ≤ 12000, search_vector)`.
   - Labels and collections: `pr_library_labels(workspace_id, asset_key 32-hex, display_title, tags)`, `pr_library_collections(id, workspace_id, name, created_by)`, `pr_library_collection_items(workspace_id, collection_id, asset_key)`.
   - Service: `UniversalLibrary` (`src/postriff_phase2/library_assets.py:72ff`), mounted as `service.library`.
2. **Legacy photos/videos:** `state.phase2.assets[]` (JSON).
   - Fields: `id (32-hex)`, `mime`, `width/height`, `processing ('decoded' image | 'ready' video)`, `objectName`, `poster{objectName,hash,width,height,bytes}`, `frames[]`, `duration`, `lineage{parentAssetId, sourceAssetIds, operation}`, `alt`, `tags`, `createdAt`, `deleted`, `deletionPending`, `category`.
   - Predicates: `asset_kinds.kind_of / is_ready / is_library_asset / is_postable_image / is_postable_video` (`asset_kinds.py:15-65`).
- **"Links"** in J03 are **not** a Library row type. They are `state.sources[]` with `kind:'link'` (URL text, `unknowns:["Link contents were not fetched."]`, `postriff_alpha/domain.py:287-308`; default policy `rewrite_approval`, `source_policy.py:17`). **[I]** Render them as an external link with no server fetch or preview. An OG/preview fetch would be a new data egress and is not authorized.

### J03.2 Read / search / filter APIs [V]

| Route | Function | Permission | Notes |
|---|---|---|---|
| `GET /api/workspaces/{w}/library?q&limit&offset&kind&tag&collection&sort` (`hosted_app.py:893-896`) | `UniversalLibrary.list(w, t, query='', limit=100, offset=0, kind='all', tag='', collection='', sort='newest')` (`library_assets.py:362-386`) | `read` | `limit 1..200`, offset-paged, `kind ∈ all\|image\|video\|audio\|document\|file`, `sort ∈ newest\|stored\|largest`. Full-text search over title/filename/summary/tags plus chunk `search_vector` and ILIKE. **[GAP] Legacy photos/videos are all appended on `offset==0` regardless of `limit`** (unbounded first page). Python word filter for legacy. Returns `{assets, query, nextOffset, storage{usedBytes,limitBytes}, capabilities{automaticTranscription:false, transcriptImport:true}}`. |
| `GET …/library/files/{id}` (`:906-908`) | `detail(w,t,i)` (`:236-244`) | `read` | `asset` + first 17 chunks + `extractedText ≤ 100k`. **Private document text.** |
| `GET …/library/collections` | `collections(w,t)` (`:280-298`) | `read` (`edit` for POST/DELETE) | |
| `GET …/library/files/{id}/url[?download=1]` (`:927`) | `url(w,t,i,download=False)` (`:316-326`) | `read` | **Signed storage URL, 300 s** (`hosted_storage.signed_url`, `hosted_storage.py:215`, 60..600 s). Active types (`html/htm/json`, kind `file`) are forced to download. |
| `GET /api/workspaces/{w}/media/{assetId}` (`hosted_app.py:942-945`) | `HostedWorkspaceService.media()` (`hosted.py:1242-1254`) | `read` (via `repository.get`) | **Authenticated bytes**, `Cache-Control: private, no-store`. A video serves its poster JPEG. Used by `agentApi.media` (`client.ts:73-78`) and `api.media`. |
| `GET /api/workspaces/{w}/media/{assetId}/url` (`hosted_app.py:940-941`) | `VideoUploads.url()` (`video_uploads.py:422-436`) | `read` | **Signed video playback URL, 600 s**, audited `media.url_signed`. |
| Agent `library_search` / `library_read` | `site_agent/library_reads.library_search(ctx, query='', limit=10)` / `library_read(ctx, assetId)` (`library_reads.py:24-62`) | `read` | **AI retrieval gate.** Only sources with `origin.kind=='library'`, `source_policy.classify(source,'draft','cloud')` admitted, **approved facts**, and an `origin.sha256` that still matches the asset. Otherwise empty, with a "review facts / allow cloud sharing" warning. |
| Picker | `reads.picker_search(…, categories=['library'])` (`reads.py:767-774`) | `read` | **Legacy photos/videos only** (no normalized documents). `href` is the authenticated `/api/workspaces/{w}/media/{id}` path (not a signed URL). |
| Lineage | `graph.neighbours(state,'asset',id)` (`graph.py:116-131`); `graph.neighbours(state,'source',id)` (`:143-150`) | `read` | **[GAP] Asset lineage covers only legacy `state.phase2.assets`.** For normalized files, lineage is `pr_library_assets.source_id`, then `state.sources[].origin{kind:'library', assetId, sha256}`, then drafts with that id in `sourceIds`, plus `duplicate_of`. Needs a thin adapter. |

### J03.3 Write / prepare paths (user-triggered only) [V]
- **Metadata:** `PATCH …/library/assets/{id}` or `PATCH …/library/files/{id}` reach `metadata(w,t,i,{title?,tags?,collections?})` (`library_assets.py:249-278`). Requires `edit`; sample workspaces are read-only. **No revision/CAS token: last write wins [GAP for contract §5].**
- **Use as draft source (the "selection for a draft" bridge for documents):** `POST …/library/files/{id}/source` with `{expectedRevision}` reaches `as_source(w,t,i,body)` (`:431-462`).
  - Imports ≤ 19,000 characters of extracted text as `state.sources[]` with `origin{kind:'library', assetId, sha256, locator, clipped}`, `sourcePolicy='rewrite_approval'`, `egressConsent=['local']`, `status 'needs_review'`.
  - It is never auto-approved for AI egress or publication.
  - The `after` hook refuses if the asset text or sha changed.
  - Idempotent when `source_id` is already set.
  - Audit `library.source_imported`.
- **Selection for a draft (photos/videos):** chip `attachments:[{assetId, role:'post'|'reference', slot?}]` in the agent turn payload (`turn_references.parse`, `turn_references.py:135-171`; `MAX_ATTACHMENTS=4`; `agent_runtime_v2/service.py:96-98`, `:480-481`).
- **Selection for a draft (imported document source):** `references:[{kind:'source', id: sourceId}]`. A normalized document with no `source_id` **cannot be referenced directly** [GAP; it must go through `as_source`, an edit-class mutation needing explicit confirmation]. Audio has extraction status `unsupported` until a user transcript is added via `POST …/transcript`.
- Delete, retry, upload and transcript exist (`:122-234`, `:300-314`, `:328-339`). **Delete stays outside GenUI** (destructive).

### J03.4 Ownership, consent, privacy [V]
- **Every read** runs inside `repository.transaction` (membership-verified principal) with `WHERE workspace_id=%s AND id=%s`. A foreign or malformed id returns `404 'File unavailable.'` (`_row`, `library_assets.py:86-93`). Existing negative test: `tests/phase2/postgres_library.py:136-141` ("isolation: foreign workspace cannot resolve asset").
- **Model egress of photos/frames:** `media_consent` (owner action `media_egress`; `allowed/require(state, purpose, processor)`, `media_consent.py:40-53`).
- **Model egress of document text:** `source_policy.classify(source, operation, provider_class)` (`source_policy.py:76`) plus approved facts (`library_reads._admitted`).
- **`_asset()` projection** (`library_assets.py:54-69`) exposes `createdBy`/`uploadedBy` (user UUIDs), `provenance` (may contain `transcriptBy` principal), `object_name` is **not** exposed, `sha256` is exposed.
- **Private-URL rule for GenUI [I, mandatory]:**
  - The model, prompt, DSL, persisted `safeState` and manifest receive **only** opaque refs (`{kind:'library_file'|'media', id}`) plus non-secret metadata.
  - Signed URLs from `url()`, `VideoUploads.url()` and PR #134 `preview()/viewer_page()` are fetched **by the browser renderer at display time** via the authenticated routes above, never cached in the artifact. They expire in 300–600 s.
  - The existing component `AssetFileThumbnail` (`web/src/features/library/asset-thumbnail.tsx:162-168`) already does exactly this (React Query `libraryFileUrl`, `staleTime 3 min`, private PDF iframe). Reuse it or its successor; do not re-implement URL handling in generated code.

### J03.5 Thumbnails / previews state at baseline vs PR #134 [V]
- **Baseline 3da806f0** (`web/src/features/library/asset-thumbnail.tsx`):
  - images and video posters come through the authenticated `/media/{id}` blob;
  - **PDF first page** is a sandboxed iframe of the 300 s signed URL (`PdfFirstPage`, `:105-124`);
  - other documents get a **CSS cover with extracted text** (`DocumentCover`, `:27-89`);
  - audio gets a deterministic waveform cover (`AudioCover`);
  - generic files get a format cover.
  - There is no server-rendered document thumbnail at baseline.
- **PR #134** (OPEN, **draft**, head `codex/rafii-real-document-previews-20261008`, updated 2026-10-08T16:29Z) adds:
  - `src/postriff_phase2/library_preview.py` (new, `VERSION='source-page-v1'`, LibreOffice → PDFium JPEG in a seccomp no-network child, `SUPPORTED` = pdf/docx/xlsx/pptx/doc/xls/ppt/odt/ods/odp/rtf/txt/md/markdown/html/htm/csv/json);
  - `UniversalLibrary.preview()` and `viewer_page(w,t,i,page)`, which return **signed `media`-category URLs**, cache page metadata in `provenance.thumbnail`, count thumbnail bytes in storage capacity, and cap concurrency at 2 renders per workspace (429);
  - new routes `GET …/library/files/{id}/viewer?page=` and `GET …/library/files/{id}/preview` (`hosted_app.py` +6 lines at ≈ line 927);
  - legacy Office MIME types (`LEGACY`) in `library_extract.py`;
  - `_asset()` gains `canRetryProcessing` and strips `provenance.thumbnail.pages/claim`;
  - search by sha256 prefix;
  - web `document-viewer.tsx`, `gallery-media-preview.tsx`, a rewritten `asset-thumbnail.tsx` (−133/+41), `api/client.ts` (`libraryViewerPage`, `libraryPreviewUrl`, `get(…, timeoutMs)`), `api/types.ts` (`Asset.canRetryProcessing`, `SourceOrigin.assetId/sha256/filename/locator/clipped`);
  - **outside the Library** it also changes `vercel.json` (adds `buildCommand: python3 runtime/build_document_renderer.py && python3 runtime/provision_video_storage.py`; `excludeFiles` for `phone`), `requirements.txt` (+`pypdfium2==5.14.0`, `Markdown==3.11`), `web/package.json` (`test:library` script), `.github/workflows/*`, `.depot/workflows/james-cloud-build.yml`, `.james-cloud-build.json`, `.vercelignore`, `.gitignore`, and **`web/src/features/founder/agent/chat.tsx`** (session-ready gating).

**Conflict risk (PR #134) [I]:**

| Area | Risk | Why |
|---|---|---|
| `library_assets.py` / `hosted_app.py` library block / `library_extract.py` | **HIGH** for D | Any J03 adapter that edits `_asset()`, `list()` or the route block will textually conflict. |
| `vercel.json`, `requirements.txt`, `web/package.json`, CI workflows | **HIGH** for A (A-owned shared files) | A must sequence: either merge #134 first and rebase, or keep OpenUI changes to these files minimal and rebase after. |
| `web/src/lib/api/client.ts` / `types.ts` | **MEDIUM** for C/D/E | If they add API methods there. Prefer new modules under `generative-ui/bridges/`. |
| `asset-thumbnail.tsx` | **MEDIUM** for E | E must not fork it. Wrap whichever version lands. |
| `founder/agent/chat.tsx` | **MEDIUM** for F | Founder surface integration. |
| Security | Note | PR #134 previews are signed URLs and must obey the private-URL rule above. Its render path is a heavy subprocess. Never trigger it from Presenter or mount: browser display only, already bounded at 2 concurrent per workspace. |

- **[I] Mitigation:** D's J03 adapter should **call** `service.library.list/detail/collections` and **project**, never modify `library_assets.py`. The thumbnail capability must be feature-detected (`hasattr(service.library, 'preview')`) so the adapter works before and after #134.

### J03.6 Thin adapters [I]
- **`query: library.search`**
  - Args: `{q≤120, kind, tag≤40, collection(32-hex), sort, cursor}`.
  - Calls `service.library.list(w,t, q, limit=min(page,100), offset=cursor.offset, kind, tag, collection, sort)`.
  - Must **re-bound the merged list** (legacy plus normalized) to the page size and encode a cursor that covers legacy first-page overflow.
  - Project per item: `{ref:{type:'library_file'|'media', id}, kind, title (displayTitle\|originalFilename), mime, extension, bytes, createdAt, processing, indexingStatus, transcriptionStatus, tags, collections, hasSource(bool), duplicateOf, previewKind ('image'|'video_poster'|'pdf_page'|'document_cover'|'audio_cover'|'file_cover'|'server_page' when #134 present)}`.
  - **Drop** `createdBy`, `uploadedBy`, `provenance`, `sha256` (or a short prefix), `extractionError` raw text (map it to a code).
  - `coverage{known: returned, total: null}` (the endpoint gives no total), `asOf`.
  - Storage usage only if needed.
- **`query: library.item`**
  - Calls `detail()`. Returns metadata plus **browser-only** text excerpt (bounded) and chunk count.
  - The Presenter receives no extracted text unless `library_reads._admitted` admits that source for cloud (D-7).
- **`query: library.lineage`**
  - Legacy: `graph.neighbours(state,'asset',id)`.
  - Normalized: `source_id` → source → `graph.neighbours(state,'source',sourceId)`; plus `duplicate_of`.
- **`query: library.collections`** wraps `collections()`.
- **`action: library.use_as_source`**
  - User-triggered and edit class. Calls `service.library.as_source(w,t,i,{expectedRevision})` with a re-read workspace revision.
  - Result `{sourceId, status:'needs_review'}`, outcome `applied` (import) with honest `needs_review`.
  - Then the selection becomes a `references:[{kind:'source',id}]` chip for the next turn.
- **`action: library.select_for_draft`**
  - **No write.** Records interaction context: refs in order, artifact/revision.
  - For legacy media, offers the attachments chip on the next turn. Requires `media_consent` only when a model will look at the image (existing turn path enforces it).
- **`action: library.metadata`** (optional)
  - `metadata()`. Edit class. Needs a CAS decision (D-8). Otherwise exclude it from GenUI.

---

## 4. Cross-journey risks and gaps (summary)

1. **[GAP] Proposal persistence outside a turn (J02):** proposals must live on an assistant message (`pr_messages.body.siteAgent.proposals`) for the original apply/dismiss to find them (`site_agent/service.py:1060`).
2. **[GAP] Durable idempotency** is absent for `draft_edit`, `schedule_propose` (`idempotent=False`) and `library.metadata`. Writing-pipeline keys are bound to `trace_id`. Contract §5 needs a D-owned additive table (A owns the migration registry; next number after `096`).
3. **[GAP] Voice selection not forwarded** to the agent writing pipeline (J01). Writer is forwarded.
4. **[GAP] `draft_get` text truncated at 1,500 characters.** Seeding an edit form from it would truncate drafts on save.
5. **[GAP] 5-platform enum** in `draft_create`/`draft_rewrite` vs 22 platforms in `LIMITS`.
6. **[GAP] No collision check** on a proposed slot. `calendar_range` shows only 30 entries, without instants or per-entry zone.
7. **[GAP] DST `fold`** is not supported in scheduling proposals (ambiguous times are refused).
8. **[GAP] Library list:** unbounded legacy first page; offset (not cursor) paging; no total count; metadata last-write-wins; normalized-asset lineage absent from `graph.neighbours`; ordinal references have no `asset` type.
9. **[RISK] Two apply endpoints** exist (site-agent apply vs agent decide). GenUI must route to exactly one native path and never expose either as a generated control.
10. **[RISK] PR #134 overlap** with D/E files and with A-owned `vercel.json`/`requirements.txt`/`package.json`/CI.
11. **[RISK] Library data to the Presenter:** titles, filenames, extracted text and `createdBy` UUIDs are private workspace content. Policy needed (D-7).
12. **[RISK] Rewrite from GenUI** is a paid writer call. If executed outside a turn it bypasses the combined admission plan (spec §9).
13. **[V] Viewer role:** `edit` excludes viewer and approver. `schedule_propose` and apply need `approve`, which an editor without `can_publish` lacks. The UI must show the honest permission state from the action binding rather than hide it.

---

## 5. Decisions A must freeze (referenced above as D-1 … D-8)

- **D-1 Query execution seam.**
  - **Recommended:** `ui_queries.py` runs inside `service.repository.transaction(token, w)` with `require(member,'read')` and a `site_agent.tools.Context` built exactly as `SiteAgentService.search()` builds it.
  - Call either `site_tools.run(tool_id, args, ctx)` (validation + role check) or `UniversalLibrary.list/detail/collections`, then a D-owned projection whitelist.
  - Rejected: the generic agent `REGISTRY` executor for reads, because its schema allows Manager-oriented arguments, and because it would require a fake turn context.
- **D-2 Where a GenUI-prepared proposal lives.**
  - **Recommended:** create a new deterministic assistant message in the same conversation, `body.siteAgent = {intent:'agent', blocks:[proposal_diff(view)], proposals:[proposal], refs:[draft/job], model:{composedBy:'grounded'}}`, written through `ideas._append_message` plus an `action.proposed` run event, under one transaction.
  - Then the original `_proposal_row`/apply/dismiss and `approvals.bind` (latest answer, so a spoken "yes" still works) all work unchanged.
  - Alternative: append to the artifact's parent answer. This is weaker for voice binding and mutates an older message.
- **D-3 Native confirm endpoint.**
  - **Recommended:** native confirmation calls `POST /agent/approvals/decide` (re-read verification, task steps, paused-run resume). `verified` comes from `approvals.verify_applied`.
  - Keep the existing `ProposalCard` visual (or a native twin outside the generated subtree).
  - Never expose either apply route through `toolProvider`, a generated `Mutation`, or `execute_ui_action`.
  - A must also decide whether `ProposalCard` switches from `site-agent/proposals/apply` to `agent/approvals/decide` (behaviour-equivalent superset) or stays as is, with `decide` used only for GenUI-origin proposals.
- **D-4 Rewrite/adapt from GenUI.**
  - **Recommended:** an explicit "continue" control posts a normal agent turn (`command: rewrite|translate|repurpose`, `references:[{kind:'post', id, role:'rework'}]`, the conversation's `model`). It is metered by the existing turn admission; no direct paid writer call from `/agent/ui/actions`.
  - The result is a `proposedUpdate` that the person accepts natively (`accept_update`).
- **D-5 Voice continuity for agent drafts.**
  - **Recommended:** add `voiceMode` (`neutral|personalized`) and `voiceSourceIds` to the agent turn payload, then `RafiiRunContext`, then the `_writing_run` request (mirror of `writer_model`).
  - This is shared-file work (`agent_runtime_v2/service.py`, `context.py`, `domain_tools.py`) and A assigns a single owner.
  - Without it, J01 cannot honestly claim "preserve user-selected voice".
- **D-6 Selection memory.**
  - **Recommended:** record selections as an interaction entry whose refs use the existing `siteAgent.refs` shape `[{type,id,title}]` in displayed order at selection time, attached to the artifact's message or the next turn's `pageContext.selectedEntity`. `references.resolve` then resolves "the second draft" without a new resolver.
  - Add an `asset` type word only if J03 ordinals are required.
- **D-7 Library and draft content reaching the Presenter model.**
  - **Recommended:** the Presenter sees binding schemas, counts, kinds and opaque refs only. Titles, excerpts, extracted text and full draft text flow browser-side through `UiQuery` results bound by reference.
  - Any text given to the Presenter must pass `source_policy.classify(…,'cloud')` / `library_reads._admitted` and `memory.egress` exactly as Manager tools do.
  - Never include signed URLs, `createdBy` UUIDs or raw `provenance`.
- **D-8 Durable idempotency and CAS store.**
  - **Recommended:** one additive table (A allocates migration `097_*`): `pr_agent_ui_actions(workspace_id, principal, artifact_id, action_id, idempotency_key unique per workspace, input_digest, outcome jsonb, created_at)`, written in the same transaction as the domain command via `repository.command(after=…)` where possible.
  - Same key + same digest returns the stored result. Same key + different digest returns 409.
  - Library metadata edits: either exclude them from GenUI or add an `updated_at`-based precondition in D's adapter (read, compare, then `metadata()` under the same lock is not possible without editing `library_assets.py`, which conflicts with PR #134). Recommended: exclude from GenUI in this release, link to the Library page.

## 6. Worktree note

At the time of writing, `git status` in this worktree shows `M .depot/workflows/james-cloud-build.yml` and `M .james-cloud-build.json`. **These were not modified by this reader.** This reader created only this file. A should confirm who owns those edits before they are committed.
