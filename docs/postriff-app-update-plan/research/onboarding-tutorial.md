# 專題研究：PostRiff onboarding + tutorial system（first-run welcome、跨頁 guided tour 同 navigate animation、coach marks、教人嘅 empty states、Help／Replay、progress persistence）

> 研究 agent 起稿（包括網上資料），再由另一個 agent 重新 fetch 關鍵來源同 grep codebase 覆核。

## 建議

建議：**唔用第三方 tour library，喺另一個 session 已經砌好嘅 v1（`web/src/features/onboarding/`，約 1100 行，untracked）上面做 v2**，繼續用 Base UI Dialog／DropdownMenu + motion v11 + external store。v1 方向啱：一個大 box-shadow 盒做 spotlight；template re-mount 由 `tourStore` 接力；`lastRect` 令新一頁由同一個長方形 morph 過去，正正就係 James 要嘅 navigate animation。唔揀 library 嘅真正原因係呢個 morph：react-joyride v3（MIT，3.2.0；3.0.0 喺 2026-03-23 出，支援 React 19，有 focus trap 同 async `before` hook，其實可以包到跨頁）、NextStep（MIT，2.3.0，有 `nextRoute` 同單一 `selector`，peer 係 motion）同 driver.js（MIT，1.8.0）都係自己畫 spotlight 同 tooltip，做唔到「由 sidebar link 同一個框 morph 去下一頁 target」，而且唔跟 transitions.css token。Onborda（1.2.5，2024-12 之後冇 release，peer 係 framer-motion 同 Radix）已經停咗。Shepherd.js 同 intro.js 係 AGPL-3.0，收費 SaaS 要買商業 license，出局。

v2 要改嘅重點：(a) **honesty**：`use-tour-context.ts` 嘅 `channelCount/draftCount/jobCount … ?? 0` 喺 API 出錯時會變 0，要改做 `Fact<T>`（ready／unavailable），copy 分「有／冇／讀唔到」三種寫。「Eleven kinds of post」而家啱（`QUICK_STARTS` 真係 11 個），但 `tours.ts` 同 `home-view.tsx:323` 兩處都寫死，要改讀 `QUICK_STARTS.length`，費事之後 drift。(b) **navigate animation 唔用計時器**：v1 用 1400ms 自動轉頁（reduced motion 下都照轉）。改做由用戶撳「Next: Channels」觸發：spotlight 用 ≤250ms morph 去 sidebar link，然後 `router.push`，新一頁由同一個 rect 接住。冇倒數、冇 progress bar，唔會有「扮進度」嘅疑慮，亦符合 WCAG change-on-request。(c) **sidebar 邊界**：nav group 閂住嗰陣 link 唔喺 DOM，v1 會無限 rAF。要先打開所屬 group，再唔得就用 group trigger rect，最後先 fallback 去 fade；tour 完要還原 sidebar 同 group 本來嘅狀態。(d) **motion 規則**：overlay 而家開同收都係 200ms，要改做開 250ms、收 150ms。(e) **a11y**：加 `inert`（app root）+ 卡內 Tab loop + `aria-live` 步數；keydown 唔好掛 window。(f) **progress 上 server**：開新 migration 加 `pr_profiles.onboarding jsonb`。`update_profile` 而家係整欄覆寫嘅 upsert，要為 onboarding 另寫 jsonb merge SQL；而 `GET /api/me` 會 touch session，client 要用 PATCH response `setQueryData`，唔好 invalidate。

有一樣要 James 決定：`src/postriff_phase2/store.py:359` 冇 active voice revision 就拒絕 approval，同「Remind, don't block」有張力。v1 brand step 照實講「scheduling needs an active voice profile」係誠實嘅，但係咪保留呢條硬規則，應該由 James 拍板，唔係 tour 決定。tour 只係如實反映現況，用提醒語氣寫。

## 考慮過嘅選項

