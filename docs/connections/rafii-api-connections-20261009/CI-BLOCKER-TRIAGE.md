# CI blocker triage — PR #150

Audit date 2026-10-09. PR head `ed8d4bb6d3e951062456bf2680f54bc738e550e0` (docs only on top of application-code head `1956428296f43dfa4550bbcd111a4b47670e6f7d`). PR base `220d2de1…`; `origin/consumer-saas` is now `2af255fd…`. The extra commits are #151 (GenUI presenter, 3 files), with no overlap with this PR, and `git merge-tree` is clean.

## B1. `document-runtime`: BLOCKED (infrastructure); owner: Library/CI lane

| Run / attempt / job | Head | Result | Exact cause (from job log) |
|---|---|---|---|
| 37986228759 / 1 / 114009022473 | `19564282` (code head) | **success** | Pulled `amazonlinux:2023` from Docker Hub at index digest `sha256:8ed3c0a9…e73f`; `test_library_preview` ran 10 tests, OK; Lambda image `public.ecr.aws/lambda/python:3.12@sha256:049c15df…14af` pulled |
| 37990798335 / 1 / 114024125139 | `ed8d4bb6` | failure | `docker run amazonlinux:2023` → Docker Hub `toomanyrequests` (unauthenticated pull rate limit). No test ran. |
| 37990798335 / 2 / 114034241799 | `ed8d4bb6` | failure | Docker Hub token server `auth.docker.io` request timed out (`Client.Timeout exceeded`). No test ran. |

Root cause, **VERIFIED**: the workflow pulls the unpinned tag `amazonlinux:2023` anonymously from Docker Hub (`.github/workflows/library-release.yml:73`). Two independent Docker Hub failures followed: throttling, then token-server unavailability. It is not image selection and not this PR's code. The runner's general networking was fine: the same runners checked out code and later steps reached other hosts.

The acceptance standard is not met yet. There is no `document-runtime` PASS at the exact candidate head `ed8d4bb6`. The code is identical to `19564282`, where it passed, but that is supporting evidence, not acceptance.

### Repair proposal (implementation-ready; for the Library/CI owner, not committed from PR #150)

Pull the same Amazon Linux image from AWS's own public registry, pinned by digest:

```diff
-          docker run --rm -v "$GITHUB_WORKSPACE:/work" -w /work amazonlinux:2023 bash -euc '
+          docker run --rm -v "$GITHUB_WORKSPACE:/work" -w /work \
+            public.ecr.aws/amazonlinux/amazonlinux:2023@sha256:12052e9b5d3fd85769abbdd863dd038e1890c9ace31d5fdbe1afa78eda97d061 bash -euc '
...
-            --entrypoint /var/lang/bin/python3.12 public.ecr.aws/lambda/python:3.12 \
+            --entrypoint /var/lang/bin/python3.12 public.ecr.aws/lambda/python:3.12@sha256:049c15dfc70e1efbb857b27d21f39bdd53245380521a3cff6035cc6ac94414af \
```

Verification done in this audit (anonymous, read-only registry API, 2026-10-09):

- `public.ecr.aws/amazonlinux/amazonlinux:2023` index `sha256:12052e9b…d061` → amd64 manifest `sha256:3552faf4…d247` → single layer `sha256:7234d0a9b6ba1270c7bb653ee62a443a1dbb6fdfa833336edd3c0691c2524d1f` (54,630,770 bytes).
- Docker Hub `library/amazonlinux:2023` index `sha256:8ed3c0a9…e73f` (the one the passing job used) → amd64 manifest `sha256:500790b3…fb96` → **the same single layer** `sha256:7234d0a9…524d1f`, same size. The root filesystem is byte-identical; only the config and attestation wrappers differ.
- ECR Public is AWS's official publisher for Amazon Linux. The second step already trusts it for the Lambda image. Anonymous pulls need no new credentials, secrets or paid service.

Owner follow-ups:

- Refresh pinned digests deliberately (for example monthly, or when AL2023 security updates matter), never by floating tag.
- Optional: cache with `docker save`/`actions/cache` keyed by digest. Not required for determinism.
- Do not add a Docker Hub login or a third-party mirror.
- Keep the `dependency-lock` job and the `test_library_preview` assertions unchanged.

