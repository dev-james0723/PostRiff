# 07 · Pipeline

> Route：`/app/pipeline` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

【入口】`web/src/app/app/pipeline/page.tsx:1-8` 只 render `PipelineView`；sidebar `web/src/config/nav-config.ts:43-49`（Create group，icon `kanban`，shortcut p p，**冇 access key**，所以 viewer／approver 都見到）；breadcrumb `web/src/hooks/use-breadcrumbs.tsx:19`；Overview Getting started 第 4 步「Approve and schedule it」指嚟呢頁（`web/src/features/overview/getting-started.tsx:32`）。

【平行工作（2026-09-16 17:31-17:32，untracked）】另一個 session 已建立 `web/src/features/pipeline/board.ts`（deriveBoard、toEpoch、boardInvariants、COLUMN_META）同 `web/src/features/pipeline/job-state.ts`（jobGroup、jobBadge、HOLD_CANCEL_*，註明係 queue-view 嘅 copy）；`web/src/features/onboarding/`（tours.ts `PAGE_TOURS` :156、tour-overlay、store localStorage、help-menu）同多頁 data-tour（calendar-view.tsx:190、inbox-view.tsx:203/226、memory-view.tsx:200、brand-view.tsx:52、queue-view.tsx:216/261、getting-started.tsx:66）亦已加。Pipeline 未有 page tour，pipeline-view.tsx 仍未用 board.ts。

【數據】`pipeline-view.tsx:73` 只用 `useSnapshot()`（`web/src/lib/api/hooks.ts:39-42` → `GET /api/workspaces/{id}`，`src/postriff_phase2/hosted_app.py:459-462` → `hosted.py:541-542 service.get` → `_present`，`store.py:64-75` 加 channels displayState）。冇用 `useChannels()`（`hooks.ts:49-52` → `hosted_app.py:412-414` → `oauth.py:191 channels()`，view 由 `channels.py customer_view` 砌），所以卡片唔知 per-capability 能力。Snapshot 係成個 state deep copy（`hosted.py:124-127`），API 已送但 web types 未宣告：variant `revisions[]`（domain.py:370,386,400,507 有 `at` ISO；**hosted Ideas candidate `ideas.py:521` 冇 `at`、origin 'ideas-candidate'**）、`rejected`／`feedback[]`（store.py:333-334）、`runId`；source `createdAt`（domain.py:282 ISO）；review `createdAt`（store.py:286 epoch）；job `approvedAt/nextAt/scheduleId/approvedBy`（store.py:302）同 `nextAction`（只喺 worker 結果路徑：store.py:519-521、hosted_worker.py:126-134；**held 由 invalidate store.py:421-426 或 hosted_worker.py:66 產生時冇 nextAction**，原因喺 events 最後一條 message）。web types：`Job` types.ts:71-82、`Review` :84-89、`SnapshotVariant` :101-127、`SnapshotSource` :131-142。

【五欄邏輯（現行）】`pipeline-view.tsx:87-130`：Sources（active）、Drafts（未 review 或有 proposedUpdate，排除 blockedByRetraction）、Needs approval（review `needs_review`）、Scheduled（WAITING set line 61）、Published（`verified`）。

【已核實嘅缺口】
1. **嘢會消失。** WAITING（line 61）冇 held／failed／canceled；`reviewedKeys`（line 85）將所有 review（包括 stale，store.py:418-420）同所有 job 當已 review，所以 stale review、canceled/failed/held job 同佢哋嘅 draft 都唔喺任何一欄；`blockedByRetraction` draft 被 filter 走（line 103）。
2. **Scheduled 欄混咗 in-flight 同 uncertain**（line 120 同一個 secondary badge），Queue 頁分 WAITING/IN_FLIGHT/DONE/FAILED（queue-view.tsx:32-35, 74-80；held 喺 Queue 都係 neutral 且唔屬任何 filter）。
3. **計數同顯示唔一致**：DigitSwap 全數（line 146），只 render 首 30 張（line 155）。
4. **權限錯配**：`canSchedule = edit`（line 79）同時 gate Edit 同 Schedule…。ScheduleDialog 會送 accept_update、p2_variant_review（edit class）再送 p2_review（approve，`permissions.py:28`；web mirror `web/src/lib/auth/permissions.ts:14`）— `schedule-dialog.tsx:73-103`。Editor 冇 can_publish：variant_review 成功咗先喺 p2_review 403（半套 mutation）；admin 同樣冇 approve。
5. **語言標籤 hard-code**（line 104；edit-draft-dialog.tsx:53），同 worldwide-languages-plan §7.1／§7.1a（language-badge.tsx，flag + native name）相違；language-badge.tsx 未存在。
6. **狀態頁面唔齊**：loading 一塊 `Skeleton h-[32rem]`（line 137）；冇 error state（line 136 只 check isLoading）；空欄「Empty」（line 153）；成個 board 空冇教學。
7. **Motion 超標**：entrance delay `columnIndex*40ms + min(index,8)*30ms`（line 162）最長 400ms。Hover lift（line 166-168）、DigitSwap、ContextMenu 冇問題；每張卡 mount 隱藏 context menu 已記喺 docs/postriff-motion-system.md §6。
8. **Responsive 冇做**：5 × `w-72` 橫向 ScrollArea（line 139-142）。
9. **Board 唔會自己郁**：hooks.ts 冇 refetchInterval（web/src 0 hit）；Vercel cron 每分鐘打 `/api/cron/worker`（vercel.json:57-62；hosted_app.py:326-337），頁面要 reload。
10. **Action 得一半**：有 Edit、Schedule…、Copy text、前往連結；冇 set aside（`p2_variant_feedback` store.py:322-334，FEEDBACK_REASONS :23）；冇 cancel（Queue 只喺 WAITING 顯示 HoldActionButton，queue-view.tsx:360、:192）；approve 留喺 Queue（:148）係啱。冇 delete/archive draft action。
11. **Sample workspace**：後端所有 mutate 403（hosted.py:189），web 完全冇 `workspace.sample` 處理。

