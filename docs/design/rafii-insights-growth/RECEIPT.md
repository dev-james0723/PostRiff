# Rafii Analytics / Growth Studio / Trends 實作收據

本地 P0→P1→P2 實作及工程驗收已完成。整體 Task 8 尚未完成：AC08／AC58 的真實 native gate、AC57 的遠端 CI 仍 blocked。

- Spec：RAFII-INSIGHTS-GROWTH-20261004 v1.0；canonical 00–05 及兩份 catalogs 已讀取。
- 最新遠端 integration base：676397a205de065f6962fb6c3f6a9204681c31b4；fresh git ls-remote 記錄見 [integration-final.json](evidence/integration-final.json)。
- **接受本地驗收的 application source SHA：b42da10f87d31dd7398cdcd3512266d3052dfd9a**。後續收據／證據 commit 只記錄交付資料；不能代替部署 SHA。
- Branch：codex/rafii-insights-growth-20261004；隔離樹：/Users/ouxianxing/.codex/worktrees/rafii-insights-growth-20261004/James-Au-Studio。
- Original consumer-saas/d91660b7、dirty edits 及另一個 studio-product-finish owner 保留；取得 own write lease，未 takeover。
- 詳細任務、storage 與 owner map：[IMPLEMENTATION.md](IMPLEMENTATION.md)；一次 whole-branch reviewer 的三項 RED→GREEN 裁定：[FINAL-REVIEW.md](FINAL-REVIEW.md)。

## 最終行為

每 metric 保留自己的 native identity、observed/ingested/definition/readOffset；lesson 保留 support/counter 期間。Review 只查目前允許的已存來源，24h comparable cohort 不混入 1h、7d、unknown offset 或不同原生定義。Legacy 無時間資料維持 unavailable。

Analytics 和 Growth Studio 共用 server-resolved context、Saved Views、版本化人工分類及最多三個描述性 takeaways。下一步沿用 Growth Loop，明確 owner accept／prepare；Growth Studio 接入既有 Growth Lab。Saved View 相對日期會重解析；固定報告與註記新版本保持不可變。

週／月報告的 Markdown、CSV、安全 fixed HTML→browser PDF 共用 payload、digest、context、cutoff 與 exact source IDs。每次讀取、重開、replay、匯出都重查 current source identity/rights。403／409／410 會刷新目前 projection，清除舊數值、原文及 report actions。通用 workspace presenter 不回傳 private Review snapshots/idempotent results。

Trends 沿用 canonical schema／lineage／current-rights／baseline owners。Content reuse 是有原 native identity 的 content-only 候選。沒有 reviewed timing/format/frequency method 時明示 method_unavailable；existing writing calibration owner approve/restore 不冒充該方法。

## 已執行的本地驗收

[validation.json](evidence/validation.json) 記錄每個 command、原始 source SHA、環境、實際輸出與已驗證的 unchanged-source reuse。不得把舊 SHA 的結果改寫成新 SHA 的執行。

- Python：208 run，179 pass、29 PG-dependent skips；另在真臨時 PostgreSQL 跑 45 Trends tests，0 skips，覆蓋相關 SQL 依赖。
- Review generated contracts：10 pass；canonical Trends schema／revocation／strict mutations／restricted projections pass。
- Review／current-rights／API boundaries／export retry／retention：10＋5＋3 check groups pass，b42da10f87d31dd7398cdcd3512266d3052dfd9a。包括兩線 CAS、一線 current-rights race rollback、native ID rebinding、membership、expired/revoked/deleted、replay、CSV injection、view33／snapshot65 拒絕且保留既有 state/revision。
- Existing Growth Loop：9 PG check groups；Growth Phase2：7 PG groups；lesson/Genome owner approve、≥50 chronological calibration approve v1→v2→restore v1 的實際 browser flow 通過。
- Actual Chrome／HTTP／PG browser：跨頁 exact context、12-post scope、Save View／classification／1-post gate、現有 experiment proposal＋明確 owner accept、delay/error 清除舊 DOM、真 PG stale/partial/revocation、empty recovery 通過。UI-state catalog 23/23 DOM pass，design-state overlays 明確 synthetic。
- 1440／390／430px 無 whole-page overflow；keyboard、axe serious/critical 0；actual 10-page A4 繁體 PDF 提取最後一行註記，視覺檢查頁1／5／10 及表格／來源／wrap。
- Web lint：0 errors、3 preexisting warnings；typecheck exit0；production build exit0。臨時 Next dist-dir include 已還原，不留產品配置變更。
- 新 CI workflow YAML／shell syntax 在本地通過。**沒有 remote CI result**。

