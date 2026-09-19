# 20 · Usage & plan

> Route：`/app/account/billing` · Sidebar：Account · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

而家有一個單一 client component `web/src/features/billing/billing-view.tsx:88-325`，由 `web/src/app/app/account/billing/page.tsx:7-13` 用 Suspense 包住。資料鏈：`useUsage()`（`web/src/lib/api/hooks.ts:44-47`）→ `api.usage()`（`web/src/lib/api/client.ts:156`）→ `GET /api/workspaces/{id}/usage`（`src/postriff_phase2/hosted_app.py:389-390`，同一 handler 都答 `/subscription`）→ `HostedWorkspaceService.usage()`（`src/postriff_phase2/hosted.py:316-322`）= `Ledger.usage_view()`（`src/postriff_phase2/billing.py:114-131`）+ `Billing.lifecycle()`（`billing.py:234-246`）+ `Billing.availability()`（`billing.py:220-228`）+ membership summary。注意 GET 有寫入：lifecycle 會 UPDATE status（`billing.py:245`），budget 會 upsert 加 FOR UPDATE（`billing.py:33-37`）。Trial workspace 首次讀取時已經 INSERT 一條 `pr_subscriptions` status='trial'（`billing.py:55`，provider default 'fixture'，`007_consumer_web_billing.sql:30`）→ `subscription` 唔係 null，label 係「14-day trial」，`live=false`。Types 喺 `web/src/lib/api/types.ts:489-556`。Checkout／portal：`api.checkout`／`api.portal`（`client.ts:157-164`）→ `POST /api/workspaces/{id}/billing/checkout|portal`（`hosted_app.py:383-388`）→ `billing_checkout()`（`hosted.py:360-385`：未 mount Stripe 就 503、owner-only、5 次/分鐘 throttle、plan 要 `status='active'` 同有 `provider_price_id` 否則 409、已經有 active/past_due/grace 就 409（cancelled/expired 可以再買）、email 搵唔到就 502；webhook 未到之前乜都唔寫）同 `billing_portal()`（`hosted.py:387-398`，冇 `provider_customer_id` 就 409）。Audit：`hosted.py:380`（checkout_started）、`:398`（portal_opened）。Webhook：`POST /api/billing/webhook`（`hosted_app.py:289-296`）→ `Billing.process_webhook()`（`billing.py:177-218`）。Stripe mapping 喺 `billing_stripe.py:25-38`。任何 status=active 兼帶 planTermsId 嘅 applied event（checkout.session.completed、customer.subscription.created/updated、invoice.paid）都會觸發 `_reconcile_entitlement()`（`billing.py:210-211, 231-232`），所以 allowance 唔單止每月重設，portal 改設定都可能期中補滿；trial 永遠唔會 reset。`grace` 狀態喺 Stripe mapping 入面從來唔會出現。Provider 由 `hosted_app.py:113-120` 揀：未有 `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` 就係 `DisabledPaymentProvider`，checkoutAvailable／portalAvailable 都係 false。Plan rows 全部係 `proposed`（`007:21-25`，包括 `assist-bounded-v1`）；`studio-v1` 嘅 writingBatches 同 mediaCredits 都係 0（`007:23`）；`provider_price_id` 由 `008:7` 加。Overview 都讀同一份 usage（`web/src/features/overview/overview-view.tsx:146, 167-170, 183, 215-219`）。Nav／sidebar gate 做 owner（`web/src/config/nav-config.ts:155-161`、`web/src/components/layout/app-sidebar.tsx:221-226`）；access context 喺 `web/src/lib/auth/access.tsx`（STUB_ACCESS 預設 owner，`:37-43`）。Onboarding：tour runner 已經存在（`web/src/features/onboarding/tours.ts` PAGE_TOURS／TourCtx、`tour-mount.tsx` 由 `web/src/app/app/template.tsx` mount），但未有 billing entry，billing-view 亦冇任何 `data-tour`。

已知缺口：(1) `billing-view.tsx:106` `?? 0`：channels loading／error 時顯示 0/N。(2) `:77-81` badge 讀 raw `subscription.status`，唔係 `lifecycle.status`；usage_view 先讀、lifecycle 後 UPDATE，同一個 response 兩個值可以唔同。(3) `:218` trial 都寫「Resets」（trial resetsAt = `pr_trials.expires_at`，`billing.py:51-54`）。(4) `:207, 212` fallback 去 `TRIAL` 常數（`web/src/config/plans.ts:70-78`）。(5) `:105` 冇剔走 `assist-bounded-v1`。(6) `:241` 顯示寫死嘅 note（`billing.py:130`）。(7) `:96-100` toast 講「updates as soon as…」但冇 refetch。(8) `:142-143` isError 時永遠停喺 skeleton。(9) `:229` 顯示 raw「candidate」。(10) `:300-313` 顯示內部字眼、100 條只顯示 20 條；rows 冇 reservationId／runId／chargeBatch（`billing.py:118-119`）。(11) `:47,67` amber 條件用 value/max，但 batches／credits 嘅 value 係 remaining，accounts 係 used：警示色倒轉。(12) max=0（studio writingBatches）畫出「0 / 0」空 bar。(13) `:216` storage 只寫「included」：backend 冇量度 storage used（`storageMb` 喺 billing.py 以外冇引用）。(14) `:217` members 冇用真數（`useMembers`，`hosted.py:711-715`）。(15) 冇 invoice endpoint。(16) Backend `usage()` 冇 require，非 owner 都讀得到 budget 同 ledger 成本，只係 UI 封咗。(17) `lifecycle.canPublish`（`billing.py:246`）trial 過期都係 true；connected accounts 上限冇 enforce。(18) 402（`billing.py:71,73,78`）喺 run transaction 入面 raise（`ideas.py:390`），前端只係 toast（`ideas-view.tsx:143`、`home-view.tsx:193`、`conversation-view.tsx:204`）。Motion：`Meter`（`:45-75`）用 motion.div transform 同 NumberTicker，有 useReducedMotion。Tests：`tests/test_postriff_billing.py:108-138`、`tests/phase2/postgres_billing.py`、`tests/phase2/postgres_billing_stripe.py`。

