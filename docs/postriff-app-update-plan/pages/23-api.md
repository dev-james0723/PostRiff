# 23 · API & integrations

> Route：`/app/account/api` · Sidebar：Account · 成熟度：未 set up · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

呢頁而家係一個「講緊冇嘢」嘅 placeholder，只有一個 real-data list，其餘全部係靜態文字或者靜態 config。

**前端** `web/src/features/account/api-view.tsx`（102 行，'use client'）：
- 第 15–16 行：`useChannels()`（`web/src/lib/api/hooks.ts:49-52` → `client.ts:167` → `GET /api/workspaces/{id}/channels`）攞 `channels[]`，第 32–40 行逐個 render platform · account 同 `scopes.length` Badge。全頁唯一真數據，同 `/app/channels` 重複，冇用 `ChannelView.capabilities`（`types.ts:445-455`）。
- 第 50–68 行「Developer access」card：純文字「There is no separate API key yet」，CTA 去 `siteConfig.links.contact?topic=api`（`web/src/config/site.ts:16` → `/contact`）。冇 hook。
- 第 70–98 行「Integration surface」card：讀 `hostedChannels` / `localChannels`（`web/src/config/channels.ts:145-146` 靜態 config），第 78 行對成組 hosted connectors 硬寫 `<CapabilityBadge level='assisted' label='review pending' />`，第 84 行印 config 嘅 `reviewStatus`（`channels.ts:55, 78, 97`）。Blended badge + 唔係 API 值，違反 capability honesty 同真數據規則。API 已回 `providers[].productionReviewed`（`src/postriff_phase2/oauth.py:203`，type `ProviderView` `types.ts:460-465`），頁面冇用。
- 冇 `access=` gate：`PageContainer`（`web/src/components/layout/page-container.tsx:42-70`）支援 `access` / `accessFallback`，`members-view.tsx:263`、`billing-view.tsx:136` 有用，`api-view.tsx` 冇。Sidebar 有 gate（`web/src/config/nav-config.ts:175-181` `manage_connections`），viewer 直接打 URL 照見到（`checkAccess` 本身係 UI-only，`web/src/lib/auth/access.tsx:66-69` 註解）。
- 冇 loading / error state：load 緊會顯示「No providers connected yet」（假 empty）。
- 冇 `infoContent`、冇 `data-tour`；`web/src/features/onboarding/tours.ts:156` PAGE_TOURS 有 home / channels / analytics / queue / calendar / overview / brand / memory / inbox 9 個 tips，冇 api。
- Route `web/src/app/app/account/api/page.tsx`；breadcrumb `web/src/hooks/use-breadcrumbs.tsx:36`。UI copy 全英文，冇 i18n framework。

**後端** `src/postriff_phase2/`：
- `tools.py`（88 行）：6 個 versioned tool（第 17–36 行），`isolation_status()` 第 49–51 行回 `{isolated: False, runner: 'request-process', detail, publicInvokeEnabled: False}`；`invoke()` 79–88 行永遠 503（paid tool 先 402，而 `hosted_app.py:380` 冇傳 credits_ok）。
- `hosted_app.py:313` `GET /api/tools`（public）回 `{tools, isolation}`；`hosted_app.py:378-380` `POST /api/tools/{id}/invoke`（要 session）→ 503。Tests `tests/test_postriff_consumer_web.py:128-143, 183-186`。web/src 冇 call `/api/tools`。
- Auth 只有 Supabase session：`__call__` 第 332 行先 `_origin()`、334 行 `_token()`（`hosted_app.py:184-188`，Bearer 長度 >27）；真正 verify 喺 service 入面 `self.verify_session(token)`（`hosted.py:107` 等），production 係 `supabase_verifier`（`hosted_app.py:39-76`，62-71 行查 tombstone / session revocation / MFA AAL2），dev 係 `scripts/postriff_dev_hosted.py` 嘅 verifier（`auth_time` 回 `time.time()`）。**冇 personal access token、冇 table、冇 route。** Session：`GET /api/auth/sessions`（`hosted_app.py:350` → `hosted.py:886`）、`DELETE /api/auth/sessions/{id}`（`hosted_app.py:432` → `hosted.py:898`，`assert_fresh` 喺 `hosted.py:117-122`）。
- `_origin()`（`hosted_app.py:209-219`）只管 mutation：要 `X-Postriff-Request: founder-alpha` + Origin 對 host，非 browser client 打唔到 mutation（GET 用 session JWT 就得）。
- Workspace 存取：`hosted.py:108-114` foreign / 不存在一律 403 `Workspace unavailable.`，每次 transaction 重查 active membership。
- Audit：`audit()` `hosted.py:91`，24 個 kind，冇 `api_token.*`；rate limit `throttle()` `hosted.py:77-88`。
- Webhooks：只有 inbound `POST /api/billing/webhook`（`hosted_app.py:289-296`）；`channels.py:9` 嘅 `webhooks` 係 provider capability。
- Ideas：`ideas.py:388-390` paid model route 會 reserve writing batch——任何「draft」scope 都會用錢。
- MCP：src 冇 server（`research.py:201` 只係 Exa MCP client）。計劃：`docs/postriff-agent-chat-design.md:116, 221-223`（stdio + paired device credential）、`docs/postriff-mobile-model-access.md:22, 69, 141-143`（remote MCP Streamable HTTP + OAuth 2.1）。
- RBAC：`permissions.py:21` `manage_connections` = owner + admin（或 flag `can_manage_connections`）。Migration 去到 `012_channel_pictures.sql`，下一個 013；`tests/phase2/rls.sql:19-29` `\ir` list。

