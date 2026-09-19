# 12 · Inbox

> Route：`/app/inbox` · Sidebar：Grow · 成熟度：未 set up · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**路徑更正**：`src/postriff_phase2/inbox.py` 唔存在，後端係 `src/postriff_phase2/audience.py`（docstring 1–5 行引 architecture §16）。

**Frontend（有）**
- Route page：`web/src/app/app/inbox/page.tsx:1-8` 只 render `<InboxView />`。
- View：`web/src/features/inbox/inbox-view.tsx`。`InboxView`（192–243）用 `useAudience()`（`web/src/lib/api/hooks.ts:59-62`，key `keys.audience` :16）+ `checkAccess(access, { permission: 'reply' })`（195）。Loading 條件係 `audience.isLoading || !data`（200）→ **query error 時永遠卡喺 `Skeleton h-64`，冇 error state**。Empty state（203–223，`data-tour='inbox-empty'`）列 `connection {id.slice(0,8)}… · comments {level}`，即係俾用戶睇 connection uuid；thread grid `xl:grid-cols-2`（226，`data-tour='inbox-threads'`），每卡 stagger 50ms cap 300ms（232，超過 motion 規則 40ms）；`data.limits`（238）。
- `ThreadCard`（46–190）：state 全部 component local（48–54）。`makeDraft(origin)`（62–76）call `api.draftReply`；`openPreview`（78–88）；`send`（90–104）approve 後 toast + 清 state，**冇 invalidate `keys.audience`**。Composer（121–162）：`Textarea maxLength=500`、「Suggest (labelled AI)」（144）、「Save my reply」（155）、「Review & send」（158）。Read-only 文案（163–167）只講 level，冇 evidence。
- **Approval bug**：Dialog（169–187）blockquote 顯示本地 `text`（177），但批准嘅係已儲存 draft（`preview.draftId`，text 喺 `draft_reply` 時寫入 DB）；textarea 喺 draft 儲存後仍可改（126–129 冇清 draft）→ 用戶改完字再 Review，Dialog 顯示新字、實際送舊字，違反 exact-text approval。
- API client：`web/src/lib/api/client.ts:213-230`。Types：`web/src/lib/api/types.ts:592-610`（`Thread`、`Audience`）。冇 mutation hooks；`useInvalidate` 喺 `hooks.ts:164`。
- Nav：`web/src/config/nav-config.ts:88-95`（Grow group :79），`access: { permission: 'reply' }`。呢個只過濾 sidebar / Cmd+K（`web/src/hooks/use-nav.ts:23`）；`InboxView` 冇傳 `access` 俾 `PageContainer`，所以冇 reply 嘅 member 直接開 URL 仍然讀得到，只係 composer 位顯示「You need the reply permission」。
- Tour：**已存在**。`web/src/features/onboarding/tours.ts:326-338` `inbox-tips` 一步，target `[data-tour="inbox-threads"]` / `[data-tour="inbox-empty"]` + heading。
- Motion 現況：`StatefulButton` + 一個自寫 `motion.div` stagger（`docs/postriff-motion-system.md:48`）。

**Backend（有）**
- Routes `src/postriff_phase2/hosted_app.py:398-410`：GET threads（401）、POST reply-drafts（402–404）、POST reply-preview（405–407）、POST reply（408–410）。
- `AudienceService.threads()`（`audience.py:47-56`）：最新 200 條（`ingested_at`），逐條 query `reply` capability（52，N+1），`replyAvailable = reply Direct AND member.allows('reply')`（53）；`capabilities` 只有 `connectionId + commentsRead`（54–55）；唔 join `pr_reply_drafts`。
- `draft_reply()`（58–76）：`require(edit)`（63）；`ai_fixture` 係固定字串（73–74），冇 model call，label `AI-suggested (deterministic preview)`（76）。
- `reply_preview()`（78–87）：冇 `require`，冇 check tombstoned。
- `approve_reply()`（89–102）：digest + confirmed 校驗、`require(reply)`（94）、Direct + providerAccountId、`draft→approved`、audit `reply.approved`（101）、note「Queued for the connector worker…」（102）。
- **RBAC 錯位**（`permissions.py:17-19`）：edit = owner/admin/editor；reply = owner 或 `can_reply`（非 viewer）。approver + can_reply 批得但寫唔到 draft；admin 冇 can_reply 寫得 draft 但送唔到；前端只 check reply。
- `send_approved()`（105–133）：Threads container → publish，outcome `submitted / uncertain / held`。**全 repo 冇 caller**；`hosted_worker.py:154-160` `tick()` 只行 publish jobs。
- `ingest_replies()`（31–44）：只 `threads` + `self.transport`；fields `id,text,username,timestamp`（37）；唔寫 `created_at_provider`；冇 tombstone writer；冇 pagination。唯一 caller 係 dev harness `scripts/postriff_dev_hosted.py:173-181`（:171 傳 `audience_transport`，:183 `on_verified`）。Production `runtime_from_environment`：`hosted_app.py:146` 冇 `audience_transport`、:151 `PostgresWorker(database, social=social)` 冇 `on_verified` → production 永遠 `not_supported`。
- Schema：`migrations/postriff/007_consumer_web_billing.sql:160-187`（`created_at_provider` :169、`tombstoned_at` :171、origin check 只 `manual/ai_fixture` :179、status set :181）；RLS :189-200 —— 所有 member（包括 viewer）可 select `pr_reply_drafts`。
- **Capability 覆寫（頭號 blocker）**：`oauth.py:172-188` `_capabilities` 每次 connect 由 fresh unsupported/assisted matrix 開始、只設 *requested* 嗰一項；`oauth.py:145-146` 再 upsert 全部 rows。即係為 `comments_read` reconnect 會將 `publish` 覆寫成 Unsupported/Assisted，`reply` 亦係 Unsupported。現時一個 connection 最多一個 publish/analytics/comments_read/reply 係 Direct → 「PostRiff 發佈嘅 post + 讀留言 + 覆」喺同一 account 結構上做唔到。
- Scopes：Threads `providers.py:124`（`threads_read_replies` / `threads_manage_replies`，冇 moderate）；Instagram `:151`。
- `oauth.channels()`（`oauth.py:191-201`）逐 connection 回 `capabilities.{level,evidence,verifiedAt}`（`types.ts:438-458`，level 包括 `Bridge`）；`useChannels()` `hooks.ts:49-52`。
- Tests：`tests/phase2/postgres_billing.py:143-148` 驗 empty state 誠實；`tests/test_postriff_billing.py:60-76` 用 FakeAudience 驗 routes；真 service draft→approve→send→receipt 冇測試。

