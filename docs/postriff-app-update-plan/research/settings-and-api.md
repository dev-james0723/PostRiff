# 專題研究：PostRiff Settings 資訊架構同「API & integrations」頁嘅完整設計（已覆核修正版）

> 研究 agent 起稿（包括網上資料），再由另一個 agent 重新 fetch 關鍵來源同 grep codebase 覆核。

## 建議

建議將 sidebar 而家嘅「Workspace」（5 項）同「Account」（6 項）收埋做一個「Settings」區：路徑係 `/app/settings/[section]`，左邊有一條第二層 rail，分「你（Personal）」、「Workspace」、「Developer」三組。唔建議用一頁橫向 tabs，原因有三。第一，項目有 11 個以上，好多項要睇 permission 先顯示，橫 tabs 會隨角色跳位，手機亦塞唔落。第二，而家分錯咗位：`API & integrations` 放喺 Account，但 access 用 `manage_connections`，係 workspace 權限，key 同 webhook 都屬於 workspace。第三，Brand 同 Memory 係日日寫作都會用嘅內容，應該留喺主 sidebar，開一個「Voice」組，URL 保持 `/app/workspace/brand`、`/app/workspace/memory` 唔變，咁 welcome tour 同舊 link 都唔使改。咁樣主 sidebar 由 21 項減到 13 項。Settings 用 Linear、Vercel 嗰種「左 rail + 內容」模式，手機就用「清單 → 詳情」。舊 URL（`/app/account/*`、`/app/workspace/(members|roles|audit)`）喺 `web/next.config.ts` 加 `redirects()`（而家未有），Cmd+K 照樣逐頁列出；順手修正 Channels 同 Home 共用 `h h` shortcut 嘅衝突。

API & integrations 嘅核心原則同產品定位一致（見 `docs/postriff-competitive-research-20260916.md`「5. Approval-first agent」）：agent 同外部程式可以做 research、寫 draft、提出 schedule，但係 publish、reply、connect、charge、delete 永遠要人喺 PostRiff 入面批准。API key scope 只可以對應 `permissions.py` 嘅 `read` 同 `edit`，外加 `schedule:propose`（只建立 review manifest），永遠唔可以攞 `approve`、`reply`、`moderate`、`manage_connections`、`manage_members`、`owner`。每次 request 都用「建立者當刻 membership ∩ key scopes」重新計權限，建立者被刪帳戶（`pr_profiles.deleted_at`）或者離開 workspace，key 即時失效。Webhooks 跟 Standard Webhooks：簽 `id.timestamp.body`，secret 用 `whsec_`，rotation 期間同一個 `webhook-signature` header 放兩個 `v1,` 簽名。Payload 係 thin event（`type`、`timestamp`、`data` 只有 id 同數字）。送出前要重新檢查建立者仲有冇該類事件嘅權限（例如 inbox 事件要 `reply`），唔可以令 webhook 變成繞過 RBAC 嘅側門。

有兩個技術限制，研究初稿估錯咗。第一，`/api/cron/worker` 已經喺一個 60 秒 function 入面行 `worker.tick()`（預設 20 秒）、reminders 同 learning sweep，webhook 同 RSS 唔可以再塞 40 秒入去，要開獨立 cron path `/api/cron/deliveries`。第二，`PostgresWorkspaceRepository.effects` 只喺 `command()` 入面行，channel、成員、inbox 嘅 mutation 都唔經佢，所以 outbox 要用一個 `emit()` helper，喺每個 `audit()` call site 用同一個 cursor 寫入，job 事件就接 `hosted_worker.py` 嘅 `complete()`。分期：第一期做 Settings 殼、API keys、public API v1（讀取、draft、schedule proposal，server 端處理 revision 409 同 Idempotency-Key）、webhooks。第二期做 MCP：先接受 API key bearer；之後跟 MCP spec 2025-11-25 做 OAuth 2.1，以 Client ID Metadata Documents 為主，DCR 只做 fallback，`/.well-known/*` 要喺 `vercel.json` 加 rewrite 先會去到 Python。Zapier、Make、n8n 第一期唔整官方 app。Desktop pairing 未接通，照實顯示「未開放」。RSS 抓返嚟嘅 item 入 Ideas，唔會自動變 draft 或者發佈。

## 考慮過嘅選項

| Option | Verdict | Why |
|---|---|---|
| A. 維持而家兩組 sidebar（Workspace 5 項 + Account 6 項，主 sidebar 合共 21 項） | 唔建議 | 主 sidebar 太長，而且分組同權限模型對唔上：API & integrations 用 manage_connections（workspace 權限）卻放喺 Account；Models & providers 嘅 route 政策同 billing 都係 workspace 決定；Brand、Memory 係日常內容，唔係設定。 |
| B. 一頁 /app/settings，上面橫向 Tabs（ui/tabs.tsx / motion/tabs.tsx） | 唔建議做主結構 | 11 項以上再加權限過濾，tab 數量會隨角色變，位置會跳；手機要橫 scroll；每個 tab 內容量差好遠。Tabs 只適合頁內第二層，例如 Agents 頁嘅 client snippet。 |
| C. 單一 Settings 區：/app/settings/[section] + 左 rail 三組，手機 list→detail；主 sidebar 只留 Settings 入口，Brand、Memory 移去「Voice」組並保留原 URL | 建議 | 同 Linear、Vercel、Notion 做法一致；權限過濾只影響 rail 入面嘅項目，主導航穩定；Brand、Memory 保留原 URL，welcome tour（tours.ts 嘅 brand、memory 步驟）唔使改；主 sidebar 由 21 項減到 13 項。 |
| D. 將 API keys、MCP 併入 Models & providers（agent-chat-design §8.4） | 唔建議 | Models & providers 講嘅係 draft 用邊個 model 寫、點計錢，權限係 edit；API、webhook、MCP 講嘅係外部程式點樣入嚟，權限係 manage_connections。兩樣混埋，editor 會見到佢管唔到嘅嘢。兩頁互相 link 就夠。 |
| API key scope：俾 owner 開 approve／publish scope（好似 Buffer、Blotato、Postiz 嘅 API 可以直接發佈） | 第一期唔做，列做要 James 拍板嘅問題 | tools.py 將 external_representation 列入 FORBIDDEN_EFFECTS。Blotato 嘅 `blotato_create_post` 確實可以經 MCP 直接發佈，所以競品壓力係真嘅。將來要開嘅話，要限 owner、要 MFA、只可以批准已經 review 過 digest 嘅 manifest，而且每日有上限。 |
| MCP 認證：API key header vs OAuth 2.1 | 兩期：先 API key bearer，後 OAuth 2.1（CIMD 優先，DCR fallback） | Blotato 兩種都有：Claude 類 client 用 OAuth，Cursor、ChatGPT 用 `blotato-api-key` header。MCP spec 2025-11-25 規定 PRM（RFC 9728）係 MUST，CIMD 係 SHOULD，DCR 由 SHOULD 降做 MAY，PKCE 要 S256。API key 版工作量係 M，OAuth 係 L。 |
| Webhook payload：fat vs thin | Thin | 同 hosted.py `audit()` 嘅 content-free 規則一致；Standard Webhooks spec 亦指出 thin payload 喺效能同 auditability 上較好。收到之後用 API key 攞細節，權限檢查自然生效。 |
| Webhook delivery 放入現有 /api/cron/worker vs 獨立 cron path | 獨立 /api/cron/deliveries（vercel.json 加一條 * * * * *） | 現有 route 已經行 worker.tick（20s）+ run_reminders + learning.sweep，function maxDuration 係 60s。Delivery 積壓唔可以拖慢 publish worker。 |
| Zapier／Make／n8n：即刻出官方 app vs 先用通用 webhook + REST | 先通用，後 n8n node，Zapier app 最後 | API v1 未穩定前出 app 會鎖死 schema；n8n community node 工作量 M，Zapier app 要審核，係 L。 |

