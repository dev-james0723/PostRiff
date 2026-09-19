# 10 · Queue

> Route：`/app/queue` · Sidebar：Distribute · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

已經有嘅嘢（全部讀真 snapshot）：

- Route：`web/src/app/app/queue/page.tsx:1-8` render `QueueView`；sidebar entry `web/src/config/nav-config.ts:69-75`（icon `listDetails`、shortcut q q，冇 `access` key，所有 member 包括 viewer 都見到）；sidebar badge 只數 `needs_review`（`web/src/components/layout/app-sidebar.tsx:127-130`）。
- 數據：`useSnapshot()`（`web/src/lib/api/hooks.ts:39-42` → `GET /api/workspaces/{id}`，`src/postriff_phase2/hosted_app.py:459-462` → `hosted.py:504-507` `_present` → `store.py:64-75`）。Mutation 行 `useAct()`（`hooks.ts:151-163` → `POST .../actions` `hosted_app.py:477-485` → `hosted.py:156-160` command → `hosted.py:186-203` → `store.py:182` `apply_phase2`）。Response 係成個 snapshot（`client.ts:137-138`）。
- 兩個 section：「Waiting for approval」（`queue-view.tsx:216-259`，`data-tour='queue-approvals'`）同「Publishing jobs」（`:261-390`，`data-tour='queue-list'`）。
- `ReviewCard`（`:96-171`）：frozen manifest 詳情 + `ManifestPreview` scale 0.5（`:129-133`）；「Approve & schedule」送 `p2_approve {reviewId,digest,confirmed:true}`（`:147-149`；後端 `store.py:287-305`：digest、stale 檢查、idempotency、`DAILY_LIMITS` `store.py:21`）；expired `manifest.expiresAt <= now`（`:100`；`expiresAt = timing+3600`，`store.py:380`）。
- Jobs table 七欄（`:292-387`）、last event（`:306, :338-340`）、eye popover（`:343-356`）、`HoldActionButton` 900ms（`:361-377`，`p2_cancel` → `store.py:316-321`），7rem slot（`:359`）。
- Filter pills（`:267-276`）＋ state sets（`:31-34`）。同一套 vocabulary 已經喺 `web/src/features/pipeline/job-state.ts:11-67` 有更完整版本（`jobGroup` 分 waiting/publishing/uncertain/held/verified/ended、`jobBadge`），註解 `:4-6` 寫明要搬去 `features/queue/job-state.ts` 共用。
- 權限：UI `checkAccess(access,{permission:'approve'})`（`:178`），access 由 `web/src/lib/workspace/provider.tsx:145` 用 `permissionsFor(membership)`（`web/src/lib/auth/permissions.ts:14,22-29`）派生，UI-only。API 執法：`permissions.py:28` 將 `p2_review/p2_approve/p2_approve_many/p2_cancel` 歸 `approve`；approve = owner 或 approver role，或任何帶 `can_publish` 嘅非 viewer（`permissions.py:18, 59-65`）。
- `ScheduleDialog`（`web/src/features/queue/schedule-dialog.tsx`）：`accept_update` → `p2_variant_review` → `p2_review`（`:69-110`），完成 `router.push('/app/queue')`；Pipeline preselect（`pipeline-view.tsx:134`）。
- Worker：`src/postriff_phase2/hosted_worker.py` claim（`:39-90`；re-auth `:62-69` 失敗寫 held `:68`；3 attempts 上限 `:70-72` 寫 failed；45s lease `:73-75`）、complete（`:92-136`，寫 `providerReference/providerConfirmed/verification/nextAction`，nextAction 只喺 complete 更新）。Cron 每分鐘（`vercel.json:57-62`，`hosted_app.py:326-337`）。`invalidate`（`store.py:416-426`）將 review 標 `stale`、waiting job 標 `held`（唔更新 nextAction）。
- Tour：`web/src/features/onboarding/tours.ts:97-107` 已有 Queue step，target `[data-tour="queue-approvals"]` → `queue-list` → tablist；TourCtx 有 `needsReview/jobCount/canEdit`（冇 canApprove）。
- Motion：`AnimatedBadge`、`HoldActionButton`、`StatefulButton`、`Tabs`、`DigitSwap`（`docs/postriff-motion-system.md:44`）；`t-page-enter`（`web/src/app/app/template.tsx:13`）；approvals stagger 50ms×≤6（`:247`，超出 §5 嘅 40ms）；rows 30ms×≤10（`:315`）；`REVIEW_EXIT` 0.6s delay（`:53`）。
- 入口：Live island（`live-island.tsx:428, 470`）、Calendar（`calendar-view.tsx:122, 208`）、Home（`home-view.tsx:116`）、Overview（`overview-view.tsx:211`）、Plan card（`plan-card.tsx:275, 389`）、Analytics post sheet（`post-sheet.tsx:154`）全部 link 去 `/app/queue`，冇 deep link 到 job。

