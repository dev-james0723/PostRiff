# 03 · Agent conversation

> Route：`/app/agent/[conversationId]` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**注意**：`conversation-view.tsx`、`variant-card.tsx`、`composer.tsx`、`web/src/lib/api/{hooks,client,types}.ts` 喺 git status 係 M（parallel session 改緊），以下行號係 2026-09-16 嘅 working tree，落實時用 grep 再定位。

**頁面殼**：`web/src/app/app/agent/[conversationId]/page.tsx:1-9` server component，await `params` 後 render `<ConversationView conversationId>`，metadata title 'Chat'。目錄只有 `page.tsx`；成個 `web/src/app/app/` 冇 `loading.tsx` / `error.tsx`，只有 root `web/src/app/not-found.tsx`。Route 唔喺 `web/src/config/nav-config.ts`（Create group 只有 Home/Overview/Ideas/Calendar/Pipeline…），頁面冇 access gate（讀 thread 係 read 級）。

**主 view** `web/src/features/agent/conversation-view.tsx`（438 行）：
- Data hooks（:101-104）：`useSnapshot()`、`useConversations()`、`useMessages(conversationId)`、`useModels()`；`useRun(lastRunId, seed)`（:109-110），seed 由 ad-hoc key `['agent-run', workspaceId, runId]` 攞（唔喺 `hooks.ts:11-32` `keys`）。
- Layout（:212）：`grid lg:grid-cols-[13rem_1fr] xl:grid-cols-[13rem_1fr_20rem]`；rail `hidden lg:flex`（:214）、inspector `hidden xl:block`（:392）。<1024px 冇 conversation list，<1280px 冇 inspector（只靠 variant-card Preview popover `xl:hidden` 同 Compare dialog）。冇 sticky composer、冇 auto-scroll。
- Header（:247-262）：title（:161，fallback 'Conversation'）、plan `AnimatedBadge`（:251）、model `Badge`、'Open Queue'。冇 rename / archive，冇 `InfoButton`。
- Thread（:265-363）：`thread.isLoading` → Skeleton（:266）；**冇讀 `thread.error`**——404（`ideas.py:171-176` 'Conversation unavailable.'）會 render 'Conversation' + 空 thread + composer。Assistant turn：`ActivityStrip` 只喺 current run（:290）、summary、`ProposalCard`、excluded sources。Live run card：queued → `Loader ascii-braille` + `ThinkingShimmer`；否則 `StageProgress`（`AgentProgress`，秒數由第一個 event `at` 計）；Cancel → `api.cancelRun`（:315，**冇 canEdit gating、失敗冇 toast**）；`StreamingText` + `StreamCaret`（:322）。Failed：server `fail()` 將訊息寫入 assistant body `failed: true`（ideas.py:67-76），view 只喺 body 未寫 failed 時補一行（:330-332），**冇 Try again**。Cancel 會寫 'Cancelled before the draft finished.'（ideas.py:483）。`VariantCard`（:334）+ `PlanCard`（:341，要 `snapshot.data`，snapshot error 時靜靜唔出）+ no-plan hint（:342-350）只喺 current run；earlier turns 只得 'Proposed N posts … earlier turn'（:355）。
- Composer（:368-386）：`data-tour='composer'`（composer.tsx:74）、`data-tour='composer-channels'`（:88）已存在；chips 由 `state.phase2.channels` `displayState` 砌（conversation-view :138-142）；dot（composer.tsx:91,107）綠 = 'Ready for posting'／琥珀／灰，係**混合 readiness**（違反 §1.1）。語言寫死 EN / 繁中（composer.tsx:15,113-126）；`DRAFT_PLATFORMS` LinkedIn / Instagram / Threads（:18）。Hint：'⌘↵ to send · channels and times you name in the message win over the chips'。viewer 見 'You need the edit permission…'。
- Inspector（:392-434）：Tabs Preview | Sources。Preview `DraftPreview scale 0.7`；Sources 列 active 頭 12 個（:417），得 kind badge，冇 policy / origin / Approve use；§8.2 要求嘅 Memory tab 未有。

**`activity-strip.tsx`**（128 行）：intent / destinations、Skills、Memory、Sources、warnings、status（秒數 + model + cost，:48-55,105，cost 只喺 run 完先有）、run log。`STRIP` stagger 40ms、`LINE` 220ms（:12-13）——行數多時總長超過 §5 嘅 300ms。冇 Research 行（body `research` ideas.py:267/:414；event `progress.updated stage=researched` ideas.py:402）。

**`variant-card.tsx`**（138 行）：segment Tabs、`LIMITS` 寫死（:15）、`DigitSwap`、warnings / unknowns / candidateOnly badges、Preview popover（:81-91，<xl）、**`CompareDrafts` Dialog**（:107-138，並排 preview）。冇 Edit / Copy / feedback。

**`use-run.ts`**（47 行）：每 1200ms 由 cursor 0 replay（:30-32），catch 靜靜吞（:34-36）；server `_events_for` LIMIT 500（ideas.py:461），>500 events 後半睇唔到。SSE route（hosted_app.py:254-266）replay 完即閂，polling 係啱。

**`plan-card.tsx`**（482 行）+ `plan.ts`：approve chain `applyRun → accept_update? → p2_variant_review → p2_review ×N → p2_approve_many`（plan.ts:58-106）；blockers（plan-card.tsx:162-175，有 blocker 嘅 row checkbox disabled 被排除，其他照批）；`canApprove`（:114）。:289 `LevelBadge level='Assisted'` 寫死；`RowReveal`（:96-101）0.24s + min(index,5)×50ms → 最長 490ms。

**Onboarding 已存在**：`web/src/features/onboarding/`（tours.ts registry、tour-overlay.tsx、tour-mount.tsx、store.ts localStorage、help-menu.tsx、welcome-dialog.tsx）。`tour-mount.tsx:30` 排除 `/app/agent/` 唔出 welcome；`tours.ts:266` `pageTourFor` exact match，conversation 未有 page tour。

**Info sidebar**：`PageContainer` 只喺有 `pageTitle`/`pageHeaderAction` 時先 render `Heading → InfoButton`（page-container.tsx:58-68）；Home 傳咗 `infoContent`（home-view.tsx:201）但實際睇唔到。Infobar 快捷鍵係 ⌘/Ctrl+I（components/ui/infobar.tsx:27,130）。

