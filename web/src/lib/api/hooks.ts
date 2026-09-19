'use client';

/**
 * React Query hooks over the hosted API, keyed per workspace. Pages compose
 * these; mutations invalidate the narrowest keys they affect.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
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
  memoryProposals: (w: string) => ['memory-proposals', w] as const,
  sessions: ['sessions'] as const,
  me: ['me'] as const,
  myChannels: ['me', 'channels'] as const,
  securityEvents: ['me', 'security-events'] as const,
  myInvitations: ['me', 'invitations'] as const,
  tools: ['tools'] as const,
  models: ['models'] as const,
  privacyNotice: ['privacy-notice'] as const
};

function useScoped() {
  const { api, workspaceId } = useWorkspace();
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useTools() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.tools, queryFn: () => api.tools(), staleTime: 10 * 60_000 });
}

export function useSnapshot(options: { refetchInterval?: number | false } = {}) {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.snapshot(w), queryFn: () => api.snapshot(w), enabled, refetchInterval: options.refetchInterval, refetchIntervalInBackground: false });
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

export function useInvitations(options: { enabled?: boolean } = {}) {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.invitations(w), queryFn: () => api.invitations(w), enabled: enabled && options.enabled !== false });
}

export function useAudit() {
  const { api, w, enabled } = useScoped();
  const access = useWorkspaceAccess();
  return useQuery({ queryKey: keys.audit(w), queryFn: () => api.audit(w), enabled: enabled && checkAccess(access, { role: 'admin' }) });
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

/** The signed-in person: display name, current session, second-factor state. Not per workspace. */
export function useMe() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.me, queryFn: () => api.me() });
}

/** Every connected channel across the user's workspaces. */
export function useMyChannels() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.myChannels, queryFn: () => api.myChannels() });
}

/** The person's account history: sign-ins, second-factor changes, revoked sessions, membership changes. */
export function useSecurityEvents() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.securityEvents, queryFn: () => api.securityEvents() });
}

/** Invitations waiting for the person's verified email. */
export function useMyInvitations() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.myInvitations, queryFn: () => api.myInvitations() });
}

export function useModels() {
  const { api } = useWorkspace();
  return useQuery({ queryKey: keys.models, queryFn: () => api.models(), staleTime: 10 * 60_000 });
}

export function useRescanModels() {
  const { api, w } = useScoped();
  const client = useQueryClient();
  return useMutation({ mutationFn: () => api.rescanModels(w), onSuccess: (data) => client.setQueryData(keys.models, data) });
}

/** Rendered memory files: the API identifies which go to writing routes and which are reference only. */
export function useMemory() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.memory(w), queryFn: () => api.memory(w), enabled });
}

/** Preference proposals waiting for an owner, recent decisions, and the learned items (everyone can read). */
export function useMemoryProposals() {
  const { api, w, enabled } = useScoped();
  return useQuery({ queryKey: keys.memoryProposals(w), queryFn: () => api.memoryProposals(w), enabled });
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
      void client.invalidateQueries({ queryKey: keys.audit(w) });
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
