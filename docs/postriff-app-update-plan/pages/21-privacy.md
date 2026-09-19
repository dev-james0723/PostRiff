# 21 · Privacy & data

> Route：`/app/account/privacy` · Sidebar：Account · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

【前端】`web/src/app/app/account/privacy/page.tsx:1-8` 只 render `PrivacyView`。`web/src/features/account/privacy-view.tsx:56-277` client component，用 `useDataRequests()`（`web/src/lib/api/hooks.ts:79-82` → `client.ts:248` → `GET /api/workspaces/{w}/data-requests`）同 `usePrivacyNotice()`（`hooks.ts:144-147` → `client.ts:104` → `GET /api/privacy/notice`，public、staleTime 10 分鐘）。Page description 已經寫「Export, retract, inspect or delete」，但頁面冇 retract。

現有動作同問題：
1. Export drafts（`privacy-view.tsx:82-87`）：先 `api.dataRequest(w,{kind:'export'})`（`client.ts:249-250` → `hosted.py:439-445` build zip、SHA-256、receipt、audit `data.exported`），再 `api.exportDrafts(w)`（`client.ts:143` → `hosted_app.py:487-490` → `hosted.py:966-977`）**再 build 一次**。`hosted.py:973-976` `writestr(name字串)` 用當前時間做 entry 時間戳，兩次 build 唔保證 byte-identical，toast 個 sha256 未必係手上個檔。
2. Voice profile（`privacy-view.tsx:89-92` → `client.ts:144` → `hosted_app.py:491-494` → `hosted.py:979-1004`）：無 receipt、無 audit；package 未 approve（條件係 `engine._profile(state).packageSchema`，唔係 `speaker.activeRevision`）時 throw（`hosted.py:983-985`），UI 撳咗先知。
3. Diagnostics（`privacy-view.tsx:94-98`）：`POST /data-requests {kind:'diagnostics',consent:true}`；後端（`hosted.py:447-453`、`privacy.py:52-66`）回傳 sanitized `package`，**UI 掉咗**；receipt 只存 `fields`，package 冇儲存、冇 GET；冇任何 code 將 package 送去 support。
4. Delete account（`privacy-view.tsx:100-111,149-180`）：`checkAccess(access,{permission:'owner'})`（line 62）係真 gate——`web/src/lib/workspace/provider.tsx:145-153` 由 membership 計 permissions（`access.tsx` 嘅 STUB 只係 context default）。`DELETE /account`（`client.ts:152-153` → `hosted_app.py:495-497` → `hosted.py:1016-1052`）：confirmation → identity configured → `assert_fresh`（`hosted.py:117-122`，`permissions.py:43 STEP_UP_WINDOW=600`，403「Sign in again…」）→ owner（否則 403「Workspace unavailable.」）→ 任何 job 喺 `IN_FLIGHT`（`store.py:19`）就 409（`hosted.py:1030-1031`）。注意 cancel 一個 in-flight job 只會轉 `uncertain`（`store.py:316-321`），仍然鎖住。UI 冇 pre-check；`/data-deletion`（`web/src/app/(marketing)/data-deletion/page.tsx:38`）承諾「the app tells you if any are pending」。
5. Data requests table（`privacy-view.tsx:183-220`）：kind raw string、靜態 Badge、只識 `sha256`。API 有 `completedAt`（`privacy.py:80`），`DataRequest` type（`types.ts:729-735`）冇；diagnostics / retraction / deletion receipt 顯示「—」。
6. Notice（`privacy-view.tsx:222-273`）：只畫 status / aiProcessing / providerAccess / telemetry；retention label 用 `replace(/_/g,' ')` 兼掉 `.note`；`ingestion`、`subprocessors`、`rights`（`privacy.py:30-41`、`types.ts:737-747`）冇畫。

【承諾咗但唔存在】`data-deletion/page.tsx:54` 同 `web/src/content/docs.ts:58-66` 話可以喺 Ideas / Brand & voice retract **或 delete** source 並留 receipt；`legal-shared.ts:32` RIGHTS 寫「Retract or delete any source」。Web 冇 retract UI，亦冇 delete-source action。`sources-panel.tsx:30` 只顯示 active。後端 `POST /data-requests {kind:'retraction',sourceId,expectedRevision}`（`hosted.py:459-464`，經 `mutate` → class `edit`，409「Workspace changed; reload.」`hosted.py:138`）→ `retract_source`（`src/postriff_alpha/domain.py:302-314`：清空 text/facts、title「Withdrawn source」、`active=False`、`withdrawnAt`、移出 `brief.sourceIds`、如係 idea source 重設 brief.idea、依賴 variants `blockedByRetraction`）。**Bug**：receipt `dependentVariantsBlocked`（`hosted.py:462`）數嘅係全 workspace 累計 blocked variants，而且 response（`hosted.py:464`）冇 receipt。另 `kind:'deletion'`（`hosted.py:454-458`，owner only）UI 冇 call。Retraction 唔會抹走已生成 draft 嘅文字同 revision history，`GET /export` 亦冇 block（`domain.py:309` 註釋同 hosted export 行為唔一致）。

【Route table】notice `hosted_app.py:286-288`；data-requests GET/POST `hosted_app.py:391-395`（list `privacy.py:77-80`，LIMIT 100，任何 active member）；export `487-490`；profile-export `491-494`；DELETE account `495-497`。Table `pr_data_requests`：`migrations/postriff/hosted-004-008.sql:414-424`。Export / profile-export / diagnostics 冇 role gate（只查 membership，`hosted.py:106-115`）；但 viewer 本身已可讀全 snapshot（`hosted.py:124-127`），所以 gate export 係產品決定，唔係 leak fix。

