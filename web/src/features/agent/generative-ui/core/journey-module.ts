/**
 * The single seam between lane C's registry and lane E's journey components (React-free).
 *
 * Lane E owns `components/journeys/specs.ts` and exports `JOURNEY_SPEC_MODULE: JourneySpecModule` from it. Until that
 * file exists on the integration branch this module contributes no journey components, so the libraries hold only C's
 * primitives. When E lands, this file becomes exactly:
 *
 *   export { JOURNEY_SPEC_MODULE as JOURNEYS_MODULE } from '../components/journeys/specs';
 *
 * and `journey-renderers.tsx` re-exports E's `JOURNEY_RENDERERS` the same way. Nothing else changes: prompts, schemas,
 * hashes and the validator pick the new components up from `library-registry.ts`.
 */
import type { JourneySpecModule } from '../component-specs';

export const JOURNEYS_MODULE: JourneySpecModule = {
  consumer: { specs: [], groups: [] },
  founder: { specs: [], groups: [] },
  journeys: {},
};
