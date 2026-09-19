# 08 · Library

> Route：`/app/library` · Sidebar：Create · 成熟度：部分完成 · 覆核：needs-fixes
> 呢份 spec 由研究 agent 對住 codebase 起稿，再由另一個 agent 逐句核對 file:line 並改正（改正記錄見文末）。

## 而家嘅狀態

【頁面】`web/src/app/app/library/page.tsx:7` render `LibraryView`（`web/src/features/library/library-view.tsx`）。Sidebar 入口喺 `web/src/config/nav-config.ts:50-55`（title 'Library'、url '/app/library'、icon 'media'、shortcut l l），**冇 `access` key**，所以 viewer／approver 都見到呢頁。

【資料流（全部真）】`useSnapshot()`（`web/src/lib/api/hooks.ts:39-42`）→ `GET /api/workspaces/{id}`（`src/postriff_phase2/hosted_app.py:461-462` → `hosted.py:124-127` 由 `pr_workspaces.state` 讀）→ `state.phase2.assets`（`types.ts:148`）。`Asset` type 喺 `types.ts:42-51`：id、hash、mime、width?、height?、bytes?、deleted、storagePath?。頁面喺 `library-view.tsx:100` filter `!a.deleted`，按 array 順序 render。Assets 只會 append（`hosted.py:230`、`store.py:254-255`），所以 array 順序就係真實上載先後（最舊喺頭）。

縮圖：`AssetThumb`（`library-view.tsx:59-69`）→ `api.media(w, id)`（`client.ts:139`，blob）→ `GET /api/workspaces/{id}/media/{assetId}`（`hosted_app.py:435-438` → `hosted.py:957-964` → Supabase private bucket `hosted_storage.py:77-84`，`Cache-Control: private, no-store`）。冇 objectName 或 deleted 會 404（`hosted.py:962-963`）；storage 未配置會 503（:958-959）。Query key `['media', w, id]`、`staleTime: Infinity`；`web/src/components/application/post-preview/use-preview-post.ts:25-27` 用同一個 key，Queue/Calendar preview 同 Library 共用縮圖。

上載：file input（`accept='image/*'` :155；單一檔 :159 只取 `files?.[0]`）→ base64（`toBase64` :71）→ `POST /actions` action `p2_media_upload`（:112）→ `hosted_app.py:480-481` → `hosted.py:934-946`：storage 未配置 503（:935-936）→ `require(edit)`（:939）→ `PrivateAssetService.stage_upload`（`hosted_storage.py:112-120`）→ `decode_upload(payload, decoder="pillow")`（`media.py:82-92`）。規則：只收 JPEG/PNG magic bytes（:20）、1 B–8 MB（:18）、320–4096 px 每邊、≤16.7 MP（:60）、full decode、EXIF transpose、alpha 壓白底、重新編碼 JPEG q92、去 metadata（:61-75）。Body 上限 12,000,000 bytes（`hosted_app.py:198`），8 MiB base64 ≈ 11.18 MB。Asset record：id、sourceHash、hash、bytes、width、height、mime（永遠 'image/jpeg'）、duration 0、processing 'decoded'、decoder、deleted，加 storagePath/objectName/execution（`hosted_storage.py:119`）。**冇 createdAt、uploadedBy、name、alt**。Command 失敗會 remove 已 stage 嘅 object（`hosted.py:941-945`）。

刪除：`p2_media_delete` → `hosted_app.py:482-483` → `hosted.py:948-955` 兩段式（prepare :233-241 → storage delete → finish :243-252）。有 in-flight job（`store.py:19` IN_FLIGHT = submitting/provider_accepted/published/uncertain）引用就拒絕「Reconcile this asset's in-flight jobs before deleting its bytes.」（`hosted.py:237-238`）。Manifest 保留 media id+hash（`store.py:374`），刪圖後 review 變 stale、scheduled job 變 held（`store.py` current()/invalidate；`tests/test_postriff_phase2.py:310-324`）。

權限：前端 `checkAccess(access, { permission: 'edit' })`（`library-view.tsx:94`，`web/src/lib/auth/access.tsx:69`）；後端 upload 明確 `require(edit)`（`hosted.py:939`），delete 行 `repository.command` 預設 requirement='edit'（`hosted.py:129-131`）。準備 post（`p2_review`）係 'approve'（`permissions.py:28`）。

【Sample workspace】read-only 檢查喺 `HostedPhase2Commands.__call__`（`hosted.py:188-189`），但 upload_media/delete_media 直接呼叫 add_asset/prepare_asset_delete（:942、:951），**唔經呢個檢查**。

【現有 UI】PageContainer header + `StatefulButton`（Uploading…/Uploaded/Upload failed，`useFlash`）；grid 2/3/4/6 欄；每卡 `TiltCard max=6` + hash 前 10 位 + mime · WxH · size + Delete 按鈕（:235-239）；`ContextMenu`：Copy hash / Delete…；`AlertDialog` 確認；`AnimatePresence mode='wait'` 空狀態（標題『No media yet』:197）↔grid；grid staggerChildren 35ms 冇上限（:44）、enter 280ms、exit 200ms（reduced 150ms）、`layout='position'` + `SPRING_LAYOUT`；`useReducedMotion` 已處理。Loading 係一舊 `h-64` Skeleton（:180）。縮圖失敗顯示 'Preview unavailable'（:67），冇 retry。

【邊度用緊 Library 嘅圖】`web/src/features/queue/schedule-dialog.tsx:49,55,192-205`：`Select` 列 `mime · hash8…`，dialog 已有 `variantId` preselect prop（:37,54）；`web/src/features/agent/plan-card.tsx:117,327-351`：只有 Instagram 行有 `Select` + alt Input + 連去 `/app/library`。Alt text 同 rights 係 review 時先要（`store.py:371`），Instagram 4:5–1.91:1 喺 review 時 enforce（`store.py:372-373`）。`ideas.py:208-229` 有 conversation attachment kind 'asset'（`client.ts:195` `api.attach`），web/src 冇任何呼叫。

