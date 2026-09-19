# PostRiff — 全 App 更新計劃：逐頁 design spec、technical requirements、features、onboarding 同 motion

> 狀態：計劃已定稿；可以純前端完成嘅部分已經落實（未 commit）
> 日期：2026-09-16 · Branch：`consumer-saas`
> 範圍：`/app/*` 每一個 sidebar 項目、app shell（sidebar / header / ⌘K / 右欄）、sign-in 同 invite；marketing site 唔包
> 做法：每頁一個研究 agent 對住 codebase 寫 spec → 另一個 agent 逐句核對 file:line 並改正 → 三份專題研究（onboarding、motion、settings／API）同樣覆核 → completeness critic 搵跨頁缺口 → 前端部分逐頁實作，每頁再經獨立 code review
> 配套：design canvas https://claude.ai/artifact/StUWQHx7sp5n2t5dy1GgAf · 逐頁完整 spec `docs/postriff-app-update-plan/pages/` · 研究 `docs/postriff-app-update-plan/research/` · 再生成用嘅資料同 script 唔入 repo

---

## 0. 一句講完

**App 嘅骨架同後端已經到位，缺嘅係「每一頁都完整、每一頁都教人用、每一頁都有真數據喺度郁」。** 今次將 24 個 surface 逐一補齊最新版 design spec、technical requirements 同 features，再加兩條橫跨全 app 嘅線：一套教第一次用嘅人嘅 onboarding，同一個「唔 static、但唔扮數據」嘅 motion 層。

| 有覆核 spec | 今次已落實 | 部分落實 | 只出計劃 |
|---|---|---|---|
| 24 | 18 | 2 | 4 |

---

## 1. 今次落實咗乜

全部喺 web/ 入面，未 commit。全 app typecheck 0 error、lint 0 error，production build 50 條 route 全部通過。每頁喺實作階段都有瀏覽器驗證（自己嘅 tab，或者擋住所有寫入 request 嘅 headless browser）；最後一輪 review 修正之後 :3100 dev server 被停咗，所以嗰一輪靠 typecheck 同 build 確認。全程冇撳 approve、schedule、send。

- **Onboarding 系統。** 首次入 app 有 welcome dialog 同教學短片；9 步 welcome tour 跨 6 頁；轉頁時先亮起 sidebar link，由用戶撳「Open」先轉；18 頁有自己嘅 tips；header 加咗 help menu，⌘K 搵到 tour 同 Reset tips。
- **HyperFrames 教學短片。** 8 秒無縫 loop，示範一句說話變成每個 channel 一份 draft、兩份批准、入 calendar；light 同 dark 各一版，冇假數字、冇人名。
- **Home 背景粒子場。** 跟住滑鼠推開，打字時變安靜，標題後面變淡；觸控裝置減半而且唔郁；reduced motion 時唔畫。
- **逐頁重砌。** 18 頁完成：Channels、Overview、Analytics、Calendar、Ideas、Queue、Pipeline、Library、Inbox、Roles、Members、Audit、Brand、Memory、Usage & plan、Privacy & data、Models & providers、API & integrations。後 12 頁每頁都經過獨立 code review，review 搵到嘅 3 個嚴重問題同 24 個中度問題已經修正。
- **App shell。** Home 右欄說明終於顯示返 Home 自己嘅內容；header 喺 768 同 1024px 唔再撐爆頁面；Create 掣統一去 Home composer；Channels 支援由其他頁 deep link 打開 Connect sheet。
- **研究同覆核。** 24 份頁面 spec、onboarding／motion／settings-API 三份專題研究、一份 completeness critic，每份都有獨立 agent 核對 file:line 同重新 fetch 來源。

## 2. 原則（每一頁 spec 同實作都跟）

1. **真數據先郁。** 數字、狀態、進度、計時全部讀 snapshot 或 API；「Unavailable」永遠唔變 0；冇假 loading 字眼、冇模擬進度。
2. **提醒，唔阻止。** 規則只可以喺 draft 上加 reminder；缺事實就去 research；永遠唔會有一個 failed run。
3. **General，唔 personal。** Ship 畀每個用戶嘅嘢（template、tour 文案、例子、empty state）要令 designer、老師、店主、developer 讀落一樣。
4. **Capability honesty。** 每條 channel 逐項能力分開評級（Direct／Assisted／Unsupported + evidence + verifiedAt），永遠唔出現一個混合嘅「Connected ✓」。
5. **Motion 規則**（`docs/postriff-motion-system.md` §5）：先用現有 inventory；收快過開（開 250ms、收 150ms）；stagger ≤ 40ms、總長 ≤ 300ms；只郁 transform／opacity；尊重 reduced motion；純裝飾 motion 唔讀任何數據。
6. **權限喺 UI 只係遮掣，enforce 喺 API。** 權限已經由 `web/src/lib/workspace/provider.tsx` 用真 membership 推算（`access.tsx` 頂嘅 stub 註解過時）。
7. **Empty state 係教學。** 每頁 loading／error／empty／有數據四種狀態分開設計；empty state 講清下一步。

## 3. 逐頁總表

Spec 成熟度係研究時嘅狀態；「今次」係執行之後嘅狀態。每頁完整內容（design spec、technical requirements、features、onboarding 步驟、next steps、覆核記錄）喺附錄檔案。

