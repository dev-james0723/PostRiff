# 工程合約與實作細節

主規格：[Admin & Social Analytics](../superpowers/specs/2026-09-14-postriff-admin-analytics-design.md)。**本文件與contracts均candidate，不是runtime已實作。** 採用Python/Postgres、React/Vite，不新增框架或資料供應商。

## 1. 模組與寫入責任

候選新模組`src/postriff_analytics/`：

| 模組 | 責任／input→output | 不可承擔 |
|---|---|---|
| authz.py | verifiedPrincipal+resource+action→AccessContext(workspace,account,capabilities,epoch) | 不信任browser role；不持所有token |
| registry.py | metric id/version＋policy→definition及合法query | 不把native名稱轉成可任意SUM的generic metric |
| query.py | AccessContext+validatedFilter→read projection+provenance | 不讀private workspace JSON，不發provider call |
| repositories.py | bounded SQL、tenant predicates、transactions | 不暴露raw SQL/filter fragments |
| events.py/projector.py | domain outbox→dedup first-party facts/cohort/read model | 不重新執行business command、publish或payment |
| planner.py | connector能力/配額/window→costed partitions | 不因manual refresh繞過global budget |
| sync_worker.py | leased job→read adapter→validated revision+cursor | 無publish工具；無UIrequest lifecycle依赖 |
| adapters/youtube.py等 | server持有的目的受限token+query spec→native raw envelope | 不自行推論內容成效，不要求無關scope |
| normalizer.py | pinned registry+raw schema→canonical points/revisions | 不填缺值為0，不自行外送LLM |
| costs.py | reserve/settle/correct＋idempotent账本 | 不把供應商未知費用設0 |
| imports.py/exports.py | bounded CSV parse／scope-limited export job | 不eval/執行文檔；不以signed URL略過權限 |
| retention.py | consent/policy tombstone→purge tasks+receipt | 不以備份繞過刪除 |
| admin_api.py/workspace_api.py | 分開路由+server action allowlist | 不用一個isAdmin開放所有endpoint |

React候選：`studio/web/src/admin/`與`studio/web/src/analytics/`，共用MetricCard、ScopeBar、EvidenceDrawer、FreshnessBadge、EmptyState、DataTable。lazy import不令首稿增加analytics JS。現有FounderApp Analytics placeholder改成權限內入口，其他導航不重寫。

## 2. 候選資料模型（關係與約束）

沿用public.pr_workspaces(id)及pr_memberships(workspace_id,user_id,role,status)。首期一workspace一brand；`brand_id`取workspace現有brand hub stable id並保存映射。若往後多brand，所有鍵擴為(workspace_id,brand_id,id)，不用臨時client supplied brand。

