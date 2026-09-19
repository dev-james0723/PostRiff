# 19 · Notifications

> Route：`/app/account/notifications` · Sidebar：Account · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

頁面：`web/src/app/app/account/notifications/page.tsx` 只 render `NotificationsView`（`web/src/features/account/notifications-view.tsx`，工作樹 131 行、git `M`，並行 session 改緊）。Sidebar：Account group `web/src/config/nav-config.ts:148-153`，icon `notification`（`web/src/components/icons.tsx:175` = IconBell），冇 access key，所有 role 見到（person-level 頁，正確）。

而家三張 card（`grid gap-4 lg:grid-cols-3`，line 86）：
1.「Emails we send」（87-107）：hard-coded `EMAILS`（21-29，7 種），唯一真數據係 `auth.user?.email`（91）。冇 API read；NullTransport deployment 都照寫「Delivered to …」「sent at most once per event」。
2.「In the app」（108-126）：純文案 + `Link` 去 `/app`（117-119）；owner 先見 billing 備註（`checkAccess(access,{permission:'owner'})` line 80，`web/src/lib/auth/access.tsx:69`）。
3.「Security alerts」`SecurityAlerts`（32-75）：`ui/switch` 綁 `useMe().data.preferences.alertNewDevice`（37，error 時 `?? false` 會顯示成『關』），save `api.updateProfile`（42）→ `PATCH /api/me`（`web/src/lib/api/client.ts:120-121`），invalidate `keys.me`（`web/src/lib/api/hooks.ts:26`）再 toast；loading Skeleton（67）。全頁唯一讀寫 API 嘅部分。

Backend：
- `GET /api/me`（`src/postriff_phase2/hosted_app.py:358-359` → `src/postriff_phase2/hosted.py:570-590`）回 `preferences.alertNewDevice`（589）；session 第一次出現（`_touch_session` 576）就叫 `_alert_new_device`（580；`sessions()` 895 亦會）。
- `PATCH /api/me`（`hosted_app.py:360-361` → `hosted.py:592-626`），`alertNewDevice` 只收 bool（612-615）。
- `_alert_new_device`（`hosted.py:489-502`）：冇 `public_base_url` 靜靜 return 兼唔 audit（492）；讀 `pr_profiles.alert_new_device`；冇 address → `{sent: False}`；audit `session.alerted` meta 只有 `{sent}`，冇 reason（502）。
- Mailer `src/postriff_phase2/email.py`（`M`，240 行）：`KINDS` line 80（7 種）；`_template` 89-131；`ResendTransport` 53-76（非 2xx → AlphaError 502「The email service did not accept this message.」）；`NullTransport` 42-50 回 `{id}`；`Mailer._deliver` 162-170 對任何冇 raise 嘅 transport 回 `sent: True`（所以 NullTransport = sent true），只 catch AlphaError（網絡層 exception 會穿出）；`Reminders` 195-240：trial_ending now+2d..+3d、trial_ended now-1d..now（217），dedupe key `{kind}:{workspace_id}:{int(expires_at)}`，`MAX_PER_RUN=50`（20），缺 address → row 留 sent=false 冇 reason；HTML 冇 tracking pixel，footer 只 privacy link（139-156）。
- Wiring：`hosted_app.py:113-127` `billing_from_environment` — 有 `RESEND_API_KEY` 先 Resend（要 `EMAIL_FROM` + `POSTRIFF_PUBLIC_BASE_URL`，124-126），否則 NullTransport（127）；service default `hosted.py:303-306`。Dev harness `scripts/postriff_dev_hosted.py:169-171`：NullTransport、`public_base_url='https://dev.postriff.invalid'`、email_lookup `dev-<id>@postriff.invalid` → dev 會行完整寄送路徑並記 sent=true。
- 邊度寄：welcome `bootstrap()` `hosted.py:534-537` 直接寄（唔入 ledger）；invitation `_send_invitation` 771-775 只回 bool（唔入 ledger，invitee 未必有 user_id）；billing `_billing_notice` 408-436：INSERT `pr_notifications`（418，dedupe `{kind}:{eventId}`），寄到先 `sent=true`（435），duplicate / no address reason 只 return（421/424），Mailer 失敗 reason 完全丟失；grace 7 日 hard-code 兩次（`billing.py:208`、`hosted.py:433`）；trial reminders `run_reminders` 402-406，由 `/api/cron/worker`（`hosted_app.py:326-337`，333）每 tick 叫。
- Ledger：`migrations/postriff/008_billing_provider_notifications.sql:11-21`（workspace_id NOT NULL、user_id、kind、dedupe_key UNIQUE、sent、meta、created_at），service_role only（23-34）。產品代碼（src/）冇任何讀取路徑；只有 `tests/phase2/postgres_billing_stripe.py:172`、`tests/phase2/postgres_migration_008.py` 讀。
- Preference column：`migrations/postriff/011_account_preferences.sql:8`（檔案 untracked `??`）。
- Account history：`GET /api/me/security-events`（`hosted_app.py:364-365` → `hosted.py:661-673`），`SECURITY_KINDS`（658）含 `session.alerted`，merge `pr_sessions`；`web/src/features/account/profile-model.ts:104-107`（`??`）譯做「New-device alert emailed to you / could not be emailed」，只喺 Profile 用。
- Overview「Needs your attention」：`web/src/features/overview/overview-view.tsx:172-246` inline 推導 7 個信號（voice、past_due、reconnect、needsReview、trial ≤5 日、export-only、未連 channel），render 305-363（`AnimatePresence mode='popLayout'`，`EASE_OUT`/`SPRING_LAYOUT` 來自 `web/src/lib/ease.ts:5,37`）。已知 bug：snapshot / channels error 時 attention 係空 → 顯示「All clear」（312 只 check isLoading）。Publish job `held`（`src/postriff_phase2/hosted_worker.py:66-68`）/`failed`（70-71；`failed` ∈ `store.py:18` TERMINAL，永久保留），nextAction 127-130，唔喺 attention、冇 email。Worker 已有 `on_verified` callback（`hosted_worker.py:26,33,112-116`）。
- 前端 API 層：`hooks.ts:103-107` `useMe`、115-120 `useSecurityEvents`、121-126 `useMyInvitations`；`client.ts:119-125`；types `Me` `web/src/lib/api/types.ts:651-665`、`ProfileChanges` 668-673、`SecurityEvent` 698-、`Job` 71-82。冇 notifications hook / type / endpoint。
- Tests：`tests/test_postriff_email.py`（templates / transports / never raises / dedupe / bounded）；`tests/test_postriff_account_security.py:309-321`、426-452；`tests/phase2/postgres_account.py:193-194`。
- Infobar：本頁冇 `infoContent`（17 個其他 view 有，包括 profile / privacy / billing）；型別 `web/src/components/ui/infobar.tsx:29-43`。
- Tour：已有基建（並行 session，untracked）`web/src/features/onboarding/tours.ts`（`PAGE_TOURS`、`TourStep {id, route, target: string[], title, body, when?, placement?, stop}`）、`tour-overlay.tsx`、`tour-mount.tsx`（mount 喺 `web/src/app/app/template.tsx`）、`web/src/styles/tour.css`；本頁未有 entry、未有 `data-tour`。