| # | 頁面 | Route | Spec 時成熟度 | 今次 | 摘要 | 完整 spec |
|---|---|---|---|---|---|---|
| 1 | App shell（sidebar、header、⌘K、右欄） | `/app/* (shell)` | 部分完成 | 部分落實 | Help menu、⌘K tour actions（連 Reset tips）、header 窄屏唔撐爆、Home 右欄內容、Create 入口已改；19 套 tour 註冊；Settings 重組、mobile tab bar、shortcut 去重未做。 | [pages/01-shell.md](postriff-app-update-plan/pages/01-shell.md) |
| 2 | Home（Agent Chat） | `/app` | 部分完成 | 部分落實 | 背景粒子場、tour 錨點、右欄說明已落實；home-view.tsx 本身由另一個 session 擁有，誠實狀態 pass 同 capability chips 留待佢哋。 | [pages/02-home.md](postriff-app-update-plan/pages/02-home.md) |
| 3 | Agent conversation | `/app/agent/[conversationId]` | 部分完成 | 只出計劃 | conversation-view.tsx 同 variant-card.tsx 正由另一個 session 修改，今次只出 spec。 | [pages/03-conversation.md](postriff-app-update-plan/pages/03-conversation.md) |
| 4 | Overview | `/app/overview` | 部分完成 | 今次已落實 | 每個 query 出錯顯示 Unavailable 同 Retry；Next up + 7 日 strip；attention 單一口徑；Channels 卡逐項 level；Recent activity 人話化。 | [pages/04-overview.md](postriff-app-update-plan/pages/04-overview.md) |
| 5 | Ideas | `/app/ideas` | 部分完成 | 今次已落實 | 變成 source library：capture 四種、filters 真計數、inspector（事實批准、policy、公開使用批准、長按撤回）、Draft now 交去 agent 對話。 | [pages/05-ideas.md](postriff-app-update-plan/pages/05-ideas.md) |
| 6 | Calendar | `/app/calendar` | 部分完成 | 今次已落實 | 九種誠實狀態（held、expired、stale 唔再消失）、錯誤同空狀態、live legend filters、有 job 發送時 30 秒自動更新。 | [pages/06-calendar.md](postriff-app-update-plan/pages/06-calendar.md) |
| 7 | Pipeline | `/app/pipeline` | 部分完成 | 今次已落實 | deriveBoard 保證冇嘢會消失；Needs you 同 platform filter 用真計數；card detail sheet（revision、events、receipt）；Set aside 有確認；手機單欄、桌面五欄；有 job 發送緊先自動更新。 | [pages/07-pipeline.md](postriff-app-update-plan/pages/07-pipeline.md) |
| 8 | Library | `/app/library` | 部分完成 | 今次已落實 | 多檔同拖放上載（按真實階段顯示進度）、Used／Unused 真計數、image detail（大小、fingerprint、用喺邊個 post）、搜尋、縮圖 Retry，另外起咗可重用嘅 AssetPicker。 | [pages/08-library.md](postriff-app-update-plan/pages/08-library.md) |
| 9 | Channels（+ Connect） | `/app/channels` | 部分完成 | 今次已落實 | 問題排先、六項 capability chips 連證據、Connect sheet、History sheet、連接後自動捲到新卡並播一次成功動畫、deep link。 | [pages/09-channels.md](postriff-app-update-plan/pages/09-channels.md) |
| 10 | Queue | `/app/queue` | 部分完成 | 今次已落實 | 兩件事一眼睇晒：乜嘢等你批、每個 post 去到邊。Approve all（最多 10 個）有逐項確認；held 同 stale 唔再消失；撳 job 開完整 receipt（?job=）；filter 同 account 存 URL；有 job 發送緊時 15 秒自動更新；所有批准動作要 approve 權限。 | [pages/10-queue.md](postriff-app-update-plan/pages/10-queue.md) |
| 11 | Analytics | `/app/analytics` | 部分完成 | 今次已落實 | Coverage 由真 capability 計、每個 provider 一張表（native metric 永不相加）、Unavailable 唔變 0、四種 empty state、post sheet。 | [pages/11-analytics.md](postriff-app-update-plan/pages/11-analytics.md) |
| 12 | Inbox | `/app/inbox` | 未 set up | 今次已落實 | 逐 account 顯示 comments／reply 能力同證據；兩欄 layout（手機用 sheet）；Unanswered／Replied；批准 dialog 顯示真正會送出嘅文字；未有 sender 就照實寫「sending is not switched on yet」。 | [pages/12-inbox.md](postriff-app-update-plan/pages/12-inbox.md) |
| 13 | Members | `/app/workspace/members` | 部分完成 | 今次已落實 | 同 Roles 共用 access sheet；Members 頁即時 bug 修正，invite 同 invitations 狀態講清楚。 | [pages/13-members.md](postriff-app-update-plan/pages/13-members.md) |
| 14 | Roles | `/app/workspace/roles` | 未 set up | 今次已落實 | Your access、五張 role 卡（真持有人數）、共用 access sheet（改之前確認）、permission matrix（By role／By grant）、邊啲操作要重新登入、最近權限變動。 | [pages/14-roles.md](postriff-app-update-plan/pages/14-roles.md) |
| 15 | Audit log | `/app/workspace/audit` | 未 set up | 今次已落實 | 21 種事件人話化、按類別同人篩選（存 URL）、講明載入咗幾多（API 上限 200）、detail sheet、empty state 教點樣會有紀錄。 | [pages/15-audit.md](postriff-app-update-plan/pages/15-audit.md) |
| 16 | Brand & voice（voice setup） | `/app/workspace/brand` | 部分完成 | 今次已落實 | Status strip（active revision、依賴佢嘅 draft 同 post 數）、proposal 卡（owner 批准前睇影響）、identity 同 voice、連去 Memory 嘅 What drafts read、revision 歷史。 | [pages/16-brand.md](postriff-app-update-plan/pages/16-brand.md) |
| 17 | Memory | `/app/workspace/memory` | 部分完成 | 今次已落實 | Files 分「Given to writing routes」同「For you to read」；viewer 講明邊個 writer 收到；cloud 同 web research 開關要確認；What drafts read；learning 歷史。 | [pages/17-memory.md](postriff-app-update-plan/pages/17-memory.md) |
| 18 | Profile | `/app/account/profile` | 已成形 | 只出計劃 | Security、passkeys、preferences 正由另一個 session 開發，今次只出 spec。 | [pages/18-profile.md](postriff-app-update-plan/pages/18-profile.md) |
| 19 | Notifications | `/app/account/notifications` | 部分完成 | 只出計劃 | notifications-view.tsx 正由另一個 session 修改，今次只出 spec。 | [pages/19-notifications.md](postriff-app-update-plan/pages/19-notifications.md) |
| 20 | Usage & plan | `/app/account/billing` | 部分完成 | 今次已落實 | 狀態讀 lifecycle；Unavailable 同 Not included 分清；checkout 返嚟後 backoff polling 等 provider 確認；allowances、plans、ledger（人話標籤、$0 run 標明）。 | [pages/20-billing.md](postriff-app-update-plan/pages/20-billing.md) |
| 21 | Privacy & data | `/app/account/privacy` | 部分完成 | 今次已落實 | Holdings 真計數、egress 開關、完整 privacy notice、export 後喺瀏覽器計 SHA-256 fingerprint、diagnostics 先預覽、撤回 source 前列出真實影響、刪 account 前 pre-flight。 | [pages/21-privacy.md](postriff-app-update-plan/pages/21-privacy.md) |
| 22 | Models & providers | `/app/account/models` | 部分完成 | 今次已落實 | Writing now（你而家用緊邊個 writer、邊個畀錢）、完整 sign-in 狀態、managed／CLI／preview 清楚分開、Check again、付費同 consent 說明。 | [pages/22-models.md](postriff-app-update-plan/pages/22-models.md) |
| 23 | API & integrations | `/app/account/api` | 未 set up | 今次已落實 | 只顯示真實存在嘅嘢：狀態數字、逐 account capability、tool registry；tokens、webhooks、AI agent server 用「Not available yet」講清楚將來嘅規則，冇假 key。 | [pages/23-api.md](postriff-app-update-plan/pages/23-api.md) |
| 24 | Auth：sign-in、sign-up、invite accept、MFA | `/auth/*, /invite/[token]` | 部分完成 | 只出計劃 | auth-form 同 MFA 正由另一個 session 修改，今次只出 spec。 | [pages/24-auth.md](postriff-app-update-plan/pages/24-auth.md) |

### 3.1 每頁 P0 features

