# Real writing: the server-side model route

**Code:** `src/postriff_phase2/model_runtime.py` (`ServerModelRuntime`), mounted by `hosted_app.ideas_runtime_from_environment` → `HostedWorkspaceService(ideas_runtime=…)`. **Tests:** `tests/test_postriff_model_runtime.py`.

## What it does
- One HTTPS call per turn to an OpenAI-compatible chat-completions endpoint (Vercel AI Gateway, `https://ai-gateway.vercel.sh/v1/chat/completions`), `response_format: json_object`, structured `{variants:[…]}` validated before any text is shown. At most two attempts; a 45 s timeout; 1 MB response cap; 60 kB context cap.
- Prompt rules: approved facts only, unknowns listed instead of invented, one variant per destination within `contracts.LIMITS`, source text treated as data (prompt-injection guard).
- Reasoning: `quick` (one pass), `standard` (one pass with a self-check instruction), `deep` (draft + critique-and-revise pass, two requests).
- Cost: estimate before the call (`price_quote`), actual from provider token usage or the gateway's reported `usage.cost`; returned in `usage.costUsd` so `ideas.turn` settles the ledger (reserve $0.50 → settle actual; workspace and global stop-lines still apply).
- The key lives only in server env; it never appears in events, artifacts or errors.

## Skills (writing method)
When `IdeasService.turn()` binds a skill library (`request["skills"]["text"]`, composed by the agent-chat session's `SkillLibrary`), the paid route appends it to the system prompt under a **SKILLS (writing method only)** section, capped at `MAX_SKILLS_BYTES` (60 kB) and counted in `price_quote`. It is method guidance only: it never adds facts, never changes rules 1–6, never speaks for the author. Hosted note: `.vercelignore` excludes `skills/`, so production runs carry no skill text until that is deliberately bundled (cost: up to ~15k extra prompt tokens per draft).

## Fail-closed on consent (decision D10)
`start_turn` refuses any context whose `providerClass` is not `"cloud"` (403). Only `source_policy.project_context(state, "draft", "cloud", …)` produces that, and it excludes every source without `egressConsent: ["cloud"]`. **Merge point for `ideas.py`:** `turn()` currently projects with `"local"` for every runtime; it must pass `getattr(runtime, "provider_class", "local")` so the cloud route receives the consent-filtered context. Until that line lands, selecting the paid model fails safely with the 403 message.

## Founder setup
1. Vercel → AI Gateway → create an API key; set `AI_GATEWAY_API_KEY` (production + preview). Optional: `POSTRIFF_MODEL_ID` (default `anthropic/claude-sonnet-5`), `POSTRIFF_MODEL_IDS`, `POSTRIFF_MODEL_PRICES`.
2. Fund the gateway (it needs a small balance); the ledger stop-lines ($6 / workspace / month, $10 / day global — candidates) refuse requests before a call once crossed.
3. Redeploy. `/api/ideas/models` then lists the paid model as qualified next to the deterministic preview.

## UI (shipped)
- **Ideas** (`web/src/features/ideas/ideas-view.tsx`): writing-model `Select` over the qualified entries of `/api/ideas/models` (cost class shown per option), reasoning toggle only for a paid model, `model` + `reasoning` sent on `quick-start` and `turn`; destinations default to the connected channels (green dot = connected); run log shows `usage.costUsd` and provenance; a `pending` assistant row (asynchronous runtimes) renders as “Writing…”.
- **Sources & consent** (`web/src/features/ideas/sources-panel.tsx`): per-source policy select and an “Allow AI model (cloud)” switch — both call `source_policy {sourceId, policy, egressConsent, confirmed: true}`. Nothing reaches the paid route without the switch (server refuses with 403 regardless of the UI).
- **Draft editing** (`web/src/features/pipeline/edit-draft-dialog.tsx`): `variant_edit {variantId, variantRevision, text}` from the Pipeline card; accepts a pending `proposedUpdate` first (same chain as the Schedule dialog). Pipeline keys “already reviewed” on `variantId:contentRevision`, so an edited draft is schedulable again.
- **First-run checklist** (`web/src/features/overview/getting-started.tsx`): voice → channel → first draft → first approval, read from workspace state; hidden once complete.
- Not yet: an estimated cost *before* drafting (needs `price_quote` exposed on a route).
