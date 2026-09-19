# 16 · Brand & voice（voice setup）

> Route：`/app/workspace/brand` · Sidebar：Workspace · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**Route 同入口。** `web/src/app/app/workspace/brand/page.tsx:1-8` metadata title 'Brand & voice'，只 render `<BrandView />`；sidebar entry `web/src/config/nav-config.ts:123-129`（title 'Brand'、icon palette、`access: { permission: 'edit' }`）。送人嚟呢頁嘅地方：`home-view.tsx:112-114`（NeedsYou「Set up your voice」）同 `:253-256`（'Voice · rev N' link）、`overview-view.tsx:172-180`、`getting-started.tsx:29`、`ideas-view.tsx:204-213`（Alert）、`plan-card.tsx:397-401`（approve 要 voiceActive :118,:180）、`schedule-dialog.tsx:120-125`、`memory.py:26` `BRAND_HREF` → IDENTITY/VOICE/BOUNDARIES/BRAND.md 嘅 editHref（`memory.py:128-132`），同 onboarding tour `web/src/features/onboarding/tours.ts:116-125`（welcome）、`:295-309`（brand-tips）。即係產品已經宣佈咗呢頁係 memory 檔嘅編輯器，但頁面本身未做到。

**`brand-view.tsx`（125 行）。** 讀 `useSnapshot()`（:22）；`you` 硬 cast（:25）；active profile :26-28。冇 active revision → `<VoiceSetup />`（:51-54）；有 → 四張純顯示 card：Identity（:57-71）、Writing sample（:72-84）、Observations（:85-101）、Sources（:102-120）。兩個分支都有 `data-tour='voice-setup'`（:52、:56），`tours.ts:119,304` 靠佢。**現有 copy 有三句唔誠實**：:42「can be exported or deleted」（export 必失敗、冇 delete path）、:75「Used to match rhythm and vocabulary」、:88「Patterns noticed across your approved drafts」（observations 係 `domain.py:325-327` 固定字串，冇 model 分析）；:81 叫人去 Ideas 加 sample，但 Ideas 冇 flow 寫 `writingExample`。Loading 係 ad-hoc Skeleton（:49-50），冇用 `PageContainer isLoading`（`page-container.tsx:72`，PageSkeleton :22-39）；冇 `infoContent`（:48）；冇用 `access` prop（:44-45,:60-70）；冇 error state。**Active 之後乜都改唔到**：冇 edit、冇 revision history（`types.ts:160-166` Speaker.revisions 有 approvedAt/reason）、冇 restore（`src/postriff_alpha/visuals.py:98-113` 存在）、冇 identity sentence 編輯（`visuals.py:82-83`，240 字）、冇 boundaries。

**`voice-setup.tsx`（212 行）。** 三個 fieldset 一張 card：mode RadioGroup（:136-150，`components/motion/radio.tsx`）、purpose/audience + AnimatePresence subject/speaker（:152-176）、tone + sample（:178-196）。`propose()`（:60-76）順序發 `mode` → `context` → `profile_propose`，中途失敗冇 rollback（brandHub 已寫入）。Review card（:93-127）`profile_decide`，owner-only（:43、:117-123）。問題：(a) placeholder 寫死 piano（:156、:160）；(b) `tone`/`writing` 永遠由 'warm'/'' 開始（:50-51）；(c) `useVoiceStatus`（:208-212）同 `onDone`（:36）全 app 冇人用；(d) note label（:112）冇講會**取代全部 observations**（`domain.py:339-341`）。

**Backend。** `POST /api/workspaces/{id}/actions`（`hosted_app.py:477-486`）→ `service.mutate` → `HostedPhase2Commands.__call__`（`hosted.py:185-222`，sample workspace 一律 403 :188-189，最後必 `engine.invalidate` :221）→ `domain._apply`。`mode`（`domain.py:220-226`）、`context`（:227-248；非 hybrid 會覆寫 speaker 做 'The author'/'The business' :241-243）、`profile_propose`（:321-330，冇 model 分析）、`profile_decide`（:331-348；approve → `_voice` :171-178 開新 revision + `_mark_stale` :183-187 將**所有** variant 標 needsReview；reject → 清 provisional **兼 `activeRevision = None`** :334-337）。`you_restore_voice` 係開**一個新 revision**（reason 'Explicit restore of voice revision N'）、`_mark_stale`、唔清 provisional。權限（`src/postriff_phase2/permissions.py:27-39`）：`profile_decide` owner（:37）；`you_identity`、`you_restore_voice`、`mode`、`context`、`profile_propose` 冇 entry → edit（owner/admin/editor :17）。GET snapshot `hosted_app.py:461-462`；GET memory `:467-468` → `ideas.py:122-127`（files/egress/research/learning）。Tone 入 draft：`ideas.py:451-454`。`quick_start` 靜靜寫 brandHub audience/purpose（`ideas.py:553-556`）。

**改 voice 嘅真實後果（UI 冇講）。** Manifest 綁 `voiceRevision` + `brandDigest`（`store.py:380`）；`current()`（:393-414，比較喺 :408）亦要 `!needsReview`；`invalidate()`（:416-426）將唔 current 嘅 review 標 stale、scheduled/approved/claimed job 標 held。所以 approve / restore voice = 全部 draft 要 review + 全部排程 post held；改 mode/purpose/audience/subject/speaker/layers 改 digest → 一樣 held；淨係改 identity sentence（state.you）唔影響。Scheduling 要 `v.voiceRevision == activeRevision`（:359）。

