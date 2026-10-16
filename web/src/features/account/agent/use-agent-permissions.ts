'use client';

/**
 * TanStack Query hooks over /agent/permissions (rafii-agent-authz/1). With the permissions mode off for the workspace the
 * server answers 404 `agent_permissions_unavailable`; `permissionsOff(query)` lets a surface hide itself instead of
 * showing an error. A change is never reported as saved until the server returns its receipt.
 */
import { useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AgentPermissionsError, createAgentPermissionsApi } from '@/lib/api/agent-permissions';
import type { AgentPermissionsView, PermissionSource, PresetId, ScopeChanges, SpendConfirmation } from '@/lib/api/agent-permissions-types';
import { newRequestKey, putBody } from '@/lib/agent-permissions/model';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';

export const permissionKeys = {
  view: (w: string) => ['agent-permissions', w] as const,
  history: (w: string, member: string | null) => ['agent-permissions', w, 'history', member ?? 'me'] as const,
  members: (w: string) => ['agent-permissions', w, 'members'] as const
};

export function useAgentPermissionsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createAgentPermissionsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/** True when the query failed only because permissions are not turned on for this workspace. */
export function permissionsOff(query: { error: unknown }): boolean {
  return query.error instanceof AgentPermissionsError && query.error.code === 'agent_permissions_unavailable';
}

function retry(count: number, error: unknown) {
  if (error instanceof AgentPermissionsError && error.status < 500) return false;
  return count < 2;
}

export function useAgentPermissions(options: { enabled?: boolean } = {}) {
  const { api, w, enabled } = useAgentPermissionsApi();
  return useQuery({ queryKey: permissionKeys.view(w), queryFn: () => api.getAgentPermissions(w), enabled: enabled && options.enabled !== false, retry, staleTime: 30_000 });
}

export function useAgentPermissionHistory(member: string | null = null, options: { enabled?: boolean } = {}) {
  const { api, w, enabled } = useAgentPermissionsApi();
  return useQuery({ queryKey: permissionKeys.history(w, member), queryFn: () => api.getAgentPermissionHistory(w, { member }), enabled: enabled && options.enabled !== false, retry });
}

export function useAgentPermissionMembers(options: { enabled?: boolean } = {}) {
  const { api, w, enabled } = useAgentPermissionsApi();
  return useQuery({ queryKey: permissionKeys.members(w), queryFn: () => api.getAgentPermissionMembers(w), enabled: enabled && options.enabled !== false, retry });
}

export interface Choice {
  preset: PresetId;
  changes?: ScopeChanges;
  spend?: SpendConfirmation | null;
  source: PermissionSource;
}

/** What happened to a save. `confirm` and `sign_in` wait for the person; nothing was saved yet. */
export type SaveOutcome =
  | { kind: 'saved'; view: AgentPermissionsView }
  | { kind: 'confirm' }
  | { kind: 'sign_in'; message: string }
  | { kind: 'reload'; message: string }
  | { kind: 'error'; message: string };

export function useAgentPermissionChanges() {
  const { api, w } = useAgentPermissionsApi();
  const client = useQueryClient();

  async function settle(work: () => Promise<AgentPermissionsView>): Promise<SaveOutcome> {
    try {
      const view = await work();
      client.setQueryData(permissionKeys.view(w), view);
      await client.invalidateQueries({ queryKey: ['agent-permissions', w, 'history'] });
      await client.invalidateQueries({ queryKey: permissionKeys.members(w) });
      return { kind: 'saved', view };
    } catch (error) {
      if (error instanceof AgentPermissionsError) {
        if (error.code === 'confirmation_required') return { kind: 'confirm' };
        if (error.code === 'step_up_required') return { kind: 'sign_in', message: error.message };
        if (error.code === 'agent_permissions_changed' || error.code === 'agent_permissions_copy_stale') {
          await client.invalidateQueries({ queryKey: permissionKeys.view(w) });
          return { kind: 'reload', message: error.message };
        }
        return { kind: 'error', message: error.message };
      }
      return { kind: 'error', message: error instanceof Error ? error.message : 'Rafii could not save that. Try again.' };
    }
  }

  return {
    /** First without `confirmed`; the server answers `confirmation_required` when the choice lets Rafii do more. */
    save: (view: AgentPermissionsView, choice: Choice, flags: { confirmed?: boolean; stepUp?: boolean } = {}) =>
      settle(() => api.putAgentPermissions(w, putBody(view, { ...choice, ...flags }, newRequestKey()))),
    revoke: (scopes: string[] | 'all', source: PermissionSource = 'settings') =>
      settle(() => api.revokeAgentPermissions(w, { ...(scopes === 'all' ? { all: true as const } : { scopes }), idempotencyKey: newRequestKey(), source })),
    remind: async (action: 'shown' | 'not_now' | 'dismissed') => {
      try {
        await api.remindAgentPermissions(w, { action });
      } catch {
        /* a reminder that could not be recorded simply shows again later */
      }
      await client.invalidateQueries({ queryKey: permissionKeys.view(w) });
    }
  };
}
