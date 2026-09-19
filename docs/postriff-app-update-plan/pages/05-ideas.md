# 05 · Ideas

> Route：`/app/ideas` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

而家嘅 Ideas 頁係一個「細份」嘅 Home + Conversation 複製品，加一個 Sources panel。

**Route / view**
- `web/src/app/app/ideas/page.tsx:1-13`：`<Suspense>` 包 `IdeasView`，metadata title 'Ideas'；**冇 route-level access gating**（冇用 `PageContainer` 嘅 `access` prop，`web/src/components/layout/page-container.tsx:27-48`），nav 隱藏只係 UX（`web/src/hooks/use-nav.ts:23`）。
- `web/src/features/ideas/ideas-view.tsx`（517 行）：`PLATFORMS` 硬寫（:41）；hooks `useSnapshot / useConversations / useModels / useMessages`（:78-82）；`?new=1` 清空 thread（:98-104）；grid `lg:[14rem_1fr] xl:[14rem_1fr_24rem]`（:216）：左 Conversations（:218-264，`SharedLayoutBg` :244）、中 thread + composer + run log、`SourcesPanel` 喺 `lg:col-start-2`（:440-441）、右 Candidates（:444-513）。
- `quickStart()`（:150-164）/ `sendTurn()`（:166-176）/ `apply()`（:178-185）都冇傳 `timeZone`（Home 有：`web/src/features/agent/home-view.tsx:127,183`）。
- **真 bug**：async route（Claude Code / Codex）回 `status:'running'`，Ideas 只喺 `lastRunId` 變時 fetch 一次（:106-115），冇 polling；`web/src/features/agent/use-run.ts:33` 每 1.2s poll 嘅邏輯冇用。Candidates 亦冇 `VariantCard` / `DraftPreview` / `PlanCard` / `ActivityStrip`（Conversation 頁 `conversation-view.tsx:290-341` 用緊）。
- Header badge（:197-202）顯示 local state 嘅 `qualified.label`（:89,:136），唔係 `useModelChoice`（`use-model.ts:28`），同 Home model pill 可以唔一致。

**Sources panel**（`web/src/features/ideas/sources-panel.tsx`）
- 只列 active sources（:30）；每行 title、kind、approved facts 真數、policy `Select`（POLICIES :14-19）、cloud `Switch`（:95-101）；`useAct` 送 `source_policy`（:33-42）。Row stagger（:60-65）總長 440ms，超 motion §5.4。
- 冇 source 時 `return null`（:44），新用戶見唔到 Sources 概念。
- `grep -rn "source_use_approve\|retract_source\|approve_source" web/src` 零結果：冇 UI 可以逐條 approve fact、批 public use、撤回、睇 web research provenance。`text/document/link` 預設 `rewrite_approval`（`src/postriff_phase2/source_policy.py:17`），Queue blocker `source_use_approval_required`（`source_policy.py:158`）前台清唔走。

**Backend（已存在）**
- `src/postriff_phase2/hosted_app.py:231-273` `_ideas`：quick-start、conversations GET/POST、turns、messages、attachments、runs events（JSON / SSE replay）、cancel、apply；`GET /api/ideas/models`（:303）。
- `src/postriff_phase2/ideas.py`：`IdeasService`（:79-98）；`memory_files`（:122-127，回 `research: consent_summary`）；`conversations`（:187-190）；`create_conversation`（:192-198）；`attach`（:208-227，寫 `pr_attachments`，turn 從不讀——inert）；`_research`（:279-334，`message = text or intentText` :286，web 頁變 source + origin/unknowns :318-319）；`turn`（:336-438，`sourceIds` :358）；`apply`（:487-527）；`quick_start`（:530-563，turn 用 `text:''` + `intentText` :562）。
- `src/postriff_phase2/research.py`：`allowed`（:89-91）、`consent_summary`（:94-98）、`needs_research`（:128-141）、`Researcher.run`（:291-327，有 URL 先讀 URL，否則 Exa search；最多 2 頁、30 秒；失敗只 warning）。
- Source actions（`POST /api/workspaces/{w}/actions`，client `act` `web/src/lib/api/client.ts:137-138`）：`source`（`src/postriff_alpha/domain.py:259-288`，kinds idea/text/link/document/sample；text/document 按換行分 facts :278，idea/link 冇 facts :279-280；fingerprint 重複 raise **400**（AlphaError 預設，:276 / :35）；document 只收 .txt/.md ≤ 20 KB；link 唔 fetch）、`approve_source`（:289-300，factIds 取代成套）、`retract_source`（:302-313，source title 變 'Withdrawn source'、清 text/facts、引用 variants `blockedByRetraction`）、`source_policy` / `source_use_approve`（`source_policy.py:109-142`；digest 唔啱回 409 :135-136）。權限：`permissions.py:27-39` 冇列 → 全部 `edit`（:69-72）。
- **副作用**：上述每個 action 都 `brief.revision += 1`（domain.py:285,298,313；source_policy.py:128,141），source / approve / retract 仲 `_mark_stale`（domain.py:183-187）將**全 workspace** variants 設 `needsReview`。`store.py:278`（variant_review）同 `:354`（schedule）要求 `v.briefRevision == brief.revision` → 喺 Ideas 儲一條 source 會令所有未排程 draft 要 regenerate。
- Snapshot presenter 係 deep copy（`domain.py:130-134`；`hosted.py:182-183` `HostedPhase2Commands.present`、`:504-507` `_present`），`hosted.py:221` 每個 command 後 `stamp()`；所以 `origin / useApprovals / createdAt / unknowns / withdrawnAt / fingerprint` 已到瀏覽器，只係 `web/src/lib/api/types.ts:131-142` `SnapshotSource` 冇 declare。`use_approved` 要對 `facts_digest`（`source_policy.py:53-59`），client 計唔到。
- Data request retraction（`hosted.py:458-462`）嘅 `dependentVariantsBlocked` 係全 workspace 計數，唔可以當單一 source 數字。

**Onboarding infra（已存在，未 commit）**
- `web/src/features/onboarding/`：`tours.ts`（`PAGE_TOURS` :156、`pageTourFor` :345、`TourCtx` :14-24）、`tour-overlay.tsx`、`tour-mount.tsx`（喺 `web/src/app/app/template.tsx` mount，一次性 toast nudge）、`store.ts`（localStorage `postriff-onboarding` :40）、`help-menu.tsx`（header Help）。Ideas 未有 page tour，亦冇 `data-tour` anchor。

