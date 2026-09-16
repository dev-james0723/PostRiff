# PostRiff Admin Dashboard — 設計交付與驗證收據

2026-09-14 當地／2026-09-15 UTC。**交付狀態：詳細設計＋本地可點選示範＋候選工程合約。未整合正式app，未取得真實社交分析。** 首期平台由用戶確認為YouTube、Instagram、LinkedIn。

## 1. 從這裏看成果

| 產物 | 內容／如何使用 |
|---|---|
| [完整產品規格](../superpowers/specs/2026-09-14-postriff-admin-analytics-design.md) | 決策、報告映射、現況、兩個視角、角色、10組頁面、指標、同步／成本、安全／刪除、SLO、交付次序 |
| [可點選示範](index.html) | 用瀏覽器打開本地HTML；切換James／客戶、品牌社交成效、7／28日、三平台、缺資料、指標說明。全部synthetic |
| [工程實作規格](ENGINEERING.md) | 模組、24類資料實體、自然鍵、修正、16個候選路由、adapter、交易、預算／撤權競態、24項驗收情境 |
| [平台核對及缺口](SOURCES.md) | 官方URL、查閱日期、可讀範圍、Instagram缺口、三平台qualification worksheet |
| [Metric registry](contracts/metric-registry.json) | 42個定義：24個社交候選指標＋18個第一方產品／經營指標；單位、粒度、口徑、政策gate、公式 |
| [OpenAPI核心合約](contracts/openapi.json) | 10條最初切片路由、DTO、權限、錯誤、同步preview與submit分離。這些endpoint尚未接到runtime |
| [Metric JSON Schema](contracts/metric-point.schema.json)／[Event JSON Schema](contracts/product-event.schema.json) | 嚴格欄位形狀；事件schema是初始子集，完整業務事件見主規格§7。schema本身不代替server授權 |
| [候選資料庫DDL](contracts/analytics-candidate.sql) | 7張最小表、鍵／RLS／current view；未涵蓋完整job／budget／billing等schema，不可當正式migration直接投產 |
| [內部CSV模板](contracts/canonical-import-template.csv)／[虛構例子](contracts/canonical-import-example.csv) | canonical交換格式；不是YouTube／Instagram／LinkedIn原生CSV格式，仍需平台mapper與來源授權 |

**你會在哪裏見到改良：** app側欄新增經營入口及品牌分析入口。前者顯示用戶是否有用、回訪、付款、完整成本與事故；後者顯示授權帳號的帖文成效及最後完整資料日期。單帖可追到來源、草稿版本、記憶選擇、匯出／發布證據。現階段只有本地HTML讓你預覽這些畫面，原app的Analytics placeholder仍未替換。

## 2. 邊界與資料擁有人

- 你是PostRiff管理員：可按server授權看第一方營運統計；身份本身不授予所有客戶社交數據。
- 你管理自己的品牌：在membership＋account grant＋平台許可下看自己的YouTube、Instagram、LinkedIn數據。
- 客戶：只看自己有權的workspace／帳號；不見你的MRR、全站CAC、其他客戶內容或內部margin。
- 客服：健康metadata與明確、短時授權；不能任意impersonate客戶。
- 分析同步只讀；analytics故障不阻止草稿保存、審核和匯出，也不能觸發發布。

以上是已寫成可測試的候選權限設計；本輪SQL測了最小隔離合約，完整HTTP／JWT／Storage／cache／worker整合仍待工程實作。

## 3. 本輪驗證與證據

| 實際執行 | 結果／證據 | 能證明的範圍 |
|---|---|---|
| `.venv/bin/python docs/postriff-admin-analytics/validate_sql.py` | **20項通過**：[SQL收據](evidence/sql-validation.json) | 獨立本地PostgreSQL 17、synthetic資料；跨租戶FK/RLS、admin非自動grant、撤權epoch、profile刪除、重複point/event、晚到舊資料不覆蓋新值、missing與0 |
| `python3 docs/postriff-admin-analytics/validate_contracts.py` | **24項通過**：[合約收據](evidence/contract-validation.json) | 42定義一致性、例子／負例、first-party/social隔離、公式存在、0與null、policy不允許derived、local OpenAPI refs、路徑參數、Pacific DST |
| `node docs/postriff-admin-analytics/validate_ui.cjs` | **14項通過**：[UI收據](evidence/ui-validation.json) | 獨立HTML可用；平台／7日切換、圖表／表格數值一致、未成熟分母、缺資料、視角示範、390px無橫向溢出、dialog與Escape、無JS錯誤 |
| 目視檢查 | [經營頁](evidence/admin-demo.png)、[社交頁](evidence/social-demo.png)、[客戶空狀態](evidence/customer-empty.png)、[手機](evidence/mobile-demo.png) | 畫面可讀與排版。圖片全屬synthetic畫面，不是客戶成效證據 |