| 表／實體 | 主要欄位 | 關鍵约束／用途 |
|---|---|---|
| admin_memberships | principal_id,role,capabilities,status,version,granted_by,created_at,revoked_at | unique(principal_id)，server-only管理；沒有signup auto-admin |
| analytics_accounts | workspace_id,id,brand_id,provider,provider_account_id,account_type,display_name,metadata_version,consent_epoch,status | unique(workspace_id,provider,provider_account_id)；同provider ID不同workspace不可共享私有cache |
| account_grants | workspace_id,account_id,principal_id,analytics_read,analytics_export,purpose,expires_at,consent_epoch | composite FK account，受provider接收人規則；新workspace成員不自動讀此前已授權帳號 |
| connector_capabilities | workspace_id,account_id,operation,metric_family,scope_hash,token_status,verified_at,expires_at,policy_version,qualification_evidence | unique(account,operation,metric_family,version)；identity/read/insights/publish分離 |
| policy_profiles | provider,version,allowed_operations,retention_classes,derived_metrics,aggregate_rules,approval_ref,effective_at | version不可變；unknown權限default false |
| external_posts | workspace_id,account_id,id,provider_post_id,media_ids,published_at,native_type,language,origin,availability,metadata_refresh_at,policy_version | unique(workspace,account,provider_post_id)；provider id存text，避免長整數溢位 |
| content_links | workspace,account,external_post_id,link_id,variant_id,variant_revision,content_hash,source_digest,publish_intent_id,confidence,linked_by,linked_at | composite FK；一external_post最多一個active primary link；draft JSON內ID無DB FK時由service在workspace CAS transaction驗證，不能假裝已有relational Draft表 |
| metric_definitions | key,version,provider,native_name,unit,value_type,aggregation_kind,allowed_grains,policy_ref,query_family,verified_docs | registry為權威；unique(key,version)，任意admin不能改formula |
| metric_points | id,workspace,account,object_key,metric_key,metric_version,grain,period_key,dimensions_hash,source_kind,execution,current_revision_id | composite identity unique；object_key=account或post id；dimensions canonical hash；period_key原生date/window/asof slot不null |
| metric_revisions | id,point_id,workspace,account,fetch_id,value,status,period_start/end,observed_at,ingested_at,available_through,evidence_ref,correction_reason | unique(point_id,fetch_id)；point+workspace/account composite FK；歷史append-only且受retention。current指標只讀最新合法revision |
| sync_jobs | id,workspace,account,consent_epoch,kind,query_family,window_start/end,job_key,state,lease_generation,lease_until,attempts,next_at,checkpoint,budget_reservation_id | unique active job_key；重複refresh返回既有job；lease比較才能更新 |
| sync_fetches | id,job_id,page_key,adapter_version,api_version,request_hash,status,resource_count,request_units,raw_ref,observed_at | unique(job_id,page_key,lease_generation)，去秘密，不保存authheaders |
| raw_evidence | id,workspace,account,encrypted_object_ref,hash,media_type,size,delete_by,policy_version | 物件路徑由server生成，≤1MB，按最短保留期；一般client不可取 |
| event_outbox | event_id,workspace,aggregate_type/id/revision,kind,schema_version,payload,execution,occurred_at,delivered_at | 與domain mutation同交易；unique(event_id)及operation语義键；retry不重複business |
| product_facts | event_id,workspace,participant_pseudonym,task_id,kind,occurred_at,assisted,experiment_id,execution | unique(consumer_version,event_id)；no body/token；刪除適用mapping |
| task_measurements | task_id,workspace,participant,baseline_pair_id,metric,elapsed_ms,method,assisted,quality_flags,confirmed_at | 基線/試點method不同顯示；client時間不當server精確計時 |
| cohort_memberships | participant,experiment,cohort_start,icp_version,activation_definition_version,activated_at,assisted | cohort固定；新定義新projection版本，不靜默改歷史 |
| billing_facts | provider_event_id,workspace,subscription_id,invoice_id,price_version,status,amount,currency,effective_at,received_at | unique(provider,event_id)；webhook驗簽；out-of-order靠有效版本/對帳 |
| budget_pools/reservations | pool scope(global/tenant/provider),currency,limit_micros,reserved,settled; operation/account/expiry/reservation state | lock固定順序global→tenant→provider，同層按id排序；入場只允許預留後不超limit；實際供應商負債即使超預留仍如實入帳並hard stop；未知費用不自動全release |
| cost_ledger | id,operation_id,attempt_id,workspace,category,amount,currency,provenance,source_ref,rate_version,reversal_of | unique(operation,entry_kind,sequence)；provenance實測/估計/unknown；禁止費用重複列入固定與變動 |
| support_work_logs | id,workspace可null,task,work_type,minutes,paid_rate,opportunity_rate,allocation_method | 一分鐘只一分類；全局產品工時不能又分攤同成本到每客 |
| attribution_touches | id,participant,qualified_at,channel,campaign,method,permission,source_ref | 可有unknown；first qualified歸因，其他觸點不雙算成交 |
| export_jobs | id,requested_by,scope_json,scope_hash,consent_epoch,state,file_ref,expires_at,downloaded_at | queue/完成/下載三次查權；object not public；撤權撤ticket |
| audit_events/deletion_tasks | id,actor,resource/action,reason,result,policy_version,time；delete scope/checklist/receipt | append最少metadata；不以audit保存本應刪除的platform數值 |

候選SQL只展示並驗證最小鍵、RLS、**社交metric**和事件合約；全站第一方MRR等由獨立product/billing projections提供，不可塞入要求account key的社交表。其餘表按上述欄位另寫additive migration，**不把合約DDL當完整production migration**。

## 3. Canonical metric key與修正策略

