'use client';

import { useQuery } from '@tanstack/react-query';
import { founderFetch } from '@/lib/founder/api';
import { useFounderScope } from '../customers/kit/api';
import type { Envelope } from '../customers/kit/types';
import { canListStuck, stuckPath, verifyStuck, type MetricIntervalLike, type StuckData } from './product-data';

/**
 * `GET /product/funnel/stuck?mode=&step=&start=&end=&timeZone=` (CONTRACTS §8.C, `customers.read`): the matured
 * workspaces of the funnel's own cohort interval that reached the previous step but not `step`. Asked for only when a
 * step is opened and the operator holds the capabilities the route checks, so the page never earns a 403; a refusal
 * is not retried. Keys follow `['founder', mode, environment, …]` so a mode switch never shares cache.
 */
export function useFunnelStuck(step: string | null, interval: MetricIntervalLike | null) {
  const scope = useFounderScope();
  const allowed = canListStuck(scope.capabilities, scope.mode);
  const query = useQuery({
    queryKey: scope.key('product-funnel-stuck', step, interval?.start ?? null, interval?.end ?? null, interval?.timeZone ?? null),
    enabled: scope.ready && allowed && step !== null && interval !== null,
    retry: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<StuckData>>(stuckPath(scope.mode, step as string, interval as MetricIntervalLike), { signal });
      return { ...result, data: verifyStuck(result?.data, scope.mode, step as string) };
    }
  });
  return { allowed, query };
}
