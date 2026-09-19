# 14 · Roles

> Route：`/app/workspace/roles` · Sidebar：Workspace · 成熟度：未 set up · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

而家嘅 Roles 頁係純靜態 reference，冇讀任何 workspace 數據。

**前端現況**
- `web/src/features/workspace/roles-view.tsx:1-9` 冇任何 `@/lib/api/hooks` hook；`:11` 硬寫 `ROLES`，`:12-21` 硬寫 8 個 permission label；`:35-42` 五張 card 只有 label + description；`:43-88` matrix 每格兩次 `allows()`（`:60-69`）；`:89-91` 硬寫「10 minutes」（真值 `permissions.py:43` `STEP_UP_WINDOW = 600`）。
- `:25-33` `PageContainer` 冇 `access`、`infoContent`、loading／error state、`data-tour`；motion 只有 `web/src/app/app/template.tsx:13` `.t-page-enter`。
- Matrix 來源係手抄 mirror `web/src/lib/auth/permissions.ts:8-20`，`:2-4` 明言人手 sync。
- Access：`web/src/lib/auth/access.tsx:61-63` `useWorkspaceAccess`、`:69-92` `checkAccess`；`web/src/lib/workspace/provider.tsx:131-134` membership、`:146-155` `permissionsFor`。
- Sidebar：`web/src/config/nav-config.ts:109-115` Roles（`:114` `manage_members`）。呢個 gate 只影響 sidebar（`web/src/hooks/use-nav.ts:23`）同 ⌘K（`web/src/components/kbar/index.tsx:11`）；route `web/src/app/app/workspace/roles/page.tsx` 同 roles-view 本身冇 gate，任何 member 打 URL 都入到，只係搵唔到。
- Sibling `web/src/features/workspace/members-view.tsx:45-66` infoContent 重複解釋 roles／step-up；`:239` `canManage`；`:263` `access={canManage}`；`:148`／`:161` mutation 後只 invalidate `keys.members`，唔 refresh provider。
- Onboarding：`web/src/features/onboarding/`（tours.ts、tour-mount.tsx、tour-overlay.tsx、help-menu.tsx、use-tour-context.ts；而家係另一 session 未 commit 嘅 WIP）已有 tour runner；`tours.ts:156` `PAGE_TOURS` 有 overview／brand／memory／inbox tips，冇 Roles；`TourCtx`（`tours.ts:14-24`）冇 `canManageMembers`。`data-tour` 已用喺 calendar／inbox／memory／brand／composer／queue／getting-started。
- 其他頁 permission gate：`web/src/features/agent/plan-card.tsx:114`（approve）、`web/src/features/queue/queue-view.tsx:178`（approve）、`web/src/features/channels/channels-view.tsx:180`（manage_connections）、`web/src/features/inbox/inbox-view.tsx:195`（reply），全部冇指去 Roles。

**後端真相（RBAC）**
- `src/postriff_phase2/permissions.py:10-11` ROLES／FLAGS；`:15-24` CLASSES（admin 預設冇 approve／reply／moderate）；`:27-39` ACTION_CLASSES；`:42` STEP_UP_ACTIONS；`:43` STEP_UP_WINDOW；`:59-65` allows；`:86-98` validate_grant。
- Step-up 真相唔止 STEP_UP_ACTIONS：佢只喺 `hosted.py:160` state command 路徑被讀；其餘係硬寫 `assert_fresh`——`hosted.py:703` disable MFA、`:721` update member、`:738` remove member、`:756` invite、`:900` revoke session、`:916` revoke other sessions、`:1022` delete account、`oauth.py:251` disconnect。
- Members service：`hosted.py:711-715` `members()` 任何 active member 可讀、冇 filter status、冇 displayName；`:717-733` update（`:722` 自己 409、`:730` owner 409）；`:735-747` remove；`:557-566` leave（`:561` owner 409）；`:749-769` invite；`:777-785` invitations；`:787-794` revoke。Ownership transfer 功能唔存在。
- Counts：`hosted.py:31-37` + `:60-70` → `GET /api/workspaces`（`hosted_app.py:368`）→ `web/src/lib/api/types.ts:37` `memberCounts`；但 provider（`provider.tsx:77`、`:80`）只喺 load 時更新，同 session 內會過時。
- Audit：`hosted.py:929-932`（任何 active member、LIMIT 200），kinds `member.updated :732`、`member.removed :746`、`member.left :565`、`invitation.created :764`、`invitation.revoked :793`、`invitation.accepted :829`、`invitation.declined :883`；route `hosted_app.py:465`；hook `hooks.ts:74-77`。
- `/api/me`（`hosted_app.py:358`、`hosted.py:570-592`）冇 verifiedAt／freshUntil。
- Route table `hosted_app.py`：members GET `:463`、PATCH/DELETE `:439-443`；invitations GET `:469`、POST `:471-473`、DELETE `:444-446`；leave `:474`；audit `:465`；public block `:283` catalog、`:286` privacy notice、`:313` tools；`_json`（`:178`）一律 `Cache-Control: no-store`。冇 `/api/permissions`、冇 transfer route。
- Client `web/src/lib/api/client.ts:235-244` members…revokeInvitation、`:245` audit、`:116` leaveWorkspace、`:119` me、`:102-105` unauthenticated gets（catalog／health／privacyNotice／models）。Hooks `hooks.ts:64-72` useMembers／useInvitations、`:104-108` useMe、`:127-130` useModels、`:144-147` usePrivacyNotice（staleTime 10 分鐘先例）。Types `types.ts:19-25` Membership、`:614-619` Member、`:621-631` Invitation、`:651` Me、`:720-727` AuditEvent。
- Tests：`tests/test_postriff_phase2_hosted.py:166-189` matrix、`:191-202` grant、`:204-210` production auth_time 缺 iat 當 stale。`web/package.json` 冇 test runner，驗證靠 `npm run typecheck`、`npm run lint`（oxlint）、`npm run build` + preview pane localhost:3100。
- Dev harness：`scripts/postriff_dev_hosted.py:45-55` DevVerifier 接受任何 `dev:<uuid>`（多 identity 可行，冇 seed script）；`:61-63` `auth_time` 回 `time.time()`，本機 step-up 永遠通過。

