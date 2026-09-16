# 來源、平台能力與待驗證事項

查閱：2026-09-15 UTC／America/Indiana/Indianapolis 2026-09-14。**E=官方文件可讀，不等於PostRiff app已獲權限；V=本次程式；U=不能驗證。** 本輪沒有登入客戶平台、讀token、發API業務請求或更改scope。

## 官方核對紀錄

| ID | 官方來源 | 本輪用於設計的有限結論 |
|---|---|---|
| E-YT-1 | [YouTube reports.query](https://developers.google.com/youtube/analytics/reference/reports/query) | GET reports、ids/channel、metrics/dimensions/date；endDate可能晚於實際availableThrough；頁首目前要求youtube.readonly，另有analytics scopes。query資格需真實小額/配額有界probe |
| E-YT-2 | [YouTube metrics](https://developers.google.com/youtube/analytics/metrics) | 原生views/engagedViews/watch minutes/average duration等；不同report組合可用性不同，不從Studio畫面推API有同欄位 |
| E-YT-3 | [YouTube dimensions](https://developers.google.com/youtube/analytics/dimensions) | 報表日期採Pacific，DST會有23/25小時，不能把聚合日重標使用者時區 |
| E-YT-4 | [YouTube Developer Policies](https://developers.google.com/youtube/terms/developer-policies) | 資料接收人、跨owner聚合、衍生、更新及撤回/刪除受限。初期不做跨客戶聚合。某些authorized statistics有例外，不能一概理解所有資料皆固定30天；metadata及其餘資料要按類別refresh/delete。撤權需及時執行平台期限 |
| E-YT-5 | [Additional derived metrics/data storage policy](https://developers.google.com/youtube/terms/derived-metrics-policy) | 需符合審核／接受amendment程序才可開特定衍生與至多36月部分統計保存；不自動適用。首期flag=false，證明approved用例後再評估；metadata仍有更新/刪除規則 |
| E-LI-1 | [Member Post Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?view=li-lms-2026-08) | memberCreatorPostAnalytics、r_member_postAnalytics；TOTAL/DAILY依metric及target。單post impression daily、reach及部分新增metric daily受限；dateRange start含/end不含。best-effort值不用於billing |
| E-LI-2 | [Member Follower Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/follower-statistics?view=li-lms-2026-08) | profile/follower是獨立分析資源，不能從post metrics假造完整followers歷史；exact permission/shape在adapter資格票確認 |
| E-LI-3 | [Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?source=recommendations&view=li-lms-2026-03) | Development/Standard access分開申請；該頁Development列500 app calls/day、100 member calls/day及batch/webhook限制。不是所有access tier通用承諾，實際console/version為準 |
| E-IG-1 | [Meta官方Instagram collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-6fa9ed1d-3310-4844-ad25-f0001ab66f11) | 官方Professional Business/Creator；Facebook Login需linked Page，不能用於consumer帳號。Collection涵蓋token/發布/insights用途，但可讀頁不提供完整最新insights矩陣 |
| E-META-1 | [Meta官方團隊](https://www.postman.com/meta/) | 確認Postman workspace是Meta維護的一手來源，而非第三方鏡像 |
| E-TH-1 | [Threads官方post insights request](https://www.postman.com/meta/threads/request/ndeeu6p/get-post-insights) | read insights endpoint及原生分項；P2參考，沒有併入首期範圍，不使用collection全scope字串作最小OAuth請求 |
| E-TT-1 | [TikTok Query Videos v2](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-query) | user授權、video.list、最多20video IDs/query與views/likes/comments/shares；P2，不能當research API授權 |
| E-X-1 | [X Pricing](https://docs.x.com/x-api/getting-started/pricing) | pay-per-use、post reads按resource；Owned Reads有developer owner條件；daily dedupe不是硬保證；成本示例用標示價，正式採用再查console |
| E-X-2 | [X Metrics](https://docs.x.com/x-api/fundamentals/metrics) | public/private/organic/promoted口徑不同；部分private只可查近期自有內容。P2，不用public total代替organic |
| E-PIN-1 | [Pinterest官方Pin Analytics](https://www.postman.com/pinterest/pinterest-collections/request/cfpxpxs/get-pin-analytics) | 有pin analytics API；scope/歷史/准入本輪未完整核實，P2研究票 |
| E-BSKY-1 | [Bluesky API reference](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed) | 許多app.bsky GET為public；不表示有impressions/reach私有成效。P2，必查Lexicon後才列metric |

來源內容有版本差異時不拼湊最大權限。X旧Usage頁仍列2M cap，最新Pricing列3M；本spec不依任一cap推營運容量，只用console實際配額。LinkedIn同頁多版本表與例子需釘定header版本；一個metric名稱出現不代表所有aggregation可查。

## Instagram核對缺口：明確保留

[Instagram Login insights](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/insights)、[Facebook Login insights](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/insights)本輪經web工具無法讀取；部分Meta路徑回429／無可讀內容。標記`source_unavailable`（此工具查核），不是宣稱API不存在。

待核對候選scope：Instagram Login `instagram_business_basic`＋`instagram_business_manage_insights`；Facebook Login `instagram_basic`＋`instagram_manage_insights`＋所需Page read scope。**這些字串此輪未由可讀完整官方insights正文核實，只作工程調查候選，registry不啟用、不要求用戶現在授權。** 不把第三方GitHub鏡像當一手證據。

IG接入前具體驗收：確定一種login flow與app review/access level→本人professional account身份→只讀scope→選一account metric和一media metric的最小probe→保存去秘密schema/request id→確認metrics/period/media type/deprecation/retention→核對後才`qualified=true`。需要認證/approval的步驟另有實際target與範圍，不讓缺口阻止D0本地合同與UI製作。

## 三平台qualification worksheet（目前均未通過live）

| 欄位 | YouTube | Instagram | LinkedIn |
|---|---|---|---|
| 用戶首期選擇 | confirmed | confirmed | confirmed |
| 身份/account id | U，本輪未驗 | U | U |
| App產品/審批 | U | U | U，Community Management tier |
| 建議只讀scope | youtube.readonly + yt-analytics.readonly候選；無monetary | 上述候選未官方完整核實 | r_member_postAnalytics；followers另查 |
| 首個report | own channel 7完整原生日views | professional account/media一項，待文檔 | 自己post TOTAL一項 |
| endpoint/version | reports v2；report family allowlist | 待當前Graph/Instagram版本 | rest/memberCreatorPostAnalytics；明確LinkedIn-Version |
| 成功證據 | response schema、stable id、scope、asOf、compare原生同窗口 | 同左＋login flow／media type | 同左＋queryType/aggregation支持 |
| derived/retention政策 | 未有advanced批准；default native only | 未完成，default native only | 未完成，default native only |
| 回退 | 人工授權原生report；仍標來源及限制 | 同左 | 同左 |

## 程式與報告證據

主spec §2列真實路径；`evidence/source-snapshot.json`保存此輪hash與定位。舊report及上輪規格在[改善交付包](../postriff-improvement-20260914/DECISIONS.md)。Phase3已存在局部reserved allowance，故此次不重複稱「完全沒有成本控制」；完整可對帳USD ledger仍待實作。

MiroFish人格反應/價格意願/36月MRR皆R；不進live registry seed。沒有以瀏覽器登入、舊connector說明或memory中的YouTube read-only狀態作本輪analytics qualified證據。