**Export 係壞嘅。** `hosted.py:979-984` 要 `packageSchema`，只有 `profiles.py:364` `profile_finish`（web 從未發）先寫（:375）。所以 web 建立嘅 profile export 必失敗：`brand-view.tsx:31-37` 同 `memory-view.tsx:175-181` 吞咗 server message 出 generic toast；`privacy-view.tsx:89-92,128` 經 `run()`（:70-80）已經顯示 `ApiError.message`。Tests 用 fixture（`tests/test_postriff_phase2_hosted.py:80,161`）或 guided package（`tests/test_postriff_profiles_auth.py:223`），冇 test 捉到。

**Types / hooks。** `types.ts:153-158` VoiceProfile（冇 `fields`）、`:160-166` Speaker、`:168` BrandMode、`:179-189` SnapshotState（`you` 靠 index signature）。`useSnapshot` `hooks.ts:39-42`；`useMemory` `:133-136`；`useAct` `:150-162`（setQueryData snapshot + invalidate usage/channels，**唔 invalidate memory**）；`useInvalidate` `:164-173`。`web/src/hooks/use-stepper.tsx:85` `useFormStepper`（zod）VoiceSetup 冇用；redesign doc §6.8（`docs/postriff-consumer-saas-redesign.md:380`）指明 brand = multi-step form + use-stepper。

**Access。** `web/src/lib/auth/access.tsx:69 checkAccess` + `lib/workspace/provider.tsx:145-153` 已經由真 membership 計 permissions；nav 會收起 Brand，但頁面本身冇 gate，viewer/approver 打 URL 會見到表單。

**Tour。** `web/src/features/onboarding/`（tours.ts、tour-overlay.tsx、use-tour-context.ts 等）同 `web/src/styles/tour.css` 已存在（另一個 session 未 commit 嘅 WIP）；brand-tips 得一步。

**Motion。** motion-system §1 Brand row 只 RadioGroup；StatefulButton 有用；page enter `web/src/app/app/template.tsx:13`。

**Tests。** `tests/test_postriff_alpha.py:52-53,152-162`；`tests/phase2/postgres_isolation.py:156-158`（editor propose OK、editor decide 403、owner decide OK）；`tests/test_postriff_visuals.py:52`（you_identity）；`tests/test_postriff_consumer_web.py` 冇 brand test。

## 1. Design specification（最新版）

**目的**：一個地方決定「邊個講嘢、點樣講、乜嘢唔講」——IDENTITY.md / VOICE.md / BOUNDARIES.md / BRAND.md 嘅來源。頁面上每個字、每個數都係 snapshot 或 GET /memory 嘅真值；冇嘢係 model 推斷。Drafting 同 preview 永遠唔會被呢頁擋住，只有 scheduling 等一個 approved voice（store.py:359），頁面一開始就講清楚。

**Layout**：`PageContainer`：pageTitle 'Brand & voice'，pageDescription 'Who speaks in this workspace and how they sound. Every draft reads this; nothing here is inferred by a model.'，`isLoading={snapshot.isLoading}`，`access={checkAccess(access, { permission: 'edit' })}`（同 nav 一致；accessFallback：'You can read what drafts are written from on the Memory page.' + link），`infoContent`（見 sections），`pageHeaderAction` = Export voice profile（StatefulButton outline；backend 修好之前見 technical_requirements）。Sample workspace（`state.workspace.sample`）→ 頁頂 Alert 'This sample workspace is read-only.'，所有 mutation 掣 disabled（hosted.py:188-189）。

**1440px：** 頂部全闊 Status strip（`bg-card ring-foreground/10 rounded-xl`，同 memory-view 一樣嘅殼）。下面 `grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]`：左欄 Identity card → Voice card → Boundaries card（P1）→ Revision history；右欄「What drafts read」preview，`lg:sticky lg:top-4`。冇 active revision 時左欄換成 Setup stepper，右欄照顯示 VOICE.md 原文（memory.py:109）。

**768px：** 單欄，sticky 取消；順序 Status strip → Setup 或 Identity/Voice → preview → history。Status strip 數字 `grid-cols-2`。

**375px：** PageContainer 已經 `px-4`；card 全闊；mode / tone radio 一欄（現有 `sm:grid-cols-*`）；stepper Back / Next 各 50%；header Export 收入 strip 右邊 `DropdownMenu`「More」；preview body `max-h-[40vh]` 喺 `ui/scroll-area`；Edit dialog 用 `ui/dialog`（已 `max-w-[calc(100%-2rem)]`）。冇橫向 scroll。

**Primary action：** 未 set up → 'Propose my voice' / 'Use this voice'（owner）；已 active → 冇 header primary，card 各自 Edit / Revise。