- **App shell（sidebar、header、⌘K、右欄）**：⌘K 權限過濾修正 + nav shortcut 去重；共用 attention selector + Channels count + snapshot 新鮮度；Route boundaries（error.tsx、not-found.tsx、[...slug] catch-all）；Workspace switcher v2：真名、plan pill、invitations、leave、切換後 route 檢查
- **Home（Agent Chat）**：Info sidebar 顯示 Home 自己嘅「How the agent works」+ mobile 入口；Home 誠實狀態：unavailable 永遠唔變 0 / not set up / No conversations；Channel chips 讀 capability matrix（Direct / Assisted / Bridge / 未接）
- **Agent conversation**：Route states：loading / error / 404 empty + title Skeleton；權限對齊：Cancel / 寫入掣按 edit / approve / owner gating；Thread 自動跟到底 + Jump to latest；Responsive：rail / inspector Sheet + sticky composer；Chips 同 plan rows 讀 capability matrix（連 evidence）；Failed / stalled run 嘅 Try again；Motion 合規修正（strip 同 plan rows 總長 ≤300ms）；Variant Copy + inline Edit
- **Overview**：Honest error states（Unavailable ≠ 0）；Next up card（下一個 approved slot + 今個星期 7 日 strip）；Attention 單一口徑（Home + Overview 共用 deriveAttention，含 access 過濾同 held）
- **Ideas**：Source inspector：facts approve + policy + cloud + 公開使用批准；收窄 source 改動嘅 staleness（或真數提醒）；Capture without drafting（Idea / Paste text / Link / File → `source` action）；Draft from this source → 交去 /app/agent/[id]；Provenance 同 unknowns 真值顯示
- **Calendar**：誠實嘅狀態：held、expired review、stale review 各自有 kind 同顏色；Error state 取代空月曆；喺 popover 直接 Approve & schedule／Hold to cancel／Prepare again；由任何一日開始 schedule（header「Schedule a draft」+ 格內「+」+ DayPanel footer）
- **Pipeline**：Nothing vanishes：deriveBoard 保證 held／failed／cancelled／stale／retracted／set-aside 全部可見；誠實嘅 Queue 欄：waiting／publishing／uncertain／held 分開 badge，synthetic 標「Fixture」，欄底「Cancelled or failed · N」；權限正確嘅 actions：Edit／Set aside（edit）、Schedule…（edit + approve）、Cancel（approve）、viewer 同 sample workspace 冇 mutate；Card detail sheet：全文、preview、revision history、job events、provider receipt、nextAction；真 loading／error／empty states + 每欄教學句；保持「唔 drag」，用明確 action 代替拖拉
- **Library**：Editor／admin 都可以上載同刪除（修 owner-only guard）；Media 路徑補 sample read-only 檢查；多檔 + 拖放上載，進度係真計數；Newest first 排序；Used / Unused filter + 卡上 usage chip（去重）；Asset detail sheet：provenance + Used in + 下一步；誠實統計 + 修正 info sidebar 文案
- **Channels（+ Connect）**：Re-verify 寫返真狀態 + hosted 一小時規則修正（backend）；Additive capability grant + 過渡期 reminder；Commit 已做好嘅 Channels 前端（按 path）
- **Queue**：Honest loading and error states；Permission-honest actions；Held and uncertain jobs visible with their real reason；Live refresh while something is moving；Job detail sheet with the full receipt and a deep link
- **Analytics**：生產數據路徑：verified 後讀 + 固定時間表再讀；Types 對齊 + summary hardcode 清理；Capability-honest coverage strip；以 post 為單位 table + 四個 empty state
- **Inbox**：Capability matrix merge：同一 account 可以同時 publish + comments_read + reply；真 pipeline：production ingestion + worker 送 approved replies + verification；Approval 誠實修正：Dialog 顯示 manifest.text、textarea 同 draft 同步、error 唔卡 skeleton；Reply 狀態持久化 + receipt timeline + Unanswered / Replied filter（真 counts）；Coverage strip + 有 account 名嘅 empty state；「Check for new comments」手動 sync + 真 lastSyncAt；Suggestion 掣誠實化：先改名「Insert a starter line」，再接真 model；Permission 對齊：nav 所有 member 可入；Save/Suggest gate edit、Send gate reply，文案講清楚邊個做到乜
- **Members**：真身份：名、avatar initials、加入時間、「Invited as」；Error / access 狀態修正；Invite dialog + permission preview；Step-up 用 dialog 處理；之後可以改 grants；Revoke 要確認；每行 overflow menu；修正 role 改動 403；Invitations Pending / History，Resend，Empty
- **Roles**：Matrix 由 API 提供（`GET /api/permissions`），唔再手抄；「You in this workspace」自我定位 panel；開放俾所有 member（移除 nav gate，page gate 改 hasWorkspace）；每個 role 嘅 live active member count + solo 提示；Permission 行 anchor + 其他頁 deep link
- **Audit log**：人話 rows：describeAuditEvent + actorName + 每行 deep link；誠實 states + 真計數 + 權限對齊；Publishing 決定同結果入 trail（post.approved / post.cancel_requested / post.published / post.failed / post.held / post.uncertain / post.canceled）
- **Brand & voice（voice setup）**：修 brand-view 唔誠實 copy + RBAC gate + sample 唯讀；Setup stepper：三步 + review，general 文案，『draft 照做、scheduling 等』reminder；Active 狀態可以改：Identity edit、identity sentence、Voice revise，confirm 前顯示真實 impact 數；Status strip + 『What drafts read』preview；修 Export：backend 對冇 packageSchema 嘅 profile 出 memory 檔 zip；Brand/Memory 顯示 server 原因；Revision history + Restore（owner）
- **Memory**：Prompt 真相：Files 分「Given to writing routes」同「For you to read」，移除假 badge；誠實狀態：每個 region unavailable + Retry、修 viewer 假 pulse、expiry、Decided tab；Export memory files（新 endpoint）；Learned preferences 三段 tabs + HoldActionButton reset
- **Profile**：Capability-honest channel rows；認得出嘅 device 名 + First seen
- **Notifications**：Delivery status 讀 server；「Recent notifications」ledger 清單（sent / not delivered / recorded only）；「Waiting for you」live 清單，共用 `useAttention()`，按權限過濾，加 held / 近期 failed jobs；Switch error 誠實化
- **Usage & plan**：誠實狀態模型：badge 讀 lifecycle.status；trial 寫 ends；缺數據寫 Unavailable；total 0 寫 Not included；amber 按 meter mode 判斷；Checkout 返嚟真確認：backoff polling 直到 lifecycle.status=active，badge loading→success，逾時轉 warning；Plans：每個 plan 一張卡；footer 用 hasOpenSubscription 對齊 backend 409；副標由 provider 派生；Error state + retry；loading 交俾 PageContainer；stale 數據標示
- **Privacy & data**：Honest export receipt：一次 build、瀏覽器核對 SHA-256，相同先話 Verified；Retract a source（呢頁 + per-source receipt）；Diagnostics package 先睇後落地，講明冇送去任何地方；Delete pre-flight：in-flight / scheduled 真數、owner gate、step-up 處理；Data requests table 讀得明
- **Models & providers**：Rescan 真係 rescan（force probe + probedAt + StatefulButton）；完整 auth state 詞彙 + Codex budget 誠實化；誠實 route inventory：kind、host、costClass、consent 前提、per-route reasoning；billing 文案由 API 生成；fixture stub 唔再同真 managed route 撞；Catalog 收返做登入後先攞 + page access gate
- **API & integrations**：Personal access tokens（workspace-scoped，read + draft，必有 expiry，一次過顯示，長按 revoke）；Access status strip 全部讀 API；Tool registry card 讀 /api/tools，isolated 同 publicInvokeEnabled 分開顯示；Connected accounts 逐 capability + providers review 狀態分開講（取代靜態 Integration surface）；Page-level access gate + create 要 step-up
- **Auth：sign-in、sign-up、invite accept、MFA**：Invite 頁登入前睇到邀請內容（preview endpoint）+ mfa-required 分支；2FA 第二步搬去 `/auth/verify`

