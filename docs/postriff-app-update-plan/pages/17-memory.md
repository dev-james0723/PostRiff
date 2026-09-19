# 17 · Memory

> Route：`/app/workspace/memory` · Sidebar：Workspace · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**已經有嘅（code 為準，working tree 2026-09-16）**

Route 同入口：`web/src/app/app/workspace/memory/page.tsx:1-8` render `<MemoryView />`；sidebar `web/src/config/nav-config.ts:131-137`（Workspace group，icon `page`，access `permission: 'edit'`）。注意 `web/src/lib/auth/access.tsx:6-7, 38-39` 仲係 Phase A stub（所有人當 owner），nav gating 未真；頁內 owner-only 靠 `snapshot.data.membership.role === 'owner'`（memory-view.tsx:72、learning-panel.tsx:38）同後端 `permissions.py:32-36`。Home 有真數 pill「Memory · N files」「PostRiff noticed N · review」（`web/src/features/agent/home-view.tsx:77-81, 259-264`）；activity strip「Memory · N learned rules used」（`activity-strip.tsx:86`）。

Page shell `web/src/features/memory/memory-view.tsx`（未 commit WIP）：
- Header：infobar L21-28，action「Export package」L188-192 → `api.exportProfile`（`client.ts:144` → `GET /profile-export`）；catch 吞咗 server message（L178-179）。
- 三條 strip L194-198：`CloudSharing` L66-108（egress 缺席 L74 return null）、`WebResearch` L110-165（research 缺席 L118 return null）、`LearningPanel`。
- Grid `md:grid-cols-[18rem_1fr]` L199：FileTree 容器 L200 **已有 `data-tour='memory-files'`**；FileTree L210-225；viewer header L230-245 對**全部五個檔**掛「Read every draft」badge（L236）、左欄寫「Core files · read every turn」（L201）——**唔誠實**：`src/postriff_phase2/memory.py:21` `PROMPT_FILES = (BOUNDARIES.md, IDENTITY.md, VOICE.md)`，L137「AGENT.md is for people; BRAND.md duplicates IDENTITY.md」，`projection` L151-158 local 同 cloud route 都只收呢三個；cloud 再受 `MAX_MEMORY_BYTES = 16_000`（`model_runtime.py:32, 164`）截尾。`egress_summary` 已回 `sharedFiles`（memory.py:165）但 UI 冇用。
- `motion.pre` blur swap 0.18s，exit 同 enter 一樣長（L253-264）；footer L266。
- Loading Skeleton L202-208、L246-251。**冇 error state**；error 時 `!file` 令 viewer Skeleton 永遠 pulse（L246）＝假 loading。

Learned preferences `learning-panel.tsx`：`useMemoryProposals()` / `useMemory()`（`hooks.ts:133, 139`）；Learn Switch L128；badges L120-121；子 switch cloudExtraction L131-145、teamEdits L147-158；stats L162-169；pending L171-178；listed Pause/Resume/Retire L184-209（`updateLearnedItem` client.ts:150-151）；retired 只計數 L213；reset inline 兩步 L215-229；空狀態 L180-182。冇 error state（L160）。`recent` 只喺 `proposal-card.tsx:41` 用。

ProposalCard `proposal-card.tsx:36-133`：decide client.ts:148-149；四個按鈕 L107-120；performance L83-88；evidence 只係「Seen in N of your edits.」L62-63；`expiresAt`（types.ts:378）冇顯示。

Types `web/src/lib/api/types.ts`：MemoryFile 323、MemoryEgress 332、LearnedItem 343、LearningSummary 361、MemoryProposal 372、PerformanceNote 395、MemoryProposals 405、MemoryBinding 415、ResearchEgress 423；speaker.activeRevision 164。

Backend（`src/postriff_phase2/hosted_app.py`）：
- `GET /memory` L467-468 → `ideas.memory_files`（ideas.py:122-127）：files（render_files memory.py:76）、egress（egress_summary L161-166，含 sharedFiles / withheldBoundaries）、research（research.py:94-98；非 hosted 時 web=enabled()，本機預設 On）、learning（learning.py:355-358，enabled 預設 True）+ pendingProposals。
- `GET /memory/proposals` L450-451 → learning_service.py:240-246（stats：learning_extract.py:313，WINDOW_DAYS 90）。
- `POST …/decide` L452-454 → L256-311（owner）。
- `PATCH /memory/versions/{id}` L455-457 → L313-332；冇傳 reason，雖然 `learning.set_status(..., reason=None)`（learning.py:331）同 `retire(reason="undone")`（L272）支援。
- `POST /actions` L477 → `hosted.py:152-160`；audit 只有 memory.egress_decided / research.egress_decided；learning_settings / learning_reset 冇 audit。
- `GET /profile-export` L491 → `hosted.py:979-997`，L983 要 `packageSchema`；web voice setup（voice-setup.tsx:72, 81 → domain.py:331 profile_decide）唔設，只有 profiles.py:375 設 ⇒ web 用戶撳 Export 會 400；內容係 profiles.py:398-405 fields 版本，唔係頁面五個檔。Brand（brand-view.tsx:31-44）同 Privacy（privacy-view.tsx:89-128）同一個問題。
- `GET /export` L487 → hosted.py:966-970，含 `learning_service.export_files`（L82-88：events.jsonl / proposals.json / versions.json；後兩者係 SELECT *，含 decided_by / confirmed_by uuid）。
- Cron `/api/cron/worker`（L326-336，vercel.json 每分鐘）→ learning.sweep → extract：workspaces_due min 5 unconsumed 或 1 日（L162）、每日 1 個自動 proposal（L432）、MAX_PENDING 3（learning.py:32）、30 日過期（L35）、dismiss 靜 90 日（learning_service.py:94）。`pr_learning_events` 冇 consumed_at（migration 010:4-18；mark_consumed L182-184 唔寫時間）⇒ 而家冇「幾時睇過」嘅真數。
- `HostedLearning.events()` L337-339 有 method 冇 route；`self.failures` L226 process-wide。

