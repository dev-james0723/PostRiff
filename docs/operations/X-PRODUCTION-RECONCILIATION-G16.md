# X G16 — production-preserving release candidate

## Release boundary

This is isolated engineering, not public acceptance or permission to deploy. Preserve PR #214 and its qualified `41a7c54aeb2262d3b35062fec939080d34b2274c` source. This branch descends from it and restores already-live integration code so an X release does not remove another platform. No real customer identity, X provider receipt, charge, schema mutation, staging build or production promotion is asserted.

Canonical targets remain Vercel `postriff-phase2-private` and Supabase `buoyhkbodnhzngaotoel`; never substitute the old staging project. Git automatic deployment remains globally disabled. The local optimized browser build uses loopback fixture routing and MUST NOT be deployed.

## Production source preservation

The recovered input manifest of live deployment `dpl_yKAToJbvjRdQRmCS3RLKHTYegqUr` contains 2,217 hash-verified paths. Its historical Git SHA remains unknown; recovered bytes are not invented historical Git provenance.

Compared with PR #214, 61 live paths differed: 15 were intended X-only changes, 34 required preserving live code/configuration, and 12 needed three-way reconciliation. Thirty-three files were restored byte-for-byte. The old live `vercel.json` per-branch autodeployment setting was deliberately NOT restored: `git.deploymentEnabled=false` stays in force. Nine shared files merged without textual conflicts; three files required explicit preservation of both platforms' independent consent and dispatch guards.

`X-PRODUCTION-PRESERVATION.json` records exact inherited-file hashes and reviewed overlaps. Tests enforce those 33 files and the no-autodeploy policy. The resulting comparison is 2,189 unchanged live paths, 28 intentional X/shared/policy differences, zero missing live paths and zero unclassified differences. Restoring live code does not certify that its original features have provider approval. The existing Pinterest private-trial, quota, account binding, visibility and consent restrictions remain intact.

## Pending-OAuth disconnect defect

A real local HTTP/PostgreSQL test reproduced a 500 response when an X customer disconnected while another OAuth callback was pending. The old code wrote `outcome='disconnected'`, which the real OAuth CHECK constraint does not permit. Provider revocation could already have occurred before the database transaction failed.

The corrected X path records the existing valid outcome `denied`, consumes the pending transaction, removes its verifier, expires it, cancels queued work, and retains the existing account/credential-generation fences. Tests prove that the old callback cannot exchange, new interactive consent can reconnect, and old approvals do not resume. This does not weaken or replace the existing outcome constraint.

Both Chromium desktop and WebKit mobile acceptance now exercise pending consent -> disconnect -> rejected stale callback -> visibly disconnected account -> new explicit reconnect, in addition to media approval, per-step receipts, separate post approval, exact media readback, schedule cancellation and tenant denial. All identities and provider responses remain synthetic; the actual Rafii HTTP, SQL, PKCE and application code runs.

## Migrations 131–135 and rollback

Migrations 131–134 are still pending production approval. They are applied only to disposable databases by acceptance. Actual database roles are tested: anon and authenticated cannot read the direct or cost tables; the service role retains its explicit server-side privileges. The synthetic full-schema role setup matches the observed production service-role BYPASSRLS attribute, without granting privileges in production.

Migration 135 is now conservative and bounded. An already-effective validated exact rule is a catalog-only no-op; its constraint OID is preserved. Only the known legacy length rule is upgraded. Missing, unvalidated, NO INHERIT or unexpected rules fail closed. The upgrade is rechecked under an exclusive lock, with a five-second lock timeout and thirty-second statement timeout. Tests cover legacy upgrade, exact no-op, unknown-policy refusal, and client-role isolation. Alternate PostgreSQL expression formatting deliberately requires review rather than guessing equivalence.