## 1. Design specification（最新版）

**目的**：一頁答三個問題：呢個 workspace 而家係咩 plan、今期仲剩幾多（writing batches／media credits／connected accounts／members；storage 未量度就講明未量度）、幾時會變（trial 幾時完、幾時續期、付款失敗幾時到期）。Owner 有兩個真出口：Stripe Checkout 同 Stripe Portal。每個數字都讀 `GET /usage` 或 `/members`／`/channels`；讀唔到就寫「Unavailable」，冇量度嘅就寫「not measured」。

**Layout**：用 `PageContainer`（`web/src/components/layout/page-container.tsx`）：pageTitle「Usage & plan」、pageDescription「What you have, what you have used, and what changes next.」、infoContent 保留三段再加「What counts as a writing batch」。唔用 `pageHeaderAction`（header 唔 wrap，而且 CTA 唔應該出兩次），Manage billing 只放 Current plan card footer。主體 `flex flex-col gap-6`：Row 0 lifecycle Alert；Row 1 `grid gap-4 lg:grid-cols-3`（左 Current plan，右 lg:col-span-2 Allowances，owner 先見 cost guard）；Row 2 Plans `grid gap-4 md:grid-cols-2`；Row 3 Recent usage。Responsive：375px 單欄；meter 全闊；plan cards 疊；ledger 唔用七欄橫 scroll，改用 stacked rows（When + What 一行，Estimated → Actual + State badge 第二行）。768px plans 2 欄，ledger 轉 table 包喺 `overflow-x-auto rounded-lg border`，第一欄用 `getCommonPinningStyles`（`web/src/lib/data-table`）pin 住。1440px（infobar 開住）Row 1 1/3 + 2/3，ledger 全部欄唔使 scroll。Gutter 跟 PageContainer `px-4 md:px-6`。文案暫時 English-only，全部集中放 `billing-copy.ts`，方便日後按 UI locale 翻譯；日期用 `lib/time.ts` formatDate（跟 timeDefaults locale），價錢用 `cents(priceCents, currency)`。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Row 0 · Lifecycle alert | lifecycle 有事，第一眼就見到，而且只講 API 證實到嘅嘢。 | 讀 `usage.lifecycle.status`。`past_due`：destructive Alert「Payment failed」+「Publishing continues until {formatDate(subscription.graceUntil)}」（null → 「grace period end unavailable」）+ owner 且 portalAvailable 就加 Manage billing。`cancelled`／`expired`：neutral Alert「Subscription ended」（有 currentPeriodEnd 先寫日期）+「Drafts stay readable and exportable」+ owner 見「Choose a plan」錨去 Plans（backend 容許 cancelled 再 checkout）。`trial` 且 `daysUntil(entitlement.resetsAt) <= 0`：info Alert「Trial ended on {date}. Whatever is left of the trial allowance still works; choose a plan for a monthly allowance.」，唔可以寫「publishing paused」（`billing.py:246`）。`active` 且 `cancelAtPeriodEnd`：info「Ends {date}. Resume from the billing portal.」。文案要同 overview-view.tsx:215-219 嘅 trial 提示一致。 | 冇事就唔 render；冇 lifecycle 就唔 render。`grace` 分支保留，但註明 Stripe mapping 暫時唔會產生。 |
| Row 1 左 · Current plan card | 五秒內知道自己係邊個 plan、幾錢、下一個日期。 | CardDescription「Current plan」；CardTitle = `subscription.label`（null 係防禦分支，寫「Plan unavailable」）+ `AnimatedBadge`（`contentKey=lifecycle.status`；trial→info、active→success、past_due→danger、grace→warning、cancelled/expired→neutral）。價錢行：`lifecycle.status==='trial'` →「$0 · no card on file · nothing converts automatically」；其他 → `cents(priceCents, currency)` / month，`priceStatus !== 'active'` 加「· introductory」。日期行：trial →「{n} days left · ends {formatDate(resetsAt)}」（≤0 →「Trial ended {date}」；resetsAt null →「End date unavailable」）；其他 → `cancelAtPeriodEnd ? 'Ends' : 'Renews'` + formatDate(currentPeriodEnd)，null →「Renewal date unavailable」。保障行：「Export: {exportAvailable === false ? 'unavailable' : 'available'}」·「Publishing: {canPublish === undefined ? 'unavailable' : canPublish ? 'on' : 'paused'}」。Footer：owner 且 portalAvailable → `StatefulButton`「Manage billing」（`data-tour="billing-manage"`；loading 係真請求；error 顯示 `ApiError.message`）；owner 但 !portalAvailable →「Payment method, invoices and cancellation appear here after your first subscription.」；非 owner →「Plan changes are made by the workspace owner.」。Card 加 `data-tour="billing-plan"`。 | 首次載入交俾 PageContainer isLoading；usage error 就用整頁 error_state。 |
| Row 1 右 · This period · Allowances | 今期仲剩幾多，同埋用完會點（停低兼提醒，唔會收錢）。 | `Meter` 改成明確兩種 mode。remaining mode：① AI writing batches：value `entitlement.writingBatchesRemaining`，total = `planTerms.find(t => t.id === entitlement.planTermsId)?.entitlements.writingBatches`；total 唔係數字 →「{remaining} left · plan total unavailable」，唔畫 bar，唔用 TRIAL；total === 0 →「Not included in this plan」，唔畫 bar；remaining/total ≤ 10% 先 amber。② Media credits 同樣處理。used mode：③ Connected accounts：value = channels 入面計入 allowance 嘅 account 數（計數規則同 channels 頁一致，要明文寫低，唔可以寫成混合「Connected ✓」），total `entitlement.connectedAccounts`；`channels.isPending` → bar 位用 `Skeleton`，唔出數字；`channels.isError` →「Unavailable」，唔畫 bar；used ≥ 90% 先 amber；超額只提醒「{n} of {max}. Connecting more is not blocked.」。④ Members：`useMembers()`，只計 status 屬 active 嘅 membership，對 `entitlement.members`；status 語義未確認就「Unavailable」。⑤ Storage：「{storageMb} MB included · usage is not measured yet」，要等 backend `storageUsedBytes` 出咗先變 meter。每條 meter 下面：trial →「No reset during the trial · ends {date}」；live →「Resets {formatDate(resetsAt)}」；resetsAt null →「Reset date unavailable」。Card footer 常設提醒：「When an allowance runs out, paid drafting stops and tells you. Nothing is charged silently.」。Cost guard panel（owner-only，而且 backend 要對非 owner 剔走 budget）：「Model spend this {budget.windowKind}」`usd(spentUsdMicro)` of `usd(stopUsdMicro)` · reserved `usd(reservedUsdMicro)`；status map：candidate →「provisional ceiling」、approved →「approved ceiling」；「Requests are refused before the ceiling would be crossed, never charged after.」。Allowances card 加 `data-tour="billing-allowances"`，panel 加 `data-tour="billing-cost-guard"`。 | 每條 meter 獨立：usage 有但 channels 出錯，就只有③寫 Unavailable；refetch 失敗而手上有舊數據時，card header 加「Last updated {relativeTime}」同 Retry，唔好靜靜雞顯示舊數。 |
| Row 2 · Plans | 揀 plan，或者知道點解仲揀唔到；一個 plan 一張卡。 | 由 `usage.planTerms` 派生：剔走 `plan==='trial'` 同 `status==='retired'`；每個 plan 只留一 row（有 active 就揀 version 最高嘅 active，冇就揀 version 最高嘅）。Card：CardDescription 顯示 plan 名 + `Current` Badge（`terms.id === entitlement.planTermsId`）+ status 唔係 active 時加「Introductory pricing」；CardTitle = label + `cents(priceCents, currency)` / month；body 列出 entitlements 嘅真值（writing batches、connected accounts、media credits、storage、members），值係 0 寫「Not included」，冇 key 寫「—」。設 `hasOpenSubscription = ['active','past_due','grace'].includes(lifecycle.status)`。Footer：(a) owner 且 checkoutAvailable 且 status==='active' 且唔係 current 且 !hasOpenSubscription → `StatefulButton`「Choose {label}」，成功就 `location.assign(url)`；(b) hasOpenSubscription 且唔係 current →「Switch plans from the billing portal」；(c) !checkoutAvailable 或者 status 唔係 active →「Not yet available for purchase」；(d) 非 owner →「Ask the workspace owner to change the plan」。Section 副標唔用 API `note`，由 `billing.provider` 派生：disabled →「Checkout is not enabled on this deployment yet.」；stripe →「Checkout and invoices are handled by Stripe. Nothing is charged until you confirm there.」；其他值 → 唔顯示副標。加 `data-tour="billing-plans"`。 | `?checkout=success` 且 !hasOpenSubscription：section 頂出 `AnimatedBadge status='loading'`「Confirming with Stripe…」，useUsage 開 refetchInterval（2s、4s、8s 逐步 backoff，上限 10s，總共最多 2 分鐘），因為每次 GET 都係寫入 transaction；lifecycle.status 變 active → success「Subscription confirmed」+ `SuccessCheck`，之後 `router.replace` 清走 query；逾時 → warning「Still waiting for Stripe. Refresh in a minute; nothing else is needed from you.」。`?checkout=cancelled` → toast.info 一次。planTerms 係空陣列 →「No plans are published on this deployment yet.」。 |
| Row 3 · Recent usage (ledger) | 每個 run 由估價到實價嘅真紀錄，對得返 allowance 點樣減。 | `DataTable`（`web/src/components/ui/table/data-table.tsx`）：When（formatDateTime）；What（dimension map：text_model→Writing、image_generation→Media、tool→Tool、storage→Storage、action→Action；model 放副行）；Step（reserve→Reserved、settle→Settled、release→Released (failed run)、adjust→Adjusted）；Estimated（usd）；Actual（null →「—」；costState==='estimated_unknown' 就加 Tooltip「waiting for provider reconciliation」）；State（AnimatedBadge：actual→success、estimated→info、estimated_unknown→warning、released→neutral）；Batch（要 backend 加 chargeBatch：true →「uses a batch」，false 而 estimate 係 0 →「$0 run」）。Toolbar：motion `Tabs variant='segment'` All／Writing／Media／Other，計數用 `DigitSwap`；「Show all {ledger.length}」（預設 20 行）；「Export CSV」用 `downloadBlob`（`web/src/lib/download.ts`）。加 `data-tour="billing-ledger"`。 | empty → Empty（見 empty_state）；首次 loading 跟頁面；底部寫「Showing the latest {ledger.length} entries (up to 100)」。 |
| Info sidebar | 解釋規則，唔重覆數字。 | 保留 `billing-view.tsx:26-43` 三段，但「Trial」段唔好再由 TRIAL 常數砌數字（常數可能同 plan_terms 唔一致），改寫成冇數字嘅規則描述；「Cancelling」段嘅「Publishing pauses at the end of the paid period」要同 lifecycle（`billing.py:241-246`）一致。新加第四段「What counts as a writing batch」：「A batch is one paid drafting run. Runs that use no paid model show at $0 and do not use a batch. Each run reserves an estimate first, then settles to the real cost, or is released if it failed.」；link 去 `/docs#usage-and-billing`（`web/src/content/docs.ts:48-56`）。 |  |

