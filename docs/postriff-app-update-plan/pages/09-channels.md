# 09 · Channels（+ Connect）

> Route：`/app/channels` · Sidebar：Distribute · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

【注意：兩個版本】HEAD（已 commit）同 working tree（另一個 session 未 commit）差好遠。以下以 working tree 為準；HEAD 版本就係舊嘅三 section 頁（raw connectionState 字串、六行 capability table、Select + Dialog、50ms stagger，見 `git show HEAD:web/src/features/channels/channels-view.tsx`）。實作前要先搞清楚邊個 session 擁有呢啲未 commit 嘅檔。

【頁面與資料流】`web/src/app/app/channels/page.tsx:1-8` render `ChannelsView`（`web/src/features/channels/channels-view.tsx`，有 Suspense 包住，因為用咗 `useSearchParams`）。資料：`useChannels()`（`web/src/lib/api/hooks.ts:49`）→ `api.channels`（`web/src/lib/api/client.ts:167`）→ `GET /api/workspaces/{id}/channels`（`src/postriff_phase2/hosted_app.py:411-414`）→ `OAuthService.channels`（`src/postriff_phase2/oauth.py:191-201`），回 `{channels: ChannelView[], providers: ProviderView[]}`（`web/src/lib/api/types.ts:445-464`，ChannelView 多咗 `pictureDigest`）。每張 card 由 `customer_view`（`src/postriff_phase2/channels.py:50-59`）砌：`connectionState`（7 個值 `channels.py:11`，由 `connection_state()` `:33-47` 推算）、9 項 capability `{level, evidence, verifiedAt, capabilityVersion}`、`evidenceSource`、`scopes`、`expiresAt`。另外用 `useUsage()`（hooks.ts:44）同 `useSnapshot()`（jobs 計 per-account activity）。Providers 只喺 env 有 `POSTRIFF_OAUTH_<ID>_CLIENT_ID/SECRET` 先 mount，`_REVIEWED=true` 先 productionReviewed（`src/postriff_phase2/providers.py:174-181`）；LinkedIn（`:84-113`，SCOPES 只有 identity/publish/schedule `:91`）、Threads（`:116-141`）、Instagram（`:144-168`）。Dev harness（`scripts/postriff_dev_hosted.py:165`）只 mount linkedin + threads `DevProvider`，`production_reviewed = True`（`:102`），所以 dev 見 Direct、production 未審批會係 Assisted。

【Endpoint】(1) `POST /channels/{provider}/oauth/start`（`hosted_app.py:415-417` → `oauth.py:79-99`）：未知 capability 400、provider 唔提供 409、要 `manage_connections`（owner/admin 或 `can_manage_connections` flag，`permissions.py:21`）、throttle 20/600s（429）、base URL 非 https 503（`oauth.py:74-75`）。(2) 公開 callback `GET /api/oauth/{provider}/callback`（`hosted_app.py:315-325`）→ `/channels/connect` → `web/src/app/channels/connect/forwarder.tsx` → `web/src/features/channels/connect-return.tsx` 做 `api.oauthComplete`（`client.ts:170-175` → `hosted_app.py:418-420` → `oauth.py:108-152`），upsert snapshot channel（`src/postriff_phase2/hosted.py:256-270`，`language` 硬寫 "English" `oauth.py:148`）。(3) `POST /channels/{id}/verify`（`hosted_app.py:422-423` → `oauth.py:222-245`）。(4) `GET /channels/{id}/picture`（`hosted_app.py:426`）。(5) `DELETE /channels/{id}`（`hosted_app.py:430-431` → `oauth.py:247-271`）：remote revoke、抹 ciphertext、capability 全降 Unsupported 並寫 evidence『Disconnected by the customer.』（:262）、mutate `p2_channel_disconnect`（`store.py:273` 只設 `revoked=True`，所以 API 回 `reauthorization_required`）。(6) `GET /api/me/channels`（`hosted_app.py:362-363` → `hosted.py:628-658`），Profile 用。(7) `GET /workspaces/{id}/audit`（`hosted.py:929-931`，LIMIT 200，冇 permission 限制）。(8) `GET /usage` 帶 `entitlement.connectedAccounts`（`billing.py:47`）。

【Working tree UI 已有】`channels-view.tsx`：PageContainer header `+ Connect`（`data-tour=channels-connect`，手機 icon-only；冇 canManage 就顯示一句文字）；`ChannelsSummary`（`channels-summary.tsx`，DigitSwap，usage 未返就隱藏 quota，到上限 link billing）；beUI `Tabs variant=pill` 用 `?filter=`（all / attention / direct / assisted / local，DigitSwap 計數）；`sortForAttention` 排序；Empty（channels-empty）同 filter-empty；card grid 用 `AnimatePresence` + stagger `min(index,3)*40ms`、0.18s；provider `ProviderTile` grid（CapabilityBadge、可請求 capability chips、『Connect another account』）；Collapsible Desktop companion（`Local · not available yet`，有 connected 時預設收埋）；error Alert + Retry，provider 區另外講『could not be loaded』。`channel-card.tsx`：`AnimatedBadge`（`channelBadge()`）、amber inset border + attention Alert + Reconnect（開 ConnectSheet reconnect mode）、`CapabilityChips`（`capability-chips.tsx`，hover 用 HoverCard、touch 用 Popover，顯示 evidence / verifiedAt / version）、meta 行（expiry amber、Verified relative、Evidence、Collapsible scopes）、activity link `/app/queue?channel=`、Re-verify StatefulButton（read_verified/publish_verified 閃『Verified』）、History（`channel-history-sheet.tsx`，所有 member）、Disconnect AlertDialog。`connect-sheet.tsx`：platform tiles → motion RadioGroup capability → oauthStart → 顯示 permissionExplanation + scopes → `Continue to {platform}`；reconnect 時 `rememberExpectedReconnect`（sessionStorage，`web/src/lib/channels/connect-expect.ts`）。`connect-return.tsx`：成功即 `router.replace('/app/channels?connected=<id>')`，missingScopes 同 account 唔符都 toast；Channels 頁 scrollIntoView + `SuccessCheck` 一次再清 param。共用模型 `web/src/lib/channels/state.ts` + `capabilities.ts`。Tour：`web/src/features/onboarding/tours.ts`（untracked）有 `channels-tips` 五步同 welcome tour 嘅 channels stop，data-tour ids 全部已加。

