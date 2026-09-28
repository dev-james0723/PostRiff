# Current requirement evidence reconciliation

Canonical release base: `822f25d21138be18dbcd0eb7d3d2bcb1baff87cc`. Stable IDs and exact source text remain preserved.

Current counts: NOT_APPLICABLE=154, IN_PROGRESS=1431, VERIFIED=167, BLOCKED_EXTERNAL=19.

All 107 prior `IMPLEMENTED_UNVERIFIED` rows now have current source-bound local acceptance evidence. The 10 prior `NOT_STARTED` rows are operation-scoped `BLOCKED_EXTERNAL`; none was converted into speculative local provider work.

The current pass also promoted 29 directly evidenced compound obligations, including source deletion/retention, the M1 definition-of-done subcontracts, trust inspection/recomputation, and the minimum stored Radar flow. M1/M2 remain open; M3 remains capability-by-capability.

Validation: 1,026 Trend Python tests (784 pass plus 242 database-only skips), 584 disposable PostgreSQL tests, 108 real Next/API/PostgreSQL browser assertions, and 16 strategy assertions. Provider calls=0, model calls=0, paid external spend=$0.

See `evidence/m1m2-acceptance/acceptance-tests.json`, `IN_PROGRESS_DEPENDENCY_CLASSIFICATION.json`, `M3_CAPABILITY_MATRIX.json`, and `MANUAL_DEVICE_ACCESSIBILITY_CHECKLIST.md`. Synthetic evidence is not empirical cohort or production qualification.
