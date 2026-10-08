# Rafii Universal Library production release

Execution state: candidate; production migrations, merge, deployment and authenticated acceptance remain gated on the current release checks.

Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-universal-library-production-20261007`

PR: https://github.com/dev-james0723/PostRiff/pull/116

Baseline production SHA: `91f6572c46fe9c357ca23ba43524f1ea3f27814e`

Baseline deployment: `dpl_9Jiq5wtAzg7iwJHC7DqW5kbJw8en`, `https://postriff-phase2-private-krdqhkp5i-jamesau0723-6572s-projects.vercel.app`

Rollback: promote the baseline deployment using the existing Vercel project, retain all Library tables/private files. Do not drop schema, erase objects, or downgrade unrelated production work. Pause Library ingestion via code rollback if required. A newer production deployment requires a refreshed rollback baseline before release.

Migrations: production preflight found no Library tables, policies or bucket. Staging has 093 and the lifecycle migration applied, with zero Library assets. A staging audit found the private 50 MiB bucket lacked accepted audio MIME types; additive 095 preserves the existing document/generic MIME types and adds all 11 audio containers. It also initializes the full 23-type list when the bucket is absent. Staging verification reports private bucket, 50 MiB, 23 MIME types, and all required upload types. Applied staging history: `universal_library_storage_mime_types` at `20261007234839`. Source SHA-256: 093 `9d35962f93afbe56d4ad6dc6f7a9fed1c25f422334747118d1242e8e29e5b5d8`; 094 `313ab91df771656b7d77d8532c901ec744f3ca371e6a5d942452b0c5055308df`; 095 `083b5b298b8dd3656fffc6dfb3b654e914899a293c3d45a7c081e854d40b981a`. All three are additive; rollback retains private rows and objects.

Remote validation: JCB `4ssm6cjmrt` passed parser/disposable-PostgreSQL lifecycle checks and typecheck; JCB `n9wzg809vd` passed cloud lint after explicit control labels were added. Local single-test check `PYTHONPATH=src:tests python3 -m unittest test_site_agent.ToolTest.test_catalogue_pin` passed after the two Library read tools were added to the pinned catalogue. Dependency-lock preparation run `37703884929` reported zero vulnerabilities and changed only patched versions of Sharp, tinypool and source-map-js, with no package entries added or removed. On head `49738d466c81cde326ba81da2e0ce67696577246`, all 36 parser/unit checks and disposable PostgreSQL lifecycle/MIME assertions passed, and the hosted PostgreSQL path fix brought the browser stage up. That run stopped at its direct `/api/auth/verify` request because the browser harness omitted the required `X-PostRiff-Request: founder-alpha` application guard, now fixed. On head `353c79d17338dd6f9ab2b0f516b67fd0b261a81d`, parser, database, typecheck, lint, and build stages passed; the UI upload then timed out before the test Markdown asset appeared. The current test change records the API listing and visible page state on that failure; the latest cloud rerun is pending. Synthetic identity/storage checks are not production acceptance.

Remaining gates: current-head release/browser/security and regression checks, production migrations, merge/deploy, authenticated production file/permission/search/source/deletion acceptance, and runtime-error review. Automatic audio transcription is unavailable; uploaded audio supports playback and user-supplied, searchable transcripts. No new paid service or paid model call is enabled by this release.
