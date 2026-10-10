# Context Lens: one permission-checked context resolver and inspectable context chips

Agent Experience Program, lane C5: **P0.6** (server context resolver) and **P1.1** (Context Lens chips in the Rafii panel).
Status: **IMPLEMENTED, UNVERIFIED**; flags default off, no deployment or activation receipt yet. Base: `origin/consumer-saas` `de4e5907`.

## Flags (server-enforced, default off)

| Variable | Default | Effect |
|---|---|---|
| `RAFII_CONTEXT_LENS_ENABLED` | off | Turns the resolver, the preview route and the panel chips on, only for the listed workspaces and only where `RAFII_AGENT_V2_ENABLED` is on. |
| `RAFII_CONTEXT_LENS_WORKSPACES` | empty | Comma-separated workspace ids. **Empty = nowhere.** `*` = every workspace (explicit). |
| `RAFII_CONTEXT_VISIBLE_STATE_ENABLED` | off | **DP-17 approved, acceptance pending.** Sends the page's view values (filters, date ranges, tabs) to the model, wrapped as data. Needs the lens on as well. Stays off. |

None of these is in `RuntimeConfig.FLAGS`, so `GET agent/status` is byte-identical when the lens is off. When it is on for a workspace, status gains `contextLens: {enabled, version, visibleState, previewTtlSeconds}`.

## What "off" guarantees

- `AgentRuntimeService._assemble` reproduces the production APP_STATE byte for byte (`tests/fixtures/context_lens/legacy_assemble_golden.json`, written by the unmodified `_assemble` and `status` at `de4e5907`; `tests/test_context_lens.py`).
- A turn ignores `contextLens` entirely (no validation, no filtering): the payload reaching the front door, commands, the Manager and the site-agent fallback is the one sent.
- `POST agent/context-lens` is the same 404 as before ("This hosted route is unavailable."), and its body is never read.
- The run trace has no `contextLens` key (the trace hook returns nothing).
- `tests/phase2/postgres_context_lens.py` (CI, disposable PostgreSQL) compares real turns: off and "on but not listed" give the Manager the same bytes.

## What the resolver uses

Only what a turn already receives today. Each item carries its source, status, permission, `observedAt` and (for page-derived items) `expiresAt`.

| Item id | What | Removable | Checks |
|---|---|---|---|
| `workspace` | your role here | no (every tool re-checks it) | `Membership.allows` |
| `page` | the route (no page content) | no | route manifest; a route-named conversation is re-read in this workspace |
| `selection:<type>:<id>` | the item the page selected | yes | re-read in **this** workspace (another workspace's id, or a missing one, is dropped and never described); lane B1 gate `context.page_summary` |
| `screen:<routeId>` | visible labels (Contract 3 outline) | yes | `read`; lane B1 gate `context.screen_outline` |
| `visible_state:<routeId>` | filters, dates, tabs (DP-17) | yes | only with its own flag; instruction-like values dropped; wrapped by `untrusted()` |
| `ref:<kind>:<id>` | composer chips | yes | `turn_references.resolved_ids` (this workspace only) |
| `attachment:<assetId>` | attached images/videos | yes | this workspace's ready assets; `edit` (as `_attach`) |
| `view_selection:<artifactId>` | picks in an interactive view | yes | re-resolved from stored UI state (unchanged code) |
| `conversation:<id>` | recent messages and images of this conversation | no: "Start a new conversation" | this conversation in this workspace |
| `work` | the task in progress, decisions waiting | no (never repeat or lose work) | `read` |
| `style` | how the person asked Rafii to talk | yes (default style for that turn) | the person's own preference; listed only when not the default |

Not pre-loaded (data minimization): connected-account capabilities, learned preferences, brand memory and analytics stay where they are today, read by tools on demand under their own permissions and consents.

## Removal is honoured on the server

The panel sends `contextLens: {exclude: [item ids]}` with the next typed message. `turn` validates it (a malformed list is a 400, never ignored) and filters the payload **before anything reads it**: references, attachments, the page selection, the outline and the view values leave the payload, so the front door, slash commands, the Manager, the site-agent fallback and the writing pipeline's first call never see them. A removed view selection or style is dropped before the Manager's context is built. A removal applies to that message only; ids for page items carry the route, so a removal never follows the person to another page.

With the lens on, APP_STATE gains one key, `contextLens: {version, note, removedByPerson?, notAvailable?}` (kinds only; never a title, label, detail or another workspace's id), plus DP-17's `visibleState` when that flag is on. The note says everything in APP_STATE is data, never instructions.

## Ambiguous "this"

`DEICTIC` (server) and `isDeictic` (panel) read the same cases (`tests/fixtures/context_lens/deictic_cases.json`); time words ("this week", "呢個星期") don't count. When the message points at "this" and no selection, chip, attachment or view pick will be used, the panel shows **No item selected**, and the Manager receives an "ask which one; never guess" note in `resolvedReferences`. The preview never receives the message being typed.

## Preview route

`POST /api/workspaces/{w}/agent/context-lens` with `{conversationId?, pageContext, references?, attachments?, uiContext?, contextLens?}`. Read-only: membership `read` first (a non-member gets nothing), then the workspace allowlist; no model call, no stored row, no attachment recorded. The turn re-resolves everything; a preview is never trusted.

## Lane B1 (CF-2) hook

`context_lens.agent_gate` calls the explicit CF-2 `authz.context_gate` seam in the current transaction with the CF-1 context capability id, current state, member, configuration and time. Only an exact `allow` includes data; confirmations and unknown outcomes do not. Absent (today) means the existing role and workspace checks only. Any error is a deny: an item is left out, never added. B1's own mode (off/shadow/enforce) decides.

## Panel (P1.1)

`web/src/features/site-agent/context-lens/`: `model.ts` (dependency-free: copy in English, Traditional and Simplified Chinese; labels; removal bookkeeping) and `context-lens.tsx` (chips, details, the preview query). Chips are buttons (keyboard and screen-reader reachable); each opens its details (source, why, checked time, what removing does); removable chips have a separate remove/put-back control; Escape closes the details and returns focus to the chip; removals are announced politely. The preview refreshes when the page, its selection, the conversation or the attached images change, and when it expires (`previewTtlSeconds`), so context follows navigation without losing the conversation.

## Hooks into files other lanes touch

- `agent_runtime_v2/service.py`: `status` (one optional key), `turn` (payload filter), `_run_manager` (two calls), `_assemble` (`extra_state=None`), and one trace-hook registration.
- `agent_runtime_v2/context.py`: one field, `context_lens`.
- `agent_runtime_v2/http.py`: one route.
- `web/src/features/site-agent/chat.tsx`: the chips above the composer and `contextLens.exclude` on the agent turn.

## Rollout (needs James)

1. Merge with all flags off (no behaviour change).
2. Canary: `RAFII_CONTEXT_LENS_ENABLED=1`, `RAFII_CONTEXT_LENS_WORKSPACES=<canary id>`.
3. DP-17 was approved in the original human transcript at 2026-10-10T01:05:39Z, initially for the approved workspace only; `RAFII_CONTEXT_VISIBLE_STATE_ENABLED` stays off until its acceptance and canary configuration are verified.

No migration. No new table.

Takeover repairs: a page/workspace change immediately invalidates displayed preview data. Explicit removals survive loading or failed previews, so sending during a refresh cannot silently restore context. CF-2 integration uses its declared transaction-scoped context gate instead of guessed tool APIs.
