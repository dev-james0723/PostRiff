import type { AuthMode, Me, WorkspaceListItem } from '@/lib/api/types';

/** Verified account and memberships only; never a bearer token or workspace content. */
export interface WorkspaceBootstrap {
  mode: AuthMode;
  me: Me;
  workspaces: WorkspaceListItem[];
  workspaceId: string;
  fetchedAt: number;
}

export function bootstrapOrigin(values: Record<string, string | undefined>): string | null {
  const local = values.POSTRIFF_DEV_SSR === '1' && !values.VERCEL;
  const raw = local ? values.POSTRIFF_API_ORIGIN : values.NEXT_PUBLIC_APP_URL;
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null;
    if (local ? url.protocol !== 'http:' || url.hostname !== '127.0.0.1' : url.protocol !== 'https:') return null;
    return url.origin;
  } catch { return null; }
}

export async function fetchWorkspaceBootstrap(origin: string, token: string, mode: AuthMode, selected: string | undefined, send: typeof fetch = fetch): Promise<WorkspaceBootstrap | null> {
  // Fixed endpoints only; no request host, redirect, shared cache, mutation or token serialization.
  async function get<T>(path: string): Promise<T> {
    const response = await send(origin + path, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(2500) });
    if (!response.ok) throw new Error('Workspace bootstrap unavailable');
    return response.json() as Promise<T>;
  }
  try {
    const [me, spaces] = await Promise.all([get<Me>('/api/me'), get<{ workspaces: WorkspaceListItem[] }>('/api/workspaces')]);
    if (!me.userId || !spaces.workspaces.length || (me.mfa.enforced && me.mfa.aal !== 'aal2')) return null;
    const workspaceId = spaces.workspaces.find((w) => w.workspaceId === selected)?.workspaceId ?? spaces.workspaces[0].workspaceId;
    return { mode, me, workspaces: spaces.workspaces, workspaceId, fetchedAt: Date.now() };
  } catch { return null; }
}
