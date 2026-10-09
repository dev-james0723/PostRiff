'use client';
/**
 * The consumer Generative UI library (J01–J08): lane C primitives + lane E consumer journey components, as one
 * module-level OpenUI library (OpenUI keys its parser on library identity, so it must never be rebuilt per render).
 * The founder library is a separate module and chunk (`founder-library.tsx`, loaded only by the founder surface); its
 * journey renderers come from lane E's FOUNDER_JOURNEY_RENDERERS, never from this module.
 */
import { buildReactLibrary } from './core/build-library';
import { JOURNEY_RENDERERS } from './core/journey-renderers';
import { PRIMITIVE_RENDERERS } from './components/primitives';

export const CONSUMER_RENDERERS = { ...PRIMITIVE_RENDERERS, ...JOURNEY_RENDERERS };
export const CONSUMER_LIBRARY = buildReactLibrary('consumer', CONSUMER_RENDERERS);
