# 專題研究：PostRiff「冇咁死板」motion 層：Hyperframes／Remotion 應該放喺邊、Home pointer-reactive particle field、逐頁 alive moments、onboarding 導航動畫 primitives

> 研究 agent 起稿（包括網上資料），再由另一個 agent 重新 fetch 關鍵來源同 grep codebase 覆核。

## 建議

現況：另一個 session 已經起咗兩樣嘢，都未 commit。第一樣係 `web/src/components/motion/particle-field.tsx`（278 行，Canvas 2D，component default alpha 0.55），由 Server Component `web/src/app/app/page.tsx` 以 alpha 0.42 mount 喺 HomeView 後面。第二樣係 `web/src/features/onboarding/*`（tour-overlay、store、tours、tour-mount 等）加 `web/src/styles/tour.css`，已經有 sidebar link pulse、spotlight 由 `lastRect` morph、`hop` 同 HOP 進度條。建議係「保留 hand-written canvas，補 6 個修正，將 mount 搬入 client；tour 保留結構，只收緊 motion 規則」。唔裝 tsParticles：佢係 MIT、4.4.0（2026-08）、支援 React 19，冇相容問題，但係成個通用 engine，我哋只要 drift + repel + hairline，唔抵。唔裝 OGL（Unlicense，core 8KB）／three：120 粒點用 WebGL 冇好處，反而要處理 context loss 同 oklch theme colour。

Hyperframes（Apache-2.0，預設 GSAP runtime）同 Remotion 本質上係 video renderer，合約係 deterministic、seek-safe、single paused timeline，同 live UI「讀真數據、即時回應 pointer」係兩回事。啱用嘅地方：(1) 預先 render 嘅 onboarding 短片同 empty state 插圖，內容係中性示範，畫面入面唔放似用戶數據嘅數字、唔放 Connected ✓，文字盡量放 HTML 唔放入片（咁先跟到 worldwide languages）；(2) marketing hero loop；(3) 產品功能 `skills/postriff-hyperframes-motion`（MotionVideoJob，Phase 0 只做 plan），同 app chrome 無關。產品化 render 之前要核對 GSAP Standard License：佢商業免費，但限制用喺同 Webflow 競爭嘅 no-code 視覺動畫工具，有需要就揀 CSS／WAAPI adapter。Remotion 唔引入：repo 冇 Remotion source；免費授權只限個人、≤3 員工公司同非牟利，超過要 company license，5.0 仲會改條款；Hyperframes 已經夠用。錯誤用法：將 live 數字、channel 狀態、queue 進度做成影片或者 Lottie，影片入面嘅數字一定係假。

逐頁 alive moments 嘅原則係「狀態變咗先郁，冇變唔郁」：每個動畫都要由 snapshot revision、API refetch 或者真時鐘觸發。唔可以將一次過返嚟嘅結果扮 streaming，亦唔可以將冇 bytes 數據嘅上載扮成百分比。先重用現有 32 個 beUI component、15 個 transitions.dev transition 同已經存在嘅真數據 UI（Library 階段式上載 badge、HOP 進度條、Billing NumberTicker），全部唔使新 dependency。

## 考慮過嘅選項