Rollback is forward-compatible containment: disable X admission/dispatch and keep journals, approvals and provider receipts intact; restore only an independently qualified compatible application deployment. Do not DROP the new journals, erase cost counters or replay uncertain writes. The cost-controller tests continue to reject old-binary inserts that would bypass the new durable grant counters. Any destructive DB recovery needs separate approval and verified backup/PITR evidence.

## Verification and reviewer scope

Use `scripts/x_direct_acceptance.py` with the pinned requirements, Node and Playwright dependencies. The runner now includes inherited Pinterest regression and an explicit opt-in no-egress local OAuth/SQL lifecycle fixture. It records exact source manifests before/after and stops only its own disposable servers. The new OAuth tests also run directly with `RAFII_X_LOCAL_OAUTH_E2E=1`.

The complete repository's secret scanner is unchanged. Three restored zero-network test constants were reviewed and permitted by exact path+hash only: two synthetic redaction sentinels and the example.com `user:pass` negative URL test. There is no broad file/directory exemption, credential verification or real secret in those fixtures.

Author review and test evidence are not independent external approval. A second reviewer must examine the three manual shared-file merges, OAuth disconnect ordering, migration 135's recognized expressions and the exact release source. Do not approve this PR using the author account as a substitute for independent signoff.

## Remaining human and hosted acceptance

The original X app's current registered callback, API entitlements, transfer pricing, finite provider billing cap, and consenting ordinary non-owner customer still require authenticated nonsecret Console evidence. No current Console login or real customer consent is supplied by this branch. The prior US$0.10 identity-only allowance is not a publishing/media budget.

Before any external effect, bind explicit authorization to the final SHA, canonical schema plan, exact test account/content/media/scheduled time/cleanup actions, current per-endpoint pricing and total allowed spend. A separately approved production-target staged build must verify its immutable Git source and actual deployment artifact before a further alias-promotion approval. The existing live alias and independent working integrations must remain untouched until those gates pass.

Current verdict: **engineering candidate only; PUBLIC PRODUCTION NO-GO until actual provider/customer and hosted release gates pass**. Poll/tagged-user or other unimplemented/unverified operations must remain accurately disabled; a complete public API catalogue is not a claim of universal entitlement.

## G16 Linux PostgreSQL closure (2026-10-20)

On GitHub PR #214 at source `28304f2c30d0c24882629f6b73fcf16c9751aae7`, X source-bound CI passed; general release gates executed 133 disposable PostgreSQL scripts and failed exactly two inherited cross-platform scripts, not X provider dispatch. They were **not skipped or silenced**:

- `postgres_pinterest.py` referenced a quota migration and a private trial journal missing from the *merged source package*. Recovered their actual previously committed bytes from peer-agent Git history: `20261014_pinterest_rate_budgets.sql` from `6d36716cfcc945fcc93a819ba243ffa870a1a799`, and `20261017_pinterest_trial_journal.sql` plus its guarded rollback SQL from `730d044078434638f31eb5ca0e57280307ff8317`. Original worktrees are unchanged. The restored SQL explicitly narrows `service_role`, denies `TRUNCATE`, forces RLS, preserves already consumed quota and aborts rollback while intents exist. One isolated real PostgreSQL run of the full Pinterest integration script passed, including quota concurrency and negative tenant/permission assertions. No canonical Production migration was executed.
- `postgres_rapv2_acceptance.py` expected sensitive session-revocation actions to succeed with synthetic JWTs carrying only `iat` (not an AMR method). Runtime security correctly refuses such sessions. The fixture now injects a signed *session-bound* password AMR timestamp on regular synthetic sign-in, and reuses the exact timestamp during JWT refresh. Tests explicitly asking for missing AMR still send `amr=[]`. This does **not** relax `verified_auth_time`, Session Security, MFA, or account-hold controls. The 126 real-disposable-Postgres RAPv2 acceptance rows all passed; negative cases RAP-016 (missing AMR), RAP-021 (stolen device cookie), RAP-036 (stale TOTP/refresh) and RAP-150 (revocation survives flag-off) stayed passing.

