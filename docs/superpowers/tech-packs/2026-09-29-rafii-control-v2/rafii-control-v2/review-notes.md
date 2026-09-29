# Design review and validation notes

## Corrections made during v2 review

- Replaced the stale assumption that notifications and chart infrastructure must be created from scratch.
- Preserved the existing customer agent's forbidden effects and single-workspace authority.
- Revised the v1 same-project hosting recommendation for v2's expanded privilege and execution scope.
- Distinguished user-approved support access from exceptional investigation authority.
- Separated recurring MRR from cash collections and one-time credit purchases.
- Added reactivation explicitly to the MRR bridge instead of silently omitting it.
- Distinguished code failures from runner/disk failures and required checks from skipped checks.
- Kept actual business outcomes separate from model estimates, technical fixes and associated recovery.
- Kept all model/detector/external-action activation off pending approval and qualification.

## Scope of verification

`validation-report.json` records serialization, JSON Schema, example, reference and selected semantic consistency checks for this artifact. The 96 product acceptance cases remain NOT RUN. Nothing here certifies a live application, vendor account, complete security audit or production deployment.

The formatted reader is self-contained and has no external scripts. HTML structure and internal links were validated. A browser visual preview was blocked by the local browser's file-navigation policy; see `reader-qa.json`. No browser policy bypass was attempted. The Markdown remains the authoritative complete text.

The initial OpenAPI covers the intelligence surface. The full retained support, finance and account workflows are specified in the master; their exact adapters must be reconciled against current source before implementation. The schemas do not replace semantic authorization, provider qualification or business-policy review.
