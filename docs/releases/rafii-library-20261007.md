# Rafii Universal Library production release

Execution state: candidate; not yet production released.

Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-universal-library-production-20261007`

PR: https://github.com/dev-james0723/PostRiff/pull/116

Baseline production SHA: `91f6572c46fe9c357ca23ba43524f1ea3f27814e`

Baseline deployment: `dpl_9Jiq5wtAzg7iwJHC7DqW5kbJw8en`, `https://postriff-phase2-private-krdqhkp5i-jamesau0723-6572s-projects.vercel.app`

Rollback: promote the baseline deployment using the existing Vercel project, retain all Library tables/private files. Do not drop schema, erase objects, or downgrade unrelated production work. Pause Library ingestion via code rollback if required. A newer production deployment requires a refreshed rollback baseline before release.

Migrations: apply only verified 093 and 094; do not automatically apply unrelated ledger gaps. Each is additive and keeps legacy media/state paths; 094 widens lifecycle checks and reconciles the staging candidate filename check. Production has no Library tables or bucket at baseline. Staging has an earlier manually provisioned 093 candidate. Preserve historical applied bytes and record exact new checksums.

Remote validation: JCB `6jcw5k5078` passed 36 unit tests and existing disposable PostgreSQL Library checks. JCB `4ssm6cjmrt` passed extended real parser/DB lifecycle and typecheck, then failed four frontend accessibility lint errors, repaired in the next candidate. Identity/storage in this harness are synthetic; it is not production acceptance.

Remaining gates: cloud build/lint/browser/security and full CI, exact production schema/bucket configuration, merge/deploy, authenticated production file and regression acceptance. No paid transcription/model calls are enabled by this release.
