# Rafii Trends × Meta 三平台 × JEV｜全套運作邏輯

> 2026-10-08 工程分析。**技術原理、已存在程式、真正 Production 驗收**必須分開判定。本文所指全網分析係「取得官方／正式授權所容許嘅最大公開內容覆蓋」，**唔係任何 Facebook／Instagram／Threads 用戶嘅所有私人或公開內容都可以無限制抽取**。

## 一、究竟 JEV 係咪 Trends 引擎？

**JEV 係語義判斷引擎，唔係整套系統嘅 crawler、熱度計算器或者唯一模型。**

Rafii 有兩條相互獨立、互補嘅分析路線：

1. **Deterministic Evidence Pipeline（數據事實）**：Python 做資料檢查、計數、時間窗、基準線、變化率、生命週期候選、可信度／來源覆蓋。計算結果可以重播，不依賴模型猜測。
2. **JEV + Other Models（語義解釋）**：由已授權嘅 evidence pack 入手，JEV 執行結構化問題判斷；另一個受控生成模型可以解釋主題、提出創作角度。兩者都唔可以捏造 Meta 未回傳嘅 view／reach／engagement 數字。

實際源碼：

| 子系統 | 檔案 | 職責 |
| --- | --- | --- |
| JEV API | `src/postriff_phase2/growth/jev.py` | `typesafe-ai/jev`，`POST https://ai-gateway.vercel.sh/v1/evaluate`，帶 `state`、`questions`、Gateway usage |
| Model Router | `growth/router.py` | 任務路由、超時、fallback、預算 |
| Typed Judgment | `growth/trends/judge.py` | 12 種問題集合，輸出 allowlisted answers、abstention、來源 digest、模型/成本/校準狀態 |
| Model Enrichment | `growth/trends/enrichment.py` | 已授權、已訂預算、證據現時有效先排程 JEV；失權後不可沿用舊語義判斷 |
| Data acquisition | `growth/trends/providers/*` + `worker.py` | 官方來源拉取、限額、contract/policy、分頁、權限、失敗與補償 |
| Durable Store | `growth/trends/store.py` | 帶收集時間、政策/版本、source identity、retention、provenance，分 workspace 存入 PostgreSQL |
| Topic aggregation | `growth/trends/{clustering,membership,metrics}.py` | 語言／關鍵字候選聚類、同一原生內容去重、合規計量 |
| Time series | `growth/trends/{baselines,momentum}.py` | 同口徑時間窗比較、posts/hour、增長、速度、加速度、異常值 |
| Trend phase | `growth/trends/lifecycle.py` | emerging / rising / breaking / hot / peaking / saturated / declining / evergreen 嘅 **candidate**，唔係無條件真實判定 |
| Confidence | `growth/trends/confidence.py` | 數量、獨立作者、來源涵蓋、觀察完整性、校準、可靠性；唔係「95% 一定爆紅」 |
| Forecast | `growth/trends/forecast.py` | bounded last-value／seasonal baseline／local-linear 候選、留出驗證；預測要獨立 qualification |
| Creative narrative | `growth/trends/generation.py` | 經批准嘅創作解說／內容 angle；只可引用真實可顯示嘅 evidence |
| Existing owned analytics | `src/postriff_phase2/insights.py` | 自己 Posts 嘅 Instagram 和 Threads native metrics（定義互異） |

### 12 個 JEV 趨勢判斷任務

| 任務 | 問題 |
| --- | --- |
| `cluster_merge_check` | 兩組 Posts 係咪其實講同一件事？ |
| `semantic_label_check` | 主題、語義、關鍵字標籤係咪準確？ |
| `culture_classify` | 有咩語言文化、地區語境，會唔會誤解？ |
| `workspace_fit` | 同目前 Creator／品牌方向有幾適合？ |
| `originality` | 建議內容／角度有幾大原創價值？ |
| `execution_risk` | 有冇品牌、平台政策、資訊誤導、執行風險？ |
| `narrative_stance` | 論述／群眾對同一件事嘅立場？ |
| `genome_support` | Trend 是否有足夠可核對根據支持 Creator Genome 關聯？ |
| `spread_mechanism` | **候選**傳播機制；係分析假說，不等於證實因果 |
| `whitespace_support` | 當前題材有冇值得嘗試但未被充分覆蓋嘅創作空間？ |
| `draft_diagnostic` | 一份草稿點樣回應主題？ |
| `platform_fit` | 同各平台原生內容習慣嘅配合程度？ |

