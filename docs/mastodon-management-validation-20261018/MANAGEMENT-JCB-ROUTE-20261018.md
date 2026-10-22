# Dedicated management-after134 cloud route — candidate

This follow-up makes the isolated management harness selectable through JCB. It is local preparation, not a submitted cloud job or deployment. Base: `bb4f38b322ad5fbc4d9011e7a3a56f97bfec66e4`.

The dedicated config `.james-cloud-build.mastodon-management-after134.json` maps only `ci` to the new package script. After integration and separate job approval, the proposed invocation is:

```sh
jcb --repo "$MANAGEMENT_WORKTREE" --config "$MANAGEMENT_WORKTREE/.james-cloud-build.mastodon-management-after134.json" ci
```

`MANAGEMENT_WORKTREE` must be the actual final combined management worktree. The release owner must regenerate its final source closure and reconcile the allowed cost before submission. No final sanitized snapshot is claimed here.

The route reuses `cloud-python-bootstrap.sh` and the focused PostgreSQL 17 mode `management-after134-only`. Python discovery selects every `test_mastodon_*.py`, including an integrated `test_mastodon_polls.py` and all classes in `test_mastodon_management.py` (including `MastodonNativeFormatGateTests`). Five relevant existing shared adapter/metrics contract modules follow. The SQL mode runs only the two existing management/automation suites against the pinned synthetic after134 fixture, preserving full future-SQL preflight and Pinterest coverage. It never selects the generic all-pending migration runner.

Six existing channel/connect/publishing/receipt/calendar UI contract files, lint, typecheck and the localhost-configured build complete the route. Actual browser E2E, real OAuth and production acceptance remain **NOT RUN**. No document, standalone YouTube, scale/load or browser suite is selected.

The generated workflow has one manual, contents-read-only job on `depot-ubuntu-24.04-4`, a 45 minute timeout, empty environment allowlist and `persist-credentials: false`. Local fallback remains disabled. The installed JCB controller hardcodes `.depot/workflows/james-cloud-build.yml` and checks exact renderer parity even with `--config`; the generated canonical workflow is therefore included in this management-only candidate. Original JSON configs, the frozen Connect worktree and the pending Connect approval packet are untouched. Use the exact dedicated config for this candidate; other configs require their own matching generated workflow.

Validation: **17 static checks PASS**, installed controller pure detect/render parity PASS, Bash syntax and Git whitespace checks PASS. See `MANAGEMENT-JCB-ROUTE-STATIC.json` for file/controller hashes and exact checks. Doctor, provider health, snapshot generation, remote execution, Node/Python suites, SQL runtime, build and browser checks are **NOT RUN**. Runtime validation is unavailable until a separately approved cloud job; static checks do not establish test success.

An initial composite shell file-write was rejected by the cloud guard because its here-document contained future Node commands. No workload executed. Files were subsequently edited through the patch tool; the guard and global tooling were not changed.

Cost: no job submitted and no paid operation initiated. Runtime price/invoice and token usage are unknown. This route does not authorize a paid job, production SQL, provider calls, publication or release.
