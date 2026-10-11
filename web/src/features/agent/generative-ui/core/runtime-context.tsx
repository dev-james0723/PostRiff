'use client';
/**
 * Per-message runtime facts for Rafii components (outside OpenUI's own context; lane E may read it too).
 *
 *   accepted    the rendered source is the server-accepted revision (reads and actions may run); false while streaming
 *   historical  an older message: show saved as-of data until the person explicitly asks for current data
 *   surface     chat | panel | expanded | mobile | founder (layout density)
 *   library     consumer | founder
 *   fieldHosts  component → name prop of input components (for dirty-state protection)
 *   onFirstComponent  called by the first component that renders real content (G17 mark)
 *   fetchPreview      authenticated GET of an existing same-workspace preview route (`/api/workspaces/{w}/media/…`,
 *                     `/api/workspaces/{w}/library/files/…/preview|url`) through the message's transport; null when the
 *                     view may not load previews (not accepted, founder scope, no transport)
 */
import { createContext, type JSX, type ReactNode, useContext } from 'react';
import type { UiSurface } from '@/lib/agent-runtime/ui-contracts';

export interface GenUiRuntime {
  artifactId: string;
  revision: number;
  accepted: boolean;
  historical: boolean;
  surface: UiSurface;
  library: 'consumer' | 'founder';
  /** Narrow layouts (side panel, phone) collapse grids and comparisons to one column. */
  compact: boolean;
  onFirstComponent(): void;
  fetchPreview: ((path: string, signal: AbortSignal) => Promise<Response>) | null;
}

const INERT: GenUiRuntime = {
  artifactId: '',
  revision: 0,
  accepted: false,
  historical: false,
  surface: 'chat',
  library: 'consumer',
  compact: false,
  onFirstComponent: () => undefined,
  fetchPreview: null,
};

const GenUiRuntimeContext = createContext<GenUiRuntime>(INERT);

export function GenUiRuntimeProvider(props: { value: GenUiRuntime; children: ReactNode }): JSX.Element {
  return <GenUiRuntimeContext.Provider value={props.value}>{props.children}</GenUiRuntimeContext.Provider>;
}

/** Never throws; outside a generated view everything is inert (not accepted, no reads, no actions). */
export function useGenUiRuntime(): GenUiRuntime {
  return useContext(GenUiRuntimeContext);
}
