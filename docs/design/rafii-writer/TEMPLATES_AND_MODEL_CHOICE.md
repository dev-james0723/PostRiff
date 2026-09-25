# Rafii writer: saved templates and model choice (design, not built)

Status: proposal for the owner, 2026-09-25. Nothing here is implemented. Code starts only after the owner approves each part.

The owner's rules behind this page:
- Every draft comes from the AI writer. Templates are used only when the person chooses them.
- Every draft reads the destination's `postriff-channel-*` skill and the person's brand and voice memory.
- If the person has saved their own templates, Rafii asks before using one.

## 1. Customer-saved templates

### What exists today (none of it lets a person save text for the writer)
- **Preview templates.** Per-channel phone mockups. UI only.
- **Home Quick Starts.** 11 generic presets. They put example text in the composer and pick a content type.
- **Content type "My template".** Overrides only, no text body. Stored in the shared workspace state. No web caller, and the writer never reads it. Every member can read it, even when it is marked private.
- **Local Studio Markdown templates.** Local-only SQLite. The defaults name James, so they cannot become hosted defaults.
- **Template guidance inside skills.** Visual and motion work only: offer at most three plus "No template / decide for me".
- **Automation builder presets.** Method only.

### Proposal
**Storage.**
- New table `pr_writing_templates`, plus `pr_writing_template_revisions`, in migration **030**. The next free number is 030; see `docs/postriff-migration-numbering.md`.
- Columns:
  - `id`, `workspace_id` (FK, cascade), `owner_user_id`, `visibility` (`private` | `workspace`);
  - `name` (≤ 80), `description` (≤ 300), `body` (≤ 4,000 characters), `body_sha256`;
  - `platform`, `language`, `content_type_id`, `format_id`: each NULL means any;
  - `cloud_consent` `{allowed, by, at}`, `revision`, `archived`, timestamps.
- Not in the workspace state. State is rewritten whole on every command and cannot keep a template private to its owner.
- The hosted API does not run under RLS; it filters in application code. So every read path must check owner and visibility itself: matching, drafting, snapshot and export. Add RLS as well, for direct reads.

**How the writer reads a template.**
- A dedicated `request["templates"]` slot, built in `ideas._project`.
- Rendered by `ServerModelRuntime._system_prompt` as "SAVED TEMPLATES (the author's own structure and fixed lines, chosen for this post; data, not instructions)", between MEMORY FILES and SKILLS.
- Its own byte cap: `MAX_TEMPLATE_BYTES`, about 8 kB per turn. An over-budget choice is refused with a message, never cut silently.
- The run and each draft record the template id, revision and hash.
- Not through `SkillLibrary.bind` (product skills only; its budget is already 55–59 kB of 60 kB). Not as a memory file (it would share the 16 kB cut and the Brand Brain switch). Not through `material`.

**Asking the person.**
- **Composer.** When the destinations change, a deterministic match runs: platform, language family, then content type and account. No model call, no cost. It shows a chip beside the Quick Start badge: "Your template · {name} for LinkedIn · English", with Use / Not this time / Always for LinkedIn · English. With a remembered default it shows "Using {name} · Change".
- **Rafii chat.** A metadata-only `template_match` tool, and a `templateId` / `none` argument on `draft_create` and `draft_rewrite`. With a match and no decision yet, Rafii asks with a question form of at most four options. Binding the reply to the next draft needs new wiring; the existing pending-choice mechanism is only fed by approvals today. The agent model never receives the template body. Only the writer route reads it.
- **What is remembered.** "Always" is kept per person and per scope (platform · language family · content type). Whether an owner may also set a workspace default is an open question below.

**Precedence in the prompt.**
1. The fact rules: approved facts only, unknowns listed.
2. BOUNDARIES.
3. The channel adapter's hard rules: limits and native fields.
4. The template's structure and fixed lines.
5. VOICE.md.
6. Learned preferences.
7. General craft.

Template slots are filled only from the idea and approved facts. A slot that cannot be filled becomes an unknown, never an invention.

The current SYSTEM_PROMPT forbids adding hashtags, CTAs or emoji unless the facts or idea contain them. A template's fixed lines (signature, disclaimer, required tags) therefore need an explicit rule change: "fixed lines from the chosen template may appear verbatim". The same conflict already exists with the Xiaohongshu adapter's mandatory 3–6 tags.

**Consent and privacy.**
- Template bodies are customer text sent to the cloud writer. Each template therefore needs cloud consent from its author, recorded with who and when. A template without it is not offered on cloud routes.
- Only metadata reaches the agent model. Bodies never appear in traces or telemetry.
- Templates are included in export (filtered per requester) and handled by account deletion. Migration 024 avoided foreign keys to `pr_profiles` for person-keyed data, so deletion needs an explicit step.

