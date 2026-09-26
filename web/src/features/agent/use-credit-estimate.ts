'use client';

import { useEffect, useRef, useState } from 'react';
import type { CreditEstimate } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export interface CreditEstimateBody {
  operation: 'quick-start' | 'turn';
  conversationId?: string;
  request: Record<string, unknown>;
}

/** The cache key: the exact body, the workspace revision it was priced on (an upload or a new note re-prices) and the
 * refresh key (on Auto: the model Auto resolves to). The body sent is unchanged, so the estimate still matches the quote. */
export function estimateKey(enabled: boolean, body: CreditEstimateBody, stateRevision?: number | null, refreshKey?: string): string {
  return enabled ? JSON.stringify([body, stateRevision ?? null, refreshKey ?? null]) : '';
}

/**
 * The server's estimate for the exact request a quote would bind, refreshed after edits settle. `refreshKey` asks
 * again when something outside the body changes what the server will price (on Auto: the model Auto resolves to);
 * `stateRevision` asks again after the workspace changes (an upload finishes, a note is read).
 */
export function useCreditEstimate(enabled: boolean, body: CreditEstimateBody, refreshKey?: string, stateRevision?: number | null) {
  const { api, workspaceId } = useWorkspaceApi();
  const key = estimateKey(enabled, body, stateRevision, refreshKey);
  const [result, setResult] = useState<{ key: string; estimate: CreditEstimate | null; error: string | null }>({ key: '', estimate: null, error: null });
  const latest = useRef(0);
  useEffect(() => {
    if (!key) return;
    const mine = ++latest.current;
    const timer = setTimeout(() => {
      const [request] = JSON.parse(key) as [Record<string, unknown>, number | null, string | null];
      api.creditEstimate(workspaceId, request).then(
        (estimate) => { if (mine === latest.current) setResult({ key, estimate, error: null }); },
        (error: unknown) => { if (mine === latest.current) setResult({ key, estimate: null, error: error instanceof Error ? error.message : 'The estimate is unavailable.' }); }
      );
    }, 600);
    return () => clearTimeout(timer);
  }, [api, workspaceId, key]);
  const current = result.key === key && key ? result : null;
  return { estimate: current?.estimate ?? null, error: current?.error ?? null, loading: Boolean(key) && !current };
}
