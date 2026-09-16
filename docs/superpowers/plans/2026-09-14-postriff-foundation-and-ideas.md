# PostRiff Foundation and Ideas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current James Au Studio shell with the six-destination PostRiff shell and deliver the first production-quality Ideas workflow: persistent Codex-backed conversation, attachments/skills/access controls, platform variants, live previews, smart preflight, generated-image result cards, and an exact handoff to the existing delivery approval boundary.

**Architecture:** Keep the React 19 + TypeScript + Vite client and FastAPI + SQLite local service. Extract the monolithic application shell into feature modules. Add a server-owned, version-pinned Codex app-server broker over stdio with a compatibility fallback to the existing `studio_codex.py` bridge. Keep every external action outside the agent transport: the agent produces content artifacts and action proposals; PostRiff preflight, approval manifests, existing delivery workers, and receipts own execution.

**Tech Stack:** React 19.3, TypeScript 7, Vite 8, Tailwind 4, GSAP, Node built-in test runner, Python 3 standard `unittest`, FastAPI, SQLite, installed Codex CLI 0.154.0.

**Specs:**

- `docs/superpowers/specs/2026-09-14-postriff-product-design.md`
- `docs/superpowers/specs/2026-09-14-postriff-content-type-template-system.md`

## Global constraints

- Execute in the git-backed source worktree when implementation begins. The current `/Users/ouxianxing/Documents/James-Au-Studio` copy is not a Git repository, so do not invent commit receipts there.
- Do not alter or re-authorize provider connections as part of the shell/Ideas work.
- Do not make a chat message itself a publish, schedule, reply, or moderation instruction. It can only create an `ActionProposal`.
- Preserve identity-connected, capability-ready, action-submitted, published, and verified as distinct states.
- Do not surface chain-of-thought, raw app-server events, secrets, filesystem paths, or internal exception messages to the browser.
- Keep `/api/bootstrap`, current draft/template/assets routes, current agent routes, and delivery routes functional during migration.
- Use expected revisions for mutable resources and idempotency keys for run/action creation.
- Implement the smallest slice in each task, run its checks, repair failures, then continue.

---

## Task 1: Freeze the six-destination navigation contract

**Files:**

- Create: `studio/web/src/app/navigation.ts`
- Create: `studio/web/tests/navigation.test.ts`
- Modify: `studio/web/package.json`

- [ ] **Step 1: Add a failing navigation contract test**

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import { PRIMARY_NAV, utilityItems } from '../src/app/navigation.ts'

test('PostRiff exposes exactly six primary destinations', () => {
  assert.deepEqual(PRIMARY_NAV.map(item => item.label), [
    'Dashboard', 'Ideas', 'Scheduling', 'Channels', 'Analytics', 'Audience',
  ])
  assert.equal(new Set(PRIMARY_NAV.map(item => item.id)).size, 6)
})

test('technical utilities are not primary destinations', () => {
  const labels = PRIMARY_NAV.map(item => item.label)
  for (const label of ['Settings', 'Activity', 'Backups', 'Templates', 'Delivery']) {
    assert.equal(labels.includes(label), false)
  }
  assert.deepEqual(utilityItems.map(item => item.label), [
    'Settings', 'Activity & receipts', 'Backups & export', 'Help', 'App status',
  ])
})
```

- [ ] **Step 2: Confirm the test fails because the contract does not exist**

Run: `cd studio/web && npm test -- tests/navigation.test.ts`

Expected: FAIL with module-not-found for `src/app/navigation.ts`.

- [ ] **Step 3: Implement the typed navigation constants**

```ts
export type PrimaryPage =
  | 'dashboard' | 'ideas' | 'scheduling'
  | 'channels' | 'analytics' | 'audience'

export const PRIMARY_NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: 'home' },
  { id: 'ideas', label: 'Ideas', icon: 'spark' },
  { id: 'scheduling', label: 'Scheduling', icon: 'calendar' },
  { id: 'channels', label: 'Channels', icon: 'channels' },
  { id: 'analytics', label: 'Analytics', icon: 'chart' },
  { id: 'audience', label: 'Audience', icon: 'people' },
] as const satisfies readonly { id: PrimaryPage; label: string; icon: string }[]

