/**
 * Client for Rafii's agent permissions (rafii-agent-authz/1, CF-2 §17). Same transport rules as `lib/api/client.ts`: the
 * signed-in session's bearer token and the request-guard header on every call. Errors keep the server's whole body
 * (for example `stepUp` or `current`), so a page can react to the code without parsing a message.
 */
import { APP_GUARD_HEADER, ApiError, type TokenSource } from '@/lib/api/client';
import type { AgentPermissionHistory, AgentPermissionMembers, AgentPermissionsPut, AgentPermissionsReceipt, AgentPermissionsView, PermissionSource } from './agent-permissions-types';

const base = (workspaceId: string) => `/api/workspaces/${encodeURIComponent(workspaceId)}/agent/permissions`;

export class AgentPermissionsError extends ApiError {
  body: Record<string, unknown>;
  constructor(message: string, status: number, code: string | undefined, body: Record<string, unknown>) {
    super(message, status, code);
    this.name = 'AgentPermissionsError';
    this.body = body;
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: Record<string, unknown> = {};
    try {
      const parsed = (await res.json()) as unknown;
      if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
    } catch {
      /* keep the generic message */
    }
    const message = typeof body.error === 'string' && body.error ? body.error : 'Rafii could not change its permissions.';
    throw new AgentPermissionsError(message, res.status, typeof body.code === 'string' ? body.code : undefined, body);
  }
  return res.json() as Promise<T>;
}

export function createAgentPermissionsApi(getToken: TokenSource) {
  async function headers(): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }
  async function get<T>(path: string): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(), cache: 'no-store' }));
  }
  async function send<T>(method: 'PUT' | 'POST', path: string, body: unknown): Promise<T> {
    return parse<T>(await fetch(path, { method, headers: await headers(), body: JSON.stringify(body) }));
  }
  return {
    getAgentPermissions: (w: string) => get<AgentPermissionsView>(base(w)),
    putAgentPermissions: (w: string, body: AgentPermissionsPut) => send<AgentPermissionsView & { receipt: AgentPermissionsReceipt }>('PUT', base(w), body),
    revokeAgentPermissions: (w: string, body: { scopes?: string[]; all?: true; idempotencyKey: string; source?: PermissionSource }) =>
      send<AgentPermissionsView & { receipt: AgentPermissionsReceipt }>('POST', `${base(w)}/revoke`, body),
    remindAgentPermissions: (w: string, body: { action: 'shown' | 'not_now' | 'dismissed' }) =>
      send<{ reminder: { due: boolean; nextAt: number | null } }>('POST', `${base(w)}/reminder`, body),
    getAgentPermissionHistory: (w: string, options: { cursor?: string | null; member?: string | null } = {}) => {
      const query = new URLSearchParams();
      if (options.cursor) query.set('cursor', options.cursor);
      if (options.member) query.set('member', options.member);
      const suffix = query.toString();
      return get<AgentPermissionHistory>(`${base(w)}/history${suffix ? `?${suffix}` : ''}`);
    },
    getAgentPermissionMembers: (w: string) => get<AgentPermissionMembers>(`${base(w)}/members`)
  };
}

export type AgentPermissionsApi = ReturnType<typeof createAgentPermissionsApi>;
