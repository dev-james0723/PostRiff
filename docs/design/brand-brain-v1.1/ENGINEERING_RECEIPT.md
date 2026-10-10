# Brand Brain v1.1 engineering receipt

Status: implemented and automated validation passed; 39/41 acceptance criteria verified. Two criteria and the separate creator study retain human/device gates. Feature flag defaults OFF. No release approval or production deployment.

## Scope and source

Branch `codex/rafii-brand-brain-v11`, based on `4707b1304720c6bc4aaf67d8b9ceedd73df7ad06` from `consumer-saas`. The original dirty checkout was preserved. Supplied UX spec, Memory Integration Addendum, interactive concept and desktop/mobile images were read and remain in the local worktree. The remote repository is public, so original handoff documents/images are excluded from the PR; SOURCE_PROVENANCE.json records their hashes. `acceptance.json` tracks all 41 requirements and the separate human acceptance gate.

## Implementation

The existing `/app/workspace/brand` route renders Brand Brain only with `NEXT_PUBLIC_BRAND_BRAIN_V11=1`; otherwise it retains the legacy view. The flow covers retained writing, separate route permissions, local or quoted named AI analysis, per-trait evidence review, paired/guideline previews, owner activation, source ledger, immutable version history and safe restore. English, Traditional Chinese and Simplified Chinese use the existing locale resolver.

Canonical speaker/source/profile state remains authoritative. `VOICE.md`, `IDENTITY.md`, `BOUNDARIES.md`, `BRAND.md` and `AGENT.md` remain renderer outputs. New commands do not create a separate Markdown store or schema migration. Identity and boundary editing use canonical fields; learned preferences keep their own lifecycle. Composer, reply writer, Post Doctor rewrite and J04 reuse the same effective voice and Memory assembly.

Memory receipts record the actual included files, withheld/truncated fragments, route, voice revision and content-free digests. Explicit neutral mode omits voice and learned style. Cloud consent cannot override source grants or private/local-only boundaries. Current permissions and memory are rechecked at provider dispatch and completion/application.

Approval and restore require owner authority, current workspace/proposal/impact digests and explicit confirmation. Existing drafts need review and approved/scheduled posts are held. Restore creates a new version without restoring old permissions. Revocation removes retained evidence and blocks reuse. Legacy direct activation paths are also owner constrained.

## Verification boundaries

All Node/TypeScript/lint/build/browser/PostgreSQL validation runs on JCB/Depot. Local checks are limited to file inspection, Python syntax/JSON checks, shell syntax and Git diff checks. Browser tests use the built Next app, actual hosted Python handlers and disposable PostgreSQL, with synthetic identities and no mocked application API responses.

Injected model transports test quote/admission/settlement and exact paired inputs. They are not paid/live model acceptance. Free synchronous local runtimes can supply paired previews; deterministic templates are labelled as templates and unavailable comparable generation falls back to clearly labelled guidance. Paid/cloud/async preview routes are not silently used.

## Release and rollback

No migrations are added. The approved Brand Brain export is a read-only archive of the same canonical renderer; it carries no execution grants and is not a field-package import. Legacy field-package exports remain unchanged. No production flags, provider settings or deployments were changed. The branch is explicitly excluded from automatic Vercel Git deployment in `vercel.json`. Approval of this PR is separate from deployment or enabling the flag.

UI rollback: leave or return `NEXT_PUBLIC_BRAND_BRAIN_V11` to OFF. Data rollback: use the owner history restore flow with current permissions and impact confirmation. Do not replace the database with an old snapshot or revive revoked source permissions. Existing queue holds require normal explicit review/reapproval.

## Outstanding human gates

The supplied specification requires three unfamiliar creators to complete four tasks, a physical iPhone Safari pass and a human keyboard/screen-reader pass. Automated Chromium/WebKit and axe checks do not satisfy these human gates. Paid model behavior remains untested under the task's explicit restriction. Production readiness must not be certified until required human acceptance and any separately authorized provider acceptance are complete.

## Test results