- **Empty state**：Ledger 空：`Empty` + `EmptyMedia`（Icons.creditCard），EmptyTitle「No usage yet」，EmptyDescription「Every drafting run appears here: runs with no paid model at $0, paid runs as a reservation that then settles to the real cost.」；有 `edit` permission 先顯示 EmptyContent「Start an idea」→ `/app/ideas?new=1`。Allowances 唔會空（`ensure_entitlement` 首次讀取就建 row）。Plans 空 →「No plans are published on this deployment yet.」，唔隱藏 section。
- **Loading**：首次 `usage.isPending`：`PageContainer isLoading` 出 `PageSkeleton`（`page-container.tsx:22-38`，Tailwind animate-pulse）；唔出數字，唔出「Loading your plan…」之類文案。Refetch（polling／focus）保留舊數據，pending 只喺 Confirming badge 顯示。channels／members 各自 pending 時，對應 meter 用 Skeleton 行，唔出數字、唔畫 bar；互相唔影響。
- **Error**：`usage.isError` 而冇數據：destructive Alert「Usage could not be loaded」+ ApiError.message（401 →「Sign in again」；403 →「You no longer have access to this workspace」）+ StatefulButton「Retry」→ `usage.refetch()`；meters、plans、ledger 全部唔 render。有舊數據但 refetch 失敗：保留舊數據，加「Last updated …」同 Retry。Checkout／portal 失敗：StatefulButton 轉 error，顯示 backend 原文（409 already has a subscription／not yet available／No billing account yet、429 throttle、502 email could not be resolved、503 Billing is not configured／public base URL），唔跳頁。Polling 逾時：warning badge，唔好轉 success。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Page 進場 | route mount | `.t-page-enter` fade + rise（--page-fade-dur／--page-slide-dur 250ms） | web/src/app/app/template.tsx + web/src/styles/transitions.css:252-266 | 否（純裝飾） |
| Allowance meter fill | usage／channels／members 數據到 | 現有 Meter：motion.div translateX 去到 pct-100%，只郁 transform，EASE_OUT；有 bar 嘅 meter 用 40ms stagger（最多 4 條，stagger 總共 ≤ 120ms）；useReducedMotion → duration 0；Unavailable／Not included／pending 就唔 render bar；amber 按 mode 判斷 | billing-view.tsx:45-75 Meter + web/src/lib/ease.ts EASE_OUT | 是 |
| Remaining／used 數字 | 數據到或者 refetch 後數值改變 | NumberTicker 逐位滾動（locale）；reduced motion 直接顯示 | web/src/components/motion/number-ticker.tsx | 是 |
| Plan status badge | lifecycle.status 改變（polling 期間 trial→active；past_due→cancelled） | AnimatedBadge 文字同 icon roll，contentKey=lifecycle.status；reduced motion 只 fade | web/src/components/motion/animated-badge.tsx | 是 |
| Confirming with Stripe badge | ?checkout=success 且 !hasOpenSubscription，真 polling 進行中 | AnimatedBadge status='loading'（pulse 只喺真 polling 期間出現）；lifecycle.status 變 active → success + SuccessCheck；逾時 → warning | animated-badge.tsx + web/src/components/ui/success-check.tsx | 是 |
| Choose plan／Manage billing／Retry 按鈕 | click → 請求進行中 → 成功就 navigate，失敗就出錯 | StatefulButton idle→loading→error（errorText = ApiError.message）；成功直接 location.assign，唔播 success | web/src/components/motion/button/stateful.tsx | 是 |
| Ledger filter tabs 計數 | 切 tab 或者 refetch 令計數改變 | motion Tabs segment pill 滑動 + DigitSwap；計數 = ledger.filter(...).length | web/src/components/motion/tabs.tsx + web/src/components/motion/digit-swap.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{id}/usage 回傳 entitlement／subscription／budget／ledger／planTerms／lifecycle／billing／membership | api | 有 | hosted_app.py:389-390 → hosted.py:316-322 → billing.py:114-131, 220-228, 234-246 | S |
| 2 | usage 按角色剔走敏感欄位：非 owner 唔返 budget 同 ledger 成本／model（或者另外開 member view） | backend | 冇 | hosted.py:316-322 冇 require，任何 member 都攞到完整 budget + ledger | S |
| 3 | POST /billing/checkout（owner-only、active terms + provider_price_id、5/min throttle、cancelled 可以再買） | api | 有 | hosted_app.py:383-386；hosted.py:360-385；tests/test_postriff_billing.py:108-120 | S |
| 4 | POST /billing/portal（owner-only，要有 provider_customer_id） | api | 有 | hosted_app.py:387-388；hosted.py:387-398 | S |
| 5 | Stripe webhook → subscription state → entitlement reconcile | backend | 有 | hosted_app.py:289-296；billing.py:177-218, 231-232；billing_stripe.py:25-38（任何 active + planTermsId event 都會 reconcile，唔止 invoice.paid） | S |
| 6 | Reconcile 只喺新 billing period（current_period_end 改變）或者換 plan 時先補滿 allowance | backend | 冇 | billing.py:210-211 冇 period 檢查；portal 嘅 subscription.updated 會期中補滿 | S |
| 7 | Stripe provider mount（兩個 env 齊先 live） | infra | 有 | hosted_app.py:113-120；billing_stripe.py；docs/postriff-consumer-web/billing-and-email.md:20 Founder-only setup | S |
| 8 | Plan terms 轉 active + provider_price_id（founder SQL，D3） | data | 冇 | 007_consumer_web_billing.sql:21-25 全部 proposed；008:7 有欄位但未有值 | S |
| 9 | useUsage／useChannels／useMembers hooks + api.checkout／api.portal + Usage types | frontend | 有 | web/src/lib/api/hooks.ts:44-67；client.ts:156-164；types.ts:489-556 | S |
| 10 | useUsage 接受 options（refetchInterval） | frontend | 冇 | hooks.ts:44-47 冇參數 | S |
| 11 | usage_view ledger rows 加 reservationId／runId／chargeBatch | backend | 冇 | billing.py:118-119 SELECT 冇呢三個欄位；types.ts LedgerEntry 都冇 | S |
| 12 | usage_view 嘅 note 唔再寫死（刪走或者按 provider 派生） | backend | 冇 | billing.py:130；billing-view.tsx:241 | S |
| 13 | Error state + retry；每條 meter 獨立 Unavailable；Meter 雙 mode 同 amber 修正；total 0 顯示 Not included | frontend | 冇 | billing-view.tsx:142-143、:106、:47/:67、:207/:212 | S |
| 14 | Storage used：backend 計 workspace storage bytes（`storageUsedBytes` 加入 usage view） | backend | 冇 | storageMb 喺 billing.py 以外冇引用；snapshot assets.bytes（types.ts:48、media.py:92）只包 phase2 media，唔係全部儲存 | M |
| 15 | Members count：GET /members（按 status 篩 active） | api | 有 | hosted.py:711-715；hooks.ts:64 | S |
| 16 | 非 owner 開放頁面（nav／sidebar／view），配合 backend 剔走欄位 | frontend | 冇 | nav-config.ts:155-161、app-sidebar.tsx:221-226、billing-view.tsx:103,136-139 一律 owner | S |
| 17 | Drafting 402 提醒兼出口（See plan），而且保留使用者輸入 | frontend | 冇 | billing.py:71,73,78 拋 402；ideas.py:390；ideas-view.tsx:143、home-view.tsx:193、conversation-view.tsx:204 只 toast.error | S |
| 18 | Invoice 列表 endpoint（Stripe invoices proxy） | api | 冇 | hosted.py／billing_stripe.py 冇 list；docs.ts:54 已講 invoices 喺 portal | M |
| 19 | Tour runner + page tips registry | frontend | 有 | web/src/features/onboarding/tours.ts（PAGE_TOURS、pageTourFor、TourCtx、when）、tour-mount.tsx（template.tsx mount） | S |
| 20 | billing-tips PAGE_TOURS entry + TourCtx 加 isOwner／portalAvailable + billing-view data-tour attributes | frontend | 冇 | tours.ts 冇 billing；TourCtx 只有 canEdit／canManageConnections／canReply；billing-view.tsx 冇 data-tour | S |
| 21 | Motion 元件：NumberTicker、AnimatedBadge、StatefulButton、SuccessCheck、Tabs(segment)、DigitSwap、t-page-enter | frontend | 有 | web/src/components/motion/{number-ticker,animated-badge,tabs,digit-swap}.tsx、motion/button/stateful.tsx、ui/success-check.tsx、styles/transitions.css:252-266 | S |
| 22 | DataTable + getCommonPinningStyles + downloadBlob + Empty | frontend | 有 | ui/table/data-table.tsx:21；lib/data-table（posts-table.tsx:21 用緊）；lib/download.ts:1-11；ui/empty.tsx:94 | S |
| 23 | Webhook applied events 寫入 audit | backend | 冇 | hosted.py:380, 398 只 audit checkout／portal；hosted.py:324-333 applied 只寫 pr_notifications | S |

