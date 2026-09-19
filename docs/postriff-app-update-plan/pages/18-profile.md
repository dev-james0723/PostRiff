# 18 · Profile

> Route：`/app/account/profile` · Sidebar：Account · 成熟度：已成形（polish） · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

頁面已經係一個完整、全部讀真數據嘅 account page；之後嘅 proposal 係 polish 或者加一層，唔係重寫。

**Route 同結構**：web/src/app/app/account/profile/page.tsx:1-8 → `ProfileView`（web/src/features/account/profile-view.tsx:714-742）。Layout `grid gap-4 lg:grid-cols-2`：左欄 IdentityCard + PreferencesCard；右欄 SecurityCard + **PasskeysCard**（profile-view.tsx:726-729，web/src/features/account/passkeys-card.tsx:98-234，'Passkeys for sign-in'，用 web/src/lib/auth/passkeys.ts）；之後 ChannelsCard、WorkspacesCard、AccountActions 三張 `lg:col-span-2`。Info sidebar 三段（profile-view.tsx:56-76）。Page enter `t-page-enter` 同 `<TourMount />` 都喺 web/src/app/app/template.tsx:13-15。Nav：web/src/config/nav-config.ts:143-147，Profile **冇 access key**，所有 role 都見。

**IdentityCard**（profile-view.tsx:167-318）：avatar（web/src/components/user-avatar-profile.tsx）；display name 同時 `PATCH /api/me` 同 Supabase `updateUser({data:{full_name}})`（187）；EmailChangeDialog（87-165，updateUser({email}) 121）；pending email（291-298）；Verified/Unverified（277-283）；`SIGN_IN_METHODS`（profile-model.ts:35）+ Member since（310）；Copy user ID（224）；Dev identity badge（271）。

**PreferencesCard**（preferences-card.tsx:55-159）：time zone Combobox、locale Select、Follow this device；`PreferencesProvider`（web/src/lib/preferences.tsx）。

**SecurityCard**（security-card.tsx:813-829）三段：TwoFactor（446-622；listFactors 453；afterEnrol 478-487；turnOff 489-496 先 disableMfa 再逐個 unenroll；Badge On/Off 521；Your only method 561；no recovery codes 569；Add backup method 573）、Sessions（624-751；table Device / Last seen 686-723；revoke-others copy 730 冇講分鐘數；`SessionInfo.firstSeen` types.ts:643 未用）、SecurityActivity（753-811；Nothing recorded yet 784；Show all 806）。

**New-device alert toggle 已存在**：web/src/features/account/notifications-view.tsx:32-77 `SecurityAlerts`（/app/account/notifications），Switch → `api.updateProfile({alertNewDevice})` → invalidate keys.me。Profile 頁冇提及佢，new-device email 卻 link 返 /app/account/profile（hosted.py:501）。

**ChannelsCard**（profile-view.tsx:328-419）：`groupByWorkspace`、`channelBadge`（profile-model.ts:62-76，389 使用）出 'Connected' / 'Connected · read only' 等；Reconnect/Open `switchTo` + push /app/channels（337-338）；role-aware Empty（363-378）；error + Retry。**重複實作**：web/src/lib/channels/state.ts:59-71 有同一個 channelBadge（亦出 'Connected'）、:80 needsReconnect；Channels 頁用 web/src/features/channels/capability-chips.tsx:64 `CapabilityChips` + web/src/lib/channels/capabilities.ts:17 `CAPABILITY_CHIPS`。

**WorkspacesCard**（634-654）：PendingInvitations（434-524，440-441 空就 return null，冇讀 `available`）；WorkspaceRow（526-632；planLabel 565；Tier 587-589；Leave 606；owner copy 610「Transfer ownership first」）；只分 `status !== 'ready'`，冇 error 分支（provider.tsx:51,55,63 有 'error'、`error`、`refresh`）。

**AccountActions**（656-712）：Sign out + Delete account link /app/account/privacy；description 671「revoke them above」。

**Data trace**：hooks.ts:25-29 keys；useSessions 98、useMe 104、useMyChannels 110、useSecurityEvents 116、useMyInvitations 122。client.ts:111-133。types.ts：WorkspaceListItem 27、SessionInfo 641-648、Me 651-665、ProfileChanges 668-673、MyChannel 676-693（冇 capabilities）、SecurityEvent 698-706、PendingInvitation 709-718、CapabilityLevel/Capability 436-441。

**Backend**（src/postriff_phase2/hosted_app.py）：350 GET sessions、352 revoke-others、355 POST|DELETE mfa、358/360 GET|PATCH /api/me、362 me/channels、364 security-events、366 invitations、374 accept|decline、432 DELETE sessions/{id}、474 leave。hosted.py：assert_fresh 117-122；_touch_session ON CONFLICT 485；_alert_new_device 489-503；leave_workspace 557；me 570-590；update_profile 592-626；my_channels 628-659（唔讀 pr_channel_capabilities）；security_events 661-675；enable_mfa 680-696；disable_mfa 698-708（assert_fresh 703）；update_member 730 raise 'Ownership transfer is a separate step-up action'；my_invitations 839-847（冇 email → available:false）；sessions 886-896；revoke_session 898-910（assert_fresh 900）；revoke_other_sessions 912-928（915）。permissions.py:43 STEP_UP_WINDOW=600。hosted_app.py:73-75 verify.auth_time；86-90 client_label。oauth.py:192-199 讀 matrix；channels.py:9-10 CAPABILITIES/LEVELS。email.py:190-192 new_device。