| Option | Verdict | Why |
|---|---|---|
| Build our own（v1 再加強：Base UI + motion v11 + external store） | 揀呢個 | 零新 dependency；spotlight、卡同 hop 都用 SPRING_LAYOUT 同 transitions.css token；step 讀真 facts，按權限 skip；template re-mount + tourStore 已經做到跨頁接力同 rect morph。代價係 a11y（inert、focus loop、live region）同 placement 要自己維護，而且要處理 sidebar group 閂住嘅 edge case。 |
| react-joyride v3（3.2.0，MIT，React 16.8–19） | 次選 | v3 換咗 Floating UI，有每步可控嘅 focus trap 同 focus restore，亦有 async `before`/`after` hook，可以喺 hook 入面 router.push 再等 target，所以跨頁係包得到。唔揀係因為 spotlight 同 tooltip 係佢自己嘅 DOM，冇「由上一頁 rect morph 過嚟」嘅概念；要逐個 style override 先跟到 Base UI 主題；仲要多約 10 個 dependency（floating-ui、deepmerge、scroll 等）。 |
| NextStep（nextstepjs 2.3.0，MIT，2026-07-20） | 參考 | Next.js 原生有 `nextRoute`／`prevRoute`，route 完會等 `selector` 出現先顯示；peer 係 motion。但每步只得一個 selector，冇 fallback 陣列；hop 動畫同卡要 custom；冇「先 spotlight sidebar link 再轉頁」；條件 step 要自己包。用咗都係 fork 級客製。 |
| driver.js（1.8.0，MIT） | 唔揀 | 最輕、零 dependency，但係 vanilla DOM，popover 唔入 React tree，唔用我哋 Button 同 token；官方 multi-page 做法係自己存 step 再喺新頁 re-drive，冇 morph。 |
| Onborda（1.2.5，MIT） | 唔揀 | 2024-12-22 之後冇 release；peer 係 framer-motion 同 @radix-ui/react-portal，同我哋 motion + Base UI 唔夾；有停止維護風險。 |
| Shepherd.js（15.3.0） | 唔揀 | AGPL-3.0 + 商業 license 雙授權；官方寫明公司有收入就要買商業 license；framework-agnostic，跨頁一樣要自己接駁。 |
| intro.js（8.5.0） | 唔揀 | AGPL-3.0，商業用途要付費 license；冇 React／router 整合。 |

## 點樣接入 codebase

