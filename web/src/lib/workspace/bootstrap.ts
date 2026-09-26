import type { AuthMode, Me, WorkspaceListItem } from '@/lib/api/types';

/** Verified account and memberships only; never a bearer token or workspace content. */
export interface WorkspaceBootstrap {
  mode: AuthMode;
  me: Me;
  workspaces: WorkspaceListItem[];
  workspaceId: string;
  fetchedAt: number;
}

export function bootstrapOrigin(values: Record<string, string | undefined>, requestHost?: string | null): string | null {
  const local = values.POSTRIFF_DEV_SSR === '1' && !values.VERCEL;
  const preview = values.VERCEL_ENV === 'preview';
  let previewHost = values.VERCEL_URL;
  if (preview && previewHost && requestHost) {
    const allowed = [previewHost, values.VERCEL_BRANCH_URL];
    try {
      const alias = new URL(values.POSTRIFF_STAGING_PUBLIC_BASE_URL || '');
      if (alias.protocol === 'https:' && !alias.username && !alias.password && alias.pathname === '/' && !alias.search && !alias.hash) allowed.push(alias.host);
    } catch { /* no approved alias */ }
    if (allowed.includes(requestHost)) previewHost = requestHost;
  }
  const raw = local ? values.POSTRIFF_API_ORIGIN
    : preview ? (previewHost ? `https://${previewHost}` : undefined)
    : values.NEXT_PUBLIC_APP_URL;
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) return null;
    if (local ? url.protocol !== 'http:' || url.hostname !== '127.0.0.1' : url.protocol !== 'https:') return null;
    return url.origin;
  } catch { return null; }
}

export interface DeploymentAccess { cookie?: string; bypass?: string; }

export async function fetchWorkspaceBootstrap(origin: string, token: string, mode: AuthMode, selected: string | undefined, send: typeof fetch = fetch, access?: DeploymentAccess): Promise<WorkspaceBootstrap | null> {
  // Fixed endpoints only; no request host, redirect, shared cache, mutation or token serialization.
  async function get<T>(path: string): Promise<T> {
    const response = await send(origin + path, { headers: { Authorization: `Bearer ${token}`, ...(access?.cookie ? { Cookie: access.cookie } : {}), ...(access?.bypass ? { 'x-vercel-protection-bypass': access.bypass } : {}) }, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(2500) });
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
