# 15 · Audit log

> Route：`/app/workspace/audit` · Sidebar：Workspace · 成熟度：未 set up · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

**前端（73 行嘅 stub）**
- `web/src/app/app/workspace/audit/page.tsx:1-8` 只係 render `<AuditView />`，metadata title = "Audit log"。
- `web/src/features/workspace/audit-view.tsx:30-73`：plain `Table`（When / Event / Actor / Subject / Details）。loading 係 `Skeleton h-64`（:36），empty 係 `<p>No events recorded yet.</p>`（:38）。**冇 error state**：`events = audit.data?.events ?? []`（:32），API 500 / 403 會顯示成「No events recorded yet.」— unavailable 變咗 empty，違反真數據原則。
- Actor 欄 `event.actor?.slice(0, 8)`（:58）冇 display name；Event 欄印 raw `kind`（:56）；Details `summarise(meta)`（:21-28）raw dump 頭 4 個 key。
- 冇 filter、pagination、export、row detail、deep link。Info sidebar（:10-19）講「last 200 events」係真（LIMIT 200），但「full trail is kept with the workspace」同 `on delete cascade` 唔夾（見 risks）。
- Nav：`web/src/config/nav-config.ts:116-122` title "Audit log"、icon `history`、`access: { role: 'admin' }`（:121）。`checkAccess`（`web/src/lib/auth/access.tsx:69-94`，role check :79）= admin 或 owner。頁面冇用 `PageContainer` 嘅 `access` prop，直接入 URL 照睇到；API 同 RLS 容許任何 active member 讀。三層唔一致。
- **三個 consumer 共用 `useAudit()`**：本頁；Overview "Recent activity" card（`web/src/features/overview/overview-view.tsx:148`、card :401-425，`kind.replace(/[._]/g, ' ')` :414）；Channel history sheet（`web/src/features/channels/channel-history-sheet.tsx:62-66` 用 `subject === channel.id` 過濾，:77 文案明講『last 200 workspace events』）。Response 要保留 `events` key。
- Data layer：`web/src/lib/api/hooks.ts:19` key、`:74-77` `useAudit()`；`web/src/lib/api/client.ts:245` `audit: (w) => get<{ events: AuditEvent[] }>(...)`（冇 params）；`web/src/lib/api/types.ts:720-727` `AuditEvent { id?, kind, actor: string, subject, meta, at }`（actor 型別未反映可以係 null）。
- Cache：只有 `web/src/features/channels/channel-card.tsx:158` invalidate `keys.audit`。Members（`members-view.tsx:148,161,250,276`）、`connect-return.tsx:46-47`、privacy export、approve / cancel 都冇 — 做完動作返 Overview，activity 可能係舊。
- Tour：`web/src/features/onboarding/tours.ts` 已有 `PAGE_TOURS`（:155 起，home / channels / analytics / queue / calendar / overview / brand / memory / inbox），`TourStep { id, route, stop, target[], title, body, when? }`；`app/app/template.tsx` 已 mount `TourMount`。Audit 未有 entry，亦未有 `data-tour` id。
- Web 冇 unit test runner（`web/package.json` 冇 test script）。

**後端（route 有、資料有、覆蓋唔全）**
- Route：`src/postriff_phase2/hosted_app.py:465-466` `GET /api/workspaces/{id}/audit` → `service.audit_events`。`_query_int` 喺 `hosted_app.py:222`。
- Service：`src/postriff_phase2/hosted.py:929-932` `SELECT id, actor, kind, subject, extract(epoch from at), meta ... ORDER BY at DESC LIMIT 200`，經 `repository.transaction`（:105-116，只 check active membership）；冇 actor name、total、cursor、filter。
- Writer：`hosted.py:91-93` `audit(cur, workspace_id, actor, kind, subject="", meta=None)`，subject 截 200 字。`repository.command`（:129-150）喺 :144-145 寫 `audit_event`；`self.effects`（:103，signature comment `(cur, workspace_id, before, after, principal)`）喺 :146-147 執行。
- Table：`migrations/postriff/004_consumer_web_tenancy.sql:45-63`（`on delete cascade` :48；RLS `audit_tenant_read` :62、`audit_service_write` :63；冇 update/delete grant）。`011_account_preferences.sql:12-14` 加 `(actor, at desc)` 同 partial `(subject, at desc)`。
- **同一張 table 仲有 Profile security activity 讀緊**：`hosted.py:658-666` `SECURITY_KINDS` / `ABOUT_ME_KINDS` 按 actor / subject 跨 workspace 讀。
- **而家寫嘅 workspace-scoped kinds（21 種）**：`workspace.created`（hosted.py:531）、`invitation.created`（:764）、`invitation.revoked`（:793）、`invitation.accepted`（:829）、`invitation.declined`（:883）、`member.updated`（:732）、`member.removed`（:746）、`member.left`（:565，subject 係 ''）、`billing.checkout_started`（:380）、`billing.portal_opened`（:398）、`data.exported`（:445）、`data.diagnostics`（:452）、`memory.egress_decided`（:157）、`research.egress_decided`（:159）、`oauth.started`（oauth.py:96）、`oauth.rejected`（:123）、`oauth.denied`（:130）、`channel.connected`（:147）、`channel.verified`（:244）、`channel.disconnected`（:264）、`reply.approved`（audience.py:101）。Account-scoped（workspace_id NULL）：`mfa.enabled/disabled`（hosted.py:693,708）、`session.revoked`（:909）、`session.revoked_others`（:924）、`session.alerted`（:502）。
- **冇寫嘅**：approve / approve_many / cancel（`store.py:287`、`:306`、`:316-321`，經 `hosted.py:152-160 mutate()`）；plan 變更（`store.py:187`，hosted action `p2_plan`）；`profile_decide` / `preference` / `learning_settings` / `learning_reset`（`permissions.py:35-37` owner class；preference / profile 決定實際經 `learning_service.py:256 decide()`，只寫 `pr_memory_proposals.decided_by` :294）；worker 結果（claim path `hosted_worker.py:56` canceled、`:59` uncertain、`:68` held、`:71` failed；finish path `:100-136`，只有 `:119 record_published` 寫 learning ledger）；media upload / delete（hosted.py:934-958）；billing webhook（billing.py 冇 `audit(`）；`delete_account`（hosted.py:1016+ 冇 audit，而且 cascade 會連 log 刪）。即係批核、發佈、發佈失敗 — 最不可逆嘅事 — audit log 一條都冇。
- Tests：`tests/phase2/postgres_isolation.py:197-218`（tenant-scoped、immutable、forged insert 被拒）、`postgres_channels.py:237-241`（OAuth lifecycle 冇 token）、`postgres_memory_egress.py:120-121`、`postgres_research.py:149`。

