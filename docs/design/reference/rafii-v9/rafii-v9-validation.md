# Rafii v9 validation

## Delivered artifact

`rafii-prototype-v9.html` is the rebuilt self-contained v9 prototype, not a design image.
SHA-256: `9fa6c351bdf9dc5a2486f05c23813d7d0ce6ce1de05cea94e3d098479b6a3e39`.
It was built from v8 with the new folder modules and a scoped Channel Bloom interface.

## Results

**51 new folder-specific tests passed:** 21 Node state/helper tests and 30 Chromium interaction tests.
The initial pre-implementation checks failed because the folder API and UI were absent; red and green logs are included in `tests/v9/`.

Coverage includes:
- None/mixed/all group states and account-ID-based membership.
- One account in several folders; addition/removal without duplicate destinations; unrelated selections preserved; Undo.
- Inspecting a folder versus selecting it as separate actions.
- Folder creation from scratch or the current selection; name/member validation; safe text rendering.
- Rename, symbol selection, member editing, duplicate, pin/unpin, reorder, delete and confirmation.
- Search of both folders and accounts; empty results; the four-folder compact shelf and View all.
- Cancel versus Done; explicit folder-save transaction remaining independent of draft destinations.
- Composer folder label and customized-selection label.
- Generation of one draft per unique selected demo account/platform.
- Preserved model, writing voice and output language settings.
- Keyboard activation, editor Escape/back, reduced motion, intermediate-height expansion, rapid folder open/close and cleanup.
- Corrupt/empty storage decoding and two separate account IDs belonging to the same platform in the pure folder core.

**80 responsive/runtime checks passed:** eight viewport sizes × two themes × four folder interface states plus runtime checks. Sizes: 320×740, 375×812, 390×844, 430×932, 768×1024, 1024×768, 1440×1000, 1920×1080. States: shelf, inspector, editor, long name. Checks include modal bounds, horizontal overflow, scroll area, footer separation, uncaught errors and external runtime requests. Actual dark/light screenshots are in `previews-v9/` and representative images were visually inspected. Mobile and desktop renders show the folder inspector directly beneath its folder row rather than below an unrelated group.

**Retained regression evidence:** 39 inherited Node cases, 22 base browser cases, 13 phone-preview cases, 16 motion/refinement cases, 25 swipe/language/model cases, 8 taxonomy/reasoning cases, 16 Content Library cases and 10 v8 toolbar cases have passing evidence. Including new folder tests, that is 200 distinct cases with successful results. This is a coverage count, not a claim that one aggregate invocation completed successfully.

The initial aggregate runner, and two long-lived inherited v7 runner attempts, exceeded the execution budget. Other suites were rerun individually; the missing v7 cases were run in fresh processes without changing their assertions. `tests/v9/v7-case-coverage.json` lists all 16 v7 cases covered by successful runs. The interrupted logs are retained; they are not represented as green full-suite runs.

## Visual and motion evidence

- `previews-v9/390-dark-shelf.png`: compact two-column glass folder shelf and account rows.
- `previews-v9/390-dark-inspector.png`: inline folder opening and member checkboxes.
- `previews-v9/390-dark-editor.png`: rename, symbol, pin and account membership controls.
- Equivalent light and desktop states are included, along with long-name captures.
- The separately delivered `rafii-v9-folders.mp4` is an approximately eight-second recording of 225 actual Chromium screencast frames, with their captured timestamps. It demonstrates batch selection, folder unfolding, a per-draft exception, Undo, editing and saving. It is not an AI-generated animation.

## Persistence and test-environment limitations

The application attempts to store only folder definitions in localStorage and handles unavailable or corrupt storage. The browser test harness uses `set_content` in a restricted/opaque origin; the UI correctly displays **Session-only folders** there. Direct file URL navigation was blocked by the environment (`ERR_BLOCKED_BY_ADMINISTRATOR`); no policy was changed or bypassed. Normal-origin/local-file persistence across reloads and iOS Edge external-file persistence are **not verified** in this environment.

Chromium was used for tests and screenshots. Physical iPhone/Safari/Edge, Firefox, screen-reader behaviour, real mobile keyboard/safe-area behaviour and cross-device synchronization are not verified. Responsive geometry and keyboard tests are not a full accessibility audit or performance certification.

The prototype has six demo accounts, one per platform. Folder data uses distinct account IDs; real multiple-account-per-platform generation and connection flows are outside this prototype. There is no live AI/CLI invocation, social account access, translation service, scheduling or publishing. Folder membership changes do not overwrite language, model, voice or an existing draft's saved destination snapshot.

No live website or repository was modified or deployed. Prior app-fit research and native preview templates are inherited from v8; their external factual status was not refreshed during this folder-focused update.
