# PostRiff：先證明每週價值，再擴大功能

決策時間：2026-09-14 America/Indiana/Indianapolis（部分驗證為 2026-09-15 UTC）。狀態：**本地安全修復 + 可審核產品／商業候選；未部署、未收款、未招募、未證明盈利。**

## 一、決策摘要

首要 ICP：**自己使用及付款、每週已有教材／公開長文，需為自己專業品牌寫英文 LinkedIn 文字帖的獨立知識教育者**。以過去四週每週至少一次創作、已有素材、親自審稿作篩選；「教育者」不等於全部 YouTuber。次要：同樣以公開長文／演講建立個人專業品牌的獨立顧問／創辦人。最優細分仍未知。

候選承諾：「協助每週分享專業知識的獨立教育者，把自己有權使用的教材片段與長文整理成可審核的英文 LinkedIn 帖文，保留其表達方式，並減少需要重寫及核對的時間。」**未測量前不宣稱已節省 30%。**

最重要三項決策：

1. **先封住審批與不確定發布的可重現缺口。** 本輪已實作來源／brief 與平台帳號綁定、批准人再檢查、唯讀角色限制、取消競態及對帳狀態限制；細節與測試在 [RECEIPT](RECEIPT.md)。
2. **首稿先行，一份素材、一種用途、一份可用成品。** 下一批 P1 將複雜 profile、Agent、技能及第二平台版本後置；現有 Phase 2 可在零社交連接下完成單稿編輯、記憶選擇及私人 ZIP 匯出，但不是已驗證的真實 AI 首稿。
3. **以四週行為與全成本決定投入。** 候選主力 $39／月，先驗證每月 8 個文字批次（每批一份主要內容，最多一次有界修訂）的價值／成本。它不是原報告 100 請求方案的直接改價，也尚未改任何訂閱。$19 不含客製 CLI 排障；$79 及多品牌團隊承諾延後。

保留：來源定位、編輯歷史、用戶確認記憶、可攜匯出、既有 React/Python/SQLite/Postgres。延後：多 Agent 消費級安裝、自動全平台發布、無限圖片／影片、全面多語言、技能商店與多人企業銷售。已有功能不因本報告被刪除。

## 二、證據分級與工作樹

- **V：本次驗證**：目前代碼、重新執行的測試、PDF 原文。這只能證明本地行為／文件存在。
- **R：報告模擬**：33 頁 PDF 中的虛擬角色、種子及計算，不是真實訪談或付費。
- **E：外部資料**：官方頁面，URL 與查閱日期列下。
- **P：提議／推論**：包括 ICP、目標、工時與模型；可被新證據推翻。
- **U：未知**：實際 MRR、客戶、跑道、每週可投入工時、供應商合約／地域授權、正式環境當前狀態。

指定暫存目錄為 symlink，實際代碼在 `/Users/ouxianxing/Documents/James-Au-Studio`。根及適用父目錄未找到額外 AGENTS.md；沿用本任務提供的規則。這是安裝 source tree，沒有 `.git`；`git status`／歷史 diff 為 `validation_unavailable`。不初始化 Git、不使用舊的 b1f5 checkout 代替目前產品。修改前保存明確檔案備份與 SHA-256。Phase 3 同時有其他編輯，故本輪不改其 runtime 或 UI。

PDF 可讀，SHA-256 與頁数記錄於 [baseline](evidence/baseline.json)。已閱讀 pp1–33，使用同目錄 HTML 交叉核對金融表。原始 seed 未在報告目錄、目前 docs/scripts 有限搜尋中取得：`source_unavailable`。未大範圍搜尋私人資料、信箱、社交私訊或實際內容資料庫。

## 三、有範圍的現況與差距

工時、每月维护均為 P 估算；高／中／低表示對問題機制的信心，非 ROI。P0 為高風險能力啟用前紅線，不代表發生過事故。

