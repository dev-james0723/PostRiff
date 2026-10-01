'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { founderFetch, founderKeys } from '@/lib/founder/api';
import { useFounderScope } from '../customers/kit/api';
import type { Envelope } from '../customers/kit/types';
import type { ActionKind, ActionResponse, ActionsList } from './types';

/**
 * Founder action calls over the shared client (`founderFetch`: same-origin cookie, CSRF on POST, 401 → sign-in, fixed
 * error copy). Writes are Live only and are never sent from Demo; the listing is read only by an operator holding
 * `audit.read`, so a page without it sends no request that would fail.
 */

export interface ActionsQuery {
  targetId?: string | null;
  kind?: ActionKind;
  limit?: number;
  enabled?: boolean;
}

/** `GET /actions`: recent requests, the active blocks and the action policies (credits on or off). Live only. */
export function useFounderActions(options: ActionsQuery = {}) {
  const scope = useFounderScope();
  const limit = options.limit ?? 50;
  const params = new URLSearchParams({ mode: 'live', limit: String(limit) });
  if (options.kind) params.set('kind', options.kind);
  if (options.targetId) params.set('targetId', options.targetId);
  return useQuery({
    queryKey: scope.key('actions', options.targetId ?? null, options.kind ?? null, limit),
    enabled: scope.ready && scope.mode === 'live' && scope.capabilities.includes('audit.read') && options.enabled !== false,
    staleTime: 15_000,
    queryFn: ({ signal }) => founderFetch<Envelope<ActionsList>>(`/actions?${params.toString()}`, { signal })
  });
}

/** One preview or confirm. The caller supplies the request id so a retry of the same payload is answered idempotently. */
export function postAction(path: string, body: Record<string, unknown>): Promise<Envelope<ActionResponse>> {
  return founderFetch<Envelope<ActionResponse>>(path, { method: 'POST', body });
}

/** After a preview or confirm: refresh the action listing (and the reconcile queue for a reconciliation). */
export function useActionRefresh() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useCallback(
    (kind: ActionKind) => {
      void client.invalidateQueries({ queryKey: scope.key('actions') });
      if (kind === 'reconcile') void client.invalidateQueries({ queryKey: founderKeys.usageUnknown(scope.mode, scope.environment) });
    },
    [client, scope]
  );
}