## 點樣接入 codebase

前端（web/src 有平行 session 改緊，實作要按路徑 stage）：
- `web/src/config/nav-config.ts`：刪走 `Workspace` 同 `Account` 兩組；新開 `Voice` 組，放 Brand（`/app/workspace/brand`，access edit）同 Memory（`/app/workspace/memory`，access edit），URL 唔變；底部加 `Settings` → `/app/settings`，icon 用現有 `Icons.settings`（icons.tsx:143 已經有 `IconSettings`）。修正 Channels 同 Home 共用 `['h','h']` 嘅衝突。
- 新增 `web/src/config/settings-nav.ts`：三組 rail，沿用 `access` shape；過濾重用 `web/src/hooks/use-nav.ts`／`use-nav-groups.ts` 同 `web/src/lib/auth/access.tsx` 嘅 `checkAccess`。Cmd+K（`web/src/components/kbar/index.tsx`）同時讀 `settingsNav`，保留 `b b` → Usage & plan。
- 新增 `web/src/app/app/settings/layout.tsx` 同 `web/src/app/app/settings/[section]/page.tsx`，掛返現有 view：`web/src/features/account/profile-view.tsx`（連 `security-card.tsx`、`passkeys-card.tsx`、`preferences-card.tsx`）、`notifications-view.tsx`、`privacy-view.tsx`、`models-view.tsx`、`web/src/features/billing/billing-view.tsx`、`web/src/features/workspace/members-view.tsx`、`roles-view.tsx`、`audit-view.tsx`。Memory 用 `web/src/features/memory/memory-view.tsx`，唔搬。
- `web/next.config.ts`：新增 `async redirects()`（而家只有 rewrites）：`/app/account/:slug` → `/app/settings/:slug`（billing → usage），`/app/workspace/(members|roles|audit)` → `/app/settings/...`，先用 `permanent:false`。dev `rewrites()` 加 `/.well-known/:path*` → API origin。
- Developer section 由 `web/src/features/account/api-view.tsx` 拆出嚟，放入 `web/src/features/settings/developer/`：`api-keys-section.tsx`、`webhooks-section.tsx`、`agents-mcp-section.tsx`、`automation-apps-section.tsx`、`desktop-section.tsx`、`sources-section.tsx`，另加總覽 `/app/settings/api`。
- 資料層：`web/src/lib/api/hooks.ts`（`keys` 喺第 11 行）加 `useApiKeys`、`useCreateApiKey`、`useRotateApiKey`、`useRevokeApiKey`、`useWebhooks`、`useWebhookDeliveries`、`useWebhookEventCatalog`、`useSources`、`useTools`（`GET /api/tools` 已經有）。Types 加入 `web/src/lib/api/types.ts`；client 用 `web/src/lib/api/client.ts` 嘅 `ApiError`，step-up 403 時重用 `security-card.tsx` 嘅 re-auth 流程。
- UI：`ui/dialog.tsx`、`ui/alert-dialog.tsx`、`ui/input-group.tsx`、`ui/checkbox.tsx`、`ui/field.tsx`、`ui/table/data-table.tsx`（連 `data-table-pagination.tsx`、`data-table-faceted-filter.tsx`、`data-table-date-filter.tsx`）、`ui/empty.tsx`、`ui/skeleton.tsx`、`ui/badge.tsx`、`web/src/components/app/level-badge.tsx`。Motion：`components/motion/hold-action-button.tsx`（預設 holdDuration 1600ms）、`components/ui/success-check.tsx`、`components/motion/animated-badge.tsx`、`components/motion/number-ticker.tsx`（兩個都已經用 useReducedMotion）、`components/motion/tabs.tsx`；tokens 用 `web/src/styles/transitions.css`（`--duration-fast` 250ms、`--duration-quick` 150ms、`--duration-stagger` 40ms、`--distance-micro` 4px）。Page enter 沿用 `web/src/app/app/template.tsx`。
- Tour：`web/src/features/onboarding/tours.ts` 加 `settings-tips`、`api-tips`；`TourCtx` 同 `use-tour-context.ts` 加 `apiKeyCount`、`webhookCount`（`canManageConnections` 已經有）。

後端：
- `src/postriff_phase2/permissions.py`：`ACTION_CLASSES` 加 `api_key_create`、`api_key_rotate`、`api_key_revoke`、`webhook_create`、`webhook_update`、`webhook_delete`、`webhook_rotate_secret`、`source_add`、`source_remove` → `manage_connections`；`api_key_create`、`api_key_rotate`、`webhook_rotate_secret` 加入 `STEP_UP_ACTIONS`。新增 `TOKEN_SCOPES`（scope → class）、`NON_DELEGABLE`，以及 `Membership.for_token(scopes)`，回傳兩者交集。
- 新檔 `src/postriff_phase2/api_keys.py`：生成 token、HMAC-SHA256(pepper) 儲存（env `POSTRIFF_API_KEY_PEPPER`，加入 `web/.env.example` 同 `hosted_app.runtime_from_environment`）、驗證（join `pr_memberships` 同 `pr_profiles.deleted_at IS NULL`）、用 `hosted.py` 嘅 `throttle()` 做 rate limit、last-used 最多每 60 秒寫一次。
- `src/postriff_phase2/hosted_app.py`：跟 `/api/billing/webhook`（第 289 行）同 cron 嘅先例，喺 `self._origin()`（第 338 行）之前開 `/api/v1/*` 同 `/api/mcp` 分支；Bearer 以 `prk_` 開頭嘅 token 永遠唔會交俾 `_token()`／Supabase verify；唔回 CORS header。另開 `/api/cron/deliveries`（驗證同 cron_secret 一樣）。
- `vercel.json`：`crons` 加 `/api/cron/deliveries`；第二期 `rewrites` 加 `/.well-known/oauth-protected-resource(.*)`、`/.well-known/oauth-authorization-server` → `postriff_api`。
- 新檔 `src/postriff_phase2/webhooks.py`：event catalogue、`emit(cur, workspace_id, type, data)`、Standard Webhooks 簽名、SSRF 防護、按建立者權限過濾事件、`deliver_due(limit, budget_seconds=15)`。`emit` 喺以下地方同一個 cursor 呼叫：`hosted.py` 嘅 `audit()` call site（例如 member.left:565、member.removed:746）、`oauth.py`（channel.verified:244、channel.disconnected:264）、`audience.py`、`billing.py`、`learning_service.py`、`hosted_worker.py` 嘅 `complete()`／`on_verified`（job state），另外用 `repository.effects` 處理 `command()` 內嘅 state diff（review、approve）。
- 新檔 `src/postriff_phase2/public_api.py`：寫入類 endpoint 由 server 端讀最新 revision，撞 409 就喺 transaction 重試最多 3 次；要求 `Idempotency-Key`，傳去 `Ledger.reserve(idempotency_key=…)`。
- 新檔 `src/postriff_phase2/mcp_server.py`：Streamable HTTP；401 帶 `WWW-Authenticate`；tools 按 scope 過濾；`tools.isolation_status().publicInvokeEnabled` 係 False，registry tool 唔列出。
- Desktop（第二期）：`src/postriff_phase3/hosted.py` 同 `contracts.py` 已經有 enroll／pair，要補 hosted route。第 35 行檢查嘅係配對者（`device['actor']`）角色係咪 `('owner','editor')`，admin、approver 配對嘅裝置會失效，要同 RBAC 對齊。
- Sources：新檔 `src/postriff_phase2/sources.py`，重用 `research.py` 嘅 `host_of`、`skip_host`、`_http(limit=…)` 同 `source_policy.py`；經 Jina Reader 抽全文前要檢查 `research.allowed(state)`。
- Migration：`migrations/postriff/013_api_integrations.sql`，並同步處理 `hosted-precheck.sql` 或者 hosted 部署 script；`pr_audit_events` 加 `actor_kind`、`actor_ref`。Notifications 寫入 `pr_notifications`（008）；webhook secret 放 `pr_encrypted_credentials`（006）；Desktop 沿用 `pr_runtime`（003）。

