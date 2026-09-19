# 13 · Members

> Route：`/app/workspace/members` · Sidebar：Workspace · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

頁面已經 end-to-end 行到（邀請、改 role、移除、撤銷邀請），但停留喺「API 有咩就照出咩」，未係一個真正嘅 Members 頁。

**前端（web/src/features/workspace/members-view.tsx，385 行）**
- Gate：`checkAccess(access, { permission: 'manage_members' })`（L239）交畀 `PageContainer access`（L263），fallback 只係一句「Only owners and admins manage members.」（L264）。Nav 入口 `web/src/config/nav-config.ts:102–108`（icon `teams`、shortcut `m m`、同一個 permission）。
- **access=false 時 hooks 照 fire**：`useMembers()` / `useInvitations()`（L240–241）冇 `enabled` 條件，非 staff 直接開 URL 會打一個 403 invitations request。
- 三個 block stack 埋一齊：`InviteForm`（L65–130，永遠展開嘅 Card）、Members table（L310–337）、Invitations table（L339–381）。
- **Error state 缺失**：兩個 section 只 check `isLoading`（L315、L343），query error 時 render 空表格 / 「No invitations yet.」——即係將 Unavailable 當成冇數據，違反真數據原則。
- **身份顯示係 `member.userId.slice(0, 8)…`（L175）**，冇名、冇 avatar。後端 `members()`（`src/postriff_phase2/hosted.py:711–715`）只 SELECT user_id/status/role/flags/updated_at，冇 join `pr_profiles.display_name`；亦冇 status filter（revoked row 都會回），前端 Status column（L324）照出。
- Role 可以改（L184–195），但 **extra grants 唯讀**（L169、L200）；`change()`（L138–146）將 row 原有 flags 連新 role 一齊 PATCH。後端 `update_member`（hosted.py:717–733）接受 flags，所以「之後改 grants」係純前端缺失。
- **隱藏 bug**：非 owner 嘅 admin 改一個持有佢自己冇嘅 flag 嘅 member 嘅 role，`validate_grant`（`src/postriff_phase2/permissions.py:92–95`）會 403「You cannot grant 'can_reply' because you do not hold it.」——因為前端照抄 row flags。`validate_grant` 本身有 unit test（`tests/test_postriff_phase2_hosted.py:193–201`），但冇經 update_member 嘅 end-to-end test。
- **Step-up 冇處理**：`invite` / `update_member` / `remove_member` 都 `assert_fresh`（hosted.py:756、721、738；`assert_fresh` hosted.py:117–122；`STEP_UP_WINDOW = 600` permissions.py:43）。`revoke_invitation`（hosted.py:787–794）**冇** step-up。頁面只喺 infobar 寫咗一段字（L54–57），失敗時 toast（L81、L150、L163）。`StepUpDialog` 係 `web/src/features/account/security-card.tsx:72` 私有 function（:813 只 export `SecurityCard`；用喺 :600、:610）。
- 後端「recent sign-in」量度嘅係 JWT `iat`（`src/postriff_phase2/hosted_identity.py:36–44`），見 risks。
- Revoke invitation（L246–254，button onClick 直接 call）**冇 confirm**，違反 motion 規則 5（docs/postriff-motion-system.md:108）。
- Invitations 列表混埋 pending / accepted / revoked / expired（`invitations()` hosted.py:777–785，最近 100 條）。**Declined 喺 DB 係 `revoked_at`**（`decline_my_invitation` hosted.py:872–885），所以 API 分唔到 declined 同 revoked。冇 tab、冇 Resend。Raw token 只喺建立時回一次（hosted.py:765 註解）。
- Invitations 空狀態係一句 `<p>`（L346），冇用 `web/src/components/ui/empty.tsx`。
- 建立邀請後嘅 Alert（L280–306）誠實區分 `emailSent`（`_send_invitation` hosted.py:771–775 要 `public_base_url` + mailer `src/postriff_phase2/email.py:172`），要保留。
- Hooks：`useMembers`（`web/src/lib/api/hooks.ts:64`）、`useInvitations`（:69）、`useAudit`（:74）、`keys.members/invitations/audit`（:17–19）。Client：`api.members`（`web/src/lib/api/client.ts:235`）、`updateMember`（:236）、`removeMember`（:238）、`invitations`（:240）、`invite`（:241）、`revokeInvitation`（:243）、`audit`（:245）；`ApiError` 只有 message/status（:47–54）。Types：`Member`（`web/src/lib/api/types.ts:614–619`）、`Invitation`（:621–631）、`InvitationCreated`（:633–639）、`AuditEvent`（:720）。

**後端 route 已存在（src/postriff_phase2/hosted_app.py）**
- `GET /api/workspaces/{id}/members` → `service.members`（:463–464）——**後端冇 require()，任何 active member 都讀到**
- `PATCH|DELETE /api/workspaces/{id}/members/{userId}` → `update_member` / `remove_member`（:439–443）
- `GET|POST /api/workspaces/{id}/invitations` → `invitations`（require manage_members，hosted.py:779）/ `invite`（:469–473；POST 回 201）
- `DELETE /api/workspaces/{id}/invitations/{invId}` → `revoke_invitation`（:444–446）
- `POST /api/invitations/accept` → `accept_invitation`（:370–372；hosted.py:796–811，throttle 10/60s by client；**唔核對登入 email**，link 任何人都用得，hosted.py:832–834 註解）
- `GET /api/me/invitations`、`POST /api/me/invitations/{id}/accept|decline`（:366–377；hosted.py:839–885）——email 配對，UI 喺 `web/src/features/account/profile-view.tsx:433+`
- `POST /api/workspaces/{id}/leave`（:474–476；hosted.py:557–566，owner 唔可以離開 :560–561）
- `GET /api/workspaces/{id}/audit`（:465–466；hosted.py:929–932，**冇 require()**；nav 用 `access: { role: 'admin' }` nav-config.ts:118–120）——事件：`member.updated`（hosted.py:732）、`member.removed`（:746）、`member.left`（:565）、`invitation.created`（:764）、`invitation.revoked`（:793）、`invitation.accepted`（:829）、`invitation.declined`（:883）
- 錯誤序列化：`{error: str}` + status（hosted_app.py:499–500），冇 machine-readable `code`