**結論**：UI 骨架同 digest 合約方向啱，但 (1) capability matrix 覆寫令 comments + reply + publish 唔可以並存、(2) production 冇 ingestion、(3) approved reply 冇 worker 送、(4)「AI」建議唔係 AI、(5) Dialog 顯示嘅字可能唔係被批嘅字、(6) reload 後失去 reply 狀態、(7) error 卡 skeleton、(8) empty state 顯示 uuid、(9) draft/approve permission 錯位。(2)(3)(4)(5)(7) 直接違反 house rule 1。

## 1. Design specification（最新版）

**目的**：一頁睇晒 PostRiff 自己發佈嘅 post 底下嘅留言（只限 comments_read 係 Direct 嘅 connection），一次覆一條、每條有自己嘅 exact-text approval 同 receipt。同時誠實講：邊個 account 有被覆蓋、邊個冇、點解，同埋上次幾時真係 check 過。呢頁唔係 unified social inbox，唔做 bulk、唔做 auto-reply、唔做 moderation（除非 capability 真係 Direct）。Reply 唔 Direct 嘅 account 都唔會被擋：提供「Reply on {provider} ↗」click-through。

**Layout**：沿用 `PageContainer`（`web/src/components/layout/page-container.tsx:24`）：`pageTitle='Inbox'`、`pageDescription`、`infoContent`、`pageHeaderAction` = Sync cluster。Header 下面 **Coverage strip**（每個 connection 一粒 chip，`overflow-x-auto`）。主體 **two-pane**：≥1280px 左 list 360px + 右 detail flex-1，兩邊獨立 scroll（`min-h-0`）；1024–1279px 左 320px；<1024px 只顯示 list，揀 thread 用 `Sheet side='right'`（`web/src/components/ui/sheet.tsx`，transitions #07）開 detail。注意 `useIsMobile`（`web/src/hooks/use-mobile.ts`）斷點係 768px，1024px 要用 CSS `lg:` class 或新 `useMediaQuery`，唔好直接借用。375px：Sheet 全闊、filter Tabs 一行 `overflow-x-auto`、composer 掣 `flex-wrap`、composer `sticky bottom-0`。Gutter 由 PageContainer `px-4 md:px-6` 提供，冇橫向 page scroll。Info sidebar 保留 `infoContent` 並加「Which accounts feed this inbox」。Page-level primary =「Check for new comments」；composer primary =「Review & send」。URL state：`?thread={threadId}`、`?filter=unanswered`；workspace 切換時清走兩者同 local draft。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header + Sync cluster | 話俾人知數據幾新、可唔可以即刻 check | `pageHeaderAction`：`AnimatedBadge`（`sync.lastSyncAt` 有值 → neutral「Checked {relativeTime}」；`null` →「Never checked」；`availability==='unavailable'` → warning + API reason 原句）+ `StatefulButton`「Check for new comments」（loading「Checking…」→ success「Checked」，只喺 API 回應後轉）。API 回 `{checkedPosts, ingested, tombstoned, lastSyncAt, availability, reason?}`；toast 只講真數，例如「Checked 6 posts · 2 new comments」。Audience query 未返時 badge 用 Skeleton，唔顯示任何時間。 | 冇任何 comments_read Direct 嘅 connection → 掣 disabled + Tooltip 寫真原因；API 429 cooldown → 顯示 API 原句；reduced motion 下 badge 唔郁。 |
| Coverage strip | Capability honesty：逐 account 逐 capability 顯示，永不 blended | `useChannels()` join `audience.connections`。每粒 chip：`ChannelIcon`（`web/src/components/channel-icon.tsx:120`）+ account handle + 兩個 `LevelBadge`（`web/src/components/app/level-badge.tsx:17`，同 `web/src/features/channels/capability-chips.tsx` 同一套 vocabulary，包括 Bridge）：「comments · Direct」「reply · Unsupported」；hover / focus Tooltip 顯示 `evidence` + `verifiedAt`。唔好用 `components/marketing/capability-badge.tsx`（lowercase level、有 `local`，同 API 唔對應）。每粒 chip 尾有該 connection 嘅 `lastSyncAt`（null →「never checked」）。最後一粒「Manage channels ›」（transitions #24）。 | 冇 connection →「No account covered yet」+ link `/app/channels`；有 connection 但 comments 唔係 Direct → muted chip + evidence 原句。喺 capability 覆寫問題修好之前，唔可以寫「reconnect with comments enabled」呢類會搞壞 publish 嘅指示。channels query error → strip 顯示「Account coverage unavailable」+ Retry，唔可以當成冇 account。 |
| Thread list（左 pane） | 揀一條嚟覆；Unanswered 行先 | 頂部 motion `Tabs` segment（`web/src/components/motion/tabs.tsx:75`）：All / Unanswered / Replied / No longer returned，label 後 `DigitSwap`（`digit-swap.tsx:48`）顯示 `audience.counts.*`（後端全表 COUNT，唔係 200 cap 內數；counts 未返就唔顯示數字）。Row：`ChannelIcon size='xs'` + `@author` + 2 行 excerpt + 時間（`relativeTime(createdAtProvider ?? ingestedAt)`；用 ingestedAt 時 title 寫明「first seen」）+ status pill（`AnimatedBadge size='sm'`）+ post excerpt（前端用 `thread.providerPostId` match `useSnapshot()` jobs 嘅 `providerReference`，`types.ts:77`；match 唔到顯示 `post {providerPostId}`）。揀中行用 `SharedLayoutBg`（`shared-layout-bg.tsx:50`）。保留 `data-tour='inbox-threads'` 喺 list container。排序：provider 時間 desc，fallback ingested。 | Loading：3 行 `Skeleton`，冇文案。Filter 空：per-filter `Empty`（Unanswered 空 →「Nothing waiting for a reply」）。Error：inline `Alert` 顯示 `ApiError.message` + Retry。 |
| Thread detail（右 pane / Sheet） | 原 thread 先睇，之後先寫 | (1) 原留言 `MessageBubble align='start' variant='soft'`（`web/src/components/agents/message-bubble.tsx:89`）+ header（`@author · {provider} · formatDateTime`）+ 有 `permalink` 就「Open on {provider} ↗」；(2) Post context 小卡（同上 match 邏輯）+「Open in Queue ›」；(3) Reply history：每個 `thread.replies[]` 一個 `MessageBubble align='end'`，footer `AnimatedBadge` status + origin label（「Your reply」/「Starter line (not AI)」/「AI suggestion · {model}」）+ `relativeTime(updatedAt)`；(4) Composer；(5) Receipt。Tombstoned：頂部 Badge「No longer returned by {provider}」+ composer 收起。 | 未揀 thread（desktop）：右 pane `Empty`「Pick a comment on the left」。Sheet 關閉時清 `?thread`。 |
| Composer | 寫 / 儲 / 送，每步真狀態，按真 permission 分開 gate | `Textarea maxLength={500} rows=3`，右下 `DigitSwap` 顯示 `500 - text.length`。掣：(a) Suggestion —— `audience.suggestion.availability==='available'` →「Suggest a reply」+ label「AI suggestion · {model} · edit before sending」；否則「Insert a starter line」+ label「Starter line (not AI)」，永不叫 AI；(b)「Save my reply」（`StatefulButton` success「Saved」1.6s，沿用 `inbox-view.tsx:56-60` timer）；(c)「Review & send」。**Draft 同步規則**：textarea 內容 ≠ `draft.text` 時，(c) 會先自動 save 新 draft 再開 preview（或者提示「Save your changes first」），Dialog 永遠顯示 `preview.manifest.text`。Draft 存在時顯示 `Draft saved · {label} · {relativeTime}` +「Discard draft」。**Permission**：Suggest / Save 用 `checkAccess({ permission: 'edit' })`；Review & send 用 `{ permission: 'reply' }`。 | `replyAvailable===false`（capability 唔係 Direct）→ read-only 卡：「Replies are {replyLevel} for @{account}」+ evidence + `permalink` 有就「Reply on {provider} ↗」。冇 edit 但有 reply（例如 approver + can_reply）→「You can send replies others have drafted; drafting needs the editor role.」冇 reply 但有 edit →「You can draft replies; sending needs the reply permission from the workspace owner.」都冇 →「You can read comments here.」同一時間只有發起嗰粒掣 loading（沿用 `pending` 設計 :43-52）。 |
| Approval dialog | Exact account + thread + text 先送得 | `Dialog`（transitions #06）。Title = `preview.action`；body：account（ChannelIcon + handle）、「Replying to @author」+ 原留言 1 行、`preview.manifest.text` 全文 blockquote（唔係 local textarea）、`Digest {digest.slice(0,12)}…` + `LevelBadge replyLevel`。Footer：Cancel + `StatefulButton`「Approve & send」（loading「Approving…」）。成功後 dialog 收埋、history 多一個 bubble（status `approved`）、toast 顯示 API `note` 原句、invalidate `keys.audience` + `keys.audit`。喺 worker 未接好前，API note 唔可以講「Queued for the connector worker」。 | `replyLevel!=='Direct'` → 掣 disabled「Sending not available」+ evidence + 「Reply on {provider} ↗」click-through（唔係死路）。409（digest mismatch / already approved）→ toast API message + refetch。 |
| Receipt timeline | 每條 reply 一張 receipt，同 Queue 同一套 vocabulary | `Collapsible`「Receipt」（status 唔係 draft 先 default open）：列 `reply.events[]`（`at`、`state`、`message`），`providerReference` monospace 可 copy。文案全部 API 原句。保留 `data-tour='inbox-receipt'`。 | `uncertain`：warning + 原句，**冇 Resend**；`held`/`failed`：danger + message + link `/app/channels`；`cancelled`：neutral。 |
| Info sidebar | 解釋規則，唔阻人 | 保留 `inbox-view.tsx:25-35` 三節，第二節改為「A suggestion is labelled with what produced it (an AI model or a plain starter line) and is never sent on its own」；新增「Which accounts feed this inbox」：「Comments appear only for connections whose comments capability is Direct. Each capability shows its own level and evidence on the Channels page.」link `/app/channels`。 | 靜態。 |