JEV 只負責 **interpretation/classification**。天然模型 confidence 同經過實測校準嘅 outcome probability 係兩件事；冇足夠真實歷史標籤同 holdout cohort 時，結果必須標示 **unqualified／interpretation_only**。

## 二、由三平台來源去到 Trends 畫面

```text
Instagram Public Hashtags   Threads Public Keywords   Facebook Public Pages
       \                        |                        /
        \------ [Public Source Provider Adapters] -----/
                             |
              逐平台官方 App Review／scope／user consent
                  工作空間授權／法定資料權利／配額
                             |
                  Bounded API acquisition
          確定資料版本、canonical Post ID、時間、語言
                             |
              Store / RLS / revision / tombstone
                             |
                    Dedupe + Clustering
                    Conversation Episodes
                             |
                  Comparable Observation Windows
             Qualified Sample Rates + Real Baselines
                   Velocity + Acceleration
                             |
              Lifecycle Candidate + Support Score
                             |
              Current Authorized Evidence Pack
                             |
               +-------------+--------------+
               |                            |
        Typed JEV Judgment          Optional Writer Model
         semantic / brand fit       explanation / creative ideas
               |                            |
               +-------------+--------------+
                             |
                 Verified Receipt + Source Links
                             |
             Trends / Growth Studio / Saved Ideas UI
```

**另一條 Owned Lane 必須分開**：
`Creator 登入 IG/Threads 或管理 Facebook Page → 原生授權 → 自己 Posts + Native Insights → post-mortem / Creator Genome / Growth Studio`。唔可以將自己賬號嘅流量當作「全站搜尋總量」；更唔可以話「用戶連咗 FB = 獲准存取全網 FB」。

## 三、統計模型具體做緊乜？

**Step A — 正規化同去重：** Meta 原始欄位喺不同 API 可以不同，Rafii 統一存 provider、operation、source identity、post 時間（同 retrieval 時間分開）、language、內容保存權、作者可否確認、revision/deletion key、完整度。相同 provider + canonical native ID 唔因為 hit 多個 keywords 而變成幾篇 Posts。

**Step B — Topic clusters：** original-language/CJK lexical candidate + 可用嘅已合格 embedding；JEV 可選擇做語義聚合判斷，但唔可以越過來源 policy 或喺不確定時強行 merge。建立 conversation episode／topic nodes。

**Step C — Comparable windows：** 只比較同一來源、相同查詢邊界、時間、方法、涵蓋人群、語言及同一計量口徑嘅時間窗，先計 `mention_rate = qualifying sampled posts / hours`。這個「mentions」係 **樣本每小時出現量**，唔係整個平台所有 Posts 的統計母數。

**Step D — 數學：** `velocity = (rate_now - rate_prev) / Δhours`；`acceleration = (velocity_now - velocity_prev) / Δhours`；`growth_pct = 100 × (rate_now / comparable_baseline_rate - 1)`。基準線來源不足或口徑唔同 => NULL／insufficient，而唔係估數字。異常度可以用 median / robust scale。

**Step E — Trend phase / confidence：** 使用連續時間窗、增幅、活躍獨立作者、最大作者集中度、完整度、歷史水平作 lifecycle **候選**。Confidence 係「證據夠唔夠支持結論」，不是預測爆紅機率；JEV 更不可以取代這些統計條件。

**Step F — Optional semantic explanation：** 先確認 `llm_process` 權限和 usage/budget，再由模型處理 **有 digest 嘅 evidence pack**，回答「呢件事講緊乜？對邊類 Creator 有用？有邊啲文化風險？可以點創作？」，並保存模型版本、task、資格／拒答、成本和可追溯來源。

## 四、三平台真實覆蓋（Source Matrix）