## 3. Features

### P0

- **誠實狀態模型：badge 讀 lifecycle.status；trial 寫 ends；缺數據寫 Unavailable；total 0 寫 Not included；amber 按 meter mode 判斷**：規則 1。billing-view.tsx:106 顯示 0/N、:218 trial 都寫 Resets、:207/:212 用 TRIAL 常數、:77-81 讀 raw status、:47/:67 amber 倒轉、studio writingBatches=0 畫空 bar。
- **Checkout 返嚟真確認：backoff polling 直到 lifecycle.status=active，badge loading→success，逾時轉 warning**：billing-view.tsx:98 講咗會更新但冇 refetch；GET /usage 係寫入 transaction，所以要 backoff。（depends on：useUsage 接受 options）
- **Plans：每個 plan 一張卡；footer 用 hasOpenSubscription 對齊 backend 409；副標由 provider 派生**：assist-bounded-v1 而家所有人都見到（:105）；note 喺 Stripe 上線後變假話（billing.py:130）；subscription.live 會錯誤擋住已取消嘅用戶再 checkout（hosted.py:376-378）。（depends on：billing.py:130 note 刪走或者派生）
- **Error state + retry；loading 交俾 PageContainer；stale 數據標示**：:142-143 出錯都永遠係 skeleton。