**DB**：001_phase2.sql pr_profiles.display_name；009 pr_mfa_enforcement；011:6-13 time_zone/locale/alert_new_device + audit index；004 pr_sessions.client_label ≤40。

**Tests**：tests/phase2/postgres_account.py:59-185（含 alertNewDevice on/off、'Safari on iPhone' label 182）。Web 冇 unit test；package.json 只有 lint / lint:fix / typecheck。

**Onboarding infra 已存在**：web/src/features/onboarding/tours.ts（WELCOME_TOUR 53、PAGE_TOURS 156、`pageTourFor` 345）、tour-overlay.tsx、tour-mount.tsx（一次性 toast nudge 39）、store.ts（localStorage 'postriff-onboarding' 40）、help-menu.tsx。Profile 未有 page tour，亦冇 data-tour。

**已確認 gap**：
1. Profile 冇講 new-device alert 開咗未，control 喺 Notifications 頁。
2. `client_label` 幾乎永遠係 'Mozilla'。
3. Channels card 'Connected' blended（rule 5），而且 helper 喺 profile-model.ts 同 lib/channels/state.ts 重複。
4. 單一 session revoke 都要 10 分鐘內 sign-in，UI 冇數字。
5. Owner copy 指向唔存在嘅 transfer。
6. invitations `available:false` 靜靜消失；Workspaces 冇 error state。
7. Profile 冇 page tour 同 data-tour。
8. turnOff 半途失敗會令 Supabase factor 殘留。

## 1. Design specification（最新版）

**目的**：一頁答三個關於「我」（唔係 workspace）嘅問題：我係邊個、我個 account 點樣受保護、我可以去到邊。每個數字、badge、日期都讀 `/api/me*`、`/api/auth/sessions`、Supabase factors / passkeys 或 `/api/workspaces`；冇一個係推算。頁面本身唔做 RBAC gate（nav 冇 access key），每行 action 由 API 回嘅 `canManage`、membership role 決定，API 仍然係唯一 enforcement。

