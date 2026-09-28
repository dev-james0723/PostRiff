# Offline trend operator evidence

These three commands execute the existing pure trend algorithms against explicit JSON files. They never connect to PostgreSQL, providers, models, DNS, or other network services. A process audit hook also blocks external subprocesses. Use the project's Python environment with its normal dependencies installed.

Every command requires `--scope`, `--at` (UTC ISO instant), `--current-rights`, `--execution fixture|local`, and a **new** `--output` path. Outputs contain `production_verified: false`, the declared execution state, and `verification_basis: explicit_operator_file_snapshot`. `local` means exported local data was checked; it is not production verification or proof of a live authorization check. No command promotes a method.

Exit codes: `0` completed, `1` blocked by verification/rights/method state, `2` malformed/missing input or output conflict. Stdout is a compact JSON receipt/error; the output file contains machine-readable evidence. Existing files are never overwritten; new outputs use mode0600. Inputs are capped at32MB, output at64MB. Receipt input is bounded to2000 sources/10000 membership events/200 windows; replay allows48 cutoffs with at most50000 source-cutoff combinations. Large datasets must be exported as explicit bounded decisions, without pretending that a partial corpus has complete coverage.

## Current-rights snapshot

The explicit current-rights file has this shape:

```json
{
  "schema": "rafii.trend-current-rights.v1",
  "scope_key": "shared:fixture",
  "checked_at": "2026-09-28T08:00:00Z",
  "source_policies": [],
  "deleted_observation_ids": [],
  "revoked_policy_versions": [],
  "withdrawn_methods": []
}
```

`checked_at` must exactly equal `--at`. `source_policies` contains complete canonical policy objects with structured permission grants, scope, provider, version, effective/expiry instants and revocation/readiness fields. Populate it from an authorized current policy export for local data; historical receipt policies are not evidence of current permission. `withdrawn_methods` contains `{name,version}` pairs. Empty or missing policies do not grant permission. Both recorded source and current policy grants must permit metric derivation, raw retention and derivative retention. Deletion, expiry or current revocation suppress measurements and source fingerprints in failed verification results.

Full replay evidence retains original source revisions and membership recipes. Its retention/deletion obligations remain those of the source; the command cannot purge other copies or recheck production rights after export. An operator-generated digest proves consistency, not authenticity of the exported dataset or policy snapshot.

## Reproducible synthetic example

Set `TREND_PYTHON` to the installed project Python (this managed checkout uses `/Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python`); the example otherwise defaults to `python3`. From the repository root, create a private scratch directory and prepare the checked-in60/90/150 fixture. The extra derivative-retention grant below is **only a synthetic test permission**; never add it to real data to bypass a missing grant.

```sh
export TREND_PYTHON="${TREND_PYTHON:-python3}"
export TREND_EXAMPLE_DIR="$(mktemp -d /private/tmp/trend-offline-example.XXXXXX)"
"$TREND_PYTHON" - <<'PY'
import json, os
from copy import deepcopy
from pathlib import Path
out = Path(os.environ['TREND_EXAMPLE_DIR'])
data = json.loads(Path('tests/fixtures/trends/metrics/60_90_150.json').read_text())
for row in data['observations'] + data['source_policies']:
    row['rights']['retain_derivatives'] = deepcopy(row['rights']['store_raw'])
rights = {'schema': 'rafii.trend-current-rights.v1', 'scope_key': 'shared:fixture',
          'checked_at': '2026-09-28T08:00:00Z', 'source_policies': data['source_policies'],
          'deleted_observation_ids': [], 'revoked_policy_versions': [], 'withdrawn_methods': []}
for name, value in [('input', data), ('rights', rights),
                    ('outcomes', {'schema': 'rafii.trend-receipt-bundles.v1', 'bundles': []})]:
    path = out / (name + '.json')
    path.write_text(json.dumps(value, ensure_ascii=False))
    path.chmod(0o600)
print(out)
PY

"$TREND_PYTHON" scripts/trend_replay.py \
  --input "$TREND_EXAMPLE_DIR/input.json" --scope shared:fixture \
  --cutoff 2026-09-27T20:00:00Z --at 2026-09-28T08:00:00Z \
  --method current --method-available-at 2026-08-01T00:00:00Z \
  --trend-id topic_fixture --episode-id episode_fixture --group-id topic_fixture \
  --current-rights "$TREND_EXAMPLE_DIR/rights.json" --execution fixture \
  --output "$TREND_EXAMPLE_DIR/replay.json"

"$TREND_PYTHON" scripts/trend_verify_receipt.py \
  --bundle "$TREND_EXAMPLE_DIR/replay.json" --scope shared:fixture \
  --at 2026-09-28T08:00:00Z --current-rights "$TREND_EXAMPLE_DIR/rights.json" \
  --execution fixture --output "$TREND_EXAMPLE_DIR/verification.json"

"$TREND_PYTHON" scripts/trend_shadow_report.py \
  --baseline "$TREND_EXAMPLE_DIR/replay.json" --candidate "$TREND_EXAMPLE_DIR/replay.json" \
  --outcomes "$TREND_EXAMPLE_DIR/outcomes.json" --holdout-start 2026-09-27T20:00:00Z \
  --embargo-hours 12 --scope shared:fixture --at 2026-09-28T08:00:00Z \
  --current-rights "$TREND_EXAMPLE_DIR/rights.json" --execution fixture \
  --output "$TREND_EXAMPLE_DIR/shadow.json"
```

