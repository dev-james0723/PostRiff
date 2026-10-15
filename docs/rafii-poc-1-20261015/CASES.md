# Rafii POC-1 — case table (candidate only)

Scope: one Instagram account, one native metric (`reach`, definition `2026-09`, unit `count`), one post-age cohort
(`24h`, upper bound `+3h` from `metric_schedule.WINDOW_TOLERANCE`). Synthetic fixtures only. Base `5f93f375`.

| # | Case | Input (synthetic) | Expected (implemented) | Test |
|---|---|---|---|---|
| 1 | Observed zero | `reach=0`, `available`, read at +24h+1m | `measured`, value `0.0`, eligible, counted in median | unit A-D01, PG A-D01 |
| 2 | Missing | `unavailable`, value NULL | `missing`, value `null`, reason `missing_reading`, excluded; CSV `null`, never `0` | unit A-D01/A-D13, PG |
| 3 | Legacy NULL basis | `read_offset` NULL | reason `unknown_read_offset`, `windowQualification=unknown`, actual age kept in `rejectedReadings` | unit A-D02, PG |
| 4 | Late 24h | labelled `24h`, read at +28h | reason `window_late`, `windowQualification=missed`, `actualAgeSeconds=100800`, value withheld | unit A-D02, PG |
| 5 | Early 24h | labelled `24h`, read at +20h | reason `window_unqualified`, `windowQualification=early` | unit A-D02 |
| 6 | Within tolerance | read at +26h | eligible, `windowQualification=within_tolerance`, age 93600 s | unit A-D02 |
| 7 | Reading after cutoff | observed after the scope cutoff | invisible to that scope (as-of), basis digest unchanged | unit A-D02 |
| 8 | Different definition | `definition_version=2025-01` | reason `definition_mismatch`; never aggregated; scope refuses non-current definition | unit A-D03, PG |
| 9 | Different unit / metric | `unit=percent`; `likes` rows | `definition_mismatch`; likes never join the reach group; mixed-reading ratio refused | unit A-D03 |
| 10 | Insufficient sample | 2 measured | group `insufficient_sample`, aggregate `null`, no takeaway; "descriptive floor, not statistical confidence" | unit A-D05 |
| 11 | Scope downgraded | credential lacks `instagram_business_manage_insights` | eligibility `userGrant=downgraded`, `repairAction=reconnect`; values, sources, aggregates, exports withheld; pending read cancelled before grant/provider | unit A-S02/A-C05, PG |
| 12 | Capability demoted / disconnected | analytics `Unsupported`, credential revoked, channel revoked | `not_comparable`, report 410, pending reads cancelled | unit, PG A-C09 |
| 13 | Rights epoch | scope restored to identical rights | same epoch → frozen report readable again | PG A-C05 |
| 14 | Cross-workspace / account | foreign workspace id, foreign channel, foreign observation | 400 / 403 / 404; `publication_mismatch` | unit A-S01, PG A-S01 |
| 15 | Trends lineage | publication carries `trendLineage` | excluded `trend_lineage_out_of_scope` (fail closed) | unit |
| 16 | Late scheduled read | 24h read row claimed at +30h | closed `window_missed`, no provider call, no observation | unit + PG A-D02 |
| 17 | On-time scheduled read | claimed at +24h+10m | stored with `observed_at` = read time | PG A-D02 |

Result states use the research contract vocabulary where it fits (`windowQualification`: `within_tolerance`,
`missed`, `early`, `unknown`; projection `qualification`: `descriptive_only`, `insufficient_sample`, `not_comparable`).