### P1

- **Members meter 用真數；Storage 講明未量度，等 backend storageUsedBytes**：Members 已經有真數（hosted.py:711-715）；storage 冇 backend 量度，前端加總係部分數字。（depends on：Storage：backend storageUsedBytes）
- **非 owner 讀到 allowances（冇 cost guard、冇 checkout／portal）**：規則 2：editor 撞到 402 要知道點解；但要 backend 同步剔走 budget／ledger 成本，唔可以淨係靠 UI 收起。（depends on：usage 按角色剔走欄位；nav-config.ts:155-161 + app-sidebar.tsx:221-226）
- **Ledger v2：人話標籤、$0 run 同 batch 標示、filter tabs 真計數、Show all、CSV、mobile stacked rows**：要對得返「點解少咗一個 batch」；$0 run 本身就喺 ledger 入面（ideas.py:390）。（depends on：usage_view rows 加 reservationId／runId／chargeBatch）
- **402 提醒：toast 加「See plan」action，保留使用者輸入，唔好清走 composer**：規則 2：提醒兼出口，唔係 dead end；backend message 已經講明 drafts／exports／reviews 仲用得。
- **Billing tips tour（喺現有 tours.ts 註冊）**：Runner 已經存在；只需要加 entry 同 anchors，文案要 general 兼讀真 ctx。（depends on：TourCtx 加 isOwner／portalAvailable）
- **Reconcile 只喺新 period／換 plan 時補滿**：billing.py:210-211 portal 嘅 subscription.updated 會期中補滿 allowance，令 meter 數字同真實 period 對唔上。（depends on：founder 確認係 bug 定產品決定）