已知 gaps：
1. Loading 時 filter 計數 `DigitSwap value={0}`（`:267-276`）— Unavailable 變 0。
2. 冇 `isError` 分支，API 失敗照顯示「Nothing to approve」「No jobs here」（`:225-289`）。
3. `held`／`uncertain` 冇獨立 filter；held badge neutral（`:79`）只喺 All 出現。
4. `verification`、`events` 全 timeline、`manifest.execution`、`nextAction` 冇 render；`approvedBy/approvedAt/nextAt/checks/scheduleId`（`store.py:302`）、`events[].execution`（`store.py:412`、`hosted_worker.py:37`）、`Review.createdAt`（`store.py:286`）有落 client 但 `types.ts:71-89` 冇 declare。
5. 冇 `refetchInterval`（`hooks.ts:39-42`），`staleTime` 60s（`query-client.ts:7`）。
6. Filter／job 唔喺 URL（`:179`）。
7. `ScheduleDialog` 唔送 `fold`，DST 重複時間 409（`contracts.py:53-54`）。
8. 過咗 scheduled time 但未過 expiresAt 仍可 approve，冇 reminder。
9. Stale reviews 完全隱藏（`:185` filter）。
10. 「Failed」計數包埋 canceled（`:34, :86`）。
11. 手機七欄 table 只靠 `overflow-x-auto`（`:291`）。
12. Header「Schedule a draft」edit 權限都顯示（`:209`），但 `p2_review` 要 approve，editor 做到第三步先 403。
13. ScheduleDialog 語言硬寫「繁中／EN」（`schedule-dialog.tsx:136, 144`），同 worldwide languages 決定唔夾。
14. `docs/postriff-motion-system.md:112`：Approve／HoldActionButton 未喺真實流程播過。

## 1. Design specification（最新版）

**目的**：一頁答兩個問題：「有咩等緊我批？」同「批咗嘅嘢而家去到邊、有咩 receipt？」。批核係 exact approval（text＋media＋account＋time 凍結成 manifest digest），所以每個數、每個 state、每句說明都係 API 原話；唔扮進度、唔混合狀態、唔將 Unavailable 變 0。

**Layout**：保留兩段式：`PageContainer` header（title「Queue」、description、info sidebar、右邊 primary action）→ Section A「Waiting for approval」（card grid，底部可摺「Stale reviews」）→ Section B「Publishing jobs」（toolbar + table/cards）。Row click 開 job detail `Sheet`，`?job=<id>` 同 `?filter=` 用 nuqs 保存。Info sidebar（`queue-view.tsx:57-72`）加「Held」同「Uncertain」兩段。

Primary action gating：有 approve → 「Schedule a draft」；得 edit → 唔出掣，改一句 muted reminder「An approver prepares and approves the exact schedule.」；viewer → 乜都唔出，頁面照睇 receipts。

