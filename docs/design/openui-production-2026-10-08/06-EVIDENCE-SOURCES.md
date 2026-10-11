# Evidence Baseline and References

Prepared on 2026-10-08, America/Indiana/Indianapolis. Statements about code are snapshot observations; production capability is not inferred from file presence. Numeric acceptance bounds are chosen engineering requirements, not observed benchmark results.

## Local read-only inspection in this task

ORC targeted the paired MacBook Pro. `git rev-parse --show-toplevel` resolved `/Users/ouxianxing/Documents/James-Au-Studio`; origin resolved `https://github.com/dev-james0723/PostRiff.git`.

Local worktree HEAD was `80bc24d20397a90257cb5571f8a3914a652bfb51`. `git status --short` returned unrelated changes in social-connector/backend/web files, vendor work and numerous untracked project documents. No implementation, cleanup, branch switch, reset or commit was performed by this packaging task.

`git ls-remote --heads origin consumer-saas` returned `3da806f0e31a01396a3bd4a9e27f66f9b21ce816`. Local remote-tracking ref matched. This is a source baseline, not proof of the running production deployment. Reads of AGENTS.md at root/web/src in that Git snapshot did not resolve; execution must still inspect current local/global instructions and CLAUDE.md as applicable.

`git show` at that snapshot confirmed web/package.json uses Next 16.3.8, React 19.2.4, Zod 4.3.6 range, Node 24.x and npm 11.12.1; no OpenUI package was listed. requirements.txt includes pinned openai-agents 0.22.3, openai 3.19.2, jsonschema, psycopg and the existing Starlette/Uvicorn dependencies. Do not automatically upgrade those runtime pins.

The snapshot file listing confirms existing Library attachment views, voice-learning UI, analytics, automation and founder-agent modules and their tests. A file listing does not prove every service is enabled, integrated or production-verified. D/E must read the actual relevant service/route implementations.

## Earlier conversation source review

The attached `rafii-openui-plan-2026-10-08.md` was read in full. It described the same source SHA and the existing Manager/structured result/client/routing architecture. Its three-journey scope, two-implementer cap and October 12–22 schedule are superseded by this package. Its source review is not a new product test result.

Snapshot source base: `https://github.com/dev-james0723/PostRiff/blob/3da806f0e31a01396a3bd4a9e27f66f9b21ce816/`

Relevant paths: `web/package.json`; `requirements.txt`; `web/src/features/agent/conversation-view.tsx`; `web/src/features/site-agent/answer.tsx`; `web/src/lib/agent-runtime/client.ts`; `src/postriff_phase2/agent_runtime_v2/manager.py`; `contracts.py`; `service.py`; `http.py`; `docs/design/site-agent/agent-runtime/ARCHITECTURE_LOCK.md`; `api/index.py`; `vercel.json`; `tests/test_agent_runtime.py`.

Historical architecture notes can lag implementation. Reconcile them against current code, live configuration and controlled behavior at execution, without treating new behavior as permission to bypass security.

## Official primary references rechecked for this package

- **S1** OpenUI introduction: https://www.openui.com/docs — model-composed own components, renderer and optional chat shell/hosted services.
- **S2** Defining components: https://www.openui.com/docs/openui-lang/defining-components — defineComponent/createLibrary, Zod schemas, ordered arguments, grouping and component subsets.
- **S3** Renderer: https://www.openui.com/docs/openui-lang/renderer — response/library/isStreaming, action/state callbacks, initialState, toolProvider, parse/error behavior.
- **S4** Reactive state: https://www.openui.com/docs/openui-lang/reactive-state — variables, binding and dependent state/query updates.
- **S5** Queries/mutations: https://www.openui.com/docs/openui-lang/queries-mutations — runtime tool data flow, explicit mutation trigger, refresh; examples still require application authentication and lifecycle handling.
- **S6** Incremental editing: https://www.openui.com/docs/openui-lang/incremental-editing — merge by statement name and edit prompt mode; absence in a patch does not mean deletion.
- **S7** Architecture: https://www.openui.com/docs/openui-lang/architecture — separates generation from subsequent execution; function-map/MCP examples are not authorization guarantees.
- **S8** Telemetry: https://www.openui.com/docs/openui-lang/telemetry — installation telemetry defaults on, runtime off, opt-out environment variables.
- **S9** OpenAI Agents SDK streaming: https://openai.github.io/openai-agents-python/streaming/ — stream consumption/finalization, approvals and cancellation; verify exact installed SDK support.
- **S10** OpenUI production: https://www.openui.com/docs/production — generation failures, optional Gateway/Autofix/monitoring; not an obligation to send Rafii data to a new vendor.
- **S11** Official OpenUI repository for package export/version verification at implementation: https://github.com/thesysdev/openui — locator, not a pinned package audit performed in this task.

Docs showed language specification v0.5 as latest at inspection. That does not establish an npm package version or compatibility with Rafii. R0 must feature-probe the actually pinned packages. A direct attempt to read a guessed built-in-functions path failed; no claim in this package depends on that unread page. Do not cargo-cult demo API code or vendor speed/token marketing as measured Rafii performance.

## Not verified in this packaging task

No product code changes, dependency install, model call, UI screenshot, application test, database mutation, actual deployment/running SHA, feature-flag activation, auth callback/canonical-domain check or iPhone app test was performed. Document existence/checksums will be verified separately when copied to the Mac. That receipt proves file delivery only.