**後端缺嘅 / 要知嘅**
- Ownership transfer：`update_member` 寫明「Ownership transfer is a separate step-up action.」（hosted.py:730），冇 endpoint；owner 唔可以 leave。
- `remove_member` 只擋 owner（hosted.py:742–743），**冇擋移除自己**——「唔可以移除自己」只係前端 `editable`（members-view.tsx:170）。
- Admin 可以建立 / 移除其他 admin（permissions.py:96–97；hosted.py:742–743）。
- Resend、invitation preview 都冇。
- Seat：`pr_entitlements.members`（`src/postriff_phase2/billing.py:44–47`；`Entitlement.members` types.ts:494，經 `useUsage()` → `Usage` types.ts:540），`web/src/config/plans.ts:48、66` 都係 `members: 1`，但 `invite()` 只 check `MAX_PENDING_INVITATIONS = 25`（hosted.py:40、759）。
- `pr_memberships.invited_by`（migration 004:16）存在但 hosted.py 從未寫入。

**已有可以直接用嘅資產**
- `allows`（:22）/ `permissionsFor`（:28–30）/ `ROLE_LABELS`（:32）/ `ROLE_DESCRIPTIONS`（:40）喺 `web/src/lib/auth/permissions.ts`，鏡像 permissions.py CLASSES
- `memberTiers` / `isStaff` / `extraGrants`（`web/src/features/account/profile-model.ts:12、19、53`）
- `memberCounts`（types.ts:37；hosted.py:31–38 + `workspace_summary` :58–68）——但係 GET /api/workspaces 快照，本頁應該由 members query 計
- Roles 頁（`web/src/features/workspace/roles-view.tsx`，PERMISSIONS labels :12）已經解釋 matrix
- Motion / UI：`NavCount`（`web/src/components/layout/app-sidebar.tsx:102–115`，counts 只有 `/app/queue` :128–130，aria-label 寫死「waiting for approval」:177）、`SuccessCheck`（ui/success-check.tsx）、`useFlash`（hooks/use-flash.ts，default 1800ms）、`AnimatedBadge`（motion/animated-badge.tsx）、`StatefulButton`（motion/button/stateful.tsx）、`HoldActionButton`（motion/hold-action-button.tsx）、`NumberTicker`、`ActionSwapIcon`（motion/action-swap.tsx:251）、`Empty`、`ui/avatar`、`ui/spinner`、`ui/tabs`、`useIsMobile`（hooks/use-mobile.ts）、data-table（ui/table/）
- **Tour 基建已存在**：`web/src/features/onboarding/tours.ts`（page tips registry：home/channels/analytics/queue/calendar/overview…，selector array + `when(ctx)`）、`tour-overlay.tsx`、`help-menu.tsx`、`use-tour-context.ts`；全 app 已有 63 個 `data-tour`。未有 `members-tips`，`TourCtx`（tours.ts:14–24）冇 `canManageMembers`。
- Accept 頁 `web/src/app/invite/[token]/accept-invitation.tsx`：loading / unavailable / signed-out（`next=` L70）/ signed-in，但接受前唔知 workspace、role、邀請人（L50 通用文案）；成功寫 `localStorage['postriff-workspace']`（L31）再 `router.replace('/app')`（L35）
- Tests：`tests/phase2/postgres_account.py:67–164` cover invite → accept、leave、account history、my_invitations accept/decline；冇 cover update_member flags 403、remove self、resend、preview、transfer。
- UI i18n：web 冇翻譯層（只有 calendar 用 `@react-aria/i18n` 做日期），所有 copy 係英文字串。

## 1. Design specification（最新版）

**目的**：俾 owner / admin 一眼睇到「邊個可以喺呢個 workspace 做咩」，並且安全咁邀請、調整、移除人——每個數字讀真數據，破壞性動作有確認，敏感動作有清楚嘅 step-up。Roles matrix 留喺 /app/workspace/roles，Members 頁只做「人」。

**Layout**：沿用 `PageContainer`（`web/src/components/layout/page-container.tsx`）+ `web/src/app/app/template.tsx` 嘅 `.t-page-enter`。Workspace provider 未 ready 時用 `PageContainer isLoading`，唔好靠 `STUB_ACCESS`（lib/auth/access.tsx:37–43，預設 owner）閃出 staff UI。

**Header**：`pageTitle='Members'`、`pageDescription='Who can do what in this workspace.'`；`pageHeaderAction` 放 primary「Invite」（`data-tour='members-invite'`），開 `ui/dialog`（transition 06）。InviteForm 由永遠展開嘅 Card 搬入 dialog。

**主欄（由上至下）**：
1. Summary strip（`data-tour='members-summary'`）：3 個 tile——Active members（`members.data.members.filter(m => m.status==='active').length`）、Staff / Members（由**同一個 members query** 嘅 active rows 計 owner+admin vs 其餘，唔用 `useWorkspace().memberCounts`，避免 mutation 後兩個數唔一致）、Pending invitations（`state==='pending'` 數；副字「of {limit}」只喺 API 回 `limit` 時顯示，未回之前唔出上限）。Query loading → skeleton；error → 「Unavailable」，永遠唔變 0。
2. Members table（`data-tour='members-table'`）：只列 `status==='active'`。Columns = Person · Role · Extra grants · Joined · actions。Person cell = `ui/avatar` initials（displayName 第一個字，冇就 generic user icon）+ displayName（冇就「Unnamed member」）+ 細字「Invited as {invitedEmail}」（只有 API 回 invitedEmail 先出；明確係邀請地址唔係帳戶 email）+ `you` badge。Role cell：可編輯時 `ui/select`（transition 05）+ 20px slot 俾 `SuccessCheck`；owner 行、自己行純文字。Extra grants cell：`ui/badge` outline chips；可編輯時末尾「Edit」ghost button 開 `ui/popover`（`data-tour='members-grants'`），4 個 `ui/checkbox` + Save `StatefulButton`。非 owner actor 自己冇持有嘅 flag：disabled + `ui/tooltip`「You can only grant rights you hold yourself.」（permissions.py:92–95）；改 role 時亦只送 actor 持有嘅 flags，修正現有 403 bug。Joined cell：`joinedAt` 有就 relativeTime；冇（owner、舊資料）就顯示 `updatedAt` 並 label「Last changed」，唔扮係加入日期。Actions：`ui/dropdown-menu`「Change role…」「Edit grants…」「Remove from workspace…」（alert-dialog）。Owner 行：只有 owner 本人見到「Transfer ownership…」（P1）。
3. Invitations section（`data-tour='members-invitations'`）：`ui/tabs`「Pending (N)」「History」，N 由真數據計。Pending rows：email · role + grants chips · Invited by（`createdByName`，空就「A workspace admin」）· Sent（relativeTime createdAt）· Expires（剩 <24h 用 AnimatedBadge warning）· actions「Resend」「Revoke…」（alert-dialog）。History rows：state 用 `AnimatedBadge`（accepted=success、revoked/expired=neutral；declined 只喺 API 分得出先顯示，見 technical requirements），冇 actions。剛建立 / resend 嘅邀請：inline `ui/alert`（現有 L280–306 邏輯）帶 link + Copy link，文案講明「This link is shown once」。切換 workspace 時清走呢個 alert state。
4. Recent changes（P1）：5 行 list，讀 `useAudit()` 過濾 member.* / invitation.*，label map 喺前端；link「See the audit log ›」去 /app/workspace/audit。