| 報告風險／頁 | 本次現況證據 V | 影響／優先 | 候選改動、驗收 | 信心；工時；维护/月；依賴 |
|---|---|---|---|---|
| 來源更改仍被使用 pp9,29 | `domain.py approve_source` 更改 brief；原 `p2_variant_review` 未核對 brief，回歸可重現舊稿再獲核對 | P0 審批內容可能不再獲來源授權 | **已修** briefRevision/sourceDigest、workspace/brand/providerAccountId/scopes 檢查；撤回批准後必須重新生成／審稿 | 高；4–6h；0.5h；共享 Phase 2 引擎 |
| 審批人／品牌授權 pp25,29 | 本地 mutate 原未驗 role；worker 原未再查 Membership；hosted HTTP 已限制 owner/editor | P0 權限撤銷後仍可能提交 | **已修** local role、兩 worker claim 前讀真實 membership；不信 state 裡的 role | 高；3–5h；0.5h；Postgres membership |
| API 結果未知 pp24–25 | 有 lease/uncertain，但 adapter 可回 scheduled；synthetic 測試重現 2 次 submit | P0 重複發布／錯誤收據 | **已修** shared outcome validator、未知只對帳、取消+429不重送、异常遮罩 | 高；4–6h；1h；本地/PG回歸 |
| 初稿前設定 pp15–18 | UI `FounderApp.tsx` step0–6；新用戶先 mode/profile/source/runtime，再 variants；domain 最短樣本路径首稿需9條 command，另有帳號動作 | P1 激活過重；時間尚未測 | 候選 source-first；一份內容可保存／copy；可選樣式，系統預設 route；使用者判有用 | 高代碼／低轉換；12–20h；1h；安全上下文與有界模型 |
| AI 能力與模擬混淆 pp10,24 | alpha generation 為 FixtureAdapter；Phase3 fixture 可用，其餘需 permit、資格与成本授權 | P1 核心付費價值未實測 | 保持 fail-closed；完成真實文字 route 的來源政策與成本上限後，才執行明確授權小額評估 | 高；8–16h；2h；供應商合約／授權 |
| 資料政策／個人轉公司 pp11–12,29 | source 只有 active/private-local；profile 有 public/workspace_only/private/local_only/excluded 欄位；非四類來源執行政策 | P0 **真實模型啟用前阻斷**；local_only 標籤不能保證 hosted 不上傳 | [SPEC](SPEC.md) 的 sourcePolicy+egress policy，統一 context builder；本輪末並行Phase3已新增cloudVoiceRevision/provider_allowed同意；仍需四類policy及field privacy一致執行 | 高；12–20h；1–2h；跨 alpha/phase3，避免並行覆寫 |
| 可糾正記憶 pp26–28 | `preference` remember/post-only/reject/undo/delete；一次任意 edit 就提出 shortOpenings；有版本但來源類型及确认者未完整正規化 | P1 可能學錯偏好 | 建議顯示前後差異與提出原因；分寫作偏好／公司事實；允許修訂建議；採用/撤回後再生成測試 | 高；8–12h；1h；schema版本 |
| 審核與發布 pp29–31 | manifests/jobs/attempts 狀態分離；local adapter 全 synthetic；hosted `DisabledHostedSocial` 預設 held | 已有防線；P1 real adapter qualification | 初期保留 export；只有確實需求才做一條 LinkedIn 文字 path，不能以其本地測試宣稱可發布 | 高；12–24h；2–4h；scope、平台實測授權 |
| 背景恢復 pp24–25 | SQLite durable JSON aggregate，CAS；PG lock/lease/fencing；最多3提交，5次對帳後每日查；無 production cadence 證據 | P1 排程可靠性／運維 | 待 live path 加 jitter/dead-letter/SLO；限定批次、公平取件；未知人工處置 | 高；6–12h；1h；真實 provider semantics |
| OAuth pp24 | Phase2 configured/identityVerified/capabilityVerified/expiresAt/scopes；畫面會在 fixture 顯 Ready；CLI存在獨立於資格 | P1 容易過度聲稱 | UI 顯示 synthetic／身份／scope／token／讀取／發布分層；單純 reconnect 不解除舊批准 | 高；4–8h；1h；一條route |
| 付款／試用 pp16–21 | 14天/10 writing trial、idempotent fixture sign-in；PLANS為候選，未有 live billing webhook/退款/取消實作或交易資料 | P1 收款與用量可信度 | 不開放自動收款；UsageLedger+webhook unique鍵+取消退款狀態規格；驗證後才接付款 | 高；12–20h；1–2h；processor/jurisdiction授權 |
| 成本與客服 pp17–21 | writingUsed/artworkUsed counters、Phase3 token usage，但無完整 USD帳本/客服分鐘；預覽更新計量仍需涵蓋 | P1 無法判貢獻／全局濫用 | reserve/settle/release，失敗供應商成本另記；租戶和全局停止線；本輪模型已交付 | 高；10–16h；1h；最小模型路徑 |
| 隔離／刪除 pp12,27 | hosted membership+RLS+private storage；每 workspace一brand aggregate；retract清原文/facts但舊variant revision留存，私人export含全state | P0 客戶資料全面上傳前需補；不等於跨租戶已洩漏 | 撤回與删除分開；派生圖級聯、tombstone、備份重放；來源來源歷史可見刪除說明 | 高；12–20h；2h；資料保留政策 |
| 留存與獲客 pp29–33 | Phase0 evidence matrix：0/5完整訪談；6個公開prospect文件，0聯絡；未验证可觸達或ICP資格；無真實付款 | P1 最大商業未知 | 招募素材、管道表及四週試點；以相同分母記錄全部成功／退出 | 高文件／低市場；每週6–10h；持續；發送另授權 |
| 擴張 | 多模式、多平台、桌面／多Agent已累積相當範圍 | P2 維護負擔先於需求 | 在留存/貢獻/容量門檻前不新擴平台；現有路徑不承諾商業SLA | 中；每週取捨；按實際票量；前述門檻 |