**Copy 語言：** UI copy 英文（web 冇 i18n library）；所有 text field 接受任何語言；samples 嘅 language tag 等 languages Stage 2。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Status strip | 五秒內答到：voice 有冇 active、幾多 draft 同排程 post 綁住佢。全部真數。 | 左：`AnimatedBadge` 三態——'Active · rev {activeRevision}'（success）／'Waiting for an owner'（`speaker.provisional` 存在，warning）／'Not set up'（neutral）。下一行 'Approved {approvedAt 本地日期}'，reason 原文放 Tooltip。中：`DigitSwap` 三個數：'{D} drafts on this voice'（`variants.filter(v => v.voiceRevision === active)`）、'{B} written before it'（`!==`）、'{J} scheduled posts bound'（`phase2.jobs.filter(j => ['scheduled','approved','claimed'].includes(j.state))`）。P1 第四格：'{L} learned preferences'（`useMemory().data.learning.items.filter(i => i.status === 'active').length`）。右：'Open Memory'（`ui/learn-more-chevron`）+ 375px More dropdown。`data-tour="brand-status"`。 | snapshot 未返 → PageContainer skeleton；`phase2` 或 `learning` undefined → '—'（永遠唔係 0）；`useMemory` error → 該格 'Unavailable'。 |
| Setup stepper（冇 active revision 時） | 三條短問題 + review；每步都係真 workspace action，冇嘢推斷。 | `Empty` header：'Set up your voice'，description 'Three short questions, then an owner approves. You can draft and preview now; scheduling waits for an approved voice so every post is checked against whose words it carries.' 下面一張 card，頂部 `<ol>` 步驟（1 What you're building · 2 Purpose and people · 3 Tone and a sample · Review），current `aria-current="step"`。Step 1：mode RadioGroup（現有 MODES）。Step 2：purpose / audience / subject（非 personal）/ speaker（只 hybrid——非 hybrid server 會覆寫，domain.py:241-243），client 驗證同 domain.py:231-240；**離開 step 2 即發 `mode` + `context`**（brandHub 持久化，refresh 由 :45-49 prefill 續返）。Placeholder 全部 general：purpose 'e.g. Share what I learn while doing my work.'；audience 'e.g. People who are starting out in my field.'；subject（business）'e.g. A small neighbourhood shop'、（niche）'e.g. Working from home well'；speaker 'e.g. Me, as the founder'。Step 3：tone + sample Textarea（hint 'Kept for your reference. No model analyses it and it is never quoted publicly.'）；'Propose my voice' → `profile_propose`。Review：tone Badge、observations、sample、'Unknowns kept explicit'、note Input（label 'Optional: one line in your words — it replaces the observations above'）、'Use this voice'（owner）/ 'Start again'（owner，只喺冇 active voice 時出現）。Non-owner：'An owner needs to approve this. You can keep drafting meanwhile.'，掣 disabled。保留 `data-tour="voice-setup"`（tours.ts:119,304 用緊），另加 `brand-setup` 唔需要。 | `act.isPending` → StatefulButton loading；409 'Workspace changed; reload.'（hosted.py:138）→ toast + `invalidate('snapshot')`，stepper 由 brandHub 續返；sample workspace → 掣 disabled + reminder；approve 成功 → SuccessCheck 一次、toast、AnimatePresence 換去 active layout、`invalidate('memory')`。 |
| Identity card | 邊個講嘢、講俾邊個聽、做乜——IDENTITY.md 同 BRAND.md 嘅來源。 | Definition list：Building（mode label）、Purpose、Audience、Subject（有先顯示）、Speaker（`speaker.label`）、Identity sentence（`you.identitySentence`；inline Textarea，240 字計數，save → `you_identity`；空值 'Not set.'；呢個 save **唔**影響排程，唔出 impact line）。右上 'Edit' 開 `ui/dialog`：step 1+2 fields prefill 現值，save 順序發 `mode`（只喺 mode 改咗）→ `context`。Dialog 底部 impact line（只喺 brandHub fields 真係改咗先出）：'Saving holds {J} scheduled or approved posts until they are approved again.'；J = 0 → 'No scheduled posts are affected.'；`phase2` undefined → 唔顯示。`data-tour="brand-identity"`。 | edit class（owner/admin/editor）可以改；`act.isPending` disable save；error toast 用 `ApiError.message`。 |
| Voice card | 點樣講——tone、observations、sample、unknowns；VOICE.md 嘅來源。 | Tone Badge；Observations `<ul>`（標題 'Observations you approved'，唔再講 'patterns noticed'）；Writing sample blockquote（超過 6 行用 `ui/collapsible` 'Show all'；標題 'Your sample — for reference, not analysed'）；'Unknowns kept explicit' muted。右上 'Revise voice' → 同一個 stepper `mode="revise"` 開喺 step 3，**prefill 現有 tone 同 sample**，propose 後 card AnimatePresence 換成 review。Review 嘅 'Use this voice' 經 `ui/alert-dialog` confirm（motion rule 5），內有 impact line：'Approving marks {V} drafts for review and holds {J} scheduled posts until they are approved again.'（V = `variants.length`，因為 domain.py:183-187 係全部 variant）；兩個都 0 → 'Nothing scheduled is affected.'。'Discard this proposal' 掣要等 backend（technical_requirements），之前唔出。有 provisional 而自己唔係 owner → Badge 'Revision waiting for an owner'。`data-tour="brand-voice"`。 | provisional 存在時 'Revise voice' 隱藏；approve 後 SuccessCheck 一次；`invalidate('memory')`。 |
| What drafts read（preview panel） | 誠實錨點：agent 每次 draft 收到嘅原文（memory.py:4-5）。 | `ui/tabs` 三個 tab：IDENTITY.md / VOICE.md / BOUNDARIES.md，來源 `useMemory().data.files`（memory.py:128-132）；body `<pre class='font-mono text-xs whitespace-pre-wrap'>` 喺 `ui/scroll-area`；tab 頭 Badge `file.source`；footer 'Cloud model access: {On\|Off}'（`egress.cloud`；egress undefined → 'Unavailable'），link 'Change on Memory'（owner decision，唔喺呢頁改）。`data-tour="brand-preview"`。 | loading → 三行 Skeleton；error → 'Unavailable right now' + Retry（`memory.refetch()`）；冇 voice → VOICE.md 原文照顯示。 |
| Revision history | 每個 revision 留低；owner 可以 restore；代價喺 confirm 前講明。 | `ui/collapsible`（`CollapsibleContent` 加 `t-nav-panel`，同 app-sidebar.tsx:90）標題 'Revisions ({revisions.length})'，由新到舊：'rev {n} · {tone} · {approvedAt} · {reason}'，current Badge 'Active'。非 current 行 'Restore'（owner；非 owner disabled + tooltip 'Only an owner can restore a revision'）→ `ui/alert-dialog`：'Restoring creates revision {revisions.length + 1} from revision {n}.' + 同一條 impact line → `you_restore_voice {revision}`。有 provisional 時 restore disabled（避免 restore 後仲掛住舊 proposal）。`data-tour="brand-history"`。 | 一個 revision → 'One revision so far.'；restore 成功 → toast + `invalidate('memory')`，list 多一行。 |
| Boundaries card（P1，backend 未有寫入） | 乜嘢唔可以入 content——BOUNDARIES.md；私隱層。 | Backend 落地前：只顯示 BOUNDARIES.md 原文（同 preview 同一來源），冇假 editor。落地後：list 由 active revision `profile.fields` 用 `memory.boundary_fields`（memory.py:58-73）同一條規則篩，value + privacy Badge；'Add a boundary' dialog（category 文字 + privacy Select）→ 新 action。`data-tour="brand-boundaries"`。 | 冇 boundaries → Empty 'No boundaries recorded yet. Name categories, never secret values.' |
| Info sidebar | 首次嚟嘅人五秒明白呢頁做乜、唔做乜。 | `infoContent` 三段：'What a voice profile changes'——'The tone goes into every draft request; the observations and sample become VOICE.md, which writing routes read before drafting.'；'What it never does'——'No model analyses your sample. Nothing here infers your experience, credentials or results; unknowns stay listed as unknown.'；'What happens without one'——'Drafts and previews work. Scheduling waits for an approved voice.'；links：Memory、Ideas（sources）、Queue。 |  |

