# Rafii Insights / Growth implementation

Spec：RAFII-INSIGHTS-GROWTH-20261004 v1.0。已依序讀取 canonical `00–05` 文件及兩份 catalogs，來源：`/Users/ouxianxing/Documents/Rafii-Insights-Growth-Spec-2026-10-04`。

最新 integration base：`676397a205de065f6962fb6c3f6a9204681c31b4`。起初以已查遠端 `fc29af29482fb28e1acbd42a62700b0db7e51829` 建立隔離工作樹，遠端前進後 fetch/rebase 到 676397a；最終已再以 receipt 的 fresh `git ls-remote` 記錄為準。原 checkout 的 consumer-saas/d91660b7 及既有 dirty edits 保留。另一個 studio-product-finish owner 的工作樹未寫入。

隔離工作樹：`/Users/ouxianxing/.codex/worktrees/rafii-insights-growth-20261004/James-Au-Studio`。Branch：`codex/rafii-insights-growth-20261004`。Source SHA：`b42da10f87d31dd7398cdcd3512266d3052dfd9a`。Token Pilot own write lease；exact session `01a108b0-c465-7851-b443-43be5c769da0`，沒有 takeover、hook trust 或 global rules 修改。

## 03 計劃逐項狀態

| Task | 狀態 | 實作與沿用 owner |
| --- | --- | --- |
| 0：base、ownership、wire/storage map | local done | 現行 integration base、isolated tree、write lease 已確認；來源身份/registry/read schedule/Trends schema owners 沿用，不重做已存在的 reader/worker/admission。 |
| 1：P0 metric times／lesson periods／strict projection | local done | `insights.py`、`coworker/performance.py`、`growth/performance.py`、`closed_loop.py`、`postmortem.py`：每 metric 的 observed/ingested/definition/IDs，各自的 digest；legacy period unavailable；精確 publication/readOffset/count/definition/cutoff 綁定。 |
| 2：shared ReviewContext 與 honesty states | local done | 新 thin `coworker/review.py` 與 existing coworker HTTP mount；Analytics/Growth 共用 panel、完整固定或相對 scope、rights epoch cache、舊 response/hidden action 清除；使用 canonical tracking states 顯示 read due/timezone/recovery。 |
| 3：Saved Views／theme、campaign、series | local done | 現有 workspace JSON aggregate，owner command/revision/audit/CAS/idempotency；AI suggestion 不進分析，人工確認後版本化；historical classification membership 保留。 |
| 4：最多三個 takeaways／一個下一步 | local done | deterministic，3 篇描述性門檻；綁現有 Growth Loop hypothesis/experiment（5/arm），明示 support/counter/actual period/limitations，行動前重查 scope/basis/rights，沒有自動 Genome 更新或 publication。 |
| 5：immutable weekly/monthly reports | local done | 沿用 workspace proof/Time Back；native cohort 與 UTC workspace work 分列，Time Back estimated/unavailable；MD/CSV/fixed safe HTML→browser PDF 共用 payload/version/digest/notes，匯出與 replay 重查 current rights。 |
| 6：Trends 完整 lineage／feedback | local done | canonical `trend-types.ts`、receipt validation、exposure/learning owners 沿用；server 提供 provenance/current learning，不接受 client lineage；5 篇 24h baseline、counter、treatment unknown、causal=false 保留。 |
| 7：P2 reuse／personalization qualification | local done | 原 verified publication／Evergreen identity 可追溯、content-only、同作品去重；現有 writing calibration 不能冒充 timing/format/frequency reviewed method，顯示 method_unavailable；owner approve/restore 沿用。 |
| 8：final gates／native evidence／receipt | local engineering done; native / CI blocked | 58 cases 分別記 source SHA/environment/method/output；remote CI 與 exact24h live native evidence 維持獨立 gate。本地工程檢查已完成；真實 native 與 remote CI 未完成。見 `RECEIPT.md` 及 `evidence/acceptance.json` 最終狀態。 |

## Storage 與相容性

- Native metric rows/read jobs 仍由既有 tables/registry/worker 管理；沒有新 acquisition/provider/model engine 或 DB migration。Review 只查已保留、目前允許的來源。
- 私有 workspace `coworker.review`：views、tags、classification histories、immutable snapshot versions、idempotency results；沿用 membership/revision/audit/current-rights transaction。通用 workspace presenter 省略整個私有 namespace，避免繞過專用報告 guard。
- Retention 有界：300 matching publications、bounded observation reads、32 Saved Views（含 archived history）、64 snapshot versions；超界回報 loading/history limit，沒有默默清除證據。
- Canonical Trends schema/enum 未改；Review 僅把 canonical postTracking list 上限擴至其既定 300 篇 scope，保持 canonical states。
- 新 `rafii-review.yml` 把 unit/contracts/browser/real disposable PG 接進現有 CI 工具鏈；未 push 或 dispatch，remote result 尚不存在。

## 不變的授權边界

HistoryImport OFF；沒有 scopes、價格、正式 provider admission、production payment settings 變更。測試 transport/model helpers 明確 synthetic；不作真實 native 證據。沒有新 social publication、paid generation、push、merge 或 deploy。這個新 branch 沒有找到適用的明確 merge/deploy 授權。

## 證據

Historical 7 tests 從 48af4304 恢復，沒有抄其 synthetic RESULTS；base 為 5 pass/2 fail。RED→GREEN logs 保留。正式判定只採 final validation index 指向的成功結果；早期 logs 標為 intermediate。實際 live UI probe：2026-10-05 00:14 UTC 當時的 workspace 為 0 posts read／0 of 0 accounts reporting／No accounts connected，deployment SHA unknown。未用 integration SHA 充當部署版本，也未以 fixtures 滿足 AC58。

最新 01:19 UTC reload 已轉到 MFA verify，沒有執行原生讀取。最後 browser 也補上 Growth Studio 既有 Growth Lab 的明確 owner accept，以及報告 reopen current-rights 拒絕後立即刷新舊值／原文／actions。
