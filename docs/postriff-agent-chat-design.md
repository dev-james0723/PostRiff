# PostRiff — Agent Chat（Home）設計方案

> 狀態：提案 / 待決策
> 日期：2026-09-16
> 範圍：喺 `web/` 加一個以 AI agent chat 為中心嘅 Home 頁，接駁 user 自己嘅 Claude Code / Codex CLI，
> 管理 memory 檔案，做 voice onboarding，自動揀 skills，並可以由 chat 直接排好 posts。
> 視覺稿：canvas「PostRiff Agent Chat」（5 個 artboard：Home、Conversation、Onboarding、Models & providers、Memory）
> → https://claude.ai/artifact/QQrr4CkQyK7L1B5ChV4NXv （用 app 嘅 `vercel` theme token 畫，可以直接改）。
> 參考對象：[`nexu-io/open-design`](https://github.com/nexu-io/open-design) v0.22.1（調研日期同上）。

---

## 0. 執行摘要

三句講完：

1. **OpenDesign 最值得抄嘅唔係個靚 UI，係佢「adapter 係 data、engine 係 generic」嘅 CLI 接駁方式**，
   加上「chip 綁 skill 而唔係綁 prompt」同「memory 係 Markdown 檔案」。呢三樣我哋嘅 codebase 已經有八成基礎。
2. **我哋同 OpenDesign 有一個結構性分別：佢係 local-first desktop app，我哋係 hosted web。**
   Hosted API 冇可能 spawn user 部 Mac 上面嘅 CLI。所以「接 Codex / Claude CLI」一定要行
   **Desktop companion（Bridge）**——而呢件嘢 `desktop/` + `postriff_phase3` 已經起咗一半（pairing、`OutboundHost`、`RuntimeAdapter.argv`）。
3. **Agent 只可以 propose，唔可以 publish。** 「今日 4 點 IG、5 點 LinkedIn、聽日 3 點半 FB」呢個 flow
   係 agent 出一張 *Schedule plan card* → user 一次過 approve → 行現有 `review` + `approve_many` chain →
   Queue / Calendar 自然見到。呢個 invariant（`requirements-ledger.md` 第 107 行）唔郁。

---

## 1. OpenDesign 調研摘要

### 1.1 Tech stack

| 層 | OpenDesign | 我哋 |
|---|---|---|
| Shell | Electron 41，thin shell，兩個 sidecar（daemon + web） | Electron 44（`desktop/`），Python sidecar |
| Web | Next.js 16 App Router + React 18，Tailwind v4 + CSS Modules，Lexical composer | Next.js 16 + React 19，Tailwind v4 + shadcn（base-ui） |
| Daemon | Node Express 5，SSE，better-sqlite3，node-pty，MCP SDK | Python WSGI（`hosted_app.py`），SSE + cursor replay 已有 |
| State | 無 Redux / Zustand，localStorage-backed modules 同 daemon sync | TanStack Query + Zustand |
| Persistence | SQLite：`projects / conversations / messages / message_event_batches / agent_sessions` | Postgres：`pr_conversations / pr_messages / pr_attachments / pr_agent_runs / events`（migration 005） |

### 1.2 CLI 接駁（佢個 "Local CLI" tab 背後）

- **一個 CLI 一個 `RuntimeAgentDef` data object**（27 個），定義 `bin, versionArgs, buildArgs(), streamFormat,
  eventParser, authProbe, listModels, resume flags, inactivityTimeoutMs`。Generic engine 負責 spawn / parse / cancel。
- **啟動時並行 probe** 每個 def：搵 binary → `--version` → help-text capability probe → model list → auth probe。
  `GET /api/agents?stream=1` 逐個 SSE 出 `AgentInfo {available, version, authStatus, models, modelsSource: 'live'|'fallback'}`，
  Settings card 逐張亮起（呢個就係 screenshot 入面 "Synced from CLI" / "Authentication required" 嘅來源）。
- **Claude Code**：`claude -p --input-format stream-json --output-format stream-json --verbose [--include-partial-messages]
  [--model X] [--add-dir …] (--resume <id> | --session-id <uuid>) --permission-mode bypassPermissions`，
  prompt 由 stdin 送 JSONL，**stdin 唔閂**，所以 run 中途可以「steer」（再塞一句 user message）。Auth probe：`claude auth status`。
- **Codex**：預設 `codex app-server`（stdio JSON-RPC：`thread/start`、`turn/start`），legacy 係
  `codex exec --json --sandbox workspace-write -C <cwd>`；models 用 `codex debug models`；auth 用 `codex login status`；
  session id 由 stream 嘅 `thread.started` 捕捉。
- **Cursor Agent**：`cursor-agent --print --output-format stream-json`；auth `cursor-agent status`。
- 全部 stream 都 normalise 做一個 SSE event union：`status, text_delta, thinking_delta, tool_use, tool_result, usage,
  done_key, next_steps, conversation_title, error`。
- **Session resume 有 identity guard**：model / cwd / 最後一條 assistant message / prompt hash 任何一樣變咗就唔 resume，改為重播 transcript。
- **Permission 係固定每個 def**（bypass / yolo），冇 interactive approval UI。← 呢點我哋**唔抄**。

### 1.3 Chat UI

- **Home**：一張 composer card + intent chip rail（Prototype / Slide deck / Image / Document / HyperFrames / Website clone…）。
  **每個 chip 綁一個 scenario plugin（skill），唔係一段 system prompt。** Composer footer 有 Design system picker、Working directory picker、
  同一粒 `InlineModelSwitcher` chip（Mode: Local CLI | BYOK → Agent → Model → reasoning）。「+」menu：Attach、Reference project、Skills、Connectors、MCP。
- **Studio**：左 chat、右 preview，寬度可拖並記住。
- **Message rendering**：一個 pure function 將 turn 嘅 event list 變成 blocks（`ToolRow`、`ShellText`、`ShellPlan`、`ShellTodo`），
  有明確 degradation 規則（冇 tool event 就淨係出文字，唔會出假 placeholder）。用一個每次 run 隨機嘅 `<od-done key>` marker
  分開「過程敘述」同「最後答案」。
- **Structured questions**：agent 可以出 `<question-form>`（radio / checkbox / colour / direction cards），唔係淨係文字問。

### 1.4 Skills、Design systems、Memory

- Skills = Agent Skills 格式（`skills/<name>/SKILL.md`），163 個。**注入方式**：daemon 將選中嘅 SKILL.md 內容 compose 入 system prompt，
  同時**copy**（唔係 symlink）成 `<project-cwd>/.od-skills/<name>-<hash>/`，等 side files 可以讀到。唔會寫入 `~/.claude/skills`。
- Design systems = `DESIGN.md + tokens.css`，compose 順序 `USAGE → DESIGN → tokens → components → craft → skill`。
- **Memory = `<dataDir>/memory/MEMORY.md` index + `<type>_<slug>.md`**，frontmatter `type: profile|user|feedback|project|reference|rule`，
  `source: heuristic|llm|manual|connector`。每個 turn 有 heuristic extraction，可選用細 model 做 LLM pass，
  仲有一個 "Keep gate" 先至真正入 memory。「Instructions & rules」= 全域 `customInstructions` + 每 project 嘅 instructions。

### 1.5 對照 `OpenCoworkAI/open-codesign`

佢**唔 spawn CLI**，係「一鍵 import」Claude Code / Codex 嘅 API key config 落自己 `config.toml`，然後自己行 agent loop（pi-ai）。
簡單、provider-agnostic，但失去 CLI 原生嘅 session / memory / tools。**我哋唔行呢條路**：James 想用嘅正正係 Claude Code 嘅 skills 同 memory。

### 1.6 抄乜、唔抄乜

| 抄 | 唔抄 |
|---|---|
| adapter-as-data + generic engine | bypassPermissions / yolo 固定權限 |
| `--help` capability probe、live vs fallback model list | BYOK key 放 browser localStorage |
| progressive detection SSE + auth classifier | 自己養一個 agent loop（open-codesign 式） |
| chip 綁 skill；`@` mention 加 skill | 無 approval UI |
| copy skills 入 cwd；SKILL.md compose 入 system prompt | |
| Markdown memory + Keep gate | |
| event union → pure "turn → blocks" builder | |
| structured `<question-form>` | |

---

## 2. 我哋已經有嘅（唔好重寫）

| 能力 | 位置 | 狀態 |
|---|---|---|
| Conversation / turn / run / safe events / SSE replay / apply | `src/postriff_phase2/ideas.py`、`hosted_app.py:200-241`、migration 005 | 可用（fixture runtime） |
| `AgentRuntime` interface + §10.4 safe-event 白名單 + `translate()` | `src/postriff_phase2/agent_runtime.py` | 可用 |
| `/api/ideas/models`（models + reasoning catalog） | `hosted_app.py:272` | 可用，得 fixture qualified |
| Tool registry（effect class、bounds、release hash；**publish 永遠唔係 tool**） | `src/postriff_phase2/tools.py` | 可用，public invoke 封住 |
| 四類 source policy `project_context()` | `src/postriff_phase2/source_policy.py` | 可用 |
| Claude / Codex / Gemini CLI argv + stream normalise | `src/postriff_phase3/adapters.py:44-85` | 有 code，得 `claude --bare` 一條 qualified |
| Desktop companion：Electron shell、sidecar、pairing、`OutboundHost` heartbeat/discover/claim/complete | `desktop/main.cjs`、`postriff_phase3/transport.py` | 可用（fixture route） |
| Codex content bridge（policy overrides、BINDING_FILES 將 skills 全文注入、hash-bound skillBindings） | `src/james_au_social/studio_codex.py` | 本地 Studio 可用 |
| 一次一問 intake、intent / slot 詞彙、routing table | `director.py`、`conversation.py`、`orchestrator.py`、`skills/james-au-social-orchestrator/references/routing-and-safety.md` | 可用 |
| Voice profile：問題庫、evidence / privacy states、`ALLOWED_FILES`、portable builder prompt | `src/postriff_alpha/profiles.py`、`profile_builder_prompt.md` | 可用 |
| Content types + `skillRouteIds` + preflight | `src/postriff_phase2/content_types.py` | 可用 |
| 33 條 channel skills + content-craft + research + 其他 | `~/.claude/skills/james-au-*`（repo `skills/` 有 5 個） | 可用 |
| Review → approve / `approve_many`（scheduleId、per-destination jobs、daily limits、tz fold） | `src/postriff_phase2/store.py:207-303` | 可用 |
| PostRiff MCP 候選（`read_selected_context`、`submit_candidate`、`review_link`） | `integrations/postriff/SKILL.md` | 候選 |
| Web chat primitives：`message`、`bubble`、`message-scroller`、`attachment`、`resizable`、`command` | `web/src/components/ui/` | template 自帶 |

**結論：要起嘅係「一個 Home 頁 + intent router + plan card + memory files + companion CLI bridge」，唔係一個新 agent 系統。**

---

## 3. 三個結構性決定（要你拍板）

### 決定 1 — Agent 喺邊度跑？

| Route | 邊個 spawn | 用邊個錢 | Skills / memory | 幾時用 |
|---|---|---|---|---|
| **A. Local CLI（Bridge）** | PostRiff Desktop companion 喺 user 部 Mac | user 自己嘅 Claude Code / Codex subscription（$0 for PostRiff） | 直接 mount 本地 skills folder + memory 檔案 | James 自己、power users、中文平台 |
| **B. API key（BYOK）** | Hosted API（`ServerModelRuntime`） | user 嘅 key，Fernet 加密（跟 D13 token custody） | server 端 compose SKILL.md 入 prompt | 冇裝 CLI 但有 key |
| **C. PostRiff managed** | Hosted API | 扣 writing batches | 同 B | Consumer 預設 |

**建議：三條都要有，但 Phase 1 淨係做 A + C。** Model picker 同 OpenDesign 一樣分兩組（Local CLI / Cloud），
每個 CLI 顯示 version、auth state、model synced from CLI。Route A 嘅 model list 由 companion 上報，hosted API **永遠唔碰 CLI credentials**（跟 `restricted_environment()` 嘅做法）。

### 決定 2 — Chat 係咪取代 Overview 做 `/app` Home？

建議 **係**。`/app` = Agent Home（artboard 1），`/app/ideas` redirect 去 `/app`（nav 入面 "Ideas" 變 "Home"）。
Overview 嘅四張 stat card 同 "Needs your attention" 唔係冇用，但唔應該係 landing：
attention items 變成 Home composer 下面一行 inline notice（「1 draft waiting for approval · LinkedIn token expires in 3 days」），
stat 搬去 Queue / Analytics。Cmd+K 同 sidebar 唔變。

### 決定 3 — Agent 嘅權力邊界

Agent 可以：讀 memory、讀 channel capability、讀 calendar、搵素材（經 research tool）、寫 draft、**propose** schedule plan、**propose** memory 修改。
Agent 唔可以：publish、reply、connect channel、扣錢、delete。呢個係 `tools.py` 嘅 `FORBIDDEN_EFFECTS` 同 ledger 第 107 行嘅現有 invariant。
所有 external representation 都要經 user 一 click——但係**一 click 可以批十個 destination**（`approve_many` 已經支援 1–10 個）。

---

## 4. Agent 架構

### 4.1 一個 turn 嘅 pipeline

```
user text (+attachments)
   │
   ▼
① Intent router（deterministic first，model second）
   intents: draft · research · schedule · publish_now · setup · analytics · memory · onboarding · question
   slots  : topic · channels[] · times[] (NL → resolve_time) · language · content_type · sources[]
   │
   ▼
② Context assembly（server 端，pure）
   memory files (AGENT/IDENTITY/VOICE/BOUNDARIES/BRAND + matched notes)
   + project_context(sources, four-class policy)
   + channel capabilities (which channels can schedule today)
   + calendar occupancy (avoid same-hour collisions)
   + entitlement (batches left, budget)
   │
   ▼
③ Skill binding（routing table §7.2）→ ordered list of SKILL.md (+ references), hash 記入 run.skillBindings
   │
   ▼
④ Runtime run（route A / B / C）── streams safe events §10.4 ──▶ UI
   output schema (strict JSON):
     { canonicalBrief, variants[{channelId, formatId, language, copy, notes, warnings, unknowns[]}],
       plan?: { destinations[{channelId, variantRef, localTime, timeZone}] },
       memoryProposals[{file, section, op, text, why}],
       questions[{id, prompt, kind, options[]}],
       researchLog[{url, retrievedAt, claim, support}] }
   │
   ▼
⑤ Cards：Variant card · Schedule plan card · Question form · Memory proposal · Research sources
   （每張 card 對應一個 safe event：artifact.created / action.proposed / warning.created）
```

- ① 先用 regex + 時間 parser + channel 名 alias（"IG" → instagram）做 deterministic classify；classify 唔到先問 model 一句
  （cheap model，`memoryModel`）。呢個同 `director.py` 嘅 `intent` slot 詞彙對齊（`draft / schedule / publish_now / setup / analytics / verify`）。
- ② 完全喺 server 做，adapter 淨係收到 projection（跟 D10 嘅精神：adapter only ever receives the projection）。
- ④ 嘅 output schema 係 `studio_codex.py` `CANDIDATE_SCHEMA` 嘅超集，向後兼容。

### 4.2 Runtime adapters（adapter-as-data）

`src/postriff_phase3/adapters.py` 已經有 `argv()`，改成 data object，並分開兩種 run：

| Run kind | Claude Code | Codex | 用途 |
|---|---|---|---|
| **content-only**（無 tool） | `claude --bare --print --verbose --output-format stream-json --include-partial-messages --tools '' --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}' --no-session-persistence --permission-mode dontAsk --model <m> --json-schema <schema> --max-budget-usd <b>`（現有） | `codex exec --json --ephemeral --ignore-user-config --sandbox read-only --output-schema schema.json -C <workdir> -m <model> -`（現有） | 寫 draft、改 draft、memory 提議 |
| **agentic**（有 tool，限 PostRiff MCP） | 同上但 `--tools` 改為 MCP 白名單：`--mcp-config <postriff-mcp.json> --allowedTools "mcp__postriff__*" --add-dir <workdir>/.postriff-skills --add-dir <workdir>/memory` | `codex app-server`（thread/start → turn/start），MCP 經 `-c mcp_servers.postriff=…` | research、多步 plan、需要讀 skills side files |

- **Session resume**：跟 OpenDesign 嘅 identity guard——(conversation, agent) 一個 session；model / cwd / skillBindings hash / 最後 assistant message 任何一樣變就 reseed。Claude 用 `--session-id` / `--resume`，Codex 由 `thread.started` 捕捉。
- **Probe**：companion 啟動 + Rescan 時並行跑 `claude --version`、`claude auth status`、`codex --version`、`codex login status`、`codex debug models`，
  上報 `AgentInfo`；hosted 存喺 device row，`/api/ideas/models` 合併輸出（`source: 'cli-live' | 'cli-fallback' | 'managed'`）。
- **Budget**：每 run `--max-budget-usd`（Claude）/ timeout + output cap（Codex）；companion 同 hosted 都記 usage，`provenance: 'measured_locally'`。
- **Steering**：Claude stream-json 可以開住 stdin 塞第二句——Phase 3 先做。

### 4.3 Tools（擴展 `tools.py`，全部走 effect class）

| Tool | Effect | 做乜 | 邊度執行 |
|---|---|---|---|
| `memory.read` | read | 讀 memory files + 用 topic 撈 notes | hosted |
| `memory.propose` | workspace_mutation | 建立一個 pending proposal（唔直接改檔） | hosted |
| `channels.capabilities` | read | 每條 channel 今日可唔可以 schedule / publish | hosted |
| `calendar.occupancy` | read | 某段時間已排咗乜 | hosted |
| `sources.attach` | workspace_mutation | 將 research 結果變成 source（policy = `rewrite_approval`） | hosted |
| `research.search` | read（network） | agent-reach / anysearch → 經 research-and-source-log ledger 記錄 | **companion**（有網）或 hosted research runner |
| `plan.propose_schedule` | workspace_mutation | 寫一個 `pr_agent_plans` row，狀態 `proposed` | hosted |
| `delivery.prepare_manifest` | workspace_mutation | 現有；plan approve 時逐個 destination 用 | hosted |

`publish / reply / connect / billing / delete` **繼續唔喺 registry**。
Route A 嘅 tool 由 PostRiff MCP stdio server（`integrations/postriff` 嘅 `postriff_agent_tools.py`）expose，
用 paired device credential 打返 hosted `/api/device/action`；agent 見到嘅係 MCP tool，hosted 見到嘅係 device action。

### 4.4 「今日 4 點 IG、5 點 LinkedIn、聽日 3 點半 FB」— 完整 flow

```
1. router  : intent = draft+schedule; channels = [instagram, linkedin, facebook]
             times   = [today 16:00, today 17:00, tomorrow 15:30] @ Asia/Hong_Kong（resolve_time，DST fold 照舊）
2. run     : variants ×3（各自 playbook）+ plan{3 destinations}
3. UI      : Variant card（tabs per channel）+ Schedule plan card（3 rows，每 row 顯示 capability level）
             ─ 有 unknown / 缺 image → Approve 掣 disabled，agent 講清楚差乜
4. user    : 改時間 / 改文 / 上圖 → 按「Review & approve all 3」
5. client  : for each destination:
               POST /actions {action:'review', variantId, channelId, localTime, timeZone, assetId?, alt?, rightsConfirmed, acknowledgedWarnings}
             then one
               POST /actions {action:'approve_many', reviews:[{reviewId, digest}…], confirmed:true}
6. server  : 3 jobs，共用 scheduleId，各自 state；plan.status = 'approved'
7. Queue / Calendar：即刻見到 3 個 job；chat 入面 plan card 變成「Approved · open in Queue」
```

- Facebook 係 local channel（companion）：plan card 顯示 `Local · companion`，approve 後 job 等 companion claim，同其他兩個一樣有自己嘅 state。
- 時間衝突（同一 channel 同一小時已有 job）→ router 喺 plan 出之前就 warn，唔係等 approve 先炸。
- Daily limit（`DAILY_LIMITS`）照舊喺 approve 時 enforce。

### 4.5 Research（「agent 會自動用 agent-reach 搵素材」）

- 觸發：intent = research，或 draft 嘅 content type 係 `article_news_commentary / deep_point_of_view / product_feature_launch`（`content_types.py` 嘅 preflight 要 `source_freshness / citation`）。
- 執行：**Route A** 用 companion 跑 `agent-reach`（`gh`、`r.jina.ai`、Exa）——因為 companion 有網、有 user 嘅 cookie 環境；**Route B/C** 用 hosted research runner（Exa / Jina 純 HTTP）。
- 記錄：每條結果入 research-and-source-log 嘅 provenance ledger（URL、retrievedAt、excerpt、claim、support/contradict），
  再以 `sources.attach` 變成 workspace source，policy 預設 `rewrite_approval`——即係唔會未經 use-approval 就出街。
- UI：Inspector 右邊「Sources · 3」tab；每條 source 有 policy badge 同「Approve use」掣。

---

## 5. Memory 檔案

### 5.1 檔案集

| 檔 | 內容 | 邊個寫 |
|---|---|---|
| `AGENT.md` | agent 點同你合作：問幾多、幾時 draft around unknown、預設 channel / language、tone default | onboarding + user |
| `IDENTITY.md` | 公開身份：名、一句定位、brands（James Au / My Best Life OS / Fantasia / D Festival）、audience | onboarding |
| `VOICE.md` | traits、openings、avoid list、languages、examples（approved excerpts） | onboarding + proposals |
| `BOUNDARIES.md` | 唔入內容嘅題目 / 私隱類別 | onboarding |
| `BRAND.md` | 每個 brand 嘅 voice 差異 | user |
| `notes/<type>-<slug>.md` | 學到嘅事：`type: project|feedback|reference|rule`，frontmatter 有 `source`、`evidence`、`privacy` | agent（經 proposal）|
| `MEMORY.md` | index，一行一 note（unlink = deactivate，跟 OpenDesign） | 系統 |

同 `profiles.py` 嘅 `ALLOWED_FILES` 對齊（`PROFILE.md` → `IDENTITY.md` 係改名，其餘照舊），evidence state 同 privacy state 照用：
`user_confirmed / observed_in_approved_example / agent_proposed_needs_confirmation / conflicting / unknown`、
`public / workspace_only / private / local_only / excluded`。

### 5.2 規則

- 每個 turn 都讀 core files；notes 用 topic / channel match（唔係全部塞入去）。
- Agent **唔可以直接寫**。佢出 `memoryProposals[]` → `pr_memory_proposals` → Inspector「Memory · 1」/ Memory 頁顯示 diff → user Accept / Edit / Dismiss。
  Accept 先 bump revision。（等於 OpenDesign 嘅 Keep gate，但係人手。）
- `privacy: private / local_only` 嘅內容永遠唔入 public draft，唔入 export（除非 user 揀）。
- Revision 綁入 manifest：`voiceRevision` 已經係 `build_manifest` 嘅一部分，改咗 VOICE.md 舊 approval 自然 stale。
- **Sync to Claude Code**：companion 將 `memory/` copy 去 `~/PostRiff/<workspace>/memory/`，run 時 `--add-dir` 掛上；
  格式刻意同 Claude Code memory folder 一樣（frontmatter `name / description / type`），所以 James 喺 terminal 開 Claude Code 都用得。

### 5.3 Memory model

同 OpenDesign 一樣分開一個平價 model（預設 `claude-haiku-4-5` via CLI，或 managed 細 model）做 extraction 同 proposal 措辭，
唔用主 model 做呢啲。

---

## 6. Onboarding（voice interview）

- 入口：sign-up 後第一次入 `/app`，或 Memory 頁「Redo interview」。
- 形式：**同一個 chat UI**，一次一問，option chips + 自由輸入（artboard 3）。問題直接用 `profiles.py` 嘅 `RELATIONSHIP`（7 條，問你同 AI 嘅關係）+ `GUIDED`（16 條，audience / expertise / voice traits / anti-style / languages / boundaries / writing sample / optional self-description）。
- 右邊 live 顯示 VOICE.md / IDENTITY.md 正在生成，每個 field 帶 evidence badge。
- **Import from your AI**：如果 companion 偵測到 Claude Code 已登入，出一張 card「Run with Claude Code」——用 route A 跑 `profile_builder_prompt.md`
  （scope 由 user 揀：current conversation / selected files / writing examples），結果係 candidate package（`review.md` + files），
  user 逐行 confirm 先寫入。冇 companion 就「Copy the portable prompt」。
- 最少可行：答 5 條（name、audience、traits、anti-style、languages）就可以 Skip，其餘 field 標 `unknown`，agent 會 draft around it。
- 完成後：`AGENT.md / IDENTITY.md / VOICE.md / BOUNDARIES.md` rev 1；`speaker.activeRevision` 指向 VOICE rev 1。

---

## 7. Skills

> **2026-09-16 更新——已去人格化，並且接咗線。** §7 原本全部掛 `james-au-*`，即係將「方法」同「James 呢個人」焊死咗。
> 而家 `skills/postriff-*/` 有一套對外可用嘅 duplicate（45 package）：方法照舊，人格層改成讀 workspace 自己嘅
> memory 檔（§5）。原有 `skills/james-au-*` 同 `~/.claude/skills/james-au-*` 一個都冇 delete。
> Hosted 寫作 run 經 `src/postriff_phase2/skills.py` 真係會收到呢套 skills。
> 逐個 skill 嘅 Purpose、點解幫到 user 出 content、同改咗乜 → [`docs/postriff-skills-generalization.md`](postriff-skills-generalization.md)。

### 7.1 用邊啲

**會掛入寫作 run 嘅**（`SkillLibrary.bind(destinations, format_id, intent, content_type)`，按呢個次序 compose）：

| Skill / 檔 | 幾時掛 | 超出預算時 |
|---|---|---|
| `postriff-content-engine` SKILL.md（voice contract） | 每個 run | 必要 |
| ↳ `references/content-pillars-and-workflows.md` | 揀咗 format 或 content type | 第 1 個省略 |
| ↳ `references/localization.md` | 有非英文、或者多過一種語言嘅 destination | 必要 |
| ↳ `references/research-and-sensitivity.md` | intent = research，或 content type 要 citation | 必要 |
| ↳ `references/platform-and-templates.md` | 視覺 format | 第 2 個省略 |
| `postriff-content-craft` SKILL.md + `editorial-workflow` + `human-voice-pass` | 每個 run | 必要 |
| ↳ `references/algorithm-practice.md`（寫作時嘅 discoverability：title、hook、hashtags、link placement） | 每個 run | 第 3 個省略 |
| ↳ `references/visual-handoff.md` | 視覺 format | 第 4 個省略 |
| ↳ `references/platform-playbooks.md` | 每個 run | 第 5 個省略 |
| `postriff-research-and-source-log` + `provenance-ledger` | intent = research，或 content type 要 citation（`article_news_commentary` / `deep_point_of_view` / `product_feature_launch`） | 必要 |
| `postriff-adapter-contract` | 有任何 channel adapter 嗰陣掛**一次** | 必要 |
| `postriff-channel-<x>`（33 條） | 每個 destination 一條；冇 mapping 嘅 platform 會出 warning | 必要 |

**唔會掛入寫作 run 嘅**——寫作 run 嘅 output schema 係 `variants[{platform, language, text, sourceIds, unknowns, notes}]` + `warnings`（`cli_runtime.OUTPUT_SCHEMA`，strict），以下 skills 嘅產出裝唔落：

| Skill | 點解 | 佢嘅寫作嗰半由邊個負責 |
|---|---|---|
| `postriff-social-graphics` | 產出 asset manifest、contact sheet、validation report | content-craft `visual-handoff.md`（明確 hand off 過去） |
| `postriff-discoverability` | 產出 `DiscoverabilityBrief`（連 measurement plan） | content-craft `algorithm-practice.md` |
| `postriff-source-extraction-providers`、`agent-reach`、`postriff-video-transcript-intake` | 取材，喺 run 之前做；run 收到嘅係已批准嘅 sources | — |
| `postriff-hyperframes-motion` | motion plan，唔係 copy | — |
| `postriff-conversation-director` | intake 由 `intent.py` 做 | — |
| `postriff-security-and-approval`、`postriff-publish-and-verify` | Host 嘅責任（`tools.py`、`store.py`），唔係 prompt 嘅責任 | — |

`james-au-social-orchestrator` **冇**做 duplicate：佢做嘅 routing 由 §4.1 ① intent router + `skills.py` 頂上，佢嘅 research 路由由 §4.3 `research.search` 頂上，而佢入面三處寫死咗本機絕對路徑。

### 7.1a 人格層點供應（呢個係去 James 化嘅核心）

Skill **只帶方法**。所有「呢個人係邊個」由 §5 嘅 memory 檔供應（`src/postriff_phase2/memory.py` 生成）：

| Memory 檔 | 內容 | 寫作 run 收唔收到 |
|---|---|---|
| `IDENTITY.md` | speaker、purpose、audience、subject、identity sentence | 收到 |
| `VOICE.md` | tone、observations、preferences、已批准嘅 writing example、明確列出嘅 unknowns | 收到 |
| `BOUNDARIES.md` | 唔入內容嘅題目 / 私隱類別 | 收到 |
| `BRAND.md` | workspace 嘅 brand layers，俾人睇 | **收唔到** |
| `AGENT.md` | agent 點同你合作，俾人睇 | **收唔到** |

「收到」嗰欄跟 `memory.prompt_fragments()` 實際送出嘅檔；engine 入面嗰張表有 test 對住佢，兩邊唔同步就會 fail。Engine 叫 model 淨係用收到嘅檔：缺咗嘅檔會講嘅嘢當 unknown，**唔好**將「冇收到某個檔」當成發現寫入 notes。

Voice profile 薄嗰陣（新 user 答咗 5 條就 Skip，§6）：缺嘅 field 標 `unknown` 入 warnings，**唔准**作職業、背景、資歷、意見或個人經歷去填氹，亦唔准借另一個 workspace 嘅聲音。

原本嘅品牌表（James Au / My Best Life OS / Fantasia Studio / D Festival）改成四種**形態**（Personal / Product / Service / Institution）。跟 `memory.py` 嘅實作：**一個 workspace 一個 brand**，有幾個 brand 就開幾個 workspace；形態由 `IDENTITY.md` 睇出嚟。Model 唔准作出第二個 brand。（§5.1 仲寫住 `BRAND.md`「每個 brand 嘅 voice 差異」，嗰個係實作之前嘅提案。）Content pillars 改成掛 `content_types.py` 嘅 11 個 type（同 §8.1a Quick Starts 同一個來源）。

順手修正咗一個同 ledger 抵觸嘅地方：content engine 原本寫「Green: may auto-schedule」，同 §3 決定 3 同 `tools.py` `FORBIDDEN_EFFECTS` 衝突。新版三級只決定張 plan card **點呈現**——Green 可以即刻俾 Approve、Yellow 要先出 warning、Red 唔會出現喺 destination 上（仍然可以 draft，理由入 warnings）。冇任何 tier 授權 publish。

### 7.2 Routing（intent × context → skills）

已經實作：`src/postriff_phase2/skills.py`，唔係原本諗嘅 `skill_routes.py`。`ideas.turn()` 將 destinations、`contentSystem.selection.formatId`、`parsed["intent"]` 同 `contentTypeId`（`unclassified` 當冇）傳入 `bind()`，條件全部寫喺 §7.1 第一張表。`content_types.py` 嘅 `skillRouteIds` 仲未被 `bind()` 讀——而家嘅 routing 淨係靠 content type id 本身。

### 7.3 點注入

- **Route A**：companion 將選中 skills **copy** 去 `<workdir>/.postriff-skills/<name>-<sha10>/`（跟 OpenDesign），
  `--add-dir` 掛上；SKILL.md 全文 compose 入 system prompt，references 留喺 folder 俾 agentic run 自己讀。
- **Route B/C**：淨係 compose 入 prompt（冇 filesystem）。`cli_runtime.compose()` 將 skills 放喺 policy 同 memory 檔之後，標明「method only, never identity」。
- 每個 run 記 `skillBindings[{id, version, sha256, files}]`；UI 嘅 activity strip 顯示「Skills · content-engine, content-craft, adapter-contract, channel-instagram…」。
- **只帶指令，唔帶 runtime**：原 `james-au-*` 每個 package 夾住一份 248 KB 嘅 `runtime/src/james_au_social/`（33 條 channel 各夾一份 ≈ 8 MB 重複 Python）。`postriff-*` 唔抄——hosted adapter 邏輯已經喺 `src/postriff_phase2/`。每個 package 尾嘅「PostRiff runtime binding」明寫：得指令、冇 Python、冇 credential、冇 transport。
- **Voice contract 拆開咗**：`skills/postriff-content-engine/SKILL.md` 約 15.2k 字元（`MAX_FILE_CHARS` 20k 以下，唔會被截），其餘拆做 5 個 reference，按 §7.1 條件掛。`references/operations.md`（排程習慣、publish 鏈、analytics）係俾人睇嘅，永遠唔掛入 run。放喺 `skills/` 唔放 `docs/`，因為 `vercel.json` 嘅 API bundle 排除咗 `docs/**`。
- **Adapter contract 抽出咗**：33 條 adapter 嘅 §5–§10 同 runtime 段原本逐字相同，每多一個 destination 就重複送約 3.2k 字元。而家集中喺 `postriff-adapter-contract`，每個 run 掛一次；每條 adapter 淨係留 §1–§4（purpose、語言、native formats、caption 規則）。淨係 `x`（§6/§7/§8/§10 + controlled-browser route）同 `reddit`（§7/§8）有真正嘅 override，照原文留喺 adapter。每條 adapter 平均由約 4.8k 跌到約 1.8k 字元；contract 本身約 4.6k。
- **Memory 檔以實際送出嘅為準**：engine 原本話五個 memory 檔「loaded before this engine runs」，仲有一句「`BRAND.md` 冇宣告就喺 notes 講出嚟」。但 run 從來收唔到 `BRAND.md`，所以**每一個** variant 都會多一句假 note。已改成跟 `prompt_fragments()`，並加咗 test（用 mutation 驗證過：`memory.py` 一開始送 `BRAND.md`，test 就會 fail）。
- **Skills 描述嘅係真 schema**：之前 bound skills 叫 model 出 `channelId`、`formatId`、`copy`、`fields`、`canonicalBrief`，全部係 strict schema 會拒絕嘅欄位（寫嘅時候跟咗 §4.1 嘅*提案* schema，唔係實作）。而家 title、description、slide text 呢類 native field 一律放 `notes` 並標明，缺嘅嘢放 `unknowns`。`tests/test_postriff_skills.py` 有兩個全庫 guard：bound skills 唔准出現 schema 會拒絕嘅欄位名；SKILL.md 唔准 link 一個 binder 永遠唔會送出去嘅檔（因為 `compose()` 同 model 講「every file a skill refers to is included inline」）。content-craft 嘅 `source-review.md` 係俾 maintainer 睇嘅，所以改成唔 link。
- **預算**：`MAX_TEXT_CHARS` = 60,000。超出嗰陣按 `DROP_ORDER` **成個檔**咁省略可省嘅 reference，省略記錄喺 binding 嘅 `omitted` 同 run usage 嘅 `skillOmissions`，**唔係** run warning（草稿唔依賴嗰啲檔，而且每個多 channel turn 都出 warning 只會令人習慣唔理 warning）；`skillBindings` 嘅 files 同 sha256 只記錄真係送咗出去嘅嘢。以前嘅做法係喺尾度 `text[:60000]` 硬截，可以將 adapter contract 嘅 approval 規則斬開一半，而 hash 仲記住 model 從來冇收過嘅文字。而家硬截只係最後防線：

  | 情況 | 字元 | 省略咗 |
  |---|---|---|
  | 1 channel，英文 post | 45,759（76%） | — |
  | 3 channels，雙語 carousel | 56,371（94%） | workflows |
  | 2 channels，news + research | 58,109（97%） | workflows |
  | 5 channels，視覺 + citation + 中文 | 59,319（99%） | workflows、templates、algorithm-practice |
  | 8 channels，視覺 + citation + 中文 | 55,222（92%） | 以上 + visual-handoff、platform-playbooks |
  | 一個 turn 20 個 platform | 60,000 | 全部可省嘅都省咗之後仲要硬截（不切實際嘅情況） |

  **已決定（2026-09-16，James 拍板）**：預算按 route 分——paid cloud route 保持 60,000；Claude Code / Codex 呢類由用戶自己 subscription 找數嘅 route 用 `SUBSCRIPTION_TEXT_CHARS` = 120,000（`skills.budget_for(cost_class)`，`ideas.turn()` 傳 `max_chars`），常見 turn 唔使省略。超出預算嘅次序：先按 `DROP_ORDER` 靜靜省可省嘅 reference（只記錄）；再按 `FALLBACK_ORDER` 省該 turn 揀咗嘅規則（editorial-workflow → localization → research → provenance → 整個 research skill → 整個 voice contract），每省一個出一條 warning；editorial core、human-voice pass、adapter contract 同 channel adapters 永遠唔省，真係連呢啲都超出先硬截，而嗰條 warning 會講明 adapter 可能唔完整。
- **本地 Studio 刻意保留 `james-au-*`**：`studio_codex.py` `BINDING_FILES` 冇切去 generic set，原因兩個，都有 test 守住（`tests/test_studio_bindings.py`）。(1) Studio 嘅 input 冇 voice、identity 或 brand 資料，James 嘅聲音淨係喺 `docs/james-au-social-content-engine.md` 入面；切過去就會出冇聲音嘅 draft。(2) Studio 用嘅係 `CANDIDATE_SCHEMA`（`canonicalBrief`、`channelId`、`copy`），`james-au-*` 描述嘅正正係呢啲欄位；generic set 描述嘅係 hosted schema（`text`、`unknowns`），切過去會喺另一個方向製造同一個 schema 錯配。呢個 test 做過 mutation 驗證：喺記憶體將 Studio 換做 generic set，test 會 fail 並講明原因。Studio 嘅 binding 文件冇改，所以冇 reviewed input 會變 stale。

---

## 8. UI 逐頁（對應 canvas 5 個 artboard）

### 8.1 `/app` Home（artboard 1）

```
┌ sidebar ┬──────────────────────────────────────────────────────────┐
│ Home ●  │  What are we putting out this week, James?               │
│ Calendar│  [Post●][Thread][Carousel][Video script][Research][Sched]│
│ …       │  ┌────────────────────────────────────────────────────┐  │
│         │  │ textarea                                           │  │
│         │  │ [+] [✦ Post ▾] [in LinkedIn][◎ Instagram][+ Channel]│  │
│         │  │                       [● claude-fable-5 · Claude ▾] [↑]│
│         │  └────────────────────────────────────────────────────┘  │
│         │  Voice · James Au rev 3 ▾ | Memory · 5 files ▾ | Sources ▾│
│         │  Quick starts  [All][Reflection][News][Launch][Music]…   │
│         │  ▢ Weekly reflection ▢ News + my view ▢ Launch ▢ YouTube │
│         │  Recent conversations                                    │
└─────────┴──────────────────────────────────────────────────────────┘
```

- Intent chips = `Post / Thread / Carousel / Video script / Research / Schedule week`，每粒綁 content type + format + skill set（唔係 prompt）。
- Target chips 來自 `useChannels()`：連接咗嘅 channel 先顯示；每粒帶 capability dot（Direct 綠 / Assisted 琥珀 / Local 藍）。
- Model pill = `/api/ideas/models` 合併結果；Local CLI 項目顯示 CLI 名 + 綠點（auth ok）。
- Context bar：Voice（speaker revision）、Memory（files 數 + 最後更新）、Sources（已選 sources）。
- Quick starts = 11 個 general-audience 模板（§8.1a），每個綁 `content_types.py` 一個 creator type；Recent = `useConversations()`。

#### 8.1a Quick Starts 模板（普羅大眾版，`web/src/config/quick-starts.ts`）

原則：文案要令設計師、老師、小店老闆、工程師都 relate 到；James 自己嘅 project / 品牌 / 練琴例子只可以留喺佢個 workspace 嘅 memory 同 voice 檔，唔可以做產品文案。每個模板 = 一個 content type（揀模板即 `p2_content_install_pack` + `p2_content_select`，preflight rules 跟住嚟）。

| # | 模板 | Content type | Footnote（解釋） | Example prompt（用戶改括號） | 常見呈現 |
|---|---|---|---|---|---|
| 1 | Quick thought | `quick_thought_quote` | 一個觀察、矛盾或問題，用自己嘅話講一次。唔使鋪排、唔使列點、唔使結論。 | “One thing I keep noticing: the tasks I put off are never the hard ones, they are the ones with no obvious first step…” | Threads / X / Bluesky 純文字；IG / 小紅書 quote card |
| 2 | Personal reflection | `personal_reflection` | 一個真實嘅片段同佢帶起嘅感覺。唔一定要有教訓，一個準確嘅觀察已經夠。 | “This morning I finally did the thing I had been avoiding for a month, and it took twenty minutes…” | 相片＋caption、純文字、日記式筆記、短片旁白 |
| 3 | News + my view | `article_news_commentary` | 發生咗乜、對你嘅讀者有乜影響、你點睇或者仲未諗通乜。來源同觀點分開。 | “I read this today: [link or key points]. First say what happened in two lines. Then my take…” | quick take / thread、LinkedIn 長文、carousel、Facebook link post |
| 4 | Deep point of view | `deep_point_of_view` | 一個守得住嘅立場：主張、理由同證據、最強嘅反對意見同你嘅回應。 | “My position: [one clear claim]. My reasons: … The best argument against it: … Write this as a longer piece.” | 長文 / article、newsletter、知乎 / note / Naver、video essay |
| 5 | Building in public | `building_in_public` | 進度、決定、死胡同同代價。有數字就講數字，草稿唔好扮 launch。 | “This week on [what you are building]: what I tried, what broke, the decision I made and why, what comes next.” | screenshot＋說明、build log、carousel、demo clip |
| 6 | How-to | `tutorial_how_to` | 一個你真係用過嘅方法，分步驟：開始前要乜、步驟、最易錯嘅一步。 | “Step by step, how I [do one specific task] using [a tool or method]…” | 小紅書步驟筆記、IG carousel、LinkedIn document、短教學片 |
| 7 | Launch | `product_feature_launch` | 點解做、俾邊個、今日有乜（未有乜）、點試。一次 launch 拆成幾個唔同任務嘅 post。 | “We just released [product, feature, service or offer]. Why we built it, who it is for, what is included right now…” | 公告、demo clip、幕後決定、入門教學、回應 feedback |
| 8 | Practice & performance | `music_performance_teaching` | 今日練習 / session / 課堂嘅一件事：練緊乜、乜嘢變咗、乜嘢仲難。任何 craft 都適用。 | “From today’s [practice, session, rehearsal or class]: what I was working on, the one thing that changed…” | performance / process clip、studio 相＋caption、短課、長片、隨筆 |
| 9 | Video extension | `youtube_derivative` | 一條長片變幾個原生入口：核心問題、最好嘅一刻、幕後、後續討論。 | “My latest video is about [topic]. The core question it answers is … The best moment is …” | Community post、Short / Reel、conversation post、Facebook preview |
| 10 | Answer a question | `community_q_and_a` | 答一個真實問題，或者就某件具體嘢徵求 feedback。講你會點做、邊度唔肯定、邀請更好嘅答案。 | “Someone asked me: [the question]. Answer it plainly, say what I would do and where I am unsure…” | Reddit / 知乎答案、forum reply、Discord / Telegram、poll |
| 11 | Event or service update | `event_service_institutional_update` | 確定咗嘅日期、地點、offer 或合作，加埋行動所需嘅資料：俾邊個、發生乜、點參加、去邊問。 | “On [date] at [place] we are hosting [the event, class, opening or service]…” | FB / IG / LinkedIn post、Google Business update、社群 broadcast |

Filter groups：Thoughts & moments（1–2）· News & opinion（3–4）· Work & launches（5–7）· Craft & video（8–9）· Community & events（10–11）。
- Template 元素：`card`、`badge`、`capability-badge`、`textarea`、`dropdown-menu`、`command`（`@` skill mention 用 cmdk）。

### 8.2 Conversation（artboard 2）

- 三欄：conversation list（256）｜chat｜inspector（340，`resizable`，可收）。Sidebar 自動 icon-collapse。
- Message 用 `ui/message.tsx` + `bubble.tsx`；stream 用 `message-scroller.tsx`。
- **Activity strip**：由 safe events 砌（`run.started / progress.updated / source.added / warning.created`），
  顯示 detected intent、skills、memory read、research、run 時間 + 成本；「Show run log」展開原始 event list（現有 `run-log` details 嘅升級版）。
- **Variant card**：tabs per channel，字數 vs limit（`LIMITS`），unknowns badge，Edit / Another angle / Add image。
- **Schedule plan card**：見 §4.4。Approve 掣 disabled 直至 unknown 清晒 + IG 有 image。
- **Inspector tabs**：Preview（native mock per channel）｜Sources（policy badges）｜Memory（proposals）。
- Composer docked，帶 model pill 同「3 channels」pill。

### 8.3 Onboarding（artboard 3）— 見 §6。

### 8.4 Models & providers（artboard 4）

- Tabs：Local CLI ｜ API providers ｜ PostRiff managed。
- 頂：PostRiff Desktop 狀態 card（paired device、last seen、sandbox 描述、Manage devices、Rescan）。
- Installed CLIs list：logo、name、version、auth badge、model synced / qualified、Default badge、model select。未登入 → 「Sign in, then rescan」+ 指引（跟 OpenDesign auth classifier 嘅 guidance 文案）。
- Execution settings：reasoning（Quick/Standard/Deep）、budget per run、sandbox（read-only · no shell · no network）、working directory、skills mounted。
- 右欄：billing 解釋、Memory model、offline fallback toggle。
- 路徑：`/app/account/models`（nav 「API & integrations」改名做「Models & providers」，API keys / MCP 放入去）。

### 8.5 Memory（artboard 5）

- 路徑：`/app/workspace/memory`（nav 加一項）。
- 左：core files + notes/ tree；右：rendered markdown + 右側 proposal / provenance / privacy。
- Header：Export package（現有 `export_profile`）、Sync to Claude Code（companion）。
- Proposal 用 diff 樣式（綠底 + 左邊線），Accept / Edit wording / Dismiss。

### 8.6 Nav 變更（`nav-config.ts`）

```
Create   : Home（/app）· Calendar · Pipeline · Library      ← Ideas 併入 Home
Distribute: Channels · Queue
Grow     : Analytics · Inbox
Workspace: Memory（新）· Brand · Members · Audit log · Roles
Account  : Profile · Notifications · Usage & plan · Privacy & data · Models & providers（改名）
```

---

## 9. Data model 同 API（全部 additive，migration 009）

```sql
pr_memory_files      (workspace_id, name, revision, body, frontmatter jsonb, updated_by, updated_at)   -- unique(workspace_id, name, revision)
pr_memory_proposals  (id, workspace_id, run_id, file, section, op, text, why, status, decided_by, decided_at)
pr_agent_plans       (id, workspace_id, conversation_id, run_id, plan jsonb, status, schedule_id, created_at)
pr_device_agents     (device_id, agent_id, available, version, auth_status, models jsonb, models_source, probed_at)
ALTER pr_agent_runs ADD route, adapter, skill_bindings jsonb, budget_usd_micro
```

新 routes（全部 workspace-scoped，行現有 membership transaction）：

| Route | 用途 |
|---|---|
| `GET/PUT /api/workspaces/{w}/memory/{file}` | 讀 / 寫 core file（PUT 要 `expectedRevision`） |
| `GET /api/workspaces/{w}/memory/proposals` · `POST …/proposals/{id}/decide` | Accept / Edit / Dismiss |
| `POST /api/workspaces/{w}/ideas/plans/{id}/approve` | client helper：逐 destination `review` 再 `approve_many`（server 端做，避免 client 半途死） |
| `GET /api/ideas/models` | 擴展：合併 device-reported CLI models |
| `POST /api/device/action` | 擴展 action：`agents.report`、`run.event`（streaming）、`run.complete`、`research.result` |
| `GET /api/workspaces/{w}/ideas/runs/{id}/events` | 現有 SSE；companion 嘅 events 經 `translate()` 入同一條 stream |

---

## 10. Desktop companion 變更（`desktop/` + `postriff_phase3`）

1. **Probe CLIs**（跟 OpenDesign detection）：啟動 + Rescan 並行跑 version / auth / models probe，上報 `agents.report`。
2. **Claim → spawn → stream**：`OutboundHost.tick()` 由 fixture 擴展到 `route in ('claude-cli','codex-cli')`；
   spawn 用 `RuntimeAdapter.argv()`；每條 normalised event 用 `run.event` 打返 hosted（batch 每 300ms）。
3. **Sandbox**：workdir = `~/PostRiff/<workspace>/`（memory/、.postriff-skills/、sources/），env 用 `restricted_environment()`，
   content-only run `--tools ''`；agentic run 只開 PostRiff MCP。**永遠唔讀 CLI credential、唔改 HOME。**
4. **Cancel**：hosted 設 `cancelRequested` → companion SIGTERM（Codex：`turn/interrupt`）。
5. **Research**：`research.search` tool 由 companion 執行（agent-reach），結果經 `research.result` 上報。
6. **Memory sync**：`memory/` 雙向 copy（hosted 係 source of truth，本地 copy 供 CLI 讀）。
7. Auth guidance：CLI 未登入 → UI 顯示「Run `claude auth login` in Terminal, then Rescan」，唔喺 app 入面收密碼。

---

## 11. 分期

| Phase | 內容 | 驗收 |
|---|---|---|
| **1（~2 週）** | Home + Conversation UI（fixture / managed runtime）；deterministic intent router；Schedule plan card → `review` + `approve_many`；memory files CRUD + proposals；onboarding chat（問題來自 `profiles.py`）；nav 改動 | 由一句「今日 4 點 IG、5 點 LinkedIn、聽日 3 點半 FB」到 Queue 見到 3 個 job，全程唔離開 chat；PG tests 證明 chat text 唔可以 publish |
| **2（~2 週）** | Companion：CLI probe + `agents.report`；Claude Code content-only route（`--bare`，現有 qualification）；Models & providers 頁；`/api/ideas/models` 合併；memory sync | Home model pill 顯示「claude-fable-5 · Claude Code」，draft 由本地 CLI 寫出，hosted 冇碰任何 credential |
| **3（~2 週）** | Codex app-server route；agentic run + PostRiff MCP（`plan.propose_schedule`、`memory.propose`、`research.search`）；research 經 ledger 入 sources；activity strip 顯示 research | 「幫我寫一個關於 X 嘅 post」會自動搵 3 個 source、標 policy、寫 draft，全部 source 可追溯 |
| **4** | Steering（open stdin）、`<question-form>` 式結構化提問、skills marketplace、BYOK tab | — |

---

## 11a. Phase 1 實作記錄（2026-09-16，拍板後同日）

拍板後即日落實嘅 slice，全部 additive，未 commit：

| 層 | 檔案 | 內容 |
|---|---|---|
| Router | `src/postriff_phase2/intent.py` | Step ①：channel alias（中英）、時間（`4pm` / `16:00` / `4 點半` / `晏晝 下晝 朝早` / 今日 聽日 後日 / 星期X / 日期）、同一 clause 內配對、日子 carry-over、過咗鐘自動推去聽日並 warn、`publish_now / schedule / research / draft` intent、語言偵測 |
| Runtime | `agent_runtime.py` | `supported_platforms()`（fixture = LinkedIn / Instagram / Threads） |
| Turn | `ideas.py` `turn()` / `quick_start()` | message 入面講到嘅 channel 蓋過 composer 選擇；`plan` 掛喺 artifact 同 assistant message；`warning.created`（unsupported / assumed / passed）同 `action.proposed` 緊跟 `run.started` 之後，stream 形狀不變 |
| Tests | `tests/test_postriff_intent.py`（14）、`tests/phase2/postgres_agent_plan.py`（6 checks） | 全部通過；原有 243 unit + `postgres_ideas.py` 8 checks 無回歸 |
| Web | `web/src/features/agent/*`（composer、activity-strip、variant-card、plan-card、plan.ts、use-run、home-view、conversation-view） | `/app` = Home；`/app/agent/[id]` = conversation；plan card approve = `applyRun → accept_update? → p2_variant_review → p2_review ×N → p2_approve_many` |
| Web | `features/memory/memory-view.tsx`、`/app/workspace/memory` | Phase 1 read-only：五個檔由 speaker / brandHub / profile 生成，export package；proposals 留 Phase 3 |
| Nav | `nav-config.ts`、`use-breadcrumbs.tsx`、`/app/overview` | Home 行先，Overview 搬去 `/app/overview`，Workspace 加 Memory |

**E2E（dev harness，disposable Postgres）**：一句「今日晏晝 4 點 post 去 Instagram、今日下晝 5 點 post 去 LinkedIn、聽日晏晝 3 點半 post 去 Facebook」→ 偵測 schedule、2 destinations、Facebook 剔出並解釋 → plan card 顯示每行 blocker（未接 account / 未設 voice / IG 要圖）→ 裝 voice + 接 LinkedIn 後，一撳「Review & approve all 1」→ Queue 出現 `scheduled` LinkedIn job（Sep 16 5:00 PM）。全程冇任何 publish 路徑。

**同 §11 Phase 1 嘅差異**
- Onboarding chat 未做：voice setup 已由 Brand 頁（`voice-setup.tsx`，另一 session 同日完成）承擔，Home 同 plan card 都指向佢。Chat-first interview 留待 Phase 2 前。
- Memory 係 read-only render（無 migration 009、無 proposals），因為 fixture runtime 冇嘢可以 propose。
- Intent chips 只切換 placeholder / 預設 channel，fixture runtime 唔會因 chip 改變輸出。
- Ideas 頁保留（另一 session 仍在改），未併入 Home。
- 已知限制：fixture 嘅 fact extraction 對中文 source 抽唔到 facts（`no_approved_facts`），所以中文 quick start 只出 outline；真 model route 先解決。

## 11b. Phase 2 實作記錄（2026-09-16，同日）

Phase 2 嘅第一個 slice：**Claude Code 變成一條真正嘅寫稿 route**——先喺「serve API 嗰部機」上直接 spawn（本地 harness / James 自己部 Mac），adapter 同 completion 合約已經係將來 desktop companion 用嘅同一套；companion transport（pairing、claim、device events）留 Phase 2b。

| 層 | 檔案 | 內容 |
|---|---|---|
| Runtime | `src/postriff_phase2/cli_runtime.py` | `ClaudeCliRuntime`：`detect()`（`--version`、`claude auth status --json`，唔存 email）、model aliases（`claude-code:default/fable/opus/sonnet/haiku`）、content-only argv（`-p --output-format stream-json --include-partial-messages --tools "" --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --disable-slash-commands --no-session-persistence --permission-mode dontAsk --max-budget-usd --json-schema --system-prompt`）、restricted env（`HOME PATH LANG USER TMPDIR` 而已，冇 API key、冇 nested-session marker）、stream 解析（`system/api_retry` → warning、`stream_event` text delta → `message.delta` 合併、`result.structured_output` → artifact）、`normalize_output` fail-closed（缺 destination 即失敗、超字數只 warn 唔 truncate、sourceIds 過濾）、timeout 用 reader thread、cancel 即 terminate、401 → 「run `claude auth login`」guidance |
| Runtime 合約 | `agent_runtime.py` | `provider / cost_class / asynchronous / owns() / describe() / dispatch()` |
| Ideas | `ideas.py` | runtime registry + `model_catalog()`（models + agents）；`turn()` 揀 route；async route：即刻回 `running`、寫 pending assistant message、`RunSink` 用獨立 transaction 完成 / 失敗 / 取消；`_finish` 統一 settle（subscription route PostRiff $0，CLI 報嘅 cost 記喺 usage）；event 寫入用 workspace `FOR KEY SHARE` + per-run advisory lock 嘅固定次序（sink 同 cancel 唔會 deadlock）；`project_context` 用 runtime 嘅 `provider_class`（另一 session 嘅 cloud runtime 要） |
| Memory | `memory.py` + `GET /api/workspaces/{w}/memory` | server-side render AGENT / IDENTITY / VOICE / BOUNDARIES / BRAND；Memory 頁同 CLI prompt 用同一份 |
| API | `hosted_app.py` | `/api/ideas/models` 出 `models + reasoning + agents`；memory route |
| Web | `features/agent/{use-model,model-picker}.tsx`、composer、home / conversation | model picker（PostRiff / Local CLI 分組，localStorage 記住）；quick start 同 turn 傳 `model`；conversation 見 pending run 即 poll，顯示「Claude Code is writing…」+ streaming text + Cancel；完成後 invalidate messages / snapshot |
| Web | `features/account/models-view.tsx`、`/app/account/models` | Models & providers：agent card（version、Signed in / Sign-in required、aliases、execution settings、env）、PostRiff routes、billing 說明、current default |
| Tests | `tests/test_postriff_cli_runtime.py`（13，用 fake `claude`）、`tests/phase2/postgres_cli_route.py`（10 checks） | 全過；unit 256、PG 三套無回歸 |

**E2E（dev harness）**
- Fake `claude`（`POSTRIFF_CLAUDE_BIN`）：Home 揀 `Claude Code · sonnet` → 送出 → conversation 顯示 streaming → 5 秒完成 → variant 帶「Written by Claude Code」warning → plan card → Models 頁見 agent card。
- 真 `claude`（James 部 Mac）：`claude auth status` 話 loggedIn，但 `-p` run 回 401「OAuth access token has expired」→ UI 顯示「Claude Code is not signed in… Run `claude auth login`」。**要 James 喺 Terminal 跑一次 `claude auth login` 先有真 run。**
- `claude auth status` 有存過 credentials 就話 loggedIn，過期 token 都係咁講；所以（Phase 3 後補）run 一次被拒 401 之後，runtime 會將 probe 標成 `expired`，picker 同 Models 頁即刻轉「Sign-in required」，直至 rescan 或者下一次成功 run。Codex route 同一機制（`codex login`）。

**同 §11 Phase 2 嘅差異**
- Companion transport（CLI probe 上報、claim、device events、memory sync 到 `~/PostRiff/<ws>/memory/`）未做——而家 CLI 喺 API process 內 spawn；hosted（Vercel）冇 CLI 所以自動唔列出呢條 route。
- Reasoning effort 未 map 到 CLI；skills 未 mount（Phase 3）。
- Codex route 未做（adapter 合約已經支援，加多一個 def 即可）。

## 11c. Phase 3 實作記錄（2026-09-16，同日）

Phase 3：**skills 綁定 + Codex route**。原則照 §7：skills 帶方法、memory files 帶個人；每次 run 記低用咗邊個 skill、邊個版本、邊個 sha256，事後可以追。

| 層 | 檔案 | 內容 |
|---|---|---|
| Skills | `src/postriff_phase2/skills.py` | `SkillLibrary`：root = `POSTRIFF_SKILLS_DIR` 或 repo `skills/`（要有 `postriff-content-craft/SKILL.md` 先算 available）；`load()` 讀 SKILL.md（去 frontmatter，取 `metadata.version`，冇就 `unversioned`）＋指定 reference files，每個 file 記 sha256 同字數，路徑鎖死喺該 skill 目錄內（`../` 出唔到去）；`bind(destinations, formatId)`：core `postriff-content-craft`（＋ editorial-workflow / human-voice-pass / platform-playbooks，visual formats 加 visual-handoff）＋每個 destination 一個 `postriff-channel-*`；每 file 上限 20k 字；總文預算按 route（`budget_for`：paid 60k、subscription CLI 120k），超出先靜靜省可省嘅 reference（記入 `omitted` / `skillOmissions`），再省規則（warning），adapters 永遠最後；缺 skill / 冇 library 係 warning 唔係 fail |
| Ideas | `ideas.py` | `turn()` 步驟③：`request["skills"] = library.bind(...)`；bind warnings 變 `warning.created` context events；`skillBindings`（id / version / sha256 / files）寫入 run usage（pending 同 completed 都有）；assistant message body 帶 `skills` ids；`IdeasService(skill_library=…)` 可注入 |
| Claude Code | `cli_runtime.py` | `compose()` 喺 system prompt 尾加 SKILLS 段（「method only, never identity；引用檔已 inline；永遠唔 override 上面規則」） |
| Codex | `src/postriff_phase2/codex_runtime.py` | `CodexCliRuntime(ClaudeCliRuntime)`：`codex exec --json --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check --sandbox read-only --output-schema <tmp>/schema.json -C <tmp> [-m model] -`，prompt 由 stdin 入（system ＋ INPUT）；temp workdir 0700，run 完即刪；detect 用 `codex --version` ＋ `codex login status`（restricted env，Codex 要 `TMPDIR` 先肯答）；events：`item.completed/agent_message` → 最後一段當 JSON candidate、`turn.completed.usage` → tokens、`error` / `turn.failed` → classify（usage limit → 指去 usage 頁；not logged in → `codex login`）；models：`codex:default` ＋ `POSTRIFF_CODEX_MODELS` 白名單先可以 `-m`；`POSTRIFF_CODEX_BIN` override；同 Claude Code 一樣 subscription route，PostRiff 記 $0 |
| Registry | `ideas.py` | `IdeasService` 自動加 Claude Code / Codex route（各自 `available()`：CLI 喺 PATH 而且 `POSTRIFF_LOCAL_CLI != 0`）；hosted 冇 CLI 就自然唔列 |
| Web | `features/agent/{use-model,model-picker,activity-strip,conversation-view}.tsx` | picker 按 route 分組（`ROUTE_LABELS`：Claude Code / Codex CLI）；pill「Codex · default」；activity strip 加「Skills · content-craft, channel-linkedin」一行（由 message body `skills` 嚟，冇就唔顯示） |
| Tests | `tests/test_postriff_skills.py`（7）、`tests/test_postriff_codex_runtime.py`（6，fake `codex`）、`postgres_cli_route.py` 加 skills 斷言 | 全過；agent 四個 unit module 40 個、PG 三套無回歸；web typecheck ＋ lint 過 |

**E2E（dev harness，fake `codex` 經 `POSTRIFF_CODEX_BIN`）**：picker 見「Local CLI · Codex CLI」組 → 揀 `Codex CLI · your default model` → 送出 → run 完成，activity strip 顯示 Skills 行 ＋「Codex · default」；Models 頁見 codex agent card。
真 `codex`（James 部 Mac）：`codex login status` = Logged in using ChatGPT，但 2026-09-16 已到 usage limit（「You've hit your usage limit」）→ UI 會顯示 usage-limit guidance；要等 limit reset 先有真 run。

**未做 / 留待**
- hosted（Vercel）`.vercelignore` 排除咗 `skills/`，所以 hosted run 會出「No skill library is installed on this host」warning、只用 editorial policy——要 hosted 有 skills 就要將 `skills/postriff-*` 入 bundle（另一 session 嘅檔案，由佢決定）。
- Agentic research（agent-reach / URL fetch 做 sources）、onboarding chat、memory proposals、companion transport 未做。
- Reasoning effort 未 map 去兩條 CLI。

## 12. 要你答嘅問題

1. Home 取代 Overview（決定 2）— OK？定係保留 `/app` Overview，Home 放 `/app/agent`？
2. Phase 1 嘅 managed route 用邊個 model？（`ServerModelRuntime` 仲係 `qualified: false`；如果暫時淨係 fixture + Claude Code 本地，consumer 就要等 Phase 2。）
3. Facebook 呢類 local channel，plan card 批咗之後 job 等 companion——如果 Mac 瞓咗，job 應該 `needs_review` 定係自動延後？
4. Memory 檔名用 `IDENTITY.md`（新）定沿用 `PROFILE.md`（`profiles.py` 現有）？
5. 中文 UI 文案：Home 嘅 greeting 同 activity strip 係咪跟 user 語言（zh-HK / en）？