**Backend（`src/postriff_phase2/hosted_app.py` `_ideas` :231-274 → `ideas.py`）**：
- `GET …/ideas/conversations`（:239-240 → ideas.py:187，LIMIT 100，含 `archived`）；`POST`（:241-243 → :192，require edit）
- `POST …/conversations/{id}/turns`（:244-246 → :336，require edit；`idempotencyKey` 同 key 返舊 run :363）
- `GET …/messages?cursor=`（:247-248 → :200，回傳帶 conversation title，LIMIT 500）
- `POST …/attachments`（:249-251 → :208-229）——只 INSERT，`turn()` 唔讀
- `GET …/runs/{id}/events`（:254-266 → :466；artifact 對 completed/applied 回，:464）；`cancel`（:267-269 → :472，require edit）；`apply`（:270-272 → :487，require edit；已有同 slot 未 committed draft 時 candidate 變 `proposedUpdate` 而唔改 text，:513-518；source policy 變咗 409，:509）
- `quick-start`（:235-237）、`GET /api/ideas/models`（:302-312）
- Workspace actions（client.ts:137 `act`）：`accept_update`（domain.py:359-375）、`variant_edit`（domain.py:376-390；hosted.py:216-220 set needsReview 並還原 unknowns）、`variant_feedback`（store.py:322，`FEEDBACK_REASONS` store.py:23）、`source_use_approve`（source_policy.py:130；permissions.py 冇列 → edit 級）
- Memory proposals：hosted_app.py:450-452；client.ts:147-149；hooks.ts:139-142；decide 只限 owner
- `GET …/channels`（hosted_app.py:411-414 → oauth.py:191-201）：per-capability `{level, evidence, verifiedAt}`；冇 DB row 時 default `assisted_matrix()`
- **缺**：PATCH conversation（rename / archive）；turn 消化 attachments；steering。

**Tests**：`tests/phase2/postgres_ideas.py`（bare asserts：events cursor、idempotency、apply）、`postgres_agent_plan.py`、`postgres_cli_route.py`；`tests/test_postriff_consumer_web.py` 約 :147-190 用 fake ideas service 打 conversations / turns。

## 1. Design specification（最新版）

**目的**：一條 conversation 就係一個 idea 由一句話變成每個 channel 嘅 draft、再變成 Queue 入面 jobs 嘅完整記錄。頁面做三件事：(1) 睇住 run 真實進行（queued → writing → drafted），(2) 逐個 channel 檢視、修改、預覽 draft，(3) 一次過 approve schedule plan。Agent 只可以 propose；呢頁係 user 批核嘅地方，唔係 publish 嘅地方。任何 rule（blocker、stale voice、source policy）只會喺 draft 上面提示，唔會阻止 user 繼續打字、Copy 或者 draft again。

**Layout**：**Grid（保留三欄骨架，補 responsive）**
- ≥1280px（xl）：`[13rem rail] [1fr thread] [20rem inspector]`；inspector 用 `ui/resizable.tsx` 可拖 280–420px（design §8.2 寫 340），寬度記 localStorage（try/catch，純 convenience）。
- 768–1279px：單欄 thread；rail 入 `Sheet side='left'`（transitions.dev 07 panel reveal），header 左 `Icons.panelLeft` 掣；inspector 入 `Sheet side='right'`，header 右 `Icons.eye` 掣，同一個 Tabs component。
- 375px：單欄；thread 用 `MessageScroller`（`ui/message-scroller.tsx`）做 viewport，container 要有明確高度（`h-[calc(100dvh-…)]`，PageContainer 係 flex-1）；composer `sticky bottom-0` + `pb-[env(safe-area-inset-bottom)]`，chips 一行 horizontal scroll；Preview 用現有 popover，Compare 用現有 dialog（已 snap scroll）。

**Header（thread 欄頂，自己砌，唔靠 PageContainer pageTitle）**：左：title（`thread.data.title` 先到就用，未到 Skeleton；P1 inline rename）+ `relativeTime(updatedAt)` + `InfoButton content={infoContent}`（components/ui/info-button.tsx）；右：plan `AnimatedBadge`、model `Badge`、'Open Queue'；<xl 加 rail / inspector 兩粒 icon 掣。

**Primary action**：composer Send（⌘↵）。Current run 有 plan 未 applied 時，PlanCard 'Review & approve' 係第二個 primary（只 `approve` 權限見到可按）。Run running 時 Send 變 spinner。

**Info sidebar**：`infoContent` 三段：'Channels in your message win'、'Everything is a proposal'、'What the strip shows'（intent / sources / skills / memory / cost 全部由 run events 讀，cost 喺 run 完先出）。⌘I 開關。

**權限（`web/src/lib/auth/access.tsx` `checkAccess`）**：read → 睇 thread、Preview、Compare、Copy；edit → composer、Cancel、Try again、quick-reply、Edit、Don't use、Approve use、rename / archive；approve → PlanCard approve；owner → Memory proposal decide。冇權限嘅掣唔顯示，並喺相關位置講一句原因（沿用現有 'You need the edit permission…'）。

