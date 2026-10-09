'use client';
/**
 * The founder Generative UI library (J09), read-only in this release (D-A22): lane C's primitives without Form,
 * ActionButton or AssetPreview, plus lane E's founder components. Loaded as its own chunk by the renderer only for the
 * founder surface; never used for consumer messages.
 */
import { buildReactLibrary } from './core/build-library';
import { FOUNDER_JOURNEY_RENDERERS } from './core/founder-journey-renderers';
import { PRIMITIVE_RENDERERS } from './components/primitives';

/** D-A45: only lane E's founder renderers (never the consumer journey map) join the founder chunk. */
export const FOUNDER_RENDERERS = { ...PRIMITIVE_RENDERERS, ...FOUNDER_JOURNEY_RENDERERS };
export const FOUNDER_LIBRARY = buildReactLibrary('founder', FOUNDER_RENDERERS);
