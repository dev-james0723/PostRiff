# Rafii Design DNA: v9 addendum

Prepared: 2026-09-23  
Foundation: the unchanged `Rafii_Design_DNA_v8.md`  
Behavioral reference: `rafii-prototype-v9.html`  
Reference SHA-256: `9fa6c351bdf9dc5a2486f05c23813d7d0ce6ce1de05cea94e3d098479b6a3e39`

## Status and purpose

This is a newly prepared addendum to the recovered v8 design document, not a claim that a separate v9 design-DNA file existed previously. It records the folder behavior in the supplied v9 prototype and distinguishes it from requirements for promotion into the real application. It does not certify production implementation, current model capabilities, browser compatibility, or external research claims.

## 1. The visual foundation is unchanged

V9 inherits the monochrome, borderless neutral-glass system; selective serif-italic editorial accents; purposeful whitespace; stable selection lenses; and the WHAT / FIND / VIEW / COMMIT hierarchy from v8. It does not introduce a new palette or authorize a return to purple/colored AI chrome.

Keep the reorganized Content Library workbar, separate Language/Model/Writing Voice controls, provider/reasoning transitions, complete locale selector, semantic illustration library, phone slide/crossfade and swipe, and expanded writing surface. Native app previews and real user media remain distinct from Rafii-owned glass surfaces.

Use the existing DNA's task-specific page recipes. V9's new folder metaphor belongs in destination selection and account management, not arbitrarily on Billing, Calendar, or every list.

## 2. New reusable component: Channel Folders

A Channel Folder is a named saved set of account identities. It is a batch-selection shortcut, not an exclusive container, a platform, or a workflow preset.

Its compact glass surface shows a custom name, platform miniatures, account count, selection state and separate disclosure affordance. The miniature icons sit behind a restrained folder front; they become readable account rows when inspected. The inspector expands beneath the relevant folder row rather than at the bottom of an unrelated collection.

The main hit area selects the group; the chevron only opens/closes inspection. Neither action should require hover or drag. Optional motion compresses/lifts the folder detail, reveals the selected mark and unfolds the inspector. Preserve interruptibility, reduced motion, stable focus, and readable stationary account rows.

The account list below uses compact rows with identifiable accounts instead of six oversized app tiles. A shared search matches folder names, platform names and handles. The compact shelf exposes at most four folders with View all for the remainder, following the prototype's pin/order behavior.

## 3. Selection contract

- None, some and all selected are different states, with accessible mixed-state semantics.
- Tapping none/some adds all valid members. Tapping all removes the members and preserves unrelated selections.
- Overlapping groups derive their states from one account selection set. A shared account is counted once; different account IDs on the same platform stay distinct.
- Inspector checkboxes and individual rows edit the same staged destination set. Undo restores its previous values and selection context.
- Done commits destinations. Cancel or close discards unapplied destination changes.
- Preview navigation and Content Library app-fit browsing do not alter destinations.

The v9 folder core models distinct account IDs, but the prototype contains only one sample account per platform. Its `folders-ui.js` bridge emits a platform list alongside account IDs. Production must not collapse its generation/save/preview/publish targets to that platform list.

## 4. Folder editing is a separate saved transaction

Support New folder and Save selection as folder; name and optional symbol; add/remove members; pin/unpin; reorder within the applicable section; duplicate; and delete confirmation.

Saving a folder does not apply destinations. Cancelling Channel Bloom's staged destination choices does not undo a previously saved folder edit. Deleting a folder neither disconnects nor deselects accounts. Preserve the existing draft's membership snapshot when a saved folder changes.

Composer summaries can show the source folder or a customized state. Labels must reflect the snapshot and current selection rather than reinterpret old drafts using a newly edited folder definition.

The supplied prototype limits names to 40 characters and folders to 50 and has no nesting. Inspect existing product conventions before promoting limits; enforce/document intentional limits on both client and server. Drag-to-group, cover uploads and cross-setting workflow presets were deferred, not implemented requirements.

## 5. Settings remain orthogonal

A folder changes only destinations. It does not save or override output languages, model/provider, reasoning intensity, Writing Voice, source permissions, editorial type or native format.

Shared output language remains an explicit override of individual values. Disabling that override restores the individual configuration. Preserve any richer multiple-locale-per-account behavior already implemented in the real product.

## 6. Persistence: observed demo versus production requirement

Observed v9 stores folder definitions in browser localStorage when available and reports Session-only folders when storage is blocked. Other prototype data remains demonstration/session state. This is not cross-device, workspace-secure production persistence.

For production, reuse existing account-group services or implement minimally scoped authenticated storage with tenant/owner boundaries, membership validation, access checks, concurrency and errors. Do not persist OAuth credentials in folders. Do not silently import sample groups or map old definitions to real accounts by platform name.

Handle stale/deleted/restricted members explicitly. Saved membership and current connection capability are different facts. Expired credentials cannot become a ready checkmark just because a folder is selected.

## 7. Reuse map and validation boundary

Reference modules:

- `src/folders-core.js`: selection sets, mixed state, validation, ordering, snapshots and storage decoding.
- `src/folders-ui.js`: shelf/inspector/editor, staged destination selection, saved-folder transactions, Undo and storage feedback.
- `src/folders-v9.css`: scoped folder/account-row surfaces and responsive styling.
- `src/app.js` and `src/index.html`: the reference integration points, not a required production architecture.
- `tests/v9/`, `previews-v9/`, and `VALIDATION.md`: historical prototype evidence and limitations.

The inherited validation distinguishes successful individual suites from interrupted aggregate attempts and explicitly leaves physical iPhone/Safari, cross-device synchronization, live AI/CLI, and real multi-account generation unverified. Rerun the actual production project tests and capture current route-specific evidence. Do not use old prototype totals as the acceptance result.

Follow `Rafii_V9_Production_Integration_Agent_Prompt.md` for the complete application integration, rollout, security and handoff requirements.