**Layout**：保留 PageContainer + Heading + info sidebar，冇 header action。1440px（lg+）：第一行兩欄 — 左 Identity 之上 Preferences；右 Security（Two-factor + New-device alert 狀態行）之上 Passkeys for sign-in。第二行兩欄：左「Where you are signed in」、右「Recent security activity」（由 SecurityCard 拆出，解決右欄過高）。之後 Connected channels、Workspaces & access、Account 三張 full-width。每張卡加 `id`（identity / preferences / security / passkeys / sessions / activity / channels / workspaces / account）同 `data-tour='profile-…'`；new-device email link 改 `/app/account/profile#sessions`。768px：單欄，Tier grid 保持 `sm:grid-cols-3`、Preferences `sm:grid-cols-2`。375px：單欄、PageContainer `px-4` gutter；sessions table 喺 `sm` 以下轉 stacked row（device 一行、first/last seen 一行、Revoke 靠右）；PasskeysCard row 同 channel row 用 `flex-wrap`；dialogs 用 ui/dialog `t-modal`。冇全頁 primary；每段最多一個 default button。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Identity | 我係邊個：名、email、sign-in 方式、幾時加入。 | 保留 IdentityCard（profile-view.tsx:167-318）。Polish：Save name 用 StatefulButton（讀真 promise）。多 provider 顯示留待 P2 linked identities（session.tsx:102 而家只有 `provider`）。 | loading：Skeleton h-6 w-32（253）。dev：Dev identity badge，冇 email change。error：toast（194）。pending email：提示 + Resend（291-298）。 |
| Preferences | 時區同日期／數字格式，跟人唔跟 workspace。 | 保留 preferences-card.tsx，唔加新嘢。locale 只影響 Intl 格式，唔係 UI 翻譯（UI copy 全英文）。 | loading：Skeleton。error：toast。 |
| Security · Two-factor | 開關 2FA、管理 authenticator / passkey factor、加 backup。 | 保留 TwoFactor（security-card.tsx:446-622）。Polish：(a) On/Off Badge（521）改 AnimatedBadge success/neutral，`contentKey={String(enforced)}`；(b) `enforced && verified.length === 1` 時 footer（567-575）加 AnimatedBadge warning 'No backup method'，'Add backup method' 升 default variant；(c) 本 session afterEnrol 成功後用 `SuccessCheck animate`（web/src/components/ui/success-check.tsx）+ useFlash 播一次，reload 唔重播；(d) turnOff 改 allSettled 逐個 unenroll 並報告殘留。 | unavailable（`me.mfa.available=false`）：Turn on disabled + 解釋句（505-506），永遠唔扮 On。loading：Skeleton。enrol error：dialog 內 Alert。mfa-required session 由 app gate（session.tsx:36,108）處理。 |
| Security · New-device alert 狀態行（新，read-only） | 喺 Profile 講清楚 alert 開咗未，control 留喺 Notifications 一處。 | TwoFactor 同 Passkeys 之間一行：Icons.notification + 'New-device alert emails: On / Off'（AnimatedBadge success/neutral 讀 `me.data.preferences.alertNewDevice`）+ link 'Change in Notifications' → /app/account/notifications。若 `useSecurityEvents` 有 kind='session.alerted' 事件，細字顯示最近一次 relativeTime；冇就唔顯示。唔加第二個 Switch。 | loading：Skeleton h-5 w-24。`useMe` error：成行唔 render（由 Identity error 覆蓋），唔顯示 Off。 |
| Passkeys for sign-in | 用 passkey 直接 sign in（有別於 2FA 第二步）。 | 保留 PasskeysCard（passkeys-card.tsx）。CardDescription 加半句區分：呢度係 sign-in passkey；Two-factor 入面嘅 Face ID / Touch ID 係第二步 factor。唔改流程。 | 跟現有：loading Skeleton、passkeySignInEnabled=false 時 Alert、rename / remove dialog。 |
| Security · Where you are signed in | 列出用過呢個 account 嘅 device，revoke 唔認得嘅。 | 保留 Sessions（624-751），搬去第二行左欄。Polish：(a) 加 First seen 欄（`firstSeen`，types.ts:643），current row 排首；(b) backend client_label 改 'Chrome · macOS' 格式，未知顯示 'Unknown device'（699）；(c) 按鈕 'Sign out {n} other sessions'，n 用 DigitSwap，只喺 revoke 後改變時郁；(d) step-up 說明句讀 `/api/me` 新 `stepUp.windowSeconds`，未有 API 前唔寫分鐘數。 | loading：Skeleton h-24。error：Alert + Retry（675-684）。empty 不可能（current 永遠喺度）。403 step-up：toast 顯示 API 原句 'Sign in again to confirm this sensitive action.' + 'Sign in again' 出路（要先驗證 re-auth 流程會更新 auth_time）。唔 disable Revoke 按鈕。 |
| Security · Recent security activity | 我自己嘅 account 歷史（唔係 workspace 內容）。 | 保留 SecurityActivity（753-811），搬去第二行右欄。empty copy（784）改 'Sign-ins on new devices, two-factor changes, revoked sessions and membership changes will appear here.'；warning tone 行加 Icons.warning（唔只靠顏色）。 | loading / error + Retry / empty；>8 條 Show all。 |
| Connected channels | 我喺所有 workspace 可以去到嘅 account，每項 capability 獨立評級。 | 保留分組、Reconnect / Open、role-aware empty。改動：(a) profile-view.tsx 改 import web/src/lib/channels/state.ts 嘅 channelBadge / needsReconnect，刪 profile-model.ts:60-80 重複版；(b) state.ts:63 verified 狀態 label 由 'Connected' 改為中性嘅 'Verified' / 'Verified · read only'（只講 identity + token 狀態，publish 能力交畀 chips），Channels 頁同時受益；(c) 每行第二行 render 現有 `CapabilityChips`（features/channels/capability-chips.tsx:64，CAPABILITY_CHIPS 六項，hover 顯示 API evidence / verifiedAt），資料來自 `/api/me/channels` 新 `capabilities`；(d) 首次 settle 時行 stagger：motion + `delay = i * min(0.04, 0.3/n)`、只 opacity/translateY、useReducedMotion（跟 member-access-sheet.tsx:61-69），唔用 `.t-stagger-line`。 | loading：Skeleton h-24。error：Alert + Retry。empty：Empty（363-378）。`canManage=false` 冇 Reconnect。`capabilities` 缺某項 → chip 顯示 Unsupported（跟 API matrix），唔推算。 |
| Workspaces & access | 我喺每個 workspace 嘅角色、人數、邀請、離開。 | 保留 WorkspaceRow + PendingInvitations。改動：(a) Tier 數字靜態 render，只喺 refresh 後數值改變先 DigitSwap；(b) `invitations.data?.available === false` 時顯示 muted 一行 'Invitations cannot be matched to your email on this deployment.'；`invitations.isError` 顯示細 Alert + Retry；(c) provider `status === 'error'` 顯示 Alert（`error` 原句）+ Retry（`refresh()`）；(d) owner copy（610）改 'You own this workspace, so you cannot leave it. Ownership transfer is not available yet.'；(e) Accept 用 StatefulButton。 | status loading：Skeleton h-40（647）。error：新 Alert。invitations 空而 available=true：唔 render。 |
| Account | Sign out 呢部 device；delete account 入口。 | 保留（656-712）。671「revoke them above」改 link `#sessions`。 | busy：'Signing out…'。 |

