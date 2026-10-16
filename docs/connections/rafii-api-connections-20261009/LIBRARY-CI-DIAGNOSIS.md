# Library WebKit 1440 failure on PR #150: diagnosis

> Superseded by CI-BLOCKER-TRIAGE.md §C1 (the audit adds the `uploadTrace` finding and the owner handoff). Outcome: attempt 2 of run 37986228759 PASSED on the identical head `19564282`, and the Library browser job passed on `ed8d4bb6` (job 114024124860).

Recorded 2026-10-09. This is diagnosis only: the Library code, the test and its assertions are unchanged.

## Failure

- Run 37986228759, job 114009022850, head `19564282`. Artifact `universal-library-80f67d8e…` (id 11643478150).
- `web/tests/library-production-browser.cjs:613` expects zero browser runtime errors for WebKit at 1440 px. It collected one `pageerror`:
  `…/api/workspaces/<test-workspace>/library/files/<test-file>/preview due to access control checks.` RSC failures: none.
- The synthetic harness logs (`durable-backend.log`, `durable-frontend.log`) don't record per-request lines, so the artifact cannot show the blocked request's status or which asset it belonged to.

## Regression or this PR?

| Evidence | Result |
|---|---|
| PR #150 diff | Touches no Library, API-client or shared web code. The web change is limited to `web/src/features/founder/settings/*`, which the Library test never renders. |
| Same signature elsewhere | #138 branch `74cb0452`, run 37973259495 (18:36Z, before PR #150 existed): same WebKit 1440 `/preview … due to access control checks` and the same zero-runtime-errors assertion (line 617 there). #138 `e97a79d0` (run 37986101854) also failed the Library workflow, at a different line (381). |
| Same workflow passing | PR #150 earlier head `c6de568c` (run 37981366670) passed. Branch `claude/rafii-genui-firstpass-20261009` `13240d96` (run 37986339426) passed at the same time. |
| Re-run of the identical head | Re-run of the failed job only (same run id 37986228759). Outcome is recorded in RELEASE-RECEIPT.json. |

Conclusion: an intermittent, pre-existing WebKit failure in the Library browser acceptance test, not introduced by PR #150. The root cause is **not established**.

## Code path

- The request comes from `DocumentFirstPage`'s React Query loader in `web/src/features/library/asset-thumbnail.tsx`, which calls `api.libraryPreviewUrl` (`web/src/lib/api/client.ts`, 90 s `AbortSignal.timeout`). It re-fetches every 4 minutes and retries on 409/429.
- Leading hypothesis, unproven: a preview fetch is in flight when its card unmounts (the test deletes that document just before the assertion) or when the context closes. WebKit reports the aborted or failed same-origin fetch with its generic "access control checks" text.

## Owner boundary and next repair

- Owner: the Library lane (#144 `claude/rafii-intelligent-library-20261008`; #134 introduced the first-page thumbnails). Its branch is still running this workflow. No commit, PR or comment found mentions a repair for this signature.
- PR #150 does not change Library code or the test, and does not mute or filter the assertion.
- Suggested next step for the Library owner: in the test, record `requestfailed` and `response` events for `/library/files/*/preview` (status, failure text, timing relative to the delete). That establishes the cause. Then fix the app path, for example by cancelling the query on unmount or treating a 404 for a deleted asset as handled. Do not filter the runtime-error assertion.
