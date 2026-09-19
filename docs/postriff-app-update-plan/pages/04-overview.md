# 04 · Overview

> Route：`/app/overview` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

Route：web/src/app/app/overview/page.tsx:1-8 直接 render `OverviewView`（web/src/features/overview/overview-view.tsx:144）。`/app` 本身係 agent chat Home（web/src/app/app/page.tsx:9 註明 dashboard 已搬去 /app/overview）。Sidebar entry 喺 web/src/config/nav-config.ts:21-27（Create group，icon `dashboard`，shortcut o o，冇 access key，所有 member 可見）。

資料流（全部真 API，冇 fixture）：
- `useSnapshot()` hooks.ts:39 → client.ts:134 `GET /api/workspaces/{w}` → hosted_app.py:459-462 → hosted.py:541 `get()` → repository.get hosted.py:124 + `present()` hosted.py:182。Snapshot 包 `state.phase2.jobs / reviews / channels`（types.ts:144-151，channels 帶 `displayState`）、`state.speaker.activeRevision`、`state.variants`、`state.workspace.sample`（types.ts:179-189）。
- `useUsage()` hooks.ts:44 → client.ts:151 `GET /api/workspaces/{w}/usage` → hosted_app.py:389-390 → hosted.py:316-322（ledger.usage_view + billing.lifecycle + billing.availability）。Type：Entitlement types.ts:489（writingBatchesRemaining :491、resetsAt :496）、SubscriptionView :501（currentPeriodEnd :505）、Usage :540-556（lifecycle :555）。
- `useChannels()` hooks.ts:49 → client.ts:162 `GET /api/workspaces/{w}/channels` → hosted_app.py:411 → oauth.py:194-201（每個 connection 嘅 capability matrix 由 `pr_channel_capabilities` 讀，providers 帶 `productionReviewed`）。`connectionState` 詞彙喺 channels.py:11；ChannelView types.ts:445-457（connectionState :450、expiresAt :454）。
- `useAudit()` hooks.ts:74 → client.ts:245 `GET /api/workspaces/{w}/audit` → hosted_app.py:465-466 → hosted.py:929-932（`ORDER BY at DESC LIMIT 200`，冇 pagination、冇 `since`）。AuditEvent types.ts:720-727 有 `id` / actor / subject / meta。Event kinds（grep audit() 呼叫）：workspace.created、channel.connected/disconnected/verified、oauth.started/denied/rejected、invitation.created/accepted/declined/revoked、member.left/removed/updated、mfa.enabled/disabled、session.revoked/revoked_others/alerted、billing.checkout_started/portal_opened、data.exported/diagnostics、reply.approved、memory.egress_decided（hosted.py:157）、research.egress_decided（:159）。

已起好嘅 sections（要保留）：
1. GettingStarted（getting-started.tsx:23-82）：4 步（voice → channel → draft → approve）全部讀真 state（:29-32），4 步齊就 return null（:35），用 beUI `TodoList`（agents/todo-list.tsx）`spinActive={false}`，已有 `data-testid='getting-started'` 同 `data-tour='getting-started'`（:66）。
2. 四張 StatCard（overview-view.tsx:266-302，grid div :265 已有 `data-tour='overview-stats'`；components/app/stat-card.tsx:17-45，`value: ReactNode` :9，number 時用 `NumberTicker` :26）：Scheduled（PRE_FLIGHT ∪ IN_FLIGHT，:155）、Published · 30 days（DONE = published+verified，用 verification.at 或最後 event，:156-160）、Writing batches left（entitlement，:280-291）、Connected channels（:292-302，hint 分 direct / assisted）。
3. Needs your attention（:306-364）：7 類 rule（voice :173、past_due :183、reconnect :193-204、needs_review :205、trial ≤5 日 :215、provider 未 production-reviewed :225、零 channel :236），`AnimatePresence mode='popLayout'` + `layout='position'`，reduced-motion 全部處理（:323-346）。
4. Channels card（:366-397）：每條 connection 得 platform、account、`LevelBadge`（publish level，level-badge.tsx:10-11 將 Bridge 顯示為 Local）。
5. PublishingActivity（:71-142）：`HeatCalendar`（components/charts/heat-calendar.tsx），只計 DONE jobs，weeks 由 ResizeObserver 量（8–26 週，PITCH 20px），`jobs === null` 時顯示「unavailable」而唔係 0（:108, :124-125）。
6. Recent activity（:401-425）：audit 頭 8 條，只顯示 kind + relativeTime，link 去 /app/workspace/audit。
7. Info sidebar 內容（:32-50）三段：Honest numbers / Direct·Assisted·Local / Nothing publishes without you。
8. Header action「New idea」→ /app/ideas?new=1，gate 住 `checkAccess(access, {permission:'edit'})`（:248, :256-260；checkAccess 喺 web/src/lib/auth/access.tsx:69）。

已存在但 Overview 未用嘅 infra（另一 session 嘅 untracked WIP，git status `??`）：
- Onboarding：web/src/features/onboarding/ — tours.ts（`WELCOME_TOUR` 有 overview step :137-143 target `[data-testid="getting-started"]` / `[data-tour="overview-stats"]`；`PAGE_TOURS` 有 `overview-tips` :280-294 一步）、tour-overlay.tsx（motion + useReducedMotion）、store.ts（localStorage progress，註明 `PATCH /api/me` onboarding field 係將來 seam）、use-tour-context.ts（TourCtx 讀真 snapshot / channels / access）、help-menu.tsx（Take the tour / Tips for {page} / Reset tips）。`TourMount` 已 mount 喺 web/src/app/app/template.tsx:15，`HelpMenu` 喺 layout/header.tsx:44。
- Channel state：web/src/lib/channels/state.ts — `ATTENTION_STATES`、`needsAttention(channel, now, heldJobs)`、`attentionSentence()`、`expiringSoon()`（7 日）、`channelBadge()` → `{label, status: AnimatedBadgeStatus}`、`channelCounts()`、`isConnected()`、`disconnectedByCustomer()`，註明供 Channels / Overview / profile 共用。
- Preferences：web/src/lib/preferences.tsx `usePreferences()` / `useTimeZone()`（:67-75）讀 profile timeZone / locale（GET /api/me preferences，types.ts:664）；hosted.py:592-606 `PATCH /api/me` 接受 displayName / timeZone / locale / alertNewDevice；lib/time.ts formatDate / relativeTime 已跟 profile。
- Calendar 已有 `?date=` query param（calendar-view.tsx:141-145，nuqs `useQueryStates`）。