【已確認 gap】(a) `oauth.verify`（`oauth.py:222-245`）只 audit，唔寫 snapshot；`store.channel_state`（`store.py:82`）`verifiedAt+3600<now` 就回『Finish setup』，approve（:292）、build_manifest（:350）、reconcile（:425，job 變 held）全部要求『Ready for posting』→ hosted OAuth channel 連接一個鐘後排唔到程，Re-verify 救唔返，但 card 仲會閃『Verified』。(b) Grant 非 additive（`oauth.py:145-150`）；Threads exchange `scopes=None`（`providers.py:133`），IG 靠 `permissions`（`:160`）。Working tree 嘅 Connect sheet 已經為已連接平台提供 analytics / comments / reply，即係 bug 而家已經撳得到；`reconnectCapability()` 亦可能揀 analytics 而丟 publish。(c) `OAuthComplete`（`types.ts:477-485`）冇 `connectionId`，connect-return 用 cast；`Manifest.channelId` 已在 type（`types.ts:57`）但 channels-view 仲 cast。(d) Profile（`profile-model.ts:62-78`）、Overview（`overview-view.tsx:30, 194-199`，仲顯示 raw state 字串）、Billing（`billing-view.tsx:106` `channels.length`）、Getting started（`getting-started.tsx:30`）未用 `lib/channels/state.ts`，connected 數字同 Channels summary 唔一致；plan-card 用 `displayState`（`plan-card.tsx:146, 168`）另一套講法。(e) Queue 冇 `?channel=` filter（`queue-view.tsx` 冇 useSearchParams），card link 去到唔 filter 嘅頁。(f) `oauth.start` 冇 entitlement 檢查。(g) Disconnected 靠 evidence 字串判斷（`state.ts` DISCONNECTED_EVIDENCE），脆弱；disconnect 咗嘅 card 永遠留喺 list。(h) Card exit 用 0.18s，冇收快過開。(i) Language gate（`store.py:359`）仍在，但 languages plan §10 決定 1 已決定移除（`docs/postriff-worldwide-languages-plan.md:466`），未實作；defaults 存邊（決定 2，:480-482）未決。(j) `access.tsx:37-43` 仲係 STUB。(k) UI copy 全部硬寫英文，冇 UI i18n 框架。

## 1. Design specification（最新版）

**目的**：一頁答三個問題：邊啲 account 已經接咗、每項 capability PostRiff 真係驗證到咩 level（連證據同時間）、邊啲 account 而家要即刻處理（過期／缺 scope／即將到期／有 post 被 hold）。連接係可選：唔接任何嘢都可以 draft，empty state 要講明。

