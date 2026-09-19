# 02 · Home（Agent Chat）

> Route：`/app` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

已經起好、可以直接用嘅部分（file:line 以 consumer-saas working tree 2026-09-16 為準；注意 web/src/features/onboarding/ 同 web/src/styles/tour.css 係另一 session 未 commit 嘅 WIP，composer.tsx / home-view.tsx / header.tsx 亦係 M）。

Route 同殼：web/src/app/app/page.tsx:14–30 — `/app` render ParticleField（:17–25，純 ornament，冇數據，reduced motion 靜止）+ Suspense 包住 HomeView；sidebar Create 第一項（web/src/config/nav-config.ts:11–19，冇 access key）；page enter 由 web/src/app/app/template.tsx:13 `.t-page-enter` 負責，:15 mount 咗 `<TourMount />`（onboarding WIP）。

主體 web/src/features/agent/home-view.tsx：
- 資料來源（:74–78）：useSnapshot、useConversations、useModels、useMemory、useMemoryProposals（web/src/lib/api/hooks.ts:39, 84, 127, 133, 139）。Endpoint：GET /api/workspaces/{w}（hosted_app.py:461–462）、GET …/ideas/conversations（:238–240 → ideas.py:187–190）、GET /api/ideas/models（:303 → ideas.py:101–109）、GET …/memory（:467–468 → ideas.py:122 memory_files）、GET …/memory/proposals（:450–451）。
- canEdit gate（:73, :230–251）：冇 edit permission 唔 render Composer，只出一句提示；context bar、Needs you、Quick starts、Recent 照出。
- 六個 MODES（:33–46）只換 placeholder 同預設 platforms（pickMode :139–143）；server 唔收 mode（docs/postriff-agent-chat-design.md:537 §11a）。
- Context bar（:253–277）全部真數據：Voice = state.speaker.activeRevision；Memory = files.length（memory.py:18 FILE_ORDER 固定五個）；Sources = sources.filter(active).length；pending proposals pill（:262–266）。
- Needs you（:111–124 → :291–321）：冇 active voice、needs_review 數、channel displayState 唔係 'Ready for posting'；NotificationStack + sr-only list。
- Quick starts（:323–367）：11 個模板來自 web/src/config/quick-starts.ts:41–（5 個 group :32–39）；揀模板 = pickTemplate（:145–151）。Send 時 selectContentType（:158–168）：`p2_content_install_pack` → `p2_content_select`（POST /actions hosted_app.py:477+ → hosted.py:199 剝 p2_ → content_types.py:288, 295）。
- start()（:170–196）：api.quickStart（client.ts:207–211）→ POST …/ideas/quick-start（hosted_app.py:235–237 → ideas.py:530–565）：建 source（own → public_quote + approve）、建 conversation（頭 60 字；create_conversation :194 require edit）、行 turn()（:336；:386 INSERT pr_agent_runs；:389–390 ledger.reserve 只喺 paid route charge_batch）。成功 setQueryData(['agent-run', w, runId])（:185）畀 conversation-view.tsx:111 做 seed，invalidate conversations / snapshot / usage（:186–190），router.push；失敗 toast + busy 重設（:192–195）。
- Recent conversations（:369–403）：API 只有 id / title / createdBy / createdAt / updatedAt / archived；顯示 8 條。

Composer web/src/features/agent/composer.tsx：DRAFT_PLATFORMS（:18）= agent_runtime.py:13 DESTINATIONS；root 已有 `data-tour='composer'`（:74），chips group `data-tour='composer-channels'`（:88）；chips（:90–112）讀 displayState 決定綠 / 琥珀 / 灰（:92, :108），唔讀 capability matrix；:100 冇 account 一律「No account connected yet · drafts only」；EN / 繁中 radiogroup（:115–132）；ModelPicker（model-picker.tsx:22–70；:26 `qualified ?? model === 'deterministic-preview'`；:35–42 trigger；:40 TextScramble 只喺揀完先播）；useModelChoice（use-model.ts:28–55，localStorage 'postriff-agent-model'）；consent（:143–150）；⌘↵（:66–71）；canSend（:61）。

Onboarding 已存在（untracked WIP，web/src/features/onboarding/）：tours.ts:53–87 WELCOME_TOUR 三個 Home step（composer / chips / quick-starts，body 讀 TourCtx 真數據，`when: canEdit`）；:156–161 PAGE_TOURS `home-tips`；tour-mount.tsx 首次 WelcomeDialog + 每頁一次 nudge toast；help-menu.tsx（header.tsx:44）「Take the tour / Tips for Home / Reset tips」；store.ts localStorage 'postriff-onboarding'（try/catch）；use-tour-context.ts 讀 snapshot + channels，未 ready 唔開。缺：home-view 冇 `data-tour="quick-starts"`（靠 fallback `main section:has(h2)`）、冇 model / context bar anchor 同 step。

Plan card 唔喺 Home（conversation-view.tsx:340）；approve chain plan.ts:42–109；variantForRow :33–40 有 fallback。

Motion 已用：TextReveal h1（:204，default stagger 0.09 text-reveal.tsx:49）、motion.p subtitle（:206–213）、Tabs pill（:216, :329）、AnimatePresence popLayout（:341–365）、NotificationStack、SharedLayoutBg（:385）、ActionSwapIcon + motion Checkbox（composer）、TextScramble、ParticleField（page.tsx）、TourOverlay（tour.css）。

Live：localhost:4331 /api/health ok、:3100/app 307；chip 狀態同數字今次未經 browser 重驗（上一版 spec 話 Threads @dev_creator Ready for posting、Voice rev 1、Memory 5、Sources 3）。