### P2

- **頁內 Invoices 列表**：Stripe Portal 已經有 invoice history，docs.ts:54 亦已經咁承諾；頁內列表係錦上添花。（depends on：GET /billing/invoices（owner-only））
- **Billing activity（audit checkout／portal + webhook applied）**：俾 owner 對返「幾時撳過 checkout、Stripe 幾時確認」。（depends on：process_webhook applied 時寫 audit）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明白三樣嘢：(1) 呢個 workspace 係邊個 plan 同狀態（Current plan card 大字 label + AnimatedBadge）；(2) 今期仲剩幾多 writing batches（Allowances 第一條 meter，NumberTicker 大數 +「left of N」或者「Not included in this plan」）；(3) 下一個會改變嘅日期（trial ends／renews／ends）。Card footer 常設提醒「When an allowance runs out, paid drafting stops and tells you. Nothing is charged silently.」，設計師、老師、店主、developer 讀落都一樣。未有 Stripe 時 Plans 副標直接講「Checkout is not enabled on this deployment yet」。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="billing-plan"]（新增；fallback heading('billing')）` | Your plan | This is the plan for the workspace you have open, with its status and the next date that changes something. |
| 2 | `[data-tour="billing-allowances"]（新增）` | What is left this period | Each bar reads your real allowance. When one runs out, paid drafting stops and tells you. Nothing is charged silently. |
| 3 | `[data-tour="billing-cost-guard"]（新增；when: ctx.isOwner）` | Cost ceiling | Every paid run reserves an estimate first. If the ceiling would be crossed, the request is refused before any model call. |
| 4 | `[data-tour="billing-plans"]（新增）` | Choosing a plan | Checkout happens with the payment provider. This page shows a subscription as confirmed only after the provider tells us. |
| 5 | `[data-tour="billing-ledger"]（新增；fallback billing-ledger-empty）` | Recent usage | Each run reserves an estimate, then settles to the real cost or is released if it failed. Runs with no paid model show at $0. |
| 6 | `[data-tour="billing-manage"]（新增；when: ctx.isOwner && ctx.portalAvailable）` | Manage billing | Payment method, invoices, plan changes and cancellation live in the billing portal. |

**Empty state 教咩**：Ledger 空時教：每個 drafting run 都會喺度出現，冇用 paid model 嘅係 $0，paid run 先 reserve 再 settle；出口係「Start an idea」（有 edit 先顯示）。Plans 空時講事實：「No plans are published on this deployment yet」。Trial 用戶由 meter 下面「No reset during the trial · ends {date}」學到 trial allowance 只有一次。

## 5. Next steps（按次序）

1. **Backend：usage_view ledger rows 加 reservationId／runId／chargeBatch；刪走寫死嘅 note；非 owner 剔走 budget 同 ledger 成本；補 tests**（effort S）  
   檔案：`src/postriff_phase2/billing.py:114-131；src/postriff_phase2/hosted.py:316-322；tests/phase2/postgres_billing.py；tests/test_postriff_billing.py；web/src/lib/api/types.ts（LedgerEntry、Usage.budget optional）`
2. **抽出 pure model `billing-model.ts`：lifecycleTone、latestTermsPerPlan、hasOpenSubscription、allowanceTotal（回傳 number | null）、meterState（remaining／used mode、Not included、amber）、ledger label maps，加 unit tests**（effort S）  
   檔案：`web/src/features/billing/billing-model.ts（新）；web/src/features/billing/billing-model.test.ts（新）；web/src/features/billing/billing-copy.ts（新）`
3. **重寫 view：拆做 plan-card／allowances／plans／ledger；error + stale state；PageContainer isLoading；所有 Unavailable 分支；AnimatedBadge 讀 lifecycle；StatefulButton；加 data-tour**（effort M）  
   檔案：`web/src/features/billing/billing-view.tsx；web/src/features/billing/{plan-card,allowances,plans,ledger}.tsx（新）`
4. **Checkout 確認 polling：useUsage(options)；backoff 2→10s，最多 2 分鐘；成功就 router.replace 清走 query**（effort S）  
   檔案：`web/src/lib/api/hooks.ts:44-47；web/src/features/billing/plans.tsx`
5. **Members meter（按 status 篩）；Storage 暫時寫「not measured」**（effort S）  
   檔案：`web/src/features/billing/allowances.tsx`
6. **Billing tips tour：tours.ts 加 billing-tips；TourCtx 同 use-tour-context 加 isOwner／portalAvailable**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts；web/src/features/onboarding/use-tour-context.ts`
7. **非 owner 讀取（要等 step 1 剔走欄位先做）：nav／sidebar 拎走 owner gate；checkout／portal／cost guard 用 checkAccess owner**（effort S）  
   檔案：`web/src/config/nav-config.ts:155-161；web/src/components/layout/app-sidebar.tsx:221-226；web/src/features/billing/billing-view.tsx`
