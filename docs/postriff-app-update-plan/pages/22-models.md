# 22 · Models & providers

> Route：`/app/account/models` · Sidebar：Account · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

頁面已經存在，讀真數據，但係「半成品」。Route：`web/src/app/app/account/models/page.tsx:1-8` → `ModelsView`（`web/src/features/account/models-view.tsx`，187 行）。Data 只有一個 hook：`useModels()`（`web/src/lib/api/hooks.ts:127-130`，staleTime 10 分鐘）→ `api.models()`（`web/src/lib/api/client.ts:105`，`GET /api/ideas/models`，第二個參數 `false` = 唔帶 auth）→ `ModelCatalog {models, reasoning, agents}`（`web/src/lib/api/types.ts:282-320`）。Default writer 由 `useModelChoice`（`web/src/features/agent/use-model.ts:28-55`）管理，存喺 localStorage key `postriff-agent-model`（`use-model.ts:6`），唔存 server；Home composer（`web/src/features/agent/home-view.tsx:125`）、conversation（`conversation-view.tsx:143`）都讀同一個 hook，`ideas-view.tsx:76` 亦 call `useModels()`。

Backend：`src/postriff_phase2/hosted_app.py:303-312` 回 `IdeasService.model_catalog()`（`src/postriff_phase2/ideas.py:102-109`）：逐個 runtime 攞 `list_supported_models()` + `describe()`；`reasoning` 只係 `self.runtime`（fixture）嗰份（`ideas.py:109`）——即使 managed route mounted，頂層 reasoning 仍然話 Standard/Deep「Requires a qualified model route」。Runtime registry（`ideas.py:87-93`）：fixture + Claude Code / Codex（CLI 喺 PATH 而且 `POSTRIFF_LOCAL_CLI!=0`）；有 `AI_GATEWAY_API_KEY` 就 append `ServerModelRuntime`（`hosted.py:288-294`、`hosted_app.py:93-110`）。Agent card 嘅 name / vendor / version / authStatus / authMethod / host / guidance / execution 由 `cli_runtime.py:210-234`（Claude Code `detect`）同 `codex_runtime.py:68-101`（Codex）probe 出嚟；CLI model option 嘅 `qualified` = installed && authStatus ok（`cli_runtime.py:262-267`、`codex_runtime.py:103-107`）；managed label / detail 由 `model_runtime.py:103-105`；preview 由 `agent_runtime.py:66-70`。Cost class 三種：`none`（fixture）、`subscription`（CLI，`cli_runtime.py:184`）、`paid`（managed，`model_runtime.py:87`）；ledger 只有 paid route 先 reserve 錢同 writing batch（`ideas.py:389-390`）。

已知缺口（每個有 evidence）：
1. Rescan 係假嘅：button 只係 `invalidateQueries`（`models-view.tsx:111`）；`describe()` → `detect()` 冇 force（`cli_runtime.py:259-260`），probe cache 60 秒（`cli_runtime.py:211`）；`_auth_failed` 只有 `force=True`（`cli_runtime.py:238-244`）或者成功 run（`_note_auth_ok`，`:251-254`）先清。即係一次 401 之後，Rescan 永遠清唔到「expired」。
2. authStatus `expired` UI 唔識：API 出 `expired`（`cli_runtime.py:242-244`），`authBadge()`（`models-view.tsx:25-30`）只處理 `ok` / `missing`，其餘變灰色「Status unknown」。
3. Budget：失敗訊息話「raise the budget in Models & providers」（`cli_runtime.py:108`），但 budget 只係 env `POSTRIFF_CLI_BUDGET_USD`（`cli_runtime.py:29,190`，argv `:320`），頁面冇掣。Codex 冇 budget flag，`execution_settings` 回 `budgetUsd: 0.0`（`codex_runtime.py:101`），而現有 UI 將佢顯示成「$0.00 · stops the run, never overcharges」（`models-view.tsx:80`）——而家就係一個假數字。
4. Managed route 同 fixture stub 重疊：fixture 永遠列 `server-openai`「PostRiff managed model · Not qualified」（`agent_runtime.py:69`）；有 gateway key 時同一頁又有「… · PostRiff managed · Available」。Managed option 冇 `route` key（`model_runtime.py:104`），前端靠「冇 route」推斷分組（`models-view.tsx:103`、`model-picker.tsx:26-28`）。
5. `/api/ideas/models` 係 public（`hosted_app.py:303`，喺 `:339 self._runtime()` / `:340 self._token(environ)` 之前）：未登入都攞到 serve API 嗰部機嘅 CLI version、authMethod、host、env key 名。`tests/test_postriff_consumer_web.py:181-182` 仲用未登入 GET 斷言 200。
6. Reasoning 冇按 route：CLI Standard / Deep「Not mapped yet」（`cli_runtime.py:269-270`）；managed 三級都得（`model_runtime.py:107-110`，deep = 兩次 call，`:249-259`）；composer 從來唔送 `reasoning`（`web/src/features/agent/` grep 零命中），`ideas.py:338` 永遠 `quick`，`ideas.py:408` run.started 亦寫死 quick。
7. 冇 runs 歷史：`pr_agent_runs`（`migrations/postriff/005_consumer_web_ideas.sql:40-57`）有 model / status / usage jsonb / created_at，但只有 per-run events route（`hosted_app.py:252-262`），冇 list。Ledger（`billing.py:110-131`，`GET /api/workspaces/{w}/usage`，`hosted_app.py:389-390`）有 provider / model 但 CLI route 一律 $0；Claude Code 自己報嘅 `cliCostUsd` 只喺 run usage（`cli_runtime.py:455-456`），Codex 係 `None`（`codex_runtime.py:201`）；activity strip 有顯示（`activity-strip.tsx:48-55`）。
8. 右欄「How each option is billed」係硬 code 文案（`models-view.tsx:157-175`），唔讀 `costClass`，而且用 LevelBadge Direct/Assisted 標 route kind（混用 readiness 顏色）；「Current default」card 只係一行 mono 字（`:176-182`）。
9. Privacy notice 同頁面唔一致：`privacy.py:26`（SUBPROCESSORS）同 `aiProcessing` 仲話只有 deterministic preview，但 `model_runtime.py:22` 已經行 Vercel AI Gateway。
10. 冇 tour、冇 `data-tour`：`web/src/features/onboarding/tours.ts` PAGE_TOURS 冇 `/app/account/models`。
11. Desktop companion 未有 transport（`docs/postriff-agent-chat-design.md:594` §11b；`hosted_app.py` 冇 import `postriff_phase3`），頁面只喺 infoContent 講一句（`models-view.tsx:21`）。
12. Cloud consent 資料已有 endpoint 但頁面唔用：`GET /api/workspaces/{w}/memory`（`client.ts:145`）回 `egress`（`types.ts:332-340`）、`research`（`types.ts:423-432`，含 `hosted`）、`learning.cloudExtraction`（`types.ts:364`），Memory 頁用緊（`memory-view.tsx:66-160`）。
13. 冇 page-level access gate：nav 設 `permission: 'edit'`（`web/src/config/nav-config.ts:168-174`），但 `ModelsView` 冇傳 `access` 畀 `PageContainer`（`page-container.tsx:44-66` 支援），viewer 直接打 URL 都入到。Access 真值由 `web/src/lib/auth/access.tsx` + `lib/workspace/provider.tsx:173` 提供。
14. 「hosted 定本機」冇可靠 signal：`/api/catalog` `execution`（`hosted_app.py:285`）預設 'hosted'、dev harness 'dev-synthetic'，從來唔會係 'local'；真正判斷係 `research.hosted()`（`research.py:80-81`，前端經 `ResearchEgress.hosted`）。