**可以重用**
- `web/src/features/account/profile-model.ts:87` `describeSecurityEvent()` — kind → 句子 + tone。
- `web/src/features/account/security-card.tsx:753` `SecurityActivity`（:774 Alert destructive、:779 Retry）。
- `web/src/features/queue/queue-view.tsx:267-276` motion `Tabs variant='pill'` + `DigitSwap`。
- `web/src/components/ui/table/`（data-table、toolbar、faceted-filter、date-filter、skeleton 等 10 個）+ `web/src/hooks/use-data-table.ts`；`docs/postriff-consumer-saas-redesign.md:379`（§6.8）指定呢頁 = data-table + date filter + faceted filter。
- `ui/empty.tsx`、`ui/sheet.tsx`（transitions 07）、`ui/loading-button.tsx`、`ui/learn-more-chevron.tsx`、`motion/animated-badge.tsx`、`motion/action-swap.tsx`（`ActionSwapIcon`）、`motion/button/stateful.tsx`、`hooks/use-flash.ts`、`client.ts:94 blob()`、`lib/time.ts`（`relativeTime` :35、`formatDateTime` :51，locale / timeZone 由 `setTimeDefaults` 設定）。
- Competitor 對照：Buffer 權限文件只講 admin 可以 see who created each post（https://support.buffer.com/article/670-adding-users-and-setting-up-permissions-in-your-organization）；Postiz team collaboration 文章只列 roles（https://postiz.com/blog/team-collaboration-best-practices）。讀得明嘅 who-did-what trail 係差異化。

## 1. Design specification（最新版）

**目的**：俾有權睇嘅 workspace 成員（權限層級待 James 拍板，預設跟 API / RLS = 任何 member）用一句人話睇到「邊個、幾時、做咗咩」— 加入／離開、連接／斷開 channel、批核／取消、發佈成功／失敗、匯出資料、privacy 決定。永遠唔顯示 post 內文、prompt、token、email。每行可以跳去事情發生嘅頁面。所有數字（分類計數、總數、已載入數）都係 API 回傳嘅真值；未有嘅類別（例如 post.* 未寫入之前嘅 Publishing）唔出現。

**Layout**：沿用 `PageContainer`（pageTitle 'Audit log'，pageDescription 'Who did what in this workspace, newest first. Never the content itself.'，`infoContent` 開右邊 Infobar，`access` + `accessFallback` 跟 nav 決定，`pageHeaderAction` 放 Refresh；Export 只喺 export endpoint 上線 + 有 export 權限先出現）。主欄由上至下：(1) Category pills — motion `Tabs variant='pill'`（同 queue-view.tsx:267），計數讀 API `counts`；(2) Toolbar — `DataTableToolbar`：Who（`DataTableFacetedFilter`，options 讀 API `actors`）+ When（`DataTableDateFilter`）+ Reset；filter 由 server 做（query params），唔係喺已載入 rows 入面篩；(3) 主體 — ≥768px `DataTable`（sticky header，4 欄 When / What / Who / Where），<768px card list；(4) Footer — 'Showing {loaded} of {total}'（兩個都係 API 值）+ 'Load older'，載完寫 'That is everything since {formatDate(oldest.at)}'。`cat`、`actor`、`from`、`to` 放 URL（nuqs，`useDataTable`）。時間用 `lib/time.ts`（跟 profile time_zone / locale）。