**Info sidebar**（`infoContent`，`web/src/components/ui/infobar.tsx`）：4 段——「Roles set the baseline」（+ link `/app/workspace/roles`，`data-tour='members-roles-link'`）、「Extra grants add one right」、「Some changes ask you to confirm it is you」（inviting、changing roles、removing；revoking an invitation does not——文案同後端量度方式一致）、「Invitations」（7 天、一次性 link、pending 上限）。

**Responsive**：
- 375px：header action 保持 icon+label；summary strip 變 3 個橫向 scroll tile（`overflow-x-auto`，16px gutter，頁面冇橫向 scroll）；members table 轉 card list（avatar+name 一行、role + grants chips 第二行、overflow menu 右上），同一個 `MemberRow` 用 `useIsMobile()` 切 layout；invitations 同樣轉 card；dialogs 全寬、內容 scroll；grants popover 喺 mobile 改用 `ui/drawer`。
- 768px：table 顯示 Person · Role · Grants · actions，Joined 隱藏；infobar collapsed。
- 1440px：完整 table + infobar expanded；summary 三格等寬。

**Copy / 語言**：web UI 冇翻譯層，本頁所有字串集中喺 `web/src/features/workspace/members/copy.ts`（連 audit label map），日期用 locale-aware `relativeTime` / `formatDate`；將來 UI i18n 時一個檔搬。所有文案通用，冇行業 / 品牌例子。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header + Invite dialog | 一個清晰 primary action，邀請流程唔再霸住成頁。 | Email（required）、Role select（admin/editor/approver/viewer，default editor；非 owner 且非 admin 嘅 actor 冇 admin 選項，對應 permissions.py:96–97）、`ROLE_DESCRIPTIONS` 一句、Extra grants fieldset（viewer 時隱藏，同現有 L111–124）、**Permission preview**「They will be able to: …」由 `permissionsFor({role, ...flags})` 即時計，labels 用由 roles-view.tsx:12 抽出嘅共用 `PERMISSION_LABELS`。Email 已經係 active member（members query 冇 email，所以只可以對 pending invitations 嘅 email 做 reminder「An invitation to this address is already pending」）→ reminder，唔 block。Submit `StatefulButton`，success 只喺 API 201 之後。Step-up 403 → 開 StepUpDialog，通過後重試一次。 | idle / submitting / success（useFlash 1.8s 後關 dialog）/ error（dialog 內 inline `ui/alert` destructive，唔用 toast）/ step-up required（疊第二個 dialog）/ pending 已達上限（dialog 仍然開得，頂部 reminder 引用 API 409 文案「Revoke or wait for pending invitations before adding more.」，Send disabled，因為後端一定會拒） |
| Summary strip | 5 秒內知道有幾多人、幾多人管理、幾多人等緊加入。 | Active members（`NumberTicker`：首次 paint 直接顯示 API 值，只喺 refetch 值改變先滾）、Staff / Members（「2 staff · 3 members」，由 members query active rows 計）、Pending invitations（「1」；API 回 `limit` 先加「of 25」）。副標：「Owners and admins」/「Editors, approvers, viewers」/「Links expire after 7 days」。 | loading → `ui/skeleton`；error → 「Unavailable」文字；empty 唔存在（最少有 owner）。 |
| Members table | 每個人一行：身份、role、grants、加入時間、動作。 | 見 layout。Sort：owner → admin → editor → approver → viewer（後端 `ORDER BY m.role,m.user_id` 係字母序，前端用 ROLES 順序 re-sort），同 role 內按 displayName。只列 active。 | loading → 3 行 row skeleton；error → `Empty`「Members could not be loaded.」+ Retry（`refetch`）；row busy → select/menu disabled + `ui/spinner`；role / grants 改成功 → SuccessCheck（useFlash）；remove 成功 → row exit 150ms 再重排；mutation error → popover / dialog 內 inline alert。 |
| Invitations | 分開「等緊人接受」同「歷史」。 | Tabs Pending / History。Pending 空狀態 `Empty`：icon `mail`、「No one is waiting to join」、「Invite a teammate and they get a one-time link that works for 7 days.」、action「Invite」。History 空：「No invitations yet.」。Resend：API 撤舊建新 → 新 row 進場 + inline alert 帶新 link（step-up 同 invite 一樣）。Revoke：alert-dialog「Revoke this invitation? The link stops working immediately.」（revoke 唔使 step-up）。 | loading / error（`Empty`「Invitations could not be loaded.」+ Retry，唔係「No invitations yet.」）/ empty / populated；每行 resend busy / revoke busy；<24h → AnimatedBadge warning「Expires soon」；emailSent=false → 保留現有文案「Email delivery is not configured on this deployment, so share the link directly.」。 |
| Step-up dialog | 邀請、改 role / grants、移除、resend 係敏感動作；用 dialog 講清楚點解要再確認、點樣通過。 | 抽出 `StepUpDialog`（security-card.tsx:72 起）到 `web/src/components/auth/step-up-dialog.tsx`，SecurityCard 改 import。三個 mode：passkey（有 webauthn factor）、code（有 totp）、sign in again（冇 factor → button 去 sign-in `?next=/app/workspace/members`，文案「For your security, sign in again to continue. We bring you straight back.」——唔寫死「10 minutes」直到後端量度方式定案）。`useStepUp(action)`：403 + `code==='step_up_required'` → 開 dialog → 通過後重試一次；未有 code 之前唔好靠 message 字串 match。 | closed / open(passkey\|code\|signin) / verifying / retrying / error |
| Info sidebar | 解釋規則但唔重覆 Roles 頁。 | 4 段（見 layout），每段 ≤ 2 句，第一段 link Roles。通用例子：「a teammate who drafts」「someone who only approves」「a client who only reads」。 | static |
| Access fallback（非 staff） | Editor / approver / viewer 直接開 URL 時唔係冷冰冰拒絕，亦唔發多餘 request。 | `accessFallback` 換成 `Empty`：「Only owners and admins manage members」、「You are {ROLE_LABELS[membership.role]} in this workspace. Ask an owner or admin to change roles or invite people.」（role 讀 `useWorkspace().membership`）+ link「See what each role can do ›」去 /app/workspace/roles（Roles nav 本身亦係 manage_members，所以 link 去到會見同一個 fallback——改為 link 去 /app/account 嘅 workspace 摘要，或者唔出 link）。`useMembers` / `useInvitations` 加 `enabled: canManage`。Nav 已隱藏 entry（nav-config.ts:108）。 | static，role 讀真數據；provider loading 時 PageContainer isLoading |
| Recent changes（P1） | 改完嘢有跡可尋。 | `useAudit()` filter kind ∈ {member.updated, member.removed, member.left, invitation.created, invitation.accepted, invitation.declined, invitation.revoked, owner.transferred（P1 之後先有）}，最新 5 條；label map 喺 `members/copy.ts`；actor / subject 顯示 displayName（audit endpoint 要加 actorName + subjectName，subject 係 user id 或 invitation id）。 | loading skeleton / error「Recent changes are unavailable.」/ empty「No membership changes yet.」/ populated |

