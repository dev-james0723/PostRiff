# 11 · Analytics

> Route：`/app/analytics` · Sidebar：Grow · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**注意：前端已被另一個 session 重砌，未 commit（working tree，2026-09-16 17:19-17:29）。** 以下行號係 working tree，檔案仍會飄。

**前端（working tree）**：`web/src/app/app/analytics/page.tsx:1-8` metadata + `<AnalyticsView/>`。`web/src/features/analytics/analytics-view.tsx`（255 行）用 `useAnalytics()`（`web/src/lib/api/hooks.ts:54-57` → `web/src/lib/api/client.ts:214` `GET /api/workspaces/{id}/analytics/summary`）+ `useChannels()` + `useSnapshot()`（:80-82），喺 client 用 `coverage.ts` `buildCoverage()`（:85-131）由 `/channels` 嘅 per-capability matrix、snapshot verified jobs、summary posts 計 coverage；`coverageState()`（:137-145）出 unavailable/pending/partial/ready，label「No analytics source / Waiting for first reading / Some posts unread / All posts read」（:49-54）。Header：AnimatedBadge `data-tour=analytics-freshness`（:154）、「Last read …／No reading yet」、Refresh **disabled** + tooltip「Refresh arrives with scheduled readings…」（:57, :163-168）。`coverage-strip.tsx`：ui/tabs（All + 每 connection）、LevelBadge、DigitSwap 計數、motion/tooltip 顯示 evidence/verifiedAt、「Enable analytics ›」→ `/app/channels?connect=…&capability=analytics`、stagger 0.04 / cap 0.26 / 0.25s（:17-19）。StatCard×3：Posts read、Latest read、Accounts reporting（:191-213），下面明寫「readings are not scheduled yet」。`posts-table.tsx`：TanStack table + ui/table（唔係 data-table.tsx），provider column group、單一 provider 先可以按 metric sort、Likes/views rate、Read；<768px（useIsMobile）變 card list；data-tour analytics-table/row/unavailable。`post-sheet.tsx`：Sheet（mobile side=bottom）、全文（snapshot job）、metrics、rate、Readings（`post-readings.tsx` 只得一次讀數 → 「One reading so far — no trend yet」，sparkline 留空位）、providerPostId copy、「Open in Queue ›」。`empty-states.tsx` 四種（no-connections / no-analytics-capability / nothing-verified / awaiting-first-reading，:13-27），第四種明寫「Readings are not scheduled yet」。`rules-collapsible.tsx` 收埋 `data.rules`。`?connection=` 預選（:103-110）。Tour：`web/src/features/onboarding/tours.ts:211-248` analytics-tips 四步已登記。HEAD（已 commit）版本仍係 169 行單檔卡片版。

**Types 缺口**：`web/src/lib/api/types.ts:562-590` `AnalyticsPost` 冇宣告 API 已回嘅 `connectionId`／`contentTypeId`／`cohort`，`coverage.ts:15-18` 用 `AnalyticsPostRow` 暫補；`Analytics.connections[].analytics` 係 string、`state` 係 string。

**組件庫存**：`web/src/components/ui/chart.tsx`（Recharts 3.8.0，`web/package.json:55`）全 app 未用；`web/src/components/charts/heat-calendar.tsx`（`overview-view.tsx:129`）；`web/src/components/app/stat-card.tsx`；`web/src/components/app/level-badge.tsx`（包 `components/marketing/capability-badge` 嘅 CapabilityBadge）；`web/src/components/motion/button/stateful.tsx:158` StatefulButton（index.tsx 冇 re-export）；motion/{animated-badge,digit-swap,number-ticker,tooltip}.tsx。

**後端**：`src/postriff_phase2/hosted_app.py:396-397` `…/analytics/{summary|posts}` 都行 `service.analytics()`。`src/postriff_phase2/hosted.py:466-474` `analytics()`：`insights.summary()` 後 :472 hardcode connections 文字、:473 `state="limited"`（新前端已唔讀呢兩個 field）。`src/postriff_phase2/insights.py`（96 行）：`INSIGHT_METRICS` :15、`ingest_post_insights()` :19-43（每 metric 一行，缺嘅寫 unavailable，唔檢查 capability level）、`rate()` :46-51、`latest_observations()` :54-56（DISTINCT ON 最新）、`summary()` :59-82（**已回 connectionId :64、contentTypeId :75、cohort :76**）、`compare()` :85-96。表 `migrations/postriff/007_consumer_web_billing.sql:138-157` + RLS :192-199。

**最大缺口 — 生產冇數據來源**：`src/postriff_phase2/hosted_worker.py:33,112-116` 有 `on_verified`（同一 DB transaction），生產 `hosted_app.py:151` `PostgresWorker(database, social=social)` 冇傳；`hosted_app.py:150` social 只喺有 production_reviewed provider 先有。只有 `scripts/postriff_dev_hosted.py:174-183` 接咗（DevTransport :87-88 canned views/likes/replies）。冇 re-poll、冇 schedule、冇 history route。Cron：`vercel.json` 每分鐘 `/api/cron/worker` → `hosted_app.py:326-336`（tick + `hosted.py:402 run_reminders` + `learning_service.py:341 sweep`）。`providers.py:23 http_transport`、`hosted.py:77 throttle()`、`oauth.py:203 token_for_worker`。