**現有 v1（沿用）**
- Mount 位：`web/src/app/app/template.tsx` render `<TourMount />`。template 每次轉頁都 re-mount，`useSidebar()`、kbar、TanStack Query 嘅 provider 都喺 `web/src/components/layout/app-shell.tsx` 上面，所以攞得到。跑緊嘅 tour 住喺 `web/src/features/onboarding/store.ts`（module store + `useSyncExternalStore`）。
- Overlay：`web/src/features/onboarding/tour-overlay.tsx`（portal 去 body，`z-70`，蓋過 `web/src/components/ui/dialog.tsx` 嘅 z-50 同 sonner）。Registry：`web/src/features/onboarding/tours.ts`（WELCOME_TOUR 10 步 + 8 個 PAGE_TOURS）。Welcome：`welcome-dialog.tsx`。Help：`help-menu.tsx`，由 `web/src/components/layout/header.tsx:44` render；kbar：`web/src/components/kbar/index.tsx:76,86`。Pulse：`web/src/styles/tour.css`（由 `src/styles/globals.css:18` import）。
- Page enter：`.t-page-enter`，喺 `web/src/styles/transitions.css:252`（`--page-slide-dur` / `--page-fade-dur` 250ms、`--page-slide-distance` 8px）；modal token 係 `--modal-open-dur` 250ms / `--modal-close-dur` 150ms（:69–70）。Spring：`web/src/lib/ease.ts:37` `SPRING_LAYOUT`。
- Sidebar：`web/src/components/layout/app-sidebar.tsx` 由 `web/src/config/nav-config.ts` 砌 link。nav group 係 collapsible（:140–143），閂住時 link 唔喺 DOM；Queue 嘅 aria-label 會帶 count（:177），所以一定要用 `a[href]` 揀。
- 已有 anchor（約 60 個，唔好 rename）：`composer`、`composer-channels`（features/agent/composer.tsx）；`channels-connect/summary/filter/empty`、`companion-section`（channels-view.tsx）；`channel-card`、`capability-chips`、`channel-actions`（channel-card.tsx:205,251,281，第一張卡）；`queue-approvals`、`queue-list`（queue-view.tsx，FirstRun 同正常 layout 互斥，所以唯一）；`calendar-grid`；`voice-setup`（brand-view.tsx）；`memory-files`；`overview-stats/attention/next-up/channels/activity`；`getting-started`（getting-started.tsx:70）；`analytics-coverage/freshness/table/row/unavailable`；`inbox-empty/threads`；`library-*`、`ideas-*`、`pipeline-*`、`roles-*`。**唯一未有**嘅係 Home 嘅 quick starts `<section>`（`web/src/features/agent/home-view.tsx` 約 :318）。
- 真數據：`web/src/features/onboarding/use-tour-context.ts` 讀 `useSnapshot()`、`useChannels()`（`web/src/lib/api/hooks.ts`）同 `checkAccess()`（`web/src/lib/auth/access`）。`web/src/features/overview/getting-started.tsx:29–36` 用同一組 signal，而且出錯時 return null（正確）。v2 抽一個共用 `use-setup-facts.ts`。
- 教學 empty state 範本：`web/src/features/queue/queue-view.tsx:527–535` 嘅 `FirstRun`（讀 hasDrafts、hasReadyAccount、canSchedule）；primitive 係 `web/src/components/ui/empty.tsx`。
- **Server（要新增）**：`pr_profiles` 喺 `migrations/postriff/001_phase2.sql`（user_id、display_name、deleted_at）+ `011_account_preferences.sql`（time_zone、locale、alert_new_device）。`src/postriff_phase2/hosted.py:570–590` `me()`（會 `_touch_session`，有機會觸發 new-device alert）；`:592–626` `update_profile()`，whitelist 加通用 upsert（整欄覆寫）。Route 係 `src/postriff_phase2/hosted_app.py:358`（GET）、`:360`（PATCH）。前端：`web/src/lib/api/types.ts`（`Me`、`ProfileChanges`）、`web/src/lib/api/client.ts:119–121`（`me`、`updateProfile`）、`hooks.ts` `useMe()`。Profile 測試喺 `tests/test_postriff_account_security.py` 同 `tests/phase2/postgres_account.py`；RLS 已經喺 `tests/phase2/rls.sql:48` 用 table level 包 `pr_profiles`。Privacy inventory 喺 `src/postriff_phase2/privacy.py`（:14 附近）。
- 相關 product rule：`src/postriff_phase2/store.py:359` 冇 active voice revision 就拒絕 approval；`memory.py:109` 嘅 copy 同佢一致。

## Design spec

## 0. Component tree（v2）
```
app/app/template.tsx
└─ <div.t-page-enter>{page}<TourMount/></div>
   TourMount (features/onboarding/tour-mount.tsx)
   ├─ <OnboardingSync/>   useMe().data.onboarding → hydrate store；寫入 debounce 500ms PATCH，用 response setQueryData(keys.me)
   ├─ <WelcomeDialog/>    Base UI Dialog（250 開 / 150 收，自帶 focus 管理）
   ├─ <CoachMarkGate/>    每頁一次；hasContent 為真先出
   └─ <TourOverlay/>      portal → body，z-70；開緊時 app root set inert
      ├─ Spotlight（motion.div，box-shadow 0 0 0 200vmax）
      ├─ TourCard role=dialog（Tab loop；keydown 掛喺 overlay root）
      └─ SrAnnouncer aria-live=polite
```

## 1. data-tour 規則（沿用，唔 rename）
- 沿用現有約 60 個 anchor 名。新 anchor 用 `<page>-<thing>` kebab-case，例如新加嘅 `home-quick-starts`。
- 同一時間一個 anchor 只可以喺 DOM 出現一次；list 只標第一行（例：`tour={index === 0}`）；互斥 layout 可以用同一個名（例：queue FirstRun 同正常 layout）。
- Step target 陣列順序：主 anchor → empty/first-run anchor → heading fallback；`main h1` 只可以做最後 fallback。
- 加一個 dev-only 檢查（例：喺 `/dev` 或 test），逐頁確認 registry 入面每個主 anchor 存在而且唯一。