Responsive：
- 1440：approvals 兩欄（現有 `min-[1400px]:grid-cols-2`）；jobs 七欄 table；Sheet 右側，className override 到 `sm:max-w-lg`（預設 `sm:max-w-sm`，`sheet.tsx:56`）。
- 768：approvals 一欄（現有 `md:grid-cols-[minmax(0,1fr)_auto]`）；table 收起 Provider 欄（搬入 Sheet）；Sheet `sm:max-w-md`。
- 375：approvals 一欄、iPhone 喺詳情下面；jobs 轉 card list（state badge＋destination／scheduled＋attempts／last event／actions）；filter pills 橫捲（現有）；Sheet 改 `Drawer`（`web/src/components/ui/drawer.tsx`）由底升起；polling 只喺 tab visible 時行。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header | 定位同唯一入口 | title「Queue」、description「Approvals waiting on you, then everything the worker is handling.」。Primary action 只俾 approve 權限（修正 `:209`）；edit-only 顯示 reminder 句子。加 `data-tour="queue-schedule"`。Info sidebar：Exact approvals／Job states／Cancel／Held／Uncertain。Sample workspace（`hosted.py:195-196` read-only）：掣 disabled＋「Sample workspaces are read-only.」。 | viewer：冇 action，頁面可讀。edit-only：reminder。approve：掣。 |
| Waiting for approval | 批核 exact manifest；每張卡就係一份合約 | 保留 `ReviewCard`。新增（a）Time-passed reminder：`Date.parse(manifest.timing.utc) < Date.now()` 且未 expired → footer 改「The approved time has passed; approving now publishes at the worker's next run.」（唔 block）。（b）heading 右邊「Approve all N」（N = needs_review、未 expired，最多 10；超過 10 就「Approve first 10」）→ confirmation dialog 逐行列 platform·account·local time (zone)·digest 前 8 位，寫明「All or nothing: if one fails, none is approved.」，confirm 送 `p2_approve_many {confirmed:true, reviews:[{reviewId,digest}]}`。（c）manifest.payload.language 照原值顯示，唔縮成 繁中／EN。（d）第一張卡 iPhone wrapper 加 `data-tour="queue-review-phone"`；section 已有 `data-tour='queue-approvals'`。 | Loading：Skeleton h-32（現有）。Empty：現有一句。Error：見 error_state。Approve 成功：「Scheduled」0.6s 後淡出（現有）。Approve 失敗：toast 原文（例如 DAILY_LIMITS 409、「This approval is stale」）＋ StatefulButton「Try again」；409 revision conflict 自動 `snapshot.refetch()` 再提示。Expired：掣 disabled＋現有句子。冇 approve 權限：冇 footer（現有）。 |
| Stale reviews（新，可摺） | 話俾人知邊啲 review 已作廢，同一鍵重新準備 | Section A 底部 `Collapsible`（`web/src/components/ui/collapsible.tsx`）：「N reviews went stale」（N = `reviews.filter(r => r.status === 'stale').length`；N=0 唔 render）。每行 platform·account·timing.local·text 頭 60 字＋「Prepare again」（approve 權限先出）→ 開 `ScheduleDialog` preselect `manifest.variantId`。唔顯示原因（`store.py:420` 冇記錄）。只保留最近 20 個 reviews（`store.py:286`），所以唔寫「all stale reviews」。 | N=0 隱藏。variant 已刪／blockedByRetraction／voice revision 唔 usable：掣 disabled，title「This draft is no longer available」。 |
| Publishing jobs toolbar | 篩選同對數 | 先將 `web/src/features/pipeline/job-state.ts` 搬去 `web/src/features/queue/job-state.ts`，兩頁共用 `jobGroup`／`jobBadge`。Filter 用 group：All／Waiting／Publishing／Uncertain／Held／Verified／Ended（failed＋canceled）。計數 `DigitSwap`，`snapshot.isLoading` 或 `isError` 時只 render label。`?filter=` nuqs `parseAsStringLiteral`。toolbar 右一句 muted：「Latest worker event · {relativeTime(max events.at where execution==='hosted-worker')}」；冇就「No worker events recorded yet」。唔叫佢做 heartbeat。TabsList 現有 `aria-label='Filter jobs'`。 | Loading：label only。Error：唔 render 計數。 |
| Jobs table / cards | 每個 job 一行 receipt 摘要；點入睇全份 | ≥md 欄：State（`jobBadge(job)`；held／failed／uncertain 下面一行 muted 顯示最後 event message，唔用可能過時嘅 nextAction）、Destination（icon＋platform·account；`manifest.execution==='synthetic'` 加 `AnimatedBadge size='sm' status='neutral'`「Fixture」，title「Synthetic provider; nothing reaches a real account」）、Scheduled（`formatDateTime`；waiting job 加 aria-hidden 倒數，用抽出嘅 `countdown()`，過咗時間顯示「due」直至 state 改變）、Attempts（`attempts.length`；uncertain 另顯示 `checks` 次 reconcile，因為 attempts 上限 3 只計 submission，`hosted_worker.py:70`）、Provider、Last event（現有）、Actions（eye popover、details icon 開 Sheet、`HoldActionButton` 只喺 WAITING 且 approve 權限）。Row click 開 Sheet。`<md` card list 同一數據。首行 `data-tour="queue-job-row"`，首個 hold 掣 `data-tour="queue-cancel"`。 | Loading：Skeleton h-48。Filter 空：「No {label} jobs」＋一句該 group 意思（Held：「A held job needs a new review; nothing publishes from it.」；Uncertain：「The provider did not confirm; PostRiff reconciles and never resubmits.」）。Cancel pending：`cancelling`（jobBadge）。Cancel 失敗：toast＋`holdEpoch` remount（現有）。 |
| Job detail Sheet（新） | 成份 receipt：時間線、attempts、provider 原話、verification | `Sheet`（<md `Drawer`）由 `?job=<id>` 控制。Header：platform·account＋jobBadge＋Fixture（如適用）。(1)「What was approved」：`ManifestPreview` scale 0.6、timing.local (timeZone) 同 viewer 本地時間、language 原值、media 數、digest 全字 mono＋copy。(2)「Timeline」：`job.events` 全部（at、state、message、execution 原值）。(3)「Attempts」：number／startedAt／endedAt（冇 endedAt 而 state 仍 publishing →「still running」，否則「No end recorded」）；uncertain 顯示 checks。(4)「Provider」：providerReference（mono＋copy）、providerConfirmed 原文、verification method＋時間（冇就「Not verified」）；`nextAction` 只喺最後 event execution==='hosted-worker' 時以「Last worker note」顯示。Footer：「Approved by you」（`approvedBy === useMe().data.userId`）或「Approved by a teammate」＋`formatDateTime(approvedAt)`；held／failed 且 approve 權限 →「Prepare again」；waiting → hold cancel。有 analytics post（`useAnalytics().data.posts.some(p => p.jobId === job.id)`）先出「View performance」。 | `?job` 唔存在：「This job is not in the workspace」＋close。Snapshot loading／error：Sheet 唔開。 |
| Schedule dialog（現有，polish） | 準備 exact review | 保留三步 chain。(a) DST：`p2_review` 409 含「occurs twice」→ RadioGroup（`web/src/components/ui/radio-group.tsx`）「First occurrence／Second occurrence」→ 重送 `fold: 0\|1`。(b) Image select 加 40px thumbnail（`api.media()`，同 `usePreviewPost` cache）。(c) Draft label 顯示 `variant.language` 原值（或 channel locale），唔再硬寫「繁中／EN」。(d) 冇該 platform 帳號：disabled item＋link「Connect a {platform} account」去 `/app/channels`（reminder）。(e) P2 Next free slot。 | 冇 active voice：現有 CTA `/app/workspace/brand`。冇 draft：現有 disabled item。edit-only 用戶唔會開到（header gating）。 |