【Edit dialog】`edit-draft-dialog.tsx`：LIMITS hard-code 三個平台（line 13）鏡 contracts.py:11-14；但 `web/src/components/application/post-preview/limits.ts` 已有逐渠道、有出處、正確計法嘅 limits（`limitNotes` :127、`LIMITED_CHANNELS` :159）未被重用。Save line 28-45 → actions（hosted_app.py:477-486 → hosted.py:152-160 mutate → :184-223；variant_edit domain.py:376-389 bump revision、customized、append revision；hosted.py:216-220 set needsReview 同還原 unknowns）。`dirty`（line 26）同 `variant.text` 比較而初始值係 proposedUpdate.text，有 update 時一開就 dirty。學習訊號由 derive_events（learning_signals.py:105；edited :125、rejected :130、approved :144、cancelled :146）經 hosted effects hook（hosted.py:146-147 → learning_service.py:236）自動推導，Pipeline 唔使額外送嘢。

【存在嘅 endpoints】`GET /api/workspaces/{id}`；`POST /api/workspaces/{id}/actions`（variant_edit／accept_update／opening domain.py:359-400；p2_variant_review store.py:274-283；p2_review :284-286；p2_approve :287-305；p2_approve_many :306-315；p2_cancel :316-321，held 可 cancel、in-flight 變 uncertain；p2_variant_feedback :322-334）；`GET /api/workspaces/{id}/channels`；`GET /api/workspaces/{id}/analytics/summary|posts`（hosted_app.py:396-397）；`GET /api/catalog`（:283-285，未送 limits）；`GET /api/cron/worker`。

【缺嘅】draft delete/archive；API limits；Pipeline page tour（runner 已有）；web test runner（package.json 冇 vitest/jest）；language-badge.tsx；web sample-workspace gating。

## 1. Design specification（最新版）

**目的**：Pipeline 係「每一個 draft 而家喺邊、等緊乜」嘅狀態板，唔係 drag board。五欄由 workspace snapshot 純函數推導（`features/pipeline/board.ts`），保證每個 variant／review／job 都喺唯一一欄或者欄底一個有真計數嘅 group，永遠唔會消失。每次向右移都係有收據嘅明確 action（review、approve、provider 確認），所以 board 淨係顯示狀態，action 放喺卡片同 detail sheet。所有權限按真 membership（approve／edit）gate，冇權限就講明要邊個角色，唔會撞 403。