The replay seals actual60/90/150 hourly counts, velocity60, acceleration30, frozen baseline50 and growth200%. The internal candidate is Rising; the public stage remains null. The verification report recomputes those values from the full manifest. This example deliberately has no future outcome data: shadow outcomes are `not_evaluable`, not failures. Comparing the same file honestly reports `same_method_artifacts: true`; it demonstrates the harness, not an old/new-method improvement.

## Replay input and method support

`--input` accepts the existing fixture shape: `observations`, `membership_events`, `source_policies`, `window_specs`, `baseline_window_specs`. Window specs contain `start`, `end`, full `coverage`, and `comparison_scope`. Observations use the canonical typed contract; all collections must match `--scope`. Each cutoff uses then-available source, policy, method and membership versions; future windows are excluded. Window coverage is input evidence, never guessed from a complete ingestion batch. Repeat `--cutoff` for an explicit time range; windows are never automatically shifted or extrapolated.

`--method current` binds the installed immutable executable artifact digests. `--method-available-at` is an explicit operator declaration for replay, not a discovered historical deployment timestamp. A cutoff preceding it returns `method_unavailable`. Required repeated `--group-id` values declare topic, recurrence and known duplicate-family groups for holdout leakage control. These are operator benchmark metadata, not automatically inferred gold labels.

There is no archived executor loader. Verification of a receipt whose recorded artifact version is unavailable returns `method_unavailable`; it never substitutes the installed implementation. Genuine comparisons across different historical executors remain unavailable until those executors are implemented and registered. A pure candidate fixture is never promoted by a CLI run.

## Exact receipt exports

`trend_verify_receipt.py --bundle` accepts:

- The pure `{receipt,manifest}` returned by `receipts.create_receipt`.
- A replay report containing complete `decisions[].bundle` entries.
- `{schema:"rafii.trend-receipt-bundles.v1",bundles:[...]}` (up to200 entries).
- A bundle with `receipt` as a durable receipt row (its `payload.pure_receipt` and `pure_receipt_digest`) and `manifest` as the exact full result of `store.get_manifest(scope,manifest_id,cursor=cur)`. The `json-fragments-v1` recipe, all chunks/ordinals/digests, inputs and document/storage digests must be present.

The durable-row format verifies the embedded pure seal and the full manifest codec. It does not verify a live database transaction, current production policy authority, or every wire projection field; output flags state these limits. Obtain the manifest referenced by that exact receipt projection. Never borrow the latest trend's manifest for an older receipt. Missing chunks and changed numerical values fail verification.

## Separate outcomes and shadow reports

Provide `--outcomes` as complete, independently verified future receipt bundles for the same episode and comparison cohort. The reporter recomputes each receipt and takes its verified normalized hourly snapshots. It chooses the latest then-available receipt revision per episode/window, rejects conflicting equal-time revisions, and requires current rights at `--at`. It never accepts caller-authored success labels.

Only sealed Rising candidate calls in the untouched holdout are evaluated. The existing outcome method requires at least8 of12 complete, comparable future hourly rates at least1.5× the frozen baseline. Missing hours, coverage/epoch gaps, deletion, expiry and unavailable methods leave outcomes unknown. Reports preserve selected/evaluable/success/failure/unknown counts, Wilson95 intervals, group-block bootstrap sensitivity and cohort/method separation. Accuracy display remains withheld below the existing50-evaluable threshold. FPR, recall and lead time stay null when their required populations are absent.

The time embargo must be at least12 hours; related group families are purged from the training side. Comparison pairing is recomputed from actual sealed inputs, not trusted caller-written digests. The report does not certify continuous shadow operation, native-language semantic review, adequate sample size or production qualification.

## Acceptance command

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests "$TREND_PYTHON" -m unittest -v test_trend_operator_cli
```

The tests execute these real subprocesses with the existing fixture plus an800-source sealed future receipt (8 hours at80 originals/hour,4 at40). They check8/12 success against frozen baseline50, Wilson bounds, missing/deleted outcomes, future-leak invariance, embargo, unsupported executors, current rights, durable full-manifest decoding, input corruption, output preservation and blocked network access. No PostgreSQL or external services are involved.
