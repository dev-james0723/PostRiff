# Rafii Agent Chat concept redesign — implementation receipt

Date: 2026-09-28. Source: `docs/superpowers/handoffs/2026-09-28-rafii-agent-chat-concept-redesign-handoff.md`, its linked engineering spec, and the five saved concept images.

## Worktree and scope

The original `consumer-saas` checkout was at `468811b` with extensive unrelated changes. It was left untouched. Implementation is in the isolated worktree `codex/rafii-chat-concept-redesign-20260928`, based on `origin/consumer-saas` at `ee68839` so the current site agent and GPT Live stack are present. This is local code and local synthetic verification; it has not been pushed, merged, or deployed.

## Implemented

- Mobile Agent Chat is full viewport with a large 16 px multiline composer that tracks the visible viewport. Tablet uses a wider sheet; desktop retains a wider docked panel and dialog overlay.
- The default header shows Rafii and the current page. The expanded context view shows selected entities and registered visible state. Suggestions are large page-aware actions. Style, model, connected accounts, usage, help, conversation details, and phone entry live under More; the plus sheet exposes Research, Library, Sources, Campaign, and Model settings. No default control is called only “Custom.”
- Rafii Live is a distinct state using the existing GPT Live session and conversation. It shows connection/listening/thinking/speaking/error states, a transcript, stop speaking, mute, end, and keyboard return. The first-call style picker waits for saved style to load before starting.
- Multi-step answers show the server-reported steps and states. Proposal results have a review surface with existing guarded apply, edit, and revise paths. No progress is invented and the scheduling/publishing approval boundaries remain in place.
- The owner's `Meshy_AI_Raffi_Raccoon_Animati_0928194500_texture.glb` is the Live 3D character. `scripts/optimize_rafii_meshy_glb.py` creates the 3,869,800-byte browser GLB from the 44,054,908-byte source by resizing its embedded textures; all four geometry buffer views have identical SHA-256 hashes before and after. The local poster is rendered from that same model and covers loading/WebGL fallback. The source SHA-256 is `e07929b5b30c909f3855ce5785510ac9a810fa927e2292fead2a8907ea0d000f`.
- The Rafii browser CI routes style/commands/weather to the updated established scene and the new full-screen Live checks to `rafii-chat-concepts-browser.cjs` in Chromium and WebKit.

## Validation

- TypeScript `tsc --noEmit --incremental false`: pass. Scoped `oxlint`: zero warnings/errors. `git diff --check`, CJS syntax checks, optimizer compile, and workflow YAML parse: pass.
- Focused Node tests: 23/23.
- Chromium site-agent journey: 40/40 for desktop, full-screen phone, execution, review, approval guard, keyboard viewport, and axe. Help/tablet: 7/7.
- Synthetic Live with the Meshy model: 12/12 in Chromium and 12/12 in WebKit, including first-call style, listening/speaking, stop, mute, keyboard return, and end. Both browser runs loaded the actual 3D model.
- Established style/commands/weather browser scene: 62/62 in Chromium and 62/62 in WebKit. WebKit site-agent phone: 12/12.
- `validation_unavailable`: the local macOS Playwright WebKit desktop site-agent journey crashed in `NSTextInputContext textInputClientDidUpdateSelection` after its first 12 passing checks, on two isolated attempts (`evidence/site-agent-webkit-desktop/site-agent-browser.json`). The Linux CI desktop WebKit step has not run on this local branch. Chromium completed the corresponding desktop journey.

Browser evidence is in `evidence/`: `rafii-chat-home-live-enabled-mobile.png`, `site-agent-phone.png`, `rafii-plus-sheet-mobile.png`, `rafii-live-listening-mobile.png`, `rafii-live-speaking-mobile.png`, `rafii-execution-mobile.png`, `rafii-result-review-mobile.png`, and `desktop/site-agent-desktop-docked.png`. JSON checks are beside the screenshots; `help-tablet/`, `legacy-final/`, `legacy-webkit/`, `site-agent-webkit-phone/`, and `webkit/` contain their scoped results.

## Limits

The supplied Meshy GLB has one baked mesh and no joint rig, animation channels, or mouth morphs. Live state animates the whole character gently; it does not provide facial lip sync. Voice verification used a disposable PostgreSQL database and scriptable GPT Live stand-in, with no real provider or phone call. Production authentication, provider audio, and deployment were not exercised.