**Assistant turn 次序**：ActivityStrip → summary text → ProposalCard（memory turn）→ excluded sources → live run card → failed/cancelled notice + Try again → VariantCard → PlanCard 或 no-plan hint → quick-reply chips（只最後一個 turn）→ timestamp。Earlier turns：'Show N drafts' disclosure（P1）。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Conversation rail | 喺同一 workspace 嘅 conversation 之間跳；New 返 Home | `useConversations()` 列表，`SharedLayoutBg` hover pill（現有）；title + `formatDate(updatedAt)`；archived（P1）分組收埋。'New' → `/app?new=1`。<lg 變 Sheet。 | loading：2 條 Skeleton（現有）；empty：'No conversations yet · Start one from Home'；error：'Conversations unavailable' + Retry（唔顯示 0 條）。 |
| Header | 講清楚呢條 conversation 係乜、用邊個 model、plan 去到邊 | title（P1 rename，edit 權限）、plan badge、model pill、InfoButton、Open Queue；<xl 加 rail / inspector 掣。 | title 未載入：一行 Skeleton（唔用 'Conversation' 假名）；rename 儲存失敗：toast + 還原。 |
| Thread | 完整、可追溯嘅 turn 記錄；新 turn 自動跟到底 | `MessageScroller` viewport；user bubble（現有）；assistant turn 按上面次序。`MessageScrollerButton` 只喺 user 自己 scroll 走咗先出。Arrived turns 先 pop-in（`loadedIds` 保留）。live run card 加 `aria-live='polite'`。 | loading：Skeleton；404（ApiError status 404）：`ui/empty.tsx` 'This conversation is unavailable' + 'Start a new conversation' + 'Open conversations'；其他 error：`ui/alert.tsx` 'Could not load this conversation' + Retry；0 messages：Empty 教例句 + composer 可用；viewer：thread 照顯示，寫入掣隱藏。 |
| Live run card | 真實反映 run 狀態：queued / writing / 秒數 / streamed text / cancel | 現有 Loader + ThinkingShimmer / AgentProgress / StreamingText / Cancel 保留；Cancel 只 edit 權限見到，失敗 toast。加：polling 連續失敗 ≥3 次 → 'Connection lost · Retry'（`use-run` 回傳 `stalled`，唔改 run status）。 | queued（route 名）、running（stage + 秒數）、stalled、cancelled（server 寫嘅句子）、failed（`run.failed` message 原文 + Try again）。 |
| Variant card | 逐個 channel 檢視同修改 draft；字數對 limit；unknowns 留底 | 現有 tabs / DigitSwap / badges / Preview popover / Compare dialog 保留。Footer 加 `Copy`（read 級，`navigator.clipboard`，toast）同 `Edit`（edit 級，inline Textarea）。Save 流程：run 未 applied → `applyRun` → refetch snapshot → `variantForRow` → 如果有 `proposedUpdate` 而 `voiceRevision` 同 active 一致，先 `accept_update` → `act('variant_edit', {variantId, variantRevision, text})`。Applied 之後 card 顯示 workspace variant 嘅 text + 'rev N · edited'，Preview / Compare / PlanCard 用同一份 text。P1：'Don't use this draft'（`variant_feedback`）。 | over limit → 紅色字數；candidateOnly / unknowns badges；editing；saved（DigitSwap 滾到新長度）；stale（409 → toast 'This draft changed. Reload' + refetch）；apply 409 'Sources or their policies changed' → draft 上面出 reminder 'Sources changed since this draft. Draft again to use them' + Copy 照用，唔鎖 composer；proposedUpdate 對唔上 active voice → reminder 'Written with an earlier voice' + 'Draft again'。 |
| Plan card | 一次過 approve，每 row 一個 job | 現有 PlanCard 保留；:289 `LevelBadge` 改讀該 row 所揀 `channelId` 喺 `useChannels()` 嘅 `capabilities.publish.level`，tooltip 顯示 `evidence`；channels query 未到 / error 顯示 'Capability unavailable'，唔 fallback 'Assisted'。RowReveal 改 `delay = min(index,2)*0.04`、duration 0.2，總長 ≤300ms。snapshot error 時唔再靜靜消失，出 'Plan unavailable · Retry'。 | blocked（row 留低並講原因，其他 row 照批）、ready、approving（TodoList 真 step）、done（SuccessCheck 只喺本次批核播）、no voice、no approve permission（現有）。 |
| Quick-reply chips | 一撳將常見下一步放入 composer；一定要 user 再撳 Send，因為每個 turn 係一個有 model 同 cost 嘅 run | 最後一個 assistant turn 之下（edit 權限）：'Shorter'、'Another angle'、'Same idea in {另一個語言}'（語言清單讀 composer 現有 Language 型別，Stage 2 跟 worldwide languages plan 換成 per-channel locale）、'Add a time'（prefill 'Instagram at 4pm today, LinkedIn at 5pm'，通用例子）。撳落只 `setText` + focus，`SPRING_PRESS` whileTap。 | run running / failed 時唔顯示；冇 variants 時只顯示 'Add a time' 以外嘅。 |
| Composer | 下一 turn：文字 + channels + language + model | 現有 `Composer` 保留（data-tour 已有）；`ChannelChip` 加 `publish?: Capability`，dot 換 `LevelBadge size='sm'`，title '{account} · publish {level} · {evidence}'；未接 account 顯示 'Drafts only'。Home 共用同一 component，要一齊改。<md sticky bottom。 | busy（spinner）；no edit permission（現有句子）；channels query error → chips 照顯示 platform 名，badge 寫 'Unavailable'。 |
| Inspector | 旁邊睇 draft 喺 app 入面嘅樣、run 讀咗乜 source、memory 用咗乜 / 提議咗乜 | Tabs：**Preview**（現有）｜**Sources · N**（title、kind、`sourcePolicy` badge、`origin.kind==='web_research'` 顯示 host + external link、'Approve use' → `act('source_use_approve')`（edit 級）；run `source.added` events 用過嘅排前標 'Read this turn'）｜**Memory**（P1：run `memory` binding + `useMemoryProposals()` pending 用 `ProposalCard`；非 owner 見 'Only a workspace owner can decide this.'，沿用 proposal-card.tsx:125）。<xl 變 Sheet。 | Preview 冇 variant：現有一句；Sources 0：'No usable sources yet'；Memory 0 pending：'Nothing waiting for a decision'；query error：'Unavailable' + Retry。 |