| 類型 | Instagram | Threads | Facebook |
| --- | --- | --- | --- |
| Public discovery | 已批准 Hashtag Search / Business Discovery（如適用） | 已批准 keyword_search／profile_discovery | 已批准 PPCA public Pages |
| Owned analytics | Creator/Business native insights | Connected profile native insights | Managed Page insights |
| Known exclusions | 普通私人帳戶、全平台任意 text search、不在樣本嘅 Posts | 私人內容、未被搜尋／未回傳嘅內容 | 私人帳戶 Feed、非公開 Groups、受限制 Pages |
| Qualification | Facebook Login IG Professional + 應用功能審核 | Threads app + `threads_keyword_search` 審核 | Page Public Content Access 審核 |
| State as of this branch | Adapter code only, not runtime/admitted/live | Adapter code only, not runtime/admitted/live | Adapter code only, not runtime/admitted/live |

**特別註明：** Meta Content Library 適用合資格研究而非默認商業 SaaS 資料供應商；若想擴展普通公開查詢不足以涵蓋嘅人群，需要另簽允許此用途的正式 commercial feed contract，來源同採樣限制同樣須清晰揭露。

## 五、做好之後 UI 真正應顯示乜？

每個 Trend 卡片都應有：
- 所屬平台、Source／Operation、區域語言、具體查詢、樣本時間段、`as-of`、本次/上次成功收集。
- 「Sampled Posts」「Not whole network」「Unknown coverage」；對未核准來源：`Not configured`/`Pending App Review`/`Revoked`/`Rate-limited`，唔可以顯示 0 activity 嚟冒充無人討論。
- Source-backed topic cluster、sampled growth／velocity／phase（每項有限制），原生 post links。
- JEV semantic insights 明確標 `model interpretation`、模型／task、calibration／abstention；禁止當做 native metrics。
- 回到 Creator's Growth Studio 時，呈現 **Own-account Post Performance vs Public Topic Signals** 兩欄，從不直接相加／混合 native reach、views、likes。
- Disconnect、delete、rights change、token expiry 立即影響舊證據可見性；過往 report 要重新核對目前保留權。

## 六、工程／審核完成標準

**七級門檻，逐平台獨立：** (1) implemented、(2) runtime-bound、(3) app-reviewed、(4) authorized scope verified、(5) real public request accepted、(6) stored + lifecycle verified、(7) production user journey verified。

實際工程成果：
- Draft PR #143：`https://github.com/dev-james0723/PostRiff/pull/143`。
- Source：`src/postriff_phase2/growth/trends/providers/meta_public.py` — 三個只讀、server-injected-token、policy-quota-gated adapters。
- Tests：`tests/test_trend_meta_public.py` — synthetic acceptance/rejection，非 live proof。
- Plan：`docs/superpowers/plans/2026-10-08-rafii-meta-public-trends.md`。
- Review package：`docs/reviews/2026-10-08-meta-public-trends/README.md`。

**未解鎖：** Meta App Review/PPCA、新帳戶公共搜尋權限、真人 OAuth 授權、可商用 AI 衍生權利、真實三平台第三方結果、release/production、對普通用戶嘅使用驗收。冇權限唔可以聲稱完成。

## 七、Cost / capacity

官方 Graph API 整合唔等於無條件無限免費。平台 API rate/operation quota、Facebook/IG 用戶權限、JEV Gateway token/usage、雲端計算、可能的商業 feed 授權，需要分開審核；沒有現行 provider quota、invoiced cost/terms 不得捏造確切數字。JEV 僅在 evidence-processing consent、reviewed permission 和 bounded spend 全部齊備時入場，唔以高價模型代替資料真相。

## Sources / Evidence

- 目前程式：`src/postriff_phase2/growth/jev.py`、`growth/trends/{judge,enrichment,metrics,momentum,lifecycle,confidence,pipeline,advanced_pipeline,generation,forecast}.py`、`src/postriff_phase2/insights.py`。
- 原有 Meta App Review pack（owned only）：`docs/design/growth-phase0/META-APP-REVIEW.md`。
- Meta Threads 官方 collection：`https://www.postman.com/meta/threads/collection/dht3nzz/threads-api`。
- Threads Keyword Search：`https://www.postman.com/meta/threads/request/m9j4i2x/search-for-threads-posts`。
- Meta Instagram docs：`https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api`。
- Facebook PPCA：https://developers.facebook.com/docs/features-reference/page-public-content-access  (current provider portal requires validation).
- SOMAR Meta Content Library：https://www.icpsr.umich.edu/sites/somar/meta-content-library 。

**Last verified:** GitHub default branch and our own PR only; no Meta public production source has been verified in this task.
