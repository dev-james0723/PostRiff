# PostRiff — Consumer SaaS 改造與介面重構規格

> 狀態：提案 / 待決策
> 日期：2026-09-16
> 範圍：由「reviewable prototype」轉為「真實面向消費者嘅 Web SaaS」，並以
> [`next-shadcn-dashboard-starter`](https://github.com/Kiranism/next-shadcn-dashboard-starter)
> 作為前端結構與設計基礎。

---

## 0. 執行摘要

三句講完：

1. **PostRiff 嘅後端唔係 prototype，係接近生產級。** Workspace / RBAC / audit / entitlement ledger /
   budget ceiling / GDPR data request / per-capability OAuth matrix 全部已經寫好。
2. **真正缺嘅係「對外嘅一切」**：marketing site、法律頁、真付款、transactional email、
   observability、以及一個似 SaaS 嘅 app 介面。
3. **所有核心能力都刻意停喺 `candidate` / `fixture` / `proposed` 狀態。**
   由 prototype 變 product，本質上係逐項將呢啲 flag 翻做 live，而唔係寫新功能。

採用 dashboard template 順帶解決咗我哋一個結構性問題：由 Vite SPA 轉去 Next.js 之後，
marketing 頁可以 SSR，SEO 同 OG crawler 先至抓到，平台審批先至有嘢可以交。

> **品牌待辦**：codebase 入面同時出現 `James Au Studio`、`PostRiff`、`Your agency` 三個名稱。
> 對外統一一個名係 Phase A 嘅前置條件（本文件暫用 PostRiff）。

---

## 1. 現況盤點

### 1.1 已經有嘅（資產）

| 能力 | 位置 | 狀態 |
|---|---|---|
| Workspace + membership + RBAC | `src/postriff_phase2/permissions.py`, `hosted.py` | 可用 |
| Invitations（建立／撤銷／接受） | `hosted.py:384` | API 可用，**無 UI、無寄信** |
| Audit log | `/api/workspaces/{id}/audit` | 可用 |
| Entitlements + usage ledger + budget | `billing.py` | 可用 |
| GDPR data request / account deletion / export | `/data-requests`, `/account`, `/export` | 可用 |
| Per-channel OAuth + **capability matrix** | `oauth.py`, `channels.py` | 可用 |
| Cron worker + billing webhook | `hosted_app.py` | 可用 |
| Agent runtime / ideas / content types | `agent_runtime.py`, `content_types.py` | 可用 |

**Capability matrix 值得特別講。** `channels.py` 將 identity / publish / schedule / analytics /
comments_read / reply / moderate / media_types / webhooks 九項能力**獨立評級**
（`Direct` / `Assisted` / `Unsupported`），而且要有 evidence 同 verifiedAt 先可以升級。
Buffer、Publer、Postiz 全部都係俾你一個混合嘅「Connected ✓」。
**呢個係產品差異化，唔係技術細節，新介面必須將佢視覺化。**

### 1.2 缺嘅（按 blocker 程度）

**P0 — 阻住一切**

- 無 `/privacy`、`/terms`、`/data-deletion` — 平台 app review 硬性要求
- 無 marketing site — `vercel.json` 將 `/(.*)` 全部食入 SPA
- 無真付款 — `billing.py` 只有 `FixturePaymentProvider`，檔頭明寫「Nothing here charges money」
- 無 transactional email — 後果：`invite()` 只寫低 token hash，**受邀人永遠收唔到邀請**

**P1 — 唔似真產品**

- 無 Billing / Usage UI（後端有 quota，前台睇唔到剩幾多）
- 無 Sentry、無 product analytics（唔知用戶死喺 onboarding 邊一步）
- 無 calendar 視圖（呢個 category 每一隻產品都有）
- 無 media library
- Analytics route 存在但無真數據回填
- 無 support surface（contact / docs / changelog / status）
- SEO 零：無 meta description、無 OG image、無 `robots.txt`、無 `sitemap.xml`；
  `<title>` 仲係 `Private founder alpha`

---

## 2. 市場對比

| | 價格 | 渠道數 | 核心賣點 |
|---|---|---|---|
| Buffer | Free / 低價 | ~8 | 最乾淨嘅 scheduler，free tier 無敵 |
| Publer | ~$4/account | ~10 | 最抵嘅多渠道發佈 |
| Postiz | $29–39 | 21（最闊） | 開源、self-host、n8n/Make 整合 |
| Blotato | $29 / $97 / $499 | 9 | Content Remixer + **API / MCP 可程式化** |
| Typefully | $12.5 | 4 | X / LinkedIn 深度 |
| Taplio | 較高 | 1 | LinkedIn 專精 + 互動名單 |
| **PostRiff** | $19 / $39（proposed） | **30+（含中文平台）** | 中西平台通吃 + 能力誠實度 + team/RBAC |

**定位結論：唔好同 Buffer 打「平價 scheduler」。**
PostRiff 應該係「唯一同時覆蓋西方同中文平台（小紅書／B站／知乎／微博／抖音）、
而且對每條渠道嘅真實能力誠實嘅 AI 內容工作室」。
$19/$39 喺呢個帶入面合理；team/RBAC 喺 Blotato 要 $499 Agency plan 先有。

**平台審批現實（必須最早開始排隊）**

- Meta（IG/FB）：Graph API 免費但要 App Review
- LinkedIn：Community Management API 要申請表 + screen recording + 測試帳號 +
  明確商業用途，**「generic scheduler」會被 reject**
- TikTok：未過 audit 嘅 client，post 被強制 `privacy_level = SELF_ONLY`，
  **而 API 仍然回 success** — 即係靜靜哋壞咗
- 週期 2–6 週，被拒要重交

`oauth.py:160` 嘅 `production_reviewed` 而家全部 `false`，所以任何 publish 自動降級成
`Assisted / export only`。**即係產品核心動作而家做唔到。**

---

## 3. 三個結構性決定（要你拍板）

### 決定 1 — Local Studio 定 Hosted Web？

| | Local Studio | Hosted Web |
|---|---|---|
| 渠道 | 15+（Playwright broker） | **3**：LinkedIn / Threads / Instagram（`providers.py:84`） |
| 啟動 | `Start Studio.command` + 本機 browser | 瀏覽器開網址 |
| 可否做 consumer SaaS | ✗ | ✓ |

而家 landing 賣 local 嘅威力，登入後得 hosted 三條渠道 — 期望落差好大。

**建議：Hosted-first + 可選 Desktop Companion。**
Hosted 覆蓋 OAuth 渠道；中文平台由一個可選下載嘅 companion 處理，
喺 Channels 頁用 `Local` badge 清楚標示。中文平台係你唯一嘅真差異化，唔好放棄，
但唔可以做預設路徑。

### 決定 2 — 幾時接真錢？

`FixturePaymentProvider` → `StripeProvider`。Ledger 同 entitlement 已經寫好，
差嘅只係 provider 實作 + `/api/billing/checkout` + `/api/billing/portal` 兩條 route +
`pr_plan_terms.status` 由 `proposed` 改 `active`。工作量細，但冇咗就唔係 SaaS。

### 決定 3 — 前端重寫嘅代價

採用 template = Vite SPA → Next.js 16。
**得益**：SSR marketing、SEO、OG、一個 project 同時 host 公開站同 app、
成熟 component 庫、Sentry 已接。
**代價**：template 深度綁定 **Clerk**（auth + orgs + billing），
而 PostRiff 用 **Supabase**。以下位置要換：
`auth.protect()`、`useOrganization()`、`<PricingTable>`、`org-switcher.tsx`、
`user-nav.tsx`、`nav-config` 嘅 `access` 判定。
估計 1–2 週。Python WSGI 後端**完全唔郁**，繼續喺 `/api/*`。

---

## 4. Template 深度分析

### 4.1 Stack

Next.js 16.2 · React 19 · Tailwind v4 · shadcn (base-ui) · Clerk ·
TanStack Query / Table / Form · nuqs（URL state）· Zustand · Recharts 3.8 ·
dnd-kit · kbar（Cmd+K）· Sentry · sonner · motion · react-dropzone · zod 4

### 4.2 可以直接攞嚟用嘅資產（按價值排）

**① `nav-config.ts` 嘅 RBAC**

```ts
access: { requireOrg, permission, plan, feature, role }
```

呢個**直接對應** PostRiff 已有嘅 `permissions.py` + entitlements + plan。
同一份 config 同時 drive sidebar 同 Cmd+K。
→ `permission: 'manage_members'`、`plan: 'assist'`、`feature: 'publish_verified'` 即刻可用。

**② Parallel Routes（`@area_stats` / `@sales` / `@pie_stats` / `@bar_stats`）**

每個 slot 有獨立 `loading.tsx` / `error.tsx` / `default.tsx` — 獨立 streaming、獨立失敗。

> 呢個係整份分析入面**最重要嘅一個發現**。PostRiff 嘅 Analytics 每條渠道嚟自唔同 provider，
> 各有各嘅 rate limit、token 過期、未過審批。Parallel routes 令到「LinkedIn 數據拎到、
> TikTok 拎唔到」可以喺同一頁**分別呈現**，而唔係成頁一齊炸。
> 呢個結構同 capability matrix 嘅哲學完全一致。

**③ `PageContainer`**

一個 primitive 同時提供 `access` + `accessFallback` + `isLoading` skeleton +
`infoContent` + `pageHeaderAction`。
→ PostRiff 嘅 `Assisted` / `Unsupported` gating 直接塞入 `access` / `accessFallback`。

**④ `InfobarProvider` + `InfoSidebar`（右側說明欄）**

→ 專門用嚟解釋「點解呢條渠道係 export-only」、「Direct 同 Assisted 分別喺邊」、
「你剩幾多 writing batch」。呢個係誠實度嘅載體。

**⑤ Data table 全套**

`use-data-table.ts` + nuqs + faceted filter / date filter / slider filter +
column header / pagination / view options / skeleton。
→ Publishing log、Audit log、Members、Media library 全部即刻有企業級表格。

**⑥ Form field 庫（18 個）**

text / textarea / select / combobox / checkbox-group / date-picker / file-upload /
otp / radio / slider / switch / tags / toggle-group / color + multi-step + `use-stepper`。
→ `AuthEntry` 嘅 OTP 用 `otp-field`；`FounderApp` 嘅 5 步 `STEPS` 直接用 multi-step form。

**⑦ Kanban（dnd-kit + Zustand）**

→ 內容流水線：`Idea → Draft → Scheduled → Published`。

**⑧ 其他**

`kbar` Cmd+K · `org-switcher`（→ workspace switcher）· 主題系統（dark mode + theme selector +
font config）· `notification-card` + notification store · `file-uploader` / `file-preview` /
`attachment`（→ media library）· `empty`（空狀態）· AI Chat（AI SDK v7 →
PostRiff `AgentPanel`）· Sentry 已接線

### 4.3 Template **冇**嘅嘢（要自己起）

- **完全無 marketing / landing**。`src/app/page.tsx` 只係 redirect：未登入 → sign-in，
  已登入 → dashboard。整個公開面要由零起。
- **無 `/privacy-policy`、`/terms-of-service`** — auth 頁有連結但 route 唔存在
- **無 calendar / scheduling 視圖**（有 `calendar` primitive 同 react-day-picker，
  但無排程功能）
- 無 public API docs、無 changelog、無 status page
- 無 email template
- Billing 係 Clerk `<PricingTable>` — 同 PostRiff 自己嘅 entitlement/ledger 唔兼容，要換

---

## 5. 新 Information Architecture

```
PUBLIC（SSR / 靜態 — template 冇，全新）
├── /                        Landing
├── /pricing                 價格 + plan 對比
├── /channels                30+ 渠道矩陣（SEO 金礦）
├── /channels/[slug]         逐個渠道落地頁
├── /security                安全與資料邊界
├── /privacy                 ← 平台審批必要
├── /terms                   ← 平台審批必要
├── /data-deletion           ← 平台審批必要
├── /docs · /changelog · /status · /contact
└── /blog                    （選配，SEO）

AUTH（template 有，換 Clerk → Supabase）
├── /auth/sign-in · /auth/sign-up · /auth/verify
├── /auth/callback           OAuth PKCE 回調
└── /invite/[token]          接受邀請 ← 後端已有，無 UI

APP（/app/*）
┌ Create
│ ├── /app                  Overview（parallel routes）
│ ├── /app/ideas            Studio — AI 生成
│ ├── /app/calendar         ★ 新，category table stake
│ ├── /app/pipeline         Kanban
│ └── /app/library          Media library
├ Distribute
│ ├── /app/channels         能力矩陣
│ ├── /app/channels/[id]    單一渠道詳情
│ └── /app/queue            排程隊列 + 發佈記錄
├ Grow
│ ├── /app/analytics        Parallel routes per provider
│ └── /app/inbox            留言 / 回覆草稿
├ Workspace
│ ├── /app/workspace/members · /roles · /audit · /brand
└ Account
  ├── /app/account/profile · /notifications
  ├── /app/account/billing  Plan + usage + invoice
  ├── /app/account/privacy  Data request / export / delete
  └── /app/account/api      API keys · MCP · webhooks
```

---

## 6. 逐頁設計

### 6.1 `/` Landing（全新）

```
┌────────────────────────────────────────────────────────┐
│ [logo]   Product  Channels  Pricing  Docs   [Sign in]  │
├────────────────────────────────────────────────────────┤
│  一個 idea，30+ 個平台，包括小紅書同 B站。              │
│  AI 按每個平台嘅語氣重寫，你批准咗先發。                │
│     [ 免費試用 14 日 ]   [ 睇 demo ▸ ]                  │
│     無需信用卡 · 隨時匯出所有內容                       │
├────────────────────────────────────────────────────────┤
│  ▣ 產品截圖／30 秒 demo（平台審批同時要用）             │
├────────────────────────────────────────────────────────┤
│  渠道矩陣   [IG][LI][X][TikTok][小紅書][B站][知乎]...   │
│  每個 chip 標 Direct / Assisted / Local                │
├────────────────────────────────────────────────────────┤
│  01 匯入來源 → 02 AI 按平台改寫 → 03 你批准 → 04 發佈   │
├────────────────────────────────────────────────────────┤
│  「我哋唔會扮有能力」— capability matrix 解說 ★差異化   │
├────────────────────────────────────────────────────────┤
│  社會證明 · 價格摘要 · FAQ · Footer（法律連結）         │
└────────────────────────────────────────────────────────┘
```

Template 元素：`card` · `badge` · `accordion`（FAQ）· `carousel`（截圖）·
`motion` · auth 頁嗰個 `interactive-grid` 背景。

### 6.2 `/app` Overview（改用 parallel routes）

```
/app/
├── @publishing/    今個星期排程 + 狀態
├── @usage/         Quota 消耗（來自 entitlements）
├── @performance/   跨渠道表現
└── @attention/     需要處理：token 過期 / 審批中 / 草稿待批
```

頂部四張 stat card（照抄 template `overview/layout.tsx` 嘅
`CardHeader` + `CardAction` + `Badge` + `CardFooter` 結構）：

| Card | 資料來源 |
|---|---|
| 今個月已發佈 | `/analytics/summary` |
| 排程中 | queue |
| 寫作額度剩餘 | `/workspaces/{id}/usage` |
| 已連接渠道 | `/channels` |

`@attention` slot 係關鍵 — 而家用戶完全唔知自己邊條渠道壞咗。

### 6.3 `/app/channels` — 能力矩陣（旗艦頁）

```
┌─ Channels ───────────────────── [+ 連接渠道] ─┐
│ Filter: [全部][Direct][Assisted][Local][有問題]│
├───────────────────────────────────────────────┤
│ ▣ LinkedIn  @jamesau            Direct        │
│   identity ● publish ● schedule ◐ analytics ● │
│   comments ● reply ◐   · 2026-09-14 驗證      │
│   [設定] [重新驗證] [中斷]                     │
├───────────────────────────────────────────────┤
│ ▣ TikTok    @jamesau         Assisted  ⚠      │
│   publish ◐ — 未通過 TikTok 審批，只可匯出     │
│   ⓘ 點解？ → 開右側 InfoSidebar                │
├───────────────────────────────────────────────┤
│ ▣ 小紅書                        Local  ⬇       │
│   需要 Desktop Companion  [下載]               │
└───────────────────────────────────────────────┘
```

`● Direct` / `◐ Assisted` / `○ Unsupported`，逐項 capability 顯示，
hover 出 `evidence` + `verifiedAt`。
Template 元素：`card` · `badge` · `tooltip` · `hover-card` · `infobar` · `data-table`（表格檢視）。

### 6.4 `/app/calendar`（全新 — 必要）

月 / 週 / 列表三個檢視，拖拽改期，左側 channel filter，
未排程草稿 drawer。`calendar` primitive + react-day-picker + dnd-kit + `drawer`。

### 6.5 `/app/ideas` — Studio

三欄：來源 → 生成 → 每平台變體。
每個變體 card 顯示字數上限、媒體要求、預估成本（`price_quote`）。
Template：`resizable`（三欄）· `tabs` · `textarea` · `sonner` · AI Chat streaming。

### 6.6 `/app/account/billing`（**唔用** Clerk PricingTable）

```
┌─ 目前方案 ────────────────────────────┐
│ Studio · $19/月 · 下次扣款 2026-10-14 │
│ [升級] [管理付款方式] [取消]           │
├─ 本期用量 ────────────────────────────┤
│ 寫作      ████████░░ 42/60            │
│ 媒體      ███░░░░░░░ 12/40            │
│ 渠道      ██████░░░░  6/10            │
│ 10 月 14 日重置                        │
├─ 發票 ────────────────────────────────┤
│ data-table（日期／金額／狀態／下載）   │
└───────────────────────────────────────┘
```

資料來自 `/api/workspaces/{id}/usage`。`progress` + `card` + `data-table`。
Quota 用盡時嘅 `AlphaError 402` 必須帶升級 CTA。

### 6.7 `/app/account/privacy`

Data request 列表 · 匯出草稿 · 匯出個人聲音檔 · 刪除帳戶（`alert-dialog` 二次確認）。
後端全部已有，只差 UI。**呢頁同時係平台審批嘅證據。**

### 6.8 其他頁對應

| 頁面 | Template 資產 |
|---|---|
| `/app/pipeline` | Kanban（dnd-kit + Zustand），column = Idea/Draft/Scheduled/Published |
| `/app/library` | `file-uploader` + `file-preview` + `aspect-ratio` + `data-table` |
| `/app/inbox` | Chat feature（`conversation-list` + `message-bubble` + `message-composer`） |
| `/app/workspace/members` | `data-table` + `org-switcher` + invite `dialog` |
| `/app/workspace/audit` | `data-table` + date filter + faceted filter |
| `/app/workspace/brand` | Multi-step form + `use-stepper`（接管現有 5 步 `STEPS`） |
| `/app/account/notifications` | `notification-card` + notification store |
| Onboarding | Multi-step form + `tags-field`（niche）+ `toggle-group`（語氣） |

---

## 7. Design system 決定

1. **保留 template 嘅 token 系統**（Tailwind v4 + `active-theme` + theme selector），
   注入 PostRiff 品牌色。唔好硬搬現有 `founder.css` 嘅手寫美學 —
   佢個 editorial 風格靚，但唔 scale，而且同 shadcn 打交。
2. **Dark mode 由第一日做**（template 免費送）。
3. **Capability 三色語義**係全 app 統一嘅視覺語言：
   `Direct` = 綠 · `Assisted` = 琥珀 · `Unsupported` = 灰。
   一套色喺 channels / calendar / queue / analytics 通用。
4. **每一頁都要有 empty state**（用 `empty` primitive），
   而家 prototype 最露餡就係空白頁。
5. **Marketing 同 App 兩套視覺語言**：
   marketing 保留現有嘅 editorial / 手寫感（呢個係品牌）；
   app 用 shadcn 嘅中性密度。兩者共用色板同字體。

---

## 8. 落地計劃

### Phase A — 解鎖平台審批（1–2 週，最高優先）

- [ ] 定品牌名稱
- [ ] Next.js 專案骨架 + 由 template 搬 `components/ui`、`lib`、`hooks`
- [ ] `/privacy`、`/terms`、`/data-deletion`、`/security`
- [ ] `/` landing + `/pricing` + `/channels`
- [ ] SEO：metadata、OG image、`robots.txt`、`sitemap.xml`、favicon
- [ ] 錄 30 秒 demo 影片
- [ ] **同步遞交 Meta / LinkedIn / TikTok 審批**（一交等 2–6 週，所以要最早）
- [ ] `vercel.json` routing 拆分：`/` = Next.js，`/api/*` = Python（不變）

### Phase B — 審批期間補基建（並行，2–3 週）

- [ ] Clerk → Supabase：auth guard、org switcher、user nav
- [ ] `StripeProvider` + checkout + portal + webhook；`plan_terms` → `active`
- [ ] Transactional email（Resend）：邀請、歡迎、trial 到期、付款失敗
- [ ] `/invite/[token]` UI
- [ ] Sentry + product analytics
- [ ] `/app/account/billing` + usage

### Phase C — App 重構（3–4 週）

- [ ] Dashboard shell：sidebar + kbar + PageContainer + InfoSidebar
- [ ] `nav-config` 接 PostRiff `permissions` + entitlements
- [ ] Overview parallel routes
- [ ] Channels 能力矩陣頁
- [ ] Calendar（新）
- [ ] Ideas / Studio 搬入新 shell
- [ ] Pipeline / Library / Inbox
- [ ] Workspace 系列
- [ ] 全頁 empty state + error state

### Phase D — 護城河（持續）

- [ ] Public API + MCP server + n8n node（對標 Blotato 嘅主要護城河）
- [ ] 真 analytics 數據回填
- [ ] Desktop Companion（中文平台）
- [ ] `/channels/[slug]` SEO 落地頁 · changelog · status

---

## 9. 風險與未決問題

| 風險 | 影響 | 緩解 |
|---|---|---|
| LinkedIn 以「generic scheduler」為由拒批 | 核心渠道冇咗 | 申請時定位為「個人品牌內容工作室」，強調人手批准流程，唔好用 "scheduler" 字眼 |
| TikTok 未過 audit 靜默 `SELF_ONLY` | 用戶以為發咗，實際冇人見到 | Capability matrix 必須將呢個狀態明示，`Assisted` 唔可以顯示成可發佈 |
| 前端重寫期間功能凍結 | 進度風險 | Marketing（Phase A）同 app 重構（Phase C）分開部署，marketing 先上 |
| Clerk 解耦比預期難 | 拖慢 Phase B | 先起 adapter 層包住 `useAuth` / `useOrganization`，再換實作 |
| Local broker 同 hosted 期望落差 | 用戶流失 | Landing 明確標示邊啲渠道要 companion |

**未決**

1. 品牌名稱
2. Desktop Companion 做定唔做（影響中文平台差異化）
3. 價格是否維持 $19 / $39
4. Public API 幾時開（Blotato 靠呢個建護城河）

---

## 附錄 A — Template 資產對照表

| Template 檔案 | PostRiff 用途 |
|---|---|
| `config/nav-config.ts` | 接 `permissions.py` + entitlements 嘅 RBAC 導航 |
| `components/layout/page-container.tsx` | 每頁嘅 access gate + skeleton + info |
| `components/layout/app-sidebar.tsx` | 主導航 |
| `components/layout/info-sidebar.tsx` | Capability / quota 解說欄 |
| `components/org-switcher.tsx` | Workspace switcher |
| `components/kbar/*` | Cmd+K |
| `hooks/use-data-table.ts` + `ui/data-table-*` | Queue / audit / members / library |
| `components/forms/fields/*` | 所有表單 |
| `hooks/use-stepper.tsx` | Onboarding 5 步 |
| `features/kanban/*` | 內容流水線 |
| `features/chat/*` | Inbox / 回覆草稿 |
| `features/ai-chat/*` | AgentPanel |
| `features/overview/*`（Recharts） | Analytics |
| `components/themes/*` | 主題 + dark mode |
| `components/file-uploader.tsx` | Media library |
| `ui/empty` | 全部空狀態 |
| `app/dashboard/overview/@*/` | Parallel routes 模式（per-provider 獨立失敗） |

---

## 附錄 B — 參考資料

- [next-shadcn-dashboard-starter](https://github.com/Kiranism/next-shadcn-dashboard-starter)
- [Social Media APIs in 2026: A Builder's Guide](https://www.blotato.com/blog/social-media-api)
- [How to Get Social Media API Access (2026 Guide)](https://posteverywhere.ai/blog/how-to-get-social-media-api-access)
- [Best Postiz Alternatives in 2026](https://getsocialclaw.com/postiz-alternatives)
- [Blotato Review 2026](https://www.topsocialtools.com/insights/blotato/)
- [Best Social Media Schedulers in 2026](https://postfa.st/blog/best-social-media-schedulers)
- [The 7 Best Taplio Alternatives in 2026](https://typefully.com/blog/taplio-alternatives)
- [7 best social media APIs for agency workflows in 2026](https://planable.io/blog/social-media-apis/)