Tests 有：`tests/test_postriff_cli_runtime.py`、`tests/test_postriff_codex_runtime.py`、`tests/phase2/postgres_cli_route.py:92-95`、`tests/test_postriff_consumer_web.py:181-182`；web 冇 feature test runner（`web/package.json` 冇 test script）。

## 1. Design specification（最新版）

**目的**：一頁答三個問題：而家邊個 writer 幫我寫（同佢用邊個錢）、我可以揀邊啲 route（每條 route 真實狀態、行喺邊、要乜 consent）、最近幾次 run 係邊條 route 寫、花咗幾多。全部數字同狀態讀 `/api/ideas/models`、`/api/workspaces/{w}/memory`、`/api/workspaces/{w}/usage`、（P1）`/api/workspaces/{w}/ideas/runs`；冇 API 值就寫「Unavailable」或者「—」，永遠唔變 0。

**Layout**：沿用 `PageContainer`（`web/src/components/layout/page-container.tsx`），傳 `access={checkAccess(access, {permission: 'edit'})}` 同 accessFallback（「Only people who can edit drafts choose a writer. Ask a workspace owner.」）。pageTitle「Models & providers」、pageDescription、infoContent、pageHeaderAction = Rescan（`StatefulButton`，`data-tour="models-rescan"`；旁邊一行「Checked 12s ago」讀 API `probedAt`，用 Intl.RelativeTimeFormat 跟 `Me.preferences.locale`；375px 時 button icon-only + aria-label「Rescan CLIs」，Checked 文字跌落 page description 下面一行）。主體 `grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]`（現有）。左欄：①「Writing now」strip（`data-tour="models-current"`）②「Local CLI (n)」section（`data-tour="models-cli"`，n = `agents.length`；empty 時 `data-tour="models-empty"`）③「PostRiff」section（`data-tour="models-managed"`）④「Recent runs」（P1，`data-tour="models-runs"`）。右欄：ⓐ「How each option is billed」（由 `costClass` 生成）ⓑ「What a cloud model may read」（`data-tour="models-consent"`，讀 `useMemory()`）ⓒ「Where this runs」（讀 catalog 新欄 `deployment.hosted`；落地前讀 `useMemory().research.hosted`）ⓓ「Desktop companion」誠實 placeholder（`data-tour="models-companion"`）。Route kind 一律用 neutral outline Badge（Local CLI / PostRiff managed / Preview）；綠 / 琥珀 / 灰只用嚟表示 readiness。Responsive：375px 單欄，右欄跌落左欄之下，model RadioGroup 每行一個，execution grid 單欄，Recent runs 改 card list（每張：writer、status、cost、時間）；768px 仍然單欄（lg=1024 先分欄），card 內 grid 兩欄，runs 用 table + `overflow-x-auto`；1440px 兩欄。Primary action = 揀 default writer（RadioGroup 即時生效）；Rescan 係 secondary。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Writing now（strip） | 5 秒內知道邊個 writer 幫我寫、用邊個錢、存喺邊。 | 一行大字 mono label（`shortLabel()`，例如 `Claude Code · sonnet`）+ neutral route kind badge + 由 `costClass` 生成嘅一句：`subscription` →「Your subscription pays · PostRiff records $0」；`paid` →「Counts one writing batch per run · {writingBatchesRemaining} left this period」（讀 `useUsage().data.entitlement`，冇值寫 Unavailable）；`none` →「No model request · $0」。第二行：「Used by Home and every conversation. Saved to this browser.」（P1 落地後改「Saved to your account」）。Fallback 提示：stored choice 唔 qualified 而 hook 跌返第一個 qualified model（`use-model.ts:39-42`）時，顯示「Your saved choice ({id}) is unavailable here; using {label} instead.」——hook 要多回一個 `storedUnavailable` 值。 | loading：Skeleton 一行；error：沿用最後一次 data，冇 data 就「Unavailable」+ Retry；冇 CLI / managed qualified：顯示 Deterministic preview（永遠 qualified）。 |
| Local CLI（agent cards） | 每條 CLI route 嘅真實狀態、點解未 ready、行喺邊。 | Card header：`agent.name` + `vendor` + `AnimatedBadge`（installed/authStatus：ok→success「Signed in」、missing→warning「Sign-in required」、expired→warning「Sign-in expired」、unknown→neutral「Status unknown」、!installed→neutral「Not installed」；`contentKey` = `${installed}-${authStatus}`）。Sub-line：version（冇就「version unknown」）· `login: {authMethod}` · 「runs on: the machine serving the API」（`host === 'api-process'`）。未 ready 時一行琥珀 guidance（`agent.guidance`，API 文案）。Models：motion `RadioGroup`（`web/src/components/motion/radio.tsx`，同 `features/workspace/voice-setup.tsx` 一樣 card 式），label = alias、description = `model.detail`；`disabled={!qualified}`。Reasoning 行（等 per-route reasoning 落地先出，唔好用頂層 fixture reasoning）：Quick / Standard / Deep chip，unavailable 灰色 + `detail`。`Collapsible`「How it runs」：Budget per run——Claude Code 顯示 `$${budgetUsd}`；Codex（或任何 budgetUsd 唔適用嘅 route）顯示「Not applicable · time limit and output cap only」，**P0 就改**，唔可以再出 $0.00；Time limit、Tools · MCP · settings、Session persistence、Environment passed（現有欄位）。P1：Budget 行變 owner 可改 Select（$0.25 / $0.50 / $1 / $2），非 owner 只讀 + 「An owner can change this」。 | agents 為空：`Empty`（`ui/empty.tsx`）三步：Install Claude Code or the Codex CLI on the machine that serves the API → sign in in Terminal → Rescan；hosted（`deployment.hosted`）改文案「On the hosted service a CLI will run through the desktop companion on your own computer. Not available yet.」——唔係 error 樣。rescan pending：badge `pulse`（真 mutation pending）。 |
| PostRiff（managed + preview） | 講清楚 PostRiff 自己嘅 route 幾時可用、要乜 consent、幾錢。 | Managed rows（`route === 'managed'`，P0 backend 加）：label、Available badge、`detail`、requirements chips 讀真值：「Per-source cloud consent」（固定要求，link 去 Ideas sources）、「Memory sharing: Shared / Not shared」（`egress.cloud`）、「Web research: On / Off」（`research.web`；`research.enabled === false` →「Off for this deployment」）；reasoning chips 三級（per-route catalog），Deep 加註「two model calls」。Preview row：「Deterministic preview · no model request · $0」+ Use by default。冇 gateway key：只有 preview row + 一句「A managed model is listed once this deployment has a gateway key.」（backend 唔再出 fixture 嘅 Not qualified stub）。 | managed 存在但 memory sharing off：row 照樣可揀（remind, don't block），chip 琥珀「Not shared」+「Drafts will not use your memory files until an owner turns sharing on.」；`useMemory` error：chips 顯示 Unavailable。 |
| Recent runs（P1） | 真數據證明邊條 route 真係寫過、花咗幾多。 | Table（`ui/table`，同 Billing ledger 樣式 `web/src/features/billing/billing-view.tsx` ledger table）：When（DateTimeFormat 跟 profile timeZone）· Writer（`shortLabel`）· Status（AnimatedBadge：completed/applied success、failed danger、cancelled neutral、running loading）· PostRiff cost（`usage.costUsd`，冇就 —）· CLI reported（`usage.cliCostUsd`，`null` 或冇就 —，Codex 永遠 —）· Provenance（`usage.provenance` 原值：provider_reported / estimated_from_tokens / reported_by_cli / measured_locally / pending）· Open（`/app/agent/{conversationId}`）。Table 上面 counts per route（`DigitSwap`）必須寫明範圍：「In the last {rows.length} runs: Claude Code {n} · Codex {n} · Managed {n} · Preview {n}」；或者 endpoint 回 server-side `countsByRoute` 先可以寫總數。 | 冇 runs：「No runs in this workspace yet. Write something on Home and it appears here.」；endpoint 404（未 deploy）：section 唔顯示，唔出 0；error：section 內 Alert + Retry。 |
| How each option is billed（右欄） | 解釋錢從邊度嚟，唔借 readiness 顏色。 | 由 catalog distinct `costClass` 生成（有邊種先出邊種），每行 neutral badge：subscription →「Uses the subscription you already have. PostRiff spends $0 and records what the CLI reports, when it reports one.」；paid →「Counts against writing batches on your plan; cost is metered to this workspace.」+ `Usage & plan ›`（`LearnMoreChevron`，只喺 `checkAccess(access, {permission: 'owner'})` 時出，因為 nav 係 owner-only）；none →「Deterministic, no model request, $0.」底部 `Privacy notice ›`（P0 privacy 修正之後先加）。 | 冇 data：整張 card 唔顯示。 |
| What a cloud model may read（右欄） | 唔使去 Memory 頁都知道 managed route 攞到乜。 | 三粒只讀 chip：Memory files（`egress.cloud` → Shared / Not shared，Shared 時「{sharedFiles.length} files · {withheldBoundaries} boundaries always withheld」）、Web research（`research.web`；`research.hosted === false` →「Always on when drafting on your own machine」；`research.enabled === false` →「Off for this deployment」）、Learning from edits with a cloud model（`learning.cloudExtraction`，冇 `learning` 就唔出呢粒）。底部 `Manage on Memory ›`（`LearnMoreChevron`），加一句「An owner decides these.」 | `useMemory` loading：Skeleton；error：card 顯示「Unavailable」，唔扮 Not shared。 |
| Where this runs + Desktop companion（右欄） | 誠實講清楚 CLI 行喺邊部機、hosted 幾時有。 | 「Where this runs」：讀 `deployment.hosted`（P0 backend 喺 catalog 加，值 = `research.hosted()`）：false →「CLI routes run on the machine serving this API. Everyone in this workspace shares that machine's CLI sign-in and subscription.」；true →「This is PostRiff's hosted service. CLI routes are not available here yet.」「Desktop companion」card：固定文案「On the hosted service, your own CLI will run through a desktop companion on your computer, with the same no-tools sandbox. Not available yet; this card will show the paired device when it is.」冇假 status、冇假 last seen。 | deployment 值未有：「Where this runs」唔顯示；companion card 永遠顯示；transport 落地後改讀 device rows（P2）。 |