- **Empty state**：只喺 `counts.all===0` 顯示（filter 空另計；query error 唔會入 empty）。保留 `data-tour='inbox-empty'`。`Empty` icon `Icons.inbox`；title「No comments yet」；description 逐 account 講真情況（`audience.connections` + `useChannels()`，顯示 handle 唔顯示 uuid）：每個 connection 一行「@handle · comments {level}」+ evidence。三個分支：(1) 冇 connection →「Connect an account」→ `/app/channels`；(2) 有 Direct 但未有 verified post →「Comments appear after PostRiff publishes and verifies a post on @handle.」+ link `/app/queue`；(3) 有 verified post 但 `lastSyncAt===null` →「Never checked」+「Check for new comments」。底部 `data.limits` 原句。所有文案通用，冇品牌或行業例子。
- **Loading**：唔用 page-level `isLoading`（會蓋住 header）。Coverage strip 3 粒 chip Skeleton；list 3 行 `Skeleton h-16`；detail 一塊 `Skeleton h-48`；全部 `ui/skeleton`（transitions #14），冇文字。Loading 只由 `isPending` 決定，唔再用 `!data`（避免 error 時卡住）。Mutation 期間只有發起嗰粒 `StatefulButton` 轉 loading。
- **Error**：Query error：header 照 render，主體 inline `Alert variant='destructive'`：`ApiError.message`（fallback「Could not load comments.」）+ Retry（`refetch`）。Channels query error：coverage strip 顯示 unavailable + Retry，唔當冇 account。Mutation error：Sonner toast 顯示 API message，textarea 內容保留。Sync error：badge warning + API reason，掣回 idle。403（例如 permission 喺 session 中途被收）：toast API message + refetch access。永不將 error 顯示成 0、空 inbox 或無限 skeleton。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁內容 | route mount / workspace 切換 | `.t-page-enter` 浮入（結構性） | web/src/app/app/template.tsx:13 + web/src/styles/transitions.css #08 | 否（純裝飾） |
| Thread list rows | list 首次載入 / filter 改變 | opacity 0→1、y 4→0，stagger 30ms、cap 300ms（`Math.min(index,10)*0.03`）；reduced motion → `initial:false` | web/src/features/queue/queue-view.tsx:311-316 寫法（取代 inbox-view.tsx:232 嘅 50ms） | 是 |
| 揀中 thread 嘅底色 | click / keyboard 移動 | 底色 layout-animate 滑到新行；reduced motion 直接跳 | web/src/components/motion/shared-layout-bg.tsx:50 | 是 |
| Filter Tabs indicator + counts | filter 切換；counts 由 API 更新 | segment pill 滑動；數字只喺 `audience.counts` 真變先滾 | web/src/components/motion/tabs.tsx:75 + digit-swap.tsx:48 | 是 |
| Coverage chip level badges | channels query 回應 / re-verify 後 level 改變 | level 改變時 badge 內容 swap | web/src/components/app/level-badge.tsx:17（配 motion/animated-badge.tsx:109 嘅 swap） | 是 |
| 「Check for new comments」掣 | click → API 回應 | idle → loading → success 1.6s → idle；badge 同步更新 `lastSyncAt` | web/src/components/motion/button/stateful.tsx:158 | 是 |
| Reply status badge（list pill + bubble footer） | refetch 見到 status 改變 | draft=neutral、approved=info、submitting=loading、submitted/verified=success、uncertain=warning、held/failed=danger、cancelled=neutral | web/src/components/motion/animated-badge.tsx:109 + queue-view.tsx:74-80 stateStatus 模式（抽去 features/inbox/reply-status.ts） | 是 |
| 新 reply bubble | 本 session 剛 approve 嘅 reply 出現 | pop-in 一次；refetch 帶返嚟嘅舊 reply 唔重播（session `Set<draftId>` gate） | web/src/components/agents/message-bubble.tsx:89 | 是 |
| Receipt 最後一步 | 本 session 內觀察到 status → verified | 播 success check 一次；mount 時已 verified 就靜態顯示 | web/src/components/ui/success-check.tsx（transitions #10，plan-card.tsx:18 同款） | 是 |
| Approval Dialog | Review & send | 開 / 收用 #06 token，收快過開（結構性） | web/src/components/ui/dialog.tsx（transitions #06） | 否（純裝飾） |
| Mobile detail Sheet | <1024px 揀 thread | 由右滑入，收快過開（結構性） | web/src/components/ui/sheet.tsx（transitions #07） | 否（純裝飾） |
| Textarea 餘額計數 | 每次輸入 | `500 - text.length` 逐位滾動 | web/src/components/motion/digit-swap.tsx:48 | 是 |
| Sidebar Inbox 未覆數 | `counts.unanswered` 由 0→n 或 n→0 | t-badge 彈入 / 縮走；query 未返或 error 唔 render（唔顯示 0） | web/src/components/layout/app-sidebar.tsx:102 NavCount（transitions #03）；:177 aria-label 要改成 per-item 文案 | 是 |
| Toast | mutation 成功 / 失敗 | transitions #22 開合，內容係 API 原句 | Sonner + transitions.css #22 | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /audience/threads（list） | api | 有 | src/postriff_phase2/hosted_app.py:400-401 → audience.py:47-56；client.ts:215；hooks.ts:59-62 | S |
| 2 | POST reply-drafts / reply-preview / reply | api | 有 | hosted_app.py:402-410 → audience.py:58-102；client.ts:216-230。缺口：reply_preview 冇 require、冇 tombstone check | S |
| 3 | OAuth capability matrix 改為 merge（reconnect 一個 capability 唔覆寫其他已 Direct 嘅 capability），或者一次 request 多個 capability | backend | 冇 | oauth.py:172-188 fresh matrix 只設 requested；oauth.py:145-146 upsert 全部 rows → comments_read reconnect 會令 publish 變 Unsupported/Assisted | M |
| 4 | Worker 送 approved replies（send_approved 有 caller） | backend | 冇 | audience.py:105-133 零 caller；hosted_worker.py:154-160 tick 只行 publish jobs；approve note（audience.py:102）係空頭承諾 | M |
| 5 | Production replies ingestion（audience_transport + on_verified） | infra | 冇 | 只有 scripts/postriff_dev_hosted.py:171,173-183；hosted_app.py:146 冇 audience_transport、:151 冇 on_verified | S |
| 6 | 手動 / 定期 re-sync + lastSyncAt | backend | 冇 | ingest_replies 只喺 on_verified 行一次；冇 sync endpoint；需要新 migration（下一個未用編號，現時 013）`pr_audience_sync` | M |
| 7 | threads() 回 replies[] + counts + connections（account/levels/evidence/lastSyncAt）+ sync + suggestion availability，去 N+1 | api | 冇 | audience.py:49-56 唔 join pr_reply_drafts、:52 N+1；types.ts:592-610 冇呢啲欄位 | M |
| 8 | Provider comment 時間 + permalink | data | 冇 | created_at_provider column 存在（007 sql:169）但 audience.py:42 唔寫；fields（:37）冇 permalink；需要 migration 加 column | S |
| 9 | Tombstone writer + preview/approve 拒絕 tombstoned thread | backend | 冇 | tombstoned_at（007 sql:171）同 UI badge（inbox-view.tsx:113）都有，但冇 writer；reply_preview/approve_reply（audience.py:78-102）冇 check | S |
| 10 | Cancel / discard reply draft endpoint | api | 冇 | status set 有 'cancelled'（007 sql:181）但 hosted_app.py:398-410 冇 route | S |
| 11 | Reply verification（submitted → verified） | backend | 冇 | send_approved 最多去到 submitted（audience.py:125） | M |
| 12 | 真 AI suggestion（workspace voice、model 名、billing、語言跟留言 / channel locale） | backend | 冇 | audience.py:72-74 固定字串；可用 model_runtime.py:84 ServerModelRuntime（_call :182）+ billing.py:58 reserve / :87 settle；origin check 要 migration（007 sql:179）；語言規則參考 docs/postriff-worldwide-languages-plan.md | M |
| 13 | 前端 mutation hooks + cache invalidation | frontend | 冇 | hooks.ts 冇 useDraftReply 等；inbox-view.tsx:90-104 冇 invalidate；可用 hooks.ts:164 useInvalidate | S |
| 14 | Approval Dialog 顯示 manifest.text + textarea/draft 同步 | frontend | 冇 | inbox-view.tsx:177 顯示 local text；:126-129 改字唔清 draft | S |
| 15 | Query error state（唔再卡 skeleton） | frontend | 冇 | inbox-view.tsx:200 `isLoading \|\| !data` | S |
| 16 | Channel capability matrix 可供前端 join | api | 有 | oauth.py:191-201 channels()；types.ts:438-458；hooks.ts:49-52 useChannels() | S |
| 17 | Level badge（API vocabulary） | frontend | 有 | web/src/components/app/level-badge.tsx:17；features/channels/capability-chips.tsx:4,24 | S |
| 18 | Nav gate 放寬 + composer 按 edit / reply 分開 gate | frontend | 冇 | nav-config.ts:94 `permission: 'reply'`；inbox-view.tsx:195 只 check reply；後端 draft require(edit) audience.py:63、approve require(reply) :94；permissions.py:17-19 | S |
| 19 | Two-pane / Sheet 版面 primitives | frontend | 有 | ui/sheet.tsx:116；motion/tabs.tsx:75；shared-layout-bg.tsx:50；agents/message-bubble.tsx:89（注意 use-mobile.ts 斷點 768px） | S |
| 20 | Thread → 原 post 對應（前端 match） | frontend | 冇 | Job.providerReference（types.ts:77）+ useSnapshot()（hooks.ts:39-42）data 已有，但 match 邏輯未寫；唔需要後端 | S |
| 21 | Tour 基建 + Inbox tour | frontend | 有 | web/src/features/onboarding/tours.ts:326-338 inbox-tips；inbox-view.tsx:203,226 data-tour inbox-empty / inbox-threads；只需擴充 steps 同加新 data-tour | S |
| 22 | Moderate（hide reply） | backend | 冇 | providers.py:124 Threads SCOPES 冇 moderate → oauth.py:185-187 永遠 Unsupported | L |
| 23 | Instagram comments | backend | 冇 | providers.py:151 有 scopes，但 audience.py:32 及 :114 hard-code threads | L |
| 24 | 後端測試 draft→approve→send→receipt（真 service + fake transport）+ RBAC 矩陣 | backend | 冇 | tests/phase2/postgres_billing.py:143-148 只驗 empty；tests/test_postriff_billing.py:60-76 只係 FakeAudience route test | M |

