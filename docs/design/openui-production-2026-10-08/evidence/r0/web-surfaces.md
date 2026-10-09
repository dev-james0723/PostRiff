# R0 map — Web surfaces (lanes C / F)

**Reader:** read-only R0 baseline reader for role A.
**Worktree:** `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008` at `3da806f0` (branch `claude/rafii-openui-production-20261008`), clean except the untracked engineering package.
**Method:** `rg`/`sed`/`cat` only. No builds, no installs, no tests run. Line numbers are from this SHA.
**Legend:** **[V]** = verified code fact (file:line read). **[I]** = inference / recommendation, not yet proven.

All paths below are relative to `web/` unless they start with `src/postriff_phase2`, `.github`, `vercel.json`, `scripts/` or `docs/`.

---

## 0. Ten facts that change the plan

1. **[V] No OpenUI code exists anywhere.** No `@openuidev/*` dependency, no `generative-ui/` directory, no `lib/agent-runtime/ui-*`, no `tests/fixtures/agent_ui/`. Every C/F path in `03-PARALLEL-EXECUTION.md` is a new file.
2. **[V] The web has no streaming client.** No `getReader()`, `EventSource` or `text/event-stream` use in `src/`. "Live" progress is polling everywhere: `features/agent/use-run.ts:30-43` polls `GET /ideas/runs/{id}/events?cursor=0` every 1200 ms with backoff up to 15 s and 20 failures. The founder chat polls `GET /api/control/v2/agent/runs/{id}` every 1500 ms, up to 80 times (`features/founder/agent/chat.tsx:33-35,108-126`). `lib/agent-runtime/live-transport.ts` is the GPT-Live **WebRTC voice** transport, not a run stream. `useUiArtifactStream` has to be written from scratch on `fetch` + `ReadableStream` + `TextDecoder({stream:true})`.
3. **[V] The backend agent routes are WSGI and return full JSON bodies** (`src/postriff_phase2/agent_runtime_v2/http.py:46-86`, `app._json(...)`). Streaming SSE needs an iterator/flushing response, which is a B/A concern. The new consumer UI routes `/api/workspaces/{w}/agent/ui/...` land in `handle()`, where `resource = parts[4]` would be `"ui"`.
4. **[V] Every `/api/*` request on Vercel goes to Python** (`vercel.json` rewrite `"/api/(.*)" → postriff_api`). The only Next route handler is `src/app/auth/callback/route.ts`. A Node parser-validation seam must use either a non-`/api` Next route or an explicit rewrite placed before the catch-all (see D4).
5. **[V] The agent-runtime assistant message body has a fixed shape**, persisted in `public.pr_messages.body` (`src/postriff_phase2/agent_runtime_v2/service.py:879-884`): `{ text, runId, siteAgent: {...SiteAgentBody}, agent: {...AgentResult, pendingApprovals} }`. The panel and the full chat both render `body.siteAgent` through `SiteAgentAnswer`. Today nothing carries an artifact reference.
6. **[V] There is no "expanded" mode today.** The panel has three frames only: a docked column (≥1024 px), a sheet shown above another dialog, and an overlay (right sheet on tablets ≥768 px, full-screen sheet on phones). Everything uses base-ui `Dialog` through `components/ui/sheet.tsx`. **`vaul` is in `package.json` but nothing imports it.**
7. **[V] The backend's page context cannot carry a UI selection.** `src/postriff_phase2/site_agent/contracts.py:100-110` forces `selectedEntity={type:'conversation'}` on the conversation route and drops any entity type that isn't in that route's manifest `entityTypes` (`issues: entity_dropped`). Generated-UI selections need their own turn field.
8. **[V] The panel log container is a live region:** `role='log' aria-live='polite' aria-relevant='additions'` (`features/site-agent/chat.tsx:397`, founder `chat.tsx:247`). Without `aria-busy` or a separate announcer, every streamed DOM addition would be read aloud.
9. **[V] The panel always forces a dark violet palette** (`styles/rafii.css:506-524`, `.rafii-chat`), but the `--chart-1..5` tokens stay the light-theme values: `oklch(0.2 0 0)` for chart-1 (`rafii.css:95-99`). A recharts chart in the panel would draw near-black lines on `#0d0c14`.
10. **[V] The founder thread lives only in memory** (`features/founder/agent/store.ts:42`, `threads: Record<string, FounderThreadItem[]>`). Only the conversation id is kept, in sessionStorage. A reload loses every rendered founder answer, so founder replay/resume needs a server read path.

---

## 1. Turn-result data model as the web sees it

### 1.1 Agent Runtime client and types
- **[V]** `lib/agent-runtime/client.ts:9` base `/api/workspaces/{w}/agent`. `createAgentApi(getToken)` at `:44-81`. Headers at `:45-49`: `Content-Type`, `APP_GUARD_HEADER` (`X-PostRiff-Request: founder-alpha`, from `lib/api/client.ts:78`) and `Authorization: Bearer <supabase token>`. GET uses `cache:'no-store'`. POST takes an optional `AbortSignal`. Errors become `ApiError(message,status,code)`.
  - Methods: `status`, `turn` (`POST /turns`, body passed through `turnPayload()` `:19-26`, which only sanitizes `command`), `run`, `activeRun`, `runEvents(cursor)`, `cancel`, `conversationState`, `decide` (`POST /approvals/decide`; **unused in the web today**), `attach`, `voiceStart`/`voiceTranscript`/`voiceEnd`, `media(w, assetId) → Blob` (authenticated private bytes).
- **[V]** `lib/agent-runtime/use-agent.ts:10-22`: `useAgent()` returns `{api, workspaceId, status, statusError}`. Status is a react-query `['agent-runtime','status',w]` with a 60 s staleTime.
- **[V]** `lib/agent-runtime/types.ts`:
  - `AgentResult` `:76-93`: `version, traceId, modality, answerText, speakableSummary, references[], toolActivity[{tool,label,effect,status,latencyMs,specialist?,code?}], task: AgentTask|null, changedEntities[{type,id,change,verified}], pendingApprovals: PendingApproval[], generatedAssets[], warnings[{code,message}], errors[{code,message,step?}], blocks: SiteAgentBlock[], composedBy: 'manager'|'deterministic'|'site_agent'|'grounded', language?`.
  - `AgentTurnResponse` `:122-133`: `{conversationId, runId, messageId, status, result, fallback?, delegated?, traceId?, siteAgent?: SiteAgentTurnResult}`.
  - `AgentTurnRequest` `:135-153`: `message, idempotencyKey, conversationId?, modality, pageContext?, references?, attachments?, timeZone?, locale?, model?, traceId?, delegationId?, voiceSessionId?, supersede?, command?`. **There is no UI-context field.**
  - `AgentStatus` `:155-165`: `flags: Record<string,boolean>` (from `config.FLAGS`), `manager.available`, `voice.available`. This is the existing client-visible flag channel.
  - `PendingApproval` `:53-61`, `DecideResponse` `:196-201`.
- **[V]** `lib/site-agent/types.ts`:
  - `SiteAgentBlock` union `:130-154`: `text | citation_list | navigation_card | guide_card | voice_command | diagnostic_card | proposal_diff | question_form | warning | handoff_card | error | result_list | calendar_card`.
  - `SiteAgentBody` `:168-190`: `version, runId, status, intent, language?, blocks, citations?, grounding?, proposals?, context?{route,entity,read,withheld,stale}, model?{id,composedBy,phrasedBy}, followUps?, feedback?, refs?, compound?, pending?, role?, page?`.
  - `SiteAgentProposalView` `:42-70` carries `digest`, `expiresAt`, `requiredPermission`, preview `before`/`after`.
  - `SiteAgentPageContext` `:18-26`.
