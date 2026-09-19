# 06 · Calendar

> Route：`/app/calendar` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

Calendar primitive 本身已經係 polished 級數；頁面層（data 誠實度、可以做嘅動作、空／錯誤狀態）仲係 partial。以下逐項列出而家嘅實況（行號按 2026-09-16 工作樹核對）。

【Route 同 view】
- `web/src/app/app/calendar/page.tsx:1-13`：Suspense 包住 `CalendarView`，metadata title 'Calendar'。Sidebar 喺 Create group，快捷鍵 c c（`web/src/config/nav-config.ts:36-42`）；nav item 冇 `access` key，所以 viewer 都見到呢頁（read）。
- `web/src/features/calendar/calendar-view.tsx:138-225`：唯一 data source 係 `useSnapshot()`（`web/src/lib/api/hooks.ts:39-42` → `GET /api/workspaces/{id}`，`src/postriff_phase2/hosted_app.py:459-462`）。Events 由 `state.phase2.reviews`（只計 `status === 'needs_review'`，`:178-180`）同 `state.phase2.jobs`（`:181`）砌出嚟，時間用 `manifest.timing.utc` 轉 `fromDate(at, timeZone)`（`:156-162`）。
- URL state：nuqs `?view=month|week|day&date=YYYY-MM-DD`（`:141-149`），today 唔寫入 URL（`:196-197`）。
- Header action「New post」link 去 `/app`（`:200-205`），唔係開 `ScheduleDialog`。
- Legend（`:213-220`）係六個固定 label，冇數字。
- Loading：`snapshot.isPending || !timeZone` 時出 `Skeleton h-[40rem]`（`:187-188`）。**冇 error state**：`snapshot.isError` 時 `events` 係 `[]`（`:153`），會 render 一個空月曆，即係「Unavailable」變咗 0（違反 house rule 1）。**冇 empty state**：新 workspace 只見空格，day panel 講「No posts on this day.」（`web/src/components/application/calendar/calendar.tsx:373`）。
- 工作樹（未 commit，另一 session）已喺 `:190` 加 `data-tour='calendar-grid'`；tour 引擎 `web/src/features/onboarding/`（untracked）已有 welcome step（`tours.ts:106-113`）同 `calendar-tips`（`tours.ts:266-278`，文案「Month or list」已過時）。

【時區】
- Calendar grid 用瀏覽器時區 `useLocalTimeZone()`（`web/src/hooks/use-local-time-zone.ts`，server 同 hydration 期間係 null）。`ScheduleDialog` 就用 `useTimeZone()`（`web/src/lib/preferences.tsx:72-74`，profile 設定優先、browser 係 fallback，`:36-45`）。兩者可以唔同。
- 日期格式 hard-code `'en'`（`config.ts:91` `DEFAULT_LOCALE`、`calendar-view.tsx:90, 100`），preference 嘅 `locale` 未接上。

【State mapping 嘅誠實度缺口】
- `kindOf()`（`calendar-view.tsx:71-77`）：verified / failed / canceled / in-flight（submitting, provider_accepted, published, uncertain），其餘一律 'waiting' → label「Scheduled」。但 backend 有 `held` state（`src/postriff_phase2/store.py:425-426`：manifest 唔 current／channel 唔 Ready for posting／trial 過期／`manifest.expiresAt < now`；`:467`：approval authority 變；`hosted_worker.py:127`），worker 唔會再執行 held job（`store.py:454`、`hosted_worker.py:53`），而家 held job 會顯示成藍色「Scheduled」——錯。
- Review 只睇 `needs_review`。Manifest `expiresAt = timing + 3600`（`store.py:380`），過咗 approve 會 409「This approval is stale」（`store.py:292-293`）。Calendar 對過期 review 照樣顯示黃色「Needs approval」；Queue 有「expired」badge 同 `disabled={expired}`（`web/src/features/queue/queue-view.tsx:100, 114-118, 142`），Calendar 冇。`stale` review（`store.py:419-420`，草稿改咗令 manifest 唔再 current）直接消失。
- `Manifest.expiresAt: number` 已經喺 type（`web/src/lib/api/types.ts:66`），`Job.nextAction`（`:79`）、`providerReference`（`:77`）、`events[]`（`:75`）都有，純前端可修。

【Popover 詳情】
- `PostDetails`（`calendar-view.tsx:96-136`）：ChannelIcon + `AnimatedBadge`（`web/src/components/motion/animated-badge.tsx`）、account · 時間、approvedZone 唔同時附帶批核時區嘅時間（`:88-94, 101`）、cancelRequested 文字、內文 clamp；popover context 右邊加 `ManifestPreview`（`web/src/components/application/post-preview/manifest-preview.tsx:17-22`），手機闊度上下排（`:131-134`）；底部「Open the queue」link。
- **Popover 冇任何 action**。Approve（`p2_approve`，`queue-view.tsx:137-163`）同 Cancel（`p2_cancel` HoldActionButton，`queue-view.tsx:190-197, 360-377`）都只喺 Queue。Backend：hosted.py `:199-203` 剝走 `p2_` prefix 交 `apply_phase2`；approve `store.py:287-304`（digest 要 match、channel 要 Ready for posting、每日上限 `DAILY_LIMITS` `:21` 只有 Instagram/Threads/LinkedIn，檢查 `:297-300`）；cancel `store.py:315-320`（in-flight 會變 uncertain，唔會 recall）；權限 class 'approve'（`src/postriff_phase2/permissions.py:18, 28`——`p2_review`、`p2_approve`、`p2_approve_many`、`p2_cancel` 全部同一 class），前端 `checkAccess(access, { permission: 'approve' })`（`web/src/lib/auth/access.tsx:69`；`workspace/provider.tsx:145-154` 用真 membership 建 access，`access.tsx:3-9` 嘅「stub」註解過時）。
- `useAct`（`hooks.ts:150-162`）成功時 `setQueryData` snapshot，冇 onError 處理；409 revision conflict 要自己 invalidate。

【Calendar primitive（keep 全部）】
- `web/src/components/application/calendar/calendar.tsx`（406 行）：header（today tile、title、range、prev/Today/next `ButtonGroup` aria-label 'Change period' `:291`、view `Select` aria-label 'Calendar view' `:303`、action slot）、三個 view、`DayPanel`（`MiniCalendar` + list，`:348-404`）。Period slide ±16px 240ms（reduced 120ms 只 opacity，`:63-67, 129-145`）；day panel list stagger 40ms 上限 7 個（`:377-384`）——已符合 motion §5。
- `month-view.tsx`：3 chips + 「+N more」（`config.ts:89`），`md` 以下變 dots、整格開 day（`:123-125, 135-139`）；roving tabindex + Arrow/Home/End/PageUp/PageDown（`:60-75`）。
- `time-grid.tsx`：96px/hour（`config.ts:83`）、now marker 30s tick（`calendar.tsx:78-87`、`time-grid.tsx:152-169`）、lanes overlap（`utils.ts:92-139`）、auto-scroll 去 now／第一個 event／8AM（`:55-65`）、時區縮寫喺 gutter（`:51-52, 70`）。
- `event-button.tsx`：chip／block（`:37` `transition-colors`）+ `Popover`（`:73` PopoverTrigger；`web/src/components/ui/popover.tsx:37` 用 `.t-dropdown`，開 250ms／收 150ms，`web/src/styles/transitions.css:63-64`）。
- `config.ts` `EVENT_COLORS` 九色：gray / brand / red / orange / yellow / green / blue / indigo / pink（`:26-58`）。