【相關資料源】`useSnapshot()`（`hooks.ts:39-42`）：`state.sources[]`、`state.variants[]`（`sourceIds`、`blockedByRetraction`）、`state.phase2.assets/channels/jobs`、`membership.role`；`useMemory()`（`hooks.ts:133-136`、`client.ts:145`）：`egress?`、`research?`、`learning?`（全部 optional）。Egress / research owner switch 喺 Memory page（`memory-view.tsx:70-141`，`permissions.py:33-34`，audit `hosted.py:157-159`）；Memory nav 係 `access:{permission:'edit'}`（`nav-config.ts:135`）。`GET /api/me/security-events`（`hosted.py:658-676`）actor-scoped，含 `data.exported` / `data.diagnostics`，Profile 顯示（`profile-model.ts:120-123`，diagnostics label「Shared a diagnostics package」誇大）；Profile 冇 `#security` anchor。

【Drift】`web/src/content/legal-shared.ts:1-35` 聲稱 mirror `privacy.py`：legal-shared 多 Stripe / Resend / Exa / Jina（四個喺 `billing_stripe.py`、`email.py`、`research.py` 真係用緊），`privacy.py:22-27` 只列四個——in-app notice 少報；`privacy.py:14 account_pictures` legal-shared 冇。

【Motion】現時 Skeleton pulse、AlertDialog、Sonner、Checkbox。

【Tests】`tests/phase2/postgres_billing.py:133-141`（service 層 export/diagnostics receipt、consent 403、list）；`tests/test_postriff_billing.py:86`（WSGI POST export）；`tests/test_postriff_phase2_hosted.py:161-164`（FakeService profile-export + delete）。冇：GET WSGI list、retraction / deletion kind、zip determinism。

【Nav / Tour】`web/src/config/nav-config.ts:163-167`（`shieldCheck`，冇 access）；`app-sidebar.tsx:227-230`。Tour infra 已存在但未 commit（另一 session WIP）：`web/src/features/onboarding/tours.ts`（`PAGE_TOURS`、`TourStep{id,route,stop,target[],title,body,when?}`、`TourCtx` 有 `canEdit` 冇 isOwner）、`tour-overlay.tsx`、`help-menu.tsx`、`web/src/styles/tour.css`；data-tour 已用於 `memory-view.tsx:200`、`calendar-view.tsx:190` 等。Step-up 現有 pattern：`web/src/features/workspace/member-access-sheet.tsx:141-151`（toast action「Sign in again」）；但 `auth-form.tsx:50` 已登入會即刻 redirect，re-auth 是否刷新 auth_time 未驗證。

## 1. Design specification（最新版）

**目的**：一頁畀任何用戶睇清楚 PostRiff 持有佢幾多資料（真 count）、資料會去邊（cloud model / web research），同埋自助做四件事：export、diagnostics、retract source、delete account。每個動作留 receipt，而 receipt 講嘅數必須等於實際發生嘅事。呢頁亦係平台 app review 嘅 data-deletion 證據，文案要同 `/data-deletion`、`docs.ts` 逐句對得上（包括 button 名）。