- **Empty state**：兩個 section 都空且 `!isLoading && !isError`：一個 `Empty`（icon `listDetails`）教三步：「1. Schedule a draft — pick a draft, an account and an exact time. 2. Approve the exact text, media and time here. 3. The worker publishes at that time and records what the provider confirmed.」。CTA「Schedule a draft」（approve 權限）；edit-only 改為 reminder 句；`state.variants` 空加「Draft something in Ideas」；冇 channel `displayState === 'Ready for posting'` 加 reminder link `/app/channels`（dialog 照開得）。Filter 空：「No {label} jobs」＋該 group 解釋。
- **Loading**：保留兩個 Skeleton（`:226`、`:279`）。Filter pills loading 時唔 render `DigitSwap`；approvals count Badge 已經 `reviews.length > 0` 先出。倒數、worker event 一句、Stale 行、Sheet 喺 loading 時唔 render。唔加任何 loading 文案扮進度。
- **Error**：`snapshot.isError` → 兩個 section 位置改一個 `Alert`（`web/src/components/ui/alert.tsx`）「The queue could not be loaded.」＋ `err instanceof ApiError ? err.message : ''` ＋「Retry」`StatefulButton`（`snapshot.refetch()`）。有舊 data 而 refetch 失敗：保留舊 data，toolbar 一句「Showing the last loaded state · {relativeTime(dataUpdatedAt)}」。Mutation 錯誤：toast 原文；revision 409 自動 refetch＋toast「The workspace changed; the queue is up to date now.」。403（冇權限／sample read-only）照出 server 原話。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 頁面進入 | route mount | 整頁 slide＋fade | `t-page-enter`（web/src/app/app/template.tsx:13；web/src/styles/transitions.css:252） | 否（純裝飾） |
| Approval cards 進場 | reviews 由 snapshot 到達 | opacity 0→1、y 8→0；stagger 由 50ms 改 40ms（`Math.min(index,6)*0.04`，stagger 總長 240ms ≤ 300ms）；reduced motion `initial=false` | 現有 motion.div（queue-view.tsx:243-250），只改 delay | 是 |
| Approve 成功離場 | p2_approve 成功後 review 唔再 needs_review | StatefulButton「Scheduled」，停 0.6s 再 0.22s 淡出；其餘卡 layout spring 補位 | 現有 `REVIEW_EXIT`＋`SPRING_LAYOUT`（queue-view.tsx:53, 249） | 是 |
| Approve all 確認掣 | confirm dialog 撳 Approve N | loading「Approving…」→ success「Scheduled N」（N = snapshot 入面同一 scheduleId 嘅 job 數）→ dialog 收埋，close 用 `--duration-quick`，快過 open | `StatefulButton`（web/src/components/motion/button）＋`t-modal`（transitions.css:183） | 是 |
| Filter 計數 | jobs 數量變（mutation／refetch） | 數字滾動；loading／error 時唔 render | `DigitSwap`（web/src/components/motion/digit-swap.tsx） | 是 |
| State badge 轉態 | refetch 後 job.state 改變 | badge crossfade；只有 publishing／cancelling pulse；held、uncertain warning 唔 pulse | `AnimatedBadge`＋`jobBadge()`（web/src/features/pipeline/job-state.ts:47-67，搬去 features/queue） | 是 |
| Verified 一刻 | 頁面開住時某 row 由非 verified 變 verified（ref 記上一次 state；首次 load 唔播） | State cell 播一次 success check；reduced motion 只做 opacity | `t-success-check`（transitions.css:481）／`web/src/components/ui/success-check.tsx` | 是 |
| Scheduled 倒數 | 每 30s tick | 純文字更新，aria-hidden，冇動畫；過咗時間顯示「due」直至 state 變 | live-island.tsx:131-139 `countdown()`＋TICK_MS（:30）抽去 `web/src/lib/time.ts` | 是 |
| Hold to cancel | 長按 900ms（或 Space） | liquid fill；完成「Cancelling…」；失敗 remount | 現有 `HoldActionButton`（queue-view.tsx:361-377）＋ job-state.ts hold classes | 是 |
| Job detail Sheet 開合 | row click／details icon／`?job=` 變化 | 右側 panel 開合，收快過開（用 t-panel 現有 token，唔另寫時間）；<md Drawer 由底升起 | `t-panel`（transitions.css:215-239）＋`Sheet`／`Drawer` | 否（純裝飾） |
| Timeline rows | Sheet 內容 mount | 每行 40ms stagger，最多 7 行（≤ 280ms），之後即時；reduced motion 冇 stagger | `t-stagger-line`（transitions.css:377） | 是 |
| Preview popover | eye 掣 | dropdown scale＋opacity，close 快過 open | 現有 Popover＋`t-dropdown`（transitions.css:156） | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Workspace snapshot 含 phase2.reviews / phase2.jobs | api | 有 | GET /api/workspaces/{id} — hosted_app.py:459-462 → hosted.py:504-507 → store.py:64-75；client.ts:136；hooks.ts:39-42 | S |
| 2 | p2_review / p2_approve / p2_cancel | api | 有 | store.py:284-286, 287-305, 316-321；permissions.py:28；client.ts:137-138 | S |
| 3 | p2_approve_many（1–10，共用 scheduleId，all-or-nothing） | api | 有 | store.py:306-315；tests/test_postriff_phase2.py:286-293；tests/test_postriff_providers.py:163-179；web 未用 | S |
| 4 | Worker 寫 nextAction / verification / providerConfirmed / providerReference | backend | 有 | hosted_worker.py:104-134（只喺 complete）；held 喺 claim :68 同 invalidate store.py:426 唔更新 nextAction；types.ts:76-81 | S |
| 5 | types.ts 補 Job.approvedBy/approvedAt/nextAt/checks/scheduleId/url?、events[].execution、Review.createdAt | frontend | 冇 | store.py:286, 302, 412；hosted_worker.py:37；types.ts:71-89 未 declare | S |
| 6 | 共用 job-state（groups、jobBadge、hold classes） | frontend | 有 | web/src/features/pipeline/job-state.ts:11-73；需要搬去 web/src/features/queue/job-state.ts 並令 queue-view 取代 :31-50, 74-88 | S |
| 7 | Held／Uncertain filter 同 held reason（最後 event message） | frontend | 冇 | queue-view.tsx:31-34, 74-88 冇 held／uncertain group | S |
| 8 | Honest loading（計數唔出 0）同 error state | frontend | 冇 | queue-view.tsx:267-276；全檔冇 isError | S |
| 9 | Header action gating 改為 approve-only＋edit-only reminder | frontend | 冇 | queue-view.tsx:209 edit 都顯示；permissions.py:28 p2_review 屬 approve | S |
| 10 | useSnapshot 接受 options（refetchInterval function form，只喺有 publishing／uncertain 或 2 分鐘內到期 waiting job 時 15s） | frontend | 冇 | hooks.ts:39-42 冇 options；vercel.json:57-62；query-client.ts:7 | S |
| 11 | URL state ?filter= 同 ?job=（nuqs） | frontend | 冇 | nuqs ^2.8.9 已裝，用於 calendar-view.tsx:6、use-data-table.ts:30；queue 用 useState（queue-view.tsx:179） | S |
| 12 | Job detail Sheet／Drawer | frontend | 冇 | primitives 已有：ui/sheet.tsx（右側預設 sm:max-w-sm :56）、ui/drawer.tsx、ui/collapsible.tsx、ui/alert.tsx；ManifestPreview（web/src/components/application/post-preview/manifest-preview.tsx） | M |
| 13 | 「Approved by you」判斷 | api | 有 | GET /api/me（hosted_app.py:358-359；hosted.py:570-585 userId）→ useMe hooks.ts:104-107；Member.you（hosted.py:711-715，types.ts:612-617）；冇 teammate displayName | S |
| 14 | Stale reviews 列表＋Prepare again | frontend | 冇 | store.py:416-420 標 stale（無原因）；ScheduleDialog 支援 variantId preselect（schedule-dialog.tsx:38, 52）；queue-view.tsx:185 filter 走咗 | S |
| 15 | Fixture／live execution badge | frontend | 冇 | manifest.execution（store.py:380）；types.ts:68 已 declare；queue-view 冇 render | S |
| 16 | ScheduleDialog DST fold 選擇 | frontend | 冇 | store.py:377 → contracts.py:42-58（:53-54 409）；schedule-dialog.tsx:89-102 唔送 fold；ui/radio-group.tsx 已有 | S |
| 17 | ScheduleDialog 語言顯示跟 variant／channel locale | frontend | 冇 | schedule-dialog.tsx:136, 144 硬寫「繁中／EN」 | S |
| 18 | Verified job permalink（Open post） | backend | 冇 | hosted_social.py:157 回 url；outcomes.py:27 丟咗；hosted_worker.py:104-111 冇寫 | S |
| 19 | Queue ↔ Analytics deep links | frontend | 冇 | analytics-view.tsx:138 已將 post 對 job；post-sheet.tsx:136, 154 link /app/queue 冇 ?job=；analytics 冇 URL state | M |
| 20 | Worker heartbeat（lastTickAt） | backend | 冇 | hosted_worker.py:154-160 tick 只回 dict；hosted_app.py:326-337 冇寫 state | S |
| 21 | Posting times per channel（Next free slot） | data | 冇 | grep 冇 postingTimes；manifest timing 必須 exact（contracts.py:42-58） | M |
| 22 | Approve／cancel 入 audit log | backend | 冇 | audit_event 只 memory／research（hosted.py:144-145, 157-159）；audit() helper hosted.py:93 同 GET /audit（hosted_app.py:465-466）已存在可接 | S |
| 23 | Tour infra 同 Queue anchors | frontend | 有 | web/src/features/onboarding/tours.ts:97-107（Queue step）；queue-view.tsx:216 data-tour='queue-approvals'、:261 'queue-list'；TourCtx（tours.ts:14-24）冇 canApprove | S |