## 3. Features

### P0

- **Capability matrix merge：同一 account 可以同時 publish + comments_read + reply**：House rule 5 + 1。現時 reconnect 開 comments 會靜靜咁將 publish 降級（oauth.py:145-146,172-188）；唔修，Inbox 嘅前提（PostRiff 發佈嘅 post 底下留言、再用同一 account 覆）做唔到。
- **真 pipeline：production ingestion + worker 送 approved replies + verification**：House rule 1。approve 後 API 講「Queued for the connector worker」但冇 worker（audience.py:105-133 零 caller）；production 冇 transport，頁面永遠空。（depends on：Capability matrix merge）
- **Approval 誠實修正：Dialog 顯示 manifest.text、textarea 同 draft 同步、error 唔卡 skeleton**：Exact-text approval 係呢頁嘅核心承諾；而家可能批准同顯示唔一樣嘅字（inbox-view.tsx:177），error 時無限 loading（:200）。純前端、細改動，應該最早做。
- **Reply 狀態持久化 + receipt timeline + Unanswered / Replied filter（真 counts）**：reload 後用戶唔知覆咗未。PostRiff 嘅差異係每條 reply 一張 receipt，同 Queue 同一套 state vocabulary。（depends on：真 pipeline）
- **Coverage strip + 有 account 名嘅 empty state**：House rule 5。empty state 印 connection uuid（inbox-view.tsx:217）；oauth.channels() 已有 level + evidence，只欠 join。
- **「Check for new comments」手動 sync + 真 lastSyncAt**：Comments 多數喺 verify 之後先出現；一次性 on_verified ingestion 會長期滯後。Badge 顯示真時間，冇 polling 假象。（depends on：真 pipeline）
- **Suggestion 掣誠實化：先改名「Insert a starter line」，再接真 model**：House rule 1。ai_fixture 係固定句（audience.py:73-74），標籤卻叫 AI（inbox-view.tsx:144）。改名 S，接 ServerModelRuntime + billing M。
- **Permission 對齊：nav 所有 member 可入；Save/Suggest gate edit、Send gate reply，文案講清楚邊個做到乜**：Remind, don't block。nav-config.ts:94 將冇 reply 嘅 editor 喺 sidebar 收埋，但後端 draft 只要 edit；approver + can_reply 會撞 403。