## 2. Registry shape
```ts
type Fact<T> = { status: 'ready'; value: T } | { status: 'unavailable' };
interface SetupFacts {
  voice: Fact<number | null>;      // active revision；null = 未 set up
  channels: Fact<number>; drafts: Fact<number>; jobs: Fact<number>; needsReview: Fact<number>;
  quickStartCount: number;         // QUICK_STARTS.length
  can: { edit: boolean; manageConnections: boolean; reply: boolean };
  settled: boolean;                // 所有 query 已經 success 或 error（唔係 loading）
}
interface TourStep {
  id: string; route: string; stop: string; target: string[];
  title: string; body: (f: SetupFacts) => string;   // 有／冇／unavailable 三種
  when?: (f: SetupFacts) => boolean;                // 權限 skip
  doneWhen?: (f: SetupFacts) => boolean;            // 已做好 → 確認句
  placement?: 'top'|'bottom'|'left'|'right';
  missing?: 'skip' | 'explain';
}
interface Tour { id: string; version: number; title: string; route?: string; kind: 'guided'|'page'; steps: TourStep[]; hasContent?: (f: SetupFacts) => boolean }
```
每個 step 一條 route；progress key 係 `${id}@${version}`。

## 3. First-run welcome + guided tour
觸發條件：`me` 已 load、`facts.settled`、progress 冇 `welcome@v` 嘅 completed 或 dismissed、路徑係 `/app*` 但唔係 `/app/agent/*`。**如果 voice、channels、jobs 全部 ready 而且 > 0（即係現有、已經 set up 好嘅用戶），唔自動開 dialog**，只出一次 sonner nudge「Take the tour」，並記低 nudged。
Steps（8 步，全部讀 facts）：
1. `composer`（/app，when can.edit）
2. `home-quick-starts`（/app）：「{quickStartCount} kinds of post」
3. `channel-card` → `channels-empty` → heading（/app/channels）：逐級講 Direct／Assisted／Unsupported，文字先行，顏色只係輔助；channels unavailable 就講「暫時讀唔到 account 狀態」。
4. `queue-approvals` → `queue-list`（/app/queue）：needsReview ready 先講數字。
5. `calendar-grid`（/app/calendar）
6. `voice-setup`（/app/workspace/brand，when can.edit）：`doneWhen` voice.value≠null → 「Your voice is active (revision n)」。未 set up 就照實講現行規則，但用提醒語氣（等 James 決定 store.py:359 嘅去留）。
7. `getting-started` → `overview-stats`（/app/overview）：checklist 做晒就講「Setup is complete」。
8. `help`：講 Help menu 同 ⌘K 可以 replay。
Memory 移去 `memory-tips` page tour。

## 4. Navigate animation（撳掣觸發，唔用計時器）
狀態機：`shown(A) → hop → waiting → shown(B)`
1. 下一步喺另一條 route 時，主掣寫「Next: {stop}」。撳落：
   - 確保 link 喺 DOM：mobile 開 sheet；icon mode 展開；**target 所屬 nav group 閂住就先打開**。
   - Spotlight 用 SPRING_LAYOUT 由 target A morph 去 `[data-slot=sidebar] a[href=route]`（最長約 250ms），link 加 `data-tour-pulse`；卡 cross-fade 做「Opening {stop}」。
   - morph 完（或者 250ms 上限）就 `setLastRect(linkRect)` → `hopTo(route)` → `router.push(route)`。
   - 搵唔到 link：用 group trigger rect；再搵唔到就 `lastRect=null`，spotlight 直接 fade。rAF 搵 link 最多 300ms，唔好無限 loop。
2. 新頁：`.t-page-enter` 照行；overlay `AnimatePresence initial={false}` 由 lastRect 開始，backdrop 唔閃。
3. waiting：等 `facts.settled` 之後先開始計 5000ms 搵 target。卡寫「Opening {stop}…」加 Spinner（真係等緊 DOM）。
4. shown(B)：`scrollIntoView({block:'center', behavior: reduce?'auto':'smooth'})`；spotlight spring 去 target；rAF 追 900ms；focus 去卡。
5. 搵唔到：`skip` → SrAnnouncer 讀「{stop}: nothing to show here yet, skipped」；`explain` → 卡置中講原因。
6. Tour 完或者 dismiss：還原 sidebar open/openMobile 同 nav group 本來嘅狀態；focus 返去開始前嘅元素。
時間：overlay 開 250ms、收 150ms；reduced motion 下全部 duration 0，冇 pulse 動畫（tour.css 已有靜態 2px ring）。Spotlight 盒正常模式可以郁 left/top/width/height；如果 mobile 實測 jank，就改做 transform x/y + width/height。