## 3. Features

### P0

- **Honest loading and error states**：Loading 時計數顯示 0（queue-view.tsx:267-276），API 失敗顯示「Nothing to approve／No jobs here」— 直接違反「Unavailable 永遠唔變 0」。
- **Permission-honest actions**：「Schedule a draft」俾 editor 開，但 p2_review 要 approve（permissions.py:28），做到第三步先 403。改 approve-only＋edit-only reminder；viewer read-only；sample workspace disabled 並講原因。
- **Held and uncertain jobs visible with their real reason**：held（hosted_worker.py:68、store.py:426）同 uncertain 係要人留意嘅 state，而家只喺 All、灰色。重用 job-state.ts jobGroup／jobBadge，原因讀最後 event message；nextAction 可能過時，唔當 next step 顯示。（depends on：job-state.ts 搬去 features/queue）
- **Live refresh while something is moving**：Worker 每分鐘郁（vercel.json:57-62），頁面冇 refetchInterval（hooks.ts:39-42）。只喺有 publishing／uncertain 或 2 分鐘內到期 waiting job、且 tab visible 時 15s refetch。
- **Job detail sheet with the full receipt and a deep link**：plans.ts:45 承諾「publishing receipts」，但 queue 只顯示最後 event。Sheet 顯示 timeline、attempts、providerConfirmed、verification、approved by／at；`?job=` 令 Calendar／Live island／Home／Analytics post sheet 可以直接指向一個 job。（depends on：types.ts 補欄位；nuqs URL state）

### P1

- **Approve all (up to 10) with an exact confirmation**：p2_approve_many 已存在並有 test（store.py:306-315；tests/test_postriff_phase2.py:286-293），all-or-nothing。Buffer／Typefully 一次過入 queue 係常見便利（https://support.buffer.com/article/642-scheduling-posts；https://support.typefully.com/en/articles/9210135-scheduling-and-calendar），PostRiff 保持每行 exact digest。（depends on：Honest loading and error states）
- **Stale reviews surfaced with Prepare again**：review 一變 stale 就消失（store.py:420；queue-view.tsx:185），用戶以為 bug。列出＋一鍵 preselect 重開 dialog；唔估原因。
- **Execution honesty: Fixture badge and Open post link**：Capability honesty（redesign §1.1）：synthetic manifest（store.py:380）而家同 live 一樣。加「Fixture」；後端保留 reconcile url（outcomes.py:27）之後 verified row 先出「Open post」。（depends on：backend: outcomes.py 保留 url；hosted_worker.py 寫 job.url）
- **Mobile card layout for jobs**：375px 七欄 table 靠橫捲（queue-view.tsx:291），cancel 同 preview 要捲先見。
- **Schedule dialog polish: DST fold, thumbnails, languages, time-passed reminder**：DST 409 冇得揀（contracts.py:53-54）；image 只顯示 mime＋hash（schedule-dialog.tsx:192-206）；語言硬寫繁中／EN（:136, 144）同 worldwide languages 決定唔夾；過咗時間仍可 approve 冇提醒。全部 remind-not-block。