自然鍵由server計算：`(workspace,account,object_key,metric_key,definition_version,grain,period_key,dimensions_hash,source_kind,execution)`。snapshot的period_key包含明確as_of observation slot；window report則包含原生起訖/時區。不同fetch of same window新增revision，不新增不同canonical point。相同raw/content hash、window及source version可不新增revision，只更新合法refresh evidence。

`dimensions_hash=SHA256(canonical JSON(sorted keys,no NaN))`；dimensions只allowlist如country/device/native media type，不能自由存email。值相同但provider修正其元資料仍記metadata change。writer先validateschema/type、metric-grain、policy/consent→upsert point→insert revision with fetchId→CAS current revision by observedAt/ingestion sequence→更新cursor，同transaction。較舊fetch保留可查證記錄但不覆寫current。

Response若只回10日而requested14日：只寫那10日，coverage separate；missing4日`pending_provider`。aggregate不能把missing4變0。官方不支持某metric→disable該capability version，不反覆用全metrics query拖垮其他項。

## 4. API 合約

`contracts/openapi.json`為OpenAPI3.1候選，schema以strict additionalProperties=false限制payload。完整驗收依下面語義與測試；未知interface不加假endpoint。

### 4.1 路由

| Endpoint | permission／行為 |
|---|---|
| GET /api/admin/v1/context | active admin；返回role/capability與data readiness，無社交payload |
| GET /api/admin/v1/overview | product.read + finance字段額外權；no all-tenant SNS SUM |
| GET /api/admin/v1/cohorts | product.read；cohort/definition/assisted/n/d/pending |
| GET /api/admin/v1/economics | finance.read；實際/estimated/unknown分列；simulation獨立mode且明示 |
| GET /api/admin/v1/health | ops.read；connector健康metadata，不能取token或客戶rawdata |
| GET /api/workspaces/{workspaceId}/analytics/v1/context | membership＋帳號grant；只回可見account capabilities |
| GET /api/workspaces/{workspaceId}/analytics/v1/overview | singleaccount firstrelease，allowlist metric/filter，返回point envelope |
| GET /api/workspaces/{workspaceId}/analytics/v1/posts | scope內keyset分頁，50預設/200max，id tie breaker |
| GET /api/workspaces/{workspaceId}/analytics/v1/posts/{postId} | verify account/tenant；metrics與content excerpt分field ACL |
| POST /api/workspaces/{workspaceId}/analytics/v1/sync-plans | owner/editor analytics.refresh；只預覽範圍/成本/required permission，無provider call |
| POST /api/workspaces/{workspaceId}/analytics/v1/sync-jobs | exact approved planHash+consentEpoch+idempotency，已授權budget內queue；202 |
| GET /api/workspaces/{workspaceId}/analytics/v1/sync-jobs/{jobId} | scopedjob狀態 |
| POST /api/workspaces/{workspaceId}/analytics/v1/import-previews | boundedCSV/canonical text，parse quarantine不直接進live series |
| POST /api/workspaces/{workspaceId}/analytics/v1/import-commits | 確認previewHash/revision、帳號、來源用途後transaction匯入 |
| POST /api/workspaces/{workspaceId}/analytics/v1/exports | 只授權scope、format/date，server生成ticket，202；不能指定object path |
| GET /api/workspaces/{workspaceId}/analytics/v1/exports/{exportId}/download | 再查當下grant/epoch/expiry，拒絕猜ID |

syncjob取消、account revoke、support grant等操作沿用獨立command routes按版本新增，不隱藏在GET；正式全量OpenAPI應在施工票逐個增加，此輪沒有假稱全部actions endpoints已存在。

### 4.2 通用參數

date `YYYY-MM-DD`；workspace IANA timezone只顯示context，不改原生日；`accountId`必存在scope；metricKey/version allowlist；limit int1–200；opaque cursor含scope/filterHash/snapshotId且server簽名，不能base64解出別人payload；multi-account query require provider policy permission。sorting spec禁止任意SQL columns。

GET限90日/最多12metric，超量返回422 QUERY_TOO_BROAD及建議async report。query timeout3秒候選；mutation payload≤256KB、import獨立5MB。HTTP幂等只有具備server unique record的operation，不宣稱所有provider POST支持。