## 5. Coach marks
`CoachMarkGate` 出現條件：`pageTourFor(pathname)` 有 tour、welcome 已經決定咗、未 nudge 過、`tour.hasContent(facts)` 為真、冇 tour 跑緊、冇 dialog 開緊（`document.querySelector('[role=dialog][data-open]')`）。出 sonner toast「New to {page}?」+「Show me」，8 秒自己消失，只記一次。冇內容就唔出，交畀 empty state 教。

## 6. 教人嘅 empty state（由 queue FirstRun 抽出）
- 由 `queue-view.tsx` 嘅 `FirstRun` 抽出 `TeachEmpty`：`Empty > EmptyHeader(EmptyMedia, EmptyTitle, EmptyDescription) > EmptyContent(主動作, 次動作)` + `data-tour="<page>-empty"`。
- Title 講現狀；description 講「做咗 X 之後，呢度會出現 Y」。
- 主動作係真 route 或者真 action；冇權限就唔 show 掣，改做文字「Ask a workspace owner to…」。
- 冇假 row、冇示範數字、唔用 skeleton 扮資料。
- 讀唔到資料係另一個 state：「Couldn't load」+ Retry，唔准用 empty 代替。
- 規則只可以提醒，唔寫「你要先…先可以」。

## 7. Help／Replay
HelpMenu：Take the tour、Tips for {page}、Jump to a page ⌘K、Reset tips（server 同 local 一齊清）。KBar 加 `tourResetAction`。Overview checklist 做完之後，頁尾加「Replay the tour」細 link。

## 8. Persistence
- Server：`pr_profiles.onboarding jsonb not null default '{}'`，加 `check (pg_column_size(onboarding) <= 8192)`。Shape：`{ v:1, tours: { "<id>@<ver>": { completedAt?, dismissedAt?, nudgedAt? } } }`。
- `PATCH /api/me {onboarding:{tours:{…}}}`：驗證 key 符合 `^[a-z0-9-]+@\d+$`，值係 epoch 數字，最多 64 個 tour；SQL 用 `jsonb_set(coalesce(p.onboarding,'{}'),'{tours}', coalesce(p.onboarding->'tours','{}') || %s::jsonb)`，唔行通用覆寫；RETURNING 加 onboarding。Reset 用 `{onboarding:{reset:true}}` 清空。
- `GET /api/me` 回傳 `onboarding`。
- Client：optimistic 更新 store，debounce 500ms PATCH，response `setQueryData(keys.me)`，唔 invalidate（避免多次 touch session）。失敗就寫 `localStorage['postriff-onboarding:'+userId']`，下次 load 按 timestamp 取較新；舊 key `postriff-onboarding`（冇 userId）只喺第一次讀咗做 migrate，然後刪除。active、hop、lastRect 只存記憶體。
- Privacy：`privacy.py` inventory 加 onboarding progress（retention：跟 account，刪 account 時清）。

## 9. 讀真 workspace state
所有數字嚟自 SetupFacts；unavailable 有自己嘅 copy，永遠唔當 0。done 嘅 step 用確認句，唔扮新手教學；冇權限就 skip，分母跟 `visibleSteps`。唔 seed demo data，唔自動 connect 或 draft。

## 10. General-audience copy
每句 designer、老師、店主、developer 讀落都一樣明；唔出現 James 嘅 brand 或鋼琴。Capability 一律寫 Direct／Assisted／Unsupported，文字先行，唔寫「Connected ✓」，唔單靠 Green／Amber／Grey（v1 channels-tips 要改）。數字唔寫死。一步一個重點：body ≤ 2 句、≤ 200 字元。語氣用提醒。字串留喺 registry，等 worldwide-languages 之後抽出。