**Layout**：PageContainer（pageTitle「Pipeline」、description、infoContent）。Header 下面一行：左邊「Needs you」NotificationStack（有 item 先出現），右邊 platform filter（motion Tabs pill：All + snapshot 出現過嘅 platform，每 tab 帶 DigitSwap 真計數）。主體 board：
- ≥1440px：`grid grid-cols-5 gap-4`，每欄 `min-w-0`，欄內 `max-h-[calc(100dvh-14rem)] overflow-y-auto`，冇橫向 scroll。
- 768px：保留 ScrollArea 橫向，欄 `w-72 shrink-0`，加 `snap-x snap-mandatory`／`snap-start`。
- 375px：唔顯示五欄，motion Tabs `variant='segment'` 揀欄（短 label + DigitSwap 計數，tab list 可橫掃唔爆闊），下面一欄卡片 full width；預設 tab = 第一個有 Needs you item 嘅欄，否則 Drafts。Needs you stack 喺 tabs 上面。Actions row 常駐卡片（touch 冇 hover；context menu 只作 desktop 右鍵，唔靠長按以免同 scroll 打交）。
主要 action：Drafts 卡「Schedule…」（edit+approve 先有）；board 空而用戶有 edit 時 header action「Draft a post」→ `/app/ideas?new=1`（ideas-view.tsx:99 會處理）。Viewer 見到同一個 board，全部 mutate action 隱藏，infobar 講明係 read-only。Info sidebar 保留兩節，加「Badges」同「Who can do what」。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Needs you stack | 一眼睇到有乜嘢卡住、點解、邊個可以處理。 | 重用 Home 嘅 NotificationStack（`web/src/components/motion/notification-stack.tsx`；用法 `web/src/features/agent/home-view.tsx:301`）。Items 全部由真數推導，0 就唔 render：`N drafts need a review of unknowns`（variants needsReview；係 reminder，Schedule… 入面可以直接處理，唔 block）、`N reviews waiting for approval`（reviews needs_review；有 approve 叫「Approve in the Queue」，否則「An approver must approve」）、`N jobs held`（description = job.nextAction ?? events.at(-1).message）、`N publications uncertain`、`N drafts blocked by a retracted source`、`N channels cannot publish directly`（由 `useChannels()` 嘅 `capabilities.publish.level !== 'Direct'` 計，顯示 level + evidence；channels query loading／error 時呢項唔出現，唔當 0，亦唔用 blended displayState）。onViewAll 捲去對應欄（desktop）或切 tab（mobile）。 | 0 items → 唔 render；1 item → expandedLabel 係該 item 嘅 action；channels query 失敗 → 只略過 channel 項。 |
| Columns (deriveBoard) | 五欄，每個 object 唯一歸屬。 | 純函數 `deriveBoard(state, filterPlatform, now)` 喺 `web/src/features/pipeline/board.ts`（平行 session 已起稿，先 review 對齊，唔好重寫第二份）： - key = `${variantId}:${contentRevision}`；LIVE_JOB = {approved, scheduled, claimed, held, submitting, provider_accepted, published, uncertain, verified}（`job-state.ts`）；liveKeys = needs_review reviews ∪ LIVE_JOB jobs 嘅 key。 - Sources = active sources，createdAt desc（ISO／epoch 經 toEpoch）。 - Drafts = variants 中 `!liveKeys.has(key) \|\| proposedUpdate`，**包括** blockedByRetraction 同 rejected。Chip 優先：source retracted（danger）→ set aside（neutral，收喺欄底「Set aside · N」collapsible）→ update proposed（info）→ needs review（warning）→ 上次結果：最新 job canceled「cancelled」、failed「failed」+ tag nextAction、最新 review stale「review expired」。排序：最後一個有 `at` 嘅 revision desc，冇 `at`（hosted Ideas candidate）就跟 snapshot 陣列次序排後。 - Needs approval = reviews needs_review，`manifest.timing.utc` asc。Stale／approved review 唔顯示（approved 由 job 代表；stale 由 draft chip 交代）。欄 hint 註明 workspace 只保留最近 20 個 review（store.py:286）。 - Queue（hint「Approved; the worker publishes and the provider confirms」）分組：held（warning「held」+ 原因）、uncertain（warning「uncertain · reconciling」）、publishing {submitting, provider_accepted, published}（loading pulse）、waiting {approved, scheduled, claimed}（info，subtitle timing.local）；cancelRequested 顯示「cancelling」。欄底 collapsible「Cancelled or failed · N」。Badge 用 `job-state.ts jobBadge`。 - Published = verified jobs，`verification.at` desc；「verified · {method}」；`manifest.execution === 'synthetic'` 加 neutral「Fixture」。 - Invariant：每個 job id 出現一次；每個 needs_review review 出現一次；每個 variant 喺 Drafts iff 上述條件（`boardInvariants`）。filterPlatform 只影響顯示；tab 計數係 filter 後真數。 每欄 header：title + DigitSwap 計數 + hint；超過 40 張卡顯示「Show N more」（唔再靜靜 slice 30）。 | 欄空：每欄一句教學。Filter 後空：「No {platform} items in this column.」 |
| Card | 一張卡答到「係乜、喺邊、等乜、可以做乜」。 | Header：ChannelIcon + platform + 語言（language-badge.tsx 落地前直接顯示 `variant.language` 原字串，唔准 hard-code map）；右邊 AnimatedBadge（jobBadge／draft chip）。Body：`line-clamp-3 whitespace-pre-wrap`。Meta（field 存在先 render，`web/src/lib/time.ts:35 relativeTime` + `toEpoch`）：Draft = 最後有 `at` 嘅 revision（origin：fixture／ideas-candidate→written，author-edit→edited，chosen-opening→opening chosen，accepted-fixture-replacement→update accepted）；Review = createdAt + timing.local；Job = waiting「scheduled for {timing.local}」，其他 events.at(-1).at；Source = createdAt + approved facts／facts 真數。Tag：warnings[0]，或 job.nextAction ?? events.at(-1).message。 Actions（`useWorkspaceAccess` + `checkAccess`，`web/src/lib/auth/access.tsx:61,69`）： - Edit／Set aside…：edit。 - Schedule…：edit **且** approve（ScheduleDialog 會送 accept_update／p2_variant_review 再 p2_review）。有 edit 冇 approve → muted「Needs an approver to schedule」；有 approve 冇 edit → muted「Needs an editor to prepare」。 - rejected draft：Schedule… 唔出現，顯示「Edit to restore」（variant_edit／accept_update 會 clear rejected，domain.py:369,389）。 - Queue waiting／held：Cancel（HoldActionButton，approve）。 - held：先 Cancel，cancel 完 draft 返 Drafts 先有 Schedule…（held job 仍計 daily limit store.py:298、仍擋 variant_feedback store.py:331）；failed／cancelled：draft 喺 Drafts 直接 Schedule…（ScheduleDialog 已支援 preselect variantId，schedule-dialog.tsx:38,53）。 Context menu（`components/motion/context-menu`，desktop 右鍵）：Edit draft／Schedule…／Set aside…／Copy text／Open details／前往欄連結，同樣按權限。`state.workspace.sample` 為 true 時隱藏所有 mutate action 並喺 header 講明 sample 係 read-only。 | hover-capable 先有 lift；reduced motion 只 opacity；卡片係 button 語意，Enter 開 sheet。 |
| Detail sheet | 解釋「點解喺呢度」，唔使跳頁。 | `web/src/features/pipeline/pipeline-card-sheet.tsx` 用 `web/src/components/ui/sheet.tsx`（transitions.dev #07）。 - Draft：`post-preview/draft-preview.tsx`（account = 同 platform 嘅 channel account，冇就 speaker.label）、全文、warnings／unknowns、sources 標題、revision history（倒序，origin label 同上，冇 `at` 就唔寫時間）、feedback（reasons chips + note）、同卡片一樣嘅 actions。 - Review：`post-preview/manifest-preview.tsx`、digest 頭 8 位、createdAt、timing、「Open in Queue to approve」。 - Job：ManifestPreview、events timeline（state／message／at）、attempts 數、providerReference、providerConfirmed、verification、nextAction、execution（synthetic →「Fixture」）、Cancel（waiting／held，approve）。 - Source：全文、kind、visibility、facts（approved 打剔）、「Open in Ideas」。 | item 喺 sheet 開住時被新 snapshot 移走 → 「This item moved」+ 新位置連結；找不到 → 「This item is no longer in the workspace」。關閉時 focus 返回原卡。 |
| Set aside dialog | 唔用呢個 draft，但唔刪。 | `web/src/features/pipeline/set-aside-dialog.tsx`：reasons checkbox（FEEDBACK_REASONS store.py:23，label 用中性英文）+ note ≤200 字；送 `p2_variant_feedback {variantId, variantRevision, reasons, note}`（edit）。Description：draft 會收埋喺「Set aside」組，Edit 會還原；PostRiff 只透過 Memory 頁你接受嘅 preference 學嘢。有未取消 job 時唔提供呢個 action（後端 409 store.py:331），真撞到就 toast 原句。 | pending 用 `components/motion/button/stateful.tsx`；409「This draft changed」→ refetch snapshot 再提示。 |
| Info sidebar | 解釋 board 規則、badge 同權限。 | 保留 `pipeline-view.tsx:53-59` 兩節，加「Badges」：waiting／publishing／uncertain（provider 未確認，reconcile 先會重試）／held（approval、capability 或額度變咗，要 cancel 再準備新 review）／verified（provider 確認）／Fixture（synthetic provider，唔係真 post）。加「Who can do what」：editor 可 Edit／Set aside；approver 可 Cancel 同喺 Queue approve；Schedule… 要兩樣都有；viewer 只睇。 |  |