- **Empty state**：Channels：現有 Empty（363-378）— 有 manage_connections 見 CTA 去 Channels，冇就 'An owner or admin connects accounts for this workspace.'。Activity：教學句。Invitations：available=true 且空就唔 render；available=false 要講明對唔到 email。Workspaces：provider bootstrap 保證至少一個。Sessions：冇 empty。Passkeys：跟現有 empty copy。全部 empty 唔顯示 0 或 placeholder。
- **Loading**：每段各自 `ui/skeleton`（t-skel-pulse），冇 loading 文字，先到先顯示；唔用 PageContainer `isLoading`。Skeleton 尺寸對齊真內容（name h-6 w-32、sessions h-24、channels h-24、workspaces h-40、alert 狀態行 h-5 w-24）。
- **Error**：每段 inline `Alert variant='destructive'` + Retry（refetch / refresh），toast 只用喺 mutation。403 step-up 顯示 API 原句 + 'Sign in again' 出路。401 / mfa-required 由 app gate 處理。Unavailable（dev harness 嘅 mfa、invitations、alert email）顯示 'Not available…'，唔變 0 或 Off。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Two-factor On/Off badge（security-card.tsx:521） | `me.data.mfa.enforced` 改變 | AnimatedBadge success ↔ neutral，label swap；≤250ms | web/src/components/motion/animated-badge.tsx（contentKey） | 是 |
| 2FA 剛開啟 / backup 加咗嘅 success check | 本 session afterEnrol resolve 成功（reload 唔播） | SuccessCheck animate 一次 | web/src/components/ui/success-check.tsx（.t-success-check transitions.css:481）+ web/src/hooks/use-flash.ts | 是 |
| Save name / Accept invitation 按鈕 | click → promise pending → resolve/reject | idle → loading → success / error，useFlash 預設 1.8s 返 idle | web/src/components/motion/button/stateful.tsx（StatefulButton） | 是 |
| New-device alert 狀態 badge | `preferences.alertNewDevice` 改變（喺 Notifications 改完返嚟 refetch） | AnimatedBadge success ↔ neutral label swap | web/src/components/motion/animated-badge.tsx | 是 |
| Connected channels 列表行 | `useMyChannels` 首次 settle | opacity + translateY 8px，delay i*min(40ms, 300ms/n)，總 ≤300ms；reduced motion 只 opacity | new（跟 web/src/features/workspace/member-access-sheet.tsx:61-69 motion 模式），唔用 .t-stagger-line | 是 |
| Needs reconnect badge | `needsReconnect(channel)` 為 true | AnimatedBadge warning `pulse`，其他狀態唔 pulse | web/src/components/motion/animated-badge.tsx（pulse） | 是 |
| 'Sign out {n} other sessions' 數字 | sessions list revoke 後改變 | DigitSwap 滾到新數；首次 render 靜止 | web/src/components/motion/digit-swap.tsx | 是 |
| Workspace Tier 數字 | refresh 後數值真係改變 | DigitSwap；首次 render 靜止，唔由 0 滾 | web/src/components/motion/digit-swap.tsx | 是 |
| Dialogs（email change、enrol、step-up、confirm、passkey rename） | open / close | `t-modal` 開快過收嘅 token（收快過開）+ backdrop | web/src/components/ui/dialog.tsx / alert-dialog.tsx（transitions.css:183-210） | 否（純裝飾） |
| 整頁 | route 進入 | `t-page-enter` | web/src/app/app/template.tsx:13 | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/me 回 displayName、mfa、preferences（含 alertNewDevice） | api | 有 | hosted_app.py:358；hosted.py:570-590；tests/phase2/postgres_account.py:167 | S |
| 2 | PATCH /api/me 接受 alertNewDevice | api | 有 | hosted.py:592-626；client.ts:120；types.ts:668-673；postgres_account.py:171-184 | S |
| 3 | New-device alert toggle UI | frontend | 有 | web/src/features/account/notifications-view.tsx:32-77 SecurityAlerts（Switch + updateProfile + invalidate keys.me） | S |
| 4 | Profile 上 new-device alert read-only 狀態行 + link 去 Notifications | frontend | 冇 | security-card.tsx / profile-view.tsx 冇讀 preferences.alertNewDevice | S |
| 5 | New-device email 寄送 + audit | backend | 有 | hosted.py:489-503；email.py:190-192；hosted_identity.py:94 email_for；要 public_base_url | S |
| 6 | 可分辨嘅 device label（browser family + OS family） | backend | 冇 | hosted_app.py:86-90 取 UA 第一個 '/' 之前 → 'Mozilla'；004 client_label ≤40；hosted.py:485 非空新 label 覆蓋 | S |
| 7 | Sessions table 顯示 firstSeen | frontend | 冇 | types.ts:643 有 firstSeen；security-card.tsx:686-723 只顯示 client / lastSeen | S |
| 8 | GET /api/me/channels 帶 per-capability matrix | api | 冇 | hosted.py:628-659 只出 connectionState；讀法喺 oauth.py:192-199（fallback assisted_matrix）；Capability type types.ts:436-441 | M |
| 9 | Shared channel helpers + CapabilityChips component | frontend | 有 | web/src/lib/channels/state.ts:59 channelBadge、:80 needsReconnect；web/src/lib/channels/capabilities.ts:17 CAPABILITY_CHIPS；web/src/features/channels/capability-chips.tsx:64 CapabilityChips | S |
| 10 | Profile channel rows 用 shared helper + chips，verified label 唔再講 'Connected' | frontend | 冇 | profile-view.tsx:44-49,389 仍 import profile-model.ts:62-80 重複 channelBadge；state.ts:63 同 profile-model.ts:66 都出 'Connected' | S |
| 11 | Step-up freshness 露出俾 UI（verifiedAt + windowSeconds） | api | 冇 | hosted_app.py:74 verify.auth_time；permissions.py:43 STEP_UP_WINDOW；hosted.py:570-590 me() 未回；assert_fresh 用喺 703/900/915 | S |
| 12 | Sessions revoke / revoke-others / mfa enable-disable endpoints | api | 有 | hosted_app.py:350,352,355,432；hosted.py:680-708,886-928；postgres_account.py | S |
| 13 | Supabase MFA（TOTP + WebAuthn）browser flow | frontend | 有 | web/src/lib/auth/mfa.ts；security-card.tsx:191-444；hosted_identity.py:111 verified_factors | S |
| 14 | Sign-in passkeys card | frontend | 有 | web/src/features/account/passkeys-card.tsx:98-234；web/src/lib/auth/passkeys.ts；profile-view.tsx:728 | S |
| 15 | Invitations to my email（list / accept / decline） | api | 有 | hosted_app.py:366,374；hosted.py:839-884；842-843 冇 email → available:false | S |
| 16 | Workspaces card error state + invitations unavailable note | frontend | 冇 | profile-view.tsx:440-441 冇讀 available；646-650 冇 error 分支；provider.tsx:51,55,63 有 status 'error' / error / refresh | S |
| 17 | Ownership transfer route + Members UI | backend | 冇 | hosted.py:730 raise；hosted_app.py 冇 transfer route；profile-view.tsx:610 copy | L |
| 18 | Linked sign-in identities（getUserIdentities / linkIdentity） | frontend | 冇 | web/src grep 無；session.tsx:102 只讀 app_metadata.provider | M |
| 19 | Tour / page tips infra | frontend | 有 | web/src/features/onboarding/tours.ts:156 PAGE_TOURS、tour-overlay.tsx、tour-mount.tsx:39 nudge、store.ts:40 'postriff-onboarding'、help-menu.tsx；template.tsx:15 TourMount | S |
| 20 | Profile page tour（profile-tips）+ data-tour anchors | frontend | 冇 | tours.ts 冇 '/app/account/profile'；profile-view.tsx / security-card.tsx / passkeys-card.tsx 冇 data-tour | S |
| 21 | Motion inventory 可重用件 | frontend | 有 | motion/animated-badge.tsx（pulse, contentKey）、motion/button/stateful.tsx:158、motion/digit-swap.tsx:48、ui/success-check.tsx、hooks/use-flash.ts:9 | S |
| 22 | Web unit tests for profile / channel helpers | frontend | 冇 | find web/src -name '*.test.*' 空；package.json scripts 只有 lint / lint:fix / typecheck | S |

