# Rafii Control v2 tech pack

Prepared September 29, 2026. Design only. Nothing is deployed or activated.

## Start here

Read `rafii-control-v2.html` for a self-contained formatted reader, or `rafii-control-v2-spec.md` for the authoritative editable text.

The design contains a full v1 reevaluation, separate founder deployment, existing Rafii agent integration, analytical workbenches, decision/revenue loop, continuous monitoring, exact-SHA engineering workflow, retained support/billing/account controls, data/API architecture and rollout gates.

## Package map

- `catalogs/metrics.json`: proposed versioned metric contracts.
- `catalogs/dashboards.json`: questions, metrics, renderers and caveats for each visualization.
- `catalogs/integrations.json`: selected/optional integrations and qualification gates.
- `catalogs/detectors.json`: proposed detector rules, all disabled.
- `catalogs/action-policy.json`: deny-by-default authority and executor boundaries.
- `catalogs/acceptance-cases.json` and `.csv`: required future product acceptance cases, all NOT RUN.
- `contracts/openapi.yaml`: initial intelligence surface, not every existing product API.
- `contracts/*.schema.json`: structural validation contracts; semantic authorization remains mandatory.
- `examples/`: synthetic fixtures, never real business data or execution receipts.
- `research/sources.md` and `.json`: official source and pinned repository evidence register.
- `validate_pack.py`, `validation-report.json`: document/contract consistency checks only, not app tests.
- `manifest-sha256.json`: file-integrity manifest, excluding itself.

## Important boundaries

Repository source snapshot: `dev-james0723/PostRiff` at `d91660b7936a5158b820914107306ad4a1e51c2d`. This is not production deployment evidence. The Mac connector was quota-blocked, so no local write-back is claimed. Suggested future destination: `docs/superpowers/specs/2026-09-29-rafii-control-v2/`.

No new integration is provisioned. No task is scheduled. No payment, notification, customer account, code change, PR or deployment is executed. All budgets, domains, commercial policies and privileged activation require explicit verification/approval.

## Validate this package

Use Python 3 with `jsonschema` and `PyYAML`, then run `python validate_pack.py` from this folder. This checks the delivered artifact contracts and fixtures. It does not run the 96 application acceptance cases or test live services.