- **[V]** `lib/api/types.ts:939-946`: `Message {messageId, seq, role, body: Record<string,unknown>, runId, at}`. `Run` `:863-` (`events: SafeEvent[]`, `artifact`, `artifactHash`). `SafeEvent` `:762-784`.

### 1.2 Two turn pipelines (important for "full chat")
- **[V] Writing pipeline:** `POST /api/workspaces/{w}/ideas/conversations/{id}/turns` (`lib/api/client.ts:302-303`, 150 s timeout). Used by the full chat composer (`conversation-view.tsx:447`, `submitConversationTurn`). Returns a `Run` with variants and a plan. The assistant body is `AssistantBody` (`conversation-view.tsx:96-111`), with no `siteAgent` field.
- **[V] Agent runtime:** `POST /api/workspaces/{w}/agent/turns`. Used by the panel (`site-agent/chat.tsx:240-251`), by full-chat agent slash commands (`conversation-view.tsx:400-410`), by home slash commands (`home-view.tsx:435`, which then pushes to `/app/agent/{conversationId}`) and by voice delegations (`voice-session.ts:400-405`). The assistant body is `{text, runId, siteAgent, agent}`.
- **[V] Site-agent fallback:** `POST /api/workspaces/{w}/site-agent/turns`, then `/compose` (`lib/api/client.ts:412-413`). The panel uses it when `agent.status.manager.available` is false (`chat.tsx:103,259-266`).
- **[V]** Message reads. Full chat: `api.messageWindow` → `GET /ideas/conversations/{id}/window` (`client.ts:290-293`), with infinite pages in `conversation-view.tsx:161-166`. Panel: `useMessages` → `GET /ideas/conversations/{id}/messages` (`lib/api/hooks.ts:121-128`). Query keys are workspace-scoped: `keys.messages(w,id) = ['messages',w,id]` (`hooks.ts:24`).

---

## 2. Full Agent Chat — `features/agent/conversation-view.tsx` (836 lines)

**[V] Structure**
- `ConversationView` `:831-836` re-keys `ConversationWorkspace` with `${workspaceId}:${conversationId}`, so a workspace switch remounts and clears local state.
- `ConversationWorkspace` `:145-816`. The grid is `@container/conversation` (`:476-477`): conversations aside, then thread `<section>` (`:518`), then inspector aside (`:764-812`).
- Animation of newly arrived turns: `loadedIds` `:229-233`. Turns already in the thread render still.
- Anchor scroll `:197-204` uses `reduceMotion ? 'auto' : 'smooth'` (motion `useReducedMotion`).
- `lastAssistant` / `lastSiteAnswer` `:212-213`. `useRun(lastRunId, seed)` `:216` follows only the last **writing** run.
- After the run settles, `:327-333` invalidates the messages, snapshot and usage queries.

**[V] Per-message rendering** (`timeline.map` `:544-706`)
- Media moment `:545-558`.
- User turn `:562-576`.
- **Agent-runtime / site-agent answer `:577-602`.** `siteAnswer = body.siteAgent`. While running, `RafiiThinkingStatus` or a shimmer shows (`:586-593`). Otherwise `<SiteAgentAnswer body={siteAnswer} actions={{ messageId, conversationId, latest: messageId === lastSiteAnswer }} />` at **`:595`**, with the timestamp at `:597`.
  - **[V] Gap:** there is **no `onAsk`** here, so `question_form` options, follow-ups and "Ask Rafii to revise" are disabled in full chat (they render only when `actions.onAsk` exists; `answer.tsx:224,525,623`). `AgentExtras` (generated images, live task checklist) is **not** rendered in full chat, only in the panel.
- Writing-run answer `:603-705`, native layers in order:
  1. `ActivityStrip` `:611`
  2. `body.text` `:612`
  3. `UsedThisTime` `:613`
  4. memory `ProposalCard` `:614`
  5. `ChatAutomationCard` with quick reply only on the latest turn `:615-621`
  6. source exclusion warnings `:623-633`
  7. live run surface with `StreamingText` + `StreamCaret` and **Cancel** → `api.cancelRun` `:636-667`
  8. failed `StateMessage` `:668-670`
  9. `VariantCard` + `DraftPreview` `:671-678`
  10. `ImageGenerationCard` `:679`
  11. `PlanCard` (writing-run apply) `:680`
  12. "Not scheduled" line `:681-689`
  13. historical summary `:692-699`
- Composer `:722-756` (see §8). `CreditLimitField` `:718`. A viewer gets `StateMessage kind='permission'` at `:758`.

**[I] Insertion point, full chat.** Inside `<MessageContent>` (`:585`) of the `siteAnswer` branch, **after `:595` and before the `:597` timestamp**. A better alternative is the `SiteAgentAnswer` slot in §3.3. Condition: the message has an artifact reference (D1) and the GenUI flag is on. Surface = `'chat'`. Full chat needs its own continuation sender for `onContinue`. The writing-pipeline `sendTurn` (`:374-473`) cannot be used because it requires a channel selection (`:435-438`). Reuse the agent slash path pattern (`agent.api.turn(workspaceId, {message, idempotencyKey, conversationId, modality:'text', timeZone, ...choice.requestFields})` `:400-410`), then invalidate the messages, conversations, snapshot and usage queries (`:414-419`).

---

## 3. Site Agent panel

### 3.1 Frames — `features/site-agent/panel.tsx` (229 lines)
- **[V]** `DOCK_QUERY='(min-width: 1024px)'` `:24`. `PANEL_ID='rafii-panel'`, `LAUNCHER_ID='rafii-launcher'` `:25-26`. `useDocked()` `:36-38` (server snapshot `false`).
- **[V]** `SiteAgentHotkeys` `:90-115`: ⌘J/Ctrl+J toggles, `useRegisterStyleAction()`, renders `VoiceIndicator`.
- **[V]** `SiteAgentDock` `:118-147`: `<aside id=PANEL_ID class='rafii-panel sticky top-0 z-20 flex h-dvh w-[29rem] … xl:w-[33rem]'>` wrapping `<SiteAgentChat onClose/>` `:144`.
- **[V]** `SiteAgentAbove` `:152-180`: base-ui `Sheet side='right'` `sm:max-w-md` above another dialog, `<SiteAgentChat onClose={closeAbove}/>` `:176`.
- **[V]** `SiteAgentOverlay` `:183-229`. Tablet (`useWide` = `(min-width: 768px)`, `features/queue/use-wide.ts:5`): right sheet `sm:max-w-[36rem]`. **Phone:** `'rafii-elevated rafii-mobile-chat fixed inset-0 h-dvh max-h-dvh w-screen …'` `:222`. Mounts `<SiteAgentChat onClose onNavigate={close} autoFocus={wide}/>` `:225`. The iPhone keyboard is handled by `visualViewport` resize/scroll writing `--rafii-chat-visible-height`/`--rafii-chat-visible-top` (`:187-203`), consumed by `rafii.css:546-556`.
- **[V]** These frames are mounted once in `components/layout/app-shell.tsx:53-56`.
- **[V]** Escape handling: `useEscapeClosesOnlyRafii` `:74-87` ignores focus inside `[data-rafii-style-sheet]`/`[data-rafii-capabilities]`. A generated full-height sheet or popover inside the panel must be added to that skip list, or Escape will close the whole panel.

