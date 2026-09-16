# PostRiff review for the Phase 3 prompt

Date: 2026-09-14. Scope: inspect current local source/specifications, run bounded regressions, and prepare an implementation prompt. No Phase 3 application implementation or external execution occurred.

## Correct milestone

**Phase 3 is Runtime choice and desktop.** The newer [consumer implementation plan](</Users/ouxianxing/Documents/Codex/2026-09-14/ok-just-to-continue-from-the/postriff-product-plan/implementation-plan.md>) specifies the shared desktop shell, pairing, Codex/Claude/Gemini routes, managed AI, reconnection and synchronization. Phase 4 is paid beta; Phase 5 includes richer Analytics/Audience.

This plan explicitly retains and extends the older Studio/SaaS designs. Their “Phase 3 Analytics” and “Phase 3 Paid beta” headings are different, older roadmaps. The separate [content-type specification](superpowers/specs/2026-09-14-postriff-content-type-template-system.md) remains applicable to Ideas and generation.

## Source findings

| Finding | Evidence | Consequence for the prompt |
|---|---|---|
| Agent generation is still deterministic | [generation.py](../src/postriff_alpha/generation.py) | Evolve the actual adapter; require real route conformance before readiness claims |
| CLI inspection detects versions but leaves execution unqualified | [profiles.py](../src/postriff_alpha/profiles.py) | Keep detection/auth/source scope/execution/qualification separate |
| React/Vite, founder domain and Phase 2 hosted composition already exist | [FounderApp.tsx](../studio/web/src/founder/FounderApp.tsx), [hosted_app.py](../src/postriff_phase2/hosted_app.py) | Share existing UI/domain and avoid a framework rewrite |
| Hosted social transport is disabled | [hosted_worker.py](../src/postriff_phase2/hosted_worker.py) | Pairing or generation must not imply live publishing |
| Phase 2 hosted/live acceptance remains incomplete in the latest receipt | [Phase 2 receipt](postriff-phase-2/phase-2-receipt.md) | Track inherited external gates separately and do not claim Phase 2 complete |
| An older architecture note says hosted composition is absent; newer source/preparation includes it | [architecture decision](postriff-phase-2/architecture-decision.md), [hosted preparation](postriff-phase-2/hosted-deployment-preparation.md) | Resolve against newer evidence; avoid rebuilding completed local composition |
| Phase 2 added personalized types and private templates | [increment results](postriff-phase-2/content-type-template-results.md) | Bind their versions and private overrides into every generation route |
| Installed source has no Git metadata | `git status --short` failed: not a git repository | Git history/diff validation unavailable; future edits need scoped backups/hashes/diff |

No remote repository, deployed environment or provider account was inspected for this review. Readiness statements describe local source and recorded receipts, not a live production audit.

## Fresh checks

| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests -p 'test_postriff*.py'` | 90 discovered: 89 passed, 1 skipped |
| `npm --prefix studio/web test` | 70 passed |
| `npm --prefix studio/web run typecheck` | Passed |

The Python skip is the hosted Pillow dependency check: the pinned dependency is not installed in the current interpreter. `validation_unavailable` for that decoder check in this interpreter. No package was installed to change the environment. Older isolated decoder evidence is recorded separately in Phase 2.

These checks do not validate real model execution, packaged desktop behavior, hosted RLS, cloud synchronization or live social delivery. No production build or fresh browser acceptance was run for this documentation-only deliverable. The older receipt's 102 Python-test count is not the fresh focused-suite result.

## Deliverable

[Full Phase 3 execution prompt](postriff-phase-3-execution-prompt.md).

The prompt is a reviewable candidate. It provides an explicit local Phase 3 exception **only when the user subsequently asks to execute it**, keeps research incomplete and invitations paused, allows independent local engineering to proceed, and leaves exact external actions subject to their actual authorization.

Vercel compatibility note: the session reports CLI 59.15.1 with 59.17.0 available. Before later Vercel work, an upgrade via `npm i -g vercel@latest` or `pnpm add -g vercel@latest` is strongly recommended. No global tool was upgraded during this review.
