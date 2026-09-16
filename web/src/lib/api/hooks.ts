'use client';

/**
 * React Query hooks over the hosted API, keyed per workspace. Pages compose
 * these; mutations invalidate the narrowest keys they affect.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useWorkspace } from '@/lib/workspace/provider';
import type { Snapshot } from './types';

export const keys = {
  snapshot: (w: string) => ['snapshot', w] as const,
  usage: (w: string) => ['usage', w] as const,
  channels: (w: string) => ['channels', w] as const,
  analytics: (w: string) => ['analytics', w] as const,
  audience: (w: string) => ['audience', w] as const,
  members: (w: string) => ['members', w] as const,
  invitations: (w: string) => ['invitations', w] as const,
  audit: (w: string) => ['audit', w] as const,
  dataRequests: (w: string) => ['data-requests', w] as const,
  conversations: (w: string) => ['conversations', w] as const,
  messages: (w: string, id: string) => ['messages', w, id] as const,
  memory: (w: string) => ['memory', w] as const,
  sessions: ['sessions'] as const,
  models: ['models'] as const,
  privacyNotice: ['privacy-notice'] as const
};

function useScoped() {
  const { api, workspaceId } = useWorkspace();
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useSnapshot() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.snapshot(w), queryFn: () => api.snapshot(w), enabled });
}

export function useUsage() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.usage(w), queryFn: () => api.usage(w), enabled });
}

export function useChannels() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.channels(w), queryFn: () => api.channels(w), enabled });
}

export function useAnalytics() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.analytics(w), queryFn: () => api.analytics(w), enabled });
}

export function useAudience() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.audience(w), queryFn: () => api.audience(w), enabled });
}

export function useMembers() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.members(w), queryFn: () => api.members(w), enabled });
}

export function useInvitations() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.invitations(w), queryFn: () => api.invitations(w), enabled });
}

export function useAudit() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.audit(w), queryFn: () => api.audit(w), enabled });
}

export function useDataRequests() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.dataRequests(w), queryFn: () => api.dataRequests(w), enabled });
}

export function useConversations() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.conversations(w), queryFn: () => api.conversations(w), enabled });
}

export function useMessages(conversationId: string | null) {
  const { api, w, enabled } = useScoped();
  return useQuery({
    queryKey: keys.messages(w, conversationId ?? ''),
    queryFn: () => api.messages(w, conversationId as string),
    enabled: enabled && Boolean(conversationId)
  });
}

export function useSessions() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.sessions, queryFn: () => api.sessions() });
}

export function useModels() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.models, queryFn: () => api.models(), staleTime: 10 * 60_000 });
}

/** The Markdown memory files the agent reads before every draft, rendered by the API. */
export function useMemory() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.memory(w), queryFn: () => api.memory(w), enabled });
}

export function usePrivacyNotice() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.privacyNotice, queryFn: () => api.privacyNotice(), staleTime: 10 * 60_000 });
}

/** Single mutation channel. On success the snapshot cache is replaced with the server's response. */
export function useAct() {
  const { api, w } = useScoped();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { revision: number; action: string; payload?: Record<string, unknown> }) =>
      api.act(w, input.revision, input.action, input.payload ?? {}),
    onSuccess: (snapshot: Snapshot) => {
      client.setQueryData(keys.snapshot(w), snapshot);
      void client.invalidateQueries({ queryKey: keys.usage(w) });
      void client.invalidateQueries({ queryKey: keys.channels(w) });
    }
  });
}

export function useInvalidate() {
  const client = useQueryClient();
  const { w } = useScoped();
  return (...scopes: (keyof typeof keys)[]) => {
    for (const scope of scopes) {
      const key = keys[scope];
      void client.invalidateQueries({ queryKey: typeof key === 'function' ? key(w, '') .slice(0, 2) : key });
    }
  };
}