- **Empty state**：冇 active 又冇 provisional → Setup stepper 就係 empty state：`Empty` header 講三件事（三條問題、owner approve、draft 照做 scheduling 等）。右欄 VOICE.md 原文 'No active voice profile yet…'（memory.py:109）。有 provisional 冇 active → 直接開 Review。Sample workspace → 同樣畫面但唯讀 reminder。
- **Loading**：`<PageContainer isLoading={snapshot.isLoading}>` 用 PageSkeleton（page-container.tsx:22-39），刪 brand-view.tsx:49-50。Preview panel 同 learned 數等 `useMemory`，未返 → skeleton 行／'—'。Mutation 用 StatefulButton loading，冇「Analysing your voice…」之類假字眼。
- **Error**：`snapshot.isError` → `Empty`：'This workspace could not be loaded.' + `ApiError.message` + 'Try again'（`snapshot.refetch()`）。Mutation 403 / 409 / 400 toast server message，409 另 `invalidate('snapshot')`。無權限（checkAccess 失敗）→ PageContainer accessFallback。Export 失敗 → toast server 原句。`useMemory` error → preview 'Unavailable right now' + Retry。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁內容 | route enter | t-page-enter（現有） | web/src/app/app/template.tsx:13 + transitions.css .t-page-enter | 否（純裝飾） |
| Status badge | `speaker.activeRevision` / `speaker.provisional` 變 | AnimatedBadge 換 status | web/src/components/motion/animated-badge.tsx | 是 |
| Status strip 數字 | snapshot / GET /memory 數值變 | DigitSwap 逐位滾；undefined 顯示 '—' 唔郁 | web/src/components/motion/digit-swap.tsx | 是 |
| Stepper step panel | Back / Next | AnimatePresence opacity + y 4px，入 200ms EASE_OUT、出 150ms；reduced motion → duration 0 | voice-setup.tsx:54-55,162-175 pattern + web/src/lib/ease.ts | 否（純裝飾） |
| Mode / tone 選項 | click / 方向鍵 | 圓點滑動（現有） | web/src/components/motion/radio.tsx | 否（純裝飾） |
| Propose / Use this voice / Restore / Export 掣 | `act.isPending` / 下載中 | StatefulButton idle → loading → idle | web/src/components/motion/button | 是 |
| Approve / restore 成功 | 本 view 內 act 真係成功（唔係 mount 時已 active） | SuccessCheck 畫一次 | web/src/components/ui/success-check.tsx + transitions.css .t-success-check | 是 |
| Voice card ↔ review | `speaker.provisional` 出現／消失 | AnimatePresence crossfade 200 / 150ms，只 opacity + transform | motion/react | 是 |
| Impact line | brandHub fields dirty | fade + y 4px 入 200 / 出 150 | motion/react + EASE_OUT | 是 |
| Revision history | toggle | CollapsibleContent + t-nav-panel | web/src/components/ui/collapsible.tsx + app-sidebar.tsx:90 用法 | 否（純裝飾） |
| Preview tabs | 切 tab | t-tabs-pill indicator（現有） | web/src/components/ui/tabs.tsx:52 | 否（純裝飾） |
| Edit dialog / confirm alert-dialog | open / close | t-modal（收快過開） | web/src/components/ui/dialog.tsx, alert-dialog.tsx | 否（純裝飾） |
| 375px More dropdown | open | t-dropdown | web/src/components/ui/dropdown-menu.tsx | 否（純裝飾） |
| Toasts | mutation 結果 | Sonner 現有 | web/src/components/ui/sonner.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | Snapshot 讀 speaker / brandHub / variants / phase2.jobs / membership | api | 有 | web/src/lib/api/hooks.ts:39-42；src/postriff_phase2/hosted_app.py:461-462；types.ts:71-82, 153-189 | S |
| 2 | `mode`、`context`、`profile_propose`、`profile_decide` 經 `useAct` → POST /actions | api | 有 | hooks.ts:150-162；hosted_app.py:477-486；hosted.py:185-222；src/postriff_alpha/domain.py:220-248, 321-348；tests/test_postriff_alpha.py:52-53,152-162 | S |
| 3 | Owner-only approve（`profile_decide`）同 UI 對應 | backend | 有 | src/postriff_phase2/permissions.py:37；tests/phase2/postgres_isolation.py:156-158；voice-setup.tsx:43,117-123 | S |
| 4 | 頁面 RBAC gate：PageContainer `access` + checkAccess({permission:'edit'})，同 nav 一致 | frontend | 冇 | PageContainer `access` prop 存在（page-container.tsx:44-45,60-70），checkAccess 喺 web/src/lib/auth/access.tsx:69，provider.tsx:145-153 係真 membership；brand-view.tsx 冇用（members-view.tsx:263 有先例） | S |
| 5 | 修正 brand-view 三句唔誠實 copy（:42、:75、:88） | frontend | 冇 | domain.py:325-327 observations 固定字串冇 model；hosted.py:983-984 export 必失敗；冇 delete path | S |
| 6 | Discard 一個 revision proposal 而唔影響 active voice（新 `profile_withdraw`，或 reject 有 active 時只清 provisional） | backend | 冇 | domain.py:333-337 reject 會 `activeRevision = None` + `_mark_stale` | S |
| 7 | Identity sentence 編輯（`you_identity`，240 字） | backend | 有 | src/postriff_alpha/visuals.py:82-83；tests/test_postriff_visuals.py:52；web 冇 UI，`you` 冇 type（brand-view.tsx:25） | S |
| 8 | Restore revision（`you_restore_voice`）改 owner class + test | backend | 冇 | action 存在 visuals.py:98-113（開新 revision、_mark_stale、唔清 provisional）；permissions.py:27-39 冇 entry → edit；要加 `"you_restore_voice": "owner"` + postgres_isolation.py editor 403 test | S |
| 9 | Preview panel 讀 IDENTITY/VOICE/BOUNDARIES.md（`useMemory` → GET /memory） | api | 有 | hooks.ts:133-136；hosted_app.py:467-468；src/postriff_phase2/ideas.py:122-127；memory.py:76-133（editHref :128-132） | S |
| 10 | `useAct` 成功後 invalidate `memory` | frontend | 冇 | hooks.ts:156-160 只 setQueryData snapshot + invalidate usage、channels；`useInvalidate` :164-173 | S |
| 11 | Impact counts 純前端 helper（V = variants.length、J = jobs scheduled/approved/claimed、brandHub dirty 判斷）+ unit test | frontend | 冇 | 資料齊：variants（types.ts SnapshotVariant）、phase2.jobs[].state（:71-82）；規則 domain.py:183-187、store.py:380,408,416-426；you_identity 唔入 manifest | S |
| 12 | Export voice profile 對 web 建立嘅 profile 可用 | backend | 冇 | hosted.py:979-984 要 packageSchema；domain.py:321-345 從來唔寫；改法：冇 package 時用 `memory.render_files(state)` 檔案 + manifest（`packageSchema: null`）出 zip；alpha `domain.py:556-565` 同步；加 service-level test（唔好靠 test_postriff_phase2_hosted.py:80 fixture） | M |
| 13 | Brand / Memory export 顯示 server message（Privacy 已做到） | frontend | 冇 | brand-view.tsx:31-37、memory-view.tsx:175-181 吞 message；privacy-view.tsx:70-80 run() 已顯示 ApiError.message，可照抄 | S |
| 14 | General placeholders + revise prefill tone / sample + note label 講明取代 | frontend | 冇 | voice-setup.tsx:156,160（piano）、:50-51、:112 vs domain.py:339-341 | S |
| 15 | `PageContainer` isLoading / infoContent 接上 | frontend | 有 | web/src/components/layout/page-container.tsx:43,48,72,78；brand-view.tsx 未用 | S |
| 16 | Sample workspace 唯讀偵測 | frontend | 冇 | hosted.py:188-189 sample 一律 403；types.ts SnapshotState.workspace.sample 有 | S |
| 17 | Types：`SnapshotState.you`、`VoiceProfile.fields?` | frontend | 冇 | types.ts:153-158, 179-189；shape 喺 src/postriff_alpha/profiles.py:86 | S |
| 18 | Boundaries 寫入（新 action，複製 active profile、set boundaries field、開新 revision、owner class） | backend | 冇 | 讀：memory.py:58-73 boundary_fields；寫：只有 guided flow profiles.py:264-392 | M |
| 19 | Writing samples 列表 + language tag | backend | 冇 | domain.py:322,327 單一 string；docs/postriff-worldwide-languages-plan.md:273-280 §5.5；等 Stage 2 | M |
| 20 | Home NeedsYou：owner 見到 'A voice revision is waiting for your approval' | frontend | 冇 | home-view.tsx:112-114 只有 !voiceActive；speaker.provisional 同 membership.role 喺 snapshot | S |
| 21 | Tour：擴充現有 brand-tips + 加 data-tour id | frontend | 有 | web/src/features/onboarding/tours.ts:116-125, 295-309（target `[data-tour="voice-setup"]`），TourCtx :14-24；tour-overlay.tsx；另一 session 未 commit，改之前要協調 | S |
| 22 | Workspace default language / channelLocales | backend | 冇 | languages plan §4.3（:178-183）；§10 decision 2 仍 open（:477-480） | M |
| 23 | Stepper hook（可選） | frontend | 有 | web/src/hooks/use-stepper.tsx:85 useFormStepper（zod schemas） | S |

