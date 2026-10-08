/**
 * Renderer contract of a journey component (lane E): the props object OpenUI evaluated for the statement, OpenUI's own
 * node renderer and the stable statement id (lane C's containers key children by it, so state survives patches).
 */
import type { ReactNode } from 'react';

export interface JourneyRendererProps {
  props: Record<string, unknown>;
  renderNode: (value: unknown) => ReactNode;
  statementId?: string;
}

export type JourneyRenderer = (input: JourneyRendererProps) => ReactNode;