**Nav / 入口**
- `web/src/config/nav-config.ts:28-35`：Create group，icon `sparkles`（同 Home 撞），shortcut `i i`，`access: {permission:'edit'}`。
- 三個入口：Home「Sources · N usable」（`home-view.tsx:269-271`）、「Sources & older drafts」（:372）、header「Create」→ `/app/ideas?new=1`（`web/src/components/layout/header.tsx:35-38`）。
- Access：`web/src/lib/workspace/provider.tsx:147-148` 由 membership `permissionsFor`（`web/src/lib/auth/permissions.ts`）派生。
- Docs 立場：`docs/postriff-consumer-saas-redesign.md` §6.5（:340-344）Ideas = Studio；`docs/postriff-agent-chat-design.md` §8.6（:481-487）話併入 Home，§11a（:557）記錄「Ideas 頁保留，未併入」。身份未定係頁面未 set up 好嘅根源。
- Languages：`intent.LANGUAGES` 只有 English / 繁體中文（`src/postriff_phase2/intent.py:14`）；`docs/postriff-worldwide-languages-plan.md` §7 已列 Ideas 嘅 language toggle 要改 per-channel chips（Stage 2 未開始）。

## 1. Design specification（最新版）

**目的**：Ideas 係 workspace 嘅「原材料庫」：捕捉諗法、貼文字、放 link、上 .txt/.md，然後逐條 source 決定「邊啲 fact 可以用、點樣用、可唔可以出 cloud、可唔可以公開引用」，再由任何一條 source 一撳開始 draft（交畀 /app/agent/[id] 嘅 conversation 去寫、preview、排程）。唔再複製 Home 嘅 chat thread 同 candidates——Home 係「即刻寫」，Ideas 係「先儲起、先審好、遲啲寫」（對標 Buffer Ideas capture → later post，Typefully messy notes → drafts）。每個數字、badge、provenance 都由 snapshot / API 真值嚟；任何會令其他 draft 要重寫嘅動作都先用真數提醒，唔阻止。

**Layout**：PageContainer：pageTitle 'Ideas'，pageDescription 'Capture a thought, paste text or drop a link. Approve the facts, say how each source may be used, and draft from any of them in your voice.'；`access={checkAccess(access,{permission:'read'})}`（route-level gating，viewer 可睇；所有 mutation 控件按 `edit` 隱藏，唔係 disabled 假掣）；pageHeaderAction = outline Badge 真計數 `{ideas} ideas · {sources} sources`（active only；loading '…'，isError 'Unavailable'，永遠唔以 0 代替）。

Grid：`grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_24rem]`。
- 左欄：Reminders（有先出）→ Capture card（edit 先見）→ Filter pills → Source list。
- 右欄 inspector（`lg:sticky lg:top-4 lg:self-start`）：選中 source 嘅 Inspector；未選 Empty 'Pick a source to review its facts and permissions'。
- Info sidebar（`infoContent`）：'How sources work'。

Primary action = Capture card 'Save to ideas'；secondary 'Draft now'（= `api.quickStart` 後 `router.push('/app/agent/{conversationId}')`，同 `home-view.tsx:170-192` handoff）。Inspector primary = 'Draft from this source'。