## 3. Features

### P0

- **修 brand-view 唔誠實 copy + RBAC gate + sample 唯讀**：:42/:75/:88 講緊產品做唔到嘅嘢（honesty、capability honesty）；viewer/approver 打 URL 會見到表單先 403。
- **Setup stepper：三步 + review，general 文案，『draft 照做、scheduling 等』reminder**：placeholder 係 piano（voice-setup.tsx:156,160）違反 general-not-personal；離開 step 2 即存 brandHub 令進度真實可續；reminder 對應 remind-don't-block。
- **Active 狀態可以改：Identity edit、identity sentence、Voice revise，confirm 前顯示真實 impact 數**：Memory 頁 Edit 已指嚟（memory.py:128-132）但頁面改唔到；改 voice 會 review 晒 draft（domain.py:183-187）同 hold 晒排程（store.py:408,416-426），唔講就係呃人。（depends on：discard proposal 掣要等 backend `profile_withdraw`；其餘唔使等）
- **Status strip + 『What drafts read』preview**：真數據：revision、approved 日期、幾多 draft／排程綁住，全部 snapshot／API；preview 係 memory.py:4-5 講嘅『你見到嘅就係 model 收到嘅』。
- **修 Export：backend 對冇 packageSchema 嘅 profile 出 memory 檔 zip；Brand/Memory 顯示 server 原因**：hosted.py:979-984 令所有 web profile 必失敗；Brand 同 Memory 吞 message，Privacy 已經顯示原因。
- **Revision history + Restore（owner）**：revisions 已存（types.ts:160-166）、`you_restore_voice` 已存在（visuals.py:98-113）；缺 UI 同 owner permission。（depends on：permissions.py 加 `you_restore_voice: owner`）

