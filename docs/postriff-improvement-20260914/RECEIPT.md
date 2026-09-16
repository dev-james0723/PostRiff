# 本地實作與驗證收據

日期：2026-09-14 當地／2026-09-15 UTC。**完成的是有範圍的本地修復、測試與候選決策材料；不是正式部署、真實發布、取得付費客戶或提高盈利。**

## 1. 工作位置與保存

實際 source tree：`/Users/ouxianxing/Documents/James-Au-Studio`。提供的暫存路徑是它的 symlink；不是另一份獨立checkout。目前沒有`.git`，因此Git狀態/commit/diff為`validation_unavailable`。不初始化Git，不碰舊worktree。

[baseline.json](evidence/baseline.json)記錄原檔SHA-256與33頁PDF的SHA-256；[before](evidence/before/)保留修改前指定檔案。可審核[完整本輪source diff](evidence/source-diff.patch)與[修改後hash](evidence/changed-files.json)。Phase3 runtime、desktop、UI與`contracts.py`已有並行編輯，**沒有把那些成果歸於本輪，也沒有還原它們**。`contracts.py`備份只用於對照，未列入回滾patch。

## 2. 已完成的第一批 P0 本地改動

| 檔案 | 改動／已降低的可重現風險 |
|---|---|
| [store.py](../../src/postriff_phase2/store.py) | local mutation查真實active membership及owner/editor角色；source/brief更改後舊稿不能直接再核對；manifest新增workspace/brand/sourceDigest/briefRevision/providerAccountId/scopes比對；worker提交前核對批准人與approvalDigest；取消及adapter結果在最新transaction判斷 |
| [hosted_worker.py](../../src/postriff_phase2/hosted_worker.py) | Postgres claim時鎖讀active member與未刪除profile，重新查owner/editor及批准人；lease fencing後才處理結果；provider exception轉為遮罩後unknown |
| [outcomes.py](../../src/postriff_phase2/outcomes.py) | 共用adapter回覆驗證；malformed狀態及不足發布證據成為uncertain；對帳不能以scheduled/held/failed觸發再次提交；取消後明確未接受的retry回覆轉canceled；只傳遞allowlist欄位 |
| [test_postriff_safety_regressions.py](../../tests/test_postriff_safety_regressions.py) | 新增10個有行為意義的回歸測試，涵蓋來源、角色、未知結果、取消競態、例外遮罩與零社交單稿工作流 |
| [postgres_safety.py](../../tests/phase2/postgres_safety.py) | 新增5個真實本地Postgres整合檢查，provider為synthetic |
| [postgres_repository.py](../../tests/phase2/postgres_repository.py) | 既有crash-recovery fixture補明確synthetic provider reference，符合更嚴格收據合約 |

修改前的[失敗回歸](evidence/regressions-before.txt)重現了舊來源再審、撤權仍可提交、unknown重新submit等缺口。修復後已通過以下驗證；測試並不代表現實世界發生过這些事故。

相容性與限制：舊的未提交manifest缺新欄位會held，需重新review；已提交或結果未知仍走對帳。沒有資料庫schema migration。claim/submitting transaction commit是開始提交的線性化點，之後取消可能來不及；不得顯示已成功取消。`scheduled`僅可由已資格驗證adapter用於**明確未接受**的情況，真實adapter仍未驗證。

## 3. 本輪驗證結果

以下都在本機、synthetic資料上執行。測試總數包含既有及並行Phase3測試，不等於本輪新寫同數量測試。

| 驗證 | 結果／證據 |
|---|---|
| Python domain/Phase2/Phase3全套 | **128項通過**；[python-tests.txt](evidence/python-tests.txt) |
| 前端測試 | **72項通過**；[frontend-tests.txt](evidence/frontend-tests.txt) |
| TypeScript | 通過；[typecheck.txt](evidence/typecheck.txt) |
| Vite production build | 通過、输出獨立evidence/ui-dist；[build.txt](evidence/build.txt)。單chunk約587.20kB警示尚在，非失敗；本輪無UI改動 |
| Postgres RLS SQL | 真實disposable本地PG通過；[rls.txt](evidence/rls.txt) |
| Postgres repository/worker既有整合 | **8項檢查通過**；[postgres-tests.json](evidence/postgres-tests.json) |
| Postgres新安全整合 | **5項檢查通過**；[postgres-safety.json](evidence/postgres-safety.json) |
| 實際本地dump/restore | **2個synthetic workspace狀態、revision、jobs相同**；恢復後RLS讀取隔離通過；[restore-result.json](evidence/restore-result.json)。本機耗時0.785秒，不是正式RTO；未啟動恢復後worker |
| 桌面/手機瀏覽器 | 一份草稿、0渠道、0jobs；編輯、Remember→Undo、私人ZIP下載6325bytes；1440及390px無橫向溢出、無pageerror；[browser-result.json](evidence/browser-result.json)、[桌面](evidence/desktop.png)、[手機](evidence/mobile.png)，均經視覺檢查 |
| 經濟算式 | **7項測試通過**；[economics-tests.txt](evidence/economics-tests.txt)。3情景×36月、9壓測、cohort庫存守恆；[validation.json](model/validation.json) |
| 交互決策頁 | scenario/month切換數值、手機寬度及無pageerror通過；[dashboard-result.json](evidence/dashboard-result.json)，[畫面](evidence/dashboard.png)經視覺檢查 |