Responsive：
- 1440px：兩欄；list 行單行 meta；Inspector 常駐。
- 768px：單欄；Inspector 用 `ui/sheet` side='right'。
- 375px：單欄、16px gutter、無橫向 scroll；kind tabs `overflow-x-auto`；textarea rows=3；list 行 title / meta 兩行、badges wrap；Inspector = `ui/sheet` side='bottom'（max-h 85vh + ScrollArea）；Withdraw 喺 bottom sheet 內要測長按唔會觸發 sheet 拖曳；Info sidebar 入口用 header info 掣。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Reminders（remind, don't block） | 用真 snapshot / API 狀態提醒，唔阻止 capture 或 draft。 | 1) Voice：`!snapshot.isLoading && !state.speaker.activeRevision` → Alert 'Set up your voice first' + link `/app/workspace/brand`（搬自 ideas-view.tsx:204-215）。2) Web research：`useMemory().data.research` 有值且 `hosted && !web` → 'Web research is off for this workspace. Links you add are kept as unverified references until an owner turns it on under Memory → Web research.' + link `/app/workspace/memory`；`enabled === false` → 'Web research is switched off on this deployment.'；`hosted === false` → 唔顯示。3) Allowance：`useUsage().data.entitlement.writingBatchesRemaining === 0` → 'No writing batches left this period. You can still capture and review sources; drafts resume when the allowance resets {resetsAt}.'（resetsAt null 唔顯示日期）。4) Draft staleness（backend 收窄前）：選中 source 之前，Save / Approve / Policy 掣旁顯示真數 'Saving updates the brief: {n} unscheduled draft(s) will need a fresh draft before scheduling.'（n = `state.variants` 未排程且冇 blockedByRetraction 嘅數；n=0 唔顯示）。 | 只喺 query 成功而條件成立先 render；loading / error 唔 render。 |
| Capture card | 儲低原材料而唔一定即刻寫；或者一撳交去 conversation 寫。 | Card `data-tour='ideas-capture'`，只 `edit` 可見。pill Tabs（`components/motion/tabs` variant='pill'）：Idea · Paste text · Link · File。 - Idea：Textarea（rows 3，maxLength 500）；placeholder general-audience 'e.g. A question customers keep asking me…'。送 `act('source',{kind:'idea',text,title:text.slice(0,60)})`。Checkbox 'My own words (may be quoted publicly)' 預設 on（idea 預設已係 public_quote，`source_policy.py:17`）；off 時再送 `source_policy {policy:'rewrite_approval',egressConsent:['local'],confirmed:true}`。 - Paste text：Textarea（rows 6，maxLength 20000）+ Title（預設 'Pasted source'）+ own checkbox **預設 off**。送 `act('source',{kind:'text',text,title})`；own on 時再送 `source_policy public_quote` + `approve_source {factIds: 全部}`（照 ideas.py:549-552）。 - Link：URL input（`^https?://\S+$`，同 domain.py:282）+ Title。送 `act('source',{kind:'link',text:url,title})`；row 顯示真 unknown 'Link contents were not fetched.'。唔擺『Fetch now』假掣；Inspector 講明 'Drafting from this link reads the page when web research is on'（由 `research.web` 真值決定顯示）。 - File：`<input type=file accept='.txt,.md'>`，FileReader UTF-8，>20 KB 即時 inline error（同 domain.py:263-266）；送 `{kind:'document',text,title:file.name}`。 多步提交：每個後續 act 用上一個 act 回傳 snapshot 嘅 `revision`；中途失敗 toast server message 並 select 已建立嘅 source，由 Inspector 補做。 底部：左 'Nothing is sent to an AI model until you switch it on per source.'；右 `StatefulButton` 'Save to ideas'（loading → success 只喺 2xx 後，成功 select 新 source）+ outline 'Draft now'（`api.quickStart` 帶 `text, ownContent, confirmUse:true, model: useModelChoice(models.data).model, timeZone: useTimeZone()`；destinations 同 language 沿用 Home composer 嘅 channel chips 狀態，唔自己判斷 connected，唔傳就由 server `resolve_destinations` 決定；成功 `setQueryData(['agent-run',w,runId])` + invalidate conversations/snapshot/usage → `router.push`）。'Draft now' 下細字 'Drafts with {shortLabel} · {writingBatchesRemaining} batches left'（usage 載入中 '…'，error 'Unavailable'）。⌘↵ = Save。 | 重複 source：server 回 400 'That source is already here…' → toast server message，按 `fingerprint`（snapshot 已帶）或 title+kind 搵返現有 source 並 select。Revision 409 → invalidate snapshot + toast 'Changed in another tab — reloaded, your text is kept'。冇 edit → card 唔 render，list 上方一句 'You can review sources here; adding them needs the edit permission.' |
| Filter pills + Idea bank list | 一眼睇晒 workspace 有咩原材料、每條狀態、有冇用過。 | Filter pills（motion Tabs pill，`data-tour='ideas-filters'`），`DigitSwap` 真計數：All · Ideas · Text & files · Links · From the web（`origin?.kind==='web_research'`）· Withdrawn（`!active`）。Sort `createdAt` desc（domain 係 ISO string，hosted research source 可能係 epoch；用 `_created_epoch` 同樣規則 parse）。 List `SharedLayoutBg as='ul'`，每行 `<button>`（第一行 `data-tour='ideas-source-row'`）： - 第一行：title · kind Badge。 - 第二行：`{approved}/{facts.length} facts approved`（idea/link：'no facts · text used as the brief'）；policy Badge：'Quotable' / 'Rewrite · approve use' / 'Internal only' / 'Do not use' / `AnimatedBadge status='warning'` 'Policy needed'（`sourcePolicy == null`）；'Cloud allowed' / 'Local only'；`rewrite_approval` 且 `useApproved === false` → warning 'Public use not approved'；web research → host + external icon；'Used in {k} draft(s)'（k = `state.variants.filter(v=>v.sourceIds.includes(id)).length`，0 → 'Not used yet'）。 撳行 → `?source={id}` → Inspector（≥lg）或 Sheet（<lg）。 | Loading：3 條 `ui/skeleton` + pills '…'。Empty：`Empty` + `EmptyMedia variant='icon'`（paperclip）'Nothing captured yet' + 'Save a thought, paste text or drop a link above. Sources stay private; drafts are candidates until you approve them.'，edit 時 focus Capture textarea。Per-filter empty：'No links yet' 等。Error：Alert 'Your sources could not be loaded.' + Retry（`snapshot.refetch()`），pills 'Unavailable'。 |
| Source inspector | 一條 source 嘅全部決定同 provenance 喺同一處。 | Card（≥lg）/ Sheet（<lg）。 1) Header：title、kind、`formatDate(createdAt)`；web research：`origin.url`（`rel='noreferrer'`）、host、`fetchedAt`、'Found for: “{origin.query}”'、published（有先顯示）；`unknowns[]` 真值。Withdrawn：只顯示 'Withdrawn {withdrawnAt}' + 'The text was removed. Drafts that used it are blocked until drafted again.'（server 已清 text/facts）。 2) Facts（`data-tour='ideas-facts'`）：`components/motion/checkbox` checklist，text + locator；Select all / none；`StatefulButton` 'Save {n} approved' → `approve_source {sourceId,factIds}`（取代成套）。idea/link：'Ideas and links carry no quotable facts; drafts use the text as the brief.'。Edit 先可剔，read-only 顯示狀態。 3) How it may be used（`data-tour='ideas-policy'`）：POLICIES Select（搬自 sources-panel.tsx:14-19）+ cloud `Switch`；冇 paid route（`useModels` 冇 `costClass==='paid'`）→ '· no cloud route on this deployment'。 4) Public use（policy = rewrite_approval）：`useApproved` true → `AnimatedBadge status='success'` 'Public use approved for the current facts'；false → warning 'Needed before a draft from this source can be scheduled'。掣 'Approve public use of {approved} facts' → `AlertDialog`（列出 facts）→ `source_use_approve {sourceId,factsDigest,confirmed:true}`。Facts 改咗 → 'Facts changed; approve public use again'。批完之後顯示真句：'Drafts made before this approval need a fresh draft before scheduling.'（backend 收窄 staleness 前）。 5) Where it is used：`state.variants` 含此 id：platform · language · needsReview / blockedByRetraction 狀態 · link `/app/pipeline`；0 → 'Not used in any draft yet'。 6) Actions：primary `StatefulButton` 'Draft from this source'（`data-tour='ideas-draft'`，edit only）→ `api.createConversation(w,title)` → `api.turn(w,id,{text:'', intentText: source.text（link 即 URL）, sourceIds:[id], model, timeZone, reasoning:'quick'})`（destinations / language 唔傳就由 server resolve；唔好送 'Write a post from this source.'，否則觸發錯 query 嘅 web research）→ setQueryData agent-run → `router.push`；destructive `HoldActionButton` 'Hold to withdraw'（旁邊真句 'Blocks {k} draft(s) that used it'，k 由 state.variants 計）→ `retract_source {sourceId}`；如要 data-request 記錄用 `POST /data-requests {kind:'retraction',sourceId,expectedRevision}`（hosted.py:458-462），但唔顯示佢 receipt 嘅計數。 | act.isPending 時該區控件 disabled。成功 → `useAct` setQueryData snapshot（hooks.ts:150-162）。403 → toast server message。`source_use_approve` 409（digest 過時）→ refetch snapshot，重新開 AlertDialog 列新 facts，唔自動重試；revision 409 → invalidate + toast。 |
| Info sidebar | 解釋規則，唔重複 UI。 | title 'How sources work'。(1) 'Four ways to use a source'：Quotable / Rewrite then approve / Internal only / Do not use。(2) 'Leaving this server'：'A source reaches a cloud model only after its cloud switch is on. Local routes never send it anywhere.' (3) 'Web research'：真值 'On for this workspace' / 'Off — an owner can turn it on under Memory' / 'Switched off on this deployment' / 'On when drafting on your own machine'（`research.hosted/enabled/web`）。(4) 'Drafts and changes'：'Changing a source updates the brief, so unscheduled drafts are drafted again before scheduling.'（backend 收窄後改寫）。(5) 'Cost'：'{writingBatchesRemaining} writing batches left · resets {resetsAt}'；loading '…'，error 'Allowance unavailable'。 | 同 page 一齊載入；文案 general-audience。 |