【Post preview】
- `web/src/components/application/post-preview/`：33 個 channel template + generic（`templates/`，36 個檔含 index.ts 同共用 vertical-feed.tsx），`PostPreview` lazy load（`post-preview.tsx:14-24`），`PhoneSkeleton`（定義 `:83`、用 `:67`），媒體經 `api.media` 用 Library 同一個 cache key `['media', w, id]`（`use-preview-post.ts:22-28`）。`draft-preview.tsx`（untracked 新檔）畀未有 manifest 嘅草稿用。誠實規則喺 `README.md:28-33`。

【Data 新鮮度】
- `useSnapshot` 冇 `refetchInterval`；query client `staleTime: 60s`（`web/src/lib/query-client.ts:7`）。Worker 每分鐘由 cron 行（`vercel.json:57-62`，route `hosted_app.py:326-332`），所以 scheduled → submitting → verified 嘅轉變只會喺 refetch（window focus／mutation）之後先見到；「Publishing」chip 可能對住舊 snapshot 閃。`LiveIsland`（`web/src/components/layout/live-island.tsx:204-213`，`TICK_MS` `:30`）只係每 30s 重計倒數，都唔 refetch。

【Schedule 入口】
- `web/src/features/queue/schedule-dialog.tsx:19-24, 38`：props 只有 `open / onOpenChange / variantId`；時間預設 now+1h 整點（`:28-32, 60`）；時區 `useTimeZone()`（`:61`）；payload 冇 `fold`（`:93-102`），DST 重複時段 backend 會 409「This time occurs twice」（`src/postriff_phase2/contracts.py:53`），過去時間 409「Choose a future time.」（`:56`）而 UI 冇得揀。成功後固定 `router.push('/app/queue')`（`:107`）。Pipeline 用同一個 dialog（`web/src/features/pipeline/pipeline-view.tsx:28, 134`）。

【Backend 冇嘅嘢】
- 冇 calendar 專屬 endpoint（唔需要）。冇 `p2_reschedule`：改時間 = 新 `p2_review` + `p2_approve` + 舊 job `p2_cancel` 三步（`store.py:284-320`）。冇 preferred posting slots 儲存。`p2_approve_many`（`store.py:305-314`）已有，前端只有 Home plan 流程用（`web/src/features/agent/plan.ts:88-105`），Queue／Calendar 未用。
- Snapshot `phase2.channels[]` 每個帶 `displayState`（`store.py:74, 77-83`：Connect／Reconnect／Finish setup／Ready for posting；`types.ts:147`）。

【其他】
- `docs/postriff-motion-system.md:44` Calendar 一行已過時（寫住 Tabs segment Month/List + Tooltip；實際係 `Select` + `Popover` + month/week/day）。`tours.ts:266-278` calendar-tips 同樣過時。
- `web/package.json` 冇 test script（`:5-14`），calendar 冇 unit test；languages plan（`docs/postriff-worldwide-languages-plan.md:396-398`）已定 web test 用 `node --test` 直接跑 TypeScript。`@dnd-kit/*` 已裝（`:17-20`），`motion` ^11.18.2（`:42`），`nuqs` ^2.8.9（`:46`），`react-responsive` 已裝。`hooks/use-media-query.ts` 唔收參數（固定 `(max-width: 768px)`，回 `{isOpen}`）；`hooks/use-mobile.ts` `useIsMobile()` <768。
- 共用工作樹：`calendar-view.tsx` 已有另一 session 嘅未 commit 改動；`features/onboarding/` untracked。

## 1. Design specification（最新版）

**目的**：一個地方睇晒「幾時有嘢出街」同「邊啲仲等我決定」：每粒 chip 都係真實嘅 review 或者 job，放喺批核咗嘅確切時間（用瀏覽器時區顯示，profile 時區唔同時註明）。第二層目標：可以喺呢度直接做決定（approve／cancel／prepare again）同喺任何一日開始 schedule，唔使跳去 Queue。

**Layout**：保留現有骨架：`PageContainer`（title 'Calendar'、description、info sidebar `infoContent`）→ Calendar card（header 一行：today tile、標題、range、prev/Today/next、view Select、header action）→ 三個 view → 下面 legend。改動只有四處：(1) header action 由「New post → /app」改做「Schedule a draft」，開 `ScheduleDialog`，時間預填 focused date（只喺 `checkAccess(access,{permission:'approve'})` 為真時出現，因為 `p2_review` 都係 approve class）；(2) header 同 grid 之間加一行 filter chips（channel + status），status chips 同 legend 合併成一行「live legend」，每個 chip 顯示可見 period 嘅真實數量；channel chip 附 `displayState`（非 Ready for posting 時顯示該字串）；(3) event popover 左欄底部加 action 區（Approve & schedule／Hold to cancel／Prepare again），右欄 phone preview 不變；(4) 有 error 時整個 grid 換做 Alert，唔會出空月曆。Primary action：「Schedule a draft」（header）；secondary：每格 hover／focus 出現嘅「+」（md 以上）同 DayPanel footer 嘅「Schedule on this day」。Info sidebar 繼續用現有三段，第三段改寫成「Changing a time」（改時間 = 準備新 review 再批核，舊 job 會取消）。