**Layout**：沿用 working tree 已有結構，唔重做：`PageContainer`（`pageTitle='Channels'`、description、InfoSidebar、`pageHeaderAction` = `+ Connect`，只喺 canManage 出現，否則一句『Ask someone who can manage connections in this workspace』；providers 為空時 `+ Connect` disable 並 tooltip 講冇 provider）。由上至下：(1) Summary strip；(2) Connected accounts heading + pill Tabs（`?filter=`）；(3) card grid `grid-cols-1 xl:grid-cols-2`，attention 排先；(4) Connect provider tiles `sm:grid-cols-2 xl:grid-cols-3`；(5) Desktop companion Collapsible。Responsive —— 375px：header icon-only（sr-only『Connect』）、tabs 一行 `overflow-x-auto`（頁本身唔橫 scroll）、card 單欄、chips `flex-wrap`、actions `flex-wrap`、Connect / History sheet `side='bottom'` max-h 92dvh；768px：card 單欄、tiles 兩欄；1440px：card 兩欄、tiles 三欄。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Summary strip | 五秒內知道全局：接咗幾多、幾多 Direct、幾多要處理、plan quota。 | `channels-summary.tsx`（已有）。connected 數用 `channelCounts().connected`（排除 customer-disconnected）；同一個函數要俾 Billing meter 同 Getting started 用，三頁數字一致。Quota 讀 `useUsage().data.entitlement.connectedAccounts`，到上限轉 amber link billing（只係提示，唔擋 reconnect）。 | loading：`Skeleton h-5 w-64`；usage 未返／出錯：quota 段隱藏（唔變 0）；snapshot 未返：attention 數字旁加細字『held posts not counted yet』或暫時唔計 held，唔好靜靜哋少計；零 connected：『0 connected · N platforms available to connect』。 |
| Filter row | 一撳睇要處理嘅嘢或按 level 睇。 | beUI `Tabs variant='pill'`（已有），`?filter=`；計數全部由真 list 計；`Local` tab 顯示 companion 目錄。 | 計數 0 都顯示 tab；Needs attention 冇嘢時 Empty『Nothing needs attention』+『Tokens are checked when a post is claimed and when you re-verify.』 |
| Channel card | 一張 card = 一個 account 嘅完整真相。 | 已有：header（ChannelIcon、platform、account · accountType、`AnimatedBadge` 用 `channelBadge()`）、attention Alert + Reconnect、`CapabilityChips`（HoverCard / Popover evidence）、meta 行、activity link、Re-verify / History / Disconnect。要改：(1) Re-verify 成功字眼 —— backend 未寫 snapshot 前，read_verified 只閃『Token still valid』，toast 用人話（唔好 `Verification: read verified`）；backend step 1 落地後先用『Verified』並即時反映新 verifiedAt。(2) Header 用 `pictureDigest` 顯示 account avatar（`api` picture endpoint 已有），冇就用 ChannelIcon。(3) Meta 行『Evidence: live provider / synthetic』改人話『Checked with {platform}』/『Sample data』。(4) Reconnect 固定請求 publish（provider 有提供時），唔用 level 最高嗰項，直至 additive grant 落地。(5) Customer-disconnected card：badge『Disconnected』、actions 只留 Reconnect / History，並提供『Remove from list』（要 backend 支援，見 technical_requirements）。 | needs-attention：inset amber border + banner；expiring < 7 日：badge amber、meta amber；verifying：StatefulButton loading；disconnect 後 exit 150ms opacity + translateY（快過 180ms 進入）；reduced-motion 直接切換。 |
| Connect sheet | 平台 → capability → 權限解釋 → 去 provider，一個 surface 完成。 | `connect-sheet.tsx`（已有）。要改：當所選 platform 已經有 connected account，而 additive grant 未落地時，非 publish 選項旁邊加一句 reminder『Adding this now replaces what this account already has; publishing may drop to Assisted until you reconnect for publishing.』（提示，唔 disable —— 但 Reconnect mode 預設 publish）。Additive 落地後刪走呢句。 | start 出錯（400 capability、409 provider 唔提供、429 throttle、503 冇 https base URL）：sheet 內 `Alert destructive` 顯示 API message，唔關 sheet；providers 為空：honest note；canManage false：唔開。 |
| Connect return | OAuth 返嚟即刻返 Channels，新 card 有一次真實成功回饋。 | 已有：成功 `router.replace('/app/channels?connected=<id>')`、missingScopes toast、expected reconnect 比對（sessionStorage）、scrollIntoView + SuccessCheck 一次。要改：`OAuthComplete.connectionId` 入 type 並刪 cast；session 過期時登入後要保留 provider/state/code query 返到呢頁。 | denied / expired（409）/ 404 mismatch：留喺 return 頁顯示 Alert + 『Back to Channels』；成功：唔停留。 |
| Connect (provider tiles) | 講清楚呢個 deployment 而家接到咩、接到咩 level。 | 已有 `ProviderTile`：CapabilityBadge（productionReviewed ? 'Direct publishing' : 'Assisted · review pending'）、一句解釋、可請求 capability chips、`Connect` / `Connect another account`。 | providers 為空：honest note（已有）；load 出錯：『Available connections could not be loaded.』；canManage false：冇掣。 |
| Desktop companion | 誠實交代冇 API 嘅平台，同埋而家未有得用。 | 已有 Collapsible + `HoverLiftGroup` chips link marketing `/channels/[slug]`，`CapabilityBadge level='local' label='Local · not available yet'`。唔顯示任何 installed / detected 狀態。 | 有 connected account 時預設收埋；冇時展開；`?filter=local` 時呢個 section 隱藏（內容已喺 tab 顯示）。 |