- **Empty state**：無 source（snapshot 已載入，`state.sources.length === 0`）：list 位置 `Empty`（paperclip；'Nothing captured yet'；'Save a thought, paste text or drop a link above. Nothing here is sent to a model or published on its own: you approve the facts, the use, and every draft.'），edit 時 Capture textarea focus；Inspector 欄淡色 'Pick a source to review it'。Header badge 真 '0 ideas · 0 sources'（呢個 0 係真值）。冇 edit 嘅成員：'No sources yet. Someone with the edit permission can add them.'
- **Loading**：`snapshot.isLoading`：header badge '…'，pills '…'，list 3 條 `ui/skeleton`（`.t-skel-pulse`），Capture card 照 render 但掣 disabled 直至有 `revision`。`useUsage / useMemory / useModels` 各自 loading 只影響自己嘅字（'…'）。冇任何假 loading 字眼。
- **Error**：`snapshot.isError`：主體換成 Alert 'Your sources could not be loaded.' + Retry；header badge 'Unavailable'；Capture card 隱藏（冇 revision 唔可以 act）。Mutation error：toast `ApiError.message`；revision 409 → invalidate + toast，textarea 內容保留；重複 source（400）→ select 現有；use-approve digest 409 → 重新確認。`useModels` error → 'Draft now' 照可用（server 揀 default），hint 'Model list unavailable'。`useUsage` error → 'Unavailable'。`useMemory` error → web research reminder 同 sidebar 顯示 'Web research status unavailable'，唔當 off。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Source list rows（首次 render / filter 切換） | snapshot 到達 / filter 改變 | opacity 0→1、y 6→0，duration 0.24s，delay min(index×40ms, 60ms)（總長 ≤ 300ms），EASE_OUT；reduced motion → duration 0 | web/src/features/ideas/sources-panel.tsx:60-65 pattern（收緊 delay 上限）+ @/lib/ease EASE_OUT | 是 |
| Filter pills 同 header badge 計數 | snapshot 更新 | 數字滾動到新值；'…' / 'Unavailable' 時唔用 DigitSwap | web/src/components/motion/digit-swap.tsx | 是 |
| Filter pills 選中底色 | 撳 pill | pill 滑到新 tab | web/src/components/motion/tabs.tsx variant='pill' | 是 |
| List row hover 底色 | hover / focus | 底色 pill 喺行之間滑動 | web/src/components/motion/shared-layout-bg.tsx | 是 |
| 新 source 入 list | `source` action 成功後 snapshot 多一條 | AnimatePresence popLayout：新行 opacity + scale 0.96→1，其他行 layout='position'（SPRING_LAYOUT）；reduced motion 只 opacity | web/src/features/agent/home-view.tsx:341-365 AnimatePresence pattern + @/lib/ease SPRING_LAYOUT | 是 |
| Inspector 喺 <lg 開合 | 撳 row / close | Sheet 按 side 滑入 + cross-blur，用 token --panel-open-dur / --panel-close-dur（收快過開） | web/src/components/ui/sheet.tsx `.t-panel`（transitions.dev #07，web/src/styles/transitions.css:74-79,212-250） | 是 |
| Facts checklist 剔 | 撳 checkbox | 畫剔動畫 | web/src/components/motion/checkbox.tsx | 是 |
| Save to ideas / Save approved / Approve public use / Draft from this source | 撳掣 → API 回應 | idle → loading（真 in-flight）→ success（2xx 後），失敗返 idle + toast | web/src/components/motion/button/stateful.tsx（StatefulButton） | 是 |
| Hold to withdraw | 長按 | hold 完成先觸發 retract；放手即取消（motion §5.5 破壞性動作確認） | web/src/components/motion/hold-action-button.tsx | 是 |
| Policy / public-use badges | source 狀態變更 | status 切換 icon roll；warning 只喺真係要行動時 | web/src/components/motion/animated-badge.tsx | 是 |
| Cloud switch | 撳 switch | thumb 滑動 | web/src/components/motion/switch.tsx | 是 |
| Page 進入 | navigate 到 /app/ideas | 內容浮入 | web/src/app/app/template.tsx `.t-page-enter` | 否（純裝飾） |
| Ideas tips tour | TourMount 一次性 nudge toast 'Show me' / Help menu | 現有 TourOverlay spotlight 錨定 `[data-tour]`，按步驟前進 | web/src/features/onboarding/{tours.ts,tour-overlay.tsx,tour-mount.tsx,help-menu.tsx} | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Snapshot 帶 `state.sources`（含 origin / useApprovals / createdAt / unknowns / withdrawnAt / fingerprint） | api | 有 | src/postriff_alpha/domain.py:130-134 `_present` deep copy；src/postriff_phase2/hosted.py:182-183,504-507；stamp :221；欄位寫入 domain.py:284、ideas.py:318-319、source_policy.py:139 | S |
| 2 | `SnapshotSource` TS type 補齊 `origin?`, `useApprovals?`, `createdAt`, `unknowns?`, `withdrawnAt?`, `fingerprint?`, `useApproved?`, `factsDigest?`, facts `locator?` | frontend | 冇 | web/src/lib/api/types.ts:131-142 只有 id/kind/title/text/active/visibility/reviewedAt/sourcePolicy/egressConsent/facts | S |
| 3 | Server 喺 presented source 加 `useApproved` 同 `factsDigest` | backend | 冇 | source_policy.py:53-59 `facts_digest` / `use_approved` 只喺 server；stamp（:43-50）同 HostedPhase2Commands.present（hosted.py:182-183）都冇輸出 | S |
| 4 | Staleness 收窄：source / approve_source / source_policy / source_use_approve 只令引用該 source 嘅 variants 需要重寫（或 per-source revision），唔再 bump 全 workspace brief.revision | backend | 冇 | domain.py:183-187 `_mark_stale` 全部 variants；:285,298,313 及 source_policy.py:128,141 brief.revision += 1；store.py:278,354 要求 v.briefRevision == brief.revision | M |
| 5 | 加 source：`POST /actions {action:'source', payload:{kind,text,title}}` | api | 有 | domain.py:259-288；hosted.py:172-223 `HostedPhase2Commands.__call__` → engine._apply；permission edit（permissions.py:69-72）；重複回 400（domain.py:276） | S |
| 6 | （建議）`source` payload 收 `policy` / `approveAllFacts`，一次原子完成 capture | backend | 冇 | 而家要 3 次 act（source → source_policy → approve_source），quick_start 喺 server command 內串（ideas.py:545-552） | S |
| 7 | 逐條 fact approve：`approve_source {sourceId, factIds}` | api | 有 | domain.py:289-300 | S |
| 8 | Policy + cloud consent：`source_policy` | api | 有 | source_policy.py:111-129；前台 web/src/features/ideas/sources-panel.tsx:33-42 | S |
| 9 | 公開使用批准：`source_use_approve {sourceId, factsDigest, confirmed}` | api | 有 | source_policy.py:130-141；blocker :158；前台零 caller | S |
| 10 | 撤回：`retract_source {sourceId}` 或 `POST /data-requests {kind:'retraction', sourceId, expectedRevision}` | api | 有 | domain.py:302-313；hosted.py:458-462（receipt 計數係全 workspace） | S |
| 11 | Draft from an existing source：`POST /ideas/conversations` + `POST …/turns {text:'', intentText, sourceIds:[id], model, timeZone}` | api | 有 | hosted_app.py:241-246；ideas.py:192-198、:336-438（:345 intentText、:358 sourceIds）；client.ts:189-195 | S |
| 12 | Draft now（quick start）+ handoff 去 /app/agent/[id] | frontend | 有 | web/src/features/agent/home-view.tsx:170-192；web/src/app/app/agent/[conversationId]/page.tsx；conversation-view.tsx:290-341 | S |
| 13 | Run polling（如仍要喺 Ideas 顯示 run） | frontend | 有 | web/src/features/agent/use-run.ts:33；ideas-view.tsx:106-115 冇用 | S |
| 14 | Web research consent 真值 | api | 有 | research.py:94-98；hosted_app.py:467-468 → ideas.py:122-127；client.ts:145；types.ts:423-431 ResearchEgress；hooks.ts:133 useMemory | S |
| 15 | Allowance 真值 | api | 有 | hooks.ts:44 useUsage；types.ts:489-499 Entitlement | S |
| 16 | Model 選擇同 Home 一致 + timeZone | frontend | 有 | web/src/features/agent/use-model.ts:28 useModelChoice、:14 shortLabel；web/src/lib/preferences.tsx:72 useTimeZone；ideas-view.tsx:89,136 自己另存 | S |
| 17 | Route-level access gating | frontend | 冇 | page-container.tsx:27-48 有 `access` prop，但 ideas-view.tsx 冇傳；nav 隱藏只係 use-nav.ts:23 | S |
| 18 | Sheet、Empty（EmptyMedia variant）、AlertDialog、Skeleton primitives | frontend | 有 | web/src/components/ui/{sheet,empty,alert-dialog,skeleton}.tsx | S |
| 19 | beUI motion：StatefulButton、HoldActionButton、DigitSwap、AnimatedBadge、SharedLayoutBg、Tabs、Checkbox、Switch | frontend | 有 | web/src/components/motion/{button/stateful,hold-action-button,digit-swap,animated-badge,shared-layout-bg,tabs,checkbox,switch}.tsx | S |
| 20 | Tour infra（PAGE_TOURS registry、TourOverlay、nudge、Help menu） | frontend | 有 | web/src/features/onboarding/tours.ts:156,345；tour-mount.tsx；template.tsx mount；未 commit（另一 session） | S |
| 21 | Ideas page tour 條目 + `data-tour` anchors | frontend | 冇 | grep 'ideas' tours.ts 零結果；Ideas 冇 data-tour | S |
| 22 | Fetch a link now endpoint `POST /ideas/research`（P2：Draft from link 已經會喺 research allowed 時讀 URL） | backend | 冇 | 邏輯喺 ideas.py:279-334 綁住 turn；research.py:295 urls_in 直接讀 link；hosted_app.py:231-273 冇 research resource | M |
| 23 | Conversation rename / archive endpoint（P2） | backend | 冇 | ideas.py:172,189 SELECT archived_at；hosted_app.py:238-252 冇 PATCH/DELETE | S |
| 24 | Attachments 真正被 turn 讀取（未做之前 Ideas 唔提供 attach UI） | backend | 冇 | ideas.py:226 INSERT pr_attachments；turn（:336-438）冇 SELECT | M |
| 25 | Nav：icon 改 `paperclip` / `folder`；access 由 'edit' 改 'read'；header Create 改指 /app | frontend | 冇 | nav-config.ts:28-35 icon sparkles + access edit；header.tsx:36 `/app/ideas?new=1`；icons.tsx:182 paperclip、:249 folder | S |
| 26 | Per-channel language（跟 worldwide languages plan） | frontend | 冇 | intent.py:14 LANGUAGES 兩種；docs/postriff-worldwide-languages-plan.md §7 Ideas 行；Stage 2 未開始 | M |