- **Empty state**：兩種。(a) 本機 API 冇 CLI：`Empty` 教三步（Install Claude Code or the Codex CLI on the machine that serves the API → sign in with `claude auth login` / `codex login` in Terminal → press Rescan），Writing now strip 同時顯示 Deterministic preview 係現時 default（真係可用、免費、冇 model request），令人知道未有 CLI 都可以出稿。(b) hosted：同一個 Empty，文案「A CLI route will arrive with the desktop companion; PostRiff's managed model and the deterministic preview are what write here today.」——唔係 error tone；如果冇 gateway key，就只講 preview。Managed 未 mount：只出一句「listed once this deployment has a gateway key」。
- **Loading**：Header 即刻出（title / description / Rescan disabled，冇 Checked 文字）；Writing now strip 一條 Skeleton；Local CLI 兩張 `h-40` Skeleton；右欄兩張細 Skeleton。用 `ui/skeleton`。冇任何 loading 文字、冇假 progress。Rescan pending：StatefulButton loading、agent badge `pulse`，其他內容保持上次真值。
- **Error**：`useModels` error：頁頂 `Alert`（`ui/alert`）「The model list could not be loaded. {error.message}」+ Retry（`refetch()`）；有 last data 就照顯示，冇就 Writing now 寫「Unavailable」。401（session 過期，catalog gate 之後）：沿用 app-gate 登入流程，唔喺頁內扮 empty。Rescan 失敗：Sonner error toast 用 API message，button 回 idle，badge 保持上次真值。`useMemory` / `useUsage` / runs 各自失敗只影響自己嗰張 card（Unavailable）。冇 edit 權限：PageContainer accessFallback。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁 | route 進入 | page-slide 浮入 | `web/src/app/app/template.tsx` `.t-page-enter` | 否（純裝飾） |
| Rescan button | click | idle → loading（真 mutation pending）→ success check / error；之後「Checked just now」讀 API `probedAt` | `web/src/components/motion/button` StatefulButton（`features/channels/channel-card.tsx:283` Re-verify 同款） | 是 |
| Agent auth badge | catalog data 變（rescan 後） | AnimatedBadge content swap；`pulse` 只喺 rescan pending；reduced motion 時直接換字 | `web/src/components/motion/animated-badge.tsx` `contentKey` / `pulse` | 是 |
| Writing now label | 用戶揀咗新 default | TextScramble 解碼；載入時唔播（`animate={picked}`）；reduced motion 唔 scramble | `web/src/components/motion/text-scramble.tsx`（`features/agent/model-picker.tsx:40` 同一規則） | 是 |
| Model 選項 | 揀 model | RadioGroup indicator 移到新選項 | `web/src/components/motion/radio.tsx`（`features/workspace/voice-setup.tsx` 用緊） | 是 |
| Recent runs counts | runs data 到達 / 更新 | DigitSwap 逐位滾動；冇 data 唔 render；reduced motion 直接換數 | `web/src/components/motion/digit-swap.tsx` | 是 |
| Run status cell | status 變（poll 到 running → completed） | AnimatedBadge swap | `web/src/components/motion/animated-badge.tsx` | 是 |
| How it runs | 展開 / 收埋 | Base UI `data-starting-style` 開 250ms / 收 150ms（收快過開） | `web/src/components/ui/collapsible.tsx` + `web/src/styles/transitions.css` token | 否（純裝飾） |
| Rescan 結果 toast | mutation settled | Sonner 入 / 出（出快過入），文字 = API 回嘅 agent name + version + auth state | `web/src/components/ui/sonner.tsx` | 是 |
| Manage on Memory › / Usage & plan › | hover | 箭嘴滑出 | `web/src/components/ui/learn-more-chevron.tsx` | 否（純裝飾） |
| Skeleton | loading | pulse | `web/src/components/ui/skeleton.tsx` | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Catalog endpoint `GET /api/ideas/models` 回 models + reasoning + agents | api | 有 | src/postriff_phase2/hosted_app.py:303-312；src/postriff_phase2/ideas.py:102-109 | S |
| 2 | AgentInfo probe（version / authStatus / authMethod / execution / host） | backend | 有 | src/postriff_phase2/cli_runtime.py:210-234；src/postriff_phase2/codex_runtime.py:68-101 | S |
| 3 | authStatus `expired` 由 API 出 | backend | 有 | src/postriff_phase2/cli_runtime.py:238-254；UI 未處理：web/src/features/account/models-view.tsx:25-30 | S |
| 4 | `POST /api/ideas/models/rescan`：登入後 force re-probe 每個 runtime（`detect(force=True)`），回新 catalog | api | 冇 | `detect(force)` 存在（cli_runtime.py:210）但 `describe()` 冇 force（cli_runtime.py:259-260；base agent_runtime.py:56）；hosted_app.py 冇 rescan route；models-view.tsx:111 只係 invalidateQueries | S |
| 5 | AgentInfo 加 `probedAt`（epoch） | backend | 冇 | `self._probe_at` 私有（cli_runtime.py:195,233），唔喺 info dict（cli_runtime.py:213-214） | S |
| 6 | Catalog 要求 session，但保留 API 未配置時 fixture fallback | api | 冇 | hosted_app.py:303 喺 `:339 self._runtime()` / `:340 self._token(environ)` 之前；fallback 喺 :305-310 靠 catch AlphaError；web/src/lib/api/client.ts:105 `get(..., false)`；tests/test_postriff_consumer_web.py:181-182 用未登入 GET | S |
| 7 | Managed option 帶 `route: 'managed'`；fixture `server-openai` stub 喺有 paid runtime 時唔列 | backend | 冇 | src/postriff_phase2/model_runtime.py:104 冇 route；src/postriff_phase2/agent_runtime.py:69 永遠列 stub；ideas.py:102-109 冇過濾 | S |
| 8 | Per-route reasoning 喺 catalog（`agents[].reasoning` + managed / fixture 各自一份） | api | 冇 | ideas.py:109 只出 fixture 嘅 `self.runtime.list_supported_reasoning()`；cli_runtime.py:269-270；model_runtime.py:107-110 | S |
| 9 | Codex「budget 不適用」要喺 API 表達（`budgetUsd: null` 或 `budgetApplies: false`），UI 唔再顯示 $0.00 | backend | 冇 | codex_runtime.py:101 `budgetUsd: 0.0`；models-view.tsx:80 `${budgetUsd.toFixed(2)} · stops the run, never overcharges`；types.ts:305-313 budgetUsd 係 number | S |
| 10 | Catalog 加 `deployment: {hosted: bool}`（= research.hosted()）畀「Where this runs」同 hosted empty state | api | 冇 | research.py:80-81 有 `hosted()`；/api/catalog `execution`（hosted_app.py:285）預設 'hosted'、dev harness 'dev-synthetic'（scripts/postriff_dev_hosted.py:184），唔可以用嚟分本機；過渡期可讀 ResearchEgress.hosted（types.ts:430） | S |
| 11 | Cloud consent 資料（memory egress / research / learning） | api | 有 | web/src/lib/api/client.ts:145；hooks.ts `useMemory`；types.ts:332-340, 364, 423-432；memory-view.tsx:66-160 用緊 | S |
| 12 | Writing batches remaining（paid route 真數） | api | 有 | billing.py:47, 110-131 `usage_view` → `entitlement.writingBatchesRemaining`；hosted.py:316-322 只要 membership；hooks.ts:44-47 `useUsage` | S |
| 13 | Page access gate（edit）+ owner-only 元素判斷 | frontend | 冇 | web/src/lib/auth/access.tsx:69 `checkAccess`；page-container.tsx:44-66 支援 access；models-view.tsx:106 冇傳；nav-config.ts:168-174 只 filter nav；Usage & plan nav owner-only（nav-config.ts:155-161） | S |
| 14 | Default writer 存喺 account（`PATCH /api/me` `defaultModel`，`Me.preferences.defaultModel`；只驗格式，唔要求喺而家 catalog 內） | data | 冇 | migrations/postriff/011_account_preferences.sql 只有 time_zone / locale / alert_new_device；hosted.py:570-626；types.ts:664；use-model.ts:6 用 localStorage | M |
| 15 | `GET /api/workspaces/{w}/ideas/runs?limit=20`（model、status、created_at、usage.costUsd / cliCostUsd / provenance、conversationId；可選 countsByRoute） | api | 冇 | table：migrations/postriff/005_consumer_web_ideas.sql:40-57（index workspace_id, conversation_id, created_at desc :59）；只有 per-run events route hosted_app.py:252-262 | M |
| 16 | Claude Code per-run budget 做 workspace setting（owner）而唔係 env | backend | 冇 | cli_runtime.py:29,190 讀 env；argv cli_runtime.py:320；失敗訊息 cli_runtime.py:108；permissions.py:27-38 ACTION_CLASSES 冇 `agent_settings`（缺省 = edit） | M |
| 17 | Privacy notice 跟 mounted runtimes 生成 | backend | 冇 | src/postriff_phase2/privacy.py:22-27 SUBPROCESSORS 同 `aiProcessing` 寫死；model_runtime.py:22 已經行 Vercel AI Gateway；route hosted_app.py:286-288 | S |
| 18 | Page tour 登記 + `data-tour` ids | frontend | 冇 | tours.ts PAGE_TOURS（:156+）冇 `/app/account/models`；models-view.tsx 冇任何 data-tour | S |
| 19 | Motion / UI components：StatefulButton、AnimatedBadge、TextScramble、RadioGroup、DigitSwap、Collapsible、LearnMoreChevron、Empty、Alert、Skeleton、Sonner、Table | frontend | 有 | web/src/components/motion/{button/stateful.tsx,animated-badge.tsx,text-scramble.tsx,radio.tsx,digit-swap.tsx}；web/src/components/ui/{collapsible,learn-more-chevron,empty,alert,skeleton,sonner,table}.tsx | S |
| 20 | Desktop companion transport（device probe、device rows） | infra | 冇 | docs/postriff-agent-chat-design.md:594（§11b）；hosted_app.py 冇 import postriff_phase3（src/postriff_phase3/transport.py 存在但未接） | L |
| 21 | Tests：catalog 已有；rescan / expired 清除 / catalog auth gate 未有 | backend | 冇 | 已有：tests/test_postriff_cli_runtime.py、tests/test_postriff_codex_runtime.py、tests/phase2/postgres_cli_route.py:92-95、tests/test_postriff_consumer_web.py:181-182；冇 rescan / 401→expired→rescan / 未登入 401 斷言 | S |