- **Empty state**：兩種：(1) **404 / 唔屬於呢個 workspace**：`ui/empty.tsx`，`Icons.messageCircle`，'This conversation is unavailable'，副題 'It may belong to another workspace or was removed.'，actions 'Start a new conversation'（/app?new=1）+ 'Open conversations'（開 rail / Sheet）。(2) **有 conversation 但 0 messages**：Empty 'Nothing has been written here yet'，副題 'Say the topic, the channels and the times, e.g. “A post about what I learned this week. Instagram at 4pm today, LinkedIn at 5pm.” Each channel gets its own draft; you approve before anything is scheduled.'（通用例句）；composer 可用並 auto-focus（edit 權限）；viewer 只見副題第一句。
- **Loading**：`loading.tsx`：三欄骨架（rail 2 條、thread 1 user bubble + 1 assistant block、inspector 1 個 phone 比例），全部 `ui/skeleton.tsx` pulse；title 位一行 Skeleton。唔顯示任何 'Loading…' 文字，唔顯示 0。Run 進行中由 live run card 負責（真 stage + 真秒數）。
- **Error**：`error.tsx`（route boundary，client component）：'This page could not be shown' + Retry（`reset()`）+ 'Back to Home'；唔猜原因。Query 層：`thread.error` 404 → Empty；其他 → inline alert + `thread.refetch()`。`useRun` 連續失敗 → 'Connection lost · Retry'。`sendTurn` 失敗 → toast（現有）+ composer 保留原文。`cancelRun` 失敗 → toast。Approve chain 失敗 → TodoList 停喺該 step（現有）。Apply 409（policy 變咗 / hash 唔對）→ draft 上 reminder + 'Draft again'，永遠唔鎖 composer。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 新到嘅 user / assistant turn | message 唔喺 `loadedIds`（真係新到） | pop-in spring，reload 唔重播 | components/agents/message.tsx `Message animateIn` + `MessageBubble` | 是 |
| Live run card queued 行 | 最後一個 `progress.updated` stage === 'queued' | ascii-braille spinner + shimmer 文字（route 名由 run.model 對應 option 讀） | components/motion/loader.tsx `Loader variant='ascii-braille'` + components/agents/loading-states/thinking-shimmer.tsx | 是 |
| Live run card writing 行 | stage 唔係 queued 而且 run.events[0].at 存在 | 真實經過秒數；冇 event 唔顯示計時器 | components/agents/loading-states/agent-progress.tsx `AgentProgress` | 是 |
| Streamed draft text | 每個 `message.delta` event 到達 | 新字由模糊變清，舊字唔郁；caret 閃（reduced motion 唔出） | ui/streaming-text.tsx `StreamingText` + 現有 `StreamCaret` | 是 |
| Activity strip 各行 | strip 首次 mount / 新 warning 到達 | 頭 3 行 stagger 40ms、每行 220ms ease-out，之後嘅行同第 3 行一齊出，總長 ≤300ms；run settle 時 spinner → check | activity-strip.tsx 現有 `STRIP`/`LINE` variants（加 cap）+ components/motion/action-swap.tsx `ActionSwapIcon` | 是 |
| Run log 展開 / 收埋 | Show / Hide run log | 高度動畫，收快過開；文字 roll swap | components/agents/agent-disclosure.tsx + `ActionSwapText animation='roll'` | 是 |
| Variant tabs + 字數 | 切換 channel tab / Save edit | segment pill 滑動；字數由上一個真實長度滾到新長度 | components/motion/tabs.tsx `variant='segment'` + components/motion/digit-swap.tsx | 是 |
| Inline edit 開合 | 撳 Edit / Cancel / Save | Textarea disclosure 高度動畫，收快過開；Save idle → loading → success 跟真實 request | components/agents/agent-disclosure.tsx + components/motion/button/stateful.tsx `StatefulButton` | 是 |
| Plan card rows | PlanCard 首次顯示 | 逐行浮現，delay = min(index,2)×40ms、duration 200ms，總長 ≤300ms；reduced motion 無動畫（現有） | plan-card.tsx 現有 `RowReveal`（改常數） | 是 |
| Approve checklist + Scheduled | approvePlan 每個真實 step 嘅 onProgress | TodoList 逐 step 剔；SuccessCheck 只喺本 session 批核先播 | components/agents/todo-list.tsx + `StatefulButton` + ui/success-check.tsx | 是 |
| Jump to latest | viewport 唔喺底而有新 message / delta | 浮起 arrow-down 掣，撳落滑到底；reduced motion 直接跳 | ui/message-scroller.tsx `MessageScrollerButton` | 是 |
| Rail / inspector Sheet（<xl） | header 兩粒 icon 掣 | 由左 / 右滑入 + cross-blur，收快過開（用 transitions.css token，唔自訂 ms） | ui/sheet.tsx（transitions.dev 07 panel reveal） | 是 |
| Quick-reply chips | 撳落 | scale 0.96 spring press，composer 文字更新 + focus；reduced motion 唔縮 | `SPRING_PRESS`（lib/ease.ts:13），同 composer.tsx chips 一樣 | 是 |
| Conversation rail hover 底色 | hover 另一條 conversation | 底色 pill 跟住滑 | components/motion/shared-layout-bg.tsx（現有） | 是 |
| Page enter | 由 Home 或 rail 轉入 | 內容浮入 | web/src/app/app/template.tsx `.t-page-enter`（transitions.css:252） | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Conversation messages endpoint（cursor，帶 title） | api | 有 | hosted_app.py:247-248 → ideas.py:200-206；client.ts:191-192；hooks.ts:89-96 | S |
| 2 | Turn endpoint（intent → research → skills → run；idempotencyKey） | api | 有 | hosted_app.py:244-246 → ideas.py:336-440（key :339，重用 :363）；client.ts:193 | S |
| 3 | Run events polling + cancel + apply | api | 有 | hosted_app.py:254-272 → ideas.py:456-529；client.ts:197-201；use-run.ts:30 | S |
| 4 | Incremental cursor polling（保留 run.cursor、merge events） | frontend | 冇 | use-run.ts:30 永遠 cursor 0；ideas.py:461 LIMIT 500 | S |
| 5 | Polling failure 訊號（stalled）+ cancel 失敗 toast | frontend | 冇 | use-run.ts:34-36 空 catch；conversation-view.tsx:315 `void api.cancelRun` | S |
| 6 | Route-level loading / error + 404 Empty + title Skeleton | frontend | 冇 | 目錄只有 page.tsx；conversation-view.tsx:161 fallback、:266 只讀 isLoading | S |
| 7 | Header InfoButton（infoContent） | frontend | 冇 | page-container.tsx:58-68 冇 pageTitle 就唔 render InfoButton；components/ui/info-button.tsx 可直接放入自訂 header | S |
| 8 | Thread auto-follow + Jump to latest | frontend | 冇 | ui/message-scroller.tsx:120-127 exports；conversation-view.tsx:265 用普通 `<ol>` | S |
| 9 | Responsive rail / inspector（Sheet）+ sticky composer | frontend | 冇 | conversation-view.tsx:214、:392；ui/sheet.tsx、ui/resizable.tsx、hooks/use-media-query.ts 已有 | M |
| 10 | Per-capability channel data（publish level + evidence） | api | 有 | hosted_app.py:411-414 → oauth.py:191-201；client.ts:167；hooks.ts:49-52；types.ts:438-451 | S |
| 11 | Composer chips + plan rows 讀 capability level | frontend | 冇 | composer.tsx:91,107 displayState；plan-card.tsx:289 寫死 'Assisted'；components/app/level-badge.tsx:17；features/channels/capability-chips.tsx 可參考 evidence tooltip | M |
| 12 | Permission gating：Cancel / Retry / Edit / quick-reply 要 edit | frontend | 冇 | conversation-view.tsx:315 Cancel 冇 canEdit；server cancel require edit（ideas.py:474）；lib/auth/access.tsx:69 checkAccess | S |
| 13 | Variant edit backend（apply → accept_update? → variant_edit） | api | 有 | apply ideas.py:487-529（proposedUpdate :513-518）；accept_update domain.py:359-375；variant_edit domain.py:376-390；hosted.py:216-220 needsReview；client.ts:137 act | S |
| 14 | Variant card Edit / Copy + applied-variant text 顯示 + apply 409 reminder | frontend | 冇 | variant-card.tsx 只 render `variant.text`（:62）；`variantForRow` plan.ts:33；accept_update 處理可抄 plan.ts:69-73 | M |
| 15 | Retry failed run（同 text / destinations / language / model / timeZone，新 key） | frontend | 冇 | conversation-view.tsx:330-332 只顯示；ideas.py:339 | S |
| 16 | Quick-reply chips（prefill composer） | frontend | 冇 | 無此 component；純 client state | S |
| 17 | Earlier turns 嘅 drafts（按 runId 取 artifact）+ `keys.run` | api | 有 | ideas.py:464 artifact 對 completed/applied 回；hooks.ts:11-32 未有 run key，conversation-view.tsx:109,197 用 ad-hoc key | M |
| 18 | Research 行喺 activity strip（已讀，唔係進度） | frontend | 冇 | body `research` ideas.py:267,414；event stage=researched ideas.py:402；activity-strip.tsx 冇讀 | S |
| 19 | Sources tab：policy badge、origin host / link、Approve use | api | 有 | types.ts:131-141 sourcePolicy / egressConsent；origin ideas.py:317（types.ts 要加 optional）；source_use_approve source_policy.py:130（edit 級） | M |
| 20 | Inspector Memory tab（owner decide） | api | 有 | hosted_app.py:450-452；client.ts:147-149；hooks.ts:139-142；features/memory/proposal-card.tsx:43,125 owner-only | S |
| 21 | Rename / archive conversation | api | 冇 | hosted_app.py:231-274 冇 PATCH；ideas.py:172,189 已 SELECT archived_at；`_conversation` :171 FOR UPDATE 可重用 | M |
| 22 | Don't use this draft（variant_feedback） | api | 有 | store.py:322-333；FEEDBACK_REASONS store.py:23 | M |
| 23 | Thread live refresh（pending / teammate turn） | frontend | 冇 | hooks.ts:89-96 冇 refetchInterval；query-client.ts:7 staleTime 60s；body `pending: true` ideas.py:414 | S |
| 24 | Attachments 入 run | backend | 冇 | ideas.py:226 只 INSERT；turn() 唔讀 pr_attachments | L |
| 25 | Conversation page tour（接入現有 onboarding） | frontend | 冇 | features/onboarding/tours.ts 有 registry 但冇 conversation；:266 pageTourFor exact match；tour-mount.tsx:30 排除 /app/agent/；data-tour 'composer' / 'composer-channels' 已存在（composer.tsx:74,88） | S |
| 26 | Languages：quick-reply / composer 語言跟 per-channel locale | frontend | 冇 | composer.tsx:15 `Language = 'English' \| '繁體中文'`；variant-card.tsx:17 destinationLabel 二選一；docs/postriff-worldwide-languages-plan.md Stage 1 已決定 per-channel locale | M |