## Design spec

# 1. Settings 資訊架構

## 1.1 主 sidebar（改動後，13 項）
Create：Home · Overview · Ideas · Calendar · Pipeline · Library
Distribute：Channels · Queue
Grow：Analytics · Inbox
Voice：Brand · Memory（URL 保持 /app/workspace/*，權限照舊 edit）
（底部）Settings
Shortcut：Channels 由 `h h` 改做唔同 Home 撞嘅組合（例如 `g c`，最後由 James 決定）。

## 1.2 Settings 左 rail
**你（Personal）**：所有成員都見到
1. Profile & security：`/app/settings/profile`
2. Notifications：`/app/settings/notifications`
3. Preferences：暫時留喺 Profile 入面（`preferences-card.tsx`）

**Workspace**
4. General：需要 `edit` 先改得，其他人只讀
5. Members：需要 `manage_members`
6. Roles & permissions：需要 `manage_members`
7. Models & providers：需要 `edit`
8. Usage & plan：需要 `owner`
9. Privacy & data：個人部分所有人見到，workspace export／delete 限 owner
10. Audit log：需要 `role: admin`

**Developer**：需要 `manage_connections`；其他人見到但係 disabled，附「Ask an owner or admin」
11. Overview `/app/settings/api` · 12. API keys · 13. Webhooks · 14. Agents (MCP) · 15. Automation apps · 16. Desktop companion · 17. Sources

手機（<768px）：`/app/settings` 係清單頁，撳入去係詳情頁，頂部有返回掣。

# 2. API & integrations

## 2.0 總覽 `/app/settings/api`
- 六張 summary card，全部讀真 API 值。以下只係格式範本，唔可以寫死：「API keys：{active} active · {expiringSoon} expiring within 14 days」、「Webhooks：{endpoints} endpoints · last delivery {relative} · {failing} failing」。某項數值係 0，就顯示真嘅 0。
- API 出錯時嗰張 card 顯示「Unavailable」加 retry，唔可以變 0。載入中用 `ui/skeleton.tsx`，唔加 loading 文案。
- 頂部原則 callout：「API、agents 同 automations 可以讀資料、寫 draft、提出 schedule。發佈、回覆、連接 channel、收費、刪除，永遠要有人喺 PostRiff 入面批准。」
- Connected providers 改為 link 去 Channels，並顯示每個 capability 嘅 Direct／Assisted／Unsupported 計數，唔可以寫「N connected ✓」。

## 2.1 API keys
**權限**：`manage_connections` 先可以建立、rotate、revoke；其他成員只讀（名、prefix、建立者、scopes、last used）。
**格式**：`prk_live_` + 43 字 base62 secret + 6 字 crc32 checksum；dev 環境用 `prk_test_`。資料庫只存 `HMAC-SHA256(pepper, secret)`；UI 只顯示頭 12 字。
**建立 Dialog**：
1. 名稱（必填，≤60 字）。
2. Scopes 分組 checkbox：讀取（`workspace:read`、`channels:read`、`analytics:read`、`usage:read`）；寫入 draft（`ideas:write`、`drafts:write`、`media:write`、`sources:write`）；排期提案（`schedule:propose`）。灰色、揀唔到：Publish/Approve、Reply、Moderate、Connect channels、Manage members、Billing，附「These always need a person in PostRiff.」。預設只剔 `workspace:read`、`channels:read`；冇「Full access」。
3. Expiry：7／30／90（預設）／180／365 日，冇「Never」。
4. 提交時做 step-up（600 秒），已開 MFA 要 aal2。
5. 一次性顯示：AlertDialog 顯示完整 key 同 copy 掣（`success-check.tsx`），附「You won't see this key again」，要剔「I've stored it」先關得。開用 `--duration-fast`（250ms）、收用 `--duration-quick`（150ms）、`--scale-large` 0.96。
**列表**（`ui/table/data-table.tsx`）：名稱 · prefix · scopes（超過 3 個摺埋）· 建立者 · 建立日期 · Expires（≤14 日轉 amber）· Last used（從未用過寫「Never used」）· Requests (7d)（讀 `pr_api_key_usage_daily`，查詢失敗寫「Unavailable」）· 操作：Rotate（舊 key 保留 24 小時 grace，標「Rotating」）、Revoke（`hold-action-button.tsx` 預設 1600ms，要 step-up）。
**狀態**：active／expiring／expired／revoked／rotating。
**Empty state**：「No API keys yet」／「Create a key to let your own scripts, an automation tool or an AI agent read this workspace and draft posts. Publishing still waits for your approval.」／「Create API key」。
**授權語義**：每次 request 用 `Membership(建立者當刻 role + flags).for_token(scopes).allows(class)` 計權限。建立者 membership 唔再 active、或者 `pr_profiles.deleted_at` 有值，key 即時失效，寫 audit `api_key.revoked` {reason:'creator_left'}。Membership 快取最多 60 秒，要寫入文件。
**Rate limits**（`throttle()`）：每條 key 每分鐘 60 次；write 每分鐘 20 次；每個 workspace 每小時合共 1000 次。超過回 429，帶 `Retry-After`、`RateLimit-Limit`、`RateLimit-Remaining`。
**寫入語義**：POST／PATCH 必須帶 `Idempotency-Key`（同一個 key 24 小時內重送就回同一個結果）。Server 端讀最新 revision，撞 409 重試最多 3 次，仍然失敗就回 409 同 `Retry-After: 1`。付費生成行 `Ledger.reserve`；entitlement 用完回 402（沿用 billing.py 文案），但 idea 或 draft 輸入照樣儲存，response 帶 `generation: "skipped_allowance"`。
**唔 block 創作**：preflight 問題同缺事實只放入 `reminders[]`，並喺 draft 上面顯示，唔會回 4xx；會 block 嘅只有認證、scope、rate limit 同 entitlement。
**CORS**：`/api/v1` 同 `/api/mcp` 唔回 `Access-Control-Allow-Origin`，文件寫明 key 唔可以放入前端網頁。
**通知**：到期前 7 日同 1 日，發俾建立者同 owner（`pr_notifications`）；90 日冇用過就標「Unused for 90 days」，唔會自動刪。
**Audit**：`api_key.created` {keyId, prefix, scopes, expiresInDays}、`api_key.rotated`、`api_key.revoked` {reason}、`api_key.expired`。`pr_audit_events` 加 `actor_kind`（person／api_key／mcp_client／device／system）同 `actor_ref`；由 key 觸發嘅 mutation 記 actor_kind=api_key、actor_ref=keyId、actor=建立者。

## 2.2 Webhooks
**權限**：`manage_connections`；每個 workspace 最多 10 個 endpoint。
**建立**：URL 只收 https；server 端拒絕 localhost、私有、保留同 metadata IP，每次送出都重新解析 DNS，並檢查連線 IP，唔跟 redirect。另有描述同 events 分組 checkbox。建立後一次性顯示 `whsec_` + base64 secret（每個 endpoint 獨立）。Rotate 後 24 小時內，`webhook-signature` 同時帶新舊兩個 `v1,` 簽名，以空格分隔（Standard Webhooks 規格）。
**Headers**：`webhook-id`（retry 時唔變）、`webhook-timestamp`（unix 秒）、`webhook-signature: v1,<base64(HMAC-SHA256(secret, id.timestamp.body))>`。文件建議 receiver 拒絕相差超過 5 分鐘嘅 timestamp（慣例，spec 冇硬性規定），並用 constant-time 比較。Body ≤64KB：`{type, timestamp, workspaceId, data:{ids and counts}}`。
**權限過濾（新增）**：每次送出前，檢查建立者當刻 membership：`inbox.*`、`reply.*` 要 `reply`；`member.*` 要 `manage_members`；`billing.*`、`usage.*` 要 `owner`；其他要 `read`。唔夠權限嘅事件唔送，delivery log 記「skipped: creator lacks permission」。
**送出同 retry**：獨立 cron `/api/cron/deliveries`（vercel.json `* * * * *`），每 tick `deliver_due(limit=200, budget_seconds=15)`。UI 唔承諾延遲，只寫「Checked every minute」；有數據就顯示 delivery log 過去 24 小時嘅真 p50 延遲，冇數據就唔顯示。回 2xx 而且 10 秒內完成先算成功。Retry 受 cron 分鐘粒度限制，參考 spec 建議改為：+1m、+5m、+30m、+2h、+5h、+10h、+14h、+20h、+24h，最多 10 次，之後標 abandoned。連續失敗超過 72 小時或者 50 次，就 `auto_disabled`，通知 owner 同建立者，audit `webhook.disabled`。
**Delivery log**（data-table）：時間、type、attempt n/10、HTTP status、duration、下次 retry。狀態用 `animated-badge.tsx`，只喺 poll 到真狀態改變時轉換。可以「Redeliver」（同一個 webhook-id）。保留 30 日，只存 response 頭 256 bytes，標「truncated」。
**Test**：「Send test event」真係送 `webhook.test`，結果即刻入 log。
**Empty state**：「No webhooks yet」／「Get a signed HTTP call when a post is scheduled, published or needs attention, so a chat tool, a spreadsheet or an automation can react.」／「Add endpoint」。
**Event catalogue**（`emit()` 喺同一個 cursor 同 transaction 寫入 `pr_webhook_outbox`）：
- 發佈（`hosted_worker.py` 嘅 `complete()`）：`post.scheduled`、`post.published`（verified）、`post.failed`、`post.held`、`post.uncertain`、`post.canceled`。Data：jobId、variantId、channelId、platform、scheduledAt、providerReference。
- 審批（`command()` effects，比較 review state）：`review.requested`、`review.approved`
- 內容：`draft.created`、`media.uploaded`
- Channels（`oauth.py` audit 旁 emit）：`channel.connected`、`channel.verified`、`channel.disconnected`、`channel.capability_changed`。所有 channel 事件都帶 `capabilities: {publish: 'direct'|'assisted'|'unsupported', …}`，唔可以單靠「connected」代表 ready。
- Inbox（`audience.py`）：`inbox.thread_received`、`reply.approved`
- 成員（`hosted.py` audit 旁 emit）：`member.joined`、`member.updated`、`member.removed`、`member.left`
- Memory（`learning_service.py`）：`memory.proposal_created`、`memory.proposal_decided`
- Usage／billing（`billing.py`）：`usage.allowance_low`、`usage.budget_warn`、`billing.subscription_changed`、`billing.payment_failed`
- 系統：`webhook.test`
- 刻意唔送：session、MFA、security events。
**Audit**：`webhook.created` {endpointId, host, events}、`webhook.updated`、`webhook.deleted`、`webhook.secret_rotated`、`webhook.disabled` {reason}、`webhook.enabled`。

## 2.3 Agents (MCP)
**Endpoint**：`https://<host>/api/mcp`（Streamable HTTP）。頁面有 copy 掣，加三個 snippet tab：Claude Code（`claude mcp add --transport http postriff <url> --header "Authorization: Bearer prk_…"`）、Cursor（`mcp.json`）、通用 MCP client。
**第一期**：API key bearer。缺 key 或 key 無效：回 401 + `WWW-Authenticate: Bearer`（OAuth 上線後加 `resource_metadata`）。Scope 不足：回 403 + `WWW-Authenticate: Bearer error="insufficient_scope", scope="…"`。冇權限嘅 tool 唔出現喺 `tools/list`。
**第二期（MCP spec 2025-11-25）**：
- Protected Resource Metadata（RFC 9728，MUST）：`/.well-known/oauth-protected-resource/api/mcp` 同 root 兩個位置都提供，包括 `authorization_servers`、`scopes_supported`（只列最少 scope）。
- AS metadata（RFC 8414）：`/.well-known/oauth-authorization-server`，必須有 `code_challenge_methods_supported: ["S256"]` 同 `client_id_metadata_document_supported: true`。
- Client 註冊：以 Client ID Metadata Documents 為主（fetch client_id URL 時用同 webhook 一樣嘅 SSRF 防護）；DCR（RFC 7591）只做 fallback。Consent 畫面清楚顯示 redirect URI hostname；只有 localhost redirect 嘅 client 要加警告。
- Token：短命 access token；public client 嘅 refresh token 要 rotate；按 RFC 8707 `resource` 綁定 `/api/mcp`，並驗證 audience；唔可以將收到嘅 token 轉傳落游。
- `vercel.json` rewrites 加 `/.well-known/*` → `postriff_api`，因為而家只有 `/api/*` 會去 Python。
- Consent 文案：「This agent can draft and propose schedules. It cannot publish or reply.」
**Tools**：`workspace.get`、`channels.list`（附 capability matrix）、`drafts.list`、`drafts.create`、`drafts.update`、`schedule.propose`（回傳 reviewId 同 Queue deep link）、`jobs.get`、`analytics.posts`、`usage.get`、`memory.read`、`memory.propose`。`tools.catalog()` 入面嘅 registry tools，喺 `publicInvokeEnabled` 仍然係 false 時唔會出現喺 `tools/list`；UI 讀 `GET /api/tools` 嘅真值，顯示「Listed · not runnable on this deployment」。
**Empty state**：「No agent connected」／「Connect an MCP client to draft and plan posts from where you already work.」
**Audit**：`mcp.client_authorized`、`mcp.client_revoked`、`mcp.tool_denied`（每條 key 每小時最多記 1 次）。

## 2.4 Automation apps
- 三張 card（Zapier／Make／n8n），第一期都顯示「No official app yet · use Webhooks + API key」，唔可以寫「Coming soon ✓」。
- 每張有 3 步指引（Trigger 用 Webhooks、Action 用 HTTP request 打 `/api/v1/*`），附 copy 得嘅 URL、`Authorization` 同 `Idempotency-Key` header 範例。
- 第二期出 n8n community node：版本讀 npm registry 真值，讀唔到就顯示「Unavailable」，唔 fallback 做寫死嘅版本號。
- 範例文案保持通用：「When a post is published, add a row to a spreadsheet」、「When a feed has a new item, start an idea」。

## 2.5 Desktop companion
- 現況：Alert「Hosted pairing is not available yet. Local channels publish from the desktop app on the same computer.」；Local channel 數量讀 `web/src/config/channels.ts` 嘅 `localChannels`。
- 開通後：Devices 表（名稱、OS、version、paired by、paired at、last seen，超過 5 分鐘標 Offline；reported agents 用 `level-badge.tsx`）。「Pair a computer」會顯示 16 字 code，倒數讀 `expiresAt`（300 秒）；過期後顯示「Expired · Generate new code」。每人最多 5 個有效 enrollment，429 時直接顯示 server 文案。Unpair 用 hold（1600ms）+ step-up。
- 權限：pair／unpair 要 `manage_connections`，或者成員操作自己嘅裝置；修正 `src/postriff_phase3/hosted.py:35` 對配對者角色 `('owner','editor')` 嘅限制。
- Audit：`device.paired`、`device.unpaired`、`device.renamed`。

## 2.6 Sources（RSS / feeds）
- 新增：貼 URL，server fetch 一次（SSRF 防護、2MB 上限），偵測 RSS／Atom／JSON Feed，預覽最新 3 條真 item，確認後先儲存。失敗照實顯示原因。
- 列表：標題、host、頻率（1／6／24 小時）、last checked、last result、7 日新 item 數、狀態。
- 行為：新 item 入 Ideas，標「From sources」，唔會自動寫 draft 或者發佈。直接 fetch feed 唔需要 research_egress。要經 Jina Reader 抽全文，先要 `research.allowed(state)`；未開就照樣收 item（只有標題、摘要、link），唔抽全文，並提醒「Full-article reading uses an outside reader. An owner can turn it on under Memory → Web research.」。
- Fetch 喺 `/api/cron/deliveries` 行，`fetch_due(limit=20, budget_seconds=10)`。
- 限制：每個 workspace 最多 50 個 feed。
- Audit：`source.added` {host}、`source.removed`、`source.paused`。

## 2.7 Migration `migrations/postriff/013_api_integrations.sql`
所有 table 開 RLS，只准 service role 存取；同步更新 `tests/phase2/rls.sql` 同 hosted 部署 script。
- `pr_api_keys(id, workspace_id, created_by, name, prefix unique, secret_hash bytea, scopes text[], expires_at not null, last_used_at, last_used_client, rotated_from, grace_until, revoked_at, revoked_by, revoke_reason, created_at)`
- `pr_api_idempotency(key_id, idem_key, response_hash, response jsonb, created_at, pk(key_id, idem_key))`：保留 24 小時。
- `pr_api_key_usage_daily(key_id, day, requests, denied, rate_limited, pk(key_id, day))`
- `pr_webhook_endpoints(id, workspace_id, created_by, url, description, events text[], secret_ref → pr_encrypted_credentials, previous_secret_ref, previous_until, status check(enabled|disabled|auto_disabled), failing_since, consecutive_failures, disabled_reason, created_at, updated_at)`
- `pr_webhook_outbox(id uuid, workspace_id, type, occurred_at, data jsonb, required_class text)`
- `pr_webhook_deliveries(id, endpoint_id, event_id, attempt smallint, status, response_status, duration_ms, response_excerpt, next_attempt_at, created_at)`，index `(status, next_attempt_at)`
- `pr_sources(...)`、`pr_source_items(...)`（欄位同初稿一樣）
- `alter table pr_audit_events add column actor_kind text not null default 'person', add column actor_ref text`
- `pr_mcp_clients`、`pr_mcp_tokens`：第二期（014），包括 `client_id_url`（CIMD）同 `resource`。

**Routes**（`hosted_app.py`）：
- 管理（經 session，行 `_origin`）：`GET/POST /api/workspaces/{w}/api-keys`、`POST …/api-keys/{id}/rotate`、`DELETE …/api-keys/{id}`、`GET …/api-keys/usage?days=30`；`GET /api/webhook-events`；`GET/POST /api/workspaces/{w}/webhooks`、`PATCH/DELETE …/webhooks/{id}`、`POST …/webhooks/{id}/test`、`POST …/webhooks/{id}/rotate-secret`、`GET …/webhooks/{id}/deliveries?cursor=`、`POST …/webhooks/deliveries/{d}/redeliver`；`GET/POST /api/workspaces/{w}/sources`、`POST …/sources/preview`、`PATCH/DELETE …/sources/{id}`。
- Public（喺 `_origin` 之前處理，只接受 `prk_` bearer）：`/api/v1/workspace`、`/channels`、`/ideas`、`/drafts[/{id}]`、`/media`、`/schedule-proposals`、`/jobs/{id}`、`/analytics/posts`、`/usage`、`/openapi.json`；`POST/GET/DELETE /api/mcp`。
- Cron：`GET /api/cron/deliveries`（cron_secret），回傳真計數 `{webhooks:{sent, failed, abandoned, skipped}, sources:{fetched, failed}}`。
- 第二期：`/.well-known/oauth-protected-resource[/api/mcp]`、`/.well-known/oauth-authorization-server`、`/api/oauth2/authorize|token|register|revoke`、`GET/DELETE /api/workspaces/{w}/mcp-clients[/{id}]`；Desktop routes。
**驗證流程**：用 prefix 查 key → constant-time 比較 hash → 檢查未過期、未撤銷 → 建立者 membership active 而且 profile 未刪 → `Membership.for_token(scopes).allows(class)`。跨 workspace 或者 key 唔存在，一律回 401「Invalid API key.」。

# 3. 動效（docs/postriff-motion-system.md §5）
- Key dialog：開 `--duration-fast`（250ms），收 `--duration-quick`（150ms），scale 用 `--scale-large`；copy 完成用 `success-check.tsx`。
- Revoke、刪 endpoint、unpair：`hold-action-button.tsx` 預設 1600ms，唔改。
- Delivery log 新 row：只喺真 poll 帶嚟新 row 時先插入，opacity + translateY `--distance-micro`（4px），stagger `--duration-stagger`（40ms），合共 ≤300ms（超過 7 行就唔再 stagger）。
- 計數用 `number-ticker.tsx`，只喺值真正改變時滾動，首次載入唔滾。
- Reduced motion：現有元件已經處理；新加嘅 motion 要用 `useReducedMotion()`，只郁 transform／opacity。
- Settings rail 切頁沿用 `web/src/app/app/template.tsx`。

# 4. 其他 Settings 頁下一步
**Notifications**：做「事件 × 渠道」矩陣（review requested、post published、failed/held/uncertain、inbox thread、allowance low、API key expiring、webhook auto-disabled、member joined × In-app／Email）。「Last sent」讀 `pr_notifications`，未發過寫「Never」。Billing 同 security 標「Required for owners」。
**Models & providers**：Desktop 狀態 card 讀真 last seen，未開通就照實寫。分 Local CLI／Bring your own key／PostRiff managed；本月用量讀 `Ledger.usage_view`。Probe 失效時提醒改用其他 route，唔可以令 run fail。
**Privacy & data**：加「Where your data goes」清單，列出 channels（逐個 capability）、webhook host、API keys 同 MCP clients、`memory_egress`、`research_egress`（Exa、Jina）、model routes。加 data request 歷史（`GET /api/workspaces/{w}/data-requests`）同各類保留期。
**Usage & plan**：Ledger 按 dimension 分，來源分 App／API key（逐條）／MCP client／Desktop；budget 照 `CANDIDATE_BUDGETS` 標「candidate」；reset 倒數讀 `resetsAt`。
**Roles**：`permission-matrix.tsx` 加「Can be delegated to API keys」欄；改角色前預覽影響，例如「This member created {n} API keys; they will lose drafts:write」，n 讀真值。
**Audit log**：用 data-table 加篩選（kind、actor_kind、日期）、cursor 分頁、owner 可以 export CSV（audit `audit.exported`），加入 api_key.*、webhook.*、mcp.*、device.*、source.*。

# 5. Tour／onboarding
- Welcome tour 唔加 Settings 步驟，只喺 `help` 步驟加一句「Settings holds your profile, team and integrations.」。Brand、Memory URL 唔變，原有步驟唔使改。
- `settings-tips`（`/app/settings`）3 步；第 3 步 `when: ctx.canManageConnections`。
- `api-tips`（`/app/settings/api`）4 步：`api-principle` → `api-keys`（讀真 `apiKeyCount`：0 時「Start with a read-only key」，>0 時「You have {n} active keys; check the ones near expiry」；讀取失敗就略過呢句）→ `webhooks` → `agents`。
- 文案唔提任何品牌、行業或者 James 嘅例子。
- 第一次入 Developer 組時，rail 項目旁邊顯示一次性小圓點（localStorage，try/catch），唔自動彈 tour。

## Implementation plan

1. **Settings 殼同導航：settings-nav、settings layout（左 rail + 手機 list→detail）；Brand／Memory 移入 Voice 組（URL 唔變）；next.config.ts 新增 redirects()；Cmd+K 讀 settingsNav；修正 h h shortcut 衝突。**（effort M）  
   檔案：`web/src/config/nav-config.ts, web/src/config/settings-nav.ts（新）, web/src/app/app/settings/layout.tsx（新）, web/src/app/app/settings/[section]/page.tsx（新）, web/next.config.ts, web/src/components/kbar/index.tsx, web/src/hooks/use-nav-groups.ts`
2. **RBAC 延伸：TOKEN_SCOPES、NON_DELEGABLE、Membership.for_token、新 ACTION_CLASSES 同 STEP_UP_ACTIONS；unit test 證明 token 永遠唔可以 approve、reply、connect。**（effort S）  
   檔案：`src/postriff_phase2/permissions.py, tests/test_postriff_phase2_hosted.py`
3. **Migration 013：api keys、idempotency、usage、webhook endpoints／outbox／deliveries、sources、audit actor_kind／actor_ref，連 RLS；同步 hosted 部署 script。**（effort M）  
   檔案：`migrations/postriff/013_api_integrations.sql, migrations/postriff/hosted-precheck.sql, tests/phase2/rls.sql, tests/phase2/postgres_channels.py`
4. **API keys 後端：生成、HMAC pepper（env）、喺 _origin 之前嘅 prk_ bearer 分支（唔落 Supabase verify、冇 CORS）、throttle、usage、creator／deleted_at 檢查、管理 routes（step-up + aal2）、audit actor_kind、到期通知。**（effort M）  
   檔案：`src/postriff_phase2/api_keys.py（新）, src/postriff_phase2/hosted_app.py, src/postriff_phase2/hosted.py, src/postriff_phase2/email.py, web/.env.example`
5. **API keys UI：data-table 列表、建立 dialog、一次性顯示（250／150ms tokens）、rotate、hold-to-revoke（1600ms）、empty state、hooks 同 types。**（effort M）  
   檔案：`web/src/features/settings/developer/api-keys-section.tsx（新）, web/src/lib/api/hooks.ts, web/src/lib/api/types.ts, web/src/lib/api/client.ts`
6. **Public API v1：讀取 endpoints、idea／draft 寫入（server 端 revision retry、Idempotency-Key、reminders[] 唔 block、402 時保留輸入）、schedule-proposals、openapi.json。**（effort L）  
   檔案：`src/postriff_phase2/public_api.py（新）, src/postriff_phase2/hosted_app.py, src/postriff_phase2/hosted.py, src/postriff_phase2/ideas.py, src/postriff_phase2/billing.py`
7. **Webhook emitter：emit() helper，喺 audit call site（hosted.py、oauth.py、audience.py、billing.py、learning_service.py）同一個 cursor 呼叫；job 事件接 hosted_worker complete()；review 事件用 command() effects；每個事件記 required_class；PG test 驗證冇漏、冇重複。**（effort L）  
   檔案：`src/postriff_phase2/webhooks.py（新）, src/postriff_phase2/hosted.py, src/postriff_phase2/oauth.py, src/postriff_phase2/audience.py, src/postriff_phase2/hosted_worker.py, src/postriff_phase2/billing.py, src/postriff_phase2/learning_service.py, tests/phase2/postgres_channels.py`
8. **Webhook delivery：獨立 cron /api/cron/deliveries（15s 預算）、Standard Webhooks 簽名（rotation 雙簽名）、送出前權限過濾、SSRF 防護、retry 表、auto-disable、redeliver、test；管理 routes 同 delivery log UI。**（effort L）  
   檔案：`src/postriff_phase2/webhooks.py, src/postriff_phase2/hosted_app.py, vercel.json, web/src/features/settings/developer/webhooks-section.tsx（新）, web/src/lib/api/hooks.ts`
9. **MCP 第一期：/api/mcp Streamable HTTP、API key bearer、401／403 WWW-Authenticate、按 scope 過濾 tools、registry tools 唔列出；Agents 頁（URL、snippets、讀真 /api/tools）。**（effort M）  
   檔案：`src/postriff_phase2/mcp_server.py（新）, src/postriff_phase2/tools.py, src/postriff_phase2/hosted_app.py, web/src/features/settings/developer/agents-mcp-section.tsx（新）`
10. **總覽頁、Automation apps card、Desktop「未開放」頁；api-view.tsx 改做總覽，Connected providers 改為按 capability 計數。**（effort S）  
   檔案：`web/src/features/account/api-view.tsx, web/src/features/settings/developer/automation-apps-section.tsx（新）, web/src/features/settings/developer/desktop-section.tsx（新）`
11. **Sources／RSS：preview、新增、喺 /api/cron/deliveries fetch（10s 預算）、ETag、item 入 Ideas、SSRF 同 byte limit；Jina 全文抽取跟 research.allowed(state)，冇 consent 就提醒，唔 block。**（effort M）  
   檔案：`src/postriff_phase2/sources.py（新）, src/postriff_phase2/research.py, src/postriff_phase2/source_policy.py, src/postriff_phase2/hosted_app.py, web/src/features/settings/developer/sources-section.tsx（新）`
12. **Tours：settings-tips、api-tips，TourCtx 加 apiKeyCount、webhookCount，加 data-tour 屬性，welcome tour help 步驟加一句。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts, web/src/features/onboarding/use-tour-context.ts`
13. **其他 Settings 頁增強：Notifications 矩陣、Privacy「Where your data goes」、Usage 按來源分、Roles delegable 欄、Audit 篩選（actor_kind）、cursor、export。**（effort L）  
   檔案：`web/src/features/account/notifications-view.tsx, web/src/features/account/privacy-view.tsx, web/src/features/billing/billing-view.tsx, web/src/features/workspace/permission-matrix.tsx, web/src/features/workspace/audit-view.tsx, src/postriff_phase2/hosted.py`
14. **第二期：MCP OAuth 2.1（PRM 兩個位置、AS metadata 帶 S256 同 CIMD flag、CIMD 優先 DCR fallback、resource／audience 綁定、refresh rotation、consent 畫面、vercel.json /.well-known rewrites）；Desktop hosted pairing（視乎 Anthropic／OpenAI 書面答覆）同 phase3 角色修正；n8n community node；最後先做 Zapier app。**（effort L）  
   檔案：`src/postriff_phase2/mcp_oauth.py（新）, migrations/postriff/014_mcp_oauth.sql（新）, vercel.json, web/next.config.ts, src/postriff_phase3/hosted.py, desktop/main.cjs, 獨立 repo：n8n-nodes-postriff`

## Risks

- 競爭壓力：Blotato（`blotato_create_post`）、Buffer、Postiz 嘅 API／MCP 都可以直接發佈；PostRiff 第一期唔開 publish scope，要 James 拍板將來開唔開，同埋開嘅條件。
- Cron 預算：60 秒 function 入面已經有 publish worker、reminders 同 learning sweep。Delivery 同 feed fetch 分開 cron 之後，仍然受每分鐘一次限制，量大時會積壓，要監察 backlog；長遠可能要 queue 或者獨立 worker。
- Event 漏送：mutation 分散喺 command()、oauth.py、audience.py、hosted.py 直接 SQL，任何新 audit call site 冇配 emit() 就會漏 event。要加 test：列出所有 audit kind，逐個對照 catalogue。
- Webhook 變 RBAC 側門：送出前唔重新檢查建立者權限，manage_connections 嘅人就可以收到 inbox、成員、billing 資料；過濾邏輯一定要有 test。
- Revision 衝突：API 寫入同 app 用戶共用 workspace state JSON 同 revision lock，高頻 automation 會令 app 用戶成日見到「Workspace changed; reload」；server 端 retry 可以減少，但要監察 409 比率。
- SSRF：webhook、RSS，同第二期 CIMD fetch client_id URL，都係 server 端向用戶提供嘅 URL 發 request，要每次解析 DNS、檢查連線 IP、封鎖私有／保留／metadata IP、唔跟 redirect、限大小同時間。
- Origin 分支：`prk_` bearer 分支一定要喺 `_origin` 之前、獨立處理，而且唔可以令 session token 路徑放寬；`_token()` 只檢查長度，要明確拒絕 `prk_` 前綴。
- Token 洩漏：prefix + checksum 方便 secret scanning，但要另外申請 GitHub secret scanning partner program；加入之前只能靠 expiry、最小 scope、last-used 異常提示同冇 CORS。
- 權限漂移：membership 快取 60 秒，被移除嘅成員嘅 key 最多仲有 60 秒有效，要寫入文件。
- MCP spec 仲喺度變：2025-06-18 到 2025-11-25 已經將 DCR 由 SHOULD 降做 MAY，加咗 CIMD；第二期開工前要再核對最新版本，同埋 Claude／ChatGPT connector 嘅審核要求。
- tools.py isolation 未 qualified（publicInvokeEnabled False）：MCP 唔可以為咗 demo 繞過佢。
- Desktop relay 取決於 Anthropic／OpenAI 嘅書面答覆（docs/postriff-mobile-model-access.md P0）；phase3/hosted.py:35 嘅角色限制要先確認有冇刻意原因先改。
- 平行 session：web/src 有其他 session 改緊 nav-config、kbar、tours，commit 要按路徑 stage；Brand／Memory 保留原 URL 可以減少衝突。
- Hosted migration：013 如果冇同步入 hosted 部署 script，production 會缺 table，API key 功能一上線就 500。

## Sources

- /Users/ouxianxing/Documents/James-Au-Studio/web/src/config/nav-config.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/lib/auth/access.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/hooks/use-nav.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/icons.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/next.config.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/styles/transitions.css
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/motion/hold-action-button.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/ui/table/data-table.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/account/api-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/memory/memory-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/onboarding/tours.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/package.json
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/permissions.py
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/tools.py
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/hosted_app.py（_token:184、_origin:209、billing webhook:289、/api/tools:313、cron worker:326、_origin call:338）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/hosted.py（throttle:77、audit:91、effects:103/146、assert_fresh:117、command:132、member.left:565、member.removed:746、_aal:674）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/oauth.py（channel.verified:244、channel.disconnected:264）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/hosted_worker.py（on_verified:32、complete:92、tick max_seconds:154）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/billing.py（CANDIDATE_BUDGETS、reserve、usage_view）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/research.py（research_egress consent:70-100）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase3/contracts.py（enroll:132-136）
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase3/hosted.py:35
- /Users/ouxianxing/Documents/James-Au-Studio/desktop/main.cjs:52
- /Users/ouxianxing/Documents/James-Au-Studio/vercel.json（rewrites 只轉 /api/*、maxDuration 60、cron * * * * *）
- /Users/ouxianxing/Documents/James-Au-Studio/migrations/postriff/（001–012、hosted-004-008.sql、hosted-precheck.sql）
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-competitive-research-20260916.md（5. Approval-first agent，約第 211 行）
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-motion-system.md §5
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-consumer-saas-redesign.md §1.1
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-agent-chat-design.md §8.4、§8.6
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-mobile-model-access.md（P0、P2）
- https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md（已重新 fetch）
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization（已重新 fetch）
- https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization（已重新 fetch，用嚟比較 DCR 由 SHOULD 變 MAY）
- https://help.blotato.com/api/mcp/setup（已重新 fetch）
- https://docs.postiz.com/public-api/introduction
- https://github.com/gitroomhq/postiz-n8n
- https://support.typefully.com/en/articles/13128440-typefully-mcp-server
- https://developers.buffer.com/guides/integrations/mcp.html
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- https://linear.app/docs/api-and-webhooks

## 覆核記錄

- 改正：Sidebar 而家有 20 項，改完之後大約 11 項 → 改做「由 21 項減到 13 項」。
- 改正：過濾邏輯喺 @/hooks/use-nav 同 web/src/lib/auth/access.ts 嘅 checkAccess → 路徑改做 web/src/lib/auth/access.tsx，並提埋 use-nav-groups.ts。
- 改正：一次性 key dialog 打開 220ms、關閉 150ms，用 transitions.css tokens → 改用 --duration-fast 250ms 開、--duration-quick 150ms 收。
- 改正：Revoke 用 hold-action-button 撳住 1 秒 → 沿用預設 1600ms，唔另外設。
- 改正：Webhook delivery 喺 /api/cron/worker 行，budget_seconds=40 → webhooks 同 sources 分開另一條 cron path（例如 /api/cron/deliveries），或者喺原 route 設硬上限（webhooks ≤15s、sources ≤10s），而且要喺 worker.tick 之後先行。
- 改正：/.well-known/oauth-protected-resource 同 oauth-authorization-server 由 hosted_app.py 提供 → vercel.json 加 `/.well-known/oauth-protected-resource(.*)` 同 `/.well-known/oauth-authorization-server` rewrite 去 postriff_api；next.config.ts 嘅 dev rewrite 亦要加。
- 改正：Pair code 係 16 字，300 秒過期，rate limit 5 次／5 分鐘 → 改寫做「每人最多 5 個有效 enrollment、配對嘗試 5 分鐘 window」，UI 直接顯示 server 嘅 429 文案。
- 改正：competitive-research §214 講 approval-first agent → 改做「§『5. Approval-first agent』（約第 211 行）」。
- 改正：MCP 第二期：OAuth 2.1 + PKCE + RFC 9728 + RFC 8414 + DCR + RFC 8707 → 第二期改為 PRM（兩個 well-known 位置）+ AS metadata（有 code_challenge_methods_supported、client_id_metadata_document_supported）+ CIMD 優先，DCR 只作 fallback；另外加 WWW-Authenticate 同 insufficient_scope 處理。第一期 API key 模式亦要喺 401 回標準 header。
- 補上遺漏：Cron 時間預算：/api/cron/worker 已經行 worker.tick（20s）+ reminders + learning.sweep，maxDuration 60s；webhooks 40s 會超時，要分開 cron path 或者設硬上限。
- 補上遺漏：Vercel 路由：/.well-known/* 唔會去 Python service，要改 vercel.json rewrites 同 next.config.ts 嘅 dev rewrite。
- 補上遺漏：Event 來源覆蓋：effects 只喺 command() 行，oauth.py、成員操作、audience.py 自己寫 audit，唔會觸發 effects；要喺 audit call site 同一個 cursor emit，job 事件就接 hosted_worker 嘅 complete()／on_verified。
- 補上遺漏：Revision 409 同 idempotency：workspace state JSON 有 revision lock，API 寫入要 server 端 retry，並要求 Idempotency-Key（Ledger.reserve 本身要 idempotency_key）。
- 補上遺漏：Audit actor schema：pr_audit_events.actor 係 uuid，要加 `actor_kind`（person／api_key／mcp_client／device／system）同 `actor_ref`，migration 013 要 alter。
- 補上遺漏：Webhook 資料權限：endpoint 由有 manage_connections 嘅人建立，但 inbox.*、member.*、billing.* 事件需要建立者喺送出時仍然有對應權限（reply／manage_members／owner）；每次送出前重新檢查，否則 webhook 會變成繞過 RBAC 嘅側門。
- 補上遺漏：MCP spec 2025-11-25：CIMD 優先、DCR 係 MAY、WWW-Authenticate resource_metadata、insufficient_scope 403、S256 PKCE metadata。
- 補上遺漏：Standard Webhooks：簽名 header 係空格分隔清單，rotation 時送兩個 v1 簽名；payload 欄位用 type／timestamp／data。
- 補上遺漏：CORS：/api/v1 同 /api/mcp 要明確拒絕瀏覽器跨域（唔回 Access-Control-Allow-Origin），防止 key 被放入前端網頁。
- 補上遺漏：Pepper 同 env：POSTRIFF_API_KEY_PEPPER 要加入 web/.env.example、hosted_app runtime_from_environment 同 Vercel env，並寫明 rotate pepper 會令所有 key 失效。
- 補上遺漏：帳戶刪除同 profile.deleted_at：建立者刪帳戶時 key 要即時失效（hosted.py 查詢已經用 p.deleted_at IS NULL，驗證 key 時要 join 返）。
- 補上遺漏：Hosted migration 流程：migrations/postriff/hosted-004-008.sql 同 hosted-precheck.sql 係合併部署 script，013 要同步處理。
- 補上遺漏：現有 bug：nav-config.ts 入面 Channels 同 Home 都用 shortcut ['h','h']，搬 nav 時應該一齊修正。
- 補上遺漏：Memory view 喺 web/src/features/memory/memory-view.tsx，搬 nav 時唔好當佢喺 features/workspace。
- 補上遺漏：Welcome tour 嘅 brand／memory 步驟 route 係 /app/workspace/brand 同 /app/workspace/memory；如果只改 nav，唔改 URL，tour 唔使改。建議 Brand／Memory 保留原 URL，避免多餘 redirect。
- 補上遺漏：ui/table/data-table.tsx（連 pagination、faceted filter、date filter）已經有，key 表、delivery log、audit 應該重用。
- 補上遺漏：平行 session：web/src 由其他 session 改緊，實作要按路徑 stage，而且研究文件應該放 docs/。