Gap：(1)「Emails we send」「Delivered to」係文案，NullTransport deployment 講大話；(2) 冇「寄咗未」記錄，ledger 唔齊（welcome / invitation / new_device 唔入），失敗 reason 冇存；(3) in-app 部分冇 live 數據；(4) held / failed 冇任何通知；(5) 2–3 日、7 日 grace 係手寫；(6) 冇 Infobar、冇 page tour entry；(7) Switch 喺 `/api/me` error 時顯示『關』（unavailable 變 false）。

## 1. Design specification（最新版）

**目的**：一頁答三條問題：PostRiff 幾時會 email 你（同呢個 deployment 究竟寄唔寄得出）、寄咗未、而家有咩等緊你決定。所有狀態讀 server（`GET /api/me/notifications` + `GET /api/me` + current workspace snapshot / usage / channels）；唯一可校嘅係 opt-in 提醒（而家得 new-device，P1 加 publish-failed）。頁面唔係 inbox：冇 mark as read、冇 unread 數，決定全部喺 Queue / Channels / Billing 做。

**Layout**：PageContainer（`pageTitle='Notifications'`，`pageDescription`「Where PostRiff reaches you, what was sent, and what is waiting for a decision.」）+ `infoContent`（`InfobarContent`，`web/src/components/ui/infobar.tsx:40-43`）。冇 header primary action（呢頁係設定 + 記錄，冇真主動作）。唔用 PageContainer `isLoading`（會整頁 skeleton），每張 card 自己處理。Body `grid gap-4 lg:grid-cols-3`：Row 1 `lg:col-span-3`「Delivery」；Row 2 左 `lg:col-span-2`「What we send」、右「Waiting for you」；Row 3 `lg:col-span-3`「Recent notifications」。375px：單欄；kind row 沿用現有 `flex-col sm:flex-row sm:items-center sm:justify-between`（line 97），Switch `shrink-0`；Recent row 兩行（label + status badge / 時間 + workspace），reason `break-words`；Retry / Switch touch target ≥ 40px；gutter 由 PageContainer 提供，冇橫向 scroll。768px：仍單欄（`lg` 斷點），Delivery 內部 `sm:flex-row`，Recent row 單行三段（kind / when / status）。1440px：3 欄；Infobar 打開時 grid 外層 `min-w-0`（template.tsx 已有）唔會塌。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Delivery | 第一眼講清楚 email 去邊、呢個 deployment 係咪真係寄得出。Unavailable 永遠唔變 off。 | 左：`Icons.send` +「Email goes to {auth.user.email}」（address 只來自 auth provider，冇就寫「your sign-in email」；API 永不回 address）。右：`AnimatedBadge`（`web/src/components/motion/animated-badge.tsx`，status 型別 line 15）讀 `delivery.configured`（server 定義 = transport 唔係 NullTransport **且** `public_base_url` 存在）：true → success「Email on」；false → warning「Email not set up on this deployment」+「Nothing is delivered until email is set up. Attempts are still recorded below.」。副行「Plain text and HTML, one link each, no tracking pixels」（對應 `email.py:133-160`）。`data-tour='notifications-delivery'`。 | loading：badge `loading`「Checking」；error：badge `neutral`「Unavailable」+「Could not read delivery status」+ Retry；configured=false 係正常狀態（dev harness 就係），唔係 error。 |
| What we send | 由 server 決定嘅完整清單：唔喺 `Mailer.KINDS` 就唔出現；文案留 client，數字讀 server。 | `ul divide-y`，每行由 `kinds[]`（次序跟 server）：label + when（client `KIND_COPY` map；trial_ending「{a}–{b} days before」讀 `meta.daysBefore`，payment_failed「{g}-day grace」讀 `meta.graceDays`，server 由抽出嘅 module 常數計，取代 `email.py:217`、`billing.py:208`、`hosted.py:433` 三處 hard-code）；右 `Badge variant='outline'` audience「You」/「Workspace owner」/「The invitee」；當前 workspace 你係 owner（`checkAccess(access,{permission:'owner'})`）就加「(you)」。invitation 行下面細字「Invitations are not listed under Recent notifications.」（因為 invitee 未必有 account，冇 ledger）。`optional=true` 行（new_device）右邊放 `ui/switch`（搬入現有 `SecurityAlerts` 邏輯，保留 `aria-label`，加 `data-testid='switch-alert-new-device'`），細字「One email per new device, with a link to review your sessions. Each attempt also appears in your account history.」；`lastSentAt` 有值先顯示「Last sent {relativeTime}」（`web/src/lib/time.ts:35`）。`data-tour='notifications-kinds'`。 | loading：Skeleton 行 `h-12`，Switch 位 `h-5 w-9`。error（notifications 或 `/api/me` 任一）：card 內 `Alert variant='destructive'` + Retry；Switch 唔 render（修正現有 `?? false` 喺 error 時扮『關』）。saving：`disabled={busy}`，server 回應後先 toast；失敗 toast.error，Switch 由 query 派生自動彈返。 |
| Waiting for you | 將「In the app」一句文案變成 current workspace 嘅 live 清單，同 Overview 共用 derivation，兩頁一致。 | CardTitle「Waiting for you」+ 副題 workspace 名（多 workspace 用戶要知道係邊個）+ 右邊 count（`DigitSwap`，`web/src/components/motion/digit-swap.tsx`；loading / unavailable 唔 render）。CardDescription「Decisions only you can make. Nothing publishes on a notification alone.」。內容 = 抽出嘅 `<AttentionList />`。項目按權限過濾：past_due / trial 只俾 `owner`，approvals 只俾 `approve`，reconnect / export-only 只俾 `manage_connections`（viewer 見到嘅係冇 action 嘅資訊項或者乜都冇）。新增 `jobs-held`：只數 `state==='held'`（非 terminal，真係等緊）＋ `failed` 而最後 event 喺 7 日內；title「{n} scheduled post(s) did not go out」，n=1 時 description 用該 job `nextAction`（worker 寫嘅真下一步，`hosted_worker.py:127-130`），failed 窗口寫明「in the last 7 days」；href `/app/queue`、action「Open the queue」。語氣係提醒，唔暗示創作被擋。底部「Open Overview」link 加 `t-learn` class + `LearnMoreChevron`（`web/src/components/ui/learn-more-chevron.tsx`，用法見 overview-view.tsx:393）。`data-tour='notifications-attention'`。 | `access.hasWorkspace=false`：整張 card 換做 Empty「No workspace yet」+ link `/app/account/profile`（睇 invitations），唔出任何項目（query disabled 時 isLoading=false，唔可以當 loaded）。loading（snapshot / channels / usage 任一 pending）：2 個 Skeleton `h-16`，冇 count。error：Empty「Unavailable」+「Could not read the workspace right now」+ Retry，絕不顯示「All clear」或 0（抽出時順手修 Overview 同一 bug）。empty：「All clear」/「No approvals waiting and every connection is healthy.」。 |
| Recent notifications | 答「PostRiff 有冇 email 過我？」——讀 ledger，包括寄唔到嘅，並誠實區分『冇 email service 只係記錄』。 | `items[]`（newest first，≤50，server 回 `truncated`）每行：`KIND_COPY[kind].label`（unknown kind 顯示 kind 字串 replace `_`）、`formatDateTime(at)`（`time.ts:51`，跟 person locale / time zone）、workspace name（只限你仍然係 member 嘅 workspace，已離開就唔 join 名）、status 由 server 決定：`sent` → `Badge`「Sent」；`not_sent` → `Badge variant='destructive'`「Not delivered」+ `reason`（Mailer / service 句子，永冇 address）；`recorded` → `Badge variant='outline'`「Recorded only」+ tooltip「This deployment had no email service when this was created.」（寫入時 `meta.transport='null'`；舊 row 冇 meta.transport 而現時 configured=false 亦當 recorded）。`source='history'`（audit `session.alerted`）label「New device sign-in alert」。冇 filter、冇分頁；`truncated=true` 先顯示「Showing the latest 50」。`data-tour='notifications-recent'`。 | loading：3 行 Skeleton `h-10`；error：`Alert variant='destructive'` + Retry；empty：見 empty_state。 |
| Infobar | 同其他頁一致嘅 `i` 側欄，文案對所有職業一樣。 | title「About notifications」；sections：(1)「Only transactional email」—「PostRiff emails you about your account, your trial and your plan. There is no marketing email and no tracking pixel.」links `/privacy`；(2)「Decisions live in the app」—「Approvals, reconnects and billing problems appear under Waiting for you and on the Overview. An email never publishes anything.」links `/app/queue`、`/app/channels`；(3)「Who gets what」—「Billing and trial emails go to the workspace owner. Invitations go to the person invited. The new-device alert is optional and off by default.」links `/app/workspace/members`、`/app/account/profile`。 | 靜態。 |

