# 24 · Auth：sign-in、sign-up、invite accept、MFA

> Route：`/auth/*, /invite/[token]` · Sidebar：Auth（唔喺 app sidebar / nav-config） · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

三條 flow（email code / Google / passkey 登入、MFA 第二步、invite 接受）行得通，但有幾個誠實同完整度問題。

**Git 狀態先講：** `web/src/components/auth/mfa-challenge.tsx`、`web/src/lib/auth/mfa.ts`、`web/src/lib/auth/passkeys.ts` 係 untracked，`web/src/lib/auth/session.tsx`、`web/src/components/auth/auth-form.tsx`（+17 行 passkey）、`web/src/components/layout/app-gate.tsx`、`src/postriff_phase2/hosted.py`、`src/postriff_phase2/hosted_app.py` 都有未 commit 修改——成個 MFA / passkey stack 係另一個 session（account security / 2FA）嘅 WIP。最後一個 commit 係 `b678aad`。

**Sign-in / sign-up。** `web/src/app/auth/sign-in/page.tsx:11-17`、`sign-up/page.tsx:11-17` 只包 `<AuthForm intent=…>`（Suspense fallback `null`）。`web/src/app/auth/layout.tsx:4-16` 係 `AuthProvider` + Wordmark + 置中 `max-w-sm`，冇 template、冇 `.t-page-enter`。`web/src/components/auth/auth-form.tsx`（321 行）：Google OAuth 65-73、passkey sign-in 75-82（`passkeySignInEnabled()` + `passkeysSupported()`，`lib/auth/passkeys.ts:20-22`、`lib/auth/mfa.ts:34-36`）、email OTP `sendCode` 84-93 → `verifyCode` 95-105。問題：(1) 89 行兩個 intent 都 `shouldCreateUser: true`——sign-in 頁打錯 email 會喺 Supabase 開一個未確認 user 並寄 sign-up email 畀陌生人；如果返嚟嘅人用咗另一個自己擁有嘅 email，驗證後 `web/src/lib/workspace/provider.tsx:84-89` 會 bootstrap 第二個 trial workspace（`hosted.py:509-538`，welcome email 535-537）。Typo 本身唔會開 workspace，因為收唔到 code。Google 路徑（68-71）無論 intent 都可以開新 user。(2) Code 步 `InputOTP maxLength={8}` 8 格、門檻 ≥6（264-273）；MFA 頁 6 格（`mfa-challenge.tsx:96-102`）。Email OTP 長度係 Supabase project 設定（6-10），repo 冇 config 讀得到；8 格 × 32px（`ui/input-otp.tsx:57` `size-8`）= 256px，375px 唔會爆。`input-otp` 已預設 numeric + one-time-code autocomplete。(3) 冇 resend、冇 cooldown；error 直接吐 Supabase 原句（59）。Plan chooser 133-161 讀 `web/src/config/plans.ts:33-55`，價錢 inline `${priced.priceCents / 100}`（152）而唔係 `formatPrice`（plans.ts:84）。Sign-up 經 invite link（`next=/invite/…`）都照樣顯示 trial plan chooser。`web/src/app/auth/callback/route.ts:9-19` PKCE exchange，失敗只帶 `?error=callback`，唔 forward `error_description`。`safeNext` 喺 `auth-form.tsx:26-28` 同 `callback/route.ts:4-6` 各 copy 一份。`web/src/proxy.ts:19-34` gate `/app/*`。

**Session。** `session.tsx` boot 136-210 先 `GET /api/catalog`（`hosted_app.py:283-285`）；`statusFor` 108-110 用 `assurance()`（`mfa.ts:26-31`）；`signOut` 212-225 → `POST /api/auth/logout`（`hosted_app.py:347-349` → `hosted.py:1005-1015`）。API 401「This session expired or was revoked. Sign in again.」（`hosted_app.py:66`）冇全局 handler（`lib/api/client.ts:60-73` 只 throw；80 行係「冇 token」401）。被「Sign out others」嘅機：refresh token 已被撤（`hosted.py:912-929` `logout_others`），access token 到期後 `onAuthStateChange`（session.tsx:188-200）→ AppGate redirect（app-gate.tsx:78-82）；喺到期之前每個 query 各自紅字，冇原因提示。API error body 只有 `{error}`（`hosted_app.py:499-500`），冇 machine code。

**MFA。** `mfa-challenge.tsx`（138 行，自帶 `min-h-svh` 全屏殼 64 行）由 `app-gate.tsx:87` inline render，冇自己 route。Passkey 優先 / TOTP 後備 42-44，sign out 132-134，verified factors 27-40。`disable_mfa` 要 fresh AAL2（`hosted.py:698-708`），冇 recovery code、冇 admin 解除。Verifier `hosted_app.py:57-71`：enforced + 非 AAL2 → 403「Two-factor verification required.」；`GET /api/me`（358-359 → `hosted.py:570-590`）帶 `mfa.{available,enforced,enforcedAt,aal}`。

**Invite。** `web/src/app/invite/[token]/page.tsx:11-27` 自己 copy 咗一個 AuthProvider + Wordmark 殼（`max-w-md`），唔係 auth layout。`accept-invitation.tsx`（94 行）：signed-out 兩條 link 帶 `next=`（67-80）；signed-in → `POST /api/invitations/accept`（`client.ts:114-115` → `hosted_app.py:370-372` → `hosted.py:796-812`，throttle 10/60 per IP）；成功寫 `localStorage['postriff-workspace']` 再 `router.replace('/app')`（28-35）。**冇 `mfa-required` 分支**：開咗 2FA 嘅人見到一張冇按鈕嘅 card。標題通用（50），冇 workspace 名 / inviter / role / 過期日，因為冇 preview endpoint。69 行「with the invited email first」係 API 冇執行嘅限制（token accept 唔 check email；`hosted.py` my_invitations 區塊註解明言 link works for anyone holding it）。邀請 email `src/postriff_phase2/email.py:92-97`（inviter label 其實係 inviter 嘅 email，`hosted.py:774`）；link 由 `hosted.py:771-775` 砌，冇 `public_base_url` → `emailSent: false`（`types.ts:638`）。TTL 7 日、25 pending（`hosted.py:39-40`）。