## 3. Features

### P0

- **Capability-honest channel rows**：House rule 5：Profile 同 Channels 頁嘅 verified label 都係 'Connected'（profile-model.ts:66、lib/channels/state.ts:63）。`/api/me/channels` 加 `capabilities`（照 oauth.py:192-199），Profile 重用 CapabilityChips，label 改中性 'Verified'，publish / analytics / reply 各自由 matrix 講。一次過清走重複 helper。（depends on：GET /api/me/channels capabilities 欄）
- **認得出嘅 device 名 + First seen**：client_label 幾乎永遠 'Mozilla'（hosted_app.py:86-90），sessions list 同 new-device email 冇資訊量。改 browser family + OS family（coarse、≤40 字、冇版本號），並顯示已回傳未用嘅 firstSeen。

### P1

- **New-device alert 狀態喺 Profile 見得到**：Toggle 已經喺 Notifications（notifications-view.tsx:32-77），但 email link 返 Profile，而 Profile 冇講 alert 開咗未。加 read-only 狀態 + link，保持單一 control。
- **Step-up readiness（真數字嘅 sign-in window）**：revoke 單一 session、revoke others、turn off 2FA 都 assert_fresh（600 秒），UI 只含糊講 'a recent sign-in'。`/api/me` 加 `stepUp: {verifiedAt, windowSeconds}`，UI 講清楚，403 俾出路；唔 disable 按鈕（remind, don't block）。（depends on：GET /api/me stepUp 欄；確認 re-auth 會更新 auth_time）
- **Backup-method nudge + turn-off 韌性**：冇 recovery codes（security-card.tsx:569），只有一個 factor 時 lock-out 風險真；turnOff（489-496）半途失敗會殘留 factor。Warning badge + default 'Add backup method' + allSettled。
- **Workspaces card 三個誠實修正**：available:false 靜靜消失、provider error 冇 UI、owner copy 指向唔存在嘅 transfer（hosted.py:730）。
- **Profile page tips（重用 onboarding）**：Profile 係少數未註冊 PAGE_TOURS 嘅頁；加 profile-tips + data-tour，跟現有 nudge / help menu，唔整新 infra。

### P2