## 3. Features

### P0

- **Route states：loading / error / 404 empty + title Skeleton**：而家 404 conversation 會 render 假嘅 'Conversation' 標題 + 可打字 composer，send 先爆錯（conversation-view.tsx:161,:266）。真數據先郁：唔知就話唔知。
- **權限對齊：Cancel / 寫入掣按 edit / approve / owner gating**：Cancel 而家 viewer 都見到，撳落 403（ideas.py:474）；新加嘅 Edit、Retry、Approve use 一開始就要跟 access.tsx。
- **Thread 自動跟到底 + Jump to latest**：Run 期間 streamed text 同 variant card 喺 viewport 之外；`ui/message-scroller.tsx` 已喺 repo 未用。
- **Responsive：rail / inspector Sheet + sticky composer**：<1024px 去唔到 conversation list，<1280px 冇 inspector（:214,:392）。
- **Chips 同 plan rows 讀 capability matrix（連 evidence）**：§1.1：composer.tsx:107 綠點同 plan-card.tsx:289 寫死 'Assisted' 都係混合狀態；`useChannels()` 已有 level + evidence。（depends on：useChannels()（hooks.ts:49））
- **Failed / stalled run 嘅 Try again**：Run 失敗只得一句文字，要重打；polling 斷線零訊號（use-run.ts:34）。失敗要即刻俾到下一步。
- **Motion 合規修正（strip 同 plan rows 總長 ≤300ms）**：activity-strip 最長 ~580ms、RowReveal 490ms，都超出 §5。改常數即可。
- **Variant Copy + inline Edit**：Draft 而家 read-only，改一個字都要去 Queue；design §8.2 variant card 要 Edit。Backend 已有，但要處理 apply → proposedUpdate → accept_update 先改到正確 text（ideas.py:513-518）。一撳 AI 改寫唔做，因為每次係有 cost 嘅 run，要經 composer。（depends on：applyRun + accept_update 處理）

### P1

- **Quick-reply chips（Shorter / Another angle / 另一語言 / Add a time）**：誠實版一撳改寫：chip 只 prefill，user 再 Send，model / cost 由 strip 顯示。唔係必要功能，排 P1。
- **Earlier turns 顯示自己嘅 drafts**：之前每個 turn 只得 'earlier turn'（:355）；events endpoint 對 completed/applied run 回 artifact（ideas.py:464），純 UI 工作。
- **Inspector Memory tab + Research 行 + Sources policy / origin / Approve use**：§8.2 要求三 tab；research 已經真係跑但睇唔到讀咗邊幾頁；web research source 要 use approval 先可出街，而家要走去 Ideas 頁。
- **Conversation page tips（接入現有 onboarding）**：features/onboarding 已有 registry / overlay / nudge；只需加 'conversation-tips' 同 prefix match，唔使新機制。Tour 只可以講已 ship 嘅功能。
- **Rename / archive conversation**：Title 係 quick_start 頭 60 字（ideas.py:561）改唔到；list LIMIT 100 冇 archive。缺一條 PATCH route。（depends on：新 endpoint PATCH /ideas/conversations/{id}）
- **Don't use this draft（feedback）**：`variant_feedback` 係 preference learning signal，而家只有 Queue 可以俾。（depends on：variant 已 applied）
- **Thread live refresh（pending / teammate）**：多人 workspace 另一個 member 起嘅 turn 唔會出現；條件用真數據 `pending: true`。

### P2

