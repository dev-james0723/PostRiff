# Completeness critic：跨頁 flow、矛盾同執行次序

> 睇晒 24 份覆核後 spec 同 3 份研究之後，專門搵「仲漏咗乜」嘅 agent 嘅結論。

## Sidebar 建議

建議跟 settings-api research 嘅方向，但分兩步行。Phase 1 只修 bug，Phase 2 先搬 route，免得同 onboarding tour 同其他 session 嘅 WIP 撞。

**Phase 1（今個星期，唔改 URL）：**
- 修正 shortcut 重複：Home 同 Channels 都係 `['h','h']`。全部改 `g` 前綴序列：g h Home、g o Overview、g i Ideas、g c Calendar、g p Pipeline、g l Library、g n Channels、g q Queue、g a Analytics、g x Inbox、g b Brand、g m Memory、g s Settings。另加 node test 斷言唔重複。
- Inbox 嘅 nav gate 由 `reply` 改做所有 member 可見，頁內 action 再按權限 gate（跟 Inbox spec）。
- Roles 移除 nav `access`（跟 Roles spec）。
- sidebar 包 `<nav aria-label="Workspace">`。

**Phase 2 主 sidebar（13 項，URL 大部份唔變）：**
1. **Create**：Home（/app）、Overview、Ideas、Calendar、Pipeline、Library
2. **Distribute**：Channels（amber badge = `countChannelsNeedingAttention`）、Queue（badge = `countNeedsReview`；有 job in flight 時 icon 加細點）
3. **Grow**：Analytics、Inbox（badge = 真 unanswered count；Phase 3 ingestion 落地之前唔顯示 badge）
4. **Voice**：Brand & voice（`/app/workspace/brand` 保持）、Memory（`/app/workspace/memory` 保持；owner 見 pending proposals count）
5. sidebar footer：**Settings**（g s）+ user menu（avatar、Profile、Sign out），另有 workspace switcher v2 喺頂。

**Settings（`/app/settings/[section]`，左 rail；手機用「清單 → 詳情」）：**
- Personal：Profile、Notifications、Privacy & data、Models & providers
- Workspace：General（新：name、time zone、預設 languages、danger zone）、Members、Roles（所有 member 可見）、Audit log（權限等 James 拍板：跟 API／RLS 定收緊到 owner + admin）、Usage & plan（owner；非 owner 喺 General 見唯讀 plan 名 + 「Ask the owner」）
- Developer：API & integrations（由 Account 搬到 Workspace／Developer，因為 access 係 `manage_connections`，屬 workspace 權限）、Companion（Phase 4 先出現，未 ship 前唔顯示）

**Badge 規則（真數據先郁）：** 所有 count 由 `web/src/lib/attention.ts` 一個 module 出，error 或未 load 就唔顯示 badge（唔係 0），同一個數喺 sidebar、mobile tab bar、bell、Home、Overview 必須一致。

**遷移：** 舊 `/app/account/*`、`/app/workspace/{members,roles,audit}` 喺 `next.config.ts` 做 permanent redirect。`use-breadcrumbs` GROUP_LANDING 同 tours.ts 嘅 stop／path 一次過由 onboarding owner 改。Brand／Memory URL 唔變，tour 唔使郁。

**手機：** 底部 tab bar（Home／Calendar／Queue／Inbox／More），More 開完整 sidebar Sheet。

## 仲未有 spec 嘅 surface

- **Mobile navigation（手機底部導航 + shell 喺 <768px 嘅行為）**：而家 header.tsx 喺手機收埋 LiveIsland（`hidden md:block`），淨係得 SidebarTrigger 開 Sheet。21 個 nav item 要撳兩下先去到，而 Queue／Inbox／Calendar 正係手機上最常用嘅 approve 同 reply 動作。page spec 入面淨係 Agent conversation 有講 responsive（rail／inspector Sheet），其他頁都冇講手機點行。  
  建議：喺 `web/src/components/layout/` 加 `mobile-tab-bar.tsx`：Home／Calendar／Queue／Inbox／More 五格，More 開返完整 sidebar Sheet。badge 同 sidebar 一樣讀 `lib/attention.ts`，error 嗰陣唔顯示數字（唔可以變 0）。bar 要加 safe-area padding。LiveIsland 喺手機收做 tab bar 上面一條細 strip，只喺 `hasJobsInFlight` 係 true 先出。每頁 spec 嘅驗收一律加 375px。
- **User menu／Sign out 喺 shell**：Sign out 而家只喺 `web/src/features/account/profile-view.tsx:662`。shell 冇 avatar menu，用戶唔知自己用緊邊個 account，亦要入 Profile 先登出得。多 workspace、step-up 同 2FA 流程都需要一個固定位置顯示身份。  
  建議：sidebar footer 加 `nav-user.tsx`：avatar initials + display name + email，menu 有 Profile、Settings、Theme、Sign out（沿用 AlertDialog）。資料讀 `useMe()` 真值，未 load 到就用 Skeleton，唔好顯示假名。
