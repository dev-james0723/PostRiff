# 01 · App shell：sidebar、header、Cmd+K、info sidebar、workspace switcher

> Route：`/app/* (shell)` · Sidebar：Shell · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

Shell 骨架齊全而且讀真數據；主要缺口係 ⌘K 權限過濾會過期、⌘K 同 channel 狀態定義同其他頁唔一致、冇 route-level error／404、mobile 冇 ⌘K 入口。注意：以下大部分檔案係 working tree WIP（見最後一段）。

【Provider 堆疊】`web/src/components/layout/app-shell.tsx:20-51`：AuthProvider → WorkspaceProvider → Suspense → AppGate → PreferencesProvider → KBar → SidebarProvider → skip link（29-34）→ AppSidebar → SidebarInset `id=main-content`（36）→ Header → InfobarProvider(defaultOpen=false) → children + InfoSidebar(side=right)。重要：KBar 喺 SidebarProvider 同 InfobarProvider 外面，KBar 入面用唔到 `useSidebar()`／`useInfobar()`。`web/src/app/app/layout.tsx:11-13` 讀 `sidebar_state` cookie；`web/src/app/app/template.tsx:11-18` 包 `.t-page-enter`（transitions.css:252-256）+ `<TourMount />`。`web/src/lib/preferences.tsx:61` 用 `key={tz|locale}` re-key 成個 subtree：改 time zone 會 remount KBar、Sidebar。

