'use client';

import { useEffect, useRef, useState } from 'react';
import type { CreditEstimate } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export interface CreditEstimateBody {
  operation: 'quick-start' | 'turn';
  conversationId?: string;
  request: Record<string, unknown>;
}

/** The server's estimate for the exact request a quote would bind, refreshed after edits settle. */
export function useCreditEstimate(enabled: boolean, body: CreditEstimateBody) {
  const { api, workspaceId } = useWorkspaceApi();
  const key = enabled ? JSON.stringify(body) : '';
  const [result, setResult] = useState<{ key: string; estimate: CreditEstimate | null; error: string | null }>({ key: '', estimate: null, error: null });
  const latest = useRef(0);
  useEffect(() => {
    if (!key) return;
    const mine = ++latest.current;
    const timer = setTimeout(() => {
      api.creditEstimate(workspaceId, JSON.parse(key)).then(
        (estimate) => { if (mine === latest.current) setResult({ key, estimate, error: null }); },
        (error: unknown) => { if (mine === latest.current) setResult({ key, estimate: null, error: error instanceof Error ? error.message : 'The estimate is unavailable.' }); }
      );
    }, 600);
    return () => clearTimeout(timer);
  }, [api, workspaceId, key]);
  const current = result.key === key && key ? result : null;
  return { estimate: current?.estimate ?? null, error: current?.error ?? null, loading: Boolean(key) && !current };
}