所有技術測試的 external/native inputs 皆 synthetic、實際 provider/model calls 0，不能代替真實原生驗收。未變更 HistoryImport OFF、scopes、價格、正式 admission 或 payment settings。

## 58 cases 與未完成 gate

[acceptance.json](evidence/acceptance.json)：54 local pass、3 blocked、1 not_applicable。每項包含 source、環境、方法、output、evidence paths。AC18 不提供 ratio aggregate；只有明確 native count median/mean，matched ratio guard 另由 AC17 驗收。

1. **AC08／AC58 blocked**：[native-probe.json](evidence/native-probe.json)。00:14 UTC 的已登入 production UI 是 0 posts read／0 of 0 accounts reporting／No accounts connected。01:19 UTC 最後 reload 要求 MFA reauthentication。沒有 exact24h native IDs／definition／observedAt／ingestedAt 與 provider native口徑對照；deployment SHA unknown。
2. **AC57 blocked / validation_unavailable**：此 local branch 尚未 push，沒有該 source SHA 的遠端 CI run。Workflow 是可審閱候選，不是已成功的 CI 執行。
3. **未 merge／deploy**：未找到可套用此新 branch 的既有明確授權。沒有 publication、paid generation 或 production settings action。

下一項需要的是已授權的 native publication／當前 account analytics rights／admitted exact24h read／native UI 對照，以及對應新 source SHA 的 CI。MFA、部署、原生覆蓋與發佈是分開的 gate。不要新增 scopes／admission／history import 或發布素材來補造通過。

## 失敗修復與重用規則

Whole-branch review 的 current native identity、relative comparison baseline、filter-before-retention 三項已 RED→GREEN。其後補修 generic private Review leakage 及 Growth Studio 的 owner experiment 接口。

Node setup fetch 遇到 ECONNRESET 的重現是同步 fixture seed 阻塞 event loop 超過 Next idle keepalive；實際 diagnostic 比對預設 connection 失敗、Connection: close 成功。只調整 test setup transport，不改 global Next server 或 production networking。

--review-fixture 缺少 --growth-phase2-fixture 原先在 guard 前啟動臨時 PG；guard 已移到 init 前，negative CLI exit2 不再啟動 PG。已辨識並清理當時本 agent 的 orphan cluster，未停止其他 owner 資源。

Supplemental CSV/retention 驗收早期失敗是測試對 existing Direct enum、views-only native metric filter、CSV explicit null／unknown window、reseed 清空 views 的錯誤假設。修正 harness 後全部通過；沒有放寬產品的資料／rights checks。Intermediate logs 保留，但不列為成功證據。

最後 app source 固定後不再擴大驗收。本次 reuse 僅限 diff／dependency／runtime 沒變的受測範圍；新 UI 行為已另以 b42da10f87d31dd7398cdcd3512266d3052dfd9a browser＋lint/typecheck/build 驗證。Git diff whitespace check 用於 source／手寫文件；captured stdout 與 formatter 產出的實際檔案保留原始 CR、縮排及行尾空白，沒有為通過 check 而改寫 evidence bytes。

Token Pilot 收據：本地 checkpoint 保存 source/base、已驗收項目及未完成 gate；provider token／實際費用／節省比較均為 unknown，沒有可靠計數可支持金額或節省百分比。
