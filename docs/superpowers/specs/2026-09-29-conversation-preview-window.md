# Conversation phone preview: sticky, floating and resizable

Date: 2026-09-29
Base: consumer-saas at d91660b7936a5158b820914107306ad4a1e51c2d
Scope: conversation UI only. No publishing, model, billing, acquisition, notification, database, deployment or production-flag changes.

## User intent and acceptance contract

Keep the actual platform-specific phone preview visible while a desktop or iPad user reads a long conversation. The preview begins docked in the inspector, can be deliberately lifted out, moved and made smaller, and remains floating until the user drops its drag handle inside the original dock target or activates the equivalent Dock control. Merely releasing elsewhere, scrolling, changing inspector tabs, changing orientation, resizing the viewport or opening an on-screen keyboard must never dock it.

The existing DraftPreview, PostPreview, platform templates, fixed 393 by 852 phone canvas, preview tools, exports, carousel and media state are preserved. A layout change is not a new preview. Selecting a genuinely different draft retains the existing intentional draft key semantics.

## Verified starting structure

conversation-view.tsx currently renders a three-column grid only at xl. Its inspector is hidden below xl; DraftPreview has scale 0.7 and unmounts whenever Sources is selected. PhoneFrame already accepts scale, so the new window must change that prop rather than stretch the preview's internal app layout. PostPreview owns carousel, playback and guide state.

## Implementation decision

Use a small, isolated Pointer Events controller in React, pure geometry helpers and scoped CSS transitions. No new npm dependency or lockfile change is required. react-rnd remains a reasonable general-purpose option, but this single proportional window requires custom docking, viewport and accessibility policy regardless; native pointer capture lets those policies be tested directly without competing transform owners. Existing Motion usage elsewhere remains unchanged. Do not install react-rnd, another animation engine, or a docking workspace framework as part of this change.

Render the window into one stable portal container for its entire mounted lifetime, in both docked and floating modes. Never switch portal containers or conditionally render two copies of the phone. Measure the original dock slot in viewport coordinates and follow its position with a top clamp below the app header. This implements sticky behavior without relying on the ancestor scroll/overflow configuration. Track scroll in the capture phase, window resize, VisualViewport resize/scroll and ResizeObserver changes, coalescing measurements with requestAnimationFrame. Remove every observer/listener/frame on unmount.

## States and transitions

- Docked: follow the original slot's horizontal position and remain below the sticky header while scrolling. A reserved dock slot prevents conversation text reflow.
- Pending drag: pointer down on the dedicated handle records the pointer and pre-gesture state. Movement below 6 CSS pixels is a click, not a detach.
- Floating: movement beyond the threshold detaches the same window; pointer coordinates control position, constrained to the visible viewport. Releasing outside the dock leaves this mode unchanged.
- Dock candidate: while moving, highlight the original dock rectangle and show Release to dock only when the pointer is inside it. Do not attract the window early. Only a primary-pointer release inside the candidate commits docking.
- Resizing: the lower-right handle adjusts one proportional size parameter. Resizing never docks, including a release over the dock.
- Cancelled gesture: Escape, pointercancel or lost pointer capture restores the state before the gesture and clears the target. A second pointer is ignored. This is cancellation, not automatic docking.

Provide Float/Dock buttons, S/M/L size presets and click-based corner placement, plus arrow-key movement on the handle (Shift for a larger step). Those are equivalents to dragging, not hidden keyboard-only fallbacks. Escape must not dock an already-settled floating window.

## Sizing and viewport behavior

Keep controls at normal readable/tappable size. Derive phone scale from window width and preserve the logical phone canvas. Bound requested width and height against the available viewport, reserving the header and safe margins. Never allow the drag handle to leave the visible viewport. On very short keyboard viewports the content area may scroll; header controls remain accessible. VisualViewport offsets are included in position bounds. Resizing or rotating clamps an existing floating window without changing its mode.

