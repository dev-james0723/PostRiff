# Phase 3 implementation receipt

Latest local build: [sync recovery follow-up](sync-recovery-receipt.md), including delayed/lost response acceptance.

Follow-up: [runtime repairs, rebuilt package and prepared real-run review](runtime-followup-receipt.md). The original results and ZIP below are historical; the follow-up records the current app build.

2026-09-14/15. **Local Phase 3 foundation implemented and packaged desktop validated; full Phase 3 remains incomplete.** Execution was local and reversible under the explicit Phase 3 research-gate exception. Phase 0 is still incomplete. No invitation, provider login, paid model request, cloud provisioning/deployment, publication, billing, installed/global skill change or Phase 4 work was performed.

## Delivered

- Shared React/Vite runtime/device controls in Ideas and You, retaining all six primary destinations and the existing onboarding/profile/content-type UX.
- Separate Phase 3 local Python store/launcher, approved input/version snapshots, single-use native-confirmed pairing, OS-encrypted device vault, revocation, scoped jobs, durable claims/leases/events and no blind model retry.
- Independent candidate review, preservation of customized variants, field-reviewed profile candidates, explicit local-only managed-source eligibility, durable unsent edits and revision-conflict recovery.
- Separate Codex/Claude/Gemini adapter contracts. Claude bare/API process path and managed DeepInfra HTTP path implemented behind server-provided authorization; real routes remain visibly limited/blocked. Synthetic process and HTTP transport tests are labelled fixtures.
- Additive PostgreSQL runtime migration and repository, protected from direct browser reads; tested in a fresh disposable local database. No hosted migration was applied.
- Candidate external-agent stdio MCP/neutral skill surface: selected context, candidate submission and review link only; not installed into any native/global agent configuration.
- Actual macOS arm64 Electron app with bundled Python 3.14 sidecar and shared frontend. End users do not need development Python. No agent binary, provider credential, private installed skill, local database or device vault is bundled.

## Open / restart

- [PostRiff.app](../../desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app)
- [Local ZIP](../../desktop/artifacts/PostRiff-0.3.0-macos-arm64-local.zip), approximately 143 MB; ZIP integrity passed.
- [Desktop launch/restart evidence](evidence/desktop-acceptance.json), [desktop screenshot](evidence/desktop-runtime.png), [mobile screenshot](evidence/mobile-runtime.png).

```sh
open /Users/ouxianxing/Documents/James-Au-Studio/desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app
```

The desktop uses its separate Electron user-data directory and loopback port 4330. The source launcher is `python3 scripts/postriff_phase3.py`; its default database is under `~/Library/Application Support/PostRiffPhase3/`. These are separate local stores, not a cloud synchronization claim. Quit the app to stop the sidecar; acceptance confirmed no orphan process/listener.

Package ZIP SHA-256:

`1443ad0b162f65c60836ae05bba85bd732b59cf4d8fa011906342d186acc960d`

Package tree SHA-256:

`e6b8a305ae68f616c2cd656843d05bd8a40a59da6a02c91a1604e8ce2a3b1ee5`

Electron 44.3.0; PyInstaller 6.22.3; macOS 15.1 arm64 tested. Electron declares macOS 13.0 minimum, which was not tested separately. Binary has ad-hoc linker signing only, no Developer ID/team, resource seal or notarization. It is an unsigned local development delivery for distribution purposes. Windows CI/build configuration is reviewable at `desktop/windows-build.yml`; Windows execution, public distribution and automatic updates are unvalidated.

## Validation

| Check | Result |
|---|---|
| Before edits: Python | 90 discovered, 89 passed, 1 Pillow skip |
| Before edits: frontend/typecheck | 70 passed; typecheck passed |
| Final integrated Python | **127 passed**, no skip, using the isolated build environment with pinned Pillow |
| Phase 3 focused checks | **25 passed**; included in the final Python total |
| Frontend | **72 passed** |
| TypeScript, existing web and shared alpha builds | Passed |
| Desktop IPC tests | **2 passed** |
| Disposable local PostgreSQL 17 | Migration, two-user isolation, pairing, stale revision, direct-browser denial and member revocation passed |
| Packaged macOS journey | Passed outside development cwd: synthetic account/source → two candidates → independent edit → offline unsent text → restart → vault persistence → revoke → clean shutdown |
| Responsive/a11y checks | Desktop + 390×844 viewport, keyboard focus, reduced motion, no horizontal overflow, zero page errors; screenshots visually inspected |
| Package | 361 files hashed, explicit app allowlist, ZIP integrity passed; no private runtime data bundled |
| Git history/diff | `validation_unavailable`: installed source has no `.git`; scoped backups/hashes/diff supplied |

The packaged native pairing dialog response was injected by the acceptance harness, not a user or hosted-device approval. Quota/timeout/provider results are synthetic. Physical sleep/wake, real model output, native auth/resume and hosted multi-device behavior remain unverified.

## Source scope and concurrent work

[Source audit](evidence/source-and-package-audit.json) and [scoped diff](evidence/source-diff.patch) identify owned Phase 3 edits. Original source backups remain in `evidence/pre-phase3/`. Concurrent Phase 2 changes were observed in eleven other baseline files and additional hosted-account hunks in `FounderApp.tsx`; they were preserved. Those hunks are excluded from the owned Phase 3 patch. The final tests and package cover the integrated source present at build time; this receipt does not attribute the concurrent Phase 2 changes to Phase 3. Existing three neutral template definitions were hash-verified unchanged.

## Four independent completion states

1. **Local engineering / desktop:** delivered local foundation and executable package passed the checks above. This is not the complete Phase 3 product: hosted desktop identity/transport mounting, native-agent credential handoff, supported provider parity and real run acceptance remain unfinished.
2. **Providers:** synthetic route works locally; Codex limited, Claude limited, Gemini limited, managed blocked. **Zero real model routes qualified in this execution.** See [runtime matrix](runtime-qualification.md).
3. **Hosted pairing/sync:** pending. Local PostgreSQL, one computer and simulated network loss are lower-level evidence. `HostedRuntimeService` and migration are prepared but not mounted/deployed; a signed-in remote desktop confirmation flow and two real devices still need implementation/integration and acceptance.
4. **Inherited Phase 2:** prior receipts record a protected Preview and synthetic hosted isolation pass; not revalidated here. Real auth recovery coverage, artwork, social connector qualification, production worker cadence and laptop-off scheduling remain pending. Phase 2 is not marked complete.

Next bounded external candidate: [managed-writing action preview](external-action-preview.md). It identifies the proposed endpoint/model, exact fictional material, one-request/$0.05 ceiling and missing account/current-price verification. It is not authorization and was not executed. Remaining hosted/native integration work must retain these fail-closed limits rather than advertising three ready agents.

Supporting records: [readiness / architecture](readiness-and-architecture.md), [security / sync / rollback](security-sync-acceptance.md), [runtime qualification](runtime-qualification.md).