- **Empty state**：Recent notifications 冇 row：`Empty` + `EmptyMedia variant='icon'` `Icons.notification`，title「Nothing sent yet」，description「When PostRiff emails this account — a welcome, a trial reminder, a billing notice or an alert you turned on — it will be listed here with whether it was delivered.」。冇 CTA。`delivery.configured=false` 時改為「This deployment has no email service. Anything PostRiff would have sent is listed here as Recorded only.」。Waiting for you 冇項目沿用「All clear」；冇 workspace 見上。
- **Loading**：全部 `ui/skeleton`（`.t-skel-pulse`，`web/src/styles/transitions.css:271`），形狀跟真行高：Delivery badge 用 AnimatedBadge `loading`、kinds `h-12`、attention 2×`h-16`、recent 3×`h-10`。任何數字（count、Last sent）data 到之前唔 render。四組 query 各自獨立，唔用 PageContainer `isLoading`。
- **Error**：每張 card 獨立：`Alert variant='destructive'` + `Icons.alertCircle` + `ApiError.message`（fallback「Could not load this section.」）+ `Button variant='outline' size='sm'`「Retry」→ 該 query `refetch()`。Delivery badge neutral「Unavailable」。Waiting for you 絕不 fallback「All clear」。`/api/me` 失敗（例如 011 未 apply 導致 500）時 Switch 唔 render，顯示「Could not read your alert preference」+ Retry。Switch save 失敗：toast.error + 彈返 server 值。401/403 由 app gate 處理。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Delivery badge | `useMyNotifications` loading → success / error | AnimatedBadge 由 `loading`「Checking」變 `success` / `warning` / `neutral`「Unavailable」；reduced motion 由元件內 `useReducedMotion` 處理。 | web/src/components/motion/animated-badge.tsx（同 web/src/features/channels/channels-summary.tsx 用法） | 是 |
| Waiting for you list items | snapshot / channels / usage refetch 令 items 變 | 沿用 Overview：`AnimatePresence initial={false} mode='popLayout'`，enter opacity + y（200ms `EASE_OUT`，layout `SPRING_LAYOUT`），exit opacity→0 y -4（160ms，快過 enter）；reduced motion duration 0；無 stagger。 | 抽出 overview-view.tsx:319-361 做 `web/src/features/overview/attention-list.tsx`；web/src/lib/ease.ts EASE_OUT / SPRING_LAYOUT | 是 |
| Waiting for you count | attention items 數目改變 | DigitSwap 滾到新數（default 180ms、stagger 6ms）；loading / unavailable 唔 render，唔會由 0 滾上去。 | web/src/components/motion/digit-swap.tsx（web/src/features/queue/queue-view.tsx 同款） | 是 |
| Recent notifications new row | refetch 帶到新 row（例如 toggle 後嘅 `session.alerted`） | 同 attention-list motion props：新 row enter 200ms，舊 row `layout='position'`；exit 160ms；總長 ≤300ms；reduced motion 直接出現。只郁 transform / opacity。 | attention-list.tsx 嘅 motion props，唔另外發明 | 是 |
| New-device Switch | 用戶撥動 | Switch 視覺切換，`busy` 期間 disabled；server 回應後 sonner toast（`--toast-open` 350ms / `--toast-close` 250ms）；失敗彈返。 | web/src/components/ui/switch.tsx + sonner（現有 SecurityAlerts 行為）；web/src/styles/transitions.css:129-130 | 是 |
| 「Open Overview」「Open the queue」links | hover / focus | chevron 右移、兩臂張開變箭嘴。 | web/src/components/ui/learn-more-chevron.tsx + parent `t-learn` class | 否（純裝飾） |
| Page enter | route 進入 | `.t-page-enter` fade + slide。 | web/src/app/app/template.tsx（已有） | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | `PATCH /api/me { alertNewDevice }` 讀寫 person-level opt-in | api | 有 | src/postriff_phase2/hosted.py:612-615；hosted_app.py:360-361；web/src/lib/api/client.ts:120-121；migrations/postriff/011_account_preferences.sql:8（untracked） | S |
| 2 | `GET /api/me` 回 `preferences.alertNewDevice` | api | 有 | hosted.py:577, 589；web/src/lib/api/types.ts:664；hooks.ts:103-107 `useMe` | S |
| 3 | New-device email + audit `session.alerted` | backend | 有 | hosted.py:489-502；email.py:125-130、190-192；tests/test_postriff_account_security.py:426-452；tests/phase2/postgres_account.py:193-194 | S |
| 4 | Mailer 7 kinds + Resend + NullTransport | backend | 有 | email.py:80、53-76、42-50、162-170（只 catch AlphaError）；hosted_app.py:113-127 | S |
| 5 | Ledger `pr_notifications` | data | 有 | migrations/postriff/008_billing_provider_notifications.sql:11-21；寫入只有 hosted.py:418/435 同 email.py:220/236；welcome（hosted.py:534-537）、invitation（771-775）、new_device（489-502）唔寫；src/ 冇讀取 | S |
| 6 | `GET /api/me/notifications`：`delivery.configured`（非 NullTransport 且有 public_base_url）、`kinds[]`（audience / optional / enabled / lastSentAt / meta.daysBefore / meta.graceDays）、`items[]`（ledger by user_id ∪ audit `session.alerted` by actor，status sent / not_sent / recorded，reason，只 join 仍係 member 嘅 workspace name）、`truncated` | api | 冇 | hosted_app.py:358-367 冇此 route；src/ 冇 SELECT pr_notifications | M |
| 7 | Ledger 補齊：welcome 寫 ledger（dedupe `welcome:{workspace_id}`）；所有寫入加 `meta.transport`；失敗 reason 存 `meta.reason`（_billing_notice、Reminders 缺 address / Mailer 失敗） | backend | 冇 | hosted.py:534-537 冇 INSERT；hosted.py:421/424 reason 只 return，433-436 Mailer reason 丟失；email.py:228-240 缺 address 冇 reason；meta 永遠 `{}`。reason 冇 address，符合 008 註釋 | S |
| 8 | Grace / reminder 窗口抽成 module 常數 | backend | 冇 | email.py:217（2d/3d/1d）、billing.py:208 同 hosted.py:433（7*86400）三處 hard-code | S |
| 9 | Person-level kinds（new_device）經 audit merge | data | 冇 | 008:13 workspace_id NOT NULL；security_events hosted.py:661-673 有同款 merge 手法 | S |
| 10 | 前端 type `MyNotifications` + `client.myNotifications()` + `useMyNotifications()`（key `['me','notifications']`） | frontend | 冇 | types.ts 冇；client.ts:119-125；hooks.ts:26-29 keys 冇 | S |
| 11 | 抽出 `useAttention()` + `<AttentionList />`，加權限過濾、hasWorkspace / unavailable 分支、`jobs-held`（held + 7 日內 failed） | frontend | 冇 | overview-view.tsx:172-246 推導、305-363 render（error → All clear bug 喺 312）；grep `useAttention` 零結果；Job 型別 types.ts:71-82；failed ∈ TERMINAL store.py:18 | M |
| 12 | Notifications 頁 `infoContent` | frontend | 冇 | notifications-view.tsx:82-85；型別 ui/infobar.tsx:29-43；profile-view / privacy-view 等 17 個 view 有先例 | S |
| 13 | Page tour entry（`PAGE_TOURS` 加 '/app/account/notifications'）+ `data-tour` targets | frontend | 冇 | 基建已存在：web/src/features/onboarding/tours.ts（PAGE_TOURS、TourStep）、tour-mount.tsx（template.tsx mount）；本頁未有 entry / data-tour | S |
| 14 | Opt-in「Publish failed / held」email（P1）：migration `alert_publish_failed`、Mailer kind、worker `on_failed` callback（仿 `on_verified`）、PATCH /api/me 新 key、kinds 表多一個 Switch | backend | 冇 | hosted_worker.py 冇 mailer；on_verified callback 喺 hosted_worker.py:26,33,112-116 可仿；email.py:80 冇 publish_failed | L |
| 15 | Email / 頁面語言跟 `pr_profiles.locale` | backend | 冇 | email.py templates 全英文；011 已有 locale column；docs/postriff-worldwide-languages-plan.md 冇提 email，等 §10 決定 | M |
| 16 | Dev harness 驗證環境 | infra | 有 | scripts/postriff_dev_hosted.py:169-171 NullTransport + dev email_lookup + public_base_url；:3100 web / :4331 API | S |