**Capability 真相**：`channels.py:9`；`oauth.py:185-187` 只有 `production_reviewed` 先 Direct；`oauth.py:85` 唔支援 capability → 409；`oauth.py:191-201 channels()` 回 matrix + `providers[].capabilities.analytics`；scopes `providers.py:123`（Threads insights）、`:151`（Instagram insights）、LinkedIn `:91` 冇 analytics（:90 註釋 Community Management API not held）。

**RBAC**：`permissions.py` 冇 analytics class，read route 行 membership；`classify()` 預設 'edit'（:74），'refresh': 'read'（:38）。Client `web/src/lib/auth/access.tsx` 仍係 STUB_ACCESS（全部 owner）；nav-config.ts:79-87 Analytics 冇 access key。Pipeline CTA `pipeline-view.tsx:126-127`。

**其他 consumer／tests／docs**：`learning_service.py:173-179 latest_metrics_by_job()`；tests `tests/test_postriff_billing.py`（compare、route mock 'limited'）、`tests/phase2/postgres_billing.py:143-148`（斷言 limited）、`tests/phase2/postgres_learning_extract.py:202-204`；ingest_post_insights 零測試。Docs：`docs/postriff-consumer-saas-redesign.md:66,160-168,248,394,440`；`docs/postriff-motion-system.md:51`（Analytics 行）、§5 :102-108；`docs/postriff-worldwide-languages-plan.md:313`（cohort 用 canonical tag）、:340（language-badge.tsx 未落地）、:370（analytics 行）；`docs/postriff-admin-analytics/DELIVERY.md:13-14,19,48`（registry ≠ runtime）。i18n：web 冇翻譯框架，copy 全英文。

## 1. Design specification（最新版）

**目的**：俾用戶睇到「PostRiff 幫我出咗嘅 post，provider 自己報咗幾多」— 用 provider 原名同定義，逐個 account 睇，永遠唔跨 provider 加埋；邊個 account 有 analytics 權限、幾時讀過一眼睇晒；冇數寫 Unavailable，唔係 0；未有嘅功能（時間表、Refresh）照實講未有。

