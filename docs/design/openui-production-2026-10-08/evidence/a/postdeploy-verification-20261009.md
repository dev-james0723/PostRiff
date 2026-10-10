# Post-deploy verification — production dpl_F5FApgN9MnHZvybjbF9SvHtSB3xF (94ca0dbd)

Release owner A, 2026-10-09 (UTC). Logged-out and read-only checks only. Signed-in checks (canary, live sample,
journeys, drills) are recorded separately; nothing here substitutes for them.

## Identity of what is deployed

| Fact | Evidence |
|---|---|
| PR #137 merged as 94ca0dbd207cff9c4a20122f1a4f72adb20bf792 at 2026-10-09T01:00:13Z | `gh pr merge 137 --merge --match-head-commit 671974aa…` |
| Production deployment dpl_F5FApgN9MnHZvybjbF9SvHtSB3xF, target production, READY, meta githubCommitSha 94ca0dbd | Vercel MCP list_deployments(sha=94ca0dbd) |
| rafii.io and postriff-phase2-private.vercel.app serve it | 05:59Z: `/api/health` sourceRevision=94ca0dbd on both; HTML `data-dpl-id="dpl_F5FApgN9MnHZvybjbF9SvHtSB3xF"` on both |
| Deployed tree = PR head tree = CI merge-ref tree | `git rev-parse 94ca0dbd^{tree}` = `671974aa^{tree}` = 23aec2c4d0f2c190bab119277bc12d532cad8818; GitHub API commit 8e8da8a7 (strict CI merge ref, parents a522482e + 671974aa) tree = 23aec2c4… |
| Strict acceptance CI on that tree | run 37865089349 attempt 2 (pull_request, head 671974aa): agent-ui 113613049648 success, agent-ui-browser 113613048624 success; gate records 27/27 (evidence/g/results/ci-671974aa.json) |
| Rollback target | dpl_HE8oWvF5TMF7xo63rgS26NSVB3WR (a522482e, PR #136) |

## Logged-out route smoke (G22 route order, partial G24)

Same probe script before (production a522482e, 2026-10-09 ~01:05Z) and after (94ca0dbd, 06:03Z). No credentials sent.
W = canary workspace id, R = random uuid.

| Probe | Before (a522482e) | After (94ca0dbd) |
|---|---|---|
| GET /api/health | 200 JSON, sourceRevision a522482e | 200 JSON, sourceRevision 94ca0dbd |
| GET /api/me | 401 unauthenticated | 401 unauthenticated |
| GET /app, /app/agent | 307 → sign-in | 307 → sign-in |
| GET /api/workspaces/W/agent/status | 401 | 401 |
| GET …/agent/ui/presentations/R, …/events?after=0 | 401 JSON | 401 JSON (no stream opened) |
| POST …/agent/ui/queries, actions/activate, actions | 403 permission_denied (application guard) | 403 permission_denied (application guard); edits and state also 403 |
| same POSTs with the non-credential request marker | — | 401 unauthenticated (never 5xx) |
| GET /api/control/v2/agent/ui/presentations/R | 404 SCOPE_DENIED (path unmapped) | 401 AUTH_REQUIRED (path now mapped to copilot.use, reaches the auth check) |
| POST /internal/agent-ui/validate (no HMAC) | 200 text/html (catch-all page; route did not exist) | 401 JSON {accepted:false, errors:[unauthorized]}, x-matched-path /internal/agent-ui/validate |
| POST /internal/agent-ui/validate (well-formed bogus HMAC) | — | 401 JSON (not 503, so the validator secret is configured; value never read) |
| GET /internal/agent-ui/validate | — | 405 (POST-only route) |

No 5xx and no Set-Cookie on any probe. Source check: the `ui` resource branch in agent_runtime_v2/http.py runs after
`require_session_token` and matches `parts[4] == "ui"` exactly (no existing resource is named `ui`); vercel.json is
unchanged versus a522482e; web/src/proxy.ts excludes `internal/` so the validator is not redirected to sign-in.

## Database (read-only, Supabase buoyhkbodnhzngaotoel, 06:15Z)

The six pr_ui_* tables exist with RLS enabled and forced, one service_only policy each; authenticated/anon have no
SELECT. Indexes match migration 102 (including the partial unique one-producer index on pr_ui_attempts). n_tup_ins = 0 on
all six tables: GenUI has not yet persisted anything in production. This is expected before the signed-in canary, and
it means the end-to-end path (Python → Node validator round trip, SSE, persistence) is **not yet proven in production**.
Old-reader compatibility: production a522482e (no GenUI code) ran from ~23:08Z to 01:03Z with migration 102 applied and
showed no error cluster.

## Install telemetry (G14, build side)

Production build log of dpl_F5FApgN9 (01:00:34Z): `npm warn install-scripts 2 packages have install scripts not yet
covered by allowScripts: @openuidev/lang-core@0.3.2 (postinstall: node ./postinstall.cjs), @sentry/cli@2.58.6 …` —
npm 11 did not run the OpenUI postinstall. Independently, OPENUI_TELEMETRY_DISABLED was set to `1` for Production and
Preview by A on 2026-10-08 13:10 (value recorded at write time; it is a sensitive variable and cannot be read back).
The lazily loaded GenUI client chunk is only reachable signed in; its byte scan is in CI (e2e:devtools-not-shipped,
0 chunks) and is repeated against production during the signed-in canary.

## Adversarial review (workflow wf_e4c3b10f-ceb, 5 checkers + critic)

Refuted overclaims, accepted:
- Logged-out probes cannot pass G20, G22 or G24 by themselves. G24 needs the signed-in smoke and positive activation;
  G20 needs the existing suites (green in CI on tree 23aec2c4, see above) plus a signed-in production check; G22 needs
  the migration rehearsal (CI PostgreSQL jobs apply 102 on a disposable database) plus the route smoke above.
- The before column above comes from A's own probe at ~01:05Z (session transcript); per-deployment URLs of a522482e are
  SSO-protected, so it cannot be re-taken.

Defects found and handled:
- Medium: the GenUI cron steps swallowed exceptions without a log line. Fixed on the follow-up branch:
  `genui_cron_summary` puts counts or the error class name in `cron.completed` and raises it to WARNING on failure
  (tests/test_rafii_cron_summary.py).
- Low: the validator's internal-error path returned `validator_error` without any log. Fixed: logs
  `genui.validator_error` with the error class only.
- Low (not A's change, reported to James): shareable-link protection bypasses exist on the rafii.io and
  postriff-phase2-private.vercel.app aliases, created ~01:16Z by the project owner account, expiring ~2026-10-10T00:16Z.
  Custom domains are exempt from deployment protection on this project, so they only affect the vercel.app alias.
- Low, pre-existing: no Content-Security-Policy header on app pages.