## 3. Features

### P0

- **Delivery status 讀 server**：NullTransport deployment（包括 dev harness）而家都顯示「Delivered to …」。`delivery.configured` 由 server 講（transport + base URL），false 時明講未設定。
- **「Recent notifications」ledger 清單（sent / not delivered / recorded only）**：產品冇讀 `pr_notifications`，用戶答唔到「有冇 email 過我」；trial reminder 缺 address 或 502 而家靜靜消失。三態 status 避免 NullTransport 記錄扮「Sent」。（depends on：Ledger 補齊（welcome 入 ledger、meta.transport、meta.reason））
- **「Waiting for you」live 清單，共用 `useAttention()`，按權限過濾，加 held / 近期 failed jobs**：「In the app」只係文案。Remind, don't block：只提醒去 Queue，唔擋創作；同 Overview 同一 derivation，並一次過修 error → All clear bug。（depends on：抽出 attention.ts / attention-list.tsx（overview-view.tsx 並行 session 改緊，要協調））
- **Switch error 誠實化**：`/api/me` 失敗時現有 `?? false` 將 unavailable 顯示成『關』；改為 error + Retry。

### P1

- **Opt-in「Publish failed / held」email**：排程工具常見期望（Buffer 將 post-failed 做成可 toggle email；Typefully 喺 app 講失敗原因）。PostRiff worker 已寫 `nextAction`，email 同 row 都帶住，link 去 Queue。（depends on：P0 endpoint；migration；worker on_failed callback）
- **Infobar 三段 + PAGE_TOURS entry**：其他 account 頁都有 Infobar；tour 基建已存在，只需加 registry entry 同 data-tour。