| Option | Verdict | Why |
|---|---|---|
| Hyperframes composition 直接 embed 入 live app（iframe 或者 runtime player） | 否決 | seek-driven render 合約（paused timeline、禁 Math.random、禁 repeat:-1），要 GSAP runtime（web/package.json 冇裝）。做唔到 live data 同 pointer 互動，數字只會寫死。 |
| Hyperframes render 成 webm/mp4（+ poster）做 onboarding 短片、empty state 插圖、marketing hero loop | 採用（限定範圍） | 呢啲係示範唔係數據。條件：中性例子（設計師／老師／小店／developer 都通用）、影片入面唔放用戶式數字同 Connected ✓、盡量唔放文字（交畀 HTML caption 做 i18n）；reduced-motion 淨係 poster；每段 ≤ 8s、≤ 400KB；有文字描述。 |
| Lottie（Hyperframes adapter 支援）做 empty state | 暫緩 | 要多裝 lottie player；webm + poster 或者 CSS/SVG 已經夠。有 After Effects 素材先考慮。 |
| Remotion 做 app 內動畫或者教學片 | 否決 | repo 冇 Remotion source；授權：個人／≤3 員工／非牟利免費，其餘要 company license，5.0 會再改；Hyperframes（Apache-2.0）已覆蓋 render 需求。 |
| 將 Hyperframes animation rules 詞彙（counting、stat fill、stagger cap、transform-only）翻譯去 motion v11 + transitions.css | 採用 | 同 docs/postriff-motion-system.md §5 一致，唔使 GSAP。時間用現有 token（--duration-fast 250ms 開、--duration-quick 150ms 收、--duration-stagger 40ms）。 |
| tsParticles（@tsparticles/react + @tsparticles/slim 4.4.0，MIT） | 否決 | 相容 React 19（peer react >=16.8），維護活躍，但係通用 engine（options schema、plugin loader、interaction manager），我哋只需要 drift + repel + hairline；theme token、reduced-motion、IntersectionObserver 暫停都要自己再包，成本唔抵。 |
| OGL（Unlicense，core 8KB／total 29KB minzipped）或者 three.js WebGL points | 否決 | ≤ 140 粒點 Canvas 2D 已經好平；WebGL 多咗 context loss、shader 讀 oklch、iOS Safari GPU 記憶體問題。幾千粒先值得轉。 |
| Hand-written Canvas 2D（現有 particle-field.tsx，278 行） | 採用 + 修正 | 已做 currentColor 跟 theme、DPR ≤ 2、tab hidden／offscreen 暫停、reduced-motion 一格靜止、coarse 冇互動、aria-hidden + pointer-events-none + print:hidden。要補：ghost pointer、暫停時轉 theme 唔重畫、逐條 stroke、冇 fps cap、coarse 冇降粒數／冇收線、標題對比度；另外 quiet／safeArea 需要 client 端 state，要將 mount 搬出 Server Component。 |

## 點樣接入 codebase

Particle field：
- 組件：`web/src/components/motion/particle-field.tsx`（untracked，另一 session WIP；改之前協調，stage by path）。Component default alpha 0.55；Home 傳 0.42。
- Mount：而家喺 `web/src/app/app/page.tsx`，但呢個檔案 export `metadata`，係 Server Component，唔可以持有 focus state。要傳 `quiet` 就將 `<ParticleField>` 搬入 `web/src/features/agent/home-view.tsx`（已經 'use client'，L97／L150 管 composer focus），或者起一個細 client wrapper `web/src/features/agent/home-backdrop.tsx`。外框保持 `relative isolate`，canvas `absolute -z-10 h-[44rem]` + mask-image。
- 對比度：composer 係 `bg-card`（`web/src/features/agent/composer.tsx` L73，`data-tour='composer'`），不透明；h1、副標題、mode Tabs 冇底色，係風險區。safeArea 用 React ref 傳 element，唔好用 `data-tour` selector（`data-tour` 係 `web/src/features/onboarding/tours.ts` 嘅定位 namespace，而且 repo 冇 `home-title`）。
- 顏色：`text-foreground` → `getComputedStyle().color`；10 個 theme 喺 `web/src/styles/themes/*.css`，由 `web/src/components/themes/active-theme.tsx` 設 `data-theme`；MutationObserver 已監聽 `class`／`data-theme`／`style`。

Onboarding 導航：
- `web/src/app/app/template.tsx`：`.t-page-enter`（#08）+ `TourMount` 每次轉頁 re-mount。
- `web/src/features/onboarding/store.ts`：`hop`、`lastRect`、`hopTo()`。
- `web/src/features/onboarding/tour-overlay.tsx`：`HOP_MS = 1400`（L32）；overlay `fixed inset-0 z-70`（L304）；spotlight animate `left/top/width/height/opacity`（L311）+ `boxShadow: '0 0 0 200vmax rgb(0 0 0 / 0.5)'`（L314）；`SPRING_LAYOUT`（`web/src/lib/ease.ts` L37），reduce 時 duration 0；HOP 進度條已存在（L380–386，linear HOP_MS）。
- `web/src/styles/tour.css`（由 `web/src/styles/globals.css` L18 import）：`[data-tour-pulse]` infinite box-shadow pulse，reduced-motion 靜態 2px ring。