- **Workspace creation（新增 workspace）**：`workspace-switcher.tsx:96` 寫住「You join other workspaces by invitation.」，`hosted_app.py` 淨係有 `GET /api/workspaces`，冇 POST。一個人想分開兩個 brand 或者客戶就冇路行。Shell spec 嘅 Workspace switcher v2 有 leave，但冇 create，sample workspace 亦冇「離開 sample、開真 workspace」嘅出口。  
  建議：後端加 `POST /api/workspaces`：沿用 bootstrap 路徑，寫 audit `workspace.created`、welcome ledger，受 plan entitlement 限制（超出上限就提示去 Usage & plan，唔阻已有 workspace 繼續用）。前端 switcher 加「New workspace」Dialog（name + time zone）。sample workspace 頂部加一條 banner「This is a sample · Create your workspace」。因為要動 backend，放 Phase 3。
- **Workspace general settings（名、time zone、預設語言、刪除 workspace）**：Overview 同 Calendar spec 用 `useTimeZone()`，但冇任何一頁擁有 time zone 設定。worldwide languages plan 有 `channelLocales`，但冇 workspace 層面嘅預設。Privacy spec 嘅 delete pre-flight 係刪 workspace，混咗喺 account 區。  
  建議：Settings → Workspace → General（`/app/settings/workspace`）：name、time zone、預設 languages（用 language picker）、Danger zone（delete 由 Privacy 頁連過嚟，pre-flight 邏輯共用 `privacy-model.ts`）。owner 先改得，其他人唯讀，並講明邊個改得。
- **In-app notification centre（header bell）**：Notifications spec 做嘅係 email 設定 + ledger，屬 settings 頁。shell 冇一個入口顯示「Waiting for you」。attention 散落喺 Home、Overview、LiveIsland、sidebar count 四度，用戶要自己逐頁搵。  
  建議：header 加 bell Popover，內容直接 render Notifications spec 嘅「Waiting for you」清單（`useAttention()`，按權限過濾，包括 held／failed），加最近 10 條 ledger，底部 link 去 `/app/account/notifications`。bell 上嘅點只喺 attention.data 存在而且 >0 先出；error 時用灰色 icon + tooltip「unavailable」。唔使新 backend。
- **Global search（內容搜尋，唔止跳頁）**：`SearchInput` 同 kbar 而家只搜 nav。drafts、sources、assets、conversations、channels 都搵唔到。Pipeline、Library、Ideas 各自有 filter，但冇跨頁搜尋。  
  建議：Phase 2：kbar 加「Search this workspace」section，由 snapshot 喺 client 端搜 variants text、sources title、assets name、conversations title（`useSnapshot` 已經有），每項 deep link 去對應 detail sheet（`?draft=`、`?asset=`、`/app/agent/[id]`）。唔使 backend。conversations 如果超過 snapshot 範圍，Phase 4 先加 server search。
- **Keyboard shortcuts help（? 鍵）**：Shell spec 將 nav shortcut 改做 `g` 前綴序列，⌘B／⌘I 亦有 guard。但冇地方教人，HelpMenu 淨係有 ⌘K。現時 Home 同 Channels 兩個都用 `['h','h']`，證明冇人睇住成份清單。  
  建議：`web/src/components/kbar/shortcuts-dialog.tsx`：清單由 `nav-config.ts` + 一個 `shortcuts.ts` registry 生成（唔手抄）。`?` 開（input focus 時唔觸發）；HelpMenu 加「Keyboard shortcuts」；再加一個 node test 斷言 shortcut 唔重複。
- **Offline／API unavailable／session expired 全域狀態**：Shell spec 有 `error.tsx`、`not-found.tsx`，每頁 spec 各有 Retry，但冇全域處理：斷網時 mutation（approve、schedule、reply）會靜靜失敗；API 503 會令每個 region 各自出一個 unavailable；session 過期會喺動作中途 401。  
  建議：`query-provider.tsx` 加 `onlineManager` 綁 `navigator.onLine`，header 下出一條「You're offline · changes will not send」banner（只讀真 online 狀態）。mutation 喺 offline 時 disable 並顯示 reason，唔 queue 假成功。QueryCache `onError` 集中處理 401 → 保留當前 path，跳 `/auth/sign-in?next=`（用 Auth spec 嘅 `safe-next.ts`）；多個 query 同時 503 → 一條全域 Alert，唔好每個 region 重複出。
- **Plan limits／upgrade prompts（entitlement reminders）**：`channels-summary.tsx:69` 寫「upgrade for more」，但 Usage & plan 喺 nav 係 owner-only，editor 撳落去入唔到。trial ending、grace period 喺 shell 冇 banner。Billing spec 只處理 billing 頁本身。  
  建議：共用 `PlanReminder` component：讀 `access.plan` + usage meter 真值。owner 見到「Open Usage & plan」；非 owner 見到「Ask the workspace owner」，並顯示 owner 名。trial／grace 剩 ≤3 日，shell 頂出一條可以收埋嘅 banner（`TRIAL_ENDING_DAYS`／`GRACE_DAYS` 用 Notifications spec 抽出嚟嗰份常數）。依照 remind-don't-block：到上限只係提示，唔 disable composer；backend 嘅真限制（例如 channel 數）照返 409 嘅原因文字顯示。