**Layout**：PageContainer（title、description、infoContent、pageHeaderAction）。Header cluster：AnimatedBadge（client 由 coverage 計 state）+「Last read {relativeTime}」／「No reading yet」+ Refresh button：backend refresh route 未上線前 disabled + 誠實 tooltip（現況）；上線後換 StatefulButton（`@/components/motion/button/stateful`）。主體：(1) Coverage strip（ui/tabs：All + 每 connection chip，LevelBadge=capabilities.analytics.level，DigitSwap 計數，tooltip evidence/verifiedAt）；(2) StatCard×3：Posts read（of N verified）、Latest read、Accounts reporting（Direct 數 of connected）— 「Next scheduled read」只喺 API 回 nextReadAt 之後先取代第三格；(3) Posts table（TanStack + ui/table，provider column group，All tab 多 provider 時 metric 欄唔可以 sort）；(4) Rules collapsible。Responsive：<768px（useIsMobile）table 變 card list、Sheet side=bottom max-h 85dvh；coverage tabs 橫向 scroll-snap；StatCard sm 以上三欄；≥768px Sheet side=right max-w 30rem、post 欄 pinned left。URL `?connection=<id>` 預選 tab。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header freshness cluster | 講清呢頁嘅數幾新、可唔可以再讀 | AnimatedBadge data-tour=analytics-freshness，label 用 coverage.ts STATE_LABEL（ready=「All posts read」，唔講 Up to date）。「Last read」= 所有 posts freshness.observedAt 最大值。Refresh：Phase 1 disabled + tooltip；refresh route 上線後 StatefulButton（idle→loading→success/error，success 只代表 provider 已回應），toast 講「{n} metrics available, {m} unavailable」，429 顯示 throttledUntil；上線時先加 data-tour=analytics-refresh 同 tour step。 | loaded 前 Skeleton；unavailable→neutral；pending/partial→warning；ready→success；refresh 429/5xx 唔改 badge。 |
| Coverage strip | 用 capability matrix 真值逐 account 講 analytics level，同時做 filter | 現有 coverage-strip.tsx：ChannelIcon + account + LevelBadge + DigitSwap（posts read 數）；tooltip = evidence／verifiedAt／「{read} of {verified} verified posts read」；providerOffersAnalytics && !Direct → 「Enable analytics for {account} ›」；provider 唔提供 → 「Not offered by {platform}’s API for this app.」（唔講 coming soon）；platform fallback 配對時出一句說明。data-tour=analytics-coverage。 | channels loading → Skeleton；channels error → RetryAlert；冇 connection → 唔 render（empty state 接手）。 |
| Stat tiles | 三個係 list 長度嘅 count，唔係 metric 總和 | Posts read（visiblePosts.length，hint of verified）、Latest read（relativeTime 或 —）、Accounts reporting（Direct 數 of connected）。時間表上線後：第三格可換「Next scheduled read」= relativeTime(API nextReadAt)，footer 讀 API 回嘅 schedule offsets，唔寫死。 | 各自 loading；API error → value「—」；Unavailable 永遠唔變 0。 |
| Posts table | 以 post 為單位、用 provider 原名逐欄睇 | 現有 posts-table.tsx：Post（ChannelIcon、account、text 首 80 字／providerPostId、language · origin · state）、Published（snapshot job verification.at）、per-provider native metric 欄（header tooltip：unit、definitions、not comparable across providers）、Likes/views（rate.display，numerator/denominator 同一次讀數）、Read。row click → Post sheet。data-tour analytics-table／analytics-row（第一行）／analytics-unavailable（第一個 Unavailable cell）。P2：faceted filter by language/contentType（要等 canonical language tag）。 | <768px card list；Direct 但未有讀數 → 見 empty；某 tab 冇 row → 該 account 專屬 Empty（analytics-view.tsx:223-238）；有 verified 未讀 → 表下一句「{n} verified posts have no reading yet」。 |
| Post sheet | 一條 post 嘅完整證據：全文、receipt、讀數 | 現有 post-sheet.tsx：text（snapshot job；冇就「The text is not part of this reading」）、metrics、rate、Readings、Details（providerPostId copy、job、Published + verification.method、definitions、observed/ingested）、「Open in Queue ›」。History route 上線後：post-readings.tsx ≥2 個 available 點先畫 ChartContainer + Recharts LineChart（animationDuration 250、isAnimationActive={!reduce}），1 點「One reading so far — no trend yet」，0 點「Unavailable at every reading」；observations list 加 sourceEndpoint host。 | job 唔喺 snapshot → 誠實 fallback；history loading → Skeleton；history error → Alert + Retry，唔關 sheet。 |
| Compare card (P1) | 同 provider + 同語言 + 同 content type 先比較，包現成 insights.compare() | Select provider / language / contentTypeId / native metric（只列有數嘅 cohort）→ GET /analytics/compare。observation_only → mean + 「{measured} of {sampleSize} posts had a reading」+「Observation, not a cause」；insufficient_sample →「{measured} posts have this metric; 3 needed」。language 要等 canonical tag（languages plan :313）先上。 | 冇 cohort → 唔 render；409 唔應出現（UI 只揀單一 cohort），出現就 Alert。 |
| Rules (collapsible) | 保留 API rules 但唔霸位 | 現有 rules-collapsible.tsx，data.rules 四條，預設收埋。 | data 到咗先出。 |
| Info sidebar | 解釋定義同讀數規則 | 現有五段（analytics-view.tsx:34-55），包括「When PostRiff reads」（現況：冇固定時間表）同「Why some accounts have no numbers」。時間表上線後先將「When PostRiff reads」改為 API 回嘅 offsets。 | static，但讀數時間表文字跟 backend 能力更新。 |