## 3. Features

### P0

- **Source inspector：facts approve + policy + cloud + 公開使用批准**：rewrite_approval source 出嘅 draft 全部 candidateOnly，Queue 出 `source_use_approval_required`（source_policy.py:158）但前台冇掣可以批。呢個係 Ideas → Queue 流程斷咗嘅一環。
- **收窄 source 改動嘅 staleness（或真數提醒）**：而家儲一條 source / 批 facts / 批 public use 都會令全 workspace 未排程 draft 要重寫（domain.py:183-187；store.py:278,354）。冇呢步，Ideas 做得愈好，Queue 愈多莫名其妙嘅 'Regenerate' 錯誤，違反 remind-don't-block。（depends on：backend staleness 改動；未做之前用 Reminder #4 真數提醒）
- **Capture without drafting（Idea / Paste text / Link / File → `source` action）**：Buffer Ideas = capture 咗先、遲啲先變 post。PostRiff 已有 `source` action（domain.py:259-288）但前台只有 quick-start。分兩步令 Ideas 同 Home 分工清楚。
- **Draft from this source → 交去 /app/agent/[id]**：停止喺 Ideas 複製較差嘅 thread（冇 polling、冇 preview、冇 plan card）。用現有 createConversation + turn（text '' + intentText + sourceIds），同 quick_start 一致，避免錯誤 research query。
- **Provenance 同 unknowns 真值顯示**：web research source 已記 url/host/query/fetchedAt 同 'verify each claim' unknown（ideas.py:318-319），用戶睇唔到就冇辦法 verify 先批 public use。

### P1

- **Route-level RBAC + read-only 模式**：而家 viewer 打 URL 入到；approver 冇 edit 批唔到 use（permissions.py 冇列 source_use_approve）。頁面要誠實顯示邊啲自己做得。
- **Idea bank list：filters + 真計數 + 'Used in N drafts' + Withdrawn**：知邊啲未用、用咗喺邊、邊啲已撤回（blockedByRetraction 影響 pipeline，pipeline-view.tsx:103 會隱藏）。全部由 snapshot 計。
- **Withdraw（HoldActionButton）+ 真數顯示會 block 幾多 draft**：Retraction backend 已有（domain.py:302-313；hosted.py:458-462），marketing data-deletion 頁承諾『Remove a single source』（page.tsx:52）但 app 冇 UI。
- **Reminders：voice / web research / allowance / staleness（真值，唔阻止）**：House rule 2；flags 已有 API（speaker.activeRevision、GET /memory research、GET /usage entitlement、state.variants）。
- **Ideas page tips（接入現有 onboarding）+ 教學式 empty state**：Sources / policy / cloud / use-approval 係 PostRiff 獨有概念；SourcesPanel 冇 source 時 return null（sources-panel.tsx:44）。Tour infra 已喺 features/onboarding，只欠 Ideas 條目同 anchors。