**RLS 前提**：`migrations/postriff/004_consumer_web_tenancy.sql:21` team_membership 已俾 member 睇隊友 user id 同 role；API `members()` 同 `audit_events()` 本身亦冇 permission require，開放 Roles 頁冇新增資料面。

## 1. Design specification（最新版）

**目的**：一頁答三條問題：（1）我喺呢個 workspace 係咩 role、可以做咩、唔可以就搵邊個；（2）五個 role 同四個 grant 嘅真實 matrix，以 API enforce 嗰份為準；（3）邊啲動作要 fresh sign-in。佢係 reference + 自我定位頁；invite／改 role／remove 留喺 Members；Roles 唯一獨有嘅管理動作係 Transfer ownership（P1）。

**Layout**：PageContainer（`web/src/components/layout/page-container.tsx`）+ `infoContent`。Page gate：`access={access.hasWorkspace}`，fallback「Join or create a workspace first.」（唔再用 manage_members）。Header：title「Roles」、description「What each role can do in this workspace, and where you stand.」；`pageHeaderAction` 只喺 `checkAccess(access, { permission: 'manage_members' })` 時顯示「Manage members」（outline + `LearnMoreChevron`、class `t-learn`），否則唔渲染。內容 `flex flex-col gap-6`，六個 region：

A「You in this workspace」（`data-tour='roles-you'`）：Card，AnimatedBadge（status `info`）顯示 role label；每個 true flag 一粒 outline Badge；「You can: …」由 `permissionsFor(membership)` + label；對每個缺失嘅 approve／reply／moderate／manage_connections 一句「To approve publications, ask an owner or admin to add the approve grant.」（viewer 改講「ask an owner or admin to change your role」，因為 flag 唔會升級 viewer）。Owner：「You own this workspace: every permission, billing and deletion.」

B「Roles」（`data-tour='roles-cards'`）：五張 card，`grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5`，owner→viewer。每張：label、description、右上角 active member count（由 `useMembers()` filter `status==='active'` 按 role 計，Members 頁 mutation 會 invalidate 同一 query）、自己嗰張「you」chip。Owner 喺 `access.role==='owner'` 時多「Transfer ownership…」（P1）。Section 標題旁註明「Active members」。

C「Permission matrix」（`data-tour='roles-matrix'`）：8×5 Table，數據來自 `usePermissionMatrix()`（`GET /api/permissions`）。第一列 label + Collapsible「What this covers」列出 `actions` 人話。每行 `id='permission-<key>'`。Cell 三態：✓（`aria-label='Yes'`）、「with grant」outline Badge + `ui/tooltip`（「An owner or admin can add the <flag> grant on Members.」；viewer 列永遠唔顯示 with grant，同 `permissions.py:65` 一致）、—（`aria-label='No'`）。你嘅 role 列 `bg-muted/40` + header「you」。外層 `overflow-x-auto`，第一列 `sticky left-0 bg-background`。

D「What you can grant」（`data-tour='roles-grants'`，只喺 manage_members 渲染）：可派 role chips（Admin／Editor／Approver／Viewer，對應 `validate_grant`）；可派 grant 四粒 chip 讀 `membership.can_*`（owner 全 ✓）；「You can only hand out grants you hold yourself. Nobody can change their own role.」（`hosted.py:722`）。

E「Sensitive changes」（`data-tour='roles-stepup'`）：列出 API `stepUpActions` 人話（Disconnect a channel／Delete the account／Invite someone／Change or remove a member／Sign out a session／Sign out other sessions／Turn off two-step verification；Transfer ownership 只喺 P1 落地後由 API 加入），文案「need a sign-in from the last {stepUpWindow/60} minutes」。P2：`/api/me.stepUp.freshUntil` 存在時顯示剩餘分鐘。

F「Recent role changes」（`data-tour='roles-recent'`）：`useAudit()` filter `member.`／`invitation.` 開頭，最新 10 條：relative time、人話 kind、subject 短 id、meta role／flags。底部「Open the audit log ›」只喺 `checkAccess(access, { role: 'admin' })`。對 editor／approver／viewer 開放呢個 region 係產品決定（API 已容許，nav 將 Audit 限 admin），落地前要 James 確認；未確認前先限 manage_members。

Infobar `infoContent`：{ title: 'Roles and grants', sections: [「Five roles, four grants」, 「Grants never elevate a viewer」, 「Recent sign-in required」(links: Members, Audit log)] }，由 `members-view.tsx:45-66` 搬過嚟。

Responsive：375px：A stack；B 一欄；C 用 CSS 切換（`md:hidden` list／`hidden md:block` Table，唔用 `useIsMobile` 避免 hydration 閃動），list 上方 motion `Tabs variant='segment'` 揀 role（預設你嘅 role，五個 segment 放唔落時容器 `overflow-x-auto`）；D chips wrap；E／F 全寬；gutter 16px，冇橫向 scroll；Infobar 係 Sheet（<768px）。768px：B 三欄；C Table + sticky 第一列；Infobar 係側欄（`use-mobile.ts:3` breakpoint 768 起唔係 Sheet）。1440px：B 五欄；C 全寬；Infobar 展開 22rem 時 content `min-w-0`。