已知缺口（有 file:line 證據）：
- 真數據違規：snapshot 或 channels error 時 `snapshot.data` undefined → `jobs = []`（:153）→ Scheduled / Published 兩張 StatCard 顯示 0（:268, :275），Connected channels 顯示 0（:294）；而且 `!channels.isLoading && connected.length === 0`（:236）會喺 channels error 時錯誤彈「Connect your first channel」。Query `isError` 完全冇讀。PublishingActivity 有處理（:108），StatCard 冇。
- 「Scheduled」混咗 in-flight（submitting/provider_accepted/uncertain）入去，但 hint 寫「Waiting for the approved time」（:270）。
- 「Published · 30 days」footer 寫「Only receipts the provider confirmed count」（:278），但 DONE 包含 `published`（store.py:19 將 `published` 列為 IN_FLIGHT，`verified` 先係 TERMINAL receipt :18；outcomes.py:20 兩者都要 providerReference）。Live Island 將 `published` 當 PUBLISHING（live-island.tsx:23），Queue 嘅 DONE 只計 `verified`（queue-view.tsx:33，tab label 'Verified'）。四處口徑唔一致。
- `held` jobs（store.py:426、hosted_worker.py:127）唔喺任何 set 入面：Scheduled 唔計、attention 唔提。
- Attention 同 Home 重複而且來源唔同：Home（features/agent/home-view.tsx:107-122）用 snapshot `channels[].displayState`（store.py:77-84：Connect / Reconnect / Finish setup / Ready for posting）；Overview 用 /channels 嘅 `connectionState`（:194）。同一個「Reconnect」可以喺兩頁出現唔同結果。
- Attention 冇按 access 過濾：voice → /app/workspace/brand（edit）、billing → /app/account/billing（owner）、reconnect → /app/channels（reconnect 要 manage_connections）；viewer 會見到撳唔入嘅 action。
- 冇「Next up」：Live Island 已經有 `readStatus()` 計下一個 approved slot（live-island.tsx:98-120，讀 `manifest.timing.utc`，TICK_MS 30_000 :30，failed 24h :105-107），但係 module-private，Overview 冇用。
- Recent activity 冇 actor / subject / 連結，key 用 `kind-at-index`（:414）雖然 AuditEvent 有 `id`（types.ts:721）；「Full audit log」link（:421）對所有 role 顯示，但 nav-config.ts 將 /app/workspace/audit gate 為 role admin。
- Channels card 冇顯示 `connectionState` / `expiresAt`；只有 publish level。lib/channels/state.ts 已有 badge / expiry helper 未接。
- Trial 倒數用 `entitlement.resetsAt`（:170），同 features/billing/billing-view.tsx:107 一致；billing.py:51-55 trial 時 resets_at 同 current_period_end 都寫 pr_trials.expires_at，所以 trial 期間兩者相同（paid plan 時 resetsAt 係 quota reset）。
- Sample workspace（`state.workspace.sample`，types.ts:180；hosted.py:188-189 mutation 一律 403）UI 冇讀，「New idea」照出。
- Tour：infra 已有（見上），但 overview-tips 只得一步，Overview 只有兩個 data-tour id（getting-started、overview-stats）。
- web/package.json 只有 lint / typecheck / format，冇 unit / e2e；web/ 冇 *.test.*；tests/test_postriff_consumer_web.py 冇 overview 相關 test。
- 後端冇 worker heartbeat（只有 per-job lease heartbeat store.py:525；hosted_worker.py `tick()` :154 唔記錄時間），所以任何「queue 有人睇緊」嘅指示都冇真數據支持。
- Motion 現況：page enter 用 `.t-page-enter`（app/app/template.tsx:13；transitions.css:252）、StatCard NumberTicker（0.9s/digit、0.04 stagger）、attention AnimatePresence、`t-learn` chevron（:393, :421；transitions.css:425-446）。Recent activity 同 Channels list 冇 motion；GettingStarted 嘅「N of 4 done」係 plain text（getting-started.tsx:70-72）。`.t-stagger-line`（transitions.css:377-386）係 500ms/行 + 40ms stagger + blur（:123-126），8 行 ≈ 780ms，唔適合 app 列表。

## 1. Design specification（最新版）

**目的**：答三個問題：而家有咩會出街（幾時、去邊）、有咩只有我先決定到、我個 plan 仲剩幾多。每個數字都係 ledger / receipt / capability matrix 嘅真值；讀唔到就寫 Unavailable，永遠唔變 0。Overview 係「狀態頁」，Home（/app）係「開工頁」——Overview 唔放 composer，Home 唔放 heat calendar。所有時間用 profile time zone（useTimeZone()），同 Calendar / Queue 一致。

**Layout**：保留現有 PageContainer（title 'Overview'、description、infoContent、header action 'New idea'）。內容由上至下：(1) GettingStarted card（四步齊就消失，現狀不變）；(2) Stats row：4 張 StatCard，`grid-cols-1 md:grid-cols-2 lg:grid-cols-4`（現狀，div 已有 data-tour='overview-stats'）；(3) 主 grid `lg:grid-cols-7`：左 `lg:col-span-4` = 新「Next up」card（今個星期 7 日 strip + 下一個 approved slot）；右 `lg:col-span-3` = Needs your attention（由現時 col-span-4 縮做 3）；(4) 第二行：左 `lg:col-span-4` = Publishing activity（HeatCalendar，由 col-span-7 縮，ResizeObserver 會自動量少啲週）；右 `lg:col-span-3` = Channels card；(5) 第三行 `lg:col-span-7` = Recent activity。Primary action 維持 header 嘅「New idea」（edit permission），sample workspace 時 disabled + tooltip「Sample workspace is read-only」。Info sidebar（右邊 22rem，鍵 i，ui/infobar.tsx:24-27）沿用 :32-50 三段，加第四段「Next up counts」：「Only approved jobs with a time the worker can read appear here, in your profile time zone. Drafts waiting for approval are listed under attention, not here.」

