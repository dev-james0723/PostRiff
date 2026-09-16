# Real writing: the server-side model route

**Code:** `src/postriff_phase2/model_runtime.py` (`ServerModelRuntime`), mounted by `hosted_app.ideas_runtime_from_environment` → `HostedWorkspaceService(ideas_runtime=…)`. **Tests:** `tests/test_postriff_model_runtime.py`.

## What it does
- One HTTPS call per turn to an OpenAI-compatible chat-completions endpoint (Vercel AI Gateway, `https://ai-gateway.vercel.sh/v1/chat/completions`), `response_format: json_object`, structured `{variants:[…]}` validated before any text is shown. At most two attempts; a 45 s timeout; 1 MB response cap; 60 kB context cap.
- Prompt rules: approved facts only, unknowns listed instead of invented, one variant per destination within `contracts.LIMITS`, source text treated as data (prompt-injection guard).
- Reasoning: `quick` (one pass), `standard` (one pass with a self-check instruction), `deep` (draft + critique-and-revise pass, two requests).
- Cost: estimate before the call (`price_quote`), actual from provider token usage or the gateway's reported `usage.cost`; returned in `usage.costUsd` so `ideas.turn` settles the ledger (reserve $0.50 → settle actual; workspace and global stop-lines still apply).
- The key lives only in server env; it never appears in events, artifacts or errors.

## Fail-closed on consent (decision D10)
`start_turn` refuses any context whose `providerClass` is not `"cloud"` (403). Only `source_policy.project_context(state, "draft", "cloud", …)` produces that, and it excludes every source without `egressConsent: ["cloud"]`. **Merge point for `ideas.py`:** `turn()` currently projects with `"local"` for every runtime; it must pass `getattr(runtime, "provider_class", "local")` so the cloud route receives the consent-filtered context. Until that line lands, selecting the paid model fails safely with the 403 message.

## Founder setup
1. Vercel → AI Gateway → create an API key; set `AI_GATEWAY_API_KEY` (production + preview). Optional: `POSTRIFF_MODEL_ID` (default `anthropic/claude-sonnet-5`), `POSTRIFF_MODEL_IDS`, `POSTRIFF_MODEL_PRICES`.
2. Fund the gateway (it needs a small balance); the ledger stop-lines ($6 / workspace / month, $10 / day global — candidates) refuse requests before a call once crossed.
3. Redeploy. `/api/ideas/models` then lists the paid model as qualified next to the deterministic preview.

## UI
Ideas page: model selector (from `/api/ideas/models`), per-source **cloud consent** switch (`source_policy` action with `egressConsent: ["local","cloud"]`), estimated cost shown before drafting, provenance and cost in the run log.