【Onboarding】tour 系統已存在：`web/src/features/onboarding/tours.ts`（WELCOME_TOUR、PAGE_TOURS :156、TourCtx :14-24），`help-menu.tsx:37` 開本頁 tips；Library 未有條目，頁面亦未有任何 data-tour。

【誠實問題】Info sidebar「Storage counts toward your plan allowance」（`library-view.tsx:55`），但 server 冇計 storage：`billing.py:60` 接受 dimension 'storage'，upload_media 冇 reserve；`Entitlement.storageMb`（`types.ts:495`、`billing.py:47`）只係 plan 數字（`billing-view.tsx:216` 寫『included』）。

【疑似 bug（PLAUSIBLE，未有 test）】`add_asset`（`hosted.py:226`）、`prepare_asset_delete`（:234）、`finish_asset_delete`（:244）用 `state["membership"]["userId"] != principal` 做 guard。`state["membership"]` 只喺 bootstrap 寫死做創建者（`auth.py:24`），grep src/postriff_phase2 冇其他寫入；真 membership 只放 snapshot 頂層（`hosted.py:127,150`）。即 editor/admin 過咗 `require(edit)` 之後會收到 403。`tests/test_postriff_phase2_hosted.py:115-119` 只測 command engine 擋 media shortcut，冇非 owner 上載。

【測試】`tests/test_postriff_phase2.py:272-278`（decoder 拒絕假檔、去 metadata）、`:310-324`（Instagram 要圖、rights、刪圖後 job 變 held）、`tests/test_postriff_hosted_deployment.py:52-60`（Pillow 路徑）。`tests/test_postriff_consumer_web.py` 冇 Library 測試。Motion inventory：`docs/postriff-motion-system.md:45`。

## 1. Design specification（最新版）

**目的**：Workspace 私有嘅圖片庫。每張圖一上載就 decode、去 metadata、記 hash；之後準備 post 時揀圖，manifest 綁死個 hash。頁面要喺 5 秒內答到三件事：我有幾多張圖（真數）、邊張用過喺邊個 post、呢張圖喺我連咗嘅 channel 有冇已記錄嘅圖片規則。呢頁唔會發佈任何嘢，亦唔會阻任何人寫 draft。

**Layout**：沿用 `PageContainer`（pageTitle 'Library'、pageDescription、infoContent、pageHeaderAction）。

1440px：header 右邊 `StatefulButton`「Upload images」（multi-file，只 edit 權限 render）；header 下一行 toolbar：左＝search input（hash 前綴／WxH），中＝motion `Tabs` variant 'segment'「All · Unused · Used」每格附 `DigitSwap` 真計數，右＝sort `Select`（Newest · Oldest · Largest）+ 統計「N images · X MB」。Grid `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4`（現有）。edit 權限先將 content 區變 dropzone（`react-dropzone` `useDropzone({ noClick: true, noKeyboard: true, accept: {'image/jpeg':[], 'image/png':[]}, maxSize: 8*1024*1024 })`），拖入時 overlay border-dashed +「Drop to upload」。撳卡開右邊 `ui/sheet`（w-[480px]）detail。Info sidebar 三段：Private by default／Provenance／What is accepted（plan storage 數字只喺 usage query 成功時以『Your plan includes Y MB』出現）。

768px：grid 3 欄；sheet 420px；toolbar wrap 兩行（search 全寬）。

375px：header 疊（title → description → Upload 全寬）；toolbar：search 全寬、Tabs 全寬、sort + 統計再一行；grid 2 欄 gap-3；detail 用 `ui/drawer` 由底彈出（85vh，可 scroll，有明確 Close）；ContextMenu 靠長按，所以 detail 要有齊同一組 actions；coarse pointer 停用 TiltCard。無橫向 scroll，gutter 由 PageContainer `px-4`（`page-container.tsx:60`）提供。

權限：read（所有成員）＝睇、search、detail、Copy hash；edit（owner/admin/editor）＝上載、刪除；approve（owner/approver 或 can_publish）＝『Use in a post』。Primary action 對 edit 權限係 Upload；viewer 見到唯讀頁面同一句『Ask a workspace editor to add images』。卡面冇 Delete 按鈕（搬入 detail 同 context menu），卡面只剩：圖、usage chip、WxH · size。