- **Empty state**：已有 `Empty`（`data-tour=channels-empty`）：icon `Icons.broadcast`，『No accounts connected』，『You can draft and export without connecting anything. Connect an account when you want previews, scheduling, analytics or comments for it — each capability is verified on its own.』；canManage 時 `Connect an account`，否則『Ask someone who can manage connections in this workspace』。下面即刻係 provider tiles，唔係死路。
- **Loading**：已有：Suspense fallback 同 `isLoading` 都用 `ChannelsSkeleton`（summary 一條、兩張 card 形、三個 tile 形），header 即刻出；冇『Loading your channels…』文字。History sheet 自己有三條 skeleton。
- **Error**：已有：`Alert variant='destructive'` + API message + Retry（`refetch()`）；出錯時 summary / tabs / cards 唔顯示（唔用 stale 數），provider 區顯示『could not be loaded』，companion 照出。單一動作失敗（verify / disconnect / start）toast + 掣回 idle／sheet 內 Alert。Snapshot 或 usage 單獨失敗：只隱藏依賴佢嘅段（activity、quota、held 計數），唔當 0。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁進入 | route 進入 /app/channels | 只靠 `app/app/template.tsx:13` 嘅 `.t-page-enter`；card list stagger 維持 `min(index,3)*40ms` + 180ms（總長 ≤ 300ms，已合規）。 | transitions.css page slide；`useReducedMotion` | 是 |
| Card 移除／filter 切換 exit | disconnect 成功或 filter 改變令 card 離開 | exit 用 150ms（--duration-quick）opacity + translateY，快過 180ms 進入；而家 code 用同一個 0.18s，要改。Reduced-motion 只 opacity 0ms。 | motion AnimatePresence + transitions.css --duration-quick | 是 |
| Card 狀態 badge | refetch 後 connectionState / expiring 改變 | `AnimatedBadge` `contentKey={connectionState:expiring}`，狀態冇變就唔郁（已有）。 | components/motion/animated-badge.tsx | 是 |
| Re-verify 掣 | 撳掣 → API 回應 | `StatefulButton` idle → loading（真請求）→ success 只喺 verified state（backend 未寫 snapshot 前文字係『Token still valid』）／error『Not verified』；`useFlash` 後回 idle。 | components/motion/button/stateful.tsx + hooks/use-flash.ts | 是 |
| 新連接 card | `?connected=<id>` 而且 id 真係喺 list | scrollIntoView（reduced-motion 用 auto）+ `SuccessCheck` 一次，清 param，reload 唔重播（已有）。 | ui/success-check.tsx | 是 |
| Filter tabs / 計數 | 撳 tab；真數改變 | pill indicator 滑動；`DigitSwap` 逐位滾動（已有）。 | components/motion/tabs.tsx、digit-swap.tsx | 是 |
| Capability chip 說明 | hover 80ms / focus；touch 撳 | HoverCard 開 80ms delay、收 100ms（已有）；Popover 用 dropdown token 開 250ms 收 150ms。 | ui/hover-card.tsx、ui/popover.tsx | 是 |
| Connect / History sheet | 撳 + Connect / Reconnect / History | Panel 開 400ms 收 350ms；手機由底升起。 | ui/sheet.tsx | 是 |
| Disconnect 確認 | 撳 Disconnect | `AlertDialog` 開 250ms 收 150ms。 | ui/alert-dialog.tsx | 是 |
| Companion chips | hover / focus | 被 hover chip 升起，鄰居跟住（已有）。 | ui/hover-lift-group.tsx | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{id}/channels 回 channels + providers | api | 有 | src/postriff_phase2/hosted_app.py:411-414 → oauth.py:191-201；types.ts:445-464；hooks.ts:49 | S |
| 2 | OAuth start / public callback / authenticated complete（PKCE、single use、same member） | api | 有 | hosted_app.py:315-325, 415-420；oauth.py:79-99, 101, 108-152；forwarder.tsx；connect-return.tsx | S |
| 3 | Channels 頁前端重寫（summary、pill tabs ?filter=、attention 排序、CapabilityChips、ChannelCard、ConnectSheet、History sheet、?connected= 高亮、companion Collapsible、data-tour ids） | frontend | 有 | Working tree 未 commit：web/src/features/channels/{channels-view,channel-card,capability-chips,connect-sheet,channel-history-sheet,channels-summary,connect-return}.tsx；web/src/lib/channels/{state,capabilities,connect-expect}.ts。要確認 owner 並按 path commit。 | S |
| 4 | Verify 寫返 snapshot（verifiedAt、identityVerified、revoked／expiresAt），令 connectionState 同 displayState 反映 Re-verify | backend | 冇 | oauth.py:222-245 只 audit；hosted.py:256-270 upsert_verified_channel 只喺 complete 用；冇 mark_channel_verified | M |
| 5 | Hosted live channel 唔再因 verifiedAt+3600 變『Finish setup』（只對 evidenceSource=='synthetic' 生效，live 改睇 revoked / expiresAt / capability rows） | backend | 冇 | store.py:82（channel_state）、:292、:350、:425；tests/test_postriff_phase2.py:149；tests/phase2/postgres_channels.py:220 用 clock-3600 | M |
| 6 | Additive capability grant：merge 現有 pr_channel_capabilities（取較高 level）、union scopes，capability_verified 睇 merge 後 publish level | backend | 冇 | oauth.py:145-150；Threads exchange scopes=None（providers.py:133），IG 靠 permissions（:160） | M |
| 7 | OAuthComplete.connectionId 入 TS type；刪 connect-return 同 channels-view 嘅 cast（Manifest.channelId 已在 type） | data | 冇 | types.ts:477-485 冇 connectionId（API oauth.py:152 有）；types.ts:57 已有 channelId?，但 channels-view.tsx activityByChannel 仲 cast | S |
| 8 | Profile / Overview / Billing / Getting started 遷移去 lib/channels/state.ts（channelBadge、needsReconnect、isConnected、attentionSentence） | frontend | 冇 | profile-model.ts:62-78 自己一套；overview-view.tsx:30, 199 raw state 字串；billing-view.tsx:106 同 getting-started.tsx:30 用 channels.length | S |
| 9 | Per-channel audit history | frontend | 有 | channel-history-sheet.tsx；hosted.py:929-931 LIMIT 200（已標明）；useAudit hooks.ts:74 | S |
| 10 | Backend 明確 disconnected 標記（snapshot channel disconnectedAt 或 connection_state 回 'disconnected'）＋可選『remove from list』 | backend | 冇 | store.py:273 只設 revoked=True；state.ts 靠 evidence 字串 'Disconnected by the customer.'（oauth.py:262）判斷 | S |
| 11 | Plan quota：UI N of M（已有）；backend 喺 complete 時只對新 connection_id 超額回 402，reconnect 同一 account 永遠放行 | backend | 冇 | channels-summary.tsx 已顯示；oauth.py:79-99 / 108-152 冇 entitlement 檢查；connection_id 喺 complete 先知（oauth.py:138） | S |
| 12 | Reconnect = 同 provider 再 oauthStart（冇新 endpoint），platform→provider 由 providers[].platform | frontend | 有 | channel-card.tsx reconnect()；connect-sheet.tsx reconnect mode；client.ts:168-169；connection_id sha256(provider:account) oauth.py:138 | S |
| 13 | Queue 支援 ?channel=<id> filter | frontend | 冇 | queue-view.tsx 冇 useSearchParams；channel-card.tsx 已 link 去 /app/queue?channel= | S |
| 14 | 真 RBAC：useWorkspaceAccess() 由 snapshot.membership 推算 | frontend | 冇 | access.tsx:37-43 STUB；types.ts:194 snapshot membership?；API 已 enforce（permissions.py:21，oauth.py:89） | M |
| 15 | Motion 元件同 tokens | frontend | 有 | components/motion/{animated-badge,digit-swap,tabs,radio}.tsx、motion/button/stateful.tsx；ui/{hover-lift-group,success-check,sheet,hover-card,collapsible,popover,alert-dialog}.tsx；transitions.css:22-25, 63-66；lib/hooks/use-hover-capable.ts | S |
| 16 | Onboarding tour（channels-tips + welcome channels stop） | frontend | 有 | web/src/features/onboarding/tours.ts（untracked）PAGE_TOURS 'channels-tips'；tour-overlay.tsx、store.ts、help-menu.tsx | S |
| 17 | Provider registry + production_reviewed（env 驅動） | infra | 有 | providers.py:174-181；scripts/postriff_dev_hosted.py:102, 165 | S |
| 18 | 移除 channel language gate + per-channel 語言記憶（channelLocales） | backend | 冇 | store.py:359 仍有 gate、oauth.py:148 硬寫 English；languages plan §10 決定 1 已決定移除（docs/postriff-worldwide-languages-plan.md:466），§4.3 channelLocales（:179），決定 2 未決（:480-482） | M |
| 19 | Desktop companion 真實狀態 | infra | 冇 | 冇 companion endpoint；marketing 頁寫 coming with the companion release | L |