逐頁 moments 用到嘅 hooks（`web/src/lib/api/hooks.ts`）：useSnapshot、useUsage、useChannels、useAnalytics、useAudience、useMembers、useInvitations、useAudit、useDataRequests、useConversations、useMessages、useSessions、useMe、useMyChannels、useSecurityEvents、useMyInvitations、useModels、useMemory、useMemoryProposals、usePrivacyNotice。全部冇 refetchInterval（calendar 另有 `useLiveSnapshotRefresh`）。
Types（`web/src/lib/api/types.ts`）：`CapabilityLevel`（L436）；`Capability { level, evidence, verifiedAt, capabilityVersion }`（per capability，唔係 per channel）；`ChannelView.capabilities: Record<string, Capability>`；`Job.manifest.timing { local, timeZone, utc }`（排程時間，冇 `scheduledAt`）；`LedgerEntry`、`Metric`、`AuditEvent`、`DataRequest`；session `current: boolean`（L647）。冇任何 webhook type。

現有真數據 motion（唔好重做）：
- Library：`web/src/features/library/use-upload-queue.ts` 真階段 waiting→reading→sending→done/failed（fetch 冇 bytes，所以刻意冇 %），`library-view.tsx` 用 AnimatedBadge。
- Billing：`web/src/features/billing/billing-view.tsx` 已用 NumberTicker。
- Overview：`web/src/features/overview/overview-view.tsx` HeatCalendar，weeks 係「卡片放得落幾多就幾多」（動態）。
- Memory：`web/src/features/memory/memory-view.tsx` 已用 FileTree。
- Sidebar #03 badge：`web/src/components/layout/app-sidebar.tsx` L108。
- 時鐘：`web/src/features/calendar/use-calendar-live.ts`（setInterval Date.now）；`toEpoch(manifest.timing.utc)` 用法見 `web/src/features/pipeline/pipeline-card.tsx` L101。
- Audit 邏輯喺 `web/src/features/workspace/audit-view.tsx`（唔係 app route folder）。

Hyperframes 素材：
- 產出 `web/public/motion/<slug>.{webm,mp4,png}`；composition source 放 repo 根新 folder `motion-src/`，唔入 web bundle。
- 播放器新 component `web/src/components/motion/tutorial-clip.tsx`。
- `skills/postriff-hyperframes-motion`（Phase 0 MotionVideoJob plan only）同 `~/.claude/skills/james-au-hyperframes-motion`（symlink 去 ~/.codex）唔改。
- 後端唔使改：所有 moments 讀現有 route（`src/postriff_phase2/hosted_app.py`）。

## Design spec

A. Home particle field（ParticleField，Canvas 2D）

API（保留現有 props，加 3 個）：
```ts
interface ParticleFieldProps extends React.HTMLAttributes<HTMLCanvasElement> {
  density?: number;   // 每 10,000 CSS px²，default 1.8
  max?: number;       // default 140；Home 120；coarse pointer 自動 ×0.4
  radius?: number;    // default 160
  mode?: 'repel' | 'attract';
  link?: number;      // default 110；coarse pointer 自動 0
  alpha?: number;     // component default 0.55；Home 由 0.42 降到 0.28
  fps?: 30 | 60;      // 新：frame cap，default 60
  quiet?: boolean;    // 新：true 時 pointer strength 目標 → 0、alpha ×0.5（composer focus／送出中）
  safeAreaRef?: React.RefObject<HTMLElement | null>; // 新：量度該元素 rect，區內點 alpha ×0.25
}
```
quiet／alpha 改用 ref 讀入 loop，唔好放入 useEffect deps，否則每次 focus 都會 teardown + reseed，粒子會跳。