| Section | 做咩 | 內容 | States |
|---|---|---|---|
| Header + Upload | 唯一主動作。多檔上載，每檔一個真請求，按鈕文字讀真計數。 | `StatefulButton` icon=`Icons.upload`，`<input type='file' multiple accept='image/jpeg,image/png'>`（取代現有 image/*）。Queue 逐個送 `p2_media_upload`，revision 用上一個成功回傳嘅 `snapshot.revision`。loadingText「Uploading 2 of 5…」；successText「5 uploaded」；部份失敗 errorText「3 of 5 uploaded」+ 每個失敗檔一個 toast 寫 server 原文（例如 media.py:60 嘅尺寸訊息）。Client 只先驗 ≤ 8 MB 同 type，尺寸留 server。`canEdit` false 唔 render；sample workspace（`state.workspace.sample`）顯示 disabled + tooltip「This sample workspace is read-only」，同時 backend 要補同一檢查（見 technical_requirements）。 | idle / loading（真計數）/ success / partial / error；hidden（無 edit）；disabled（sample、已知 storage 503）。 |
| Dropzone overlay | 拖放上載，同按鈕行同一條 queue。 | 只喺 canEdit 時啟用。`isDragActive` render `absolute inset-0 rounded-lg border-2 border-dashed bg-background/80` + `Icons.upload` +「Drop JPEG or PNG · up to 8 MB each」。fileRejections（非 JPEG/PNG、>8 MB）即刻 toast，唔入 queue。 | hidden / active（真 dragenter）/ reject（toast）。 |
| Toolbar | 搵圖、分用過未用、真統計。 | Search：`ui/input` + `Icons.search`，match `hash.startsWith(q)`、`sourceHash?.startsWith(q)`、`${width}×${height}` 包含 q。Tabs（`components/motion/tabs` variant 'segment'）：All(n) · Unused(n) · Used(n)，n 用 `DigitSwap`，由 usage map 計。Sort：Newest（array 反轉，真上載次序，而家就做得）· Oldest（array 原序）· Largest（bytes）。統計「{n} images · {formatBytes(sum bytes)}」，只計未刪除 asset；唔寫『of Y MB』，因為 server 冇計 storage。 | 有 assets 先顯示；filter／search 後為空顯示 filtered-empty。 |
| Asset grid + card | 一眼睇晒；卡面只放真數據。 | `motion.figure` 沿用現有 variants；`TiltCard max=6` 只包圖（fine pointer 先啟用）。圖用 `AssetThumb`，loading `Skeleton aspect-square`；失敗顯示「Preview unavailable」+「Retry」（`queryClient.refetchQueries({ queryKey: ['media', w, id] })`）。Caption：`AnimatedBadge`「Used in N」或 outline「Unused」。Usage map：先遍歷 `jobs[].manifest.media[]`，再加 `reviews[]` 中 `manifest.idempotencyKey` 冇對應 job 嘅，以 `media.id === asset.id` 配對——**以 idempotencyKey 去重**，因為 approve 後 review 保留 'approved'（store.py:288-301）。第二行 `{width}×{height} · {formatBytes(bytes)}`。整張卡係 `button`（aria-label『Image {width}×{height}, used in N posts』）開 detail，關閉後 focus 返原卡；`ContextMenu`：Open · Use in a post（approve）· Copy hash · Delete…（edit）。Stagger `custom={Math.min(index, 8)}`，delay = i×0.035，spread ≤ 280ms。 | enter（stagger）/ layout shift（SPRING_LAYOUT）/ exit（刪除）/ thumb loading / thumb error / thumb 404（asset 冇 objectName）。 |
| Asset detail (Sheet / Drawer) | 講清楚 provenance，同埋帶去下一步。 | 頂：大圖（`AspectRatio ratio={width/height}` 內 `object-contain`，max-h 60vh）。Facts（`ui/table`）：Dimensions、Size、Format（'JPEG (re-encoded from your upload)'）、Stored hash（全 64 位 mono + `Icons.copy`）、Source hash、Decoder（asset.decoder）、Uploaded（有 `createdAt` 先顯示；有 `uploadedBy` 先顯示人，舊 asset 冇就成行唔出）。「Image rules」列：對每個 `state.phase2.channels` 一行 platform + 結果——只有有證據嘅規則先評（目前得 Instagram 比例 0.8–1.91，來源 `store.py:372-373`，寫『Instagram accepts 4:5 to 1.91:1』），其他平台寫「No image rule recorded for {platform}」，唔出 ✓。唔符合時係 reminder 文字，唔係錯誤態。「Used in」列：去重後每個 job/review 一行 platform · account · state（`AnimatedBadge`）· timing.local，link `/app/queue`；冇就「Not used in any post yet」。Actions：primary「Use in a post」（只 approve 權限；開 `ScheduleDialog` 帶 `assetId`，跟現有 `variantId` preselect 寫法）；冇 approve 但有 edit 時換成 link「Open drafts ›」→ `/app/ideas`；「Copy hash」；destructive「Delete…」（edit）→ 現有 `AlertDialog`。若有 IN_FLIGHT job 引用（鏡射 `store.py:19` 到 `web/src/features/library/asset-usage.ts`），Delete disabled + 說明「A post using this image is still being published or checked. Delete it once that post has settled.」（server 會拒絕，`hosted.py:237-238`，前端只係提早講）。 | open / closing（收快過開）/ deleting（按鈕 loading）/ delete refused（toast server 原文，sheet 唔關）。 |
| Empty state | 教識第一次嚟嘅人：收咩、會發生咩、圖之後去邊。 | 現有 `Empty`，加 `data-tour='library-empty'`。Title「No images yet」。Description：『Upload JPEG or PNG, up to 8 MB and 320–4096 px per side. Each image is fully decoded, stripped of metadata and stored with its hash. Attach it when you prepare a post from a draft.』Actions：edit 權限 primary「Upload images」（同 header handler）；secondary `learn-more-chevron`「Open drafts ›」→ `/app/ideas`。Viewer 版只有 description + 「Ask a workspace editor to add images.」。edit 權限時整區係 dropzone。 | 只喺 snapshot 已載入且未刪 assets.length === 0。 |
| Info sidebar | 邊界同限制，全部係真。 | Private by default（現有）；Provenance（現有）；What is accepted：『JPEG or PNG · up to 8 MB · 320–4096 px per side · re-encoded to JPEG with metadata removed · video is not accepted in this release』。刪走「Storage counts toward your plan allowance」。Plan storage：`useUsage()` 成功先加一句『Your plan includes {storageMb} MB of storage.』，失敗唔出（唔變 0）。 | 靜態 + usage 句子有／冇。 |

- **Empty state**：未刪 assets.length === 0：`Empty` + 教學文案 + Upload（edit）/ Open drafts，edit 時整區可拖放；viewer 版冇 Upload。Filter 後為空（例如 Unused 冇嘢）：細版 `Empty`「Every image is used in a post」+ `Button variant='ghost'`「Show all」。Search 冇結果：「No image matches “{q}”」+ Clear。
- **Loading**：snapshot.isLoading：一行 toolbar skeleton + 12 個 `Skeleton aspect-square rounded-lg`（ui/skeleton，transitions #14），冇文字。個別縮圖 loading 用 `Skeleton aspect-square`。上載中：按鈕文字讀真計數，grid 唔加 placeholder 卡（asset 未存在就唔畫）。
- **Error**：snapshot.isError：`ui/alert` destructive「Could not load the library」+ server 訊息 + Retry（refetch）。Storage 未配置：upload/delete/media 任一回 ApiError status 503（`hosted.py:936,950,959`）時，header 下顯示 `ui/alert`「Private media storage is not configured for this deployment」並 disable Upload；**唔讀 /api/health**（Health type 冇呢個欄）。縮圖 error：卡內「Preview unavailable · Retry」；404 就唔出 Retry。刪除拒絕：toast server 原文，卡留原位。上載 409：refetch snapshot 後重送該檔一次（會重新傳 bytes），仍失敗 toast server 原文「Workspace changed; reload.」並停 queue。403（非 owner guard 未修前）：toast 原文，唔扮成功。

### Motion moments

| Element | Trigger | Behaviour | Reuse | 讀真數據 |
|---|---|---|---|---|
| Grid 首次顯示 | snapshot 載入後 assets.length > 0 | opacity 0→1、scale .96→1，280ms EASE_OUT；delay = min(index,8)×35ms（spread ≤ 280ms）；reduced motion 唔播 | 現有 GRID_VARIANTS / ASSET_VARIANTS（library-view.tsx:44-48）改用 custom delay + EASE_OUT | 是 |
| 新上載嘅卡 | act onSuccess 後 snapshot 多咗一個 asset | 繼承 variants 自己 enter；其他卡 layout='position' + SPRING_LAYOUT 讓位（reduced 時 layout false） | 現有 motion.figure layout + SPRING_LAYOUT（lib/ease） | 是 |
| Upload 按鈕 | queue 開始／每檔完成／全部完成 | idle→loading（'Uploading 2 of 5…'）→success/error，useFlash 收返 | components/motion/button StatefulButton + hooks/use-flash | 是 |
| Toolbar 計數（All/Unused/Used、N images、X MB） | snapshot 變更 | 數字逐位滾動；reduced 時直接換 | components/motion/digit-swap DigitSwap | 是 |
| Filter tabs | 用戶切換 | segment pill 滑動；grid 用 AnimatePresence 換內容（exit 150ms、enter 250ms，收快過開） | components/motion/tabs（variant 'segment'，transitions #16） | 是 |
| 卡上 usage chip | 去重後 usage 由 0 變 N | badge 內容 crossfade | components/motion/animated-badge AnimatedBadge | 是 |
| Dropzone overlay | 真實 dragenter / dragleave / drop | 只郁 opacity：入 --duration-quick（150ms）、出 --duration-micro（80ms） | web/src/styles/transitions.css tokens；新 overlay 元素 | 是 |
| Detail sheet / drawer | 撳卡 / 關閉 | sheet 由右滑入，收快過開；reduced motion 退為純 opacity（唔用 blur）；mobile drawer 由底 | ui/sheet（transitions #07 panel reveal）、ui/drawer | 否（純裝飾） |
| 刪除確認 + 卡離場 | AlertDialog 確認後 act onSuccess | dialog #06；卡 opacity→0 scale .94 200ms（reduced 150ms opacity） | ui/alert-dialog + 現有 exit variants | 是 |
| Image tilt | hover / pointer move（fine pointer only） | max 6°；只包圖唔包 caption；reduced motion 停用 | components/motion/tilt-card TiltCard（glare prop 要先確認存在） | 否（純裝飾） |
| Copy hash | context menu / detail 按鈕 | Sonner toast | sonner（transitions #22） | 否（純裝飾） |
| Page enter | route 轉入 /app/library | content 浮入 | web/src/app/app/template.tsx:13 .t-page-enter（transitions #08） | 否（純裝飾） |

## 2. Technical requirements

| # | Item | Kind | 已有 | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | 讀 workspace snapshot 嘅 assets | api | 有 | web/src/lib/api/hooks.ts:39-42 useSnapshot → GET /api/workspaces/{id}（src/postriff_phase2/hosted_app.py:461-462 → hosted.py:124-127）；web/src/lib/api/types.ts:148 | S |
| 2 | 私有縮圖 GET /api/workspaces/{id}/media/{assetId} | api | 有 | src/postriff_phase2/hosted_app.py:435-438 → hosted.py:957-964 → hosted_storage.py:77-84；client web/src/lib/api/client.ts:139 | S |
| 3 | 上載／刪除 actions p2_media_upload / p2_media_delete | api | 有 | src/postriff_phase2/hosted_app.py:480-483 → hosted.py:934-955；decoder src/postriff_phase2/media.py:82-92 | S |
| 4 | 修正非 owner 上載／刪除被 403（editor/admin） | backend | 冇 | src/postriff_phase2/hosted.py:226,234,244 比較 state['membership']['userId']（auth.py:24 bootstrap 寫死創建者，src/postriff_phase2 冇其他寫入）；upload 已 require(edit)（hosted.py:939），delete 經 repository.command 預設 'edit'（:129）。Guard 改為只驗 asset 冇 'data'、id 未重複／存在。tests/test_postriff_phase2_hosted.py 冇非 owner case | S |
| 5 | Media 路徑補 sample workspace read-only 檢查 | backend | 冇 | sample 檢查只喺 hosted.py:188-189（HostedPhase2Commands.__call__）；upload_media/delete_media 經 add_asset/prepare_asset_delete（:942,:951）繞過 | S |
| 6 | Asset 記錄加 createdAt 同 uploadedBy（只用嚟顯示） | backend | 冇 | media.py:92 回傳冇時間／人；hosted_storage.py:119 只加 storagePath/objectName/execution。喺 add_asset（hosted.py:225-231，有 principal 同 self.clock）加；本地 store.py:254-255 同步加 createdAt；types.ts:42-51 加 optional sourceHash/decoder/createdAt/uploadedBy。排序唔依賴佢（array 已係 append 順序） | S |
| 7 | Newest／Oldest／Largest 排序 | frontend | 冇 | assets append-only（hosted.py:230、store.py:255）→ reverse array 即 Newest；bytes 喺 types.ts:49 | S |
| 8 | 真統計：N images、總 bytes；plan storage 另句顯示 | frontend | 冇 | bytes 喺每個 asset（types.ts:49）；storageMb 喺 useUsage()（hooks.ts:44-47、types.ts:495、billing.py:47）；server 未計 storage（billing.py:60 有 dimension 但 upload_media hosted.py:934-946 冇 reserve），所以唔可以寫『of Y MB』 | S |
| 9 | 多檔上載 queue（逐個真請求、revision 串聯） | frontend | 冇 | web/src/features/library/library-view.tsx:155 accept image/*、:159 只取 files?.[0]；useAct（hooks.ts:150-162）onSuccess 回傳 snapshot.revision 可串下一個 | S |
| 10 | 拖放上載 | frontend | 冇 | react-dropzone ^14.4.1（web/package.json:52），已用於 web/src/components/file-uploader.tsx:6；Library 未用 | S |
| 11 | Usage map（去重後邊個 job/review 用咗邊張圖）+ inFlight | frontend | 冇 | types.ts:64 Manifest.media[]、Job 71-82、Review 84-89；approve 後 review 保留 'approved' 且同 job 共用 manifest（store.py:288-301），要以 manifest.idempotencyKey（types.ts Manifest）去重；IN_FLIGHT 鏡射 store.py:19 | S |
| 12 | 平台圖片規則表（只放有證據嘅） | frontend | 冇 | 只有 Instagram 比例規則喺 src/postriff_phase2/store.py:372-373；web 未有 image 規則。新檔 web/src/features/library/image-rules.ts，冇規則嘅平台顯示 'No image rule recorded' | S |
| 13 | ScheduleDialog 接受預選 assetId | frontend | 冇 | web/src/features/queue/schedule-dialog.tsx:55 useState('')；已有 variantId preselect pattern（:37,:54）可照抄；Select 喺 :192-205 | S |
| 14 | 『Use in a post』按 approve 權限 gate | frontend | 冇 | p2_review 歸類 'approve'（src/postriff_phase2/permissions.py:28）；前端鏡射 web/src/lib/auth/permissions.ts，checkAccess 喺 web/src/lib/auth/access.tsx:69 | S |
| 15 | 共用 AssetPicker（縮圖 grid popover）取代兩處 hash Select | frontend | 冇 | web/src/features/queue/schedule-dialog.tsx:192-205、web/src/features/agent/plan-card.tsx:329-340 都用 hash 文字 Select；縮圖 key ['media', w, id]（use-preview-post.ts:25） | M |
| 16 | Sheet / Drawer / Table / Alert / Empty / AspectRatio primitives + motion Tabs/DigitSwap/AnimatedBadge | frontend | 有 | web/src/components/ui/{sheet,drawer,table,alert,empty,aspect-ratio}.tsx；web/src/components/motion/tabs.tsx:18（segment）、digit-swap.tsx:48、animated-badge.tsx:109 | S |
| 17 | Library page tips 註冊入 tour 系統 + data-tour ids | frontend | 冇 | tour 系統存在：web/src/features/onboarding/tours.ts PAGE_TOURS（:156）、TourCtx（:14-24）、help-menu.tsx:37；Library 未有條目、library-view.tsx 冇 data-tour；TourCtx 要加 assetCount | S |
| 18 | Conversation 內由 Library attach 圖（P2） | api | 有 | API 存在：src/postriff_phase2/ideas.py:208-229（kind 'asset' :218-222）、web/src/lib/api/client.ts:195；UI 缺：web/src 冇 api.attach 呼叫 | M |
| 19 | Server-side storage 用量入 ledger（P2） | backend | 冇 | billing.py:60 已接受 dimension 'storage'，upload_media（hosted.py:934）冇 reserve/settle | M |
| 20 | Library 頁 web 測試 + 三個寬度截圖 | infra | 冇 | tests/test_postriff_consumer_web.py 冇 Library 測試；截圖流程見 memory reference-hidden-pane-screenshots | S |
| 21 | Object URL 回收 | frontend | 冇 | library-view.tsx:63 同 use-preview-post.ts:26 createObjectURL 後冇 revokeObjectURL，staleTime Infinity；抽共用 useMediaUrl hook，用 queryClient.getQueryCache().subscribe 監聽 'removed' revoke，並設 gcTime | S |

## 3. Features

### P0

- **Editor／admin 都可以上載同刪除（修 owner-only guard）**：`hosted.py:226/234/244` 用 bootstrap 寫死嘅創建者 id 做 guard，有 edit 權嘅隊員都會食 403，Library 對 team workspace 等於壞咗。Guard 改為只驗資料；權限交返 `require(edit)`（已存在）。加非 owner 上載測試。
- **Media 路徑補 sample read-only 檢查**：sample 檢查只喺 `hosted.py:188`，media endpoint 繞過；前端 disabled 之前 server 要先真係擋，唔好 UI 講一樣 server 做另一樣。
- **多檔 + 拖放上載，進度係真計數**：單檔 picker 係最慢路徑；react-dropzone 已裝。每檔一個真請求，按鈕讀「Uploading 2 of 5…」，失敗檔逐個 toast server 原文，唔扮進度條。
- **Newest first 排序**：Array 最舊喺頭，新上載嘅圖落喺 grid 最底。Assets 係 append-only，反轉就係真實上載次序，唔使等 backend。
- **Used / Unused filter + 卡上 usage chip（去重）**：Later 嘅 Side Library 可以 filter unused media（https://help.later.com/hc/en-us/articles/360043244573-Managing-Your-Media-from-the-Side-Library），因為最常問係「呢張用過未」。PostRiff manifest 已綁 media id + hash（store.py:374），由 snapshot 計、以 idempotencyKey 去重，唔使加 API。
- **Asset detail sheet：provenance + Used in + 下一步**：Hash 係 provenance 承諾，但卡面得 10 字符冇解釋。Detail 顯示 stored/source hash、decoder、dimensions，列出用咗呢張圖嘅 post 連去 Queue；approve 權限有『Use in a post』，editor 有『Open drafts』。刪除搬入呢度。（depends on：ScheduleDialog 預選 assetId；approve 權限 gate）
- **誠實統計 + 修正 info sidebar 文案**：House rule 1。「Storage counts toward your plan allowance」冇數據支持。改為真 client sum，plan storage 另句『Your plan includes Y MB』，query 失敗唔出，永遠唔出 0，亦唔暗示有計量。

### P1

- **Asset 加 createdAt / uploadedBy**：Detail 可以誠實顯示『Uploaded {時間} by {人}』；舊 asset 冇就唔出嗰行。排序唔依賴佢。（depends on：backend add_asset 改動）
- **共用 AssetPicker（縮圖 grid）取代 schedule-dialog 同 plan-card 嘅 hash Select**：而家揀圖係揀「image/jpeg · 3f9a1c2b…」，人眼睇唔出係邊張。Picker 同 Library 共用 ['media', w, id] cache，唔會重覆下載。
- **Image rules（每個已連 channel，只講有證據嘅）**：Buffer 嘅 help page 顯示每個 network 圖片限制唔同（https://support.buffer.com/article/615-attaching-images-videos-and-other-media-to-your-posts）。PostRiff 只有 Instagram 4:5–1.91:1 一條 server 規則（store.py:372-373），其他平台寫「No image rule recorded」，唔出混合 ✓；唔符合只係 reminder。
- **Search + skeleton grid + 縮圖 Retry + Library page tips**：完整頁嘅底線：loading 唔應該係一舊方塊；縮圖失敗要有 retry；tour 系統已存在，Library 應該有自己嘅 tips。

### P2

- **由 Library attach 圖入 conversation**：API 已存在（ideas.py:208-229）但冇 UI；AssetPicker 做好後接 composer。未有證據顯示要先做，所以 P2。（depends on：AssetPicker）
- **Server-side storage 計量入 ledger**：有咗先可以誠實顯示「X of Y MB」；billing.py:60 已有 dimension 'storage'。
- **Server-side 縮圖 rendition**：每張卡 fetch 原圖（最大 4096px JPEG），手機好重。要改 storage object 規則（hosted_storage.py:19 OBJECT regex），所以推後；之前用 lazy 延遲 fetch。

## 4. Onboarding／tutorial

**第一次入嚟要明嘅嘢**：5 秒內要明：呢度係 workspace 私有嘅圖片庫；上載 → decode、去 metadata、記 hash → 準備 post 時揀佢；呢頁唔會發佈任何嘢。教法：pageDescription 改為『Images for your posts. Private to this workspace; each one is stored with its hash and attached when you prepare a post.』；空狀態直接寫收咩、發生咩、去邊用；有圖時「Unused / Used in N」chip 本身就係教學。Tips 註冊喺 `web/src/features/onboarding/tours.ts` PAGE_TOURS（id 'library-tips'、route '/app/library'、stop 'Library'），由 help menu 開。所有文案通用，唔提任何品牌或行業。

| Step | Target | Title | Text |
|---|---|---|---|
| 1 | `['[data-tour="library-upload"]', '[data-tour="library-empty"]', ...heading('library')]（header StatefulButton 加 data-tour='library-upload'；when: ctx.canEdit）` | Upload images | JPEG or PNG, up to 8 MB and 320–4096 px per side. Drop files on this page or pick several at once. Each image is fully decoded and its metadata removed before it is stored. |
| 2 | `['[data-tour="library-stats"]']（toolbar 統計 span，要新加；when: assetCount > 0）` | Counts from your workspace | The number of images and their total size come from this workspace. Deleted images are not counted. |
| 3 | `['[data-tour="library-filter"]']（motion Tabs root，要新加；when: assetCount > 0）` | Used or unused | Every prepared or scheduled post records exactly which image it uses. Filter to the ones you have not used yet. |
| 4 | `['[data-tour="library-card"]']（grid 第一張卡，要新加；when: assetCount > 0）` | Open an image | See its stored hash, source hash and which posts use it. From here you can copy the hash, prepare a post if you have permission, or delete it. |
| 5 | `['a[href="/app/queue"]']（sidebar 現有連結）` | Where images get attached | Images are attached when a post is prepared from a draft. That step freezes the text, image hash, account and time; approving it in the Queue is what schedules the post. |

**Empty state 教咩**：三件事：(1) 收咩——JPEG／PNG、≤8 MB、320–4096 px，唔收 video；(2) 上載後會發生咩——full decode、去 metadata、記 hash、私有儲存；(3) 圖去邊用——由 draft 準備 post 時 attach，link 去 /app/ideas。Viewer 版講明要 editor 加圖。文案通用（設計師、老師、店主、developer 讀落一樣）。edit 權限時整區可拖放。

## 5. Next steps（按次序）

1. **Backend：add_asset / prepare_asset_delete / finish_asset_delete 刪走 state['membership'] guard（只驗 asset 冇 'data'、id 未重複／存在、deletionPending），權限交 require(edit)；三個 method 補 `state.get('workspace',{}).get('sample')` → 403；add_asset 加 createdAt（self.clock()）同 uploadedBy（principal）；store.py media_upload 同步加 createdAt。測試：editor 上載／刪除成功、viewer 403、sample 403、createdAt 存在。**（effort S）  
   檔案：`src/postriff_phase2/hosted.py:225-252,934-955; src/postriff_phase2/store.py:254-255; tests/test_postriff_phase2_hosted.py; tests/test_postriff_phase2.py`
2. **Types + 資料 hook：Asset 加 sourceHash?/decoder?/createdAt?/uploadedBy?；新 `use-library.ts` 由 snapshot 派生 sorted assets（reverse = Newest）、去重 usage map（jobs 先、reviews 以 idempotencyKey 補）、per-asset inFlight、totals；`asset-usage.ts` 鏡射 IN_FLIGHT；`image-rules.ts` 只放 Instagram 比例 + 來源註解；共用 `useMediaUrl`（revoke object URL）。**（effort S）  
   檔案：`web/src/lib/api/types.ts:42-51; web/src/features/library/use-library.ts (new); web/src/features/library/asset-usage.ts (new); web/src/features/library/image-rules.ts (new); web/src/components/application/post-preview/use-preview-post.ts:25-27`
3. **拆 library-view：`library-view.tsx`（shell、toolbar、dropzone、dialogs、權限三層）、`asset-card.tsx`（TiltCard + chip + context menu，stagger 上限 8）、`asset-detail.tsx`（Sheet ≥768 / Drawer <768）、`upload-queue.ts`（多檔逐個 act、revision 串聯、真計數、409 重送一次）。改 accept、info sidebar、空狀態文案（含 viewer 版）、skeleton grid、縮圖 Retry、503 alert。加 data-tour ids。**（effort M）  
   檔案：`web/src/features/library/library-view.tsx; web/src/features/library/asset-card.tsx (new); web/src/features/library/asset-detail.tsx (new); web/src/features/library/upload-queue.ts (new)`
4. **ScheduleDialog 加 `assetId?: string` prop（跟現有 variantId preselect 寫法做初始值）；detail 嘅「Use in a post」用 checkAccess approve gate 後開佢。**（effort S）  
   檔案：`web/src/features/queue/schedule-dialog.tsx:37,54-55,192-205; web/src/features/library/asset-detail.tsx`
5. **註冊 Library page tips：tours.ts PAGE_TOURS 加 'library-tips'，TourCtx 加 assetCount（喺 use-tour-context.ts 由 snapshot 計）。**（effort S）  
   檔案：`web/src/features/onboarding/tours.ts:14-24,156; web/src/features/onboarding/use-tour-context.ts`
6. **共用 AssetPicker：`components/application/asset-picker.tsx`（Popover + 縮圖 grid + 'No image'，用 useMediaUrl），取代 schedule-dialog 同 plan-card 嘅 Select；plan-card 冇圖時保留連去 /app/library。**（effort M）  
   檔案：`web/src/components/application/asset-picker.tsx (new); web/src/features/queue/schedule-dialog.tsx:192-205; web/src/features/agent/plan-card.tsx:327-351`
7. **驗證：npx tsc --noEmit、npm run lint；web 測試加 Library case（空狀態文案、viewer 冇 Upload、上載後卡出現、usage 唔雙計）；hidden-pane 截圖 375/768/1440 light+dark（用自己嘅 tab，唔撳 approve/schedule/send）。**（effort S）  
   檔案：`tests/test_postriff_consumer_web.py; web/`
8. **更新 motion inventory 嘅 Library 一行（DigitSwap、Tabs segment、AnimatedBadge、Sheet、dropzone overlay）同 §6 已知限制。**（effort S）  
   檔案：`docs/postriff-motion-system.md:45, §6`

## Risks

- Owner-only guard 係靜態推斷（PLAUSIBLE）：要用 editor principal 走一次 upload_media／delete_media 先確認；修改時唔可以放鬆 require(edit)。
- Usage 雙計：approve 後 review 同 job 共用 manifest（store.py:288-301），唔去重『Used in N』就係假數。
- 權限錯配：『Use in a post』= p2_review = approve；editor 可以上載但唔可以準備 post，UI 要分開 gate，唔好撳完先 403。
- 並行 session 規則（memory：avoid web/src、shared tree stage by path）：spec 會改 schedule-dialog.tsx、plan-card.tsx、tours.ts，同其他 session 有衝突風險；先做 backend + features/library，picker 換入兩個 dialog 留最後，commit 按路徑 stage。
- Stagger 規則：現有 staggerChildren 0.035 乘全部卡（library-view.tsx:44），24 張就 840ms；必須 cap 首 8 張。
- createObjectURL 從不 revoke（library-view.tsx:63、use-preview-post.ts:26）+ staleTime Infinity：大庫長開會食記憶體。
- 縮圖即原圖（最大 4096px JPEG）：冇 rendition 之前用 loading='lazy' / IntersectionObserver 延遲 fetch，唔可以扮縮圖。
- Plan storage：storageMb 只係 plan 數字，server 唔計唔 enforce；文案用『includes』，唔用『of』或『limit』。
- 刪除兩段式（hosted.py:948-955）：storage delete 成功但 finish 失敗會留低 deleted=true + deletionPending=true；前端已 filter deleted，但冇重試入口，manifest 仍指住個 hash，Used in 照計。
- Base64 上載 8 MiB → ≈11.18 MB JSON，body 上限 12,000,000（hosted_app.py:198）；queue 一定逐個送；409 重送會重新傳 bytes，只重送一次。
- Video 不支援（media.py:60 訊息）：accept 只寫 image/jpeg,image/png，空狀態同 sidebar 明講，避免人試 HEIC/WebP。
- i18n：app UI 字串目前得英文；worldwide languages Stage 1 係 post locale，唔係 UI 翻譯。Library 字串集中喺一個 copy 物件，日後翻譯唔使拆 component；alt text 語言屬 review 時嘅 channel locale。

## 覆核記錄

- 改正：GET /api/workspaces/{id} 喺 hosted_app.py:451-453 → hosted.py:113 → 改為 hosted_app.py:461-462、hosted.py:124-127。
- 改正：types.ts:146 assets；Asset type 42-51；Entitlement.storageMb types.ts:488 → 改為 types.ts:148、:64、:71-82、:84-89、:495。
- 改正：縮圖 route hosted_app.py:431-434 → hosted.py:891-898；client.ts:137 media → 改為 hosted_app.py:435-438、hosted.py:957-964、client.ts:139。
- 改正：use-preview-post.ts:24-26 用同一個 ['media', w, id] key → 改為 :25-27。
- 改正：上載：hosted_app.py:476-477 → hosted.py:868-880、require(edit) :873、stage_upload hosted_storage.py:110-117、rollback :876-879 → 全部行號更新。
- 改正：刪除兩段式 hosted.py:882-889；in-flight 拒絕 hosted.py:223-224；IN_FLIGHT store.py:19 → 更新行號。
- 改正：tests/test_postriff_phase2_hosted.py:117 只測 routing → 描述改為『只測 command engine 擋 media shortcut，冇非 owner 上載測試』。
- 改正：Sample workspace 上載會喺 hosted.py:174 食 403，所以按鈕要 disabled → Backend 要喺 add_asset/prepare_asset_delete 補 sample 檢查；前端 disabled 係提示，唔係鏡射現有 server 行為。
- 改正：schedule-dialog.tsx:48,192-204 用 Select；:54 useState('') 冇 prop → 改 :49、:55、:192-205，並註明跟 variantId prop pattern。
- 改正：ideas.py:210-226 有 asset attachment API；client.ts:190-191 api.attach；features/agent 冇 UI 呼叫 → client.ts 行號改 :195。
- 改正：Tour 系統喺 repo 未存在（grep 冇 data-tour／tour） → tour 改為喺 PAGE_TOURS 加 'library-tips'，target 用 string[] fallback，並喺 TourCtx 加 assetCount。
- 改正：冇 createdAt 就冇得誠實地排 Newest first → Newest/Oldest 而家就可以做（reverse array）；createdAt/uploadedBy 只用嚟顯示『Uploaded』行，降為 P1。
- 改正：Usage map = 遍歷 reviews[].manifest.media + jobs[].manifest.media → 以 manifest.idempotencyKey 去重：先計 jobs，再計冇對應 job 嘅 reviews（排除 stale？保留但標 state）。
- 改正：Detail『Use in a post』→ 開 ScheduleDialog，editor 都用得 → 按鈕以 checkAccess(access,{permission:'approve'}) gate；冇權限時改顯示『Open drafts』連結，唔阻上載。
- 改正：可由 /api/health 知 storage 503 → 由第一個 media GET 或 upload 回 503 推斷，唔好話讀 health。
- 改正：Dropzone motion 用 transitions.css --dur-fast → 入 --duration-quick（150ms）、出 --duration-micro（80ms）。
- 改正：House rules 文件路徑 web/src/lib/auth/access.ts → 引用 access.tsx。
- 違反原則（已改）：House rule 1（誠實數字）：toolbar『X MB of Y MB』將 client 自己加出嚟、server 從未計量嘅 bytes 同 plan 嘅 storageMb 並排，暗示有計量／配額追蹤。改為分開兩句：『{n} images · {X MB}』同 info 內『Your plan includes {Y} MB』（usage query 成功先出）。
- 違反原則（已改）：House rule 1：Usage map 由 reviews + jobs 直接加總會雙計（approve 後 review 仍然 'approved'，store.py:301），『Used in 2』會係假數。要用 manifest.idempotencyKey 去重。
- 違反原則（已改）：House rule 1：error_state 話由 /api/health 得知 storage 503，但 Health type 冇呢個欄位；顯示一個讀唔到嘅狀態等於扮。
- 違反原則（已改）：House rule 1 / capability honesty：『Sample workspace 上載 403（hosted.py:174）』同『server 一樣會拒絕』描述咗 server 未有嘅行為；media 路徑冇 sample 檢查。
- 違反原則（已改）：Motion rule 4：dropzone 引用唔存在嘅 --dur-fast token；detail sheet 嘅 cross-blur 唔係 transform/opacity，reduced-motion 下要退為純 opacity。
- 違反原則（已改）：RBAC honesty：『Use in a post』開 ScheduleDialog（p2_review = approve）卻冇 gate approve 權限，editor 撳落去先食 403，屬『撳完先話唔得』。
- 違反原則（已改）：General-not-personal：tour 文案本身通用，冇違規；但 tour 要註冊落 features/onboarding/tours.ts（該檔 :6-8 已寫明 copy rules），唔好另起一套。
- 補上遺漏：RBAC 全表：nav-config.ts:50-55 Library 冇 access key，viewer/approver 都入到；要講明 read（睇、Copy hash、Open）、edit（上載、刪除，hosted.py:939）、approve（Use in a post → p2_review，permissions.py:28）三層，ContextMenu 同 detail actions 逐項 gate。
- 補上遺漏：Sample workspace 喺 media 路徑冇 server 檢查（hosted.py:188 只喺 __call__）→ backend 要補，唔係只靠前端 disabled。
- 補上遺漏：現有 onboarding tour 系統（features/onboarding/tours.ts PAGE_TOURS、TourCtx、help-menu pageTourFor），spec 誤以為冇。
- 補上遺漏：Legacy／local execution 嘅 asset 冇 objectName → media GET 404（hosted.py:962-963）；storage 未配置時每張縮圖都 503，頁面級 alert 應由縮圖 query error status 推斷。
- 補上遺漏：deletionPending 殘留記錄（deleted=true, deletionPending=true）冇重試 finish 嘅入口，亦冇 UI 提示。
- 補上遺漏：Mobile：ContextMenu 喺 touch 要長按；TiltCard 喺 coarse pointer 應停用；detail drawer 要有明確 Close。
- 補上遺漏：鍵盤／a11y：卡變 button 後 Enter 開 detail、Shift+F10 開 context menu、focus 回到原卡。
- 補上遺漏：i18n／languages：app 介面目前只有英文字串，worldwide-languages Stage 1 係 per-channel post locale，唔係 UI 翻譯；Library 字串集中喺一個 copy 物件，alt text 語言屬 review 時嘅 channel locale，唔係 asset 屬性。
- 補上遺漏：ScheduleDialog 已有 variantId preselect pattern（schedule-dialog.tsx:37,54），preselectedAssetId 應照抄同一寫法。
- 補上遺漏：現有 input accept='image/*'（library-view.tsx:155）要收窄為 image/jpeg,image/png。
- 補上遺漏：409 自動重送：upload_media 已 stage bytes 再 command，失敗會 remove（hosted.py:941-945），重送會重新上載 8 MB，要限一次並講明。