- **Empty state**：條件：active sources、variants、reviews、jobs 全部 0（snapshot 已成功載入）。Render 五欄 header 顯示真 0 計數，欄內各一句教學；board 上面 `Empty`（`web/src/components/ui/empty.tsx`）：EmptyMedia `Icons.kanban`、title「Nothing on the board yet」、description「Sources become drafts. A draft becomes an exact review of text, account and time. An approved review becomes a job, and the provider confirms it. Start with one sentence.」；有 edit：primary「Draft a post」→ `/app/ideas?new=1`、secondary「Add a source」→ `/app/ideas`；冇 edit：唔顯示按鈕，改一句「An editor in this workspace adds drafts.」。每欄教學句（general）：Sources「No sources yet. Drafts can start from a sentence; sources give them facts to draw on.」；Drafts「No drafts. Write one in Ideas and it lands here.」；Needs approval「Nothing waiting. Schedule… on a draft prepares an exact review here.」；Queue「Nothing approved yet. Approve a review in the Queue and it waits here for its time.」；Published「No provider-confirmed posts yet.」
- **Loading**：`snapshot.isLoading`：結構性 skeleton — 五欄 header（title 真文字、計數位留空唔顯示 0）+ 每欄三張 card skeleton（`ui/skeleton`，#14）。375px 顯示 segment tabs skeleton + 一欄。冇假 copy。`isFetching && data` 時唔閃 skeleton，計數用 DigitSwap 更新。useChannels loading 時 capability 相關 chip／Needs you 項唔出現（唔係 0）。
- **Error**：`snapshot.isError`（冇 data）：`Empty`，EmptyMedia `Icons.refresh`，title「The board could not load」，description = `err instanceof ApiError ? err.message : 'The workspace snapshot did not arrive.'`，button「Try again」→ `snapshot.refetch()`；唔 render 任何計數。有舊 data 但 refetch 失敗：保留上一個真 snapshot，header 細字「Last updated {relativeTime(dataUpdatedAt)}」。Mutation 失敗（Edit／Schedule／Set aside／Cancel）→ sonner toast 用 ApiError 原句；409「Workspace changed; reload.」→ 自動 invalidate snapshot。useChannels 失敗 → capability 相關位置顯示「Channel capabilities unavailable」。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Page | route enter | 內容浮入（transitions.dev #08 page slide）；純 route 裝飾 | web/src/app/app/template.tsx `.t-page-enter` | 否（純裝飾） |
| Cards on first render | snapshot 首次到達 | opacity 0→1、y 6→0，duration 0.18s EASE_OUT；五欄同時開始（刪 columnIndex 項），每欄 stagger 30ms、cap index 4 → 最長 delay 120ms，最後一張 300ms 內完成；之後 refetch 唔再播；reduced motion 唔做 initial | 現有 pipeline-view.tsx:158-163 改參數；EASE_OUT from web/src/lib/ease.ts | 是 |
| Job card changing group/column | polling／refetch 令同一個 job 由 waiting→publishing→verified 或變 held／uncertain | `motion.div layout layoutId={'job-'+job.id}` + AnimatePresence，SPRING_LAYOUT 滑去新組／新欄；exit 0.15s 快過 enter 0.18s；reduced motion 只 opacity。唔做 draft→review 跨 kind 滑動（Schedule… 成功會跳去 /app/queue） | SPRING_LAYOUT web/src/lib/ease.ts:37-42；pattern from queue-view.tsx MotionTableRow／REVIEW_EXIT | 是 |
| Column counts / filter tab counts | 計數改變 | 逐位滾動 | web/src/components/motion/digit-swap.tsx | 是 |
| Status badge on card | job／variant 狀態改變 | AnimatedBadge contentKey=state，只有 publishing／cancelling pulse | web/src/components/motion/animated-badge.tsx + web/src/features/pipeline/job-state.ts jobBadge（之後同 queue-view 共用） | 是 |
| Needs you stack | hover／focus 展開 | 疊卡展開，count badge 真數 | web/src/components/motion/notification-stack.tsx（home-view.tsx:301 用法） | 是 |
| Platform filter / mobile column picker | 揀 tab | pill／segment indicator 滑動 | web/src/components/motion/tabs.tsx variant pill（desktop）／segment（375px） | 是 |
| Cancel a waiting/held job | 長按 | hold-to-confirm 波浪填充，放手未完成即取消 | web/src/components/motion/hold-action-button.tsx + HOLD_CANCEL_* from web/src/features/pipeline/job-state.ts | 是 |
| Card hover | pointer hover（hover-capable only） | y -2，0.18s | 現有 pipeline-view.tsx:166-168 + useHoverCapable | 否（純裝飾） |
| Detail sheet | 撳卡／Enter／Open details | 側面滑入 + cross-blur，收快過開 | web/src/components/ui/sheet.tsx（transitions.dev #07） | 是 |
| Context menu | desktop 右鍵 | 跟 trigger 方向放大（#05）；改為第一次開先 mount（motion doc §6 待辦） | web/src/components/motion/context-menu.tsx | 否（純裝飾） |
| Set aside / Edit save buttons | mutation pending → success | Saving… → 剔（只喺 API 成功先播） | web/src/components/motion/button/stateful.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Workspace snapshot endpoint（sources／variants／phase2.reviews／jobs） | api | 有 | hosted_app.py:459-462 → hosted.py:541-542 service.get → store.py:64-75 _present；hooks.ts:39-42 useSnapshot | S |
| 2 | Actions endpoint 接 variant_edit／accept_update／p2_variant_review／p2_review／p2_cancel／p2_variant_feedback | api | 有 | hosted_app.py:477-486；hosted.py:152-160, 184-223；domain.py:359-400；store.py:274-286, 316-334；RBAC permissions.py:15-39 | S |
| 3 | Capability matrix query（channels[].capabilities.publish.level + evidence） | api | 有 | hosted_app.py:412-414 → oauth.py:191 channels() → channels.py customer_view；hooks.ts:49-52 useChannels；types.ts:436-457 Capability/ChannelView | S |
| 4 | Learning signals 由 Pipeline action 自動推導 | backend | 有 | learning_signals.py:105 derive_events（:125,:130,:144,:146）；hosted effects hook hosted.py:146-147 → learning_service.py:236 | S |
| 5 | Tour runner + page tour registry | frontend | 有 | web/src/features/onboarding/tours.ts（PAGE_TOURS :156）、tour-overlay.tsx、store.ts（untracked，平行 session）；Pipeline 未有 page tour，要加 data-tour 同 PAGE_TOURS entry | S |
| 6 | deriveBoard 純函數 + boardInvariants | frontend | 有 | web/src/features/pipeline/board.ts:296 deriveBoard、:407 boardInvariants（untracked 草稿，未接入 pipeline-view.tsx）；需要 review 對齊本 spec（held 原因、冇 at 嘅 revision） | M |
| 7 | Job-state mapping（WAITING/PUBLISHING/UNCERTAIN/HELD/LIVE_JOB、jobBadge、HOLD_CANCEL_*） | frontend | 有 | web/src/features/pipeline/job-state.ts（untracked copy）；queue-view.tsx:32-35, 47-51, 74-80 仍然各自一份 → 之後共用 | S |
| 8 | Web types 補齊：SnapshotVariant.revisions（at 可缺）/rejected/feedback/runId、SnapshotSource.createdAt、Review.createdAt、Job.approvedAt/nextAt/scheduleId/approvedBy | frontend | 冇 | types.ts:71-142 冇；board.ts:19-50 暫用 local narrow types；payload 有（domain.py:282,386；ideas.py:521；store.py:286,302,333-334） | S |
| 9 | Unit test runner + board invariant tests | frontend | 冇 | web/package.json 冇 vitest/jest；web/src 冇 *.test.* | M |
| 10 | Set aside UI（p2_variant_feedback） | frontend | 冇 | 後端 store.py:322-334 + FEEDBACK_REASONS :23；web/src 冇呼叫 | S |
| 11 | Detail sheet（DraftPreview／ManifestPreview／revision history／job events／receipt） | frontend | 冇 | primitives 有：ui/sheet.tsx、post-preview/draft-preview.tsx、post-preview/manifest-preview.tsx；組合未有 | M |
| 12 | 權限 gating：Edit／Set aside = edit；Schedule… = edit AND approve；Cancel = approve；viewer read-only；sample workspace 隱藏 mutate | frontend | 冇 | pipeline-view.tsx:79 只用 edit；schedule-dialog.tsx:73-103 送 edit + approve 兩類 action；permissions.py:28；web lib/auth/permissions.ts:13-14；hosted.py:189 sample 403；web/src 冇 workspace.sample 處理 | S |
| 13 | Error state + 結構性 loading + board／per-column empty | frontend | 冇 | pipeline-view.tsx:136-137 只有 isLoading；:153「Empty」；ui/empty.tsx 有 primitive（queue-view.tsx:281-289 用法） | S |
| 14 | 375px 單欄 segment 佈局 + 1440px grid | frontend | 冇 | pipeline-view.tsx:139-142 固定 w-72 橫掃；motion/tabs.tsx:18 有 segment variant | M |
| 15 | Pipeline 內 snapshot polling（有 live job 先 poll，背景 tab 唔 poll） | frontend | 冇 | hooks.ts:39-42 冇 refetchInterval；cron vercel.json:57-62 + hosted_app.py:326-337；job.nextAt 喺 payload（store.py:302） | S |
| 16 | Timestamp normalise helper（ISO string 同 epoch 秒） | frontend | 有 | board.ts:58 toEpoch（草稿）；domain.py:30-31 now() ISO，phase2 store 用 self.clock() epoch；Python 側對應 store.py:26 signals_epoch；web lib/time.ts:35 relativeTime 只接 epoch | S |
| 17 | Edit dialog 重用 post-preview limits | frontend | 冇 | web/src/components/application/post-preview/limits.ts:127 limitNotes、:159 LIMITED_CHANNELS 已存在；edit-draft-dialog.tsx:13 仍 hard-code 3 個平台 | S |
| 18 | Language badge（flag + native name） | frontend | 冇 | docs/postriff-worldwide-languages-plan.md:340（§7.1）、:342（§7.1a）；web/src 冇 language-badge；pipeline-view.tsx:104、edit-draft-dialog.tsx:53 hard-code | S |
| 19 | Platform publish limits 經 API（/api/catalog 加 limits） | backend | 冇 | contracts.py:11-14 LIMITS；hosted_app.py:283-285 catalog 未送 | S |
| 20 | Draft archive/delete action | backend | 冇 | domain.py／store.py 冇 delete／archive variant action；本 spec 用 p2_variant_feedback「Set aside」代替，唔加 endpoint | M |