文案：全部英文 UI copy 集中喺 `web/src/features/workspace/roles/copy.ts`；server 回穩定 key，client 對未知 key 顯示 raw key，方便將來 UI 本地化（而家 web 冇 i18n library）。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| You in this workspace | 五秒內答「我係邊個、可以做咩、唔可以就搵邊個」；每個限制都指出一條路。 | AnimatedBadge role；flag chips；「You can: …」；缺失 class 各一句 ask an owner or admin；viewer 講 change role；owner 專屬一句。數據：`useWorkspace().membership`（provider.tsx:131-134）+ `useWorkspaceAccess()`。 | membership 存在→渲染；冇 workspace→PageContainer access fallback。provider 未 ready 由 `web/src/components/layout/app-gate.tsx` 處理，頁面唔使另做。 |
| Roles (five cards) | 呢個 workspace 每個 role 有幾多 active 真人。 | label、`ROLE_DESCRIPTIONS`、count（useMembers active by role）、「you」chip、Owner card Transfer ownership（owner only，P1）。solo（active 總數 1）且 manage_members：「You're the only member. Invite someone from Members to hand out a role.」 | useMembers loading→數字位 `Skeleton h-6 w-8`；error→「—」+ sr-only「Member count unavailable」，永遠唔顯示 0；success→整數（0 只喺真係冇人時出現）。 |
| Permission matrix | 唯一真相：API enforce 嘅 CLASSES。 | 8×5 Table（<768px role segment + list）；`id='permission-<key>'`；「What this covers」；with grant tooltip；你嘅 role 列 highlight。數據 `usePermissionMatrix()`。 | loading→8 行 Skeleton；error→destructive Alert「The permission matrix couldn't be loaded.」+ Retry（`refetch()`），唔靜靜 fallback 去本地 mirror；success→表格。 |
| What you can grant | 將 `validate_grant` 同「唔可以改自己 role」提早講，避免喺 Members 撞 403／409。 | 可派 role chips；grant chips 讀 `membership.can_*`；兩句規則。 | 只喺 manage_members 渲染；其他人完全唔顯示。 |
| Sensitive changes (step-up) | 解釋點解某啲按鈕會叫你 sign in again。 | API `stepUpActions` + `stepUpWindow` 分鐘數；P2 倒數。 | 跟 matrix query loading／error；冇 `freshUntil`→唔顯示倒數。 |
| Recent role changes | 答「邊個幾時改咗邊個 role」。 | `useAudit()` filter member.*／invitation.*，最新 10 條；admin／owner 見「Open the audit log ›」。 | loading→Skeleton h-24；空→「No role changes in the latest 200 workspace events.」；error→inline Alert「Couldn't load recent changes.」+ Retry；success→list，冇 pop-in 動畫。 |