**結論**：頁名叫「API & integrations」但冇 API、冇 integration；唯一真數據係 Channels 頁嘅副本。核心要做 (1) workspace-scoped personal access token（read + draft，永遠唔俾 publish / reply / connect）、(2) 所有 status 讀真 snapshot、(3) 靜態「integration surface」換成 API 回傳嘅 providers + per-capability 資料，review 狀態同 capability level 分開講。

## 1. Design specification（最新版）

**目的**：俾 owner / admin 一頁睇晒「瀏覽器以外點樣接觸到呢個 workspace」：建立同撤銷 personal access token（只限 read + draft，publish / reply / connect 永遠留喺 app 人手批）、睇 tool registry 同 runner 隔離狀態嘅真實值、睇每個 connection 逐項 capability level，同埋老實列出未有嘅嘢（MCP connector、webhooks）。每個數字、badge、狀態都讀 API；未有嘅寫「Not available yet」，攞唔到嘅寫「Unavailable」，永遠唔變 0。

**Layout**：沿用 `PageContainer`：`pageTitle='API & integrations'`、`pageDescription='Tokens for your own scripts and agents, the tool registry, and what each connected account allows.'`、`infoContent`（3 段）、`pageHeaderAction=<Button data-tour='api-create-token'>Create token</Button>`、`access={checkAccess(useWorkspaceAccess(), { permission: 'manage_connections' })}`（`web/src/lib/auth/access.tsx:61, 69`），`accessFallback`：「Only owners and admins manage tokens. Ask one of them, or open Channels to see what is connected.」+ Channels link。API 仍然係真 enforcement。

主體 `grid gap-4 grid-cols-1 lg:grid-cols-3`：
- Row 1（`col-span-full`）`data-tour='api-status'`：3 個 `StatCard`（`web/src/components/app/stat-card.tsx`，已包 Skeleton + NumberTicker），`grid-cols-1 md:grid-cols-3`：Active tokens · Connected accounts · Tool runner。
- Row 2 左（`lg:col-span-2`）`data-tour='api-tokens'`：Personal access tokens card（≥768px table；<768px 用 `Item` 疊卡）。欄：Name · Prefix（`prt_ab12…` monospace）· Scopes · Expires（`formatDate` + `relativeTime`，`web/src/lib/time.ts`）· Last used（`relativeTime` + client label，冇就 `Never`）· Created by · Status（`AnimatedBadge`）· Revoke（`HoldActionButton`）。
- Row 2 右（`lg:col-span-1`）`data-tour='api-tools'`：Tool registry card。
- Row 3（`col-span-full`）`data-tour='api-grants'`：Connected accounts + providers card。
- Row 4（`col-span-full`）`data-tour='api-roadmap'`：Not here yet card。