- **Empty state**：Members list 永遠有 owner。Invitations Pending tab 空：`Empty`（ui/empty.tsx）icon `mail` +「No one is waiting to join」+「Invite a teammate and they get a one-time link that works for 7 days.」+ button「Invite」開 dialog。History 空：「No invitations yet.」。教到：(1) 邀請喺 header；(2) link 一次性；(3) 7 日。Error 永遠唔會用呢個空狀態代替。
- **Loading**：Workspace provider loading → `PageContainer isLoading`（PageSkeleton）。之後每個 section 獨立 `ui/skeleton`：summary 3 tile、members 3 行、invitations 2 行。冇「Loading members…」文字、冇 progress bar。Dialog submit 用 StatefulButton loading，label 保持「Send invitation」+ spinner。
- **Error**：Query error → 該 section 換成 `Empty`（icon `alertCircle`）：「Members could not be loaded.」/「Invitations could not be loaded.」+ Retry（`refetch()`）；summary tile →「Unavailable」。修正現有 bug：error 唔可以 render 空表格或「No invitations yet.」。Mutation error → dialog / popover 內 inline `ui/alert` destructive，文案用 `ApiError.message`（例如「Ask another owner or admin to change your own role.」「The owner cannot be removed.」）；403 + code step_up_required → StepUpDialog；403 grant（「You cannot grant …」）應該因為前端預先 disable 而唔會出現，出現就 inline 顯示；409 pending 上限 → dialog 頂部 reminder；404「Member unavailable.」/「Invitation unavailable.」→ inline alert + invalidate query（有人喺另一個 tab 改咗）。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁 | route enter | fade + slide 入（transition 08） | web/src/app/app/template.tsx `.t-page-enter`（零改動） | 否（純裝飾） |
| Invite dialog / Step-up dialog / Remove·Revoke alert-dialog | open / close | modal scale + backdrop（transition 06），收快過開 | web/src/components/ui/dialog.tsx、alert-dialog.tsx | 否（純裝飾） |
| Invite / Save grants submit button | POST /invitations 或 PATCH /members 進行中 → 成功 / error | idle → loading → success tick（useFlash 1.8s）→ idle；error 回 idle + inline alert | web/src/components/motion/button/stateful.tsx `StatefulButton` + web/src/hooks/use-flash.ts | 是 |
| 新 pending invitation row | invitations refetch 後出現上次 data 冇嘅 invitationId | opacity 0→1 + translateY 6px→0，200ms，只對新增 id 播；reload 唔重播；prefers-reduced-motion 直接出現 | new（`motion` AnimatePresence + useReducedMotion，只郁 transform/opacity） | 是 |
| Invitation state badge | state 值改變 | icon roll + label swap；pending=info、accepted=success、revoked/expired=neutral | web/src/components/motion/animated-badge.tsx `AnimatedBadge` contentKey=state | 是 |
| Role select / grants chips 旁嘅 tick | PATCH /members/{id} 成功 | SuccessCheck 畫剔（transition 10），1.8s 後消失 | web/src/components/ui/success-check.tsx + useFlash | 是 |
| Member row 被移除 | DELETE /members/{id} 成功 + refetch | opacity→0 + translateY -4px 150ms 後移除；reduced motion 直接移除 | new（同新 invitation row 共用 AnimatePresence wrapper） | 是 |
| Summary tile 數字 | refetch 後值改變（首次 paint 唔滾） | 由舊值滾到 API 新值；「Unavailable」係文字唔滾 | web/src/components/motion/number-ticker.tsx `NumberTicker` | 是 |
| Copy link button | clipboard.writeText resolve | copy icon 滾成 check，1.8s 後滾返；reject 時唔變 check，顯示 inline「Copy failed, select the link manually」 | web/src/components/motion/action-swap.tsx `ActionSwapIcon` + useFlash | 是 |
| Pending / History tabs | 切 tab | indicator 滑動（transition 16） | web/src/components/ui/tabs.tsx | 否（純裝飾） |
| Grants popover / overflow menu / role select | open / close | 跟 trigger 方向放大（transition 05），收快過開 | web/src/components/ui/popover.tsx、dropdown-menu.tsx、select.tsx | 否（純裝飾） |
| Sidebar「Members」nav count（P1） | pending invitations count > 0（只對 manage_members 用戶 enable query） | badge 滑入彈出；0 時縮走 | web/src/components/layout/app-sidebar.tsx `NavCount`（counts map :128–130 加 '/app/workspace/members'；aria-label :177 改為按 url 揀文案，例如「N invitations pending」） | 是 |
| 「See the audit log ›」 | hover | 箭嘴滑動（transition 24） | web/src/components/ui/learn-more-chevron.tsx | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{id}/members 回 userId/status/role/flags/updatedAt/you | api | 有 | hosted_app.py:463–464 → hosted.py:711–715；client.ts:235；hooks.ts:64。注意：冇 require()，任何 member 可讀 | S |
| 2 | members() 加 displayName（LEFT JOIN pr_profiles，deleted_at IS NULL）、joinedAt（最新 pr_invitations.accepted_at WHERE accepted_by=user_id）、invitedEmail（同一條 invitation 嘅 email，**只喺 actor 有 manage_members 時回**）；加 status='active' filter 或者前端 filter | backend | 冇 | hosted.py:713 只 SELECT user_id,status,MEMBER_COLUMNS,updated_at；pr_profiles.display_name migrations/postriff/001_phase2.sql:6–8；pr_invitations.accepted_by/accepted_at 004_consumer_web_tenancy.sql:23–38；_join 寫 accepted_by hosted.py:828。唔可以逐行叫 email_for（hosted_identity.py:94–104 Supabase Admin API） | S |
| 3 | Member type 加 displayName: string、invitedEmail?: string \| null、joinedAt: number \| null | frontend | 冇 | types.ts:614–619 只有 userId/status/you/updatedAt | S |
| 4 | PATCH /members/{userId} 接受 role + 4 flags（可淨改 grants） | api | 有 | hosted_app.py:439–442 → hosted.py:717–733；validate_grant permissions.py:86–98 | S |
| 5 | 前端 grants popover + 修正 change() 只送 actor 持有嘅 flags；非 owner actor 冇持有嘅 flag disabled + tooltip | frontend | 冇 | members-view.tsx:169、200 唯讀；:138–146 照抄舊 flags；actor flags 由 useWorkspace().membership（web/src/lib/workspace/provider.tsx:131–133） | S |
| 6 | DELETE /members/{userId}（owner 受保護） | api | 有 | hosted_app.py:443 → hosted.py:735–747；owner 擋 :742–743 | S |
| 7 | remove_member 擋移除自己（指向 /leave） | backend | 冇 | hosted.py:735–747 冇 user_id == principal 檢查 | S |
| 8 | GET/POST /invitations、DELETE /invitations/{id} | api | 有 | hosted_app.py:469–473、444–446 → hosted.py:749–769、777–794；MAX_PENDING_INVITATIONS hosted.py:40；revoke 冇 step-up | S |
| 9 | invitations() 加 createdByName（LEFT JOIN pr_profiles ON created_by）+ 回 `limit`（MAX_PENDING_INVITATIONS）+ 分得出 declined（LEFT JOIN audit invitation.declined 或加 declined_at） | backend | 冇 | hosted.py:780–784 只回 createdBy uuid、state 冇 declined；decline 寫 revoked_at hosted.py:879；同類 join 已喺 my_invitations() hosted.py:849 | S |
| 10 | POST /api/workspaces/{id}/invitations/{invId}/resend：同一 transaction 撤舊建新（同 email/role/permissions）、回 InvitationCreated、audit invitation.resent；manage_members + step-up + pending 上限 | api | 冇 | hosted.py:765「The raw token is returned exactly once」；hosted_app.py route table 冇 resend | S |
| 11 | GET /api/invitations/preview?token=…：回 workspaceName、role、permissions、invitedBy.displayName、expiresAt（唔回 invitee email）；唔需要 sign-in，throttle 同 accept（hosted.py:799–802） | api | 冇 | accept-invitation.tsx:50 通用文案；hosted_app.py 冇 preview route | S |
| 12 | POST /api/workspaces/{id}/owner {userId}：owner-only + step-up；目標要係 active admin；新 owner role=owner 四 flag=true（004:18 慣例），舊 owner 降為 admin（flags 決定要寫明）；audit owner.transferred；確認 billing owner / subscription 關係 | api | 冇 | hosted.py:730；leave_workspace hosted.py:560–561；permissions.py CLASSES 有 owner class；冇 endpoint | M |
| 13 | Step-up 錯誤帶 machine-readable code（`{error, code: 'step_up_required'}`） | api | 冇 | hosted.py:122 raise AlphaError(message, 403)；hosted_app.py:499–500 只序列化 {error}；client.ts:47–54 ApiError 冇 code | S |
| 14 | 研究 step-up freshness 改用 sign-in / MFA 時間（例如 JWT amr timestamps）而唔係 iat；先用真 Supabase token 驗證，唔好打爛現有 passkey/TOTP step-up | backend | 冇 | hosted_identity.py:36–44 讀 iat；repo 冇 amr 處理，屬未驗證假設 | M |
| 15 | 共用 StepUpDialog（passkey / code / sign-in-again）+ useStepUp() 重試 helper | frontend | 冇 | security-card.tsx:72 私有（:813 只 export SecurityCard，用喺 :600、:610）；verifyTotp/verifyPasskey/listFactors 喺 web/src/lib/auth/mfa.ts:38–100；next= 慣例 accept-invitation.tsx:70 | M |
| 16 | Revoke 經 alert-dialog 確認（Remove 已有） | frontend | 冇 | Remove members-view.tsx:211–229 有；Revoke :246–254 直接 call | S |
| 17 | Query error state（Members / Invitations）+ hooks enabled: canManage | frontend | 冇 | members-view.tsx:315、343 只 check isLoading；:240–241 無條件 fire | S |
| 18 | Invitations Pending / History tabs + Empty | frontend | 冇 | members-view.tsx:339–381 單一表格；:346 純 <p>；ui/empty.tsx、ui/tabs.tsx 已有 | S |
| 19 | Permission preview（permissionsFor + 共用 PERMISSION_LABELS） | frontend | 冇 | permissionsFor web/src/lib/auth/permissions.ts:28–30；labels 寫死 roles-view.tsx:12 | S |
| 20 | Summary strip 數據：active members、staff/members split、pending 數 | data | 有 | 全部可由 members query（hosted.py:711–715）同 invitations query（:777–785）計；memberTiers 邏輯 profile-model.ts:12–16 可重用（傳入由 members 計嘅 counts） | S |
| 21 | Audit 事件 member.* / invitation.* | api | 有 | GET /audit hosted_app.py:465–466 → hosted.py:929–932；冇 actorName / subjectName（加 LEFT JOIN pr_profiles 係 S，同 hosted.py:638 connected-by 做法一樣）；endpoint 冇 require() | S |
| 22 | Seat entitlement 數值 | data | 有 | billing.py:44–47；types.ts:494 Entitlement.members 經 useUsage()（types.ts:540）；invite() hosted.py:749–769 唔 enforce，所以未可以顯示「N of M seats」 | M |
| 23 | Accept 頁顯示 preview + 「Signed in as {email}」對照 | frontend | 冇 | accept-invitation.tsx:47–93；auth.user 由 web/src/lib/auth/session.tsx | S |
| 24 | Members page tips：喺 tours.ts 登記 members-tips + 加 data-tour 錨點 + TourCtx.canManageMembers | frontend | 冇 | tour 基建已存在：web/src/features/onboarding/tours.ts（page tips :158–320）、tour-overlay.tsx、help-menu.tsx；TourCtx tours.ts:14–24 冇 canManageMembers；members-view.tsx 冇 data-tour | S |
| 25 | Sidebar Members NavCount（P1） | frontend | 冇 | NavCount app-sidebar.tsx:102–115；counts 只有 /app/queue（:128–130）；aria-label 寫死 approval 文案（:177） | S |
| 26 | Tests：members() displayName/joinedAt/invitedEmail 可見度、update_member flags 403 end-to-end、remove self、resend、preview、transfer、step-up code、declined state | backend | 冇 | tests/phase2/postgres_account.py:67–164 只 cover invite→accept、leave、history、my_invitations；validate_grant unit test tests/test_postriff_phase2_hosted.py:193–201 | M |

