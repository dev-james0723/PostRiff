# Agent A — Future management harness preparation

**PREPARED ONLY. Runtime PostgreSQL / DDL / RLS / encryption tests / cloud execution NOT RUN.** Frozen Connect remains unchanged; no production/job/provider/remote Git actions occurred.

Owned new worktree: `e-management-validation`. Base management commit: `057062fb18490fac94443409c59b86a115bd5298`. Applied Karpathy Guidelines: preserve existing journal coverage, repair only concrete setup/selection defects, keep runtime code unchanged, verify static integrity without claiming runtime success.

## Concrete defects and repair

1. Existing management `setUpClass` replayed old131–133 twice; automation replayed them once. Old132 narrows `pr_metric_reads` to threads/instagram/mastodon and removes Pinterest. Both suites now share one fixture helper that applies current134 plus the byte-exact future management SQL and separately builds its concurrent indexes.
2. This G7-derived management base does not contain current134. Four exact source artifacts are bundled under `tests/fixtures/mastodon_after134_20261018`:134 from frozen Connect01c, future payload/metadata/index proposal from schema commit0114. `FIXTURE-LOCK.json` verifies each SHA before database work. Nothing was copied into runtime migrations or promoted for production application.
3. JCB excludes `docs/**`; reading future SQL from docs would fail after transport. Required SQL now resides under tests/fixtures, which this configured exclusion list includes. Evidence docs remain outside runtime inputs.
4. Existing broad/default validation includes `postgres_consumer_migrations`, whose generic planner replays all pending historical scripts and cannot represent the new timestamp-named fixture ledger. The new `management-after134-only` mode uses the existing `postriff_disposable_postgres.py` with only the existing management/journal and automation suites. It never selects the generic all-pending suite. Other broad modes are not certified for this new schema.
5. The old encryption cache assertion checked the unused literal `fixture-secret`, although the actual secret is randomized. It now checks the actual fixture secret is absent and decrypts the stored ciphertext to verify the returned app credentials.

The helper refuses non-Linux/non-CI, missing explicit fixture mode, non-loopback/nonstandard DSN, unexpected credential/routing environment and a server whose data_directory is not owned by the existing disposable runner. It does not adopt pre-existing Mastodon tables or unknown fixture markers. It executes the exact future payload, with its full preflight intact. A pre134 run must fail at the original missing134 guard before any DDL. Only the private disposable database receives expressly **synthetic prerequisite registry snapshots**; these do not prove the historical production migrations were applied there.

Before the core upgrade, it adds the known Pinterest provider admission to the synthetic baseline and inserts a synthetic Pinterest reading. The exact reading must survive unchanged. The helper applies current134, its truthful synthetic134 record, full future core and its distinct fixture ledger record, then runs each concurrent index command separately in autocommit. Both indexes must be ready/valid. A matching fixture marker permits the second existing suite to reuse this state without replaying non-idempotent DDL.

## Baseline security coverage

Static source mapping confirms `rls.sql` already loads007 for metric observations/definitions RLS, catalog/tenant/service policies and grants;035 for reads RLS, policies/grants and five indexes;006 for credential primary key;100 for credential privacy index;119 for restrictive browser-session policies on all three browser-readable metric tables. Together these account for all ten shared indexes and the captured shared metric policies/grants. No policy/index baseline rewrite or preflight stripping was added. Actual PostgreSQL17 catalog/deparse equality remains NOT RUN; the exact future preflight will refuse any mismatch.

Existing journal suite coverage is retained: application cache encryption/binding, tenant negatives before provider I/O, exact preview/digest/expiry, single committed action intent, concurrent confirmation, unknown-outcome no resend, credential rotation/revocation fences, disconnect serialization, health leases, retention, private result fences and native schedule reconciliation. Its original28 test methods remain, with four missing contracts added:

- Service-role CRUD over encrypted application cache, actions and health; actual cached cipher decrypts to the fixture secret.
- Service-role action/health composite foreign keys reject a different workspace's connection pair.
- All four reviewed metric providers remain admissible while an unknown provider is rejected.
- Native optional quotes use the actual integer field; legitimate0 is available, absent/boolean/negative/oversized/string values persist NULL/unavailable. The quotes dictionary name/version is verified.

Browser-role negative checks now also include health alongside cache/actions. Existing automation/Brand Brain/Queue integration is reused with injected provider/writer transports. No duplicate full CI, new provider calls, load suite or broad frontend build was added.

## Validation and handoff

PASS — Python AST for helper and both modified suites; Bash syntax for the targeted wrapper; diff whitespace;17 static source/hash/selection checks. All four bundled artifact bytes match immutable source; source/tree/test input closure is retained in `INPUT-CLOSURE.json`.

NOT RUN — any module import requiring psycopg/cryptography, PostgreSQL parser/DDL/RLS, service-role runtime assertions, concurrent builds, complete32-test journal suite, automation execution, backup/restore, external provider, production or cloud job. No runtime PASS is claimed.

Future approved cloud entrypoint from repository root:

`bash scripts/cloud-python-bootstrap.sh bash scripts/cloud-mastodon-automation.sh management-after134-only`

This is an entrypoint proposal, not an executed job or a new JCB mapping. Existing JCB `ci/test` aliases select unrelated/broader tasks; obtain the exact mapping, bounded runner/cost and source approval before submission. Do not substitute generic all/default validation. No local heavy fallback is allowed.

Integrate this harness-only commit into the new management integration tree with the other reviewed management changes, then regenerate the closure for that exact combined source before any approved cloud test. Do not alter frozen Connect or treat synthetic ledger/bootstrap fixtures as production migration, restore or public launch evidence.

Usage/cost comparison unknown. Only lightweight local static work ran; no paid job or external mutation submitted.