Responsive：375px — 一欄，順序 GettingStarted → Stats（每張全闊）→ Next up → Attention → Publishing activity（HeatCalendar `max-w-full`，MIN_WEEKS 8 × PITCH 20 = 160px + label，唔會爆）→ Channels → Recent activity；7 日 strip 改為橫向 scroll-snap（`overflow-x-auto snap-x`），每日格最少 44px 闊（touch target），gutter 16px；Attention Alert 內 button 最少 44px 高；Recent activity 每行 subject 最多兩行 line-clamp。768px — Stats 2×2，主 grid 仍然一欄，Next up 嘅 7 日 strip 一行放得落。1440px — 上述 7 欄 grid，HeatCalendar 大約 16–18 週。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Get set up (GettingStarted) | 首次用戶由空 workspace 去到第一個 scheduled post 嘅四步 checklist；每步讀真 state，完成就消失。 | 保留 getting-started.tsx 全部邏輯。改動只有兩處：(a) 「N of 4 done」counter 用 `DigitSwap`（components/motion/digit-swap.tsx:48）滾動，reduced-motion 時直接換字；(b) 每步 `detail` 文案要 general（現時第 2 步 :30 寫「LinkedIn, Instagram or Threads」——改為「Any account you own: publish is Direct, Assisted or Local per channel.」）。每步 action link 按 access 顯示：voice 要 edit、channel 要 manage_connections、draft 要 edit、approve 要 approve；冇權限嘅步驟顯示 step 但 link 換成 muted「Ask an editor」。 | Loading：整張 card 唔 render（現狀 :26）。Error：snapshot error 時同樣唔 render（唔好扮 0/4）。Done：4 步齊 return null。Sample workspace：card 照出，links 保留，card description 加一句「Sample workspace is read-only; create your own to continue.」 |
| Stats row | 四個真值：Scheduled、Published · 30 days、Writing batches left、Connected channels。 | StatCard × 4 照舊。改動：(1) Scheduled hint 改為兩段真值「{preFlight} waiting · {inFlight} publishing now」，value 仍然係總數；held jobs 唔計入 Scheduled，但有 held 時 footer 加「{held} on hold」；(2) Published · 30 days：value = verified + published，hint 寫「{verified} verified · {published - verified} accepted, receipt pending」，footer 改為「Provider-accepted posts; verified means the receipt was read back」；(3) 任何 query `isError` 而且冇舊 data → value 傳 string 'Unavailable'（stat-card.tsx:9 `value: ReactNode`），hint 寫「Could not read the workspace」，footer 放一個 `Retry` ghost button 叫 `query.refetch()`；refetch 失敗但有舊 data → 保留舊值，footer 寫「Last read {relativeTime(dataUpdatedAt)}」；(4) Writing batches：entitlement 缺 → '—' 照舊（:282），但 usage error → 'Unavailable'；(5) Connected channels 用 lib/channels/state.ts `channelCounts()`（connected / direct / assisted），唔再用 `connected.length`，咁樣 disconnectedByCustomer 嘅 card 唔會當 connected。 | Loading：Skeleton（stat-card.tsx:24）。Error：'Unavailable' + Retry，永不 0。Empty（真 0）：hint 用現有「Nothing in the queue」/「No publications yet」文案。 |
| Next up（新） | 答「下一個 post 幾時、去邊個 account」同「今個星期邊日有嘢出」。只計已 approved 而且 worker 讀得到 timing 嘅 job，等待批核嘅 draft 唔會出現喺度。 | Card 分兩層。上層：一行「Next: {platform} · {account} · {shortTime}（in 2 h）」，用 ChannelIcon + LevelBadge（該 connection 嘅 publish level，由 /channels 對 platform+account 配對）；冇 approved job → 「Nothing approved yet. Approve a draft in the Queue and it appears here.」+ link /app/queue?filter=waiting（`t-learn` chevron）。下層：7 日 strip（今日起，以 `useTimeZone()`（lib/preferences.tsx）為準，SSR/hydration 前用 `useLocalTimeZone()` 嘅 null 出 Skeleton，同 calendar-view.tsx:140 一樣；`new Date(manifest.timing.utc)`）；每日格顯示日期、count（有 job 先出 AnimatedBadge neutral，零時唔出 badge），每個 job 一粒 ChannelIcon（最多 4 粒 + 「+N」）；WAITING（scheduled/approved/claimed）實心，IN_FLIGHT 用 pulse=true 嘅 AnimatedBadge（status 'info'），failed（最近 24h，同 live-island.tsx:105-107 口徑）紅點。點擊某日 → `/app/calendar?date=YYYY-MM-DD`（calendar-view.tsx:141-145 已支援）。派生邏輯抽去 web/src/lib/jobs.ts `readQueueStatus(phase2, now)`（由 live-island.tsx:98-120 搬出並 export，加 per-day bucket 同 held 計數），Live Island 同 Overview 共用一個口徑。倒數每 30s 重算（沿用 TICK_MS = 30_000），只喺有 next 時先開 interval。Hint 一句「Times shown in {timeZone}」。 | Loading：Skeleton h-24。Error：「Next up is unavailable right now」+ Retry。Empty：見上；7 日 strip 仍然 render 7 個空格（真嘅空，唔係 skeleton），每格寫 '—'。Sample workspace：照 render 真 sample data。 |
| Needs your attention | 只有呢個人先決定到嘅事。Empty is good。 | 保留 Alert 列表 + AnimatePresence。改動：(1) 派生邏輯搬去 web/src/lib/attention.ts `deriveAttention({snapshot, channels, usage, access, now})`，Home（home-view.tsx:107-122）同 Overview 共用；reconnect / expiring 一律用 lib/channels/state.ts `needsAttention()` + `attentionSentence()`（/channels `connectionState` + `expiresAt`），snapshot `displayState` 只作 fallback（channels query 未返或 error）；(2) 加 `channels.isError` / `snapshot.isError` guard：error 時唔推「first-channel」/「voice」呢啲「零 = 未做」嘅 rule；(3) 新 rule「{n} posts on hold」（job.state === 'held'，store.py:426），link /app/queue；(4) 每條 entry 按 access 過濾 action：voice 要 edit、billing 要 owner、reconnect 要 manage_connections、approvals 要 approve；冇權限時 entry 照出但 action 換成 muted「Ask an admin」，唔藏起事實；(5) 每個 Alert 加 `data-attention-id` 方便 test / tour。 | Loading：2 個 Skeleton（現狀）。Error：一條 tone='warning' 嘅 Alert「Could not read part of the workspace; some reminders may be missing」+ Retry，而唔係 All clear。Empty：All clear（現狀 :328-336）。 |
| Publishing activity | Provider 確認嘅 post 逐日熱力圖，只計 verified（receipt 讀返）；同 Queue 'Verified' tab 一個口徑。 | 保留 PublishingActivity 全部（:71-142），DONE 改為只計 `verified`（同 queue-view.tsx:33），description 改「Posts whose receipt was read back, by day」。加：HeatCalendar `selection` / `onSelectionChange`（heat-calendar/types.ts:26-29 已有）→ 選咗 span 之後 card footer 出現「{total} posts {from}–{to} · Open in Queue ›」，link `/app/queue?filter=done&from={iso}&to={iso}`（Queue 要新增 query param 支援）。Card 由 col-span-7 縮到 col-span-4。 | Loading：Skeleton h-44（現狀）。Error / unavailable：現有文案（:125）。Empty：現有 description 分支（:117-118）。 |
| Channels | 每條 connection「今日真係做到咩」，永遠唔顯示混合嘅 Connected ✓。 | 每行：ChannelIcon、platform、account；右邊兩粒 badge：(a) connection state 用 AnimatedBadge（`contentKey=connectionState`），status 由 lib/channels/state.ts `channelBadge()` 攞，label 喺 Overview 改用「Verified」/「Read only」/「Expiring soon」/「Needs reconnect」/「Missing permissions」/「Identity only」/「Disconnected」（唔用 'Connected' 字眼，避免同 LevelBadge 疊成 Connected ✓ 觀感）；(b) 現有 `LevelBadge` publish level。`expiringSoon()` 為 true → 行底一行 muted「Access ends {relativeTime(expiresAt)}」。Header 右上加 count「{direct} Direct · {assisted} Assisted」（由 `channelCounts()`；Local 而家冇 connected card，唔顯示 0）。「Manage channels ›」照舊。 | Loading：Skeleton h-24。Error：「Channels are unavailable right now」+ Retry（唔好顯示「No channels connected yet」）。Empty：現有文案 + Connect link（manage_connections 先顯示 Connect，否則「Ask an admin to connect an account」）。 |
| Recent activity | Content-free audit trail：邊個做咗咩。 | 8 條照舊。每行改為三段：kind label（web/src/lib/audit-labels.ts 小型 map，涵蓋上述 26 個 kind，例如 `channel.connected` → 'Channel connected'、`session.alerted` → 'New device alert sent'；未 map 到嘅 kind fallback 現有 replace 邏輯）、subject（有就顯示，例如 platform 或 member email，後端已截）、actor（`actor` id 頭 8 位；如果等於自己 user id 顯示 'You'）、relativeTime。key 改用 `event.id ?? `${event.kind}-${event.at}-${index}``。「Full audit log ›」只喺 `checkAccess(access, { role: 'admin' })` 為 true 時顯示；否則顯示「Ask an admin for the full log」muted 文字。首次 paint 唔加 per-row stagger（page enter 已有；`.t-stagger-line` 係 780ms marketing reveal，超 300ms）；只有 refetch 後新 event 入場時用 AnimatePresence opacity 0→1 200ms。 | Loading：Skeleton h-32。Error：「Activity is unavailable right now」+ Retry。Empty：「No activity recorded yet」（現狀）。 |