**Backend 已有：** `POST /api/auth/verify`（`hosted_app.py:341-346` → bootstrap，throttle 30/60 IP、60/60 user，`hosted.py:514-519`）、`GET /api/auth/sessions`（350-351）、`DELETE /api/auth/sessions/{id}`（432-434）、`POST …/revoke-others`（352-354）、`POST|DELETE /api/auth/mfa`（355-357）、`GET /api/me/invitations`（366-367）+ accept/decline（374-377 → `hosted.py:839-884`）、`GET /api/auth/config`（300-302）。Tests `tests/test_postriff_phase2_hosted.py:221-254`。

**IA / onboarding：** `docs/postriff-consumer-saas-redesign.md:232` 列 `/auth/verify`（喺「template 有，換 Clerk → Supabase」底下，原意未確認係 MFA；同 `POST /api/auth/verify` 撞名），421 行 `[ ] /invite/[token] UI` 未 tick。TourMount 只喺 `web/src/app/app/template.tsx:15`；`web/src/features/onboarding/tours.ts:14-24` `TourCtx` 冇 security 欄位。i18n：冇 library，`web/src/app/layout.tsx:55` `lang='en'`。RBAC：`web/src/lib/auth/access.tsx` 仍係 Phase A stub，auth 頁唔經 access。

## 1. Design specification（最新版）

**目的**：Auth 係四個入口：sign-in（返嚟）、sign-up（開 trial）、/auth/verify（2FA 第二步）、/invite/[token]（被人請入）。每個入口只做一件事，每句話都對得住 API 真行為：email code sign-in 唔會暗中開 account、Google 路徑講明可能開新 account、invite 頁講得出邊個請你入邊度做咩、2FA 有自己 URL、被 revoke 嘅 session 會被送返嚟並講原因。