8. **Ledger v2：DataTable + Tabs segment + DigitSwap + Show all + CSV + mobile stacked rows**（effort M）  
   檔案：`web/src/features/billing/ledger.tsx；web/src/components/ui/table/data-table.tsx；web/src/lib/download.ts`
9. **402 提醒：三個 toast 喺 err.status===402 時加 See plan action，並保留 composer 輸入**（effort S）  
   檔案：`web/src/features/ideas/ideas-view.tsx:143；web/src/features/agent/home-view.tsx:193；web/src/features/agent/conversation-view.tsx:204`
10. **Founder 決定：reconcile 係咪只喺新 period 補滿；trial 完咗係咪真係停 publishing；assist-bounded-v1 係咪 retire**（effort S）  
   檔案：`src/postriff_phase2/billing.py:210-211, 246；docs/postriff-consumer-web/billing-and-email.md`
11. **Founder-only：Stripe products／prices、portal、webhook、env、SQL 將 plan 設做 active；用 test mode 行一次 checkout 驗證 polling 同 cancelled 後再 checkout**（effort S）  
   檔案：`docs/postriff-consumer-web/billing-and-email.md:20；migrations/postriff/007_consumer_web_billing.sql:21-25（用 SQL update，唔係新 migration）`
12. **P2：storageUsedBytes backend；invoices proxy；webhook applied audit + Billing activity**（effort M）  
   檔案：`src/postriff_phase2/billing.py；src/postriff_phase2/billing_stripe.py；src/postriff_phase2/hosted.py；src/postriff_phase2/hosted_app.py:383-390；web/src/lib/api/{client,types,hooks}.ts；web/src/features/billing/invoices.tsx（新）`

## Risks

- 另一個 session 改緊 web/src，實作時要 stage by path。
- Stripe 未 mount 之前，Plans 全部顯示「Not yet available」，而且冇 Manage billing；係事實，唔可以扮有得買。
- Trial 過期 server 冇 enforce（billing.py:246）；UI 唔可以寫「publishing paused」，要 founder 拍板。
- Connected accounts 上限冇 enforce；將來 enforce 都要跟 remind, don't block，唔可以令 OAuth 失敗。
- raw subscription.status 同 lifecycle.status 喺同一個 response 可以差一步；一律用 lifecycle。
- GET /usage 會 UPDATE 同 FOR UPDATE（billing.py:33-37, 245）；polling 同開放俾所有 member 都會增加 workspace row lock，所以 polling 要 backoff，而且只喺 checkout=success 時開。
- 任何 active + planTermsId 嘅 webhook 都會補滿 allowance（billing.py:210-211），portal 改設定可能期中重設，meter 數字會同 period 對唔上。
- 同一個 plan 有兩個 active row 時，規則係揀 version 最高嘅，要喺 docs 記低。
- Ledger 只返最新 100 條（billing.py:118），冇 pagination；CSV 亦只有呢 100 條。
- Storage 未有 backend 量度之前冇 meter，頁面會一直寫「not measured」。
- plan_terms currency 限死 USD（007:12）；Stripe price 如果係其他幣種，UI 顯示嘅價錢會同實際收費唔同，webhook 唔會察覺。
- WorkspaceAccessProvider 未 wrap 時 STUB_ACCESS 預設 owner（access.tsx:37-43），gating 會靜靜雞失效。
- Allowance 用完時 paid run 喺 transaction 入面直接 402（ideas.py:390），同「never block creation」有張力；至少要保留輸入、提供 $0 路線或者提醒，唔可以係 dead end。

## 覆核記錄