## 3. Features

### P0

- **Re-verify 寫返真狀態 + hosted 一小時規則修正（backend）**：唔改嘅話 hosted OAuth channel 連接一個鐘後 schedule / approve / claim 全部拒絕（store.py:82, 292, 350, 425），而 card 仲會閃『Verified』—— 核心動作靜靜哋壞，UI 又講假話。（depends on：oauth.py verify、hosted.py 新 command、store.py channel_state、tests）
- **Additive capability grant + 過渡期 reminder**：Working tree 嘅 Connect sheet 已經俾人為已連接平台請求 analytics / comments / reply，一撳就將 Direct publish 打回 Assisted（oauth.py:145-150）。Backend merge 前：sheet 加一句 reminder、Reconnect 固定請求 publish；之後先考慮『Add capability』掣。（depends on：backend additive merge）
- **Commit 已做好嘅 Channels 前端（按 path）**：Needs-attention 排序、人話 badge、chips + evidence、Connect sheet、返回高亮、History、summary 已經喺 working tree，但未 commit、屬另一個 session；唔處理就會被 reset 或者重做。（depends on：確認 owning session；只 stage web/src/features/channels/、web/src/lib/channels/、web/src/features/onboarding/ 同相關 types）

### P1

- **全 app 一致嘅 channel 狀態同數字**：Channels summary、Billing meter、Getting started、Overview、Profile 而家用唔同規則計『connected』同標籤，同一個 account 喺唔同頁講法唔同，違反真數據先郁。（depends on：lib/channels/state.ts（已有））
- **Motion 收尾同文案人話化**：Card exit 未快過進入；Re-verify toast 同 Evidence 行仲係 developer 字串（read verified、live provider）。（depends on：無）
- **Per-account activity 接通 Queue ?channel=**：Card 已 link 去 /app/queue?channel=，但 Queue 唔 filter，link 變死路。（depends on：queue-view.tsx 讀 searchParams + manifest.channelId）
- **Plan quota 喺 complete 時只擋新 account**：Channels 頁已顯示 N of M；backend 而家唔擋會超額，但喺 start 擋會連 reconnect 都擋埋，令已排程 post 出唔到（remind, don't block）。（depends on：oauth.complete entitlement check）
- **明確 disconnected 狀態 + remove from list**：而家靠 evidence 字串判斷，改 wording 就壞；disconnect 咗嘅 card 永遠留喺 All 計數。（depends on：store.py channel_disconnect / channels.py connection_state）
- **真 RBAC 遮掣**：STUB 令冇 manage_connections 嘅人見到 Reconnect / Disconnect，撳落先 403。（depends on：access.tsx 由 snapshot.membership 推算）

### P2