## 3. Features

### P0

- **Nothing vanishes：deriveBoard 保證 held／failed／cancelled／stale／retracted／set-aside 全部可見**：真數據先郁：而家 job 一 hold／fail／cancel、review 一 stale、source 一 retract，draft 同 job 都唔喺任何一欄（pipeline-view.tsx:61,85,103）。board.ts 草稿已存在，要 review、補 held 原因同冇 at 嘅 revision，再接入 view。
- **誠實嘅 Queue 欄：waiting／publishing／uncertain／held 分開 badge，synthetic 標「Fixture」，欄底「Cancelled or failed · N」**：Capability honesty：uncertain 同 published-未-verified 而家讀成「Scheduled」。held 原因讀 nextAction ?? 最後 event message，唔會空白。
- **權限正確嘅 actions：Edit／Set aside（edit）、Schedule…（edit + approve）、Cancel（approve）、viewer 同 sample workspace 冇 mutate**：而家 editor 冇 can_publish 會半套 mutation 後 403；approver 冇 edit 會喺 accept_update／p2_variant_review 403。冇權限時講明要邊個角色，而唔係靜靜隱藏或者撞錯。
- **Card detail sheet：全文、preview、revision history、job events、provider receipt、nextAction**：「點解喺呢度」係呢頁存在理由；資料已喺 snapshot，只係 types 冇宣告。
- **真 loading／error／empty states + 每欄教學句**：「Empty」一個字唔教嘢；冇 error state 會令 API 落咗時 board 空白，似係 0。
- **保持「唔 drag」，用明確 action 代替拖拉**：每次向右移都要收據（review digest、approve、provider 確認），drag 會令狀態同收據脫節。repo 雖然有 ui/kanban.tsx（dnd-kit），呢頁刻意唔用。