## 3. Features

### P0

- **Rescan 真係 rescan（force probe + probedAt + StatefulButton）**：而家撳 Rescan 只係 refetch 一個 60 秒 cache，而且永遠清唔到 401 之後嘅 `expired`（cli_runtime.py:238-254）——「sign in then rescan」呢個承諾（infoContent、guidance 文案）實際上係死路。真數據先郁：顯示 API 回嘅 probedAt，唔係假「Scanning…」。
- **完整 auth state 詞彙 + Codex budget 誠實化**：`expired` 係 API 已經出嘅真狀態，UI 顯示「Status unknown」等於丟走真資料；Codex 顯示「$0.00 · stops the run」係假數字（codex_runtime.py:101 → models-view.tsx:80）。Readiness 用綠 / 琥珀 / 灰，永遠唔出混合式「Ready ✓」；route kind 用 neutral badge。（depends on：無）
- **誠實 route inventory：kind、host、costClass、consent 前提、per-route reasoning；billing 文案由 API 生成；fixture stub 唔再同真 managed route 撞**：有 gateway key 時同一頁出「Not qualified」同「Available」兩個 managed——自相矛盾；頂層 reasoning 係 fixture 版本，用戶冇地方知 managed 有三級。Consent chips 讀 `/memory` 真值，managed route 唔跟 memory 嘅原因即場睇到（remind, don't block：仍然可以揀）。
- **Catalog 收返做登入後先攞 + page access gate**：`/api/ideas/models` 未登入攞到 serve API 嗰部機嘅 CLI version、authMethod、env key 名；所有用家（home-view、conversation-view、ideas-view、models-view）都喺 /app 入面，收返冇代價，但要保留未配置 fallback 同改 consumer_web test。頁面亦要用 `checkAccess` gate，唔只靠 nav。

