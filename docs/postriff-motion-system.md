# PostRiff — Motion 系統（beUI components + transitions.dev）落實記錄

> 狀態：已落實喺 `web/`（未 commit）
> 日期：2026-09-16
> 來源：[starc007/ui-components](https://github.com/starc007/ui-components)（beUI，MIT）、[Jakubantalik/transitions.dev](https://github.com/Jakubantalik/transitions.dev)（skill `transitions-dev` + `transitions-polish`）
> 驗證：`npx tsc --noEmit` 0 error；`npm run lint` 353 個檔 0 warning / 0 error；`next build` 全部 route 編譯成功；browser 逐頁實測（light / dark、1440px / 375px），console 冇 error

---

## 0. 一句講完

**兩層分工：beUI 做「component 層」嘅互動（JS spring、有狀態），transitions.dev 做「系統層」嘅時間同 primitives（CSS token，全 app 共用）。**

| 層 | 負責 | 放喺邊 |
|---|---|---|
| **beUI** | 會變嘅嘢：狀態徽章、數字、按鈕狀態、tabs pill、agent 進度、context menu、live island | `web/src/components/{motion,agents,charts}/` |
| **transitions.dev** | 每個 dropdown / select / popover / dialog / sheet / tooltip / toast / checkbox / skeleton / tabs 嘅開合時間；轉頁；SSR 標題 | `web/src/styles/transitions.css` + `components/ui/*` |

原則：**真數據先郁**。所有數字、計時、進度、狀態都讀 workspace snapshot 或者 API；冇假 loading 字眼、冇模擬進度。

---

## 1. beUI：32 個 component 用喺邊

| 頁面 | Component | 做咩 |
|---|---|---|
| Header（全 app） | DynamicIsland | Live Island：publishing 中／待批／失敗／下一個 post 倒數；hover 展開；job 變 published 時彈「Published on …」 |
| Header | ActionSwapIcon | 主題掣日／月 icon 滾動切換 |
| Home | TextReveal | 標題逐字浮現 |
| Home | Tabs（pill） | 「What to make」同 Quick start 分組，primary pill 滑動 |
| Home | NotificationStack | 將「Set up your voice／drafts 待批／channel 要 reconnect」疊成一疊，hover 展開 |
| Home、Conversation、Ideas | SharedLayoutBg | 對話列表 hover 底色跟住滑 |
| Composer | ActionSwapIcon、Checkbox | 送出掣 send↔spinner；同意 checkbox 畫剔 |
| Model picker | TextScramble | 用戶揀 model 後名稱亂碼解碼（載入時唔播） |
| Conversation | Message、MessageBubble | 新到嘅訊息先有 pop-in，reload 唔會重播 |
| Conversation | Loader（ascii-braille）、ThinkingShimmer、AgentProgress | queued：終端 spinner + shimmer 字；writing：真實經過秒數 |
| Activity strip | AgentDisclosure、ActionSwapText/Icon | run log 展開收埋；run 完成時 spinner 轉剔 |
| Variant card | Tabs（segment）、DigitSwap | 平台切換；字數滾動 |
| Plan card | TodoList、StatefulButton、Checkbox、AnimatedBadge | 批核流程逐步 checklist（真實 step）；Approving…→Scheduled |
| Overview | NumberTicker、HeatCalendar、TodoList | 統計數字；Publishing activity 熱力日曆（provider 確認嘅 post）；Get set up |
| Billing | NumberTicker | allowance 數字 + 條 |
| Queue | AnimatedBadge、HoldActionButton、StatefulButton、Tabs、DigitSwap | job 狀態；長按取消；Approve & schedule；filter 計數 |
| Calendar | Tabs（segment）、Tooltip、AnimatedBadge | Month/List；格仔 tooltip；月份左右滑 |
| Pipeline | ContextMenu、DigitSwap | 右鍵：Edit／Schedule／Copy text／前往；欄計數 |
| Library | TiltCard、ContextMenu、StatefulButton | 圖片傾斜反光；Copy hash／Delete…；上載狀態 |
| Channels | AnimatedBadge、StatefulButton | 連接狀態；Re-verify／Connect |
| Ideas | Tabs、Switch、Checkbox、StatefulButton、AgentDisclosure | candidates；cloud 開關；run log |
| Inbox | StatefulButton | Suggest／Save／Review／Send 各自狀態 |
| Memory | FileTree | `memory/` 資料夾樹（keyboard 導航） |
| Brand（voice setup） | RadioGroup | 卡片式選項，圓點滑動 |
| Analytics | NumberTicker、AnimatedBadge | 只有 API 有真實整數先滾動 |
| Marketing 首頁 | ChromaticTextReveal、Magnetic、Marquee、ScrollReveal、BouncyAccordion、TiltCard | 「Rewritten in your voice for LinkedIn/小紅書/…」；CTA 磁吸；33 個 channel 跑馬燈；section 浮現；FAQ（保留 h3）；產品框傾斜 |
| 404 | NotFound（Magnetic stage） | 數字跟滑鼠；h1 保持真標題 |
| Status | AnimatedBadge | Checking（真請求中）→ Operational／Degraded／Unavailable |

## 2. transitions.dev：tokens + 15 個 transition

`web/src/styles/transitions.css` 由 `globals.css` import。Skill 原本用 JS toggle `.is-open` / `.is-closing`；Base UI 本身有 `data-starting-style` / `data-ending-style`，而且會等 transition 完先 unmount，所以直接接上，唔使 timer。

| # | Transition | 用喺 |
|---|---|---|
| 03 | Notification badge | Sidebar「Queue」待批數字滑入彈出 |
| 05 | Menu dropdown | `ui/dropdown-menu`、`ui/select`、`ui/popover`（跟 trigger 方向放大，開 250ms／收 150ms） |
| 06 | Modal | `ui/dialog`、`ui/alert-dialog` + backdrop |
| 07 | Panel reveal | `ui/sheet`（按 side 方向 + cross-blur） |
| 08 | Page slide | `app/app/template.tsx`：每次轉頁內容浮入 |
| 10 | Success check | Plan card「N posts approved」（只喺今次真係批核先播） |
| 11 | Avatar group hover | Channels desktop companion chips |
| 14 | Skeleton pulse | `ui/skeleton` |
| 16 | Tabs sliding | `ui/tabs`（Base UI Indicator 量度） |
| 17 | Tooltip | `ui/tooltip`（80ms intent delay、50ms 收） |
| 18 | Texts reveal | Marketing hero 同 PageHero 標題（純 CSS，JS 未載入都睇到，唔拖 LCP） |
| 22 | Toast | Sonner：入 350ms／出 250ms + blur |
| 24 | Learn more hover | 「Manage channels ›」「Open the queue ›」等連結箭嘴 |
| 25 | Checkbox check | `ui/checkbox` 畫剔 |
| 30 | Streaming text | Conversation 串流：每個真正到達嘅字由模糊變清 |

Token 衝突處理：skill 嘅 `--ease-out` / `--ease-in-out` 同 Tailwind 自己嘅變數同名，冇重新定義（直接用 keyword），其他 token 全部照搬。

## 3. 對 library 嘅本地改動

beUI 路徑同原 repo 一樣（方便日後 `npx shadcn add @beui/…` 更新），改動記錄喺 `web/src/components/motion/README.md`，重點：

- Icon 由 `lucide-react` 換成 `@/components/icons`（Tabler）
- `button/base.tsx` 用 app 自己嘅 `buttonVariants`，跟 10 個主題
- Tabs：方向鍵、roving tabindex、`tabpanel` 關聯、focus ring
- RadioGroup：方向鍵選擇、`aria-label`、description 行
- ContextMenu：article/figure 唔加 popup ARIA；選咗文字時保留瀏覽器原生右鍵（Copy）
- HoldActionButton：休息時唔露波浪、`waveClassName`、disabled 時放開未完成嘅 hold
- TodoList：`ariaLabel`、`spinActive`（「目前步驟」唔扮緊做嘢）
- ScrollReveal / TextReveal：完成後清走 `filter`
- NotificationStack：「1 notification」單數；BouncyAccordion：`headingLevel`；HeatCalendar：「1 post」單數；404 actions 用 Next Link；TiltCard 反光改淺色
- TextScramble：`animate` 開關（只喺用戶操作時播）

## 4. 順手修正（原本已存在）

- **Calendar 星期錯位**：表頭 Mon–Sun，格仔卻由星期日開始 → 加 `weekStartsOn: 1`
- **Queue「cancelling」**：已經 `canceled` 嘅 job 會永遠轉圈 → 只喺未完結時顯示
- **Conversation 等候字眼**：「Waiting for Claude Code…」連 Codex run 都顯示 → 按 run 嘅 route 顯示
- 共用 `useFlash` 抽去 `web/src/hooks/use-flash.ts`

## 5. 規則（之後加 motion 請跟）

1. 真數據先郁；「Unavailable」永遠唔變 0。
2. Reduced motion：library 已處理；自己加嘅 motion 要 `useReducedMotion()`，只郁 transform / opacity。
3. SSR 重要文字（marketing 標題）用 CSS reveal，唔好用要等 hydration 嘅 JS reveal。
4. 開合時間用 `transitions.css` token：收一定快過開；stagger 40ms、總長 ≤ 300ms。
5. 破壞性動作保留確認（dialog 或長按）。

## 6. 已知限制 / 待辦

- **Dev harness 嘅 Threads 係 live provider**（Channels 頁顯示 `evidence: live provider`）。今次驗證冇撳任何批核、排程、Re-verify 或送出，所以 HoldActionButton、Approve 流程、Success check、Streaming text 只做咗 code review + typecheck，未喺真實流程播過。
- **Memory 頁 API 404**：dev API server 02:26 開，`GET /memory` 04:05 先 commit；重開 `postriff-api` 就會有資料顯示 FileTree。
- Pipeline 每張卡都 mount 住一個隱藏 context menu（inert），卡多時可考慮 lazy mount。
- `StatefulButton` 冇前置 icon slot；`Switch` 冇細 size。