- **Card avatar（picture endpoint）**：API 已有 pictureDigest 同 picture route，card header 用返令人一眼認得邊個 account，減少 reconnect 揀錯 account。（depends on：無）
- **Per-channel 語言**：§10 決定 1 已移除 gate（未實作），決定 2（defaults 存邊）未決；Channels card 可能係設定位，但要等 Stage 2 同決定 2。（depends on：docs/postriff-worldwide-languages-plan.md §10 決定 2；store.py:359 gate 移除）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明白三件事：(1) 唔接任何 account 都可以 draft（empty state 第一句）；(2) 每個 account 唔係一個『Connected ✓』，而係每項 capability 各自有 Direct / Assisted / Unsupported 同證據（chips + page description『A connected account is not the same as a publishable one.』）；(3) 要處理嘅嘢排最頂並有 Reconnect。教法：description + summary strip + chips 顏色（capability-badge 全 app 統一）+ InfoSidebar。Tour 沿用 `web/src/features/onboarding` 嘅 store 同 help menu（`channels-tips`），唔另起 localStorage 機制；唔自動彈。所有文案通用，唔提任何特定品牌或行業。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="channels-connect"]（已有；冇 canManage 時 fallback [data-tour="channels-summary"]）` | Connect when you need it | You can draft and export without connecting anything. Connect an account when you want previews, scheduling, analytics or comments for it. |
| 2 | `[data-tour="channel-card"]（已有，第一張 card；冇 card 時 [data-tour="channels-empty"]）` | One card per account | Each card is one account on one platform: who it is, what PostRiff has verified, and when access runs out. |
| 3 | `[data-tour="capability-chips"]（已有）` | Capabilities, verified one by one | Green is Direct through the official API after your approval. Amber is Assisted: PostRiff prepares the post and you finish it. Grey is not offered yet. Hover or tap a chip to read the evidence and when it was checked. |
| 4 | `[data-tour="channels-filter"]（已有）` | Problems come first | Expired access, missing permissions and accounts about to expire sort to the top and appear under Needs attention, with a Reconnect button on the card. |
| 5 | `[data-tour="channel-actions"]（已有，但未入 tours.ts，要加）` | Check, review, disconnect | Re-verify asks the provider whether this account's access still works. History lists what happened to the account. Disconnect wipes the stored token. |
| 6 | `[data-tour="companion-section"]（已有；?filter=local 時唔存在，tour 要 skip）` | Platforms without an API | Some platforms offer no publishing API a small studio can use honestly. Those will run through a desktop companion on your own machine. It is not available yet, and this page will say so until it is. |

**Empty state 教咩**：Draft 唔需要連接；連接係為咗 previews / scheduling / analytics / comments，而且每項 capability 各自驗證；下面 provider tiles 即刻顯示呢個 deployment 可以接咩平台、到咩 level（Direct publishing 定 Assisted · review pending）。冇 manage_connections 嘅人見到『Ask someone who can manage connections in this workspace』，唔係一個撳咗會 403 嘅掣。

## 5. Next steps（按次序）

1. **協調：確認邊個 session 擁有 working tree 嘅 Channels 重寫（untracked channels/*.tsx、lib/channels/*、features/onboarding/*），由佢按 path commit；之後所有改動基於嗰個版本，唔好重做 HEAD 版本嘅 spec。**（effort S）  
   檔案：`web/src/features/channels/；web/src/lib/channels/；web/src/features/onboarding/；web/src/lib/api/types.ts`
2. **Backend：`OAuthService.verify` 寫返 snapshot —— 新 command `mark_channel_verified(state, actor, channel_id, result, now)` 更新 verifiedAt / identityVerified / revoked（drift → revoked；token_expired → expiresAt=now）；verify 回傳加 verifiedAt；`store.channel_state` 嘅 verifiedAt+3600 只對 evidenceSource != 'live_provider' 生效。加 unit + postgres tests，更新 tests/test_postriff_phase2.py:149 嘅 fixture 假設。**（effort M）  
   檔案：`src/postriff_phase2/oauth.py:222-245；src/postriff_phase2/hosted.py:256-270（新 method）；src/postriff_phase2/store.py:77-84；tests/test_postriff_channels.py；tests/phase2/postgres_channels.py；tests/test_postriff_phase2.py:149`
3. **Backend：additive grants —— complete() 先 SELECT 現有 capability rows + credential scopes，merge（Direct > Assisted > Bridge > Unsupported）、union scopes，capability_verified 用 merge 後 publish level。落地前前端過渡：connect-sheet 對已連接平台嘅非 publish 選項加 reminder；`reconnectCapability()` 改為 provider 有 publish 就請求 publish。**（effort M）  
   檔案：`src/postriff_phase2/oauth.py:108-152, 174-189；src/postriff_phase2/hosted.py:256-270；tests/phase2/postgres_channels.py；web/src/features/channels/connect-sheet.tsx；web/src/lib/channels/state.ts`
4. **Web 誠實修正：Re-verify 成功字眼改『Token still valid』（step 2 落地前）、toast 人話化；Evidence 行改人話；card exit 150ms；`OAuthComplete.connectionId` 入 type 並刪 connect-return / channels-view 嘅 cast 同過時註解。**（effort S）  
   檔案：`web/src/features/channels/channel-card.tsx；web/src/features/channels/channels-view.tsx；web/src/features/channels/connect-return.tsx；web/src/lib/api/types.ts:477-485`
5. **Web：Profile、Overview、Billing、Getting started 改用 lib/channels/state.ts（channelBadge、needsReconnect、isConnected、attentionSentence），刪 profile-model.ts 重複實作同 overview NEEDS_RECONNECT。**（effort S）  
   檔案：`web/src/features/account/profile-model.ts:59-80；web/src/features/account/profile-view.tsx；web/src/features/overview/overview-view.tsx:30, 193-204；web/src/features/billing/billing-view.tsx:106；web/src/features/overview/getting-started.tsx:30`
6. **Web：Queue 讀 `?channel=<id>`（用 manifest.channelId）filter jobs，顯示可清除嘅 filter chip。**（effort S）  
   檔案：`web/src/features/queue/queue-view.tsx`
7. **Backend：明確 disconnected 標記（snapshot channel disconnectedAt，connection_state 回 'disconnected'），state.ts 改讀呢個欄位而唔係 evidence 字串；可選 remove-from-list mutate。**（effort S）  
   檔案：`src/postriff_phase2/store.py:272-273；src/postriff_phase2/channels.py:33-59；web/src/lib/channels/state.ts；web/src/lib/api/types.ts`
8. **Backend：oauth.complete 喺 connection_id 係新（唔喺 snapshot configured 且未 disconnected）而且已到 connectedAccounts 上限時回 402 `{upgradePath:'/app/account/billing'}` 並 audit `oauth.blocked_quota`；reconnect 永遠放行。Return 頁顯示 upgrade CTA。**（effort S）  
   檔案：`src/postriff_phase2/oauth.py:108-152；src/postriff_phase2/billing.py:40-50；tests/test_postriff_billing.py；web/src/features/channels/connect-return.tsx`
9. **Web：`useWorkspaceAccess()` 由 snapshot.membership 推算 role / permissions（包括 can_manage_connections flag），Channels canManage 即時生效；文案改『Ask someone who can manage connections in this workspace』。**（effort M）  
   檔案：`web/src/lib/auth/access.tsx:37-63；web/src/lib/workspace/provider.tsx；web/src/features/channels/channels-view.tsx`
10. **Tour：tours.ts channels-tips 加 channel-actions step（文案唔提 Add capability），companion step 喺 ?filter=local 時 skip。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts`
11. **驗證：dev harness（web :3100）連 Threads，等超過一小時（或調 clock）確認 schedule 仍 Ready；為 analytics 做第二次 OAuth 確認 publish 唔降級；375 / 768 / 1440、light / dark、prefers-reduced-motion、keyboard（chips focus 開 HoverCard、tabs 方向鍵）、touch Popover；唔撳 approve / schedule / send（harness Threads 係 live）；API restart 後 re-seed。**（effort S）  
   檔案：`scripts/postriff_dev_hosted.py；.claude/launch.json`
