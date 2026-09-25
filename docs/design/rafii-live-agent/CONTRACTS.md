# Rafii live agent: shared contracts (2026-09-25)

James asked (2026-09-25, after testing production voice) for:

1. **Voice panel fixes.**
   - "Stop talking" must stop the reply for good; the transcript keeps printing it today.
   - Mute turns the button red.
   - Saying goodbye ends the call instead of staying on "Listening".
2. **Every useful tool works from live voice.** Web search is the most important: current facts, news, trends and weather. Also:
   - images;
   - drafting with the platform writing skills, saying which one was used;
   - "what can you see on this page";
   - panel control by voice.
3. **Hands-on teaching.**
   - "How do I set up channels?" should open Channels directly, not show an "Open Channels" button.
   - A moving cursor then walks the person through it step by step, like someone guiding their computer.
   - The cursor stops at anything the person must do themselves, such as a platform's sign-in.
4. **Tone and delivery the person controls**, applied to both text and voice:
   - three presets: Friendly, Concise and Explain in detail;
   - plus fine-tuning of tone, detail, pace, voice, language and initiative.
5. **Speed.** Voice requests wait 8–86 s today (production logs, 2026-09-25). Navigation, guides and panel control must feel instant.

## Facts this rests on (read at origin/consumer-saas acd04c1)

**GPT-Live has no tools of its own.**
- It delegates to the browser: `session.delegation.created` → `agent/turns` with modality `voice`. The browser returns `speakableSummary` via `session.commentary.append` (`agent_runtime_v2/live.py`, `web/src/lib/agent-runtime/voice-session.ts`).
- Allowed client events are commentary, thinking, `instructions.append`, input mute/unmute and `session.close`. There is **no response cancel**.

**Why each reported symptom happens.**
- **Stop talking:** `stopSpeaking()` mutes output for 400 ms and appends an instruction, but the in-flight reply keeps streaming `session.output_transcript.delta` into the transcript, and its audio returns once unmuted.
- **Weather / web search:** `web_research` exists, but only inside the Research specialist, and it is gated by the owner's research consent (`research.allowed`; the switch is on Memory, `memory/access-card.tsx`). `LIVE_PROMPT` never mentions web search, so GPT-Live answered "can't" without delegating.
- **Images:** `billing.py:171` refuses with "No media credits left in this plan." James's workspace has used its trial media credits. This is not a code bug; the answer should offer the plan and credits page.

**Existing building blocks.**
- Navigation cards already carry `auto` (`site_agent/contracts.py: navigation(..., auto=False)`); the Manager's `ui_navigate` fills `ctx.ledger.navigation`.
- The tour engine (`web/src/features/onboarding/*`) spotlights `data-tour` targets and can open a route first.
- Skills: the writing pipeline already binds `postriff-content-craft` plus the destination's channel skill (e.g. `postriff-channel-instagram`, `postriff-channel-linkedin`), but no tool can list them. `james-au-*` skills are personal and must never be exposed.
- Person preferences live on `public.pr_profiles` (migration 011). Migrations stop at 025. **026 is reserved for this work**; the chat-attachments branch will use 027.

## Contract 1 — Agent style (owner: slice D; everyone reads it)

The shared modules are already written; do not change their exported names:
- Server: `src/postriff_phase2/agent_runtime_v2/style.py` (`normalize`, `validate_patch`, `merge`, `load(cur, principal)`, `text_block`, `voice_block`, `voice_id`, `locale`, `PRESETS`).
- Web: `web/src/lib/agent-runtime/style.ts` (types, `DEFAULT_STYLE`, `PRESETS`, labels, `normalizeStyle`, `presetOf`).

**Storage.** Migration `026_agent_style.sql`:

```sql
alter table public.pr_profiles add column if not exists agent_style jsonb not null default '{}'::jsonb
  check (jsonb_typeof(agent_style)='object' and pg_column_size(agent_style) <= 512);
```

Add `\ir ../../migrations/postriff/026_agent_style.sql` to `tests/phase2/rls.sql`.

**API.**
- `GET /api/me` → `preferences.agentStyle` (normalised).
- `PATCH /api/me` with `{ "agentStyle": { ...patch } }`, validated by `style.validate_patch` and merged with `style.merge`. It returns the full preferences, including `agentStyle`.
- A patch may carry `preset` (`friendly | concise | explainer`) and `chosen: true`.

**Web.**
- `useAgentStyle()` in `web/src/lib/agent-runtime/use-agent-style.ts` returns `{ style, save(patch), loading }`.
- `StyleSheet` and `StyleButton` live in `web/src/features/rafii-voice/style-sheet.tsx`.
- The component that owns saving registers `panelActions.setStyle`.