已知缺口：
1. Info sidebar 顯示 template boilerplate：infoContent（:58–65）只經 PageContainer → Heading → InfoButton 發佈（page-container.tsx:57–70；heading.tsx:15–17；info-button.tsx:27–29 useEffect setContent），Home 冇 pageTitle → fallback info-sidebar.tsx:17–31「Documentation / Installation Guide（'#'）」。mobile 亦冇任何入口。
2. 誠實度：snapshot / conversations isError 冇 error state——:112 `!snapshot.isLoading && !voiceActive` 會彈「Set up your voice」；:271 Sources「0 usable」；:383「No conversations yet」；composer.tsx:100 loading 期間已寫「No account connected yet」；model-picker.tsx:26 catalog 失敗時綠點「Deterministic preview」。
3. Capability honesty：chips 同 plan-card.tsx:289（硬寫 'Assisted'）唔讀 GET …/channels（hosted_app.py:411–414；types.ts:436–453；hooks.ts:49–52）；Channels 頁已有 capability-chips.tsx + capability-badge.tsx:48 capabilityDotClass + lib/channels/capabilities.ts LEVEL_MEANING 可以 reuse。
4. Recent conversations 冇 run 狀態 / drafts / jobs。
5. 冇 first-run empty state（tour 已有）；Overview GettingStarted（getting-started.tsx:23–82）四步邏輯 inline，:31 'draft' 指去 /app/ideas。
6. Hero motion ≈ 1.1s，超出 docs/postriff-motion-system.md §5 第 4 條「stagger 40ms、總長 ≤ 300ms」。
7. 冇 web test：web/package.json 冇 playwright / vitest / jest；Playwright 只喺 desktop/node_modules（memory harness recipe：API 4341 fake claude/codex、web 3010）。
8. Language toggle 會被 docs/postriff-worldwide-languages-plan.md §7.2 換做 per-channel chips（composer.tsx:15, 36–40, 90–131；home-view.tsx:82–83, 123–131, 170–178；plan-card.tsx:188, 288）。
9. content_types.py:88 label「Music / Performance / Teaching」——quick start 文案已 general，但 content type 名會喺 conversation 頁出現。

## 1. Design specification（最新版）

**目的**：Home 係每次入 app 嘅第一屏同主要起點：用一句話講出想出乜（題目、channel、時間），PostRiff 用你把聲逐 channel 起稿、提出 schedule plan，然後由你批。頁面要喺五秒內講清三件事——講嘢就得、chip 係真狀態、乜都唔會自己出街——同時畀返嚟嘅人一眼見到邊條對話仲有嘢等佢。冇 edit permission 嘅人（viewer）都入到呢頁：佢見到嘅係 workspace 狀態同 recent conversations，唔係一個壞咗嘅 composer。

**Layout**：沿用現有單欄佈局，唔重寫：PageContainer（px-4 md:px-6）入面 `mx-auto max-w-3xl` 直欄；右邊 Infobar 預設收埋（app-shell.tsx:38 defaultOpen={false}），`i` 或 trigger 開，mobile 係 Sheet；header 有 LiveIsland 同 HelpMenu。由上至下八個 region：(1) hero h1 + subtitle（+ 新加一粒細 text button「How this works」開 Infobar，因為 Home 冇 header InfoButton，mobile 先有入口）；(2) mode pill tabs；(3) composer card = textarea → 新加 plan-preview 行 → footer（chips + language + model pill + send）→ consent row；canEdit=false 時整個 region 換做現有一句提示；(4) context bar（Voice · Memory · Sources · 新加 Writing allowance · shield 句）；(5) template badge row；(6) Needs you stack；(7) Quick starts（section 加 `data-tour="quick-starts"`）；(8) Recent conversations，或者零對話時 first-run card。Primary action = Send（⌘↵）。Responsive：375px——gutter 16px（現有 px-4），mode tabs flex-wrap，chips + language 一行、model pill + send 另一行靠右，plan-preview 每個 destination 一行，context bar 摺兩行、shield 句最後，quick starts 一欄（現有 grid），recent 標題 truncate（現有），冇橫向 scroll；768px——quick starts 兩欄（sm:grid-cols-2）；1440px——三欄（lg:grid-cols-3），Infobar 仍然預設收埋，開咗係 22rem。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Hero | 一句講清呢頁做乜，同「乜都唔會自己出街」嘅承諾。 | h1「What are we putting out this week?」（TextReveal stagger 收短到 0.04）；subtitle 一句（delay 0.2 / duration 0.3）；subtitle 下面一粒 text button「How this works」→ setContent(infoContent) + setOpen(true)。文案 general，唔帶人名。 | 靜態；reduced motion 即時顯示（現有：initial style 相同，timing 歸零）。 |
| Mode tabs | 揀想出嘅形式，換 placeholder 同預設 channels。 | 現有六粒（motion Tabs variant='pill'）。P2 先加 format 選擇。 | selected 一粒；鍵盤方向鍵（library 已有）。 |
| Composer | 唯一入口：文字 + channels + language + model + consent。 | 沿用 composer.tsx。新加 `preview` slot 喺 textarea 同 footer 之間，顯示 server parse 結果：每個 destination 一粒 AnimatedBadge（info = 有時間；warning = assumed / past / rolled），unsupported 另一粒「Facebook left out (not draftable yet)」；warning 文字直接用 parser 回傳嘅 warnings 原句。Chips 改讀 capability matrix：dot 用 capabilityDotClass(levelKey(level))，title = `account · displayState · level` + evidence 第一句；冇 account 保持灰點「No account connected yet · drafts only」。Model pill 唔郁；catalog isError 時 pill 寫「Default · model list unavailable」（灰點，唔係綠），送出時唔帶 model（ideas.py:111–113 `_select_runtime(None)` 回 self.runtime），唔 disable send。 | idle；typing（≥8 字 + debounce 400ms 先發 parse，未返之前乜都唔顯示）；preview shown；preview failed（靜靜收起）；busy（send spinner，textarea 可讀）；canEdit=false（現有一句提示，整個 composer 唔 render）；consent 未剔 → send disabled（現有）。 |
| Context bar | 講清 agent 今次會用乜：聲、記憶、素材、額度。 | Voice · rev N（/app/workspace/brand）｜Memory · N files + pending pill（/app/workspace/memory）｜Sources · N usable（/app/ideas；viewer 冇 edit 時唔做 link，只顯示數字）｜新加 Writing · N batches left · resets {date}（只喺 choice.option?.costClass === 'paid'；'subscription' route 顯示「your subscription writes」；'none' / fixture 唔顯示；link /app/account/billing）｜shield 句。 | loading「…」；value；isError——「unavailable · Retry」，永遠唔變 0 或「not set up」；allowance 0 → reminder pill「No writing batches left · see plan」，send 照可撳，由 server 決定（billing.py:70 → 402，toast 原句）。 |
| Template badge row | 話俾人知揀咗邊個 content type，同點清走。 | 現有 Badge「Template · {title}」+ 解釋 + Clear。 | 只喺 template 非 null 先出。 |
| Needs you | workspace 真係等緊你嘅事。 | 現有 NotificationStack：voice 未設、N drafts 待批、channel 要 Reconnect / 未 ready。 | 0 項唔 render；1 項 expandedLabel = 該 action；多項「Open overview」；snapshot.data 未存在（loading 或 isError）→ 唔 render。 |
| Quick starts | 11 種普通人真係會出嘅 post。 | 現有 grid + group tabs + popLayout；section 加 `data-tour="quick-starts"`（tours.ts:82 已經搵呢個 selector）。 | group filter；selected；hover；reduced motion layout 唔郁（現有）。 |
| Recent conversations / First-run card | 返嚟嘅人即刻接返上次；新人知道下一步。 | Recent：每行 title、relativeTime、新加 AnimatedBadge lastRun.status（running = loading「writing…」、completed = neutral、failed = danger），`N drafts · N scheduled`（只計 variants.provenance.runId ∈ runIds，jobs.manifest.variantId 對返；唔用 variantForRow fallback）。First-run card（conversations.data 存在且 length === 0）：「Your first post」，三行真狀態（Voice / Channel / Sources），一句「You can draft now; connect a channel when you want to schedule.」，掣「Try a quick start」揀 quick-thought 並 focus composer（canEdit 先出呢粒掣）。 | loading skeleton（現有）；empty → first-run card；isError → 「Couldn't load your conversations · Retry」；list；有 running run 時 refetchInterval 5000，冇就 false。 |