12. **之後（languages Stage 2 + §10 決定 2）：移除 store.py:359 gate，card 加 per-channel 語言 chip 寫 channelLocales。**（effort M）  
   檔案：`src/postriff_phase2/store.py:359；src/postriff_phase2/oauth.py:148；web/src/features/channels/channel-card.tsx`

## Risks

- Hosted OAuth channel 連接一小時後靜靜哋排唔到程（store.py:82, 292, 350, 425）；Re-verify 救唔返（oauth.py:222-245）而 card 仲閃『Verified』—— step 2 未落之前 UI 唔可以用『Verified』。
- 非 additive grant 已經喺 working tree 撳得到：Connect sheet 為已連接平台提供 analytics / comments / reply，會覆寫 matrix 同 scopes（oauth.py:145-150），Direct publish 變 Assisted；reconnectCapability() 亦可能丟 publish。
- Working tree 嘅前端重寫未 commit、屬另一個 session；shared tree 曾經被 reset 抹走未 commit 嘅改動（memory），要盡快由 owner 按 path commit。
- Production providers 未過審批時全部 Assisted；dev harness（reviewed=True）同 production 要分開測，設計唔可以假設 Direct happy path。
- Reconnect 時喺 provider 揀咗另一個 account → 新 connection_id（oauth.py:138）多一張 card、舊 card 仍然壞；expected-reconnect 靠 sessionStorage，private mode 會 skip 比對。
- Audit 只回最新 200 條 workspace events（hosted.py:931），History 對舊 account 可能唔完整（已標明）。
- `useWorkspaceAccess()` 仍係 STUB（access.tsx:37-43），冇權限嘅人見到 manage 掣、撳落先 403。
- Disconnected 判斷靠 evidence 字串（state.ts ↔ oauth.py:262），backend 改 wording 就會將 disconnect 咗嘅 account 當成 Needs reconnect。
- Quota 如果喺 start 擋，會擋埋 reconnect 令已排程 post 出唔到；只可以喺 complete 對新 account 擋。
- Token 會唔會 refresh 由 provider 決定（refresh_supported，oauth.py:142）；LinkedIn 冇回 refresh_token 時到期要重新授權，Expiring soon 提示要夠顯眼。
- Language gate（store.py:359）仲喺度：OAuth channel 永遠 English（oauth.py:148），非英文 draft 排唔到去真 account，直至 languages Stage 2。
- Companion 未 ship：任何 installed / detected 顯示都係假。
- UI copy 全部硬寫英文，冇 UI i18n；文案集中喺 lib/channels/capabilities.ts 同 state.ts，日後抽出較易。

## 覆核記錄