**Layout**：抽一個共用 `AuthShell`（`web/src/components/auth/auth-shell.tsx`）畀 `web/src/app/auth/layout.tsx` 同 `web/src/app/invite/[token]/page.tsx` 用，取代 invite 頁自己 copy 嘅殼。頂部 56px Wordmark bar（`max-w-6xl`，`px-4 sm:px-6`），主體垂直置中；新增 `web/src/app/auth/template.tsx` 放 `.t-page-enter`（layout 唔會 remount）。
- **375px**：單欄，16px gutter，form `w-full max-w-sm`；OTP 格數跟 deployment 設定（8 × 32px = 256px 都放得落）。Context panel 併入 form 流程（sign-up plan chooser 喺方法列上面；invite preview card 喺按鈕上面）。
- **768px**：單欄置中 `max-w-sm`（invite `max-w-md`），`py-10`。
- **1440px（`lg:` ≥1024）**：只有 sign-up（非 invite 流程）同 invite 用 `grid-cols-[minmax(0,420px)_minmax(0,360px)] gap-16`：sign-up 右欄 plan card，invite 右欄 preview card。Sign-in 同 /auth/verify 維持單欄。
- **Header** 只有 Wordmark（link `/`）；intent 切換留喺 form 底（現有 302-318）。
- **Primary action** 每頁一個：sign-in = passkey（出現時）否則「Send one-time code」；code 步 =「Verify and continue」；/auth/verify =「Continue with Face ID / Touch ID」或「Verify and continue」；invite =「Accept invitation」。
- **Info sidebar** 唔用。Legal 一句留 form 底 `text-xs`。
- Copy 集中喺 `web/src/components/auth/strings.ts`（暫時英文），方便之後跟 worldwide languages 計劃用 Accept-Language 本地化；未登入讀唔到 profile locale。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Auth shell（AuthShell + template） | 四個入口共用一個安靜嘅殼。 | `AuthShell`：Wordmark bar + 主體（單欄或 `lg:` 兩欄 slot）。`web/src/app/auth/template.tsx` 包 `.t-page-enter`（`web/src/styles/transitions.css:252`），invite page 喺 shell 內自己加同一 class。h1 / 副題可加 `.t-stagger-line`（transitions.css:377，`--stagger-i` 0/1），喺 mount 時播；唔係 SSR 文字（AuthForm 等 catalog boot）。metadata 沿用 sign-in:5-9、sign-up:5-9、invite:6-9。 | 無 data 依賴；reduced motion 由 transitions.css:596-631 處理。 |
| Sign-in：方法揀選 | 返嚟嘅人三秒內揀到慣用方法；email code 路徑唔會開新 account。 | 標題「Sign in to PostRiff」、副題現有 107-111。按序：`Sign in with a passkey`（`auth-form.tsx:82` 條件）、`Continue with Google`（outline，下面 `text-xs`「New Google accounts start a free trial.」——因為 Supabase OAuth 冇 per-call 禁 sign-up）、分隔、email + `Send one-time code`（`LoadingButton`，`ui/loading-button.tsx:21`）。`sendCode` 喺 sign-in intent 用 `shouldCreateUser: false`。Supabase 回 `otp_disabled` / `/signups not allowed/i` → 中性 notice「We couldn't find an account for that email.」+ `Start a free trial`（`${siteConfig.links.signUp}?email=…&next=…`）；其他 error 經 mapping 表，未知就顯示原句。URL param：`?error=oauth&detail=…` → Alert「Google sign-in did not complete: {detail}」；`?reason=revoked` → Alert「You were signed out on this device because the session was revoked or expired.」 | loading → 現有 skeleton 113-122；unavailable → Alert + `Try again`（reload）；busy → LoadingButton；signed-in → `router.replace(next)`；mfa-required → `router.replace('/auth/verify?next=…')`。 |
| Email → Code 兩步 | 人永遠知自己喺邊步、code 寄咗去邊、幾時可以再寄。 | Step 2「Enter the code we sent to **{email}**」+ `Change email`。OTP 格數 = `GET /api/auth/config` 新欄位 `emailOtpLength`（deployment 設定，同 Supabase project 一致）；未有設定就保留現有 8 格 + ≥6 門檻，唔估。Submit `Verify and continue`（LoadingButton）。`Resend code`：按鈕喺 Supabase 回 rate-limit error 時 disabled，倒數用 error 入面嘅秒數（「after N seconds」）或 config `emailResendSeconds`，用 `DigitSwap`（`motion/digit-swap.tsx`，內置 reduced motion）；冇真值就唔顯示倒數，只顯示 Supabase 句子。Code 錯 → destructive Alert，清 code、focus 第一格、保留 email。成功 → `assurance()` pending → `/auth/verify?next=`，否則 `router.replace(next)`；`SuccessCheck`（`ui/success-check.tsx`）只喺非 reduced-motion 時顯示，而且唔阻 navigation 超過 `--duration-very-slow`。唔顯示 code 過期時間。 | idle → sending → sent → verifying → verified，全部由真 promise 推動。 |
| Sign-up：plan chooser + 已有 account 提示 | 開 trial 前揀 plan；已有 account 就講明只會登入。受邀嘅人唔揀 plan。 | 方法列同 sign-in（冇 passkey），`shouldCreateUser: true`。Plan chooser 133-161：`lg:` 右欄 card，phone / tablet 留 form 上方；價錢改 `formatPrice`；保留「You are not charged during the trial and nothing converts automatically.」。加 `text-xs`「Already have an account? This signs you in instead; your existing workspace keeps its plan.」（provider.tsx:84-89 有 workspace 就唔 bootstrap）。`?email=` 預填。`next` 以 `/invite/` 開頭時隱藏 plan chooser，改一句「You're creating an account to join a workspace.」（invite 流程唔 bootstrap trial）。 | 同 sign-in；plan 讀 `?plan=` / localStorage（44-47）。 |
| /auth/verify：2FA 第二步 | 2FA 第二步有自己 URL，refresh / back / deep-link 一致。 | 新 `web/src/app/auth/verify/page.tsx`（metadata `robots: noindex`）render `MfaChallenge next={safeNext}`。先抽走 `mfa-challenge.tsx:64` 嘅 `min-h-svh` 殼（AppGate fallback 自己包）。內容照舊：shield icon、「Confirm it's you」、passkey 優先 / TOTP 後備、`Sign out`。加 `Collapsible`（`ui/collapsible.tsx`）「Lost access to your authenticator?」：「If a passkey is saved on this device, use it above. Otherwise contact {siteConfig.supportEmail}. Two-factor can only be turned off from a verified session, so recovery needs a manual identity check.」（對應 hosted.py:698-708；唔承諾 support 一定解到）。成功 → `auth.completeMfa()` → `router.replace(next)`。AppGate `mfa-required` 改 `router.replace('/auth/verify?next=…')`，inline 版保留做 fallback。signed-out 到呢頁 → 去 sign-in；aal2 / 冇 enforcement → 直接 `next`。 | factors 未載 → 40px skeleton（84-85）；`factors=[]` 但 mfa-required → 「Your account expects a second factor but none could be listed. Sign out and try again, or contact support.」；busy → LoadingButton / 按鈕內 `Loader`（`motion/loader.tsx`）。 |
| /invite/[token]：邀請預覽 + 接受 | 撳 email link 入嚟嘅人，未登入都睇到邊個請佢入邊個 workspace 做咩 role；登入後一撳就入；過期 / 撤回 / 已用講清楚。 | 載入先 `GET /api/invitations/preview?token=…`（新，public，throttle）。Card：「{invitedBy.displayName \|\| 'A workspace admin'} invited you to {workspaceName \|\| 'a PostRiff workspace'}」；role 行「{ROLE_LABELS[role]} · {ROLE_DESCRIPTIONS[role]}」（`lib/auth/permissions.ts:32-46`）；權限用靜態 `Badge`（`ui/badge.tsx`），只列對該 role 真正生效嘅 flag（跟 permissions.ts `allows`：viewer 嘅 flag 無效）；「Expires {formatDate(expiresAt)}」（`lib/time.ts:46`）；「Sent to {emailHint}」（server masked）。 **signed-out**：`Sign in to accept` / `Create an account`（帶 `next=`），下面「Anyone signed in with this link can accept it; the workspace will see who joined.」（改正 69 行）。 **mfa-required**（新分支）：「Confirm two-factor to accept」→ `/auth/verify?next=/invite/…`。 **signed-in**：「Accepting as {auth.user.email}」+ `Switch account`（`auth.signOut()` 後留喺本頁）。Call `auth.api.myInvitations()`（`client.ts:125`）；`available` 且 `invitationId` 喺 list → badge「Sent to this email」；`available` 但唔喺 → reminder「This invitation was sent to a different address. You can still accept.」（remind, don't block）；`available: false` → 唔顯示任何配對句。Primary `Accept invitation`（LoadingButton）。 **成功**：「You joined {workspaceName} as {ROLE_LABELS[role]}.」，寫 localStorage、`router.replace('/app')`。 **409** → 「You are already a member of {workspaceName}.」+ `Open workspace`。 | preview loading → card skeleton；`state` ∈ expired / revoked / accepted / unavailable → `Empty`（`ui/empty.tsx`）各自句子 +「Ask the person who invited you to send a new one. Invitations sent to your email also appear on your profile.」，冇 Accept；preview 429 → 「Too many attempts. Try again in a minute.」；API unreachable → Alert + retry；auth unavailable → 現有 62-66。 |
| Context panel（lg+，sign-up 非邀請流程 / invite） | 右欄只放真選擇或真 data。 | sign-up：plan card。invite：preview card。冇 testimonial、冇統計、冇 logo wall。 | 跟各自 form。 |
| Legal + 切換 link | 每頁底部一致。 | 「By continuing you agree to the Terms and Privacy Policy.」（291-301）+ 相反 intent link（302-318），保留 `next`。 | 無。 |
| Dev harness 變體 | `authMode: 'dev'`（session.tsx:143-144）保持兩粒 button（auth-form.tsx:163-196）。 | 唔改行為。/auth/verify 喺 dev 唔會到（`me.mfa.available === false`）。Invite preview 喺 dev 用真 DB；`myInvitations` 喺 dev 可能 `available: false`，所以唔顯示配對句。 | signed-in → redirect。 |