- 改正：api.usage 喺 client.ts:153；api.checkout/api.portal 喺 client.ts:154-161 → 改做 client.ts:156（usage）、157-164（checkout/portal）
- 改正：hosted.py:373, 396 audit checkout_started / portal_opened → 改做 hosted.py:380, 398
- 改正：每月 allowance reset 係靠 invoice.paid webhook → 寫成「任何 active + planTermsId 嘅 applied webhook 都會重設 allowance（invoice.paid 係其中之一）」，並列入 risks
- 改正：subscription.label null → 「Trial」；trial workspace 嘅 subscription 係 null → Current plan 標題直接用 subscription.label；null 分支只作防禦性「Plan unavailable」，唔好寫死「Trial」
- 改正：Plans footer (a)/(b) 用 `!subscription.live` 判斷可唔可以 checkout → 用 `hasOpenSubscription = ['active','past_due','grace'].includes(lifecycle.status)` 取代 `subscription.live`，同 backend 409 條件一致
- 改正：Meter 90% 以上 amber（現有邏輯）照用 → Meter 統一語義：batches/credits 顯示 remaining，amber 條件係 remaining/total ≤ 10%；accounts/members 顯示 used，amber 係 used/total ≥ 90%
- 改正：Studio plan 有 writing batches allowance，meter 一定有 total → total===0 → 「Not included in this plan」，唔畫 bar
- 改正：Deterministic previews cost $0 and are not listed（empty state、info sidebar、tour 文案） → 改寫：「Runs that use no paid model are listed at $0 and do not use a writing batch.」
- 改正：Each model call appears twice: reserved, then settled to the real cost → 寫「Each run first reserves an estimate, then settles to the real cost, is released if it failed, or waits for reconciliation.」
- 改正：全 app 冇任何 data-tour 或 tour runner；onboarding 只靠 Infobar（page-container.tsx:23-40） → Tech req 改 exists:true（runner），新增工作只係 tours.ts 加 `billing-tips` PAGE_TOURS entry + TourCtx 加 isOwner/portalAvailable + billing-view 加 data-tour
- 改正：PageSkeleton 喺 page-container.tsx:5-22，用 animate-pulse／t-skel-pulse token → 改做 page-container.tsx:22-38 `animate-pulse`
- 改正：PageContainer pageHeaderAction 可以 flex-wrap 落標題下面 → 唔用 pageHeaderAction；Manage billing 只放 Current plan card footer（亦避免同一個 CTA 出兩次、data-tour 重覆）
- 改正：Storage used = snapshot assets bytes 總和（exists:true） → 改成 backend `storageUsedBytes`（exists:false，effort M）；未有之前只寫「{storageMb} MB included · usage not measured yet」
- 改正：Drafting 402 toast 喺 ideas-view.tsx:143、home-view.tsx:193、conversation-view.tsx:202 → conversation-view.tsx:204
- 改正：web/src/lib/auth/access.ts → 改路徑；risks 加：provider 未 wrap 時 fallback 係 owner
- 改正：Currency schema 只容許 USD（007:11） → 行號改 007:12；risk 改為：Stripe price 幣種同 plan_terms currency 唔一致時 UI 顯示嘅價錢會錯，webhook 唔會察覺
- 改正：Skeleton → 內容以 --duration-slow 淡入（transitions.css §14 + PageSkeleton） → 刪走呢條 motion，或者標 reuse:new 並講明要加 class；corrected spec 刪走
- 違反原則（已改）：規則 1（真數據）：Storage「used」由 snapshot assets 前端加總，backend 根本冇量度 storage，數字係部分值卻標做 used。
- 違反原則（已改）：規則 1：保留現有 ≥90% amber 邏輯，但 remaining 型 meter 會喺剩得多時變 amber，警示色同事實相反。
- 違反原則（已改）：規則 1：empty state、info sidebar、tour 寫「Deterministic previews cost $0 and are not listed」同「Each model call appears twice」，同 ideas.py:390 同 billing.py:101-106 嘅實際行為唔符。
- 違反原則（已改）：規則 1：Studio plan writingBatches=0 會畫出「0 / 0」空 bar，冇講明「Not included」。
- 違反原則（已改）：規則 1／誠實出口：用 subscription.live 判斷可唔可以 checkout，已取消嘅 Stripe 用戶會被引去 portal「Switch plans」，但 backend 其實容許重新 checkout。
- 違反原則（已改）：規則 4（motion）：「Skeleton → 內容 400ms 淡入」冇任何現有機制支持，係虛構 reuse。
- 違反原則（已改）：規則 4：reuse claim「PageSkeleton 用 t-skel-pulse token」唔真，實際係 Tailwind animate-pulse。
- 違反原則（已改）：規則 2（remind, don't block）：402 CTA 本身合規，但 spec 冇指出 allowance 用完會令 paid drafting run 直接失敗（ideas.py:390 喺 run transaction 入面 raise）；按 founder 規則應該提醒兼提供 $0 路線或保留輸入，唔可以只係一個失敗 toast。
- 補上遺漏：現有 tour 系統（features/onboarding/tours.ts PAGE_TOURS、TourCtx、when、heading() fallback）：billing tips 應該註冊喺度，TourCtx 要加 isOwner / portalAvailable，唔使新 runner。
- 補上遺漏：RBAC 邊界：usage response 包括 budget 同完整 ledger（model、成本）。如果對非 owner 開放頁面，只喺 UI 收起 cost guard 唔係安全邊界；backend 要按 owner 剔走 budget/ledger cost，或者另開 member view。
- 補上遺漏：WorkspaceAccessProvider 未 wrap 時，STUB_ACCESS（access.tsx:37-43）預設係 owner，會令 gating 靜靜雞失效。
- 補上遺漏：GET /usage 有寫入 side effect：lifecycle 會 UPDATE（billing.py:245）、budget 會 upsert 加 FOR UPDATE（billing.py:33-37）、entitlement 會 FOR UPDATE。3 秒 polling 兩分鐘即係 40 次鎖 workspace 嘅寫入 transaction，要考慮 backoff。
- 補上遺漏：Allowance 會喺任何 active subscription.updated event 補滿（billing.py:210-211）：喺 portal 撳 cancel/resume 可以期中重設 allowance。係 backend bug 定產品決定，要 founder 拍板。
- 補上遺漏：Checkout 其他真錯誤：429 throttle、502 email 解析唔到、503 public base URL 未設定、400 return path。
- 補上遺漏：Connected accounts 計數冇定義邊啲 channel status 算數（expired/needs reconnect 算唔算）；亦唔可以寫成一個混合嘅「Connected ✓」。
- 補上遺漏：i18n／語言：頁面文案全部係寫死嘅英文；formatDate 用 time.ts timeDefaults locale；cents() 固定 USD。docs/postriff-worldwide-languages-plan.md 講嘅係 post languages，唔係 UI locale，要講明呢頁暫時 English-only，文案集中放一個地方方便日後翻譯。
- 補上遺漏：Mobile：PageContainer header 唔 wrap；ledger 喺 375px 應該轉做 stacked rows，唔好靠七欄橫向 scroll。
- 補上遺漏：Grace 狀態：Stripe mapping 永遠唔會產生 'grace'（billing_stripe.py 冇 map），badge 嘅 grace 分支實際係 dead path，要註明。
- 補上遺漏：Trial 過期 + allowance 剩餘：overview-view 同 billing 兩邊嘅 trial 文案要一致（overview-view.tsx:215-219）。
- 補上遺漏：Members 計數要按 membership status 篩選。
- 補上遺漏：Refetch 失敗（已經有舊數據）時要有 stale 標示，唔好靜靜雞顯示舊數。