- **Per-channel 語言（跟 worldwide languages plan）**：composer / quick-reply / destinationLabel 寫死 EN / 繁中；Stage 2 落實時一齊換，唔好喺呢頁再加寫死語言。（depends on：docs/postriff-worldwide-languages-plan.md §10 決定）
- **Attachments +**：Endpoint 存在但 turn() 唔讀，加 UI 係假功能。（depends on：ideas.py turn() 消化 pr_attachments）
- **Steering（run 進行中補一句）**：Design Phase 4；cli_runtime 而家一問一答。（depends on：cli_runtime 支援 open stdin）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明三樣：(1) 每一個 turn 係一個 proposal——agent 寫，你批；(2) 每個 channel 有自己一份 draft，字數同 limit 真實顯示；(3) 講明時間就有 schedule plan，approve 一次，jobs 去 Queue。點教：header plan badge 常駐；activity strip 第一行永遠係 detected intent + destinations；header `InfoButton`（⌘I）三段說明；composer hint 加一句 'Nothing is scheduled until you approve'（新加）。Tips 接入現有 `features/onboarding`：`tours.ts` 加 `conversation-tips`（route '/app/agent'），`pageTourFor` 支援 `/app/agent/` prefix；沿用 tour-mount 嘅一次性 toast nudge（'Show me'）同 Help menu 重播，唔自動開 overlay，永遠唔阻止打字或 approve。Step 用 `when` 跟 `TourCtx.canEdit` 同 target 是否存在自動略過。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="conversation-thread"]（新加喺 conversation-view.tsx thread `<ol>` / MessageScrollerContent）` | Every turn is a proposal | You describe the post; the agent drafts it. Nothing here publishes. You approve the exact text and time before anything is scheduled. |
| 2 | `[data-tour="activity-strip"]（新加喺 activity-strip.tsx 最外層 motion.div）` | What the agent actually read | The intent it detected, the sources it was allowed to read, skills and memory rules. When the run finishes, the cost appears here. Open the run log to see every event. |
| 3 | `[data-tour="variant-card"]（新加喺 variant-card.tsx 最外層 div）` | One draft per channel | Switch tabs to see each channel's version, or Compare them side by side. The count is against that channel's limit. Unknowns stay listed until you confirm they are out. （Edit ship 之後先加 'Edit the text here.'） |
| 4 | `[data-tour="plan-card"]，fallback [data-tour="no-plan-hint"]（新加喺 plan-card.tsx 最外層 / conversation-view no-plan hint）` | Approve once, jobs appear in the Queue | Each row becomes its own job. A row that is missing something (an account, an image, a time) says what and is left out; the other rows can still go. |
| 5 | `[data-tour="composer"]（已存在 composer.tsx:74）` | Say the channel and the time | Channels and times inside your message win over the chips, e.g. “Instagram at 4pm today, LinkedIn at 5pm”. ⌘↵ sends. The model pill shows who writes. |
| 6 | `[data-tour="inspector"]（新加喺 inspector Tabs 最外層；<xl fallback header `aria-label='Open inspector'` 掣）` | See it as the app shows it | The selected draft is drawn inside its channel, with the planned time if there is one. The sources this workspace can draft from sit in the next tab. |

**Empty state 教咩**：0 messages 嘅 conversation（或 404 之後 Start new）教一句通用例句：'A post about what I learned this week. Instagram at 4pm today, LinkedIn at 5pm.'——示範 topic + channel + time 三件事就夠，並講明 each channel gets its own draft、you approve before anything is scheduled。例句唔帶任何品牌、行業或 James 自己嘅 project，設計師、老師、小店老闆、工程師讀落一樣。

## 5. Next steps（按次序）

1. **Route states + header：加 `loading.tsx`（三欄 Skeleton）、`error.tsx`（reset + Back to Home）；conversation-view 讀 `thread.error`（ApiError 404 → `ui/empty.tsx`；其他 → alert + refetch）；title 用 `thread.data.title`，未到 Skeleton；header 加 `InfoButton content={infoContent}`；Cancel 加 canEdit gating + 失敗 toast。**（effort S）  
   檔案：`web/src/app/app/agent/[conversationId]/loading.tsx（新）、error.tsx（新）；web/src/features/agent/conversation-view.tsx（title :161、header :247-262、thread :265-266、Cancel :315）；web/src/components/ui/info-button.tsx（現有）`
2. **Motion 合規：activity-strip.tsx `STRIP`/`LINE` cap 總長 ≤300ms；plan-card.tsx `RowReveal` 改 `min(index,2)*0.04` + duration 0.2。**（effort S）  
   檔案：`web/src/features/agent/activity-strip.tsx:12-13；web/src/features/agent/plan-card.tsx:96-101`
3. **Thread viewport 換 `MessageScrollerProvider / MessageScroller / MessageScrollerViewport / MessageScrollerContent / MessageScrollerItem` + `MessageScrollerButton`；container 固定高度；composer `sticky bottom-0` + safe-area；加 data-tour（conversation-thread / activity-strip / variant-card / plan-card / no-plan-hint / inspector），`composer` 已有。**（effort S）  
   檔案：`web/src/features/agent/conversation-view.tsx:247-390；web/src/components/ui/message-scroller.tsx；activity-strip.tsx、variant-card.tsx、plan-card.tsx 最外層`
4. **Responsive：抽 `conversation-rail.tsx`、`inspector.tsx`；<lg rail 入 `Sheet side='left'`、<xl inspector 入 `Sheet side='right'`（`hooks/use-media-query.ts`）；header 加 `Icons.panelLeft` / `Icons.eye` 掣（aria-label）；xl inspector 用 `ui/resizable.tsx`，寬度 localStorage（try/catch）。**（effort M）  
   檔案：`web/src/features/agent/conversation-rail.tsx（新）、inspector.tsx（新）、conversation-view.tsx:212-245,:392-434；web/src/components/ui/sheet.tsx、resizable.tsx`
5. **Capability honesty：conversation-view 同 home-view 加 `useChannels()`；`ChannelChip` 加 `publish?: Capability`；composer dot 換 `LevelBadge size='sm'` + evidence tooltip，query error 顯示 'Unavailable'；plan-card.tsx:289 改讀 row 所揀 `channelId` 嘅 `capabilities.publish`，冇 data 顯示 'Capability unavailable'。**（effort M）  
   檔案：`web/src/features/agent/composer.tsx:21-27,:89-110；conversation-view.tsx:138-142；home-view.tsx；plan-card.tsx:289；web/src/components/app/level-badge.tsx`
6. **Run 失敗 / 斷線：`use-run.ts` 改 incremental cursor（保留 `run.cursor`、merge events）並回傳 `{ run, stalled }`（連續 ≥3 次失敗先 true）；failed / cancelled turn 加 'Try again'（重送上一個 user turn 嘅 text、destinations、language、model、timeZone，新 idempotencyKey，edit 權限）；live card 加 'Connection lost · Retry'。**（effort M）  
   檔案：`web/src/features/agent/use-run.ts；conversation-view.tsx:180-208,:302-332`
7. **Variant Copy + Edit：variant-card footer 加 Copy（read）同 Edit（edit；AgentDisclosure + Textarea + StatefulButton）；新 `use-variant-edit.ts`：未 applied → `api.applyRun` → `api.snapshot` → `variantForRow` → 有 `proposedUpdate` 且 voiceRevision 對 → `act('accept_update')` → `act('variant_edit', {variantId, variantRevision, text})`；applied 後 card / Preview / Compare 顯示 workspace variant text + 'rev N · edited'；409 stale → toast + refetch；apply 409 policy changed / voice 唔對 → draft 上 reminder + 'Draft again'，Copy 照用。**（effort M）  
   檔案：`web/src/features/agent/variant-card.tsx；web/src/features/agent/use-variant-edit.ts（新）；plan.ts:33,69-73（重用）；conversation-view.tsx:334-340`
8. **Conversation tips：`tours.ts` 加 `conversation-tips`（steps 見 onboarding，只包已 ship 嘅功能），`pageTourFor` 支援 `/app/agent/` prefix；`tour-mount.tsx` 保持排除 welcome 但容許 page nudge；`use-tour-context` 已有 canEdit。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:266-268 + PAGE_TOURS；web/src/features/onboarding/tour-mount.tsx:30-36`
9. **Quick-reply chips：新 `reply-chips.tsx`（Shorter / Another angle / Same idea in {另一語言} / Add a time），只 `setText` + focus；edit 權限；最後一個 assistant turn 而 run 唔係 running / failed 先 render。**（effort S）  
   檔案：`web/src/features/agent/reply-chips.tsx（新）；conversation-view.tsx（timestamp :359 之前）`