Full remote run `89wk54dsx7` passed: **179 Python tests, five disposable PostgreSQL suites, lint (warnings only), TypeScript, 927 Node tests, production build and 26 browser checkpoints**. [Cloud run](https://depot.dev/orgs/jf34f85hr0/workflows/q49t8nlfx0?job=6dbxlk2wlh&attempt=2gr14rm7k0), [backend transcript](evidence/backend-r12.txt), [25 final backend source hashes](evidence/backend-r12.json), [browser proof](evidence/browser-r12.json), [named invariant mapping](BACKEND_EVIDENCE.md).

The browser matrix is Chromium 1440×1000, Chromium 375×844 and WebKit 375×844 with reduced motion. It exercises actual UI source storage/grants, pending analysis, guided and paired template previews, cancel/approve, history restore, source revoke, manual setup, identity/boundary writes, canonical five-file readback, independent person-level Rafii personality, denied cloud Memory, 44px Memory disclosures and ZIP export. Automated axe reported zero violations in each approved overview. Both Chinese scripts complete storage → analysis → review → preview → approval at 375px. No API responses are mocked.

Visual review of r12 screenshots found adjacent overview content links needed spacing. The two presentation/test files were updated. Final frontend run `42xct4v28b` passed lint, TypeScript,927 tests,build and all26 browser checkpoints, including the new spacing assertion. [Final cloud run](https://depot.dev/orgs/jf34f85hr0/workflows/dqvws3j7sr?job=tck18pdlgk&attempt=xmw5v3b24l), [final browser evidence](evidence/browser-final.json), [67 final changed-code/test hashes](evidence/final-source.json). At that checkpoint, backend source matched r12. Desktop and mobile final screenshots were visually inspected; the subsequent backend repair is recorded below.

Subsequent full PR CI found a background-worker dispatch compatibility failure in `postgres_consumer_campaign_worker.py`: the new preflight called the UI read helper, whose deletion-readback keyword is outside the worker's restricted transaction interface. Preflight now uses the normal transaction directly, retaining worker-bound authority and default deletion denial. Final backend run `g47rz51ls0` passed **179 Python tests and six disposable PostgreSQL suites**, including in-flight cancellation, restart reconciliation and no repeated provider call. [Cloud run](https://depot.dev/orgs/jf34f85hr0/workflows/g47rz51ls0), [final backend receipt](evidence/backend-r14.json), [transcript](evidence/backend-r14.txt). This supersedes r12 for backend source validation. The aggregate source manifest records these backend overrides; frontend source remains the r13-validated implementation plus the separately verified attachment fix.

Concrete failures repaired during validation: atomic manual context normalization, synthetic foreign-user fixture ownership, real Memory test setup, optional diagnostic fields, navigation module import compatibility, oversized-paste test consent reset, asynchronous source selection assertion, mobile first-fold spacing and sticky actions, associated checkbox labels, accessible select test matching, and legacy package export compatibility for approved Brand Brain profiles. Memory disclosure targets were also brought to 44px. Prior failed runs are diagnostic evidence only.

## Reproduce remotely

Use this isolated branch/worktree. Back up `.james-cloud-build.json` and `.depot/workflows/james-cloud-build.yml`, then run `jcb --config .james-cloud-build.brand-brain.json --force setup` and inspect `jcb doctor`. JCB currently submits the fixed workflow/primary mapping, so passing the custom config only at run time is insufficient. Run `jcb test` for the backend, `jcb e2e` for frontend/browser, or `jcb ci` for both. Poll the same remote run. Restore the two prior mapping files afterward; this PR preserves the established default cloud mapping. No local heavyweight fallback.

The harness builds Next with the flag enabled, then starts the built application and the actual Python/SQL backend on cloud loopback. Identity is synthetic, external browser destinations are blocked, and no application API responses are mocked. Only bounded synthetic JSON/PNG proof is exported through runner logs. The original input files are excluded from cloud validation uploads.


## Local validation and preserved state

Local checks: Python AST parsing, JSON structure/acceptance completeness, shell syntax, evidence SHA256 checks and `git diff --check`. No local Node/test/build/browser install or PostgreSQL suite. JCB primary config and workflow are restored byte-for-byte to their pre-task versions; the dedicated Brand Brain config remains. Original dirty checkout and unrelated work are untouched.

## Review status

Code and automated evidence are ready for engineering review. Human gates BB-18/MEM-16 and the three-creator study remain UNVERIFIED. This receipt does not authorize merge, deployment, feature activation, live paid models or publication. Normal PR CI is additional repository-wide evidence and must be checked before merge.

PR #174's initial Generative UI regression exposed an obsolete J04 assertion that expected direct summary-card approval. The card deliberately opens the canonical Brand Brain review, where current impact and owner confirmation are required. The test now verifies that review link and that no direct write action is available. This test-only follow-up does not change the 67 source/test files validated in the dedicated cloud runs. Its validation is recorded by the subsequent PR Generative UI check; the initial failure is retained in run `38077795361`.

Generative UI run `38078107188` then passed 400 Python tests, 227 web tests and six disposable PostgreSQL suites. Repository-wide regression also exposed two follow-ups: the plus-only attachment wrapper could shrink below its fixed 44px button, letting the adjacent model selector intercept clicks; and the security capability lock still described the permission table before Brand Brain. The attachment wrapper now retains its width, with desktop/mobile bounds and actual click/tap assertions. The repository capability metadata is versioned 1.3.2 with its recomputed hash; policy prose and integrity checks are unchanged. Candidate/backup diffs were retained locally before the metadata update. Failed runs `38078107207` and `38078107152` retain the original evidence. See PR #174's latest checks for these follow-ups; the dedicated 67-file source manifest remains unchanged, and `evidence/pr-followup-source.json` records the additional files.