### P2

- **Email 語言跟 person locale**：worldwide languages 計劃未覆蓋 email；011 已有 locale。等 §10 決定先做。
- **Trial reminder 預告日期**：trial 行加「On or after {date}」，讀 `usage.entitlement.resetsAt` 同 `meta.daysBefore`；『on or after』因為視乎 cron tick。只 subscription.status='trial' 且 owner 先顯示。（depends on：kinds[].meta）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明白：PostRiff 只為固定幾件事 email 你（冇 marketing）、呢個 deployment 寄唔寄得出、唯一可選提醒預設關、要你決定嘅嘢喺「Waiting for you」而唔係 inbox。三個視覺信號：Delivery badge、只有 optional 行先有 Switch、Waiting for you 同 Overview 一致。文案對 designer / teacher / shop owner / developer 一樣，冇品牌或行業例子。首次到訪由現有 TourMount 嘅 page-tips nudge 帶出（唔自動彈 overlay）。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="notifications-delivery"]（需新增）` | Where email goes | Everything goes to your sign-in email. This badge is read from the server: if email is not set up here, it says so. |
| 2 | `[data-tour="notifications-kinds"]（需新增）` | The whole list | These are the only emails PostRiff sends: account, trial and plan events. No marketing and no tracking pixels. Rows without a switch are ones you would always want. |
| 3 | `[data-testid="switch-alert-new-device"]（需新增；fallback `[aria-label="Email me when a new device signs in"]` 已存在）` | The one optional alert | Off by default. Turn it on to get one email the first time your account is used on a device we have not seen. |
| 4 | `[data-tour="notifications-attention"]（需新增）` | Decisions wait here | Approvals, reconnects, billing and posts that did not go out show up here and on the Overview, for the things your role can act on. An email never publishes anything. |
| 5 | `[data-tour="notifications-recent"]（需新增）` | What was sent | Each email PostRiff tried to send is listed with whether it was delivered. Nothing to clear or mark as read. |

**Empty state 教咩**：Recent 空狀態教：呢個係記錄唔係 feed，第一封通常係 welcome 或 trial reminder。configured=false 版本教「Recorded only」唔係 bug。Waiting for you「All clear」教空係好事；冇 workspace 版本教去 Profile 睇 invitations。

## 5. Next steps（按次序）

1. **Backend `HostedWorkspaceService.my_notifications(token)`：(a) `delivery.configured = not isinstance(self.mailer.transport, NullTransport) and bool(self.public_base_url)`；(b) `kinds[]` 由 `Mailer.KINDS`，audience map {invitation: invitee, welcome/new_device: you, 其餘: owner}，optional 只 new_device（enabled 讀 pr_profiles），`meta.daysBefore` / `graceDays` 讀新 module 常數，`lastSentAt` = 每 kind max(created_at) where user_id 且 sent；(c) `items[]` = ledger `WHERE n.user_id=%s ORDER BY created_at DESC LIMIT 51`，LEFT JOIN pr_workspaces + active membership 先回 name，∪ audit `session.alerted` by actor（source='history'），sort、cap 50、`truncated`；status：sent && meta.transport!='null' → sent；!sent → not_sent；其餘（或舊 row 且現時未 configured）→ recorded。Route 喺 hosted_app.py:365 之後加 `/api/me/notifications` GET。Tests：account_security（wiring、shape、NullTransport→configured=false / recorded）；postgres_account.py（真 DB 次序、離開 workspace 唔回 name）。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py（放 security_events 附近 ≈661）；src/postriff_phase2/hosted_app.py:364-367；tests/test_postriff_account_security.py；tests/phase2/postgres_account.py`
2. **Ledger 補齊：抽 `TRIAL_ENDING_DAYS=(2,3)`、`GRACE_DAYS=7` 常數（email.py / billing.py:208 / hosted.py:433 共用）；bootstrap welcome 先 INSERT（dedupe `welcome:{workspace_id}`）再寄，寄到 UPDATE sent；所有 INSERT 帶 `meta.transport`；_billing_notice（hosted.py:421-436）同 Reminders（email.py:228-240）失敗時存 `meta.reason`（≤200 字，冇 address）。NullTransport 保持 sent=true（tests 靠佢），誠實由 transport 標記處理。順手將 `_deliver` 改為 catch Exception（reason 用固定句子），補 test。**（effort S）  
   檔案：`src/postriff_phase2/hosted.py:408-436, 534-537；src/postriff_phase2/email.py:162-170, 208-240；src/postriff_phase2/billing.py:208；tests/test_postriff_email.py；tests/phase2/postgres_billing_stripe.py`
