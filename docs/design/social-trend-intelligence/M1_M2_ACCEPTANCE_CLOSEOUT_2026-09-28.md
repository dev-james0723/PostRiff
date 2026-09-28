# Social Trend Intelligence M1/M2 acceptance closeout candidate

Recorded on 2026-09-28 from the requested release baseline `822f25d21138be18dbcd0eb7d3d2bcb1baff87cc`, then rebased onto merged-head base `a25bb4583035d4abb18f8735cc92c7b619cdcb31` to preserve the concurrent hosted-social release, on branch `codex/trend-acceptance-m1-m2`. This is a source-bound local release-candidate receipt. Production remains the canonical release until the candidate passes the normal PR, merge, deployment and live-revision checks.

## Outcome

- Stable ledger population remains 1,771 requirements.
- State counts are 167 `VERIFIED`, 1,431 `IN_PROGRESS`, 19 `BLOCKED_EXTERNAL`, 154 `NOT_APPLICABLE`, 0 `IMPLEMENTED_UNVERIFIED`, and 0 `NOT_STARTED`.
- Every one of the prior 107 `IMPLEMENTED_UNVERIFIED` rows was inspected, bound to a source-hashed local proof, and promoted to `VERIFIED`. The row-level implementation files, tests, evidence text and hashes are in `requirements.json`.
- All ten prior `NOT_STARTED` rows are genuine provider, contract, legal, access or global-activation gates and are now `BLOCKED_EXTERNAL`: `STI-S17-L1934`, `STI-S17-L1935`, `STI-S20-L2161`, `STI-S20-L2162`, `STI-S20-L2163`, `STI-S20-L2167`, `STI-S20-L2197`, `STI-S20-L2198`, `STI-S20-L2199`, and `STI-S26-L2905`.
- Twenty-nine additional `IN_PROGRESS` obligations with exact local evidence were promoted to `VERIFIED`. This was evidence reconciliation, not a claim that M1 or M2 is complete.

## Acceptance evidence

The source-bound receipt is `evidence/m1m2-acceptance/acceptance-tests.json`; path-to-code/test/database/requirement bindings are in `COMPOUND_ACCEPTANCE_BINDINGS.md`.

- 1,027 Python trend tests: 785 passed locally, 242 database-only skips, zero failures/errors. The 242 database cases were exercised in the PostgreSQL groups below.
- 584 disposable-PostgreSQL tests passed across advanced 43, forecast 15, frontier 37, generation 39, interpretation 49, media 51, pipeline 14, planner 53, services 136, trust 112 and whitespace 35.
- 108 browser→real API→PostgreSQL assertions passed at 1440, 768, 390 and 430 px with API interception disabled.
- 16 strategy adoption/revocation browser→real API→PostgreSQL assertions passed at the same four widths.
- 435 web tests passed; production build, TypeScript and lint passed.
- Provider calls: 0. Model calls: 0. Paid external spend: USD 0. No activation, collection, notification, competitor observation, publication or external rollout occurred.

The compound scenarios cover evidence→opportunity, opportunity→Ideas, explicit three-angle authorization boundary, Ideas→Weekly, Ideas→Campaign, Rafii chat handoff, strategy adoption, rights revocation, exposure/outcome lineage, performance learning, deleted/expired/revoked evidence, tenant isolation, recomputation, retention/deletion, local language preservation, and cost/model accounting boundaries.

## Defect found and repaired

The expanded PostgreSQL acceptance caught a real reverse-dependency deletion defect: a revoked source invalidated its `frontier_control` request, but bounded physical purge did not include that invalidated node kind. The merged-head rerun then caught an ordering edge: physical purge could erase the request before paged frontier maintenance scrubbed its linked job. `retention.py` now permits the control-node purge only after the dependency-validity predicate authorizes it and no linked job retains payload. The affected frontier 37 and trust 112 groups were rerun and passed.

The Linux release gate then exposed a cross-platform receipt-seal defect: Shannon entropy for a single known creator was emitted as IEEE `-0.0`; PostgreSQL JSONB normalized it to `0.0` on the CI build, so the immutable receipt no longer matched its pre-storage digest. `metrics.py` now canonicalizes the mathematically non-negative result to positive zero. The regression test, all 1,027 trend tests and the affected 136-test PostgreSQL services group passed locally before the follow-up release gate.

## Milestone status

- **M1: not globally complete.** The trustworthy signal/receipt spine and representative end-to-end lineage are locally evidenced. Observed evidence, calculated metrics, inferred lifecycle and model interpretation remain distinct; missing/unknown data is not coerced to zero; current-rights revocation and deletion propagate. Exact remaining obligations are still `IN_PROGRESS` or `BLOCKED_EXTERNAL`.
- **M2: not globally complete.** Bounded creator-action handoffs, exposure/outcome linkage, authorized-current performance learning, strategy withdrawal/recomputation and no-invented-outcome behavior are locally evidenced with clearly synthetic fixtures. Actual creator outcomes, empirical cohorts and paid generation remain open.
- **M3: not globally complete.** `M3_CAPABILITY_MATRIX.json` records text/genome, visual/keyframe, audio/transcript, forecast and competitor reconstruction separately. Local synthetic contracts pass where present; empirical language/modality rights, forecast cohorts, real authorized corpora and competitor observation remain open.

## Remaining `IN_PROGRESS` dependency classification

`IN_PROGRESS_DEPENDENCY_CLASSIFICATION.json` is the row-level authority. Counts sum to 1,431:

- locally implementable engineering remaining: 0;
- compound verification remaining: 1,211;
- provider-rights blocked: 4;
- activation blocked: 30;
- paid-spend/model blocked: 71;
- licensing/policy blocked: 20;
- language-cohort blocked: 15;
- forecast-cohort blocked: 22;
- actual creator-outcome blocked: 6;
- competitor-observation blocked: 33;
- physical-device/manual-accessibility blocked: 12;
- other genuine external dependencies: 7.

“Locally implementable engineering remaining: 0” means no remaining row lacks an implementation candidate after this audit. It does not turn the 1,211 unbound compound-verification obligations into verified rows and is not a milestone-completion claim.

## Manual and external gates

Physical-device and manual VoiceOver verification is open. `MANUAL_DEVICE_ACCESSIBILITY_CHECKLIST.md` defines the exact eight-step human check; browser emulation and axe results are not substituted for it.

The minimum next authorization depends on the capability being pursued. None is required to merge the fail-closed defect fix and evidence artifacts. Any activation work requires a separately scoped approval naming the test/production workspace and capability. Provider or competitor work additionally requires approved provider/account/data rights and policy/licensing basis; paid generation requires a spend/model cap; notification work requires channel and spend approval; empirical M2/M3 qualification requires authorized language, forecast or creator-outcome cohorts. Production Trends and provider execution must remain off until those approvals and the signing-key gate are satisfied.

## Database and release boundaries

Migration `040` is unchanged and its receipt hash remains `fbabec3c66efc22927e9c2974c3c08b6cda122a4272bf1c63dd50c7c13f5f9c0`. The unrelated existing `041` discrepancy was not changed or adopted. All database acceptance used disposable PostgreSQL. This candidate does not prove production database migration state, authenticated production UI behavior or an exact deployed revision; those require the release receipt after merge and deployment.