Onboarding：`web/src/features/onboarding/`（tours.ts、store.ts、tour-overlay.tsx、help-menu.tsx、use-tour-context.ts；**untracked，另一 session WIP**）。WELCOME_TOUR memory stop（tours.ts:128-135）同 PAGE_TOURS `memory-tips`（L311-323，一步，target `[data-tour="memory-files"]`）已存在；進度 localStorage `postriff-onboarding`（store.ts:40）有 try/catch；TourCtx 有 hasVoice / canEdit。**memory-tips 文案「with the evidence behind them」超出現有能力**（evidence drill-down 未做）。

Tests：tests/phase2/postgres_{memory_proposals,learning_decide,learning_events,learning_extract,memory_egress}.py；web 只有 oxlint / tsc。

**缺口**：(1) 兩個 query 冇 error / unavailable，viewer error 時假 pulse；(2)「Read every draft」同實際 prompt 唔符；(3) Export 會 400 而且內容唔對；(4) recent / expiresAt 有數唔顯示；(5) evidence 冇 drill-down，tour 文案超前；(6) 冇學習活動訊號（亦冇時間欄支援）；(7) 冇跨 run 嘅「draft 實際收到乜」；(8) learning settings / reset 冇 audit；(9) reset 唔係 hold / dialog；(10) 三條 strip 令檔案落第二屏（未實測驗證）。

## 1. Design specification（最新版）

**目的**：Memory 頁係控制面，答三條問題：① writing route 寫 draft 前**實際收到乜**（由 `egress.sharedFiles` 決定嗰幾個檔，而家係 BOUNDARIES / IDENTITY / VOICE；AGENT.md、BRAND.md 標明「For you to read」）；② **邊個可以讀**（本機 route 永遠讀得；cloud model、web research、learning 各自一個 owner 決定，有 decided line）；③ **PostRiff 學咗乜、點學、你決定咗乜**。每個數字狀態由 `GET /memory`、`GET /memory/proposals`（同之後嘅 activity / evidence / reads）讀；缺席寫 Unavailable，唔變 0、Off 或空。

**Layout**：沿用 `PageContainer`（title、description、infobar、header action）。Header action「Export memory files」（新 endpoint）。

**Region A · Access card（`data-tour="memory-access"`）**：「Who reads these files」，三行：Cloud model access / Web research / Learning。每行：標題 + `AnimatedBadge`（status 由真值：Shared/On → success、Not shared/Off → neutral、Unavailable → warning）+ 描述 + decided line（現有 `useDecidedLine`）+ `Switch`。Learning 行子 switch（cloud extraction、teammates' edits）收入 `AgentDisclosure`。非 owner：switch disabled +「Only an owner can change this.」。

**Region B · Files（現有 grid）**：FileTree（`data-tour="memory-files"`，已有）分兩組：「Given to writing routes」（`egress.sharedFiles`）同「For you to read」（其餘）；badge 由 API 決定，移除全部五個檔嘅「Read every draft」。Viewer（`data-tour="memory-viewer"`）：檔名、source、purpose、Edit in Brand；sharedFiles 內嘅檔加一行「Cloud routes receive at most 16,000 bytes of these files combined」（數字要由 API 帶返，唔 hardcode；未帶之前唔顯示）。未有 voice（`speaker.activeRevision == null`）→ viewer header「Set up your voice」→ `/app/workspace/brand`。

**Region C · Learned preferences（`data-tour="memory-learning"`）**：標題 + style rev badge + 活動一行（有 activity endpoint 先出）。beUI `Tabs` segment：Waiting (N) / Active (N) / Decided (N)，N 用 `DigitSwap`。Waiting：ProposalCard（≤ MAX_PENDING）+ Expires in N days + Why?（evidence endpoint 落地先出）；Active：active / paused + Pause / Resume / Retire；Decided：`recent` + retired items。底部 stats 一行 + Forget（`HoldActionButton`，預設 1600ms 同 Queue 一致）。

**Responsive**：375px 單欄；Access 行 switch 落標題下（現有 `sm:flex-row`）；FileTree 保留（得 5 行，唔換 Select，免失 tree keyboard 導航）；Tabs label 用短字（Waiting / Active / Decided）三粒等寬；viewer `pre` `whitespace-pre-wrap overflow-x-auto`，頁面唔橫 scroll。768px Region B 兩欄。1440px 同 768，viewer 內容 `max-w-prose`。