- **Empty state**：整頁冇全空情況（matrix 永遠有內容）。局部空態：（1）Solo workspace：Owner card 顯示真值 1 + you，其餘四張顯示真 0；manage_members 見「You're the only member. Invite someone from Members to hand out a role.」加一句 general 例子「an approver for whoever signs off, an editor for whoever drafts, a viewer for whoever only needs to read」；冇 manage_members 嘅人唔見 CTA。（2）Recent role changes 空：「No role changes in the latest 200 workspace events.」（唔推斷「只有 owner」）。
- **Loading**：Header 即時 paint。Region A 用 provider 已 load 嘅 membership，唔使 skeleton。Region B counts：`useMembers()` isLoading→每張 card 數字位 `Skeleton h-6 w-8`，label／description 照常顯示。Region C／E：`usePermissionMatrix()` isLoading→8 行 Skeleton（`t-skel-pulse`）。Region F：`Skeleton h-24`。冇任何「Loading roles…」文案。
- **Error**：（1）`GET /api/permissions` 失敗：Region C／E destructive Alert + Retry，唔 fallback 本地 mirror。（2）`useMembers` 失敗：counts 顯示「—」+ sr-only「Member count unavailable」，其他 region 照常。（3）`useAudit` 失敗：Region F inline Alert + Retry。（4）403「Workspace unavailable.」：由 query error 顯示「This workspace is unavailable.」，唔當成冇權限。（5）Transfer ownership 失敗（403 step-up／404／409）：toast.error 用 API message 原文，dialog 保持開住可重試。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁 | route enter | page fade + slide 250ms（`--page-fade-dur`／`--page-slide-dur`）；唔再加 card stagger | `web/src/app/app/template.tsx:13` `.t-page-enter` | 否（純裝飾） |
| Role card member count | useMembers 資料到達／refetch 後數值改變 | 數字滾動（NumberTicker 預設 0.9s、stagger 0.04），只喺 count 係整數時渲染；loading 係 Skeleton，unavailable 係「—」 | `web/src/components/motion/number-ticker.tsx`（Billing／Analytics 同一用法） | 是 |
| Region A role badge | `membership.role` 改變（例如 transfer ownership 後 `refresh()`） | icon + 文字 roll 換（`contentKey={role}`） | `web/src/components/motion/animated-badge.tsx` | 是 |
| Matrix with grant cell | hover／focus | tooltip 80ms delay、150ms 開、50ms 收（transitions.css:118-121） | `web/src/components/ui/tooltip.tsx` | 是 |
| <768px role segment | tap 一個 role | segment indicator 滑到選中 role，list 即時換內容 | `web/src/components/motion/tabs.tsx` `variant='segment'` | 是 |
| Matrix 行 hover／你嘅 role 列 | hover | 只改 background-color，150ms | Tailwind `transition-colors` + `--duration-quick`（transitions.css:22） | 否（純裝飾） |
| Deep link 到達嘅 permission 行 | mount 時 `location.hash` 對應 `permission-<key>` | `scrollIntoView({ block: 'center' })`（reduced motion 用 `behavior: 'auto'`）+ `bg-primary/10` 150ms 後褪走，只改顏色 | new（transitions.css token） | 是 |
| 「Manage members ›」「Open the audit log ›」 | hover／focus | chevron 右移成箭嘴 | `web/src/components/ui/learn-more-chevron.tsx` + `t-learn` | 否（純裝飾） |
| Transfer ownership 確認（P1） | 用戶喺 dialog 內確認 | 破壞性動作保留確認（motion §5.5）：dialog 內用長按按鈕 | `web/src/components/motion/hold-action-button.tsx` | 否（純裝飾） |
| Transfer ownership 完成（P1） | API 200 之後同一 view | 剔號畫出，只喺今次真係轉咗先播；reload 唔重播 | `web/src/components/ui/success-check.tsx` `animate` | 是 |
| Skeleton（counts、matrix、recent changes） | query isLoading | pulse | `web/src/components/ui/skeleton.tsx`（`t-skel-pulse`） | 是 |
| Step-up 剩餘分鐘（P2） | 每 60s tick，值 = `freshUntil - now` | 分鐘數字 roll，到 0 時整行消失 | `web/src/components/motion/digit-swap.tsx` | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | `permissions.describe()`：回 `{ roles, flags, classes: {key: {roles, flag}}, actions: {action: class}, stepUpActions: [key], stepUpWindow }`，只回穩定 key；stepUpActions 係明確 list，覆蓋全部 `assert_fresh` call site（member_update／member_remove／invitation_create／p2_channel_disconnect／delete_account／session_revoke／sessions_revoke_others／mfa_disable） | backend | 冇 | `src/postriff_phase2/permissions.py` 冇 serialisation；STEP_UP_ACTIONS（:42）漏咗 `hosted.py:703` disable MFA 同 `:916` revoke other sessions | S |
| 2 | `GET /api/permissions`（public，放 `hosted_app.py:286` privacy notice 之後，沿用 `_json` no-store） | api | 冇 | `hosted_app.py:283-313` public block 冇；`:178` `_json` 寫死 no-store | S |
| 3 | Backend test：payload classes == CLASSES、stepUpWindow == 600、每個 ACTION_CLASSES key 喺 actions、stepUpActions 包含 STEP_UP_ACTIONS 全部；另加一個測試讀 `web/src/lib/auth/permissions.ts` 文字比對 CLASSES（因為 web 冇 test runner） | backend | 冇 | `tests/test_postriff_phase2_hosted.py:166-202` 只測 Membership／validate_grant | S |
| 4 | 前端 contract：`types.ts` `PermissionMatrix`；`client.ts` `permissions: () => get<PermissionMatrix>('/api/permissions', false)`；`hooks.ts` `keys.permissions` + `usePermissionMatrix()`（staleTime 10 分鐘）；label map 喺 `web/src/features/workspace/roles/copy.ts`，未知 key 顯示 raw key | frontend | 冇 | 先例 `client.ts:104` privacyNotice、`hooks.ts:144-147` usePrivacyNotice | S |
| 5 | 每個 role 嘅 active member count（live） | data | 有 | `hosted.py:711-715` members()（任何 active member 可讀）→ `hosted_app.py:463` → `client.ts:235` → `hooks.ts:64-67` useMembers；Members mutation invalidate 同一 key（`members-view.tsx:148`、`:161`）。provider `memberCounts`（`hosted.py:37` → `types.ts:37`）只喺 load 時更新，唔用 | S |
| 6 | 當前 member 嘅 role + 四個 flag 喺 client | frontend | 有 | `provider.tsx:131-134` membership、`:146-155` permissions；`access.tsx:61-63` useWorkspaceAccess | S |
| 7 | Audit events（member.*／invitation.*）endpoint + hook | api | 有 | `hosted_app.py:465` → `hosted.py:929-932`（LIMIT 200）；kinds `:732`、`:746`、`:565`、`:764`、`:793`、`:829`、`:883`；hook `hooks.ts:74-77` | S |
| 8 | Nav gate 改為所有 member 可見：`nav-config.ts:114` 移除 `access`；roles-view PageContainer `access={access.hasWorkspace}` | frontend | 冇 | `nav-config.ts:114` `{ permission: 'manage_members' }`；roles-view 冇 page gate | S |
| 9 | PageContainer `access`／`accessFallback`／`infoContent`／`pageHeaderAction` props | frontend | 有 | `page-container.tsx:24-42` | S |
| 10 | Permission 行 anchor `id='permission-<key>'` + 其他頁 deep link | frontend | 冇 | `roles-view.tsx:57` TableRow 冇 id；call sites `plan-card.tsx:114`、`queue-view.tsx:178`、`channels-view.tsx:180`、`inbox-view.tsx:195`（逐個確認係 hide 定 disable） | S |
| 11 | Roles page tips：`tours.ts` PAGE_TOURS 加 `roles-tips`；`TourCtx` + `use-tour-context.ts` 加 `canManageMembers`；六個 `data-tour` anchor | frontend | 冇 | tour runner 已存在 `web/src/features/onboarding/tours.ts:156`（untracked WIP）；冇 Roles entry；`TourCtx` `tours.ts:14-24` 冇 canManageMembers | S |
| 12 | Ownership transfer：`POST /api/workspaces/{id}/owner` body `{ userId }`，owner-only + `assert_fresh`，一個 transaction：目標 active 且 ≠ principal、目標 role→owner + 四 flag true、actor→admin（flag 保留）、audit `owner.transferred`；stepUpActions 加 `owner_transfer` | backend | 冇 | `hosted.py:730`、`:561` 引用唔存在嘅動作；`004_consumer_web_tenancy.sql:8-9` role check 已容許 owner | M |
| 13 | Transfer ownership UI：`client.ts` `transferOwnership`、Owner card action、member picker（useMembers，排除 you 同非 active）、HoldActionButton 確認、StepUpDialog、成功後 `refresh()` + invalidate members／audit | frontend | 冇 | `web/src/features/account/security-card.tsx:72-188` StepUpDialog 未 export；`provider.tsx:63` `refresh` | M |
| 14 | `GET /members` 回 `displayName`（join `pr_profiles`） | backend | 冇 | `hosted.py:713` 只 select pr_memberships；`:36` 有 join 先例；`types.ts:614-619` 冇 displayName；profiles RLS 係 self-only（004:20 註解），要經 service 層回 | S |
| 15 | `/api/me` 回 `stepUp: { verifiedAt, freshUntil }`（冇 auth_time 回 null） | api | 冇 | `hosted.py:570-592` 冇；`hosted_identity.py:36` verified_auth_time 存在；dev harness `scripts/postriff_dev_hosted.py:61-63` 永遠回 now | S |
| 16 | Motion 元件：NumberTicker、AnimatedBadge、Tabs(segment)、HoldActionButton、DigitSwap、ui/tooltip、ui/skeleton、success-check、learn-more-chevron | frontend | 有 | `web/src/components/motion/{number-ticker,animated-badge,tabs,hold-action-button,digit-swap}.tsx`；`web/src/components/ui/{tooltip,skeleton,success-check,learn-more-chevron}.tsx` | S |