## 4. Onboarding／tutorial

三層教學，冇一層會阻住做嘢：welcome dialog（可以 Not now）、guided tour（隨時 Skip）、每頁 tips（一次 toast，之後喺 help menu）。研究比較過 react-joyride、NextStep、driver.js、Onborda、Shepherd、intro.js，最後自己砌：因為只有自己砌先做到「由 sidebar link 同一個框 morph 去下一頁」，而且 Shepherd 同 intro.js 係 AGPL。

### 4.1 三層教學

| 層 | 幾時出現 | 形式 | 點樣收 |
|---|---|---|---|
| Welcome | 第一次入 app（workspace ready，唔喺對話頁） | Dialog：HyperFrames 教學短片 + 三句產品說明，「Take the two-minute tour」／「Not now」 | Not now 記住；已經 set up 好（voice + channel + 排咗程）嘅 workspace 唔彈 dialog，改為一次 toast |
| Welcome tour | 用戶揀開始，或者 help menu、⌘K | 9 步跨 6 頁 spotlight | Esc／Skip 隨時結束；完成記錄 |
| Page tips | 第一次入一頁（welcome 已決定，而且 tour 未行過呢頁） | 一次 toast「New to …? · Show me」 | 8 秒消失；help menu「Tips for …」重開 |

### 4.2 Welcome tour 步驟

| # | 頁面 | 標題 | 轉頁 |
|---|---|---|---|
| 1 | Home | Say what you want to put out | 同一頁 |
| 2 | Home | Channels you can draft for | 同一頁 |
| 3 | Home | 11 kinds of post to start from | 同一頁 |
| 4 | Channels | One card per account, one level per capability | 先亮 sidebar link，再由用戶撳 Open |
| 5 | Queue | Nothing publishes on its own | 先亮 sidebar link，再由用戶撳 Open |
| 6 | Calendar | Your week at its exact times | 先亮 sidebar link，再由用戶撳 Open |
| 7 | Brand | Your voice | 先亮 sidebar link，再由用戶撳 Open |
| 8 | Overview | Four steps to your first scheduled post | 先亮 sidebar link，再由用戶撳 Open |
| 9 | Overview | Come back any time | 同一頁 |

### 4.3 Navigate animation 點做

- 下一步喺另一頁時，spotlight 移去 sidebar 入面嗰頁嘅 link，link 用一個 ring 脈動兩次再停；卡片寫「Next: Channels · Channels lives in the sidebar under Distribute」。
- 用戶撳「Open Channels」（或者直接撳亮咗嘅 link）先轉頁；冇計時器、冇進度條。
- 新一頁嘅 overlay 由同一個長方形開始，搵到目標就 spring morph 過去；搵唔到（權限收起、頁面空）就自動跳下一步。
- Sidebar section 閂住就自動打開，tour 完還原；手機就亮起 menu 掣。
- Tour 期間 app 係 `inert`，Tab 只喺卡片循環，每步有 aria-live 讀出；目標用 80ms timer 搵（背景 tab 嘅 animation frame 會停）。

### 4.4 規則

- 每步文案讀真 workspace 狀態；API 讀唔到嗰陣講一句仍然成立嘅說話，唔會變 0。
- 冇計時器、冇假進度條；轉頁一定係用戶撳掣。
- Sidebar section 閂住就自動打開，tour 完還原。
- Tour 期間 app 係 inert，Tab 只喺卡片入面循環，Esc 隨時結束。
- 進度按用戶記住；已經 set up 好嘅 workspace 唔彈 dialog，只出一次 toast。
- 下一步：進度存上 server（pr_profiles.onboarding）；Home 同 Conversation 嘅 tips 等擁有嗰兩個檔案嘅 session commit 之後補。

實作位置：`web/src/features/onboarding/`（`store.ts`、`tours.ts`、`use-tour-context.ts`、`tour-overlay.tsx`、`tour-mount.tsx`、`welcome-dialog.tsx`、`welcome-clip.tsx`、`help-menu.tsx`）、`web/src/styles/tour.css`、`web/src/components/kbar/index.tsx`。Target 約定：元素加 `data-tour="<id>"`，每步列 selector 順序試。完整研究：`research/onboarding-tutorial.md`。

## 5. Motion：唔 static，但唔扮數據

原則係「狀態變咗先郁，冇變唔郁」：每個動畫都由真數據、refetch 或者真時鐘觸發。純裝飾嘅 motion（粒子場）明確唔讀任何數據，免得被誤會係訊號。開 250ms、收 150ms，stagger 40ms、總長 300ms 以內。

| 用途 | 用咩 | 原因 |
|---|---|---|
| Live UI：狀態、數字、轉頁、tour spotlight | motion v11 + transitions.css tokens + 32 個 beUI component | 要跟真數據同即時回應，要 reduced motion |
| 環境裝飾：Home 粒子場 | 手寫 Canvas 2D（約 300 行） | tsParticles 太重、WebGL 對 120 粒冇好處 |
| 教學短片、empty state 插圖、marketing loop | HyperFrames render 成 webm／mp4 + poster | 預先 render，前端零成本；Apache-2.0 |
| Remotion | 唔引入 | repo 冇 Remotion source；超過 3 人公司要 company license |
| 任何顯示真數字嘅動畫 | 永遠唔用影片或 Lottie | 影片入面嘅數字一定係假 |

### 5.1 Home 背景粒子場（已落實）

- `web/src/components/motion/particle-field.tsx`：Canvas 2D，跟 theme（`currentColor`），最多 60fps，tab 隱藏或者捲出畫面就停，reduced motion 完全唔畫，Save-Data 只畫一格。
- 觸控裝置粒子減半、冇連線、唔跟手指；滑鼠離開視窗即放手；連線分三批 stroke。
- `web/src/app/app/home-backdrop.tsx`：focus 喺 composer 時變安靜，標題後面變淡，手機高度 28rem、桌面 44rem。

### 5.2 HyperFrames 教學短片（已落實）

- 原始檔：`motion/onboarding-welcome/`（composition、BRIEF、README 有 re-render 指令）。
- 輸出：`web/public/onboarding/welcome-loop-{light,dark}.{webm,mp4,jpg}`，896×560、8 秒、每個約 240KB。
- 內容：composer 打字 → 三張 draft 卡（LinkedIn、Instagram、Threads）→ 兩張 Approve、Threads 保持 draft → 入 week calendar → 返回空白 composer（無縫 loop）。冇數字、冇人名、冇 account。
- 下一步：同樣方法做 3–4 段 empty state 短片（Channels capability、Queue 批准、Memory proposal），每段 ≤ 8 秒、≤ 400KB，片內盡量唔放文字方便翻譯。

### 5.3 逐頁「alive」時刻

每頁 spec 嘅 design specification 都有一張 Motion moments 表（element、trigger、behaviour、reuse、係咪讀真數據）。原則係每頁 1–2 個、由狀態變化觸發、先用 inventory（AnimatedBadge、DigitSwap、NumberTicker、Tabs、StatefulButton、HoldActionButton、SuccessCheck、Sheet）。完整研究：`research/motion-hyperframes-particles.md`。