**Primary action**：有 pending proposal 時「Remember this」；未有 voice 時「Set up your voice」；其餘冇 primary。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header | 命名頁面、infobar、匯出 | title「Memory」；description 改「Plain Markdown files behind every draft. You own them; the agent can only propose changes.」（唔再講「reads before every draft」概括五個檔）；infobar 第一段同步改：只講 sharedFiles 交俾 writing route；action「Export memory files」（`data-tour="memory-export"`）→ 新 `GET /memory/export`。 | 匯出中按鈕 disabled + `ActionSwapIcon`；成功 `useFlash` 1800ms 剔號；失敗 toast 用 `ApiError.message`。 |
| Who reads these files（Access card） | 三個 owner 決定同真實狀態一眼睇晒 | Cloud model access（`egress.cloud`、`withheldBoundaries`、decided line）；Web research（`research.web / hosted / enabled`，本機或 deployment 關咗 switch disabled + 現有 note）；Learning（`learning.enabled`；子 switch cloudExtraction 需 `egress.cloud`、teamEdits）。 | `memory.isError` → 一句「Access settings are unavailable right now.」+ Retry（`refetch`），唔出 switch；`egress` 或 `research` 缺席 → 該行 badge「Unavailable」（唔 return null）；`act.isPending` → switch disabled；非 owner → disabled + note。 |
| Files | 顯示 writing route 實際收到嘅原文，同俾人睇嘅參考檔分開 | 兩組檔（sharedFiles vs 其餘）；viewer `body` / `source` / `purpose` / `editHref`；footer 改：「Workspace only. The files marked ‘Given to writing routes’ go to routes on your machine, and to the cloud model only when access is allowed above.」（export 包唔包，等 export endpoint 落地先寫）。 | loading Skeleton；`memory.isError` → 左欄「Memory files are unavailable right now.」+ Retry，viewer 顯示同一句而唔係 Skeleton；未有 voice → CTA；BOUNDARIES 「Not recorded yet」source badge（現有）。 |
| Learned preferences | 決定 proposals、管理 learned items、睇返決定歷史 | 活動一行（有 activity endpoint 先出）；Tabs Waiting / Active / Decided；stats 一行（現有文案，<5 approvals 標 small sample）；Forget（hold）。ProposalCard：scope、source、statement、why、performance、Expires in N days（`expiresAt` null 就唔出）、Why?（evidence endpoint 之後：每條 event kind、日期、scope、feature 前後計數，variant 仍在先有 Open draft）。 | `proposals.isLoading` Skeleton；`proposals.isError` → 「Learned preferences are unavailable right now.」+ Retry，唔出 Learn switch、唔出 0；三個 tab 空 → 空狀態；非 owner →「Only a workspace owner can decide this.」；decide 成功 → 卡由 Waiting 去 Decided。 |