## 3. Features

### P0

- **真身份：名、avatar initials、加入時間、「Invited as」**：8 個字 uuid 冇人認得，冇辦法決定移除邊個。displayName 已喺 pr_profiles；邀請地址只標示為「Invited as」，因為 token link 任何人都可以接受，唔可以當成佢帳戶 email；owner 或冇邀請紀錄就唔出嗰行。Email 只俾 manage_members 睇。（depends on：members() join（hosted.py:713）+ Member type）
- **Error / access 狀態修正**：現有頁面 error 時顯示空表格，等於將 Unavailable 當 0；非 staff 開頁仍然打 403 request。呢個係真數據原則嘅 bug，唔係 polish。
- **Invite dialog + permission preview**：5 roles × 4 flags 容易錯 grant；preview 由 permissionsFor 計，同後端 CLASSES 鏡像。非 owner 自己冇嘅 flag 預先 disable，避開 permissions.py:92–95 嘅 403。（depends on：共用 PERMISSION_LABELS）
- **Step-up 用 dialog 處理**：而家撞 403 只有 toast。抽出現有 StepUpDialog，加 sign-in-again mode 俾冇 2FA 嘅人；通過後自動重試。文案唔寫死分鐘數，直到後端量度方式定案。（depends on：API error code + 共用 StepUpDialog）
- **之後可以改 grants；Revoke 要確認；每行 overflow menu；修正 role 改動 403**：後端 PATCH 已支援 flags；Revoke 冇確認違反 motion 規則 5；change() 照抄 flags 係現存 bug。
- **Invitations Pending / History，Resend，Empty**：Pending 先係要處理嘅清單；token 只回一次，冇 Resend 即係 link 唔見咗要 revoke 再 invite。Resend = 撤舊建新。（depends on：POST /invitations/{id}/resend）