- **Empty state**：Auth 冇 list，「empty」有三種：(1) invite token 過期 / 撤回 / 已用 / 搵唔到——由 preview API `state` 決定，`Empty` 講明邊種，並指出 profile 頁「Invitations waiting for you」（`web/src/features/account/profile-view.tsx:477`）會列出寄畀 verified email 嘅邀請；(2) sign-in 搵唔到 account——中性 notice + Start a free trial；(3) /auth/verify 列唔到 factor——講真話 + sign out。
- **Loading**：`role='status' aria-label='Loading'` Skeleton，形狀對齊最終 layout（標題 2/3、副題 1/2、兩粒 40px button；invite card 多兩行）。按鈕 busy 用 `LoadingButton`。唔寫「Checking your invitation…」之類假進度，唔用 progress bar。
- **Error**：全部讀真 error：(a) API unreachable → Alert + Try again；(b) Supabase rate limit → 顯示原句，倒數用句中秒數；(c) code 錯 / 過期 → destructive Alert，保留 email、清 code；(d) email sign-in 冇 account → 中性 notice；(e) OAuth callback → `?error=oauth&detail=`（限 200 字、strip 控制字元）；(f) passkey 取消 → `passkeyError`（mfa.ts:75-80）muted Alert；(g) invite 404 / 409 / 429 / 非 pending → 各自句子；(h) 被 revoke → API 回 `code: 'session_revoked'` → sign-in `?reason=revoked`；(i) API 403 `code: 'mfa_required'` → `/auth/verify`。Handler 唔 match 英文句子，唔處理 client.ts:80 嘅 no-token 401，喺 /auth/* 同 /invite/* 唔 redirect，避免 loop。未知 Supabase error 顯示原句。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Auth / invite 頁主體 | route mount（`web/src/app/auth/template.tsx` 每次導航 remount） | `.t-page-enter` fade + 8px slide，backwards fill；reduced motion 關閉。 | web/src/styles/transitions.css:252 `.t-page-enter`（同 web/src/app/app/template.tsx:13） | 否（純裝飾） |
| 每頁 h1 + 副題 | auth boot 完成後 mount | `.t-stagger-line` `--stagger-i` 0 / 1，40ms 一行，總長 < 300ms；純 CSS。 | web/src/styles/transitions.css:377 `.t-stagger-line` | 否（純裝飾） |
| Email step ↔ Code step 容器 | `sent` 改變（真 promise 完成後） | 新 `AuthStep` wrapper：`motion/react` `AnimatePresence`，enter opacity + translateY `--distance-base`，`--duration-fast` `--ease-smooth-out`；exit `--duration-quick`（收快過開）；`useReducedMotion()` → 只 opacity。 | transitions.css tokens（:20-37）；wrapper new（約 30 行） | 是 |
| Send code / Verify / Accept / 2FA 按鈕 | `busy === true` | `LoadingButton loading={busy}` spinner 疊喺 label 上，唔變闊、唔換假進度文字。 | web/src/components/ui/loading-button.tsx:21 | 是 |
| Verify / Accept / 2FA 成功 check | 真 `data.session` / accept 200 / `completeMfa()` 回嚟 | `SuccessCheck animate` 畫勾；reduced motion 時唔顯示並即刻導航；唔將導航延遲超過 500ms。 | web/src/components/ui/success-check.tsx + transitions.css:481 `.t-success-check` | 是 |
| Resend 倒數 | Supabase rate-limit error 回傳秒數 / config 值，每秒 tick | `DigitSwap` 換位數，只顯示真剩餘秒數；冇真值就唔顯示倒數。 | web/src/components/motion/digit-swap.tsx | 是 |
| Passkey 按鈕（sign-in、/auth/verify） | `busy` 期間等 WebAuthn ceremony | 按鈕內 `Loader` 取代 key icon；「Waiting for your device…」係真狀態（mfa-challenge.tsx:122 已用呢句）。 | web/src/components/motion/loader.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | 抽 `safeNext` 去 `web/src/lib/auth/safe-next.ts`，auth-form、callback route、/auth/verify、AppGate 共用 | frontend | 冇 | auth-form.tsx:26-28 同 callback/route.ts:4-6 各一份；proxy.ts 冇 | S |
| 2 | Email sign-in intent `shouldCreateUser: false` + `otp_disabled` / `/signups not allowed/i` → no-account notice；Supabase error mapping 表（fallback 原句）；Google 按鈕下「New Google accounts start a free trial.」 | frontend | 冇 | auth-form.tsx:59, 87-91 | S |
| 3 | `GET /api/auth/config` 加 `emailOtpLength`、`emailResendSeconds`（deployment env，同 Supabase project 一致；未設就省略） | api | 冇 | hosted_app.py:300-302 只回 `public_auth`；repo 冇 Supabase auth config | S |
| 4 | Code step 按 `emailOtpLength` 畫格（未設保留 8 格 + ≥6）；Resend + 真秒數倒數（Supabase error 秒數或 config） | frontend | 冇 | auth-form.tsx:255-288 冇 resend；264-273 8 格。`input-otp` 已預設 numeric / one-time-code，唔使加 | S |
| 5 | `/auth/callback` forward `error` / `error_description`（sanitise、限 200 字）→ `/auth/sign-in?error=oauth&detail=…&next=` | frontend | 冇 | web/src/app/auth/callback/route.ts:10-18 | S |
| 6 | Sign-up：`?email=` 預填；`formatPrice`；「signs you in instead」一句；`next` 係 `/invite/` 時隱藏 plan chooser | frontend | 冇 | auth-form.tsx:133-161, 152；plans.ts:84 | S |
| 7 | `GET /api/invitations/preview?token=…`（public，喺 `self._origin` / `self._token` 之前，hosted_app.py:338；token 長度 20-128；`throttle(cur, f'invite-preview:{client}', 30, 60)`）回 `{state, invitationId, workspaceName, role, permissions, invitedBy:{displayName}, expiresAt, emailHint}`；永遠唔回完整 email | api | 冇 | hosted_app.py:283-440 冇 preview | M |
| 8 | `HostedWorkspaceService.invitation_preview(raw, client=None)`：sha256 對 `token_hash`，JOIN workspace name + `pr_profiles.display_name`（抄 my_invitations hosted.py:839-854 嘅 SELECT），state 計法同 `invitations()`（revoked / accepted / expired / pending），唔 lock 唔寫 | backend | 冇 | hosted.py:796-812 只有 accept；state 邏輯喺 invitations() 約 780-786 | M |
| 9 | API error 加 machine code：verifier 401 → `code: 'session_revoked'`、403 → `code: 'mfa_required'`（AlphaError 加 optional code，hosted_app.py:499-500 一併回） | backend | 冇 | hosted_app.py:66, 71, 499-500 只回 `{error: str}` | S |
| 10 | Tests：preview route（pending / expired / 429 / 短 token 404）+ error `code` 欄位 | backend | 冇 | tests/test_postriff_phase2_hosted.py:221-254 冇 preview、冇 code | S |
| 11 | Client `previewInvitation(token)`（`get(…, false)`）+ `InvitationPreview` type（types.ts:709 附近）；invite 頁喺 WorkspaceProvider 之外，用 `useAuth().api` + 本地 `useQuery`，唔放 hooks.ts 嘅 useWorkspace 系列 | frontend | 冇 | client.ts:114-115 只有 acceptInvitation；hooks.ts:122-125 依賴 useWorkspace | S |
| 12 | `ApiError` 帶 `code`；`client.ts parse()` 讀 `code` | frontend | 冇 | client.ts:47-73 ApiError 只有 message + status | S |
| 13 | 抽 `AuthShell`（auth layout + invite page 共用）+ `web/src/app/auth/template.tsx`（.t-page-enter）+ `lg:` 兩欄 slot | frontend | 冇 | auth/layout.tsx:7-14 同 invite/[token]/page.tsx:13-26 重複殼；冇 auth template | S |
| 14 | 重寫 `accept-invitation.tsx`：preview-driven states、mfa-required 分支、email 配對 reminder（尊重 `available`）、Switch account、409、role-effective Badge | frontend | 冇 | accept-invitation.tsx:47-93 冇 mfa-required 分支、通用 card、69 行 claim 錯 | M |
| 15 | `MfaChallenge` 抽走 `min-h-svh` 殼、加 `next` prop、Lost access Collapsible、factors 空句子；新 `web/src/app/auth/verify/page.tsx` | frontend | 冇 | mfa-challenge.tsx:19, 64；`ls web/src/app/auth` 冇 verify | S |
| 16 | `AppGate` mfa-required → `router.replace('/auth/verify?next=…')`（inline fallback）；`verifyCode` / passkey / callback 後 `assurance()==='pending'` 直接去 /auth/verify | frontend | 冇 | app-gate.tsx:87；auth-form.tsx:78, 104 | S |
| 17 | 全局 session handler：`parse()` 見 `code==='session_revoked'` → `postriff:session-revoked` event；`code==='mfa_required'` → `postriff:mfa-required`；AuthProvider 監聽：前者 `signOut({scope:'local'})` + `/auth/sign-in?reason=revoked&next=`，後者 `setStatus('mfa-required')`；喺 /auth/* 同 /invite/* 唔 redirect，唔處理 client.ts:80 no-token 401 | frontend | 冇 | client.ts:60-73, 80；session.tsx 冇 listener | M |
| 18 | `data-tour` ids：`security-2fa`（security-card.tsx 約 511 嘅 row wrapper）、`security-sessions`（`Sessions()` 624 嘅 root）、`security-passkeys`（passkeys-card.tsx:146 Card）；pending invitations 用現有 `section[aria-label='Invitations waiting for you']`（profile-view.tsx:477）或加 `pending-invitations`；`TourCtx` 加 `mfaAvailable`、`mfaEnforced`、`passkeySignIn`、`pendingInvitations` | frontend | 冇 | features/account 冇 data-tour；tours.ts:14-24 | S |
| 19 | Copy strings module `web/src/components/auth/strings.ts`（英文，預留本地化） | frontend | 冇 | copy 散落 auth-form / accept-invitation / mfa-challenge；app/layout.tsx:55 `lang='en'`，冇 i18n library | S |
| 20 | MfaChallenge（passkey 優先、TOTP 後備、sign out）——未 commit WIP | frontend | 有 | web/src/components/auth/mfa-challenge.tsx:19-138（git untracked） | S |
| 21 | MFA server 強制 + `POST\|DELETE /api/auth/mfa` + `GET /api/me` 帶 mfa | backend | 有 | hosted_app.py:57-71, 355-359；hosted.py:570-590, 680-708（hosted*.py 有未 commit 修改） | S |
| 22 | `POST /api/invitations/accept`（throttle 10/60 IP、token hash、7 日 TTL） | api | 有 | hosted_app.py:370-372；hosted.py:39, 796-812 | S |
| 23 | 邀請 email + welcome email | backend | 有 | email.py:92-102；hosted.py:771-775（invitation，inviter label = inviter email）、535-537（welcome）；都要 `public_base_url` + mailer | S |
| 24 | `GET /api/me/invitations`（verified email；`available:false` 當 lookup 唔可用） | api | 有 | hosted_app.py:366-367；hosted.py:839-854；client.ts:125 | S |
| 25 | Supabase email template 有 `{{ .Token }}`；OTP 長度同 resend 間隔同 `emailOtpLength` / `emailResendSeconds` env 一致 | infra | 冇 | repo 冇 Supabase auth config；auth-form.tsx:97-101 期望 code | S |
| 26 | Production apply migration 009（`pr_mfa_enforcement`）+ Supabase 開 TOTP / WebAuthn | infra | 冇 | hosted_app.py:63 每個 request SELECT `pr_mfa_enforcement`；memory project-account-security-2fa 列為 deploy 前置 | S |
| 27 | Passkey sign-in flag + Supabase experimental passkeys | infra | 有 | lib/auth/passkeys.ts:20-22；lib/supabase/client.ts:14；web/.env.example:14 預設 false | S |
| 28 | Role labels / descriptions + `allows` 規則 | frontend | 有 | web/src/lib/auth/permissions.ts:25-46 | S |
| 29 | Motion 元件：LoadingButton、SuccessCheck、DigitSwap、Loader、Badge、`.t-stagger-line`、`.t-page-enter` | frontend | 有 | ui/loading-button.tsx:21；ui/success-check.tsx:9；motion/digit-swap.tsx:48；motion/loader.tsx:54；ui/badge.tsx；transitions.css:252, 377, 481 | S |

## 3. Features

### P0

- **Invite 頁登入前睇到邀請內容（preview endpoint）+ mfa-required 分支**：而家 card 通用、claim 一個 API 冇執行嘅 email 限制（accept-invitation.tsx:50, 69），開咗 2FA 嘅人仲見唔到任何按鈕。Link 本身係憑證，可以登入前講：邊個、邊個 workspace、咩 role、幾時過期、寄畀邊個（masked）。過期 / 撤回 / 已用由 `state` 講。（depends on：`GET /api/invitations/preview` + `hosted.invitation_preview`）
- **2FA 第二步搬去 `/auth/verify`**：而家人喺 `/app/calendar` URL 睇住登入畫面（app-gate.tsx:87）；有 route 之後 refresh / back / deep-link 一致，invite 頁 mfa-required 都有地方去。

### P1

- **Email code sign-in 唔開新 account + no-account notice**：`shouldCreateUser: true`（auth-form.tsx:89）令 sign-in 頁打錯 email 會喺 Supabase 開未確認 user 並寄 sign-up email 畀陌生人；用錯另一個自己嘅 email 就會開第二個 trial workspace。Google OAuth 冇得禁，所以講明。
- **Code step：真長度、Resend、真秒數倒數**：冇 resend，email 遲到要 reload；格數同倒數都係 Supabase project 設定，要讀 deployment 值或 Supabase error，唔寫死。（depends on：`GET /api/auth/config` 加 `emailOtpLength` / `emailResendSeconds`）
- **被 revoke / 過期 session 送返 sign-in 並講原因**：Refresh token 撤咗之後，到 access token 過期前每個 query 各自紅字（冇 401 handler）。加 error `code` 之後前端可以即刻送返 sign-in。（depends on：API error `code` 欄位）
- **OAuth callback error 講明細**：`?error=callback` 一句對 consent 被拒、provider 未設定、cookie 被擋都一樣；Supabase 已帶 `error_description`。
- **AuthShell + template 進場 + context panel**：兩個殼 copy 咗兩次；進場同 app 一致（template.tsx:13）；右欄只放真選擇 / 真 data。

### P2

- **Profile 頁「Account security」tour**：sign-in 見到嘅 passkey / 2FA / invitation 概念要有地方教；tours.ts 冇 security 步。Tour copy 只描述已 ship 嘅行為。（depends on：`data-tour` ids + `TourCtx` 新欄位；sessions step 嘅 revoke 句要等 P1 handler）
- **「Lost access to your authenticator」誠實路徑 + 之後 admin unenroll**：冇 recovery code，`disable_mfa` 要 AAL2（hosted.py:698-708）。第一步講真話；第二步另開 spec。
- **Passkey sign-in 可用性由 `GET /api/auth/config` 講**：`NEXT_PUBLIC_PASSKEY_SIGN_IN` 係 build-time（passkeys.ts:20-22），同一個 build 對唔同 Supabase project 講唔到唔同答案。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明三件事：(1) 冇密碼——email code、Google 或 passkey 就入到（方法列排序 + 分隔線教，副題講明係返嚟嘅門）；(2) sign-up 係開 14 日 trial、唔使卡（現有副題 auth-form.tsx:110 + 「nothing converts automatically」+「Already have an account? This signs you in instead.」）；(3) invite：邊個請你入邊個 workspace 做咩 role、幾時過期（preview card 第一行 + ROLE_DESCRIPTIONS）。Auth 頁唔跑 tour（TourMount 只喺 web/src/app/app/template.tsx:15，登入畫面唔應有 overlay），教學由 copy 同 state 做；passkey / 2FA / invitation 喺 /app/account/profile 有短 tour。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour='security-2fa']（加喺 web/src/features/account/security-card.tsx 約 511 嘅「Two-factor authentication」row wrapper；`when: ctx.mfaAvailable`）` | Two-factor authentication | Turn this on and every sign-in asks for a second step: a passkey on this device or a code from an authenticator app. Sessions that skip it are refused. (Body reads `ctx.mfaEnforced` → "It is on for your account." / "It is off.") |
| 2 | `[data-tour='security-passkeys']（加喺 web/src/features/account/passkeys-card.tsx:146 Card；`when: ctx.passkeySignIn`）` | Passkeys for sign-in | Register a passkey here and the sign-in page offers Face ID, Touch ID or a security key instead of an email code. Only the public key is stored; the biometric never leaves your device. |
| 3 | `[data-tour='security-sessions']（加喺 web/src/features/account/security-card.tsx:624 `Sessions()` 嘅 root）` | Where you are signed in | Every device that reached PostRiff is listed with when it was first and last seen. You can sign out one device or all the others. (Body reads the real count from `useSessions`; add "that device is sent back to the sign-in page" only after the revoked-session handler ships.) |
| 4 | `section[aria-label='Invitations waiting for you']（web/src/features/account/profile-view.tsx:477，已存在；`when: ctx.pendingInvitations > 0`）` | Invitations waiting for you | Invitations sent to your verified email show up here even without the link. Accept or decline; accepting adds you with the role the inviter chose. (Body: "{n} waiting" from `useMyInvitations`.) |

**Empty state 教咩**：Invite 頁過期 / 撤回 / 已用 empty state 教：邀請一次性、7 日有效（hosted.py:39），寄畀你 verified email 嘅邀請都會喺 profile 出現，叫 inviter 再寄就得。Sign-in no-account notice 教：email code sign-in 唔會偷偷開 account，開 trial 係另一道門。/auth/verify 冇 factor 嘅 state 教：第二步係 server 強制，有問題 sign out 或聯絡 support。

## 5. Next steps（按次序）

1. **落手前 `git status` + `git diff` 以下檔案：mfa-challenge.tsx、lib/auth/mfa.ts、lib/auth/passkeys.ts（untracked）、session.tsx、auth-form.tsx、app-gate.tsx、hosted.py、hosted_app.py。確認 account-security session 已 commit 或協調好；只按 path stage。**（effort S）  
   檔案：`web/src/components/auth/mfa-challenge.tsx, web/src/lib/auth/mfa.ts, web/src/lib/auth/passkeys.ts, web/src/lib/auth/session.tsx, web/src/components/auth/auth-form.tsx, web/src/components/layout/app-gate.tsx, src/postriff_phase2/hosted.py, src/postriff_phase2/hosted_app.py`
2. **Backend：`invitation_preview`（token 長度檢查、sha256、JOIN、state、masked emailHint）+ public route（hosted_app.py:338 之前，throttle 30/60）；AlphaError 加 optional `code`，verifier 401 / 403 帶 `session_revoked` / `mfa_required`；`public_auth` 加 `emailOtpLength` / `emailResendSeconds`（env，可省略）；tests 加 preview pending / expired / 429 / 短 token + error code。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py（796 附近）, src/postriff_phase2/hosted_app.py（57-71, 300-340, 499-500）, tests/test_postriff_phase2_hosted.py（221 附近）`
3. **Client：`ApiError.code`、`previewInvitation(token)`、`InvitationPreview` type；抽 `lib/auth/safe-next.ts`。**（effort S）  
   檔案：`web/src/lib/api/client.ts（47-73, 114）, web/src/lib/api/types.ts（709 附近）, web/src/lib/auth/safe-next.ts（新）`
4. **`AuthShell` + `web/src/app/auth/template.tsx`（.t-page-enter）；auth layout 同 invite page 改用 AuthShell；copy 搬去 `components/auth/strings.ts`。**（effort S）  
   檔案：`web/src/components/auth/auth-shell.tsx（新）, web/src/app/auth/layout.tsx, web/src/app/auth/template.tsx（新）, web/src/app/invite/[token]/page.tsx, web/src/components/auth/strings.ts（新）`
5. **`MfaChallenge` 抽殼、加 `next` + Lost access Collapsible + factors 空句；新 `/auth/verify` page；AppGate mfa-required → redirect（inline fallback）。**（effort S）  
   檔案：`web/src/components/auth/mfa-challenge.tsx, web/src/app/auth/verify/page.tsx（新）, web/src/components/layout/app-gate.tsx:86-87`
6. **重寫 `accept-invitation.tsx`：preview states、mfa-required 分支、email 配對 reminder（尊重 `available`）、Switch account、409、role-effective Badge、LoadingButton。**（effort M）  
   檔案：`web/src/app/invite/[token]/accept-invitation.tsx`
7. **AuthForm：sign-in `shouldCreateUser:false` + error mapping + Google 提示句；sign-up `?email=`、`formatPrice`、signs-you-in 句、invite 流程隱藏 plan；OTP 格數讀 config；Resend + 真秒數倒數（DigitSwap）；LoadingButton；`AuthStep` wrapper；verify / passkey 後 pending → /auth/verify；讀 `error` / `detail` / `reason` params。**（effort M）  
   檔案：`web/src/components/auth/auth-form.tsx, web/src/components/auth/auth-step.tsx（新）`
8. **Callback route forward `error` / `error_description`（限 200 字、strip 控制字元）。**（effort S）  
   檔案：`web/src/app/auth/callback/route.ts`
9. **全局 session handler：parse() 按 `code` dispatch event；AuthProvider 監聽並 redirect（/auth/*、/invite/* 除外，唔理 no-token 401）。**（effort M）  
   檔案：`web/src/lib/api/client.ts:60-73, web/src/lib/auth/session.tsx`
10. **Onboarding：三個 `data-tour` id；`tours.ts` 加 security tour（route `/app/account/profile`）；`TourCtx` + `use-tour-context.ts` 加四個欄位；sessions step 嘅 revoke 句等 step 9 上線。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts, web/src/features/onboarding/use-tour-context.ts, web/src/features/account/security-card.tsx, web/src/features/account/passkeys-card.tsx`
11. **Infra checklist + docs：Supabase template `{{ .Token }}`、OTP 長度 / resend 間隔同 env 一致；migration 009；TOTP + WebAuthn；`NEXT_PUBLIC_PASSKEY_SIGN_IN`；`public_base_url` + mailer。docs §5 232 行註明 `/auth/verify` = 2FA step（同 `POST /api/auth/verify` 區分）；§8 421 行 tick invite UI 並加 preview。**（effort S）  
   檔案：`web/.env.example, docs/postriff-consumer-saas-redesign.md（232, 421）`
12. **驗證：dev harness（:3100 web；唔好喺 :4331 做 approve / send）走 invite preview + accept；Supabase 環境走 email no-account、code 長度、resend rate-limit、/auth/verify、另一部機 revoke、invite + 2FA；375px 截圖。**（effort S）  
   檔案：`scripts/postriff_dev_hosted.py（只用嚟跑）`

## Risks

- Supabase email template 只有 magic link 冇 `{{ .Token }}` 的話，code step 係死嘅；repo 驗證唔到，deploy 前要睇 dashboard。
- OTP 長度同 resend 間隔係 Supabase project 設定；env 同 dashboard 唔一致就會畫錯格數，所以未設 env 時保留現有寬鬆行為。
- `otp_disabled` code / 「Signups not allowed for otp」句子隨 auth-js 版本可能變（`@supabase/supabase-js ^2.58.0`）；mapping 同時對 code 同 regex，fallback 原句。
- No-account notice 會洩露某 email 有冇 account（Supabase 本身都洩露）；如果要收緊，改中性句「If an account exists, a code is on its way」並接受 UX 代價——要 James 決定。
- Google OAuth 喺 sign-in 頁仍然可以開新 account（Supabase 冇 per-call 選項）；只能靠 copy 講明。
- Preview endpoint 令持有 link 嘅人睇到 workspace 名同 inviter display name；link 本身已係憑證，但要 throttle、驗 token 長度、永遠唔回完整 email。
- Accept-by-token 唔 check email 係設計決定；UI 只 remind，唔寫成限制。改做強制 match 要改 backend + email 文案，另開決定。
- 2FA 鎖死冇出路：冇 recovery code、冇 admin unenroll；support 而家實際幫唔到，copy 唔可以承諾。
- Migration 009 未 apply 的話 verifier（hosted_app.py:63）每個 request 500。
- `NEXT_PUBLIC_PASSKEY_SIGN_IN=true` 但 Supabase 未開 experimental passkeys → 按鈕永遠失敗（passkeys.ts:9-11）。
- Bootstrap throttle 30/60 per IP（hosted.py:514-516），共用 NAT 可能 429。
- `/auth/verify` 同 `POST /api/auth/verify`（bootstrap）撞名，log / 文件要講清楚。
- 全局 401 handler 如果 match 錯（no-token 401、auth 頁自己）會 redirect loop；只按 `code` 處理。
- MFA / passkey stack 係 untracked WIP，另一個 session 可能重寫；memory 記錄過 parallel-session reset 洗走未 commit 修改，落手前先確認。

## 覆核記錄

- 改正：打錯 email 會開孤兒 workspace + 寄 welcome email → 改寫問題描述，priority 由 P0 降 P1。
- 改正：welcome email 喺 hosted.py:541-544 → 改做 hosted.py:535-537
- 改正：OTP 八格係 UI bug、375px 會爆闊 → 唔 hardcode 6；長度由 deployment 設定講（例如 `GET /api/auth/config` 加 `emailOtpLength`），前端按真值畫格。
- 改正：要加 inputMode='numeric'、autoComplete='one-time-code' → 從 requirement 移除，改為驗證 iOS autofill 實際有效。
- 改正：safeNext 喺 proxy.ts:29 同 route.ts:4-6 已有 → 抽去 web/src/lib/auth/safe-next.ts，三處共用。
- 改正：401「This session expired or was revoked」冇全局 handler，被 revoke 嘅機每個 query 各自紅字、唔會返 sign-in → 描述改為有時間窗；handler 唔好 match 英文句子，backend 加 `code`（session_revoked / mfa_required）。
- 改正：MfaChallenge 可以直接放入 auth layout render → 抽走外殼，AppGate fallback 自己包。
- 改正：auth 檔案自 b678aad 之後未 commit；只有 auth-form.tsx、app-gate.tsx 有未 commit 修改 → next step 1 改為 diff 全部上述檔案，並先確認 account-security session 是否已 commit。
- 改正：auth layout 加 .t-page-enter 就每頁有進場 → 新增 web/src/app/auth/template.tsx 放 .t-page-enter。
- 改正：h1 / 副題用 .t-stagger-line 係「純 CSS，SSR 先讀到字」 → 保留 CSS class（mount 時播），但刪除 SSR claim。
- 改正：/invite/[token] 同 auth 共用 web/src/app/auth/layout.tsx 殼 → 抽 AuthShell component 畀兩邊用。
- 改正：AnimatedBadge 適合做 permission chips 逐粒出 → 用 ui/badge.tsx，冇 motion；或者只隨 card 一齊進場。
- 改正：Sign-in 用 shouldCreateUser:false 就「sign-in 永遠唔開新 account」 → feature 名改為「Email code sign-in 唔開新 account」，Google 路徑誠實講。
- 改正：RBAC 規則路徑 web/src/lib/auth/access.ts → auth 頁唔經 access；invite chips 要用 permissions.ts 嘅 allows 規則（viewer 嘅 flag 無效）。
- 違反原則（已改）：Capability honesty：tour step「Where you are signed in」寫「that device is sent back to the sign-in page with the reason shown」，但 revoked handler 未存在；tour copy 描述未 ship 嘅行為。要喺 P1 landing 之後先加，或者寫現況。
- 違反原則（已改）：真數據先郁：Resend 倒數寫死 Supabase 60s、OTP 寫死 6 位，兩者都係 project 設定，唔係 repo 讀得到嘅真值；倒數要讀 Supabase error 回傳秒數或 deployment config。
- 違反原則（已改）：Motion §5.3：聲稱 `.t-stagger-line` 令 auth h1「SSR 先讀到字」，但 AuthForm 係 client-only render（loading 時係 Skeleton），claim 唔成立。
- 違反原則（已改）：Motion reuse：用 AnimatedBadge（status morph、spring + blur exit）做靜態權限 chips，唔係佢嘅用途，而且 exit 用 filter 唔止 transform/opacity。
- 違反原則（已改）：Motion：`.t-page-enter` 放 layout 唔會喺 auth 頁之間 replay，要用 template.tsx（同 app/app/template.tsx 一致）。
- 違反原則（已改）：誠實：「sign-in 永遠唔開新 account」對 Google OAuth 唔成立；「typo 變孤兒 workspace + welcome email」誇大咗問題。
- 違反原則（已改）：General-not-personal：冇違規（copy 全部通用），但 first_visit 加咗未證實嘅「plan 可以之後改」，要刪。
- 補上遺漏：Invite 頁冇處理 `auth.status === 'mfa-required'`：accept-invitation.tsx 只有 signed-out / signed-in / unavailable 分支，開咗 2FA 嘅人會見到一張冇任何按鈕嘅 card，而 accept 會被 verifier 403。
- 補上遺漏：Sign-up 經 invite link 入嚟（next=/invite/...）仍然顯示 trial plan chooser，但受邀嘅人唔會 bootstrap trial（invite 頁冇 WorkspaceProvider，accept 後 /app 已經有 workspace）；應隱藏 plan chooser 並講明「You are joining a workspace」。
- 補上遺漏：Account enumeration：sign-in no-account notice「No account uses {email} yet」會洩露某 email 有冇 account；要記錄呢個取捨（Supabase otp_disabled 本身已洩露），並加 throttle / 中性措辭選項。
- 補上遺漏：API error 冇 machine-readable code（hosted_app.py:499-500 只回 `{error}`），全局 401/403 handler match 英文句子好脆弱；要加 `code`。
- 補上遺漏：全局 401 handler 要避開 client.ts:80 嘅「no token」401、auth 頁本身、同 /api/cron 等其他 401，唔可以 loop redirect。
- 補上遺漏：MfaChallenge 自帶 min-h-svh 殼（mfa-challenge.tsx:64），搬去 /auth/verify 前要抽走。
- 補上遺漏：Invite 頁殼係 copy 出嚟（invite/[token]/page.tsx:13-26），唔係 auth layout；兩欄 context panel 要一個共用 AuthShell。
- 補上遺漏：所有 MFA / passkey 檔案係 untracked WIP（git status ??），spec 只提 auth-form / app-gate。
- 補上遺漏：i18n / languages：web 冇 i18n library（app/layout.tsx:55 `lang='en'`），auth 頁未登入讀唔到 profile `preferences.locale`；要講清楚 copy 暫時英文、集中喺一個 strings module，之後跟 worldwide languages 計劃用 Accept-Language。
- 補上遺漏：Invite chips 嘅權限要跟 permissions.ts `allows` 規則（viewer 嘅 flag 無效），唔係直接列 true flags。
- 補上遺漏：Preview endpoint 要驗 token 長度 20-128（同 accept_invitation 一樣），避免任意字串打 DB。
- 補上遺漏：SuccessCheck 500ms 之後先 router.replace 會人為延遲導航；reduced-motion 時應即刻導航。
- 補上遺漏：`/auth/verify` 同 `POST /api/auth/verify`（bootstrap）撞名，docs 232 原意未確認係 MFA。
- 補上遺漏：Error copy 直接吐 Supabase 原句（auth-form.tsx:59），要有 mapping 表 + fallback 顯示原句。