Responsive：375px 單欄、PageContainer `px-4` gutter，stat 疊 3 行，token 變 `Item` 卡（name+prefix / scopes / expires+last used / status+revoke 四行），HoldActionButton 全寬 ≥44px 高，capability chips `flex-wrap`，token reveal `break-all` + Copy 全寬。768px：stat 3 格一行，token table 出現（Last used、Created by `hidden lg:table-cell`），tools card 喺 tokens 下面。1440px：3 欄（tokens 2、tools 1），info sidebar 開住，table 全欄。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Access status strip | 5 秒內答到「呢個 workspace 有幾多個非瀏覽器入口」同「tool runner 係咪隔離」。 | 3 個 `StatCard`：(1) Active tokens = `tokens.filter(t => !t.revokedAt && t.expiresAt > now).length`，footer `n expire within 14 days`；(2) Connected accounts = `channels.length`（同 Channels 頁同一個 `useChannels`），footer 數 `capabilities.publish.level`：`d Direct publish · a Assisted · b Bridge`；(3) Tool runner：value 讀 `isolation.isolated ? 'Isolated' : 'Not isolated'`，footer 讀 `publicInvokeEnabled ? 'Invoke enabled' : 'Invoke blocked'` + `runner: {isolation.runner}`。 | Loading：`StatCard loading`。Error：value 顯示 `Unavailable`（文字，唔 mount ticker），其餘 tile 照常。0 只會喺 API 真係回空 array 時出現。 |
| Personal access tokens | 建立、睇、撤銷 workspace-scoped token；講清楚 token 做唔到咩。 | Status：`revokedAt` → `neutral 'Revoked'`（30 日後唔再列出）；`expiresAt <= now` → `danger 'Expired'`；`< 14d` → `warning 'Expires soon'`；否則 `success 'Active'`。Create token `Dialog`：Name（必填，≤40 個字元，任何文字）、Scopes（`read` 預設剔；`draft` 附一句：`Draft runs use this workspace's writing batches, the same as in the app.`）、Expiry `RadioGroup`（30 days / 90 days / 1 year，冇 never）。Supabase 模式先彈 `StepUpDialog`（由 `security-card.tsx:72` 抽出 export），`me.mfa.available=false`（dev）唔彈，後端 dev verifier 自己過 `assert_fresh`。成功後同一個 Dialog 轉 reveal：完整 token 一次過（monospace、`Copy`），警告 `This is the only time PostRiff shows the full token.`，關閉後 invalidate。Revoke 唔使 step-up（漏咗 token 要即刻熄得）。Card 底固定 copy：`Tokens read the workspace and create drafts. Publishing, replying, connecting accounts, billing, members and deleting always happen in the app, by a person.` | Empty：`Empty`（`web/src/components/ui/empty.tsx`）見 empty_state。Loading：3 行 `Skeleton`。Error：`Alert variant='destructive'` `Tokens could not be loaded.` + Retry。Revoke：`HoldActionButton holdingLabel='Keep holding' completeLabel='Revoked'`，完成後 row status 變 Revoked（唔即刻消失，保留紀錄）。Create 失敗：Dialog 內 `Alert` 顯示 API message（例如 429 `Too many attempts. Wait a minute and try again.`），保留輸入。 |
| Tool registry | 誠實展示 `/api/tools` 嘅 tool 同 runner 狀態，令人明白「有 registry ≠ 可以 invoke」。 | 頂部 `AnimatedBadge`：`isolated` false → `warning 'Not isolated'`，下面一句讀 `isolation.detail`。每行：`{id}` monospace + `v{version}`、effect Badge（read / creative_write / workspace_mutation / paid_generation，中性 outline，唔用 capability 顏色免混淆）、cost Badge（none / metered / paid）、purpose。Footer 讀 `bounds`：`{maxSeconds}s · {maxInputBytes} bytes in · network {network}`；如果 `publicInvokeEnabled` false，加一句 `Invoke is blocked on this deployment.`（由 flag 決定顯唔顯）。 | Loading：6 行 skeleton（數目唔寫死亦可以用 4 行）。Error：`Alert` `The tool registry could not be loaded.`。API 回空 array：`No tools are registered for this deployment.`。 |
| Connected accounts & providers | 每個 connection 逐項 capability level；deployment 提供邊啲 provider、review 到邊。管理動作留喺 Channels。 | 上半每個 connection 一行：`ChannelIcon` + platform · account · `connectionState` badge · `CapabilityChips`（`web/src/features/channels/capability-chips.tsx` 原樣 reuse，hover / tap 睇 evidence、verifiedAt、capabilityVersion）· `Access until {expiresAt}` · `Manage on Channels`。下半「Providers on this deployment」讀 `providers[]`：platform + 中性 Badge `productionReviewed ? 'Provider review passed' : 'Provider review pending'`（唔用 LevelBadge）+ 列出 `capabilities` 入面 true 嘅項目做 plain text `Scopes offered: publish, analytics`（false 唔顯示成 level）。冇任何 blended Connected 剔。 | Empty：`No accounts connected in this workspace.` + `Open Channels`；providers 部分照顯示。Loading：2 行 skeleton。Error：`Alert` `Accounts could not be loaded.`，唔影響其他 card；status strip 第 2 格同步 Unavailable。 |
| Not here yet | 老實列出 roadmap 上未 ship 嘅入口。 | 兩行：`MCP connector — Not available yet. Planned: an assistant app you already use reads this workspace and proposes drafts, and you approve them here.`；`Outbound webhooks — Not available yet. Planned events: post published, post failed, approval requested.` 每行 `LevelBadge level='Unsupported' label='Not available yet'`。CTA `Request early access` → `/contact?topic=api`。 | 純 copy，無 loading。MCP endpoint 上線時必須改讀 API 狀態（見 risks）。 |
| Info sidebar | 常駐解釋。 | `infoContent` title `Outside the browser`：(1) `What a token can do` — read the workspace, channels, queue and analytics; with the draft scope, start drafts and conversations in Ideas, which use writing batches like the app does；(2) `What always stays in the app` — publishing, replying, connecting or disconnecting accounts, approving, billing, members, deleting; a token that tries gets 403；(3) `Where to look` — Channels for connected accounts, Workspace audit for token events。 | 靜態 copy。 |