### P1

- **Default writer 存喺 account（跟人走），頁面講明 fallback**：而家存 localStorage：換機、換 browser、甚至另一個 tab 都唔同步。存 `pr_profiles`（migration 011 person-level 模式）就跨 workspace 一致；localStorage 留做 cache；id 唔喺當前 catalog 就行 fallback 提示，唔拒絕儲存。（depends on：P0 route key（managed 要有穩定 id））
- **Recent runs by route（`GET /ideas/runs`）**：係「錢從邊度嚟」嘅收據：邊條 route 寫過、狀態、PostRiff 花幾多 vs CLI 自己報幾多（Codex 冇報就 —）、provenance。Ledger 唔夠：CLI route 一律 $0。Counts 必須寫明範圍。可見範圍（全 workspace 定自己）要先定。
- **Claude Code per-run budget 做 owner 可改嘅 workspace setting**：失敗訊息已經叫用戶「raise the budget in Models & providers」（cli_runtime.py:108），頁面冇掣。（depends on：P0 rescan（改完要見到新值））

### P2

- **Default reasoning per route（composer 送 `reasoning`）**：managed Standard / Deep 已經 implement（deep = 兩次 call）但 composer 永遠送 quick。P0 只顯示 availability；default setting 同 composer 改動留 P2，因為要改 web/src/features/agent（其他 session 常改範圍）。（depends on：P0 per-route reasoning 喺 catalog）
- **Desktop companion device card**：Design doc §8.4 原本要有；transport 未做（§11b），而家只放誠實 placeholder。（depends on：companion transport（infra L））
- **BYOK：自己嘅 OpenAI-compatible endpoint + key**：`ServerModelRuntime` 已經係 OpenAI-compatible transport（model_runtime.py:45-65），加 per-workspace key（走 CredentialVault）係自然延伸；競品需求（Postiz issue、Blotato）屬外部資料，今次未核實。（depends on：P1 runs list）

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明：（1）有三種 writer——serve API 嗰部機上面嘅 CLI（用你已付費嘅訂閱）、PostRiff managed（按 writing batch 計，行喺 PostRiff server）、Deterministic preview（免費、冇 model request）；（2）揀咗嗰個就係 Home 同每個 conversation 用嘅 writer；（3）冇嘢會靜靜地花錢。「Writing now」strip 講第 2 點，neutral route badge + readiness 顏色講第 1 點，costClass 生成嘅一句講第 3 點。文案對設計師、老師、店主、developer 讀落一樣，唔提任何品牌或個人例子。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="models-current"]（要加；fallback：main [data-slot="heading"] h1，tours.ts:51 已有）` | What writes your drafts now | This is the writer Home and every conversation use. Pick a different one below and it changes straight away; every run still shows which writer produced it. |
| 2 | `[data-tour="models-cli"]（要加；empty 時 [data-tour="models-empty"]）` | A CLI you already pay for | A coding CLI signed in on the machine that serves PostRiff can write for you. It runs with no tools and no MCP servers, and PostRiff never reads its login. Green means signed in; amber tells you what to run in Terminal. |
| 3 | `[data-tour="models-managed"]（要加）` | PostRiff's writers | The managed model runs on PostRiff's server and counts one writing batch per run. It only reads sources you allowed for the cloud. The deterministic preview is always available and never calls a model. |
| 4 | `[data-tour="models-rescan"]（要加喺 Rescan StatefulButton）` | Signed in just now? Rescan | PostRiff checks each CLI when this page loads and remembers the result for a minute. After you sign in or out in Terminal, press Rescan for a fresh check. |
| 5 | `[data-tour="models-consent"]（要加）` | What a cloud model may read | These show what the managed model may see right now: memory files, web research and learning from edits. An owner changes them on the Memory page. |

**Empty state 教咩**：（本機 API）Deterministic preview 而家就係你嘅 writer，真係會出稿、免費；加一條 CLI route 只需三步（install → sign in in Terminal → Rescan），PostRiff 唔會喺 app 入面收密碼；CLI 行喺 serve API 嗰部機，唔一定係你面前嗰部。（hosted）managed model（如有 gateway key）同 preview 係而家可用嘅 writer；CLI route 會隨 desktop companion 嚟，未有就話未有，唔扮 error。

## 5. Next steps（按次序）

1. **Backend：`describe(force=False)` / `model_catalog(force=False)` 傳到 `detect(force)`；AgentInfo 加 `probedAt`；Codex `execution.budgetUsd` 改 `null`（types.ts 改 `number | null`）；catalog 加 `deployment: {hosted: research.hosted()}`；新 route `POST /api/ideas/models/rescan`（`_token` 之後，任何登入用戶）回同 GET 一樣嘅 catalog。Tests：fake claude missing → login → rescan 變 ok；401 → expired → rescan 清走。**（effort S）  
   檔案：`src/postriff_phase2/ideas.py:102-109；src/postriff_phase2/agent_runtime.py:56；src/postriff_phase2/cli_runtime.py:210-260；src/postriff_phase2/codex_runtime.py:68-101；src/postriff_phase2/hosted_app.py:303-312（新 route 放 :340 之後）；tests/test_postriff_cli_runtime.py；tests/test_postriff_codex_runtime.py`
2. **Backend：`/api/ideas/models` 搬到 `self._token(environ)` 之後；API 未配置（`_runtime()` raise）時喺搬之前保留一個明確 fixture fallback 或者回 503 + 前端 Unavailable（二揀一，唔可以靜靜變空）；web client `models: () => get(..., true)`；改 `tests/test_postriff_consumer_web.py:181-182` 帶 auth，並加未登入 401 斷言。**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:303-312, 339-340；web/src/lib/api/client.ts:105；tests/test_postriff_consumer_web.py:181-182`
3. **Backend：managed options 加 `route: 'managed'`、preview 加 `route: 'fixture'`；`model_catalog()` 有 paid runtime 時剔走 `server-openai` stub；catalog 加 per-route reasoning（`agents[].reasoning`、managed / fixture 各自）；types.ts 同步。**（effort S）  
   檔案：`src/postriff_phase2/model_runtime.py:103-110；src/postriff_phase2/agent_runtime.py:66-77；src/postriff_phase2/ideas.py:102-109；web/src/lib/api/types.ts:282-320；tests/phase2/postgres_cli_route.py:92-95`
