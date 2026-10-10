import { APP_GUARD_HEADER, ApiError, type TokenSource } from '@/lib/api/client';
export type Platform = 'LinkedIn' | 'Instagram' | 'Threads';
export interface Selection { suggestionId: string; platforms: Platform[]; budgetCeilingUsdMicro: number }
export interface Preview extends Selection {
  workspaceId: string; digest: string; observation: string; source: { id: string; type: string; revision: number; goal: string; audience: string; facts: Record<string, unknown> };
  expectedBenefit: { kind: 'estimate'; text: string }; effort: string; cost: { state: 'unknown'; text: string; ceilingUsdMicro: number };
  permissions: string[]; inputs: { brief: string; campaignId?: string; platforms: Platform[] }; canCreate: boolean; permissionReason: string;
}
export interface CreateRequest extends Selection { digest: string; idempotencyKey: string }
export interface Entry {
  taskId: string; title: string; state: string; href: string; observation: string; recordedAt?: number; source?: { type: string; id: string; revision: number }; expectedBenefit: { text: string };
  drafts: { id: string; href: string; platform: string; revision: number }[];
  jobs: { id: string; href: string; platform: string; state: string; verified: boolean; verifiedAt: number | null; providerReference: string | null }[];
  resultsTruncated?: boolean; experiment: { hypothesis: string }; measurement: { truncated?: boolean; status: string; reason: string; posts?: { jobId: string; provider: string; metrics: Record<string, { value: number | null; availability: string; nativeName: string; observedAt: number; definitionVersion: string; readOffset: string }> }[] };
  analyticsHref: string;
}
export function createPipelineApi(getToken: TokenSource) {
  async function call<T>(workspaceId: string, suffix = '', body?: unknown, signal?: AbortSignal): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError('Sign in to open Creator Pipeline.', 401);
    const response = await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/agent/creator-pipeline${suffix}`, {
      method: body ? 'POST' : 'GET', cache: 'no-store', signal,
      headers: { ...APP_GUARD_HEADER, Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.error ?? 'Creator Pipeline is unavailable.', response.status, data.code);
    return data as T;
  }
  return {
    list: (w: string, signal?: AbortSignal) => call<{ workspaceId: string; items: Entry[]; hasMore: boolean }>(w, '', undefined, signal),
    preview: (w: string, input: Selection) => call<Preview>(w, '/preview', input),
    create: (w: string, input: CreateRequest) => call<{ taskId: string; href: string; replayed: boolean }>(w, '/create', input)
  };
}
const PREFIX = 'rafii.creator-pending.';
export function normalizePending(value: unknown): CreateRequest | null {
  if (!value || typeof value !== 'object') return null;
  const r = value as CreateRequest;
  if (typeof r.suggestionId !== 'string' || !/^[A-Za-z0-9_.:-]{1,120}$/.test(r.suggestionId) || !/^[a-f0-9]{64}$/.test(r.digest)
    || typeof r.idempotencyKey !== 'string' || r.idempotencyKey.length < 16 || r.idempotencyKey.length > 100
    || !Number.isSafeInteger(r.budgetCeilingUsdMicro) || r.budgetCeilingUsdMicro < 0 || r.budgetCeilingUsdMicro > 10_000_000
    || !Array.isArray(r.platforms) || r.platforms.length < 1 || r.platforms.length > 3 || new Set(r.platforms).size !== r.platforms.length
    || r.platforms.some((p) => !['LinkedIn', 'Instagram', 'Threads'].includes(p))) return null;
  return { suggestionId: r.suggestionId, digest: r.digest, idempotencyKey: r.idempotencyKey, platforms: [...r.platforms], budgetCeilingUsdMicro: r.budgetCeilingUsdMicro };
}
export function readPending(scope: string): CreateRequest | null {
  try { const value = sessionStorage.getItem(PREFIX + scope); return value && value.length < 2000 ? normalizePending(JSON.parse(value)) : null; } catch { return null; }
}
export function savePending(scope: string, request: CreateRequest) {
  const safe = normalizePending(request);
  if (!safe) throw Error('Invalid pending request.');
  // Persist BEFORE dispatch. If storage is unavailable, preserve safety by refusing the POST.
  sessionStorage.setItem(PREFIX + scope, JSON.stringify(safe));
}
export function clearPending(scope: string) { try { sessionStorage.removeItem(PREFIX + scope); } catch { /* unavailable */ } }
export function safeHref(value: string): string | null {
  if (!/^\/app\/(tasks\?task=|queue\?(job=|view=drafts&draft=))[-a-zA-Z0-9]+$/.test(value)) return value === '/app/analytics' ? value : null;
  return value;
}