Home 用法（喺 client：home-view.tsx 或者新 home-backdrop.tsx）：`<ParticleField className='absolute inset-x-0 top-0 -z-10 h-[28rem] sm:h-[44rem] [mask-image:linear-gradient(to_bottom,black,black_50%,transparent)]' density={2} max={120} radius={170} alpha={0.28} link={110} safeAreaRef={titleRef} quiet={composerFocused} />`

物理（維持現狀）：永久 drift 5–14 px/s；reactive velocity `exp(-2.2·dt)` 衰減；力 = (1−d/r)² × 260 × strength；strength 以 6/s 緩入緩出；邊界 wrap ±4px；twinkle 只改 opacity。

必修 6 項：
(1) Ghost pointer：移除 `document` 嘅 `pointerleave`；改聽 `window` `pointerout`（`relatedTarget === null` → active=false）同 `window` `blur`。
(2) MutationObserver callback 改 `() => { readColor(); if (!running) draw(); }`。
(3) 連線批次：alpha 分 3 bucket，每 bucket 一條 path、一次 `stroke()`。
(4) Frame cap：`if (last && t - last < 1000 / fps - 1) { raf = requestAnimationFrame(frame); return; }`，dt 用實際 elapsed。
(5) 觸控：`onMove` 忽略 `event.pointerType === 'touch'`；`coarse.matches` 時 `link = 0`、target 粒數 ×0.4；`coarse` change 時 reseed。另外 `navigator.connection?.saveData` 為 true 時行 reduced 路徑（一格靜止）。
(6) safeArea：ResizeObserver／scroll（passive, rAF-throttled）量 rect，唔好每 frame `getBoundingClientRect`；區內點 alpha ×0.25。

效能預算（中階 laptop，1440×700 CSS，DPR 2）：目標 frame callback self time p95 < 2ms。驗證：Chrome Performance 錄 10s；超出先 link 降 90，再 max 降 90。以上係目標，唔係已量度嘅數字。

暫停條件：`document.hidden`、IntersectionObserver 離開視窗、`prefers-reduced-motion`（一格靜止）、Save-Data；`quiet` 只係減弱唔停。

轉頁：/app ↔ /app/agent/[conversationId] 會 unmount；返 Home 會 reseed，屬預期，唔做跨頁保存。

Z 層：外框 `relative isolate`，canvas `-z-10`、`pointer-events-none`、`aria-hidden`、`print:hidden`；tour overlay `z-70` 蓋過。

誠實界線（寫入 JSDoc 同 motion-system §5）：粒子永遠唔讀 workspace 數據；唔因送出、run 完成、publish 而爆開或變色；數量唔對應任何嘢；唔加「AI 思考中」效果。

B. Hyperframes → live app 分工
- Tutorial clip：Hyperframes composition（16:9 或 1:1，≤ 8s，無聲），export `webm`（VP9）+ `mp4`（H.264）+ `poster.png`，每段 ≤ 400KB。
- 畫面內容：中性示範帳號同 UI 形狀；數字位用「—」；唔出 Connected ✓；盡量唔喺片入面放句子，標題／步驟文字放 HTML（`label`、caption），咁先可以跟 per-channel／UI 語言。角落 HTML 標「Example」。
- `TutorialClip({ src, poster, label, caption })`：`<video muted playsInline loop preload='none' aria-hidden>` + 旁邊可見文字 caption；IntersectionObserver 入視窗先 `play()`，出視窗 `pause()`；`useReducedMotion()` 或 Save-Data 時只顯示 poster。
- 用喺：Home 冇 conversation 時嘅 empty state（「一句話 → channel drafts → 你批核」）、Channels 冇連接（「Direct vs Assisted 係咩」）、Queue 空（「Nothing publishes until you approve」）、Library 空、marketing hero。
- 過時管理：UI 改咗相關畫面要 re-render；喺 dev gallery（例如 /dev 頁）列晒所有 clip 同 source commit，方便檢查。