### P1

- **Members page tips（help menu）**：tour 基建已存在，登記 members-tips 成本低；copy 通用、每句講嘅狀態都讀真數據。（depends on：data-tour 錨點 + TourCtx.canManageMembers）
- **Accept 頁 preview + signed-in-as 對照**：受邀人接受前應該知道加入邊個 workspace、咩 role、邊個邀請；登入 email 同邀請地址唔同要明講（remind，唔 block——後端容許）。（depends on：GET /api/invitations/preview）
- **Transfer ownership**：後端寫明係 separate step-up action 但冇做；owner 想離開而家係死路。（depends on：POST /workspaces/{id}/owner）
- **Recent changes strip + sidebar pending count**：改完 role 或者有人接受邀請都有跡可尋；NavCount 已喺 Queue 用緊。（depends on：audit actorName/subjectName；NavCount aria-label 按 url）

### P2

- **Seat count「N of M」**：數據真但 invite() 未 enforce，顯示會誤導（plans 寫 1 seat 但可以邀請 25 人）。等 billing 決定 seat 模型。（depends on：invite() enforce entitlement.members + billing 決定）
- **Members table 搜尋 / 排序（data-table）**：workspace 通常人少；人多先值得上 data-table toolbar。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明：「呢頁係邊個可以喺呢個 workspace 做咩；role 定底線，extra grants 加一項權利；邀請人撳右上角 Invite。」靠三樣嘢教：(1) summary strip 第一眼「N active members · N staff / N members · N pending」，全部讀真數據；(2) table 第一行係 owner，role 同 grants 並排，model 唔使解釋；(3) header 只有一個 primary action「Invite」。Info sidebar 第一段 link Roles 頁。Help menu 開 members-tips（tours.ts 登記，`when: ctx.canManageMembers`）。所有文案通用，冇行業例子。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="members-summary"]（新加；fallback 'main h1'）` | Who is here | Active members, how many of them are owners or admins, and how many invitations are still waiting. Every number comes from this workspace right now. |
| 2 | `[data-tour="members-invite"]（新加）` | Invite someone | Enter an email, pick a role and any extra rights. You see what they will be able to do before you send. They get a one-time link that works for 7 days. |
| 3 | `[data-tour="members-table"]（新加）` | Roles set the baseline | Owner, admin, editor, approver, viewer. Change a role from the row. Your own role and the owner's are changed another way. |
| 4 | `[data-tour="members-grants"]（新加；只喺有可編輯 row 時存在，否則 step 用 when 跳過）` | Extra rights add one thing | Approve publications, reply, moderate, or manage connections. Give only what someone needs; you can only give rights you hold yourself. |
| 5 | `[data-tour="members-invitations"]（新加）` | Pending and history | Pending invitations can be resent or revoked. Accepted, revoked and expired ones stay in History. |
| 6 | `[data-tour="members-roles-link"]（新加；fallback a[href="/app/workspace/roles"]）` | The full matrix | The Roles page lists every permission per role. Inviting, changing and removing people may ask you to confirm it is you. |

**Empty state 教咩**：Members 永遠有 owner，空狀態只喺 Invitations Pending tab：icon `mail`、「No one is waiting to join」、「Invite a teammate and they get a one-time link that works for 7 days.」、button「Invite」——教邀請喺邊、link 一次性、7 日。非 staff 嘅 access fallback 用 `Empty` 講「You are {role}; only owners and admins manage members」。Error 時唔用空狀態。

## 5. Next steps（按次序）

1. **後端：members() join pr_profiles.display_name + pr_invitations（accepted_by）攞 joinedAt / invitedEmail（invitedEmail 只俾 manage_members）；remove_member 擋自己；invitations() 加 createdByName、limit、declined 分辨；audit_events() 加 actorName/subjectName；AlphaError 加可選 code，assert_fresh raise code='step_up_required'，hosted_app.py:500 序列化 {error, code}。加 tests。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:117–122、711–747、777–794、872–885、929–932；src/postriff_phase2/hosted_app.py:499–500；AlphaError 定義（postriff_alpha）；tests/phase2/postgres_account.py`
2. **Types + client：Member 加 displayName/invitedEmail/joinedAt；Invitation 加 createdByName、state 加 'declined'；列表 response 加 limit；AuditEvent 加 actorName/subjectName；ApiError 加 code?: string（parse body.code）。**（effort S）  
   檔案：`web/src/lib/api/types.ts:614–639、720；web/src/lib/api/client.ts:47–54、235–245`
3. **即刻修現存 bug（唔等重建）：Members / Invitations query error state、hooks enabled: canManage、change() 只送 actor 持有嘅 flags、Revoke alert-dialog。**（effort S）  
   檔案：`web/src/features/workspace/members-view.tsx:138–146、240–254、315–381；web/src/lib/api/hooks.ts:64–72`
4. **抽出 StepUpDialog 到共用位置，加 signin mode；新增 useStepUp()（403 + code step_up_required → dialog → 重試一次）；SecurityCard 改用共用版。**（effort M）  
   檔案：`web/src/components/auth/step-up-dialog.tsx（新）；web/src/hooks/use-step-up.ts（新）；web/src/features/account/security-card.tsx:60–160、600–620；web/src/lib/auth/mfa.ts（只 import）`