- **Ownership transfer（Members 頁 + step-up route）**：Owner 嘅 Leave 係死路；backend 明文話係 separate step-up action。唔屬 Profile 本身。（depends on：POST /api/workspaces/{id}/transfer-ownership（assert_fresh + owner only + audit））
- **Linked sign-in methods**：Identity card 只顯示一個 provider（session.tsx:102）。Supabase 支援 linkIdentity，但要 project 開 manual linking。（depends on：Supabase manual linking 設定）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明：「呢頁講我，唔係講 workspace」— 我係邊個（Identity）、點樣受保護（Security On/Off badge + Passkeys）、我可以去到邊（Channels、Workspaces）。page description（profile-view.tsx:718）已講呢三句；Two-factor Off 時 default 'Turn on' 係最強 CTA。教法跟現有 onboarding：喺 web/src/features/onboarding/tours.ts PAGE_TOURS 註冊 `profile-tips`（route '/app/account/profile'），第一次到訪由 tour-mount.tsx 出一次性 nudge toast（store.ts 'postriff-onboarding' 記 nudged/completed，唔自動開 overlay），之後隨時由 help menu 開。每步 target 用 `[data-tour=…]` 加 heading fallback。Copy 全 general，唔提任何品牌。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `['[data-tour="profile-identity"]', ...heading('profile')] — 要喺 IdentityCard `<Card>`（profile-view.tsx:206）加 data-tour` | Your name, everywhere | The name here is what teammates see in every workspace. Your email belongs to your sign-in; changing it sends a confirmation link first. |
| 2 | `['[data-tour="profile-2fa"]'] — 要喺 TwoFactor root div（security-card.tsx:512）加` | Turn on two-factor | Once it is on, every sign-in needs a second step, and the API refuses sessions without one. Add a second method as your backup: there are no recovery codes. |
| 3 | `['[data-tour="profile-sessions"]'] — 要喺 Sessions root div（security-card.tsx:660）加` | Where you are signed in | Every browser or device that used this account. Sign out anything you do not recognise. New-device alert emails are switched on under Notifications. |
| 4 | `['[data-tour="profile-channels"]'] — 要喺 ChannelsCard `<Card>`（profile-view.tsx:342）加` | What you can reach | Accounts connected across your workspaces. Each capability is rated on its own evidence, so an account can publish directly but only draft replies. Connecting happens on each workspace's Channels page. |
| 5 | `['[data-tour="profile-workspaces"]'] — 要喺 WorkspacesCard `<Card>`（profile-view.tsx:637）加` | Your role in each workspace | One owner, staff who run it, members who do the content work. Your role sets what you can do in each. Invitations sent to your email appear here. |

**Empty state 教咩**：Channels empty：邊個有權連接（role-aware）— 已有。Activity empty：將會出現啲咩（新 device sign-in、2FA 改動、revoked sessions、membership 改動），講明係 account 層。Invitations：available=false 講明「呢個 deployment 對唔到你嘅 email」。Sessions：永遠有 current device 一行。所有 empty 唔顯示 0。

## 5. Next steps（按次序）

1. **Capability-honest channels（backend）：hosted.py `my_channels` 用一次 `SELECT … FROM pr_channel_capabilities WHERE workspace_id = ANY(%s::uuid[])`（同 audit query 一樣 ANY，唔好 loop），砌 matrices，每個 channel 加 `capabilities`（CAPABILITIES 全部 key，fallback assisted_matrix / unsupported_matrix 同 oauth.py:197-199）；types.ts MyChannel 加 `capabilities: Record<string, Capability>`；postgres_account.py assert 形狀。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:628-659；web/src/lib/api/types.ts:676-693；tests/phase2/postgres_account.py`
2. **Capability-honest channels（frontend）：profile-view.tsx 改 import `channelBadge` / `needsReconnect` 自 web/src/lib/channels/state.ts，刪 profile-model.ts:60-80 重複；state.ts:63 label 改 'Verified' / 'Verified · read only'（Channels 頁一齊生效，要睇埋 channel-card.tsx）；row 第二行 render `CapabilityChips`。**（effort S）  
   檔案：`web/src/lib/channels/state.ts:59-71；web/src/features/account/profile-model.ts:60-80；web/src/features/account/profile-view.tsx:328-419；web/src/features/channels/capability-chips.tsx`
3. **Device label：hosted_app.py `client_label` 抽 browser family（Chrome / Safari / Firefox / Edge / 其他）+ OS family，'Chrome · macOS'，≤40 字、冇版本；postgres_account.py 加 UA → label 案例。security-card.tsx sessions 加 First seen 欄，current row 排首，`sm` 以下 stacked row。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:86-90；tests/phase2/postgres_account.py；web/src/features/account/security-card.tsx:686-723`
4. **Layout 重排 + anchors：security-card.tsx export TwoFactor / Sessions / SecurityActivity；profile-view.tsx grid 改 [Identity+Preferences | Security(2FA + alert 狀態行) + Passkeys] → [Sessions | Activity] → Channels → Workspaces → Account；每張卡加 id 同 data-tour；AccountActions 671 改 link #sessions；hosted.py:501 email link 加 #sessions。**（effort S）  
   檔案：`web/src/features/account/profile-view.tsx:656-742；web/src/features/account/security-card.tsx:813-829；web/src/features/account/passkeys-card.tsx；src/postriff_phase2/hosted.py:501`
5. **New-device alert 狀態行：讀 `useMe().data.preferences.alertNewDevice` 顯示 AnimatedBadge On/Off + link /app/account/notifications；最近一條 session.alerted relativeTime；info sidebar 第二段提及。**（effort S）  
   檔案：`web/src/features/account/security-card.tsx；web/src/features/account/profile-view.tsx:56-76`