Responsive：
- 375px：header 垂直疊（現有 `flex-col lg:flex-row`）；filter chips 一行橫向 scroll（`overflow-x-auto`，snap）；month 格用 dots、整格開 day（現有）；day view 嘅 DayPanel 疊喺 grid 下面，mini calendar 隱藏（現有 `max-lg:hidden`）；popover `max-w-[calc(100vw-1rem)]`（現有），phone preview `scale={0.5}`（`useIsMobile()` 為真）並疊喺詳情下面（現有 `sm:flex-row`），action 按鈕 full width；HoldActionButton 加 `touch-action:none select-none` 免 iOS 長按選字。
- 768px：month 出 chips（`md:`），popover 左右並排，phone 0.62；DayPanel 仍然疊底。
- 1440px：day view `lg:grid-cols-[minmax(0,1fr)_20rem]`（現有）；popover 詳情 `w-72` + phone 0.62；filter 一行放得晒。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header（保留 + 改 action） | 定位時間、切 view、開始 schedule。 | 現有 `CalendarHeader`（`calendar.tsx:244-319`）。`headerAction` 改為 `<Button>` 「Schedule a draft」→ `ScheduleDialog`，只喺 `canApprove`（`checkAccess(access,{permission:'approve'})`）時 render；冇權限時 header action 留空（唔出 disabled 掣）。新增 prop `initialLocalTime`：用 dialog 自己嘅 `useTimeZone()` zone 計（唔係 calendar 嘅 browser zone），focused date 係今日就用下一個整點，未來日子用 09:00；過去日子照開 dialog 但 time 用今日下一個整點並喺 dialog 內出一句「That day has passed; the time below is the next available hour.」（remind, don't block；backend `contracts.py:56` 會拒絕過去時間）。冇 draft 時 dialog 已經有「No drafts yet — add candidates from Ideas」。`ScheduleDialog` 完成後 `router.push('/app/queue')`（`:107`）要改為可選：由 Calendar 開嘅話留喺 Calendar，並將 `date` 設做新 review 嘅日子（用回傳 snapshot 最後一個 review 嘅 `manifest.timing.utc` 轉 browser zone），令新 chip 即時出現。 | default；dialog open；無 draft（dialog 內文案）；無 active voice（dialog 內現有「Set up your voice」）；無 approve 權限（冇掣）。 |
| Filter row + live legend | 縮窄到某個 account 或某種狀態，同時教識顏色代表咩。 | 一行 chips，兩組：(a) channel：由 `state.phase2.channels` 每個 account 一粒（`ChannelIcon` + account；`displayState !== 'Ready for posting'` 時附一個細 `AnimatedBadge` 顯示該字串，例如「Reconnect」；永遠唔出「Connected ✓」），旁邊 `DigitSwap` 顯示可見 period 內屬於該 channel（用 `manifest.channelId` 對 `channels[].id`，冇 channelId 先 fallback `account+platform`）嘅 event 數；(b) status：KIND_META 每個 kind 一粒（dot 顏色 + label + `DigitSwap` 數量），新增 `held`（orange，「Held」）、`expired`（red，「Review expired」）、`stale`（gray，「Out of date」）。撳 chip toggle；多選；URL 用 nuqs `?channel=<id>,<id>&kind=review,waiting`（`parseAsArrayOf`），預設全部時唔寫入 URL。數量永遠計 filter 前、可見 period（`visibleRange`）內嘅真實數（period 改變數字先滾動）。Filter 影響 month chips、time grid、DayPanel list、MiniCalendar markedDays。 | 全選（預設，chips 全部 outline）；部分選中（選中 chip 用 `EVENT_COLORS[color].chip`）；可見 period 一個 event 都冇時 chips 顯示 0（真實 0，唔係 unavailable）；error 時整行唔 render。 |
| Month / Week / Day grid（保留） | 月睇形狀，週／日睇每個 post 落喺邊個鐘。 | 全部保留。加兩樣（只喺 `canApprove` 時）：(1) `month-view.tsx` 每格右上角一個 `size-6` 嘅「+」button，`md:` 以上 hover／focus-within 先出現（`opacity-0 group-hover:opacity-100 group-focus-within:opacity-100`，`transition-opacity`），aria-label 'Schedule on {date}'，撳 → `onCreateAt(day)`；(2) `time-grid.tsx` 空白位雙擊（desktop）→ `onCreateAt(day, hour)` 預填該小時。兩者都經新 prop `onCreateAt?: (date: CalendarDate, hour?: number) => void` 傳入 `Calendar`，冇傳就唔 render。Event chip 新增 `held`（orange）、`expired`（red，status 文字「Review expired」，唔用 line-through）、`stale`（gray）三種顏色，全部係 `EVENT_COLORS` 現有色。Chip title 同 block 文字加 `lang={manifest.payload.language}` `dir='auto'`（languages plan §7.3）。 | 現有；filter 後零 event 嘅 period → grid 上方一行小字「No posts match in this period · Next: {date} →」（link 跳去最近一個未來 event 嘅日子；冇未來 event 就唔出 link）。 |
| Event popover（保留 + 加 actions） | 見到批核咗乜、喺邊個 app 點樣出、同即場決定。 | 左欄保留 `PostDetails`（內文加 `lang`／`dir='auto'`）；喺內文之下加 action 區（只喺 `canApprove` 為真時出現）： - kind=review 且未過期：`ReviewApproveButton`（共用組件，StatefulButton 「Approve & schedule」loading 'Approving…'／success 'Scheduled'／error 'Try again'）→ `useAct().mutate({ revision, action:'p2_approve', payload:{ reviewId, digest, confirmed:true } })`；成功後 popover 留住 0.6s 畀「Scheduled」讀到再 close（同 Queue `REVIEW_EXIT` 一樣），chip 由黃轉藍係 snapshot 換咗之後自然發生。旁邊一句「Approves exactly this text, media, account and time.」；如果該 channel 喺 `DAILY_LIMITS`（Instagram 100／Threads 250／LinkedIn 150，前端 mirror 同一個表）而當日該 channel 嘅 waiting + in-flight 數已達上限，Approve 旁邊出 reminder「{platform} allows {limit} posts per 24 hours for this account; this one would exceed it.」但唔 disable 掣（backend 做裁決）。 - kind=review 已過期／stale：唔出 Approve；出 `Link`「Prepare again」→ `ScheduleDialog` 帶 `variantId=manifest.variantId`、`initialLocalTime` 用原本 `manifest.timing.local`（過咗就用下一個整點）。 - kind=waiting（approved／scheduled／claimed）且未 cancelRequested：`JobCancelHold`（共用組件，HoldActionButton 「Hold to cancel」同 `queue-view.tsx:360-377` 同一個 class set），完成 → `p2_cancel`。 - kind=in-flight：唔出 cancel（backend 只會變 uncertain）；顯示「Submitted; the provider has the post. PostRiff reconciles before any retry.」 - kind=held／failed：顯示 `job.events.at(-1).message`（真實原因，例如「Approval, capability or entitlement changed…」）+ `job.nextAction`（`types.ts:79`）+ 「Prepare again」link。 - kind=verified：`providerReference` 有就顯示「Receipt: {providerReference}」，冇就唔顯示。 - 底部保留「Open the queue ›」。 - Approved zone（`manifest.timing.timeZone`）同 browser zone 唔同時保留現有括號時間；profile zone（`useTimeZone()`）同 browser zone 唔同時再加一句「Your profile zone is {zone}」。 右欄 `ManifestPreview` 不變；`useIsMobile()` 為真時 scale 0.5。 | idle；approving（button loading，其他 action disabled）；approved（success 0.6s → close）；error（toast + button 'Try again'；409 時 `invalidateQueries(keys.snapshot)` 並提示「Reloaded; try again」）；cancelling（button 消失，badge 顯示「cancelling」直到 snapshot 換）；無權限（冇 action 區，只有「Open the queue」）。 |
| Day panel（保留 + footer action） | 一日嘅完整清單，手機上係主要入口。 | 保留 `DayPanel`。`dayPanelFooter` 改為兩個：「Schedule on this day」（`canApprove` 時，開 dialog 預填該日）同現有「Open the queue ›」。List item 用 `renderDetails(event,'list')`，list context 都加同一組共用 action（Approve／Hold to cancel）但排成一行細掣。 | 有 event；冇 event（「No posts on this day.」+ 「Schedule on this day」）；過去日子（唔出 Schedule 掣，改出「This day has passed.」）。 |