- **Empty state**：未有 voice、未學到嘢：Access card 照出三行**真值**（hosted 通常係 Cloud Not shared、Web research Off、Learning On——讀 API，唔寫死）；Files 照出真 render 檔，VOICE.md 顯示現有「No active voice profile yet…」+「Set up your voice」CTA；Learned panel：「Nothing learned yet. Tell the agent how to write — for example “from now on, no hashtags on Instagram” — or keep editing drafts. Nothing changes until an owner accepts a suggestion.」門檻（5 個 edit / 1 日 / 每日 1 個 / 最多 3 個）要等 activity endpoint 帶返 `thresholds` 先加入句子，唔 hardcode。冇 fake 卡、冇示範 proposal。
- **Loading**：PageContainer 唔用 `isLoading`（header 即出）；Access card 三條 `Skeleton h-16`；FileTree 三條 `h-9`；viewer 三條 line；Learned panel 一條 `h-16`。Skeleton 只喺 `isLoading` 時出，error 時一定換成 unavailable（修正而家 `!file` 永遠 pulse 嘅 bug）。Mutation 中只 disable 相關控件，唔出「Learning…」「Syncing…」字眼。
- **Error**：Region 獨立 fail：`useMemory` error → Access card 同 Files 各自「… unavailable right now.」+ Retry；`useMemoryProposals` error → Learned panel 一句 + Retry；activity / evidence / reads error → 各自一行「unavailable」。Mutation error → toast `ApiError.message`；409「Workspace changed; reload.」（hosted.py:138）→ toast 加「Reload」action，invalidate `snapshot`、`memory`、`memoryProposals`（同之後新 key）。Export 失敗顯示 server message。任何情況 unavailable 唔顯示成 0、Off 或空列表。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 頁面進入 | route change | 整頁浮入（現有） | web/src/app/app/template.tsx `.t-page-enter` | 否（純裝飾） |
| Viewer 內容 | 揀另一個檔 | 新內容 blur→清 0.18s；exit 縮到 0.12s（收快過開）；reduced motion duration 0 | 現有 `motion.pre` + `EASE_OUT`（memory-view.tsx:253-264），只改 exit transition | 是 |
| Access card 狀態 badge | egress.cloud / research.web / learning.enabled 變 | 文字翻轉到新狀態，色跟真值；缺席時 warning「Unavailable」 | web/src/components/motion/animated-badge.tsx（status, contentKey） | 是 |
| Switch | owner 撥動 | thumb spring（現有） | web/src/components/motion/switch.tsx | 是 |
| Tabs Waiting / Active / Decided | 切換 tab | segment pill 滑動；panel 內容 opacity enter 0.15s / exit 0.1s | web/src/components/motion/tabs.tsx（segment，variant-card.tsx:41 已用） | 否（純裝飾） |
| Tab 計數 | pending / active / recent 數目變 | 數字逐位滾動；query error 時唔 render 數字 | web/src/components/motion/digit-swap.tsx | 是 |
| Proposal 卡列表 | 首次載入 / 新 proposal | opacity + y 4px，stagger 40ms，≤3 張（≤120ms）；reduced motion duration 0 | motion/react variants，跟 activity-strip.tsx 模式 | 是 |
| Proposal 卡決定後 | decide success | 卡 exit opacity/transform 0.15s；Decided 計數 DigitSwap | AnimatePresence + AnimatedBadge | 是 |
| Why? evidence disclosure | 撳 Why?（evidence endpoint 落地後） | 展開 0.2s、收 0.15s | web/src/components/agents/agent-disclosure.tsx | 是 |
| Forget what you learned | 長按 | hold 填滿（預設 1600ms）先觸發 learning_reset；放手取消 | web/src/components/motion/hold-action-button.tsx（queue-view.tsx:361 已用） | 否（純裝飾） |
| Export 按鈕 | 撳 Export memory files | icon ↔ spinner，完成 1800ms 剔號 | web/src/components/motion/action-swap.tsx ActionSwapIcon + web/src/hooks/use-flash.ts | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /memory：files + egress(含 sharedFiles) + research + learning(+pendingProposals) | api | 有 | hosted_app.py:467-468 → ideas.py:122-127；memory.py:76 render_files、161-166 egress_summary；research.py:94-98 | S |
| 2 | GET /memory/proposals | api | 有 | hosted_app.py:450-451 → learning_service.py:240-246；learning_extract.py:313 | S |
| 3 | POST /memory/proposals/{id}/decide（owner） | api | 有 | hosted_app.py:452-454 → learning_service.py:256-311（requirement owner） | S |
| 4 | PATCH /memory/versions/{id} | api | 有 | hosted_app.py:455-457 → learning_service.py:313-332 → learning.py:331-345 | S |
| 5 | PATCH /memory/versions/{id} 傳 reason 'undone' | api | 冇 | learning_service.py:320 冇傳 reason；learning.set_status(reason) L331、retire(reason='undone') L272 已支援 | S |
| 6 | POST /actions：memory_egress、research_egress、learning_settings、learning_reset（owner） | api | 有 | hosted_app.py:477 → hosted.py:152-160；permissions.py:32-36 | S |
| 7 | Audit learning.settings_changed / learning.reset（content-free） | backend | 冇 | hosted.py:158-159 只為 memory_egress / research_egress 設 audit_event；audit() hosted.py:91 | S |
| 8 | GET /memory/export：zip sharedFiles + 其餘 rendered .md + learning/*（唔靠 packageSchema） | api | 冇 | profile-export hosted_app.py:491 → hosted.py:983 要 packageSchema；render_files memory.py:76、export_files learning_service.py:82-88 已有。要決定 RBAC：workspace export 係 read 級（hosted.py:966-968），proposals/versions JSON 含 decided_by uuid，考慮 strip actor 或限 owner | S |
| 9 | Viewer 用 egress.sharedFiles 分組、移除假「Read every draft」 | frontend | 冇 | memory-view.tsx:201, 236 對五個檔一律標 read every turn；memory.py:21, 137, 151-158 只交三個檔；types.ts:332 MemoryEgress 需確認有 sharedFiles 欄 | S |
| 10 | Cloud memory byte cap 由 API 帶返（例如 egress.maxCloudBytes） | api | 冇 | model_runtime.py:32 MAX_MEMORY_BYTES = 16_000 冇出現喺 egress_summary | S |
| 11 | Learning 時間欄：pr_learning_events.consumed_at 或 workspace-level lastExtractedAt（migration 011） | data | 冇 | migrations/postriff/010_preference_learning.sql:4-18 冇 consumed_at；mark_consumed learning_service.py:182-184 唔寫時間 | S |
| 12 | GET /memory/activity：{eventsWaiting, oldestWaitingAt, lastExtractedAt(需上項), automaticToday, thresholds:{minEvents, maxAgeHours, dailyProposals, maxPending}} | api | 冇 | workspaces_due learning_service.py:162；automatic_proposals_since L152；budget L432；MAX_PENDING learning.py:32；self.failures L226 process-wide，唔可以當 per-workspace 數 | M |
| 13 | GET /memory/proposals/{id}/evidence | api | 冇 | proposal body evidence（learning_service.py:208；types.ts:388）；event features before/after 計數（learning_signals.py:125），冇原文 | M |
| 14 | GET /memory/reads：最近 20 個 run 嘅 memoryBindings | api | 冇 | ideas.py:263 usage.memoryBindings；destinations 喺 summary（ideas.py:267）唔喺 usage；pr_agent_runs.usage 005:53 | M |
| 15 | Frontend hooks / client / types for 以上 | frontend | 冇 | hooks.ts:23-24, 133-142；client.ts:144-151 | S |
| 16 | Error / unavailable states（useMemory、useMemoryProposals、egress/research 缺席、viewer 假 pulse） | frontend | 冇 | memory-view.tsx:74, 118, 246；learning-panel.tsx:160 | S |
| 17 | Render recent 同 expiresAt | frontend | 冇 | proposal-card.tsx:41；types.ts:378 | S |
| 18 | Reset 用 HoldActionButton | frontend | 冇 | learning-panel.tsx:215-229；hold-action-button.tsx:42, 49（預設 1600ms） | S |
| 19 | beUI Tabs(segment)、DigitSwap、AnimatedBadge、AgentDisclosure、ActionSwapIcon、HoldActionButton、useFlash | frontend | 有 | motion/tabs.tsx:18、digit-swap.tsx:48、animated-badge.tsx:109、action-swap.tsx:251、hold-action-button.tsx:42；agents/agent-disclosure.tsx:14；hooks/use-flash.ts:9 | S |
| 20 | Snapshot speaker.activeRevision（Set up your voice 條件） | data | 有 | types.ts:164；use-tour-context.ts:20 hasVoice 已用 | S |
| 21 | Tour infra（registry、overlay、help menu replay、localStorage 進度）+ memory-tips tour | frontend | 有 | web/src/features/onboarding/tours.ts:128-135, 311-323；store.ts:40；memory-view.tsx:200 data-tour='memory-files'（untracked WIP，另一 session） | S |
| 22 | memory-tips 擴展步驟 + 新 anchors（memory-access、memory-viewer、memory-learning、memory-export） | frontend | 冇 | tours.ts:314-322 得一步；grep 其餘 data-tour 喺 features/memory 零命中 | S |
| 23 | Sync to Claude Code（companion） | infra | 冇 | companion transport 未做；infobar 第三段（memory-view.tsx:26）已提「exporting and syncing」——sync 未有之前要改文案 | L |
| 24 | PG tests 覆蓋 decide / versions / egress / extract | backend | 有 | tests/phase2/postgres_{memory_proposals,learning_decide,learning_events,learning_extract,memory_egress}.py | S |

## 3. Features

### P0

- **Prompt 真相：Files 分「Given to writing routes」同「For you to read」，移除假 badge**：House rule 1 / 5。memory.py:21, 137 顯示 AGENT.md、BRAND.md 從來冇交俾 route，而家 UI 同 Home「Memory · 5 files」令人以為全部都入 prompt。API 已回 sharedFiles，改動細。
- **誠實狀態：每個 region unavailable + Retry、修 viewer 假 pulse、expiry、Decided tab**：House rule 1。egress / research 缺席時 strip 消失、error 時 Skeleton 永遠 pulse；recent 同 expiresAt 有真數冇顯示。
- **Export memory files（新 endpoint）**：而家 web 設定 voice 嘅人撳 Export 會 400（hosted.py:983），內容亦同頁面唔同。RBAC 同 actor uuid 要一齊定。
- **Learned preferences 三段 tabs + HoldActionButton reset**：冇決定歷史、冇 retired 列表；reset 係唯一不可逆動作（capture DELETE 三張表 learning_service.py:233-235），motion 規則 §5.5 要 dialog 或長按。

### P1

- **Access card 合併三個決定**：三條 strip 高度大，檔案落後；合併後首屏見到 access + 檔案樹。（768px 高度係 spec 作者觀察，實作時截圖驗證）
- **Audit learning_settings / learning_reset**：四個 owner 決定得兩個有 audit；reset 前要先落地。
- **Tour 文案修正 + memory-tips 擴展**：tours.ts:320 講「with the evidence behind them」超出現有能力；擴展現有 infra 而唔係另起一套。（depends on：onboarding WIP commit（另一 session））
- **Why? evidence disclosure**：每條規則睇到證據係差異化；event 只有 feature 計數，UI 只顯示計數差 + Open draft，唔承諾全文 diff。落地之後先恢復 tour 嘅 evidence 字眼。（depends on：GET /memory/proposals/{id}/evidence）
- **Learning activity 一行**：用戶分唔清係未夠 edit、每日上限定係 capture 失敗。「last looked」要新時間欄，唔可以用 event created_at 冒充。（depends on：consumed_at / lastExtractedAt migration + GET /memory/activity）

### P2

- **Recent reads**：每個 run 嘅 memoryBindings 過咗 conversation 就搵唔返；omitted 要如實顯示。（depends on：GET /memory/reads）
- **Undo（remembered 後）**：後端 retire(reason='undone') 已支援，只差 route 同 button；7 日窗口要後端 enforce，唔可以只靠 UI。（depends on：PATCH reason）
- **Sync to Claude Code**：companion 未做，唔擺唔 work 嘅 button；infobar 講 syncing 嘅字眼要先收細。（depends on：desktop companion transport）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明：「有幾個檔係 writing route 實際收到嘅，其餘係俾我睇嘅參考；邊個讀得由 owner 決定；PostRiff 學到嘅嘢先問，唔會靜靜改。」頁面用四樣教：① description 一句；② Access card 三個 badge 讀真值；③ FileTree 預選 VOICE.md，分組標題講明「Given to writing routes」；④ 擴展現有 `memory-tips` page tour（help menu 已可 replay，進度存 `postriff-onboarding`），唔另起 tour 系統。步驟文案一律講「an owner」，editor 睇都啱；`when: ctx.canEdit` 沿用。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="memory-files"]（已存在，memory-view.tsx:200）` | Files, not a black box | Your voice, identity and boundaries are plain files. The ones marked ‘Given to writing routes’ are what a draft is written from; the rest are here for you to read. |
| 2 | `[data-tour="memory-viewer"]（要加，viewer 卡 memory-view.tsx:230）` | Read the exact text | This is the text a writing route receives. Change it from Brand and the file re-renders. |
| 3 | `[data-tour="memory-access"]（要加，Access card；未重組前 fallback 到 CloudSharing strip）` | An owner decides who reads it | Writing on your own machine always reads these files. The cloud model reads them only after an owner allows it, and boundaries marked private never leave. |
| 4 | `[data-tour="memory-learning"]（要加，learning-panel.tsx:113 section）` | Suggestions, never silent changes | When you tell the agent how to write, or your edits show a pattern, PostRiff suggests a preference. Nothing changes until an owner accepts it, and it only shapes future drafts. |
| 5 | `[data-tour="memory-export"]（要加，header Export 按鈕；export endpoint 落地先加呢步）` | Take it with you | Export these files and your learned preferences as plain files at any time. |

**Empty state 教咩**：(1) 檔案係真嘅：VOICE.md 寫「No active voice profile yet」+「Set up your voice」CTA；(2) learning 點觸發：「tell the agent how to write」或「keep editing drafts」，門檻數字等 activity endpoint 帶返先顯示；(3) 私隱：Access card badge 讀真值（唔寫死全部 Off——learning 預設 On、本機 web research 預設 On）。文案通用，冇示範資料，冇 dev seed 內容。

## 5. Next steps（按次序）

1. **Frontend 誠實修正（細、即做）：Files 用 `memory.data.egress.sharedFiles` 分組，移除五個檔一律嘅「Read every draft」/「read every turn」；`memory.isError` → Access strips 同 Files 各出 unavailable + Retry，viewer error 唔再 Skeleton；egress / research 缺席 → badge「Unavailable」唔 return null；`proposals.isError` → panel 一句 + Retry；ProposalCard 加 Expires in N days；render `recent` 做 Decided 列表；exportPackage catch 顯示 `ApiError.message`；viewer exit 0.12s。先 `git diff HEAD -- web/src/features/memory`（未 commit WIP），stage by path。**（effort S）  
   檔案：`web/src/features/memory/memory-view.tsx:66-118, 175-266、web/src/features/memory/learning-panel.tsx:160-213、web/src/features/memory/proposal-card.tsx:62-73、web/src/lib/api/types.ts:332`
2. **Tour 文案同 anchors：同 onboarding session 協調後，改 tours.ts:320 memory-tips body（拎走「with the evidence behind them」），加 viewer / access / learning 步驟同 data-tour anchors；Export 步驟等 step 3。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:311-323、web/src/features/memory/memory-view.tsx、web/src/features/memory/learning-panel.tsx`
3. **Backend `GET /api/workspaces/{w}/memory/export` → `service.export_memory`：zip render_files 全部 .md（README 講明邊幾個交俾 route）+ `learning_service.export_files`（strip decided_by / confirmed_by 或者限 owner，先定 RBAC）；web `client.ts` 加 `exportMemory`，header 按鈕改用（`data-tour="memory-export"`），footer 加返「Included in the memory export」。PG test：唔需要 packageSchema、有 .md 同 learning 檔。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:487-492、src/postriff_phase2/hosted.py:966-997、src/postriff_phase2/memory.py:76、web/src/lib/api/client.ts:144、web/src/features/memory/memory-view.tsx:175-192, 266、tests/phase2/postgres_memory_egress.py`
4. **Backend audit：hosted.py mutate 為 `learning_settings` 加 `("learning.settings_changed", "", {changed keys → bool})`、`learning_reset` 加 `("learning.reset", "", {})`。PG test 驗 audit row。**（effort S）  
   檔案：`src/postriff_phase2/hosted.py:152-160、tests/phase2/postgres_learning_decide.py`
5. **Layout 重組：抽 `access-card.tsx`（AnimatedBadge + Switch + AgentDisclosure）；learned 部份用 Tabs segment（Waiting / Active / Decided，DigitSwap 計數）；reset 改 HoldActionButton（預設 1600ms）+ toast 講明 gone；未有 voice CTA；proposal stagger 40ms、reduced motion 0。`npm run typecheck && npm run lint`，light/dark × 375/768/1440 截圖（用自己 tab，唔撳任何決定按鈕）。**（effort M）  
   檔案：`web/src/features/memory/memory-view.tsx、web/src/features/memory/learning-panel.tsx、web/src/features/memory/access-card.tsx（新）、web/src/components/motion/{tabs,digit-swap,animated-badge,hold-action-button}.tsx（只引用）`
6. **Learning activity：migration 011 加 `pr_learning_events.consumed_at`（mark_consumed 寫 now）或 state `learning.lastExtractedAt`；`learning_service.activity()` 回 eventsWaiting、oldestWaitingAt、lastExtractedAt、automaticToday、thresholds（由 workspaces_due 預設同 MAX_PENDING 取，唔喺 web hardcode）；route memory block 加 `activity`；web hook + 一行文案（缺席寫 unavailable）+ 空狀態用 thresholds。唔顯示 per-workspace failure 數。**（effort M）  
   檔案：`migrations/postriff/011_*.sql（新）、src/postriff_phase2/learning_service.py:152-184、src/postriff_phase2/hosted_app.py:447-457、web/src/lib/api/{client,hooks,types}.ts、tests/phase2/postgres_learning_events.py`
7. **Evidence endpoint `GET /memory/proposals/{id}/evidence`：由 body.evidence eventId 讀 pr_learning_events kind / created_at / scope / features before-after；variant 仍在附 Open draft link。Web：Why? AgentDisclosure lazy fetch；language 名跟 per-channel locale 顯示。落地後 tour 先可以講 evidence。**（effort M）  
   檔案：`src/postriff_phase2/learning_service.py:187-220、src/postriff_phase2/hosted_app.py:447-457、web/src/features/memory/proposal-card.tsx:62-63、web/src/lib/api/{client,hooks,types}.ts、tests/phase2/postgres_memory_proposals.py`
8. **Recent reads `GET /memory/reads`：pr_agent_runs 最近 20 個有 usage.memoryBindings 嘅 run（destinations 由 summary 讀）；Files region 底 disclosure，omitted 如實標「left out」；空寫「No drafts written yet.」。**（effort M）  
   檔案：`src/postriff_phase2/ideas.py:263-267、src/postriff_phase2/hosted_app.py、web/src/features/memory/memory-view.tsx、web/src/lib/api/{client,hooks,types}.ts`
9. **Undo：PATCH body 接受 reason 'undone'（只配 status retired，後端檢查 remembered 時間窗）→ set_status(reason)；Active tab 對合資格 item 顯示 Undo。**（effort S）  
   檔案：`src/postriff_phase2/learning_service.py:313-332、src/postriff_phase2/hosted_app.py:455-457、web/src/lib/api/client.ts:150-151、tests/phase2/postgres_learning_decide.py`
10. **Sync to Claude Code：companion transport 落地前唔加 button，並將 infobar 第三段（memory-view.tsx:26）「syncing」字眼改為只講 export；落地後先加 header action 顯示真 lastSyncedAt。**（effort L）  
   檔案：`web/src/features/memory/memory-view.tsx:21-28、desktop/（之後）`

## Risks

- Parallel sessions：memory-view.tsx 同整個 web/src/features/onboarding/ 係未 commit WIP（git status M / ??）；實作前 diff，commit stage by path，tour 改動要同 onboarding session 協調。
- Dev harness API 可能舊過 code（docs/postriff-motion-system.md §6）；重開 postriff-api 會清 dev DB 要 re-seed；:3100 harness 有 live Threads，驗證唔撳 approve / schedule / send / decide。
- access.tsx 係 stub（全部當 owner）：nav 同 TourCtx.canEdit 暫時對所有人為真；owner-only 控件一定要靠 snapshot membership + 後端 permissions，唔好靠 access.tsx。
- activity「last looked」冇時間欄就冇真數；`HostedLearning.failures` process-wide，最多顯示 deployment-level boolean。
- Evidence 只有計數冇原文；variant 被刪就冇 link。
- Export RBAC：learning proposals/versions JSON 含 decided_by / confirmed_by uuid；workspace export 係 read 級，新 export 要決定 strip 定限 owner。
- Brand / Privacy 頁仍用 profile-export（brand-view.tsx:31-44、privacy-view.tsx:89-128），同一個 400 bug 要另外處理。
- Dev seed IDENTITY.md 有創辦人自己品牌內容：tour、截圖、fixture、空狀態例子一律用通用場景。
- learning_reset 不可逆（learning_service.py:233-235）：audit（step 4）要先落地；HoldActionButton 之外 toast 講明 gone。
- 409 之後：useAct 只 set snapshot + invalidate usage / channels（hooks.ts:150-162），頁面要自己 invalidate memory / memoryProposals 同新 key。
- Cloud 16,000 bytes 截尾（model_runtime.py:164）：VOICE.md learned section 可能被截，reads 嘅 omitted 同 viewer 提示要如實。
- i18n：UI copy 暫時英文，冇 i18n library；evidence / reads 嘅語言名跟 worldwide-languages per-channel locale，唔 hardcode 繁體中文。

## 覆核記錄

- 改正：RBAC gating 由 web/src/lib/auth/access.ts 決定 → status_now 寫明 nav gating 仲係 stub，頁內 owner-only 由 snapshot membership + 後端 permissions.py 保證
- 改正：api.exportProfile 喺 client.ts:141 → 更新行號 client.ts:144-151
- 改正：types.ts 行號 321-327 MemoryFile … 421-430 ResearchEgress → 全部 +2 左右，已喺 corrected_spec 更新
- 改正：hosted_app.py 路由行號：/memory L462-463、proposals L445-446、decide L447-449、versions L450-452、actions L472-481、export L482-485、profile-export L486-489 → 更新行號
- 改正：五個檔（AGENT/IDENTITY/VOICE/BOUNDARIES/BRAND）就係 agent 每篇 draft 讀嘅全部，viewer 顯示嘅同 prompt 一模一樣 → Files region 按 egress.sharedFiles / PROMPT_FILES 分兩組：『Given to writing routes』(3) 同『For you to read』(AGENT.md、BRAND.md)，badge 讀 API 值；cloud 另受 MAX_MEMORY_BYTES 16,000（model_runtime.py:32, 164）截尾
- 改正：`grep data-tour / useTour` 喺 web/src 零命中，冇 onboarding tour infra → 唔好起新 memory-tour.tsx / Popover / 新 localStorage key；擴展 tours.ts 'memory-tips' 嘅 steps，加 data-tour anchors
- 改正：HoldActionButton 長按 1.2s → 沿用預設 1600ms（同 Queue 一致），唔另訂 1.2s
- 改正：GET /memory/activity 可以用 `lastExtractedAt: max(created_at) where consumed_by is not null` → 要新增 consumed_at 欄（migration 011）或者喺 extract 寫一個 workspace-level lastExtractedAt；未有之前只顯示 eventsWaiting 同 due 條件，唔顯示「last looked」
- 改正：空狀態 Access card 三個 badge 全部顯示 Not shared / Off（預設乜都唔出去） → 空狀態同 tour 文案讀真值，唔寫死「全部 Off」
- 違反原則（已改）：House rule 1 + 5（誠實 / capability honesty）：spec 將「五個檔 = agent 每篇 draft 讀嘅全部、同 prompt 一模一樣」寫入 purpose、tour step 1-2 同 onboarding；code 顯示 writing route 只收 PROMPT_FILES（BOUNDARIES / IDENTITY / VOICE，memory.py:21, 137, 151-158），cloud 仲要受 MAX_MEMORY_BYTES 截尾。現有「Read every draft」badge 亦係假，spec 冇發現反而延續。
- 違反原則（已改）：House rule 1：activity 一行「Last looked at your edits 3 h ago」冇真數據來源（pr_learning_events 冇 consumed_at），會變成用 event created_at 冒充 extraction 時間。
- 違反原則（已改）：House rule 1：空狀態聲稱 Access card 三個 badge「全部 Not shared / Off」，但 learning 預設 On、本機 web research 預設 On；寫死預設值違反讀真值。
- 違反原則（已改）：House rule 1：現有 tours.ts:320 memory-tips 文案承諾「with the evidence behind them」，但 evidence drill-down 未存在；spec 冇提出喺 evidence endpoint 落地前改文案。
- 違反原則（已改）：Reuse before inventing（motion / infra）：spec 提議新 memory-tour.tsx + Popover + 新 localStorage key，但 web/src/features/onboarding 已有 tour registry、overlay、help-menu replay、localStorage 進度（store.ts:40），同 memory-tips tour。
- 違反原則（已改）：Motion：HoldActionButton 寫 1.2s，同 Queue 用緊嘅 1600ms 預設唔一致；Tabs panel opacity 冇講 exit 快過 enter。
- 違反原則（已改）：General, not personal：例子「Sep 14 · Instagram · 繁體中文」OK，但 evidence 行要跟 per-channel locale 顯示語言名，唔好寫死繁體中文；risk 提到 dev seed IDENTITY.md 有 James 品牌內容係啱嘅，要保留。
- 補上遺漏：Prompt 真相：邊幾個檔真係交俾 writing route（egress.sharedFiles / PROMPT_FILES），AGENT.md 同 BRAND.md 只係俾人睇；cloud 16,000 bytes 截尾要喺 viewer 講明。
- 補上遺漏：現有 tour infra（web/src/features/onboarding，untracked，另一 session 做緊）同 memory-tips tour；data-tour='memory-files' 已經喺 memory-view.tsx:200。
- 補上遺漏：RBAC：access.tsx 仲係 stub（全部當 owner），nav 權限未真；頁面 owner 判斷靠 snapshot membership；Export memory files 應該俾邊個 role（workspace export 係 read 級，learning JSON 含 decided_by uuid）。
- 補上遺漏：CloudSharing 喺 egress 缺席時都係 return null（memory-view.tsx:74），唔止 WebResearch。
- 補上遺漏：Viewer 喺 error 時 `!file` 會永遠 Skeleton pulse（L246）——即係假 loading，違反規則 1。
- 補上遺漏：activity endpoint 需要 migration（consumed_at 或 lastExtractedAt）先有「last looked」數。
- 補上遺漏：i18n：UI copy 暫時英文；evidence / reads 行嘅 language 用 worldwide-languages 嘅 per-channel locale 名，唔 hardcode。
- 補上遺漏：Mobile：375px Tabs 三粒 label（In your drafts）會唔夠位，要短 label 或 scroll；HoldActionButton 喺 touch 要有 keyboard 同 pointer fallback（component 已處理，要驗）。
- 補上遺漏：Parallel session：web/src/features/memory/memory-view.tsx 同 onboarding/ 都係未 commit WIP，實作要協調。
- 補上遺漏：Error：exportProfile catch 吞咗 ApiError message（memory-view.tsx:178-179）。