### P2

- **Fetch the page now（新 endpoint）**：Draft from link 已經會讀頁（research allowed 時）；獨立 fetch 令 link 可以先審 facts 再寫。未有 endpoint 時唔顯示掣。（depends on：Web research consent；dev 要喺 Terminal 跑 scripts/postriff_dev_hosted.py（launch.json Run 掣 sandbox 封網，docs/postriff-agent-chat-design.md:590））
- **Conversation rename / archive**：Ideas 唔再放 conversation list，Home recent 會愈來愈長；archived_at 已有。（depends on：新 PATCH endpoint）
- **Content type tag on a source**：Buffer tags 貫穿 idea → post；PostRiff 對應物係 content type。要先決定 source-level 定 conversation-level。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明白：「呢度係我嘅原材料庫。我儲乜、批乜 fact、准佢點用，PostRiff 先會咁寫。」三樣嘢教：(1) pageDescription 一句講晒 capture → approve → draft；(2) Capture card 喺頂、四個 kind tabs；(3) 冇 source 時 Empty state 直接講規則。Tips 經現有 onboarding：喺 `web/src/features/onboarding/tours.ts` `PAGE_TOURS` 加 `{id:'ideas-tips', route:'/app/ideas'}`，由 TourMount 一次性 toast nudge（welcome 完成後）同 Help menu 重播；進度用現有 `postriff-onboarding` store。步驟用 `when` 按 `ctx.canEdit` 同 source 數（`TourCtx` 要加 `sourceCount`）跳過冇 anchor 嘅步，target 帶 structural fallback，唔會指住空氣。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour='ideas-capture']（when canEdit；fallback 'main h1'）` | Capture anything | A one-line thought, a pasted paragraph, a link or a .txt/.md file. Saving keeps it here; nothing is drafted or sent to a model yet. |
| 2 | `[data-tour='ideas-filters']` | Your idea bank | Every source you keep, with real counts: which still need a decision, which came from the web, which were withdrawn. |
| 3 | `[data-tour='ideas-facts']（when sourceCount > 0）` | Approve the facts | Only the sentences you tick can appear in a draft. Anything unticked stays out and is listed as an unknown instead of being guessed. |
| 4 | `[data-tour='ideas-policy']（when sourceCount > 0）` | Say how it may be used | Quote it, rewrite it (then approve public use), keep it internal, or never use it. The cloud switch decides whether it may leave this server for an AI model. |
| 5 | `[data-tour='ideas-draft']（when canEdit && sourceCount > 0）` | Draft from it | Opens a conversation that writes from this source in your voice and shows each post as its app would. Nothing publishes without your approval. |

**Empty state 教咩**：三種 capture（thought / text or file / link）；儲低 ≠ 送去 model ≠ 發佈；每條 source 由你決定 facts、用途、cloud；Draft 出嚟係 candidate，Queue 先係批准發佈嘅地方。文案 general-audience，唔用任何個人品牌或行業例子。

## 5. Next steps（按次序）

1. **Backend：presented source 加 `useApproved` 同 `factsDigest`（`HostedPhase2Commands.present` 內，stamp 之後）。Unit test 斷言 `GET /workspaces/{w}` 回兩個 field，`source_use_approve` 後 true、改 facts 後 false。**（effort S）  
   檔案：`src/postriff_phase2/source_policy.py（:43-59）、src/postriff_phase2/hosted.py（:182-183）、tests/test_postriff_phase2_hosted.py、tests/phase2/postgres_ideas.py`
2. **Backend：收窄 staleness——source / approve_source / source_policy / source_use_approve 只標記引用該 source 嘅 variants，唔 bump 全 workspace brief.revision（或引入 per-source revision 並改 store.py:278,354 檢查）。加 test：儲新 source 後，現有無關 draft 仍可 variant_review / schedule。需 James 拍板，因為影響 Queue 規則。**（effort M）  
   檔案：`src/postriff_alpha/domain.py（:183-187,:259-313）、src/postriff_phase2/source_policy.py（:109-142）、src/postriff_phase2/store.py（:278,:354）、tests/test_postriff_phase2_hosted.py`
3. **Types：`SnapshotSource` 加 `origin?`、`useApprovals?`、`createdAt`、`unknowns?`、`withdrawnAt?`、`fingerprint?`、`useApproved?`、`factsDigest?`、facts `locator?`。**（effort S）  
   檔案：`web/src/lib/api/types.ts（:131-142）`
4. **重砌 Ideas view：拆 `capture-card.tsx`、`source-list.tsx`、`source-inspector.tsx`、`use-sources.ts`（counts / usedIn / filter / staleness 數）。刪 thread、candidates、run log、conversations（ideas-view.tsx:218-264, :267-438, :444-513）；`sources-panel.tsx` 搬入 inspector 後刪。`PageContainer access` read gating，mutation 控件按 edit 隱藏。Draft 用 `useModelChoice` + `useTimeZone` + `text:'' / intentText`。加 `?source=` deep link。Row stagger 改 delay 上限 60ms。**（effort M）  
   檔案：`web/src/features/ideas/ideas-view.tsx、web/src/features/ideas/sources-panel.tsx（刪）、新 web/src/features/ideas/{capture-card,source-list,source-inspector}.tsx、web/src/features/ideas/use-sources.ts`
5. **Inspector mutations：approve_source、source_policy、source_use_approve（AlertDialog 列 facts；digest 409 → refetch 再確認）、retract_source（HoldActionButton，k 由 state.variants 計）；capture 多步用上一步回傳 revision 串起；重複 source（400）自動 select 現有。**（effort M）  
   檔案：`web/src/features/ideas/source-inspector.tsx、web/src/features/ideas/capture-card.tsx`
6. **Reminders + info sidebar 真值：voice、`useMemory().data.research`、`useUsage()`、staleness 真數；header badge 計數；'…' / 'Unavailable' 規則。**（effort S）  
   檔案：`web/src/features/ideas/ideas-view.tsx`
7. **Responsive + motion：<lg inspector `ui/sheet`（768 right、375 bottom，token 時長）；DigitSwap 計數；AnimatePresence popLayout；自加 motion 用 `useReducedMotion` 只郁 transform/opacity。Browser pane（:3100）375/768/1440、light/dark 逐個睇，唔撳 approve / schedule / withdraw。**（effort S）  
   檔案：`web/src/features/ideas/*.tsx（web/src/styles/transitions.css 只讀）`
8. **Tips：`tours.ts` PAGE_TOURS 加 `ideas-tips`（5 步、when + fallback selector），`TourCtx` 加 `sourceCount`（use-tour-context.ts），Ideas 加五個 `data-tour`。onboarding 仲未 commit，先同該 session 協調。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts、web/src/features/onboarding/use-tour-context.ts、web/src/features/ideas/*.tsx`
9. **Nav 同入口：Ideas icon 改 `paperclip`（或 `folder`）；access 改 'read'（配合 order 4 嘅控件隱藏）；header 'Create' 改指 `/app`（Home composer）；Home :372 文案改 'Ideas & sources'。James 決定 `source_use_approve` 係咪改 'approve' class（permissions.py + web/src/lib/auth/permissions.ts 要同步）。**（effort S）  
   檔案：`web/src/config/nav-config.ts（:28-35）、web/src/components/layout/header.tsx（:35-38）、web/src/features/agent/home-view.tsx（:269-272, :372）、src/postriff_phase2/permissions.py（:27-39）`
10. **Languages：跟 docs/postriff-worldwide-languages-plan.md §7 將 Draft now / Draft from this source 嘅 language 改用 per-channel chips（Stage 2 落地後），唔喺 Ideas 另寫 CJK 偵測。**（effort S）  
   檔案：`web/src/features/ideas/capture-card.tsx、web/src/features/ideas/source-inspector.tsx`
11. **P2 Backend：抽 `_research` 做 `research_sources(workspace_id, token, text)`，新 route `POST /api/workspaces/{w}/ideas/research {url}` → `{sourceIds, record}`；consent off 回 `off:true` record（唔 error）；喺 `/api/catalog` 或 memory research summary 暴露 capability flag，前台據此先 render 'Fetch the page now'（唔用 404 probe）。加 route test + PG test。**（effort M）  
   檔案：`src/postriff_phase2/ideas.py（:279-334）、src/postriff_phase2/hosted_app.py（:231-273）、web/src/lib/api/client.ts、tests/test_postriff_consumer_web.py、tests/phase2/postgres_research.py`
12. **P2：`PATCH /ideas/conversations/{id} {title?, archived?}` + Home recent archived filter；決定 source-level content type tag。**（effort S）  
   檔案：`src/postriff_phase2/ideas.py、src/postriff_phase2/hosted_app.py、web/src/lib/api/client.ts、web/src/features/agent/home-view.tsx`

## Risks

- 另一個 session 同日改緊 web/src（home-view.tsx 12:34、features/onboarding 17:16-17:24 未 commit）。重砌前要協調；commit 要 stage by path。
- Workspace-wide staleness：未做 next step 2 之前，Ideas 每次儲 source / 批 facts / 改 policy / 批 public use 都會令所有未排程 draft 要重寫（domain.py:183-187；store.py:278,354），連『批完 public use 嗰篇』都要 regenerate。上線前一定要至少有真數提醒，否則用戶會以為 Queue 壞咗。
- 身份決定：本 spec 將 candidates / thread 由 Ideas 移走交畀 /app/agent/[id]。如 James 想喺 Ideas 即場見 candidates，替代方案係 embed `features/agent/{use-run,variant-card,activity-strip}`，唔保留 bespoke code；兩者都要先修 polling bug。
- `source_use_approve` classify 為 'edit'（permissions.py:27-39 冇列）；nav 放寬到 read 都唔會令 approver 批到 public use——要 James 決定 class。前後端 permissions 要同步（web/src/lib/auth/permissions.ts 註明 mirror）。
- idea / link source 冇 facts（domain.py:279-280）：list 顯示 'no facts · text used as the brief'，唔可以扮有 0/0 可批。Quick start 將 ≤500 字無換行嘅 own text 當 idea（ideas.py:546），同理。
- Draft from this source 如果送非空 text（例如 'Write a post from this source.'），`needs_research` 會用錯誤 query 做 web search（research.py:128-141）；必須 text '' + intentText。
- Web research 喺 hosted 預設關；dev 用 launch.json Run 掣起 API 會被 sandbox 封網（docs/postriff-agent-chat-design.md:590），驗證要喺 Terminal 跑 scripts/postriff_dev_hosted.py。
- `retract_source` 清空 source text/facts 並令引用 variants `blockedByRetraction`（domain.py:303-312），pipeline-view.tsx:103 會隱藏 blocked variants；hold 前要顯示真數，data-request receipt 嘅 dependentVariantsBlocked 係全 workspace 數，唔可以用。
- Facts digest：approve facts 後 public use 會變返 needed，UI 要即時解釋；`source_use_approve` digest 過時回 409，唔可以同 revision 409 用同一個自動重試。
- 重複 source 回 400（唔係 409）；UI 靠 message / fingerprint 對返現有 source，文案改動會令 match 失效，最好 server 回 existing sourceId。
- Capture 多步 act 非原子，中途失敗會留下未設 policy 嘅 source；Inspector 要顯示 'Policy needed' 真狀態畀用戶補。
- Attachments endpoint 存在但 turn 唔讀（ideas.py:208-227）——未真係用到之前唔好提供 attach UI。
- Nav access 放寬到 'read' 後，所有 mutation 控件要按 `checkAccess(access,{permission:'edit'})` 隱藏，而唔係 disabled-with-fake-copy；route 亦要加 PageContainer access gating。
- Bottom sheet（375px）入面長按 HoldActionButton 可能同 sheet 手勢衝突，要真機 / Browser pane mobile preset 測。

## 覆核記錄

- 改正：quickStart/sendTurn/apply 冇傳 timeZone；Home 有（home-view.tsx:239） → 改引 home-view.tsx:127,170-192
- 改正：conversation-view.tsx:281-300 用 VariantCard / DraftPreview / PlanCard / ActivityStrip → 改引 conversation-view.tsx:290-341
- 改正：rewrite_approval 預設 source_policy.py:17；blocker source_use_approval_required 喺 :169 → 改引 :158
- 改正：重複 source 回 409 'That source is already here' → UI 要按 message / 400 處理，唔好 match 409
- 改正：Snapshot presenter deep copy：domain.py:130-134、hosted.py:470-473 → 改引 hosted.py:182-183,504-507
- 改正：useApproved / facts_digest 只喺 server；stamp() :33-40 → 改引 :43-59；HostedPhase2Commands.present 喺 hosted.py:182
- 改正：Home 兩處指去 /app/ideas：home-view.tsx:355-358 同 :363 → 改引行號，加 header.tsx:36
- 改正：docs：redesign §6.5 :341-345；agent-chat §8.6 :481-487；§11a :551 記錄 Ideas 保留 → 改引 :557
- 改正：Tour infra 唔存在（grep -rni tour web/src 零結果），要新開 web/src/hooks/use-tour.ts + localStorage postriff-tour-ideas → 喺 tours.ts PAGE_TOURS 加 route '/app/ideas' 條目 + Ideas 加 data-tour anchors；唔好新開 hook
- 改正：Sheet 開 250ms 收 150ms（transitions.dev #07） → 寫 'token --panel-open-dur / --panel-close-dur（400/350ms）'，唔好寫死數字
- 改正：Row stagger 沿用 sources-panel.tsx:60-65（0.24s + delay min(i×40ms, 200ms)） → delay min(i×40ms, 60ms)、duration 0.24s → 總長 ≤ 300ms
- 改正：SPRING_LAYOUT、EASE_OUT 喺 @/lib/ease；Home AnimatePresence popLayout :398-416 → 改引 :341-365
- 改正：useUsage hooks.ts:44；Entitlement types.ts:508-518 → 改引 :489-499
- 改正：Research consent：GET /memory hosted_app.py:463-464、client.ts:141、ResearchEgress types.ts:421-430 → 改引行號
- 改正：createConversation / turn client.ts:184-189 → 改引 :189-208
- 改正：retract 經 POST /data-requests {kind:'retraction'} 喺 hosted.py:445-449 → 改引 :458-462，註明計數唔可以當『呢條 source block 咗幾多』顯示
- 改正：Fixture 對中文 source 抽唔到 facts → 中文貼文會顯示 0/0 facts → 風險改寫為『idea / link 冇 facts』
- 改正：權限 gating：nav access edit 已足夠 → PageContainer access={checkAccess(access,{permission:'read'})} + mutation 控件按 edit 隱藏
- 改正：（spec 冇講）加 source / approve facts / 改 policy 只影響嗰條 source → 加 P0 backend requirement：staleness 只限引用該 source 嘅 variants；未做之前 UI 要真數提醒
- 改正：（spec 設計）Draft from this source 送 text 'Write a post from this source.' → turn body 用 {text:'', intentText: source.text, sourceIds:[id], ...}
- 違反原則（已改）：Motion §5.4：row stagger 0.24s + delay 上限 200ms = 440ms，超過『≤ 300ms 總長』；要將 delay 上限降到 60ms。
- 違反原則（已改）：Motion §5.4：Sheet 寫死 250/150ms，同 transitions.css token（--panel-open-dur 400ms / --panel-close-dur 350ms）唔一致；應該讀 token 唔好自己作數字。
- 違反原則（已改）：真數據（rule 1）：'Hold to withdraw' 顯示『Blocks {k} draft(s)』如果用 data-request receipt 嘅 dependentVariantsBlocked（hosted.py:462 計全 workspace）就係假數；k 必須由 state.variants.filter(sourceIds 含 id) 計。
- 違反原則（已改）：Remind, don't block（rule 2）：spec 冇講 Save / approve / policy 會 bump brief.revision 令所有 draft 要 regenerate（store.py:278,354）——實際效果係靜默 block 其他 draft 排程；至少要真數提醒，理想係 backend 收窄 staleness。
- 違反原則（已改）：Capability honesty（rule 5）：'Draft now' destinations 用『連接咗嘅 platforms，冇就 LinkedIn』係 blended connected 判斷；應沿用 Home composer 嘅 channel chips（per-capability 狀態）或者交畀 server resolve_destinations，唔好喺 Ideas 自己判斷『connected』。
- 違反原則（已改）：誠實 default：Paste text 預設勾『My own words (may be quoted publicly)』會將第三方文字一撳變 public_quote 兼 approve 全部 facts；Paste text / File 應預設 off，只有 Idea 預設 on。
- 違反原則（已改）：Reuse before inventing（rule 4 / stack）：tour 已有 features/onboarding（PAGE_TOURS registry + TourOverlay + HelpMenu），spec 另起 use-tour.ts 同新 localStorage key 係重複發明。
- 補上遺漏：Workspace-wide staleness：source / approve_source / source_policy / source_use_approve / retract_source 全部 bump brief.revision + _mark_stale（domain.py:183-187,285,298,313；source_policy.py:128,141），Ideas 每個動作都會令其他 draft 需要 regenerate；要列 backend requirement 同 UI 提醒。
- 補上遺漏：Capture 多步非原子：source → source_policy → approve_source 係三次 act，每次要最新 revision（用上一個 act 回傳 snapshot.revision 串起），中途失敗會留半套狀態；建議 server 端 `source` payload 收 policy/approveAll 一次完成。
- 補上遺漏：Route-level RBAC：ideas/page.tsx 冇 PageContainer access gating；viewer / approver 打 URL 可以入。要定 read 可睇、edit 先見 Capture 同 mutation 控件，並註明 source_use_approve 而家係 edit class（approver 批唔到）。
- 補上遺漏：第三個入口：header.tsx:36 『Create』→ /app/ideas?new=1；Ideas 移走 thread 之後要改指 /app（Home composer）或 /app?new=1，否則 Create 掣語意錯。
- 補上遺漏：Draft from this source 要用 text '' + intentText（照 quick_start ideas.py:562），否則觸發錯誤 web research query。Link source 經 intentText 帶 URL 其實已經會喺 research allowed 時讀頁（research.py:295 urls_in），『Fetch the page now』endpoint 可以降為 P2。
- 補上遺漏：Languages：intent.LANGUAGES 而家只有 English / 繁體中文（intent.py:14），docs/postriff-worldwide-languages-plan.md §7 表列 Ideas 嘅 language toggle（ideas-view.tsx:38,61,85…）會改為 per-channel chips；spec 嘅 CJK 偵測要跟該 plan，唔好再硬寫兩種語言。UI copy i18n 亦未有計劃。
- 補上遺漏：Tour 要接入現有 onboarding：TourCtx（tours.ts:14-24）冇 source 計數，Ideas tips 嘅 `when` 要加 sourceCount 或用 structural fallback selector。
- 補上遺漏：Error：source_use_approve factsDigest 唔啱回 409（source_policy.py:135-136），同 revision 409 要分開處理（前者要 refetch 後重新確認 facts，唔可以自動重試）。
- 補上遺漏：Withdrawn source 嘅 title 已被 server 改為 'Withdrawn source' 兼清空 text/facts（domain.py:303），Inspector 冇原文可顯示，要講清楚。
- 補上遺漏：Mobile：Sheet side=bottom 時 HoldActionButton 長按同 sheet drag-to-dismiss 手勢衝突要測；375px 下 Info sidebar 入口位置未講。