export const utilityItems = [
  { id: 'settings', label: 'Settings' },
  { id: 'activity', label: 'Activity & receipts' },
  { id: 'backups', label: 'Backups & export' },
  { id: 'help', label: 'Help' },
  { id: 'status', label: 'App status' },
] as const
```

- [ ] **Step 4: Make the test script accept explicit test files**

Keep the default `tests/*.test.ts` behavior and ensure `npm test -- tests/navigation.test.ts` also works under Node's TypeScript stripping.

- [ ] **Step 5: Run unit test and typecheck**

Run: `cd studio/web && npm test && npm run typecheck`

Expected: PASS.

- [ ] **Step 6: Checkpoint in the tracked worktree**

```bash
git add studio/web/src/app/navigation.ts studio/web/tests/navigation.test.ts studio/web/package.json
git commit -m "feat(postriff): define six-destination navigation"
```

If `git rev-parse --is-inside-work-tree` is false, stop the commit step and report that implementation is running in the untracked copy.

## Task 2: Extract and rebrand the application shell

**Files:**

- Create: `studio/web/src/app/PostRiffShell.tsx`
- Create: `studio/web/src/app/UtilityMenu.tsx`
- Create: `studio/web/src/features/placeholders/PlaceholderPage.tsx`
- Modify: `studio/web/src/App.tsx`
- Modify: `studio/web/src/main.tsx`
- Modify: `studio/web/src/styles.css`
- Modify: `studio/web/index.html`
- Modify: `src/james_au_social/studio_api.py`
- Test: `studio/web/tests/navigation.test.ts`

- [ ] **Step 1: Extend the shell test with the default destination and URL parser**

Add assertions that `/` resolves to `dashboard`, `/ideas` to `ideas`, and an invalid path to `dashboard`. Run the test and confirm the new exports are missing.

- [ ] **Step 2: Build `PostRiffShell`**

Requirements:

- Brand reads `PostRiff`.
- Exactly six primary nav links render from `PRIMARY_NAV`.
- Sidebar collapses while retaining accessible names/tooltips.
- The header has page title, search, and one `+ Create` action.
- Utility menu owns Settings, Activity & receipts, Backups & export, Help, and App status.
- No permanent right-side agent rail is rendered.
- Mobile navigation uses Dashboard, Ideas, Scheduling, Audience, and More.

- [ ] **Step 3: Route existing content without deleting it**

For this transitional task:

- `Channels` renders the existing Channels content.
- `Ideas` temporarily mounts the existing Drafts editor and agent panel in the new content region.
- `Scheduling` temporarily mounts Calendar and Delivery under an internal view switch.
- Dashboard, Analytics, and Audience receive explicit “coming in this phase” functional placeholders, not dead navigation.
- Templates, Activity, and Settings remain reachable through contextual/utility routes.

- [ ] **Step 4: Rebrand browser and local fallback copy**

Update HTML title, `/api/health` app identifier to a versioned PostRiff value while preserving a compatibility field if clients depend on the old value, and the unbuilt frontend fallback. Do not rename storage folders or migration identifiers in this task.

- [ ] **Step 5: Split shell CSS into named sections**

Keep current warm off-white/charcoal/rust visual identity. Add focus styles, collapsed/sidebar responsive behavior, and reduced-motion handling. Do not perform a mechanical restyle of channel/provider components yet.

- [ ] **Step 6: Validate**

Run:

```bash
cd studio/web
npm test
npm run build
```

Expected: tests pass; TypeScript and Vite build succeed.

- [ ] **Step 7: Checkpoint**

Commit message: `feat(postriff): introduce simplified application shell`

## Task 3: Define Ideas domain contracts and pure state reducers

**Files:**

- Create: `studio/web/src/features/ideas/types.ts`
- Create: `studio/web/src/features/ideas/ideasState.ts`
- Create: `studio/web/tests/ideas-state.test.ts`
- Modify: `studio/web/src/types.ts`

- [ ] **Step 1: Write failing state tests**

Cover:

- Quick/Standard/Deep are the only UI reasoning choices.
- Drafting/Research/PostRiff workspace are the only capability profiles.
- Applying a canonical-draft edit updates uncustomized variants only.
- A customized variant is preserved until the user explicitly accepts a proposed update.
- A selected channel group expands into explicit account IDs.
- Missing/unavailable capability is not coerced to `false` or zero.
- Content-type IDs are namespaced/extensible rather than an exhaustive universal union.
- Content type, format, and destination variant can change independently without losing inputs.
- Catalog resolution separates PostRiff core, installed packs, workspace types, and private templates.

Representative contract:

```ts
export type ReasoningChoice = 'quick' | 'standard' | 'deep'
export type AccessProfile = 'drafting' | 'research' | 'postriff_workspace'

export interface PostVariant {
  id: string
  accountId: string
  platform: string
  revision: number
  body: string
  mediaIds: string[]
  language: string
  customized: boolean
  syncState: 'current' | 'update_available'
}
```

- [ ] **Step 2: Implement reducers as pure functions**

Use explicit events such as `canonical.updated`, `variant.customized`, `variant.updateAccepted`, `channelGroup.expanded`, `asset.selected`, and `preflight.replaced`. Do not mix API calls into the reducer.

- [ ] **Step 3: Add legacy adapters**

Write typed conversion functions from current `Draft`, `DraftInput`, `Channel`, and `Asset` shapes to the new Ideas view model. Unknown legacy fields remain preserved in an `extensions` map for round-trip safety.

- [ ] **Step 4: Validate**

Run: `cd studio/web && npm test && npm run typecheck`

Expected: PASS, including customized-variant preservation.

- [ ] **Step 5: Checkpoint**

Commit message: `feat(ideas): define conversation and variant state`

## Task 4: Add forward-only local persistence for conversations and artifacts

**Files:**

- Modify: `src/james_au_social/studio.py`
- Create: `tests/test_postriff_store.py`

- [ ] **Step 1: Add failing migration/store tests using a temporary directory**

Use standard `unittest` and `tempfile.TemporaryDirectory`. Cover:

- Empty database migrates to the new schema.
- Existing reviewed schema migrates without changing drafts, assets, runs, delivery reviews, jobs, or receipts.
- Unknown schema still fails closed.
- Conversation, message, attachment, content item, variant, and preflight issue round-trip.
- Optimistic revision conflicts return the existing stable error form.
- Backup excludes secrets and includes new content tables.

- [ ] **Step 2: Define normalized tables**

Add forward-only tables for:

```text
postriff_conversations
postriff_messages
postriff_attachments
postriff_content_items
postriff_post_variants
postriff_preflight_issues
postriff_agent_runs
postriff_agent_events
postriff_channel_groups
```

Use stable IDs, timestamps, revision columns for mutable aggregate roots, foreign keys where the reviewed store policy allows them, and JSON only for versioned extension data. Do not repurpose existing agent/draft rows destructively.

- [ ] **Step 3: Implement store methods**

Required methods:

```py
create_conversation(...)
list_conversations(...)
get_conversation(...)
append_message(...)
add_attachment(...)
create_agent_run(...)
append_agent_event(...)
update_content_item(...)
upsert_variant(...)
replace_preflight_issues(...)
save_channel_group(...)
```

Validate all accepted enum values and size limits server-side.

- [ ] **Step 4: Validate**

Run:

```bash
.venv/bin/python -m unittest tests.test_postriff_store -v
```

Expected: PASS; no existing table data changes outside the migration.

- [ ] **Step 5: Checkpoint**

Commit message: `feat(ideas): persist PostRiff conversations and artifacts`

## Task 5: Qualify and implement the server-owned Codex transport

**Files:**

- Create: `src/james_au_social/postriff_codex.py`
- Create: `studio/agent/app-server-policy.md`
- Create: `studio/agent/app-server-qualification.json`
- Create: `tests/test_postriff_codex.py`
- Modify: `src/james_au_social/studio_codex.py`

- [ ] **Step 1: Write failing policy tests**

Tests must prove:

- UI profile names map to server-owned model/reasoning/sandbox/network/tool allowlists.
- Client-supplied raw flags are rejected.
- Publishing, reply, moderation, connection, shell, secret, and arbitrary filesystem tools are absent.
- Unknown app-server events do not reach the UI event stream.
- Reasoning content and raw exception text are dropped.
- Version mismatch activates the content-only fallback and a safe status message.

- [ ] **Step 2: Add an app-server qualification command**

The command should:

1. Resolve the reviewed qualified Codex binary, never ambient `PATH` alone.
2. Verify exact version `0.154.0` for this release.
3. Generate/read the version-specific protocol schema.
4. Start app-server over stdio in a temporary test boundary.
5. Start a thread, create a harmless turn, observe completion, then close cleanly.
6. Record only non-sensitive capability results and hashes in `app-server-qualification.json`.

Any failed criterion leaves the new transport disabled.

- [ ] **Step 3: Implement a narrow broker interface**

```py
class PostRiffCodexBroker(Protocol):
    def status(self) -> dict: ...
    def start_thread(self, request: ThreadRequest) -> ThreadHandle: ...
    def resume_thread(self, thread_id: str) -> ThreadHandle: ...
    def start_turn(self, thread_id: str, request: TurnRequest) -> RunHandle: ...
    def cancel(self, run_id: str) -> None: ...
    def events(self, run_id: str, after: int) -> Iterable[SafeEvent]: ...
```

The concrete app-server process remains behind this interface. Add a fallback adapter over the current bounded `CodexEditorialProvider`.

- [ ] **Step 4: Map safe events**

Only emit:

```text
run.started
progress.updated
source.added
artifact.created
message.delta
message.completed
warning.created
action.proposed
run.completed
run.failed
run.cancelled
```

Add deterministic tests for every allowed event and for rejection of unknown events.

- [ ] **Step 5: Validate**

Run:

```bash
.venv/bin/python -m unittest tests.test_postriff_codex -v
/Users/ouxianxing/.local/bin/codex --version
```

Expected: unit tests pass; version matches qualification. If the live handshake is unavailable, record `validation_unavailable` with the exact reason and keep fallback active.

- [ ] **Step 6: Checkpoint**

Commit message: `feat(ideas): add qualified Codex conversation transport`

## Task 6: Add Ideas conversation, attachment, and event APIs

**Files:**

- Create: `src/james_au_social/postriff_ideas_api.py`
- Create: `tests/test_postriff_ideas_api.py`
- Modify: `src/james_au_social/studio_api.py`

- [ ] **Step 1: Write failing API tests**

Cover:

- List/create/get conversation.
- Add text, URL, document, image, and video attachment metadata with type/size validation.
- Start turn with expected revision, idempotency key, reasoning choice, access profile, explicit attachment IDs, skill IDs, and account IDs.
- Server rejects raw paths, raw Codex flags, unknown skills, or accounts outside the current workspace.
- SSE reconnect with `Last-Event-ID` does not duplicate events.
- Cancel is idempotent.
- App-server unavailable returns fallback capability state without leaking errors.

- [ ] **Step 2: Implement endpoints**

```text
GET/POST /api/ideas/conversations
GET      /api/ideas/conversations/{id}
POST     /api/ideas/conversations/{id}/turns
GET      /api/ideas/runs/{id}
GET      /api/ideas/runs/{id}/events
POST     /api/ideas/runs/{id}/cancel
POST     /api/ideas/attachments
GET      /api/ideas/capabilities
GET      /api/ideas/skills
```

SSE response headers disable buffering/caching. Persist the safe event before emitting it so refresh/resume is deterministic.

- [ ] **Step 3: Add attachment ingestion boundaries**

- Accept multipart upload only for local files.
- Enforce a per-type allowlist and configured size limit.
- Copy into the existing managed asset boundary; never retain an arbitrary client path.
- Record extraction/generation provenance.
- Treat extracted text and URLs as untrusted source content.

- [ ] **Step 4: Preserve old endpoints**

Do not remove `/api/agent/*`. Mark the old bridge capability as `legacyAgentBridge` in bootstrap and add `ideasAgent` capability separately.

- [ ] **Step 5: Validate**

Run: `.venv/bin/python -m unittest tests.test_postriff_ideas_api -v`

Expected: PASS, including reconnection/idempotency and safe errors.

- [ ] **Step 6: Checkpoint**

Commit message: `feat(ideas): expose resumable conversation API`

## Task 7: Build the persistent Ideas chat workspace

**Files:**

- Create: `studio/web/src/features/ideas/ideasApi.ts`
- Create: `studio/web/src/features/ideas/IdeasPage.tsx`
- Create: `studio/web/src/features/ideas/ConversationList.tsx`
- Create: `studio/web/src/features/ideas/ConversationStream.tsx`
- Create: `studio/web/src/features/ideas/ComposerDock.tsx`
- Create: `studio/web/src/features/ideas/RunCard.tsx`
- Create: `studio/web/src/features/ideas/ContentTypeLibrary.tsx`
- Create: `studio/web/src/features/ideas/ContentTypeBuilder.tsx`
- Create: `studio/web/src/features/ideas/PostTemplateDialog.tsx`
- Create: `studio/web/tests/ideas-api.test.ts`
- Modify: `studio/web/src/App.tsx`
- Modify: `studio/web/src/styles.css`

- [ ] **Step 1: Write failing API serialization and reducer tests**

Assert that the browser sends only friendly enums and IDs, merges SSE by sequence number, resumes after disconnect, and represents an interrupted run without losing the unsent draft.

- [ ] **Step 2: Implement the API client**

Use same-origin relative URLs, `AbortController`, and a typed SSE parser. Unknown event types are ignored and reported through a safe local diagnostic hook.

- [ ] **Step 3: Implement the three-pane Ideas layout**

- Left: conversations and draft states.
- Center: messages, progress, source/artifact cards, and composer.
- Right: preview placeholder connected to selected content/variant.
- Side panels collapse; Focus Mode expands center/right.
- On narrow screens, Chat/Edit/Preview use a segment control.

- [ ] **Step 4: Implement header and composer controls**

- Reasoning: Quick, Standard, Deep.
- Access: Drafting, Research, PostRiff workspace.
- Channel group/account selector with explicit expansion preview.
- Attach: URL/source, document, image, video, audio/transcript, existing post.
- Skills: Auto plus supported explicit choices.
- Post type: no more than four personalized suggestions, Browse, and Create a type.
- Format: independent family selector using the 10 required format IDs.
- Send, stop, retry, edit-and-resend.

The guided type builder asks one adaptive question at a time, accepts an example-based or manual path, produces a reviewable proposal, and saves only after confirmation. James's founder workspace must be able to install all 11 Creator Starter Pack types; unrelated workspaces must not receive them automatically.

Tooltips explain impact in one sentence. Never show sandbox flags.

- [ ] **Step 5: Implement safe run rendering**

Render progress, citations/sources, created artifacts, warnings, messages, and action proposals. No generic renderer may inject arbitrary event HTML.

- [ ] **Step 6: Validate**

Run:

```bash
cd studio/web
npm test
npm run build
```

Expected: PASS; Ideas is reachable from `/ideas`; refresh restores the active conversation.

- [ ] **Step 7: Checkpoint**

Commit message: `feat(ideas): build persistent PostRiff chat workspace`

## Task 8: Implement channel variants, previews, and smart preflight

**Files:**

- Create: `studio/web/src/features/ideas/VariantEditor.tsx`
- Create: `studio/web/src/features/ideas/PostPreview.tsx`
- Create: `studio/web/src/features/ideas/PreflightPanel.tsx`
- Create: `studio/web/src/features/ideas/preflight.ts`
- Create: `studio/web/tests/preflight.test.ts`
- Create: `src/james_au_social/postriff_preflight.py`
- Create: `tests/test_postriff_preflight.py`
- Modify: `studio/web/src/features/ideas/IdeasPage.tsx`

- [ ] **Step 1: Write a shared preflight fixture set**

Fixtures cover:

- Not publish-ready.
- Platform requires video.
- Upload incomplete.
- Character limit exceeded.
- Missing schedule/timezone.
- Account identity changed.
- Missing media recommendation.
- Missing alt text.
- Identical cross-platform copy.
- Language mismatch.
- Stale source.
- Recent duplicate.
- Aspect-ratio and time-slot tips.

- [ ] **Step 2: Write failing frontend and backend tests against the same fixture semantics**

Frontend tests cover grouping, sorting, counts, and quick-action mapping. Backend tests prove blockers are authoritative and client attempts cannot downgrade severity.

- [ ] **Step 3: Implement the composer pattern**

- Channel/account icons at top.
- Shared canonical editor.
- Per-channel `Customize` mode.
- Preview selector and platform approximation.
- Footer: Save draft, Schedule, Publish.
- Customized variants are never silently overwritten.

- [ ] **Step 4: Implement compact preflight**

Show one count/status control. The panel orders blockers, warnings, then tips and provides one quick action per issue. Each issue targets the affected account and variant.

- [ ] **Step 5: Implement authoritative server preflight**

Server uses current connection/capability state, stored variant revision, attachment status, schedule/timezone, and platform rules. Return a snapshot hash consumed by action preview; any content/account/time change invalidates it.

- [ ] **Step 6: Validate**

Run:

```bash
cd studio/web && npm test && npm run build
cd ../.. && .venv/bin/python -m unittest tests.test_postriff_preflight -v
```

Expected: PASS; visual warnings do not replace authoritative server blockers.

- [ ] **Step 7: Checkpoint**

Commit message: `feat(ideas): add channel previews and smart preflight`

## Task 9: Add generated-image result cards and media assignment

**Files:**

- Create: `studio/web/src/features/ideas/MediaResultCard.tsx`
- Create: `studio/web/src/features/ideas/MediaTray.tsx`
- Create: `src/james_au_social/postriff_media.py`
- Create: `tests/test_postriff_media.py`
- Modify: `studio/web/src/features/ideas/ConversationStream.tsx`
- Modify: `studio/web/src/features/ideas/VariantEditor.tsx`

- [ ] **Step 1: Write failing provenance and assignment tests**

Cover candidate, selected, rejected, and failed generation states; prompt/provider/version/timestamp provenance; alt text; rendition/crop; assign-to-all; assign-to-selected; and removal without deleting the source asset.

- [ ] **Step 2: Add a provider-neutral media job contract**

```py
class MediaJob:
    id: str
    kind: Literal['generate_image', 'create_variation', 'crop']
    status: Literal['candidate', 'running', 'completed', 'failed', 'cancelled']
    estimated_cost: Decimal | None
    cost_authorized: bool
    provenance: dict
```

The first implementation may use an available reviewed image-generation provider. If none is configured, return a clear unavailable state and keep upload/manual media fully functional.

- [ ] **Step 3: Enforce cost and external-transfer boundaries**

- Free/local job: execute within current creative authorization.
- Paid job: require estimated cost and explicit cost authorization.
- External provider receiving user media: disclose the transfer before first use under that capability.
- Never treat generated output as selected.

- [ ] **Step 4: Build inline result cards and tray**

Actions: zoom, select/reject, variation, crop, edit prompt, alt text, attach to all, attach to selected. Use actual managed asset URLs; no data URLs in persisted conversation state.

- [ ] **Step 5: Validate**

Run backend unit tests, frontend tests, build, and image decode/dimension checks on a deterministic fixture. Visually inspect selected/unselected/failed cards.

- [ ] **Step 6: Checkpoint**

Commit message: `feat(ideas): support generated media candidates`

## Task 10: Connect action proposals to exact schedule/publish approval

**Files:**

- Create: `src/james_au_social/postriff_actions.py`
- Create: `tests/test_postriff_actions.py`
- Create: `studio/web/src/features/ideas/ActionPreview.tsx`
- Create: `studio/web/tests/action-preview.test.ts`
- Modify: `src/james_au_social/studio_delivery.py`
- Modify: `src/james_au_social/studio_delivery_api.py`
- Modify: `studio/web/src/features/ideas/IdeasPage.tsx`

- [ ] **Step 1: Write failing approval-boundary tests**

Prove:

- A chat message mentioning “publish” creates only a proposal.
- Preview expands a channel group into exact account IDs and shows exclusions.
- Manifest binds content/media hashes, variant revisions, accounts, timing/timezone, and action.
- Any changed bound field invalidates approval.
- Unsupported destinations are not attempted.
- Partial results remain per account.
- An uncertain provider response is reconciled before any retry.
- Schedule approval does not authorize immediate publish; reply approval does not authorize post publication.

- [ ] **Step 2: Implement `ActionProposal` and `ApprovalManifest` adapters**

Reuse current delivery manifest/receipt semantics where compatible. Add an adapter rather than duplicating provider execution.

- [ ] **Step 3: Build the action preview UI**

Show exact account handle, platform, copy/media revision, timing, timezone, blockers, unsupported accounts, and what will happen. The final action button names the operation: `Schedule 6 posts` or `Publish 4 posts now`.

- [ ] **Step 4: Execute only through the existing delivery worker**

The Codex broker cannot call delivery endpoints. The browser submits the valid reviewed manifest to the PostRiff API, which uses the existing reviewed worker/ledger.

- [ ] **Step 5: Render receipts precisely**

Show `not attempted`, `blocked`, `submitted`, `published`, `verified`, and `failed` per destination. Never summarize partial execution as “published to all channels.”

- [ ] **Step 6: Validate**

Use mocked providers only for automated tests. Do not run a live post. Run:

```bash
.venv/bin/python -m unittest tests.test_postriff_actions -v
cd studio/web && npm test && npm run build
```

Expected: PASS; no external call occurs without a valid manifest.

- [ ] **Step 7: Checkpoint**

Commit message: `feat(ideas): hand proposals to exact delivery approval`

## Task 11: Add browser, accessibility, and regression acceptance

**Files:**

- Create: `scripts/verify_postriff_ui.py`
- Create: `docs/postriff/phase-1-acceptance.md`
- Modify: `studio/web/src/styles.css`
- Modify: affected Phase 1 components

- [ ] **Step 1: Start an isolated local test instance**

Use a temporary data directory and test port. Do not point acceptance tests at the user's live Studio database or provider sessions.

- [ ] **Step 2: Automate the critical browser path**

The script must verify:

1. PostRiff brand and exactly six primary destinations.
2. Settings/Activity/Templates/Delivery are absent from primary nav.
3. Ideas can create and resume a conversation.
4. Reasoning, access, skills, attachments, and channel-group controls work.
5. A fixture article creates a canonical brief and two platform variants.
6. One variant can be customized without overwrite.
7. A generated-image fixture card previews and assigns to one variant.
8. Preflight shows a media warning and a not-ready blocker.
9. Action preview lists exact accounts.
10. No live provider execution occurs.

- [ ] **Step 3: Add keyboard/accessibility acceptance**

Verify:

- Every primary destination, conversation, composer control, channel selector, preview tab, and action preview is keyboard reachable.
- Focus is visible.
- Dialog focus is trapped and restored.
- Status/error changes are announced.
- Account icons have platform + account labels.
- Drag-and-drop alternatives exist where Scheduling is visible.
- Reduced-motion media query removes nonessential transitions.

- [ ] **Step 4: Capture visual evidence**

Capture desktop at 1440 × 1000 and mobile at 390 × 844 for Dashboard, Ideas chat, Ideas preview/preflight, and Channels. Inspect the images; mechanical capture is not visual approval.

- [ ] **Step 5: Run the full Phase 1 validation**

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
cd studio/web
npm test
npm run build
cd ../..
.venv/bin/python scripts/verify_postriff_ui.py
```

Expected: all automated checks pass; visual review records pass/watch/fail per screenshot.

- [ ] **Step 6: Write the Phase 1 acceptance receipt**

Record:

- Exact source revision.
- Commands and results.
- Codex transport mode used: app-server or content-only fallback.
- Screenshots and visual verdicts.
- Confirmed absence of live publish/reply actions.
- Capability limitations by channel.
- Deferred Phase 2–4 work.

- [ ] **Step 7: Final tracked checkpoint**

Commit message: `test(postriff): verify foundation and Ideas workflow`

## Completion gate

Phase 1 is complete only when:

- The six-destination shell is real and visually inspected.
- Ideas supports a resumable persistent conversation with the requested controls.
- Ideas resolves a workspace-specific content-type catalog; James's workspace supports the full Creator pack without making it universal.
- Guided type creation, proposal review, private template reuse, and workspace sharing permissions are validated.
- URL/document/media attachment paths are validated.
- At least two native channel variants can be edited and previewed.
- Smart preflight is server-authoritative.
- Generated image candidates preview and attach without being auto-selected or published.
- Schedule/publish remains behind exact approval and current provider readiness.
- Full frontend/backend tests and build pass.
- The acceptance receipt distinguishes local validation from external execution.

Analytics and Audience placeholders do not count as implementation of those features; they remain planned for later phases of the product specification.