Header：Authorization由現有verified session；Content-Type JSON；Idempotency-Key對queue/import/export必需；Expected-Revision/planHash避免使用舊preview；response requestId。cookie session時需SameSite/CSRF token/Origin allowlist，不能因JWT做過驗證忽略CSRF。auth token不放query或local logging。

Error envelope `{code,message,requestId,retryable,retryAt,details}`，details只allowlist。401→登入；403/404→無權/不存在統一；409→scope/revision/consent變更；422→metric/grain/period不支持；429→本地/平台限流有RetryAfter；503→資料pipeline暫不可用但已有cache可標stale。

### 4.3 每個metric response

精確例子見`contracts/examples.json`。嚴格規則：

- measured有decimal value，missing value=null+reason，不允許以NaN/空字串表示。
- `dataDomain=social`要求workspaceId及accountId；`first_party`的accountId必null，workspaceId=null僅代表經授權的全站第一方統計。metric provider與domain交叉驗證，不能把社交值偽裝成全站產品指標。currency指標必含ISO幣別，非貨幣值的currency=null。
- 數值JSON schema只約束形狀，權限、metric註冊口徑和幣種不可混算仍由server執行；18個第一方公式為可審核文字，並非已運行的query engine。
- 來源live provider_api可引用raw evidence server id，不暴露rawdata URL；native_export附filehash而非原文。
- dateScope與dataAvailability都存在；requested range不是已取得range。
- ratios若是derived需metric registry derivedAllowed已通過，且n/d本身有同口徑足夠coverage；YouTubedefault不能算自建engagement rate。
- administration data readiness不是metric value。例如沒有billing：readiness.billing=not_integrated，MRR null；已驗無活躍subscription才MRR=0。
- api與CSV保留source lineage，不以更大value自動選勝；API current優先原則僅在同metric/window/source policy已確定。

## 5. Adapter contract（只讀）

```python
class ReadAnalyticsAdapter:
    def inspect(self, token_ref, account_ref) -> IdentityAndScopes: ...
    def capabilities(self, identity, api_version) -> CapabilityManifest: ...
    def plan(self, query, policy, quota) -> BoundedReadPlan: ...
    def fetch_page(self, plan, cursor, token_ref) -> NativePage: ...
    def normalize(self, page, definitions) -> list[MetricRevisionCandidate]: ...
    def classify_error(self, error) -> SyncError: ...
```

Token access由caller驗job目的/expiry/consent後交vaulthelper，`token_ref`非browser傳任意vaultpath。Class沒有publish/comment/like/delete content方法。NativePage包括response schema version、retrievedAt、availableThrough、nextCursor、query hash、quota headers、billable resources、sanitized error，response bodynever executing指令。

`CapabilityManifest` key包含provider、accountType、authFlow、metric、targetType、grain、dateRangeLimit、requiredScopes、apiVersion、docVerification、liveQualification、retentionPolicy。unknown capability≠false unsupported，但兩者都禁止使用，UI理由不同。

### YouTube v1（工程第一條）

metadata Data API與Analytics reports獨立adapter子family；實作讀本人channel固定7完整Pacific日query，metrics先views及likes等通過組合，後按registry增加，不一次請求所有可想像指標。channel-level total與video dimension報告互斥聚合，provider重算由晚到revision覆蓋current。

必測：channel==MINE身份映射、scope缺少、reportedThrough較短、Pacific DST、null rows、quota耗盡、deleted video、revokedconsent。monetary、跨owneraggregate、derived score、全網競品全部disabled；取得額外正式能力才另feature。

### Instagram v1

先決定Instagram Login或Facebook Login之一，不能共用host/token/scope假設；綁professional account stable ID。待核實media/account insights各自支援的metric、period、media type、最低受眾閾值、history與expiry。initial route設unqualified→UI說「尚待API資格核實」，不是0views。

必測：consumer帳號、scope缺少、Professional account換綁、metric deprecated、有API200但data empty、privacy suppression、不同media type不支持同metric。沒有最新官方matrix及live read證據不能開production資格；原生CSV仍可表示native_export。

### LinkedIn v1

member與organization endpoints分開；首期memberCreatorPostAnalytics TOTAL，固定apiVersion/restli header及URN encoding。metric版本對應可用queryType，reach不當daily additive；TOTAL lifetime與TOTAL dateRange兩種period_key不同。follower/profile為另family，缺權限時其他post metrics仍可用。