Desktop uses the existing right inspector. Tablet widths expose the inspector rather than hiding it at xl; the conversations list yields space before the preview does. The window's public API separates its original slot from the floating layer so it can survive Sources tab changes. Below the desktop/tablet breakpoint, retain existing mobile in-message previews and hide the extra window without resetting its session state.

## Inspector and state integration

Add PreviewWindow around the selected inspector DraftPreview, passing a render function that receives scale. The selected draft key depends only on the existing variant/platform/account identity, never floating state, viewport dimensions, Sources selection or size. Keep PreviewWindow mounted while toggling Preview/Sources. When floating, Sources may occupy the original inspector area while the phone remains visible. A successful drop or explicit Dock action selects the Preview tab.

No storage of draft content or private workspace information is added. Window geometry is session-local and resets when the existing conversation/workspace keyed component unmounts. There is no cross-conversation playback or content persistence.

## Appearance and interaction

Use existing background, border, foreground and focus tokens. The floating window has a quiet border, rounded corners and a slightly stronger shadow. No backdrop, modal focus trap, screen blocking, rotating phone, momentum throw, confetti or magnetic pointer movement. Native scrolling inside the preview remains enabled; touch-action:none belongs only on drag and resize handles. Do not set it on the phone or page.

Animate explicit dock and preset changes with a restrained approximately 220ms transition. Pointer movement and resizing follow the pointer immediately, without interpolation lag. Respect prefers-reduced-motion by disabling movement transitions. Keep the window below dialogs, command palettes and existing highest-priority notifications; do not use maximum z-index.

## Files and responsibilities

- web/src/components/application/post-preview/preview-window-geometry.ts: pure viewport, proportional size, containment and position calculations.
- web/src/components/application/post-preview/preview-window.tsx: stable window/slot, input lifecycle, bounded movement, accessible controls and render-prop scale.
- web/src/features/agent/conversation-view.tsx: explicit inspector integration and tablet layout. Preserve all unrelated request, credit, media, navigation and publishing logic byte-for-byte.
- web/tests/preview-window.test.cjs: deterministic geometry/state contract tests using Node's test runner and the repo's TypeScript compiler.
- web/tests/preview-window.browser.cjs: browser acceptance against an explicitly supplied conversation URL, with no sending or publishing side effects.

## Verification gates

1. Write and run failing tests before implementing geometry. Cover proportional phone sizing, tiny viewports, visual viewport offsets, negative/offscreen positions, target hit testing and viewport changes that do not imply a mode change.
2. Compile and run those same tests after implementation; perform TS/TSX syntax diagnostics. Run full web lint, typecheck and build when dependencies are available. Never substitute syntax checking for full typechecking.
3. Browser acceptance: docked visibility during long scroll; detach and persistent position; actual drag/drop docking; resizing that does not dock; Sources while floating; same DOM preview/media instance throughout; pointer cancellation; keyboard and click alternatives; portrait/landscape iPad dimensions; reduced motion; no viewport overflow; mobile regression.
4. Real iPad Safari remains a separate manual release gate even when desktop browser emulation passes.
5. Verify the GitHub commit tree and PR diff. Report exact executed tests separately from authored but unexecuted tests. Leave merge and production deployment for explicit release authorization.

## Inline implementation plan

Task 1: commit this document before product code; create isolated feature branch from the verified base. Task 2: establish RED geometry tests, implement pure calculations, rerun to GREEN. Task 3: implement the persistent window and input cancellation/cleanup. Task 4: integrate the inspector without changing draft identity or any network/publishing behavior. Task 5: add non-destructive browser checks, run available validation and review the exact diff. Task 6: commit to the feature branch and open a PR against consumer-saas with evidence and remaining release gates.

Environment note: the editing container currently cannot resolve GitHub/npm DNS, and the previously attempted user-browser relay reported a Durable Objects read quota failure. GitHub connector access works. Do not claim npm installation, full application build, authenticated browser testing or production verification unless a subsequent tool actually succeeds.
