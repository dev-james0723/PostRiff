# 最終 review 記錄

一名 fresh reviewer 檢查 integration base `676397a205de065f6962fb6c3f6a9204681c31b4` 到 `2862b81fecdfb46c662fb146cad2d485ae8fb100` 的整個 branch，完成一次要求的 branch review，結果為 changes required。以下三項均在本地重現 RED，再修正並驗證 GREEN。

| 發現 | 處理與實際證據 |
| --- | --- |
| P1：固定報告沒有再次比對 current native post ID | 加入 current providerReference、connection/provider/workspace 及 manifest/verification digest 比對；變更 ID 後 read、replay、三格式 export 均 410。`evidence/native-identity-red.log`、`evidence/postgres.json`。 |
| P2：relative Saved View 的 previous-period baseline 固定在舊日期 | Saved View 儲存相對 comparison 規則；每次重開以 IANA civil week/month 解析，snapshot 保留 fixed resolved context。跨週、跨月、DST 與 schema 回歸通過。`evidence/final-review-red.log`、`evidence/final-review-green.log`、`evidence/contract-final.log`。 |
| P2：300 篇上限在 account/cohort filters 前套用 | 先解析 account/date/language/format/classification，再限制 300 篇；300 篇其他 account 不會擠走 6 篇本 scope，truncation 有明示。`evidence/final-review-red.log`、`evidence/final-review-green.log`、`tests/test_review.py`。 |

沒有重跑第二名 reviewer。確認的發現由回歸測試、真 PostgreSQL及 browser 逐項驗證。後續資料邊界檢查亦修正了通用 workspace presenter 帶出 private Review snapshots/idempotent results 的問題；專用 Review endpoints 才回傳這些資料，membership/current-source checks 保持生效。`evidence/private-storage-red.log`、`test_generic_workspace_presentation_never_contains_private_review_storage`、`evidence/boundaries.json`。

其餘建議的裁定：

- deployment/provider readiness 的外部 gate：保留為 AC57/58 blocked，沒有推成已部署或已通過原生驗收；做成 pass 會錯誤授權或誤報實際 native coverage。
- account deletion：既有 repository transaction 已拒絕 tombstoned workspace；沿用既有 owner，真 PG deletion/RLS 測試繼續覆蓋，沒有另外改帳戶刪除流程。
- 同一 native ID 出現在不同 managed jobs：review 以 verified publication identity 及其 observation IDs 綁定；既有 managed publisher 的 job/verification owner 保留。已測多 reading snapshots 不增加 publication 樣本，未將不具正常可達路徑的跨-job import 作新功能；HistoryImport 維持 OFF。
- PDF renderer：沿用明示的 Print / save PDF，API 回傳安全 fixed HTML，不冒稱 HTTP binary PDF；用 Chromium 實際產生多頁 PDF，Poppler 提取最後一行繁體註記，並作視覺檢查。

最終 release candidate：`b42da10f87d31dd7398cdcd3512266d3052dfd9a`。此 review 記錄是本地證據，不是 PR review 發表、merge 或部署紀錄。

最後驗收補修 Growth Studio 缺少現有 experiment acceptance surface：直接沿用 Growth Lab，proposal 後刷新原 query。報告重開選單使用明確 aria-label；403/409/410 拒絕後刷新 current projection。source b42da10f 的完整 browser 已通過。