## 3. Features

### P0

- **Matrix 由 API 提供（`GET /api/permissions`），唔再手抄**：真數據先郁：顯示嘅就係 `permissions.py:15-24` enforce 嗰份；`permissions.ts:2-4` 靠人手 sync。stepUpActions 要覆蓋全部 assert_fresh call site，唔係淨係 STEP_UP_ACTIONS。
- **「You in this workspace」自我定位 panel**：第一次嚟嘅人最想知「我可唔可以 approve，唔可以搵邊個」。每個限制都指出一條路（ask an owner or admin），UI 唔俾死路；role 限制係 owner 嘅 authorization 決定，唔係內容規則。
- **開放俾所有 member（移除 nav gate，page gate 改 hasWorkspace）**：`nav-config.ts:114` 令 editor／approver／viewer 喺 sidebar／⌘K 搵唔到唯一解釋佢哋限制嘅頁；RLS `004:21` 同 API 已容許 member 睇隊友 role，冇新暴露。管理動作仍按 permission 條件渲染。
- **每個 role 嘅 live active member count + solo 提示**：由 `useMembers()` 計，Members 改完即時更新；provider memberCounts 會過時所以唔用；unavailable 顯示「—」唔係 0。
- **Permission 行 anchor + 其他頁 deep link**：`plan-card.tsx:114`、`queue-view.tsx:178`、`channels-view.tsx:180`、`inbox-view.tsx:195` 冇解釋點解唔得；加「Needs the <permission> permission · See Roles」連去 `/app/workspace/roles#permission-<key>`。

### P1

- **Roles page tips（現有 tour runner）**：`features/onboarding/tours.ts` PAGE_TOURS 已經係每頁 tips 嘅機制，加 roles-tips 零新基建。（depends on：onboarding WIP commit；TourCtx 加 canManageMembers）
- **Transfer ownership（Owner card 專屬動作）**：`hosted.py:730`、`:561` 都指向一個唔存在嘅動作，owner 永遠離開唔到 workspace；單一 owner 模型下 transfer 係必須嘅出口，Members 頁 owner row 唔可編輯，Roles 係自然位置。（depends on：backend route + stepUpActions + StepUpDialog export）
- **Recent role changes（audit 過濾）**：用現有 `useAudit()` 答「邊個幾時改咗 role」，零後端。對非 admin 開放要 James 確認（Audit nav 限 admin）。（depends on：產品決定：非 manage_members 可唔可以見）
- **What you can grant**：`validate_grant`（`permissions.py:86-98`）同 `hosted.py:722`（唔可以改自己）而家只會提交後以 403／409 出現。

### P2