### P1

- **Two-pane + mobile Sheet + 「Reply on {provider} ↗」click-through**：redesign doc §6.8（docs/postriff-consumer-saas-redesign.md:377）定咗 chat 模式；reply 唔 Direct 時唔阻人，送去原生 app 覆。（depends on：permalink 寫入）
- **Cancel approved-but-unsent reply（HoldActionButton）+ discard draft**：Schema 已有 cancelled；approve 同 worker claim 之間有窗口，同 Queue 長按取消一致。（depends on：真 pipeline）
- **Provider 時間 + tombstone（「No longer returned by provider」）**：而家用 ingestedAt 當留言時間；tombstone badge 有 UI 冇 writer。用字係「provider 唔再回」唔係「已刪除」。（depends on：re-sync）
- **Sidebar 未覆數 + Home NotificationStack「N comments waiting」**：Grow 頁回流入口；NavCount（app-sidebar.tsx:102）同 NotificationStack（home-view.tsx:301）已存在。數未返唔顯示 0。（depends on：counts 喺 API）
- **Thread ↔ 原 post 對應 + 「Open in Queue」**：info sidebar 承諾「Original thread first」（inbox-view.tsx:28）；前端 match providerReference，零後端改動。
- **Cron 自動 re-sync（bounded）**：手動 sync 嘅延伸；同一 sync function，同一 lastSyncAt。（depends on：手動 sync）