### P1

- **Set aside（p2_variant_feedback）+ Drafts 欄底「Set aside · N」，Edit 還原**：冇 delete，Drafts 只會越積越多；後端已有 rejected + FEEDBACK_REASONS，而且係 learning 訊號（learning_signals.py:130）。係用戶自己嘅決定，唔係系統 block。
- **Needs you stack + platform filter（真計數，channel 項讀 capability matrix）**：重用 Home 嘅 NotificationStack；多 channel 用戶一眼睇到邊度卡住。Channel 項用 per-capability level + evidence，唔用 blended displayState。（depends on：P0 deriveBoard；useChannels）
- **375px 單欄 segment 佈局、1440px 五欄 grid**：五個 18rem 欄橫掃喺手機唔可用；大 mon 浪費闊度。
- **Live board：有 live job 先 poll，同一 job 換組／欄用 layoutId 滑動**：Cron 每分鐘推進 job，但 board 唔 reload 就唔郁。Polling 由真狀態決定；動畫只喺真 state 變化時播。（depends on：types 補 nextAt；P0 deriveBoard）
- **Pipeline page tour（註冊入現有 PAGE_TOURS）**：Tour runner 已存在（features/onboarding），只需 data-tour target 同 tour 定義；copy 讀 TourCtx 真數。
- **Edit dialog 用 post-preview/limits.ts；language badge 取代 hard-code 繁中／EN**：limits.ts 已有出處同正確計法；§7.1a 已拍板 flag + native name。（depends on：language-badge.tsx（worldwide-languages workstream））

### P2

- **Platform publish limits 由 /api/catalog 送**：contracts.py 係 publish 嘅 authority，前端 mirror 會 drift。
- **Keyboard：欄之間 ←→、卡片 ↑↓、Enter 開 sheet；context menu lazy mount**：Board 而家只有 pointer；motion doc §6 記低每卡 mount 隱藏 menu 嘅成本。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明白：（1）由左到右五個階段，每張卡而家喺邊；（2）冇嘢會自己向右郁，每一步係人或者 provider 嘅明確動作；（3）計數係真嘅，冇權限做嘅 action 會講明要邊個角色。頁面用欄 header hint、Needs you stack、空欄教學句教；Info sidebar 補 badge 同權限；tour 用現有 onboarding runner（help menu 可重開）。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `新加 data-tour="pipeline-board"（五欄容器；375px 放喺 segment tabs 容器）；fallback 'main h1'` | Left to right | Sources become drafts; drafts become exact reviews; approved reviews wait in the queue; the provider confirms. Nothing moves by itself and nothing is dragged. |
| 2 | `新加 data-tour="pipeline-col-drafts"（Drafts 欄 section；現有 aria-labelledby="col-drafts" 可作 fallback selector `section[aria-labelledby="col-drafts"]`）` | Drafts | Edit the text, or choose Schedule… to pick an account and time. An edit makes a new revision, so any earlier review of it no longer applies. |
| 3 | `新加 data-tour="pipeline-col-review"（fallback `section[aria-labelledby="col-review"]`）` | Needs approval | A review freezes the exact text, media, account and time. Someone who can approve confirms it in the Queue; until then nothing is scheduled. |
| 4 | `新加 data-tour="pipeline-col-queue"（現有 key 係 col-scheduled，改名後 col-queue）` | Queue | Waiting, publishing, uncertain and held are different things. Held means something changed after approval: cancel it and prepare a new review. Uncertain means the provider did not confirm; nothing is retried until it is reconciled. |
| 5 | `新加 data-tour="pipeline-col-published"（fallback `section[aria-labelledby="col-published"]`）` | Published | Only posts the provider confirmed appear here, with the receipt. A Fixture label means a test provider, not a real post. |
| 6 | `新加 data-tour="pipeline-needs-you"（NotificationStack wrapper；TourStep.when 由真 item 數決定，冇 item 就跳過）` | Needs you | Anything blocked is listed here with the reason. Open it to jump to the column. |

**Empty state 教咩**：空 board 教「五個階段」同「第一步喺 Ideas 寫一句」（冇 edit 權限就講由 editor 加）；每欄空句教「呢欄嘅嘢由邊個 action 產生」（Schedule… 產生 review、Queue 頁 approve 產生 job、provider 確認產生 published）。全部 general 用語，唔提任何行業或品牌。

## 5. Next steps（按次序）

1. **同平行 session 對齊：確認 board.ts／job-state.ts／features/onboarding 由邊個完成；之後只 stage by path（web/src/features/pipeline/、web/src/features/onboarding/tours.ts 內 Pipeline entry）**（effort S）  
   檔案：`web/src/features/pipeline/board.ts；web/src/features/pipeline/job-state.ts；web/src/features/onboarding/tours.ts`
2. **補 web types：SnapshotVariant.revisions（at?: string）/rejected/feedback/runId、SnapshotSource.createdAt、Review.createdAt、Job.approvedAt/nextAt/scheduleId/approvedBy；board.ts 改用共用 type；toEpoch 保留喺 board.ts 或移去 lib/time.ts**（effort S）  
   檔案：`web/src/lib/api/types.ts:71-142；web/src/features/pipeline/board.ts:19-66；web/src/lib/time.ts`