### 3.2 Conversation — `features/site-agent/chat.tsx` (569 lines)
- **[V]** `SiteAgentChat({onClose,onNavigate,autoFocus})` `:86`. One conversation per workspace comes from `panelStore` (`:106-110`). `agentOn = agent.status?.manager.available` `:103`. `voiceEnabled` needs `flags.RAFII_VOICE_ENABLED && flags.RAFII_AGENT_V2_ENABLED` `:164`.
- **[V]** `send(raw)` `:213-299`:
  - slash `client` commands run locally (`:219-223`)
  - agent turn `:240-251` uses `idempotencyKey: newKey()`, `pageContext: currentPageContext(pathname)`, `attachments role 'reference'`, `model: choice.model`
  - `voiceSession.typedExchange(message, response.result)` `:253`
  - `result = response.siteAgent ?? {...}` `:254`
  - `panelStore.setLive(runId, {events, composing})` `:272`
  - invalidate messages `:273`
  - site-agent compose step `:276-283`
  - auto actions once per answer via the module-level `AUTO` ledger `:67,286`
  - failure copy states the change may already have happened `:291`
- **[V]** Auto-scroll `:156-158`: `end.scrollIntoView` on `[messages.length, optimistic, busy, reduced, live, notes.length]`. **Risk:** if artifact stream state is routed through `panelStore.live` or `busy`, the panel will keep scrolling to the bottom while the person reads.
- **[V]** In live mode, `mode==='live' && voiceEnabled` replaces the whole log and form with `<VoiceMode immersive …/>` (`:396`), so generated UI is not visible during a call. Voice answers re-enter through `onVoiceAnswer` → invalidate messages (`:306-315`).
- **[V]** Log container `:397`: `role='log' aria-live='polite' aria-relevant='additions'`.
- **[V]** The "More options" menu already has **"Open full conversation" → `/app/agent/{conversationId}`** (`:389`). That is the existing "expand to the full surface" path, and it keeps the same conversation.
- **[V]** `ThreadItem` `:505-569`. `agentBody = body.agent` `:515`. A running site answer shows `activityRows(liveEvents)` + Stop (`:528-550`). Completed answers render:
  ```
  554 <article className='min-w-0 flex-1' aria-label={`${siteConfig.name}'s answer`}>
  555   <SiteAgentAnswer body={body.siteAgent} actions={{ onAsk, onNavigate, messageId: message.messageId, conversationId, latest }} />
  556   {agentBody && agentBody.traceId && <AgentExtras result={agentBody} conversationId={conversationId} />}
  557 </article>
  ```
  Delegated writing-pipeline messages go through `<DelegatedMessage …/>` at `:565`.
- **[I] Insertion point, panel / tablet sheet / phone sheet / above-dialog sheet (all one code path).** Inside `<article>` `:554`: between `:555` and `:556`, or via the slot in §3.3. Surface: `'panel'` when docked or above, `'mobile'` when `!useDocked() && !useWide()`, tablet → `'panel'`. A must decide whether tablet counts as `panel` or `mobile` in `UiSurface`.

### 3.3 Native answer renderer — `features/site-agent/answer.tsx` (676 lines)
- **[V]** `SiteAgentAnswer({body, actions})` `:95-117`:
  - `:99-107` compound "Rafii is working" section (`data-rafii-execution`, `executionRows`)
  - `:108-110` `CompoundWatcher` (calls `siteAgentCompoundContinue` once when the writing run ends)
  - `:111-113` `blocks.map(...)`: `proposal_diff` is wrapped in `<section aria-label='Result for review' data-rafii-review>` with a "Ready for your review" heading. Keys are **index-based** (`${block.type}-${index}`).
  - `:114` `{body.status === 'completed' && <AnswerMeta …/>}`
- **[V]** `AnswerBlock` switch `:119-286`. `RichText` `:36-62` handles plain text with `**bold**` and lists, never HTML. `SafeLink` `:74-82` only links hrefs allowed by `route-manifest.json` (`safeHref`).
- **[V] Native approval path:** `ProposalCard` `:403-537`. Apply calls `api.siteAgentApplyProposal(w, {conversationId, messageId, proposalId, digest, expectedRevision: snapshot.revision, timeZone})` → `POST /site-agent/proposals/apply` (`:424-455`). It retries **once** on `workspace_revision_conflict` after re-reading the snapshot (`:438-441`). Dismiss → `/site-agent/proposals/dismiss` (`:457-469`). After use, focus moves to the result line (`:410-415`). `statusLine` copy is at `:472-478`. `PreparedReview` + `ReviewApproveButton` (exact digest, approve permission) `:570-594`. Copy: "Nothing changes until you apply it." `:527`.
- **[V]** `AnswerMeta` `:603-676`: follow-up chips (latest only), provenance `<details>` (Read / Did not read), helpful/not-helpful feedback → `/site-agent/feedback`.
- **[I] Recommended slot (F's bounded edit):** add an optional `generated?: ReactNode` prop and render it **between `:113` and `:114`** inside a boundary such as `<section data-rafii-generated aria-label='Interactive view'>`. Reading order then becomes: progress → native text/warnings/errors → native review cards → generated workspace → follow-ups/provenance/feedback. This keeps every native approval and receipt outside the generated subtree, and one edit serves both full chat (`:595`) and the panel (`:555`).

### 3.4 Other panel pieces
- **[V]** `features/site-agent/delegated.tsx`: `DelegatedMessage` `:112-136`. `WritingRun` `:25-110` uses `useRun` polling and "Save to drafts" → `api.applyRun(w, runId, snapshot.revision, artifactHash)` (`:40-54`).
- **[V]** `features/rafii-voice/agent-extras.tsx`: `AgentExtras({result, conversationId})` `:54-97`. Private images are fetched with `api.media` → object URL and revoked on unmount (`:15-52`). The live task checklist polls `conversationState` every 2.5 s while that task is running (`:57-67`). The trace line shows only outside production (`:94`).
- **[V]** `features/site-agent/store.ts`: module store outside React (`:38-135`). `open` persists in localStorage `rafii.panel.open`; the conversation per workspace in sessionStorage `rafii.panel.conversation.<w>`. `register(key,page)` for page context `:117-125`, `setLive(runId,…)` `:126-131`, `setBusy(w,…)`. **Note: `live` is keyed by runId, not workspace.**
- **[V]** `features/site-agent/launcher.tsx:11-31`: header button with `aria-controls={PANEL_ID}`.
- **[V]** `features/site-agent/use-page-context.ts`:
  - `useSiteAgentPageContext({selectedEntity, visibleState})` `:12-19` registers into `panelStore`
  - `currentPageContext(route,{voice})` `:30-45` adds the page outline
  - `OWN_SURFACES = '#rafii-panel, [data-guide-overlay], [data-slot="tour-overlay"]'` `:293`
  - `outlineRoots` reads dialogs plus `main` (`:296-300`)
  - **Risk:** generated UI in the full chat sits inside `main`, so its model-written labels would be read back into the next turn's `pageContext.outline`. Recommend adding `[data-rafii-generated]` to `OWN_SURFACES`. Panel content is already excluded because the panel root is `#rafii-panel`.

---

## 4. Expanded mode (does not exist)