## 6. Settings 同 API & integrations

研究建議將 Workspace 同 Account 兩組收做一個 Settings 區（/app/settings/[section]，左邊 rail 分 Personal／Workspace／Developer），Brand 同 Memory 留喺主 sidebar 開一個 Voice 組、URL 唔變。Critic 建議分兩步：今個星期只修 bug，下一階段先搬 route，免得同其他 session 撞。

### 6.1 Sidebar：而家 vs 建議

**而家（21 項）**


- **Create**：Home、Overview、Ideas、Calendar、Pipeline、Library
- **Distribute**：Channels、Queue
- **Grow**：Analytics、Inbox
- **Workspace**：Members（建議搬入 Settings）、Roles（建議搬入 Settings）、Audit log（建議搬入 Settings）、Brand、Memory
- **Account**：Profile（建議搬入 Settings）、Notifications（建議搬入 Settings）、Usage & plan（建議搬入 Settings）、Privacy & data（建議搬入 Settings）、Models & providers（建議搬入 Settings）、API & integrations（建議搬入 Settings）

**建議（主 sidebar 13 項）**

- **Create**
  - Home
  - Overview
  - Ideas
  - Calendar
  - Pipeline
  - Library
- **Distribute**
  - Channels · 要處理嘅 account 數
  - Queue · 待批數
- **Grow**
  - Analytics
  - Inbox · 未覆數（有真 ingestion 先顯示）
- **Voice**
  - Brand & voice（URL 不變）
  - Memory（URL 不變）
- **Settings（sidebar 底部）**
  - Personal：Profile、Notifications、Privacy & data、Models & providers
  - Workspace：General（新）、Members、Roles、Audit log、Usage & plan
  - Developer：API & integrations、Companion（ship 咗先出）

### 6.2 API & integrations 點樣運作

- 今次落實嘅頁面只顯示真實存在嘅嘢：tool registry、每個 account 逐項 capability、provider 審批狀態；未有嘅功能用「Not available yet」卡講清楚，冇假 key、冇假 endpoint。
- API key 只可以 read、draft 同提出 schedule；永遠唔可以 approve、publish、reply、connect。每次 request 用「建立者當刻權限 ∩ key scope」重新計，建立者離開 workspace 就即時失效。
- Key 一次過顯示、有前綴同到期日、記 last used、長按 revoke，建立同 reveal 要 step-up 再驗證。
- Webhooks 跟 Standard Webhooks：thin event（只有 id 同數字）、簽名、rotation 期間雙簽名、送出前重新檢查權限，delivery 用獨立 cron。
- MCP server 分兩期：先接受 API key bearer，之後做 OAuth 2.1（PRM + CIMD，DCR 做 fallback）。
- Zapier／Make／n8n 等 API v1 穩定先做；desktop companion 未接通前照實寫「未開放」。

完整研究（包括 migration、routes、權限檢查、MCP spec 細節）：`research/settings-and-api.md`。

## 7. 分階段計劃

### Phase 0 · 協調同共用 module（第 1 日）

十幾份 spec 各自定義 job state 同 attention，唔先定位置就會出五份常數同 merge conflict；未 commit 嘅改動隨時會畀其他 session 洗走。

- [ ] 決定邊個 session commit 今次嘅改動（按 path stage）
- [ ] 一份 job state 真相：web/src/lib/jobs.ts（而家 Overview、Queue、Pipeline 各有一份）
- [ ] 一份 attention 真相：web/src/lib/attention.ts（Overview 已經寫好 deriveAttention，可以直接搬）
- [ ] Error code contract：AlphaError(code=) + ApiError.code

### Phase 1 · Onboarding、motion 同四個重點頁（今個星期）

你指定優先做 onboarding、動態感，同 Channels、Inbox、Analytics、API 呢幾頁；大部分係前端。

- [x] Onboarding tour v2 + help menu + ⌘K
- [x] Welcome 教學短片（HyperFrames）
- [x] Home 粒子場 + 6 項修正
- [x] Channels 前端重砌 + deep link
- [x] Analytics 前端重砌
- [x] Header 窄屏、Home 右欄、Create 入口
- [x] Inbox 誠實修正同 two-pane
- [x] API & integrations 誠實頁
- [ ] Backend：Re-verify 寫返狀態、一個鐘規則、capability additive merge
- [ ] Shortcut 去重（Home 同 Channels 都係 h h）、app error／not-found

### Phase 2 · 跨頁誠實度同 Settings 重組（下 1–2 星期）

將共用 module 落地到其餘頁面；Settings 重組涉及 URL，要等 tour commit 之後先做。

- [x] Overview、Calendar、Ideas 重砌
- [x] Queue、Pipeline、Library、Roles／Members、Audit、Memory、Brand、Usage、Privacy、Models
- [ ] 共用 JobDetailSheet、ReviewApproveButton、JobCancelHold
- [ ] Settings 區 + redirects + mobile tab bar + 通知 bell + shortcuts dialog
- [ ] Auth：/auth/verify、/auth/reset、invite 後按權限導向
- [ ] API key migration + security review

### Phase 3 · Backend-heavy（2–4 星期）

要 migration、worker、外部 provider 或者產品決策。

- [ ] Inbox 真 pipeline：ingestion、worker 送 reply、reconcile
- [ ] Analytics 讀數時間表（1h／1d／3d／7d／28d）
- [ ] Audit 讀寫兩邊（等你決定權限）
- [ ] Privacy export receipt、Billing checkout polling backend、Models 真 rescan
- [ ] Workspace creation、worldwide languages slice 2 同 5

### Phase 4 · 護城河同國際化（持續）

依賴 Phase 3 嘅 audit、token 同 capability 基建。

- [ ] Desktop companion pairing
- [ ] Webhooks + MCP server
- [ ] 介面語言 i18n、server-side 搜尋、channel detail route

Critic 嘅完整跨頁缺口、矛盾同次序：`research/completeness-critic.md`。

## 8. 要你決定嘅事