- **Empty state**：四個（現有 empty-states.tsx，chooseEmptyKind 由真 list 決定）：(a) no-connections →「No accounts connected」+ Connect a channel；(b) no-analytics-capability → 每 connection 一行 LevelBadge + evidence／「Not offered by {platform}’s API for this app.」+ Enable analytics；(c) nothing-verified →「Nothing published through PostRiff yet」+ Open the queue（**唔寫**「one hour after」直至時間表存在）；(d) awaiting-first-reading →「Waiting for the first reading」，現況講明「Readings are not scheduled yet」；時間表上線後改為「First read {relativeTime(nextReadAt)}」。
- **Loading**：三個 query（useAnalytics、useChannels、useSnapshot）各自 loading：header badge Skeleton、CoverageStrip Skeleton、StatCard loading、DataTableSkeleton（5 欄 3 行）。唔用 PageContainer isLoading 成頁遮。冇假 loading copy。缺口：useSnapshot error 時 loaded 永遠 false，要加 snapshot RetryAlert。
- **Error**：channels / analytics（/ snapshot 要補）分開 RetryAlert（ApiError →「{what} could not be read (HTTP {status}).」+ Retry）。channels 失敗時 table 照出；analytics 失敗時 coverage 照出、tiles「—」。Refresh（上線後）429 → toast throttledUntil；5xx → toast「The provider could not be reached」，badge 唔變。Sheet 內 history error → Alert + Retry。Unavailable 永遠唔渲染成 0。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 頁面內容 | route 進入 | page slide 進入 | web/src/app/app/template.tsx:13 .t-page-enter | 否（純裝飾） |
| Header AnimatedBadge | coverage state 計出／改變 | badge pop（--badge-pop-dur，transitions.css:52）；顏色由真 state | web/src/components/motion/animated-badge.tsx | 是 |
| Refresh button（route 上線後） | click → mutation pending → settled | idle→loading→success/error，success 只喺 200 後；收快過開 | web/src/components/motion/button/stateful.tsx（StatefulButton，冇 icon slot） | 是 |
| Coverage chips、table rows、mobile cards | data 首次到達 | opacity 0→1、y 8→0，stagger 40ms，delay cap 0.26s，duration 0.25s；reduced motion → initial=false | coverage-strip.tsx:17-19 STAGGER 常數（posts-table 共用）+ EASE_OUT @/lib/ease | 是 |
| Tab 計數 | posts read 數改變 | 數位滾動 | web/src/components/motion/digit-swap.tsx | 是 |
| Tabs pill | 切換 tab | active indicator 滑動 | web/src/components/ui/tabs.tsx | 否（純裝飾） |
| Metric cell、StatCard 數字 | value 到達 | NumberTicker 只對 availability=available 嘅整數；Unavailable 靜態文字 | features/analytics/metric-value.tsx + web/src/components/app/stat-card.tsx | 是 |
| Post sheet | row click / Escape | panel 開 400ms／收 350ms（--panel-open-dur/--panel-close-dur，transitions.css:75-76） | web/src/components/ui/sheet.tsx（mobile side=bottom） | 否（純裝飾） |
| Sparkline（history route 上線後） | sheet 開、observations 到達 | Line animationDuration 250、isAnimationActive={!reduce}；≥2 個 available 點先畫 | web/src/components/ui/chart.tsx ChartContainer + recharts LineChart | 是 |
| Metric header / chip tooltip | hover / focus | tooltip 開合用 transitions token | web/src/components/motion/tooltip.tsx | 是 |
| Enable analytics › / Open in Queue › | hover | 箭嘴滑動（.t-learn） | web/src/components/ui/learn-more-chevron.tsx | 否（純裝飾） |
| Rules collapsible | toggle | t-nav-panel 展開；chevron rotate duration-fast，motion-reduce 關 | web/src/components/ui/collapsible.tsx | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | 前端 coverage／table／sheet／empty states／rules／tour ids／?connection= | frontend | 有 | working tree（未 commit，另一 session）：web/src/features/analytics/{analytics-view,coverage,coverage-strip,posts-table,post-sheet,empty-states,rules-collapsible,metric-value,post-readings}；tours.ts:211-248 | S |
| 2 | TS types 宣告 API 已回嘅 connectionId／contentTypeId／cohort；state 改 union；之後加 nextReadAt／history／refresh／compare types | frontend | 冇 | types.ts:570-590 冇；coverage.ts:10-18 暫補；insights.py:64,75-76 已回 | S |
| 3 | 生產 wiring：on_verified 只 insert 首個讀數排程（或直接 ingest），只對 analytics=Direct connection | backend | 冇 | hosted_app.py:151 冇 on_verified；hook hosted_worker.py:112-116（同一 transaction）；dev 版 scripts/postriff_dev_hosted.py:174-183；ingest_post_insights 唔檢查 level | S |
| 4 | 讀數時間表：migration `pr_metric_reads` + RLS；`insights.sweep()` SKIP LOCKED、bounded max_seconds、429/5xx back-off、abandon 寫 unavailable；HTTP 喺 job transaction 外做 | backend | 冇 | 只有 pr_metric_observations（007:138-157）；cron pattern hosted_app.py:326-336；migrations 最新 untracked 012_channel_pictures.sql，新 migration 編號要協調（013+） | M |
| 5 | Summary 清理：刪 hosted.py:472-473 hardcode connections／limited，或改用 capability 真值；同步改 tests 斷言 | backend | 冇 | hosted.py:466-474；tests/phase2/postgres_billing.py:143-148 同 tests/test_postriff_billing.py route test 斷言 'limited' | S |
| 6 | `GET /analytics/posts?connectionId=` 回每 post observations history | api | 冇 | hosted_app.py:396-397 posts = summary alias；latest_observations DISTINCT ON（insights.py:54-56） | S |
| 7 | `POST /analytics/refresh`：throttle(cur, f"analytics-refresh:{workspace_id}", 1, 600)；permissions.py ACTION_CLASSES 登記 'analytics_refresh': 'read' | api | 冇 | 無 route；hosted.py:77 throttle；permissions.py:74 classify 預設 edit、:38 refresh→read | S |
| 8 | `GET /analytics/compare` 包 insights.compare() | api | 冇 | insights.py:85-96 + tests/test_postriff_billing.py rate/compare test；無 route | S |
| 9 | client + hooks：analyticsPosts／refreshAnalytics／analyticsCompare + useAnalyticsPosts／useRefreshAnalytics（invalidate keys.analytics）／useAnalyticsCompare | frontend | 冇 | client.ts:214 只有 analytics；hooks.ts:54-57 只有 useAnalytics；keys.analytics hooks.ts:15 | S |
| 10 | Chart／motion primitives | frontend | 有 | ui/chart.tsx（recharts 3.8.0 package.json:55，未用）；app/stat-card.tsx；app/level-badge.tsx；motion/{number-ticker,digit-swap,animated-badge,tooltip}.tsx；motion/button/stateful.tsx:158 | S |
| 11 | 觀察表 + RLS | data | 有 | migrations/postriff/007_consumer_web_billing.sql:138-157、:192-199 | S |
| 12 | 每分鐘 cron | infra | 有 | vercel.json crons /api/cron/worker；hosted_app.py:326-336 | S |
| 13 | Threads／Instagram insights 讀取 code | backend | 有 | insights.py:19-43；GRAPH_VERSION providers.py:15；只喺 dev harness 被 call | S |
| 14 | Capability Direct 門檻 | backend | 有 | oauth.py:185-187；LinkedIn providers.py:91 冇 analytics scope | S |
| 15 | Tests：ingest_post_insights（total_value vs values、non-200）、sweep PG、refresh throttle + permission、跨 tenant、tick 唔因 insights 失敗 | backend | 冇 | grep tests 冇 ingest_post_insights | M |
| 16 | Snapshot error handling（loaded 永遠 false） | frontend | 冇 | analytics-view.tsx:100 loaded 需要 snapshot.data，但冇 snapshot.error Alert | S |
| 17 | LanguageBadge + canonical language tag | frontend | 冇 | docs/postriff-worldwide-languages-plan.md:340,370；web/src/components/language-badge.tsx 未存在 | S |

