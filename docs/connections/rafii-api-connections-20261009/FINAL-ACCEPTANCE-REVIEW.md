# PR #150 — final acceptance review (independent audit)

> **Superseded status (2026-10-10).** This page records the 2026-10-09 audit. For the current state, see RELEASE-CLOSEOUT-20261010.md and RELEASE-GATE-MATRIX.json (schema v2). The current state is: B1 is resolved by #155 (pinned digests, PASS); C1 has a verified root cause, fixed in #161; the High and Medium review findings are fixed in 65205edc and 45b564ff.

Audit date 2026-10-09. Authority boundary: no merge, deploy, DDL, provider grants, scope changes, credentials, real posts or purchases. The PR stays a draft.

## Revisions

| Revision | Meaning |
|---|---|
| `94f156681b9e6e8dc0830d3c63f6ac3acc0b2e7f` | **Application-code head** after the second review's fixes (`src`, `tests`) |
| `1956428296f43dfa4550bbcd111a4b47670e6f7d` | Previous code head (first review's fixes); most CI evidence below belongs to it |
| `ed8d4bb6d3e951062456bf2680f54bc738e550e0` | Previous docs head (code = `19564282`) |
| PR base `220d2de120e5…` | `origin/consumer-saas` is now `2af255fd…` (#151, GenUI, 3 files); `git merge-tree` against it is clean, no file overlap |
| Final docs head | The commit that adds this file (on top of `94f15668`, docs only). CI on it is **pending** at the time of writing; see RELEASE-GATE-MATRIX.json |

## Method

1. Re-checked live GitHub state (PR draft/open/mergeable, 0 reviews, base and head SHAs, every run, attempt and job id).
2. Ran a second fresh-context adversarial reviewer, read-only, against `220d2de1...19564282`, plus my own code reading.
3. Fixed every finding inside PR #150's own files (`94f15668`) and added tests.
4. Re-ran targeted tests locally against the worktree:
   `…/.venv/bin/python run_tests.py control.test_founder_connections control.test_founder_ops control.test_founder_slices control.test_boundary`
   - `19564282`/`ed8d4bb6`: `Ran 109 tests … OK`
   - `94f15668`: `Ran 114 tests … OK`
5. Inspected the CI blockers from logs and registry APIs (CI-BLOCKER-TRIAGE.md).

## Findings

Severity is impact if released; confidence is in the finding. Status: VERIFIED (true and confirmed), UNVERIFIED (unproven), BLOCKED (needs another owner or gate), REGRESSION (caused by this PR).

| # | Sev. | Conf. | Finding | Evidence | Status / disposition |
|---|---|---|---|---|---|
| R2-M1 | Medium | high | A malformed registry decision of a non-`ValueError` shape (`approvedScopes: 5`, non-mapping decision, non-iterable `requestedScopes`) escaped `evaluate_registry` and returned 503 for the whole route | `founder_connections.py` `registry_entries` / `evaluate_registry` at `19564282` | VERIFIED, **fixed in `94f15668`**: the shape is validated and only that row is blocked. Test `test_malformed_decisions_of_any_shape_block_only_their_row` |
| R2-M2 | Medium | medium | Hourly stage keeps the first 5000 channels and deletes the rest. The route then reported `coverage: complete` with exact counts | `founder_metrics_ops.py` `connection_health_stage` (MAX_CONNECTIONS) vs route coverage | VERIFIED, **fixed in `94f15668`**: coverage counts all projected connections; at the cap coverage is partial and counts are lower bounds. Test `test_projection_at_the_stage_cap_is_partial_not_complete`. Residual: projected connections can be slightly below 5000 when some capped channels classify as disconnected (Low, documented) |
| R2-L1 | Low | high | "Inactive operator" test exercised session exchange, not the route | old test body | VERIFIED, **fixed**: `test_operator_suspended_after_sign_in_is_denied_on_the_route` (existing session, then suspended → 401/403, reader untouched) |
| R2-L2 | Low | high | Summary showed "at least 0" when no source was observed | `queue()` | VERIFIED, **fixed**: unknown (`value: null`). Tests updated |
| R2-L3 | Low | high | Adapter catalogue import failure was reported as "no launch scope recorded" | `registry_items` | VERIFIED, **fixed**: P2 `launch_provider_not_in_registry` |
| R2-L4 | Low | medium | YouTube overlay fallback was silent | stage | VERIFIED, **fixed**: warning log (error class only) and `youtubeOverlay` in the stage result |
| R2-L5 | Low | medium | `not_required_evidenced` skipped the scope-coverage check; `decidedAt` was not skew-checked | `evaluate_requirement` | VERIFIED, **fixed**. Test `test_future_decision_time_and_not_required_scope_gap` |
| R2-L6 | Low | medium | 'expiring' and stored deadline used stale channel JSON instead of the vault access-token deadline | `project_connections` | VERIFIED, **fixed**; test covers refreshable-near-expiry (`ok`) vs non-refreshable (`expiring`) |
| R2-L7 | Low | high | No test for a vault-revoked YouTube grant through the projection | test gap | VERIFIED, **fixed**: blocked / `reauthorization_required` |
| R2-L8 | Low | high | Registry rows are fixed to `environment: production` regardless of deployment | `registry_entries` | VERIFIED, **accepted by design**: the registry describes production apps; items carry the request environment |
| R2-L9 | Low | high | No-writes / no-provider-calls proven by inspection only; the web panel has no unit test (typecheck and lint only) | — | UNVERIFIED by test. Inspection: reader-role `metric_rows` in a read-only transaction plus `open_incidents` SELECT; adapter classes are read as attributes only |
| R1 | — | — | First review (2 Medium, several Low) | fixed in `19564282` | VERIFIED fixed (tests present, pass at `94f15668`) |

**No Critical or High findings. No REGRESSION attributable to PR #150 found.** Unrelated Founder, YouTube and social behaviour:
- the `HEALTH` change only affects `client_binding_missing`, which needs the new overlay;
- `expiring` only changes for YouTube with vault facts;
- the slice is appended last and failure-isolated;
- the existing ops, slices and boundary suites pass.

## Requirement-by-requirement (code head `94f15668`, synthetic tests unless noted)

| # | Requirement | Status | Test(s) |
|---|---|---|---|
| 1 | Founder-only `control.read`; inactive operator denied on the route | VERIFIED (synthetic) | `EndToEndAuthorizationTests.test_founder_session_reads_the_queue`, `test_operator_suspended_after_sign_in_is_denied_on_the_route`, `test_inactive_or_non_operator_identity_is_denied` |
| 2 | Anonymous 401, missing capability 403, invalid mode 400 | VERIFIED (synthetic) | `test_anonymous_is_denied`, `test_operator_without_control_read_is_denied`, `test_demo_never_reads_live_and_bad_mode_is_rejected` |
| 3 | Demo/Live isolation; internal workspaces excluded | VERIFIED (synthetic) | `test_demo_is_synthetic_and_never_reads_live`, `test_statements_are_fixed_and_exclude_internal_workspaces` |
| 4 | No credential, ciphertext, token or identifier exposure | VERIFIED (synthetic and inspection) | `test_union_counts_distinct_tenants_and_connections`, `test_live_assembles_sources_and_never_claims_live_verification`, `test_founder_session_reads_the_queue` |
| 5 | No provider calls or writes | VERIFIED by inspection only | — |
| 6 | Distinct union, unknown never 0, truncation → lower_bound | VERIFIED (synthetic) | `QueueTests.*`, `test_truncated_read_reports_lower_bounds`, `test_projection_at_the_stage_cap_is_partial_not_complete` |
| 7 | Freshness, stale, partial, clock skew, source failures | VERIFIED (synthetic) | `FreshnessTests.*`, `StaleTelemetryTests.*`, `test_reader_errors_degrade_connection_health_only` |
| 8 | Approvals by exact (provider, appRef, environment, kind) and scope set | VERIFIED (synthetic) | `RegistryTests.*`, `test_recorded_scopes_never_narrow_the_adapter_request` |
| 9 | Brand ≠ sensitive-scope approval | VERIFIED (synthetic) | `test_brand_approved_does_not_approve_sensitive_scopes` |
| 10 | YouTube refreshable / expired / revoked / `client_binding_missing` | VERIFIED (synthetic). Production pre-deploy counts show 1 YouTube connection in exactly the `client_binding_missing` vault state | `test_projection_overlays_youtube_vault_facts_like_the_channels_card`, `test_youtube_overlay_failure_never_aborts_the_refresh` |
| 11 | Fallbacks (coverage, rows, incidents, registry, overlay) | VERIFIED (synthetic) | `ReviewFindingTests.*`, `SecondReviewFindingTests.*`, `test_incident_store_failure_is_unknown_not_empty` |
| 12 | No regressions | VERIFIED for the targeted suites; full suites pending on the final head's CI | ops, slices and boundary suites |

**Live verification: none.** Every PASS above is synthetic or code inspection. The signed-in Founder (MFA) production readback, an observed hourly refresh and a rollback drill are NOT_RUN (not authorized).

## Provider approvals

`RECORDED_DECISIONS` is empty, so every requirement for every app is `check_required`. YouTube read-only is the recorded first acceptance scope (`LAUNCH_SCOPE`); publishing, content changes and scope changes are excluded. No provider approval is claimed.

## Verdict

**REVIEWABLE.** This means only that the PR is ready for human review. It is **not RELEASE-ELIGIBLE**:
- CI on the final head is pending;
- `document-runtime` needs the Library/CI owner's repair and a PASS at the candidate head;
- James's NO merge/deploy instruction stands;
- production readback is NOT_RUN.
