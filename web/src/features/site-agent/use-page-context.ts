'use client';

import { useEffect, useId } from 'react';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';
import { panelStore } from './store';

/**
 * A page tells Rafii what is selected on it (an id the server re-reads, never the object) and a few plain
 * view values. The route itself comes from the address. Registered while the page (or panel) is mounted;
 * `null` registers nothing.
 */
export function useSiteAgentPageContext(context: Pick<SiteAgentPageContext, 'selectedEntity' | 'visibleState'> | null) {
  const id = useId();
  const key = JSON.stringify(context ?? null);
  useEffect(() => {
    panelStore.register(id, JSON.parse(key));
    return () => panelStore.register(id, null);
  }, [id, key]);
}