10. **Earlier turns drafts：hooks.ts `keys` 加 `run: (w, id) => ['agent-run', w, id]`，統一 conversation-view 同 home-view 嘅 ad-hoc key；新 `useRunArtifact(runId, enabled)`（staleTime Infinity）；非 current turn 加 'Show N drafts' AgentDisclosure，展開先 fetch，render VariantCard（read-only + Copy + Compare）。**（effort M）  
   檔案：`web/src/lib/api/hooks.ts:11-32 + 新 hook；conversation-view.tsx:109,:197,:352-357`
11. **Inspector 三 tab：Sources 加 `sourcePolicy` badge、`origin` host + link（types.ts SnapshotSource 加 optional `origin`）、'Read this turn' 排序（run `source.added`）、'Approve use'（edit）；Memory tab 用 `useMemoryProposals()` + `ProposalCard`（owner decide）；activity-strip 加 Research 行（`research.pages.length` + hosts，完成式文案 'Read N pages'）。**（effort M）  
   檔案：`web/src/features/agent/inspector.tsx；activity-strip.tsx；web/src/lib/api/types.ts:131-141；web/src/features/memory/proposal-card.tsx`
12. **Rename / archive：`ideas.py` 加 `update_conversation`（require edit、`title` clean ≤200、`archived` bool → archived_at，經 `_conversation` 404）；`hosted_app.py _ideas` 加 `PATCH …/conversations/{id}`；client.ts `updateConversation`；hooks `useUpdateConversation` invalidate `keys.conversations` + `keys.messages`；header inline rename、rail archive 分組；`tests/phase2/postgres_ideas.py` 加 asserts（rename 生效、archived flag、viewer 403）；`tests/test_postriff_consumer_web.py` fake service 加 route。**（effort M）  
   檔案：`src/postriff_phase2/ideas.py:187-198 附近；src/postriff_phase2/hosted_app.py:238-251；web/src/lib/api/client.ts:188-193；web/src/lib/api/hooks.ts；conversation-rail.tsx；tests/phase2/postgres_ideas.py；tests/test_postriff_consumer_web.py`
13. **Don't use this draft：variant-card footer Popover（`FEEDBACK_REASONS` label + note）→ 共用 use-variant-edit 嘅 apply 邏輯 → `act('variant_feedback', {variantId, variantRevision, reasons, note})`；已 scheduled 嘅 variant 按 409 訊息提示。**（effort M）  
   檔案：`web/src/features/agent/variant-card.tsx；use-variant-edit.ts`
14. **Thread refetch：`useMessages` 加 `refetchInterval: (q) => q.state.data?.messages.some((m) => (m.body as {pending?: boolean}).pending) ? 3000 : false`、`refetchOnWindowFocus: true`。**（effort S）  
   檔案：`web/src/lib/api/hooks.ts:89-96`
15. **Languages（P2）：composer 語言、quick-reply、`destinationLabel` 改讀 per-channel locale registry（跟 worldwide languages Stage 2）。**（effort M）  
   檔案：`web/src/features/agent/composer.tsx:15,113-126；variant-card.tsx:17；reply-chips.tsx`
16. **Attachments end-to-end（P2）：`turn()` 讀 `pr_attachments`（source → source_ids；asset → assets；link → research urls）；之後先加 composer '+'。**（effort L）  
   檔案：`src/postriff_phase2/ideas.py:336-390；web/src/features/agent/composer.tsx`

## Risks

- **Apply 唔一定改 text**：同 platform/language 已有未 committed draft 時，apply 只將 candidate 放入 `proposedUpdate`（ideas.py:513-518）。Edit 前唔 accept_update 就會改錯 text，之後 accept_update 409 stale；voiceRevision 唔對時 accept_update 會拒絕，要 reminder + Draft again。
- **Parallel sessions 改緊 web/src**：conversation-view.tsx、variant-card.tsx、composer.tsx、hooks.ts、types.ts、client.ts 全部 M；行號會再漂移，落實前 grep 定位，commit 要 stage by path。
- **Capability default**：冇 pr_channel_capabilities row 時 server 回 `assisted_matrix()`（oauth.py:201）；badge 要同時顯示 evidence，唔好令 'Assisted' 睇落似驗證過。
- **Polling 由 cursor 0 + LIMIT 500**：長 CLI run 後半 events 睇唔到，好似卡住；incremental cursor 係 P0 一部分。
- **Motion 總長**：strip 同 plan rows 現時超出 300ms；新 Sheet / disclosure 用 transitions.css token，收快過開，全部 `useReducedMotion()`。
- **Tour copy 誠實**：tours.ts 規定唔可以講產品做唔到嘅嘢；Edit 未 ship 前 tour 唔提 Edit，cost 只喺 run 完先出。
- **Attachments 半成品**：endpoint 201 但 run 唔讀；backend 改好前任何 '+' 掣都係假功能。
- **General, not personal**：quick-reply、empty state 例句、tour 文案全部通用；code review grep 一次品牌 / 鋼琴字眼。
- **Dev harness Threads 係 live provider**：驗證 approve chain 用 fixture / fake CLI + disposable Postgres，唔好喺 :3100 撳 Review & approve；API 重開清 dev DB 要 re-seed。
- **RBAC**：rename / archive / Edit / Retry / Approve use 用 edit；Approve 用 approve；Memory decide 只 owner；UI 要同 permissions.py 一致，否則見到掣但 403。
- **MessageScroller 高度**：PageContainer 係 flex-1，冇固定高度時 scroller 唔會 scroll，sticky composer 喺 iOS keyboard 彈出時要測。
- **Teammate turn pop-in**：refetchInterval 後別人嘅 turn 經 `loadedIds` 判定為 arrived 會 pop-in，合理；settle 同一 messageId 唔重播。

## 覆核記錄