### P2

- **Keyboard 導航（j/k/Enter/r）**：高量留言時快啲；但要先確認唔同 kbar 兩鍵 shortcut 撞，textarea focus 時唔觸發。
- **Hide reply（moderate）逐條 approval**：要 scope + provider review，§1.1 要 evidence 先升級；之前一律顯示 moderate Unsupported。
- **Instagram comments**：providers.py:151 有 scopes，但 ingest / send hard-code Threads；等 production review。
- **Saved replies（workspace 通用 snippets）**：對任何行業都有用；唔預載行業例子。
- **Comment → 新 post（交去 /app/ideas 作 source）**：source-grounded 路徑；要等 Ideas 支援 comment source type。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明白三件事：(1) 呢度係「PostRiff 發佈咗嘅 post 底下嘅留言」，唔係全網 inbox；(2) 只有 comments capability 係 Direct 嘅 account 先會出現 —— coverage strip 一眼睇到邊個 account 有、邊個冇、點解；(3) 每條 reply 逐條批准，冇嘢自動送。教法：page description 一句（「Comments on posts PostRiff published, from accounts whose comments capability is Direct. Reply one at a time; each reply has its own approval and receipt.」）、coverage strip 永遠喺頂、sync badge 顯示真時間、empty state 逐 account 講真情況同下一步。Tour 沿用現有 `web/src/features/onboarding/tours.ts` 嘅 `inbox-tips`，擴充 steps。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `data-tour="inbox-coverage"（Coverage strip container，新增）` | Which accounts feed this inbox | Each account shows its comments and reply capability separately, with the evidence behind each level. Nothing here is a blended “connected” tick. |
| 2 | `data-tour="inbox-sync"（header「Check for new comments」StatefulButton，新增）` | Check when you want | PostRiff reads replies to posts it published. The time shown is the last real check; press to check again now. |
| 3 | `data-tour="inbox-threads"（thread list container，現有 inbox-view.tsx:226，重建時保留）；fallback data-tour="inbox-empty"（現有 :203）` | Replies you approve one at a time | Comments appear for accounts whose comments capability is Direct. Unanswered means no reply has been approved yet; a saved draft still counts as unanswered. |
| 4 | `data-tour="inbox-composer"（composer wrapper，新增）` | One reply, one approval | Write your own reply or insert a labelled suggestion, edit it, then review the exact account, thread and text before anything is sent. |
| 5 | `data-tour="inbox-receipt"（Receipt Collapsible trigger，新增；只喺有 reply 時存在，tour 要可以 skip）` | Every reply keeps a receipt | Each step is recorded with the provider’s reference. If a step is uncertain, PostRiff says so and never resends on its own. |

**Empty state 教咩**：三個真分支，全部讀 API：冇 connection → 去 Channels 連接；有 Direct 但未有 verified post →「Comments appear after PostRiff publishes and verifies a post on @handle」+ link Queue；有 verified post 但從未 check →「Never checked」+ Check 掣。每個分支逐 account 列 level + evidence，底部係 API limits 原句。Capability 覆寫問題修好之前，唔教用戶「reconnect 開 comments」。用字通用，唔提任何行業或品牌。

## 5. Next steps（按次序）

1. **即時誠實修正（純前端，細）：Dialog blockquote 改顯示 `preview.manifest.text`；textarea 改字時若 ≠ `draft.text` 就清 draft 或 Review 前自動 save；loading 改 `isPending`，error 顯示 inline Alert + Retry；「Suggest (labelled AI)」改「Insert a starter line」；empty state 用 `useChannels()` account handle 代替 uuid；stagger 改 30ms；approve 後 invalidate `keys.audience`。後端同步改 label `'Starter line (not AI)'`。保留 data-tour inbox-threads / inbox-empty。**（effort S）  
   檔案：`web/src/features/inbox/inbox-view.tsx:176-178,200-223,232,90-104,144；src/postriff_phase2/audience.py:76`
2. **Capability matrix merge：`_capabilities` 讀返現有 `pr_channel_capabilities` rows 做 base，只更新 requested capability（或 `oauthStart` 接受 capability list，一次 request 多組 scopes）；audit 記錄 before/after level；測試「publish Direct → reconnect comments_read → publish 仍 Direct」。**（effort M）  
   檔案：`src/postriff_phase2/oauth.py:79-90,140-150,172-188；web/src/features/channels/connect-sheet.tsx:132；web/src/lib/api/client.ts:168；tests/phase2（新 case）`
3. **Worker 送 reply：`PostgresWorker` 加 `audience=` kwarg + `reply_step()`（`SELECT … FROM pr_reply_drafts WHERE status='approved' ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED` → `send_approved`），`tick()` 行完 jobs 再行最多 5 條 replies；加 reconcile：`submitted` 超過 30s 就讀返 `provider_reference` → `verified`，失敗保持 `uncertain`（唔 resend）。新測試用 fake transport 行 draft→approve→submitted→verified 同 container 失敗→uncertain。**（effort M）  
   檔案：`src/postriff_phase2/hosted_worker.py:26-34,154-160；src/postriff_phase2/audience.py:105-133；src/postriff_phase2/hosted_app.py:151,326-332；scripts/postriff_dev_hosted.py:183；tests/phase2/postgres_audience.py（新）`