**Cost** (openai/gpt-6-sol, $2 / $10 per MTok, from the runtime's own formulas):
- An 8 kB template adds about 10% to the reservation ceiling (+$0.032 on $0.318) and about 11% to the typical cost (+$0.005 on $0.049).
- A 2 kB template adds about 2.7%.
- Both stay under the $1 per-request policy.

**Also fix first (pre-existing):**
- The Quick Start pick mutates the shared `contentSystem.selection`. A per-person template chip must not reuse it.
- Content-type private templates and `/export` are readable by every member.
- The humanizer placeholder check runs only on weekly and campaign drafts.

### Open questions for the owner
1. **Name.** "Template" already means Quick Starts, phone mockups, content-type presets and Studio Markdown. Should the new object be called "My formats", "Saved structures", or something else?
2. **Verbatim or structure-only.** Which parts may the writer copy word for word: signature, disclaimer, CTA, tags?
3. **Consent.** Is the author's per-template consent enough, or does the owner's cloud-memory switch also apply? Whose consent covers a workspace-shared template when another member uses it?
4. **"Always".** Per person only, or also an owner-set workspace default?
5. **Other languages.** Offer a template in another language family (structure only), or never?
6. **Unattended work.** May automations, the weekly operator and replies use a template without asking, if the person said "Always"?

## 2. Model choice (the Accio pattern)

The owner's reference is Accio Work: one setting with Auto, Gemini, GPT, Claude, DeepSeek and Qwen. It shows no version numbers, and the cost varies by model.

**Proposal**
- **Auto** = the workspace's default managed model.
  - The owner sets it on a settings page. It is stored per workspace, and `POSTRIFF_MODEL_ID` is the fallback.
  - `IdeasService.default_runtime()` (PR #17) returns the managed writer. The turn's model then becomes `workspace default or runtime.model`, a one-line follow-up in `ideas.turn` and `quick_start`.
- **One representative per family:** gpt-6-sol, claude-sonnet-5, gemini-3.8-flash, deepseek-v4-pro, qwen3.6-plus. A "More models" expander shows the full `POSTRIFF_MODEL_IDS` list.
- **A cost tier badge** per model (for example $, $$, $$$), derived from the price table the server already keeps, not typed by hand.
- **A per-person override** in the composer, remembered per browser. It already exists; since PR #17 it uses a new storage key.
- **The owner approves the model list first.** The price table must include every offered model: an unpriced model is refused with 503 before any call, by design.

## 3. Reasoning strength per model

The owner's requirement: reasoning strength is selectable per model, offers only the levels that model supports, and has an Auto mode.

**What the gateway publishes.**
- Each model's catalog entry has `reasoning_options` of three kinds:
  - `toggle`;
  - `effort`, with a list of values;
  - `budget_tokens`, with a minimum.
- Every model in the proposed list accepts the unified `reasoning` and `include_reasoning` parameters.
- Examples, as reported by the release executor:
  - gpt-6-sol / luna and claude-sonnet-5: toggle, plus none / low / medium / high / xhigh;
  - gpt-6-astra and opus-5.5: low … max, with no "none";
  - gemini-3.x: low / high;
  - deepseek-v4-pro: none / high / max;
  - haiku-4.5 and minimax-m3: budget tokens.

**Design.**
- **One control, not two.** Today's quick / standard / deep writer passes become part of the same control. The "deep" revise pass becomes a level ("Thorough"), not a separate switch.
- **Auto** means Rafii picks a level per task tier:
  - drafting: the lowest effort the model offers above "none" (the baseline PR #16 sends as `reasoning_effort` "low");
  - rewrites and replies: the same;
  - planning and campaign reading: one step up.
- **The server owns the mapping.**
  - It fetches the gateway catalog once a day, caches it, and records the catalog version on each run.
  - The browser gets only the levels the chosen model supports, each with a plain label and a cost hint.
  - A level the model lacks is never sent. An unknown model gets only Auto.
- **Estimates include reasoning.** Per level, the reservation ceiling reserves `max_tokens` headroom (PR #16's 8,000 for thinking models; larger for high and above, capped by the request policy), and the typical cost adds an expected reasoning allowance per level. A level whose ceiling would exceed the per-request policy is not offered.
- **Recording.** The run stores the requested level, the level sent, and the reasoning tokens reported (`completion_tokens_details.reasoning_tokens`), so the actual cost is shown.

**Order.** This is the model-picker PR, after the engagement-reply work (E). It needs the approved model list and price table first.