- **Empty state**：只喺 `snapshot.isSuccess && phase2.reviews.length === 0 && phase2.jobs.length === 0`（整個 workspace 真係冇嘢）時，喺 grid 上方插一個 `Empty`（`web/src/components/ui/empty.tsx`）：`EmptyMedia` 用 `Icons.calendar`，title「Nothing scheduled yet」，description「Draft something in Ideas, then schedule it to an account and an exact time. Approved posts appear here at that time, in your time zone.」CTA 按真實 snapshot 揀：`canApprove && variants.length > 0` → 「Schedule a draft」（開 dialog）；`variants.length === 0` → Link「Go to Ideas」（只喺 `checkAccess(access,{permission:'edit'})`）；`phase2.channels.length === 0` 再加一句「You have no connected accounts yet.」+ Link「Connect a channel」（只喺 `manage_connections`）。Grid 照樣 render（空格），唔放任何 sample chip。文案對設計師、老師、店主、developer 讀落一樣。
- **Loading**：`snapshot.isPending || !timeZone` 時：保留 `Skeleton`，但改成 calendar 形狀（一條 header 高 4rem + 6 行 grid 各 8.5rem，全部 `Skeleton` pulse），冇任何文字、冇假數字。Popover 內 phone 未載入用現有 `PhoneSkeleton`（`post-preview.tsx:67, 83`）。ManifestPreview 媒體 loading 由 template 自己處理（現有）。
- **Error**：`snapshot.isError` → 唔 render grid、filter、legend（冇數字可以誠實地顯示），改出 `Alert variant='destructive'`（`ui/alert.tsx:12`）：title「Couldn't load your schedule」，description 顯示 `ApiError.message`（有就顯示，冇就「The workspace could not be read.」），`AlertAction` 一個 `Button` 「Try again」→ `snapshot.refetch()`；button 喺 `isFetching` 時 loading。401／403（session 過期、冇 workspace）交 app-gate，Calendar Alert 只處理其餘 error。Popover 內 mutation 失敗：toast + `StatefulButton` error 狀態 + `useFlash` 1.5s 後回 idle；409 revision conflict 時額外 `invalidateQueries(keys.snapshot)`。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Period（月／週／日）切換 | prev／next／Today／MiniCalendar pick | 舊 period 向反方向滑出 16px + fade，新 period 滑入；view 切換只 fade。240ms，reduced-motion 120ms 只 opacity。 | 現有 `calendar.tsx:63-67, 129-145`（motion AnimatePresence popLayout + EASE_OUT） | 是 |
| Day panel list | 開 day view 或揀另一日 | 每個 item opacity 0→1、y 6→0，stagger 40ms，最多 7 個（≤300ms）。 | 現有 `calendar.tsx:377-384` | 是 |
| Event popover | 撳 chip／block | 跟 trigger 方向 scale 0.97→1，開 250ms 收 150ms。 | 現有 `ui/popover.tsx:37` `.t-dropdown` token（`transitions.css:63-67`） | 否（純裝飾） |
| Live legend / filter 數字 | 可見 period 或 filter 改變 | 每個 kind／channel 嘅數量逐位滾動（direction up），180ms／glyph；數字係可見 period 內真實 event 數。 | `web/src/components/motion/digit-swap.tsx` DigitSwap（`queue-view.tsx:221, 272` 已經咁用） | 是 |
| Approve & schedule 掣 | 撳 approve → mutation pending → success／error | idle → loading（spinner）→ success 'Scheduled'（0.6s 後 popover close）或 error 'Try again'；只喺今次真係批核成功先播 success。 | `web/src/components/motion/button` StatefulButton + `web/src/hooks/use-flash.ts`（同 `queue-view.tsx:137-163`） | 是 |
| Hold to cancel | 長按（或 hold Space） | 液態填充到滿先觸發 `p2_cancel`；放手未滿即取消；destructive 保留確認（§5 rule 5）。 | `web/src/components/motion/hold-action-button.tsx`（同 `queue-view.tsx:47-50, 360-377` 嘅 class 同 wave） | 是 |
| Chip 顏色轉變 | snapshot 換咗，同一個 event 嘅 kind 改變（例如 review→waiting、in-flight→verified） | 只用 `transition-colors`（現有 `event-button.tsx:37`），唔加 layout animation；popover 內 `AnimatedBadge` 自己過渡。 | 現有 Tailwind `transition-colors` + `motion/animated-badge.tsx` | 是 |
| Month 格「+」掣 | hover／focus-within（md 以上） | opacity 0→1，150ms；reduced-motion 直接顯示。 | CSS `transition-opacity` + `--duration-quick` token（`transitions.css:22`） | 否（純裝飾） |
| Now marker | 每 30s tick | 位置更新，冇動畫。 | 現有 `calendar.tsx:78-87`、`time-grid.tsx:152-169` | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Workspace snapshot 提供 reviews + jobs（含 manifest.timing.utc/local/timeZone、expiresAt、job.state、events[]、cancelRequested、nextAction、providerReference）同 channels[].displayState | api | 有 | `src/postriff_phase2/hosted_app.py:459-462` GET /api/workspaces/{id}；`store.py:74` displayState；`web/src/lib/api/types.ts:53-89, 144-151`；`hooks.ts:39-42` | S |
| 2 | `held` job state 同 review `stale` / 過期 manifest 喺前端正確分類 | frontend | 冇 | `calendar-view.tsx:71-77` 冇 held 分支；`:178-180` 只計 needs_review 且唔睇 `manifest.expiresAt`。Backend：`store.py:18-19, 292-293, 380, 419-420, 425-426, 467` | S |
| 3 | Approve 由 popover 觸發（`p2_approve` reviewId+digest+confirmed） | frontend | 冇 | Backend 存在 `store.py:287-304`，權限 `permissions.py:28`；前端只喺 `queue-view.tsx:137-163`，calendar popover `calendar-view.tsx:96-136` 冇 | M |
| 4 | Cancel 由 popover 觸發（`p2_cancel` jobId，hold 確認） | frontend | 冇 | Backend `store.py:315-320`；前端只喺 `queue-view.tsx:190-197, 360-377` | S |
| 5 | `ScheduleDialog` 接受 `initialLocalTime` 同 `onPrepared`（唔一定 push 去 /app/queue） | frontend | 冇 | `web/src/features/queue/schedule-dialog.tsx:19-24` props 只有 open/onOpenChange/variantId；`:60` 時間硬性 `defaultLocalTime()`；`:107` 固定 `router.push('/app/queue')`；時區 `:61` `useTimeZone()` | S |
| 6 | Calendar primitive 提供 `onCreateAt(date, hour?)`（month 格「+」、time grid 空位雙擊、DayPanel footer） | frontend | 冇 | `calendar.tsx:41-61` CalendarProps 冇；`month-view.tsx:105-165` 格內只有 date button 同 chips | M |
| 7 | Channel + status filter，nuqs URL state，可見 period 真實計數，channel chip 帶 displayState | frontend | 冇 | 資料齊：`phase2.channels`（`types.ts:147`，含 displayState）、`manifest.channelId/account/platform`（`types.ts:57-59`）；nuqs 已裝 `web/package.json:46`；現有 legend `calendar-view.tsx:213-220` 係靜態 | M |
| 8 | Error state（snapshot.isError → Alert + refetch） | frontend | 冇 | `calendar-view.tsx:187-222` 只分 pending／ready，error 落入空 grid；`ui/alert.tsx:12` 有 destructive variant、`:69` AlertAction | S |
| 9 | Workspace 空狀態（Empty + 按真實 variants/channels/權限 揀 CTA） | frontend | 冇 | `ui/empty.tsx:94` 有 Empty 組件；calendar 未用 | S |
| 10 | `useSnapshot` 可傳 `refetchInterval`（有 in-flight 或 5 分鐘內到期嘅 job 先 poll） | frontend | 冇 | `hooks.ts:39-42` 無 options；`lib/query-client.ts:7` staleTime 60s；worker 每分鐘 `vercel.json:57-62` → `hosted_app.py:326-332` | S |
| 11 | DST 重複時段 `fold` 揀選（first/second occurrence） | frontend | 冇 | `contracts.py:50-54` 要求 fold；`schedule-dialog.tsx:93-102` 冇送；前端可用 `Intl.DateTimeFormat` 檢測 offset 唔同 | S |
| 12 | RBAC：approve 類動作（p2_review／p2_approve／p2_cancel）限 owner／approver／can_publish；前端 access 由真 membership 建 | backend | 有 | `src/postriff_phase2/permissions.py:15-28`；前端 `web/src/lib/auth/access.tsx:69` `checkAccess`、`web/src/lib/workspace/provider.tsx:145-154`、`lib/auth/permissions.ts:24-31` | S |
| 13 | Post preview 33 templates + ManifestPreview 喺 popover | frontend | 有 | `web/src/components/application/post-preview/manifest-preview.tsx:17-22`；`calendar-view.tsx:133` | S |
| 14 | Tour 引擎 + calendar steps（`TourStep {id, route, target[], title, body\|fn(ctx), when?, stop}`） | frontend | 有 | `web/src/features/onboarding/tours.ts:28-46`（untracked，另一 session）；`tour-overlay.tsx:38-48` 順序試 selector、`:216-222` 5 秒搵唔到先跳步；`use-tour-context.ts:18-30` 真數據 ctx；`calendar-view.tsx:190` 已有 `data-tour='calendar-grid'`；`tours.ts:266-278` calendar-tips 文案過時 | S |
| 15 | 原子 `p2_reschedule`（cancel 舊 waiting job + 用同一 variant/channel/media 建新 review） | backend | 冇 | `store.py:182-339` apply_phase2 冇此分支；而家要三步 `p2_review`→`p2_approve`→`p2_cancel`（`store.py:284-320`） | M |
| 16 | Week／day view 拖放改時間（落下後要再批核） | frontend | 冇 | `time-grid.tsx:130-148` block 係 absolute 定位 EventButton，冇 drag；`@dnd-kit/core` 已裝 `web/package.json:17-20`，motion v11 亦有 drag | L |
| 17 | Preferred posting slots（ghost slots） | backend | 冇 | snapshot state 冇 slots 欄位；冇對應 action；`types.ts:180-190` SnapshotState 冇 | M |
| 18 | `p2_approve_many`（一日批核多個） | backend | 有 | `store.py:305-314`（1–10 個 reviews，共用 scheduleId）；前端 Home plan 流程已用（`web/src/features/agent/plan.ts:105`），Queue／Calendar 未用 | S |
| 19 | Unit test：kind mapping（held／expired／stale）用 `node --test` | infra | 冇 | `web/package.json:5-14` 冇 test script；`docs/postriff-worldwide-languages-plan.md:396-398` 已定 web test 用 `node --test` 直接跑 TypeScript，唔加新 dependency；kind mapping 要先抽做純 function（`calendar-kinds.ts`） | S |