### P2

- **Queue ↔ Analytics deep links**：analytics-view.tsx:138 已經對到 job；post-sheet.tsx:154 去 queue 冇 ?job=；queue verified job 有 analytics post 先出「View performance」。（depends on：?job= URL state；analytics 加 ?post=）
- **Next free slot in the schedule dialog**：借 Buffer／Typefully slot 便利但保持 exact approval：client 算出下一個 slot 填入 datetime-local，manifest 仍 exact。冇設定 posting times 就唔出掣。（depends on：backend: per-channel posting times）
- **Worker heartbeat in the snapshot**：而家只可以顯示「Latest worker event on a job」；tick 寫 `phase2.worker.lastTickAt` 先可以誠實講「worker last ran」。
- **Approve and cancel in the audit log**：job.events 係唯一記錄；audit() 同 GET /audit 已存在（hosted.py:93；hosted_app.py:465-466），接入成本細。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明：「上半部係等我批嘅合約（text＋media＋account＋time 凍結咗），下半部係批咗之後 worker 嘅 receipt；冇批就冇嘢會出街。」教法：section heading 本身係句子；description 一句；第一張 review card 嘅 iPhone；info sidebar 解釋 exact approval、job states、cancel、held、uncertain。現有 welcome tour Queue step（tours.ts:97-107）保留，另加 Queue page tips。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="queue-schedule"]（要加喺 header「Schedule a draft」Button，queue-view.tsx:210；冇 approve 權限時 fallback 去現有 [data-tour="queue-approvals"]）` | Start here | Pick a draft, an account and an exact time. This prepares a review; nothing publishes yet. |
| 2 | `[data-tour="queue-approvals"]（已存在，queue-view.tsx:216）` | Approve exactly this | Each card freezes the text, media, account and time. Approving the card is the only way a post enters the queue. |
| 3 | `[data-tour="queue-review-phone"]（要加喺第一張 ReviewCard 嘅 ManifestPreview，queue-view.tsx:129；ctx.needsReview === 0 時 skip）` | What the app will show | The phone draws your post inside the destination app. The app has the final say on layout. |
| 4 | `main [aria-label="Filter jobs"]（已存在，queue-view.tsx:268），fallback [data-tour="queue-list"]（:261）` | Where every job is | Waiting, publishing, verified. Held means something changed and the job needs a new review; the counts come straight from the workspace. |
| 5 | `[data-tour="queue-job-row"]（要加喺第一行／card；ctx.jobCount === 0 時 skip）` | Open the receipt | Open a row for the full timeline: every worker event, every attempt and what the provider confirmed. |
| 6 | `[data-tour="queue-cancel"]（要加喺第一個 HoldActionButton，queue-view.tsx:361；冇 waiting job 或冇 approve 權限時 skip — TourCtx 要加 canApprove）` | Cancel before it goes | Hold to cancel a waiting job. Once the provider has accepted a post, PostRiff reconciles instead of retrying, so nothing is posted twice. |

**Empty state 教咩**：首次（冇 review、冇 job）一個 Empty 教三步：Schedule a draft → Approve the exact text, media and time → The worker publishes at that time and records what the provider confirmed。CTA 只俾 approve 權限；edit-only 顯示「An approver prepares and approves the exact schedule.」；冇 draft 加「Draft something in Ideas」；冇 Ready for posting channel 加 reminder link 去 Channels（唔 block）。文案對設計師、老師、店主、developer 讀落一樣，唔提任何品牌或行業。

## 5. Next steps（按次序）

1. **搬 `web/src/features/pipeline/job-state.ts` 去 `web/src/features/queue/job-state.ts`，Pipeline 同 Queue 都 import；queue-view 改用 jobGroup／jobBadge，filter 改 group（Ended 取代 Failed）；types.ts 補 Job（approvedBy、approvedAt、nextAt、checks、scheduleId、url?）、events[].execution、Review.createdAt**（effort S）  
   檔案：`web/src/features/pipeline/job-state.ts → web/src/features/queue/job-state.ts；web/src/features/pipeline/board.ts:15；web/src/lib/api/types.ts:71-89；web/src/features/queue/queue-view.tsx:31-50, 74-88`
2. **Honest loading（唔 render DigitSwap）＋ `snapshot.isError` Alert＋Retry；header action approve-only＋edit-only reminder；sample workspace disabled**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx:203-289`
3. **useSnapshot 接受 options（refetchInterval function form）；queue-view 傳入；抽 live-island `countdown()`＋TICK_MS 去 lib/time.ts**（effort S）  
   檔案：`web/src/lib/api/hooks.ts:39-42；web/src/features/queue/queue-view.tsx:174；web/src/components/layout/live-island.tsx:30, 131-139 → web/src/lib/time.ts`