C. 逐頁 alive moments（每頁 1–2 個，全部由真數據觸發）
1. Home：① ParticleField（純裝飾）；② Sidebar Queue #03 badge（已存在於 app-sidebar.tsx），唔重複做。
2. Overview：① 數字卡 NumberTicker 由 TanStack cache 上一次值滾去新值，首次載入直接顯示唔滾；② HeatCalendar 首次有數據先 reveal：per-week delay = `min(40ms, 300ms / weeks)`，或者整塊 opacity 250ms；unavailable 保持現有文字。
3. Ideas：① research candidate 以 layout pop-in 入列，reload 唔重播；② AgentDisclosure run log 行只喺真事件到達時用 #30。
4. Calendar：① 改期經 API 確認後 chip 用 `layoutId` 滑去新格（唔做 optimistic）；② 「而家」線用 `use-calendar-live.ts` 時鐘，每分鐘更新。
5. Pipeline：① snapshot 狀態變咗，卡片用 `layoutId`（包 `LayoutGroup`）由一欄滑去下一欄；② 欄計數 DigitSwap。
6. Library：保留現有真階段 badge（waiting→reading→sending→uploaded/failed），唔加 %、唔改 XHR；完成時 badge 轉 success 已足夠。
7. Channels：① 每個 capability 一個 AnimatedBadge（Direct/Assisted/Bridge/Unsupported + evidence tooltip）；Re-verify 後逐個比較 `capabilities[key].capabilityVersion`，只有 version 真係變咗嗰幾個 crossfade，stagger 40ms、總長 ≤ 300ms；絕對唔合成單一「Connected ✓」；② StatefulButton Re-verify。
8. Queue：① 排程倒數讀 `toEpoch(job.manifest.timing.utc)` 減真時鐘，< 1h 先顯示分鐘，用 DigitSwap；② provider 確認（`providerConfirmed`）先播 #10。
9. Analytics：① NumberTicker 只用喺有真整數嘅 metric；「Unavailable」係靜態文字（已存在於 analytics-view.tsx／metric-value.tsx），永遠唔顯示 0；② 如果將來加 sparkline，第一次有數據先 `pathLength` draw 300ms，refetch 唔重播（而家冇 sparkline，唔好為動畫而加）。
10. Inbox：① 用戶撳 refresh 或 refetch 後真係多咗 thread 先由頂 layout 插入；② suggested reply 一次過出現（opacity 250ms），唔扮逐字 stream，並保持現有「AI suggestion」標示。
11. Members：① invite 送出後新行帶 Pending AnimatedBadge 入場；refetch 見 `member.status` 變 active 先轉 badge。
12. Roles：① Checkbox #25 畫剔；「affects N members」N 由 useMembers 真數計，DigitSwap。
13. Audit（`web/src/features/workspace/audit-view.tsx`）：① 自上次到訪（localStorage per-viewer，try/catch）之後嘅新 event 背景由 primary/8 淡去 0，用 --duration-very-slow 500ms 延遲 1s 開始，只郁 opacity；唔當作已讀狀態；② refetch 有新行時由頂插入。
14. Brand：① voice profile activate 後 revision 號 DigitSwap；② RadioGroup 圓點滑動（已有）。
15. Memory：① 接受 proposal 後，proposal 卡 collapse（150ms），FileTree 對應檔案節點 opacity pulse 一次（唔用跨樹 layoutId，避免兩個 scroll container 之間 layout 計錯）；② 新增徽章「N to review」，N 讀 useMemoryProposals 長度，#03。
16. Profile：① revoke session 用 HoldActionButton，成功後行 collapse 150ms；② 「This device」讀 useSessions `current`。
17. Notifications：① Switch 撳完，API 成功後 ActionSwap「Saving…→Saved」；失敗回彈 + toast。
18. Billing：① allowance 條 scaleX 由 cache 舊值過渡到新值，NumberTicker（已存在）同步；unavailable 顯示文字唔顯示 0；② 新 LedgerEntry 由頂插入。
19. Privacy：① DataRequest 狀態 AnimatedBadge，refetch 真狀態；② Ready 時 download 掣 #10 一次。
20. Models：① available AnimatedBadge 讀 useModels；② TextScramble 只喺用戶揀 model 時播（已有）。
21. API：① 新 key 只展示一次，Copy 用 ActionSwap copy→check。（冇 webhook API，唔做 webhook 狀態。）