### P1

- **Boundaries card**：BOUNDARIES.md 係 PROMPT_FILES 第一個（memory.py:21），web 冇寫入路徑。（depends on：backend boundaries action）
- **Writing samples 列表 + language tag**：languages plan §5.5 已定 samples per-language；外部參考（Blotato、Typefully，未驗證）都用多篇 sample。Skills trial：rich profile 推高 invented claims，samples 係『參考』。（depends on：worldwide-languages Stage 2）
- **Non-owner flow：editor/admin propose → owner 喺 Home NeedsYou 見到**：postgres_isolation.py:156-158 已係 editor propose / owner decide；owner 而家唔知有 proposal。
- **Info sidebar + 擴充 brand-tips tour**：page-container.tsx:48 已支援；tours.ts brand-tips 得一步，要講清楚唔分析、唔擋 draft。

### P2

- **Workspace default language / per-channel languages**：languages plan §10 decision 2 未拍板。（depends on：languages plan §10 decision 2）
- **Gendered self-reference IDENTITY field**：languages plan §5.5 / §10 decision 10，只可以由人答；未拍板。（depends on：languages plan §10 decision 10）
- **『Try this voice』：approve 前用 quick-start preview 出一篇 draft**：unknowns 寫住『Voice fit has not been tested with a model』（domain.py:327）；會用 writing allowance，要顯示 quote。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：五秒內明白三樣：(1) 呢頁決定『邊個講嘢、點樣講』，每個 draft 都讀佢——pageDescription 同右欄 Markdown 原文教；(2) 而家有冇 voice、幾多嘢綁住佢——Status strip AnimatedBadge 同真數教；(3) 冇 voice 都可以 draft 同 preview，只係未可以 schedule；冇嘢係 model 推斷——Empty header 同 info sidebar 教。Tour 擴充現有 `brand-tips`（tours.ts:295-309），body 用 TourCtx（hasVoice / voiceRevision / canEdit）讀真狀態。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="brand-status"]（新加）` | Your voice, at a glance | Which revision is active, how many drafts were written with it and how many scheduled posts are bound to it. Every number is read from your workspace. |
| 2 | `[data-tour="voice-setup"]（現有，tours.ts:119,304 用緊；active 時 fallback [data-tour="brand-identity"]）` | Who speaks | What you are building, for whom, and the one line drafts are checked against. The Memory page shows it as IDENTITY.md. |
| 3 | `[data-tour="brand-voice"]（新加）` | How you sound | A starting tone, short observations and an optional sample. No model analyses the sample. An owner approves each revision. |
| 4 | `[data-tour="brand-preview"]（新加）` | What drafts read | The exact Markdown the agent receives before every draft. If it is not here, the agent does not know it. |
| 5 | `[data-tour="brand-history"]（新加）` | Every revision kept | Older revisions stay listed and an owner can restore one. Changing the voice marks drafts for review and holds scheduled posts; the page shows how many before you confirm. |

**Empty state 教咩**：四件事：(1) 三條短問題就夠，唔使填人生故事；(2) sample 係俾自己參考，冇 model 分析（domain.py:325-327）；(3) 未有 voice 都可以 draft 同 preview，只係 scheduling 等（store.py:359）；(4) approve 係 owner 決定，因為會改所有人嘅 draft（permissions.py:35-37 註解）。右欄 VOICE.md 原文同時示範 preview panel 係乜。

## 5. Next steps（按次序）

1. **Copy + gate + types + export message：改 brand-view :42/:75/:88 唔誠實句、PageContainer access gate + isLoading、sample 唯讀；placeholder general、revise prefill、note label；`you`/`fields` types；Brand/Memory export catch 顯示 `ApiError.message`（照 privacy-view run()）；刪未用 `useVoiceStatus`／`onDone`**（effort S）  
   檔案：`web/src/features/workspace/brand-view.tsx:25,31-50,75,88；web/src/features/workspace/voice-setup.tsx:36,50-51,112,156,160,208-212；web/src/lib/api/types.ts:153-189；web/src/features/memory/memory-view.tsx:175-181`
2. **Backend 三件：(a) `profile_withdraw`（或 reject 有 active 時只清 provisional）；(b) `you_restore_voice` → owner；(c) `export_profile` 冇 packageSchema 時出 memory 檔 zip（alpha 同步）。每件加 test。**（effort M）  
   檔案：`src/postriff_alpha/domain.py:331-348,556-565；src/postriff_phase2/permissions.py:27-39；src/postriff_phase2/hosted.py:979-1003；tests/test_postriff_alpha.py；tests/phase2/postgres_isolation.py:156-158；tests/test_postriff_phase2_hosted.py`
3. **`useAct` onSuccess 加 invalidate memory；新 pure helper `voiceImpact(state)` → {variantsMarked, draftsOnVoice, draftsBefore, jobsBound} + unit test**（effort S）  
   檔案：`web/src/lib/api/hooks.ts:150-162；新 web/src/features/workspace/voice-impact.ts（+ test 按 web 現有慣例）`
4. **VoiceSetup 重組做 stepper：`<ol>`、Back/Next、離開 step 2 即發 mode+context、`mode="setup"|"revise"`、review 經 alert-dialog + impact line、non-owner waiting、SuccessCheck 一次；保留 data-tour='voice-setup'**（effort M）  
   檔案：`web/src/features/workspace/voice-setup.tsx；可選 web/src/hooks/use-stepper.tsx`
5. **BrandView 重砌：infoContent、Status strip（AnimatedBadge + DigitSwap）、Identity card + Edit dialog + identity sentence、Voice card + Revise、preview panel（useMemory + tabs + scroll-area）、error Empty、375px More dropdown；Sources card 改成 info sidebar link 去 Ideas**（effort M）  
   檔案：`web/src/features/workspace/brand-view.tsx；新 web/src/features/workspace/{voice-status.tsx,identity-card.tsx,voice-card.tsx,voice-preview.tsx}`
6. **Revision history + Restore（alert-dialog + 'creates revision N' + impact line + owner gate + provisional 時 disabled）**（effort S）  
   檔案：`新 web/src/features/workspace/voice-history.tsx；brand-view.tsx`
7. **擴充 tours.ts brand-tips（先同 onboarding WIP 嘅 session 協調）+ Home NeedsYou『voice revision waiting for your approval』（owner && provisional）**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:295-309；web/src/features/agent/home-view.tsx:112-114`
8. **Boundaries：backend action（複製 active profile fields、開新 revision、owner class、`profiles.text()` 封 secret）+ Boundaries card + tests（boundary_fields 讀到、cloud egress 唔出 private）**（effort M）  
   檔案：`src/postriff_alpha/profiles.py 或 domain.py；src/postriff_phase2/permissions.py；tests/test_postriff_memory_egress.py；新 web/src/features/workspace/boundaries-card.tsx`
