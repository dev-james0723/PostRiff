# Frozen forecast acceptance evidence

This archive preserves three accepted runs. All observations, time series and
review records are synthetic. The positive SQL qualification demonstrates the
implementation against explicitly reviewed synthetic fixtures only. It does not
qualify any live target/cohort, establish production accuracy, promote a
production method, enable a feature, or complete M3. No provider/model calls were
made in these runs.

## Accepted runs

| Evidence | Result | Execution boundary |
| --- | --- | --- |
| [Pure forecast receipt](forecast-pure.json) / [log](forecast-pure.log) | 30/30, zero skips; 6.8009 s | Actual bounded forecast arithmetic on offline synthetic time series; no DB. |
| [Admission/evaluation receipt](forecast-admission-evaluation.json) / [log](forecast-admission-evaluation.log) | 47/47, zero skips; 3.9573 s | Actual forecast arithmetic and trusted-record contract tests using an in-memory SQL seam; no PostgreSQL. |
| [PostgreSQL receipt](forecast-postgres.json) / [log](forecast-postgres.log) | 15/15: 14 actual PostgreSQL cases + 1 pure DSN guard; zero skips | Fresh disposable PostgreSQL 17.11, current baseline + frozen040, no003; NOSUPERUSER/NOBYPASSRLS runtime. unittest 13.634 s; portable runner group 17.19 s. |

Each run's recorded source guard was unchanged. These are separate source-bound
runs, not a claim that every historical source graph is identical or that later
runtime edits inherit the same acceptance.

The pure algorithm executes last-value, seasonal-naive and local-linear count
candidates with causal rolling evaluation. The adapter/evaluator suite checks
current registry and review provenance, complete preregistered slot/exact-ref
selection, rights and dependency proofs, replay, and chunked binding documents.
Its 1,000-source arithmetic case retains all sources. Qualification output still
abstains beyond 996 sources under the four-subject/1,000-manifest-input limit.

The final PostgreSQL run proves the actual AdvancedPipeline producer seals a
workspace-scoped prediction while preserving original shared-scope bindings.
It checks entitlement/source/policy/contract sharing grants independently;
current evaluator/registry/preregistration; synthetic reviewed admission,
persist/read and retry; revocation, raw-storage denial, tenant/reviewer authority,
method downgrade, late preregistration, missing DAG edges and chunk tampering.
Its 1,000-binding SQL roundtrip proves full chunk retention and a small root;
unsupported extra bindings are rejected before evaluation. That size case is
not a positive 1,000-source qualification claim.

## Exact bytes and relocation

The six receipts/logs below are byte-for-byte copies. Internal `/private/tmp`
paths, timestamps, source hashes, old status statements and commands have not
been rewritten. [forecast-index.json](forecast-index.json) provides the source
path to archive path mapping, byte counts and SHA-256 values. In particular, the
47-test receipt's `postgres: not_run` is historical for that pure run; the later
15-test receipt supplies the actual PostgreSQL evidence.

| Archived file | Bytes | SHA-256 |
| --- | ---: | --- |
| [forecast-pure.json](forecast-pure.json) | 7105 | `7395757196f52149e89f071b2e93d65c449a7b94835fcf4ce4e533bee21dbb08` |
| [forecast-pure.log](forecast-pure.log) | 4675 | `0efa69f7ffad7ad02a3277b4baeee2fceed41201b840ed4eb93cc6d6da3167d1` |
| [forecast-admission-evaluation.json](forecast-admission-evaluation.json) | 9586 | `a6fb57259bc539e60092507c9121839933ae7e87864f7b62c860ab796036cdda` |
| [forecast-admission-evaluation.log](forecast-admission-evaluation.log) | 8824 | `f8f2330b6af8d05e4c45e292d0f71e243c525265996bf06d429614a5d94c6bcc` |
| [forecast-postgres.json](forecast-postgres.json) | 26843 | `45f14d6b581d97b20908b1187677b3e1e4ca96f44d57ff9a84b18d7d7054ec24` |
| [forecast-postgres.log](forecast-postgres.log) | 4758 | `2d69111088d7b4a9e527ae8be909e9dd5c577e777d8237de67544f5874a0f893` |

The earlier 23-test admission receipt referenced by the 47-test receipt is
superseded by the expressly authorized chunk-binding unfreeze. It is not part
of this three-run acceptance archive. Original frozen forecast source hash:
`cd70dcfe71f081d1f763e2bd88116c4e340338a6c97253188e8d3ca4466b2f77`.
Admission source: `40135f75b3e8e8abfcba13e5bd4066e8a0082027c18b62cde9e628c7d9d0d544`.
Evaluation source: `ab81a55268bf8a5ba2bdd111ddb8d244a38b0e7dac198b0fa140c3884395f327`.
Complete tested source graphs and test-file hashes are embedded in the receipts.

## Earlier attempts and final handoff

Earlier failing logs were intentionally not copied into this archive. Temporary
summary links are retained for diagnosis, not as acceptance evidence:

- [Attempt 1](/private/tmp/trend-forecast-postgres-attempt1.log): synthetic raw observation omitted the required author-status fields; corrected only in the test fixture.
- [Attempt 2](/private/tmp/trend-forecast-postgres-attempt2.log): fixture attempted promotion through `put_method`; corrected to a separately explicit synthetic SQL review. Normal runtime promotion remained closed.
- [Attempt 3](/private/tmp/trend-forecast-postgres-attempt3.log): exposed the actual shared-scope prediction/workspace projection mismatch, repaired by the parent before the final run. Also corrected synthetic positive-fixture chronology: evaluation precedes a newly issued, grid-aligned prediction. No timing/qualification gate was weakened.

The final portable runner exited 0 after its successful stop/cleanup step; port
55438 was explicitly released to the parent. The final acceptance changed only
`tests/test_trend_forecast_postgres.py` and
`tests/phase2/postgres_trend_forecast.py`. This archive operation changes only
these `forecast-*` evidence documents; it reruns no tests, opens no DB, edits no
runtime, and makes no production/deployment/M3 claim. Further changes require
validation against their own source binding.