1. **Job 嘅 published 狀態點計**：Backend 同 header Live Island 當 published 係「仲發送緊」，Overview 當係「已完成」，所以兩邊數字可以唔同。揀一個口徑，其中一邊就要改。（`src/postriff_phase2/store.py:19 · live-island.tsx · overview`）
2. **冇 active voice 就唔准批准**：store.py 而家硬性拒絕，同「提醒，唔阻止」有張力。Tour 暫時用提醒語氣如實講。（`src/postriff_phase2/store.py:359`）
3. **Audit log 邊個睇得**：Nav 限 admin，但 API 同 RLS 任何 member 都讀得。要定：邊個睇、可唔可以 export、保留幾耐。（`nav-config.ts · hosted.py audit()`）
4. **API key 可唔可以直接發佈**：競品（Blotato）嘅 MCP 可以直接 publish。建議第一期唔可以；將來要開就限 owner、要 MFA、只批已 review 嘅 manifest、每日有上限。（`docs/postriff-app-update-plan/research/settings-and-api.md`）
5. **Settings 重組幾時做**：主 sidebar 由 21 項減到 13 項，舊 URL redirect。涉及 tour 同其他 session 嘅 WIP，建議 Phase 2。（`research/settings-and-api.md · research/completeness-critic.md`）
6. **Inbox 同 Roles 開放俾所有 member**：兩份 spec 都建議所有 member 入得，頁內 action 再按權限遮掣。（`web/src/config/nav-config.ts`）
7. **Source 改動嘅 staleness**：而家儲一個新 source 會令所有 draft 變 stale。收窄會影響 Queue、Calendar、Pipeline 嘅規則。（`pages/05-ideas.md`）
8. **Billing 規則**：Reconcile 係咪只喺新 period 補滿？Trial 完係咪真係停 publishing？舊 plan assist-bounded-v1 要唔要 retire？（`pages/20-billing.md`）
9. **撤回一個 source 嘅影響範圍**：而家撤回任何一個 source（就算冇 draft 用佢）都會令全 workspace 嘅 draft 要重新起稿，後端文案同 Ideas 頁都低估咗。Privacy 頁已經照實列出；要決定係咪收窄。（`src/postriff_phase2/hosted.py:462 · privacy.py`）
10. **Plan 限制要唔要 enforce**：lifecycle.canPublish 有計但冇用：trial 完、取消訂閱都照樣發佈；member 同 connected account 上限亦冇擋（dev workspace 2 個 member，plan 只容許 1 個）。頁面而家只出提醒。（`src/postriff_phase2/billing.py`）
11. **Editor 可唔可以上載同刪圖**：後端圖片上載同刪除只准 owner，團隊 workspace 嘅 editor 同 admin 用唔到 Library。頁面已經照實講。（`src/postriff_phase2/hosted.py:226/234/244`）
12. **未有 sender 之前准唔准批准 reply**：Inbox 撳「Approve reply」會記錄一個 approved reply，但冇 worker 會送出；將來 worker 上線時可能一次過送晒舊嘅批准。（`src/postriff_phase2/audience.py · hosted_worker.py`）
13. **邊個 commit 今次改動**：全部仲未 commit。好多 session 共用同一個 working tree，建議由一個 session 按 path stage。（`git status`）

## 9. 做嘢時發現嘅問題

- **Home quick start 可能用舊 idea 起稿。** quick_start 傳空 text 入 turn，turn 會用 workspace 儲低嘅舊 idea。
- **第二次 OAuth 授權會降級。** 例如加 analytics 權限時，publish 由 Direct 打回 Assisted，scopes 亦會唔見。
- **Re-verify 冇寫返狀態。** Hosted OAuth channel 一個鐘後會變「Finish setup」，排唔到程。
- **Analytics 冇讀數。** Production worker 冇接 on_verified，summary 又寫死 LinkedIn 句子同 state。
- **Calendar 用瀏覽器時區。** 唔係 profile 設定，同 Overview 嘅 7 日 strip 可能差一日。
- **Queue 權限。** Schedule a draft 掣 editor 都見到，但 server 要 approve（已交 Queue 重砌一齊修）。
- **Dev API 過期。** 運行中嘅 dev API 未有 memory/proposals route（404），重開 API 就有，但會清空 dev DB。
- **Models 目錄唔使登入就讀到。** GET /api/ideas/models 會公開 API 機器嘅 CLI 版本、登入方式同環境變數名（hosted_app.py:303），建議搬到登入之後。
- **Privacy notice 漏咗外部服務。** privacy.py 只列 4 個 subprocessor，Stripe、Resend、Exa、Jina 同 Vercel AI Gateway 都冇列。
- **重複 review 靜靜哋卡住。** 同一個 draft、account、時間準備兩次 review，server 會令第二個永遠等緊。
- **Voice 相關權限。** profile_propose 唔檢查 active revision，you_restore_voice 唔係 owner-only。
- **Inbox 冇 production ingestion。** 讀 comments 嘅 ingest_replies 只喺 dev harness 有 call。

## 10. 共用檔案要改嘅嘢

實作 agent 只准改自己 feature folder，以下係佢哋列出、需要改共用檔案先做得乾淨嘅改動（有其他 session 同時改緊呢啲檔案，所以今次冇直接改）：