D. Onboarding 導航 primitives（大部分已存在）
- SidebarPulse：`[data-tour-pulse]` 改 `::after` 偽元素 `transform: scale(1→1.35)` + opacity 環，1.1s × 2 次，之後停喺靜態 2px ring（同 reduced-motion 一樣嘅 end state），唔好完全消失。注意 `::after` 需要 `position: relative`（已有）同 `pointer-events: none`。
- SpotlightMorph：保留一個 box + 200vmax 陰影；先喺低階機（CPU 4× throttle）量 jank，有問題先改做 `x/y` transform + `width/height`，或 fixed full-screen SVG mask。reduced-motion 已直接跳位。
- CrossPageContinuity：`store.lastRect` + `hop`（已有）；新頁量 target 前等 `.t-page-enter`（250ms）完成，再加 `requestAnimationFrame` ×2。
- HOP 進度條（已存在，L380–386）：linear 1400ms 代表真係會喺呢段時間後轉頁，係真計時，保留。
- 收合：卡片離開 150ms（--duration-quick）、入場 250ms（--duration-fast）。

## Implementation plan

1. **同負責 particle-field／onboarding 嘅 session 協調（兩者未 commit），確認邊個改；只 stage 指定路徑**（effort S）  
   檔案：`web/src/components/motion/particle-field.tsx, web/src/app/app/page.tsx, web/src/features/onboarding/*, web/src/styles/tour.css`
2. **ParticleField 必修 6 項：window pointerout/blur、暫停時轉 theme 重畫、3-bucket 批次 stroke、fps cap、pointerType touch 過濾 + coarse 降粒數冇線 + Save-Data、safeAreaRef；quiet／alpha 經 ref 入 loop 唔觸發 reseed**（effort M）  
   檔案：`web/src/components/motion/particle-field.tsx`
3. **將 ParticleField mount 由 Server Component 搬入 client（HomeView 或新 home-backdrop.tsx），接 composer focus → quiet、h1 ref → safeAreaRef；alpha 0.42→0.28；mobile 高度 28rem**（effort S）  
   檔案：`web/src/app/app/page.tsx, web/src/features/agent/home-view.tsx, web/src/features/agent/home-backdrop.tsx（新，可選）`
4. **量度：Chrome Performance 10s（light/dark × 至少 Notebook、Light Green、Mono，1440px + 375px），frame callback p95 < 2ms；axe／人手核對 h1、副標題、Tabs 對比度**（effort S）  
   檔案：`（驗證，無檔案）`
5. **motion-system 文件加「ambient 裝飾唔准讀數據」、「唔准扮 streaming／扮 %」同「Hyperframes／Remotion 分工 + 授權（Hyperframes Apache-2.0、GSAP standard license 限制、Remotion ≤3 員工門檻）」**（effort S）  
   檔案：`docs/postriff-motion-system.md, web/src/components/motion/README.md`
6. **tour.css pulse 改 ::after transform 環、2 次後停喺靜態 ring；spotlight 喺 4× CPU throttle 量 jank，有需要先改 transform／SVG mask；target 量度等 page-enter 完成**（effort M）  
   檔案：`web/src/styles/tour.css, web/src/features/onboarding/tour-overlay.tsx`
7. **第一批 moments（純重用、讀現有 hooks）：Channels per-capability capabilityVersion crossfade、Queue 倒數讀 manifest.timing.utc、Billing 條由舊值過渡、Overview ticker 由 cache 值起步、HeatCalendar reveal 以 300ms/weeks 封頂**（effort M）  
   檔案：`web/src/features/channels/channel-card.tsx, web/src/features/queue/job-row.tsx, web/src/features/billing/billing-view.tsx, web/src/features/overview/overview-view.tsx`