6. **Workspaces card 誠實修正：PendingInvitations 讀 `available === false` note + `isError` Alert；WorkspacesCard 讀 provider `status === 'error'` Alert + Retry（refresh）；owner copy 610 改真話；Accept 用 StatefulButton。**（effort S）  
   檔案：`web/src/features/account/profile-view.tsx:434-524,600-611,634-654；web/src/lib/workspace/provider.tsx`
7. **2FA polish + 韌性：Badge 521 → AnimatedBadge；afterEnrol 成功播 SuccessCheck（useFlash）；single-factor 時 'No backup method' warning + default 'Add backup method'；turnOff 改 Promise.allSettled，失敗列喺 toast 並 refresh。**（effort S）  
   檔案：`web/src/features/account/security-card.tsx:478-577`
8. **Motion polish（全部讀真數據）：Save name StatefulButton；channel rows motion stagger（min(40ms, 300ms/n)，useReducedMotion）；'Sign out {n} other sessions' DigitSwap；Tier 數字 DigitSwap 只喺改變時；needsReconnect badge pulse。**（effort S）  
   檔案：`web/src/features/account/profile-view.tsx；web/src/features/account/security-card.tsx`
9. **Step-up readiness：hosted.py `me()` 加 `stepUp: {verifiedAt, windowSeconds: STEP_UP_WINDOW}`（auth_time 冇就 null）；types.ts Me 加欄；Sessions header 同 revoke dialogs 顯示 window 分鐘數，verifiedAt 超時時加提醒；revoke / revokeOthers / turnOff catch 403 → toast 原句 + 'Sign in again'（先驗證 /auth/sign-in 對已登入用戶會真係 re-auth）；postgres_account.py assert。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:570-590；src/postriff_phase2/permissions.py:43；web/src/lib/api/types.ts:651-665；web/src/features/account/security-card.tsx；tests/phase2/postgres_account.py`
10. **Profile page tips：tours.ts PAGE_TOURS 加 `profile-tips`（route '/app/account/profile'，5 步，target `[data-tour="profile-…"]` + heading fallback）；copy 用 onboarding 段落嘅 general 英文；PasskeysCard CardDescription 加 sign-in passkey vs 2FA 區分。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts；web/src/features/account/profile-view.tsx；web/src/features/account/security-card.tsx；web/src/features/account/passkeys-card.tsx`
11. **Unit tests：加 vitest（package.json `test` script），覆蓋 lib/channels/state.ts channelBadge（expiring、每個 state）、memberTiers、extraGrants（viewer 冇 extra）、describeSecurityEvent（session.alerted sent:false → warning）。**（effort S）  
   檔案：`web/package.json；web/src/lib/channels/state.test.ts（新）；web/src/features/account/profile-model.test.ts（新）`
12. **P2 Ownership transfer：hosted.py `transfer_ownership`（owner only、assert_fresh、target active member、原 owner 降 admin、audit）；hosted_app.py route；Members 頁 UI（重用 StepUpDialog 模式）；之後改 profile-view.tsx:610 同 notifications-view.tsx 相關 copy。**（effort L）  
   檔案：`src/postriff_phase2/hosted.py:717-740；src/postriff_phase2/hosted_app.py；web/src/features/workspace（Members）；web/src/features/account/profile-view.tsx:610`
13. **P2 Linked identities：web/src/lib/auth/identities.ts 包 getUserIdentities / linkIdentity / unlinkIdentity；IdentityCard Sign-in 列出所有 identities；session.tsx 讀 app_metadata.providers。**（effort M）  
   檔案：`web/src/lib/auth/identities.ts（新）；web/src/features/account/profile-view.tsx:304-313；web/src/lib/auth/session.tsx:95-104`

## Risks

- 另一個 session 正在改 web/src，而且 working tree 有大量未 commit 改動；落手前同步，commit 要 stage by path。
- 改 lib/channels/state.ts label 會同時改 Channels 頁（channel-card.tsx 等），要一齊驗，唔好只睇 Profile。
- 2FA turn-off 半途失敗：turnOff 先 DELETE enforcement 再逐個 unenroll；殘留 factor 會令 session.tsx statusFor 下次 sign-in 照樣要求 factor。Step 7 處理。
- 冇 recovery codes 係刻意，lock-out 風險真；nudge 只減少機率。sidebar 只可以寫真係存在嘅 support 流程。
- client_label 改法：舊 pr_sessions row 保持 'Mozilla' 直到該 device 再請求；revoked row 永遠舊 label；activity session.started 句子會新舊混合。
- `/api/me/channels` capability 查詢要一次 ANY(%s::uuid[])，唔好 per-workspace loop。
- Step-up 分鐘數必須嚟自 API（stepUp.windowSeconds），未落 step 9 前唔加數字；'Sign in again' 要確認已登入用戶去 sign-in 會真係更新 auth_time，否則會兜圈。
- Dev harness：mfa.available=false、invitations available:false、冇 public_base_url 唔寄 email — 好多段喺 dev 讀成 unavailable，UI 要顯示 'Not available…'，驗證要用真 Supabase deployment。
- Email change 'both inboxes' 類 copy 依賴 Supabase Secure email change 開咗；tour copy 已避開呢個講法。
- Onboarding progress 喺 localStorage（store.ts），private window 會再 nudge 一次；係現有 infra 嘅已知行為，唔另起 key。
- API restart 清 dev DB，驗證 sessions / activity 要 re-seed；dev harness Threads 係 live provider，測 channels card 唔好撳 Reconnect / Re-verify 以外嘅 action。
- i18n：UI copy 全英文，preferences locale 只改日期／數字格式；新 copy 唔好引入 UI 翻譯層，worldwide languages plan 係 post 語言。