| 檔案 | 點解 | 由邊頁提出 |
|---|---|---|
| `web/src/config/nav-config.ts` | Ideas icon 唔再同 Home 共用 sparkles；Home 同 Channels shortcut 都係 h h | ideas · shell |
| `web/src/components/ui/info-button.tsx` | content 只喺 mount 時設定，之後嘅數據變唔到；改用 keyed effect | ideas |
| `web/src/components/application/calendar/*` | calendar-period-nav、calendar-view-select、calendar-zone、calendar-event 四個 tour 錨點 | calendar |
| `web/src/lib/attention.ts（新）` | 將 features/overview/attention.ts 搬出嚟，Home 同 sidebar badge 共用 | overview |
| `web/src/lib/jobs.ts（新）` | Overview queue-status.ts、Queue job-state.ts、Pipeline job-state.ts 三份 job state 合併；live-island.tsx 改 import | overview · queue · pipeline |
| `web/src/features/account/profile-model.ts` | channelBadge／needsReconnect 改為 re-export web/src/lib/channels/state.ts | channels |
| `web/src/lib/api/types.ts` | OAuthComplete.connectionId、ChannelView.pictureDigest；AnalyticsPost.connectionId／contentTypeId、Analytics.families；SnapshotSource 嘅 facts／origin／useApprovals 等欄位（API 已經有，TS 未有） | channels · analytics · ideas |
| `web/src/lib/api/types.ts` | Declare the job, review and manifest fields the API already sends, so queue/job-state.ts can drop its narrow local QueueJob/QueueReview casts. | queue |
| `src/postriff_phase2/store.py (backend, for the founder or backend session)` | Approving a review whose post is already a job returns silently and leaves the review needs_review forever. Re-preparing the same draft, account and time after a cancelled or failed job gives the same idempotencyKey and can never be approved. | queue |
| `web/src/features/pipeline/job-state.ts` | One job vocabulary for both boards. | queue |
| `web/src/features/pipeline/pipeline-card.tsx` | scheduleGate blocks non-editors whenever proposedUpdate or needsReview is set. The Queue's dialog now lets them review a current draft whose waiting version is optional, and also blocks on unknowns. Aligning the two keeps the card and the dialog from disagreeing. | queue |
| `web/src/features/onboarding/tours.ts` | The page carries anchors for the spec's Queue tips, and the cancel step needs to know whether the viewer can approve. | queue |
| `web/src/features/calendar/calendar-view.tsx, web/src/components/layout/live-island.tsx, web/src/features/analytics/post-sheet.tsx` | The Queue opens a receipt from ?job=. Existing links go to the bare /app/queue. | queue |
| `web/src/lib/api/hooks.ts` | Optional. A refetchInterval option would let TanStack pause polling in the background by itself. | queue |
| `web/src/features/onboarding/tours.ts` | Registers the Pipeline page tour the spec asks for. Every anchor already exists. On a phone only the selected column is rendered, so each column step falls back to the board. | pipeline |
| `web/src/lib/api/types.ts` | The API already sends these fields; board.ts reads them through local narrow types (PipelineVariant/PipelineSource/PipelineReview/PipelineJob), which can go once the shared types declare them. | pipeline |
| `web/src/features/pipeline/edit-draft-dialog.tsx` | (1) With a proposed update, the text starts as proposedUpdate.text, so Save is enabled before any change. (2) 'Edit to restore' on a set-aside draft cannot save unchanged text, even though variant_edit accepts it and clears `rejected`. (3) Limits are hard-coded for 3 platforms although post-preview/limits.ts has sourced per-channel limits. (4) The language label is hard-coded. | pipeline |
| `web/src/lib/api/client.ts` | remove_member returns a `note` (hosted.py remove_member), but the client type drops it, so members-view reads it through a local cast. | roles |
| `web/src/config/nav-config.ts` | Roles is the one page that explains each person's limits. Every member can open it by URL, but the sidebar and ⌘K hide it from editors, approvers and viewers. | roles |
| `web/src/lib/api/hooks.ts` | Let callers skip queries, for example so non-staff never fetch invitations. The current workaround mounts the hooks only inside the gated child. | roles |
| `web/src/lib/auth/access.tsx` | The header comment still calls the access context a Phase A stub. | roles |
| `web/src/features/account/privacy (privacy-model.ts / delete-card.tsx) and any other page with a step-up error` | The same stale-sign-in trap applies anywhere a page sends a signed-in user to /auth/sign-in. web/src/features/workspace/use-change-error.ts could move to lib/auth (for example useSignInAgain) so Security, Channels (disconnect) and Privacy share one helper. | roles |
| `web/src/lib/api/types.ts` | Hosted assets carry these fields (media.py decode_upload, hosted_storage.py:119, hosted.py:239) and jobs carry approvalDigest (store.py:302). The Library reads them through a local LibraryAsset type and a cast. | library |
| `web/src/features/onboarding/tours.ts` | Registers the Library tips on the data-tour ids now on the page. | library |
| `web/src/features/onboarding/use-tour-context.ts` | Supplies assetCount for the Library tips' `when` checks. | library |
| `web/src/features/queue/schedule-dialog.tsx` | Lets 'Use in a post' in the Library open the dialog with the image already chosen, and swaps the hash-text Select for the thumbnail picker. | library |
| `web/src/components/providers (QueryClient setup) or a new web/src/lib/api/media.ts` | Media object URLs are never revoked (staleTime Infinity), so a large library keeps every blob in memory. Revoking at the cache level stays safe for every consumer of the shared key. | library |
| `src/postriff_phase2/hosted.py (backend, for the owner of that area)` | Editors and admins who pass require(edit) still get 403 on image upload and delete because the guard compares the bootstrap creator id. The Library shows an info alert to non-creator editors until this is fixed. The media path also skips the sample read-only check. Optional addition from this pass: a machine-readable code on the not-configured 503 (e.g. {"error": ..., "code": "media_storage_not_configured"}) would let the client stop matching message text. | library |
| `web/src/features/onboarding/tours.ts` | Add the new Inbox anchors to the existing inbox-tips tour (lines 410-424). Remove the old wording about sending, and the promise that any Direct account gets comments, since only Threads comments are read. | inbox |
| `src/postriff_phase2/oauth.py + web/src/lib/api/types.ts` | The page copies the 'only Threads comments are read' rule from audience.py:32 into model.ts (COMMENT_READ_PROVIDERS). The providers list should say this itself, so the front end can drop that copy when a second provider is added. | inbox |
| `src/postriff_phase2 (production worker wiring)` | Comment ingestion runs only from the dev harness's on_verified hook (scripts/postriff_dev_hosted.py:174-179). Nothing in src/ passes on_verified to PostgresWorker, so a hosted deploy never reads comments and the Threads empty-state sentence would be untrue there. | inbox |
| `web/src/lib/api/types.ts` | Declare the optional fields the page already reads through narrow local casts in model.ts, so the casts can go once the API sends them. | inbox |
| `web/src/config/nav-config.ts` | The Inbox item is hidden from anyone without reply (line 94), but drafting needs only edit and reading needs only read. An editor who can draft replies can't find the page. | inbox |
| `src/postriff_phase2/audience.py` | Two strings from the API are false today: the starter line is labelled AI, and the approve note promises a worker that doesn't exist. The UI works around both, but other clients would still show them. | inbox |
| `src/postriff_phase2/audience.py` | Needed for real Unanswered/Replied counts and reply status after a reload. The front end already reads these fields if present. | inbox |
| `web/src/lib/api/types.ts` | Shared types for the tool registry so the page's local types can be deleted. | api |
| `web/src/lib/api/client.ts` | The page lights up the tool registry card and the Tool runner tile as soon as `api.tools` exists (GET /api/tools is public, so auth=false). | api |
| `web/src/lib/api/hooks.ts` | Optional: a shared hook with the same query key the page already uses (['tools']), so switching over later does not split the cache. | api |
| `web/src/lib/channels/state.ts` | Found while fixing the review issue: channelCounts() counts `direct` and `assisted` over every listed record, including disconnected ones, while `connected` uses isConnected(). Overview (overview-view.tsx:228-231) shows counts.connected beside a '${counts.direct} Direct · ${counts.assisted} Assisted' hint, which is the same mismatch the reviewer flagged on this page. The Channels filter tabs use direct/assisted as list-filter counts, so this needs an owner's call: either add connected-only fields or change Overview to use them. | api |
| `web/src/features/onboarding/tours.ts` | Register page tips for the anchors this page now has. | api |
| `web/src/features/onboarding/tours.ts` | Register the billing page tips so the help menu can walk the new data-tour anchors. | billing |
| `web/src/features/onboarding/use-tour-context.ts` | Supply isOwner and portalAvailable without adding a GET /usage (a write transaction) on every page. | billing |
| `web/src/lib/api/types.ts` | Ledger rows need the fields the backend should add, so allowance markers stop relying on the narrow local type in billing-model.ts. | billing |
| `web/src/features/overview/attention.ts` | The trial reminder reads raw subscription.status (which can lag lifecycle.status within one response) and says 'Choose a plan to keep publishing', but trial expiry pauses nothing (canPublish is not enforced). This matches the billing page's wording. | billing |
| `web/src/config/nav-config.ts (and web/src/components/layout/app-sidebar.tsx:221-226)` | The billing page now works for every member (costs, checkout and portal stay owner-only), but the nav still hides it from non-owners. Apply only after the founder decides (see decisions) and the backend strips budget and ledger costs for non-owners. | billing |
| `web/src/lib/api/types.ts` | The API returns completedAt on data requests (privacy.py:80), withdrawnAt on retracted sources (domain.py:306) and revoked on snapshot channels. The page reads all three through local narrowing today. | privacy |
| `web/src/features/onboarding/tours.ts` | Registers the page tips on the anchors this page renders. The retract step now uses the corrected wording (blocked until drafted again; every draft sent back; Queue posts held). | privacy |
| `web/src/features/account/profile-model.ts` | Nothing is shared when a diagnostics package is created (hosted.py:447-453 returns it to the caller only), so the account-history label overstates what happened. | privacy |
| `web/src/app/(marketing)/data-deletion/page.tsx` | Cancelling an in-flight job only moves it to 'uncertain', which still blocks deletion. There is also no delete-source action, the Ideas withdraw path records no receipt, and retraction affects the whole workspace, not only the dependent drafts. The wording matches the corrected in-app copy. | privacy |
| `web/src/features/ideas/source-inspector.tsx` | Ideas 'Hold to withdraw' calls the same retract_source, so it has the same workspace-wide effect, but its copy (lines 252 and 477) mentions only the drafts that used the source. The Ideas owner could reuse retractionImpact/retractionLines (currently in features/account/privacy/privacy-model.ts; moving them to a shared lib file would be cleaner). | privacy |
| `web/src/features/agent/use-model.ts` | The page reads the stored key itself to explain a fallback. The hook should expose it so the key lives in one place. | models |
| `web/src/lib/api/types.ts` | Type the fields the page reads defensively, and allow a null budget so Codex can say 'no cap'. | models |
| `web/src/features/onboarding/tours.ts` | Register the page tips against the data-tour ids now on the page. | models |
| `web/src/lib/api/client.ts + web/src/lib/api/hooks.ts` | Once the backend adds POST /api/ideas/models/rescan, Check again should call it instead of refetching. | models |
| `web/src/lib/api/types.ts (LearningSummary) + src/postriff_phase2 memory summary (backend)` | The consent card can only describe learning from edits conditionally, because the API does not say which extractor the server built at startup. | models |
| `web/src/features/onboarding/tours.ts` | Registers the page tips so the help menu and one-time nudge work on /app/workspace/audit. Targets use the ids now on the page, with heading('audit') as the fallback because rows and filters are absent when the log is empty. The 'Who' step copy is corrected: members show by their profile name when set. | audit |
| `web/src/lib/api/hooks.ts` | The audit page must not call GET /invitations for people without manage_members (the API refuses with 403), so it runs a local useQuery on keys.invitations with `enabled`. A shared option would remove the duplication. | audit |
| `web/src/features/workspace/members-view.tsx, web/src/features/channels/connect-return.tsx, web/src/features/memory/memory-view.tsx, privacy export caller` | Every mutation that writes an audit row should refresh the log and the Overview activity card. Today only channel-card.tsx:158 invalidates keys.audit. | audit |
| `web/src/features/memory/proposal-card.tsx` | Show 'Expires in N days' on each waiting proposal card, where it belongs, using the helper added here. | memory |
| `web/src/features/memory/learning-panel.tsx` | The panel has no error state: when useMemoryProposals fails it shows only its description. It should also own the history tabs and a hold-to-confirm reset. | memory |
| `web/src/features/onboarding/tours.ts` | The memory-tips copy promises evidence that does not exist yet, and the new anchors (memory-viewer, memory-access, memory-learning) have no steps. | memory |
| `web/src/features/workspace/brand-view.tsx` | The Brand spec's 'What drafts read' panel should reuse the component Memory owns instead of rendering its own copy. | memory |
| `web/src/lib/api/hooks.ts` | The docstring repeats the false claim that the agent reads every file before every draft. | memory |
| `src/postriff_phase2/memory.py` | VOICE.md's source says 'From your active voice profile' even when no voice exists (backend, for the founder or backend session). | memory |
| `src/postriff_phase2/learning_service.py` | The Recent tab cannot show an honest count because `recent` is capped at 20 with no total (backend, for the founder or backend session). With this, the tab could show the real count again. | memory |
| `web/src/features/onboarding/tours.ts` | Extend the brand-tips tour to the new anchors, stop the copy promising restore, and stop saying no model reads the sample. | brand |
| `src/postriff_phase2/permissions.py` | Restore changes every member's drafts just as profile_decide does. Without this, an editor could restore through the API and hold every scheduled post. This is a prerequisite for adding a Restore button. | brand |
| `src/postriff_alpha/domain.py` | The observation profile_propose writes says the sample is 'for your own reference', but VOICE.md hands it to every writing route (memory.py:103). The Brand page shows this server string as written, so it still reads as a false claim. | brand |
| `web/src/lib/api/hooks.ts` | Brand and Memory read GET /memory, but useAct doesn't invalidate it. After a voice approval (VoiceSetup or the new Brand proposal card), the 'What drafts read' card and learned count stay stale until the next refetch. | brand |
| `web/src/lib/api/types.ts` | Brand reads these through local narrowing casts. | brand |
| `web/src/features/workspace/voice-setup.tsx` | This file belongs to another session. Its placeholders are about piano, which breaks the general-audience rule. The header says scheduling is impossible where it should be a reminder. The sample placeholder promises the sample is only for reference and never quoted, but writing routes receive it. 'Start again' (reject) has no confirmation. | brand |
| `web/src/features/account/privacy/export-cards.tsx` | When the voice export fails, the toast's 'Open Brand & voice' action sends people to a page that can't create a field-approved package, so it's a dead end. | brand |
| `web/src/features/home/home-view.tsx` | Owners are only told about a waiting proposal on Brand itself. NeedsYou (home-view.tsx:112-114) only checks !voiceActive. | brand |