- **Language picker（docs/postriff-worldwide-languages-plan.md §7 slice 5）**：冇任何一份 page spec 提到佢。但 §7.2 列出嘅 composer.tsx、home-view.tsx、conversation-view.tsx、ideas-view.tsx、plan-card.tsx、pipeline-view.tsx、schedule-dialog.tsx、queue-view.tsx、analytics-view.tsx，全部都係今次 Home／Conversation／Ideas／Pipeline／Queue／Calendar／Analytics spec 會改嘅檔，一定撞。  
  建議：page spec 唔好改語言相關嗰幾行（例如 `繁中/EN`、radiogroup），留俾 languages slice 5。每份 spec 嘅 next step 加一句「language rows untouched — slice 5」。`LanguageBadge` 同 `ChannelLanguageChip` 做好之前，Pipeline／Queue／Calendar 新 component 預留 `language` prop。排喺 Phase 3，等 slice 2 backend 落地之後先做。
- **UI 本身嘅 i18n（介面語言）**：而家所有 UI copy 都係英文 hard-code。Privacy spec 提過「文案常數方便將來 i18n」，但冇整體計劃。worldwide 產品要做到畀老師、店主用，介面語言係基本要求。  
  建議：Phase 4 先做，但由 Phase 2 開始定規矩：新 view 嘅文案集中喺 `*-model.ts` 常數（照 privacy-model.ts）；數字、日期一律用 `Intl`（`useTimeZone` + locale）。Phase 4 評估 next-intl（App Router + RSC）。介面語言設定放 Settings → Personal → Profile，同 post language 分開，避免混淆。
- **Desktop companion pairing**：`channels-view.tsx:169` 講明 companion「not available yet」，tours.ts 有 `companion` step，capability matrix 有 Bridge level，但冇 pairing surface（配對碼、裝置清單、撤銷）。Home chips 同 Conversation plan rows 會顯示 Bridge，用戶按落去冇地方可以去。  
  建議：Phase 4：Settings → Developer → Companion（`/app/settings/companion`）：pairing code（短時效、一次性）、已配對裝置（名稱、last seen、revoke 要長按）、每個 Bridge channel 喺邊部機。未 ship 之前，Bridge chip 統一 link 去 Channels 嘅 companion 說明，唔好出假「Pair」掣。
- **/app/channels/[id] 單一渠道詳情**：redesign doc §5 有列，但冇 page spec。Analytics coverage strip、Inbox coverage、Profile channel rows、Audit deep link 都需要一個 channel 落地點，去睇 capability evidence、verify history、token expiry、呢個 channel 嘅 queue／analytics。  
  建議：Phase 2：先做 Sheet 版（`/app/channels?channel=<id>`）。內容：capability matrix + evidence、verifiedAt、re-verify、scopes、最近 jobs（同 Queue 共用 JobRow）、最近 analytics read，加 audit 片段。之後有需要先升級做 route。各頁 deep link 統一用 `channelHref(id)` helper。
- **/auth/verify、忘記密碼、email change、刪除個人 account**：`web/src/app/auth/` 淨係有 sign-in、sign-up、callback。Auth spec 將 2FA 第二步搬去 `/auth/verify`，但冇講 email OTP 驗證頁、password reset 同 email change。Privacy spec 處理 workspace deletion，冇處理個人 account deletion（平台審批要求 data-deletion）。  
  建議：Auth spec 擴闊：`/auth/verify` 同時處理 email OTP 同 MFA（query 分 mode）；加 `/auth/reset`。Profile 加「Change email」（step-up）同「Delete my account」：pre-flight 列出自己係 sole owner 嘅 workspace，要先轉 owner 或刪除，文案連 `/data-deletion`。
- **First-run checklist（真數據驅動嘅起步進度）**：welcome tour 係教學，唔係進度。新用戶由 sign-up 去到第一個 verified post 中間有 4–5 步，但冇一個地方話佢知做到邊。  
  建議：`web/src/lib/first-run.ts` 由 snapshot 派生四項：channel 有 publish capability、voice 狀態、第一個 approved job、第一個 verified job。Home hero 下同 Overview 顯示「n of 4」，每項 link 去對應頁 + 對應 page tour。全部完成或者用戶收埋（localStorage，try/catch）就唔再出。數據 unavailable 就成個 checklist 唔顯示，唔估。