## 3. Features

### P0

- **誠實嘅狀態：held、expired review、stale review 各自有 kind 同顏色**：House rule 1。而家 `held` job 顯示成藍色「Scheduled」（`calendar-view.tsx:71-77`）但 worker 已經停咗佢（`store.py:454`）；過咗 `manifest.expiresAt` 嘅 review 仍然黃色「Needs approval」但 approve 會 409（`store.py:292-293`）。用戶會等一個永遠唔出街嘅 post。
- **Error state 取代空月曆**：House rule 1：API 失敗時而家 render 空 grid，等於「Unavailable」變 0。用 Alert + Try again。
- **喺 popover 直接 Approve & schedule／Hold to cancel／Prepare again**：Calendar 係用戶最自然發現「呢日有個黃色等我」嘅地方，但而家要跳去 Queue 先做到。PostRiff 嘅版本保持 exact approval：Approve 只批核 digest；cancel 要長按；held／failed 只可以「Prepare again」。所有 mutation 同 Queue 共用一份 code，避免兩邊漂移（而家 `queue-view.tsx:31-34` 同 `live-island.tsx:23-25` 嘅 DONE 已經唔同）。（depends on：誠實嘅狀態（要先有 expired／held kind 先知道出邊個 action））
- **由任何一日開始 schedule（header「Schedule a draft」+ 格內「+」+ DayPanel footer）**：而家「New post」去 `/app`，同 calendar 嘅時間脈絡斷開。預填 focused date 令「見到空檔 → 填上」一步完成；過去日子唔會 block，只係提示並改用下一個整點（remind, don't block；backend `contracts.py:56` 係最終裁決）。`p2_review` 係 approve class（`permissions.py:28`），入口要跟 `canApprove` gate。（depends on：`ScheduleDialog` 新 prop `initialLocalTime` / `onPrepared`）

### P1

- **Channel + status filter 同 live legend（真實計數、URL 記住、displayState 誠實）**：多 account 時月曆好快變成一堆 chips。合併 legend 同 status filter 一行，數字用 DigitSwap 滾動，永遠係可見 period 嘅真實數；channel chip 帶 `displayState`，唔會暗示一個要 Reconnect 嘅 channel 可用（capability honesty）。
- **Workspace 空狀態 + period 空狀態（「Next: {date} →」）**：新用戶見到空格唔知下一步；period 內冇嘢時要有真實嘅「下一個 post 幾時」而唔係空白。CTA 按真實 variants／channels 數同權限揀，唔放 sample chip。
- **有 in-flight 或即將到期 job 時自動 refetch snapshot**：Worker 每分鐘行（`vercel.json:57-62`），但頁面唔 poll，「Publishing」badge 會對住舊資料閃。只喺有需要時每 30s refetch，其餘時間唔加負載。
- **DST 重複時段揀 first／second occurrence；手機 popover phone 縮到 0.5；post text 帶 lang／dir**：`contracts.py:53` 會 409「This time occurs twice」而 dialog 冇得揀，用戶只會見到一個 toast（等於 block）。手機 375px 上 262px 嘅 phone + 詳情 + action 太高（用 `useIsMobile()`）。languages plan §7.3 要求 post text `lang` + `dir='auto'`。

### P2