### 回滾、取消與決策管理

本輪安全修復回滾只還原 receipt 列明的 source diff；不要還原整个文件夾或其他 Phase3改動。新增 manifest 欄位使舊待提交批准進入 held，需新 review；已提交／未知仍只對帳。此保守相容性是有意設計。

候選 source-first 若5次可用性測試仍需高客服才能理解，先縮減欄位／任務；記憶若無增量價值，停止自動提議，只保留手動偏好；一條 connector 若30天內不解決已觀察的阻斷，保持 export；成本帳本是 paid route 前置，不因低使用量取消。Business 在未有至少3家重複使用、可分離角色需求的實際個案前取消銷售推進。新依賴不因功能數量增加而採購。

### 候選逐項退出設計

以下不新增授權或承諾工時；按上表估算排入 ROADMAP，先處理相依紅線。

| 候選 | 回滾／降級方式 | 何時取消或收窄 |
|---|---|---|
| Source-first 首稿 | feature flag回舊流程；保留新建草稿及CAS版本 | 5次可用性測試仍需高客服：先縮成貼文字+單稿，不繼續多格式 |
| Context來源與個人／公司隔離 | 禁用真實模型外送；私人保存與匯出仍可用；不放寬舊資料預設 | 不取消安全邊界；無法完成時取消cloud route上線 |
| 記憶提議及資料模型 | 只保留手動偏好；候選不進active；migration採additive | 4週配對任務無可觀察返工改善，停止自動提議擴張 |
| 刪除／撤回 | 停相關檢索及外送；備份恢復前重放tombstone | 不取消刪除責任；超出能力則限制可上傳類型及留存 |
| 一條真實connector與OAuth狀態 | 關dispatch，保留unknown對帳、草稿及export | 30天未解決真實阻斷、scope或查證不可用，延後整合 |
| worker告警／重試運維 | pause新提交，保留持久intent及人工查證 | 不取消已有任務追查；无真實發布需求時不建新供應商隊列 |
| 成本帳本／billing | 停新paid generation，保存export；不自動撤銷已收款權益 | 無真實付費需求則延後收款整合；啟用前不能略過帳本 |
| 激活事件／4週試點 | 停新招募，保留去識別分母與退出紀錄 | 無重複使用先換任務；有使用無付費再測價值；成本負貢獻先縮scope |
| 多平台／團隊／媒體擴張 | 維持單語言文字export產品 | 未有留存、正貢獻、可接受CAC及工時容量就不啟動 |