## 覆核記錄

- 改正：web/src/app/app/account/profile/page.tsx:1-8 → ProfileView（profile-view.tsx:713-738），右欄只有 SecurityCard → ProfileView 714-742；layout 要包 PasskeysCard。
- 改正：Page enter 用 t-page-enter（template.tsx:8） → template.tsx:13，並註明 TourMount 已經喺度。
- 改正：IdentityCard 166-317、ChannelsCard 327-418、PendingInvitations 433-523、WorkspaceRow 525-631、WorkspacesCard 633-653、AccountActions 655-711 → 全部行號 +1。
- 改正：alertNewDevice 喺 web 冇任何 toggle（grep 只中 types.ts:660,668）→ P0 新增 toggle → Toggle 已存在於 /app/account/notifications。Profile 只加一行 read-only 狀態 + link，唔好整第二個 Switch（兩個真相來源）。
- 改正：Tour / onboarding infra 全 app 冇（grep data-tour|useTour|TourProvider 無） → 喺 PAGE_TOURS 加 'profile-tips'，唔好新建 components/tour/tour.tsx 或 postriff.tour.profile key。
- 改正：Channels 頁 state→status 對應喺 channels-view.tsx:82-88；建議抽去 web/src/lib/channels/state.ts → Profile 改 import lib/channels/state.ts + 重用 CapabilityChips；刪 profile-model 重複 helper。
- 改正：types.ts 行號：SessionInfo 637-644（firstSeen 639）、Me 647-662、ProfileChanges 664-669、MyChannel 672-685、SecurityEvent 694-702、PendingInvitation 705-714 → 用新行號。
- 改正：Channel 列表用 transitions.css:377 `.t-stagger-line`，40ms/行，總 ≤300ms → 跟 member-access-sheet.tsx:61-69 模式：motion + delay min(0.04, 0.3/n)，只 opacity/translateY，useReducedMotion。
- 改正：Tier 數字 NumberTicker 由 0 滾到真數 → 改為 DigitSwap，只喺數值真係改變（refresh 後）先郁，首次 render 靜止。
- 改正：新 tour 用 localStorage key `postriff.tour.profile` 自動開 5 步 → 註冊 profile-tips，跟現有 nudge 行為，help menu 開。
- 違反原則（已改）：Motion rule 4 / 2：Channels list 用 `.t-stagger-line`（500ms/行 + blur filter），總長超 300ms 而且唔係 transform/opacity only。
- 違反原則（已改）：真數據先郁：Tier 數字 NumberTicker 由 0 滾，會短暫顯示 API 冇回過嘅數（例如 'Owner 0'）。
- 違反原則（已改）：重複 toggle：再喺 Profile 加 alertNewDevice Switch 會同 notifications-view.tsx 嘅 SecurityAlerts 變兩個控制位，唔係違規但係錯誤假設（spec 以為唔存在）。
- 違反原則（已改）：Capability honesty 修法只改 profile-model.ts 嘅重複 helper，Channels 頁用嘅 lib/channels/state.ts:63 仲會出 'Connected'；label 'Publishing verified' 亦可能同 matrix 入面 publish=Assisted（assisted_matrix fallback）矛盾，等於另一個 blended 講法。
- 違反原則（已改）：Onboarding：新建 tour 組件 + 新 localStorage key 違反『Reuse before inventing』，現有 features/onboarding 已有 registry、overlay、help menu 同 nudge。
- 補上遺漏：PasskeysCard（passkeys-card.tsx，'Passkeys for sign-in'）完全冇提；layout 重排、tour、states 都要包埋佢，並講清楚同 2FA passkey factor 嘅分別。
- 補上遺漏：現有 lib/channels/state.ts、lib/channels/capabilities.ts、features/channels/capability-chips.tsx 可直接重用；profile-model.ts 重複 channelBadge/needsReconnect 應刪。
- 補上遺漏：features/onboarding PAGE_TOURS 機制同 data-tour 慣例（tours.ts:10-12, 51 heading fallback）。
- 補上遺漏：RBAC：Profile 無 nav access key；頁內 action 靠 canManage / role / canLeave；API 仍係唯一 enforcement。
- 補上遺漏：i18n：UI copy 全英文，preferences locale 只影響日期／數字格式（PreferencesProvider）；docs/postriff-worldwide-languages-plan.md 係 post 語言唔係 UI 語言，新 copy 唔好引入 UI 翻譯。
- 補上遺漏：'Sign in again' link：已登入狀態去 /auth/sign-in 可能被 redirect，要確認 re-auth 流程真係會更新 auth_time。
- 補上遺漏：Mobile：PasskeysCard 同 Sessions stacked row 都要喺 375px 驗；Identity dropdown 同 dialogs 喺細 mon。
- 補上遺漏：mfa-required status（session.tsx:36,108）時頁面點顯示 — 由 app gate 處理，spec 應註明唔重複。