4. **nuqs `?filter=`／`?job=`；新建 job-sheet.tsx（timeline、attempts、provider、approved by you、Prepare again、hold cancel）；Calendar、Live island、Analytics post sheet link 改傳 `?job=`（有 job id 時）**（effort M）  
   檔案：`web/src/features/queue/queue-view.tsx；web/src/features/queue/job-sheet.tsx（新）；web/src/features/calendar/calendar-view.tsx:122, 208；web/src/components/layout/live-island.tsx:428, 470；web/src/features/analytics/post-sheet.tsx:154`
5. **Held reason（最後 event message）、Fixture badge、「Latest worker event」一句、三步 Empty、data-tour anchors＋tours.ts Queue page tips（TourCtx 加 canApprove）**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx:216-289, 317-325；web/src/features/onboarding/tours.ts:14-24, 97-107`
6. **Approve all：heading 掣＋confirmation dialog（all-or-nothing 句子）→ `p2_approve_many`；success N 由 scheduleId 數**（effort S）  
   檔案：`web/src/features/queue/approve-many-dialog.tsx（新）；web/src/features/queue/queue-view.tsx:216-224`
7. **Stale reviews Collapsible＋Prepare again（approve gating，preselect variantId）**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx:185, 259；web/src/features/queue/schedule-dialog.tsx:38, 52`
8. **<md card layout：抽 `JobRow`（table row 同 card 兩個 render，actions 相同）**（effort M）  
   檔案：`web/src/features/queue/queue-view.tsx:291-388 → web/src/features/queue/job-row.tsx（新）`
9. **ScheduleDialog polish：409「occurs twice」→ RadioGroup fold；image thumbnails；語言顯示原值／channel locale；review card time-passed reminder；approvals stagger 改 40ms**（effort S）  
   檔案：`web/src/features/queue/schedule-dialog.tsx:69-110, 136, 144, 192-206；web/src/features/queue/queue-view.tsx:164-166, 247`
10. **Backend：normalize_result 保留 `url`（更新 allowed keys 同 test），worker 寫 `job['url']`；tick 寫 `phase2.worker.lastTickAt`；approve／cancel 入 audit**（effort S）  
   檔案：`src/postriff_phase2/outcomes.py:27；src/postriff_phase2/hosted_worker.py:104-111, 154-160；src/postriff_phase2/hosted.py:93, 156-160；tests/test_postriff_phase2_hosted.py`
11. **P2：analytics `?post=` deep link＋queue「View performance」；per-channel posting times＋「Next free slot」**（effort L）  
   檔案：`web/src/features/analytics/analytics-view.tsx；web/src/features/analytics/post-sheet.tsx；web/src/features/queue/schedule-dialog.tsx；src/postriff_phase2/channels.py`
12. **驗證：dev harness :3100 用 synthetic channel 走 review→approve→worker tick→verified，睇 refetch、badge 轉態、success check、Sheet timeline、375px card layout；唔好喺 live Threads 帳號批任何嘢**（effort S）  
   檔案：`scripts/postriff_dev_hosted.py；docs/postriff-motion-system.md:112`

## Risks

- 另一個 session 正在改 web/src；落地時 stage by path，避免掃走其他人嘅 WIP。
- Dev harness Threads 係 live provider（docs/postriff-motion-system.md:112）：測 approve／hold cancel 只可以用 synthetic channel。
- Polling 拎成個 workspace snapshot（store.py:64-75 仲會計 art brief）；15s interval 喺大 workspace 會重，需要時再加輕量 jobs endpoint（而家冇）。
- p2_approve_many all-or-nothing（store.py:306-315）：任何一個 DAILY_LIMITS 409 或 stale 都會成批失敗；dialog 要講明，toast 照出 server 訊息。
- reviews 只保留最近 20 個（store.py:286），stale 列表可能已被推走；N=0 唔 render，唔寫「all」。
- manifest.expiresAt = 時間+1 小時（store.py:380）：過咗時間一小時內仍可 approve 並即刻出街；reminder 要清楚但唔 block。waiting job 過咗 expiresAt 會被 invalidate 變 held（store.py:425）。
- nextAction 只喺 worker complete 更新（hosted_worker.py:124-134）；held 由 claim（:68）或 invalidate（store.py:426）產生時唔會改，所以唔可以當 held 嘅 next step；原因讀最後 event message。
- approvedBy 係 user id；/members 冇 displayName（hosted.py:711-715）；只可以「you／a teammate」。
- 前端 gating 讀真 membership（provider.tsx:145、lib/auth/permissions.ts）但仍係 UI-only；permissions.ts 要同 permissions.py CLASSES 保持同步。
- 改 outcomes.py 保留 url 要同時更新 test，否則 malformed adapter 檢查會誤判。
- Pipeline 同 Queue 各自一份 job-state 會 drift；搬遷要同一個 commit 改兩邊 import。
- 「Next free slot」只係 client 建議，manifest 仍 exact；唔可以令人以為 PostRiff 自動排期。

## 覆核記錄