**Layout**：沿用 `PageContainer`（title「Privacy & data」，description「What we hold, where it goes, and what you can do about it. Every action leaves a receipt.」，`infoContent` 四節；唔用 `isLoading` 避免成頁閃）。單欄 `flex flex-col gap-8`，五個 section：(1) What PostRiff holds — stat tiles + Where it goes 兩行；(2) Actions — `grid gap-4 lg:grid-cols-2`：Export workspace（primary）、Voice profile、Diagnostics、Retract a source；(3) Data requests table；(4) Privacy notice（`grid lg:grid-cols-3`：How your content is used / Retention / Subprocessors；下面 Your rights）；(5) Delete account（`border-destructive/40`）永遠最底。Info sidebar（i 鍵）四節：Export with a receipt、Diagnostics stay with you、Retraction（清空 source 原文同 facts、依賴 draft block，已寫好嘅 draft 文字唔會自動抹走）、Deletion（owner only、要等 in-flight 發佈確認、trial tombstone 會留）。權限版本：viewer / approver 見到所有 section，但 Export / Voice / Retract 卡 button disabled +「Ask an editor or owner」（純 UI 提示，API 仍係 source of truth）；「Change on Memory ›」只畀 canEdit；Delete 卡非 owner 只見說明句。Responsive：375px — tiles `grid-cols-2`、action card 單欄、table 收 Details 欄（`hidden sm:table-cell`）改成 row 展開、AlertDialog footer buttons full-width 直排、頁面冇橫向 scroll（table wrapper `overflow-x-auto` 只限 table）；768px — tiles `grid-cols-3`、action 兩欄、table 全欄；1440px — tiles `xl:grid-cols-5`，開 info sidebar 仍 fit（`min-w-0`）。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| What PostRiff holds | 首 5 秒答到「你哋有我幾多嘢」。全部讀 `useSnapshot()` / `useMemory()`，冇數字寫死。 | 五個 tile（`data-tour="privacy-holdings"`）：Sources（`sources.filter(s=>s.active).length`，副行「N withdrawn」= `!active` count，>0 先顯示）；Drafts（`variants.length`，副行「N blocked by a retracted source」>0 先顯示）；Media files（`phase2.assets.filter(a=>!a.deleted).length`）；Linked accounts（`phase2.channels` 非 revoked 數，副行「Capabilities per account on Channels ›」，唔寫「Connected」唔寫 tokens）；Learned preferences（`memory.learning?.items.filter(i=>i.status==='active').length`，`learning` undefined → Unavailable）。數字用 `NumberTicker`（`locale`、`startOnView`、`duration={0.26}`、`stagger={0.04}`）。Where it goes 兩行（`data-tour="privacy-egress"`）：Cloud model reads your memory files → `AnimatedBadge` success「Shared」/ neutral「Not shared」讀 `memory.egress.cloud`，副行「N boundaries always withheld」= `egress.withheldBoundaries`；Web research → `research.enabled===false` 成行唔顯示、`research.hosted===false` 顯示「Always on when drafting on your own machine」、否則 On/Off 讀 `research.web`。Read-only；「Change on Memory ›」（`LearnMoreChevron`）只畀 canEdit。`egress`/`research` undefined 或 memory query error → 「Unavailable」，唔可以變「Not shared」。 | loading：五個 Skeleton tile + 兩行 Skeleton；error：該 tile/行「Unavailable」+ Retry；成功而數值 0：顯示 0，副行「Nothing added yet」。 |
| Actions | 四個自助動作，每張卡一句講清楚會攞到乜、留低乜 receipt。 | Export workspace（`data-tour="privacy-export"`）：「Drafts, sources, approvals, receipts and learning ledger as a zip. No tokens, no media bytes.」；`StatefulButton` idle「Export workspace」→ loading「Preparing…」→ 落地後 `crypto.subtle.digest('SHA-256')` 計 blob hash 同 `X-PostRiff-Sha256` header 比較 → 相同：success「Verified」+ toast「sha256 …（前 12 字）」+ `SuccessCheck`；唔同：error「Hash mismatch」+ toast「The file you received does not match the recorded receipt. Export again.」。後端 single-build 未上線前，button 只寫「Exported」唔寫 Verified。Voice profile：button 保持可撳（唔用 activeRevision 猜），失敗時 toast 後端原句 + action「Open Brand & voice」；後端加 `voicePackageReady` 之後先改做 disabled + 副行。成功同樣 client hash 顯示喺 toast。Diagnostics：Checkbox「I consent to creating a diagnostics package (counts and states only)」→ `StatefulButton`「Create package」→ `Dialog` 顯示 `package` JSON（`<pre>` mono、`max-h-80 overflow-auto`）+「Download JSON」（`downloadBlob`，`postriff-diagnostics-{requestId}.json`）+「Copy」；文案「PostRiff does not send this anywhere and does not keep a copy. Download it and attach it when you contact support.」。Retract a source（`data-tour="privacy-retract"`）：`Select` 列 active sources（title 或 kind + approved facts 數）；副行「Retraction blanks the source text and facts and blocks every draft that used it. Drafts already written keep their text until you edit or remove them. It cannot be undone.」；「Retract…」→ `AlertDialog` 列真數「N drafts use this source」（`variants.filter(v=>v.sourceIds.includes(id)).length`），若係目前 brief idea 加一句「Your current idea will be reset.」→ `POST /data-requests {kind:'retraction',sourceId,expectedRevision:snapshot.revision}` → toast「Source retracted」（後端修好 per-source receipt 並回傳之後先加「· N drafts blocked」）→ invalidate `keys.snapshot(w)` + `keys.dataRequests(w)`；409 → toast 原句 + refetch snapshot。冇 active source：Select disabled +「No active sources in this workspace」。權限：Export / Voice / Retract 用 `checkAccess(access,{permission:'edit'})`（Retract 後端真係 edit；Export/Voice 後端現時冇 gate，UI 暫時唔 gate，等 James 決定）；Diagnostics 所有 member。 | busy 時其他卡 button disabled（沿用 `busy`）；API error 用 `ApiError.message` 原句 toast。 |
| Data requests | 證據表：每個動作一行，睇到幾時、乜嘢、狀態、receipt。 | `data-tour="privacy-requests"`。副題「Every export, diagnostics package and retraction adds a row here.」。欄：When（`formatDateTime(requestedAt)`，`title` 顯示 completedAt）；Request（`privacy-model.ts describeDataRequest()`：export→「Workspace export」/ receipt.contents 係 voice→「Voice profile export」；diagnostics→「Diagnostics package created」；retraction→「Source retracted」；deletion→「Deletion requested」；未知 kind → raw string）；Status（`AnimatedBadge` sm：completed→success、requested→warning、failed→danger，`contentKey=status`）；Details（export：`Intl.NumberFormat` bytes + sha256 前 16 字 mono + Copy；diagnostics：fields 列表；retraction：新 receipt 有 per-source 數先顯示「N drafts blocked」，舊 row 只顯示「Source retracted」唔顯示累計數；deletion：receipt.note）。新 row 入場同 `sources-panel.tsx:60-64`。表頂「Also in your account history ›」去 `/app/account/profile`（加 anchor 後先帶 `#security`）。 | loading：Skeleton h-24；empty：`Empty`（見 empty_state）；error：一句原句 + Retry。 |
| Privacy notice | In-app notice，完整畫出 API 每個 field。 | 標題行右邊 `AnimatedBadge` warning「Draft — pending legal review」（`LEGAL_REVIEW_STATUS==='draft'`，`web/src/config/legal.ts:8,10`；reviewed 時 success「Reviewed · LEGAL_LAST_UPDATED」）+「Full policy」「Deletion steps」link。三張卡：How your content is used（aiProcessing、providerAccess、ingestion、telemetry）；Retention（Data / Kept until / Note，label 用 `privacy-model.ts RETENTION_LABEL`，同 legal-shared.ts RETENTION wording 一致，未知 key fallback `replace(/_/g,' ')`）；Subprocessors（Name / Purpose / Status / Region，直接 render API）。Your rights：`rights[]` 靜態 check icon list。 | loading：三個 Skeleton h-40；error：「The privacy notice could not be loaded.」+ Retry，唔 fallback 去 legal-shared。 |
| Delete account | Owner 專用破壞性動作，撳之前知道會唔會成功、會刪乜留乜。 | `data-tour="privacy-delete"`。Owner 描述：「Removes this workspace, its media, your memberships and your sign-in. Content-free receipts and a trial record stay; the trial cannot be restarted.」（`hosted.py:1042`）；非 owner：「Only the workspace owner can delete the account.」冇 button。Pre-flight（真數，讀 snapshot jobs）：`inFlight = jobs.filter(j=>IN_FLIGHT.includes(j.state))`（`privacy-model.ts` mirror `store.py:19`）>0 → warning「Waiting for N publications to confirm」+「See Queue ›」，button disabled，副行「A post already sent to a platform cannot be recalled; deletion unlocks once each is confirmed or marked failed.」；=0 → neutral「No publications in flight」。另一行真數「N scheduled posts will be removed and never published」（非 terminal、非 IN_FLIGHT job，>0 先顯示）。Button「Delete account…」→ AlertDialog：「Export first if you want a copy」+ 內嵌 Export button；Input 打 `DELETE`；「Delete everything」→ `DELETE /account`。403 且 message match /sign in again/i → dialog 內顯示提示 +「Sign in again」（同 member-access-sheet.tsx:141-151 pattern，路徑要驗證可刷新 auth_time），唔關 dialog；其他 403 → 原句；409 → 原句 + refetch snapshot。成功 → toast、`auth.signOut()`、`router.replace('/')`。 | deleting：「Deleting…」disabled；snapshot loading：pre-flight Skeleton、button disabled；snapshot error：「Unavailable — reload before deleting」、button disabled。 |

