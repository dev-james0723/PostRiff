# Integration: Agent Runtime + Rafii Coworker onto consumer-saas

Local integration branch `rafii/integration-runtime-coworker` (worktree `James-Au-Studio-integration`), built 2026-09-25 by the Rafii integration session. Local only: nothing is pushed, no PR is open, nothing is merged into `consumer-saas`, no migration is applied, nothing is deployed. Shared merges wait until Opus 5.5 Extra High, the sole production release executor, declares the current release COMPLETE.

## Commits

| Commit | What |
|---|---|
| base `b5de49f` | `consumer-saas` as released (PR #4, #2, #5). |
| `42f57cb` M1 | `--no-ff` merge of the Agent Runtime, `raffi/site-agent` @ `056f71b`. The tree `135b919` is identical to Extra High's `raffi/agent-runtime-merge` @ `833bf76`. |
| `75b824b` M2 | `--no-ff` merge of the frozen coworker commit `ecb3ff3`, unchanged (merge base `cf48b42`). |
| `587fd5a` C3 | Coworker customer copy passes `consumer-saas`'s copy audit. |
| `069c303` C4 | No coworker requests while a feature is off. |
| this commit | Docs only: this file, `docs/postriff-migration-numbering.md`, and corrected migration notes in ROLLOUT, HANDOFF and ARCHITECTURE_LOCK. |

## Conflict resolutions

**M1** (10 paths, exactly as in `agent-runtime/MERGE_PLAN.md`):
- `hosted_app.py`: keep both dispatch blocks, agent then billing/credit-packs GET.
- The 8 site-agent docs and screenshots: take `consumer-saas`, path by path.
- `evidence/browser-webkit/site-agent-browser.json`: stays deleted.

Checks: `answer.tsx` equals `consumer-saas`; `migrations/` unchanged.

**M2** (4 paths):
- `hosted_app.py`: agent, then coworker resources, then credit-packs GET, then billing POST. The predicates are disjoint: the coworker resources (`coworker`, `notifications`, `notification-preferences`, `push-subscriptions`) are used by no other `parts[3]` route.
- `operational_signals.py`: the union of counts (`budgetWarnings` plus the coworker's two notification counts, which are 0 with flags off).
- `notifications-view.tsx`: `consumer-saas` layout and flag-off copy, the coworker's settings section and flag-on description, one `SecurityAlerts`.
- `overview-view.tsx`: `consumer-saas`'s `StatStrip`, with `CoworkerAttention` above it.

Also checked on M2:
- Auto-merges read line by line: `.env.example` (no duplicate keys), `email.py`, `app-sidebar.tsx`, `notification-bell.tsx`.
- Byte identities: migrations 018–022 equal `consumer-saas`; 024/025, `rls.sql` and all coworker code equal `ecb3ff3`.
- The runner's sequence is 001–022, 024, 025.

**Why C3 and C4 exist.** Both are needed for `consumer-saas`'s CI.
- **C3:** on M2 the web test "Customer screens contain no implementation words" failed, 148/149, on five coworker strings containing "deployment" or "payload".
- **C4:** with every flag off, `web/tests/ui-simplification-browser.cjs` failed 3 of 60 checks. The notification bell and the attention panel polled every 60 s and got 404 `feature_disabled`, which Chromium logs as console errors.
- Neither commit changes `ecb3ff3`.

## Verification of `069c303`

All local, with synthetic providers. None of it is live.

| Gate | Result |
|---|---|
| Python unit, everything (`unittest discover`) | 1046 OK (916 at M1) |
| PostgreSQL, every suite (`scripts/rafii_pg_private.py`, private port) | 55/55 scripts exit 0, including runtime 51/51, coworker 35/35, site agent 98/98 and every credit suite |
| Web contract tests | 149/149 (97 at M1) |
| `npm run audit:copy -- --check` | 0 banned phrases |
| Typecheck, lint | exit 0; 0 warnings, 0 errors (747 files) |
| Production build (CI recipe: `scripts/consumer_ready_web.py`, credential-free copy) | exit 0 (downloads Google Fonts) |
| `consumer-saas` CI browser scenes, every flag off, against that production build | seed ok; automations 83/83; workflow 38/38; theme bars all passed; UI simplification 60/60; Rafii home PASS; site agent 39/39 in Chromium and WebKit; 0 console or page errors |
| Launch journey | default: functional pass, no page errors. Credit fixture: pass, with a real quote, reserve and settlement (50 → 47 credits, 0 held) |
| All flags on (coworker + runtime, runtime harness) | coworker browser 47/47 in Chromium and WebKit; runtime browser 30/30 in Chromium and 29/29 in WebKit |
| Email render (24 templates × 4 locales × 2 engines × 2 themes × 2 widths) | 768/768 |
| Registry and James-leak gate | 90 capabilities, 0 orphans, 0 leaks |
| Secret scan | PASS, 1461 files, 0 unexpected |
| Production-shaped migration rehearsal | 024 and 025 apply twice without error; 10/10 tables with forced RLS; no `anon` or `public` grants; origin check adds `copilot`; the 7 credit tables are untouched |

Scene outputs that write into tracked evidence folders (`docs/design/rafii-v9/evidence/*`, `docs/launch-20260923/evidence`, the coworker's email screenshots) were copied to scratch and restored. The committed tree carries no regenerated evidence.

## What happens next

1. **Release in progress (Extra High):** PR #6, the layout hotfix, then the Agent Runtime through its own `raffi/agent-runtime-merge`, onto the new `consumer-saas`. Once `consumer-saas` contains the runtime, this branch's M1 is superseded.
2. **After Extra High declares COMPLETE:** rebuild on the new `consumer-saas` SHA. Start a new branch from it, merge `ecb3ff3`, re-apply C3 and C4, and resolve against whatever PR #6 and the runtime merge changed. Then rerun every gate above on the exact resulting commit.
3. **Migrations:** 024 then 025 go to staging, then production, with a pinned one-off runner, before the coworker build is deployed (see `docs/postriff-migration-numbering.md`).
4. **Push and PR,** each only with the owner's authorization. Merge and deploy belong to the release executor.
5. **Before any coworker flag goes on:**
   - rebind `credit_requests` in the coworker's copied writer service, and decide how autonomous drafting works on credit-policy workspaces;
   - the runtime's credit wiring and its Preview isolation;
   - a security review of the flags-off public routes;
   - site-agent route-manifest entries for `/app/weekly` and personalization.
