'use client';
/**
 * Seam for lane E's founder journey renderers (D-A45), used only by `founder-library.tsx` (its own chunk, loaded only for
 * the founder surface). Lane E owns `components/journeys/founder-renderers.tsx` and exports
 * `FOUNDER_JOURNEY_RENDERERS: JourneyRenderers` from it. Until it exists on the integration branch this contributes
 * nothing; when E lands, this file becomes exactly (E carries it, as with the other two seams, D-A43):
 *
 *   'use client';
 *   export { FOUNDER_JOURNEY_RENDERERS } from '../components/journeys/founder-renderers';
 */
import type { JourneyRenderers } from './component-types';

export const FOUNDER_JOURNEY_RENDERERS: JourneyRenderers = {};