## 3. Features

### P0

- **生產數據路徑：verified 後讀 + 固定時間表再讀**：真數據先郁之下，冇 ingestion 呢頁永遠只係空狀態；hosted_app.py:151 冇 on_verified 係主因。t≈0 一次讀好多時得 0／Unavailable，要時間表先有意義。HTTP call 唔好喺 job 嘅 DB transaction 入面行。
- **Types 對齊 + summary hardcode 清理**：前端已經用 client coverage，API 嘅 limited／hardcode 文字變成死碼兼誤導；types 唔宣告 connectionId 令 coverage.ts 要自補型別。
- **Capability-honest coverage strip**：已喺 working tree 做咗；要 commit（由擁有嗰個 session）並補 eligible 計法（授權前 verified 嘅 post 唔應令頁面永遠 partial）。
- **以 post 為單位 table + 四個 empty state**：已喺 working tree；剩 snapshot error、時間表上線後 empty (d) copy 更新。（depends on：另一 session commit）

### P1

- **Post sheet sparkline（history）**：post-readings.tsx 已預留 ≥2 點分支；有 history route 先畫，唔會一點畫線扮趨勢。（depends on：時間表 + GET /analytics/posts history）
- **Refresh now（每 workspace 10 分鐘一次）**：用戶想即刻睇；provider rate limit 要保護；現況 disabled + 誠實 tooltip，route 上線先 enable 同加 tour step。（depends on：POST /analytics/refresh + permissions 登記）
- **Like-for-like compare card**：insights.compare() 已寫好有 test；Memory 頁 performance note 用同一套 cohort 紀律。（depends on：compare route + canonical language tag）

### P2