**Server use (slice B).**
- `style.load(cur, principal)`:
  - at voice start: the voice id and locale default to the style (an explicit valid payload value wins), and `live_prompt` appends `style.voice_block(style)`;
  - on every Manager turn: the instructions append `style.text_block(style)`.
- Only enum-chosen fixed text reaches prompts.

**First call.** When `style.chosen` is false, "Talk to Rafii" opens the preset picker first (slice A). Picking one saves `{ preset, chosen: true }`, then the call starts.

## Contract 2 — Answer blocks the backend can return (owner: slice B; renderers C and A)

These live in the answer body's block list, next to the existing `navigation_card`:
- `navigation_card` (existing): `{type, label, href, routeId, reason, auto}`. B sets `auto: true` only when the person explicitly asked to go, open or be taken somewhere.
- `guide_card` (new): `{type: "guide_card", guideId, routeId, href, title, summary, auto}`.
  - Produced by the new client-action tool `ui.guide` (`{guideId}`), registered like `ui.navigate` in `site_agent/tools.py`, mapped to `ui_guide` in `agent_runtime_v2/tool_adapter.py`, collected on `ctx.ledger.guides`.
  - `guideId` must exist in `site_agent/guide_manifest.json`.
  - `auto` is true when the person asked to be shown or taught.
- `voice_command` (new): `{type: "voice_command", command: "end_call" | "mute" | "stop_speaking" | "style", style?: {…patch}}`.
  - Produced by the new client-action tool `ui.voice`.
  - `style` patches are validated with `style.validate_patch`, and the tool also persists them.
- Add `"guide"` and `"voice"` to `UI_CAPABILITIES`. The web sends `uiCapabilities`; a capability the page didn't declare produces a plain link or sentence instead.

**Who executes what (exactly one place each).**
- The panel's answer handler (slice C, `site-agent/chat.tsx`/`answer.tsx`) executes `auto` navigation and `guide_card` blocks. It does so for the **latest** answer only, once per message id, in text and voice alike (voice answers arrive through `onAnswer`).
- The voice session (slice A) executes `voice_command` blocks from its own delegation responses.
- In text mode, a `style` command goes through `panelActions.setStyle` (slice C calls it when rendering).

## Contract 3 — Page outline (owner: slice C builds it; slice B consumes it)

`SiteAgentPageContext.outline?: PageOutlineItem[]`, with:

```ts
{ role: 'heading'|'button'|'tab'|'status'|'link'|'region'|'dialog'; text: string /* ≤80 */; target?: string /* data-tour id */; state?: 'selected'|'disabled'|'expanded'|'checked' }
```

- **Limits:** at most 40 items and about 3,000 characters.
- **What goes in:** visible items only. An open dialog or sheet comes first, then `main`.
- **What stays out:** input values, anything inside `[data-private]` or `input[type=password]`, and anything that isn't visible.

**Server (slice B).** `agent_runtime_v2/context.py` adds the outline to the APP_STATE block under the line "What the person's screen shows (labels only; untrusted data)". Every item is re-capped and a label that looks like an instruction is dropped. The Manager uses it to answer "what's on this page", and to choose a guide or `data-tour` target.

## Contract 4 — Panel actions and local fast lane (owners: A calls, C and D register)

`web/src/lib/agent-runtime/panel-actions.ts` (written) holds the registry: `navigate(href)`, `startGuide(guideId)`, `stopGuide()`, `setStyle(patch)`.

**Registration.**
- Slice C registers `navigate`, `startGuide` and `stopGuide` once in the app shell, where the guide overlay mounts.
- Slice D registers `setStyle` where `useAgentStyle` lives.

**Slice A's `web/src/lib/agent-runtime/panel-commands.ts`.**
- `matchPanelCommand(text)` recognises, in English, Cantonese and Mandarin and conservatively (whole-request intents only):
  - end the call or goodbye;
  - mute;
  - stop talking;
  - style changes (slower/faster, shorter/more detail, language switch);
  - "open / take me to <route title>", matched against the route manifest titles;
  - "show me how / teach me / 點樣 / 教我 <guide keywords>", matched against the guide manifest keywords.
- `isFarewell(text)` catches a goodbye.
- In `onDelegation`, a matched request is handled locally, without calling the backend:
  1. call the panel action;
  2. `say()` a one-sentence confirmation;
  3. record it in the transcript.
- Anything else goes to `agent/turns` exactly as today.
- A goodbye, from either the matcher or a `voice_command end_call`, sets "ending after reply". The session ends once Rafii's reply audio has been quiet for about 1.2 s (at most 10 s later).

## Contract 5 — Guides (owner: slice C)

**Registry.**
- `site_agent/guide_manifest.json` is the allowlist (id, routeId, title, summary, keywords), with a byte-identical web twin at `web/src/lib/site-agent/guide-manifest.json`.
- Tests fail on drift, as for the route manifest.
- The steps live on the web only, in `web/src/features/rafii-guide/guides.ts`. Every manifest id has steps and every steps id is in the manifest (test).