8. **第二批：Calendar／Pipeline layoutId 移動（API 確認後）、Memory proposal collapse + FileTree pulse + 「N to review」徽章、Audit 新事件淡出、Inbox refetch 插入（唔扮 stream）**（effort L）  
   檔案：`web/src/features/calendar/calendar-view.tsx, web/src/features/pipeline/pipeline-view.tsx, web/src/features/memory/memory-view.tsx, web/src/features/memory/proposal-card.tsx, web/src/features/workspace/audit-view.tsx, web/src/features/inbox/inbox-view.tsx`
9. **TutorialClip component（video + poster + HTML caption + reduced-motion／Save-Data + IntersectionObserver play/pause），接 empty state**（effort S）  
   檔案：`web/src/components/motion/tutorial-clip.tsx（新）`
10. **用 Hyperframes（motion-graphics workflow）做 3–4 段中性示範 clip（片內盡量冇文字），每段 ≤ 8s、≤ 400KB，export webm/mp4/poster；source 唔入 web bundle；記錄 source commit 方便過時檢查**（effort L）  
   檔案：`motion-src/（新，repo 根）, web/public/motion/*`

## Risks

- particle-field.tsx、page.tsx、onboarding 全部係另一個 session 未 commit 嘅 WIP；whole-tree commit 會掃走人哋嘅工作，一定要協調兼 stage by path。
- Server Component 陷阱：quiet／safeArea 需要 client state，唔搬 mount 位就做唔到；quiet 放入 useEffect deps 會每次 focus 都 reseed，粒子跳位。
- 對比度：foreground 色點喺 h1／副標題／Tabs 後面（冇底色），淺色 theme（Notebook、Light Green）可能拉低 muted-foreground 可讀性；要實測 10 個 theme × light/dark。
- Ghost pointer：document 上嘅 pointerleave 唔可靠，滑鼠由 canvas 範圍直接離開 window 後，點仍然被最後位置排斥。
- Canvas fillStyle 收 oklch() 要較新瀏覽器；唔支援時 fillStyle 保持舊值。readColor 後比較 ctx.fillStyle，冇變就用 fallback。
- 120Hz／ProMotion 屏幕冇 fps cap 會令 CPU 成本加倍。
- 假 motion 誘惑：Inbox 逐字 stream、Library 上載 %、HeatCalendar 長 stagger 都好易做出嚟，但前兩者冇真數據支撐、後者違反 300ms 上限。
- Tutorial clip「示範數字被當真」同語言問題：片入面唔可以有似用戶數據嘅 count、進度或者 Connected ✓；片內文字唔跟 per-channel／UI 語言，所以文字要放 HTML。
- Hyperframes render 要 pinned CLI 同 headless Chrome，唔屬 web build；UI 改版後 clip 會過時。
- 授權：Hyperframes 係 Apache-2.0，但預設 runtime GSAP 行 Standard License，禁止用喺同 Webflow 競爭嘅 no-code 視覺動畫工具——MotionVideoJob 產品化前要核對或者改 CSS／WAAPI adapter。Remotion 超過 3 員工要 company license，5.0 條款會變。
- Tour spotlight animate width/height + 200vmax box-shadow，每 frame 重繪全屏陰影，低階機可能 jank；tour.css pulse infinite box-shadow 違反 transform/opacity 規則。
- Calendar／Pipeline layoutId 如果做成 optimistic，API 失敗時會出現「郁咗但冇改」嘅假狀態；一定等 API 確認。
- Channels crossfade 如果用 channel 級 trigger 而唔係逐個 capabilityVersion 比較，會令所有 badge 一齊閃，視覺上似 blended 狀態。
- Audit「新事件」用 localStorage，per-browser、可能被清走；只係便利功能，唔可以當已讀狀態。

## Sources

- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-motion-system.md
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/motion/README.md
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/motion/particle-field.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/app/app/page.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/app/app/template.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/agent/home-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/agent/composer.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/styles/transitions.css
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/styles/tour.css
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/onboarding/tour-overlay.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/onboarding/store.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/onboarding/tours.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/themes/active-theme.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/lib/ease.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/lib/api/hooks.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/lib/api/types.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/library/use-upload-queue.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/overview/overview-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/calendar/use-calendar-live.ts
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/pipeline/pipeline-card.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/inbox/inbox-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/workspace/audit-view.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/layout/app-sidebar.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/skills/postriff-hyperframes-motion/SKILL.md
- /Users/ouxianxing/.claude/skills/hyperframes-animation/SKILL.md
- https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- https://registry.npmjs.org/@tsparticles/react
- https://registry.npmjs.org/@tsparticles/slim/latest
- https://github.com/oframe/ogl
- https://registry.npmjs.org/hyperframes/latest
- https://gsap.com/community/standard-license/