**375px**：Refresh / Export 縮 icon-only（`Icons.refresh`、`Icons.download`，保留 aria-label）；pills `scrollbar-hide overflow-x-auto`；Who + When 收入 'Filters' 掣開 `Sheet side='bottom'`；每行一張 card：句子、`Who · relative time`、右邊 chevron；撳 card 開 detail Sheet（bottom）。16px gutter，冇橫向 scroll。
**768px**：table 4 欄，Where 縮 icon link；Infobar overlay（`useIsMobile`）。
**1440px**：table + Infobar 並排；When `whitespace-nowrap`；What `max-w-[36rem]`。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header + actions | 講清楚呢頁係咩、唔係咩，同埋 action。 | Heading 'Audit log' + description（`data-tour='audit-title'`，同 tours.ts heading() fallback 對齊）。`pageHeaderAction`：Refresh（`Button variant='outline'`，`ActionSwapIcon` refresh↔spinner 由 `query.isFetching` 驅動，撳落 `refetch()`）；Export（`StatefulButton`：idle 'Export' → request in flight 'Preparing…' → 成功 `useFlash` 1.8s 'Downloaded' → idle；`client.ts blob()` 攞 JSON Lines）。Export 只喺 `GET /audit/export` 上線同 viewer 有 export 權限（建議 `manage_members`）先 render。`data-tour='audit-export'`。 | Export 失敗：toast.error(ApiError.message)，掣回 idle。Refresh 期間 rows 唔清空（keepPreviousData），只有 icon 轉。 |
| Category pills | 一眼分辨事件類別，同時係第一層 filter。 | motion `Tabs variant='pill'`，`TabsList aria-label='Filter events'`。Values：`all`、`members`（`member.*`、`invitation.*`、`workspace.created`）、`channels`（`oauth.*`、`channel.*`）、`publishing`（`post.*`、`plan.changed`）、`privacy`（`data.*`、`memory.*`、`research.*`、`voice.*`、`preference.*`、`learning.*`）、`billing`（`billing.*`）、`replies`（`reply.*`）。每個 trigger `<DigitSwap value={counts[cat]} />`，count 讀 API `counts`（成個 workspace、套用咗 Who / When filter 之後嘅真數）。API counts 入面某類係 0 而且該類 kinds 喺 backend 未有 writer（例如 publishing 喺 write path 上線前）就唔 render 呢粒 pill。`data-tour='audit-categories'`。 | Loading：pills render，計數位 `Skeleton h-4 w-5`（唔顯示 0）。API counts 失敗：計數位留空 + pill 照可以撳，唔顯示 0。 |
| Toolbar filters | 縮窄到某個人、某段時間。 | `DataTableToolbar`：Who faceted filter（options = API `actors`：`{ value: actorId ?? 'system', label: actorName \|\| 'Former member', count }`，'You' 排最先，'System' 只喺有 actor NULL 事件時出現）；When（`DataTableDateFilter`，送 `from` / `to` epoch 去 API）；Reset 只喺有 filter 時出現。`data-tour='audit-filters'`。 | Filter 後 `total === 0` → 'No events match these filters' + Reset（唔係頁面 empty state）。 |
| Event table / card list | 主體。每行一句人話，讀得明、跳得到。 | **When** — `<time dateTime={ISO} title={formatDateTime(at)}>{relativeTime(at)}</time>`；**What** — `describeAuditEvent(event).label`（例：'Connected Instagram for publishing'、'Approved a post to LinkedIn for 14 Mar, 09:00'、'Post to TikTok failed after 3 attempts'、'Removed a member'、'Exported workspace data (1.2 MB)'），句子本身係一粒 `<button>` 開 detail Sheet（唔用 row role='button'，避免同 Where link nested interactive）；tone warning / danger 嘅 kinds（`member.removed`、`channel.disconnected`、`oauth.rejected`、`oauth.denied`、`post.failed`、`post.held`、`post.uncertain`）前面加靜態 `AnimatedBadge size='sm' pulse={false}`；**Who** — `actorName`，`you` 加 `Badge variant='outline'` 'You'；`actor === null` → 'System'（tooltip 'The publishing worker or a provider callback'）；`actorName === ''` → 'Former member'（tooltip id 頭 8 位）；**Where** — `linkFor(event)` 有值就 `Link className='t-learn'` + `LearnMoreChevron`（channel.* / oauth.* → `/app/channels`；member.* / invitation.* → `/app/workspace/members`；post.* → `/app/queue`；data.* / memory.* / research.* → `/app/account/privacy`；billing.* → `/app/account/billing`；reply.* → `/app/inbox`；voice.* / preference.* / learning.* → `/app/workspace/memory`）。Link 只喺 viewer 有權入目標頁先 render（用 `checkAccess` + nav-config access key），否則留空。第一行 `data-tour='audit-row'`，Who cell `data-tour='audit-actor'`。Sort 固定 `(at desc, id desc)`。describeAuditEvent 所有句子集中喺 audit-model.ts（方便日後 UI 翻譯）。 | Loading：`DataTableSkeleton columnCount={4} rowCount={8}`（冇假字）。Error：`Alert variant='destructive'` 'The audit log could not be loaded.' + Retry（照 security-card.tsx:774-781）— 絕對唔 fallback 去 empty。未知 kind：default 句子用 kind 分詞，唔 crash。 |
| Footer / Load older | 誠實講清楚睇緊幾多、仲有幾多。 | 'Showing {loaded} of {total} events'（total = API count，受 filter 影響）。`hasNextPage` 時 `LoadingButton` 'Load older'（spinner 由 `isFetchingNextPage` 驅動）；載完 'That is everything since {formatDate(oldest.at)}'。Cursor = 最後一行 `(at, id)`。 | Load older 失敗：inline 'Older events could not be loaded.' + Retry，已載入 rows 保留。 |
| Detail Sheet | 一行嘅完整內容，唔使猜 meta。 | `Sheet side='right'`（mobile `bottom`）。SheetTitle = 句子；SheetDescription = `formatDateTime(at)` + relative。Definition list：Kind（mono）、Who（name + 完整 id + Copy）、Subject（完整 id + Copy；label 按 kind：'Connection id' / 'Invitation id' / 'Job id' / 'Request id'；subject 空就唔顯示）、Meta（每 key 一行；object 值 `<pre>`；空 meta 寫 'No extra details'）、Where（同一個 link，有權先出）。底部：'Events are append-only and content-free.' | 開 400ms / 收 350ms（transitions 07，`--panel-open-dur` / `--panel-close-dur`，已接 ui/sheet）。 |
| Info sidebar (Infobar) | 解釋邊界，唔使問。 | title 'About the audit log'。(1) 'Content-free by design' — 'Events carry ids, kinds, counts and timestamps — never post text, prompts, tokens or email addresses.'；(2) 'Who can see this' — 按 James 拍板嘅權限寫（預設：'Every active member of this workspace.'）+ 'Sign-in and two-factor events stay on each person's own Profile page.'；(3) 'System events' — 只喺 worker write path 上線後先出：'Publishing outcomes are recorded by PostRiff itself; they show as System.'；(4) 'Retention' — 'Kept for the life of the workspace. Deleting the workspace deletes its log; export first if you need a copy.'（Export 未上線前刪走後半句；同 privacy-view.tsx:51 文案一齊對齊）。InfoButton `data-tour='audit-info'`。 | — |

