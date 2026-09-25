# Integration: Rafii Coworker onto consumer-saas

Integration branch `rafii/coworker-integration` (worktree `James-Au-Studio-integration`), built 2026-09-25 by the Rafii integration session after Opus 5.5 Extra High declared the release COMPLETE. It is pushed as `claude/rafii-coworker-integration` for a PR to `consumer-saas`, for Extra High's review. Merge, migrations and deploy belong to Extra High; this session does none of them.

## Commits

| Commit | What |
|---|---|
| base `fc72e0c` | `consumer-saas` after PR #6 (layout hotfix, `7f66582`) and PR #7 (Agent Runtime). Tree `b9cce9b`. |
| `4e25eee` M | `--no-ff` merge of the frozen coworker commit `ecb3ff3`, unchanged (merge base `cf48b42`). |
| `8005ddd` C3 | Coworker customer copy passes `consumer-saas`'s copy audit. |
| `4c9ed78` C4 | No coworker requests while a feature is off. |
| `7cf1e70`, `093bf93` | Docs only: `docs/postriff-migration-numbering.md`, this file, corrected migration notes in ROLLOUT, HANDOFF and ARCHITECTURE_LOCK. |
| `caaa60d` | Docs only: this file, for the rebuilt branch. PR #8 was opened at this commit, and CI passed on it. |
| `812c56b` | Merge of `consumer-saas` `b5b7964` (Time Back, PR #9). Two conflicts. `hosted_app.py`: Time Back's worker hook, then the coworker's `runtime.attach`. `tests/phase2/rls.sql`: 023, then 024 and 025. |
| this commit | Docs only: the 023 record and this table. |

The code is final at `4c9ed78`. The Agent Runtime is no longer merged here: it shipped in PR #7.

## Conflict resolutions (4 paths)

- `hosted_app.py`: agent, then coworker resources, then credit-packs GET, then billing POST. The predicates are disjoint: the coworker resources (`coworker`, `notifications`, `notification-preferences`, `push-subscriptions`) are used by no other `parts[3]` route.
- `operational_signals.py`: the union of counts (`budgetWarnings` plus the coworker's two notification counts, which are 0 with flags off).
- `notifications-view.tsx`: `consumer-saas` layout and flag-off copy, the coworker's settings section and flag-on description, one `SecurityAlerts`.
- `overview-view.tsx`: `consumer-saas`'s `StatStrip`, with `CoworkerAttention` above it.

These are the same 4 conflicts, resolved the same way, as on the earlier local rehearsal branch `rafii/integration-runtime-coworker` (base `b5de49f`). PR #6 and PR #7 added no new conflict.

Byte identities on the branch head:
- 024, 025 and `tests/phase2/rls.sql` equal `ecb3ff3`;
- 018–022 equal `fc72e0c`;
- the runner's sequence is 001–022, 024, 025.

**Why C3 and C4 exist.** Both are needed for `consumer-saas`'s CI.
- **C3:** the web test "Customer screens contain no implementation words" failed 148/149 on five coworker strings containing "deployment" or "payload".
- **C4:** with every flag off, `web/tests/ui-simplification-browser.cjs` failed 3 of 60 checks. The notification bell and the attention panel polled every 60 s and got 404 `feature_disabled`, which Chromium logs as console errors.
- Neither commit changes `ecb3ff3`.

## Verification of the branch

All local, with synthetic providers. None of it is live.

**Run on `093bf93`** (code identical to `4c9ed78`):

| Gate | Result |
|---|---|
| Python unit, everything (`unittest discover`) | 1046 OK |
| PostgreSQL, every suite (`scripts/rafii_pg_private.py`, private port) | 55/55 scripts exit 0, including runtime 51/51, coworker 35/35, site agent 98/98 and every credit suite |
| Web contract tests | 152/152 |
| `npm run audit:copy -- --check` | 0 banned phrases |
| Typecheck, lint | exit 0; 0 warnings, 0 errors |
| Production build (CI recipe: `scripts/consumer_ready_web.py`, credential-free copy) | exit 0 |
| `consumer-saas` CI browser scenes, every flag off, against that production build | seed ok; automations 83/83; workflow 38/38; theme bars all passed; UI simplification 64/64; Rafii home PASS; site agent 39/39 in Chromium; 0 console or page errors |
| Launch journey, default | functional pass, no page errors |
| Email render (24 templates × 4 locales × 2 engines × 2 themes × 2 widths) | 768/768 |
| Registry and James-leak gate | 0 orphans, 0 leaks |
| Secret scan | PASS, 1462 files, 0 unexpected |

**Not run locally this time.** On 2026-09-25 James limited local work on this shared Mac: swap was 99 % used and 18 Next servers were running. Browser checks go to CI and Vercel previews instead.
- **Site agent in WebKit:** the local WebKit process crashed twice at the same step, while text was typed into the composer. The error was a native AppKit `NSInvalidArgumentException` (`-[NSTextInputContext textInputClientDidUpdateSelection]`), after a spell-server timeout. The installed WebKit is revision 2359; Playwright 1.62.1 expects 2336. The web code between this branch and the earlier run that passed 39/39 differs only by PR #6's CSS and copy changes. The authoritative result is `rafii-browser.yml` on the PR, which installs the matching WebKit.
- **Launch journey with the credit fixture, and the all-flags-on coworker and runtime browser suites:** they passed on the earlier rehearsal branch (credit 50 → 47, 0 held; coworker 47/47 in Chromium and WebKit; runtime 30/30 and 29/29). They were not rerun on this base.
- **Production-shaped migration rehearsal:** not rerun. 024 and 025 are byte-identical to the rehearsed files, and so are 018–022. Earlier result: both apply twice without error; 10/10 tables with forced RLS; no `anon` or `public` grants; the origin check adds `copilot`; the 7 credit tables are untouched.

Scene outputs that write into tracked evidence folders (`docs/design/rafii-v9/evidence/*`, `docs/launch-20260923/evidence`) were copied to scratch and restored. The committed tree carries no regenerated evidence.

## Before merge and deploy (Extra High)

1. **Migrations first.** Apply 024, then 025, to staging, then production, with a one-off runner pinned to each file's sha256, **before** this build is deployed there. Account deletion deletes from their tables whatever the flags say. Production has no ledger, so `scripts/postriff_migrate.py` refuses it. See `docs/postriff-migration-numbering.md`.
2. **Environment:** nothing new is required. The 11 coworker `RAFII_*` flags default to off; leave them unset.
3. **Flags-off behaviour that ships unconditionally:**
   - the coworker status route answers, and so does the public unsubscribe page (which rejects every link, since no email is sent with the feature off);
   - the email webhook and the feature routes answer 404 `feature_disabled`;
   - the bell and the attention panel make no feature request;
   - the Notifications settings section renders nothing;
   - account deletion covers the new tables.

## Before any coworker flag goes on

- rebind `credit_requests` in the coworker's copied writer service, and decide how autonomous drafting works on credit-policy workspaces;
- the runtime's credit wiring and its Preview isolation;
- a security review of the flags-off public routes;
- site-agent route-manifest entries for `/app/weekly` and personalization.
