'use client';
/**
 * Founder journey renderers (lane E, J09): a separate module so lane C's founder library/chunk alone imports them and no
 * founder component ships in the consumer chat bundle.
 */
import { FounderAttentionList, FounderCostBreakdown, FounderMetricsTable, FounderNote, FounderSourceHealth } from './founder';
import { tagged } from './tagged';
import type { JourneyRenderers } from './types';

const RENDERERS: JourneyRenderers = {
  FounderNote,
  FounderMetricsTable,
  FounderCostBreakdown,
  FounderAttentionList,
  FounderSourceHealth,
};

export const FOUNDER_JOURNEY_RENDERERS: JourneyRenderers = Object.fromEntries(Object.entries(RENDERERS).map(([name, renderer]) => [name, tagged(name, renderer)]));