主要命令（工作目錄為source tree，除另註）：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_postriff*.py' -v
python3 docs/postriff-improvement-20260914/test_economics.py
python3 docs/postriff-improvement-20260914/economics.py
```

前端在`studio/web`執行`npm test`、`npm run typecheck`及`npx vite build --config vite.alpha.config.ts --outDir ../../../docs/postriff-improvement-20260914/evidence/ui-dist`。PG整合使用`.venv`內現有psycopg與本機PostgreSQL17，未新增runtime依賴。瀏覽器使用現有Playwright；[browser-check.cjs](evidence/browser-check.cjs)保留操作腳本。首次瀏覽器嘗試因測試locator包含icon而失敗，改為實際accessible name `You`、重建synthetic workspace後通過，沒有掩蓋產品錯誤。

## 4. 使用者要求的十類驗收逐項狀態

| 驗收 | 本輪結果、替代檢查與殘餘限制 |
|---|---|
| 1 零社交首稿／編輯／記憶／匯出 | **local-synthetic pass**。未呼叫真實模型；使用者判有用與首稿時間為`validation_unavailable`，缺真實任務／模型授權 |
| 2 租戶／品牌隔離 | local membership、兩用戶PG/RLS、private storage auth既有測試通過；未驗真實雲端Storage下載／多brand於同tenant，`validation_unavailable`。現況一workspace一brand，候選composite FK尚未上線 |
| 3 未批准、改稿／素材／帳號失效 | synthetic既有及新回歸通過；增加brief/source/account/scope及撤權檢查；沒有真實發布 |
| 4 文件惡意指令 | domain fixture不調工具、schema／allowlist與禁止未授權route的程式測試通過；**真實模型注入／來源四類policy品質`validation_unavailable`**。已交付固定8例品質集與ContextBuilder規格，不能只憑fixture宣布安全 |
| 5 重複、重啟、429、token過期、逾時 | synthetic adapter + 真實本地PG lease/crash/retry/取消回歸通過；live provider semantics未驗 |
| 6 unknown不盲重送 | SQLite與PG新增回歸通過；查證缺reference不算verified；真實connector qualification為`validation_unavailable`，沒有必要的實際發布授權／本輪未啟用 |
| 7 並發用量／重複webhook | 既有CAS、trial計量及idempotent command測試通過；**完整USD reservation/settlement與真實billing webhook尚未實作**，此部分`validation_unavailable`，規格見SPEC；paid route不得靠舊counter宣稱完整限額 |
| 8 記憶撤回／來源刪除 | 本地remember/undo與撤回來源後舊稿失效通過；歷史revision/衍生圖/備份刪除仍未完整清理，`validation_unavailable`，不等同資料已徹底刪除 |
| 9 品質基線 | quality-cases.json結構可讀、fixture程式測試通過；真實語意、英／繁中自然程度及更新回歸未測，`validation_unavailable`。沒有付費生成授權或客戶評分樣本 |
| 10 核心UI/build | 本地production build、TS、72前端tests、桌面手機主要workflow通過。未做正式登入/production playthrough |

其他`validation_unavailable`：Git狀態（source tree無.git）；正式雲端備份/RPO/RTO（本輪僅有disposable PG，未驗Storage bytes/Auth/vault）；真實付款、取消、退款、CAC、四週留存（無本輪真實交易/成熟cohort）。原始MiroFish seed為`source_unavailable`，保留Bullish算式衝突。未知不是0，也不是已發生故障。

## 5. 回滾與操作環境

**沒有執行回滾。** 因有並行工作，回滾前先以[changed-files.json](evidence/changed-files.json)檢查目前檔案hash；只有仍等於本輪after hash時，才可逐個existing檔案由before還原。新增的outcomes.py及兩個新測試只在確認無其他新依賴後移除。若hash不同，逐hunk反向套用[source-diff.patch](evidence/source-diff.patch)，不能直接覆寫整檔或整目錄。恢復後重跑上表受影響測試，停用dispatch直到重新驗證，避免重新引入已知風險。沒有schema rollback或外部content回滾。

Vite build輸出在evidence獨立目錄，未覆蓋使用者app dist。本轮測試UI服務為loopback45319、無worker；PG為loopback55438的獨立temp cluster。完成後關閉這兩個本輪啟動的服務；[cleanup.json](evidence/cleanup.json)記錄結果。沒有停止使用者其他程序。

## 6. 決策材料與未做事項

- [決策／風險／ICP](DECISIONS.md)、[架構／資料／狀態與驗收](SPEC.md)：已完成候選規格；source-first UI、四类source政策、完整ledger與memory schema尚未實作。
- [可重算經濟模型](ECONOMICS.md)：保留報告baseline，三情景、九壓測、12/24/36月、cash/full-cost及容量。基準36月正全成本結果仍超工時，不能作可執行承諾。
- [獲客實驗包](GROWTH.md)：landing文案、85秒demo、三封邀請／跟進草稿、訪談及四週試點、可填CSV；**沒有寄送或自動建立聯絡人**。
- [90天路線](ROADMAP.md)：按每週25h候選容量並行工程／市場學習，所有新目標明確為候選；沒有聲稱完成90天留存。

沒有部署、正式遷移、擴大OAuth、外部發布、上傳敏感資料、付費模型呼叫、採購、收款或通知外部人士。往後若要執行，需要覆蓋實際環境／資料／收件人／成本的明確授權；本輪的本地工作已完成，不為這些未啟動的外部步驟重複索取確認。

**下一個最便宜且有判別力的實驗**：先3名符合ICP的人，各帶一份有權使用的近期材料，比較原流程與安全可用的PostRiff全任務時間及「願不願使用」；七天內觀察是否帶新素材回來。真實模型及資料外送未授權前，只做近期行為訪談／本地可用性，不能將fixture算有用內容。通過後再擴10人四週，區分assisted/self-serve、選方案/承諾付款/實付/退款後保留。尚未證實的商業假設是任務頻率、優於通用AI的返工減少、$39付費保留、可負擔客服與可觸達渠道容量。