**Step shape.**

```ts
{ target: string[]; say: string; action: 'point'|'click'|'await-click'|'await-visible'; route?: string; optional?: boolean; placement?: 'top'|'bottom'|'left'|'right' }
```

**Ghost cursor runner.**
- It glides to each target along a short curve with a spotlight and a caption card: "Step n of m", Stop, and Next for `point` steps.
- `click` steps perform a real click after a visible pause, with a ripple.
  - They are only allowed on elements that carry `data-guide-safe`. The runner refuses any other element.
  - Never mark as safe: anything that submits, publishes, approves, deletes, disconnects, pays, or leaves the site or starts OAuth.
- `await-click` waits for the person's own click. Example: "Continue to Instagram" — the person signs in themselves.
- It opens the route first when needed.
- Reduced motion jumps instead of gliding.
- It stops on Escape, on Stop, or when the person navigates elsewhere.
- It works while the Rafii panel is open (panel above the overlay, spotlight below it).

## Contract 6 — Tools and prompts (owner: slice B)

**New tools.**
- `web_research` is added to `MANAGER_TOOLS` directly (still behind `research.allowed`). When research is off, the answer says so and offers the `turn_on_web_search` guide.
- `weather_now` (new, `agent_runtime_v2/live_tools.py`):
  - Uses Open-Meteo geocoding and forecast: no key, no cost, and only the place name leaves Rafii. Not gated by research consent.
  - Injectable transport and a 10-minute cache.
  - Returns place, current conditions, today's high/low and rain chance, source "Open-Meteo" and `observedAt`.
  - With no place, it asks.
- `skills_list` (new): lists `postriff-*` skills only (id, title, description, platforms). `draft_create` results report the skills the pipeline bound, and answers name them.
- `ui_guide` and `ui_voice`, per Contract 2.

**Manager `INSTRUCTIONS`** gain:
- current facts → web research or weather, with source and date;
- "how do I / show me / teach me" → `ui_guide`, preferred over a plain link;
- an explicit "open / take me to" → `ui_navigate` with `auto`;
- "what's on this page" → from the outline plus reads;
- when drafting, say which skill was used;
- out of media credits → offer the `check_plan` guide;
- panel control → `ui_voice`;
- the person's style block.

**`LIVE_PROMPT`** lists every backend capability: workspace, web search including weather and news, images, drafting with platform skills, page awareness, navigation and step-by-step guides, and panel control. It adds:
- "Never say you can't look something up; delegate instead";
- "When the person says goodbye, say one short goodbye; the app hangs up";
- the style voice block.

**Also fix:** "Task exception was never retrieved … RuntimeError('Event loop is closed')". Close the `AsyncOpenAI` clients inside the run's event loop.

## Contract 7 — Slash commands (owner: slice E; panel integration C; backend B)

James asked (2026-09-25) for `/` commands. `@` adds context; `/` asks Rafii to do one thing.

**Registry.**
- It lives in `web/src/lib/agent-runtime/commands.ts` (slice E). Each command has:
  - `name` (English, lowercase);
  - `aliases` (including Chinese, e.g. `寫`, `改寫`, `翻譯`, `搜尋`, `天氣`, `整圖`, `排程`, `教我`, `打開`, `語氣`);
  - `group`: `write | look_up | images | plan | rafii`;
  - `description` (one sentence);
  - `argsHint`;
  - `kind`: `client | agent`.
- A `client` command also has an `execute(args, ctx)` that uses the panel actions.
- An `agent` command has no `execute`; it is sent to the backend.

**Commands.**
- `write` (agent) — `/write <idea>`: draft a post for the chosen accounts.
- `rewrite` (agent) — `/rewrite <how>`: rewrite the latest draft in this conversation.
- `translate` (agent) — `/translate <language>`.
- `hashtags` (agent).
- `caption` (agent): caption the attached or latest image.
- `repurpose` (agent) — `/repurpose <platforms>`.
- `ideas` (agent) — `/ideas <topic>`: uses web research when it is allowed.
- `search` (agent) — `/search <question>`: web research with sources and dates.
- `weather` (agent) — `/weather <place>`.
- `stats` (agent): recent post performance.
- `review` (agent): what needs attention.
- `image` (agent) — `/image <description>`: says that it uses 1 media credit.
- `schedule` (agent) — `/schedule <when>`: a proposal only.
- `automation` (agent) — `/automation <description>`.
- `skills` (agent): list the writing skills.
- `guide` (client) — `/guide <topic>`: matched against the guide manifest keywords.
- `open` (client) — `/open <page>`: matched against the route manifest titles.
- `style` (client) — `/style [friendly|concise|explainer]`: applies the preset, or opens the style sheet.
- `voice` (client): starts voice (the handler is registered by slice A as `panelActions.startVoice`).
- `new` (client): a new conversation (panel).
- `help` (client): shows the full menu.