## 覆核記錄

- 改正：而家 alpha 係 0.42 → 寫明「Home 傳入 0.42，component default 0.55」
- 改正：Home 用法 quiet={composerFocused} 同 safeArea='[data-tour="home-title"]' 可以喺 page.tsx 直接做 → 將 ParticleField mount 搬入 HomeView（client）或者起一個 client wrapper；safeArea 用 ref 或 data-slot，唔好借用 data-tour
- 改正：HOP 進度條（ProgressHairline）係新 primitive → 標為「已存在」，只保留規格描述
- 改正：Queue 倒數讀 scheduledAt → 用 toEpoch(job.manifest.timing.utc) 減 use-calendar-live 嘅 now 值
- 改正：Library 上載進度用 XHR upload.onprogress 真 bytes → 保留現有真階段式進度，唔改 client 做 XHR（base64 JSON body bytes ≠ 檔案 bytes，而且要改 web/src/lib/api/client.ts）
- 改正：Inbox：poll 返嚟新 thread、suggested reply 用 #30 真 stream → 刪除 streaming；只喺 refetch 後真係多咗 thread 先 layout 插入
- 改正：API 頁 webhook delivery 狀態（有 field 先做） → 直接移除呢項
- 改正：Overview HeatCalendar 按週欄 stagger 40ms，最多 7 欄 = 280ms → per-column delay = min(40ms, 300ms / weeks)，或者整塊 opacity reveal
- 改正：Audit 檔案喺 web/src/app/app/workspace/audit/* → 改做 web/src/features/workspace/audit-view.tsx
- 補上遺漏：page.tsx 係 Server Component：quiet／safeArea 要喺 client（home-view.tsx 或者新 client wrapper）做，research 冇發現。
- 補上遺漏：data-tour 係 tours.ts 嘅 selector namespace；借用 data-tour="home-title" 做 safeArea 會混淆 tour 定位，應該用 ref 或者 data-slot。
- 補上遺漏：Remotion 免費門檻（個人／≤3 員工／非牟利）同 5.0 條款變更；Hyperframes 本身 Apache-2.0；GSAP standard license 對『no-code 視覺動畫工具』嘅限制，影響 MotionVideoJob 產品化。
- 補上遺漏：tsParticles 4.4.0 支援 React 19（peer >=16.8）、MIT、2026-08 仲有 release——否決理由要係 scope／bundle，唔係相容性。
- 補上遺漏：Queue 時間欄位實際係 manifest.timing.utc（字串），要用 toEpoch()；現成時鐘 hook 喺 web/src/features/calendar/use-calendar-live.ts。
- 補上遺漏：Canvas 喺 Home 同 conversation route（/app/agent/[conversationId]）之間嘅行為：只 mount 喺 /app，轉頁 template re-mount 會 reseed，粒子位置會跳；要講明係預期。
- 補上遺漏：低耗電：navigator.connection.saveData／電池冇處理；至少喺 coarse pointer 或 Save-Data 時直接用 reduced 路徑。
- 補上遺漏：Tutorial clip 要有 captions/文字替代同 i18n：worldwide languages 計劃（per-channel locale）代表影片入面嘅英文字唔會跟用戶語言，應該盡量唔喺影片入面放文字，文字交返 HTML。
- 補上遺漏：Tutorial clip 會隨 UI 改版過時：要一個檢查位（例如 dev gallery 或 PR checklist）而唔係只寫喺 risks。
- 補上遺漏：Tour pulse 限 2 次之後，如果用戶未撳，冇任何提示——要保留靜態 ring 作為 end state（同 reduced-motion 一樣），唔係完全消失。