4. **Production 接線：`runtime_from_environment` 傳 `audience_transport` 俾 `HostedWorkspaceService`，建 `on_verified` 同 dev harness 一樣 call insights + `service.audience.ingest_replies`（只對 comments_read Direct）。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:130-152；參考 scripts/postriff_dev_hosted.py:171-183`
5. **新 migration（下一個未用編號，現時 013，commit 前 re-check 並行 session）：`pr_audience_threads` 加 `permalink text`；新表 `pr_audience_sync(workspace_id, connection_id, last_synced_at, last_result jsonb)` + RLS 同 007；`pr_reply_drafts.origin` check 加 `ai_model`。`ingest_replies` 寫 `created_at_provider` 同 `permalink`；新 `sync()`：每 workspace 60s cooldown（後端 429 + 剩餘秒數）、30 日內 verified Threads jobs 最多 20 個、response 200 而缺席先標 `tombstoned_at`。`reply_preview` / `approve_reply` 拒絕 tombstoned thread。**（effort M）  
   檔案：`migrations/postriff/013_audience_sync.sql（新）；src/postriff_phase2/audience.py:31-44,78-102；tests/phase2/rls.sql`
6. **`threads()` 重寫：一次 join capabilities（去 N+1）、`LEFT JOIN LATERAL` replies、全表 `counts`、`connections[]`（account 由 snapshot channels、commentsRead/reply level+evidence、lastSyncAt）、`sync`、`suggestion{availability, model?}`。加 routes `POST /audience/sync`、`POST /audience/reply-drafts/{id}/cancel`（draft 要 edit；approved 要 reply），audit `reply.cancelled`；`reply_preview` 加 `require(read)` 以上一致性。**（effort M）  
   檔案：`src/postriff_phase2/audience.py:47-102；src/postriff_phase2/hosted_app.py:398-410；tests/phase2/postgres_audience.py；tests/test_postriff_billing.py:60-76`
7. **真 AI suggestion：origin `ai_model`，`ServerModelRuntime._call` 帶 workspace voice/context，語言跟留言或 channel locale（按 worldwide-languages plan），`billing.reserve`→`settle`，回 `{text, label: 'AI suggestion · {model}', model}`；冇 key 時 `suggestion.availability='unavailable'`，前端自動用 starter line。**（effort M）  
   檔案：`src/postriff_phase2/audience.py:58-76；src/postriff_phase2/model_runtime.py:84,182；src/postriff_phase2/billing.py:58,87；docs/postriff-worldwide-languages-plan.md`
8. **前端 types / client / hooks：`Thread` 加 `createdAtProvider|null, permalink|null, replies[]`；`Audience` 加 `counts, connections, sync, suggestion`；client 加 `syncAudience`、`cancelReply`；hooks 加 `useDraftReply / useReplyPreview / useApproveReply / useCancelReply / useSyncAudience`（`useMutation`，invalidate `keys.audience`，approve 亦 invalidate `keys.audit`）。**（effort S）  
   檔案：`web/src/lib/api/types.ts:592-610；web/src/lib/api/client.ts:213-230；web/src/lib/api/hooks.ts:16,59-62,164`
9. **重建頁面：`inbox-view.tsx`（layout、URL state、workspace 切換清 state、<1024px Sheet）、`coverage-strip.tsx`（useChannels + components/app/level-badge）、`thread-list.tsx`（motion Tabs + DigitSwap + SharedLayoutBg）、`thread-detail.tsx`（MessageBubble、post match）、`reply-composer.tsx`（edit / reply 分開 gate、draft 同步、click-through）、`reply-receipt.tsx`、`reply-status.ts`。擴充 `tours.ts` inbox-tips 至 5 步並加新 data-tour。跑 `npm run lint` + `npx tsc --noEmit`；browser 驗 1440 / 768 / 375、light / dark、reduced motion。Dev harness Threads 係 live：唔好撳 Approve & send。**（effort L）  
   檔案：`web/src/features/inbox/*；web/src/features/onboarding/tours.ts:326-338；web/src/app/app/inbox/page.tsx 不變`
10. **Nav gate：Inbox item 改 `access: { permission: 'read' }`；Roles 頁說明 viewer 可以睇留言同同事草稿（RLS 已容許），由 owner 決定係咪接受。**（effort S）  
   檔案：`web/src/config/nav-config.ts:88-95；web/src/lib/auth/permissions.ts:40-46`
11. **回流入口：sidebar `counts` 加 `/app/inbox`（只喺 `audience.data` 存在先加，唔用 `?? 0`），aria-label 改 per-item（Inbox =「comments waiting for a reply」）；`useAudience` 加 `staleTime: 60_000`；Home NotificationStack n>0 先出「{n} comments waiting for a reply」→ `/app/inbox?filter=unanswered`。**（effort S）  
   檔案：`web/src/components/layout/app-sidebar.tsx:128-130,177,184；web/src/features/agent/home-view.tsx:301；web/src/lib/api/hooks.ts:59-62`
12. **Docs：motion inventory Inbox 一行更新；redesign doc §6.8 指向本 spec；competitive research §8 決定 Inbox plan gating（建議讀留言所有 plan、AI suggestion 行 Assist 額度）。**（effort S）  
   檔案：`docs/postriff-motion-system.md:48；docs/postriff-consumer-saas-redesign.md:377；docs/postriff-competitive-research-20260916.md:279-282`

## Risks

- Capability 覆寫：喺 oauth.py:172-188 merge 修好之前，任何「reconnect with comments」文案都會令用戶 publish 降級；step 2 必須先於 pipeline 上線。
- Threads 生產環境：comments_read / reply 要 adapter production_reviewed 先 Direct（oauth.py:185-187）；未 review 前 coverage strip 必須顯示 Unsupported +「Awaiting provider review」，唔可以顯示 pending / coming soon。
- Threads API 細節未喺 repo 驗證：replies pagination、permalink 係咪 replies fields 可用、reply 發佈 quota。實作 step 5 前對照官方 docs 並寫入 evidence。
- Worker 冪等性：container 建咗但 publish 失敗留 uncertain，UI 唔提供 Resend；reconcile 要用 provider_reference 先升 verified。
- Sync 成本同濫用：cooldown 喺後端執行；cron 版本 bounded。
- threads() N+1（audience.py:52）：200 條打 200 次 DB，重寫必須一次 join。
- 「AI」標籤：真 model 接好之前任何寫住 AI 嘅字都要改走（step 1 先做）；接入後消耗 Assist 額度，要同 billing 顯示一致。
- Tombstone 語義：可能係刪除、隱藏、分頁或暫時錯誤；只喺 response 200 標記，唔刪 reply receipts。
- RBAC：draft 要 edit、send 要 reply；composer 文案要準確講邊個做到乜，否則 approver + can_reply 會以為係 bug。Nav 放寬後 viewer 見到留言同未送草稿（RLS 已容許），要同 owner 講清。
- Migration 編號：並行 session（例如 worldwide languages Stage 2）可能同時用 013，commit 前 re-check。
- 另一個 session 同時改 web/src：前端重建（step 1、9）要先協調，commit 時 stage by path。
- Dev harness Threads 係 live provider：驗證 send 流程唔好喺 harness 撳 Approve & send；用 tests/phase2 fake transport。
- Keyboard shortcut（j/k/r）可能同 kbar 兩鍵 sequence 撞，已降 P2。

## 覆核記錄

- 改正：冇 tour 系統（web/src grep data-tour|useTour 零結果） → 改為：tour 基建已存在，Inbox 已有一步 tour；重建頁面時要保留 inbox-threads / inbox-empty 兩個 target，新增步驟加入 tours.ts 嘅 inbox-tips
- 改正：Tech req「Tour 基建（data-tour targets + 共用 tour component）」exists:false, effort M → exists:true；只需要擴充 inbox-tips steps，effort S
- 改正：Approval contract 係好嘅（exact-text digest） → Dialog 必須顯示 preview.manifest.text；textarea 內容同 draft.text 唔一致時 Review & send 要先重新 save 或者 disable 並提示
- 改正：useInvalidate 喺 hooks.ts:85；step 6 引 hooks.ts:85-92 → 改為 hooks.ts:164
- 改正：冇 reply flag 嘅 editor 連睇留言都唔得 → 改為：editor 喺 sidebar 搵唔到 Inbox，但直接開 URL 可以讀
- 改正：Tests 只有 tests/phase2/postgres_billing.py:146-148 驗 empty state → 補上 test_postriff_billing.py:70 route-level fake test
- 改正：LevelBadge 喺 web/src/features/channels/channels-view.tsx:152；或 components/marketing/capability-badge.tsx:59 → 改用 web/src/components/app/level-badge.tsx:17 + capability-chips.tsx 模式
- 改正：Tech req「Thread → 原 post 對應」exists:true（前端 match Job.providerReference） → exists:false，effort S，evidence 寫「data 已有，match 未寫」
- 違反原則（已改）：House rule 1（真數據）：現有 inbox-view.tsx:200 query error 時永遠顯示 skeleton（假 loading），spec status_now 冇指出；corrected spec 加入。
- 違反原則（已改）：House rule 1 / exact approval：inbox-view.tsx:177 Dialog 顯示 local textarea text 而唔係被批准嘅 draft text，spec 反而稱讚 approval contract 完整。
- 違反原則（已改）：House rule 4（motion）：現有 stagger 50ms（inbox-view.tsx:232）超過 40ms；spec 有換，但冇列為違規。Coverage chip badge swap、sidebar NavCount 動畫都要 useReducedMotion，spec 只喺 header 提過。
- 違反原則（已改）：House rule 5（capability honesty）：spec 建議 reuse marketing/capability-badge.tsx，佢嘅 level vocabulary（direct/assisted/local/unsupported）同 API（Direct/Assisted/Bridge/Unsupported）唔一致，會令 level 顯示錯；要用 components/app/level-badge.tsx。
- 違反原則（已改）：House rule 5：spec 冇發現 oauth.py:145-146,172-188 每次 connect 只設一個 requested capability 並覆寫其他 → reconnect 開 comments 會令 publish 變 Unsupported；spec 叫用戶『reconnect with the comments capability』會靜靜咁搞壞 publish，UI 文案等於誤導。
- 違反原則（已改）：House rule 2（remind, don't block）：spec 嘅 Sync 掣喺冇 Direct connection 時 disabled 可以接受（冇嘢可做），但 Approval Dialog「Sending not available」要同時提供 click-through「Reply on {provider} ↗」，唔好喺 Dialog 死路一條；corrected spec 已補。
- 違反原則（已改）：House rule 3（general）：spec 文案大致通用；但 sidebar NavCount aria-label 寫死「waiting for approval」（app-sidebar.tsx:177），Inbox 用會變錯字，要改成 per-item label。
- 違反原則（已改）：House rule 1：step 9 `audience.data?.counts.unanswered ?? 0` —— query 未返或 error 時會顯示 0（Unavailable 變 0），應該唔 render NavCount。
- 補上遺漏：OAuth capability 覆寫問題（oauth.py:145-146,172-188）：一個 connection 無法同時 publish + comments_read + reply Direct；呢個係 Inbox 真 pipeline 嘅頭號 blocker，要先改成 merge 或一次 request 多個 capability。
- 補上遺漏：RBAC 矩陣：draft 需要 edit（owner/admin/editor），approve 需要 reply（owner 或 can_reply 非 viewer）；approver+can_reply 寫唔到 draft、admin 冇 can_reply 送唔到。Composer 要按兩個 permission 分開 gate（Save/Suggest 用 edit，Review & send 用 reply），並講清楚原因，唔係一刀切。
- 補上遺漏：Viewer：RLS 俾 viewer 讀 pr_reply_drafts（包括未送 draft 內容）；nav 放寬後 viewer 會見到同事草稿，要決定係咪 OK。
- 補上遺漏：現有 tour（features/onboarding/tours.ts:326 inbox-tips）同 data-tour inbox-threads / inbox-empty 要保留或遷移。
- 補上遺漏：Dialog 顯示嘅 text 必須係 manifest.text；textarea 同 draft 唔同步時嘅處理。
- 補上遺漏：Error state：現有 query error 卡 skeleton。
- 補上遺漏：reply_preview / approve 冇 check tombstoned，tombstone writer 做好之後要一齊補。
- 補上遺漏：Languages：reply 冇 language 欄位；thread 可能係任何語言；Suggestion 要跟 worldwide-languages plan（docs/postriff-worldwide-languages-plan.md）按 channel locale 或留言語言生成，UI 文字仍然係 English。
- 補上遺漏：useIsMobile 係 768px breakpoint，唔係 1024px；layout 斷點要對齊現有 hook 或新增 media query。
- 補上遺漏：Plan gating（Studio vs Assist）同 AI suggestion 行 billing 額度嘅 UI 顯示。
- 補上遺漏：Workspace 切換時要清 ?thread 同 local draft state。
- 補上遺漏：並行 session 可能搶 migration 013 編號。