必測：w_member_social存在但r_member_postAnalytics缺失、member/posts owner不符、urn型別、page response字段variant、development app/member限流、DAILY不支持、TOTAL缺dateRange、API version退役。best-effort成效不可當結算用量或付費觸發證據。

## 6. Database isolation與效能

獨立schema `pr_analytics` 不加入public browser直接可查的API exposed schema；授予後端限定read/write role。正式service_role可繞RLS，因此每service query仍需明確workspace/account predicate+server授權，且投產前以受限DB role測試。候選RLS作defence-in-depth，不能用UI filter代替。

FK全部含workspace/account，避免合法tenant_id和外tenant account_id組合。查customer social數據必account_grants，有效membership不自動cover它。admin aggregation用第一方fact view，role無權直接SELECT social raw/metrics。support path為限時grant join，不SET ROLE成客戶。

第一期query indexes：(workspace,account,published_at desc,id)、point自然鍵、(workspace,account,metric_key,period_key)、(job_state,next_at)、outbox未delivered partial index。每卡最多bounded rows，server聚合/投影。避免pr_workspaces FOR UPDATE大JSON阻塞創作。

容量門檻P：normalized current points>5M或月增>3M、p95主要query>800ms連續2週且索引／rollup無效，才研究時間partition/只讀副本；仍不立即採購warehouse。row/byte metrics實測再調，表數多不是微服務理由。

## 7. 交易、去重與成本例子

### 7.1 Event outbox

1. 鎖workspace revision；驗command合法→保存新state。
2. 產server eventId=operationId+semantic type+domain version的唯一鍵，寫outbox。
3. 同transaction commit；任何失敗兩者回滾。
4. projector claim批≤100；insert product fact on conflict同payload hash no-op、不同payload quarantine；寫consumer checkpoint與projection同transaction。
5. 重建analytics不呼叫provider、不產business commands，projection_version可blue/green比對再切。

### 7.2 成本並發

按global→tenant→provider取得pool lock，同層按id字典順序避免deadlock→計requested upper bound→檢查sum(reserved+settled)+new≤limit→insert唯一reservation→queue。跨worker重複operation只能拿同reservation；actual settlement有唯一providerRequestId/entry sequence。超出預留不能偷扣下一筆，停job並保留實際負債/需人工處理；rate未知不執行paid call。

retry read可能已計費：預留仍cover最大attempt；若不能覆蓋，停止，不重送。usage與UI allowance分開；API取資料失敗不一定扣客戶內容批次，但vendorcost仍可能存在。金額不可由client指定unitRate。

### 7.3 取消與撤權

revoke transaction增加consent_epoch、停新jobs、撤download grants、標purge。worker若在外部已執行，不能宣稱沒有費用；完成時epoch不符→discard metric payload、settle最低必要cost證據。新grant不復用舊run的epoch；reauthorize same account亦需重查scope及retention。

## 8. 匯入、內容關聯與匯出細節

canonical CSV模板字段：platform/provider_account_id/provider_post_id/metric_key/metric_version/grain/period_start/period_end/provider_timezone/observed_at/value/value_status/source_kind/execution。CSV具體source grammar先人工對照，禁止猜日期03/04；require ISO日期。encoding UTF-8，BOM可辨；行號error不回傳整份敏感行。

content link按三優先：①PublishAttempt verified external id與exact account；②使用者report URL後API只讀驗object ownership與正文hash/manual確認；③unverified mapping仍可看原生post但不聲稱由PostRiff產生。文本相似只能suggestion，不能靠相似自動歸因。帖子改文後contentHash mismatch標external_edit，原稿版本不被覆寫。

匯出與刪除競態：export保存query snapshot id但不保留撤權後讀取；完成/取件驗當前epoch；檔案保留候選24h（provider更短取更短），相同request不重複生成；CSV缺值留空＋status，禁止把dashboard人性化`—`轉成數字0。下載audit只記filehash/scope，沒有原文。

## 9. 開發／正式環境與變更策略

