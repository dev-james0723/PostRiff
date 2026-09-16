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

### 7.1 用邊啲

| 類別 | Skill | 幾時掛 |
|---|---|---|
| 永遠 | `docs/james-au-social-content-engine.md`、`james-au-content-craft`（editorial-workflow、human-voice-pass）、`james-au-security-and-approval` | 每個 draft run |
| 每 channel | `james-au-channel-<x>`（33 條）+ content-craft `platform-playbooks.md` 對應 section | 淨係選中嘅 channel |
| Research | `james-au-research-and-source-log`、`james-au-source-extraction-providers`、`agent-reach` | intent = research 或 content type 需要 citation |
| 視覺 | `james-au-social-graphics`、content-craft `visual-handoff.md` | format = carousel / image_caption / story |
| 影片 | `james-au-video-transcript-intake`、`james-au-hyperframes-motion` | intent = video script / youtube_derivative |
| 排程 | `james-au-conversation-director`（timing / identity slots）、`james-au-publish-and-verify` | intent = schedule |
| Discoverability | `james-au-discoverability` | draft 最後一步（title / hook / hashtags policy） |

### 7.2 Routing table（intent × context → skills）

寫成 data（`src/postriff_phase2/skill_routes.py`），格式跟 `orchestrator.py` 嘅 `ROUTES`，但 key 係 `(intent, contentTypeId?, formatId?)`，
value 係 ordered skill ids。Content types 已經有 `skillRouteIds`（例如 `postriff.editorial-craft`）——呢度做 mapping 去實體 skill 檔。

### 7.3 點注入

- **Route A**：companion 將選中 skills **copy** 去 `<workdir>/.postriff-skills/<name>-<sha10>/`（跟 OpenDesign），
  `--add-dir` 掛上；SKILL.md 全文 compose 入 system prompt（跟 `studio_codex.py` `BINDING_FILES` 做法），references 留喺 folder 俾 agentic run 自己讀。
- **Route B/C**：淨係 compose 入 prompt（冇 filesystem）。
- 每個 run 記 `skillBindings[{id, version, sha256}]`（`studio_agent.py` 已有呢個 field）；UI 嘅 activity strip 顯示「Skills · content-craft, channel-instagram…」。
- Skills 來源：Phase 1 用 repo `skills/` + `~/.claude/skills/james-au-*` 嘅 portable packages（`runtime/` 隨包）；
  Phase 3 先做 workspace-level skill upload / marketplace。

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
- Quick starts = `content_types.py` CREATOR_TYPES 揀 4 個；Recent = `useConversations()`。
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

## 12. 要你答嘅問題

1. Home 取代 Overview（決定 2）— OK？定係保留 `/app` Overview，Home 放 `/app/agent`？
2. Phase 1 嘅 managed route 用邊個 model？（`ServerModelRuntime` 仲係 `qualified: false`；如果暫時淨係 fixture + Claude Code 本地，consumer 就要等 Phase 2。）
3. Facebook 呢類 local channel，plan card 批咗之後 job 等 companion——如果 Mac 瞓咗，job 應該 `needs_review` 定係自動延後？
4. Memory 檔名用 `IDENTITY.md`（新）定沿用 `PROFILE.md`（`profiles.py` 現有）？
5. 中文 UI 文案：Home 嘅 greeting 同 activity strip 係咪跟 user 語言（zh-HK / en）？
