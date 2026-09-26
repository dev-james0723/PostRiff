'use client';

import { useEffect, useRef, useState } from 'react';
import type { CreditEstimate } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export interface CreditEstimateBody {
  operation: 'quick-start' | 'turn';
  conversationId?: string;
  request: Record<string, unknown>;
}

/**
 * The server's estimate for the exact request a quote would bind, refreshed after edits settle. `refreshKey` asks
 * again when something outside the body changes what the server will price (on Auto: the model Auto resolves to);
 * the body sent is unchanged, so the estimate still matches the quote.
 */
export function useCreditEstimate(enabled: boolean, body: CreditEstimateBody, refreshKey?: string) {
  const { api, workspaceId } = useWorkspaceApi();
  const key = enabled ? JSON.stringify([body, refreshKey ?? null]) : '';
  const [result, setResult] = useState<{ key: string; estimate: CreditEstimate | null; error: string | null }>({ key: '', estimate: null, error: null });
  const latest = useRef(0);
  useEffect(() => {
    if (!key) return;
    const mine = ++latest.current;
    const timer = setTimeout(() => {
      const [request] = JSON.parse(key) as [Record<string, unknown>, string | null];
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
