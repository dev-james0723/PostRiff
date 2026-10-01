'use client';

import { useQuery } from '@tanstack/react-query';
import { founderFetch } from '@/lib/founder/api';
import { useFounderScope } from '../customers/kit/api';
import type { IncidentDetail } from './types';

/**
 * Local queries for Operations (CONTRACTS §8.D). Metric panels use the kit's `useMetric`; this file holds the one read
 * the kit does not name. Keys follow `['founder', mode, environment, …]` so a mode switch never shares cache.
 */

/** `GET /incidents/{id}?mode=` — one incident with the server's timeline. Only asked for an incident the list returned. */
export function useIncidentDetail(id: string | null, enabled = true) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('incident', id),
    enabled: scope.ready && Boolean(id) && enabled,
    retry: false,
    staleTime: 30_000,
    queryFn: ({ signal }) => founderFetch<IncidentDetail>(`/incidents/${encodeURIComponent(id as string)}?${new URLSearchParams({ mode: scope.mode }).toString()}`, { signal })
  });
}