- **[V]** No component or state for "expanded" in `site-agent/*`, `founder/agent/*` or `conversation-view.tsx` (`rg -i expand` shows only `aria-expanded`).
- **[V]** Building blocks that exist: base-ui `Sheet` (`components/ui/sheet.tsx`, `Dialog as SheetPrimitive from '@base-ui/react/dialog'`), base-ui `Drawer` (`components/ui/drawer.tsx`), `RafiiDialog*` (`components/rafii/rafii-dialog.tsx`, exported from `components/rafii/index.ts:10`), `PreviewWindow` dock/undock pattern (`components/application/post-preview/preview-window.tsx`, used at `conversation-view.tsx:778-787`).
- **[I] Recommendation for F:**
  - `generative-ui/surfaces/expanded.tsx` renders the **same** `RafiiGenerativeMessage` by `artifactId` with `surface='expanded'` inside a `RafiiDialog` (desktop/tablet, full height), opened from an Expand control in the generated message frame.
  - On phones the panel is already full-screen. Expanded should render in place (the `mobile` surface), not as a nested sheet, to avoid nested scroll traps and double Escape handling.
  - The full-chat route `/app/agent/{conversationId}?turn={messageId}` (`conversation-view.tsx:205-210`) is the existing deep link for an expanded view of the same turn.

---

## 5. Mobile sheet specifics

- **[V]** The phone frame is the full-screen base-ui Sheet (`panel.tsx:214-227`). `.rafii-mobile-chat` sizing under 1024 px follows `visualViewport` (`rafii.css:546-556`). The header uses `padding-top: max(0.75rem, env(safe-area-inset-top))` (`rafii.css:528-532`). The form uses `pb-[calc(0.75rem+env(safe-area-inset-bottom))]` (`chat.tsx:452`).
- **[V]** The log scroller is `min-h-0 flex-1 overflow-y-auto overscroll-contain` (`chat.tsx:397`). Generated content must not add another vertical scroll container. Only genuinely wide tables should scroll horizontally.
- **[V]** IME: `createImeGuard()` (`lib/ime.ts:33`) is used for Enter-to-send (`chat.tsx:319,330`; founder `chat.tsx:75,196`). Any generated `Input`/`Form` that submits on Enter must use it, because Cantonese and Mandarin IMEs commit with Enter. Safari sends keyCode 229 after `compositionend`.
- **[V]** Touch targets: `--rafii-control-min: 2.75rem` (44 px) (`rafii.css:32`). Buttons commonly use `min-h-9`, `min-h-11` or `size='icon-control'`.
- **[V]** Textareas use `text-base` (16 px), which prevents iOS zoom (`chat.tsx:471`). Generated inputs must be ≥16 px on mobile.

---

## 6. Founder agent chat — `features/founder/agent/*`

- **[V] Files:**
  - `index.ts` (re-exports)
  - `panel.tsx` (Dock/Above/Overlay mirroring the site panel; same `PANEL_ID='rafii-panel'` `:17`; `FounderChat` mounts at `:119,143,187`; mounted in `features/founder/shell/founder-shell.tsx:64-65`)
  - `chat.tsx` (346)
  - `answer.tsx` (212)
  - `store.ts` (155)
  - `voice.tsx` (270)
  - `voice-api.ts` (150)
  - `prompts.ts`
  - `launcher.tsx`
- **[V] Transport:** `lib/founder/api.ts`, `FOUNDER_API_BASE='/api/control/v2'` `:38`. Auth is the **`__Host-rafii-control` cookie with `credentials:'same-origin'` and a CSRF token from `GET /session`** on every non-GET request, plus an `Idempotency-Key` header on agent turns (header comment `:1-8`). This differs from the consumer bearer token. Calls: `agentTurn` `:240`, `agentRun` `:241`, `cancelRun` `:243`. Session context comes from `useFounderSession()` (`features/founder/shell/founder-session.tsx:15-27`: `api, mode, environment, capabilities, can(capability)`).
- **[V] Thread:** `founderPanelStore` (`store.ts:80-143`). `conversationKey(mode, environment)` = `${mode}:${env}` `:68-70`, so Demo and Live never share a thread. `threads` live in memory only (`:42`). `FounderThreadItem.response: FounderAgentTurnResponse` (`:16-29`).
- **[V]** `FounderChat` `:52-296`. `send` `:128-170` appends user and pending items, then `api.agentTurn({message, idempotencyKey, conversationId, mode, modality:'text', pageContext, timeZone})`, then `waitForRun`. "Try again" reuses the same key (`:129-140,164`). The log is at `:247`.
- **[V]** `ThreadItem` `:298-346`. Completed answer:
  ```
  341 <article className={cn('min-w-0 flex-1')} aria-label="Rafii's answer">
  342   {item.response ? <FounderAnswer response={item.response} actions={{ onAsk, onNavigate, latest }} /> : …}
  343 </article>
  ```
- **[V]** `FounderAnswer` `:185-212`, in order:
  - empty notice `:194`
  - blocks or `answerText` `:195`
  - `FounderSectionView` (Facts + `ReceiptChips` + Hypotheses + Recommendations + Unknowns + Related records) `:196`
  - warnings `:197-202`
  - errors `:203-208`
  - `Checked` (tool activity) `:209`
  - Links pass `founderSafeHref` (`features/founder/shared/safe-href.ts`). Receipts open `useEvidence().open(id)` (evidence drawer).
- **[V]** Types: `FounderAgentTurnResponse` `lib/founder/types.ts:399-408` (`result: AgentResult`, `founder?: FounderAgentSection`, `blocker?`). `FounderAgentTurnRequest` `:369-378`.
- **[I] Insertion point, founder.** A slot in `FounderAnswer` **between `:208` and `:209`** (after native warnings and errors, before `Checked`), or as a sibling after `:342`. Surface `'founder'`. Reload/resume needs a founder-scoped server read, because the thread is not persisted client-side. Founder routes must be a separate route family under `/api/control/v2/...`, never `/api/workspaces/...`.
- **[V] Reusable founder primitives for J09** (`features/founder/shared/`): `chart-card.tsx` (ChartCard with period, receipts, dataState, coverage, definition), `state-fallbacks.tsx` (StateFallback kinds incl. `unavailable`), `metric-tile.tsx`, `receipt-chip.tsx`, `evidence-drawer.tsx`, `format.ts` (`formatMetricValue`). Chart example: `features/founder/overview/trend-chart.tsx:40-70` (`connectNulls={false}`, `isAnimationActive={false}`, "left blank rather than drawn as zero").

---

## 7. Voice

- **[V]** `lib/agent-runtime/voice-session.ts` (817): one GPT-Live session per tab, held outside React.
  - `VoiceHost` `:77-90` = `{api: AgentApi, workspaceId, conversationId, locale?, voice?, timeZone?, model?, pageContext: () => SiteAgentPageContext, onConversation, onAnswer}`.
  - `onDelegation(id)` `:356-434`: waits for the transcript to settle, tries the panel-command fast lane (`matchPanelCommand`), flushes the transcript, then sends `api.turn(w, {message, idempotencyKey: 'voice:${sessionId}:${id}', conversationId: sentIn, modality:'voice', pageContext (+'voice' capability), attachments, timeZone, locale, model, traceId, delegationId, voiceSessionId})` `:400-405`, then `current.onAnswer(response)` `:413`.
  - **Speech source:** `const spoken = result?.speakableSummary?.trim() || (errors ? 'That didn't fully work. The details are in the panel.' : 'I've put the answer in the panel.')` **`:418`**, then `say(spoken)` `:423`.
  - Failure copy distinguishes "refused" (4xx list) from "couldn't confirm" `:431-432`.
  - `typedExchange(question, answer)` `:780-783` feeds `answer.speakableSummary || answer.answerText` to GPT-Live quietly. It is called from `chat.tsx:253`.
  - `startProgress` `:437-494` polls `activeRun`, `runEvents` and `conversationState`.