- **Empty state**：Data requests 空：`Empty`（`web/src/components/ui/empty.tsx`）icon shieldCheck、title「No requests yet」、description「Exports, diagnostics packages and retractions each add a row here with a receipt.」、`EmptyContent` 一個「Export workspace」button（viewer 唔顯示）。Stat tiles query 成功而 0 → 顯示 0 +「Nothing added yet」；只有 error / field 缺失先「Unavailable」。Retract 冇 active source → Select disabled +「No active sources in this workspace」。
- **Loading**：每個 section 獨立 Skeleton（pulse），形狀同最終 layout 一致：五 tile + 兩行、四張卡 button 位、table h-24、notice 三個 h-40、delete pre-flight 一行。冇假 loading copy。
- **Error**：Per-section：`requests` / `notice` / `snapshot` / `memory` 各自 `ApiError.message` 原句（冇就 generic）+ outline Retry（`refetch()`），其他 section 照常。403「Workspace unavailable.」（membership 被移除）→ 整頁顯示原句 + link 返 /app。動作失敗 → Sonner 原句；export hash mismatch → StatefulButton error + toast，receipt row 照留。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Stat tile 數字 | snapshot / memory query 成功後首次入 viewport | NumberTicker duration 0.26s、stagger 40ms，總長 ≤300ms；reduced-motion 直接顯示；Unavailable 唔 animate | web/src/components/motion/number-ticker.tsx（必須覆寫預設 duration 0.9） | 是 |
| Where it goes badge | memory query 成功；值改變 | AnimatedBadge text roll，contentKey 跟值；唔 pulse | web/src/components/motion/animated-badge.tsx | 是 |
| Export workspace button | 撳 → fetch → 落地 → client hash 比對 | StatefulButton idle→loading→success（只喺 hash 相同）或 error；success 2s 返 idle；SuccessCheck 只喺核對成功 | web/src/components/motion/button/stateful.tsx + web/src/components/ui/success-check.tsx | 是 |
| Diagnostics checkbox / Create / package dialog | 剔 consent；撳 Create；API 回傳 package | Checkbox 畫剔；StatefulButton loading→success；Dialog 開 250ms 收 150ms | ui/checkbox.tsx、motion/button/stateful.tsx、ui/dialog.tsx（--modal-open-dur / --modal-close-dur，transitions.css:69-70） | 是 |
| Data requests 新 row | 本 session 動作後 refetch 到新 requestId | opacity 0→1、y 6px→0、240ms；stagger 40ms 上限 200ms；reload 唔重播；reduced-motion duration 0 | motion/react motion.div，參數同 sources-panel.tsx:60-64 | 是 |
| Status badge / Delete pre-flight badge | status 或 in-flight 數改變 | AnimatedBadge tone + text roll | web/src/components/motion/animated-badge.tsx | 是 |
| Retract / Delete 確認 | 撳「Retract…」/「Delete account…」 | AlertDialog modal，收快過開 | ui/alert-dialog.tsx（現有） | 否（純裝飾） |
| Change on Memory / See Queue / Channels / account history links | hover | learn-more 箭嘴 | ui/learn-more-chevron.tsx | 否（純裝飾） |
| 頁面進入 | route change | t-page-enter | web/src/app/app/template.tsx（現有） | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | GET /api/privacy/notice 回傳 status / aiProcessing / providerAccess / ingestion / retention / subprocessors / rights / telemetry | api | 有 | src/postriff_phase2/hosted_app.py:286-288 → privacy.py:30-41；web/src/lib/api/types.ts:737-747 | S |
| 2 | GET /api/workspaces/{id}/data-requests（LIMIT 100，有 completedAt） | api | 有 | hosted_app.py:391-393 → privacy.py:77-80 | S |
| 3 | POST /data-requests kinds export / diagnostics / deletion / retraction | api | 有 | hosted_app.py:394-395 → hosted.py:438-465 | S |
| 4 | Retraction 後端 retract_source | backend | 有 | hosted.py:459-464；src/postriff_alpha/domain.py:302-314 | S |
| 5 | Retraction receipt 改為 per-source（只數 sourceIds 含該 source 嘅 variants）並喺 response 回傳 receipt | backend | 冇 | hosted.py:462 數全 workspace blockedByRetraction；hosted.py:464 response 冇 receipt | S |
| 6 | GET /export、GET /profile-export、DELETE /account | api | 有 | hosted_app.py:487-497；hosted.py:966-977, 979-1004, 1016-1052 | S |
| 7 | Export 單次 build：抽 helper build zip → hash → record receipt + audit → `GET /export` 回傳 zip 連 `X-PostRiff-Request-Id` / `X-PostRiff-Sha256`；`data_request('export')` 共用 helper | backend | 冇 | hosted.py:439-445 同 966-977 兩次 build；hosted_app.py:487-490 冇 receipt/audit；同 origin（web/next.config.ts:28-34、vercel.json rewrites） | M |
| 8 | Zip determinism：`ZipInfo(name, date_time=(1980,1,1,0,0,0))` | backend | 冇 | hosted.py:973-976、1001-1002 用字串 name → 當前時間 | S |
| 9 | Voice export 留 receipt（kind export，contents='personal voice package'）+ 後端暴露 `voicePackageReady` | backend | 冇 | hosted.py:979-1004 冇 record/audit；條件係 _profile(state).packageSchema（983-985）；DB check 容許 export（hosted-004-008.sql:418） | S |
| 10 | privacy.py SUBPROCESSORS 補 Stripe / Resend / Exa / Jina（conditional status）+ RETENTION 同 legal-shared 對齊 | backend | 冇 | privacy.py:22-27 只四個；billing_stripe.py、email.py、research.py 已使用；legal-shared.ts:18-27 | S |
| 11 | API client `blobWithMeta(path)` → `{ blob, requestId, sha256 }` | frontend | 冇 | web/src/lib/api/client.ts:94-98 blob() 只回傳 res.blob() | S |
| 12 | `web/src/lib/hash.ts sha256Hex(blob)`（crypto.subtle） | frontend | 冇 | web/src/lib 冇 hash util（只有 download.ts） | S |
| 13 | `DataRequest` 加 `completedAt: number\|null` + receipt union；`SnapshotSource` 加 `withdrawnAt?` | frontend | 冇 | types.ts:729-735、131-142；domain.py:304 有寫 withdrawnAt | S |
| 14 | `web/src/features/account/privacy-model.ts`：describeDataRequest、statusTone、RETENTION_LABEL、IN_FLIGHT、TERMINAL（mirror store.py:18-19）、全部新文案常數 | frontend | 冇 | 無此檔；pattern 見 web/src/features/account/profile-model.ts | S |
| 15 | Diagnostics package Dialog + Download JSON | frontend | 冇 | privacy-view.tsx:95 掉咗 response package；hosted.py:453 有回傳 | S |
| 16 | Retract a source UI（Select → AlertDialog → POST retraction → invalidate snapshot + dataRequests） | frontend | 冇 | web/src 冇 retract UI；hooks.ts:150-163 useAct 只 setQueryData act path，要手動 invalidate keys.snapshot(w) | M |
| 17 | Delete pre-flight（IN_FLIGHT + scheduled 真數）+ 403 step-up 處理 | frontend | 冇 | privacy-view.tsx:100-111 只失敗後 toast；hosted.py:1022,1027-1031；pattern member-access-sheet.tsx:141-151 | S |
| 18 | Stat tiles + where-it-goes 讀 useSnapshot / useMemory | frontend | 冇 | hooks 存在（hooks.ts:39-42, 133-136），privacy-view 未用 | S |
| 19 | Notice 完整 render + legal review badge | frontend | 冇 | privacy-view.tsx:239-269 只畫四 field；legal.ts:8,10,13 | S |
| 20 | Profile security card 加 `id="security"` anchor；diagnostics event label 改「Created a diagnostics package」 | frontend | 冇 | features/account 冇 id='security'；profile-model.ts:123 | S |
| 21 | Page tour 'privacy-tips' 註冊入 PAGE_TOURS + data-tour anchors（privacy-holdings / privacy-egress / privacy-export / privacy-retract / privacy-requests / privacy-delete） | frontend | 冇 | tour infra 已存在（未 commit）：web/src/features/onboarding/tours.ts PAGE_TOURS、tour-overlay.tsx；privacy anchors 未有 | S |
| 22 | Tests：WSGI GET data-requests、retraction per-source receipt、deletion owner-only、export header + determinism | backend | 冇 | tests/test_postriff_billing.py:86 只 cover POST export；tests/phase2/postgres_billing.py:133-141 service 層 export/diagnostics | S |
| 23 | Drift test：privacy.py RETENTION_CLASSES / SUBPROCESSORS ↔ web/src/content/legal-shared.ts | data | 冇 | legal-shared.ts:6-27 vs privacy.py:9-27 已唔一致 | S |
| 24 | Motion primitives：NumberTicker、AnimatedBadge、StatefulButton、SuccessCheck、Empty、LearnMoreChevron、Dialog/AlertDialog | frontend | 有 | web/src/components/motion/number-ticker.tsx:8-46、animated-badge.tsx:15-27、button/stateful.tsx:9-19、ui/success-check.tsx:32、ui/empty.tsx:94、ui/learn-more-chevron.tsx:26 | S |
| 25 | Real workspace access（role → permissions） | frontend | 有 | web/src/lib/workspace/provider.tsx:145-153,173；web/src/lib/auth/permissions.ts mirror permissions.py CLASSES | S |