The repair is under an isolated follow-up Commit and still requires all same-SHA GitHub release workflows to pass before an **engineering** GO. This does not establish Provider, public-customer or Production approval. Preserve the live-alias source, X cost authorization, customer consent, no-automatic-billed-retry and app rollback gates as described above.

## Browser history-import receipt race — evidence and bounded readback (2026-10-20)

On GitHub commit `bcbedfcf6fac6593d032a1dccf64de16e995510f`, the remaining general release gate passed PostgreSQL, Python, lint, types, optimized build, source secret scan and dependency checks, but failed the synthetic History Import Browser check at `web/tests/history-import-browser.cjs:63` because an *immediate subsequent* API GET showed `none` while the UI displayed `Import queued`. This was a single read observation; evidence does not establish missing database durability or a product regression.

A separate, no-egress disposable Hosted API + PostgreSQL reproduction returned `POST 202 pending` and `GET 200 pending` on the same import. A local Next dev + real Chromium + disposable Postgres end-to-end run also completed every acceptance step. These isolated results do **not** prove the optimized Linux proxy had no race.

The browser acceptance test now captures the **actual** POST 202 server receipt (not the optimistic UI), requires its `pending` status, no-store header and UUID-shaped `importId`, then requires a fresh no-store GET to return `pending` for **that exact importId**. A bounded wait covers transient earlier views without retrying the POST or accepting another operation, wrong state or an uncommitted record. If durable state is not demonstrated within the bound, CI remains RED. UI review, user consent, throttle, provider failure, permission revocation, cancellation and data-purge requirements are unchanged.

This improvement is CI evidence handling only; it cannot be used to claim Production Readiness or a real provider test. Next step: re-run exact same-source Mac and standard GitHub Ubuntu browser gate, and investigate further if the optimized path fails again.

## G17 migration 133 bounded-lock regression (2026-10-21)

The production preflight identified an unbounded `ACCESS EXCLUSIVE` lock acquisition in `133_x_cost_approval_grants.sql`. This isolated candidate adds `SET LOCAL lock_timeout='5s'` and `SET LOCAL statement_timeout='120s'` immediately after `BEGIN`, before any DDL. These are transaction-local settings, not global database configuration. The lock is still required for the legacy cost-window migration; do not remove it to force availability. An operator must still explicitly approve the schema change and verify safe backup/PITR, installed migration history, the restored schema and compatible prior app binary before a production migration.

`tests/test_x_migration_lock_pg.py` protects this policy with a static contract check and an actual isolated PostgreSQL 17 concurrency test: a parallel `ACCESS SHARE` read holds the cost window table, the candidate exclusive lock is refused within 5–9 s (`SQLSTATE 55P03`), the transaction leaves no `postriff.x_cost_grants` table behind, and after unlocking the unchanged script applies successfully without activating an X app. Both tests passed (5.358 seconds total). The tests accept **only** an explicit `RAFII_X_TEST_DATABASE_DSN` under `/tmp/rafii-x-g14-pg-*/socket`, never production connections. All providers remain synthetic and no external X requests are made.

Independent human review has not yet signed this or any other release candidate. The actual Production database has migrations 131–134 absent and a validated equivalent OAuth constraint for 135, and X's provider Billing Cycle Cap was observed as Unlimited on 2026-10-20; no live migration, publishing or spending is authorized.

## G17 dependency-audit closure — Pillow 13.0.0 (2026-10-21)

