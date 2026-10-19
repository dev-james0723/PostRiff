# G7 — Canonical Rafii Production backup, RLS and migration audit
Read-only review 2026-10-17 · Production Supabase buoyhkbodnhzngaotoel (PostgreSQL 17.6)

## Backup and independent Restore

- The logged-in **Production** Supabase Dashboard displayed **eight PHYSICAL backup entries**, each with a Restore action. "Restore to new project (BETA)" is offered. PITR page displays "Enable add-on": PITR is not presently enabled.
- Physical backups existing is not proof of the latest snapshot timestamp, completeness, decryptability, Storage media availability or an independent successful Restore. No Restore/new project was initiated, no backup file was downloaded, and no key/secret was read. Latest backup's timestamp remains NOT VERIFIED.
- Supabase documents Restore to New Project for physical backups; it creates a new project that incurs compute/storage billing. User has **not approved** that extra resource yet. Any independent Restore must preserve source Production, sanitize/exclude customer PII from test outputs, verify 62-ledger/row/role/index/Auth/Storage coverage (and explicitly document what's not included), and prove encryption-key custody without disclosing keys.
- No PITR enablement during G7. PITR is extra hourly billing, outside Spend Cap according to the provider. Daily physical backup RPO is not second-level.

## Exact custom migration parity — PASS

- Live SELECT from postriff_private.schema_migrations returned 62 name+SHA rows; fresh side-by-side digest comparison with fixed source G6 candidate: **62/62 match, zero missing, zero mismatched, zero duplicate migration sequence prefixes**. Full receipt G7-PRODUCTION-LEDGER-READONLY-20261017.json; independent parity G7-LOCAL-PRODUCTION-LEDGER-PARITY-20261017.json.
- No Production Mastodon migration applied and no pr_mastodon_applications, pr_mastodon_actions or pr_mastodon_health relation. Actual active Mastodon connection aggregate count: **0**.
- Pending SQL:
  - 131_mastodon_management.sql SHA c85e2d27f79947692a1bf28a7087fcbe7b0d3ea9d3c57e2e0fe2dd654bacf694
  - 132_mastodon_native_metrics.sql SHA c3a887b379958bdb32282120f6b9dc5515b02882da279898453fedb8f7886d3b
  - 133_mastodon_connection_health.sql SHA eeae6a4f48fb7616ce168f672c05d6ba7e169aa91951c17fc1c4c187fb437905
- These are planned future writes, NOT authorized or applied. Existing scripts/postriff_migrate.py explicitly permits --apply-local on a LOOPBACK target only. It is not a Production migration runner. Never bypass its guard. A specially reviewed release operator must atomically apply SQL and insert precise hashes in the **custom** ledger after backup proof; a Supabase platform migration record alone is insufficient.

## Static SQL security review

- 131 creates encrypted Mastodon dynamic-app cache and exact-action journal; 133 creates credential-bound health leases. Both enable and FORCE RLS on new tables and grant SELECT/INSERT/UPDATE/DELETE to service_role only, revoke PUBLIC/anon/authenticated. Foreign key (workspace_id, connection_id) is backed by existing pr_encrypted_credentials PRIMARY KEY.
- 132 changes the existing pr_metric_reads_provider_check to add 'mastodon', writes three metric definitions and creates retention/recovery indexes. Existing pr_metric_definitions PRIMARY KEY exactly (provider,metric,definition_version), compatible with the proposed ON CONFLICT.
- Existing pr_metric_reads is ~88 kB with ~1 estimated live row, pr_metric_observations ~48 kB / ~6, and pr_metric_definitions ~32 kB / ~12 at audit time. Although small, ALTER TABLE DROP/ADD CONSTRAINT and CREATE INDEX still take locks and may block concurrent sessions. Proposed Production SQL must use a reviewed single advisory-locked transaction, bounded lock_timeout e.g. 2s, statement_timeout e.g. 30s, no automatic retries and immediate independent postcondition audit. Timings are planning constraints, not tested Production assertions.
- **Corrected RLS audit:** pr_metric_reads and pr_metric_observations each have PERMISSIVE tenant_read USING postriff_private.member(workspace_id) and RESTRICTIVE rapv2_browser_session USING postriff_private.browser_session_ok(). PostgreSQL combines the permissive access with restrictive via AND. Both FORCE RLS. Function member(wid) checks active membership for auth.uid(); browser_session_ok() validates auth/session/MFA. Therefore the initial worry of an OR-only session policy causing cross-tenant reads was WRONG and was retracted upon direct inspection of pg_policies.permissive. No evidence of this exposure; **do not change those policies in this release**.
- Existing security Advisor summaries: 21 INFO notices rls_enabled_no_policy, 1 WARN extension_in_public; unrelated existing notices requiring independent triage, not evidence of Mastodon table public access. Do not disable RLS to silence a warning.

## Production approval-specific release checklist

1. Verify EXACT Production ref and admin operator; latest backup timestamp and independent Restore result, cost approval and immutable source (no preview dependency).
2. Freeze exact source SHA and SQL digests, check previous 62 hashes at apply time, provider CHECK/current metrics compatibility, and restricted authorized writer session. Dry-run SQL on independently isolated PostgreSQL 17.6 prior to Production.
3. Prepare reviewed remote-aware operator with advisory lock, one transaction, timeouts and custom ledger insertion, disallow the wrong account/staging connection, forbid destructive actions, fail closed on any mismatch. Source script remains local-only.
4. Get a new explicit owner approval **for the exact 131/132/133 transaction** after item 1–3. Apply once. Independently read back all 65 ledger rows and table RLS/privileges, metric continuity and multi-tenant negatives.
5. Leave review/live-post flags OFF. Only after owner-controlled REAL Mastodon OAuth + disconnect can Connect be considered for invited Beta.

**DECISION: 62/62 historical ledger and RLS static review PASS; Backup record presence PASS; independent Restore + exact Production mutation approval NOT SATISFIED; schema application NO-GO.**