5. **共用 PERMISSION_LABELS：由 roles-view.tsx:12 搬去 lib/auth/permissions.ts，roles-view 改 import。**（effort S）  
   檔案：`web/src/lib/auth/permissions.ts；web/src/features/workspace/roles-view.tsx:12–21`
6. **重建 Members 頁（拆檔）：members-view、invite-dialog（form + preview + StatefulButton + created alert）、member-row（identity、role select + SuccessCheck、grants chips、overflow menu、mobile card）、grants-popover（mobile 用 drawer）、invitations-section（tabs、resend/revoke、Empty、error）、summary、model.ts（ROLE_ORDER re-sort、grantable flags）、copy.ts（全部字串 + audit label map）。加 data-tour 錨點；accessFallback 用 Empty + 真 role；workspace 切換時清 created alert。**（effort L）  
   檔案：`web/src/features/workspace/members/{members-view,invite-dialog,member-row,grants-popover,invitations-section,summary}.tsx、members/{model,copy}.ts；web/src/app/app/workspace/members/page.tsx（改 import）；刪 web/src/features/workspace/members-view.tsx`
7. **登記 members-tips：tours.ts 加 Tour（route '/app/workspace/members'，selector + fallback），TourCtx 加 canManageMembers（use-tour-context.ts）。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts；web/src/features/onboarding/use-tour-context.ts`
8. **後端 resend + preview endpoints + tests；client resendInvitation / previewInvitation；Pending row Resend 接上；accept-invitation.tsx 加 preview 同「Signed in as {email}」reminder。**（effort M）  
   檔案：`src/postriff_phase2/hosted_app.py（route table 加兩條）；src/postriff_phase2/hosted.py（invite() 附近）；web/src/lib/api/client.ts；web/src/app/invite/[token]/accept-invitation.tsx；tests/phase2/postgres_account.py`
9. **研究並驗證 step-up freshness 量度（iat vs sign-in / MFA 時間）；定案後先更新 StepUpDialog / info sidebar 文案。**（effort M）  
   檔案：`src/postriff_phase2/hosted_identity.py:36–44；tests/test_postriff_phase2_hosted.py`
10. **Transfer ownership：POST /workspaces/{id}/owner（owner + step-up + audit owner.transferred）；owner 行 overflow「Transfer ownership…」→ alert-dialog（揀 active admin）→ step-up；成功後 invalidate members + workspaces。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py；src/postriff_phase2/hosted_app.py；web/src/lib/api/client.ts；web/src/features/workspace/members/member-row.tsx；tests/phase2/postgres_account.py`
11. **Recent changes strip + sidebar Members NavCount（counts map 加 url、aria-label 按 url 揀文案、query 只對 manage_members enable）。**（effort S）  
   檔案：`web/src/features/workspace/members/recent-changes.tsx（新）；web/src/components/layout/app-sidebar.tsx:102–130、177`
12. **Browser 驗證：1440 / 768 / 375、light / dark、reduced motion、非 staff 直接開 URL、query error（停 API）；用 dev harness（:3100）試 invite → copy link → accept（另一個 email）→ 改 role → 改 grants → remove → revoke，全程唔撳 approve / schedule / send。**（effort S）  
   檔案：`docs/postriff-motion-system.md §6（補記錄）`