- 改正：status_now 描述嘅 UI（三個 section、raw connectionState 字串、六行 capability table、Select + Dialog、50ms stagger）同 channels-view.tsx:325-434 等 line refs 係而家嘅樣 → status_now 要分開寫 HEAD（已 commit）同 working tree（未 commit、屬另一個 session），並用 working tree 行號。
- 改正：api.channels client.ts:162；oauthComplete 165-170；verifyChannel 171-175；audit 242 → 更新行號。
- 改正：hosted_app.py 路由：channels 412-415、start 416-418、complete 419-421、verify 422-424、disconnect 425-427、/api/me/channels 363-364、callback 316-325 → 更新行號，加 GET /channels/{id}/picture。
- 改正：oauth.py 行號：start 77-95、https 71-74、callback 98-103、complete 106-149、channels 169-178、verify 199-220、disconnect 222-245、language 146、connection_id 136、capability upsert 142-144、capability_verified 148 → 更新行號。
- 改正：Capability grant 唔係 additive；Threads/IG exchange 唔回 scope 列表（providers.py:132, 159） → 改成『Threads exchange scopes=None；IG 靠 short-lived response 嘅 permissions，冇就 None』。
- 改正：hosted.py upsert_verified_channel 242-257；my_channels 564-590；audit 863-866 最新 200 條 → 更新行號。
- 改正：LinkedIn 冇 refresh token，每 60 日要重新授權（providers.py:107） → 改寫：『如果 LinkedIn 冇回 refresh_token，refresh_supported=false，到期就要重新授權』，唔好寫死 60 日。
- 改正：manage_connections = owner / admin → 文案改做『Ask someone who can manage connections in this workspace』。
- 改正：exists:false —— 共用 channel state model（要抽去 web/src/lib/channels/state.ts） → 改做 exists:true（Channels 頁），另開一項『Profile / Overview / Billing / Getting started 遷移去 state.ts』exists:false。
- 改正：exists:false —— Manifest.channelId 未入 TS type（types.ts:53-67） → 改 exists:true；next step 只係刪 cast 同註解。
- 改正：exists:false —— Connect return 成功後 redirect 返 /app/channels?connected=<id> 並高亮；OAuthComplete type 冇 connectionId → Redirect 改 exists:true；只保留『OAuthComplete.connectionId 入 type』exists:false。
- 改正：Card stagger 50ms / 280ms 超出 motion 規則 → 改做：stagger 已合規；exit 要改 150ms（--duration-quick）。
- 改正：Tour：用 localStorage + 『Take a 30-second tour』連結，target 要新加 data-tour → Tour 沿用 onboarding store + help menu；唔好另起 localStorage 機制。
- 改正：Languages plan §10 決定 1（language gate）未拍板；doc 行 158-162、397-402、258-261 → 改寫：gate 已決定移除但未實作（Stage 2）；per-channel locale UI 等決定 2。
- 違反原則（已改）：真數據先郁：Re-verify 喺 result.state=read_verified 時閃『Verified』（channel-card.tsx verify()），但 verify 唔寫 snapshot（oauth.py:222-245），card badge、verifiedAt 同 displayState 都唔會變；連接一個鐘之後 plan-card / schedule 仲係『Finish setup』。未修 backend 前，成功字眼應該係『Token still valid』，並講明未更新 setup 狀態。
- 違反原則（已改）：真數據先郁：同一個『connected accounts』數字三頁三個講法 —— Channels summary 用 channelCounts().connected（排除 customer-disconnected），Billing meter（billing-view.tsx:106）同 Getting started（getting-started.tsx:30）用 channels.length，會計埋已 disconnect 嘅 card。
- 違反原則（已改）：真數據先郁：snapshot 未返或出錯時，heldByChannel 係空 object，Needs attention 計數會靜靜哋少計 held jobs，但照樣顯示一個數字；應該喺 snapshot 未 ready 時標示 held 未計入，或者隱藏 held 相關部分。
- 違反原則（已改）：Motion 規則（motion-system §5 #4）：card exit 用同 enter 一樣嘅 0.18s，冇收快過開；spec 自己寫 150ms 但 code 冇跟。
- 違反原則（已改）：Capability honesty：Connect sheet 同『Connect another account』而家已經為已連接平台提供 Analytics / Comments / Reply 選項，一撳就觸發非 additive 覆寫，將 Direct publish 打回 Assisted（oauth.py:145-150）—— 呢個 bug 唔係『將來加 Add capability 先暴露』，而係 working tree 已經暴露咗。
- 違反原則（已改）：Capability honesty：reconnectCapability() 揀 level 最高嗰項，如果 analytics 係 Direct 而 publish 係 Assisted，Reconnect 會只請求 analytics，覆寫後 publish 變 Unsupported/Assisted。
- 違反原則（已改）：Tour 文案：spec 嘅 channel-actions step 提到『Add capability』，但呢個掣唔存在（亦唔應該喺 additive 落地前存在）；tour 文案唔可以描述未有嘅功能。
- 違反原則（已改）：Remind, don't block：spec 建議 oauth.start 到上限回 402。Start 嗰刻未知係咪 reconnect 同一 account（connection_id 喺 complete 先知，oauth.py:138），咁會擋住修復壞咗嘅 account，令已排程內容出唔到。應該喺 complete 時只擋『新 connection_id』，reconnect 永遠放行。
- 違反原則（已改）：文案準確度：『Ask an owner or admin』忽略咗 can_manage_connections flag（permissions.py:21）。
- 補上遺漏：Working tree 狀態：前端大部分已由另一個 session 做咗但未 commit（untracked 檔案 + channels-view.tsx 大改）。Spec 冇提，next steps 會重做一次，亦會同嗰個 session 撞。要先確認 owner，只按 path stage（memory：shared tree stage by path）。
- 補上遺漏：Disconnect 偵測：state.ts 靠 evidence 字串 'Disconnected by the customer.' 判斷『Disconnected』，因為 store.py:273 只設 revoked=True，API 回 reauthorization_required。改 backend wording 就會靜靜哋壞；應該由 backend 回明確欄位（例如 snapshot channel disconnectedAt，或者 connection_state 回 'disconnected'）。
- 補上遺漏：已 disconnect 嘅 card 永遠留喺 list 同『All』計數（冇 archive / remove），spec 冇講點處理。
- 補上遺漏：i18n：所有 UI copy 喺 component 硬寫英文，repo 冇 UI i18n 框架；languages plan 講嘅係 post 語言，唔係 UI 語言。Spec 應該講明今次唔做 UI 翻譯，文案集中喺 lib/channels/capabilities.ts 方便日後抽出。
- 補上遺漏：RBAC 細節：Channels nav item 冇 access key（nav-config.ts:59-66），所有 member 見到頁面，manage 動作靠 manage_connections；History（audit）所有 member 可讀 —— 要講明呢個係刻意設計。STUB 期間 viewer 撳 manage 掣會收 403 toast。
- 補上遺漏：OAuth return 需要 Suspense / auth：/channels/connect forwarder → /app/channels/connect，如果 session 過期要登入後保留 query，spec 冇講。
- 補上遺漏：Picture endpoint（GET /channels/{id}/picture，hosted_app.py:426；ChannelView.pictureDigest）已存在但 card header 冇用 avatar。
- 補上遺漏：Production 冇任何 provider env 時（providers 空），sheet 同 tiles 嘅 honest note 已有，但 header + Connect 仲會開一個空 sheet；應該 disable 或直接顯示 note。
- 補上遺漏：Dev harness 驗證要避開 live Threads publish（memory）同 API restart 清 dev DB 要 re-seed。
