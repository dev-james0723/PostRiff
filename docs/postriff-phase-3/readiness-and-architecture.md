# Phase 3 readiness and architecture

2026-09-14/15 · local engineering in progress. The user's explicit execution of the Phase 3 prompt grants the local research-gate exception. Phase 0 remains incomplete (0/5 full interviews). No recruitment, provisioning, provider request, authentication change or publication is authorized by this run.

## Precedence and evidence

The newer consumer plan controls P3 runtime/desktop, P4 billing, P5 expansion. The content-type spec controls type → format → destination contracts. Retained UX/security requirements apply; superseded prices/phases do not. The newer Phase 2 hosted preparation and acceptance receipts supersede older readiness notes: protected Preview, Supabase migration, synthetic two-user/media isolation and one remote fixture worker invocation were recorded as passed. These are prior receipts, not revalidated hosted state in this task. Production cadence/laptop-off proof, real auth recovery coverage, artwork and social providers remain Phase 2 dependencies.

## Decision

Use Electron with the existing React/Vite build and Python sidecar frozen with PyInstaller. No UI rewrite, no end-user Python requirement, no agent binaries/credentials/private installed skills in the package. First target: macOS 15.1 arm64; package declares minimum macOS 13.0 (Electron Info.plist); older macOS versions remain untested. Windows build recipe must run on Windows, not cross-claim acceptance. Unsigned local artifact only; no signing/notarization/update service/public distribution.

Renderer: sandbox, context isolation, no Node, no permission grants, no arbitrary navigation or general shell/file IPC. Privileged main: typed finite IPC, native confirmation, encrypted device identity via Electron safeStorage, starts one bundled sidecar using argument arrays and minimized environment. Sidecar: separate local Phase 3 database, existing Phase 2 auth/domain, durable scoped runs. The device API never confers social authority. Provider execution remains fail-closed until exact isolation/auth/model/cost evidence exists.

## Readiness ledger

| Boundary | Can proceed locally | Remaining gate |
|---|---|---|
| Shared contracts/desktop/cache | Implementation, synthetic recovery and package checks | Native macOS launch/package evidence |
| Pairing/sync | Single-use enrollment and scoped transport tests, local SQL | Hosted migration/endpoint deployment and two actual devices explicitly authorized |
| Codex 0.154.0 | Structured parser, launch policy, inspect | Auth/source/cost consent; minimum filesystem read boundary qualification |
| Claude 2.1.153 | Bare/no-tools structured adapter | API/enterprise auth; consent and paid synthetic generation; no subscription assumption |
| Gemini 0.45.2 | Distinct structured parser/policy | Supported API/enterprise auth, hooks/tools isolation qualification and consent |
| Managed writing | Server-side HTTP adapter, durable integration, cost preview | Provider credentials/configuration and bounded paid execution authorization |
| Phase 2 distribution | Preserve current domain and approval contracts | Live artwork, auth recovery, connector qualification, production cadence and laptop-off proof |

Baseline: Python 90 discovered, 89 passed, 1 skipped (Pillow absent); frontend 70 passed; typecheck passed. Git history/diff: `validation_unavailable` because this installed directory has no `.git`. Scoped copies and hashes are in evidence/pre-phase3 and baseline.json. No repository initialized.
