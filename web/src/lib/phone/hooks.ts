'use client';
import { useQuery } from '@tanstack/react-query';
import { useWorkspace } from '@/lib/workspace/provider';
import { PHONE_TERMINAL } from './types';
export function usePhoneSettings() {
  const { api, workspaceId } = useWorkspace();
  return useQuery({ queryKey: ['phone', workspaceId], queryFn: () => api.phoneSettings(workspaceId as string), enabled: Boolean(workspaceId), staleTime: 15_000,
    refetchInterval: (query) => query.state.data?.calls.some((call) => !PHONE_TERMINAL.has(call.state)) ? 2000 : false });
}