- **Webhooks／MCP（API & integrations 下一步）**：redesign §5 寫 `/app/account/api` 係「API keys · MCP · webhooks」，§8 Phase D 話 Public API + MCP 係護城河。API spec 只做 PAT（read + draft）。  
  建議：API 頁預留兩張卡：「Webhooks」同「MCP server」，寫明「Not available yet」，冇假 endpoint。Phase 4 先設計 webhook signing（HMAC、retry ledger）同 MCP（沿用 PAT scope）。

## 跨頁 flow 嘅缺口

- **Sign-up → 第一個 published post**：(1) sign-up 之後 email 驗證冇 `/auth/verify` 頁。(2) bootstrap 完落 `/app` Home，但 header「Create」掣去 `/app/ideas?new=1`，Pipeline／Overview empty state 都指去 Ideas，兩個入口唔一致。(3) Home chips 顯示「未接」，但冇 returnTo：去 Channels connect 完，OAuth 經 `web/src/app/channels/connect/forwarder` 返 `/app/channels/connect`，唔會返 Home composer。(4) voice 未 set 時，Brand spec 話「draft 照做、scheduling 等」，但 Conversation spec 嘅 plan rows 冇顯示呢個 reminder。(5) approve 發生喺 conversation 定 Queue／Calendar 冇講清楚，三度都有 approve 掣（Calendar 抽 `ReviewApproveButton`，Conversation 冇用）。(6) job verified 後只有 LiveIsland 閃一閃（手機仲收埋），冇「it's live」receipt link；Analytics 第一次讀要等固定時間表，empty state 冇講下次幾時讀。  
  建議：(a) 一個 create 入口：header Create 同所有 empty state 改去 `/app`（Home composer focus）；Ideas 只做 capture，佢嘅「Draft from this source」交去 `/app/agent/[id]`，同 Ideas spec 一致。(b) `oauthStart` 加 `returnTo`（用 `lib/auth/safe-next.ts` 驗證），Home chip、Calendar schedule dialog、Conversation plan row 帶上自己嘅 path。(c) Conversation plan row 同 schedule dialog 共用 `VoiceReminder`（讀 voice 狀態真值，只提示唔阻）。(d) Conversation 嘅 approve 用 Calendar 抽出嚟嘅 `ReviewApproveButton`。(e) job 去到 VERIFIED，toast 帶 provider URL（`job.url`）+「View receipt」deep link `/app/queue?job=`。(f) Analytics empty state 顯示真 `nextReadAt`，冇就寫「Scheduled after verification」，唔估時間。(g) first-run checklist 串起成條路。
- **Invite → accept → 第一次 review**：(1) Members invite dialog 寄 email 之後，Notifications ledger 有記錄，但 Members Pending 冇顯示「sent／not delivered／recorded only」。兩份 spec 各有 status 詞彙，冇共用。(2) `/invite/[token]` preview（Auth spec）之後如果要 sign-up，冇講 sign-up 完點樣帶返 token 去 accept。(3) accept 之後落 `/app` Home：一個只有 approve、冇 edit 嘅 reviewer 見到用唔到嘅 composer；Ideas 喺 nav 收埋，但佢真正要做嘅嘢（review）喺 Queue，冇人帶佢去。(4) 冇通知話畀 reviewer 知有嘢要 review：Notifications spec 嘅 audience map 將大部份 kind 定做 owner。(5) Roles spec 嘅「You in this workspace」panel 冇喺 accept 後出現。(6) welcome tour 係 owner 視角（composer、brand、memory），reviewer 睇唔明。  
  建議：(a) sign-up／sign-in 保留 `next=/invite/[token]`（safe-next），accept 後按權限導向：有 edit 去 `/app`；有 approve 冇 edit 去 `/app/queue?filter=review`；得 view 去 `/app/overview`。(b) tours.ts 加 role-aware 變體 `welcome-reviewer`（Queue → Calendar popover → Roles「You in this workspace」），文案保持 general。(c) Members Pending row 讀 Notifications spec 嘅 `NotificationItem.status`，用同一個 badge map（放 `lib/notifications.ts`）。(d) Phase 3 加 `review_requested` notification kind（audience = 有 approve 權限嘅 member，可以關），email link 去 `/app/queue?review=<id>`。(e) bell popover 嘅「Waiting for you」即時生效，唔使等 email。
- **Connect channel → verify → schedule**：(1) Channels spec 同 Inbox spec 都話要改 capability merge，兩個 merge 規則唔同（見 contradictions）。未 merge 之前，reconnect `comments_read` 會降級 publish，Calendar／Home 即刻顯示錯 level。(2) re-verify 寫返 snapshot 之前，Profile 同 Channels 嘅「Verified」label 係 +3600 秒推算，唔係真值。(3) schedule dialog（Calendar 由任何一日 schedule、Pipeline Schedule…、Conversation plan）冇 spec 講點樣逐個 destination 顯示 Direct／Assisted／Unsupported；Assisted 喺 Queue 顯示咩（handoff 等人手）亦冇定義。(4) token 快過期或者 revoked 時，已排期嘅 job 冇 reminder，要去到 worker 失敗先知。(5) OAuth 完冇 returnTo。  
  建議：(a) capability merge 由 Channels spec 一份 backend 改動擁有（`oauth.py` complete() + `_capabilities`），Inbox spec 只加 test「publish Direct → reconnect comments_read → publish 仍 Direct」。(b) 建 `ScheduleDestinationRow`（capability level + evidence tooltip + verifiedAt），Calendar、Pipeline、Conversation、Queue 共用。Assisted 喺 Queue 用 `jobBadge` 嘅 `handoff` 狀態，文案寫「You'll post this one yourself; we'll remind you」。(c) Overview／Queue attention 加一條規則：「channel X needs reconnect · N scheduled posts」，讀 `needsReconnect` + 真 job 數；只提醒，唔自動 cancel。(d) returnTo 同上。
