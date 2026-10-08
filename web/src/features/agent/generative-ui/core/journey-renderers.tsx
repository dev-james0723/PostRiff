'use client';
/**
 * The single seam between lane C's React library and lane E's journey renderers.
 *
 * Lane E owns `components/journeys/renderers.tsx` and exports `JOURNEY_RENDERERS: JourneyRenderers` from it (component name
 * → renderer, for both consumer and founder journey components). Until that file exists on the integration branch this
 * module contributes no renderers. When E lands, this file becomes exactly:
 *
 *   'use client';
 *   export { JOURNEY_RENDERERS } from '../components/journeys/renderers';
 *
 * together with the one-line change in `journey-module.ts`. `library.tsx` / `founder-library.tsx` then attach E's
 * renderers to E's specs by name; a spec without a renderer renders a quiet "can't be shown" state and fails the library test.
 */
import type { JourneyRenderers } from './component-types';

export const JOURNEY_RENDERERS: JourneyRenderers = {};