- **[V]** `lib/agent-runtime/live-transport.ts`: `WebRtcLiveTransport` (`:55-211`) and the dev-only `FakeLiveTransport` (`window.RAFII_FAKE_LIVE`, `rafiiLiveHarness`, `:254-372`). `createTransport()` `:374-377` returns the fake only when `NODE_ENV!=='production'`.
- **[V]** `lib/agent-runtime/voice-transcript.ts`: pure functions (`applyTranscript`, `takeRequest`, `hangUpDue`, `UTTERANCE_GAP_MS=1200`, `MAX_LINES=60`), tested in `tests/voice-transcript.test.cjs`.
- **[V]** `lib/agent-runtime/panel-actions.ts` `:8-45`: a registry of `navigate`, `startGuide`, `stopGuide`, `setStyle`, `openStyle`, `startVoice`, `newConversation`. `registerPanelActions` returns an unregister function. Nothing here executes business writes.
- **[V] Founder voice** reuses `voiceSession` with an `AgentApi`-shaped adapter, `createFounderVoiceApi` (`voice-api.ts:117-`). `withSpokenSummary` `:111-115` substitutes the delegation's server `speakable` when `speakableSummary` is empty. Answers are appended to the founder thread (`voice.tsx:126-134`).
- **[V] Phone mode** (`features/rafii-phone/call-rafii.tsx`, mounted at `chat.tsx:394`) is separate. Its browser regression tests are `tests/phone-mode-browser.cjs` and `phone-*-browser.cjs`.
- **[I] F voice integration:**
  - (a) No change is needed to speech sourcing, provided B guarantees `speakableSummary` never contains DSL, IDs or chart data.
  - (b) Selection continuity: add `uiContext?: () => {...} | null` to `VoiceHost` next to `pageContext` and send it in the `:400-405` body (requires D5). `pageContext.selectedEntity` cannot carry it (see §0.7).
  - (c) Generated UI never calls `say()` or `think()`.

---

## 8. Composer, model choice and credits UI

- **[V]** `features/agent/composer.tsx`: `Composer` forwardRef `:100`; `ComposerProps` `:48-99`; `MESSAGE_MAX=6000` `:28`; `DRAFT_PLATFORMS` `:32`. Used only by full chat and home. The panel and founder have their own plain `<textarea>` composers (`chat.tsx:456-472` with `maxLength=4000`; founder `:276-288`).
- **[V]** `features/agent/use-model.ts`: `useModelChoice(catalog, workspaceDefault)` `:131`; `requestFieldsFor` `:91-104` (omits `model` on Auto); `AUTO_MODEL='auto'`; `ROUTE_LABELS` for the CLI routes; `FIXTURE_MODEL='deterministic-preview'` `:15`. The panel always sends a concrete `choice.model` (`chat.tsx:94-97,249`).
- **[V] Credits:**
  - `features/agent/credit-turn.ts`: `submitConversationTurn` `:50-66`. With a limit it gets a snapshot, then `creditQuote({operation:'turn', conversationId, request, expectedRevision, maxMilliCredits})`, then sends the turn with `creditQuoteId`.
  - `withResend` `:18-29` resends **the same idempotency key** after a lost response (502/503/504 without a code, TypeError, Timeout, Abort), at most twice, and is never re-approved. This is the existing "no hidden spend" pattern.
  - `useCreditEstimate` (`use-credit-estimate.ts:24`); `CreditLimitField` (`credit-limit-field.tsx:24`); `parseCreditLimit`; `createSubmissionGate` (`submission-gate.ts:2`) prevents a double submit.
  - Credit mode = `usage.data.credits && choice.option.costClass==='paid'` (`conversation-view.tsx:246`).
- **[I]** An explicit UI-only retry or semantic edit (C06, `POST /presentations/{id}/edits`) is a new metered call. It should reuse this quote/limit pattern, and the gate + `withResend` same-key semantics, rather than inventing a new spend UI.

---

## 9. Native layers that must stay outside the generated subtree

| Native element | File:line | Authority it calls |
|---|---|---|
| Site-agent `ProposalCard` (Apply/Dismiss) | `site-agent/answer.tsx:403-537` | `POST /site-agent/proposals/apply` / `dismiss` with `digest` + `expectedRevision` |
| `PreparedReview` + `ReviewApproveButton` | `answer.tsx:570-594`; `components/jobs/review-approve-button.tsx:36` | workspace action `p2_approve` with `{reviewId, digest, confirmed}` |
| `CompoundWatcher` | `answer.tsx:544-567` | `POST /site-agent/compound/continue` (idempotent) |
| warning / error / diagnostic blocks | `answer.tsx:123-136,182-216` | display only |
| `AnswerMeta` provenance + feedback | `answer.tsx:603-676` | `POST /site-agent/feedback` |
| Memory `ProposalCard` | `features/memory/proposal-card.tsx:51` | `api.decideProposal(... expectedRevision)` |
| `ChatAutomationCard` | `features/automations/chat-automation-card.tsx:55` | existing automation decision path |
| `PlanCard` | `features/agent/plan-card.tsx:230` | `api.applyRun(w, runId, revision, artifactHash)` |
| `WritingRun` "Save to drafts" | `site-agent/delegated.tsx:40-54` | `api.applyRun` |
| Run Cancel | `conversation-view.tsx:651`; panel Stop `chat.tsx:415,474` | `/ideas/runs/{id}/cancel`, `/site-agent/runs/{id}/cancel` |
| Founder receipts / evidence | `founder/agent/answer.tsx:27-46,68` | evidence drawer (read) |

---

## 10. Component primitives available to C (reuse, do not import a competing theme)

- **[V] Stack:**
  - `next 16.3.8`, `react 19.2.4`, `typescript 5.7.2`, `zod ^4.3.6`
  - `@base-ui/react ^1.6.0` (shadcn style `base-nova`, `components.json`)
  - `@tanstack/react-table ^8.21.3`, `@tanstack/react-form ^1.28.5`, `@tanstack/react-query ^5.95.2`
  - `recharts 3.8.0`, `motion ^11.18.2`, `@tabler/icons-react`, `sonner`, `zustand`, `nuqs`
  - `vaul ^1.1.2` (**unused**)
  - Node engines `24.x`; `.node-version` `24.15.0`