- **Empty state**：只喺冇 filter 而且 API `total === 0` 先顯示：`Empty` + `EmptyMedia variant='icon'`（`Icons.history`）+ `EmptyTitle` 'No events yet' + `EmptyDescription` 'This log fills up as people join, channels are connected and data is exported. It records who and when — never what was written.'（publishing write path 上線後先加 'posts are approved and published'）+ general CTA：'Invite a teammate'（→ `/app/workspace/members`，只喺 `manage_members`）、'Connect a channel'（→ `/app/channels`，只喺 `manage_connections`）；冇權限就只有文字。註：`bootstrap()` 第一次 sign-in 已寫 `workspace.created`（hosted.py:531），真實 workspace 幾乎唔會見到；filter 零結果係另一個 state。
- **Loading**：Header 即時 render（Refresh / Export disabled）；pills render、計數位 `Skeleton h-4 w-5`；主體 `DataTableSkeleton columnCount={4} rowCount={8}`（<768px 4 張 `Skeleton h-16`）；footer 唔 render。冇任何 'Fetching…' 文字。`useInfiniteQuery` + `placeholderData: keepPreviousData`，refetch / 換 filter 時舊 rows 唔閃。
- **Error**：第一頁失敗：主體換 `Alert variant='destructive'`（`Icons.alertCircle`）'The audit log could not be loaded.' + `ApiError.message`（如有）+ Retry。403（transaction 對非 member 回 'Workspace unavailable.'，或將來收緊權限）：`PageContainer accessFallback` 講明呢個 role 睇唔到。Load older 失敗：inline，已載入保留。Counts / actors 失敗：計數同 facet 留空（唔顯示 0），table 照用。Export 失敗：toast。任何情況都唔顯示 'No events yet' 或 0 計數去代替 unavailable。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| 整頁 | route mount | `.t-page-enter` fade + rise（page-slide clocks） | web/src/app/app/template.tsx + transitions.css 08 | 否（純裝飾） |
| Category pill indicator | user 揀 category | pill 底色 spring 滑去新 tab | web/src/components/motion/tabs.tsx variant='pill'（queue-view.tsx:267 同款） | 是 |
| Category 計數 | API counts 改變（refresh / filter / 新 events） | 數字逐位滾動到新值 | web/src/components/motion/digit-swap.tsx | 是 |
| 新到嘅 rows | refetch 回傳 `at > lastSeenAt`（本次到訪 component state）嘅 rows | opacity 0→1 + translateY 8px→0；只 stagger 頭 2 行（40ms），其餘同第 2 行一齊出，總長 ≤ 300ms（delay 40ms + `--duration-fast` 250ms）；prefers-reduced-motion 只做 opacity；首次載入同 Load older 唔播 | new — `motion.tr` / `motion.li` 用 transitions.css `--duration-fast` `--distance-base` `--ease-smooth-out` + `useReducedMotion()` | 是 |
| Tone badge（warning / danger kinds） | row render | 靜態 status 顏色，`pulse={false}`，冇 icon roll | web/src/components/motion/animated-badge.tsx | 是 |
| Where link 箭嘴 | hover / focus | chevron 右移 | transitions.css 24 `.t-learn` + web/src/components/ui/learn-more-chevron.tsx | 否（純裝飾） |
| Refresh 掣 icon | `query.isFetching` 變化 | refresh icon ↔ spinner 切換 | web/src/components/motion/action-swap.tsx（ActionSwapIcon） | 是 |
| Export 掣 | 撳 Export → request → 完成 | 'Export' → 'Preparing…'（只喺 request in flight）→ 'Downloaded' 1.8s → idle | web/src/components/motion/button/stateful.tsx（StatefulButton）+ web/src/hooks/use-flash.ts | 是 |
| Detail Sheet | 撳 What 句子 / Enter | panel reveal 開 400ms、收 350ms + cross-blur | web/src/components/ui/sheet.tsx（transitions 07） | 否（純裝飾） |
| Load older 掣 | `isFetchingNextPage` | spinner 只喺真請求期間出現 | web/src/components/ui/loading-button.tsx | 是 |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/workspaces/{id}/audit 基本 route + service | api | 有 | src/postriff_phase2/hosted_app.py:465-466 → hosted.py:929-932（LIMIT 200，冇 params） | S |
| 2 | pr_audit_events table + RLS + indexes | data | 有 | migrations/postriff/004_consumer_web_tenancy.sql:45-63；011_account_preferences.sql:12-14 | S |
| 3 | audit() writer（content-free、append-only） | backend | 有 | src/postriff_phase2/hosted.py:91-93 | S |
| 4 | audit_events 回傳 actorName / you / subjectName / total / counts（by kind）/ actors / nextCursor，接受 limit / before / kind / actor / subject / from / to；保留 events key | api | 冇 | hosted.py:929-932 只 SELECT 六欄。LEFT JOIN public.pr_profiles p ON p.user_id=e.actor（同 hosted.py:638 寫法）；subjectName 只對 kind IN ('member.updated','member.removed') 且 subject 符合 uuid regex 先 join（member.left / workspace.created subject 係 ''，直接 ::uuid 會 500）；count / GROUP BY kind 走 (workspace_id, at desc) index；cursor `(at, id) < (to_timestamp(%s), %s::uuid)` + `ORDER BY at DESC, id DESC`；limit default 100 max 500（用 hosted_app.py:222 `_query_int`）；kind prefix 驗 `^[a-z_.]{1,80}$`；subject param 俾 channel-history-sheet 用 | M |
| 5 | Publishing 決定入 audit：post.approved / post.cancel_requested / plan.changed（subject = job id；meta {platform, channelId, scheduleId, scheduledFor, variantId}，唔放 manifest.payload.text） | backend | 冇 | hosted.py:152-160 mutate() 只 audit memory / research；approve store.py:287、approve_many :306、cancel :316-321、plan :187。用 repository.effects（hosted.py:103、:146-147，收 before / after state）diff phase2.jobs | M |
| 6 | Worker 結果入 audit：post.published / post.failed / post.held / post.uncertain / post.canceled（actor NULL；meta {platform, providerReference 有就放, verification.method, attempts, reason}） | backend | 冇 | hosted_worker.py claim path :56 canceled、:59 uncertain、:68 held、:71 failed；finish path :100-136 只 :119 record_published。hosted_worker.py:9 已 import from .hosted，可以一併 import audit。Worker 直接 UPDATE state，唔經 repository.command，所以 effects hook 覆蓋唔到，要喺 worker 自己寫 | M |
| 7 | Owner decisions 入 audit：voice.decided / preference.decided / learning.settings_changed / learning.reset | backend | 冇 | permissions.py:35-37 owner class；preference / profile 決定經 learning_service.py:256 decide()（:294 只寫 decided_by），learning_settings / learning_reset 要逐條 path 確認係咪經 mutate() | S |
| 8 | GET /api/workspaces/{id}/audit/export → application/x-ndjson + data.audit_exported {rows}；privacy export zip 加 audit/events.jsonl | api | 冇 | hosted_app.py:465-466 只有 GET /audit；hosted.py:966-977 export() zip 未包 audit。Export permission 未定（建議 manage_members） | S |
| 9 | Tests：pagination 穩定（同 at 唔跳唔重複）、counts / total 同 rows 一致、subject 非 uuid 唔 500、post.* kinds、worker events actor NULL、meta 冇 payload text、export 冇 email / token、Profile security activity 唔受影響 | backend | 冇 | tests/phase2/postgres_isolation.py:197-218、postgres_channels.py:237-241 只覆蓋現有 kinds；建議新 tests/phase2/postgres_audit.py | M |
| 10 | useAudit() hook + api.audit() + AuditEvent type | frontend | 有 | web/src/lib/api/hooks.ts:74-77；client.ts:245；types.ts:720-727 | S |
| 11 | AuditEvent 擴充（actor: string \| null, actorName, you, subjectName）+ AuditPage { events, total, counts, actors, nextCursor } + api.audit(w, params) + api.auditExport(w) + useAuditPages()（useInfiniteQuery） | frontend | 冇 | types.ts:720-727 冇呢啲欄；client.ts:245 冇 params；hooks.ts 冇 useInfiniteQuery；blob() 喺 client.ts:94 | S |
| 12 | audit-model.ts：describeAuditEvent / categoryOf / toneOf / linkFor / subjectLabel（純函數，句子集中一處） | frontend | 冇 | 只有 describeSecurityEvent（profile-model.ts:87）；audit-view.tsx:21-28 summarise() 係 raw dump | S |
| 13 | data-table kit（toolbar / faceted / date filter / skeleton）+ nuqs URL state | frontend | 有 | web/src/components/ui/table/*.tsx；web/src/hooks/use-data-table.ts；docs/postriff-consumer-saas-redesign.md:379（§6.8） | S |
| 14 | Motion 元件：Tabs pill、DigitSwap、AnimatedBadge、ActionSwapIcon、StatefulButton、useFlash、LoadingButton、Sheet（07）、t-learn（24）、t-page-enter（08） | frontend | 有 | web/src/components/motion/{tabs,digit-swap,animated-badge,action-swap}.tsx、motion/button/stateful.tsx:158、hooks/use-flash.ts、ui/loading-button.tsx、ui/sheet.tsx、styles/transitions.css:212,246,422、app/app/template.tsx | S |
| 15 | keys.audit invalidation 喺 members / invitations / connect-return / approve / cancel / privacy export / egress 決定 | frontend | 冇 | 而家只有 channel-card.tsx:158；members-view.tsx:148,161,250,276、connect-return.tsx:46-47 等要加 | S |
| 16 | 權限三層對齊：nav-config、PageContainer access、API / RLS（先由 James 拍板） | frontend | 冇 | nav-config.ts:121 `role: 'admin'`；audit-view.tsx:34 冇 access prop；API hosted.py:929-930 + RLS 004:62 任何 member 可讀；web/src/lib/auth/permissions.ts:12 read = 全部 role | S |
| 17 | Tour infra（PAGE_TOURS、TourMount、help-menu nudge） | frontend | 有 | web/src/features/onboarding/tours.ts:155 PAGE_TOURS；tour-mount.tsx；app/app/template.tsx mount TourMount；queue-view.tsx:216 已有 data-tour | S |
| 18 | audit-tips entry + data-tour ids（audit-title / categories / row / actor / filters / export / info） | frontend | 冇 | tours.ts 冇 audit entry；audit-view.tsx 冇 data-tour | S |

## 3. Features

### P0

- **人話 rows：describeAuditEvent + actorName + 每行 deep link**：而家係 `channel.connected` + UUID 頭 8 位 + raw meta，讀唔明就冇人睇。Buffer 只做到 admin see who created each post，Postiz 只有 roles — 讀得明嘅 trail 係差異化，成本低：backend 一個 JOIN、frontend 一個純函數。
- **誠實 states + 真計數 + 權限對齊**：audit-view.tsx:32-38 將 error 顯示成 'No events recorded yet.'，直接違反真數據原則。加 total / counts、error Alert + Retry；nav / page / API 三層由 James 揀一個權限之後對齊，唔再有 sidebar 隱藏但 URL 照入嘅假 gate。
- **Publishing 決定同結果入 trail（post.approved / post.cancel_requested / post.published / post.failed / post.held / post.uncertain / post.canceled）**：發佈係 workspace 入面最不可逆嘅事，但 audit log 一條都冇。post.published 只喺 worker state == 'verified' 先寫，meta 帶 verification.method；submitted 但未確認係 post.uncertain，唔扮成功。Meta 只有 ids / platform / timestamps。Publishing pill、句子同 tour 文案要等呢個上線先出現。（depends on：repository.effects hook（hosted.py:103,146-147）+ hosted_worker.py:56-71,100-136）

### P1

- **Category pills + Who + When filters（server-side），URL 可分享**：有 publishing events 之後一個月可以幾百條。Redesign doc §6.8 指定 data-table + date + faceted filter；queue 頁已有 pills + DigitSwap。Filter 同計數由 API 做，數字先係成個 workspace 嘅真數，唔係已載入嗰幾十條。（depends on：API counts / actors / filter params）
- **Load older（keyset cursor）**：去除 200 條硬上限（亦修正 channel-history-sheet.tsx:77 嗰句『older accounts may show only part』）。Cursor 用 (at, id)，因為同一 transaction（approve_many）嘅 events at 相同。（depends on：API limit / before params）
- **Row detail Sheet（meta 逐項 + Copy id + Where link）**：Table 唔應該塞 raw meta，但查問題時要睇 missingScopes、publishLevel、attempts、providerReference。Sheet 已有 transitions 07。
- **Export JSON Lines + 併入 privacy export zip**：pr_audit_events 係 on delete cascade — 刪 workspace 就冇；俾人拎走一份係誠實補救。Export 本身記 data.audit_exported。掣同 tour step 只喺 endpoint 上線後出現。（depends on：GET /audit/export + export 權限決定）

### P2

- **Owner decisions 入 trail（voice.decided / preference.decided / learning.settings_changed / learning.reset / plan.changed）**：permissions.py:35-37 話呢啲改變全隊 drafts 讀法，係 owner decision；冇 audit 就冇追溯。要逐條 path 加（learning_service.py:256 decide() 唔一定經 mutate()）。
- **Overview card + Channel history sheet 共用 describeAuditEvent / subject filter**：overview-view.tsx:414 用 kind.replace()；channel-history-sheet.tsx:64 喺 200 條入面 client 過濾。共用純函數 + API subject param 一次過修好。另一個 session 正喺 web/src 做嘢，要協調。（depends on：audit-model.ts + API subject param）
- **media.uploaded / media.deleted / billing.subscription_changed（webhook，actor NULL）**：補齊 trail，唔係 blocker；billing events 只放 plan id 同 status，唔放 Stripe customer / invoice 資料。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明三件事：(1) 呢頁係「邊個、幾時、做咗咩」嘅時間線，最新喺最上；(2) 永遠唔會有 post 內文；(3) 每行可以跳去事情發生嘅頁面。教法：pageDescription 一句；category pills 帶 API 真計數；每行一句完整句子 + 人名 + 相對時間；Where link。InfoButton 講邊界。Page tips 用現有 onboarding infra：喺 web/src/features/onboarding/tours.ts PAGE_TOURS 加 `audit-tips`（route '/app/workspace/audit'、stop 'Audit log'），help menu 同一次性 nudge 自動接上；每個 step target 用 data-tour + heading('workspace/audit') fallback，未上線功能用 `when` 跳過。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="audit-categories"]（新加；fallback heading('workspace/audit')）` | Events by kind | Members, channels, privacy, billing and replies — plus publishing once posts are recorded. The numbers count every matching event in this workspace. |
| 2 | `[data-tour="audit-row"]（新加；fallback empty state）` | Every row is a sentence | Who did it, what happened and when. Open a row for the ids and details behind it. |
| 3 | `[data-tour="audit-actor"]（新加）` | Who | Names come from each member's profile. "You" marks your own actions; "System" marks what PostRiff did on its own. |
| 4 | `[data-tour="audit-filters"]（新加）` | Narrow it down | Filter by person or date. Filters live in the address bar, so you can share exactly what you are looking at. |
| 5 | `[data-tour="audit-export"]（新加；step 用 when() 只喺 Export 掣存在時出現）` | Take a copy | Download the log as JSON Lines. The download itself is recorded here too. |
| 6 | `[data-tour="audit-info"]（新加）` | What is never here | Post text, prompts, access tokens and email addresses are never stored in this log. |

**Empty state 教咩**：Empty state（只喺冇 filter 而 API total === 0）講清楚：呢頁會喺有人加入、連接 channel、匯出資料時自動填滿（publishing 上線後再加批核／發佈）；記錄嘅係「邊個、幾時」，唔係內容。CTA 係 general 嘅 'Invite a teammate' / 'Connect a channel'（按權限），冇任何特定品牌或行業例子。Filter 零結果係另一個 state（'No events match these filters' + Reset）。

## 5. Next steps（按次序）

1. **攞 James 拍板：(a) 邊個可以睇 audit log（跟 API / RLS = 任何 member，定收緊到 owner + admin → 需要新 migration 改 audit_tenant_read + API require + Overview card / channel history gate）；(b) Export 用咩 permission；(c) retention 文案跟 cascade 定加 tombstone**（effort S）  
   檔案：`docs（決定記錄）；web/src/config/nav-config.ts:116-122；migrations/postriff/004_consumer_web_tenancy.sql:62；web/src/features/account/privacy-view.tsx:51`
2. **Backend read path：audit_events 加 limit / before(at,id) / kind / actor / subject / from / to；LEFT JOIN pr_profiles 攞 actorName；subjectName 只對 member.updated / member.removed 且 uuid 格式 subject join；加 you、total、counts、actors、nextCursor；route 解析 query；tests：pagination 穩定、counts 同 rows 一致、subject '' 唔 500、Profile security activity 照舊**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:929-932；src/postriff_phase2/hosted_app.py:465-466（用 :222 _query_int）；tests/phase2/postgres_isolation.py:197-218；新 tests/phase2/postgres_audit.py`
3. **Backend write path：repository.effects 加 job diff（post.approved / post.cancel_requested / plan.changed）；hosted_worker claim path（:56,:59,:68,:71）+ finish path（:100-136）寫 post.* （actor NULL）；owner decisions 逐條 path 加 audit（learning_service.py:256 decide() 等）；test 斷言 meta 冇 payload text、worker events actor NULL**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:103,146-147,152-160；src/postriff_phase2/hosted_worker.py:56-71,100-136；src/postriff_phase2/learning_service.py:256；tests/phase2/postgres_audit.py`
4. **Frontend data layer：types.ts AuditEvent 擴充 + AuditPage；client.ts audit(w, params) + auditExport(w)（blob()）；hooks.ts useAuditPages()（useInfiniteQuery + keepPreviousData），保留 useAudit()；members / invitations / connect-return / approve / cancel / privacy export / egress mutations 加 invalidate keys.audit**（effort S）  
   檔案：`web/src/lib/api/types.ts:720-727；web/src/lib/api/client.ts:245；web/src/lib/api/hooks.ts:74-77；web/src/features/workspace/members-view.tsx:148,161,250,276；web/src/features/channels/connect-return.tsx:46-47`
5. **audit-model.ts 純函數：describeAuditEvent（覆蓋 21 個現有 kinds + 新 kinds，未知 kind 用分詞 default）、categoryOf、toneOf、linkFor、subjectLabel；web 冇 test runner，所以用 API tests 覆蓋 kinds 清單，唔好為呢頁引入新 runner**（effort S）  
   檔案：`新 web/src/features/workspace/audit-model.ts（參考 web/src/features/account/profile-model.ts:87）`
6. **重寫 audit-view.tsx：header actions、category Tabs + DigitSwap（API counts）、DataTableToolbar（server filters，nuqs）、DataTable / mobile card list、footer + Load older、detail Sheet、empty / filter-empty / error / loading、data-tour ids、新 rows motion（頭 2 行 stagger，總長 ≤ 300ms，useReducedMotion）；按 step 1 決定改 nav-config access + PageContainer access / accessFallback；tours.ts 加 audit-tips**（effort L）  
   檔案：`web/src/features/workspace/audit-view.tsx；web/src/config/nav-config.ts:116-122；web/src/features/onboarding/tours.ts；web/src/app/app/workspace/audit/page.tsx（不變）`
7. **Export endpoint：GET /audit/export 回 application/x-ndjson（Content-Disposition postriff-audit-log.jsonl），寫 data.audit_exported {rows}；privacy export zip 加 audit/events.jsonl；test 斷言冇 '@'、冇 token**（effort S）  
   檔案：`src/postriff_phase2/hosted_app.py:465 附近；src/postriff_phase2/hosted.py:966-977；tests/phase2/postgres_audit.py`
8. **Overview card + channel-history-sheet 改用 describeAuditEvent / actorName / subject param（同另一個 web/src session 協調）；Infobar、privacy-view retention 文案對齊**（effort S）  
   檔案：`web/src/features/overview/overview-view.tsx:401-425；web/src/features/channels/channel-history-sheet.tsx:62-77；web/src/features/account/privacy-view.tsx:51`
9. **Browser 驗證：dev harness :3100 light / dark、375 / 768 / 1440，console 零 error；用 Members invite + revoke 產生真 events（唔好撳 approve / schedule，harness Threads 係 live）；以 member / admin / viewer 三個 role 驗 gate；docs/postriff-motion-system.md §1 表加一行 Audit**（effort S）  
   檔案：`docs/postriff-motion-system.md；docs/postriff-consumer-saas-redesign.md §6.8`

## Risks

- 內容洩漏：post.* events 只可以放 job id / platform / channelId / scheduledFor / verification.method / attempts / providerReference，絕對唔放 manifest.payload.text、media alt 或其他 provider 回應。tests/phase2/postgres_audit.py 要斷言 json.dumps(events) 唔含 variant text 片段。
- 權限決定未拍板：nav-config（:121）admin-only，但 RLS（004:62）同 API 俾任何 member 讀。跟 DB（read）最一致；收緊就要新 migration + API require + Overview card / channel history 一齊 gate，唔係淨改 nav。實作前要 James 決定。
- 同一 transaction events `at` 相同（now() = transaction start；approve_many 一次寫多條）：cursor 同 sort 一定用 (at, id)。
- Retention 講法矛盾：audit-view Infobar 話 'full trail is kept with the workspace'，privacy-view.tsx:51 話 'receipts survive as tombstones'，但 004:48 on delete cascade。改文案或加 tombstone，唔可以兩邊都講。
- Subject 格式唔一致：member.left / workspace.created subject 係 ''，oauth.* 係 transaction id — subjectName join 同 subject filter 唔可以假設 uuid，否則成個 read 500，變成頁面 unavailable。
- 共用 table：Profile security activity（hosted.py:658-666）按 actor 跨 workspace 讀；新 kinds 或 index 改動要保證佢唔變慢、唔多出唔屬於佢嘅 kinds。
- 三個 consumer（audit-view、overview-view.tsx:148、channel-history-sheet.tsx:62）共用 keys.audit；換成 infinite query 時 key 要分開，唔好令 Overview 同 channel history 收到 page 結構而壞。
- Actor 身份：worker events actor NULL 顯示 'System'；已刪 profile 或已離開嘅人 display_name 可能空 — 顯示 'Former member' + id 頭 8 位，唔扮有名。
- count(*) / GROUP BY 每次請求：(workspace_id, at desc) index 喺 creator 規模冇問題；將來大 workspace 考慮 cache，唔好用 pg_class estimate（會變假數字）。
- Parallel session 正喺 web/src 做嘢 — audit-view.tsx、nav-config.ts、overview-view.tsx、channel-history-sheet.tsx、tours.ts 改動要先對齊，stage by path commit。
- Dev harness API 重啟會清 dev DB，要 re-seed；harness Threads 係 live provider，post.* events 只靠 code + tests 驗，唔好真 approve。
- UI 語言：而家只有 English，worldwide languages plan 只覆蓋 post languages；句子集中 audit-model.ts，時間格式跟 lib/time.ts locale / timeZone，唔好 hard-code 英文日期格式。

## 覆核記錄

- 改正：page.tsx:1-9 render <AuditView /> → 改做 :1-8
- 改正：checkAccess 在 web/src/lib/auth/access.tsx:96-98，role check 係 admin 或 owner → 改做 access.tsx:69-94（role check :79）
- 改正：useAudit 只有 audit-view 同 overview 兩個 consumer（所以 response shape 只要顧 Overview） → 加入第三個 consumer；改 API 要保留 events key，同埋 channel history 應該改用新 subject filter，文案要跟住改
- 改正：hooks.ts:19 key、:74-77 useAudit；client.ts:242 audit()；types.ts:716-723 AuditEvent → client.ts:245；types.ts:720-727
- 改正：全個 web/src 冇任何 mutation invalidate keys.audit（grep 只有 hooks.ts:19、:76） → 改做：只有 channel-card.tsx:158 invalidate；members-view、connect-return、privacy export、approve 等冇
- 改正：channels-view.tsx:99-100 invalidate keys.channels + keys.snapshot；connect-return.tsx:40-41 → 刪 channels-view 引用；connect-return.tsx:46-47；channel-card.tsx:156-159 已經做咗
- 改正：Route hosted_app.py:460-461 GET /audit → service.audit_events → 改做 :465-466
- 改正：_query_int helper 喺 hosted_app.py:231-239 → 改做 :222
- 改正：oauth.py 行號 :94、:121、:128、:145、:219、:238 → 逐個更正
- 改正：permissions.py:33-36 列明 profile_decide / preference / learning_settings / learning_reset 係 owner → 改做 :35-37；另外 preference / profile_decide 實際寫入經 learning_service.py:256 decide()，唔一定經 mutate()，所以唔係『mutate() 加幾個 lambda』咁簡單
- 改正：Worker 結果 hosted_worker.py:104-135 只有 :119 record_published；claim path :71 failed、:60 held → held :68、uncertain :59、canceled :56
- 改正：privacy export() 喺 hosted.py:957，zip 未包 audit → 改做 :966
- 改正：Tests 覆蓋：postgres_isolation.py:196-215、postgres_channels.py:187-191、postgres_memory_egress.py:120、postgres_research.py:149 → postgres_channels.py:237-241
- 改正：describeSecurityEvent 喺 profile-model.ts:96-138 → 改做 :87 起
- 改正：冇任何 tour infra（grep data-tour / tour 零結果），tour target 要新加，tour runner 係另一件事 → 改做：加一個 'audit-tips' entry 入 PAGE_TOURS（TourStep 需要 id / route / stop / target[] / title / body，可用 when(ctx)），target 用 data-tour + heading('workspace/audit') fallback
- 改正：Motion：新 rows stagger 40ms 最多 7 行（≤ 280ms） → 只 stagger 頭 2 行（40ms），其餘同第 2 行一齊出；或 duration 用更短 token，總長 ≤ 300ms
- 改正：Category pill 計數由已載入 rows 計，tooltip 講 'in the N loaded events' → API 回傳 counts（GROUP BY kind，走 (workspace_id, at desc) index）同 actors（DISTINCT actor + display_name），pill 同 facet 讀 API 值；API 未回之前顯示 Skeleton 唔顯示 0
- 改正：subjectName：member.* kinds join subject::uuid → 只對 kind IN ('member.updated','member.removed') 且 subject ~ uuid regex 先 join
- 改正：Tour step 'Seven kinds of events' 然後列 Members, channels, publishing, privacy, billing and replies → 'Six kinds of events'，publishing pill 喺 backend write path 未上之前唔顯示
- 違反原則（已改）：真數據：category pill 計數同 actor facet options 只計已載入嘅 rows，會令一個有 300 條 channel events 嘅 workspace 顯示 'Channels 3' — 要改讀 API counts / actors。
- 違反原則（已改）：Motion §5.4：新 rows stagger 最多 7 行 × 40ms + 250ms duration ≈ 490ms，超過總長 ≤ 300ms。
- 違反原則（已改）：Capability honesty / 真數據：tour 同 Export 掣喺 GET /audit/export 未存在之前已經講 'Download the whole log as JSON Lines'；Publishing pill 同 tour 喺 post.* events 未寫入之前已經出現 — 功能未上就唔可以喺 UI 或 tour 出現（用 when() / feature presence 控制）。
- 違反原則（已改）：Spec 自相矛盾：risks 話權限決定未拍板，next_steps 第 5 步就直接改 nav-config 做 permission: 'read' — 要先由 James 決定。
- 違反原則（已改）：真數據：tour 文案 'Seven kinds of events' 數錯（實際 6 類 + All）。
- 補上遺漏：Tour infra 其實已存在（web/src/features/onboarding/tours.ts PAGE_TOURS、tour-mount、help-menu nudge），spec 應該加 'audit-tips' entry 而唔係話『冇 infra』。
- 補上遺漏：第三個 useAudit consumer：channel-history-sheet.tsx:62-77 依賴 200 條上限同 subject 過濾；API 改動要加 subject param 同更新佢嘅文案。
- 補上遺漏：Profile security activity（hosted.py:658-666）讀同一張 table，新 kinds / meta 改動要保證唔影響。
- 補上遺漏：權限：Export 應該用咩 permission（建議 manage_members 或 owner，因為係成個 workspace 嘅 trail）；PageContainer access + accessFallback 對應 nav 決定；Overview card 同 channel history 要跟同一個 gate。
- 補上遺漏：i18n：UI 文案暫時只有 English（docs/postriff-worldwide-languages-plan.md 係 post languages，唔覆蓋 UI）；時間要用 lib/time.ts 嘅 setTimeDefaults（profile time_zone / locale），describeAuditEvent 句子要集中喺 audit-model.ts 方便日後翻譯，唔好散落 JSX。
- 補上遺漏：A11y：table row role='button' 唔理想；What cell 放真 <button> 開 Sheet，Where 係獨立 link，避免 nested interactive。
- 補上遺漏：Invalidation 範圍：approve / cancel、privacy export、memory/research egress、reply approve 之後都應該 invalidate keys.audit，唔止 members / channels。
- 補上遺漏：Web 冇 unit test runner（package.json 冇 test script），驗證要靠 Python API tests + browser 驗證。
- 補上遺漏：Backend 'you' 同 subjectName query 要處理 subject 為 '' 同非 uuid 嘅情況，否則 500。
