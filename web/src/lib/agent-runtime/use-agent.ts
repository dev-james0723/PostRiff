'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { createAgentApi, type AgentApi } from './client';

const STATUS_RETRIES = 2;

/**
 * Retry a failed status read a bounded number of times when the failure may pass (network, server busy, rate limit); never
 * for a refusal (signed out, no access, runtime absent). One lost request must not switch the agent runtime off for the page.
 */
export function statusRetry(failureCount: number, error: unknown): boolean {
  const status = typeof (error as { status?: unknown })?.status === 'number' ? (error as { status: number }).status : 0;
  if (status && status < 500 && status !== 408 && status !== 429) return false;
  return failureCount < STATUS_RETRIES;
}

/** 0.5 s, then 1.5 s (capped at 4 s). */
export function statusRetryDelay(attempt: number): number {
  return Math.min(4000, 500 * 3 ** attempt);
}

/** The one status query (shared by the hook and by a turn that is sent before the hook's query answered). */
export function agentStatusQuery(api: AgentApi, workspaceId: string | null) {
  return {
    queryKey: ['agent-runtime', 'status', workspaceId],
    queryFn: () => api.status(workspaceId as string),
    staleTime: 60_000,
    retry: statusRetry,
    retryDelay: statusRetryDelay
  };
}

/** The Agent Runtime client for the signed-in session and the current workspace, plus what this deployment allows. */
export function useAgent() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  const api = useMemo(() => createAgentApi(getToken), [getToken]);
  const status = useQuery({ ...agentStatusQuery(api, workspaceId), enabled: Boolean(workspaceId) });
  return { api, workspaceId, status: status.data ?? null, statusError: status.error, refetchStatus: status.refetch };
}