GitHub Actions run [39620959152](https://github.com/dev-james0723/PostRiff/actions/runs/39620959152) for `5c2302d9d402434a03ad290c7e02337ac49a045c` passed PostgreSQL migrations/restore, Python contracts, web contracts, TypeScript, optimized build, source secret scan and product copy; the **Dependency Audits** step then failed before browser acceptance. The downloadable `ci-python-audit.json` identifies eight known advisories for exactly one package, `Pillow==12.3.0`, with all findings listing `13.0.0` as fixed. The final checkout warning is an unrelated existing orphan vendor gitlink, **not** the actual failing audit step.

The scoped fix pins `Pillow==13.0.0` in `requirements.txt` and the inherited Universal Library Amazon Linux document-renderer workflow. The guard `tests/test_x_pillow_dependency_security.py` checks both pins and was RED against 12.3.0, then GREEN against 13.0.0; no security gate, Python audit or package warning is ignored or downgraded. Verified current PyPI Pillow 13.0.0 is available for Python 3.12/3.13 and was released 2026-10-16. Official notes: https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html (Python 3.10 removal, legacy palette/image API changes; the documented changes do not apply to the core Rafii image-decoding surfaces tested).

A **separate, isolated** Pillow 13.0.0 installation under `/tmp/rafii-x-pr214-pillow13-compat-20261021` passed 100 targeted image/thumbnail/media-related tests. `pip-audit -r requirements.txt` scanned 46 production dependencies with **zero known vulnerabilities**, and the real NPM audit found **zero** vulnerabilities. Evidence is stored under `~/Documents/Rafii-X-Connect-Today-20261017/G17-Production-Preflight-20261021/pillow13-*`; no existing shared developer virtualenv was modified.

The Linux-only `test_library_preview` sandbox uses `libseccomp` and Linux-specific virtual-memory limits. On macOS it failed with exactly the same 14 failures / 11 errors under both Pillow 12.3.0 and 13.0.0 (missing Linux seccomp symbol and unsupported RLIMIT), so its local failures are **not** evidence of a Pillow 13 regression or proof of Linux compatibility. The unchanged Ubuntu / Amazon Linux Library CI must complete with the 13.0.0 wheel before this change earns whole-project engineering GO. Continue to fail-closed if CI finds other newly disclosed advisories; do not add allowlist exemptions, disable audit or suppress vulnerabilities.

**Public release remains NO-GO** until production rollback evidence, exact-scoped X access, a finite X billing cap, actual consenting non-owner OAuth, separate owner grants for paid live tests/schema/staged build, and independent release signoff. No production deployment, database write, provider call, budget change or publication resulted from this dependency fix.

## G17 Linux hosted-runtime Preflight regression (2026-10-21)

GitHub run [39628512477](https://github.com/dev-james0723/PostRiff/actions/runs/39628512477) for `49d5b2fead4a90c4f85fcb35299939de850e8e43` installed the **actual** Python 3.12 Pillow 13.0.0 wheel successfully but failed exactly one of 5,588 Python domain tests: `HostedDeploymentPreparationTests.test_structure_preflight_passes_and_keeps_external_choices_pending`. This is not an image decoder crash. The old `scripts/check_postriff_hosted_preflight.py` structural gate was still hardcoded to `Pillow==12.3.0`, so it incorrectly rejected the security-patched Production `requirements.txt`. The same test failure was reproduced locally with Pillow 13.

The minimal fix keeps the preflight's Python 3.12 and pinned psycopg requirements, but now *requires* the audited `Pillow==13.0.0` instead of the vulnerable old pin. Two additional fail-closed tests ensure that a patched release passes while the known-vulnerable 12.3.0 still fails. Both new tests were RED before this preflight edit; after the edit, the complete 14-test Hosted Deployment/Pillow Security module is GREEN using the isolated Pillow 13 virtualenv. The original Cloud Developer settings, OAuth, billing, FKs, RLS, release flags and deployment configurations were not changed. Ubuntu end-to-end Python/DB/Library workflow completion on the newest SHA is still required before Engineering GO.

A separate legacy `studio/requirements.txt` continues to pin Pillow 12.3.0, and is **not** the pinned dependency consumed by this Rafii Production CI or this isolated PR's Root/Library package. It is recorded as separate Studio security follow-up rather than silently modifying another Agent's independent product. No Production or Studio deployment was done.