- **[V] `components/ui/*`** (base-ui wrappers): accordion, alert, badge, button (variants incl. `glass`, `quiet`, `action`; sizes incl. `icon-control`, `control`, `xs`), card, chart, checkbox, combobox, dialog, drawer (base-ui Drawer), empty, field, input, input-group, label, native-select, popover, progress, radio-group, scroll-area, select, separator, sheet (base-ui Dialog), skeleton, slider, spinner, switch, table, tabs, textarea, toggle(-group), tooltip, `streaming-text.tsx` (`StreamingText({text})`, words keyed by position), `message-scroller.tsx`, `table/data-table*.tsx`.
- **[V] Charts:** `components/ui/chart.tsx`, the shadcn recharts wrapper. `ChartConfig` `:15`, `ChartContainer` `:42`, `ChartTooltip`/`ChartTooltipContent` `:109-111`, `ChartLegend`/`ChartLegendContent` `:250-252`. Used by `features/analytics/post-readings.tsx` and founder charts. **No accessible data-table alternative is built into the wrapper.** C must add one for ToolBoundChart.
- **[V] Tables:** `components/ui/table/data-table.tsx:21` `DataTable<TData>({table, actionBar, children})`, which takes a TanStack `table` instance. `hooks/use-data-table.ts` (useReactTable + nuqs URL state; **URL-state coupling is unsuitable inside chat messages**). Toolbar, faceted, date and slider filters live in `components/ui/table/`. Real usage: `features/analytics/posts-table.tsx`.
- **[V] Rafii components** (`components/rafii/index.ts`):
  - `Surface({material:'glass'|'selected'|'elevated'|'quiet'|'composer'|'paper'|'canvas', radius, padding})` (`surface.tsx:44`)
  - `StateMessage({kind, title, description, action, media, layout})` (`state-message.tsx:38`), with `StateKind = 'empty'|'loading'|'error'|'permission'|'offline'|'stale'|'partial'|'unsupported'|'success'` `:6`. It uses `role=alert` for error/permission and `status` otherwise.
  - `SegmentedControl` (tabs pattern with panelIds), `FilterPanel`/`FilterSelect`, `Workbar`/`ActiveFilters`, `RafiiDialog*`, `InfoTip`, `CollectionRow`.
- **[I]** `DataState` → `StateKind` mapping: loading→loading, empty→empty, partial→partial, stale→stale, denied→permission, unavailable→unsupported (or offline when the cause is the network). Always keep "unknown ≠ zero".
- **[V] Agent components:** `components/agents/message.tsx` (`Message`, `MessageAvatar`, `MessageContent`, `MessageTyping` …), `loading-states/agent-progress.tsx`, `thinking-shimmer.tsx`, `thinking/rafii-thinking-status.tsx` (+ `thinkingOrbsEnabled()` = `NEXT_PUBLIC_RAFII_THINKING_ORBS !== '0'`, `lib/agent-runtime/thinking-state.ts:32-34`).
- **[V] Assets:** `features/library/asset-thumbnail.tsx:162` `AssetFileThumbnail({asset, size:'gallery'|'row'|'detail', loadPreview})` uses `api.libraryFileUrl`. Private image bytes come from `agentApi.media(w, assetId)` → object URL (`agent-extras.tsx:15-52`); video uses `api.mediaUrl` (`conversation-view.tsx:341-347`). Only asset IDs should reach the model or DSL. Components resolve URLs at render time.
- **[V] Lazy loading convention:** `next/dynamic` in `features/rafii-guide/guide-mount.tsx:3`, `features/agent/home-view.tsx:4`, `features/onboarding/tour-mount.tsx:9`.
- **[V]** `useLiveRegion()` (`features/agent/attachments/attachment-bar.tsx:32-40`): clear then set after 30 ms so the same text is announced again. A small deduped announcer pattern to reuse.

---

## 11. Theme tokens

- **[V]** CSS entry: `src/styles/globals.css` (`@import 'tailwindcss' source(none); @source '../';`, then `theme.css`, `transitions.css`, `tour.css`, `rafii.css`, `growth.css`). Tailwind v4, no tailwind.config. `components.json` points at a stale `app/globals.css`.
- **[V]** `DEFAULT_THEME='rafii'` (`components/themes/theme.config.ts:5`), on `<html data-theme>` (`app/layout.tsx:55`); dark mode via the `.dark` class.
- **[V]** `rafii.css`:
  - `[data-theme='rafii']` tokens `:48-131`: radii `--rafii-radius-control|card|composer|dialog`, `--rafii-control-min`, blur, motion timings `--rafii-time-*` and eases, the `--rafii-surface-*` glass recipes, shadcn mapping (`--background`, `--card`, `--primary`, `--muted-foreground`, `--destructive`, `--border`, `--ring`), `--chart-1..5` monochrome (light `:95-99`, dark `:186-190`), `@theme inline` color exports `:210-235`.
  - Utilities `:266-368`: `rafii-glass`, `rafii-glass-selected`, `rafii-lens`, `rafii-elevated`, `rafii-composer`, `rafii-quiet`, `rafii-field`, `rafii-panel`, `rafii-action`, `rafii-scrim`, `rafii-serif`, `rafii-eyebrow`, `rafii-focus`, `rafii-paper`.
  - `data-effects='reduced'` solid fallbacks `:391-398`.
  - Panel palette `.rafii-chat, .rafii-mobile-chat` `:506-524` forces a dark violet scheme with `color-scheme: dark`.
- **[V] Container queries** are the layout convention inside the panel (`SiteAgentChat` root has `@container`, `chat.tsx:360`; `ProposalCard` uses `@[28rem]:flex-row`, `answer.tsx:496`; full chat uses `@container/conversation`). **[I]** Generated layouts should key off container width, not viewport width, because one artifact renders in a 29 rem panel and a wide chat.

---

## 12. i18n and locales

- **[V] There is no UI i18n framework** (no next-intl or i18next). UI chrome strings are English literals and `<html lang='en'>` (`app/layout.tsx:55`). `@react-aria/i18n` is used only by the calendar (`components/application/calendar/calendar.tsx:19,70`).
- **[V] Person locale and time zone:** `lib/preferences.tsx` `Preferences {timeZone, locale, …}` from `GET /api/me` preferences or the browser. `PreferencesProvider` calls `setTimeDefaults` before render and re-keys the subtree on change. `lib/time.ts` `setTimeDefaults` `:21-28`, `relativeTime` `:35`, `formatDate` `:46`, `formatDateTime` `:51` all use the person's locale and zone. `useTimeZone()` `preferences.tsx:77`. Generated dates and numbers must format through these helpers or `Intl` with `timeDefaults()`.
- **[V] Content-language catalogue** (post languages, not UI): `lib/locales/index.ts`. Tags such as `zh-Hant-HK`, `zh-Hant-TW`, `zh-Hans-CN`, `yue-Hant-HK`, with `dir:'ltr'|'rtl'` and `glyphs` (`core.ts:13-30`). `textAttributes(value)` returns `{lang, dir:'auto', style:{fontFamily}}` (`index.ts:41-48`), the existing way to render text written in a given language with correct glyphs and RTL. `catalogue.generated.json` mirrors `src/postriff_phase2/locales.py`. `core.test.mjs` runs in CI.
- **[V] Agent style language** (how Rafii talks): `'auto'|'en'|'yue'|'cmn'` with labels `廣東話`/`普通话` (`lib/agent-runtime/style.ts:10,47`). Answers carry `language` (`SiteAgentBody.language`, `AgentResult.language`).
- **[I]** For "English, Traditional Chinese/Cantonese, Simplified Chinese" coverage, generated components should:
  - apply `textAttributes(answer.language)` to model text
  - format numbers and dates with the person's locale
  - keep native chrome strings consistent with the app (English)
  - The spec's locale gate means CJK and long text don't break layout, plus correct `lang`/`dir`. It does not mean translated chrome, which the app doesn't have.

---

## 13. Reduced motion

- **[V]** `lib/rafii/motion.ts`: one effective preference that combines the OS media query with the app setting `rafii.motion` (`system|reduced|full`). `motionAllowed()` `:58-64`, `applyMotionAttribute()` sets `<html data-motion='reduced'>` `:78-83`, `useMotionPreference()` `:104` returns `{reduced, …}` and is used by `chat.tsx:100` and founder `chat.tsx:55`.
- **[V]** `motion/react` `useReducedMotion()` is used in about 63 TSX files (e.g. `conversation-view.tsx:21,133,149`).
- **[V]** CSS:
  - `.rafii-decorative-motion` / `.rafii-spatial-motion` are disabled under the media query and under `[data-motion='reduced']` (`rafii.css:401-416`)
  - panel-wide `scroll-behavior:auto; animation/transition 0.01ms` under reduce (`rafii.css:557-563`)
  - `motion-reduce:animate-none` / `motion-reduce:transition-none` Tailwind variants are common (`answer.tsx:563,634`)
  - shimmer and marquee are off (`globals.css:647,692`)
  - `transitions.css:596`