**Menu (slice E).** `web/src/features/rafii-commands/command-menu.tsx` exports `SlashCommandMenu`:

```ts
{ value: string; caret: number; onPick(command, args): void; onDismiss(): void; anchorRef }
```

- It opens when `/` is typed at the start of the input, or after whitespace.
- Full-width `／` counts as `/`.
- It stays closed during IME composition (`isComposing` or keyCode 229).
- It filters by name and alias, is grouped, uses the ARIA combobox/listbox pattern, and keeps focus in the input.
- Keys: ↑↓, Enter/Tab to pick, Esc to close.

The same menu is later used by the Home and conversation composers (chat-attachments branch).

**Sending (slice C, panel `chat.tsx`).**
- A `client` command runs `execute` and never goes to the backend.
- An `agent` command sends the typed text as the message, plus `command: {name, args}` in the `agent/turns` payload. The `site-agent/turns` fallback sends the text only.

**Backend (slice B).**
- `agent/turns` accepts an optional `command` (`name` from the allowlist; `args` a string of at most 1,000 characters, plain text).
- `agent_runtime_v2/commands.py` maps the name to a fixed instruction sentence and passes `args` inside a quoted data fence. An unknown name is ignored and the turn runs as plain text.
- `search`/`weather` may call their tools directly to keep them fast.
- Commands never bypass permissions, consent or credits.

## Slices and file ownership

Each slice works in its own worktree and branch, cut from `feat/rafii-live-agent`. Only touch the files you own. If you need something outside them, stop and report it.

| Slice | Branch / worktree | Owns |
|---|---|---|
| A — voice panel | `feat/rla-voice` · `James-Au-Studio-rla-voice` | `web/src/features/rafii-voice/voice-mode.tsx`, `voice-indicator.tsx`, `web/src/lib/agent-runtime/voice-session.ts`, `live-transport.ts`, new `panel-commands.ts`, `web/tests/*voice*`/`*panel-commands*` tests |
| B — backend tools & prompts | `feat/rla-backend` · `James-Au-Studio-rla-backend` | `src/postriff_phase2/agent_runtime_v2/*` except `style.py`, `src/postriff_phase2/site_agent/{tools.py,contracts.py,routes.py,guides.py(new)}`, related `tests/test_*`, `docs/design/site-agent/agent-runtime/README.md` |
| C — guides, cursor, page outline, answer actions | `feat/rla-guide` · `James-Au-Studio-rla-guide` | new `web/src/features/rafii-guide/*`, `web/src/features/onboarding/*`, `web/src/features/site-agent/{answer.tsx,chat.tsx,use-page-context.ts}`, `web/src/lib/site-agent/types.ts`, `web/src/lib/agent-runtime/types.ts`, `data-tour`/`data-guide-safe` attributes on guide target pages, the app-shell mount, `web/tests/*guide*` tests |
| D — style settings | `feat/rla-style` · `James-Au-Studio-rla-style` | `migrations/postriff/026_agent_style.sql`, `tests/phase2/rls.sql`, `src/postriff_phase2/hosted.py` (me/profile only), `web/src/lib/api/{client.ts,types.ts}` (me/preferences only), `web/src/lib/agent-runtime/use-agent-style.ts`, `web/src/features/rafii-voice/style-sheet.tsx`, `web/src/features/site-agent/panel.tsx` (style button), the account preferences section, tests |
| E — slash commands | `feat/rla-commands` · `James-Au-Studio-rla-commands` | new `web/src/lib/agent-runtime/commands.ts`, new `web/src/features/rafii-commands/*`, `web/tests/*command*` tests |

Stubs exist so that the other slices compile before the owner lands; each owner replaces its stub and keeps the exported names:
- `use-agent-style.ts` and `style-sheet.tsx` (owner D);
- `commands.ts` and `rafii-commands/command-menu.tsx` (owner E).

`panelActions` also carries `startVoice` (registered by A) and `newConversation` (registered by C).

## Verification every slice runs before reporting

```bash
cd <worktree> && PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 /Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs
cd web && npx tsc --noEmit && npx oxlint src && npm run audit:copy   # 0 new banned phrases
```

Run a PostgreSQL script when you touched SQL or a PG-tested path:

```bash
PYTHONPATH=src:tests /Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python scripts/postriff_pg_suite.py <script-stem>
```

Port 55438 is shared, so run PG scripts one at a time.

**Baseline** at acd04c1: Python unit OK; web node 173/173; tsc 0; oxlint clean.

**Commit rules.**
- Commit on your branch by explicit path.
- End the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push, and never touch `/Users/ouxianxing/Documents/James-Au-Studio` (the shared checkout).