3. **Review deriveBoard：held tag = nextAction ?? events.at(-1).message；revision 冇 at 時排序 fallback；origin 加 ideas-candidate；boardInvariants 覆蓋 held/failed/canceled/stale/retracted/rejected**（effort M）  
   檔案：`web/src/features/pipeline/board.ts；web/src/features/pipeline/job-state.ts`
4. **加 test runner 前先問 James（改 package.json 會同其他 session 衝突）；同意後加 vitest + board.test.ts**（effort M）  
   檔案：`web/package.json；web/src/features/pipeline/board.test.ts（新）`
5. **重寫 PipelineView：用 deriveBoard、拆 pipeline-card.tsx、jobBadge、權限 gating（edit／edit+approve／approve／viewer／sample）、loading skeleton、error Empty（isError + refetch）、board／per-column empty、entrance 0.18s + stagger 30ms cap 4、刪 columnIndex 項、「Show N more」**（effort M）  
   檔案：`web/src/features/pipeline/pipeline-view.tsx；web/src/features/pipeline/pipeline-card.tsx（新）`
6. **Detail sheet：Draft／Review／Job／Source，revision history、events timeline、receipt、Fixture、item 移走 fallback、focus return**（effort M）  
   檔案：`web/src/features/pipeline/pipeline-card-sheet.tsx（新）；web/src/components/ui/sheet.tsx；web/src/components/application/post-preview/draft-preview.tsx、manifest-preview.tsx`
7. **Set aside dialog + Drafts 欄底 collapsible；Edit dialog 修 dirty（有 proposedUpdate 時同 proposedUpdate.text 比較）、改用 post-preview/limits.ts**（effort S）  
   檔案：`web/src/features/pipeline/set-aside-dialog.tsx（新）；web/src/features/pipeline/edit-draft-dialog.tsx:13,26；web/src/components/application/post-preview/limits.ts`
8. **Needs you stack（useChannels capability matrix）+ platform filter + 375px segment／1440px grid**（effort M）  
   檔案：`web/src/features/pipeline/pipeline-view.tsx；web/src/features/pipeline/needs-you.ts（新）`
9. **Pipeline 內 polling：唔改共用 useSnapshot 預設，喺 PipelineView 用 useQuery option 或 hooks 加可選參數；`refetchInterval: hasLiveJob ? 30_000 : false`、`refetchIntervalInBackground: false`；同一 job 換組用 layoutId**（effort S）  
   檔案：`web/src/lib/api/hooks.ts:39-42；web/src/features/pipeline/pipeline-view.tsx`