9. **Samples 列表 + language tag（languages Stage 2 之後）**（effort M）  
   檔案：`src/postriff_alpha/domain.py:321-330；src/postriff_phase2/memory.py:76-133；web/src/features/workspace/voice-card.tsx`
10. **驗證：`npx tsc --noEmit`、`npm run lint`、`next build`；browser 375/768/1440 × light/dark（pane localhost:3100，唔係 4331）；用 owner、editor、viewer 三個角色睇 gate；harness 有 live Threads，voice approve 會 hold 排程但唔會發佈，唔好 approve / schedule post；API 重開要 re-seed**（effort S）  
   檔案：`web/；.claude/launch.json`

## Risks

- 改 voice 或 brandHub 會 hold 晒排程 post（store.py:380,408,416-426）同 review 晒 draft（domain.py:183-187）。頁面用真數警告係底線；另開決定：`brandDigest` 應唔應該留喺 `current()`（類似 preference-learning A1 將 styleRevision 拆出）。
- `profile_decide reject` 會清 activeRevision（domain.py:334-337）：backend 未改前，已有 active voice 時 UI 唔可以出 discard / Start again。
- Restore 係開新 revision 兼 _mark_stale，唔清 provisional：UI 要講清楚，provisional 存在時 disable restore。
- Export 冇 test 捉到（fixture 蓋住）；修 backend 要加真 service-level test。
- Rich profile 推高 invented claims（skills real-draft trial）：唔加『describe yourself in detail』field，observations 保持短。
- `quick_start` 靜靜寫 brandHub（ideas.py:553-556）→ 改咗 digest 會 hold 排程，Brand 頁顯示嘅 purpose 可能係 Quick Start 改嘅；要 backend 記 source 先講得到。
- Scheduling gate（store.py:359）係 publishing invariant；所有新 copy 要講『drafts and previews work now』，唔可以寫成『you must set up your voice first』。
- web/src 同 onboarding tour 係另一個 session 未 commit 嘅 WIP（tours.ts、brand-view.tsx data-tour 改動）：落實時 stage by path、細 commit；改 data-tour id 要同步 tours.ts。
- Languages Stage 2 會將 writingExample 變 per-language samples；而家唔好起單一 sample editor。
- Owner 唔知有 proposal：多人 workspace 會卡住，要同 step 7 一齊做。

## 覆核記錄

