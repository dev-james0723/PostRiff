'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { createAgentApi } from './client';

/** The Agent Runtime client for the signed-in session and the current workspace, plus what this deployment allows. */
export function useAgent() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  const api = useMemo(() => createAgentApi(getToken), [getToken]);
  const status = useQuery({
    queryKey: ['agent-runtime', 'status', workspaceId],
    queryFn: () => api.status(workspaceId),
    enabled: Boolean(workspaceId),
    staleTime: 60_000,
    retry: false
  });
  return { api, workspaceId, status: status.data ?? null, statusError: status.error };
}