- 改正：Route web/src/app/app/queue/page.tsx:1-9 renders QueueView → page.tsx:1-8
- 改正：useSnapshot hooks.ts:39-42 → GET /api/workspaces/{id}, route hosted_app.py:433-435 → hosted_app.py:459-462
- 改正：useAct hooks.ts:150-162 → POST actions hosted_app.py:452-460 → hosted.py:171-189 → store.py:182 apply_phase2 → hooks.ts:151-163；hosted_app.py:477-485 → hosted.py:156-160 → hosted.py:186-203 → store.py:182
- 改正：access.tsx:65-84 UI-only；permissions.py:28 approve class = owner 或 approver+can_publish (:18) → approve = owner 或 approver role，或者任何帶 can_publish 嘅非 viewer member
- 改正：access.tsx 係 STUB_ACCESS Phase A（risks） → 前端 gating 讀真 membership，但仍然 UI-only；API 執法
- 改正：Worker claim :37-89, re-auth :64-72, 3 attempt cap :73-75, 45s lease :76-77; complete :91-136 → 用正確行號；held 喺 :68 唔係 :71（:71 係 failed）
- 改正：Live island live-island.tsx:98-121 links to /app/queue → live-island.tsx:428, 470
- 改正：Tour infra 唔存在：grep web/src 冇 data-tour／tour hook → exists: true；新 page tips 加入 tours.ts registry，重用現有 anchors
- 改正：要新建 HELD set 同 stateStatus('held') → warning → 搬 job-state.ts 去 features/queue 並喺 queue-view import，唔好再抄一份
- 改正：held job 顯示 job.nextAction 作為 server 原話 next step → held 原因讀最後一個 held event 嘅 message；nextAction 只喺最後 event 由 hosted-worker 寫（execution==='hosted-worker'）時先顯示，label 做「Last worker note」
- 改正：GET /api/me userId types.ts:647-649; hosted_app.py:352-353 → 更正行號
- 改正：/members 唔提供 display name (hosted.py:647-651) → hosted.py:711-715；「Approved by you」可以用 useMe().userId 或 members[].you
- 改正：_present hosted.py:507-508 → hosted.py:504-507
- 改正：Approve all success 讀 response 新增 jobs 數 → N = response.state.phase2.jobs 入面 scheduleId 相同嘅 job 數（types 要補 scheduleId）
- 改正：Audit: hosted.py:138-145 只 memory/research；effects learning.capture hosted.py:300 → hosted.py:312；approve/cancel audit 可接現有 audit() + audit route
- 改正：Header「Schedule a draft」approve 或 edit 權限出現（:208-212）係 OK → 掣只俾 approve；edit-only 顯示一句 reminder「An approver prepares and approves the exact schedule」，唔好令人行到最後一步先失敗
- 違反原則（已改）：真數據先郁：held job 顯示 `job.nextAction` 做「server 原話 next step」— hosted held（hosted_worker.py:68、store.py:426）唔會更新 nextAction，會出過時句子。要改讀最後 held event message。
- 違反原則（已改）：真數據先郁：「Approve all → Scheduled N（N 來自 response 新增 jobs 數）」— response 冇呢個數；要由 scheduleId 數返 snapshot 入面嘅 job。
- 違反原則（已改）：真數據先郁：「Latest worker activity」其實只係 job events 最大 `at`，唔係 worker heartbeat；label 要講明係「Latest worker event on a job」，唔可以暗示 worker 仲喺度行。
- 違反原則（已改）：Remind, don't block（變相 block）：現有 header 俾 edit-only 用戶開 ScheduleDialog，但 p2_review 需要 approve，做到第三步先 403；spec 照保留，要改為 reminder。
- 違反原則（已改）：Motion：spec 要求 Sheet `max-w-lg` 但 t-panel 開合時間（400/350ms）未喺 transitions.css 核實，要讀 token 而唔係寫死數字；Approve all dialog 開 250ms／關 150ms 同理用 token 名。
- 違反原則（已改）：Reuse before inventing：spec 提議新 HELD set／stateStatus，但 web/src/features/pipeline/job-state.ts 已有完整 jobGroup／jobBadge 同 hold-cancel classes。
- 違反原則（已改）：Tour：spec 聲稱冇 tour infra 並另立 data-tour 名，忽略 tours.ts 已有 Queue step 同 queue-approvals／queue-list anchors。
- 補上遺漏：RBAC：Queue nav item 冇 access key（nav-config.ts:69-75），viewer 都入到；spec 要寫明 viewer read-only（冇 Approve、冇 hold cancel、冇 Schedule），editor 只見 reminder，approver 冇 edit 但可以 Prepare again（p2_review 屬 approve）。「Prepare again」要以 approve gating。
- 補上遺漏：Uncertain state：job-state.ts 已將 uncertain 分組（reconciling，唔可以 cancel），spec filter 冇 Uncertain／manual review（checks≥5 → 'Manual provider review required'，hosted_worker.py:124-126）。
- 補上遺漏：Revision conflict：多人同時 approve 會 409 revision；toast Reload 之外，approve 應自動 refetch 再提示，而唔係叫人手 reload。
- 補上遺漏：Languages／i18n：UI copy 全英文、冇 i18n lib；schedule-dialog.tsx:136,144 將語言硬寫成「繁中／EN」二分，違反 worldwide languages Stage 1 per-channel locale 決定；Queue card 顯示 `manifest.payload.language` 原值即可，dialog 要讀 channel locale。
- 補上遺漏：Timezone：manifest timing.local 用 approver 瀏覽器 zone；Sheet 同 table 應同時顯示 manifest zone 同 viewer 本地時間（formatDateTime），避免團隊跨時區誤讀。
- 補上遺漏：共用 job-state 搬遷：Pipeline 同 Queue 兩份 set 會 drift（job-state.ts:4-6 自己寫咗 follow-up）。
- 補上遺漏：Analytics 反向 deep link：post-sheet.tsx:154 link 去 /app/queue 但冇 ?job=。
- 補上遺漏：Sample workspace read-only（hosted.py:195-196 403）：Approve／cancel 要 disable 並解釋。
- 補上遺漏：Trial expired：approve 會 409 stale（store.py:292），held reason 亦包括 entitlement；Queue 應 link 去 billing 作 reminder。
- 補上遺漏：Polling 只喺 document visible 時行（refetchIntervalInBackground false），手機背景唔好 poll。