【Gate】`web/src/components/layout/app-gate.tsx:67-145`：loading → ShellSkeleton（14-35，冇數字）；mfa-required → `<MfaChallenge />`（87）；unavailable → Problem + Try again（89-101）；signed-out：dev mode「Enter dev workspace」（104-121），supabase 由 effect redirect（78-82）；workspace error → Retry／Sign out（125-140）。Server-side `web/src/proxy.ts:19-33` 擋 /app/*。冇 `web/src/app/app/error.tsx`：頁面 throw 會跌落 `web/src/app/global-error.tsx`（無 shell、無 globals.css，6-7）。未匹配嘅 /app/xyz 會渲染 root `web/src/app/not-found.tsx`（marketing SiteHeader 版），唔喺 shell 入面。

【Sidebar】`web/src/components/layout/app-sidebar.tsx`：`isActivePath` 43-46；`activeGroupLabel` 49-56；`NavGroupSection` 63-95（Base UI Collapsible + `.t-nav-panel`，transitions.css:579）；折疊狀態 `web/src/hooks/use-nav-groups.ts` localStorage `postriff-nav-groups`；`NavCount` 102-114（`.t-badge`，transitions.css:342）；唯一 count 係 `/app/queue` needs_review（128-130，讀 snapshot）；footer account dropdown 192-247（Profile、owner-only Usage & plan 221-226、Privacy & data、Sign out）。`web/src/components/ui/sidebar.tsx` 冇 `<nav>`；`SidebarMenuBadge`（563）喺 icon rail `group-data-[collapsible=icon]:hidden`，所以 rail 模式睇唔到 count。Mobile（<768，`web/src/hooks/use-mobile.ts:3`）變 Sheet 18rem（sidebar.tsx:27, 175-197，`.t-panel`）。⌘B（sidebar.tsx:29, 94-99）冇 input／contenteditable guard；`web/src/components/themes/theme-mode-toggle.tsx:36-50` 已有 guard 寫法可抄。

【Nav config】`web/src/config/nav-config.ts:10-184` 五組（Create／Distribute／Grow／Workspace／Account），`access` 經 `web/src/hooks/use-nav.ts:18-54` + `web/src/lib/auth/access.tsx:69-92` 過濾。Bug：Home（18）同 Channels（66）都係 `['h','h']`。`web/src/lib/workspace/provider.tsx:145-154` access `capabilities` 永遠 `[]`；`plan` 由 usage 讀，未返／失敗 default `'trial'`（68-70, 137-143），但 `WorkspaceListItem.plan` 已經有真值冇用到。

【Header】`web/src/components/layout/header.tsx:17-52`：sticky、backdrop-blur、h-16／md:h-14；SidebarTrigger（22）、Breadcrumbs（24，`web/src/components/breadcrumbs.tsx:24,29` 已經 <md 只顯示最後一級）、LiveIsland `@container/island` track（29-33，<md 隱藏，<11rem 隱藏）、Create → `/app/ideas?new=1`（35-40，gated edit；`web/src/features/ideas/ideas-view.tsx:99` 處理）、SearchInput（41-43，<md 隱藏；`web/src/components/search-input.tsx` 冇 compact 模式）、HelpMenu（44；`web/src/features/onboarding/help-menu.tsx:27` `data-tour="help"`，入面已有 Take the tour／Tips for page／Jump to a page ⌘K／Reset tips）、ThemeModeToggle（45）、ThemeSelector（<sm 隱藏）。Mobile 開 ⌘K 只剩 Help menu「Jump to a page」。Breadcrumbs：`web/src/hooks/use-breadcrumbs.tsx`，`GROUP_LANDING` 40-43 只有 workspace／account；`/app/agent/<id>` 產生「Chat」crumb 指去 `/app/agent`，但 `web/src/app/app/agent/` 只有 `[conversationId]` → dead link。

【Live Island】`web/src/components/layout/live-island.tsx`：`readStatus` 98-120（PUBLISHING／WAITING／DONE set 23-25）；`toneOf` 122-128；`snapshot.data` 冇就 `return null`（322，error 同 loading 一樣消失，分唔到「冇嘢」同「讀唔到」）；30s tick（30, 212）；「Published on …」只喺 job 轉 DONE 先播（227）。`web/src/lib/api/hooks.ts:39-42` `useSnapshot` 冇 `refetchInterval`（web/src 零結果），`web/src/lib/query-client.ts:7` staleTime 60s → publishing 中 island 唔會自己更新。

【Cmd+K】`web/src/components/kbar/index.tsx`（134 行）：nav actions 13-65 經 `KBarProvider actions` prop（section 'Navigation'，subtitle「Go to X」）；`useHelpActions` 70-99 用 `useRegisterActions` 註冊 'Help' section（Take the tour、Tips for {page}）；`KBarComponent` 101-134：positioner `z-99999`（108）、animator max-w 600（109）、results 固定 `h-[400px]`（113）、footer 鍵位提示。`use-theme-switching.tsx:20-49` 加 `t t`／`d d`；`render-result.tsx:7-13`「No results found.」。kbar `^0.1.0-beta.48`（web/package.json:41）：`node_modules/kbar/lib/useStore.js:44-54` 嘅 `options` 同 `actions` prop 只喺 mount 讀一次（default enterMs 200／exitMs 100）→ **切 workspace 去 viewer 後 ⌘K 仍然列 Ideas／Members／API**（nav 過濾過期，RBAC UX bug）。`shouldRejectKeystrokes`（utils.js:126）略過 input 內打字；KBarAnimator 會 animate height（KBarAnimator.js:109,133），冇 reduced-motion 處理。冇 workspace switch、冇 records。

【Info sidebar】`web/src/components/layout/info-sidebar.tsx:19-31` fallback 係 'Help'（Take the tour、Jump anywhere ⌘K），文案誠實、冇 dead link（WIP 改動）。`web/src/components/ui/infobar.tsx:24-27` 闊 22rem；⌘I（128-138）冇 input guard；140-155 轉頁清 content + 收埋；mobile 用 Sheet。`web/src/components/layout/page-container.tsx:12-20, 78` 冇 heading 嘅頁用 `PublishInfo`；`web/src/components/ui/info-button.tsx:28-30` mount 時 setContent。有 infoContent：home、ideas、calendar、pipeline、library、channels、queue、analytics、inbox、overview、members、audit、memory、profile、privacy、models、billing。冇：`web/src/features/workspace/roles-view.tsx`、`web/src/features/workspace/brand-view.tsx`、`web/src/features/account/notifications-view.tsx`、`web/src/features/account/api-view.tsx`、`web/src/features/agent/conversation-view.tsx`。

【Workspace switcher】`web/src/components/layout/workspace-switcher.tsx:23-104`：名稱讀 `snapshot.data?.state.workspace?.name || 'My workspace'`（27），但 `GET /api/workspaces` 已返 `name`／`plan`／`trialPlan`／`owner`／`memberCounts`（`web/src/lib/api/types.ts:27-40`；`src/postriff_phase2/hosted.py:60-69` `workspace_summary`、549-555），非 active 項先用 `item.name`（85）；role label（53, 87）；footer「You join other workspaces by invitation.」（95-97）。冇 plan、冇 pending invitations（`useMyInvitations` 只喺 `web/src/features/account/profile-view.tsx:434-470` `PendingInvitations`）、冇 leave（`POST …/leave` hosted_app.py:474、hosted.py:557-567 owner 409、client.ts:116）。`provider.tsx:118-129` `switchTo` 唔檢查 route；PageContainer `access` fallback 只有 members-view:228、roles-view:155、billing-view:136 用，ideas／brand／memory／models／api 冇 → viewer 切入去會留喺 edit-only 頁。

【已有可重用嘅 attention 邏輯】`web/src/features/overview/attention.ts`（untracked）`deriveAttention({snapshot, channels, usage, now})`：error → `unavailable`，唔當 0；`web/src/lib/channels/state.ts:73` `needsAttention(channel)`、:93 `attentionSentence`、:175 `isConnected`（按 connectionState + expiringSoon）。同一個「待批」數仲散喺 live-island.tsx:98-120、home-view.tsx:110、app-sidebar.tsx:128-130、use-tour-context.ts:25；home-view.tsx:118-121 仲用 snapshot displayState 判斷 channel。

【Onboarding】`web/src/features/onboarding/tours.ts:53-154` welcome tour 十步（composer→chips→quick-starts→channels→queue→calendar→brand→memory→overview→help），shell 只有 `[data-tour="help"]`（145-152）；`tour-mount.tsx:31` 排除 `/app/agent/`；progress 存 localStorage（store.ts:45,59），註解 10-12 預留 `PATCH /api/me` onboarding seam；`/api/me`（hosted.py:570-590）冇 onboarding 欄位。

【Backend routes（hosted_app.py）】存在：`GET /api/catalog` 283、`POST /api/auth/logout` 347、`GET|PATCH /api/me` 358/360、`GET /api/me/invitations` 366 + `POST /api/me/invitations/{id}/accept|decline` 374、`GET /api/workspaces` 368、`GET …/usage` 389（任何 member 可讀，hosted.py:316-322）、`GET …/channels` 413、`GET /api/workspaces/{id}` snapshot 461、`GET …/members` 463、`POST …/leave` 474。缺：`POST /api/workspaces`（bootstrap hosted.py:509 只建第一個）、`PATCH /api/workspaces/{id}`、`GET /api/me/notifications`（`pr_notifications` hosted.py:403-435 只 dedupe email）、search endpoint、`/api/me` onboarding 欄位。

【Working tree】git status：M `app/app/template.tsx`、`kbar/index.tsx`、`layout/{app-gate,app-shell,app-sidebar,header,info-sidebar,page-container,workspace-switcher}.tsx`、`lib/api/{client,hooks,types}.ts`、`lib/auth/session.tsx`、`lib/workspace/provider.tsx`、`lib/time.ts`；?? 整個 `features/onboarding/`、`lib/channels/`、`lib/preferences.tsx`、`features/overview/attention.ts`。另一個 session 同時編輯 web/src。

## 1. Design specification（最新版）

**目的**：Shell 係每一頁嘅底：一眼知道自己喺邊個 workspace、有咩等緊自己、下一步去邊。Shell 上所有數字（待批、channel 要處理、publishing 中、邀請數、plan）直接讀 `/api/workspaces`／snapshot／`/channels`／`/usage`／`/me/invitations`；未返就唔顯示，讀唔到就講「unavailable」，永遠唔用 0 或 placeholder 頂。Shell 本身唔阻止任何創作：gate 只擋未登入同 workspace 未載入，其餘一律 remind。

**Layout**：沿用 SidebarProvider + SidebarInset + InfobarProvider（唔另起 grid）：左 sidebar `16rem`（icon rail `3rem`，mobile Sheet `18rem`）｜main（header sticky h-16／md:h-14 + page）｜右 info sidebar `22rem`（offcanvas，預設收，mobile Sheet）。

**Header（左→右）**：SidebarTrigger ｜ Breadcrumbs（<md 只顯示最後一級——現有）｜ Live Island track（flex-1，`@container`，≥11rem 先出 pill）｜ Create（primary，gated edit；<sm 只有 icon——現有）｜ Search（≥md：outline「Search… ⌘K」；<md：新增 icon button）｜ Help ｜ Theme toggle ｜ Theme selector（≥sm）。

**Sidebar**：header = Workspace switcher（size lg）；content = `<nav aria-label="Workspace">` 包五組 NavGroupSection，每行 icon + label + 可選 NavCount；footer = account menu。Mobile Sheet 版本喺 switcher 下面多一行 Live Island compact pill。

**Primary action**：Create（header）→ `/app/ideas?new=1`；⌘K「New draft」同一目標；sidebar 唔重複「+」。Channel 健康狀況以 Channels 行 count 表達，唔喺 shell 出任何「Connected」字眼。

**Info sidebar 用途**：頁面用 `PageContainer infoContent` 講「呢頁點解咁做」（capability 解釋、quota 規則）。冇 content 嘅頁保留現有誠實 Help fallback（tour + ⌘K），唔加 toast。

**Responsive**：
- 375px：sidebar = Sheet 18rem（`.t-panel` 左入）；header 顯示 trigger、當前頁名、Create icon、Search icon、Help、Theme toggle；Live Island 搬去 Sheet 頂；info = Sheet 右入（由 Heading InfoButton 開）；⌘K palette 貼邊、`pt-[14vh]`、results `max-h-[min(400px,60dvh)]`；所有 Kbd／⌘ 提示喺 <md 隱藏（touch 冇鍵盤）。
- 768px：sidebar cookie 決定展開或 icon rail；rail 模式 hover tooltip（現有）+ count 細點；Live Island 視乎 track 闊度出現。
- 1440px：sidebar 16rem + page + info 22rem 同時可見；Live Island 喺 track 置中。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Workspace switcher（sidebar header） | 一眼知道喺邊個 workspace、自己咩 role、plan；切換、接受邀請、離開。 | Trigger：workspace icon + active `WorkspaceListItem.name`（`useWorkspace().workspaces`，唔再讀 snapshot）+ 第二行 role label；`data-tour="workspace-switcher"`。Dropdown（`.t-dropdown`，align start，desktop side=right）：① 「Workspaces」list：每項 name、role、active tick；active 項加 plan pill（AnimatedBadge size sm）——文字讀 `WorkspaceListItem.plan`／`trialPlan`（真值，唔使等 usage）；只有 owner 而且 `useUsage().data.subscription?.status === 'trial'` 並且確認咗 trial 到期欄位語義後，先加「N days left」；未確認前唔顯示天數。② 「Invitations」group：只喺 `useMyInvitations().data.available && invitations.length > 0` 出現；每項 workspaceName、role、invitedBy.displayName、Accept／Decline（抽出 profile-view.tsx:434-470 `PendingInvitations` 共用），Accept 成功 `refresh(workspaceId)` 並切過去；query error → 唔出 group（唔顯示 0）。③ Footer：非 owner 見「Leave this workspace…」（AlertDialog 確認，`api.leaveWorkspace` → `refresh()`）；owner 見灰字「Transfer ownership before leaving」；最底「You join other workspaces by invitation.」（冇 create endpoint，唔扮有）。切換：`switchTo(id)` 後用新 membership 行 `routeAllowedIn(access, pathname)`（nav-config access + 未列 route fallback map），唔允許就 `router.replace('/app')` + toast「Switched to {name}. You are {role} here, so {page} is not available.」。 | loading：唔會發生（list 係 gate 條件）。只有一個 workspace 冇邀請：得一項 + footer。error：invitations／usage 失敗各自隱藏自己嗰部分。 |
| Sidebar nav + attention counts | 去邊度 + 邊度真係有嘢等緊你。 | 五組維持 nav-config.ts。NavCount 數字由升格後嘅 `web/src/lib/attention.ts`（由 `features/overview/attention.ts` 搬出並 re-export）供應：Queue = snapshot `reviews.filter(needs_review).length`；Channels = `useChannels().data.channels.filter(c => needsAttention(c)).length`（`lib/channels/state.ts:73`，同 Overview 同一定義），/channels 讀唔到先 fallback snapshot `displayState ∈ {Reconnect, Finish setup}`（attention.ts:46-48）。其餘行冇 count（Inbox 冇 unread 數據，唔扮）。Count 0 → badge 收埋；link `aria-label` 只喺 >0 加「, N waiting for approval」／「, N need attention」。Channels badge 用 amber（同 channels-summary.tsx:62），Queue 用 primary。Channels tooltip 用 `attentionSentence` 第一句，永遠唔講「Connected」。Icon rail：count 變右上 `size-2` 細點（SidebarMenuBadge 喺 rail 被隱藏，要另加元素），tooltip 帶數字。Content 包 `<nav aria-label="Workspace">`。 | snapshot／channels 未返：冇 badge。error：冇 badge（唔係 0）。 |
| Header | 當前位置 + 全局 action + 狀態。 | Breadcrumbs：`GROUP_LANDING` 加 `'/app/agent': '/app'`（Chat crumb 指返 Home）。Create 加 `data-tour="header-create"`。SearchInput 加 `compact` prop：<md 渲染 icon button（aria-label 'Search and commands'），兩個模式都加 `data-tour="search"`。Live Island 維持現有 hover／focus／tap。 | 冇 edit：Create 唔渲染（現有）。API 中途 unavailable：Island 顯示 unavailable pill（見下）；Search／Help 照常。 |
| Live Island（DynamicIsland） | publishing 中／待批／失敗／下一個 post 倒數，真數據。 | 數據新鮮度：`useSnapshot` 加 `refetchInterval: (query) => hasJobsInFlight(query.state.data) ? 15_000 : false`（`hasJobsInFlight` 讀 live-island.tsx 嘅 PUBLISHING set，搬去 lib/attention.ts 共用）。新增 unavailable 狀態：`snapshot.isError && !snapshot.data` → 細 neutral pill「Status unavailable」（唔係 All quiet）。Mobile：`placement='sheet'`，喺 sidebar Sheet 頂渲染 compact pill，tap 展開同一個 details。加 `data-tour="live-island"`。 | quiet：「All quiet」；loading：唔渲染；error 冇舊數據：「Status unavailable」；error 有舊數據：顯示舊數據（TanStack 保留 data）。 |
| Cmd+K palette | 由任何地方去任何地方、做常用動作、切 workspace、跳去等緊你嘅 record。 | **先修 bug**：nav actions 由 `KBarProvider actions` prop 改為 `useRegisterActions(navActions, [navActions])`，令切 workspace／role 後過濾即時生效。Sections：① **Actions**（Priority.HIGH）：New draft → `/app/ideas?new=1`（gate edit）；Connect a channel → `/app/channels?connect=1`（gate manage_connections；需要 channels-view 新增 `connect=1` param 開 connect sheet——`/app/channels/connect` 係 OAuth return 頁，唔可以用）；Toggle sidebar、Show page notes（只喺 content 存在）——呢兩項由新 `<ShellCommandActions />` 喺 InfobarProvider 入面註冊，因為 KBar 喺 SidebarProvider／InfobarProvider 外；Keyboard shortcuts（≥md 先註冊）。② **Help**：維持現有 useHelpActions（Take the tour、Tips for page），唔重複。③ **Navigation**：subtitle 有數據先講真話：Queue「3 waiting for approval」、Channels「1 account needs attention」；冇數據或 error 維持「Go to X」。④ **Workspaces**：每個非 active workspace「Switch to {name}」（subtitle role），perform 用 switcher 同一段 switch + route 檢查。⑤ **Records**（有數據先註冊，穩定 id + useMemo）：Conversations（`useConversations`，非 archived，→ `/app/agent/{id}`）；Drafts waiting for approval（snapshot reviews，gate `approve`，→ `/app/queue`）。⑥ **Theme**：現有 `t t`／`d d`。外觀：`KBarProvider options={{ animations: { enterMs: reduce ? 0 : 250, exitMs: reduce ? 0 : 150 } }}`，`reduce` 喺 KBar mount 前讀 `matchMedia('(prefers-reduced-motion: reduce)')`（options 只讀一次）；results `max-h-[min(400px,60dvh)]`。 | empty query：Actions + Help + Navigation。無 match：「No results for “{query}”」。Records 冇數據／error：section 唔註冊。 |
| Info sidebar | 每頁嘅「點解」同規則說明。 | 保留現有 Help fallback（已誠實）。補齊五個 view 嘅 `infoContent`：roles、brand、notifications、api、conversation；文案一般化（designer／teacher／shop owner／developer 都讀得通），capability 相關內容跟 Direct／Assisted／Unsupported 用語。⌘I handler 加 input／contenteditable guard。開合沿用「轉頁即收」（infobar.tsx:140-155），唔加 localStorage。 | 有 content：InfoButton（Heading 內）+ rail；冇 content：rail + Help fallback；mobile：Sheet 右入，只由 InfoButton 開。 |
| Account menu（sidebar footer） | 個人設定同離開。 | 現有四項 + 「Keyboard shortcuts」（≥md 先顯示，開 dialog）。Sign out 維持 `signOut().then(() => router.replace('/auth/sign-in'))`。 | owner 先見 Usage & plan（現有）。 |
| Gate 同 route boundaries | shell 永遠唔會因為一頁出錯而消失。 | 新增 `web/src/app/app/error.tsx`（'use client'，`Sentry.captureException`，Empty + Retry（`reset()`）+ Go to Home，sidebar／header 保留）；新增 `web/src/app/app/not-found.tsx`（「This page does not exist in this workspace」+ Home link）同 `web/src/app/app/[...slug]/page.tsx`（`notFound()`），令未匹配 /app URL 留喺 shell 入面而唔係跌去 marketing 404。AppGate 四個 Problem 狀態、ShellSkeleton 維持。 | 見 loading／error 欄。 |
| Keyboard shortcuts | 一份真實、唔撞鍵嘅綁定表。 | 全局：⌘K palette；⌘B sidebar；⌘I info panel；⌘⇧D theme（現有）。序列（kbar，input 內自動略過）：`g h` Home、`g o` Overview、`g i` Ideas、`g c` Calendar、`g p` Pipeline、`g l` Library、`g n` Channels、`g q` Queue、`g a` Analytics、`g x` Inbox、`g m` Members、`g b` Usage & plan；`t t`、`d d`。序列只對 access 通過嘅 nav item 註冊（同 nav 一齊 re-register）。⌘B／⌘I 加 target guard（抄 theme-mode-toggle.tsx:36-50）。`?` 開 shortcuts dialog（同樣 guard）。Dialog 由 nav-config `shortcut` 欄 + 固定全局鍵表生成，唔手寫第二份。 | dialog：`ui/dialog`（`.t-modal`），兩欄 grid，<sm 單欄；<md 唔提供入口。 |

- **Empty state**：全新 workspace（冇 voice、channel、draft）：sidebar 冇 count；Live Island「All quiet」；switcher 一個 workspace + plan pill（讀 list 真值）、冇 invitations group；⌘K 冇 Records section；info sidebar 跟頁面或 Help fallback；Welcome dialog（tour-mount.tsx）照常提供 tour，可以 Not now。Shell 唔顯示「Get started」checklist——嗰啲喺 Home NotificationStack 同 Overview getting-started，避免重複。
- **Loading**：Auth／workspace 未 ready：`ShellSkeleton`（app-gate.tsx:14-35，role=status，aria-label 'Loading workspace'，冇數字）。Shell mount 後：switcher 即刻有 name、role、plan（全部嚟自 workspace list，係 gate 條件）；NavCount、Live Island、⌘K Records／subtitle 各自等自己嘅 query，未返就唔渲染（冇 spinner、冇 0）；page 內容由 `PageContainer isLoading` 負責。轉頁：`.t-page-enter` 250ms。
- **Error**：Auth unavailable：Problem「PostRiff is temporarily unavailable」+ Try again（現有）。Workspace load error：Retry／Sign out（現有）。Page render error：新 `app/app/error.tsx`，sidebar／header 保留，內容區 Empty + Retry + Home，Sentry capture。未知 /app URL：shell 內 404。Query 局部失敗：NavCount、invitations group、trial 天數各自隱藏（唔以 0 或「Trial」頂替）；Live Island 冇舊數據時顯示「Status unavailable」；⌘K subtitle 退返「Go to X」，Navigation 照常。Switch 後 route 唔允許：replace 去 `/app`，toast 講明係因為 role。Leave 失敗（例如 owner 409）：toast 顯示 API error 原文。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Sidebar nav group 開合 | 撳 group header | height 由 `--collapsible-panel-height` 過渡，開 250ms／收 150ms，chevron 旋轉；reduced motion 已由 transitions.css:596-608 處理 | .t-nav-panel（transitions.css:579）+ Base UI Collapsible，現有 app-sidebar.tsx:63-95 | 否（純裝飾） |
| NavCount badge（Queue、Channels）+ icon rail 細點 | count 由 0 變 >0 或反向 | 滑入 + pop，歸零時縮走，最後數字留住直至收完 | .t-badge / .t-badge-dot（transitions.css:342-361，reduced motion 615-619），現有 NavCount | 是 |
| Live Island | snapshot 更新、hover／focus／tap、job 轉 published | DynamicIsland spring 展開 details；「Published on …」4s event view；倒數每 30s | components/motion/dynamic-island.tsx + layout/live-island.tsx，只加 refetchInterval 同 unavailable view | 是 |
| Workspace switcher、account menu、help menu | open／close | 由 trigger 角落 scale + fade，開 250ms／收 150ms | .t-dropdown（ui/dropdown-menu.tsx:42 已接） | 否（純裝飾） |
| Plan pill 喺 switcher | plan／status 真正改變（唔包括首次載入） | AnimatedBadge contentKey 轉變時 text roll；首次 mount 直接顯示唔播 | components/motion/animated-badge.tsx（已有 useReducedMotion） | 是 |
| Cmd+K palette | ⌘K／Search button | kbar animator enter 250ms／exit 150ms；reduced motion 時 0ms（KBarAnimator 會 animate height，所以必須 0，唔可以淨係縮短） | kbar options.animations（mount 時讀一次），數值跟 --dropdown-open-dur／--dropdown-close-dur | 否（純裝飾） |
| Cmd+K Navigation subtitle 數字 | snapshot／channels 更新 | 純文字更新，冇 ticker | 無 motion；lib/attention.ts | 是 |
| Mobile sidebar Sheet / info Sheet | trigger／InfoButton | 由所屬邊滑入 100px + cross-blur，開 400ms／收 350ms | .t-panel（transitions.css:215，ui/sheet.tsx:56 已接） | 否（純裝飾） |
| Theme toggle icon | 切換 theme | sun／moon swap + circular reveal | 現有 ThemeModeToggle | 否（純裝飾） |
| Page enter | route change | opacity + 短距離上升，250ms，backwards fill | .t-page-enter（transitions.css:252），app/app/template.tsx | 否（純裝飾） |
| Shortcuts dialog、Leave AlertDialog | `?`／menu item／Leave | scale + fade，開快收更快（跟 modal token） | .t-modal（ui/dialog.tsx:53、ui/alert-dialog.tsx:48 已接） | 否（純裝飾） |
| Tour spotlight 落喺 shell target | welcome tour shell steps | 現有 overlay morph | features/onboarding/tour-overlay.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces 返 name／plan／trialPlan／owner／memberCounts | api | 有 | src/postriff_phase2/hosted_app.py:368 → hosted.py:549-555 + workspace_summary hosted.py:60-69；web/src/lib/api/types.ts:27-40 | S |
| 2 | GET /api/workspaces/{id} snapshot（reviews／jobs／channels.displayState／workspace.name） | api | 有 | hosted_app.py:461；types.ts:144（Phase2State）、:180（workspace.name）；useSnapshot hooks.ts:39-42 | S |
| 3 | GET /api/workspaces/{id}/channels（connectionState，capability-aware）+ needsAttention helper | api | 有 | hosted_app.py:413；useChannels hooks.ts:49-52；web/src/lib/channels/state.ts:73,93,175 | S |
| 4 | GET /api/workspaces/{id}/usage（任何 member 可讀） | api | 有 | hosted_app.py:389；hosted.py:316-322 冇 owner check；Usage types.ts:540-557；useUsage hooks.ts:44-47 | S |
| 5 | Trial 到期日欄位語義（entitlement.resetsAt 係咪 trial end） | data | 冇 | billing-view.tsx:107 假設 resetsAt；billing.py:47 resetsAt 屬 entitlement；lifecycle billing.py:235-246 trial 只返 {status:'trial'}，冇到期日 | S |
| 6 | GET /api/me/invitations + POST /api/me/invitations/{id}/accept\|decline | api | 有 | hosted_app.py:366, 374；hosted.py:839-848（available=false 喺冇 email lookup）；client.ts:125-129；useMyInvitations hooks.ts:122-125 | S |
| 7 | POST /api/workspaces/{id}/leave | api | 有 | hosted_app.py:474；hosted.py:557-567（owner 409）；client.ts:116 | S |
| 8 | POST /api/auth/logout + client signOut | api | 有 | hosted_app.py:347；web/src/lib/auth/session.tsx:212-225 | S |
| 9 | Attention selector（deriveAttention） | frontend | 有 | web/src/features/overview/attention.ts:50 deriveAttention（untracked WIP）；要搬去 web/src/lib/attention.ts 並加 needsReview／hasJobsInFlight／channelsNeedingAction，live-island、home-view、app-sidebar、use-tour-context 改用 | S |
| 10 | ⌘K nav actions 隨 access 重新註冊（修 kbar actions 只讀一次） | frontend | 冇 | kbar/index.tsx:60-64 用 KBarProvider actions prop；node_modules/kbar/lib/useStore.js:48-54 useMemo([]) | S |
| 11 | useSnapshot 條件式 refetchInterval（jobs in flight 15s） | frontend | 冇 | hooks.ts:39-42；web/src grep refetchInterval 零；query-client.ts:7 staleTime 60s | S |
| 12 | Workspace switcher：name 讀 list、plan pill、invitations、leave、切換後 route 檢查 | frontend | 冇 | workspace-switcher.tsx:27 snapshot fallback；provider.tsx:118-129 switchTo 唔檢查 route；冇 pill／invitations／leave UI | M |
| 13 | access.plan fallback 用 WorkspaceListItem.plan | frontend | 冇 | provider.tsx:68-70,143 usage 未返 default 'trial' | S |
| 14 | ⌘K v2：Actions／Workspaces／Records、真話 subtitle、animations + reduced motion、ShellCommandActions（provider 內註冊） | frontend | 冇 | kbar/index.tsx:13-65 nav、70-99 Help；KBarProvider 冇 options；app-shell.tsx:27-41 KBar 喺 Sidebar／Infobar provider 外 | M |
| 15 | Channels 頁 `?connect=1` 開 connect sheet（⌘K Connect a channel 目標） | frontend | 冇 | channels-view.tsx:185-186 只讀 filter／connected；openConnect 喺 265；/app/channels/connect 係 OAuth return（connect/page.tsx） | S |
| 16 | Mobile ⌘K 入口（SearchInput compact） | frontend | 冇 | header.tsx:41-43 `hidden md:flex`；search-input.tsx:6-23 冇 compact | S |
| 17 | Live Island mobile placement + unavailable view | frontend | 冇 | header.tsx:29 track `hidden md:block`；live-island.tsx:322 `if (!snapshot.data) return null` | S |
| 18 | 五個 view 補 infoContent（roles、brand、notifications、api、conversation） | frontend | 冇 | grep -rln infoContent web/src/features 唔包括呢五個檔 | S |
| 19 | Route boundaries：app/app/error.tsx、app/app/not-found.tsx、app/app/[...slug]/page.tsx | frontend | 冇 | web/src/app/app 冇呢三個；root web/src/app/not-found.tsx 係 marketing 版；global-error.tsx:6-7 無 globals.css | S |
| 20 | Breadcrumb dead link 修正（/app/agent） | frontend | 冇 | use-breadcrumbs.tsx:40-43；web/src/app/app/agent/ 只有 [conversationId] | S |
| 21 | Nav shortcut 去重 + `g` 前綴序列 | frontend | 冇 | nav-config.ts:18 同 :66 都係 ['h','h']；kbar utils.js:126 已擋 input | S |
| 22 | ⌘B／⌘I handler 加 input target guard | frontend | 冇 | ui/sidebar.tsx:94-99、ui/infobar.tsx:128-138；範例 theme-mode-toggle.tsx:36-50 | S |
| 23 | Shortcuts dialog（由 nav-config 生成） | frontend | 冇 | help-menu.tsx:30-63 冇此項；ui/kbd.tsx、ui/dialog.tsx 存在 | S |
| 24 | Sidebar `<nav aria-label>` + icon rail count dot | frontend | 冇 | ui/sidebar.tsx 冇 <nav>；SidebarMenuBadge（563）`group-data-[collapsible=icon]:hidden` | S |
| 25 | Shell tour steps + data-tour ids | frontend | 冇 | tours.ts:145-152 只有 help；workspace-switcher.tsx、header.tsx Create、search-input.tsx、live-island.tsx、app-sidebar.tsx 冇 data-tour | S |
| 26 | POST /api/workspaces（建立第二個 workspace） | backend | 冇 | hosted_app.py 冇；bootstrap hosted.py:509 只建首個 | L |
| 27 | PATCH /api/workspaces/{id}（改名） | backend | 冇 | hosted_app.py:458-490 冇 PATCH；grep rename src/postriff_phase2 零 | M |
| 28 | GET /api/me/notifications | backend | 冇 | pr_notifications 只 dedupe email（hosted.py:403-435）；冇 list route | L |
| 29 | /api/me onboarding 欄位 | backend | 冇 | hosted.py:570-590 me() 冇；store.ts:10-12 seam | M |

## 3. Features

### P0

- **⌘K 權限過濾修正 + nav shortcut 去重**：kbar 只喺 mount 讀 actions（useStore.js:48-54），切去 viewer workspace 後 ⌘K 仍然列 Ideas、Members、API——係 RBAC UX bug，比加新功能更急。順手修 Home／Channels 撞 `h h`。
- **共用 attention selector + Channels count + snapshot 新鮮度**：Overview 已經有 capability-aware 嘅 deriveAttention／needsAttention，但 Home、sidebar、island、tour ctx 各自再計一次，而且 Home 用 displayState 字串。升格 attention.ts 做唯一定義，sidebar 加 Channels count，jobs in flight 時 15s refetch，Live Island 先真係 live。（depends on：無）
- **Route boundaries（error.tsx、not-found.tsx、[...slug] catch-all）**：一頁 throw 成個 shell 消失；未知 /app URL 跌去 marketing 404。三個細檔解決。
- **Workspace switcher v2：真名、plan pill、invitations、leave、切換後 route 檢查**：Invitations、leave、RBAC 都已有 API，但 shell 上睇唔到邀請；viewer 切 workspace 會留喺冇 access fallback 嘅 edit-only 頁。Plan 讀 list 真值；trial 天數要等欄位語義確認先出。（depends on：抽出 profile-view PendingInvitations）

### P1

- **Cmd+K v2：Actions、Workspaces、Records、真話 subtitle、mobile 入口**：⌘K 而家基本係 sidebar 鏡像 + Help，mobile 冇直接入口。Actions 要喺正確 provider 層註冊；Records 有數據先註冊並按 permission gate。（depends on：⌘K 權限過濾修正、attention selector、channels `?connect=1`）
- **Mobile：Search icon、Live Island 搬入 Sheet、unavailable pill**：375px 時 publishing 狀態同 palette 都冇入口；snapshot error 時 island 靜靜消失，分唔到冇嘢定讀唔到。（depends on：Cmd+K v2）
- **Keyboard shortcut 系統：`g` 序列、⌘B／⌘I guard、shortcuts dialog**：⌘B／⌘I 喺 contenteditable 會攔走 bold／italic；表由 nav-config 生成先唔會同實際綁定分岔。
- **Info sidebar 補齊五頁**：「點解」欄係 capability honesty 嘅載體（redesign 文件「ⓘ 點解？→ 開右側 InfoSidebar」）；roles、brand、notifications、api、conversation 暫時只見通用 Help。

### P2

- **Shell tour steps（switcher、Create、Live Island、Search、Help）**：Welcome tour 十步冇一步教 shell；用穩定 data-tour id，文案讀 TourCtx 真值。（depends on：data-tour ids；另一 session 正改 features/onboarding（untracked），要協調）
- **Backend：建立／改名 workspace、notification center、onboarding 欄位**：而家冇 endpoint；shell 先誠實講「by invitation」。Notification center 要新事件來源，工程量大，等使用數據證明需要。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明白三件事：①「我喺 {workspace name}，我係 {role}」（switcher 第一二行，讀 workspace list）；②「等緊我嘅嘢喺邊」（Queue／Channels 行 count + Live Island pill，冇嘢就冇 badge、island 講 All quiet）；③「想做嘢撳 Create，想去邊按 ⌘K 或者撳 Search」。Welcome dialog（tour-mount.tsx）提供 tour，可以 Not now。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="workspace-switcher"]（要加喺 workspace-switcher.tsx SidebarMenuButton；fallback：現有 [data-tour="help"]）` | Your workspace | Everything here belongs to this workspace. You are {role} in {workspaceName}. Switch workspaces or accept an invitation from this menu.（role／name 讀 useWorkspace，要加入 TourCtx） |
| 2 | `[data-tour="nav-create"]（要加喺 app-sidebar.tsx NavGroupSection trigger，label==='Create'；icon rail 模式 trigger 係 aria-hidden，fallback 用 sidebar `nav[aria-label="Workspace"]`）` | Make, then distribute | Create holds what you write. Distribute is where your channels live and where every draft waits for approval. A number appears on a row only when something is really waiting. |
| 3 | `[data-tour="header-create"]（要加喺 header.tsx Create link）` | Start from anywhere | Create opens a new draft from any page. Nothing is scheduled or published until you approve the exact text, media and time.（when: ctx.canEdit） |
| 4 | `[data-tour="live-island"]（要加；<md 或 track 太窄時唔存在），fallback [data-tour="search"]` | What is happening right now | This pill shows posts publishing, drafts waiting, recent failures and the next scheduled post, read from your workspace. Right now: {needsReview} waiting for approval.（讀 TourCtx.needsReview；tour 已等 snapshot ready 先開始，use-tour-context.ts:32） |
| 5 | `[data-tour="search"]（要加喺 search-input.tsx，full 同 compact 兩個模式）` | Jump anywhere | Search pages, actions, other workspaces and drafts waiting for you from one box. On a keyboard, press ⌘K (Ctrl+K on Windows).（<md 時唔講 ⌘K） |
| 6 | `[data-tour="help"]（現有 help-menu.tsx:27）` | Come back any time | Replay this tour or open the tips for any page from the help menu.（現有 step，保留喺最後） |

**Empty state 教咩**：新 workspace 嘅 shell 教三樣嘢而唔講一句假話：sidebar 冇 count → 「冇嘢等你」係真；Live Island「All quiet」→ 狀態欄係活嘅；讀唔到時講「Status unavailable」而唔係扮 quiet；switcher 得一個 workspace + 「You join other workspaces by invitation」→ 多人協作點運作。第一步（voice、channel、draft）由 Home NotificationStack 同 Overview getting-started 負責，shell 唔重複。

## 5. Next steps（按次序）

1. **⌘K 權限 + honesty 細修：kbar/index.tsx nav actions 改 useRegisterActions（deps = filtered actions）；nav-config 改 `g` 前綴序列並去重；use-breadcrumbs GROUP_LANDING 加 '/app/agent':'/app'；workspace-switcher 名稱改讀 `useWorkspace().workspaces`；provider access.plan fallback 用 list item plan；⌘B／⌘I 加 target guard；sidebar content 包 `<nav aria-label="Workspace">`。**（effort S）  
   檔案：`web/src/components/kbar/index.tsx, web/src/config/nav-config.ts, web/src/hooks/use-breadcrumbs.tsx, web/src/components/layout/workspace-switcher.tsx, web/src/lib/workspace/provider.tsx, web/src/components/ui/sidebar.tsx, web/src/components/ui/infobar.tsx, web/src/components/layout/app-sidebar.tsx`
2. **升格 attention：將 web/src/features/overview/attention.ts 搬去 web/src/lib/attention.ts（overview 改 import），加 `countNeedsReview(snapshot)`、`countChannelsNeedingAttention(channels, snapshot)`（needsAttention，/channels error 先 fallback snapshot）、`hasJobsInFlight(snapshot)`；live-island.tsx、home-view.tsx、app-sidebar.tsx、use-tour-context.ts 改用；sidebar 加 Channels count（amber）同 icon rail 細點；hooks.ts useSnapshot 加條件式 refetchInterval 15s。先同 overview owner session 協調（檔案 untracked）。**（effort S）  
   檔案：`web/src/lib/attention.ts (moved), web/src/features/overview/attention.ts, web/src/features/overview/overview-view.tsx, web/src/components/layout/live-island.tsx, web/src/features/agent/home-view.tsx, web/src/components/layout/app-sidebar.tsx, web/src/features/onboarding/use-tour-context.ts, web/src/lib/api/hooks.ts`
3. **Route boundaries：`web/src/app/app/error.tsx`（'use client'，Sentry.captureException，Empty + Retry + Home）、`web/src/app/app/not-found.tsx`、`web/src/app/app/[...slug]/page.tsx`（notFound()）。**（effort S）  
   檔案：`web/src/app/app/error.tsx (new), web/src/app/app/not-found.tsx (new), web/src/app/app/[...slug]/page.tsx (new)`
4. **確認 trial 到期語義：讀 src/postriff_phase2/billing.py entitlement／plan terms，確定 `entitlement.resetsAt` 喺 trial 係咪等於 trial 結束；唔係就記錄，switcher 唔顯示天數（billing-view.tsx:107 亦要跟進，另開 task）。**（effort S）  
   檔案：`src/postriff_phase2/billing.py, web/src/features/billing/billing-view.tsx (read only)`
5. **Workspace switcher v2：抽 `PendingInvitations` 去 `web/src/features/account/pending-invitations.tsx`（profile-view 同 switcher 共用）；加 plan pill（list plan／trialPlan；owner + 確認語義先加天數）、Invitations group（available && length>0）、Leave（AlertDialog → api.leaveWorkspace → refresh；owner 唔出）；新增 `web/src/lib/auth/route-access.ts` `routeAllowedIn(access, pathname)`（nav-config access + fallback map：/app/agent/* 需 edit→/app，/app/channels/connect→/app/channels），switch 後唔允許就 replace('/app') + 帶原因 toast。**（effort M）  
   檔案：`web/src/components/layout/workspace-switcher.tsx, web/src/features/account/pending-invitations.tsx (new), web/src/features/account/profile-view.tsx, web/src/lib/auth/route-access.ts (new), web/src/lib/workspace/provider.tsx`
6. **Cmd+K v2：KBarProvider `options.animations`（mount 時讀 matchMedia reduced motion → 0）、results max-h；`use-app-actions.tsx`（New draft gate edit、Connect a channel gate manage_connections → /app/channels?connect=1、Keyboard shortcuts）；`shell-command-actions.tsx`（Toggle sidebar、Show page notes，喺 app-shell.tsx InfobarProvider 入面渲染）；`use-workspace-actions.tsx`（Switch to …）；`use-record-actions.tsx`（Conversations、Drafts waiting gate approve）；Navigation subtitle 讀 attention；render-result 無結果帶 query；channels-view 加 `connect=1` param；search-input 加 compact + data-tour，header <md 渲染 icon button。**（effort M）  
   檔案：`web/src/components/kbar/index.tsx, web/src/components/kbar/use-app-actions.tsx (new), web/src/components/kbar/shell-command-actions.tsx (new), web/src/components/kbar/use-workspace-actions.tsx (new), web/src/components/kbar/use-record-actions.tsx (new), web/src/components/kbar/render-result.tsx, web/src/components/layout/app-shell.tsx, web/src/features/channels/channels-view.tsx, web/src/components/search-input.tsx, web/src/components/layout/header.tsx`
7. **Mobile + unavailable：LiveIsland 加 `placement='sheet'` 同 unavailable view，app-sidebar 喺 isMobile 時放喺 SidebarHeader switcher 下；<md 隱藏所有 Kbd 提示。**（effort S）  
   檔案：`web/src/components/layout/live-island.tsx, web/src/components/layout/app-sidebar.tsx, web/src/components/layout/header.tsx`
8. **Info sidebar 補齊：roles-view、brand-view、notifications-view、api-view、conversation-view 加一般化 infoContent。**（effort S）  
   檔案：`web/src/features/workspace/roles-view.tsx, web/src/features/workspace/brand-view.tsx, web/src/features/account/notifications-view.tsx, web/src/features/account/api-view.tsx, web/src/features/agent/conversation-view.tsx`
9. **Shortcuts dialog：`web/src/features/onboarding/shortcuts-dialog.tsx` 由 navGroups shortcut + 固定全局鍵生成；HelpMenu、account menu 加項（≥md）；`?` 鍵（guard input）開啟。**（effort S）  
   檔案：`web/src/features/onboarding/shortcuts-dialog.tsx (new), web/src/features/onboarding/help-menu.tsx, web/src/components/layout/app-sidebar.tsx`
10. **Shell tour：加 data-tour ids（workspace-switcher、nav-create、header-create、live-island、search）；tours.ts WELCOME_TOUR 開頭插入 shell steps（每個 target 帶 fallback），help 維持最後；TourCtx 加 workspaceName／role。先同 onboarding owner session 協調（features/onboarding 全部 untracked）。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts, web/src/features/onboarding/use-tour-context.ts, web/src/components/layout/workspace-switcher.tsx, web/src/components/layout/header.tsx, web/src/components/search-input.tsx, web/src/components/layout/live-island.tsx, web/src/components/layout/app-sidebar.tsx`
11. **驗證：`npx tsc --noEmit`、`npm run lint`；browser 喺 :3100（唔係 4331）逐狀態實測：375／768／1440、light／dark、reduced motion、viewer role 切 workspace 後 ⌘K 列表、⌘K 各 section、API 停機時 island unavailable、error.tsx 用 throw 頁觸發、/app/does-not-exist 留喺 shell；唔撳任何 approve／schedule／send（dev harness Threads 係 live）。**（effort S）  
   檔案：`web/ (verification only)`
12. **Backend（獨立 PR，P2）：`POST /api/workspaces`、`PATCH /api/workspaces/{id}`（name）、`GET /api/me/notifications`、`/api/me` onboarding 欄位；每個要 permissions.py 對應檢查 + audit event + tests/test_postriff_phase2_hosted.py。**（effort L）  
   檔案：`src/postriff_phase2/hosted_app.py, src/postriff_phase2/hosted.py, src/postriff_phase2/permissions.py, tests/test_postriff_phase2_hosted.py`

## Risks

- Parallel session：shell 幾乎每個檔都係 WIP——M：app-gate、app-shell、app-sidebar、header、info-sidebar、page-container、workspace-switcher、kbar/index、lib/api/{client,hooks,types}、lib/workspace/provider；??：features/onboarding/、lib/channels/、lib/preferences.tsx、features/overview/attention.ts。落手前同步，commit 一定 stage by path。
- kbar 0.1.0-beta.48：actions prop 同 options 只喺 mount 讀一次；`z-99999` positioner 會蓋過 Base UI dialog／sheet（z-50）；`useRegisterActions` deps 唔穩定會每 render 重註冊——Records／nav actions 要 useMemo + 穩定 id。PreferencesProvider re-key 會 remount KBar，開住嘅 ⌘K 會被關閉。
- ⌘B／⌘I 係瀏覽器同 rich editor 常用鍵；加 guard 後 contenteditable 內唔攔，composer 日後換 rich editor 要再驗。
- Route 檢查只識 nav-config `access`；/app/agent/[id]、/app/channels/connect 等未列 route 要喺 fallback map 明確定義，否則會誤踢或者漏踢。
- Trial 天數依賴 `entitlement.resetsAt` 語義；billing.py lifecycle 對 trial 冇到期日，未確認前唔顯示天數（billing-view.tsx:107 亦有同一假設）。
- `useMyInvitations().available` 喺 dev harness 係 false（hosted.py:843），invitations group 只能喺 Supabase deployment 驗證。
- Snapshot 15s polling 只喺 jobs in flight 開；多 tab 會倍增負載，TanStack 預設 refetchIntervalInBackground=false 已限制背景 tab。
- Channels count 首選 /channels connectionState；snapshot displayState 只做 fallback，係 string contract（'Reconnect'／'Finish setup'），要加 test 釘住。
- Capability honesty：shell 上任何 channel 字眼只可以講「needs attention」＋ attentionSentence，永遠唔出「Connected ✓」；Direct／Assisted 細節留喺 Channels 頁。
- Multi-tab：一個 tab 切 workspace（localStorage postriff-workspace）另一個 tab 唔知；暫時接受，必要時聽 `storage` event。
- i18n：shell copy 全部英文 hard-code、冇 i18n library；worldwide languages 計劃係 post 語言唔係 UI 語言。新字串集中喺 config／常數，唔好喺 shell 加 locale switcher 或 flag emoji。

## 覆核記錄

- 改正：kbar/index.tsx:11-61 只由 nav 生成 actions，冇 actions；KBarComponent 62-94 → 改為『nav actions 13-65 + Help section 70-99（Take the tour／Tips for page）；KBarComponent 101-134』，Cmd+K v2 嘅 Take the tour 唔好重複註冊
- 改正：kbar ^0.1.0-beta.48 喺 web/package.json:40 → web/package.json:41
- 改正：info-sidebar.tsx:18-32 仍係 template defaultData「Documentation / Getting Started / Installation Guide → '#'」 → 刪走『template 殘留』嘅指控；fallback 已經誠實。保留嘅改善只係：冇 content 時 rail 仍然出現，可考慮淡化；唔需要 toast
- 改正：冇 infoContent 嘅 view 係 roles、notifications、api、conversation 四個 → 補齊五個：roles、notifications、api、conversation、brand
- 改正：POST /leave 已存在 hosted_app.py:474；hosted.py:557-567 owner 409；client.ts:114 → client.ts:116
- 改正：GET /api/me/invitations + accept/decline：hosted_app.py:366,374；client.ts:120-127 → client.ts:125-129
- 改正：tours.ts:53-154 welcome tour 十步，shell 只有 [data-tour="help"] 145-152；tour 由 composer 直接跳去 Channels → 改為『welcome tour 冇任何 shell step（switcher、Create、island、search）』
- 改正：未 commit 改動只列 app-sidebar、header、app-shell、app-gate、template → 列出完整清單；幾乎每個 shell 檔都係 WIP
- 改正：共用 attention selector 唔存在，要新增 web/src/lib/attention.ts → 唔新開 lib/attention.ts；將 features/overview/attention.ts 升格去 web/src/lib/attention.ts（或原地 export），加 `needsReview`、`publishing`、`hasJobsInFlight` selector
- 改正：Channels count 用 snapshot displayState !== 'Ready for posting'（同 home-view.tsx:118-124） → Channels count = useChannels().data.channels.filter(c => needsAttention(c)).length；channels query error → 冇 badge
- 改正：Cmd+K『Connect a channel → /app/channels/connect』 → 指向 /app/channels，或者新增 `?connect=1` 由 channels-view 開 sheet（要喺 channels-view 加 param handling）
- 改正：Cmd+K actions 用 useSidebar().toggleSidebar 同 useInfobar().setOpen → 新增 `<ShellCommandActions />` 放喺 InfobarProvider 入面（app-shell.tsx:38-41），用 useRegisterActions 註冊呢兩項
- 改正：kbar nav actions 會隨 role／workspace 改變重新過濾 → nav actions 改用 useRegisterActions(actions, [actions]) 註冊，唔經 KBarProvider actions prop
- 違反原則（已改）：真數據先郁：Channels count 讀 snapshot `displayState` 字串（'Ready for posting'），而唔係 capability-aware 嘅 /channels connectionState；同 Overview（features/overview/attention.ts + lib/channels/state.ts needsAttention）定義唔一致，兩處數字可以唔同。
- 違反原則（已改）：Capability honesty：snapshot displayState 係 blended 單一狀態，用嚟出 sidebar badge 等同一個混合『OK／not OK』判斷；應該用 needsAttention（逐 channel connectionState + expiringSoon），tooltip 用 attentionSentence。
- 違反原則（已改）：真數據先郁：trial pill『Trial · N days left』用 entitlement.resetsAt，但 billing.py lifecycle 對 trial 冇到期日、resetsAt 係 entitlement 週期；未證實語義前顯示天數＝可能講假數字。spec 只喺 risks 提，design 仍然當事實。
- 違反原則（已改）：真數據先郁／誠實：features 以『InfoSidebar 仍係 Installation Guide → #』做 P0 理由，但現時 fallback 已經係誠實嘅 Help 文案；spec 對現狀嘅指控係錯。
- 違反原則（已改）：Motion rules：Cmd+K reduced motion 方案只設 enterMs/exitMs=0，但 kbar options 只喺 mount 讀一次（useStore.js:44-47），OS 設定中途改唔會生效；另外 KBarAnimator 會 animate height（KBarAnimator.js:109,133），唔止 transform/opacity——要喺 spec 講明 0ms 係唯一合規做法。
- 違反原則（已改）：Motion rules：Plan pill 用 AnimatedBadge『icon + text roll』喺 usage query 返回時播——首次載入唔應該播 roll（冇狀態變化），只喺 status 真正轉變先郁。
- 違反原則（已改）：General, not personal：冇違反；tour 文案一般化 OK。
- 違反原則（已改）：Remind, don't block：switch 後 `router.replace('/app')` 靜靜踢走係 OK（viewer 本身冇 edit 權），但文案要講原因，唔可以只講『Switched to {name}』令人以為頁面壞咗。
- 補上遺漏：kbar actions prop 只讀一次（useStore.js:48-54）：切 workspace／role 後 ⌘K nav 唔會重新過濾——比 spec 任何 Cmd+K 功能都更優先嘅 RBAC bug。
- 補上遺漏：KBar 喺 SidebarProvider／InfobarProvider 外面（app-shell.tsx:27-41），spec 提議嘅 Toggle sidebar／Show page notes action 需要一個放喺 provider 入面嘅註冊 component。
- 補上遺漏：features/overview/attention.ts（deriveAttention）同 lib/channels/state.ts（needsAttention）已存在，spec 要重用而唔係新寫。
- 補上遺漏：Cmd+K 已有 Help section（kbar/index.tsx:70-99），Take the tour／Tips for page 唔好重複。
- 補上遺漏：Shell 內 404：app/app/not-found.tsx 唔會接未匹配 URL，需要 catch-all `app/app/[...slug]/page.tsx` → notFound()；root not-found.tsx 係 marketing 版。
- 補上遺漏：RBAC：Cmd+K Records『Drafts waiting for approval』要 gate `approve`（冇 approve 權就只顯示 Navigation subtitle 數字，唔出 action）；Connect a channel gate `manage_connections`；Workspace switch actions 唔使 gate；Leave 對 owner 隱藏（API 409）。
- 補上遺漏：RBAC：大部分 edit-only 頁（ideas、brand、memory、models、api）冇用 PageContainer access fallback，所以 route 檢查要靠 nav-config access + 未列 route 嘅 fallback map。
- 補上遺漏：access.plan fallback：usage 未返時應用 WorkspaceListItem.plan（已有真值），唔係 default 'trial'。
- 補上遺漏：Trial 天數顯示對象：usage 任何 member 可讀（hosted.py:316-322），但天數只對 owner 有行動意義；非 owner 只顯示 plan 名。
- 補上遺漏：Live Island unavailable 狀態：snapshot error 時完全消失，用戶分唔到『冇嘢』定『讀唔到』；應該顯示細『Status unavailable』pill（唔係 0、唔係 All quiet）。
- 補上遺漏：Channels badge 喺 channels query error 時要隱藏，snapshot fallback 只喺 /channels 讀唔到而 snapshot 有 displayState 時先用（跟 attention.ts:46-48 做法）。
- 補上遺漏：i18n／languages：shell 所有字串係英文 hard-code，冇 i18n library；PreferencesProvider locale 只影響日期格式；worldwide languages plan（docs/postriff-worldwide-languages-plan.md）講 post 語言唔係 UI 語言——shell 唔應該加 flag emoji 或 locale switcher，新 copy 集中喺 config（nav-config、shortcut 表）方便日後抽出。
- 補上遺漏：Mobile：⌘K／⌘B／⌘I 喺 touch 冇意義，shortcuts dialog 同 Kbd 提示喺 <md 要隱藏；info panel 喺 mobile 只可以由 Heading InfoButton 開。
- 補上遺漏：Multi-tab：一個 tab 切 workspace（localStorage postriff-workspace）另一個 tab 唔知，可以聽 `storage` event 或者喺 focus 時比對——至少列做 risk。
- 補上遺漏：未 commit／untracked 範圍遠大過 spec 所列（onboarding、lib/channels、attention.ts、provider、hooks、client、types 全部係 WIP），staging 風險要講清楚。