- **Edit → learning proposal → memory**：(1) edit 入口有三個：Conversation inline Edit、Pipeline edit-draft-dialog、Library 以外嘅 variant revise。spec 冇確認三個都寫入同一個 edit stats（Pipeline spec 提到 revisions，但冇提 learning evidence）。(2) proposal 出現之後，只有 Home notice（commit 27720e6）；Overview attention、Notifications「Waiting for you」冇包 pending proposals。(3) Memory ProposalCard 冇 link 返觸發佢嘅 draft／conversation。Audit spec 會記 owner decisions，但 describeAuditEvent 冇 deep link 返 Memory。(4) Brand spec「What drafts read」同 Memory spec「Given to writing routes」係同一個概念，兩頁各自做。(5) Memory tour copy 要改，但 tours.ts 屬 onboarding session。  
  建議：(a) 三個 edit 入口都經 `useAct('variant_revise')`，加一個 test 斷言 Pipeline dialog 同 Conversation edit 都產生 learning evidence。(b) `lib/attention.ts` 加 `pendingProposals`（owner-only），Home notice、Overview、bell、sidebar Memory badge 全部讀佢。(c) ProposalCard evidence 行 link `/app/agent/[id]#variant-<id>` 或 `/app/pipeline?draft=`。Audit `memory.decided` row link `/app/workspace/memory?proposal=`。(d) 「What drafts read」做一個 component，由 Memory 擁有（`features/memory/drafts-read.tsx`），Brand 頁 embed 精簡版 + link。(e) 所有 tours.ts 改動集中交 onboarding owner 一次過改。
- **Retract source → stale drafts → prepare again**：Privacy spec 喺 Privacy 頁做 Retract；Ideas spec 做 source inspector + 收窄 staleness（要 James 拍板）；Calendar 有 `stale` kind + Prepare again；Pipeline 顯示 retracted。四頁冇講 retract 之後用戶點樣由 Privacy 跳去受影響嘅 draft。staleness 規則未定之前，Calendar／Pipeline 會顯示大量 stale。  
  建議：Retract 動作做一個共用 `RetractSourceDialog`，Ideas inspector 同 Privacy 都用。完成後 toast 顯示 per-source receipt 數（Privacy spec 已回傳），加「Review N affected drafts」link 去 `/app/pipeline?source=<id>`。staleness 收窄未拍板前，Calendar stale 文案寫真原因（`review.status` + 最後 event message），唔好估。
- **Inbox comment → reply draft → approve → send → receipt**：Inbox spec 嘅 worker reply_step 同 reconcile 係 backend-heavy。前端 Approve 撳完之後，reply 狀態停喺 approved，冇 worker 送；Audit spec 嘅 post.* 冇 reply.* kinds；Notifications 冇 reply failed 通知。  
  建議：Phase 1 前端只做 honesty 修正，approved reply 顯示「Approved · sending is not switched on yet」（讀 backend 真 flag，唔好假 pending）。Phase 3 worker 落地時同步加 audit `reply.sent／reply.uncertain`，attention 加 uncertain replies。
- **Checkout → plan active → entitlement 生效**：Billing spec 做 backoff polling 等 lifecycle active，但 `access.plan`（nav filter、Channels limit、PlanReminder）由 workspace provider 讀，唔一定同步 refresh，所以 upgrade 完 sidebar 同 limit 仍然係舊值。  
  建議：polling 見到 active 時，invalidate `keys.workspaces`、`keys.snapshot`、`keys.me`。Shell spec 嘅 provider plan fallback 改讀最新 list item。加一條 test：lifecycle 轉 active 之後，`useWorkspaceAccess().plan` 更新。

## Spec 之間嘅矛盾