3. **前端 API 層：types.ts 加 `NotificationKind`、`NotificationItem`（status 'sent'|'not_sent'|'recorded'）、`MyNotifications`；client.ts:125 後加 `myNotifications`；hooks.ts keys 加 `myNotifications: ['me','notifications']`、`useMyNotifications()`；toggle 成功 invalidate `keys.me` + `keys.myNotifications`。**（effort S）  
   檔案：`web/src/lib/api/types.ts；web/src/lib/api/client.ts:119-125；web/src/lib/api/hooks.ts:26-29, 103-126`
4. **抽出 attention（先同 overview 並行 session 協調）：`web/src/features/overview/attention.ts` export `useAttention(): { items; isLoading; unavailable; hasWorkspace }`，搬 overview-view.tsx:52-60 interface + 172-246 推導，逐字保留 7 項 id / copy；加權限過濾（owner / approve / manage_connections）、`jobs-held`（held + 7 日內 failed，description 用 `nextAction`）；unavailable = 任一 query isError。`attention-list.tsx` 搬 305-363 render，error 唔再落「All clear」。overview-view.tsx 改用兩者。**（effort M）  
   檔案：`web/src/features/overview/attention.ts（新）；web/src/features/overview/attention-list.tsx（新）；web/src/features/overview/overview-view.tsx:52-60, 172-246, 305-363；web/src/lib/auth/access.tsx（只 import）`