- **改時間（Reschedule）：先做 client 三步版本，再加 backend `p2_reschedule`，最後先做 week view 拖放**：PostRiff 嘅差異係「時間係 exact approval 一部分」，所以落下後必須出「Approve new time」掣，唔會靜靜改。冇原子 action 之前，三步 mutation 中途失敗會留低半完成狀態，所以拖放排最後。（depends on：backend `p2_reschedule`）
- **Preferred posting slots 做 ghost slots（dashed）**：令「揀時間」變成「揀下一個空 slot」。要 backend 儲存 slots；而且 slot 只係建議，唔會自動 approve。（depends on：backend slots state + action）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明白三件事：(1) 每粒 chip 係一個真實嘅 post，放喺佢會出街嘅確切時間（我嘅時區）；(2) 黃色 = 等我批核，藍色 = 會自己出街，橙／紅 = 要我再處理；(3) 我可以由任何一日開始 schedule。頁面點教：today tile + 標題講明「今日」；live legend 一行有顏色 + 數字（真實），一眼見到「2 需要批核」；header 只有一個 primary「Schedule a draft」；空 workspace 時 Empty block 一句講明流程（Ideas → schedule → approve）。Info sidebar 三段常駐（What shows here／Month, week and day／Changing a time），係唔會過期嘅「tour」。Tour 用現有引擎（`features/onboarding/tours.ts`）：welcome step `calendar`（`:106-113`）保留，`calendar-tips`（`:266-278`）改寫成下面幾步；每步 `target` 係 selector 陣列，`body` 可以讀 `TourCtx`（真數），唔存在嘅 target 用 `when` 或者移除 heading fallback 令引擎 5 秒後跳步。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `['[data-tour="calendar-period-nav"]', 'main [aria-label="Change period"]']（data-tour 加喺 `calendar.tsx:291` ButtonGroup）` | Move through time | Month shows the shape of your month. Week and day put each post on the hour it goes out. Today is always one click away. |
| 2 | `['[data-tour="calendar-view-select"]', 'main [aria-label="Calendar view"]']（data-tour 加喺 `calendar.tsx:303` SelectTrigger）` | Three views | Switch between month, week and day. The address bar remembers the view and the date, so a bookmark opens where you left off. |
| 3 | `['[data-tour="calendar-legend"]', 'main [aria-label="Legend"]']（現有 `calendar-view.tsx:213` ul，合併 filter 後保留呢個 aria-label）；body 用 ctx：`ctx.needsReview > 0 ? \`Yellow waits for your approval: ${ctx.needsReview} now.\` : 'Yellow waits for your approval.'`` | Colours are states | Yellow waits for your approval. Blue goes out by itself at its time. Orange or red needs a new review. Tap a colour to show only those posts.（「數字」一句只喺 filter row 落實後先加） |
| 4 | `['[data-tour="calendar-schedule"]']（header action button）；`when: (ctx) => ctx.canApprove`（TourCtx 要加 `canApprove: checkAccess(access,{permission:'approve'})`）` | Schedule from any day | Pick a draft, an account and an exact time. This prepares a review; nothing publishes until you approve it. |
| 5 | `['[data-tour="calendar-event"]', '[data-tour="calendar-grid"]']（`event-button.tsx:73` 加 data attribute，只有第一粒帶；fallback 去 grid）；`when: (ctx) => ctx.jobCount + ctx.needsReview > 0`` | Open a post | See the exact text and how it looks in the destination app. Approve or cancel here; a held or failed post can be prepared again. |
| 6 | `['[data-tour="calendar-grid"]']（時區一句合併入 grid step，唔另開只喺 week／day 存在嘅 target）` | Your time zone | Times are shown in this browser's zone. Each approval also remembers the zone it was made in, so a post never moves when you travel. |

**Empty state 教咩**：Calendar 永遠只顯示真實嘅 review 同 job——冇 sample、冇 placeholder。要填滿佢嘅唯一路徑係：Ideas 寫草稿 → Schedule a draft（揀 account 同確切時間，產生一個 review）→ Approve（先會變成 job 出現喺日曆）。Empty block 嘅 CTA 按真實 snapshot 同權限揀：有 draft 而且可以 approve 就「Schedule a draft」，冇 draft 就「Go to Ideas」，冇 channel 就加「Connect a channel」。文案對設計師、老師、店主、developer 都適用，唔提任何具體品牌或行業。

## 5. Next steps（按次序）

1. **誠實狀態：抽 `kindOf` 做純 function 檔 `calendar-kinds.ts`，加 `held`；review 分 `needs_review`（未過期）／`expired`（`manifest.expiresAt <= Date.now()/1000`）／`stale`（`review.status==='stale'`）；KIND_META 加三個 kind（held=orange/warning、expired=red/danger 無 pulse、stale=gray/neutral）；legend 跟住更新；popover 詳情按 kind 顯示 `job.events.at(-1).message` + `job.nextAction`。加 `calendar-kinds.test.ts` 用 `node --test`。**（effort S）  
   檔案：`新增 web/src/features/calendar/calendar-kinds.ts、calendar-kinds.test.ts；web/src/features/calendar/calendar-view.tsx`
2. **Error + empty state：`snapshot.isError` → Alert + AlertAction Try again（`snapshot.refetch()`），401/403 交 gate；`isSuccess && reviews.length===0 && jobs.length===0` → Empty block（CTA 按 `variants.length`／`phase2.channels.length`／權限）；period 內零 event → 「No posts in this period · Next: {date} →」。**（effort S）  
   檔案：`web/src/features/calendar/calendar-view.tsx；web/src/components/ui/alert.tsx；web/src/components/ui/empty.tsx`
3. **抽共用 action 組件：由 `queue-view.tsx` 抽出 `ReviewApproveButton`（StatefulButton + useFlash + p2_approve + 409 invalidate + daily-limit reminder）同 `JobCancelHold`（HoldActionButton + p2_cancel，含 remount-on-error 邏輯、touch-action none）到新檔；同時抽 `JOB_STATES`（WAITING／IN_FLIGHT／DONE／FAILED）一份畀 Queue、LiveIsland、Calendar 共用；Queue 同 Calendar popover／DayPanel list 都用佢；calendar 用 `checkAccess(access,{permission:'approve'})` 決定顯示。**（effort M）  
   檔案：`新增 web/src/features/queue/review-actions.tsx、web/src/lib/job-states.ts；改 web/src/features/queue/queue-view.tsx；web/src/components/layout/live-island.tsx；web/src/features/calendar/calendar-view.tsx（PostDetails）`
4. **由日曆 schedule：`ScheduleDialog` 加 `initialLocalTime?: string`（用 dialog 嘅 `useTimeZone()` zone 解讀）同 `onPrepared?: (snapshot) => void`（有就唔 push 去 /app/queue）；`Calendar` 加 `onCreateAt?: (date, hour?) => void`（冇傳就唔 render 入口）；month 格加 hover／focus 「+」（md 以上）；time grid 空位雙擊；DayPanel footer 「Schedule on this day」；header action 改「Schedule a draft」；全部入口跟 `canApprove`；過去日子提示唔 block。**（effort M）  
   檔案：`web/src/features/queue/schedule-dialog.tsx；web/src/components/application/calendar/calendar.tsx；web/src/components/application/calendar/month-view.tsx；web/src/components/application/calendar/time-grid.tsx；web/src/features/calendar/calendar-view.tsx`
5. **Filter row + live legend：新組件讀 `phase2.channels`（含 displayState）同 events，計可見 period（用 `visibleRange`）內每 channel／kind 真實數，DigitSwap 顯示；nuqs `channel`、`kind`（`parseAsArrayOf`），預設全選時唔寫 URL；filter 後嘅 events 傳入 `Calendar`；chip title／popover 文字加 `lang`／`dir='auto'`。**（effort M）  
   檔案：`新增 web/src/features/calendar/calendar-filters.tsx；web/src/features/calendar/calendar-view.tsx；web/src/components/application/calendar/event-button.tsx（lang）；web/src/components/motion/digit-swap.tsx（reuse）`
6. **Live refresh：`useSnapshot(options?: { refetchInterval?: number | false })`；calendar 計 `needsLive = jobs.some(in-flight) || jobs.some(waiting && utc - now < 5min)` → 30_000，否則 false；`refetchIntervalInBackground: false`。**（effort S）  
   檔案：`web/src/lib/api/hooks.ts；web/src/features/calendar/calendar-view.tsx`
7. **手機 popover：`ManifestPreview scale` 用 `useIsMobile() ? 0.5 : 0.62`（`hooks/use-mobile.ts`）；action 掣 full width。DST：dialog 內用 Intl 檢測揀嘅 local time 喺該 zone 有兩個 offset 時顯示 RadioGroup「First occurrence／Second occurrence」，送 `fold: 0|1`。Profile zone 同 browser zone 唔同時 popover 加一句。**（effort S）  
   檔案：`web/src/features/calendar/calendar-view.tsx；web/src/features/queue/schedule-dialog.tsx`
8. **Tour 同 docs：`tours.ts` calendar-tips 改寫成上面 steps（加 `canApprove` 入 `TourCtx`）；加 `data-tour` 去 `calendar.tsx:291, 303`、`event-button.tsx:73`；更新 `docs/postriff-motion-system.md` §1 Calendar 一行（Select + Popover + StatefulButton + HoldActionButton + DigitSwap，month/week/day）；`components/application/calendar/README.md` 加 `onCreateAt` 用法；info sidebar 第三段改寫成「Changing a time」；`access.tsx:3-9` 過時「stub」註解一併修正。呢步要同做緊 onboarding 嘅 session sync。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts；web/src/features/onboarding/use-tour-context.ts；docs/postriff-motion-system.md；web/src/components/application/calendar/README.md；web/src/features/calendar/calendar-view.tsx（infoContent）；web/src/lib/auth/access.tsx（註解）`
9. **Backend `p2_reschedule`：`apply_phase2` 新分支 `reschedule`（hosted.py 會剝 `p2_`），payload `{ jobId, localTime, timeZone, fold? }`；驗證 job 喺 WAITING、`resolve_time`、同一 variant/channel/media 用 `build_manifest` 建新 review、舊 job `cancelRequested`；`permissions.py` ACTION_CLASSES 加 `'p2_reschedule': 'approve'`；`types.ts` 無需改（回傳 snapshot）；Python test 喺 `tests/`。之後前端「Change time…」喺 popover 開 dialog（只有時間欄）。**（effort M）  
   檔案：`src/postriff_phase2/store.py；src/postriff_phase2/permissions.py；tests/（新 test）；web/src/features/calendar/calendar-view.tsx`