- 改正：8 個入口送人嚟呢頁，包括 edit-draft-dialog.tsx:34 同 memory.py:20 BRAND_HREF、memory.py:122-128 → 改為：home-view.tsx:112-114 + :253-256、overview-view.tsx:172-180、getting-started.tsx:29、ideas-view.tsx:204-213、plan-card.tsx:397-401、schedule-dialog.tsx:120-125、memory.py:26/:128-132、tours.ts:116-125/:295-309
- 改正：brand-view.tsx 126 行；冇 data-tour；grep data-tour web/src 冇結果 → 寫明現有 id 'voice-setup' 被 tours.ts:119、:304 用緊，改名要同步改 tours.ts
- 改正：Tour infra 全 app 未有（exists:false, effort M） → exists:true；要做嘅只係喺 tours.ts 擴充 brand-tips steps + 加 data-tour id（S），唔好另起 tour component
- 改正：（spec 冇提）brand-view 現有 copy 係誠實嘅 → 加入 next_steps order 1 同 technical_requirements
- 改正：PageContainer isLoading :23-32、infoContent :60-70 → 改行數；另外 PageContainer 已有 `access` prop（:44-45,:60-70），brand-view 未用
- 改正：Actions 經 hosted_app.py:457-466 → hosted.py:185-223 → domain._apply → 改 hosted_app.py 行數
- 改正：you_identity visuals.py:80-81；you_restore_voice :98-113 → 更正行數，history UI 要預期 restore 之後 revisions 多一行
- 改正：memory.py:75-131 render_files、:100 VOICE.md 空狀態、:56-73 boundary_fields、:17-18 PROMPT_FILES、:22-24 local_only → 更正行數
- 改正：privacy-view.tsx:89-92 冇 try/catch，unhandled rejection → 只有 brand-view.tsx:31-37 同 memory-view.tsx:175-181 吞 message
- 改正：types.ts:151-164 VoiceProfile/Speaker、:166 BrandMode、:181-182 speaker/brandHub、:16 profileMetadata → 更正行數
- 改正：hooks.ts useAct :152-165 只 invalidate usage/channels；useInvalidate :167-173；useSnapshot :39-42；useMemory :132-135 → 更正行數，結論不變
- 改正：Collapsible 用 t-nav-panel（app-sidebar.tsx:96） → 改 :90，reuse 寫 'CollapsibleContent + t-nav-panel class'
- 改正：Impact line '{D+B} drafts marked for review'（D、B 都 filter !blockedByRetraction） → 用 `variants.length`（或 filter 前總數）；jobs 用 phase2.jobs state ∈ scheduled/approved/claimed
- 改正：Identity Edit dialog 所有改動都顯示 'posts will be held' impact line → impact line 只喺 mode/purpose/audience/subject/speaker/layers 真係改咗先出；identity sentence 單獨 save 唔出；speaker field 只喺 hybrid 顯示
- 違反原則（已改）：Honesty（rule 1）/ capability honesty（rule 5）：spec 冇 flag brand-view.tsx:75「Used to match rhythm and vocabulary」、:88「Patterns noticed across your approved drafts」、:42「can be exported or deleted」三句假 claim（冇 model 分析、export 必失敗、冇 delete path）；corrected spec 已加入 P0 修正。
- 違反原則（已改）：Honesty：Impact line 用 filter 過嘅 D+B 會少報被標 review 嘅 draft 數（_mark_stale 係全部 variant）；已改成全部 variant 數。
- 違反原則（已改）：General-not-personal（rule 3）：新 placeholder「one small lesson at a time」偏向教師；改成對設計師／店主／developer 都通用嘅字眼。
- 違反原則（已改）：Reuse before inventing（rule 4 / 現有 infra）：spec 提議另開 task 起 tour component，但 web/src/features/onboarding/tours.ts 已有 brand-tips tour；應擴充現有 registry，並沿用 TourCtx 真數據句式。
- 違反原則（已改）：Motion rule 5「破壞性動作保留確認」：『Use this voice』喺已有 active voice 時會 hold 全部排程 post，spec 只喺 Restore 用 alert-dialog；revise approve 都應該經同一個 confirm（impact line 放 dialog 入面）。
- 補上遺漏：RBAC gating：nav 用 access { permission: 'edit' } 但 brand-view 冇用 PageContainer `access` prop（page-container.tsx:44-45）；viewer / approver 直接打 URL 會見到表單，submit 先 403。要 `checkAccess(useWorkspaceAccess(), { permission: 'edit' })`（web/src/lib/auth/access.tsx:69、provider.tsx:145-153 係真 membership），或者俾 approver/viewer 一個唯讀版本。
- 補上遺漏：Role 細節：edit class = owner/admin/editor（permissions.py:17）；admin 可以 propose 但唔可以 approve（profile_decide 只 owner），UI 字眼要講『owner』唔係『admin』。
- 補上遺漏：現有 tour：tours.ts:116-125（welcome）同 :295-309（brand-tips）target `[data-tour="voice-setup"]`；改 DOM 結構時要保留或同步改 selector，否則 welcome tour 會 fallback 去 heading。
- 補上遺漏：Restore 嘅真實行為：開新 revision、唔清 provisional；history UI 同 impact line 要反映。
- 補上遺漏：Sample workspace：hosted.py:188-189 sample workspace 所有 action 403 'read-only'；頁面要偵測 `state.workspace.sample` 顯示唯讀 reminder，而唔係俾人填完先失敗。
- 補上遺漏：409 'Workspace changed; reload.'（hosted.py:138）喺 propose 三連發中間發生時嘅 partial state：mode/context 已存、profile_propose 未發；refresh 後 stepper 要由 brandHub 續返 step 3。
- 補上遺漏：i18n / languages：web 冇 UI i18n library，頁面 copy 係英文；sample / purpose 欄可以任何語言輸入，但冇 language tag（等 languages Stage 2）；spec 冇講清楚 UI 語言 vs 內容語言。
- 補上遺漏：brand-view Sources card 刪走之後，sources 數去邊度睇（Ideas）要喺 info sidebar link 返。
- 補上遺漏：Mobile：Status strip 四個數喺 375px 嘅排法、preview panel 喺 768px 以下 sticky 要取消。