## 11. a11y
TourCard `role=dialog aria-modal aria-labelledby aria-describedby`；開緊時 overlay 以外嘅 app root 加 `inert`，卡內 Tab 循環；Esc = dismiss（先檢查 `event.defaultPrevented`，keydown 掛喺 overlay）；←／→ 上下步，焦點喺 textarea 或 input 時唔攔；SrAnnouncer 讀「{tour}, step n of m: {title}」；完咗 focus 返原位；mobile 卡釘底（inset-x-3 bottom-3）。

## Implementation plan

1. **同 parallel session 協調：確認 v1 由邊個 commit，claim migration 編號（檢查 worldwide-languages 同 2FA 計劃有冇佔用 013）；v1 commit 之前唔好改 onboarding 檔**（effort S）  
   檔案：`web/src/features/onboarding/*; migrations/postriff/`
2. **抽 useSetupFacts()：Fact<T> ready／unavailable，加 settled 同 quickStartCount；tour 同 GettingStarted 共用**（effort S）  
   檔案：`web/src/features/onboarding/use-tour-context.ts → use-setup-facts.ts; web/src/features/overview/getting-started.tsx; web/src/config/quick-starts.ts (read only)`
3. **Registry v2：body 改成 facts function（三種 copy）；加 version、doneWhen、missing、Tour.hasContent；welcome 定 8 步，memory 移去 page tips；capability copy 文字先行；兩處寫死嘅 Eleven 改讀 QUICK_STARTS.length**（effort M）  
   檔案：`web/src/features/onboarding/tours.ts; web/src/features/agent/home-view.tsx`
