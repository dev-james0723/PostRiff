# Audited requirement-ledger candidate

Candidate: `/private/tmp/rafii-trend-ledger/requirements.json`
Execution: offline ledger audit only. No repository writes, network requests, provider/model calls, product implementation or deployment. The managed baseline was still byte-identical at final validation. All 1,771 record IDs, order, source sections, exact line spans and exact requirement text are preserved.

## Counts and interpretation

- Total stable baseline records: 1771.
- Meaningful baseline records: 1617 (1549 mandatory; 68 recommendations/planning options).
- Meaningful obligations including four header-only API supplements: 1621. These four are indexed under an existing parent ID; they do not replace or add stable record IDs.
- States: 1,607 NOT_STARTED; 10 BLOCKED_EXTERNAL; 154 NOT_APPLICABLE with rationale.
- 129 proposal contexts need qualification; no numerical candidate or method is approved by this audit.
- T01–T32 and O01–O22: all 54 exact rows retained, individually mapped.
- WP00–WP18: all 19 package deliverable, prerequisite and acceptance rows retained in `work_package_catalog`.
- 540 records have selected `tests` arrays: 1,503 links to the 54 acceptance definitions. All are SELECTED_NOT_IMPLEMENTED / NOT_RUN, with no command/result/file/pass evidence claimed.
- Section 25: 29 immutable records plus full verbatim text with headings and blank lines. `section_25_verbatim` includes line 2893; the original baseline coverage string remains available unchanged in `baseline_coverage`.
- Supplemental index: 87 items; 4 header-only API contracts plus 83 finer fields already contained inside existing fenced records. Do not add all 87 to the meaningful count.

## Delta rationale

1. Reclassified table headers, structural labels, pure historical capability/gap inventories and illustrative numerical copy as NOT_APPLICABLE. Mixed historical rows with continuing obligations (e.g. Reddit deletion, YouTube approval, TikTok route exclusion) remain meaningful. Prohibited product-copy examples remain binding, rather than being discarded as examples.
2. Corrected WP routing by section, entity/file context and explicit T/O scenario. Advanced narrative/graph/genome maps to WP14, saturation/whitespace to WP15, Lab to WP16, media to WP17 and forecasts to WP18. Multi-package/milestone fields retain shared obligations; assignments are disclosed editorial routing, not completion evidence.
3. Populated package prerequisites with stable record references. Dependency notes preserve WP10's early deletion primitives versus later completion; WP12 is optional expansion; WP13 offline public-method work is independent of competitor access. Do not interpret these staged dependencies as a strict package-completion DAG.
4. Marked only ten pure external access/procurement/approval records BLOCKED_EXTERNAL, each with exact source dependency. Mixed engineering requirements stay NOT_STARTED. The 21-entry external-gate catalog is operation-scoped, and no current account availability is asserted. Native-language review, paid smoke, provider policy and modality dependencies remain explicit without blocking deterministic offline implementation globally.
5. Replaced baseline's uppercase-only six-line trigger accounting with case-insensitive occurrence accounting: 77 MUST and 1 SHALL, plus SHOULD, requirement, prohibition, gate and imperative patterns. All 2,953 source lines are accounted for; no source-content gap is hidden by a trigger percentage.
6. Recovered API contracts that the baseline omitted because they are headings: lines 1575, 1577, 1579 and 1581. Added exact-text supplemental entries under `STI-S12-L1573` and linked the admin-only boundary at line 1582. Their SHOULD strength is retained.
7. Kept source schema/example values distinct from production measurements. The normative v2 receipt field shape remains tracked; synthetic IDs/counts/timestamps are not adopted as defaults.

Changed existing fields: {"dependencies": 1590, "external_blocker": 10, "mandatory": 222, "milestone": 70, "qualification_candidate": 213, "state": 164, "tests": 540, "work_package": 1033}. `delta.json` contains the per-ID before/after changes and rationale. New metadata includes classification, source context, multiple WP/milestone ownership, planned test selection, proposal and external-gate indexes. No stable records were added or removed.

## Validation and recovery

Validation: PASS (23 checks). SHA256 of the full 2,953-line canonical source:

`5664a50d744c95734d21dade7baf95145aa8ef14992d6ad11871c8a08828a328`

Revalidate without re-extraction:

```sh
python3 /private/tmp/rafii-trend-ledger/audit_ledger.py validate
```

Reproduce this audit from the immutable local baseline snapshot:

```sh
python3 /private/tmp/rafii-trend-ledger/audit_ledger.py audit
```

The script is standard-library-only, enforces the original source/baseline hashes, writes only this temporary directory, and never dispatches external calls. It refuses source drift. The unused extractor was repurposed into this auditor; no second extraction ran.

`requirements.baseline.json` is the exact user baseline snapshot. `canonical-spec.snapshot.md` binds source bytes. `coverage.json` contains every line/span and trigger occurrence; `coverage.md` is its compact section summary. `validation.json` reports invariant checks; `proposals.json` separates unratified contexts; `section-25.verbatim.md` is the exact full section.

Limits: meaningful counts are conservative source-record counts, not deduplicated atomic business requirements. Semantic classifications, selected test relevance and implementation ownership are editorial judgments. Literal coverage does not prove product implementation, semantic accuracy, external entitlement, test execution or release acceptance. Existing evidence arrays remain empty. This candidate has not been imported into the managed repository.