## 3. Features

### P0

- **Honest export receipt：一次 build、瀏覽器核對 SHA-256，相同先話 Verified**：而家 privacy-view.tsx:82-87 build 兩次，toast sha256 未必係手上個檔（hosted.py:973 時間戳）。Receipt 要證明「你收到嘅就係我記低嘅」。
- **Retract a source（呢頁 + per-source receipt）**：/data-deletion page.tsx:54、docs.ts:58-66、legal-shared RIGHTS 已公開承諾，reviewer 會照做；後端齊但 receipt 數錯（hosted.py:462 累計）。（depends on：retraction receipt 後端修正；SnapshotSource.withdrawnAt；privacy-model.ts）
- **Diagnostics package 先睇後落地，講明冇送去任何地方**：Consent 要 informed：UI 掉咗 package（privacy-view.tsx:95），而 Profile label 講「Shared」但實際冇分享。
- **Delete pre-flight：in-flight / scheduled 真數、owner gate、step-up 處理**：/data-deletion page.tsx:38 承諾「the app tells you if any are pending」；而家打完 DELETE 先 409；cancel 唔會解鎖，文案要講真。（depends on：privacy-model.ts IN_FLIGHT）
- **Data requests table 讀得明**：呢張表係 audit 證據；diagnostics / retraction receipt 而家顯示「—」、kind 係 raw string。（depends on：DataRequest type 更新）

### P1