- **[I]** C should use `useMotionPreference()` so the app setting is respected, not only the OS query. Mark any entry animation `rafii-spatial-motion` and use no decorative loops.

---

## 14. Web test conventions and CI

- **[V] No test runner dependency** (no vitest/jest/tsx/esbuild/jsdom). Unit tests are `node --test` CommonJS/ESM files that load TS/TSX with **`typescript.transpileModule`** and a custom `require` that maps `@/` → `src/` and resolves packages from `web/node_modules` (canonical loader `tests/rafii-commands.test.cjs:24-40`; also `picker-search`, `attachments-state`, `used-this-time`, `voice-session-lifecycle`). React output is tested with **`react-dom/server` `renderToStaticMarkup`** (`rafii-commands.test.cjs:259-263`, `visual-analysis.test.cjs:17,135`). There is **no DOM environment**, so focus, typing and interaction tests must be Playwright browser scripts.
- **[V] Browser tests:** `tests/*-browser.cjs` drive Playwright (`playwright 1.62.1` devDependency) against the local harness only. For example, `tests/agent-runtime-browser.cjs:16-24` uses `RAFII_WEB_URL` (default `http://localhost:3290`), refuses non-local hosts, and authenticates with `Authorization: Bearer dev:<uuid>` + `X-PostRiff-Request: founder-alpha`. In this harness the Manager is a deterministic stand-in (`RAFII_AGENT_HARNESS=1`) and GPT-Live is `FakeLiveTransport`, so **this is not real-model evidence**.
- **[V] CI:**
  - `.github/workflows/consumer-ready.yml` (pull_request + workflow_dispatch): `:55` `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` (new `web/tests/agent-ui-*.test.cjs` files are picked up by the glob automatically); `:59-62` typecheck → lint → isolated `npm run build`; `:64` copy audit `--check`; then real local browser/API/DB integration.
  - `.github/workflows/rafii-browser.yml` runs the Rafii browser suites (site-agent, live-agent, chat-concepts, phone, guide) on chromium + webkit against `postriff_dev_hosted.py` on :4438 and `next start` on :4439 (`:62-64`). New `web/tests/agent-ui-e2e/*` or `agent-ui-*-browser.cjs` must be added there by A.
- **[V] JCB mapping** (`.james-cloud-build.json`, tracked): `lint→lint`, `typecheck→typecheck`, `build→build`, but **`test→test:library` and `ci→ci:library`** (library cloud validation, not the web unit tests). The cloud route for web node tests is the `consumer-ready.yml` workflow_dispatch, unless A adds a JCB task.

---

## 15. Build, type and lint configuration

- **[V]** `tsconfig.json`: target ES2017, `moduleResolution: bundler`, `jsx: react-jsx`, `strict`, `paths {"@/*": ["./src/*"]}`, includes several alternate `.next*` type dirs.
- **[V]** `next.config.ts`:
  - `transpilePackages: ['geist']`, no `experimental` block
  - `compiler.removeConsole` in production
  - API rewrites only in dev or with `POSTRIFF_API_ORIGIN` (`/api/:path*` → Python, default `127.0.0.1:4331`)
  - founder redirects
  - Sentry wrapper unless `NEXT_PUBLIC_SENTRY_DISABLED`
  - `assertPreviewEnvironment` (`src/lib/deployment-env.mjs`)
  - **[I]** A may need to add `@openuidev/*` to `transpilePackages` if the pinned packages ship untranspiled syntax. C's probe must check this.
- **[V]** `.oxlintrc.json`: plugins `eslint, typescript, unicorn, oxc, react, nextjs, import, jsx-a11y`; `correctness: error`; `react-hooks/rules-of-hooks: error`; `exhaustive-deps: warn`; `no-console: warn` (warn/error allowed); `jsx-a11y/no-autofocus: error`; `ignorePatterns` includes `scripts/**`.
- **[V]** `.npmrc`: **`legacy-peer-deps=true`**, so npm will not report peer conflicts (React 19.2 / zod 4) for new packages. C must read `peerDependencies` manually.
- **[V] Copy audit** (`scripts/copy-audit.mjs`, CI `--check`): fails on string literals or JSX text (strings with a space or a leading capital) containing `deployment|backend|database|payload|schema|staging` anywhere in `src/features`, `src/components` (except `components/ui`), `src/lib`, `src/app/app`, `src/hooks`, `src/config`. It also fails on any readable "PostRiff"/"Raffi"/"Rafi"/"RAFII" spelling. Exemptions: `copy-audit: allow` on the line, `.test.` files, `/dev/` paths. This hits parser error messages and fallback copy in `generative-ui/**` and `lib/agent-runtime/ui-parser/**`.
- **[V] Observability:** Sentry with `scrubTelemetry` (`lib/telemetry.ts`) strips messages and request content. It is the existing client error channel. Don't log DSL or private values.

---

## 16. Flags and kill switch mechanism

- **[V]** Server flags: `src/postriff_phase2/agent_runtime_v2/config.py:21` `FLAGS = ("RAFII_AGENT_V2_ENABLED", "RAFII_VOICE_ENABLED", "RAFII_IMAGE_AGENT_ENABLED", "RAFII_SPECIALISTS_ENABLED", "RAFII_PROACTIVE_V2_ENABLED", "RAFII_AGENT_THINKING_STATES_ENABLED")`. Status payload `config.py:186`; `service.py:83-86`. The web reads them through `useAgent().status.flags` (e.g. `chat.tsx:164`).
- **[V]** Client build flags use the `NEXT_PUBLIC_*` pattern (`NEXT_PUBLIC_RAFII_THINKING_ORBS`). A build flag can't act as an instant kill switch.
- **[I]** Kill switch = new server flags in `config.FLAGS` (A-owned), surfaced in `/agent/status`, read by the web to decide whether to mount, and enforced by every UI route server-side.

---

## 17. Insertion-point summary

| Surface | Mount file:line | Native layers that stay outside | Data source for artifact ref | Notes |
|---|---|---|---|---|
| Full chat | `features/agent/conversation-view.tsx:595` (after `SiteAgentAnswer`, before `:597`), or the `SiteAgentAnswer` slot | `SiteAgentAnswer` (compound, blocks incl. proposal_diff, AnswerMeta) | `message.body.agent.<uiRef>` from `messageWindow` | needs an agent-runtime `onContinue` sender; add `[data-rafii-generated]` to the outline skip |
| Panel (dock ≥1024) | `features/site-agent/chat.tsx:555-556` inside `<article>` `:554`, or the slot | same + `AgentExtras` | `message.body.agent.<uiRef>` from `useMessages` | the log is `aria-live`; don't feed the auto-scroll deps |
| Above-dialog sheet | same component (`panel.tsx:176`) | same | same | add generated popovers to the Escape skip (`panel.tsx:79`) |
| Tablet sheet (768–1023) | same component (`panel.tsx:225`, `sm:max-w-[36rem]`) | same | same | surface mapping decision |
| Phone sheet (<768) | same component (`panel.tsx:222-225`, full-screen) | same | same | `visualViewport` vars; IME guard; 16 px inputs; no nested scroll |
| Expanded | **new** `generative-ui/surfaces/expanded.tsx` (RafiiDialog) | n/a | artifactId | same conversation; on phone render in place |
| Founder panel | `features/founder/agent/answer.tsx` between `:208` and `:209`, or a sibling after `chat.tsx:342` | blocks/answerText, FounderSectionView + receipts, warnings, errors, Checked | `item.response.result.<uiRef>` (in-memory) | separate `/api/control/v2` route family; cookie + CSRF; reload needs a server read |
| Browser voice | no visual mount; `voice-session.ts:400-405` (request), `:418` (speech) | `speakableSummary` only | n/a | add `uiContext` to `VoiceHost` |