13. **（P2，等 billing 決定）invite() enforce entitlement.members；summary 加「N of M seats」。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:749–769；src/postriff_phase2/billing.py；web/src/features/workspace/members/summary.tsx`

## Risks

- Step-up 量度 JWT iat（hosted_identity.py:36–44）：token refresh 都會有新 iat，所以「recent sign-in」實際較似「recent token」。前端千祈唔好用 refreshSession() 靜靜滿足 window。改用 amr 或其他 sign-in 時間屬未驗證假設，要用真 Supabase token 驗證，而且唔可以打爛現有 passkey/TOTP step-up（佢而家靠新 iat 通過）。
- Privacy：GET /members 同 GET /audit 後端冇 require()（hosted.py:711、929），任何 member 都讀到。加 displayName 同 Overview（hosted.py:36）/ connected-by（hosted.py:638）一致；但 invitedEmail 係新暴露，一定只回俾 manage_members。永遠唔逐行叫 Supabase Admin email_for。migration 004:21「profiles stay self-only」係講 browser RLS，service path 顯示名係產品決定，要記錄。
- 「Invited as」唔等於帳戶 email：accept_invitation 唔核對登入 email（hosted.py:832–834），所以 UI 唔可以寫成「Email」。
- 唔好加「Last active」：pr_sessions（migration 004:66–73）係 per-account 跨 workspace，會洩露其他 workspace 活動。
- Resend 必須同一 transaction 撤舊建新，否則同一 email 有兩條有效 link；新 token 同樣只回一次。
- Declined 而家存做 revoked_at（hosted.py:879）；未改 API 前 History 唔可以顯示 declined，只顯示 revoked。
- Admin 可以建立 / 移除其他 admin（permissions.py:96–97；hosted.py:742–743），Remove dialog 照實講「They lose access immediately.」；remove_member 冇擋移除自己，前端隱藏唔等於後端安全。
- Email 寄送要 public_base_url + mailer（hosted.py:772；email.py:172）；dev harness 多數 emailSent=false，copy-link 係主路徑，要顯眼。
- Seat（entitlement.members = 1）同實際行為（可邀請 25 人）矛盾，未 enforce 前顯示會違反真數據原則——所以 P2。
- Tour：用現有 features/onboarding registry，唔好起第二套；copy 通用、唔好承諾 UI 做唔到嘅嘢（例如 grants step 喺冇可編輯 row 時要跳過）。
- STUB_ACCESS（lib/auth/access.tsx:37–43）預設 owner 全權限；provider 未 ready 時要 loading，否則非 staff 會閃見 staff UI。
- 另一個 session 正喺 web/src 工作（shared tree）：實作時 stage by path，唔好 whole-tree commit；拆檔刪 members-view.tsx 前確認冇人改緊。
- 後端 members() ORDER BY role 係字母序（admin, approver, editor, owner, viewer），前端一定要用 ROLES 順序 re-sort。
- MAX_PENDING_INVITATIONS / INVITATION_TTL 係後端常數（hosted.py:39–40）；由 API 回 limit 代替前端寫死，避免兩邊漂移。
- UI 冇 i18n 層：字串集中喺 copy.ts，日期用 locale-aware formatter；worldwide-languages 計劃係 post 語言，唔涵蓋 app UI。

## 覆核記錄

- 改正：全 web/src 冇任何 data-tour attribute，tour 基建未存在；tour component 屬另一個 workstream → 刪走「tour 基建」technical requirement；改為喺 tours.ts 登記 `members-tips`（route '/app/workspace/members'、target selector array、stop），TourCtx 加 `canManageMembers`。
- 改正：members-view.tsx 386 行 → 385 行
- 改正：invite / update_member / remove_member 都 assert_fresh（hosted.py:755、721、738） → 756；補充 revoke 唔使 step-up。
- 改正：History tab 會有 declined state（AnimatedBadge declined=neutral） → 要 API 分得出 declined（例如 LEFT JOIN audit invitation.declined 或加 declined_at 欄）先顯示 declined；未做之前只顯示 revoked，唔可以扮有 declined。
- 改正：Raw token 只回一次（hosted.py:768 註解） → hosted.py:765
- 改正：client.ts api.members :232、updateMember :233、removeMember :235、invitations :237、invite :238、revokeInvitation :240 → 更新行號
- 改正：Types Member 610–615、Invitation 617–627、InvitationCreated 629–635 → 更新行號
- 改正：hosted_app.py route 行號：members GET 458–459、PATCH/DELETE 434–438、invitations 464–468、revoke 439–441、leave 469–471、audit 460–461 → 更新行號（route 本身全部存在）
- 改正：audit 事件行號：member.updated 730、member.removed 745、member.left 565、invitation.created 765、revoked 793、accepted 831、declined 881 → 更新行號
- 改正：update_member「Ownership transfer is a separate step-up action.」喺 hosted.py:727；leave owner 擋喺 :561 → 730
- 改正：DELETE /members/{userId}：owner 受保護、自己唔可以 → 寫明後端冇擋自己；admin 自己離開應該行 /leave。可加一行 backend guard（S）。
- 改正：GET members 係 staff-only → 加 displayName/email 之前要決定：email（invitation address）只回俾 manage_members，或者 members() 加 require。
- 改正：Seat：billing.py:44–47、plans.ts:48、66 members: 1、Entitlement.members types.ts:490、Usage types.ts:537；invite 只 check MAX_PENDING_INVITATIONS（hosted.py:40、759） → 更新 types 行號
- 改正：ROLE_LABELS / ROLE_DESCRIPTIONS / permissionsFor / allows 喺 lib/auth/permissions.ts；permissionsFor :30–32 → permissionsFor :28–30
- 改正：memberCounts 喺 types.ts:37；WORKSPACE_SUMMARY_COLUMNS hosted.py:35–37 → hosted.py:31–38、58–68
- 改正：tests/phase2/postgres_account.py:67–153 cover invite→accept、leave、history、my_invitations；冇 test cover admin flags 403 → 67–164；註明 validate_grant unit test 已有
- 改正：members() email 可以用 pr_invitations（accepted_by）已存嘅一份代表該 member 嘅 email → 只可以標示為「Invited as {email}」，唔可以當成佢嘅帳戶 email；而且只回俾 manage_members。
- 違反原則（已改）：Reuse before inventing（motion/infra 規則）：spec 話 tour 基建唔存在、要另起 workstream，但 web/src/features/onboarding/tours.ts 已經有 page-tips registry + tour-overlay；應該登記 members-tips，唔係等新系統。
- 違反原則（已改）：真數據（規則 1）：History tab 顯示 'declined' badge，但 API 將 declined 存成 revoked_at（hosted.py:872–885），UI 無從得知——會捏造 state。
- 違反原則（已改）：真數據（規則 1）：將 pr_invitations.email 顯示為 member 嘅 email 係誤導；token link 任何人都可以接受，只可以寫「Invited as …」。
- 違反原則（已改）：真數據（規則 1）：現有頁面 members.isError / invitations.isError 冇處理，error 時 render 空表格（members-view.tsx:315–336、345–346 只 check isLoading），等於將 Unavailable 變成「No invitations yet.」。spec 冇指出呢個現存違規。
- 違反原則（已改）：真數據（規則 1）：NumberTicker 首次載入由 0 滾上去會短暫顯示假數字 0；首次 paint 應直接顯示 API 值，只喺 refetch 值改變先滾。
- 違反原則（已改）：真數據（規則 1）：Staff/Members split 用 useWorkspace().memberCounts（GET /api/workspaces 快照）而 table 用 members query，mutation 後兩個數會唔一致；應該由同一個 members query 計。
- 違反原則（已改）：Capability honesty 類比：spec 話 step-up 文案要同後端一致，但同時提議 amr 改動當成已知事實（repo 無證據），要標為待驗證。
- 違反原則（已改）：NavCount 重用：現有 aria-label 寫死「waiting for approval」（app-sidebar.tsx:177），直接加 Members count 會讀錯；spec 冇處理。
- 補上遺漏：RBAC 真相：GET /members 同 GET /audit 後端冇 require（hosted.py:711、929），只係前端 gate；加 displayName / invited email 會令 editor/viewer 都讀到隊友 email。要喺 backend 決定欄位可見度。
- 補上遺漏：MembersView 喺 access=false 時仍然 call useMembers/useInvitations（members-view.tsx:240–241 無條件），非 staff 會打一個 403 invitations request；hooks 要 enabled: canManage。
- 補上遺漏：remove_member 後端冇擋「移除自己」；要 backend guard 或者明確指向 /leave。
- 補上遺漏：Revoke 冇 step-up（hosted.py:787–794），info sidebar / tour 文案唔可以話「所有改動都要 fresh sign-in」。
- 補上遺漏：STUB_ACCESS（lib/auth/access.tsx:37–43）預設係 owner 全權限；provider 未 ready 時唔可以閃出 staff UI——要喺 workspace status loading 時用 PageContainer isLoading。
- 補上遺漏：TourCtx（tours.ts:14–24）冇 canManageMembers；members-tips 要加 `when` 條件。
- 補上遺漏：i18n / 語言：web UI 冇翻譯層，全英文。spec 要講明：copy 集中喺 features/workspace/members/copy.ts（或 model.ts），relativeTime/formatDate 用 locale-aware formatter，唔好喺 JSX 散落字串；worldwide-languages 工作係 post languages，唔涵蓋 UI。
- 補上遺漏：Workspace switch：切換 workspace 時 query key 已按 workspaceId 分，但「剛建立邀請」alert state（created）要 reset，否則會喺另一個 workspace 顯示上一個 token link。
- 補上遺漏：Pending 邀請 email 同現有 member 相同時（已經係 member）accept 會 409（hosted.py:823–824）；invite 時冇預先檢查，可以喺 dialog 做 reminder（唔 block）。
- 補上遺漏：Ownership transfer：pr_memberships 有冇 unique owner constraint、舊 owner 降級後 flags 點處理、billing owner 係咪跟住轉，spec 冇講。
- 補上遺漏：members() 回埋 status='revoked' 嘅 row（冇 status filter），而 memberCounts 只計 active；spec 要統一只計 active。