- Nav shortcut 撞鍵：`nav-config.ts` 入面 Home 同 Channels 都係 `['h','h']`。Shell spec 提議改 `g` 前綴，但 Channels 同 Home spec 冇跟，要由 Shell spec 一次過擁有。
- Job state 常數有五份：Calendar spec 抽 `JOB_STATES` 去新檔；Queue spec 將 `pipeline/job-state.ts` 搬去 `queue/job-state.ts`；Overview spec 抽 `readQueueStatus` + PRE_FLIGHT／IN_FLIGHT／VERIFIED 去 `lib/jobs.ts`；Library spec `asset-usage.ts`「鏡射 IN_FLIGHT」；Privacy spec `privacy-model.ts` 又定義 IN_FLIGHT／TERMINAL。三份 spec 各自話自己係「共用」嗰份。建議統一放 `web/src/lib/jobs.ts`。
- Attention 擁有權：Overview spec 話 `deriveAttention` 由 Home + Overview 共用；Shell spec 將 `features/overview/attention.ts` 搬去 `lib/attention.ts`，並加 `countNeedsReview` 等；Notifications spec 用 `useAttention()`。三個名、三個位置，要定一個 module。
- Capability matrix merge 兩份 spec 都認做：Channels spec 喺 `complete()` 做 additive merge（Direct > Assisted > Bridge > Unsupported，union scopes）；Inbox spec 改 `_capabilities` 讀現有 rows，只更新 requested capability，或者 `oauthStart` 一次 request 多組 scopes。規則唔同，會出兩個 PR 互相覆蓋。
- `AlphaError` 加 `code` 兩份 spec 各做一次：Members spec（`step_up_required`，hosted_app.py:500 序列化 {error, code}）；Auth spec（`session_revoked`／`mfa_required`）。`ApiError.code` 亦喺兩份 spec 各自加。
- Memory 檔 export 兩條路：Brand spec 要 `export_profile` 冇 packageSchema 時出 memory 檔 zip；Memory spec 新開 `GET /api/workspaces/{w}/memory/export`。兩個 zip 內容同 RBAC（decided_by strip）可能唔一致。
- 「What drafts read」重複：Brand spec 嘅『What drafts read』preview 同 Memory spec 嘅『Given to writing routes』係同一份真相，兩頁各自 render。
- Create 入口矛盾：Home（/app）係 agent chat composer，Ideas spec 亦將 drafting 交去 `/app/agent/[id]`；但 `header.tsx:36`、`pipeline-view.tsx:311,386`、`overview-view.tsx:247` 嘅 Create／empty state 全部指去 `/app/ideas?new=1`。另外 redesign doc §5 寫 `/app` = Overview，同現況唔一致。
- Detail sheet 重複：Queue spec 有「Job detail sheet with full receipt + deep link」；Pipeline spec 有「Card detail sheet：job events、provider receipt、nextAction」；Calendar spec 喺 popover 顯示 `events.at(-1).message` + `nextAction`。三個 surface 顯示同一份 receipt，但冇共用 component。
- Inbox 權限：Inbox spec 話「nav 所有 member 可入」，但 `nav-config.ts` 係 `access: { permission: 'reply' }`；settings research 嘅 sidebar 冇處理呢點。Roles spec 開放 Roles 俾所有 member，但 Members（manage_members）同 Audit（`role: 'admin'`）唔郁。Audit spec 又話 API／RLS 係任何 member 睇得，要 James 拍板收緊，所以 nav gate 同 API 而家係矛盾狀態。
- API & integrations 位置：API spec 保持 `/app/account/api`，並喺 hosted_app 加 route；settings-api research 話佢係 workspace 權限（`manage_connections`），應該搬去 Settings → Developer／Workspace。Roles spec 又直接改 `nav-config.ts:114`，同 Settings 重組會撞。
- Channels 前端擁有權：Channels spec 話唔好重做 HEAD 版本、等 WIP owner commit；但 Profile spec 要改 `web/src/lib/channels/state.ts:63` label（'Verified · read only'），會影響 Channels 嘅 `channel-card.tsx`，而嗰個檔屬另一個 session 嘅 untracked WIP。
- tours.ts 多頭修改：Home spec（home-tips + Show me around）、Pipeline spec（tours.ts Pipeline entry）、Memory spec（改 tours.ts:320 copy + 加步驟），但 onboarding research 同 motion research 都話 `features/onboarding/*` 屬另一個 session 嘅 WIP。
- Particle field 同 motion 規則：motion research 保留 hand-written canvas 做 HomeView 背景（alpha 0.42，純 drift + repel）；但 house rule 4 同 motion-system §5 要求「motion reads real data」。純裝飾嘅持續動畫要有真數據依據，或者喺 reduced-motion 時完全唔 render，spec 未講清楚。
- Staleness 規則：Ideas spec 想收窄 source 改動嘅 staleness（唔再 bump 全 workspace brief.revision）；Calendar spec 將 `stale` 做一個獨立 kind 同顏色；Pipeline spec 將 stale 列入 boardInvariants。如果 Ideas 改動落地，Calendar／Pipeline 會少咗大量 stale；如果唔改，而家儲一個新 source 會令所有 draft 變 stale。兩邊嘅驗收條件互相依賴，但冇人標明。
- `channels-summary.tsx:69` 叫人「upgrade for more」，但 Usage & plan nav 係 owner-only。Billing spec 冇處理非 owner 嘅入口，Channels spec 亦冇改呢句。
- redesign doc §5 列咗 `/app/channels/[id]`、`/auth/verify`、「API keys · MCP · webhooks」，但 page spec 冇 channel detail，Auth spec 只將 2FA 搬去 `/auth/verify`（冇 email OTP），API spec 只做 PAT。計劃同 IA 文件唔對齊，要更新其中一邊。