Acceptance after the owner's change: `document-runtime` PASS on the candidate head that includes it, with the image digest visible in the log.

## C1. Library browser WebKit 1440 `/preview` runtime error: UNVERIFIED root cause; owner: Library lane (#144)

Evidence (all re-checked in this audit):

| Run / job | Head | Result |
|---|---|---|
| 37973259495 | #138 `74cb0452` (before PR #150 existed) | FAIL: `browser runtime errors (webkit 1440)`, `…/library/files/<id>/preview due to access control checks.`, `library-production-browser.cjs:617` |
| 37986228759 / attempt 1 / 114009022850 | #150 `19564282` | FAIL: same signature at line 613 |
| 37986228759 / attempt 2 | #150 `19564282` (identical head) | PASS |
| 37990798335 / attempt 1 / 114024124860 | #150 `ed8d4bb6` | PASS |
| 37981366670 | #150 `c6de568c` | PASS |

Classification: **intermittent, pre-existing, not a PR #150 regression** (VERIFIED). PR #150 changes no Library, API-client or shared web file. The root cause is **not established** (UNVERIFIED).

What the code shows (read-only):

- The request comes from `DocumentFirstPage` in `web/src/features/library/asset-thumbnail.tsx` (`useQuery` → `api.libraryPreviewUrl`).
- The `queryFn` ignores React Query's `signal`. `client.ts` `get()` sets only `AbortSignal.timeout(90_000)`. So unmounting the card, deleting the asset or invalidating the query never aborts the in-flight fetch; only closing the context or navigating does.
- `refetchInterval` is 4 min and retries are `count < 32` for 409/429, otherwise 1.
- The test collects `page.on('pageerror')` only into `errors`. It already traces `/library/files/...` requests, responses and `requestfailed` reasons in `uploadTrace` (`isUploadRequest`), but does not write that trace to `browser-failure.json`. That is why the artifact cannot identify the blocked request's status or timing.
- Hypotheses, none reproduced:
  - (H1) a preview fetch is aborted by context close or navigation while still in flight, because it isn't cancellable on unmount;
  - (H2) the preview for the just-deleted document is re-requested and 404s;
  - (H3) a WebKit-specific mapping of a failed or cancelled same-origin fetch to the "access control checks" console text, surfaced as `pageerror`.

### Handoff to the Library owner (implementation-ready, in the owner's branch)

1. **Instrumentation first** (test only, no assertion change). In `library-production-browser.cjs`:
   - add a `previewTrace` array, filtered with `/\/library\/files\/[^/]+\/preview/`;
   - push `{t: Date.now(), event: 'request'|'response'|'requestfailed'|'finished', status, failure, phase: navigationPhase, engine, width}` from the existing `request`/`response`/`requestfailed`/`requestfinished` listeners (sanitize with `relevantUploadUrl`);
   - push `{t, event: 'delete-confirmed', assetId: doc.id}` when the DELETE response arrives;
   - add `page.on('console', m => m.type() === 'error' && /preview/.test(m.text()) && previewTrace.push({t, event: 'console', text: sanitized}))`;
   - include `previewTrace`, `uploadTrace` and `errors` in `browser-failure.json`.
2. **Distinct cases to reproduce** (Chromium and WebKit at 1440, then the existing matrix): cancellation on unmount, 404 after deletion, 401/403 rejection, 409/429 retries, context close mid-flight. Identify which one produces the `pageerror`.
3. **Candidate fix, only after reproduction.** Pass React Query's `signal` through `libraryPreviewUrl` into `get()`, combined with the 90 s timeout via `AbortSignal.any([signal, AbortSignal.timeout(90_000)])`. Disable the query (or treat 404 as terminal) for assets removed from the listing. Keep 401/403 surfacing as today.
4. Keep `assert.deepEqual(errors, [])`. Do not filter or mute it.

## Status

| Blocker | Owner | Status |
|---|---|---|
| document-runtime image pull | Library/CI lane | BLOCKED. Repair proposed above; candidate-head PASS required |
| WebKit `/preview` pageerror | Library lane (#144) | UNVERIFIED root cause. Instrumentation handoff above; passes on the final head |