10. **Page tour：加六個 data-tour attribute；喺 PAGE_TOURS 加 route '/app/pipeline' tour（copy general、when 讀 TourCtx 真數）**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:156；web/src/features/pipeline/pipeline-view.tsx`
11. **Queue 頁改 import job-state.ts，移除 queue-view 私有 copy（held 喺 Queue 都用 warning badge）**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx:32-35,47-51,74-80；web/src/features/pipeline/job-state.ts`
12. **後端 P2：/api/catalog 加 limits（由 contracts.LIMITS 投影），Catalog type 加 limits**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:283-285；web/src/lib/api/types.ts:10-17；web/src/lib/api/client.ts`
13. **Language badge 落地後替換語言字串；更新 docs/postriff-motion-system.md §1 Pipeline 行同 §6 待辦**（effort S）  
   檔案：`web/src/features/pipeline/pipeline-view.tsx；web/src/features/pipeline/edit-draft-dialog.tsx:53；docs/postriff-motion-system.md`

## Risks

- 平行 session 已喺 web/src/features/pipeline/（board.ts、job-state.ts）同 web/src/features/onboarding/ 動工（untracked）：唔好寫第二份 deriveBoard 或第二個 tour runner；commit 只 stage by path。
- Timestamp 混合：domain.py 嘅 revisions.at／source.createdAt 係 ISO，phase2 store 嘅 events.at／review createdAt／approvedAt 係 epoch 秒，hosted Ideas candidate revision 冇 at。直接塞 relativeTime 會顯示錯時間；toEpoch 要有 test，缺就唔顯示。
- held 語意：ideas.py:512 將 held 當 committed；p2_variant_feedback 被非 canceled/failed job 擋（store.py:331）；held job 仍計 daily limit（store.py:298）。UI 流程要係「Cancel held job → draft 返 Drafts → Schedule…」。
- Schedule… 係多步 mutation（accept_update → p2_variant_review → p2_review）：權限唔啱會留低半套變更，所以 gating 必須係 edit AND approve。
- Snapshot polling：useSnapshot 係共用 query，refetchInterval 要局限喺 Pipeline；API 重啟會清 dev DB，測試時要 re-seed。
- Reviews 只保留最後 20 個（store.py:286），舊 needs_review 會靜靜消失；欄 hint／info sidebar 要講明。
- Dev harness Threads 係 live provider：驗證 UI 時唔好 approve／schedule／cancel 真 job；Set aside 同 Edit 相對安全。
- web 冇 test runner：加 vitest 會改 package.json，先問 James。
- Language badge 未落地期間顯示 variant.language 原字串，誠實但唔精緻；唔可以退回 hard-code map。
- Sample workspace 所有 mutate 403（hosted.py:189），web 未有任何 sample 判斷；漏咗新用戶第一下就撞 error toast。
- Queue 欄改名同 /app/queue 頁同名：hint 要講清「approved jobs」，approval 仍喺 Queue 頁，避免混淆。

## 覆核記錄

- 改正：snapshot route hosted_app.py:457-458 → service.get → 改為 hosted_app.py:459-462、hosted.py:541-542
- 改正：channels route hosted_app.py:412-415 → oauth.py:169-178 customer_view → hosted_app.py:412-414 → oauth.py:191 channels() → channels.py customer_view
- 改正：actions endpoint hosted_app.py:473-482；hosted.py:138-146 mutate；hosted.py:174-210；sample 403 hosted.py:178；needsReview hosted.py:202-205 → 更新所有 hosted.py／hosted_app.py 行號
- 改正：/api/catalog 喺 hosted_app.py:293-295 → hosted_app.py:283-285
- 改正：held job 有 nextAction，可以做 card tag → held tag = job.nextAction ?? events.at(-1).message
- 改正：revisions[{revision,text,origin,at}]（domain.py:386,400）可以用 revisions.at(-1).at 排序同顯示 edited/written → at 可缺；排序 fallback 到 provenance/陣列次序；origin map 加 ideas-candidate→Written；冇 at 就唔顯示時間
- 改正：lib/time.ts:6 relativeTime 只接 epoch → lib/time.ts:35
- 改正：signals_epoch 喺 learning_signals.py:26-31 → store.py:26
- 改正：Learning signals 由 state diff 推導，evidence hosted.py:97-101 → exists true 保留，evidence 改正
- 改正：Schedule… 應該用 approve 權限 gate → Schedule… 要 edit AND approve；只得其中一樣就顯示對應提示
- 改正：web/src 搜 data-tour/Tour 0 hit，要新建 components/onboarding/tour.tsx → 喺 PAGE_TOURS 加 route '/app/pipeline' 嘅 page tour，唔好另起 runner
- 改正：board.ts／job-state.ts 未存在（next_steps 標「新」，job-state 放 features/queue/） → next_steps 改為「review 及完成平行 session 嘅 board.ts/job-state.ts」，先同對方對齊
- 改正：Platform limits 只喺 edit-draft-dialog.tsx:13 hard-code 三個平台 → Edit dialog 先重用 post-preview/limits.ts；API catalog limits 係 P2
- 改正：`/app/ideas?new=1` 會 focus composer（home-view.tsx:96） → 引用 ideas-view.tsx:99
- 改正：motion/tabs.tsx 有 segment／pill variant；transitions.dev #16 屬 motion Tabs → reuse 寫 motion/tabs.tsx（layoutId indicator），唔好標 #16
- 改正：Card moving between columns 用 layoutId={kind+id} 由 Schedule… 滑去 Needs approval → 只喺 poll／refetch 期間同一 object 換欄（job 由 waiting→publishing→verified）先用 layoutId=job.id；跨 kind 用 content key 或者唔做
- 改正：Needs you：`phase2.channels[].displayState !== 'Ready for posting'` 計 channels not ready → 用 useChannels capabilities.publish.level + evidence；query 失敗時唔顯示呢項（唔當 0）
- 違反原則（已改）：Capability honesty：Needs you 用 phase2.channels displayState（'Ready for posting'）做 blended readiness，要改讀 useChannels 嘅 per-capability matrix。
- 違反原則（已改）：Motion 真數據：『Card moving between columns』聲稱 reads_real_data 但 Schedule… 成功即跳去 /app/queue，而且跨 kind layoutId 唔會 match，係唔會發生嘅動畫；Page enter 標 reads_real_data true 唔準（純裝飾）。
- 違反原則（已改）：Motion 時長：建議嘅 entrance（stagger 30ms cap 8 → delay 240ms + duration 240ms）最後一張卡 480ms 先完成，未符合『總長 ≤ 300ms』；要收窄到 delay+duration ≤ 300ms。
- 違反原則（已改）：Reuse before inventing：提議新建 components/onboarding/tour.tsx，但 web/src/features/onboarding/（tours.ts PAGE_TOURS、tour-overlay、store）已存在；job-state/board 亦已由平行 session 開始，spec 當係全新檔案。
- 違反原則（已改）：權限誠實：Schedule… 只 gate approve 會令 approver（冇 edit）撞 403，editor 冇 can_publish 會留低半套 mutation（p2_variant_review 成功、p2_review 403）。
- 違反原則（已改）：Honesty：held card tag 用 job.nextAction，但 held 路徑冇寫 nextAction，會顯示空白／錯誤原因。
- 補上遺漏：平行 session 已經喺 web/src/features/pipeline/board.ts、job-state.ts、web/src/features/onboarding/ 動工（untracked），spec 要改為對齊／review 而唔係從零寫。
- 補上遺漏：RBAC 矩陣：nav-config Pipeline item 冇 access key（viewer／approver 都見到）；viewer 全 read-only；approver 冇 edit（唔可 Edit／Set aside／Schedule 嘅 step 1-2）；admin 有 edit 冇 approve；Schedule 要 edit+approve。
- 補上遺漏：Web 完全冇 sample workspace 處理（grep workspace.sample 0 hit），隱藏 mutate 要新寫。
- 補上遺漏：Edit dialog 應重用 web/src/components/application/post-preview/limits.ts（有出處、多渠道、grapheme 計法），而唔係等 API。
- 補上遺漏：Hosted Ideas candidate 嘅 revisions 冇 `at`、origin 'ideas-candidate'（ideas.py:521）。
- 補上遺漏：held job 冇 nextAction；原因要讀 events.at(-1).message。held job 仍計入 daily limit（store.py:298），Prepare again 前要先 Cancel。
- 補上遺漏：useChannels 失敗／loading 時 capability 相關 UI 要顯示 unavailable 而唔係隱藏成 0。
- 補上遺漏：i18n：app 冇 i18n framework，UI copy 英文；時間經 lib/time.ts setTimeDefaults 用用戶 locale/timeZone；語言名經 language-badge（native name + flag）。
- 補上遺漏：Polling 要 refetchIntervalInBackground:false，且只喺 Pipeline 用 option，唔改共用 useSnapshot 預設。
- 補上遺漏：Mobile：長按 context menu 同垂直 scroll 衝突；5 個 segment tab 喺 375px 可能爆闊，要可橫掃或縮短 label。
- 補上遺漏：A11y：卡片要 keyboard 可開 sheet；計數變化唔好用 aria-live 狂讀；sheet focus return。
- 補上遺漏：Mutation 409（Workspace changed; reload.）後要 invalidate snapshot 再提示，而唔係淨係 toast。