## 建議執行次序

### Phase 0 — 協調同共用 module 定案（第 1 日，半日）

大約十份 spec 都各自抽 IN_FLIGHT／attention／AlphaError code，唔先定位置，Phase 1 同步開工就會出現五份常數同 merge conflict。WIP 未 commit 就改，會重演 parallel-session reset 洗走未 commit 改動嘅事故。

- 同擁有 WIP 嘅 session 對齊，並由佢哋按 path commit：`web/src/features/onboarding/*` + `web/src/styles/tour.css`、`web/src/components/motion/particle-field.tsx`、Channels 重寫（untracked `channels/*.tsx`、`lib/channels/*`）、Analytics（`analytics-view.tsx` + 8 個 untracked 檔）、Overview untracked 檔。之後全部改動只 stage by path，唔准 whole-tree commit。
- 定一份 job state 真相：`web/src/lib/jobs.ts`（WAITING／PRE_FLIGHT／IN_FLIGHT／VERIFIED／DONE／FAILED／held + `readQueueStatus`），Queue、Pipeline、Calendar、LiveIsland、Library asset-usage、Privacy pre-flight 全部 import。`published` 屬 in-flight，跟 store.py:19。
- 定一份 attention 真相：`web/src/lib/attention.ts`（`deriveAttention`、`useAttention`、`countNeedsReview`、`countChannelsNeedingAttention`、`hasJobsInFlight`、`pendingProposals`）。
- 定 error code contract：`AlphaError(code=)` + `ApiError.code`，一次過包 `step_up_required`、`session_revoked`、`mfa_required`（Members spec 同 Auth spec 合併做一件）。
- tours.ts 所有改動（Home、Pipeline、Memory、reviewer 變體）交 onboarding owner 一個人改。

### Phase 1 — 今個星期 ship（onboarding、motion、Channels／Inbox／Analytics／API）

呢批大部份係前端，或者係細、有 test 覆蓋嘅 backend 修正；James 指定優先做 onboarding、motion 同呢四頁。capability merge 要跟 Channels 一齊出，因為 Inbox、Home chips、Calendar 都依賴佢，而且而家 reconnect 會降級 publish，係真 bug。PAT 涉及 migration 同 auth bypass `_origin`，要 security review，唔適合塞入今個星期。

- Onboarding tour v2（喺 v1 上面改，唔裝 library）：`lastRect` morph 跨頁、sidebar link pulse、reduced-motion 時直接跳位；全部 copy 過一次 general 檢查；`welcome` 同 page tips 嘅 data-tour anchors 補齊（Channels、Inbox、Analytics、API）；HelpMenu 加「Keyboard shortcuts」。
- Particle field：mount 搬入 client component；補 research 列出嘅 6 個修正；`prefers-reduced-motion` 時唔 render canvas；tab hidden 時 pause；密度或 pulse 讀真數據（例如 `hasJobsInFlight`），唔好純裝飾性狂郁，以符合 motion §5「motion reads real data」。
- Shell 細修：⌘K 權限過濾（useRegisterActions）、shortcut `g` 前綴去重 + test、`app/app/error.tsx`／`not-found.tsx`／`[...slug]`、sidebar `<nav>`、Inbox 同 Roles 嘅 nav gate 調整。
- Home 誠實狀態 pass（unavailable ≠ 0、models.isError pill、Info sidebar `useInfoContent`、「Show me around」→ tour）。
- Channels：commit 已完成嘅前端（owner 按 path）；backend `mark_channel_verified` 寫返 snapshot + 一小時規則只限非 live_provider；additive capability merge（Channels 擁有，Inbox 共用），加 unit + postgres tests。
- Inbox 純前端誠實修正：Dialog 顯示 `manifest.text`、textarea 同 draft 同步、`isPending`／error Alert + Retry、「Insert a starter line」改名 + backend label、empty state 用 account handle、stagger 30ms。worker 未接之前，approved reply 寫明未送出。
- Analytics：types 對齊（AnalyticsPost connectionId／contentTypeId／cohort）、刪 hosted.py:472-473 hardcode 同改相關 test、RetryAlert、capability-honest coverage strip、empty state 寫真 next read。
- API & integrations 頁（唔包 PAT backend）：page access gate、access status strip 讀 API、tool registry card 讀 `/api/tools`（isolated 同 publicInvokeEnabled 分開）、connected accounts 逐 capability；Tokens、Webhooks、MCP 卡寫「Not available yet」，唔出假掣。

### Phase 2 — 下 1–2 星期（跨頁 honesty + 共用 component + Settings 重組）