- **What PostRiff holds + Where it goes**：刪除或 export 之前俾人睇到「有幾多、去咗邊」，全部真 count；Linked accounts 唔用 blended Connected。
- **Notice 完整 render + legal review badge + privacy.py subprocessor 補齊**：API 有 ingestion / subprocessors / rights / note 但 UI 冇畫；in-app 少報四個實際使用中嘅 subprocessor。
- **Voice profile export 留 receipt + voicePackageReady**：同頁兩種 export 一種冇 receipt；前端冇可靠條件預判 package 未 approve（hosted.py:983-985）。
- **文案對齊：/data-deletion、docs.ts、legal-shared RIGHTS**：刪走「or delete it」（冇 delete-source action）；「finish or be cancelled」改做等確認；button 名同步「Export workspace」。

### P2

- **Page tour 'privacy-tips'**：沿用現有 onboarding tour 系統，help menu 可開；成本只係 anchors + 一個 PAGE_TOURS entry。（depends on：web/src/features/onboarding 由另一 session commit）
- **Export role gate（決定題）**：Viewer 已可讀全 snapshot，所以唔係 leak fix；純粹係「viewer 應唔應該可以攞走 bulk copy」嘅產品決定，要 James 拍板。
- **Drift test privacy.py ↔ legal-shared.ts**：防止公開頁同 in-app notice 再講兩樣嘢。
- **Retraction 同時出現喺 Ideas sources panel + withdrawn 清單**：公開頁講「In Ideas or Brand & voice」；共用 handler。（depends on：Retract a source）
- **刪除前記一行 kind:'deletion'**：hosted.py:454-458 已支援；workspace_id on delete set null 令 row 變 content-free 記錄。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內明三件事：(1) PostRiff 持有你幾多嘢——頂部真 count tiles；(2) 你可以自己做四件事——四張 action card 同一句式「攞到乜、留低乜」；(3) 每個動作有 receipt——Data requests 副題「Every export, diagnostics package and retraction adds a row here」。教法靠 layout 同 empty state，唔彈 modal；info sidebar（i）做深一層；help menu 可開 page tour。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `[data-tour="privacy-holdings"] → fallback main h1（tours.ts heading('privacy')）` | What we hold | These counts come straight from your workspace: sources, drafts, media, linked accounts and learned preferences. Unavailable means it could not be read, never zero. |
| 2 | `[data-tour="privacy-egress"] → fallback [data-tour="privacy-holdings"]` | Where it goes | Whether the cloud model may read your memory files, and whether drafting may look facts up on the web. The workspace owner changes these on the Memory page. |
| 3 | `[data-tour="privacy-export"]（when: ctx.canEdit）` | Export with a receipt | One zip with drafts, sources, approvals and receipts. Your browser checks the file against the recorded SHA-256, so Verified means the file matches. |
| 4 | `[data-tour="privacy-retract"]（when: ctx.canEdit）` | Retract a source | Blanks the source text and facts and blocks every draft that used it. Drafts already written keep their text until you change them. |
| 5 | `[data-tour="privacy-requests"]` | Receipts | Every export, diagnostics package and retraction lands here with its receipt. |
| 6 | `[data-tour="privacy-delete"]` | Delete everything | Only the workspace owner can do this. Publications already sent must be confirmed first; this card shows how many are still waiting. A trial record stays so the trial cannot restart. |

**Empty state 教咩**：Data requests 空時教：呢張表係做乜（每個 export / diagnostics / retraction 一行）、receipt 可以自己核對；內嵌「Export workspace」令第一次到訪即刻產生第一張 receipt（viewer 唔顯示）。Tiles 全 0 時「Nothing added yet」講明 0 係真 0。

## 5. Next steps（按次序）

1. **後端 export 單次 build：抽 helper（ZipInfo date_time 固定）+ hash；`GET /export` 記 receipt + audit `data.exported` 並回傳 `X-PostRiff-Request-Id` / `X-PostRiff-Sha256`；`data_request('export')` 共用；voice export 同樣記 receipt + 暴露 `voicePackageReady`；retraction receipt 改 per-source 並喺 response 回傳；privacy.py SUBPROCESSORS 補齊。Tests：兩次 build hash 相同、header = receipt、GET WSGI list、retraction per-source 數、deletion owner-only。**（effort M）  
   檔案：`src/postriff_phase2/hosted.py:438-465, 966-1004；src/postriff_phase2/hosted_app.py:487-494；src/postriff_phase2/privacy.py:9-27；tests/phase2/postgres_billing.py:133-141；tests/test_postriff_billing.py:86 附近；tests/test_postriff_phase2_hosted.py:155-165`
2. **前端 plumbing：`client.ts` 加 `blobWithMeta()`；新 `web/src/lib/hash.ts`；`types.ts` DataRequest `completedAt` + receipt union、SnapshotSource `withdrawnAt?`；新 `privacy-model.ts`（labels、tones、IN_FLIGHT/TERMINAL、所有新文案常數，方便將來 UI i18n）。**（effort S）  
   檔案：`web/src/lib/api/client.ts:94-98, 143-144, 248-250；web/src/lib/hash.ts（新）；web/src/lib/api/types.ts:131-142, 729-735；web/src/features/account/privacy-model.ts（新）`
3. **重寫 `privacy-view.tsx` 五個 section：tiles + where-it-goes（NumberTicker duration 0.26、Unavailable 邏輯、Linked accounts）；四張 action card（export client hash；voice 原句 toast；diagnostics Dialog；Retract Select + AlertDialog + invalidate）；table（label / badge / per-kind details / 新 row motion / Empty）；notice 完整 + legal badge；delete pre-flight（in-flight + scheduled 真數）+ step-up 403 處理。權限用 `checkAccess`（provider.tsx 已係真 membership）。加六個 data-tour id。每 section 獨立 loading / error / Retry。只 stage 呢個檔同新檔。**（effort L）  
   檔案：`web/src/features/account/privacy-view.tsx；web/src/components/motion/{number-ticker,animated-badge,button/stateful}.tsx；web/src/components/ui/{success-check,empty,dialog,alert-dialog,select,learn-more-chevron}.tsx`