- **Empty state**：零對話嘅 workspace：Recent 位置換成 first-run card，讀 useSetupSteps() 嘅真狀態（voice active？channels.data.length？sources active？），每行只顯示「done」或者去邊度做；唔會因為未設 voice 而唔畀寫——文案明講「You can draft now」。Composer 保持可用。Quick starts 照常顯示。WelcomeDialog 同 home-tips nudge 由 TourMount 負責，first-run card 唔再彈第二個提示。
- **Loading**：snapshot loading：context bar 三個值「…」，chips 灰點 + title「Checking connected accounts…」，Needs you 唔出。conversations loading：兩條 Skeleton（現有）。models loading：pill 顯示「…」，冇 dot；send 照可用（server 會 validate）。usage loading：allowance 行唔出。parse preview：未返之前唔顯示任何字，唔用假 shimmer。
- **Error**：snapshot isError：Voice / Sources「unavailable · Retry」，chips 冇 dot、title「Account status unavailable」，Needs you 隱藏，send 照可用。conversations isError：「Couldn't load your conversations · Retry」。memory isError：「Memory · unavailable」。models isError：pill「Default · model list unavailable」（灰點），送出唔帶 model。channels（capability）isError：chips 退回 displayState 顏色，title 加「capability unavailable」。usage isError：allowance 行唔顯示。send 失敗：toast ApiError.message 原句（含 billing.py:71 嘅 402 文案）+ busy 重設（現有）。parse 失敗：收起 preview，唔阻 send。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Hero h1 + subtitle | page mount | TextReveal stagger 0.04（7 字 ≈ 0.28s），subtitle opacity/y 0.3s delay 0.2s；reduced motion 歸零 | components/motion/text-reveal.tsx（stagger prop）+ motion.p（home-view.tsx:206） | 否（純裝飾） |
| ParticleField 背景 | pointer | 現有 ornament，reduced motion 靜止；唔再加其他背景 motion | components/motion/particle-field.tsx（page.tsx:17–25） | 否（純裝飾） |
| Mode tabs / Quick start group tabs | click / arrow keys | pill 滑動（SPRING_LAYOUT） | components/motion/tabs.tsx variant='pill' | 否（純裝飾） |
| Plan preview row | parse response 到達 / 清空 | AnimatePresence：入 opacity+y 200ms EASE_OUT，出 120ms；每粒 AnimatedBadge 按 parser 狀態；reduced motion 只 opacity | components/motion/animated-badge.tsx（status info / warning）+ AnimatePresence（同 home-view.tsx:341 用法） | 是 |
| Channel chips | snapshot + channels query 返 | dot 顏色按 publish level；whileTap scale 0.96（現有） | composer.tsx:94–110 + components/marketing/capability-badge.tsx capabilityDotClass + components/app/level-badge.tsx levelKey() | 是 |
| Send button | busy 轉變 | send ↔ spinner blur swap（現有） | components/motion/action-swap.tsx ActionSwapIcon | 是 |
| Writing allowance 數字 | usage refetch 後數值改變 | DigitSwap 只喺真值變先滾；首次 paint 直接顯示 | components/motion/digit-swap.tsx | 是 |
| Needs you stack | hover / tap | 疊層展開（現有） | components/motion/notification-stack.tsx | 是 |
| Recent conversation status badge | lastRun.status 改變（有 running 先 5 秒 refetch） | AnimatedBadge loading → neutral / danger；行 hover 底色滑（現有） | components/motion/animated-badge.tsx + components/motion/shared-layout-bg.tsx | 是 |
| First-run card 步驟 | snapshot / channels 載入 | TodoList completed / in-progress / pending，spinActive={false} | components/agents/todo-list.tsx（同 overview/getting-started.tsx:78 用法） | 是 |
| Home tips spotlight | HelpMenu「Tips for Home」、首次 nudge toast、或 Infobar「Show me around」 | 現有 TourOverlay spotlight + tour.css pulse；唔另起 popover | features/onboarding/tour-overlay.tsx + store.ts（untracked WIP） | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Snapshot：GET /api/workspaces/{w} | api | 有 | src/postriff_phase2/hosted_app.py:461–462 service.get（hosted.py:124）；hooks.ts:39–42；types.ts:179–190 | S |
| 2 | Quick start：POST /api/workspaces/{w}/ideas/quick-start | api | 有 | hosted_app.py:235–237；ideas.py:530–565；client.ts:207–211 | S |
| 3 | Conversations 列表：GET …/ideas/conversations | api | 有 | hosted_app.py:238–240；ideas.py:187–190（只有 id/title/createdBy/createdAt/updatedAt/archived） | S |
| 4 | Conversations 列表加 lastRun {runId,status,model,at} 同 runIds（≤20） | backend | 冇 | ideas.py:187–190 SQL 冇 join pr_agent_runs；pr_agent_runs 有 conversation_id/status/model（ideas.py:386 INSERT） | M |
| 5 | Model catalog：GET /api/ideas/models（qualified / route / costClass） | api | 有 | hosted_app.py:303–310；ideas.py:101–109；types.ts:282–290 | S |
| 6 | Memory files + proposals | api | 有 | hosted_app.py:467–468（→ ideas.py:122）、:450–451；hooks.ts:133–142 | S |
| 7 | Content type 選擇：POST /actions p2_content_install_pack / p2_content_select | api | 有 | hosted_app.py:477+ → hosted.py:152 mutate（:199 剝 p2_）→ content_types.py:288, 295；home-view.tsx:158–168 | S |
| 8 | Capability matrix：GET /api/workspaces/{w}/channels | api | 有 | hosted_app.py:411–414 oauth.channels；types.ts:436–453；hooks.ts:49–52 useChannels——Home 未用；features/channels/capability-chips.tsx、capability-badge.tsx:48 capabilityDotClass、lib/channels/capabilities.ts:46 LEVEL_MEANING 可 reuse | S |
| 9 | Usage / entitlement：GET /api/workspaces/{w}/usage | api | 有 | hosted_app.py:389–390；hosted.py:316 usage；billing.py:44–47（writingBatchesRemaining, resetsAt）；types.ts:489–499 Entitlement；hooks.ts:44–47 useUsage——Home 未用 | S |
| 10 | Parse-only endpoint：POST /api/workspaces/{w}/ideas/parse（text, destinations, language, timeZone, model → parse_request + resolve_destinations + build_plan，零寫入） | backend | 冇 | intent.py:211 parse_request、:292 resolve_destinations、:304 build_plan 同 agent_runtime.py:86–87 supported_platforms() 全部純函數；hosted_app.py:231–273 `_ideas` 冇 parse resource；ideas.py:111 `_select_runtime` | S |
| 11 | Client：api.parseTurn + useParsePreview（debounce 400ms、min 8 字） | frontend | 冇 | client.ts:187–211 ideas 段冇 parse；hooks.ts 冇對應 hook（grep 零 hit） | M |
| 12 | Composer `preview` slot + features/agent/plan-preview.tsx | frontend | 冇 | composer.tsx:75–87 textarea 同 footer 之間冇 slot；grep PlanPreview 零 hit | M |
| 13 | Infobar 內容喺冇 pageTitle 時都發佈 + mobile / hero 入口 | frontend | 冇 | page-container.tsx:57–70 只喺 hasHeader 先 render Heading→InfoButton；info-button.tsx:27–29 嘅 useEffect setContent 可以抽做 useInfoContent；info-sidebar.tsx:17–31 fallback；infobar.tsx:157–163 handleSetContent；:82 mobile Sheet | S |
| 14 | Home 誠實狀態（isError → unavailable；loading → checking；models 失敗 → 唔帶 model） | frontend | 冇 | home-view.tsx:112, 256, 271, 383；composer.tsx:100；model-picker.tsx:26 | S |
| 15 | Chips / plan rows 讀 capability level | frontend | 冇 | composer.tsx:21–27 ChannelChip 冇 level；plan-card.tsx:289 硬寫 'Assisted'；level-badge.tsx:4–15 levelKey 已有 | S |
| 16 | 共用 useSetupSteps() hook | frontend | 冇 | 邏輯 inline 喺 overview/getting-started.tsx:28–33；grep useSetupSteps 零 hit | S |
| 17 | Onboarding / tour 機制（overlay、store、page tips、help menu、welcome） | frontend | 有 | web/src/features/onboarding/*（untracked WIP）：tours.ts:53–87 Home 三步、:156–161 home-tips；tour-mount.tsx；help-menu.tsx（header.tsx:44）；composer.tsx:74/:88 anchors。缺 home-view `data-tour="quick-starts"`、model / context anchor 同 step | S |
| 18 | Motion tokens 同 component inventory | frontend | 有 | web/src/styles/transitions.css；components/motion/*（32 個）；components/agents/todo-list.tsx；components/motion/particle-field.tsx；docs/postriff-motion-system.md §5 | S |
| 19 | Run seed handoff Home → conversation | frontend | 有 | home-view.tsx:185 setQueryData；conversation-view.tsx:111 getQueryData | S |
| 20 | Web test runner（Playwright dev dependency 或 desktop/node_modules/playwright + harness） | infra | 冇 | web/package.json 冇 playwright / vitest / jest，web/ 冇 e2e 目錄；desktop/node_modules/playwright/package.json 存在；memory project-postriff-agent-chat:19 harness recipe（API 4341 fake claude/codex、web 3010） | M |
| 21 | Home 嘅 Playwright smoke（render、chips title、parse preview、send 導向） | infra | 冇 | grep HomeView 只有 page.tsx 同 home-view.tsx；tests/test_postriff_consumer_web.py 係 Python unit test，唔碰 web UI | M |

## 3. Features

### P0

- **Info sidebar 顯示 Home 自己嘅「How the agent works」+ mobile 入口**：而家右欄係 template 嘅「Documentation / Installation Guide」而且 link 去 '#'——對每個用戶都係假內容，違反真數據同 general 原則。home-view.tsx:58–65 已寫好三段，只係 page-container.tsx:57–70 gate 令佢發唔出去；Home 冇 header 即係 mobile 連 InfoButton 都冇。加 useInfoContent（抄 info-button.tsx:27–29）、hero 下面一粒「How this works」、links（/app/channels、/app/workspace/memory、/app/ideas）同「Show me around」→ tourStore.start('home-tips')。
- **Home 誠實狀態：unavailable 永遠唔變 0 / not set up / No conversations**：snapshot 或 conversations 失敗時 Home 會話「Set up your voice」「0 usable」「No conversations yet」（home-view.tsx:112, 271, 383）；chips loading 期間已話「No account connected yet」（composer.tsx:100）；models 失敗時綠點「Deterministic preview」（model-picker.tsx:26）。House rule 1 直接違反，先修呢個。
- **Channel chips 讀 capability matrix（Direct / Assisted / Bridge / 未接）**：redesign §1.1 講明 per-capability matrix 係產品差異，而 Home chip 同 plan-card.tsx:289 都只係「connected 綠點」或硬寫 Assisted。改用 useChannels() 嘅 capabilities.publish.level + evidence，dot 同字眼 reuse Channels 頁嘅 capabilityDotClass / LEVEL_MEANING，令 Home 同 Channels 講同一句話。（depends on：worldwide-languages plan §7.2 會重寫 composer.tsx:90–131 同 plan-card.tsx:288——同一段 code，先傾邊個先落，或者將 level 做成 ChannelChip optional field）

### P1

- **Composer 即時 plan preview（server parse，零寫入）**：Home 嘅核心規則係「message 入面講嘅 channel 同時間贏過 chips」，但而家要送出、跳頁、等 run 先見到 Facebook 被剔走、時間被 assumed。加 POST /ideas/parse 用同一 parse_request + build_plan 回傳，composer debounce 後顯示 parser 原句。真數據、唔 block、同 run 一致（同一 function、同一 supported_platforms）。（depends on：新 endpoint POST /api/workspaces/{w}/ideas/parse）
- **Recent conversations 帶真實 run 狀態、drafts、scheduled 計數**：返嚟嘅人最想知邊條仲寫緊（CLI route async）、邊條有 plan 等批、邊條已排。API 只有 title + updatedAt。加 lastRun + runIds 後 client 用 snapshot 嘅 variants.provenance.runId 同 jobs.manifest.variantId 對返。有 running 先 refetch。（depends on：ideas.py conversations() 加 lastRun / runIds）
- **Writing allowance 一行（只喺 paid route）**：揀 paid model 而 writingBatchesRemaining 係 0，run 會喺 ledger.reserve（billing.py:70）先炸。Home 讀 GET /usage 顯示「Writing · N batches left · resets …」；0 變 reminder + link billing，send 照可撳，server 拒絕時 toast 顯示 billing.py:71 原句。（depends on：useUsage()（已有 hooks.ts:44–47））
- **First-run empty state + 共用 setup steps**：新 workspace 嘅 Home 只係「No conversations yet」一句。Overview GettingStarted 四步讀真狀態但邏輯 inline，'draft' step 指去 /app/ideas。抽 useSetupSteps() 兩頁共用，Home 版明講「You can draft now」。WelcomeDialog / nudge 已由 TourMount 負責，唔再加提示。（depends on：features/overview/getting-started.tsx 重構）
- **Home tips 補齊：quick-starts anchor + model / context 兩步**：tour 機制已在（features/onboarding WIP）：home-tips 有 composer / chips / quick-starts 三步，但 home-view 冇 `data-tour="quick-starts"`（靠 structural fallback），冇 model pill 同 context bar 嘅 step。補三個 anchor、兩步文案（general），Infobar「Show me around」→ tourStore.start('home-tips')。唔起第二套 tour、唔加新 storage key。（depends on：另一 session 嘅 onboarding slice commit 咗先（untracked））
- **Hero motion 收短到 ≤300ms**：TextReveal 0.09 × 7 字 + subtitle delay 0.45 ≈ 1.1s，超出 motion §5 第 4 條。改 stagger 0.04、subtitle delay 0.2 / duration 0.3。

### P2

- **Mode tab 揀埋 format（thread → short_text、carousel → carousel）**：Mode tabs 只換 placeholder（§11a）。skills.bind 按 formatId（agent-chat design :372），tab 揀 format 會令 run 真係唔同。short_text / carousel id 已確認（content_types.py:49–50）。（depends on：GET /api/content-formats（hosted_app.py:297–298））
- **未送出嘅 composer 文字記住（per workspace，localStorage）**：打到一半去 Channels 接 account 再返嚟，文字冇咗。Per-viewer convenience，try/catch。
- **Home Playwright smoke test**：Home 零 test；P0/P1 改動涉及 error state 同 preview。要先決定 runner（web 加 dev dependency 定用 desktop/node_modules/playwright + scratchpad harness），再寫 render、chips title、parse preview、send 導向；唔撳 approve / schedule。（depends on：web test runner 決定）
- **content type label 通用化核對**：content_types.py:88「Music / Performance / Teaching」會喺 conversation 頁 content type 名出現；quick start 文案已 general，label 要一併過 general 原則。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內要明三件事：(1) 喺框入面用平常話講想出乜——題目、邊個 channel、幾時；(2) chips 係真狀態——邊個 account 接咗、PostRiff 喺嗰度做到幾多；(3) PostRiff 只會起稿同提議時間，乜都要你批先出街。頁面點教：h1 直接問；subtitle 講「in your voice for each channel」+「for you to approve」；placeholder 示範 channel + 時間寫法；composer hint 同 context bar 尾都寫「nothing publishes without your approval」；chip tooltip 講 level + evidence。首次入 app 有 WelcomeDialog（三點）同 home-tips nudge toast（tour-mount.tsx:37–46）；HelpMenu 隨時重播。新加嘅 plan preview 會喺人打第一句時證明「你講嘅 channel 同時間我讀到」。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="composer"]（已有，composer.tsx:74；tours.ts:57–65 step 已有）` | Say what you want to put out | Type the topic, paste a link or drop your notes. Name a channel and a time in plain words and the plan follows them. |
| 2 | `[data-tour="composer-channels"]（已有，composer.tsx:88；tours.ts:66–77 step 已有，body 讀 channelCount）` | Channels you can draft for | Each dot shows an account's real state and what PostRiff can do there: Direct, Assisted, or not yet. Drafts work for channels you have not connected. |
| 3 | `data-tour="composer-model"（新加，model-picker.tsx:37 trigger Button）` | Choose who writes | A PostRiff route, or your own Claude Code or Codex on this machine. A green dot means it is signed in. Change it any time; the choice is remembered in this browser. |
| 4 | `data-tour="home-context"（新加，home-view.tsx:253 context bar div）` | What the agent knows about you | Your voice profile, the memory files it reads before every draft, and the sources you marked usable. Each one links to where you change it. |
| 5 | `data-tour="quick-starts"（新加，home-view.tsx:323 section；tours.ts:82 已搵呢個 selector）` | Eleven kinds of post to start from | Pick one, replace the brackets with your own words, send. Each one maps to a post type with its own checks. |

**Empty state 教咩**：零對話時 Recent 位置嘅 first-run card 教三樣：(1) 而家已經可以寫——三行真狀態（Voice / Channel / Sources）只講「done」或「去邊度做」，冇一行會阻止 send；(2) 每一步之後會去邊——起稿去 conversation 頁、批咗去 Queue / Calendar；(3) 「Try a quick start」揀 quick-thought 並 focus composer（canEdit 先出）。步驟狀態全部讀 snapshot / channels（useSetupSteps），唔會因為撳過而剔。Viewer（冇 edit）見到同一張卡但冇「Try a quick start」，文案改「Ask an editor to draft; you can review what they send.」

## 5. Next steps（按次序）

1. **同另一 session 對齊：features/onboarding、tour.css、composer.tsx / home-view.tsx / header.tsx 嘅 M 係佢嘅 WIP；本 spec 嘅 web 改動要等嗰個 slice commit 或者 stage by path，唔可以 whole-tree commit。**（effort S）  
   檔案：`git status；memory feedback-shared-tree-explicit-staging、feedback-parallel-sessions-avoid-web-src`
2. **誠實狀態 pass：needsYou / Voice / Sources 只喺 snapshot.data 存在先計，isError 顯示「unavailable · Retry」；conversations.isError 顯示 retry；composer chips 加 loading / unavailable title 同無 dot；models.isError 時 pill「Default · model list unavailable」灰點，quickStart body 唔帶 model。**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx:100–124, 253–277, 377–384；web/src/features/agent/composer.tsx:90–112；web/src/features/agent/model-picker.tsx:22–42；web/src/features/agent/use-model.ts:39–42`
3. **Infobar：抽 info-button.tsx:27–29 做 `useInfoContent(content)`（useEffect → setContent，unmount 清走），HomeView 直接 call；hero 下面加「How this works」text button；Home infoContent 加 links 同「Show me around」→ tourStore.start('home-tips')；info-sidebar.tsx defaultData 換成「No notes for this page.」。**（effort S）  
   檔案：`web/src/components/ui/info-button.tsx；web/src/components/ui/infobar.tsx:157–163；web/src/components/layout/info-sidebar.tsx:17–36；web/src/features/agent/home-view.tsx:58–65, 203–214`
4. **Capability-honest chips：ChannelChip 加 `level?: CapabilityLevel; evidence?: string`；home-view 用 useChannels() 按 platform 對 capabilities.publish（冇就 Unsupported）；dot 用 capabilityDotClass(levelKey(level))；title = account · displayState · level（evidence）；plan-card.tsx:289 改讀同一個 level。同 languages §7.2 協調（composer.tsx:90–131、plan-card.tsx:288 同一段）。**（effort S）  
   檔案：`web/src/features/agent/composer.tsx:21–27, 90–112；web/src/features/agent/home-view.tsx:104–108；web/src/features/agent/plan-card.tsx:256–290；web/src/components/marketing/capability-badge.tsx:48；web/src/lib/channels/capabilities.ts:46`
5. **Hero motion：TextReveal 傳 stagger={0.04}；subtitle transition { duration: 0.3, delay: 0.2 }；prefers-reduced-motion 同 375px 各睇一次。**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx:204–213；web/src/components/motion/text-reveal.tsx（只用 prop）`
6. **Home tips 補齊：home-view section 加 `data-tour="quick-starts"`、context bar div 加 `data-tour="home-context"`、model-picker trigger 加 `data-tour="composer-model"`；tours.ts WELCOME_TOUR 加 model / context 兩步（`when: canEdit`，general 文案），home-tips 自動跟。**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx:253, 323；web/src/features/agent/model-picker.tsx:37；web/src/features/onboarding/tours.ts:53–87（untracked）`
7. **Parse endpoint：hosted_app.py `_ideas` 加 `resource == "parse"` POST → ideas.parse(workspace_id, token, body)：transaction 只做 membership check（require view），runtime = _select_runtime(model) 失敗就 self.runtime，回 { intent, language, timeZone, destinations, plan, unsupported, warnings }。Tests：tests/test_postriff_intent.py 加 parse 合約；tests/phase2/postgres_ideas.py 加 route check + 斷言 pr_conversations / sources 冇增加。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:231–273；src/postriff_phase2/ideas.py（新 method，放 turn() :336 之前）；src/postriff_phase2/intent.py:211–320（唔改）；tests/test_postriff_intent.py；tests/phase2/postgres_ideas.py`
8. **Client + UI：client.ts 加 parseTurn；hooks.ts 加 useParsePreview（useQuery，enabled 當 text.trim().length ≥ 8，debounce 400ms，placeholderData 唔用）；新 features/agent/plan-preview.tsx（AnimatedBadge per destination，warnings 原句，unsupported 另一粒）；composer.tsx 加 `preview?: ReactNode` slot；Home 同 conversation-view 都可以傳。**（effort M）  
   檔案：`web/src/lib/api/client.ts:187–211；web/src/lib/api/hooks.ts；web/src/lib/api/types.ts:234–247（ParsePreview type）；web/src/features/agent/plan-preview.tsx（新）；web/src/features/agent/composer.tsx:75–87；web/src/features/agent/home-view.tsx:230–248`
9. **Conversations 狀態：ideas.py conversations() SQL 加 LEFT JOIN LATERAL 取最後一個 run（id, status, model, created_at）同 array_agg 最近 20 個 run id；types.ts Conversation 加 lastRun / runIds；Recent 行加 AnimatedBadge + `N drafts · N scheduled`（只計 provenance.runId ∈ runIds）；useConversations 加 refetchInterval = 有 running 就 5000 否則 false。**（effort M）  
   檔案：`src/postriff_phase2/ideas.py:187–190；web/src/lib/api/types.ts:265–271；web/src/lib/api/hooks.ts:84–87；web/src/features/agent/home-view.tsx:369–403`
10. **Writing allowance：home-view 加 useUsage()；只喺 choice.option?.costClass === 'paid' 顯示「Writing · {writingBatchesRemaining} batches left · resets {date}」（DigitSwap），'subscription' 顯示「your subscription writes」；0 → reminder pill link /app/account/billing；usage.isError → 唔顯示。**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx:253–277；web/src/lib/api/hooks.ts:44–47；web/src/components/motion/digit-swap.tsx`
11. **First-run card + useSetupSteps：抽 overview/getting-started.tsx:28–33 做 web/src/features/overview/use-setup-steps.ts（'draft' href 改 '/app?new=1'）；GettingStarted 改用；Home 新 features/agent/first-run-card.tsx（TodoList spinActive={false}、「Try a quick start」→ pickTemplate(QUICK_STARTS[0])，canEdit 先出），conversations.data 存在且 length === 0 先 render。**（effort M）  
   檔案：`web/src/features/overview/getting-started.tsx；web/src/features/overview/use-setup-steps.ts（新）；web/src/features/agent/first-run-card.tsx（新）；web/src/features/agent/home-view.tsx:369–403`
12. **Web test runner + Home smoke：決定用 desktop/node_modules/playwright（harness recipe：API 4341 fake claude/codex、web 3010）定 web 加 @playwright/test；然後寫 render、chips title、parse preview 出現、send 之後 URL 變 /app/agent/…；唔撳 approve / schedule。**（effort M）  
   檔案：`web/package.json 或 desktop/node_modules/playwright；web/e2e/home.spec.ts（新）；memory project-postriff-agent-chat:19`
13. **P2：mode → format（thread → short_text、carousel → carousel，id 已喺 content_types.py:49–50）；未送出文字 localStorage（'postriff-home-draft:{workspaceId}'，try/catch）；content_types.py:88 label 通用化核對。**（effort S）  
   檔案：`web/src/features/agent/home-view.tsx:139–143；src/postriff_phase2/content_types.py:48–50, 88`

## Risks

- Parse endpoint 一定要零副作用：quick_start 每次都建 source + conversation（ideas.py:548–563），preview 絕對唔可以行 quickStart 或 turn；test 要斷言 pr_conversations / sources 冇增加。
- 兩個真相：preview 同 run 用同一 parse_request，但 supported_platforms 隨 model 唔同；parse body 一定要帶 model（或者同 use-model 一樣 fallback），否則 preview 話 Facebook 會出而 run 又剔走。
- Parallel sessions：features/onboarding 未 commit，composer.tsx / home-view.tsx / header.tsx 係另一 session 嘅 M；languages §7.2 亦會重寫 composer.tsx:15, 36–40, 90–131、home-view.tsx:82–83, 123–131, 170–178、plan-card.tsx:188, 288——step 4 / 8 撞正同一段，要先傾邊個先落。
- Dev harness 嘅 Threads 係 live provider：驗證 Home 只可以 render、打字、睇 preview、send 起稿；唔可以撳 approve / schedule。
- Recent 嘅 drafts / scheduled 計數只可以計有 provenance.runId 嘅 variant；variantForRow（plan.ts:33–40）嘅 fallback 唔可以用，否則多計。
- Memory「5 files」永遠係 5（memory.py:18），數字真但冇資訊；MemoryFile 有 updatedAt 之後改「updated 2h ago」。
- content_types.py:88「Music / Performance / Teaching」label 會喺 conversation 頁出現；general 原則要 UI 文案同 content type label 兩邊都過。
- Viewer（冇 edit）嘅 Home：composer 唔 render、tour Home 步全部 `when: canEdit` 即零步、Sources link 去 nav 隱藏咗嘅 /app/ideas——要決定 viewer 版 Home 顯示乜（建議：狀態 + recent，唔 link 去佢冇 permission 嘅頁）。
- Writing allowance 只喺 paid route 顯示；billing.py:70 reserve 只喺 charge_batch（paid）先拒——subscription CLI route 顯示額度會誤導，一定要按 costClass 分支。
- TextReveal 收短之後 h1 + subtitle 總長約 0.5s，仍然係頁面最長嘅 motion；可以考慮只喺 session 首次到訪播（sessionStorage，per-viewer convenience）。
- Live 數字（Threads Ready for posting、Voice rev 1、Sources 3）今次未經 browser 重驗，落 code 前用 hidden-pane page text 再讀一次。

## 覆核記錄

- 改正：home-view.tsx line refs（:73–77 hooks、:110–123 needsYou、:252–276 context bar、:322–366 quick starts、:368–402 recent、:184 setQueryData、:203/:205–212 hero、:57–64 infoContent、:111/:270/:381 誠實度位） → 全部 +1，見 corrected_spec
- 改正：GET /api/workspaces/{w} = hosted_app.py:451–453；GET …/memory = :457；GET …/memory/proposals = :428–431；POST /actions = :469–478 → 改 ref
- 改正：ideas.py:101–109 model_catalog；:187–190 conversations；:379–381 pr_agent_runs INSERT；:530–557 quick_start → INSERT 改 :386，quick_start 改 :530–565
- 改正：hosted.py:302–308 usage；billing.py:44–47 entitlement、:70 reserve 拒絕；memory.py:18 FILE_ORDER 五個檔 → usage 改 hosted.py:316
- 改正：client.ts:202–206 quickStart；:183–206 ideas 段 → 改 :207–211 / :187–211
- 改正：1440px Infobar 預設打開（InfobarProvider defaultOpen） → 改為「預設收埋，`i` 或 InfoButton 開；唔改 default」
- 改正：grep web/src 冇 data-tour / Tour；codebase 冇任何 tour 機制 → Tour feature / step 10 改做「補 anchors + 加兩步入 home-tips」，唔起第二套
- 改正：Tour 用 Base UI Popover + transitions.css transition 05，localStorage 'postriff-tour-home' → reuse TourOverlay；刪 Popover / 新 storage key
- 改正：oauthComplete 走 client.ts 唔經 useAct，要確認 OAuth 完成後 invalidate keys.channels 同 keys.snapshot → 由 risks 刪走
- 改正：冇 web test 覆蓋 Home；Playwright smoke 放 web/e2e/home.spec.ts → 加一個「web test runner」requirement，或者 spec 走 desktop 嘅 Playwright
- 改正：features/onboarding 係已 commit 嘅 code → spec 要標明相依於未 commit 嘅 onboarding slice，stage by path
- 違反原則（已改）：Reuse before inventing（motion rule 4 / 現有 inventory）：spec 提議新起 Tour component（Base UI Popover + 'postriff-tour-home'），但 features/onboarding 已有 TourOverlay、store、HelpMenu、WelcomeDialog 同三個 Home step；重複起會有兩套 onboarding state。
- 違反原則（已改）：Capability honesty：spec 手寫 dot 顏色「Direct 綠、Assisted 琥珀、Bridge 藍」，冇用 capability-badge.tsx:48 capabilityDotClass 同 lib/channels/capabilities.ts LEVEL_MEANING，會同 Channels 頁嘅 chip 顏色 / 字眼分歧。
- 違反原則（已改）：真數據：features 第 3 / 4 條引用 Buffer marketing 頁（buffer.com/ai-assistant）嘅講法做論據，今次未驗證；proposal 內部可以提，但唔應寫成事實。
- 違反原則（已改）：Motion：「Tour popover 開 250ms / 收 150ms（transition 05）」引用嘅 05 係 Menu dropdown token，唔係 popover；現有 tour.css 已有自己嘅 timing。
- 違反原則（已改）：General, not personal：content_types.py:88 label「Music / Performance / Teaching」會經 Template badge（home-view.tsx:282 用 quick start title，冇問題）同 conversation 頁 content type 名出現；spec 只列做 risk，應該列做 next step 核對。
- 補上遺漏：RBAC：Home 冇 nav access key（nav-config.ts:11–19），任何 member 都入到；composer 只喺 `checkAccess(access, { permission: 'edit' })` 先 render（home-view.tsx:73, :230–251），但 context bar 嘅 Sources link 去 /app/ideas（nav-config.ts:35 要 edit），viewer 會撳去一個 nav 隱藏咗嘅頁；tour Home 三步都 `when: canEdit`（tours.ts:64/76/86），viewer 嘅 home-tips 係零步。spec 冇講 viewer / 無 edit 嘅 Home 應該係點。
- 補上遺漏：Onboarding 現況：WelcomeDialog（首次入 app）、page nudge toast（tour-mount.tsx:37–46）、HelpMenu「Tips for Home」全部已在；spec 嘅 onboarding section 要改寫成「補齊 anchors + 加 model / context 兩步」。
- 補上遺漏：Parallel-session 相依：features/onboarding、tour.css 未 commit，composer.tsx / home-view.tsx / header.tsx 同時係另一 session 嘅 M；本 spec 所有 web 改動要等嗰個 slice 落地或者 stage by path。
- 補上遺漏：ParticleField（page.tsx:17–25）係 Home 現有 motion，ornament 冇數據，reduced motion 靜止；motion inventory 應列出，避免再加背景 motion。
- 補上遺漏：Error copy：billing.py:71 嘅 402 message（No writing allowance left… Drafts, exports and reviews remain available）已經係 user-facing，send 失敗 toast 應原句顯示而唔係自己寫。
- 補上遺漏：Web test runner：web/package.json 冇任何 test dependency；「Playwright smoke」要先決定用 desktop/node_modules/playwright（harness recipe）定係加 dev dependency。
- 補上遺漏：Parse endpoint 嘅 permission：quick_start 本身冇 require edit，係 create_conversation（ideas.py:194）先 require；parse 應明確 `require(member, 'view')` 或 'edit'，同 UI gate 一致。
- 補上遺漏：Languages plan §7.2 亦會改 plan-card.tsx:288（LanguageBadge），所以 step 3 改 :289 同 §7.2 撞嘅唔止 composer。
- 補上遺漏：Mobile：Infobar 喺 mobile 係 Sheet（infobar.tsx:82），InfoButton 只喺有 header 先出現，Home 冇 header 即係 mobile 冇任何入口開 Home 說明——修 gate 之後要俾 mobile 一個 trigger（例如 hero 下面一粒「How this works」）。