呢批主要係將 Phase 0 定好嘅共用 module 落地到其餘頁面，backend 改動細而且有 test 可以保護。Settings 重組涉及 URL 同 tour stop，要等 Phase 1 tour v2 commit 之後先做，redirect 可以令舊 link 唔斷。

- 共用 action／detail component：`ReviewApproveButton`、`JobCancelHold`、`JobDetailSheet`（receipt、events、nextAction、provider URL），Queue、Pipeline card detail、Calendar popover、Conversation 全部用；`ScheduleDestinationRow`（capability level + VoiceReminder）。
- Overview（Next up card、honest errors）、Calendar（held／expired／stale kinds、error／empty、任何一日 schedule）、Queue（loading／error、permission-honest、live refetch）、Pipeline（deriveBoard invariants、detail sheet）、Conversation（route states、MessageScroller、motion ≤300ms、Try again）。
- 單一 create 入口：header Create 同 empty state 改去 `/app`；OAuth `returnTo`（safe-next）。
- Library backend guard 修正（editor／admin 可上載刪除、sample 403、createdAt／uploadedBy）+ 多檔上載 + asset detail sheet。
- Memory／Brand 前端誠實修正（Files 分組、unavailable + Retry、Expires in、Decided、export error message）；「What drafts read」一個 component 由 Memory 擁有。
- Members 即時 bug 修正 + members() 真身份 join；Roles `GET /api/permissions` + 「You in this workspace」；Profile capability-honest rows + device label。
- Auth：invitation preview endpoint、`/auth/verify`（email OTP + MFA）、`/auth/reset`、accept 後按權限導向 + `welcome-reviewer` tour。
- Settings 重組：`/app/settings/[section]` 左 rail + redirects + breadcrumbs；Workspace General 頁（name、time zone）；sidebar user menu；mobile tab bar；bell popover（讀 `useAttention`）；keyboard shortcuts dialog；offline banner + 401 集中處理；PlanReminder（owner／非 owner 分流）。
- kbar 內容搜尋（client 端讀 snapshot）；`/app/channels?channel=` detail Sheet。
- API PAT：migration `013_api_tokens.sql` + `api_tokens.py` + scope guard + tests，完成 security review 先 ship。

### Phase 3 — Backend-heavy（2–4 星期，部份要 James 拍板）

呢批需要 migration、worker、外部 provider 或者產品決策（audit 權限、staleness 規則），風險同依賴都高。放喺 Phase 1–2 共用 component 穩定之後做，language picker 亦避免同 page spec 撞同一批檔。

- Inbox 真 pipeline：production ingestion、`PostgresWorker.reply_step()` + reconcile（submitted → verified／uncertain，唔 resend）、「Check for new comments」手動 sync + 真 lastSyncAt、reply audit kinds。
- Analytics 生產數據路徑：verified 後讀 + 固定時間表再讀，`nextReadAt` 暴露俾前端。
- Audit log：先等 James 拍板 (a) 邊個睇得、(b) export permission、(c) retention；之後做 read path（pagination、counts、actorName）同 write path（post.*、owner decisions、api_token.*、data.exported、reply.*），describeAuditEvent 每行 deep link。
- Ideas：presented source 加 `useApproved`／`factsDigest`；staleness 收窄（要 James 拍板，影響 Queue 規則）；共用 RetractSourceDialog。
- Notifications `my_notifications` + ledger 補齊 + `review_requested` kind。
- Privacy：export 單次 build + SHA-256 receipt、per-source retraction receipt、diagnostics preview、delete pre-flight；個人 account deletion。
- Usage & plan：billing-model.ts + checkout polling + invalidate access；usage_view 清理。
- Models & providers：真 rescan、catalog 搬到 auth 之後（Home composer 同步處理 401／Unavailable）、route inventory。
- Brand backend 三件（profile_withdraw、you_restore_voice、export fallback）同 Memory export endpoint 合併設計，避免兩條 zip 路徑。
- Workspace creation（`POST /api/workspaces` + switcher New workspace + sample exit banner）。
- Worldwide languages slice 2（backend）→ slice 5（language picker、LanguageBadge 替換 §7.2 各檔）。

### Phase 4 — 護城河同國際化（持續）

呢批係 redesign doc §8 Phase D 嘅護城河項目，依賴 Phase 3 嘅 audit、PAT、capability 基建，而且冇一項係而家擋住用戶發第一個 post 嘅 blocker。

- Desktop companion pairing（Settings → Developer → Companion：pairing code、裝置清單、revoke）同 Bridge capability 接通。
- Public API 擴展：Webhooks（HMAC signing、delivery ledger）、MCP server（沿用 PAT scope）。
- UI i18n：評估 next-intl，由 `*-model.ts` 文案常數開始抽，Profile 加介面語言設定（同 post language 分開）。
- Server-side 全域搜尋（conversations、舊 revisions）。
- `/app/channels/[id]` 由 Sheet 升級做完整 route（如果 Sheet 唔夠用）。
