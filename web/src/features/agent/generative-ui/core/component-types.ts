/**
 * Renderer types shared by lane C's primitives and lane E's journey components (types only; no runtime code).
 *
 * A renderer receives `{ props, renderNode, statementId }` from OpenUI: `props` are the evaluated props of its spec (always
 * re-validate them with `safeProps` from `core/props.ts`; OpenUI validates shallowly and never validates runtime values),
 * `renderNode` renders a nested component value, and `statementId` is the stable statement id (undefined for an inline
 * call). Lane E exports `JOURNEY_RENDERERS: JourneyRenderers` from `components/journeys/renderers.tsx`, keyed by the
 * component names of its specs; `core/journey-renderers.tsx` is the one import that points at it.
 */
import type { ComponentRenderProps, ComponentRenderer } from './openui';

export type RafiiComponentRenderer<P = Record<string, unknown>> = ComponentRenderer<P>;
export type RafiiRenderProps<P = Record<string, unknown>> = ComponentRenderProps<P>;

/** Component name → renderer. A spec without a renderer fails the library test (`agent-ui-library.test.cjs`). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type JourneyRenderers = Readonly<Record<string, RafiiComponentRenderer<any>>>;