- **Step-up 剩餘分鐘**：「sign-in from the last 10 minutes」係死文字；`/api/me` 加 freshUntil 後顯示真值，冇就唔顯示。注意 dev harness 永遠 fresh，要喺 production-like identity 驗證。（depends on：`/api/me` 加 stepUp）
- **Member displayName**：audit actor／subject 同 Members 表只顯示 uuid；`hosted.py:36` 有 join 先例。（depends on：`GET /members` join pr_profiles）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明白三樣嘢：（1）「我係 <role>，可以 X、Y，唔可以 Z——要 Z 就搵 owner／admin」（Region A 最頂）；（2）「五個 role 由 owner 到 viewer，grant 加單一權利，永遠唔會升級 viewer」（Region B 順序 + matrix 你嘅 role 列 highlight）；（3）「敏感動作要 fresh sign-in」（Region E）。頁面唔靠 tour 都教到；tips 經 help menu 開（`features/onboarding/help-menu.tsx`）。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour='roles-you']` | Where you stand | This is your role in this workspace and what it lets you do. If something you need is missing, the line underneath says who can grant it. |
| 2 | `[data-tour='roles-cards']` | Five roles, most to least trusted | Owners run everything including billing. Admins manage people and channels. Editors write, approvers sign off, viewers read. Each number is how many active members hold that role. |
| 3 | `[data-tour='roles-matrix']` | The rules the server checks | Every tick here is checked on each action. 'With grant' means an owner or admin can add that single right without changing someone's role. Grants never apply to viewers. |
| 4 | `[data-tour='roles-stepup']` | Sensitive changes ask you to sign in again | Changing members, disconnecting a channel or deleting the account only work shortly after a fresh sign-in, so those buttons sometimes ask you to sign in first. |
| 5 | `[data-tour='roles-grants'] (when: ctx.canManageMembers；fallback heading)` | Hand out roles on Members | Invites, role changes and grants live on the Members page. You can only hand out grants you hold yourself. |

**Empty state 教咩**：Solo workspace（Owner 1、其他真 0）對 manage_members 顯示：「Invite someone from Members and pick the role that matches what they should do: an approver for whoever signs off, an editor for whoever drafts, a viewer for whoever only needs to read.」Recent changes 空：「No role changes in the latest 200 workspace events.」兩句對 designer、teacher、shop owner、developer 讀起嚟一樣，冇品牌或行業字眼，亦冇推斷 API 冇講嘅事。

## 5. Next steps（按次序）

1. **Backend：`permissions.py` 加 `STEP_UP_KEYS`（明確覆蓋全部 assert_fresh call site）同 `describe()`（只回 key）；`hosted_app.py:286` 之後加 `if path == '/api/permissions' and method == 'GET'`（沿用 `_json`）；tests 斷言 classes == CLASSES、stepUpWindow == 600、actions 覆蓋 ACTION_CLASSES、stepUpActions ⊇ STEP_UP_ACTIONS，另加一個測試讀 `web/src/lib/auth/permissions.ts` 比對 CLASSES。**（effort S）  
   檔案：`src/postriff_phase2/permissions.py; src/postriff_phase2/hosted_app.py; tests/test_postriff_phase2_hosted.py`
2. **前端 contract：`types.ts` `PermissionMatrix`；`client.ts` 照 `:104` 加 `permissions`；`hooks.ts` 加 `keys.permissions` + `usePermissionMatrix()`（照 `:144-147` staleTime 10 分鐘）。**（effort S）  
   檔案：`web/src/lib/api/types.ts; web/src/lib/api/client.ts; web/src/lib/api/hooks.ts`
3. **Nav + page gate：`nav-config.ts:114` 移除 Roles `access`；roles-view `access={access.hasWorkspace}`；Members `:107`、Audit `:120` 唔郁。**（effort S）  
   檔案：`web/src/config/nav-config.ts; web/src/features/workspace/roles-view.tsx`
4. **重寫 `roles-view.tsx`：拆成 `web/src/features/workspace/roles/{you-card,role-cards,permission-matrix,grants-card,step-up-card,recent-role-changes,copy}.tsx|ts`；counts 用 `useMembers()` active by role；matrix/list 用 CSS breakpoint 切換；每行 `id='permission-<key>'`；六個 `data-tour`；loading／error／empty 照 design_spec；唔加 card stagger。**（effort M）  
   檔案：`web/src/features/workspace/roles-view.tsx; web/src/features/workspace/roles/*`
5. **搬 infoContent：`members-view.tsx:45-66` 嘅 roles／step-up 段搬去 Roles；Members 保留 Invitations 並加 link 去 `/app/workspace/roles`。**（effort S）  
   檔案：`web/src/features/workspace/members-view.tsx; web/src/features/workspace/roles-view.tsx`
6. **Deep link：逐個確認 `plan-card.tsx:114`、`queue-view.tsx:178`、`channels-view.tsx:180`、`inbox-view.tsx:195` 係 hide 定 disable，喺相應位置加「Needs the <permission> permission · See Roles」（`text-muted-foreground text-xs`）；`permission-matrix.tsx` mount 讀 `location.hash` scroll + 短暫 bg highlight（reduced motion 用 instant scroll）。**（effort S）  
   檔案：`web/src/features/agent/plan-card.tsx; web/src/features/queue/queue-view.tsx; web/src/features/channels/channels-view.tsx; web/src/features/inbox/inbox-view.tsx; web/src/features/workspace/roles/permission-matrix.tsx`
7. **Recent role changes：`useAudit()` filter + `slice(0, 10)`；先限 manage_members，等 James 決定係咪開放俾所有 member；「Open the audit log ›」按 `{ role: 'admin' }`。**（effort S）  
   檔案：`web/src/features/workspace/roles/recent-role-changes.tsx`
8. **Roles page tips：onboarding WIP commit 之後，`tours.ts` PAGE_TOURS 加 `roles-tips`（route `/app/workspace/roles`、stop 'Roles'、target 陣列包 heading fallback）；`TourCtx` 同 `use-tour-context.ts` 加 `canManageMembers`，grants step 用 `when`。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts; web/src/features/onboarding/use-tour-context.ts`
9. **Ownership transfer backend：stepUp keys 加 `owner_transfer`；`hosted.py` 加 `transfer_ownership`（require owner、assert_fresh、目標 active 且 ≠ principal、兩行 FOR UPDATE、audit `owner.transferred`）；`hosted_app.py` `:474` 附近加 `parts[3]=='owner' and method=='POST'`；`:561`、`:730` 文案指向「Transfer ownership on the Roles page」；tests：非 owner 403、自己 409、非 active 404、成功後 owner 只有一個。**（effort M）  
   檔案：`src/postriff_phase2/permissions.py; src/postriff_phase2/hosted.py; src/postriff_phase2/hosted_app.py; tests/test_postriff_phase2_hosted.py`
10. **Ownership transfer UI：export `StepUpDialog`（`security-card.tsx:72-188`）去 `web/src/features/account/step-up-dialog.tsx`；`client.ts` 加 `transferOwnership`；Owner card → Dialog（Select active member，HoldActionButton 確認）→ StepUpDialog → 成功：SuccessCheck、toast、`refresh()`、invalidate members／audit。落地前確認 billing contact 唔會跟住轉走。**（effort M）  
   檔案：`web/src/features/account/step-up-dialog.tsx; web/src/features/account/security-card.tsx; web/src/lib/api/client.ts; web/src/features/workspace/roles/role-cards.tsx`
11. **P2：`hosted.py:713` join `pr_profiles` 回 displayName（`types.ts:614` Member 加欄）；`me()` 加 `stepUp`（`types.ts:651` Me 加欄），Region E 用 DigitSwap。**（effort S）  
   檔案：`src/postriff_phase2/hosted.py; web/src/lib/api/types.ts; web/src/features/workspace/roles/step-up-card.tsx; web/src/features/workspace/members-view.tsx`
12. **驗證：`npm run typecheck`、`npm run lint`、`npm run build`；preview pane localhost:3100（唔係 4331），375／768／1440 light／dark；用第二個 browser context（新 `dev:<uuid>`）接受 invitation 做 approver，驗證 counts 即時更新、非 owner 文案、recent changes；本機 step-up 永遠通過，「Sign in again」路徑要靠 production verifier 測試；全程唔撳 approve／schedule／send／disconnect。**（effort S）  
   檔案：`web/ (verification only)`

## Risks

- Mirror drift：`permissions.ts:8-20` 同 `permissions.py:15-24` 仍靠人手同步；`checkAccess`／nav 繼續用本地 mirror。web 冇 test runner，所以比對測試要放 backend（讀 TS 檔文字），否則 Roles 頁顯示 API 版、按鈕 gate 用本地版會自相矛盾。
- Step-up 真相分散：大部分 step-up 係硬寫 `assert_fresh`，唔經 STEP_UP_ACTIONS；新增一個 step-up 動作而冇更新 describe() 就會令 Roles 頁講少咗。長遠應令 assert_fresh 接受 action key 並斷言喺 list 入面。
- Remind-don't-block 邊界：role 限制係 authorization，唔係內容規則；但 UI 唔可以係死路，每個被隱藏／disabled 嘅 control 同 Region A 都要講明邊個可以開。deep link（step 6）唔做，開放咗都冇人搵到。
- Dev harness `DevVerifier.auth_time` 永遠回 now（`scripts/postriff_dev_hosted.py:61-63`），本機驗證唔到 step-up 失敗路徑，P2 倒數喺本機永遠係 10 分鐘。
- Ownership transfer 會改變邊個可以碰 billing 同 privacy 決定（ACTION_CLASSES p2_plan／memory_egress／research_egress／preference 係 owner-only）；Stripe customer 可能綁舊 owner email，落地前要 review billing checkout 路徑。
- Counts 只計 active；Members 表（`hosted.py:713` 冇 filter status）會顯示 revoked row，兩頁數字可能唔對辦，Roles 要標明「Active members」。
- Recent role changes 靠 client 過濾最新 200 條 audit（`hosted.py:931`），活躍 workspace 會被推出 window；之後要喺 audit endpoint 加 kind prefix filter。開放俾非 admin 睇係產品決定。
- Parallel sessions：`web/src/features/onboarding/` 仲係 untracked WIP，step 3–8、10 全部觸及 web/src；要協調時序，stage by path，唔好整棵 tree commit。
- Per-channel permission 唔喺範圍；matrix 係 workspace-wide，Roles 頁唔可以出現 per channel 欄位，亦唔可以同 Channels 嘅 Direct／Assisted／Unsupported matrix 混埋。
- 開放 Roles 俾 viewer 會顯示每個 role 人數；RLS `004:21` 同 API `members()` 已容許，冇新資料面；Region D 同 header action 一定要條件唔渲染，唔係 disabled。

## 覆核記錄

- 改正：STEP_UP_ACTIONS 就係所有 step-up 動作嘅真相，可以直接 serialise 做 stepUpActions → describe() 嘅 stepUpActions 要係一份明確嘅 list，覆蓋全部 assert_fresh call site；加 backend test grep/枚舉 call sites 或者將 assert_fresh 改為接受 action 名並斷言 action ∈ STEP_UP_ACTIONS
- 改正：editor／approver／viewer 完全見唔到呢頁 → 改寫為「喺 sidebar／⌘K 搵唔到，但 URL 本身冇 gate」
- 改正：members-view.tsx:46-64 infoContent、:239 canManage、:245-248 整頁 gate → 改為 :45-66、:239、:263
- 改正：全個 web/src 冇 tour runner、冇 data-tour；唯一 data-testid 係 getting-started.tsx:66 → tour 用現有 PAGE_TOURS 格式（id/route/stop/target[]/title/body/when），加 'roles-tips'
- 改正：channels-view.tsx:329 manage_connections gate → 改為 :180
- 改正：provider 已經 load 咗 memberCounts，可以直接做 Roles counts 真數據 → counts 改由 useMembers()（hosted.py:711-715，任何 active member 可讀、Members mutation 會 invalidate）filter status==='active' 按 role 計；provider memberCounts 只作 workspace switcher/profile 用
- 改正：GET /api/permissions 可以回 Cache-Control: public, max-age=300 → 沿用 _json（no-store），靠前端 staleTime 10 分鐘 cache；唔好為咗呢個 endpoint 改 _json
- 改正：client.ts :232-241 members…revokeInvitation、:242 audit、:116 leaveWorkspace、:119 me、:102 catalog（唯一 unauthenticated get 先例） → 改行號；先例改引 privacyNotice :104
- 改正：hooks.ts :64-72 useMembers/useInvitations、:74-77 useAudit、:112-115 useMe、:126-129 useModels → useMe 改 :104-108
- 改正：types.ts :19-25 Membership、:610-627 Member/Invitation、:716-723 AuditEvent、:647 Me → 更正行號
- 改正：Dev harness（scripts/postriff_dev_hosted.py:170-171）只有一個 dev identity，冇多 member → 改為「dev harness 支援多個 dev:<uuid> identity，但冇 seed script；要用第二個 browser context 接受 invitation」
- 改正：Dev harness 冇 auth_time，本機所有 step-up 動作都會 403 → risk 改寫：本機 step-up 永遠通過，所以本機驗證唔到「Sign in again」路徑；freshUntil 喺 dev 會永遠等於 now+600，倒數喺本機冇意義
- 改正：security-card.tsx:72-160 StepUpDialog module-private → 改為 :72-188
- 改正：五張 role card 用 .t-stagger-line 40ms stagger，總長 ≤ 300ms → 刪除 card stagger，靠 .t-page-enter
- 改正：NumberTicker「Overview／Billing 同一用法」 → 改為 Billing／Analytics
- 改正：768px Infobar 以 Sheet 形式出現；375px 用 useIsMobile 切換 Tabs → Sheet 只喺 <768px；Table/list 切換用 CSS（md:hidden／hidden md:block）避免 hydration 閃動
- 改正：Recent role changes 空態「No role changes yet — this workspace still has its original owner only.」 → 改為「No role changes in the latest 200 workspace events.」，並喺 counts>1 時唔講 owner only
- 違反原則（已改）：真數據先郁：Region B counts 讀 provider 嘅 memberCounts，但佢只喺 session 開頭 load，Members 改完唔會 refresh（members-view.tsx:148/161 只 invalidate keys.members），同一 session 會顯示過時數字。
- 違反原則（已改）：真數據先郁：Recent changes 空態文案「this workspace still has its original owner only」係推斷，唔係 API 事實（LIMIT 200 window）。
- 違反原則（已改）：真數據先郁：stepUpActions 直接 serialise STEP_UP_ACTIONS 會漏 disable MFA 同 revoke other sessions（hosted.py:703、:916 硬寫 assert_fresh），顯示一份唔完整嘅「真相」。
- 違反原則（已改）：Motion §5.4：card stagger 用 .t-stagger-line（500ms + 160ms offset = 660ms）超過 300ms 上限，亦同 .t-page-enter 重疊。
- 違反原則（已改）：Motion §5.1：card stagger reads_real_data=false，純裝飾入場。
- 違反原則（已改）：Motion §5.3：.t-stagger-line 係 SSR marketing headline reveal（transitions.css:370-374），唔應該用喺 app 內 client card。
- 違反原則（已改）：P2 倒數喺 dev harness 永遠 fresh（DevVerifier.auth_time = time.time()），spec 聲稱本機會 403 係錯，亦令倒數喺本機冇驗證價值。
- 違反原則（已改）：Capability honesty 冇違反；general-not-personal 文案冇違反；remind-don't-block：role 限制係 authorization 唔係內容規則，spec 處理正確。
- 補上遺漏：RBAC：Roles 頁本身冇 PageContainer access gate，任何 member 直接打 URL 已經入到；spec 冇講明開放後 page-level gate 應該係 hasWorkspace 而唔係 permission。
- 補上遺漏：Tour runner 已經存在（features/onboarding/tours.ts PAGE_TOURS、TourMount、help-menu），spec 應該加 'roles-tips' 並擴充 TourCtx（冇 canManageMembers），唔係話「tour 係 inert」。
- 補上遺漏：Tour step 5 target a[href='/app/workspace/members'] 對冇 manage_members 嘅人唔存在（sidebar 隱藏），要 when: ctx.canManageMembers，否則 tour 會 fallback 去 heading。
- 補上遺漏：Recent role changes 開放俾 viewer：API 允許（hosted.py:929 冇 require），但 nav 將 Audit 限 admin；呢個係產品決定，要 James 確認，而且只顯示 member.*／invitation.* kinds，唔好漏 security kinds。
- 補上遺漏：Counts 同 matrix 喺 workspace switch 時要跟 workspaceId 換（query key 已 scoped，但要講明）。
- 補上遺漏：i18n：web 冇 i18n library，UI copy 係英文；server label 應該用穩定 key，client 對未知 key 顯示 raw key 而唔係空白，方便將來 UI 本地化（docs/postriff-worldwide-languages-plan.md 只處理 post language，唔涵蓋 UI）。
- 補上遺漏：Mirror drift 冇 frontend test runner，所以「前端 constant 對照測試」做唔到；要改為 backend test 讀 web/src/lib/auth/permissions.ts 文字比對，或者 dev-only console.warn 對照 API。
- 補上遺漏：另一 session 嘅 onboarding 目錄仲係 untracked，Roles 改動依賴 tours.ts 要等佢 commit。
- 補上遺漏：Transfer ownership 屬破壞性動作，motion §5.5 要求 dialog 或長按確認；可 reuse HoldActionButton。