5. **重寫 notifications-view.tsx：Delivery（AnimatedBadge）、kinds 表（`KIND_COPY` + meta，Switch 併入並處理 `/api/me` error）、`<AttentionList />` + DigitSwap + hasWorkspace 分支、Recent（三態 badge + reason + truncated）、`infoContent`、`data-tour` / `data-testid`。每張 card 獨立 loading / error / Retry；刪 hard-coded `EMAILS`。**（effort M）  
   檔案：`web/src/features/account/notifications-view.tsx；web/src/components/motion/{animated-badge,digit-swap}.tsx、web/src/components/ui/{switch,badge,empty,alert,skeleton,learn-more-chevron}.tsx（只 import）`
6. **Tour：喺 `PAGE_TOURS` 加 `{ id: 'notifications', route: '/app/account/notifications', steps }`，每步 `target` 用陣列（data-tour 優先，structural fallback 例如 heading），`stop: 'Notifications'`，`when` 按需要（例如 attention 步只喺 hasWorkspace）。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts（untracked，並行 session 擁有，要協調）`
7. **驗證：`npx tsc --noEmit`、`npm run lint`、python tests；dev harness :3100（自己 tab）測 375 / 768 / 1440px、light / dark、prefers-reduced-motion；預期 Delivery「Email not set up」、welcome row 顯示「Recorded only」、toggle 後新 device 出 `session.alerted` row；停 API 驗證每張 card error 唔出 0 / All clear。唔撳 approve / schedule / publish。**（effort S）  
   檔案：`web/；tests/；scripts/postriff_dev_hosted.py（只運行）`
8. **P1 publish-failed：migration `alert_publish_failed boolean not null default false`；email.py kind `publish_failed`（platform + nextAction + queue link）；worker 加 `on_failed(cur, workspace_id, job)`（仿 hosted_worker.py:112-116 on_verified，try/except 唔影響 job），hosted 端讀 `job['approvedBy']` preference，INSERT ledger（dedupe `publish_failed:{job_id}:{attempt}`）再寄；`update_profile` / `me()` / types 加 key；kinds 表多一個 Switch。**（effort L）  
   檔案：`migrations/postriff/013_publish_failed_alert.sql（新，編號 apply 前再確認）；src/postriff_phase2/email.py:80, 89-131；src/postriff_phase2/hosted_worker.py:26-33, 66-71, 105-130；src/postriff_phase2/hosted.py:570-626；web/src/lib/api/types.ts:651-673；web/src/features/account/notifications-view.tsx`

## Risks

- 並行 session 改緊 `notifications-view.tsx`、`email.py`、`overview-view.tsx`（M）同 `web/src/features/onboarding/`（??）；實作前同步，commit 按 path stage。
- `migrations/postriff/011_account_preferences.sql` 仍 untracked；未 apply 嘅 DB 上 `me()` 會 500（`p.alert_new_device`），Switch 要顯示 error 而唔係『關』，deploy 前要 commit + apply 011。
- `delivery.configured` 必須同時睇 transport 同 `public_base_url`（`_alert_new_device` hosted.py:492、`_billing_notice` 412、bootstrap 534 冇 base URL 都靜靜唔寄），否則「Email on」但乜都冇寄。
- NullTransport 經 `Mailer._deliver`（email.py:168）回 sent=true；舊 ledger row 冇 `meta.transport`，只能用現時 configured 推斷 recorded，屬近似——要喺 tooltip 講清楚。
- `Mailer._deliver` 只 catch AlphaError；Resend 網絡層 exception 會穿出 cron / webhook，新 endpoint 同改動唔可以假設 never raises。
- `pr_notifications.workspace_id NOT NULL`（008:13）令 person-level email 只能經 audit merge；兩個來源兩種 id，前端當 opaque string。Invitation 冇 user_id，永遠唔入 Recent。
- Ledger 以 user_id 讀會包括已離開 workspace 嘅 row；只顯示 kind + 日期，唔回 workspace name（privacy）。
- Trial dedupe key 含 `int(expires_at)`（email.py:221）：trial 延期會再寄，Recent 會有兩行，文案唔好寫「only once」。
- `failed` 屬 TERMINAL 永久保留；Waiting for you 只數 held + 7 日內 failed，窗口要寫喺文案，否則舊失敗會當現況。
- `useScoped` 喺冇 workspace 時 disabled（isLoading=false、data undefined），唔處理 hasWorkspace 會誤出「Connect your first channel」或「All clear」。
- API 永不回 email address（email.py:9-11）；頁面 address 只來自 `auth.user.email`，唔好由 email_lookup 補。
- Competitor 參考（Buffer、Typefully）只用嚟決定功能；UI 文案、tour、empty state 唔可以提佢哋或任何行業例子。

## 覆核記錄

- 改正：notifications-view.tsx 工作樹版本 132 行、git M → 改為 131 行
- 改正：GET /api/me hosted_app.py:359-360；PATCH 361-362；security-events 365-366 → 行號減 1
- 改正：me() hosted.py:569-590，_touch_session line 576，_alert_new_device line 580，preferences line 589；sessions() line 895 → me() 570-590
- 改正：NullTransport 回 {sent: true}（email.py:48-50） → 改為 Mailer._deliver email.py:162-170 對 NullTransport 回 sent=true
- 改正：Mailer._deliver never raises → 寫成『只吞 AlphaError』並列為 risk
- 改正：_billing_notice 408-436，INSERT 418，sent=true 435，reason 只 return（421/425） → 421/424；Mailer reason 根本冇被保留
- 改正：全 repo 冇任何 SELECT pr_notifications → 改為『產品代碼冇讀取路徑，只有 Postgres tests 讀』
- 改正：overview-view.tsx:172-245 推導 7 個信號，render 306-358，EASE_OUT/SPRING_LAYOUT ease.ts:5,37 → render 305-363；抽出時要加 unavailable 分支
- 改正：hosted_worker.py 冇 mailer reference（imports line 8 只有 store） → callback 模式直接仿 worker 內建 on_verified
- 改正：types.ts Me 647-661、ProfileChanges 664-669、SecurityEvent ≈694-702、Job 69-80 → 更新行號
- 改正：全 web 冇 tour 基建（grep data-tour 零結果），要新起 web/src/components/tour/ PageTour → 刪走新基建步驟，改為喺 PAGE_TOURS 加 '/app/account/notifications' entry
- 改正：Infobar 型別 ui/infobar.tsx:35-38 / 29-38 → 29-43
- 改正：DigitSwap『Queue filter 計數同一用法』、AnimatedBadge『Channels / Status 頁用法』 → 引用 queue-view.tsx / channels-summary.tsx
- 改正：checkAccess 來自 web/src/lib/auth/access.ts → access.tsx
- 改正：Delivery configured=false 時 Recent 會標『Not delivered』（empty_state / Recent states） → endpoint 回 per-item status：sent / not_sent / recorded（NullTransport 寫入時 meta.transport='null'）
- 改正：Waiting for you 數 snapshot jobs state ∈ {held, failed} → 只數 held（非 terminal）＋最近 7 日內 failed，文案寫明窗口
- 違反原則（已改）：真數據先郁：configured=false 時 empty_state 同 Recent info 話『recorded as Not delivered』，但 NullTransport 經 Mailer 回 sent=true，row 會顯示『Sent』——UI 自相矛盾兼講大話。
- 違反原則（已改）：真數據先郁：『Showing the latest 50』喺剛好 50 行時出現，唔代表有更多；要 server fetch 51 回 truncated。
- 違反原則（已改）：真數據先郁：failed job 屬 TERMINAL，全部計入 Waiting for you 會將舊失敗當現況；抽出 Overview derivation 時亦承襲咗 error → 『All clear』嘅 bug（overview-view.tsx:312-320 只 check isLoading）。
- 違反原則（已改）：真數據先郁：Delivery『Email on』只睇 transport 非 Null，冇計 public_base_url（spec 自己喺 risks 承認，但 design_spec 冇改）。
- 違反原則（已改）：Reuse before inventing：提議新起 web/src/components/tour/ PageTour，但 features/onboarding/tours.ts PAGE_TOURS + TourMount（template.tsx）已經存在；tour_steps 格式亦唔跟 TourStep（target 陣列、body、route、stop）。
- 違反原則（已改）：Motion：Recent row slide-in 講『≤300ms 總長』但 exit 無定義 duration，同 attention 一樣要 exit 160ms < enter 200ms；DigitSwap default stagger 0.006s OK。
- 違反原則（已改）：Remind, don't block：publish-failed email 文案要避免暗示『要重新批核先可以繼續創作』——只係提醒，唔影響新 draft。原 spec 大致符合，但 held 描述用『need a new approval』要改為提醒語氣。
- 補上遺漏：RBAC / 無 workspace：Notifications 係 person-level（冇 access key 正確），但 Waiting for you 讀 current workspace 嘅 snapshot/usage/channels（useScoped enabled）；hasWorkspace=false（例如只有 pending invitation）時 query disabled、isLoading=false，會誤出『Connect your first channel』/『All clear』。要 hasWorkspace 分支，同埋標明係邊個 workspace（多 workspace 用戶）。
- 補上遺漏：Viewer / 無 approve 權限嘅 member：approvals、billing 項唔應該叫佢『Review now / Fix billing』；past_due 同 trial 項應只俾 owner（checkAccess permission 'owner'），approvals 只俾 'approve'。
- 補上遺漏：Invitation email 冇入 ledger 亦冇 user_id（invitee 未必有 account），Recent list 永遠唔會有；要喺頁面講清楚而唔係扮完整。
- 補上遺漏：Ledger 以 user_id 讀，會回傳已離開 workspace 嘅名：要決定係咪只顯示 kind + 日期，唔 join 已離開 workspace 嘅 name（privacy）。
- 補上遺漏：_billing_notice 同 Reminders 喺 Mailer 失敗時完全冇 reason（只有 no address / duplicate），要喺 meta 補 reason；Reminders 缺 address 時 row sent=false 但冇 reason。
- 補上遺漏：Mailer._deliver 只 catch AlphaError，網絡 exception 會穿出（影響 cron / webhook）；新 endpoint 設計唔可以假設 never raises。
- 補上遺漏：i18n：email template 同頁面文案全英文；011 已有 pr_profiles.locale，docs/postriff-worldwide-languages-plan.md 冇提 email 語言；要列為 deferred（等 §10 決定），日期用 lib/time.ts formatDateTime 已跟 person locale。
- 補上遺漏：Mobile 細節：Recent row 喺 375px 要 stack（kind+status 一行、時間第二行），reason 文字 break-words；Retry 按鈕 touch target ≥ 40px。
- 補上遺漏：Migration 011 未 apply 時 me() 500 → SecurityAlerts Switch 應該顯示 error 而唔係永遠 Skeleton / false；現有 on = ?? false 會喺 error 時顯示『關』，屬 unavailable 變 0。
- 補上遺漏：Overview 並行 session 正改 overview-view.tsx（M）同 onboarding（??）；抽 attention 要協調。