10. **Week／day 拖放：用 motion `drag='y'`（或 `@dnd-kit/core`）拖 waiting job 嘅 block，snap 15 分鐘，落下後喺原位出 popover「Approve new time {time}」（StatefulButton → `p2_reschedule` 再 `p2_approve`）或「Keep original」；in-flight／終結／held 唔可拖；reduced-motion 下改用 popover 內 time input。**（effort L）  
   檔案：`web/src/components/application/calendar/time-grid.tsx；web/src/components/application/calendar/event-button.tsx；web/src/features/calendar/calendar-view.tsx`

## Risks

- Popover 內做 mutation 會令 Queue 同 Calendar 有兩份 approve／cancel 邏輯；如果唔先抽共用組件（next_steps #3），兩邊嘅 WAITING／DONE set 同 error handling 好快漂移（而家 `queue-view.tsx:31-34` 同 `live-island.tsx:23-25` 已經各自定義，DONE 一個係 `['verified']` 一個係 `['published','verified']`）。
- Approve 用 `snapshot.revision`；如果 popover 開住期間 snapshot 由其他 tab 或 refetch 換咗，`p2_approve` 會 409。`useAct` 冇 onError（`hooks.ts:150-162`），要喺 error 時 invalidate snapshot 並提示「Reloaded; try again」，唔好靜靜重試。
- 時區三個來源（browser zone、profile `useTimeZone()`、manifest approved zone）：Calendar grid 用 browser、ScheduleDialog 送 profile zone。`initialLocalTime` 如果用 browser zone 計而 dialog 用 profile zone 解讀，預填會錯一個 offset；要統一由 dialog 嘅 zone 計，並喺 popover 註明 profile zone 唔同時嘅時間。
- 權限：`p2_review` 同 `p2_approve` 同一個 approve class（`permissions.py:28`）；Queue 而家用 `canApprove || edit` 顯示 Schedule 掣（`queue-view.tsx:209`）係寬鬆咗，editor 冇 can_publish 撳落去會 403。Calendar 唔好跟，全部 schedule 入口用 `canApprove`。
- Dev harness 嘅 Threads 係 live provider（memory note）：喺 :3100 測試 Calendar 嘅 Approve 會真發文。驗證只可以用 fixture channel（`evidenceSource: synthetic`），或者只 code review + typecheck。
- 另一個 session 正在改 `web/src`（memory note）：`calendar-view.tsx` 已有未 commit 嘅 `data-tour` 改動，`features/onboarding/` untracked；`schedule-dialog.tsx`、`hooks.ts` 都係共用檔，落實前要先 sync，commit 時按 path stage。
- `held` 由 `expired` review 分開後，legend 會有 9 個 kind；手機一行放唔落，要 `overflow-x-auto`，並確保 filter chip 嘅 aria-pressed 同數字都讀得出。
- Expired／stale 判斷用瀏覽器時鐘對 `manifest.expiresAt`；時鐘偏差大嘅裝置會早／遲一分鐘顯示 expired。真正嘅裁決仍然係 backend 409，所以 UI 應該只係「提示 + 唔出 Approve」而唔係 hard block。另外 `store.py:425` 令過咗 expiresAt 嘅 waiting job 變 held，所以「expired」只會出現喺 review，job 就會係 held。
- Live refetch（30s）喺多個 tab 同時開 Calendar 時會倍增 API 讀取；只喺有 in-flight／即將到期 job 時開，並且 `refetchIntervalInBackground: false`。
- 拖放改時間：三步 mutation（review → approve → cancel）中途失敗會留低「新 review 未批 + 舊 job 仍 waiting」；所以拖放必須等 backend `p2_reschedule` 先做，而且落下後永遠要一個明確嘅「Approve new time」掣，唔可以靜靜改（exact approval 原則）。
- 每日上限（`store.py:21, 297-300` DAILY_LIMITS，只有 Instagram/Threads/LinkedIn）而家只喺 approve 時 409；Calendar 可以按 channel 計當日 waiting／in-flight 數量預先提示（remind），但唔應該 disable Approve 掣；前端要 mirror 同一個表，唔好自己估其他 platform 嘅上限。
- Base UI Popover 會喺 outside click 收埋；HoldActionButton 長按期間 pointer 出咗 popover 會 cancel hold（預期行為），但要確保 popover 唔會因為 hold 觸發嘅 re-render 而 close；touch 裝置要 `touch-action:none` 免長按觸發選字。
- URL filter state 同 `date`（today 唔寫）要一致：全選時唔寫 `channel`／`kind`，否則 bookmark 會鎖死一個舊 filter。
- `docs/postriff-motion-system.md:44` 同 `tours.ts:266-278` 都同 code 唔符（Month/List）；如果唔同步更新，下一個做 motion 或 tour 嘅人會照住錯嘅 inventory 去做。
- Tour 引擎嘅 `heading()` fallback（`main h1`）令「target 唔存在就 skip」實際上唔會發生——會指住頁面標題。只喺某 view 先存在嘅 target（例如時區 label）唔應該獨立成一步。

## 覆核記錄