---

## 18. Risks and gaps (consolidated)

1. **[V]** No streaming client, and WSGI full-body responses. Real chunked delivery needs B's WSGI iterator or flush proof on Vercel Python, plus a new fetch-stream reader with fragmented UTF-8 handling.
2. **[V]** `/api/*` goes entirely to Python on Vercel. A Node parser route needs a non-`/api` path or a vercel.json exception before the catch-all.
3. **[V]** Backend `page_context` drops UI selections, so a dedicated turn field is required.
4. **[V]** The panel's `aria-live` log would announce streamed nodes. Use `aria-busy` on the generated root while streaming, plus one deduped status announcer.
5. **[V]** Panel auto-scroll deps (`chat.tsx:156-158`): artifact state must stay out of `panelStore.live`/`busy`/`messages.length`.
6. **[V]** Chart tokens are near-black on the dark panel palette. Scoped `--chart-*` overrides are needed under `.rafii-chat`.
7. **[V]** The page outline reads `main` in full chat, so generated text could feed back into context. Add `[data-rafii-generated]` to `OWN_SURFACES` (`use-page-context.ts:293`).
8. **[V]** The founder thread is in memory, so reload/replay has no client source. A founder artifact read route is required.
9. **[V]** Full chat has no `onAsk` for agent answers and doesn't render `AgentExtras`. Continuation from full chat needs new wiring.
10. **[V]** No expanded mode exists. F builds it.
11. **[V]** `vaul` is unused. The mobile sheet is base-ui. Don't introduce vaul.
12. **[V]** No UI i18n framework. Don't promise translated chrome. Use `textAttributes` + `Intl`.
13. **[V]** The copy audit fails on banned words in new UI code strings.
14. **[V]** `legacy-peer-deps=true` hides peer mismatches. The tests' `require()` loader may fail on ESM-only or top-level-await packages (Node 24 `require(esm)` handles sync ESM only). C's probe must cover both.
15. **[V]** The test harness Manager is deterministic and GPT-Live is fake, so harness runs don't prove real-model behavior.
16. **[V]** `jcb test` doesn't run web unit tests. Use the `consumer-ready.yml` dispatch or add a JCB task.
17. **[V]** Site-agent block keys are index-based. Generated statements must use stable IDs, never array indexes.
18. **[V]** `panelStore.live` is keyed by runId, not workspace. Artifact caches must key by `(workspaceId|founderScope, principal, artifactId)` and clear on workspace switch. The query cache is cleared on logout (`lib/auth/session-query-boundary.tsx:13`). The conversation view remounts per workspace.
19. **[V]** The existing `ProposalCard` auto-retries once on `workspace_revision_conflict`. That is native and acceptable, but generated actions must not copy it for business writes without idempotency reconciliation.
20. **[V]** Consumer routes need `Authorization: Bearer` + `X-PostRiff-Request: founder-alpha`. Founder routes need the cookie + CSRF + `Idempotency-Key`. A single generic stream client must take a pluggable fetch/auth adapter.

---

## 19. Decisions A must freeze (with recommendation)

- **D1 Artifact reference location.** Add `uiArtifacts?: Array<{artifactId, slot, revision, generationState, surfaceHints?}>` to `AgentResult`, persisted in `body.agent` by `_persist` (`service.py:879-884`) and returned in `AgentTurnResponse.result`. Leave `body.siteAgent` unchanged. Legacy messages without it render native only.
- **D2 Mount placement.** Add `generated?: ReactNode` slots to `SiteAgentAnswer` (between `answer.tsx:113` and `:114`) and `FounderAnswer` (between `:208` and `:209`), owned as F's bounded edits. Callers pass `<RafiiGenerativeMessage surface=…/>`.
- **D3 Surface enum mapping.** dock and above → `panel`; tablet sheet → `panel`; phone overlay → `mobile`; full chat → `chat`; dialog → `expanded`; founder → `founder`; voice → `browser_voice` (no visual mount).
- **D4 Parser seam route.** Next route handler at a non-`/api` path (e.g. `src/app/internal/agent-ui/validate/route.ts`, `runtime='nodejs'`), served by the existing `/(.*)` → postriff_web rewrite with no vercel.json change. Server-to-server HMAC with a new secret env var. Reject browser origins and oversized bodies before parsing. The alternative is an explicit vercel.json rewrite placed before `/api/(.*)`.
- **D5 Selection/continuation context.** New optional `uiContext: {artifactId, artifactRevision, stateRevision}` on `AgentTurnRequest` (text, panel, voice via `VoiceHost.uiContext()`). The server re-resolves the selection from persisted UI state. Do not use `pageContext.selectedEntity`.
- **D6 Stream client.** `fetch` + `ReadableStream` SSE parser with an injected auth adapter (consumer bearer + guard header; founder cookie + CSRF), `AbortController` per scope, polling `GET …/events?after=` as reconnect and fallback. No `EventSource`, no credentials in URLs.
- **D7 Kill switch.** Add `RAFII_GENUI_ENABLED` (+ `RAFII_GENUI_ACTIONS_ENABLED` for writes) to `config.FLAGS`, expose it via `/agent/status`, gate the client mount and enforce on every UI route.
- **D8 Expanded implementation.** `RafiiDialog` full-height rendering the same artifact by ID on desktop/tablet. In place on phone. Never a new conversation.
- **D9 Founder persistence.** Founder UI route family `/api/control/v2/agent/ui/*` with snapshot/events reads keyed by `messageId`/`artifactId`. The client restores the thread from server conversation state, because the in-memory thread is not durable.
- **D10 Test strategy.** Keep `node --test` + `transpileModule` + `renderToStaticMarkup` for parser, contract and SSR tests (auto-globbed by `consumer-ready.yml`). Add Playwright `agent-ui-*-browser.cjs` to `rafii-browser.yml` for focus, typing, reduced motion and mobile. Don't add jsdom unless A approves a devDependency.
- **D11 Panel chart tokens.** Scope `--chart-1..5` overrides under the generative-UI root inside `.rafii-chat` in a C-owned CSS module or root class, instead of editing global `rafii.css`. If global, A edits it.
- **D12 Outline exclusion.** A or F adds `[data-rafii-generated]` to `OWN_SURFACES` (`use-page-context.ts:293`), with a regression test in `tests/page-outline.test.cjs`.
- **D13 Full-chat continuation.** `conversation-view.tsx` gets an `askAgent(text, uiContext)` modeled on the slash agent path (`:400-419`) and passes it as `onAsk`/`onContinue` to both `SiteAgentAnswer` and `RafiiGenerativeMessage`.
- **D14 Lazy bundle.** Renderer and library loaded with `next/dynamic(() => import('@/features/agent/generative-ui/renderer'), { ssr: false })` so legacy answers don't pay the bundle cost.
