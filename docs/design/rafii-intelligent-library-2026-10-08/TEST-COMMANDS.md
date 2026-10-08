# TEST-COMMANDS — exact commands per gate

All heavyweight validation runs remotely through James Cloud Build (Depot), from the candidate worktree, using sanitized working-tree transport (no push). Only focused Python unit tests run on the Mac.

| Gate | Where | Command |
|---|---|---|
| Focused unit (per task) | Mac (seconds) | `cd <worktree> && PYTHONPATH=src:tests /Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python -m unittest test_library_intelligence_<area>` |
| All Library intelligence unit tests | Mac or cloud | `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_library_intelligence_*.py' -v` |
| Library suites: existing + intelligence unit tests, disposable PostgreSQL (with and without pgvector) and node source tests | Cloud | `jcb test` → `npm run test:library` → `scripts/library-cloud-validation.sh` |
| Typecheck | Cloud | `jcb typecheck` → `npm --prefix web run typecheck` |
| Lint | Cloud | `jcb lint` → `npm --prefix web run lint` |
| Production build | Cloud | `jcb build` → `npm --prefix web run build` |
| Full Library release validation (audit, unit, PG, typecheck, lint, build, ffmpeg media fixtures, Playwright Chromium+WebKit browser evidence) | Cloud | `jcb ci` → `npm run ci:library` → `scripts/library-release-validation.sh` |
| Existing adjacent regressions (Agent/Memory/Drafts/Queue/Now Playing source tests + full unittest discover + PG suites) | Cloud | GitHub `consumer-ready.yml` equivalent; on this candidate via `scripts/library-intelligence-validation.sh --regressions` inside `jcb test` |
| Real-provider evaluation (ASR, embeddings, vision, LLM) | Cloud or dev harness with authorized credentials | `scripts/library-intelligence-provider-eval.py` — **requires James's explicit paid-inference authorization**; not run otherwise |
| Real iPhone Safari smoke (A066) | James's device | Manual procedure in `evidence/iphone-smoke.md` — **requires James** |

Rules:
- A skipped required test, missing dependency, mock-only provider or fixture is not a pass.
- Every receipt records the candidate SHA (`git rev-parse HEAD`), the JCB run ID/URL, and the remote exit code.
- Node, Vitest/Jest, tsc, oxlint, Next and Playwright never run on the Mac for this task. If JCB fails, report the failure; do not fall back to local execution.