- **Instagram insights 實測（production review 後）**：SOURCES.md 標 Instagram 文件 source_unavailable；views vs impressions 要真 token 驗；review 前 capability 唔會 Direct。（depends on：Instagram production review）
- **Faceted filter（language／contentType）+ CSV export**：observations 本身係表，export 唔製造新數；filter 要等 canonical tag。
- **LinkedIn analytics 經 Community Management API 申請**：外部審批；未拎到前只可以 Unsupported + not offered。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明白：(1) 列嘅係 PostRiff 出過嘅 post，唔係成個 account；(2) 每個 account 有自己嘅 analytics level（Direct／Unsupported），一粒 chip 一個真值；(3) 冇數寫 Unavailable 唔係 0，唔同 provider 嘅數唔加埋；(4) 冇嘢係 live，每行有自己讀數時間。教法：coverage strip 放最頂、用 Channels 同一套 LevelBadge 三色；table header 用 provider 原名；badge 講讀數狀態唔講 Live；info sidebar 照實講「未有固定時間表」直至 backend 有。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="analytics-coverage"]（已存在，coverage-strip.tsx:54,63；已登記 tours.ts:217-223）` | Which accounts report numbers | Each connected account shows its own analytics level. Direct means PostRiff reads the provider’s official insights for posts it published. Unsupported means that provider does not offer them to this app. |
| 2 | `[data-tour="analytics-freshness"]（已存在，analytics-view.tsx:154；已登記）` | When these numbers were read | Nothing here is live and nothing is estimated. The badge tells you the state of the readings; every row carries its own time. |
| 3 | `[data-tour="analytics-table"]（已存在，posts-table.tsx:238,288；已登記）` | Native names, never added together | Each provider reports its own metrics under its own names. Columns follow the account you pick and are never summed across providers. |
| 4 | `[data-tour="analytics-unavailable"]（已存在，fallback analytics-table；已登記）` | Unavailable is not zero | When a provider has not reported a metric yet, the cell says so. A real zero shows as 0. |
| 5 | `[data-tour="analytics-row"]（element 已存在 posts-table.tsx:258,295；tours.ts 未登記，要加）` | Open a post | Select a post to see its text, the provider’s receipt and its reading. |
| 6 | `[data-tour="analytics-refresh"]（未存在；POST /analytics/refresh 上線後先加 element 同 step，body 用 TourCtx／API 值，唔寫死時間表）` | Read again | Refresh asks the provider now, at most once every few minutes per workspace. The page shows when the next scheduled reading is due when one is scheduled. |

**Empty state 教咩**：因果鏈：connect account → 另外授權 analytics（同 publish 係兩個 grant）→ 經 PostRiff 出 post → provider verify → 讀數。每個空狀態只講卡住嘅一步同 CTA；provider 唔提供就寫「Not offered by {platform}’s API for this app」，唔講 coming soon；已 verified 未讀嘅照實講「readings are not scheduled yet」，時間表上線後先顯示「First read in …」。

## 5. Next steps（按次序）

1. **協調：前端 WIP 屬另一 session（analytics-view.tsx 已 M、8 個 untracked 檔）。唔好重寫；由擁有者按 path stage + commit，或者確認後先接手。核對 tsc／oxlint 通過。**（effort S）  
   檔案：`web/src/features/analytics/*, web/src/features/onboarding/tours.ts`
2. **Types 對齊：AnalyticsPost 加 connectionId／contentTypeId／cohort，Analytics.state 收窄；刪 coverage.ts AnalyticsPostRow 暫補（只加唔改，按 path stage）。補 snapshot error RetryAlert。**（effort S）  
   檔案：`web/src/lib/api/types.ts:570-590, web/src/features/analytics/coverage.ts:10-18, web/src/features/analytics/analytics-view.tsx:80-100`
3. **Summary 清理：刪 hosted.py:472-473 hardcode（或回 capability 真值），同步改 route／PG tests 嘅 'limited' 斷言。**（effort S）  
   檔案：`src/postriff_phase2/hosted.py:466-474, tests/test_postriff_billing.py, tests/phase2/postgres_billing.py:143-148`
4. **生產 wiring + 時間表：新 migration（013+，避開 untracked 009/011/012）`pr_metric_reads` + RLS；`hosted_app.py runtime_from_environment()` 傳 on_verified，只 insert 讀數排程（檢查 analytics level==Direct）；`insights.sweep()` 喺 transaction 外 call provider，429/5xx back-off，token 錯誤寫 unavailable 唔 raise；cron tick 加 result['insights']。Unit test fake transport（total_value／values／non-200），PG test（到期、SKIP LOCKED、跨 tenant、tick 唔失敗），tests/phase2/rls.sql 覆蓋。**（effort M）  
   檔案：`migrations/postriff/013_metric_reads.sql (new), src/postriff_phase2/insights.py, src/postriff_phase2/hosted.py, src/postriff_phase2/hosted_app.py:130-152,326-336, tests/test_postriff_insights.py (new), tests/phase2/postgres_insights.py (new), tests/phase2/rls.sql`
5. **Routes：GET /analytics/posts?connectionId=（history）、POST /analytics/refresh（throttle，permissions.py 登記 analytics_refresh→read）、GET /analytics/compare；summary 加 nextReadAt。Route tests。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:396-397, src/postriff_phase2/hosted.py, src/postriff_phase2/insights.py, src/postriff_phase2/permissions.py, tests/test_postriff_billing.py`
6. **前端 hooks + 接 backend 能力：useAnalyticsPosts／useRefreshAnalytics／useAnalyticsCompare；Refresh 換 StatefulButton + data-tour=analytics-refresh；第三格／empty (d)／info sidebar 改讀 API nextReadAt；post-readings.tsx ≥2 點分支畫 Recharts sparkline；tours.ts 加 row 同 refresh step。**（effort M）  
   檔案：`web/src/lib/api/{client,hooks,types}.ts, web/src/features/analytics/{analytics-view,post-readings,post-sheet,empty-states}.tsx, web/src/features/onboarding/tours.ts, web/src/components/ui/chart.tsx`
7. **Compare card（P1）：cohort selects → useAnalyticsCompare；等 canonical language tag。**（effort S）  
   檔案：`web/src/features/analytics/compare-card.tsx (new)`
8. **Docs + 驗證：motion-system.md:51 Analytics 行更新（Tabs、DigitSwap、Sheet、StatefulButton、Recharts line）；用 dev harness 驗 UI（pane 開 :3100），**唔可以** approve／schedule／send（Threads 係 live）— 用 PG test 或直接 insert observations 驗 Unavailable／多 provider column group；375/768/1440 + reduced motion 截圖。**（effort S）  
   檔案：`docs/postriff-motion-system.md, tests/phase2/*`
9. **LanguageBadge 落地後換 posts-table／post-sheet 嘅 language 文字。**（effort S）  
   檔案：`web/src/features/analytics/{posts-table,post-sheet}.tsx, web/src/components/language-badge.tsx（per docs/postriff-worldwide-languages-plan.md:340）`

## Risks

- Parallel session：前端 analytics 檔係另一 session 未 commit 嘅 WIP；hosted.py／hosted_app.py／oauth.py／types.ts／client.ts／hooks.ts 都有未 commit 改動，行號會飄；一定按 path stage，唔可以 whole-tree commit。
- Provider review gate：oauth.py:185-187 只有 production_reviewed 先 Direct；Meta review 未過前生產頁一定係 empty (b)。接咗 wiring ≠ 即刻有數。
- Transaction 長度：on_verified 喺 worker 嘅 job transaction 入面行（hosted_worker.py:112-116）；直接做 20s HTTPS 會鎖住 job；應只排程，由 sweep 喺外面讀。
- coverageState 偏差：analytics 授權前已 verified 嘅 post 永遠唔會讀 → 永遠 partial；要按 capability verifiedAt 過濾 eligible jobs。
- Snapshot 依賴：text／Published 靠 snapshot jobs join；snapshot 失敗現時令頁面卡喺 skeleton。
- Threads insights 時效同 v24.0：新 post views 可能延遲；429 要 back-off 寫 unavailable，唔寫 0。
- Instagram metric 定義未用真 token 驗（SOURCES.md source_unavailable）；未驗前唔可以話 ready。
- LinkedIn：providers.py:91 冇 analytics scope；任何位置唔可以寫 coming soon。
- Token 生命周期：token_for_worker（oauth.py:203）對 revoked／expired 會 raise；sweep 必須 catch → unavailable，唔可以令 /api/cron/worker 失敗。
- 跨租戶：sweep 每條 SQL 帶 workspace_id；新表要 RLS + rls.sql 覆蓋。
- 重複讀數：pr_metric_observations 冇 unique；idempotency 靠 pr_metric_reads (job_id, due_at)；refresh 同 sweep 同時觸發要測。
- Learning 副作用：learning_service.py:173-179 用最新 available 值；有時間表後唔同 post 讀數齡唔同，performance note 要同 offset 比較或標明讀數齡。
- Registry ≠ runtime：docs/postriff-admin-analytics 42 個定義未接 runtime，metric 名唔同；呢頁只用 runtime 定義。
- All tab 誘惑：禁止 Total views；code 層已限制多 provider 時 metric 欄唔可 sort（posts-table.tsx:142,162），唔好加 footer 總和。
- Dev harness Threads 係 live：驗證唔可以 approve／schedule／send。
- i18n：web 冇翻譯框架，copy 全英文；language 係 display name，compare／filter 要等 canonical tag。

## 覆核記錄

- 改正：status_now：analytics-view.tsx 係 169 行單檔，Skeleton h-64、單一 Empty、每 post 一張 Card、stagger 0.05（:78, :81-101, :103-148, :109）；冇 filter／tour id／refresh → status_now 改為描述 working tree 現況，並標明係另一 session 未 commit 嘅 WIP；spec 嘅前端 next steps 大部分已完成，要改做『對齊／補完』。
- 改正：hooks.ts:54-57 useAnalytics → client.ts:209 GET …/analytics/summary → client.ts:214
- 改正：types.ts:558-586 Metric／AnalyticsPost／Analytics；connections[].analytics 係 string → types.ts:560-590
- 改正：web/src/lib/auth/access.ts 做 RBAC gating → 引用 access.tsx，並講明 client gating 未接真 membership，後端先係真 gate。
- 改正：hosted_app.py:397-398 summary|posts 兩個都行 service.analytics() → working tree 係 :396-397（HEAD :370-371）；posts 只係 alias 屬實。
- 改正：hosted.py:452-460 analytics()，:458 hardcode connections、:459 state='limited' → hosted.py:466-474
- 改正：insights.summary() 冇出 text/publishedAt/connectionId（technical_requirements 第 3 項） → 後端只欠 TS type 宣告 connectionId/contentTypeId；text/publishedAt 可以維持 client join，或者加 field 作 P1。
- 改正：oauth.py:163-165 Direct 門檻；oauth.py:82-83 start 409；oauth.py:170-178 channels() matrix；providers.py:122/:150/:90 scopes → 用 working tree 行號並註明檔案有未 commit 改動、行號會再飄。
- 改正：docs：motion-system.md:1 表 Analytics 行；worldwide-languages-plan.md:283,313 標 LanguageBadge → :51；:340,:370
- 改正：Tour targets：analytics-coverage/freshness/table/unavailable/row/refresh 全部『新加』 → 只有 row 同 refresh 步驟要加；refresh 步驟要等 POST /analytics/refresh 真存在先登記。
- 改正：Loading 用 PageContainer isLoading（page-container.tsx:5-22 PageSkeleton）；三個 query useChannels/useAnalytics/useAnalyticsPosts → 照 working tree 描述。
- 改正：375px Sheet 改用 ui/drawer；posts table 用 ui/table DataTable → 以現實為準；faceted filter 列 P2。
- 違反原則（已改）：Rule 1（真數據先郁）：tour step『Read again』同 info sidebar『When PostRiff reads』寫死「1 hour, 1 day, 3 days, 1 week and 4 weeks」、empty state (c)「The first reading happens one hour after a post is verified」、StatCard『Next scheduled read』footer — 時間表（pr_metric_reads）根本未存在；喺 backend 落地前出呢啲 copy 係講大話。Working tree 反而做得啱（analytics-view.tsx:44-47、:57 明寫 'There is no fixed schedule yet'）。必須由 API 回 nextReadAt／schedule 先顯示。
- 違反原則（已改）：Rule 1：spec 將『Refresh』描述為 enabled（只要有 Direct），但 POST /analytics/refresh 未存在；working tree 係 disabled + 誠實 tooltip，spec 要保持到 route 上線為止。
- 違反原則（已改）：Rule 1：coverage state『ready = Up to date』暗示新鮮度；實際只係『每個 verified post 至少讀過一次』。Working tree label 係『All posts read』(coverage.ts:53)，較誠實，spec 應跟。
- 違反原則（已改）：Rule 4（motion）：Refresh 『done 剔』用 StatefulButton success 狀態 — 但 refresh 可能 200 而全部 metric Unavailable；success 只可以代表『已向 provider 讀過』，唔可以暗示有新數。要喺 toast／copy 講明讀到幾多個 available。
- 違反原則（已改）：Rule 4：spec 嘅 motion 行『Header AnimatedBadge 收 180ms』無 token 證據；改為引用 transitions.css :52 badge-pop token，唔自創時長。
- 違反原則（已改）：Rule 5（capability honesty）：spec 無問題，但 compare card 『只列有數嘅組合』要避免暗示 cross-provider；OK。未見違規。
- 違反原則（已改）：House rule：spec next step 6/7 叫人重寫 analytics-view.tsx 等檔 — 呢啲檔而家係另一 session 未 commit 嘅 WIP（memory：shared working tree, stage by path），直接重砌會踩人哋改動。
- 補上遺漏：Working tree 現況：前端 coverage strip／posts table／post sheet／empty states／rules collapsible／tour registry 已由另一 session 做咗（未 commit），spec 完全冇察覺。
- 補上遺漏：RBAC：web/src/lib/auth/access.tsx 仍係 STUB（全部 owner），client 側冇真 gating；POST /analytics/refresh 要喺 permissions.py ACTION_CLASSES 登記（建議 'analytics_refresh': 'read'，同 :38 'refresh' 一致），否則 classify() 預設 'edit'，viewer 會 403。
- 補上遺漏：on_verified 喺 worker 嘅 DB transaction 入面行（hosted_worker.py:112-116），ingest_post_insights 做 HTTPS（http_transport 20s timeout）— 會拖長 job lock；建議 on_verified 只 insert 第一行 pr_metric_reads（due=now），由 sweep 喺 transaction 外讀 provider。
- 補上遺漏：hosted_app.py:150 social 只喺有 production_reviewed provider 時先建立；on_verified wiring 應同樣受 capability 限制（ingest_post_insights 本身唔檢查 analytics level）。
- 補上遺漏：coverageState 風險：analytics 授權之前已 verified 嘅 post 永遠唔會有讀數 → 頁面永遠 'partial'；需要 verifiedJobs 只計 capability verifiedAt 之後嘅 job，或者 API 回 eligible 數。
- 補上遺漏：TS types 未宣告 insights.summary() 已經回嘅 connectionId/contentTypeId/cohort/families/freshnessNow（coverage.ts:10-18 用 AnalyticsPostRow 暫補）。
- 補上遺漏：Summary API 嘅 data.state／data.connections 已冇 consumer（新 view 用 /channels + snapshot），hardcode 應刪或改；tests（test_postriff_billing.py 同 postgres_billing.py）斷言 'limited' 要同步改。
- 補上遺漏：Snapshot 依賴：post text/Published 由 useSnapshot jobs join；snapshot 冇嘅 job（例如被刪、超出保留）要有誠實 fallback（post-sheet.tsx:84,143 已有），spec 要列入 states。
- 補上遺漏：i18n：web 冇 i18n 框架，所有 copy 英文；language 欄係 display name，languages plan（docs/postriff-worldwide-languages-plan.md:313）要 cohort 用 canonical tag — compare card 同 faceted filter 要等 canonical tag。
- 補上遺漏：Mobile：working tree 用 useIsMobile（768px）切 card list + bottom Sheet；spec 講 375px drawer 同 768px sticky 欄唔符現實（768 以下已係 card）。
- 補上遺漏：Error state：channels 失敗 vs analytics 失敗分開 RetryAlert（analytics-view.tsx:180-188）已存在；snapshot 失敗冇 Alert（只會令 loaded=false 永遠 skeleton）— 缺口。
- 補上遺漏：Dev harness 警告：:3100/:4331 harness 嘅 Threads 係 live provider；驗證時唔可以 approve/schedule/send（memory reference-dev-harness-live-threads），spec step 9『行 schedule→verify』違反。
