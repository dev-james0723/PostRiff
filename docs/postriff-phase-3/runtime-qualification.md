# Runtime qualification matrix

Evidence date: 2026-09-14/15. Host: macOS 15.1 arm64. No real model request, provider login, credential copy, paid call or subscription inspection occurred.

| Route | Installed/help evidence | Implemented local boundary | Real qualification / blocker |
|---|---|---|---|
| Synthetic conformance | Authored fixture, no model | Durable preparation, source consent, progress, interruption, candidate review and saved edits | Local tests only; never a model-quality or bilingual translation claim |
| Codex | `codex-cli 0.154.0`; `exec --json`, schema, ephemeral, ignore-user-config/rules inspected | Separate parser/argument builder; reasoning/tool arguments omitted; no app-server enabled | Limited. No approved native auth/model run; read-only native sandbox does not by itself prove the required narrow file-read boundary. Execution fails closed |
| Claude Code | `2.1.153`; bare, no-tools, disable-slash-commands, strict MCP, no-session-persistence, structured output and budget options inspected | API-only bare adapter, minimized temporary home, no tools/hooks/skills/MCP, 60s bound, 256 kB output limit, process-group cancellation | Limited. No protected API credential supplied or live native permission/quota/model test. Model remains unselected; reasoning control omitted. Synthetic process tests do not qualify Claude |
| Gemini | `0.45.2`; headless stream-json, plan/sandbox, extensions and resume inspected | Distinct parser/argument candidate; no consumer-login or Antigravity substitution | Limited. API/enterprise route and tool/hook/config isolation unqualified; execution fails closed |
| Managed | No qualified existing writing provider | DeepInfra HTTP adapter, fixed endpoint, no redirects/tools/fallback, 2,048 output-token bound, server-reviewed model/rate quote, durable pre-request start and idempotent allowance accounting | Blocked. Account/key/model-price verification and exact cost/source authorization absent. Production hosted worker integration is not activated |
| External-agent tools | Local Python stdio MCP surface | Read scoped context, submit candidate, return review path; paired-device/lease/artifact guards; no publish/approve/connection/shell tool | Candidate integration only. Not installed in global/native-agent settings; protected credential handoff and each native-agent session still need qualification |

Authenticated, source-approved, executed and qualified are separate states. CLI installation is the only native runtime fact verified. Native session resume is disabled; recovery requires reconciliation and a new canonical run. No hidden native context or provider billing history is transferred. Original private skills remain unchanged; only the existing three neutral releases enter manifests.

## Official evidence

- [Codex noninteractive execution](https://developers.openai.com/codex/noninteractive/): structured execution and JSON events; installed help takes precedence for exact 0.154.0 flags.
- [Claude headless](https://code.claude.com/docs/en/headless): programmatic execution and structured output.
- [Claude billing update](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan): the June 15 pause remains at the top of the page; subscription treatment is not a permanent entitlement claim. The chosen bare adapter itself requires API/enterprise credentials and does not read subscription sessions.
- [Gemini headless](https://geminicli.com/docs/cli/headless/), [authentication](https://geminicli.com/docs/get-started/authentication/), [Google transition notice](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/): affected consumer routes changed; listed API/enterprise routes remain distinct. No actual account eligibility was checked.
- [Electron security](https://www.electronjs.org/docs/latest/tutorial/security): isolation, sandboxing, sender validation and navigation controls underpin the shell.
- [DeepInfra chat API](https://docs.deepinfra.com/chat/overview), [structured output](https://docs.deepinfra.com/chat/structured-outputs): server-only OpenAI-compatible transport. Direct model pricing page retrieval failed, so no current price is asserted or silently hardcoded.

Vercel marketplace discovery was read-only: CLI 59.15.1 returned `deepinfra/api-token` in the AI category. No integration was installed. Before future Vercel work, recheck and upgrade with `npm i -g vercel@latest` or `pnpm add -g vercel@latest`; this run changed no global tool.
