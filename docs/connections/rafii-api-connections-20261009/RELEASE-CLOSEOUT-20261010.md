# PR #150 release closeout (2026-10-10)

This supersedes the status claims in FINAL-ACCEPTANCE-REVIEW.md, CI-BLOCKER-TRIAGE.md and the earlier RELEASE-GATE-MATRIX.json wherever they differ. The matrix was rewritten with this file.

All facts below were observed from 2026-10-09 23:50Z to 2026-10-10. Anything not observed is labelled UNVERIFIED, NOT_RUN or EXTERNAL_BLOCKED.

## 1. State reconciliation

| Item | Observed |
|---|---|
| PR #150 | Draft, open, 0 formal reviews, mergeable CLEAN. Head was `36693c06` at the start. |
| Production base | `origin/consumer-saas` = `de4e5907` (#138 YouTube revocation fence). Production `dpl_4mAFnvUjrhzZVcYNir4TMXxvfHCH` serves rafii.io with `sourceRevision=de4e5907`. |
| Base drift since #150's base `220d2de1` | #151 and #138. That is 96 files and migrations 098–100 and 106. None of these files overlap with #150. |
| Merge | Clean merge `66d259a8`. |
| #138 semantics | No change to the vault columns the overlay reads (`refresh_supported`, `refresh_ciphertext`, `access_expires_at`, `revoked_at`). `authorization_generation` is not read. |
| Branch protection on `consumer-saas` | None (HTTP 404). No rulesets. No required reviews or checks. |
| Vercel | Git integration: every merge to `consumer-saas` builds and promotes production for `postriff-phase2-private` (rafii.io, www.rafii.io). |
| OpenUI canary freeze | The morning production freeze on 2026-10-09 (A log, ~06:51Z) has no "lifted" record. However, the release owner A merged #148 itself at 18:41Z, and #149, #151 and #138 merged later. A's latest log entries (to 21:11Z) are canary E2E runs on production. No active freeze is observed. |

## 2. CI image supply (Stage 2): DONE

| Item | Detail |
|---|---|
| PR | #155 (`claude/rafii-ci-image-digests-20261009`, `c2a2092b`), merged into #150 at `87d82bd3`. |
| Images (pinned by index digest) | Builder: `public.ecr.aws/amazonlinux/amazonlinux:2023@sha256:12052e9b5d3fd85769abbdd863dd038e1890c9ace31d5fdbe1afa78eda97d061`. Unchanged; amd64 manifest `3552faf4…`, single rootfs layer `7234d0a9…`, built 2026-09-29.<br>Runtime: `public.ecr.aws/lambda/python:3.12@sha256:145350008f3f67d82c0bc6ecd34d9eb0c95aecf11f9b69db6bab7de3d5d3cc61`. This is newer than the triage candidate `049c15df…`, which is superseded on purpose; amd64 manifest `9531d396…`, built 2026-10-09. |
| Verification | Done through the anonymous ECR Public registry API. AWS is the publisher. |
| Acceptance run | 38006730627 / job 114077116739 (#155). The log records both RepoDigests at `linux/amd64` and `lambda python 3.12.15`. The builder ran `test_library_preview` with 10 tests OK. The read-only Lambda image (non-root, `--cap-drop=ALL`, no-new-privileges) also ran 10 tests OK. |
| Repeat passes | document-runtime also passed on #150 at 87d82bd3, 65205edc and 45b564ff. |

## 3. Library WebKit `/preview` failure (Stage 3): root cause verified; fix in PR #161

**Root cause.** WebKit refuses any fetch a page starts *after its own navigation has begun*. It surfaces this as a page error, "Fetch API cannot load … due to access control checks.", and the request never reaches the server. Chromium sends these requests silently. The Library triggered it like this:
- `DocumentFirstPage` re-polls `/preview` every 3 s on 409/429, up to 32 times.
- At 1440 px more document cards are visible, so a retry was usually pending.
- When a retry fired during the harness's reload or goto, WebKit raised the error.

**Ruled out:** in-flight cancellation, 404 after delete, 401/403, the 409/429 responses themselves, and the 90 s timeout.

**Evidence:**
- Deterministic reproductions: runs 38007791885 and 38009215686.
- Earlier precedent: the same text on RSC prefetches in run 37791668166, fixed by e9619ec4.

**Fix (#161, head `4fe1655b`):**
- `libraryPreviewUrl` takes React Query's `signal`, combined with the 90 s timeout.
- After `beforeunload`, preview requests wait instead of fetching. They resume on `pageshow`, or after 15 s if the navigation is abandoned.
- The thumbnail passes the `signal`.
- `browser-failure.json` now carries the preview console errors, the delete-confirmed event and the upload trace.
- `assert.deepEqual(errors, [])` is unchanged.

**Regression proof:**
- Old vs new, run 38009874544: on old code the browser test fails and 4 of 5 unit tests fail. On new code, unit tests pass 5/5 and the real WebKit + Chromium teardown test passes 8/8.
- #161 library job 114090244670 passed, including Chromium + WebKit acceptance at 1440 and 390.

**Ownership:**
- #161 merges cleanly into consumer-saas.
- Against #144 it adds no new conflict regions. #144 already conflicts with consumer-saas in `tests/phase2/rls.sql` and `library-production-browser.cjs`.
- #161 is **not** bundled into #150. It changes production Library client behaviour and belongs to the Library owner's review.

## 4. Engineering acceptance (Stage 4)

**Fixes since `36693c06`** (application code head is now `45b564ff`):

| Finding | Source | Severity | Fix | Proof |
|---|---|---|---|---|
| `client_binding_missing` is not in the `pr_connection_health.connection_state` CHECK (060). The hourly multi-row upsert would abort for every customer, and do so every minute. Production has exactly 1 YouTube credential in that vault state (refresh retained, `refresh_supported=false`). | Adversarial review | **High** | Store it as `reauthorization_required`, with state `blocked` (same remedy). | Guard test parses the 060 CHECK and every Channels-card state. Real-PostgreSQL test `test_youtube_vault_overlay_projects_inside_the_060_check` passed in local-foundation (65205edc job 114083786001; 45b564ff run 38009690934). |
| A capped projection could read as complete with exact counts. | Adversarial review | Medium | `CHANNELS_SQL` drops skip-rows: id regex, configured-but-disconnected with Python-equal falsiness, and `DISTINCT ON` with last entry wins. | Same PG test includes invalid-id, duplicate, unverified and falsy-JSON channels. |
| An empty capped projection reported tenants as an exact 0. | Codex | P2 | `queue(partial=…)` uses the coverage from `build()`. | `test_capped_projection_without_attention_rows_is_unknown_impact_not_zero` |
| The panel kept showing "Current" past the stale window. | Codex | P2 | 5-minute `refetchInterval`. A cached fresh envelope expires on the client at `lastCheckedAt + staleAfterSeconds`. | Panel tests |
| Refreshable YouTube rows were still flagged by `founder_risk`. | Adversarial review | Low | No grant deadline is stored for refreshable grants. | `test_founder_ops` projection test |
| Non-boolean JSON falsiness and duplicate order | Adversarial re-review | Low | SQL falsiness now matches Python. Ordinality tiebreaker added. | PG test |
| Synthetic leak marker flagged by the secret scanner | CI | n/a | `docs/consumer-ready/secret-allowlist.json` entry (path + hash + reason). | library job pass |

**Accepted residuals:**
- **Low:** a YouTube channel revoked only in the vault, with no verified identity and no account id in its JSON, is filtered out. The connect path always records the account id.
- **Low:** if the overlay fails, refreshable YouTube rows fall back to `token_expired`. This is a false alarm, not a false all-clear. It is logged by error class.

**New automated verification:**

| Gap from the triage list | Test |
|---|---|
| No writes and no provider calls from the route | `ReleaseAcceptanceTests.test_live_route_only_selects_and_never_opens_a_network_connection`. Runs through the real `PostgresStore` and `PostgresFounderStore`. It checks:<br>• every statement is SELECT/SET;<br>• both reader transactions are `SET TRANSACTION READ ONLY`;<br>• the vault is never read;<br>• no network connection is opened (`socket.connect`, `create_connection` and `getaddrinfo` are refused). |
| Founder-only access, MFA in production, environment, role | `test_production_route_requires_a_fresh_mfa_founder_session`. Checks:<br>• aal1 and stale MFA (>300 s) are refused at exchange;<br>• an aal1 session gets 403;<br>• a session from another environment gets 401;<br>• a non-founder role gets 403;<br>• none of these reaches the reader. |
| Suspended operator, anonymous caller, capability, Demo/Live | Existing tests (unchanged). |
| No leaks in results or errors | `test_responses_carry_no_tokens_credentials_or_workspace_identifiers`: tokens, client secret, receipt URL with a query string, workspace/connection ids, `_tenantKeys`. `test_unexpected_failure_returns_a_fixed_error_without_private_detail`: 503 `SOURCE_UNAVAILABLE`, no exception text. |
| YouTube revoked / expired / refreshable / binding, end to end | `test_youtube_vault_states_reach_the_queue_with_the_right_classification` and the PG test |
| Clock skew | `test_projection_stamp_from_the_future_is_unknown_not_fresh` |
| Malformed approvals, truncation, partial coverage, incident-store failure | Existing tests, plus the new capped-coverage test |
| Settings panel states | `web/tests/founder-connections-panel.test.cjs` (9 tests). Covers:<br>• loading, inaccessible (403 shows a permission state), error with retry, empty, degraded (named unreadable sources, impact unknown), populated (lower bounds, estimates, owner, next action, truncation, registry);<br>• query wiring: mode, cancellation signal, gated on the session, polling. |

**Validation results:**

| Where | Check | Result |
|---|---|---|
| Local (narrowly targeted Python) | `control.test_founder_connections`, `test_founder_ops`, `test_founder_slices`, `test_boundary` | 122 OK |
| Remote: JCB → Depot | node suite | `vcttm52g10` and `7df32dd12q`: 858/858 |
| Remote: JCB → Depot | typecheck | `hwcdnpgvgr`, `jsw10d6f24`: exit 0 |
| Remote: JCB → Depot | lint | `4gp9zjx1dz`, `xds7qqf2k5`: 0 errors (23 pre-existing warnings) |
| Remote: GitHub Actions on code head `45b564ff` | Full configured matrix, 7 workflows, all success | Growth Studio 38009690915<br>Rafii Control foundation 38009690934 (602 tests incl. PG, OK)<br>Universal Library 38009690899 (library Chromium+WebKit, document-runtime)<br>Rafii browser scenes 38009690938<br>Founder admin browser 38009690913<br>Rafii Generative UI 38009690895 (agent-ui, agent-ui-browser)<br>Rafii local release gates 38009690888<br>Vercel preview `C1ckZ1ZkrhqHSn69o7nuRUCVFfo9` |

At 87d82bd3, agent-ui-browser failed once with WebKit "Target page, context or browser has been closed". The same WebKit-crash family appears on #152 (run 38005868943, "Target crashed") on the same production base. PR #150 touches no agent-ui code, and the check passed on 65205edc and 45b564ff. Classified as pre-existing flake (UNVERIFIED root cause; not in scope).

**Independent review:**
- Codex CLI fallback: `codex review --base origin/consumer-saas` (codex-cli 0.160.0) found 2 P2 issues, both fixed. This was not the plugin.
- Fresh-context adversarial review (two passes) found 1 High, 1 Medium and 4 Low, then confirmed the fixes: "no remaining Critical, High or Medium issues".
- No formal GitHub review exists. None is required by branch protection, and none was self-approved.

## 5. Provider approvals (Stage 5)

- `RECORDED_DECISIONS` stays empty.
- docs/youtube/public-launch records OAuth verification, the YouTube API audit and the quota extension as **NOT SUBMITTED**, with no application ids or provider decisions.
- The observed default 100 uploads/day is a Console reading, not a decision receipt.
- So every registry requirement is `check_required`, and the read-only Founder panel says so.
- No scopes were expanded, no grants created, no applications submitted, and publishing was not enabled.
- YouTube read-only remains `LAUNCH_SCOPE`.

## 6. Requirement status

| Scope | Requirement | Status |
|---|---|---|
| IN_SCOPE | Route authorization (founder, `control.read`, aal2 + fresh MFA, environment, suspended, anonymous, Demo/Live) | VERIFIED (synthetic, real Boundary/ControlApplication) |
| IN_SCOPE | No writes or provider calls from the route | VERIFIED (real store classes, statement log, socket refusal) |
| IN_SCOPE | No sensitive data in results or errors | VERIFIED (synthetic) |
| IN_SCOPE | YouTube classification incl. `client_binding_missing` | VERIFIED (synthetic + real PostgreSQL) |
| IN_SCOPE | Freshness, unknown ≠ 0, truncation, partial coverage, skew, incident failure | VERIFIED (synthetic) |
| IN_SCOPE | Settings panel states | VERIFIED (render tests) |
| IN_SCOPE | Production signed-in Founder MFA readback | see section 8 |
| IN_SCOPE | Observed hourly refresh in production | see section 8 |
| IN_SCOPE | Rollback | Readiness VERIFIED (target `dpl_4mAFnvUjrhzZVcYNir4TMXxvfHCH` READY, `isRollbackCandidate`, CLI `vercel rollback` present). A live drill is NOT_RUN: it would move live traffic. |
| EXTERNAL_BLOCKED | Google brand/sensitive-scope verification, YouTube audit, quota, Meta/TikTok app reviews | `check_required`; owners are the provider app owners |
| OUT_OF_SCOPE | Broader API Connections roadmap (RELEASE-RECEIPT.json acceptance A02–A36 except A23/A29–A31) | Unchanged NOT_RUN or BLOCKED_PROVIDER. Not converted to PASS. |

## 7. Release mechanics (Stage 7)

- Merging to `consumer-saas` triggers the Vercel Git production build and promotion. A separate unassigned production build is not part of this project's flow. The PR preview build (`C1ckZ1Zk…`) is not treated as the production artifact.
- Preflight: all checks pass on the final candidate; rollback target recorded (ROLLBACK.md); production baseline recorded.
- Post-deploy, run in this order:
  1. `/api/health` `sourceRevision` equals the merge SHA, and the deployment id is recorded.
  2. Anonymous `/api/control/v2/connections/attention` is denied.
  3. Runtime errors are checked.
  4. The hourly projection moves YouTube `expired/token_expired` to `blocked/reauthorization_required` at the next refresh.
  5. Signed-in Founder MFA readback.

## 8. Production result

Recorded in RELEASE-GATE-MATRIX.json (`G-PROD-*`) when it happens.