- **Empty state**：全新 workspace（冇 voice、冇 channel、冇 variant、冇 job）：GettingStarted 佔頂，step 1 標 in-progress；Stats 全部真 0（Scheduled 0「Nothing in the queue」、Published 0「No publications yet」、batches = entitlement 真值、channels 0「Connect an account to schedule」）；Next up 顯示「Nothing approved yet」+ 7 個空日格；Attention 有兩條 info（Set up your voice、Connect your first channel，按 access 顯示 action）；Publishing activity 顯示空 heat calendar（description 用 :118 分支）；Channels 「No channels connected yet」；Recent activity 至少有一條 `workspace.created`（hosted.py:531 寫入），所以唔會真空。頁面唔用任何 placeholder 數字。
- **Loading**：PageContainer 唔用 isLoading（會蓋走 header，page-container.tsx:55）；每個 section 自己 Skeleton（現狀），HeatCalendar Skeleton h-44。StatCard Skeleton h-8 w-20。唔加任何「Loading your dashboard…」字句；`.t-skel-pulse` 由 ui/skeleton 帶。GettingStarted loading 時唔 render。Next up 喺 time zone 未 resolve（useLocalTimeZone() 為 null）時出 Skeleton，避免 hydration mismatch。
- **Error**：每個 query 獨立處理：`isError && !data` → 該 section 顯示「… is unavailable right now」+ `Retry`（ghost sm，叫 refetch）；`isError && data`（refetch 失敗）→ 保留舊值 + 「Last read {relativeTime(dataUpdatedAt)}」。StatCard value 'Unavailable'。Attention 唔推「零 = 未做」rule，改推一條 warning。整頁唔用 error boundary 全屏蓋走（其他 section 可能仍然有真數據）。403（sample workspace mutation）唔關 Overview 事；401 由 app-gate 處理。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| StatCard values | 數據由 loading 變成真值、或 snapshot refetch 後數值改變 | 逐位數字滾動（per-digit 0.9s、stagger 40ms），value 為 'Unavailable' string 時唔滾 | components/motion/number-ticker.tsx（stat-card.tsx:26 已接） | 是 |
| GettingStarted「N of 4 done」 | 某步由 pending 變 completed（真 state 改變） | 數字上下滾換，reduced-motion 直接換 | components/motion/digit-swap.tsx:48 DigitSwap | 是 |
| Needs your attention entries | 條目新增 / 消失（例如 approve 完 needs_review 減到 0） | 入 opacity 0→1 + y 8→0（200ms EASE_OUT）；出 160ms；其餘用 SPRING_LAYOUT 滑位；reduced-motion duration 0 | 現有 overview-view.tsx:319-361 AnimatePresence popLayout + lib/ease.ts SPRING_LAYOUT | 是 |
| Next up 倒數文字（in 2 h → in 1 h 59 m） | 30s interval 重算，只喺有 next 時開 | 文字 cross-fade 120ms（opacity only）；唔用 scramble / shimmer | components/motion/action-swap-roll.tsx:22 ActionSwapRollText（contentKey = 格式化後字串） | 是 |
| Next up 7 日 strip 嘅 in-flight 日格 | 該日有 job 處於 submitting / provider_accepted / published / uncertain | AnimatedBadge status 'info' pulse=true；狀態變 verified 時 contentKey 改變觸發 badge swap；零 job 嘅日格冇 badge | components/motion/animated-badge.tsx:19-27（pulse、contentKey） | 是 |
| Channels 行 connection-state badge | channels refetch 後 connectionState 改變（例如 Re-verify 完成） | badge 內容 swap，唔 pulse；status 由 lib/channels/state.ts channelBadge() | components/motion/animated-badge.tsx contentKey + lib/channels/state.ts | 是 |
| Recent activity 新 event 行 | audit refetch 後出現新 event id（唔係首次 mount） | 新行 opacity 0→1 200ms EASE_OUT，其餘行 layout='position'；首次 paint 冇 per-row stagger（避免 .t-stagger-line 780ms + blur） | motion AnimatePresence + lib/ease.ts EASE_OUT（同 attention 一樣） | 是 |
| HeatCalendar span selection → Queue link | 用戶 click 兩日 | footer link 用 `t-learn` chevron hover（transitions.css:425-446）；link 出現用 opacity 150ms | ui/learn-more-chevron + t-learn（overview-view.tsx:393 已用） | 是 |
| Page enter | 導航到 /app/overview | 整頁 `.t-page-enter` 浮入（現狀）；唔另加 per-card stagger，避免同 NumberTicker 疊加超過 300ms | web/src/app/app/template.tsx:13 + transitions.css:252 | 否（純裝飾） |
| Overview page tips（tour） | HelpMenu「Tips for Overview」或首次 nudge toast（tour-mount.tsx:37-46） | 現有 TourOverlay spotlight + popover，SPRING_LAYOUT，reduced-motion 由 overlay 處理 | web/src/features/onboarding/tour-overlay.tsx（唔新建 page-tour） | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{w}（snapshot：jobs / reviews / speaker / variants / workspace.sample） | api | 有 | src/postriff_phase2/hosted_app.py:459-462 → hosted.py:541, :124, :182；web/src/lib/api/client.ts:134；hooks.ts:39 | S |
| 2 | GET /api/workspaces/{w}/usage（entitlement, subscription, lifecycle） | api | 有 | hosted_app.py:389-390 → hosted.py:316-322；client.ts:151；hooks.ts:44；billing.py:51-55 trial 時 resetsAt == currentPeriodEnd | S |
| 3 | GET /api/workspaces/{w}/channels（per-connection capability matrix + connectionState + expiresAt + providers.productionReviewed） | api | 有 | hosted_app.py:411 → oauth.py:194-201；channels.py:11 CONNECTION_STATES；types.ts:445-462 | S |
| 4 | GET /api/workspaces/{w}/audit（最近 200 條，含 id / actor / subject / meta） | api | 有 | hosted_app.py:465-466 → hosted.py:929-932；types.ts:720-727；client.ts:245 | S |
| 5 | Shared queue-status derivation `readQueueStatus(phase2, now)`（next approved slot、in-flight、failed 24h、held、per-day buckets） | frontend | 冇 | 邏輯已喺 web/src/components/layout/live-island.tsx:98-120 但係 module-private；Overview 冇用；冇 held 計數。抽去 web/src/lib/jobs.ts 並 export，Live Island 改 import | S |
| 6 | Shared channel-state helpers（badge、attention、expiry、counts） | frontend | 有 | web/src/lib/channels/state.ts（untracked WIP）：channelBadge :59、needsAttention :73、attentionSentence :93、expiringSoon :47、channelCounts :208、isConnected :175；要等該 session commit | S |
| 7 | Shared attention derivation `deriveAttention()`（Home 同 Overview 共用一個口徑，含 access 過濾同 held rule） | frontend | 冇 | overview-view.tsx:172-245 同 home-view.tsx:107-122 各自實作；前者用 /channels connectionState，後者用 snapshot displayState（store.py:77-84）；兩者都冇 checkAccess、冇 held | M |
| 8 | StatCard / section 嘅 error → 'Unavailable' + Retry；refetch 失敗保留舊值 | frontend | 冇 | overview-view.tsx:153, :163, :236 冇讀 `isError`；stat-card.tsx:9 `value: ReactNode` 已可以傳 string；PublishingActivity :108 已做示範 | S |
| 9 | Queue deep-link query params `?filter=waiting\|in-flight\|done\|failed&from=<iso>&to=<iso>` | frontend | 冇 | web/src/features/queue/queue-view.tsx 冇 useSearchParams（grep 零結果）；filter state 係本地（:179）；Filter type :36；DONE = verified :33。Calendar 已用 nuqs useQueryStates（calendar-view.tsx:141-145）可照抄；Home / Ideas 有 `?new=1` 先例（home-view.tsx:68, :97；ideas-view.tsx:99） | S |
| 10 | Calendar `?date=YYYY-MM-DD` deep link | frontend | 有 | web/src/features/calendar/calendar-view.tsx:141-145 `useQueryStates({ view, date: parseAsString })`，:147 parseDay(params.date) | S |
| 11 | HeatCalendar controlled selection callback | frontend | 有 | web/src/components/charts/heat-calendar/types.ts:26-29 `selection` / `onSelectionChange`；overview-view.tsx:129-136 未傳 | S |
| 12 | Profile time zone / locale for all times（useTimeZone、formatDate、relativeTime） | frontend | 有 | web/src/lib/preferences.tsx:67-75 usePreferences / useTimeZone（untracked WIP）；hooks/use-local-time-zone.ts:12；lib/time.ts:35-62 已跟 setTimeDefaults；hosted.py:592-606 PATCH /api/me 接受 timeZone / locale | S |
| 13 | Audit kind → human label map（content-free，26 kinds） | frontend | 冇 | overview-view.tsx:415 只做 `replace(/[._]/g,' ')`；kinds 由 src/postriff_phase2/*.py audit() 呼叫 + hosted.py:157/:159 egress kinds | S |
| 14 | Audit link 按 role gate | frontend | 冇 | overview-view.tsx:421 對所有人顯示；nav-config.ts /app/workspace/audit `access: { role: 'admin' }`；checkAccess 在 web/src/lib/auth/access.tsx:69（owner 自動通過 :80） | S |
| 15 | Sample workspace read-only 提示（disable New idea、GettingStarted 加一句） | frontend | 冇 | types.ts:180 `workspace.sample`；hosted.py:188-189 mutation 一律 403；overview-view.tsx:256 冇讀；grep web/src 冇任何 UI 讀 .sample | S |
| 16 | Onboarding tour infra（registry、overlay、store、help menu、nudge） | frontend | 有 | web/src/features/onboarding/tours.ts（WELCOME_TOUR overview step :137-143；PAGE_TOURS overview-tips :280-294）、tour-overlay.tsx、store.ts、use-tour-context.ts、help-menu.tsx；TourMount 喺 web/src/app/app/template.tsx:15；HelpMenu 喺 layout/header.tsx:44。全部 untracked（另一 session）。Overview 只需加 data-tour id 同擴充 overview-tips steps | S |
| 17 | Tour-seen persistence（per account） | backend | 冇 | onboarding/store.ts 用 localStorage `postriff-onboarding`（try/catch），註明 `PATCH /api/me` onboarding field 係 seam；hosted.py:592-606 update_profile 現時接受 displayName / timeZone / locale / alertNewDevice，冇 onboarding；migrations/postriff/011_account_preferences.sql untracked。過渡期沿用 localStorage | M |
| 18 | Worker heartbeat / last-tick timestamp（用嚟顯示「queue is being watched」） | backend | 冇 | hosted_worker.py:154 tick() 唔寫時間；store.py:525 只有 per-job lease heartbeat；migrations 冇 pr_worker_* table。結論：Overview 唔可以顯示 worker 健康指示，直至有真 timestamp | M |
| 19 | Analytics summary（P2 Performance tile） | api | 有 | hosted_app.py:396-397 → hosted.py:466-474（`state: 'limited'` :473，metric.availability 'available'\|'unavailable'，insights.py:59-82）；hooks.ts:54 useAnalytics | M |
| 20 | DigitSwap / AnimatedBadge / ActionSwapRollText / NumberTicker motion primitives | frontend | 有 | web/src/components/motion/digit-swap.tsx:48、animated-badge.tsx:19-27、action-swap-roll.tsx:22、number-ticker.tsx:33 | S |
| 21 | Web 測試 harness（unit / e2e） | infra | 冇 | web/package.json scripts 只有 dev/build/start/lint/typecheck/format；web/ 冇 *.test.* 檔；tests/test_postriff_consumer_web.py 冇 overview 相關 | M |

## 3. Features

### P0

- **Honest error states（Unavailable ≠ 0）**：House rule 1 直接違規：snapshot / channels error 時 Scheduled、Published、Connected channels 三張卡顯示 0，仲會錯誤推「Connect your first channel」（overview-view.tsx:153, :163, :236）。PublishingActivity 已經做啱（:108），要將同一做法推到全頁；refetch 失敗時保留舊值加「Last read」而唔係突然變 Unavailable。
- **Next up card（下一個 approved slot + 今個星期 7 日 strip）**：Overview 而家答唔到「下一個 post 幾時出、去邊」——呢個係 category table stake：Typefully 將 Scheduled queue 放喺 sidebar 首位、排程時提供 Next slot（https://support.typefully.com/en/articles/9210135-scheduling-and-calendar）。PostRiff 嘅差異係只計 approved 而且有 timing 嘅 job（Live Island 已有同一口徑 live-island.tsx:98-120），draft 唔會扮成 scheduled；日格直接 deep link 去 Calendar `?date=`（已支援）。（depends on：readQueueStatus 抽去 web/src/lib/jobs.ts；useTimeZone()（lib/preferences.tsx）commit）
- **Attention 單一口徑（Home + Overview 共用 deriveAttention，含 access 過濾同 held）**：同一個人喺 Home 同 Overview 見到唔同嘅 Reconnect 結果（displayState vs connectionState），會令「Nothing publishes without you」呢個承諾失去可信度；亦係 error guard 同 RBAC 過濾嘅唯一落點；held jobs（store.py:426）而家冇人講。（depends on：web/src/lib/channels/state.ts commit）

### P1

- **Scheduled / Published 口徑清楚（同 Queue 一致）**：「Scheduled」混入 in-flight、「Published」footer 寫 receipt 但計埋未 verified 嘅 `published`（store.py:19）；Queue 嘅 Verified tab 只計 verified（queue-view.tsx:33）。分開寫「{preFlight} waiting · {inFlight} publishing now」同「{verified} verified · {n} receipt pending」，heat calendar 改只計 verified，數字唔變大，只係唔再講大話。
- **Channels card 顯示 connection state + token expiry**：House rule 5：現時每行只有 publish level，冇 connectionState，用戶要入 /app/channels 先知 token 過期。/channels 已經有 connectionState 同 expiresAt（types.ts:450, :454）；lib/channels/state.ts 已有 badge / expiring helper，Overview 只需接線，label 避開 'Connected' 字眼。（depends on：web/src/lib/channels/state.ts commit）
- **Recent activity 有 actor / subject / 人話 label，audit link 按 role**：Content-free 唔等於無資訊：`channel connected` 唔講邊個 channel 冇用。AuditEvent 已有 subject / actor / id（types.ts:720-727）。非 admin 撳「Full audit log」會撞 access wall（nav-config.ts audit role admin）。
- **HeatCalendar span → Queue deep link**：HeatCalendar 已支援兩日 selection（types.ts:26-29）但選咗之後冇出路。加 Queue `?filter=done&from&to` 就將熱力圖變成入口，唔係裝飾。（depends on：Queue query-param support（照抄 calendar-view nuqs））
- **Overview page tips 擴充（用現有 onboarding infra）**：Overview 係第一個「睇狀態」嘅頁，而 Direct / Assisted / Local 同「approved 先計 scheduled」呢兩個概念冇人教就會誤讀。tours.ts 嘅 overview-tips 而家只得一步；加 data-tour id 同 4 步 tips，唔新建任何 tour component，唔引新 library。（depends on：web/src/features/onboarding/ commit；data-tour ids 加喺各 section）

### P2

- **Sample workspace read-only 提示**：hosted.py:188-189 會 403 任何 mutation，但 Overview 嘅 New idea 同 GettingStarted links 照出，用戶撳落去先知。Remind, don't block：links 保留，加一句提示，New idea disabled + tooltip。
- **Performance tile（/analytics/summary，Unavailable-honest）**：Redesign §6.2 嘅 @performance slot；後端 summary 存在但 `state: 'limited'`（hosted.py:473），而且只有 verified publication 先有 metric。等 analytics 回填先值得佔 Overview 位。（depends on：Phase D 真 analytics 回填）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明三件事：(1) 呢頁係「狀態」，唔係「開工」——開工去 Home / New idea；(2) 每個數字都係真嘅：approved 先算 scheduled、receipt 讀返先算 verified、讀唔到會寫 Unavailable；(3) 每條 channel 嘅「publish」係 Direct / Assisted / Local 其中一種，冇「Connected ✓」。頁面點教：GettingStarted 佔頂而且 step 1 已標 in-progress（有下一步可撳）；StatCard 嘅 footer 一句講口徑；Channels card 每行有 state badge + LevelBadge；info sidebar（鍵 i）四段解釋。Tips 由現有 onboarding infra 提供：welcome tour 嘅 overview step（tours.ts:137-143）同 overview-tips（:280-294）；首次到訪由 tour-mount.tsx:37-46 嘅 nudge toast「New to Overview?」提示一次（welcome 決定咗之後先彈），之後由 header HelpMenu「Tips for Overview」重播；seen flag 喺 onboarding/store.ts localStorage（try/catch），待 PATCH /api/me 加 onboarding field 再搬。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-testid="getting-started"]（getting-started.tsx:66 已有，亦有 data-tour="getting-started"）` | Four steps, all real | Nothing here ticks itself. A step turns green only when the workspace has it: an active voice, a connected account, a draft, an approved job. |
| 2 | `[data-tour="overview-stats"]（overview-view.tsx:265 已有）` | Numbers you can trust | Scheduled counts approved jobs only. Published counts posts the provider accepted; verified means the receipt was read back. If something cannot be read you see Unavailable, never zero. |
| 3 | `[data-tour="overview-next-up"]（加喺新 Next up card root）` | What leaves next | The next approved slot and this week's days, in your profile time zone. Drafts waiting for your approval are not here yet; they sit under attention until you approve the exact text and time. |
| 4 | `[data-tour="overview-attention"]（加喺 Needs your attention Card root）` | Only you can decide these | Voice setup, approvals, reconnects, posts on hold and billing land here. Empty is good. |
| 5 | `[data-tour="overview-channels"]（加喺 Channels Card root）` | Direct, Assisted or Local | Each account shows what publishing really is today. Direct goes through a reviewed API. Assisted means PostRiff prepares the post and you finish it. Local runs through the desktop companion. |
| 6 | `[data-tour="help"]（header HelpMenu，help-menu.tsx:27 已有；welcome tour 最後一步已指向）` | Come back any time | Replay the tour or open the tips for any page from the help menu. |

**Empty state 教咩**：全新 workspace 嘅 empty state 本身就係教材：GettingStarted 講次序（voice → channel → draft → approve）；Stats 顯示真 0 而唔係 skeleton 或假數，footer 講口徑；Next up 寫「Nothing approved yet. Approve a draft in the Queue and it appears here」教「approved 先算 scheduled」；Attention 兩條 info（voice、first channel）教「唔會 block 你，只係提醒」——draft 同 export 而家已經做到；Channels 空狀態嘅 Connect link 帶用戶去能力矩陣頁而唔係一個混合嘅 Connect 掣；Recent activity 至少有 `workspace.created` 一條，證明 audit 係真。所有文案 general：唔提任何具體 brand、行業或平台偏好（getting-started.tsx:30「LinkedIn, Instagram or Threads」要改）。

## 5. Next steps（按次序）

1. **抽 `readQueueStatus(phase2, now)` 去 web/src/lib/jobs.ts（由 live-island.tsx:98-120 搬出，加 per-day bucket、held 計數同 PRE_FLIGHT / IN_FLIGHT / VERIFIED 常數 export），Live Island 改 import；同時決定 `published` 屬於 in-flight（跟 store.py:19 同 queue-view.tsx:33）**（effort S）  
   檔案：`web/src/lib/jobs.ts（新）、web/src/components/layout/live-island.tsx:23-30, :98-120、web/src/features/overview/overview-view.tsx:27-29`
2. **Honest error states：每個 query 讀 `isError` / `dataUpdatedAt`；StatCard value 傳 'Unavailable'；section 加 Retry（refetch）；refetch 失敗保留舊值 + Last read；attention 喺 error 時唔推 voice / first-channel rule，改推一條 warning**（effort S）  
   檔案：`web/src/features/overview/overview-view.tsx:144-245, :266-302, :312-317, :372-375, :407-410；web/src/components/app/stat-card.tsx（可選加 `unavailable` prop 統一樣式）`
3. **Next up card：新 component `web/src/features/overview/next-up.tsx`，用 readQueueStatus + useTimeZone()（fallback useLocalTimeZone）；上層 next slot + LevelBadge（由 useChannels 配 platform+account），下層 7 日 strip（AnimatedBadge、ChannelIcon，零 job 冇 badge）；日格 link `/app/calendar?date=`；30s interval 只喺有 next 時開；root 加 data-tour='overview-next-up'；插入主 grid 左 col-span-4，Attention 縮 col-span-3**（effort M）  
   檔案：`web/src/features/overview/next-up.tsx（新）、overview-view.tsx:305-306, :366`
4. **抽 `deriveAttention()` 去 web/src/lib/attention.ts，Home 同 Overview 共用；reconnect / expiring 用 lib/channels/state.ts needsAttention + attentionSentence，snapshot displayState 作 fallback；加 held rule；每條 entry 按 checkAccess 過濾 action；Alert 加 data-attention-id；Card root 加 data-tour='overview-attention'**（effort M）  
   檔案：`web/src/lib/attention.ts（新）、web/src/features/overview/overview-view.tsx:172-245、web/src/features/agent/home-view.tsx:107-122`
5. **Stats 口徑：Scheduled hint「{preFlight} waiting · {inFlight} publishing now」+ held footer；Published hint「{verified} verified · {n} receipt pending」，footer 改字；Connected channels 用 channelCounts()；PublishingActivity 改只計 verified；GettingStarted step 2 文案改 general，counter 用 DigitSwap，action links 按 access**（effort S）  
   檔案：`overview-view.tsx:71-142, :266-302；getting-started.tsx:28-33, :52-61, :70-72`
6. **Channels card：接 lib/channels/state.ts channelBadge()（Overview label 用 Verified / Read only 等，唔用 Connected）、expiringSoon 提示、header count Direct/Assisted；error 時唔顯示「No channels connected yet」；Connect link 按 manage_connections；root 加 data-tour='overview-channels'**（effort S）  
   檔案：`overview-view.tsx:366-397；可抽 `web/src/features/overview/channel-row.tsx``
7. **Recent activity：kind label map（web/src/lib/audit-labels.ts，26 kinds）、subject / actor 顯示、key 用 event.id、新 event 用 AnimatePresence opacity 入場（唔用 t-stagger-line）、audit link 按 `checkAccess(access, { role: 'admin' })`**（effort S）  
   檔案：`web/src/lib/audit-labels.ts（新）、overview-view.tsx:401-425`
8. **Queue query params：queue-view.tsx 用 nuqs useQueryStates 讀 `?filter&from&to`（filter 值 waiting / in-flight / done / failed，初始化 :179 嘅 state；from/to 過濾 `epochOf(manifest.timing.utc)`）；Overview HeatCalendar 傳 selection/onSelectionChange，footer 出「Open in Queue ›」**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx:36, :83-86, :179, :186；overview-view.tsx:129-136`
9. **Overview tips：喺 web/src/features/onboarding/tours.ts 嘅 `overview-tips` 加 4 步（stats、next-up、attention、channels），target 用上述 data-tour id；welcome tour overview step 文案同步；唔新建 tour component；seen flag 沿用 onboarding/store.ts**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:280-294（另一 session 嘅 untracked 檔，要夾）、overview-view.tsx:265, :305-425`
10. **Sample workspace：讀 `snapshot.data?.state.workspace?.sample`，New idea 變 disabled + tooltip，GettingStarted description 加一句 read-only 提示（links 保留）；同 Home 共用一個 `useSampleWorkspace()` helper**（effort S）  
   檔案：`overview-view.tsx:255-261；getting-started.tsx:74；web/src/lib/workspace/provider.tsx（可加 helper）`
11. **測試：為 jobs.ts / attention.ts / audit-labels.ts 加純函數 unit test（Vitest 或 node:test；web 而家零 test harness，先加最細嘅一種）；後端唔使改**（effort M）  
   檔案：`web/package.json scripts、web/src/lib/*.test.ts（新）`

## Risks

- 另一個 session 正喺度改 web/src（git diff 54 files；web/src/features/onboarding/、web/src/lib/channels/、web/src/lib/preferences.tsx、hooks/use-nav-groups.ts 全部 untracked；overview-view.tsx:265 喺本次 review 期間被加咗 data-tour）。Overview 嘅 step 1/3/4/6/9 直接依賴呢啲 WIP，要等佢哋 commit 或者同擁有者夾；staging 一律 by path（memory：shared tree explicit staging）。
- `published` 到底算「已出」定「in flight」：store.py:19 當 in-flight，overview-view.tsx:29 當 DONE，live-island.tsx:23 當 PUBLISHING，queue-view.tsx:33 只計 verified。統一為「verified 先係 done」會令 Published · 30 days 同 heat calendar 嘅數字變（少咗未 verified 嘅），要同 James 講明係口徑修正唔係 bug。
- Trial 倒數用 entitlement.resetsAt：billing.py:51-55 trial 時同 currentPeriodEnd 相同，冇問題；但 paid plan 時 resetsAt 係 quota reset（billing.py:211 _reconcile_entitlement），唔可以拎嚟做「plan ends」倒數——Overview 只喺 status === 'trial' 時用，維持現狀。
- 冇 worker heartbeat：任何「queue is healthy / worker last ran」指示都冇真數據，Next up 只可以講「approved and waiting」，唔可以承諾「will publish at」。要加 pr_worker_ticks 之類先可以顯示。
- Audit `LIMIT 200` 冇 pagination、冇 since：Overview 只用 8 條冇問題，但如果 activity 要「since last visit」就要後端加 `?since=`。
- Tour-seen 先用 localStorage（onboarding/store.ts）：private window / 清 site data 會重播；係 viewer 方便唔係數據，可接受。migrations/postriff/011_account_preferences.sql 係另一 session 嘅 untracked WIP，hosted.py update_profile 已經讀 time_zone / locale 欄，所以 API 同 migration 要一齊落地先可以 deploy。
- lib/channels/state.ts channelBadge() 對 publish_verified 出 'Connected' label；Overview 一行同時有 LevelBadge 時會有「Connected ✓ + Direct」嘅混合觀感。Overview 用 status 但自訂 label；長遠要同 Channels 頁擁有者夾一個共用詞彙。
- HeatCalendar 由 col-span-7 縮去 col-span-4 會令 1440px 下由約 26 週跌到約 16 週；MIN_WEEKS 8 × PITCH 20 = 160px 保證 375px 唔爆，但要實測 label 欄 + gutter 唔會橫向 scroll。
- 時區：Next up / strip 用 profile timeZone（preferences.tsx），manifest.timing 有 local + timeZone（types.ts:65）——跨 timezone approve 嘅 job 喺 strip 同 Queue 列表可能顯示唔同日；Calendar 同一做法（calendar-view.tsx:96-101 顯示 approvedZone），所以一致即可，hint 要寫「Times shown in {timeZone}」。
- Provider 未 production-reviewed 嘅 alert（overview-view.tsx:225-235）會對每個 connected platform 長期顯示直到 review 通過；加埋 held、reconnect、expiring、trial，Attention card 可以好長，Next up 縮咗 col-span 之後更明顯——可以考慮 NotificationStack（home-view.tsx:301 用緊）但要先確認 James 想唔想兩頁一樣。
- RBAC 係 UI-only（access.tsx:66-67 註明 real enforcement lives in the API）：過濾 attention action 唔等於安全，只係唔俾人撞 access wall；後端 403 仍然係最終防線。

## 覆核記錄

- 改正：client.ts:134 snapshot、:151 usage、:162 channels、:240 audit → audit → client.ts:245
- 改正：hosted_app.py:451-452 snapshot、:391-392 usage、:428-430 channels、:456-457 audit、:397-398 analytics、:340-342 PATCH /api/me → 全部行號更新為上述
- 改正：hosted.py:507 get() → repository.get :110 + present() :168；:174 sample 403；:302 usage；:863-866 audit LIMIT 200；:495 workspace.created；:452-460 analytics state limited → 行號更新；功能全部存在
- 改正：oauth.py:169-178 channels list 讀 pr_channel_capabilities，providers 帶 productionReviewed → oauth.py:194-201
- 改正：types.ts:142-195 snapshot、:178 workspace.sample、:443-453 ChannelView、:447 connectionState、:452 expiresAt、:485-556 Usage、:707 AuditEvent.id、:63 timing → 行號更新為上述
- 改正：Trial 倒數用 entitlement.resetsAt (:170)，同 billing-view.tsx:107 一致；risk：billing.py 可能將 resetsAt 同 currentPeriodEnd 設成唔同時間 → 改路徑；刪除該 risk，或改為「paid plan 時 resetsAt 係 quota reset，唔係 period end；trial 時兩者相同」
- 改正：冇任何 tour / onboarding infra（grep data-tour / tour 喺 web/src 零結果） → 刪除「新建 page-tour.tsx」；改為喺 tours.ts 嘅 overview-tips 加 steps 同喺 Overview 加 data-tour id
- 改正：t-stagger-line 40ms stagger，8 行總長 ≤ 300ms → Recent activity 首 paint 唔加 per-row stagger（page enter 已夠）；只喺 refetch 有新 event 時用 AnimatePresence opacity 200ms 入場
- 改正：Queue 冇 useSearchParams；filter state 係本地 :85-88；deep link 用 ?filter=done|scheduled → query param 值用 waiting / done；行號 :179
- 改正：現時 calendar 冇 date query param，先 link 去月視圖 → 7 日 strip 點某日 → /app/calendar?date=YYYY-MM-DD
- 改正：7 日 strip 用 Intl.DateTimeFormat().resolvedOptions().timeZone，同 calendar-view.tsx:156 一樣 → 用 useTimeZone()（有 provider）fallback useLocalTimeZone()，唔直接 call Intl
- 改正：PATCH /api/me 只接受 displayName（hosted_app.py:340-342）；migrations/postriff/011_account_preferences.sql 係 untracked → 改為「PATCH /api/me 已接受 4 個 key，未有 onboarding/tourSeen；onboarding/store.ts 已預留 readProgress/writeProgress seam」
- 改正：deriveAttention 需要新寫 reconnect 判斷；Channels card badge 要新 map connectionState → label/status → Overview import 呢個 module，唔另寫 map
- 違反原則（已改）：Motion rule 4：Recent activity 用 .t-stagger-line（500ms/行 + 40ms stagger + blur filter）8 行 ≈ 780ms，超過 300ms 上限；亦係 marketing SSR reveal，唔係 app 數據列表用。
- 違反原則（已改）：Motion 規則「reuse before inventing」：spec 提議新建 web/src/components/app/page-tour.tsx，但 web/src/features/onboarding/ 已有 tour registry、overlay、store、help menu 同 TourMount；重複造輪。
- 違反原則（已改）：Motion / 真數據：Next up 7 日 strip 嘅空日格建議 render '—'——可接受，但 spec 同時建議 AnimatedBadge neutral count 喺零時都顯示，會變成 8 粒無意義嘅 badge；零應該係無 badge，唔係 badge '0'。
- 違反原則（已改）：Capability honesty（rule 5）：spec 嘅 Channels badge map 將 publish_verified 顯示 'Verified'——正確；但引用嘅 lib/channels/state.ts channelBadge() 會出 'Connected' 字眼（另一 session WIP），Overview 用時要留意 label 唔可以同 LevelBadge 混成「Connected ✓」嘅觀感——建議 Overview 行內 badge 用 state.ts 嘅 status 但 label 改 'Verified' / 'Read only'，或者同 Channels 頁擁有者夾。
- 違反原則（已改）：General-not-personal：spec 已正確指出 getting-started.tsx:30「LinkedIn, Instagram or Threads」要改；但佢嘅 features 引用 Typefully / Buffer 作為理據可以，前提係 UI 文案唔提任何平台偏好——corrected spec 保留。
- 違反原則（已改）：Remind-don't-block：spec 提議 sample workspace 時 New idea 變 disabled——sample workspace 後端本身 403，disabled + tooltip 係誠實提示，唔算 block；但 GettingStarted links 改指向 /app 會令用戶以為 Home 可以做嘢（Home composer 同樣 403）。改為 links 保留，加一句 'Sample workspace is read-only; create your own to continue'。
- 違反原則（已改）：RBAC：attention rule 'voice' 連去 /app/workspace/brand（permission edit）、'past-due'/'trial' 連去 /app/account/billing（permission owner）、'reconnect' 連去 /app/channels（reconnect 要 manage_connections，見 lib/channels/state.ts needsReconnect）；spec 嘅 deriveAttention 冇按 access 過濾，viewer/approver 會見到撳唔入嘅 action。
- 補上遺漏：Held jobs：store.py:426 / hosted_worker.py:127 嘅 'held' state（approval、capability 或 entitlement 改變後停住）唔屬 Scheduled 亦唔屬 attention；用戶會見到 Scheduled 少咗一個而冇解釋。要加 attention rule「N posts on hold」（lib/channels/state.ts needsAttention 已接受 heldJobs）。
- 補上遺漏：RBAC gating：Overview 本身冇 access key（所有 member 可見），但每條 attention 同每個 link 嘅目標頁有 gate（brand=edit、billing=owner、audit=admin、channels reconnect=manage_connections、queue approve=approve）。要用 checkAccess 過濾 attention 嘅 action link，或者顯示無 link 嘅提示文字。
- 補上遺漏：Time zone 口徑：web/src/lib/preferences.tsx（untracked）將 profile timeZone 作為所有時間格式嘅來源；Next up / 7 日 strip / relativeTime 要跟 useTimeZone()，而唔係 Intl 直讀，否則同 Calendar / Queue 唔一致。
- 補上遺漏：i18n / languages：memory 有 worldwide languages plan（per-channel locales + flag emoji）；Overview 嘅 Next up 行同 Channels 行應該預留 language/locale 標記位（manifest.payload.language 已存在，見 insights.py:71），而所有新文案要經 locale-aware 格式（formatDate/relativeTime 已用 profile locale）。
- 補上遺漏：Mobile：spec 只講 grid；冇講 Attention Alert 內 button 44px touch target、Recent activity 行內 actor/subject 喺 375px 要 truncate 兩行、HeatCalendar 喺 375px 只得 8 週而 tooltip hover 冇 touch fallback。
- 補上遺漏：Error handling 細節：TanStack Query 嘅 isError 同 isPending/isLoading 要分開處理——首 load 失敗 vs refetch 失敗（有舊 data）唔同：refetch 失敗時應該保留舊值加 'Last read {relativeTime}' 而唔係即刻換成 Unavailable。
- 補上遺漏：Sample workspace 亦影響 tour：tours.ts 嘅 overview step 讀 TourCtx（use-tour-context.ts），sample 時 ctx 會係真 sample data，文案 OK；但 nudge toast 會喺 sample workspace 彈出——可接受，要記錄。
- 補上遺漏：Concurrent WIP：web/src/features/onboarding/、web/src/lib/channels/、web/src/lib/preferences.tsx、migrations 009/011/012 全部係 untracked，屬另一 session。Overview 嘅 next steps 依賴佢哋 commit 先；staging 要 by path。