- **Empty state**：Tokens card：`Empty` + `EmptyMedia variant='icon'`（`Icons.key`，`web/src/components/icons.tsx:258`）、`EmptyTitle` `No tokens yet`、`EmptyDescription`：`A token lets your own script or agent read this workspace, and with the draft scope start drafts. It never publishes, replies or connects an account: those stay in the app, approved by a person. Every token expires on a date you pick and can be revoked here at any time.` 按鈕 `Create token`。Accounts card 空：`No accounts connected in this workspace.` + `Open Channels`。Status strip 嘅 0 係 API array length，唔係 unavailable。
- **Loading**：唔用 PageContainer `isLoading`（整頁 skeleton），每張 card 自己 `Skeleton`（`web/src/components/ui/skeleton.tsx`），形狀同最終內容一致。冇 loading 文案、冇 progress bar。`useTools` `staleTime: 10 * 60_000`（照 `useModels` hooks.ts:127-130）。
- **Error**：每張 card 獨立 `Alert variant='destructive'`（`web/src/components/ui/alert.tsx`）+ `Retry`（`refetch()`），錯一張唔拖冧其他；strip 對應格顯示 `Unavailable`。401 由 `ApiError`（`client.ts:47, 80`）統一處理。API 403（例如 role 喺 session 中途被降級）：card 顯示 accessFallback 同一句，唔用 destructive。Create 429：Dialog 顯示 API message。Revoke 失敗：row 保持原 status + toast 顯示 API message。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁 | route enter | `.t-page-enter`（transitions.css:252） | web/src/app/app/template.tsx（已有，唔使加） | 否（純裝飾） |
| Status strip 數字（Active tokens、Connected accounts） | query success，或 create / revoke 後 count 變 | `NumberTicker` 滾到 API 整數；Unavailable 時傳字串，唔 mount ticker | web/src/components/app/stat-card.tsx（內含 motion/number-ticker.tsx） | 是 |
| Tool runner badge、token Status badge | 值改變（`contentKey` = status 字串） | `AnimatedBadge` content swap | web/src/components/motion/animated-badge.tsx（channel-card.tsx:224、queue/job-row.tsx 已用） | 是 |
| Token rows 首次出現 | tokens query 第一次 success（refetch 唔重播） | motion `opacity 0→1 + y 4px→0`，每行 stagger ≤40ms，總長 ≤300ms（超過 7 行後嘅 row 唔再加 delay）；`useReducedMotion()` 時直接顯示。唔用 `.t-stagger-line`（佢係 SSR headline reveal，仲郁 blur） | new（motion v11，跟 docs/postriff-motion-system.md §5 rule 2、4） | 是 |
| Revoke | 長按 | `HoldActionButton` 填充 → `completeLabel='Revoked'`，status badge swap；破壞性動作用長按做確認（§5 rule 5） | web/src/components/motion/hold-action-button.tsx（queue-view / job-row 已用） | 是 |
| Create token Dialog、StepUp Dialog | open / close | `.t-modal` + `.t-modal-backdrop`（收快過開） | web/src/components/ui/dialog.tsx:31,53（已接 transitions.css:183-208） | 否（純裝飾） |
| Copy token 按鈕 | clipboard 寫入成功（promise resolve 先播） | success check 播一次，label `Copy` → `Copied`，1.5s 回復 | web/src/components/ui/success-check.tsx | 是 |
| Scope checkboxes、expiry radio | toggle | beUI 畫剔 / 圓點 | web/src/components/motion/checkbox.tsx、web/src/components/motion/radio.tsx | 否（純裝飾） |
| Capability chips | hover / focus / tap | HoverCard 80ms open / 100ms close；無 hover 裝置用 Popover | web/src/features/channels/capability-chips.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{id}/channels 回 channels[]（per-capability matrix）+ providers[]（productionReviewed + 4 個 boolean） | api | 有 | src/postriff_phase2/hosted_app.py:411-414 → src/postriff_phase2/oauth.py:191-203；client.ts:167；hooks.ts:49-52；types.ts:445-465 | S |
| 2 | GET /api/tools（public）回 {tools, isolation{isolated, runner, detail, publicInvokeEnabled}} | api | 有 | hosted_app.py:313-314；tools.py:49-55；tests/test_postriff_consumer_web.py:183-184 | S |
| 3 | web client `tools()`（get(path, false)）+ hook `useTools()` + types `ToolDefinition` / `ToolIsolation` | frontend | 冇 | client.ts 冇 /api/tools；client.ts:84 get(path, auth) 支援 auth=false；hooks.ts:11-32 keys 冇 tools | S |
| 4 | POST /api/tools/{id}/invoke（503，頁面唔 call） | api | 有 | hosted_app.py:378-380；tools.py:79-88 | S |
| 5 | Table public.pr_api_tokens（id, workspace_id, user_id, name, prefix, token_hash bytea unique, scopes text[], expires_at not null, last_used_at, last_used_client, revoked_at, created_at）service_role-only RLS | data | 冇 | migrations/postriff 最後 012_channel_pictures.sql；新 013_api_tokens.sql 跟 009_account_security.sql:5-15；tests/phase2/rls.sql:19-29 加 \ir + authenticated 讀唔到嘅斷言 | S |
| 6 | Routes GET/POST /api/workspaces/{id}/tokens、DELETE /api/workspaces/{id}/tokens/{tokenId}（manage_connections；POST 要 assert_fresh；DELETE 唔要；session-only） | api | 冇 | hosted_app.py 路由 279-497 冇 tokens；assert_fresh hosted.py:117-122（revoke_session hosted.py:900 用緊）；throttle() hosted.py:77-88 | M |
| 7 | Token verify：prt_ Bearer 喺 verify_session wrapper 解析（production supabase_verifier + dev verifier），sha256 查表、未 revoke / 未過期 / 未 tombstone，回 principal；session_id、aal 回 None，auth_time 回 0 令 assert_fresh fail closed；last_used 每 60s 至多寫一次 | backend | 冇 | verify 由 service call（hosted.py:107、516…），唔喺 __call__；hosted_app.py:39-76；scripts/postriff_dev_hosted.py:55-63 | M |
| 8 | Scope guard 喺 __call__：_origin()（第 332 行）之前讀 Authorization，prt_ 請求跳過 _origin，只放行 GET（read）同 ideas quick-start / conversations / turns / attachments（draft）；其餘同所有 auth/*、tokens 路由 403 `Tokens cannot do this; open PostRiff.`；workspace 唔對 → 403 `Workspace unavailable.` | backend | 冇 | hosted_app.py:209-219、332-334；hosted.py:112-114 403 規則；tools.py:5-6 原則 | M |
| 9 | Audit kinds api_token.created / api_token.revoked（meta {name, scopes, expiresAt}，永遠唔記 token）+ web label | backend | 冇 | hosted.py:91 audit()；workspace audit route hosted_app.py:465；useAudit hooks.ts:74；label 分散喺 web/src/features/workspace/audit-view.tsx、recent-access-changes.tsx、web/src/features/account/profile-model.ts | S |
| 10 | Tests：create/list/revoke、revoked/expired 401、scope deny 403（POST actions、channels oauth、billing）、token 唔可以 create token、role 降級後 token 403、cross-workspace 403、create 冇 fresh session 403、429 | backend | 冇 | tests/test_postriff_phase2_hosted.py；WSGI invoke() pattern tests/test_postriff_consumer_web.py:178-190；tests/phase2/rls.sql | M |
| 11 | web types ApiToken / ApiTokenCreated / TokenScope、client tokens / createToken / revokeToken、hooks useTokens + keys.tokens(w) + mutations invalidate tokens + audit | frontend | 冇 | types.ts、client.ts、hooks.ts:11-32 冇 | S |
| 12 | Page-level access gate + accessFallback | frontend | 冇 | api-view.tsx 冇 access prop；access.tsx:61,69；members-view.tsx:238-264 pattern；nav-config.ts:175-181 | S |
| 13 | StepUpDialog reuse（要抽出 export） | frontend | 有 | web/src/features/account/security-card.tsx:72（未 export，600/610 內部用）；Me.mfa.available types.ts:655-660；security-card.tsx:461 | S |
| 14 | StatCard / LevelBadge / CapabilityChips / ChannelIcon / AnimatedBadge / HoldActionButton / success-check / Empty / Skeleton / Dialog / Item / motion checkbox + radio | frontend | 有 | web/src/components/app/{stat-card,level-badge}.tsx；web/src/features/channels/capability-chips.tsx；web/src/components/channel-icon.tsx；web/src/components/motion/{animated-badge,hold-action-button,number-ticker,checkbox,radio}.tsx；web/src/components/ui/{success-check,empty,skeleton,dialog,item}.tsx | S |
| 15 | Info sidebar（PageContainer infoContent） | frontend | 有 | page-container.tsx:49,79 prop；web/src/components/ui/infobar.tsx:40；pattern web/src/features/account/models-view.tsx:16-23 | S |
| 16 | Tour api-tips + data-tour ids | frontend | 冇 | tours.ts:156 PAGE_TOURS 冇 /app/account/api；heading() 第 51 行；TourCtx.canManageConnections 第 22 行 | S |
| 17 | client_label() 寫 last_used_client | backend | 有 | hosted_app.py:86-90 | S |
| 18 | Remote MCP endpoint（Streamable HTTP）+ integrations 狀態 route | backend | 冇 | src 冇 MCP server；docs/postriff-mobile-model-access.md:141-143 講明要 OAuth 2.1；docs/postriff-agent-chat-design.md:221-223 stdio 方案 | L |
| 19 | Outbound webhooks（table、routes、HMAC、worker 派送 + retry） | backend | 冇 | 只有 inbound hosted_app.py:289-296；worker tick hosted_app.py:322-331 | L |
| 20 | API reference 頁 /docs/api | frontend | 冇 | web/src/app/(marketing)/docs/page.tsx grep API 零命中；site.ts:13 docs link | M |

## 3. Features

### P0

- **Personal access tokens（workspace-scoped，read + draft，必有 expiry，一次過顯示，長按 revoke）**：呢頁存在嘅理由。Creator 工具提供 API key 係常見做法（Postiz public API，[未驗證] 落手前重查 docs.postiz.com/public-api）。PostRiff 分別係 token 永遠唔帶 publish / reply / connect（tools.py:5-6、redesign §1.1），而且一定有 expiry（30 / 90 天 / 1 年）。
- **Access status strip 全部讀 API**：三格分別讀 GET /tokens、GET /channels、GET /api/tools；攞唔到就 Unavailable。（depends on：Personal access tokens）
- **Tool registry card 讀 /api/tools，isolated 同 publicInvokeEnabled 分開顯示**：後端有 6 個 tool 同 isolation_status()（tools.py:49-55），web 從來冇顯示；分開兩個 flag 先唔會將「未隔離」同「invoke 被擋」混埋。
- **Connected accounts 逐 capability + providers review 狀態分開講（取代靜態 Integration surface）**：現有 card 用 config 字串 + blended badge（api-view.tsx:78-84）。API 已回每個 connection 嘅 matrix 同 providers[]（oauth.py:191-203），reuse CapabilityChips。
- **Page-level access gate + create 要 step-up**：Sidebar gate 擋唔住直接打 URL；token 係長效憑證，create 要 assert_fresh；revoke 唔要，方便即刻熄。（depends on：Personal access tokens）

### P1

- **Token activity：last used + created by + api_token.* audit**：Revoke 要有依據；client_label()（hosted_app.py:86）已有；audit 入 workspace log。（depends on：Personal access tokens）
- **Remote MCP connector**：docs/postriff-mobile-model-access.md:22 方向：assistant app 用用戶自己 plan，PostRiff 提供 memory、drafts、排期提案。Claude / ChatGPT custom connector 要 OAuth 2.1（同文件 141-143），token bearer 只適合自家 script / 開發工具。Buffer 已有 MCP [未驗證]。未 ship 前只顯示 Not available yet。（depends on：Personal access tokens）

### P2

- **Outbound webhooks（HMAC 簽名）**：automation 用戶會要，但唔係第一步；token + MCP 穩定先做。（depends on：Personal access tokens）
- **/docs/api reference**：冇 docs 嘅 token 冇人用得到：request format、scopes、error codes、quick-start 嘅 confirmUse / ownContent 意思。（depends on：Personal access tokens）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內明白三件事：(1) 呢頁係「瀏覽器以外點接觸 workspace」，唔係 Channels 副本；(2) token 讀同起草，永遠唔代你發佈；(3) 未有嘅嘢老實寫明。點教：pageDescription 一句講範圍；status strip 三格真數字；tokens empty state 直接講 can / cannot；roadmap 用 Not available yet badge。Copy 全部 general（script、agent、workspace），唔提任何行業、品牌或者 James 嘅例子。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="api-title"] → fallback heading('api')（main h1 已存在）` | Everything outside the browser | This page is where your own scripts and agents reach this workspace. Connecting accounts still happens on Channels; here you manage tokens and see what each account allows. |
| 2 | `[data-tour="api-status"]（要加）` | Numbers from the API | Active tokens, connected accounts and the tool runner's status. When a value cannot be read it says Unavailable, never zero. |
| 3 | `[data-tour="api-create-token"]（要加）→ fallback [data-tour="api-tokens"]` | A token reads and drafts | Create a token for a script or an agent. It can read the workspace and, with the draft scope, start drafts that use writing batches like the app does. Publishing, replying, connecting accounts and billing always stay in the app. Every token expires. |
| 4 | `[data-tour="api-tools"]（要加）` | The registry is not a runner | These are the versioned tools PostRiff can offer an agent. The badge shows whether the runner is isolated and whether invoke is enabled on this deployment. |
| 5 | `[data-tour="api-grants"]（要加）` | Capability by capability | Each connected account lists its verified level for every capability. Open a chip to see the evidence and when it was checked. Manage the account itself on Channels. |
| 6 | `[data-tour="api-roadmap"]（要加）` | What is not here yet | An MCP connector and outbound webhooks are planned but not shipped. They stay marked Not available yet until they work. |

**Empty state 教咩**：Tokens empty state 教三樣：(1) token 係俾你自己嘅 script 或 agent，唔係俾人 share；(2) read + draft 做到，publish / reply / connect 做唔到，draft 會用 writing batches；(3) token 有 expiry，隨時喺呢頁 revoke。Accounts 空：connect 喺 Channels 做。Status strip 嘅 0 係 API 真 0。

## 5. Next steps（按次序）

1. **Migration 013_api_tokens.sql：建 public.pr_api_tokens（見 technical_requirements），index (workspace_id, revoked_at)、unique token_hash，service_role-only RLS（照 009:5-15）。tests/phase2/rls.sql 加 `\ir ../../migrations/postriff/013_api_tokens.sql` 同 authenticated role select 失敗嘅斷言。**（effort S）  
   檔案：`migrations/postriff/013_api_tokens.sql；tests/phase2/rls.sql`
2. **新 service src/postriff_phase2/api_tokens.py：create（require manage_connections、repository.assert_fresh、scopes ⊆ {read, draft}、expires_days ∈ {30,90,365}、'prt_' + secrets.token_urlsafe(32)、存 sha256、audit api_token.created、throttle() 5/min/user、回完整 token 一次）、list（唔回 hash，含 createdBy，revoked 30 日內仍列）、revoke（manage_connections，唔要 step-up，audit api_token.revoked）、resolve(raw) → {userId, workspaceId, scopes, tokenId}。**（effort M）  
   檔案：`src/postriff_phase2/api_tokens.py（新）；src/postriff_phase2/hosted.py（mount）`
3. **hosted_app.py：(a) __call__ 喺第 332 行 _origin() 之前判斷 Authorization 係咪 'Bearer prt_'，係就跳過 _origin 並 set environ['postriff.api_token']；(b) _scope_guard(method, parts, scopes) 放行 GET（read）同 ideas quick-start / conversations / turns / attachments（draft），其餘（actions、channels oauth/verify/disconnect、billing、members、invitations、account、memory 寫入、audience reply、auth/*、tokens）403；(c) verify_session wrapper（supabase_verifier + scripts/postriff_dev_hosted.py dev verifier）遇 prt_ 走 api_tokens.resolve，session_id/aal → None、auth_time → 0；path workspace 唔對 → 403 `Workspace unavailable.`；(d) 3 條 tokens route（session-only）。**（effort M）  
   檔案：`src/postriff_phase2/hosted_app.py（39-76、209-219、279-497）；scripts/postriff_dev_hosted.py`
4. **Tests：tests/test_postriff_phase2_hosted.py 加 TokensTest（見 technical_requirements 清單，包括 role 降級後 403、token 打 POST actions 403、token 打 tokens route 403）；跑 `python -m unittest tests.test_postriff_phase2_hosted tests.test_postriff_consumer_web`。**（effort M）  
   檔案：`tests/test_postriff_phase2_hosted.py`
5. **Web data layer：types.ts 加 TokenScope、ApiToken {tokenId, name, prefix, scopes, expiresAt, lastUsedAt, lastUsedClient, revokedAt, createdAt, createdBy}、ApiTokenCreated、ToolDefinition、ToolIsolation；client.ts 加 tokens / createToken / revokeToken / tools（auth=false）；hooks.ts 加 keys.tokens(w)、keys.tools、useTokens、useTools（staleTime 10 min）、useCreateToken / useRevokeToken invalidate tokens + audit。**（effort S）  
   檔案：`web/src/lib/api/types.ts；web/src/lib/api/client.ts；web/src/lib/api/hooks.ts`
6. **重寫頁面：拆 web/src/features/account/api/{api-view,status-strip,tokens-card,create-token-dialog,tools-card,accounts-card,roadmap-card}.tsx；StepUpDialog 抽去 web/src/features/account/step-up-dialog.tsx（security-card import 返）；page-level access；status strip 用 StatCard；每 card 自己 Skeleton / Alert；data-tour ids api-title、api-status、api-create-token、api-tokens、api-tools、api-grants、api-roadmap；infoContent 三段。落手前 sync（另一 session 改緊 web/src），逐路徑 stage。**（effort M）  
   檔案：`web/src/features/account/api-view.tsx → web/src/features/account/api/*；web/src/app/app/account/api/page.tsx（import path）；web/src/features/account/security-card.tsx；web/src/features/account/step-up-dialog.tsx（新）`
7. **Motion 接線：StatCard NumberTicker、AnimatedBadge contentKey、row 首次 stagger（motion，≤40ms、總 ≤300ms、useReducedMotion）、HoldActionButton revoke、success-check copy。**（effort S）  
   檔案：`web/src/features/account/api/tokens-card.tsx；create-token-dialog.tsx；tools-card.tsx`
8. **Tour + audit label：tours.ts PAGE_TOURS 加 api-tips（route '/app/account/api'，6 步，when ctx.canManageConnections）；audit-view.tsx、recent-access-changes.tsx、profile-model.ts 加 api_token.created / api_token.revoked label。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts；web/src/features/workspace/audit-view.tsx；web/src/features/workspace/recent-access-changes.tsx；web/src/features/account/profile-model.ts`
9. **Dev harness 驗證（preview pane :3100，唔好撳 approve / schedule / send / Re-verify / disconnect）：建 token → curl `Authorization: Bearer prt_…` 打 GET channels 200、POST actions 403；revoke → 401；viewer 身份直接開 URL 見 accessFallback；375 / 768 / 1440 截圖；`npm run lint && npx tsc --noEmit`。**（effort S）  
   檔案：`web/（verification only）`
10. **P1：remote MCP endpoint（Streamable HTTP），先支援 prt_ bearer 俾 script / 開發工具，OAuth 2.1 做正式 connector；integrations 狀態 route；roadmap card MCP 行改讀真狀態 + connector URL。**（effort L）  
   檔案：`src/postriff_phase2/mcp_server.py（新）；src/postriff_phase2/hosted_app.py；web/src/features/account/api/roadmap-card.tsx`
11. **P2：outbound webhooks（014 migration、routes、HMAC、worker 派送 + retry）+ /docs/api reference。**（effort L）  
   檔案：`migrations/postriff/014_webhooks.sql；src/postriff_phase2/webhooks.py；src/postriff_phase2/hosted_app.py；web/src/app/(marketing)/docs/api/page.tsx`

## Risks

- IA 衝突：docs/postriff-agent-chat-design.md:468 寫「API & integrations 改名做 Models & providers」，但 nav-config.ts:168-181 兩頁並存。要 James 拍板；建議保留兩頁互相 link（Models 講 draft 喺邊度寫，API 講瀏覽器以外點入嚟）。
- Token 冇 session，繞過 MFA AAL2 check（hosted_app.py:62-71）。緩解：create 要 fresh step-up、auth_time=0 令所有 assert_fresh 動作 fail closed、tombstone 即失效、expiry ≤1 年、每 request 重查 membership。
- _origin() 係 browser CSRF 防線，prt_ 請求跳過佢：判斷必須喺 _origin 之前而且只認 prt_ 前綴；test 要包 token 打 POST actions 403。
- Draft scope 會用 writing batches（ideas.py:388-390），script 出錯可能燒晒額度；要 throttle turns，Usage & plan 要見到 token 觸發嘅 run。
- Quick-start 要 confirmUse / ownContent，token client 等於代人確認使用權；docs 同 audit 要講清楚。
- 每 request 一次 sha256 lookup + last_used 寫：last_used 要 throttle（≥60s）。
- Connected accounts 數字同 Channels 頁必須用同一個 useChannels。
- Roadmap card 係唯一靜態狀態；MCP 上線後一定要改讀 API，否則變假狀態。
- 另一 session 改緊 web/src 同 scripts/postriff_dev_hosted.py：落手前 sync，逐路徑 stage。
- Dev harness Threads 係 live provider：驗證 accounts card 唔好撳 Re-verify / disconnect。
- Plan gating 未決：trial workspace 可唔可以建 token 要 James 決定；預設唔 gate，最多加 reminder。
- Copy 全部 general；tools.py purpose 字串原樣顯示 OK。外部競品數字（Postiz rate limit、Buffer MCP 日期）未驗證，唔好寫入 UI。

## 覆核記錄

- 改正：api-view.tsx 係 103 行，useChannels 喺 15-16，list 32-40，Developer access 50-68，Integration surface 70-98，第 78 行硬寫 CapabilityBadge assisted 'review pending'，第 84 行印 reviewStatus → 改做 102 行
- 改正：PageContainer access/accessFallback 喺 page-container.tsx:25-38 → page-container.tsx:42-70
- 改正：tours.ts PAGE_TOURS 157+ 只有 home / channels / queue / calendar / brand / memory / overview → 列返 9 個，冇 api-tips 呢點係啱
- 改正：rate limit helper hosted.py:~85-90 → hosted.py:77-88 throttle()
- 改正：Cross-workspace token → 404 'Workspace unavailable.' → 用 403 同一句，跟現有 indistinguishable 規則
- 改正：Verifier branch：_token() 後 prt_ 開頭就跳過 _origin() → prt_ 判斷要喺 _origin 之前讀 Authorization header；principal 解析放入 verify_session wrapper（supabase_verifier 同 scripts/postriff_dev_hosted.py 嘅 dev verifier），session_id/aal 回 None、auth_time 回 0 令 assert_fresh fail closed；scope guard 放 __call__ 路由前
- 改正：`.t-stagger-line`（transitions.css:377）用嚟做 token rows 首次出現，row 入場 220ms → 改用 motion stagger（≤40ms/行、總 ≤300ms）+ useReducedMotion，或者唔做 row 入場
- 改正：useReducedMotion 喺 motion-system.md §5.2 → motion-system.md §5 rule 2
- 改正：Empty state copy：token 'never ... spends credits' → 改寫：draft run 同 app 一樣計 workspace 嘅 writing batches，喺 Usage & plan 睇到
- 改正：Provider 列表 productionReviewed → LevelBadge Direct / Assisted → review 狀態用中性 Badge 文字；capability 只講 'scope offered' boolean，唔畀 level
- 改正：Tool runner tile：publicInvokeEnabled ? 'Isolated runner' : 'Invoke blocked' → label 讀 isolated，sub 讀 publicInvokeEnabled
- 改正：Tour：Green is Direct, amber is Assisted, grey is not offered → 唔講顏色，講 'each chip names its level'
- 違反原則（已改）：Capability honesty：providers 區用 productionReviewed 砌 LevelBadge Direct/Assisted，將 provider review 狀態扮成 capability level（違反 redesign §1.1）
- 違反原則（已改）：真數據 / 誠實 copy：empty state 同 info sidebar 話 token 'never spends credits'，但 draft scope 嘅 ideas turns 會 reserve writing batch（ideas.py:388-390）
- 違反原則（已改）：Tool runner tile 用 publicInvokeEnabled 講 'Isolated runner'，唔係讀 isolated 欄位，數據同 label 唔對應
- 違反原則（已改）：Motion §5：`.t-stagger-line` 係 SSR marketing 文字 reveal（仲郁 filter blur），拎嚟做 client table row 入場；220ms 係自創時長，冇 token 根據
- 違反原則（已改）：Motion reuse：copy 成功應 reuse web/src/components/ui/success-check.tsx，唔係直接 cite CSS class
- 違反原則（已改）：Accessibility / 誠實：tour 用顏色解釋 level，又漏咗 Bridge（local）level
- 補上遺漏：i18n：web UI 而家淨係英文，冇 i18n framework；docs/postriff-worldwide-languages-plan.md 講嘅係 post 語言唔係 UI。Token name 要接受任何文字（用 code point 計 ≤40），日期用 lib/time.ts 跟 preferences.locale / timeZone
- 補上遺漏：RBAC 細節：token 每個 request 都要經 repository.transaction 重新查 active membership + role，所以人被降級、移除或者離開 workspace 之後 token 自動失去權限；owner/admin 睇得到全 workspace 所有 token（createdBy），但只可以 revoke，唔睇到 secret
- 補上遺漏：Revoke 唔應該要 step-up（token 漏咗要即刻熄得）；只有 create 要 assert_fresh
- 補上遺漏：Consent 風險：ideas quick-start body 要 confirmUse / ownContent，token client 等於代人確認版權同使用權，要喺 scope 解釋同 API docs 講清楚，同埋 audit
- 補上遺漏：Dev verifier 喺 scripts/postriff_dev_hosted.py（另一個 session 改緊），prt_ branch 要同步；dev 嘅 auth_time 回 time.time()，所以 step-up 喺 dev 自動通過
- 補上遺漏：StatCard（web/src/components/app/stat-card.tsx）已經有 loading Skeleton + NumberTicker，status strip 應直接 reuse，唔使自己砌 tile
- 補上遺漏：Mobile：HoldActionButton 喺 touch 要 min 44px 高；token reveal 畫面 375px 下 monospace token 要 break-all + Copy 按鈕全寬
- 補上遺漏：Plan gating：access.plan 有 trial/studio/assist，spec 冇講 trial workspace 可唔可以建 token——要 James 決定，預設唔 gate（remind 唔 block）
- 補上遺漏：Error：api 403 'Workspace unavailable.' 同 client.ts ApiError 401 'Your session ended' 嘅處理；token list 讀 403 時顯示 access fallback 而唔係 destructive alert
- 補上遺漏：Audit label 冇單一 describer：web/src/features/workspace/audit-view.tsx、recent-access-changes.tsx、account/profile-model.ts 各有 switch，要逐個加 api_token.*