- feature flags `ADMIN_ANALYTICS_ENABLED`、`WORKSPACE_ANALYTICS_ENABLED`、`ANALYTICS_PROVIDER_YOUTUBE/INSTAGRAM/LINKEDIN` server默認false。clientflag不構成安全邊界。
- local fixtures與live config分storage/schema或至少execution強制條件，Demo route不能提交livejobs。test定義不可在production fallback顯為live。
- candidate migration先在disposablePG施作/驗FK/RLS/rollback，再staging→只自己workspace→3試點→廣泛beta；外部步驟另明確授權，不由此spec直接部署。
- rollback停止new sync/projectors、保留outbox與cursor、回退query projection version；不能rollback回舊policy給未授權資料。additiveschema保留直到核對，不DROP已有user data。
- 不改全局工具版本。部署前按當次環境核實Vercel CLI；session提示59.15.1→59.17.0，建議更新`npm i -g vercel@latest`，此輪未執行。

## 10. 測試合約矩陣

每測試包含setup/action/expected，fixture與live資格分開記。下面是工程驗收，不代表全部本輪已執行。

| ID | Given / When | Then |
|---|---|---|
| SEC-01 | tenantA已登入，改URL/JSON為B的account/post | 403/404無值無metadata；SQL/RLS仍拒絕 |
| SEC-02 | platform_owner無B帳號grant，查B社交metrics | 拒絕；owner仍可看第一方總體運維 |
| SEC-03 | 客戶viewer猜admin route／偽造role/tenant | 拒絕，不能從client升權 |
| SEC-04 | exportqueued→grant撤回→完成/下載 | job停用/票失效，Storage路徑不能繞過 |
| SEC-05 | cache A查完→切B/登出/撤權 | 無A閃現；cache/permission epoch失效 |
| SEC-06 | CSV/文本含script、SQL、公式、prompt/tool指令 | 隔離/escape，無工具呼叫或泄密 |
| MET-01 | metric缺資料、已量0、native不支持 | null reason／0／not_supported三者不同 |
| MET-02 | snapshot100→140、gap3日、修正−5 | 不生成假自然日flow；保留correction與period |
| MET-03 | reach兩日10/15、channel total＋post totals | 不SUM unique/重複scope |
| MET-04 | YouTube derived/crossowner未qualified | query與UI皆POLICY_BLOCKED |
| MET-05 | Pacific DST與不同日期inclusive/exclusive | 準確原生period；不轉label假每日 |
| MET-06 | LI TOTAL可用而DAILY不支持；IG empty200 | 保留可用metric，unsupported/pending明確，不全頁0 |
| MET-07 | CSV與API同window重複／較舊fetch晚完成 | 不加倍，不覆蓋較新current |
| JOB-01 | 同idempotency/並發refresh、page重放、worker crash | canonical keys/ledger不重複；bounded read retry |
| JOB-02 | 429、refresh token競態、scope403 | app/accountbackoff、一個refresh、authblocked非熱循環 |
| JOB-03 | 撤權發生於已送HTTP後 | 不存/不展示新metric；費用unknown/settle仍正確 |
| JOB-04 | readworker接惡意adapter呼叫publish | class allowlist拒絕；沒有publishcredential能力 |
| ECO-01 | 兩並發reservation剛好剩一份額度 | 最多一個成功；global不超限 |
| ECO-02 | timeout、duplicate webhook、refund亂序 | unknown成本保留，payment去重，MRR按有效entitlement |
| EVT-01 | domain saved/outboxcommit故障→重試 | 原子保存或rollback；event僅一次投影 |
| EVT-02 | synthetic、assisted、未成熟cohort | 排除/分層/pending，不灌分母 |
| EVT-03 | 10activated，6人3/4週，4選offer但0實付 | 報告gate各自顯示；付款0（有完整帳本時）且不得宣稱收入 |
| OPS-01 | restore舊backup含已刪帳號/metrics | 先replay deletion ledger，worker默認停；不可對外讀舊資料 |
| UI-01 | 390/1440/keyboard/空資料/partial/stale | 無溢出、可操作、圖表有表格替代、無mock冒live |

live資格每platform必另交：app/version/accountType/scope去秘密證據、原生同期間對照、少量request ID與成本、token過期/revoke、privacy空值、刪除、rate limit handling。不能為驗收故意發未授權內容或付費請求。