## 四、最多三個相鄰市場

以下全部是 P 主觀相對評估；沒有把模擬台詞算成訪談。高/中/低無加權分數。

| 維度 | 教育／知識創作者（首要） | 專業顧問／創辦人（次要） | 固定內容需求小企業（延後） |
|---|---|---|---|
| 痛點頻率／素材 | 高：已有每週教材／長文；篩選可驗 | 中高：案例／演講，但素材可能涉客戶保密 | 高但資料碎片、圖片促銷多 |
| 付款能力 | 中，收入與規模差異大 | 中高，需證明時間/商機價值 | 中，採購者與作者未必同一人 |
| 接觸與採購 | 公開教學內容能識別；實際可觸達未知；候選1–2週 | 公開專業文章／介紹；候選1–3週 | 管理者多步決定；候選2–6週 |
| 客服／整合 | 文字export可完成主要任務，低至中 | 需要事實、個人/公司隔離，中 | 多人審批、媒體、排程與回應承諾，高 |
| 合規／資料風險 | 自有非敏感教材低至中；學生資料先排除 | 客戶案例、商業機密中高 | 客戶資料、員工權限高 |
| 切換理由／不買 | 反覆改AI腔；若通用AI已足夠就不買 | 時间高價值；若不能保密／需代營運就不買 | 要可靠批准；功能不成熟就不買 |

首要的使用者與付款者同為獨立教育者；每週任務是取一個已存在的觀點成為1–2篇專業短帖。目前怎樣完成尚待近期真實任務核實，候選對照為手工或通用AI加人工貼上。不是假設每人都使用同一競品。「為何現在換」要以近期每週返工和現在工具支出證明，沒有觸發就不催買。

改選條件：同一招募品質、至少各5個成熟四週觀察中，顧問群有更高有用內容重複使用、實際付費保留，且每客客服不更高；先增加下一輪5人樣本，不以小差距宣布勝出。若首要群根本不使用 LinkedIn，先調整一個用途/平台，不擴成所有創作者。

當前不服務：低頻無來源、代寫無需審稿、學生個資、金融/醫療個別建議、無限媒體生成、無批准代發、客製多Agent排障、多家公司共用個人資料。多語言為之後分層測試特徵，沒有實際品質/需求前不作核心優勢。

## 五、官方資料與限制

查閱：2026-09-15 UTC／當地2026-09-14。

- [OWASP Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)：外部內容可形成間接注入；程式權限與輸出驗證必要。本案採最小工具權限與審核界線；不宣稱能消除所有注入。
- [Stripe Idempotency](https://docs.stripe.com/api/idempotent_requests)：適用該 API 的鍵與重放機制；不可推論社交平台 exactly-once。
- [Stripe Pricing](https://stripe.com/pricing)：頁面美國本地卡2.9%+$0.30；Billing pay-as-you-go另0.7%。模型僅作假設示例，尚未選收款商或驗證適用國家／稅務／合約。
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)：grants與policy都需控制；service_role只在server。現有架構可保留。
- [Supabase Backups](https://supabase.com/docs/guides/platform/backups)：DB備份不含Storage物件，故DB恢復通過不能證明完整素材恢復。
- [LinkedIn Community Policies](https://www.linkedin.com/legal/professional-community-policies)：招募不能變為未授權或重複垃圾訊息；陌生連接邀請不可用於促銷。候選接觸採既有允許渠道／社群管理者同意，不自動發送。

沒有本輪新採購／新依賴。Vercel CLI 的 session 提示為59.15.1→59.17.0；下次有Vercel操作前建議另行更新 `npm i -g vercel@latest`，本輪不作無關全局升級，也不因此改變部署狀態。
