# Candidate approval — one private-Trial cloud delta validation

Prepared 2026-10-17. **REVIEWABLE CANDIDATE / NOT EXECUTED.** This document authorizes nothing by itself. Production remains on the separately verified e2e5169f release; this candidate covers cloud validation of the unpublished private-Trial changes only.

## Verified billing boundary

Existing Depot org **jf34f85hr0 / James Cloud Build**, Developer US$20/month. Billing period **October12–November1**, invoice November1. The authenticated dashboard shows **29,512 Depot CI minutes used /2,000 included**, so included Depot CI allowance is exhausted. Additional CI is **US$0.00005/second/vCPU**. Unlimited usage is selected. Upcoming invoice **US$185.08 is an estimate**, not a finalized charge. No credit balance is displayed. Docker and GitHub Actions allowances are separate and do not establish free Depot CI execution. [Read-only receipt](evidence/trial-billing-preflight-20261017.json).

Existing CLI authentication is usable. Network-enabled `jcb doctor` passed, exit0; the earlier generic authentication error concealed restricted-network DNS failure. No login, new grant, upload, run or billing-setting change occurred.

## Intended single-run scope

Exactly **one job, 8vCPU**, from this isolated worktree. The cloud-only command is `bash ../scripts/cloud-python-bootstrap.sh bash ../scripts/cloud-pinterest-release-delta-validation.sh`, invoked from web/ through `jcb ci`. The shell script must first include **test_pinterest_private_trial**, **test_pinterest_trial_visibility**, **test_pinterest_private_trial_recovery** and **test_pinterest_analytics**, alongside its existing targeted regression set, seven disposable PostgreSQL scripts, Node bridge coverage, Next type generation/typecheck/lint/build and synthetic Pinterest browser checks. No real Pinterest/API traffic or customer credentials.

**Concrete candidate: exactly one existing JCB job,8vCPU, with its unchanged provider hard timeout45minutes.** At the observed rate, the compute ceiling is **US$1.08** (8×2,700seconds×US$0.00005). Expected timing is not guaranteed; the earlier baseline took178seconds. Existing storage/cache or other metered charges may apply: this is **not a US$1 total hard cap**, and this task cannot cap concurrent organization usage. No second run, automatic rerun or larger runner is included.

The installed JCB generator hardcodes timeout-minutes:45; doctor/run require byte-identical generated workflow, and depot ci run has no timeout flag. Do not promise10minutes/US$1, patch the global controller/guard, or substitute a shell timeout as a provider job cap. The revised45minute/US$1.08compute terms require explicit approval before this paid run. No paid submission has occurred.

## Exact reversible mapping, after the root freezes source and receives cost approval

1. Save byte-for-byte backups and SHA256 of this worktree's `.james-cloud-build.json`, `.depot/workflows/james-cloud-build.yml` and `web/package.json` under one owned /private/tmp directory. Record current fingerprints first; stop if another owner changes any mapping path.
2. Temporarily repoint the existing package script `ci:pinterest:production:jcb` to the delta command above. Restrict JCB tasks to `{"ci":"ci:pinterest:production:jcb"}`. Explicitly set **runner.ci = depot-ubuntu-24.04-8**: current JCB otherwise selects its **16CPU build runner for ci**, despite validation being8CPU. Keep org, baseRef, runtime, lockfile, cache scope and `localFallback:false` unchanged.
3. Preserve the secret exclusions and `envAllowlist:[]`. Remove only `studio/**` from inputExcludes if needed by the existing imports, as in the prior reviewed Pinterest route. Never upload `.env*`, credentials, Keychain/browser/SSH stores, local skills or blanket home content. Docs and evidence stay excluded. The sanitized remote patch is necessary to test unpublished source; no Git push is required or included.
4. Generate only the reviewed mapping using `jcb setup --force`, inspect the resulting single ci job, runner and actual45minute timeout, then run one network-enabled **`jcb doctor`**. Any different/unbounded route stops before paid submission.
5. Freeze the actual implementation: record Git HEAD, complete included-input SHA256 inventory, mapping hashes, script/test hashes and sanitized Snapshot `sourceHead`, `baseSha`, `sourceFingerprint`, `patchBytes`, `changedPaths` and source marker. Frozen product commit **730d044078434638f31eb5ca0e57280307ff8317**,18files. Product/test/migration source is fixed; later receipt-only commits do not change its included implementation inputs. Mapping hashes/fingerprint are recorded after the reversible mapping and before any paid submission; unexpected product differences stop execution.
6. Only after explicit cost approval of the finalized source and disclosed45minute compute boundary, invoke **one `jcb ci`**. Poll/reconcile that exact run ID; do not resubmit after an uncertain CLI outcome. Retain remote run/job/attempt IDs, source marker/fingerprint, final status, logs, test counts and actual timing. Cancel that same run if the approved bound is reached; a failed or timed-out run requires separate approval for another paid run.
7. Restore only the three owned mapping files to their saved bytes, after checking they still equal this task's temporary versions; otherwise preserve the concurrent changes and stop for reconciliation. Verify restored hashes. Keep the implementation changes and evidence.

## Acceptance and exclusions

PASS requires the exact frozen source fingerprint remotely, all targeted tests and browser checks passing, no credential/provider traffic, and mapping restoration. Reuse e2e5169f's unchanged scoped evidence rather than rerunning the full project. This is synthetic/disposable validation only; it cannot close real OAuth, publication, scheduling, Analytics, third-party-user or Standard Access gates.

This proposed approval covers one sanitized source upload and one bounded **paid validation job only**. It excludes Production flags/deployment/SQL, OAuth consent/scopes, Pin/board writes, Standard submission, external publication, new resources/subscriptions, plan changes and Git push. These remain separate concrete approval items.

**Still required:** the user's explicit approval of this one45minute/8vCPU paid run. Delta script includes all three private-Trial modules. No paid execution has occurred.
