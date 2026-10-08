'use client';
/**
 * The only module that imports `@openuidev/react-lang` (D-A3). Everything React-side (library, renderer, primitives and
 * lane E's journey renderers) imports OpenUI from here, so the devtools opt-out always runs first and the package can be
 * audited in one place. Server-side code (the trusted validator, the asset generator) uses `@openuidev/lang-core` only.
 *
 * Rules every caller keeps:
 *   - every `<Renderer>` passes `publishObservability={false}` (the default publishes raw source to a global bus);
 *   - `toolProvider` carries read bindings only and is passed only for a server-accepted revision (D-A12);
 *   - native `Mutation` is never used; writes go through Rafii's ActionButton and the action bridge.
 */
import './openui-optout';

export * from '@openuidev/react-lang';
