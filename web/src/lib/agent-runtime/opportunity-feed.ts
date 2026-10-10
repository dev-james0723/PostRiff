import { APP_GUARD_HEADER, ApiError, type TokenSource } from '@/lib/api/client';

export interface Opportunity {
  id: string; digest: string; family: 'suggestion' | 'attention' | 'listening' | 'performance'; sourceId: string;
  title: string; reason: string; source: string; state: string; observedAt: number | null; expiresAt: number | null;
  action: { kind: 'open'; label: string; href: string } | { kind: 'prepare_task'; label: string; suggestionId: string } | { kind: 'experiment'; label: string };
  evidence: { type?: string; id?: string; entityType?: string; entityId?: string; revision?: number; url?: string }[];
  expectedBenefit: { kind: 'estimate'; text: string }; cost: { state: string; text: string }; permissions: string[];
  dismissalScope: 'workspace' | 'person'; canDismiss?: boolean; preview: string;
  measurement?: { kind: 'observed'; metric: string; definitionVersion: string; window: string; dateRange: [number | null, number | null]; samples: { a: number; b: number }; comparison: { accountId: string; accountLabel: string; provider: string; language: string | null; contentTypeId: string | null; dimension: string; armA: string; armB: string }; causal: false };
  task?: { taskId: string; state: string } | null;
  experiment?: { outcome?: string; measurementWindow?: string; design?: string } | null;
}
export interface Feed { workspaceId: string; items: Opportunity[]; hasMore: boolean; coverage: string; sourceLinks: { label: string; href: string }[] }
export function opportunityHref(value: string): string | null {
  return /^\/app\/(?:queue|channels|automations|weekly|analytics|library|ideas|account|tasks|workspace\/personalization)(?:\?[A-Za-z0-9_=:%&.-]+)?$/.test(value) ? value : null;
}
export function createOpportunityApi(getToken: TokenSource) {
  async function call<T>(workspace: string, suffix = '', body?: unknown, signal?: AbortSignal): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError('Sign in to open opportunities.', 401);
    const response = await fetch(`/api/workspaces/${encodeURIComponent(workspace)}/agent/creator-pipeline/opportunities${suffix}`, {
      method: body ? 'POST' : 'GET', cache: 'no-store', signal,
      headers: { ...APP_GUARD_HEADER, Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.error ?? 'Opportunities unavailable.', response.status, data.code);
    return data as T;
  }
  return {
    list: (workspace: string, signal?: AbortSignal) => call<Feed>(workspace, '', undefined, signal),
    refresh: (workspace: string) => call<Feed>(workspace, '/refresh', {}),
    decide: (workspace: string, item: Opportunity, decision: 'dismiss' | 'experiment') => call<{ workspaceId: string; id: string; state: string; verified: boolean; note: string }>(workspace, '/decide', { id: item.id, digest: item.digest, decision })
  };
}