- 改正：conversation-view.tsx 435 行，layout :209、rail :211、inspector :389、title fallback :160 → 行號全部 +2~+5；落實時用 grep 定位，唔好靠行號
- 改正：Memory proposals routes hosted_app.py:446-450；client.ts:142-144；hooks.ts:139-142 → 改行號；並補 ProposalCard decide 只限 owner（features/memory/proposal-card.tsx:43,125）
- 改正：variant_edit 喺 domain.py:376-390；hosted.py:202-206 set needsReview → 改做 hosted.py:216-220
- 改正：Variant inline edit 流程：未 applied 先 applyRun，再 variant_edit 即可 → Edit 流程要：apply → refetch → variantForRow → 若有 proposedUpdate 且 voiceRevision 相符先 accept_update → 再 variant_edit；voice 唔相符時提示 'This draft was written with an older voice. Draft again or edit the current text'（reminder，唔 block Copy）
- 改正：source_use_approve 喺 source_policy.py:109-121 → source_policy.py:110-140
- 改正：SnapshotSource sourcePolicy/egressConsent types.ts:127-137；phase2.channels 冇 capability types.ts:145；ChannelView.capabilities types.ts:443-452 → 改行號
- 改正：client.ts:135 act；client.ts:162 channels；client.ts:186-199 messages/turn/runEvents → 改行號
- 改正：plan-card.tsx:242 LevelBadge 寫死 'Assisted'；RowReveal stagger 50ms（:100-107） → 行號改 :289、:96-101；motion 修正要 cap 總長（例如 delay = min(index,2)*0.04、duration 0.2）
- 改正：activity-strip stagger 40ms / 220ms 每行，合規 → stagger 只作用頭 3 行，之後同時出（或 cap delay 80ms）
- 改正：Web 冇 tour 機制（grep data-tour / joyride / driver 零命中） → 唔好新寫 use-tour.ts；喺 tours.ts PAGE_TOURS 加 'conversation-tips'，pageTourFor 支援 '/app/agent/' prefix，沿用 toast nudge + Help menu 重播
- 改正：頁面冇傳 infoContent，Home 有（home-view.tsx:200），補回係零成本；`i` 快捷鍵開 info sidebar → 喺自訂 header 直接放 `InfoButton content={infoContent}`（components/ui/info-button.tsx），唔好靠 PageContainer；快捷鍵寫 ⌘I
- 改正：'Nothing publishes until you approve' hint 常駐 → 要新加，唔可以寫成現有
- 改正：variant-card.tsx 102 行、純 read-only、Preview popover :72-81 → status_now 加 Compare；Edit/Copy 喺 Compare 掣旁邊加
- 改正：Research 行：assistant body research ideas.py:264、progress stage=researched ideas.py:389 → 改行號
- 改正：Tour step 5：'The model pill shows who writes and what it costs' → 改成 'The model pill shows who writes; the cost appears on the strip when the run finishes'
- 改正：Tour step 4：blocker rows 'instead of stopping you' → 改寫文案
- 違反原則（已改）：Motion §5 總長 ≤300ms：spec 話 activity strip『合規』，但 10 行 × 40ms + 220ms 可到 580ms；plan RowReveal 淨改 40ms 仍然 440ms。兩個都要 cap。
- 違反原則（已改）：Capability honesty 同 tour copy 規則（tours.ts:6-8『no claims the product cannot keep』）：tour step 3 教 'Edit the text here'，但 Edit 未做；step 5 話 model pill 顯示 cost，其實冇。Tour 只可以講已 ship 嘅嘢。
- 違反原則（已改）：Remind, don't block：tour 設計為『首次入頁自動開始』，同現有 onboarding 慣例（tour-mount.tsx 只出 toast nudge，Welcome 有 Not now）唔一致，會遮住 composer；改為 nudge + Help menu。
- 違反原則（已改）：真數據先郁：step 6 Edit 流程忽略 apply 會變 proposedUpdate（ideas.py:513-518），會令 card 顯示嘅 text 同真正被改嘅 workspace variant 唔一致——等於畫面講大話。
- 違反原則（已改）：真數據先郁：'Research · N pages read' 放喺 live card 做『進行中』狀態唔準確——researched event 係 research 完成後、run 開始前先 emit（ideas.py:402,409），應該係『已讀』而唔係進度。
- 違反原則（已改）：Capability honesty：plan row 同 chip 用 capability level，但冇 DB row 時 server default 係 assisted_matrix()（oauth.py:201、channels.py:20）；要顯示 evidence 字串，唔可以淨係一粒 'Assisted' badge 當真驗證過。
- 違反原則（已改）：Info sidebar 『i 快捷鍵』同 nav Ideas shortcut `i i` 撞；真正係 ⌘I。
- 補上遺漏：RBAC：Cancel 掣冇 canEdit gating（viewer 403）；Edit / Retry / quick-reply / rename / archive / Approve use 要 `edit`；Approve all 要 `approve`（plan-card.tsx:114 已有）；Memory tab decide 只限 owner（proposal-card.tsx:43,125）；viewer 應該睇到 thread 但所有寫入掣隱藏或 disabled 加原因。access 喺 web/src/lib/auth/access.tsx（唔係 .ts）。
- 補上遺漏：Nav：/app/agent/[id] 唔喺 nav-config.ts，Create group 冇 active 狀態；breadcrumb（hooks/use-breadcrumbs.tsx）同 sidebar highlight Home 要處理。
- 補上遺漏：現有 onboarding 系統（features/onboarding/*）完全冇提；tour-mount.tsx:30 排除 /app/agent/、tours.ts:266 exact match，要改。
- 補上遺漏：Parallel session 正改緊 conversation-view.tsx / variant-card.tsx / composer.tsx / hooks.ts / types.ts / client.ts（git status M），行號已經漂移，Compare dialog 係新加。
- 補上遺漏：Apply 409 情況：'Sources or their policies changed…'（ideas.py:509）同 'Review the exact candidate'——Edit / Approve 要將呢個變 reminder + 'Draft again' + Copy，唔可以卡死。
- 補上遺漏：i18n / languages：composer 語言寫死 EN / 繁中（composer.tsx:15,113-126）、variant label `destinationLabel` 只識 繁中/EN、quick-reply 'Same idea, 繁體中文'，都要跟 docs/postriff-worldwide-languages-plan.md 嘅 per-channel locale 決定；UI copy 暫時英文，要列明 Stage 2 替換點。
- 補上遺漏：Mobile：MessageScroller 要有固定高度 container（PageContainer 係 flex-1），sticky composer + iOS keyboard（visualViewport）同 safe-area；Compare dialog 喺 375px 要 snap scroll（現有已處理）。
- 補上遺漏：Error：cancelRun 失敗冇 toast（`void api.cancelRun`）；useChannels 載入失敗時 chips / plan rows 嘅顯示；snapshot error 時 PlanCard 唔 render（`snapshot.data &&`）而冇任何訊息。
- 補上遺漏：Accessibility：live run card 要 aria-live='polite'；Jump to latest 掣要 label；tab 鍵次序 rail → thread → composer → inspector。
- 補上遺漏：Title 未載入 Skeleton：thread.data 已經帶 title（ideas.py:206 `**conversation`），所以 fallback 應該係 Skeleton 至 thread 返嚟，唔使等 conversations list。
