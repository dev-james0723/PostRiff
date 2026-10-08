'use client';
/**
 * The founder Generative UI library (J09), read-only in this release (D-A22): lane C's primitives without Form,
 * ActionButton or AssetPreview, plus lane E's founder components. Loaded as its own chunk by the renderer only for the
 * founder surface; never used for consumer messages.
 */
import { buildReactLibrary } from './core/build-library';
import { JOURNEY_RENDERERS } from './core/journey-renderers';
import { PRIMITIVE_RENDERERS } from './components/primitives';

export const FOUNDER_RENDERERS = { ...PRIMITIVE_RENDERERS, ...JOURNEY_RENDERERS };
export const FOUNDER_LIBRARY = buildReactLibrary('founder', FOUNDER_RENDERERS);