- 改正：`Manifest.expiresAt: number` 喺 `types.ts:64`；`job.nextAction` 喺 `types.ts:77`；`phase2.channels` `types.ts:145`；`manifest.account/platform` `types.ts:56-57`；SnapshotState `types.ts:177-187` → 用上面實際行號
- 改正：Post preview：33 個 channel template + generic；`PostPreview` lazy load（`post-preview.tsx:11-19`）；`PhoneSkeleton`（`post-preview.tsx:48-56`）；媒體 cache key `['media', w, id]`（`use-preview-post.ts:22-28`）；`draft-preview.tsx` untracked；README 誠實規則 `:28-34` → PhoneSkeleton 寫 `post-preview.tsx:67, 83`；lazy 寫 `:14-24`
- 改正：`useSnapshot` 冇 `refetchInterval`；`staleTime: 60s`（`query-client.ts:7`）；worker cron 每分鐘（`vercel.json:57-60`，`hosted_app.py:346-356`）；`LiveIsland`（`live-island.tsx:204-213`）每 30s 重計 → 寫 `hosted_app.py:326-332`
- 改正：`queue-view.tsx:31-34` 同 `live-island.tsx:4-6` 各自定義 WAITING／DONE set → 寫 `live-island.tsx:23-25`，並指出兩邊 DONE 定義已經唔同
- 改正：`schedule-dialog.tsx:37` props 只有 open/onOpenChange/variantId；時間預設 now+1h 整點（`:27-31, 59`）；時區用 `Intl`（`:60`）；payload 冇 `fold`（`:92-101`）；`:106` 固定 `router.push('/app/queue')` → 時區改寫成「`useTimeZone()` 讀 profile preference（`lib/preferences.tsx:36-45`）」；行號 :107
- 改正：`p2_approve_many` 存在（`store.py:306-315`）但前端未用 → 改寫成「前端只有 Home plan 流程用（`plan.ts:88-105`），Queue／Calendar 未用」
- 改正：`useMediaQuery('(min-width: 640px)') ? 0.62 : 0.5`（next_steps #7） → 用 `useIsMobile()`（<768 → 0.5）或者 react-responsive；唔好用字串參數 call 現有 hook
- 改正：Tour targets 全部係要新加嘅 data-tour；「tour 引擎要 skip 唔存在嘅 target」 → tour_steps 改寫成 tours.ts 嘅 TourStep 形狀，用 `when` 唔用「引擎 skip」，並修正 calendar-tips 文案
- 違反原則（已改）：Rule 1（真數據）：next_steps #7 用 `useMediaQuery('(min-width: 640px)')`——現有 hook 唔收參數，照寫會永遠拎到 `{isOpen}` object（truthy）→ 手機都用 0.62；要改用 `useIsMobile()` 或 react-responsive。
- 違反原則（已改）：Rule 1（真數據）：tour step「Colours are states」講「The numbers count what is in view」——如果 filter row 未落實（next_steps #5 係 P1），呢句會講緊一啲唔存在嘅數字；tour 文案要用 `TourCtx.needsReview`（真數）或者等 filter 落實先講數字。
- 違反原則（已改）：Rule 4（motion）：technical_requirements「Unit test」評估寫「冇 vitest／playwright」，但 `docs/postriff-worldwide-languages-plan.md:396-398` 已經決定 web 用 `node --test` 直接跑 TypeScript，唔應該提議新裝 test runner。
- 違反原則（已改）：Rule 6（stack）：status_now 話 ScheduleDialog 時區「用 `Intl`」——實際係 `useTimeZone()`（profile preference，`lib/preferences.tsx`），spec 建議嘅 `initialLocalTime` 如果用 calendar 嘅 browser zone 計，同 dialog 送出嘅 profile zone 可能唔一致，會令預填時間錯一個 offset。
- 違反原則（已改）：Rule 5（capability honesty）：filter row 嘅 channel chips 只寫「ChannelIcon + account」，冇講 `displayState`；一個「Reconnect」或「Finish setup」嘅 channel 同「Ready for posting」嘅一樣出現會暗示佢可用。要喺 chip 附帶 displayState（非 Ready 時），永遠唔出「Connected ✓」。
- 違反原則（已改）：General-not-personal：冇違反（文案全部通用）。Remind-don't-block：冇違反（過去日期只提示、approve 過期只唔出掣、backend 做最終裁決）。
- 補上遺漏：Tour 引擎已存在（`web/src/features/onboarding/`，untracked，另一 session 進行中）：spec 要按 `tours.ts` 嘅 `TourStep`／`TourCtx` 形狀寫 steps，並修正 `tours.ts:266-278` calendar-tips 過時文案（「Month or list」）；`data-tour='calendar-grid'` 已經加咗喺 `calendar-view.tsx:190`。
- 補上遺漏：時區來源不一致：Calendar grid 用 browser zone（`useLocalTimeZone`），ScheduleDialog 用 profile zone（`useTimeZone`）。要決定：由 Calendar 開 dialog 時 `initialLocalTime` 用邊個 zone 計，同 popover 顯示 profile zone 唔同 browser zone 時嘅提示（現有 `approvedZone` 邏輯只比較 approved vs browser）。
- 補上遺漏：RBAC 全貌：Calendar nav item 冇 `access` key → viewer 都見到頁面（read）；`approve` class = owner／approver／can_publish（`permissions.py:18`）；`p2_review`（Schedule a draft）都係 `approve` class（`permissions.py:28`），所以「Schedule a draft」掣、格內「+」、DayPanel footer 都要同 Approve 一樣用 `checkAccess(access,{permission:'approve'})` gate，editor 冇 can_publish 係唔可以 prepare review 嘅（Queue :209 用 `canApprove || edit` 顯示 Schedule 掣係寬鬆咗，Calendar 唔好跟）。
- 補上遺漏：i18n／languages plan：`docs/postriff-worldwide-languages-plan.md §7.3` 要求 post text 帶 `lang="<tag>"` + `dir="auto"`——chip title（`manifest.payload.text` 第一行）、popover 內文、DayPanel list 都要加；`§7.4` 字數用 `Intl.Segmenter` 截斷。Calendar 日期格式用 `DEFAULT_LOCALE='en'`（config.ts:91）同 `Intl.DateTimeFormat('en', …)`（calendar-view.tsx:90, 100）hard-code，preference 有 `locale`（`lib/preferences.tsx:41`）未接上；至少列做 known gap。
- 補上遺漏：`held` 嘅來源唔止一種：`store.py:425-426`（manifest 唔 current／channel 唔 Ready／trial 過期／manifest 過期）同 `:467`（approval authority 變）。popover 要顯示 `job.events` 最後一條 message（真實原因），唔好只顯示 `nextAction`。
- 補上遺漏：Daily limit 預提示（risks 有提）冇落入 sections／next_steps：可以喺 popover Approve 旁邊按 `DAILY_LIMITS` + 當日該 channel waiting/in-flight 數出一句 reminder（真數），但 backend 只 enforce Instagram/Threads/LinkedIn 三個 platform，前端要 mirror 同一個表。
- 補上遺漏：Mobile：spec 有講 375px；漏咗 hold-to-cancel 喺 touch 上嘅 pointer 行為（HoldActionButton 支援 hold Space；popover 內長按可能觸發 iOS 選字／context menu，要 `touch-action: none` + `user-select: none`）。
- 補上遺漏：Error handling：`ApiError` 401／403（session 過期、無 workspace）由 app-gate 處理定由 Calendar Alert 處理要講清楚；Alert 只應處理 5xx／network，401 交 gate。
- 補上遺漏：Shared working tree：`calendar-view.tsx` 已經有另一 session 嘅未 commit 改動（data-tour），`features/onboarding/` untracked；next_steps 要註明按 path stage、先 sync。