4. **補唯一欠缺嘅 anchor：Home quick starts section 加 data-tour='home-quick-starts'；加 dev anchor 存在兼唯一檢查**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx`
5. **Overlay 修正：hop 由撳掣觸發（刪 HOP_MS 計時器同 progress bar）；nav group 閂住時先打開，冇 link 就 fallback，rAF 有上限；tour 完還原 sidebar 狀態；開 250 收 150；inert + Tab loop + SrAnnouncer；keydown scope；FIND_MS 由 facts.settled 開始計**（effort M）  
   檔案：`web/src/features/onboarding/tour-overlay.tsx; web/src/features/onboarding/store.ts; web/src/styles/tour.css; web/src/components/layout/app-sidebar.tsx (read only)`
6. **Server persistence：migration 加 pr_profiles.onboarding jsonb + size check；update_profile 為 onboarding 寫專用 jsonb merge SQL 兼驗證、reset；me() 回傳 onboarding；privacy inventory 加條目；加測試（驗證、merge 唔覆寫其他 tour、reset、刪 account）**（effort M）  
   檔案：`migrations/postriff/0NN_onboarding_progress.sql; src/postriff_phase2/hosted.py; src/postriff_phase2/hosted_app.py (route 不變，只確認); src/postriff_phase2/privacy.py; tests/test_postriff_account_security.py; tests/phase2/postgres_account.py`
7. **Client sync：Me、ProfileChanges 加 onboarding；updateProfile return type 擴充；OnboardingSync 由 useMe hydrate，debounce PATCH，setQueryData，唔 invalidate；localStorage key 帶 userId，舊 key 做一次 migrate**（effort M）  
   檔案：`web/src/lib/api/types.ts; web/src/lib/api/client.ts; web/src/lib/api/hooks.ts; web/src/features/onboarding/store.ts; web/src/features/onboarding/onboarding-sync.tsx`
8. **Welcome 同 CoachMarkGate：已 set up 好嘅用戶唔自動開 dialog，改一次性 nudge；coach mark 要 hasContent，有 dialog 或 tour 開緊就唔出**（effort S）  
   檔案：`web/src/features/onboarding/tour-mount.tsx; web/src/features/onboarding/coach-gate.tsx; web/src/features/onboarding/welcome-dialog.tsx`
9. **由 queue FirstRun 抽 TeachEmpty，分開 empty 同 unavailable；逐頁套用（channels、calendar、inbox、library、analytics、memory）**（effort M）  
   檔案：`web/src/features/queue/queue-view.tsx; web/src/features/onboarding/teach-empty.tsx; web/src/components/ui/empty.tsx (reuse); web/src/features/*/…-view.tsx`
10. **Help 入口：kbar 加 tourResetAction（清 server + local）；overview checklist 做完加 Replay link**（effort S）  
   檔案：`web/src/components/kbar/index.tsx; web/src/features/onboarding/help-menu.tsx; web/src/features/overview/overview-view.tsx`
11. **將 store.py:359「冇 active voice 唔准 approve」嘅 rule 張力交畀 James 決定；決定之前 brand step copy 照實講但用提醒語氣**（effort S）  
   檔案：`src/postriff_phase2/store.py (read only); docs/`
12. **驗證：喺 :3100 行 tour，覆蓋 sidebar icon mode、Workspace group 閂住、mobile、reduced motion、viewer role、channels API 出錯、已 set up 用戶；唔好撳 approve／schedule／send；API restart 後 re-seed；按 path stage commit**（effort S）  
   檔案：`web/ (preview pane on localhost:3100)`

## Risks

- Parallel session 仲改緊 web/src/features/onboarding/、template.tsx、header.tsx、kbar（untracked 同未 commit）。實作前要協調；一定要按 path stage，唔好 whole-tree commit。
- Migration 編號衝突：幾個 session 可能同時開 013；deploy 前要對齊 hosted-precheck.sql。
- Honesty bug（已存在）：use-tour-context.ts 嘅 channelCount / draftCount / jobCount `?? 0` 喺 API 出錯時會講「Nothing is connected yet」。
- Nav group 閂住時 sidebar link 唔喺 DOM，v1 `light()` 會無限 rAF，morph 由畫面中間開始；tour 亦會改寫用戶嘅 sidebar 開合狀態。
- GET /api/me 會 touch session，仲可能觸發 new-device alert；如果 onboarding sync 用 invalidate + refetch，會多咗 DB 寫入，甚至出錯 alert。
- update_profile 係整欄覆寫；如果照抄做 onboarding，兩部機同時寫會互相覆蓋 progress。
- 已 set up 好嘅現有用戶，deploy 之後會彈 welcome dialog，觀感似 regression；要用 facts gate。
- store.py:359 冇 active voice 唔准 approve，同 Remind, don't block 有張力；如果 James 改規則，brand step copy 要同步改。
- a11y：冇 focus trap；window keydown 同 kbar、Base UI Dialog 會撞 Escape 或 Enter。
- Spotlight 盒郁 left/top/width/height 係 layout animation，低階 mobile 可能 jank；reduced motion 下已經係 duration 0。
- z-70 overlay 會蓋住 Base UI Dialog 同 toast；coach mark 同 welcome 唔可以同 tour 同時出。
- FIND_MS 由 mount 開始計，慢 query 嘅頁（analytics）可能被誤判冇 target 而跳步；要由 facts.settled 開始計。
- Dev harness 會真係 publish 去 Threads：驗證 tour 時唔好撳 approve／schedule／send；API restart 會清 dev DB，要 re-seed。

## Sources

- https://registry.npmjs.org/nextstepjs (2.3.0, MIT, 2026-07-20; peer motion>=11, next/react-router/remix optional) — 2026-09-16 重新查詢
- https://registry.npmjs.org/onborda (1.2.5, MIT, 2024-12-22; peer framer-motion, @radix-ui/react-portal)
- https://registry.npmjs.org/react-joyride (3.2.0 2026-07-09; 3.0.0 2026-03-23; react '16.8 - 19'; deps 包括 @floating-ui/react-dom, @fastify/deepmerge, scroll)
- https://registry.npmjs.org/driver.js (1.8.0, MIT, 2026-07-17)
- https://registry.npmjs.org/shepherd.js (15.3.0, AGPL-3.0) ; https://registry.npmjs.org/intro.js (8.5.0, AGPL-3.0)
- https://react-joyride.com/docs/new-in-v3 (React 16.8–19、Floating UI、focus trap hook、async before/after)
- https://nextstepjs.com/docs/nextjs/routing (nextRoute/prevRoute、selector、等 element 出現)
- https://docs.shepherdjs.dev/guides/license/ (AGPL + 商業 license；有收入嘅公司要買)
- https://driverjs.com/docs/multi-page-tour
- https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/onboarding/ (parallel session v1, untracked)
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/components/layout/app-sidebar.tsx
- /Users/ouxianxing/Documents/James-Au-Studio/web/src/features/queue/queue-view.tsx (FirstRun)
- /Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-motion-system.md §5
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/hosted.py (me(), update_profile)
- /Users/ouxianxing/Documents/James-Au-Studio/src/postriff_phase2/store.py:359 (voice revision gate)

## 覆核記錄

- 改正：「Eleven kinds of post」係寫死，而 config/quick-starts.ts 已經唔係 11 個 → 改寫做「寫死嘅數字將來會 drift」，兩處（tours.ts 同 home-view.tsx:323）都讀 QUICK_STARTS.length。
- 改正：未有 anchor：quick-starts、channel-card、capability-chips（要確認有冇傳）、analytics-coverage、companion-section → Plan step 3 縮到只加 home-view.tsx 嘅 quick-starts section anchor。
- 改正：加 onboarding 可以直接做 PATCH merge → onboarding 要另寫 SQL（`onboarding = jsonb_set(coalesce(p.onboarding,'{}'), '{tours}', coalesce(p.onboarding->'tours','{}') || %s::jsonb)`），RETURNING 要帶埋 onboarding；client 用 PATCH response 做 setQueryData(keys.me)，唔好 invalidate，費事每次寫入都多一次 touch session。
- 改正：測試位置：tests/test_postriff_phase2_hosted.py 同 tests/phase2/rls.sql → step 5 嘅檔案改做 tests/test_postriff_account_security.py + tests/phase2/postgres_account.py。
- 改正：Overlay 處理晒 sidebar 狀態：collapsed 就 setOpen(true)，mobile 就 setOpenMobile(true) → hop 前先打開 target 所屬 group；搵唔到 link 就用 group trigger 嘅 rect，再唔得就唔做 morph，直接 fade；tour 完之後還原 sidebar 同 group 本來嘅開合。
- 改正：Overlay 收埋快過打開 → 開 250ms（--modal-open-dur），收 150ms（--modal-close-dur）。
- 改正：NextStep target 用 id，唔係 selector 陣列 → 改寫做「單一 selector，冇 fallback 陣列」。
- 補上遺漏：Nav group 閂住時 sidebar link 唔喺 DOM（app-sidebar.tsx:140–143 collapsible group），v1 `light()` 冇 timeout 會無限 rAF；tour 亦會永久改寫用戶嘅 sidebar 開合狀態。
- 補上遺漏：GET /api/me 有 side effect（_touch_session、new-device alert，hosted.py:576–580）；onboarding sync 唔可以靠 invalidate + refetch，要用 PATCH response 做 setQueryData。
- 補上遺漏：update_profile 係整欄覆寫嘅 upsert，onboarding merge 要特製 SQL 加 8KB check，client.ts:120–121 嘅 return type 要擴充。
- 補上遺漏：privacy.py 嘅 data inventory（privacy.py:14 附近）要加 onboarding progress 條目（retention：跟 account），account 刪除時要清。
- 補上遺漏：Migration 編號衝突：多個 parallel session（worldwide languages、2FA）都可能開 013；要先 claim 編號，再同 hosted-precheck.sql 流程對齊。
- 補上遺漏：已經 set up 好嘅現有用戶：deploy 之後，每個舊 account 都會彈 welcome dialog。應該按 SetupFacts 判斷，setup 做晒就唔自動開，改做一次性細 nudge。
- 補上遺漏：Voice 規則張力：store.py:359 冇 active voice 唔准 approve，同 house rule 2 有衝突，要 James 拍板；tour 唔可以自己決定點講。
- 補上遺漏：react-joyride v3 其實有 focus trap 同 async before hook，研究低估咗佢；比較表要公平。
- 補上遺漏：Global window keydown：ArrowRight / Enter / Escape 同 kbar、Base UI Dialog 會撞，要 scope 或者檢查 defaultPrevented。
- 補上遺漏：Design spec §3 step 6 一步跨 brand 同 memory 兩條 route，同 TourStep 單一 route 嘅 shape 矛盾；`hasContent` 亦冇出現喺 §2 嘅 Tour interface。
- 補上遺漏：FIND_MS 5 秒後靜靜跳步：頁面慢 load（例如 analytics）會被誤判冇 target；應該等 query 由 isLoading 變 settled 先開始計，而唔係由 mount 開始計。