測試不是把58項相加當成產品安全分數；三組各自覆蓋不同候選風險。SQL沒有因文案／JSON變更重跑，該DDL未再修改，沿用相同source已通過結果。臨時PG已停止且55449埠關閉：[清理收據](evidence/sql-cleanup.json)。沒有全局安裝新依賴。

### 必要驗證仍不可用

| 狀態 | 原因 | 本輪替代／殘餘風險 |
|---|---|---|
| `validation_unavailable` 完整JSON Schema／OpenAPI標準驗證器 | 既有runtime沒有對應validator套件；本輪不新增依賴 | 以有界本地檢查驗refs、欄位、正負例；不能宣稱完整標準conformance已通過 |
| `validation_unavailable` app HTTP／真實JWT／cache／storage／worker並發 | 新模組未整合runtime | SQL使用synthetic auth stub，不是真實登入；工程矩陣逐项列驗收 |
| `validation_unavailable` 真實三平台API／原生後台對照 | 未核實新analytics資格，也未新增外部授權 | 官方資料＋disabled registry；三平台均`insightsVerified=false`，budget=0 |
| `source_unavailable` Instagram完整最新insights文件 | web工具未取得完整官方正文 | Meta官方collection僅支持有限結論；exact scope/metric/version保留調查票 |
| `validation_unavailable` 正式備份恢復／刪除期限 | 無本轮正式restore演練 | 候選RPO24h／RTO4h及deletion-ledger順序；不當成已達SLO |
| `validation_unavailable` Git diff | 工作目錄無`.git` | 寫入僅新docs路徑；來源快照記hash及定位，沒有提交、push或回滾runtime |
| 真實市場證據未知 | 沒有本輪客戶cohort／付款／退款帳本 | 報告數值只放模擬分類；沒有聲稱盈利或獲客改善 |

runtime沒有改動，所以本輪不重跑整個app build／現有發布測試；獨立示範已做必要瀏覽器檢查。正式整合後必跑受影響的app測試／build，不能拿此收據取代。

## 4. 設計檢查後已修正

1. **成熟分母**：示範10人中8人已成熟、2人未成熟；四週6/8明示未達10人成熟門檻，沒有假稱6/10已達報告條件。
2. **日期一致**：7／28日社交圖表、原生日和卡片使用同組synthetic值；有每日數值表。營運／內容固定窗口不放無作用日期filter。
3. **資料域**：第一方MRR可為授權的全站projection；social metric仍強制workspace/account，不把兩者混進同一帳號資料表。
4. **成本先決**：最小reservation／settlement／stop必在有費用的adapter之前完成；完整財務介面可稍後。鎖順序global→tenant→provider；實際超預留負債照實入帳並停止新用量。
5. **政策真相**：YouTube advanced derived政策需要資格，不能把一份可讀文件當成已批准；Instagram缺文件不能填0或假稱supported。

## 5. 工程接手次序

**最先施工：D0-01，現有session授權＋兩個context endpoint＋metric registry＋兩租戶／兩帳號測試。** 主規格§13已列input/output/回滾；先不調外部API。接著最小outbox、preview讀模型及預算邊界，再做YouTube一帳號只讀7日資格測試與原生核對。

完整候選工程量145–230h；先投入D0+D1約50–75h。20h／週只是規劃假設，非已確認容量；平台審批等待不包含在工程小時內。Instagram及LinkedIn保留首期目標，待各自scope、帳號類型、app access及回應形狀核實後接入。沒有資格時保留清楚標記的原生報表匯入設計。

**最低成本、有判別力的下一個產品實驗：** 用本示範做15分鐘任務測試，請James分別找出「本週要處理甚麼」「哪篇內容有可比較的成效」「哪個數字尚不可信」，記錄完成時間、誤判與實際採取的決定；候選目標3分鐘找到一個需處理事項。它只驗證後台是否幫到決策，不能證明產品留存／付款。之後再用本人授權的一份原生7日報表驗證metric口徑與人工維護時間。

## 6. 回滾與未做事項

本次只有新增`docs/postriff-admin-analytics/`及`docs/superpowers/specs/2026-09-14-postriff-admin-analytics-design.md`；需要撤回時可先移至備份目錄，現有runtime無需回滾。此輪沒有執行刪除文件或修改其他人在做的Phase3代碼。

沒有部署、正式遷移、OAuth scope擴張、真實社交讀取、發布、退款／收款、寄信、購買服務、付費生成或新增排程。正式施工至外部資格／上線時，才需要對實際帳號、權限、成本和target取得欠缺的一步授權；不需要再批准同一份本地規格工作。

本輪降低的是**設計含糊導致資料混用、錯算指標／分母、權限外露與漏算同步成本的已識別風險**；並沒有證明生產環境已安全、已提高盈利或已取得客源。產品是否值得付費、每週使用與三渠道可接觸容量仍是待實測商業假設。