4. **Web：重寫 models-view.tsx——PageContainer access gate、Writing now strip（+ `useModelChoice` 回 storedUnavailable）、AnimatedBadge auth 詞彙（含 expired）、neutral route badge、RadioGroup models、per-route reasoning chips、Collapsible「How it runs」（Codex Not applicable）、consent chips（`useMemory`）、「Where this runs」（`deployment.hosted`）、costClass billing card（owner 先見 Usage link）、companion placeholder、全部 `data-tour`；Rescan 用 `useRescanModels` mutation（`setQueryData(keys.models)`）+ StatefulButton + toast；375px header / card list 行為。**（effort M）  
   檔案：`web/src/features/account/models-view.tsx；web/src/lib/api/hooks.ts（useRescanModels）；web/src/lib/api/client.ts（rescanModels）；web/src/lib/api/types.ts；web/src/features/agent/use-model.ts（只加回傳值，stage by path）`
5. **Web：tours.ts PAGE_TOURS 加 `models-tips`（route `/app/account/models`，5 步）；infoContent 更新（三種 writer、rescan 規則、companion 未有）。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts（PAGE_TOURS :156+）；web/src/features/account/models-view.tsx:16-23`
6. **Backend：`privacy.notice()` 接受 mounted routes，「AI model provider」同 `aiProcessing` 按有冇 ServerModelRuntime 出「Vercel AI Gateway · in use」定「not mounted」；billing card 加 `Privacy notice ›`。**（effort S）  
   檔案：`src/postriff_phase2/privacy.py:22-40；src/postriff_phase2/hosted_app.py:286-288；web/src/features/account/models-view.tsx`
7. **Backend + web：migration 013 `pr_profiles.default_model text not null default ''`（length check）；`me()` / `update_profile()` 加 `defaultModel`（只驗格式）；`useModelChoice` 先讀 `me.preferences.defaultModel`，localStorage 做 cache；揀 model 即 `PATCH /api/me`，strip 文案改「Saved to your account」。**（effort M）  
   檔案：`migrations/postriff/013_default_model.sql（新）；src/postriff_phase2/hosted.py:570-626；web/src/lib/api/types.ts:651-664；web/src/features/agent/use-model.ts；web/src/features/account/models-view.tsx`
8. **Backend + web：先定可見範圍（member 見全 workspace 定只見自己），再做 `GET /api/workspaces/{w}/ideas/runs?limit=20`（`_ideas` resource `runs`、len(parts)==5、GET；SQL 讀 pr_agent_runs by workspace order created_at desc；可選 `countsByRoute`）；type `RunSummary`；hook `useRuns`；Recent runs table / mobile card list + 有範圍嘅 DigitSwap counts。**（effort M）  
   檔案：`src/postriff_phase2/hosted_app.py:_ideas（:231-262）；src/postriff_phase2/ideas.py（新 `runs()`）；web/src/lib/api/{client.ts,hooks.ts,types.ts}；web/src/features/account/models-view.tsx；tests/phase2/postgres_cli_route.py`
9. **Backend + web：workspace action `agent_settings {cliBudgetUsd}`，喺 ACTION_CLASSES 明寫 `"agent_settings": "owner"`（clamp 0.05–5.00）；`ideas.turn()` 將 `budgetUsd` 放入 request；`ClaudeCliRuntime` argv / `execution_settings` 用 request 值（冇就 env default）；頁面 Select 四個 preset，非 owner 只讀；Codex 維持 Not applicable。**（effort M）  
   檔案：`src/postriff_phase2/permissions.py:27-38；src/postriff_phase2/hosted.py（mutate 分派）；src/postriff_phase2/ideas.py:336-390；src/postriff_phase2/cli_runtime.py:190,256-257,320；web/src/features/account/models-view.tsx`
10. **Infra（P2）：companion transport（device probe、`/api/ideas/models` 合併 device rows、rescan 經 companion）；companion card 讀真 device 資料。**（effort L）  
   檔案：`src/postriff_phase3/{hosted.py,transport.py,adapters.py}；src/postriff_phase2/hosted_app.py；web/src/features/account/models-view.tsx`

## Risks

- `/api/ideas/models` 未登入可讀：洩露 serve API 嗰部機嘅 CLI version、authMethod、host、env key 名（hosted_app.py:303）；第 2 步之前唔好對外 demo。
- Gate catalog 時如果直接搬去 `_runtime()` 之後，未配置嘅 API 會由「fixture fallback」變 error，Home composer 同 ideas-view 會一齊冇 model list——要同步處理。
- Rescan 清唔到 `expired`（cli_runtime.py:238-254）：用戶 sign in 完會以為 PostRiff 壞咗；第 1 步之前 infoContent 唔應該承諾「then rescan」。
- Codex budget 顯示 $0.00（codex_runtime.py:101 → models-view.tsx:80）係現存假數字，第 1、4 步之前要當已知錯誤。
- 有 gateway key 時 fixture stub「Not qualified」同真 managed「Available」並列——違反 capability honesty。
- Privacy notice（privacy.py:26 同 aiProcessing）仲話冇 AI provider，而 managed route 行 Vercel AI Gateway：審批 / 法律審閱時會被指不一致。
- Default 存 localStorage：同一人兩個 browser / tab 見到唔同 default；P1 之前文案必須寫「Saved to this browser」。
- CLI 行喺 serve API 嗰部機：多人共用本機 deployment 時共用同一個 CLI 登入同訂閱——文案寫「the machine serving the API」，唔寫「your machine」。
- Codex usage limit 只有 run 時先知（codex_runtime.py:43-49）：頁面唔可以扮顯示 quota，只可以喺 Recent runs 見失敗原因。
- Managed deep reasoning = 兩次 model call（model_runtime.py:249-259）：開放 default reasoning 時 chip 旁一定要講「two model calls」。
- Recent runs counts 由有限 list 計，冇寫範圍就變假總數。
- Budget 做 workspace setting：companion 落地後（每人自己部機）要轉 person-level；而家 workspace-level 係因為 CLI 只行喺一部機。
- Parallel sessions：另一 session 常改 web/src；第 4、7 步改 `use-model.ts` / hooks.ts 會撞，commit 要 stage by path。
- Hosted（Vercel）冇 CLI：Local CLI empty state 唔可以似 error，否則用戶以為要裝嘢先用得。

## 覆核記錄

- 改正：useModelChoice 喺 use-model.ts:29-56，fallback 喺 :38-41 → 改做 use-model.ts:28-55，fallback :39-42
- 改正：Claude Code probe 喺 cli_runtime.py:180-220 → cli_runtime.py:210-234
- 改正：cost_class subscription 喺 cli_runtime.py:150；paid 喺 model_runtime.py:87；ledger ideas.py:389-390 → cli_runtime.py:184
- 改正：Gap 1：describe() 冇 force（cli_runtime.py:222）、cache 60 秒（:181）、_auth_failed 只有 force reset（:209-215） → cli_runtime.py:259-260、:211、:238-254
- 改正：Gap 2：expired 由 cli_runtime.py:211-213 出；authBadge models-view.tsx:25-30 只處理 ok/missing → cli_runtime.py:242-244
- 改正：Gap 3：失敗訊息 cli_runtime.py:119、env cli_runtime.py:157 → 改行號；另補：Codex execution_settings 回 budgetUsd 0.0（codex_runtime.py:101），現有 UI（models-view.tsx:80）顯示『$0.00 · stops the run, never overcharges』——係而家就有嘅假數字，唔係 P1 小事
- 改正：Gap 6：CLI reasoning cli_runtime.py:236-237；managed model_runtime.py:107-110；deep :249-259；composer 冇送 reasoning；ideas.py:338 永遠 quick → cli_runtime.py:269-270
- 改正：Gap 7：pr_agent_runs 005:40-58；events route hosted_app.py:257-277；ledger billing.py:114-118；usage route hosted_app.py:384-385；cliCostUsd cli_runtime.py:470-472；activity-strip.tsx:48-55 → 更正行號；Codex 行 CLI reported 必須顯示 —，唔係 $0
- 改正：Nav nav-config.ts:172-178 icon adjustments access permission edit → nav-config.ts:168-174
- 改正：tech req：`execution`（hosted / local）由 hosted_app.py:296 /api/catalog 回 → 「Where this runs」唔好讀 /api/catalog execution；喺 /api/ideas/models 加 `deployment: {hosted: research.hosted()}`，或者暫時讀 useMemory().research.hosted
- 改正：tech req：AgentInfo 冇 probedAt，_probe_at 私有 cli_runtime.py:198，info dict :183-185 → cli_runtime.py:195,213-214,233
- 改正：next_steps files：cli_runtime.py:180-222、agent_runtime.py:60、cli_runtime.py:157,219,274、hosted_app.py:298-300、_ideas :231-278 → 見 corrected_spec.next_steps
- 改正：Writing now strip：Local CLI = Direct 綠、Managed = Assisted 琥珀 → Route kind 用 neutral outline Badge（Local CLI / PostRiff managed / Preview）；綠/琥珀/灰只留畀 readiness（Signed in / Sign-in required / Not installed）
- 改正：Recent runs counts per route（DigitSwap）由 runs list 計 → label 寫明「in the last {n} runs」，n = 實際回嘅行數；或者 endpoint 回 server-side `countsByRoute`
- 改正：Page access 由 nav-config permission edit 保護 → ModelsView 用 `checkAccess(useWorkspaceAccess(), {permission:'edit'})` 傳 access + accessFallback
- 違反原則（已改）：真數據先郁：現有頁面對 Codex 顯示「$0.00 · stops the run, never overcharges」（codex_runtime.py:101 budgetUsd 0.0 → models-view.tsx:80），係假數字；spec 將修正排喺 P1 budget setting 之後，應該升 P0 同 expired badge 一齊修。
- 違反原則（已改）：真數據先郁：Recent runs 嘅 per-route DigitSwap counts 由 limit=20 list 計，冇講明範圍就等同假總數。
- 違反原則（已改）：Capability honesty：用 LevelBadge Direct/Assisted 標 route kind（Local CLI 綠 / Managed 琥珀），將 readiness 顏色借去做分類，同一頁又用綠色表示 Signed in——兩種意思撞色。
- 違反原則（已改）：Capability honesty：「Where this runs」讀 /api/catalog `execution` 分 hosted/local，但呢個值從來唔會係 local（hosted_app.py:285 default 'hosted'，dev harness 'dev-synthetic'），本機 deployment 會被講成「PostRiff's hosted service」。
- 違反原則（已改）：Capability honesty：catalog `reasoning` 喺 managed mounted 時仍然係 fixture 版本，spec 嘅 reasoning chips 要等 per-route reasoning 落地先可以顯示，唔可以用現有頂層 reasoning 頂住。
- 補上遺漏：RBAC：頁面本身冇 access gate（只有 nav 隱藏）；要講 viewer 直接入 URL 見到乜；budget Select 要 owner（permissions.py 新 action class）；Usage & plan link 係 owner-only（nav-config Usage & plan access owner）。
- 補上遺漏：Unconfigured API fallback：catalog 搬去 _token 之後，hosted_app.py:339 `self._runtime()` 會先 raise，現有 FixtureAgentRuntime fallback（:305-310）會失效，要保留一條路。
- 補上遺漏：tests/test_postriff_consumer_web.py:181-182 用未登入 GET 斷言 200，gate 之後必然 fail，要喺 next step 明寫改 test。
- 補上遺漏：Codex usage-limit / auth 失敗（codex_runtime.py:43-49）只喺 run 出；頁面應顯示「last run failed: {reason}」而唔係扮 quota。
- 補上遺漏：Multi-tab / multi-device：localStorage default 喺其他 tab 唔同步（冇 storage event listener）；P1 account 存儲之前要講明。
- 補上遺漏：i18n：web 冇 UI translation library（只有 @react-aria/i18n），worldwide-languages plan 係講 post 語言唔係 UI；頁面文案維持 English，但「Checked 12s ago」同 run 時間要用 Intl.RelativeTimeFormat / DateTimeFormat 跟 Me.preferences.locale / timeZone。
- 補上遺漏：Mobile：Rescan + probedAt 喺 375px header 放唔落，要定義收埋去 button tooltip / 下一行；Recent runs table 喺 375px 應改 card list 而唔只係 overflow-x。
- 補上遺漏：Runs list 私隱：teammate 嘅 runs 係咪全 workspace 可見（actor 欄），要決定 member read 定只見自己 + owner 見全部。
- 補上遺漏：Default writer 驗證：唔同 deployment 嘅 catalog 唔同，PATCH /api/me 唔應該要求 id 喺『而家』catalog 內，只驗格式；fallback 提示負責講清楚。
- 補上遺漏：Reduced motion：TextScramble / DigitSwap / RadioGroup 喺 prefers-reduced-motion 下嘅行為冇寫。