4. **文案對齊：`data-deletion/page.tsx` :35 button 名、:38「finish or be cancelled」改做等確認、:54 刪「or delete it」並講明已寫 draft 唔會自動抹；`docs.ts:58-66` 同步；`legal-shared.ts` 加 account_pictures、RIGHTS「Retract any source」；`profile-model.ts:123` diagnostics label；security card 加 `id="security"`；加 drift test。**（effort S）  
   檔案：`web/src/app/(marketing)/data-deletion/page.tsx:35-54；web/src/content/docs.ts:58-66；web/src/content/legal-shared.ts:6-35；web/src/features/account/profile-model.ts:120-123；web/src/features/account/security-card.tsx；tests/（新 drift test）`
5. **Page tour：喺 `tours.ts` PAGE_TOURS 加 'privacy-tips'（route '/app/account/privacy'、stop 'Privacy & data'、target selector array + heading fallback、export/retract step `when: ctx.canEdit`）。等另一 session commit onboarding/ 之後先做，唔好一齊 stage。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts`
6. **Dev harness 手動驗證（:3100 preview pane，唔 approve / schedule / send）：export → Verified；diagnostics dialog；retract 一個 sample source → row 顯示 per-source 數、drafts blocked；delete card in-flight / scheduled 數；403 step-up 後 re-auth 路徑是否真係刷新 auth_time（auth-form.tsx:50 會 redirect 已登入用戶）；viewer 帳號睇 disabled 狀態；375 / 768 / 1440 截圖。API 重開會清 dev DB，記得 re-seed。**（effort S）  
   檔案：`.claude/launch.json；scripts/postriff_dev_hosted.py`
7. **P2 跟進：retraction 搬去 `sources-panel.tsx` + withdrawn 清單；刪除前 POST kind:'deletion'；export role gate 等 James 決定；考慮 export 對 blockedByRetraction draft 嘅處理（domain.py:309 註釋 vs hosted export）。**（effort M）  
   檔案：`web/src/features/ideas/sources-panel.tsx；web/src/features/account/privacy-view.tsx；src/postriff_phase2/hosted.py:966-977`

## Risks

- 真數據：export 兩次 build（hosted.py:439-445 vs 966-977）令 sha256 未必等於落地檔；後端未修前 UI 唔准用「Verified」。
- 真數據：retraction receipt `dependentVariantsBlocked`（hosted.py:462）係累計數；修好前唔顯示 N，舊 row 亦唔顯示。
- Honesty：retraction 只清 source 本身同 block drafts（domain.py:302-314），已寫 draft 文字同 revision history 仍在，`GET /export` 冇 block；冇 delete-source action。文案唔可以暗示衍生內容已抹走。
- In-flight 鎖死：`published` / `uncertain` 屬 IN_FLIGHT（store.py:19）；cancel 只會轉 uncertain（store.py:316-321）；worker 停咗嘅環境 deletion 會一直 409。UI 顯示真數 + Queue link，唔可以提示「cancel 就得」。
- Step-up：`DELETE /account` 要 auth_time 喺 600 秒內（hosted.py:117-122、permissions.py:43）；step-up 同非 owner 都係 403，要靠 message 分辨；/auth/sign-in 會 redirect 已登入用戶（auth-form.tsx:50），re-auth 路徑未驗證。
- Export role gate 係產品決定唔係 security fix：viewer 已可 GET 全 snapshot（hosted.py:124-127）。
- Drift：legal-shared.ts 同 privacy.py 唔同步，而且係 in-app 少報 Stripe / Resend / Exa / Jina；in-app 只 render API，唔 fallback TS 常數。
- Memory API：dev 見過 `GET /memory` 404（docs/postriff-motion-system.md:113），egress/research/learning 全部 optional；error 或缺失 → Unavailable，唔可以顯示 Not shared 或 0。
- Cache：retraction 經 data-requests 唔經 useAct（hooks.ts:150-163），要手動 invalidate `keys.snapshot(w)`，否則 source 仲喺 Select。
- Legal review：LEGAL_REVIEW_STATUS 仍係 draft（legal.ts:8）；in-app badge 唔可以收起。
- Parallel sessions：privacy-view.tsx 同 web/src/features/onboarding/（未 commit）屬其他 session WIP 範圍；實作時 stage by path。
- i18n：UI 仍係英文單語，冇 UI i18n infra；新文案集中喺 privacy-model.ts，唔好散落 JSX。

## 覆核記錄

- 改正：client.ts:245 dataRequests、246-247 dataRequest、140 exportDrafts、149-150 deleteAccount、95-99 blob()、142 memory → 改用新行號
- 改正：hosted_app.py GET /export 482-485、profile-export 486-489、DELETE account 490-492 → 改為 487-490 / 491-494 / 495-497
- 改正：export_profile 979-1001；未 approve 時 throw（982-984）；UI 應用 state.speaker.activeRevision 預判 → 唔好用 activeRevision 做 disable 條件；由後端喺 snapshot/memory 暴露 `voicePackageReady` boolean，或者保留 button 可撳、錯誤原句 toast + link 去 Brand & voice
- 改正：assert_fresh hosted.py:118-123；permissions.py:39 STEP_UP_WINDOW=600s → permissions.py:43
- 改正：delete 409 in-flight hosted.py:1032-1033；非 owner gate → 行號改 1030-1031；403 處理要 match /sign in again/i（同 member-access-sheet.tsx:141 一樣）
- 改正：Delete pre-flight 文案「Finish or cancel them in Queue」 → 文案改「Waiting for N publications to confirm — see Queue ›」，唔提 cancel；/data-deletion page.tsx:38 嘅「finish or be cancelled」一樣要改
- 改正：Retraction 成功 toast N 讀 response dependentVariantsBlocked → 後端改為只數 `sourceId in v.sourceIds` 嘅 variants 並喺 response 回傳 receipt；修好之前 toast 唔顯示 N（違反真數據）
- 改正：access.tsx:6-9 Phase A stub，人人都係 owner，delete owner gate 只係裝飾；要確認 app-gate.tsx 有冇傳真 membership → 刪走 next_step 4 嘅 app-gate 確認同 risk 3；UI gate 係真，但 API 仍然係 source of truth
- 改正：Export 冇 role gate，viewer 可 export 全部 drafts + sources，係 data leak 面 → 降為產品決定（P2，要 James 拍板），唔好當 security fix 包裝
- 改正：types.ts DataRequest 725-731（冇 completedAt）、PrivacyNotice 733-743、SnapshotSource 129-140（冇 withdrawnAt） → 更新行號
- 改正：link 去 /app/account/profile#security → 要喺 security-card.tsx 加 id，或者 link 去 /app/account/profile 唔帶 hash
- 改正：data-deletion/page.tsx:40「the app tells you if any are pending」、:54 retract or delete；docs.ts:58-66 → 行號 38；改名要同步改 page.tsx:35 同 docs.ts:62
- 改正：web/src 冇 data-tour、冇 tour infra → tour 用 PAGE_TOURS 註冊 'privacy-tips'，target 用 selector array + fallback；刪走 next_step 8「cross-page tour component」
- 改正：NumberTicker 數字滾動 stagger ≤40ms、總長 ≤300ms → 明確傳 duration={0.26}、stagger={0.04}，位數多時總長仍 ≤300ms（或 >3 位數時唔 animate）
- 改正：Diagnostics dialog 文案「This is exactly what support receives」 → 改「PostRiff does not send this anywhere. Download it and attach it when you contact support.」
- 改正：/auth/sign-in?next= 支援與否未查 → risk 改為：step-up re-auth 路徑要喺 dev harness 驗證（可能要先 signOut 再 sign in）；UI 沿用 member-access-sheet 嘅 toast action pattern
- 改正：Tests：postgres_billing.py:133-141 cover export/diagnostics；test_postriff_phase2_hosted.py:161-164；冇 WSGI data-requests route test → 改為『冇 GET WSGI、retraction/deletion kind、determinism test』
- 改正：Stat tile Connected accounts = channels.length + 副行「tokens held encrypted」 → label 改「Linked accounts」數 non-revoked，副行「Capabilities per account on Channels ›」，唔寫 tokens held
- 違反原則（已改）：真數據：Retraction toast「N drafts blocked」讀 dependentVariantsBlocked，但後端（hosted.py:462）數嘅係全 workspace 累計 blocked variants，而且 response 冇呢個 field——會顯示錯數。
- 違反原則（已改）：真數據 / capability honesty：Diagnostics dialog「This is exactly what support receives」——冇任何 code 送 package 去 support。
- 違反原則（已改）：Capability honesty：「Connected accounts」tile + 「tokens held encrypted」係 blended 狀態，包埋 revoked channel。
- 違反原則（已改）：Motion §5：NumberTicker 預設 duration 0.9s，spec 冇覆寫，實際會超 300ms 上限。
- 違反原則（已改）：真數據：Delete pre-flight「Finish or cancel them in Queue」——cancel in-flight job 只會變 uncertain，仍然鎖住刪除（store.py:316-321）。
- 違反原則（已改）：真數據：Voice export 用 activeRevision 預判，同後端 packageSchema 條件唔一致，會出現 button enabled 但必定失敗，或者相反。
- 違反原則（已改）：誠實 framing：將 export role gate 包裝成 data-leak fix，但 viewer 本身已可 GET 全 snapshot。
- 違反原則（已改）：Drift 修正方向錯：建議 privacy.py 唔加 Stripe/Resend/Exa/Jina，但四個都已喺 code 使用，in-app notice 少報先係問題。
- 補上遺漏：RBAC 全表：Privacy nav 冇 access key（全員可見）；Memory nav 係 edit-gated，所以「Change on Memory ›」link 只應顯示畀 canEdit；approver/viewer 睇到嘅版本要寫清楚。
- 補上遺漏：Retraction 副作用：會改 brief.sourceIds，若係目前 idea source 會重設 brief.idea；AlertDialog 要講。
- 補上遺漏：Export 包含已 retract source 衍生嘅 draft 文字同 revision history（domain.py:309 註釋話 export 應 block，但 hosted export 冇做）——retraction 文案唔可以暗示衍生內容已抹走。
- 補上遺漏：Delete pre-flight 除咗 in-flight，仲應講真數「N scheduled posts will be removed and never published」（非 IN_FLIGHT job 會隨 workspace 刪走）。
- 補上遺漏：Step-up re-auth 路徑：已登入用戶去 /auth/sign-in 會即刻 redirect（auth-form.tsx:50），要驗證能否真係刷新 auth_time。
- 補上遺漏：現有 tour 系統（web/src/features/onboarding，未 commit）嘅 PAGE_TOURS 格式、TourCtx（冇 isOwner）。
- 補上遺漏：Security event label「Shared a diagnostics package」（profile-model.ts:123）同樣誇大，應一齊改。
- 補上遺漏：公開頁同 docs 嘅 button 名稱（data-deletion page.tsx:35、docs.ts:62「Export drafts」）要同步。
- 補上遺漏：Mobile：Delete AlertDialog 喺 375px 要 full-width buttons；table 橫向唔 scroll 成頁。
- 補上遺漏：i18n：UI 仍係英文單語，冇 UI i18n infra（worldwide languages plan 係 post 語言）；所有新文案集中喺 privacy-model.ts，將來 localize 一處改。formatDateTime 用 browser locale。
- 補上遺漏：404/403 workspace unavailable（membership 被移除）時整頁 error state。
- 補上遺漏：parallel session：privacy-view.tsx / onboarding/ 係 WIP 區，stage by path。