## 11. 驗證記錄

- 全 app `npx tsc --noEmit`：0 error。
- 全 app `npx oxlint src`：0 error、1 warning（members-view.tsx 入面另一個 session 嘅 TransferOwnershipCard，唔係今次改動）。
- `next build`（獨立 distDir，完成後已刪除）：50 條 route 全部 compile，冇 prerender error。
- Onboarding v2：用 script 喺瀏覽器行完 welcome → 9 步 → 6 頁；hop 亮啱 sidebar link；閂住嘅 Workspace section 自動打開，Skip 之後還原；inert 解除；進度記錄正確；welcome 短片 light webm 載入（readyState 4）。
- Header：375、768、1024、1280px 都冇橫向捲動（scrollWidth === innerWidth）。
- Channels deep link `?connect=threads&capability=analytics`：Connect sheet 打開、Threads 同 Analytics 預選、參數清走（冇撳 Continue）。
- 頭 5 頁（Channels、Overview、Analytics、Calendar、Ideas）：agent 自己 tab 驗證 375／768／1440、dark、console；Overview 同 Calendar 用 cache 注入樣本數據測錯誤同 live 狀態。
- 後 12 頁：實作階段用自己 tab 或者 headless Chromium（擋住所有非 GET request，blocked list 為空）驗證；review 修正之後因為 :3100 web server 喺 23:31 被停、preview 名額被其他 chat 佔滿，冇再開瀏覽器，靠 typecheck 同 build 確認。重開 postriff-web 之後建議逐頁再睇一次 console。
- Canvas artifact：Playwright + Chrome 截圖 1280（light）同 390（dark），冇橫向捲動。
- Dev harness 嘅 Threads 係 live provider：全程冇撳 approve、schedule、send、connect、disconnect、re-verify、upload、delete、retract。

## 附錄

- `docs/postriff-app-update-plan.md`：主文件（廣東話）
- `docs/postriff-app-update-plan/pages/`：24 份逐頁完整 spec（design、technical、features、onboarding、next steps、覆核記錄）
- `docs/postriff-app-update-plan/research/`：Onboarding、motion、settings-API 三份研究 + completeness critic
- `web/src/features/onboarding/`：Tour 系統
- `web/src/components/motion/particle-field.tsx`：粒子場
- `motion/onboarding-welcome/`：HyperFrames 短片原始檔同 re-render 指令
