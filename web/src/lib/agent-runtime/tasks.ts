/** CF3 Task Center session transport. No provider credential, optimistic mutation or alternate execution engine. */
import { APP_GUARD_HEADER, ApiError, type TokenSource } from '@/lib/api/client';

export type TaskState = 'queued' | 'running' | 'awaiting_approval' | 'blocked' | 'completed' | 'failed' | 'cancelled';
export type TaskView = 'open' | 'needs_me' | 'recent';
export interface TaskRef { taskId: string; title: string; state: TaskState }
export interface TaskSummary extends TaskRef {
  partial?: boolean; reasonCode?: string | null; version?: number; conversationId?: string; href?: string;
  createdBy?: { userId: string; isMe: boolean };
  needsMe?: { kind: 'approval' | 'step_failed' | 'blocked' | 'continue'; approvalId?: string; stepKey?: string } | null;
  progress?: { total: number; completed: number; failed: number; cancelled: number };
  current?: { stepKey: string; label: string; state: TaskState } | null;
  can?: { cancel: boolean; retry: boolean; continue: boolean };
  spend?: { spentUsdMicro: number; unknown: boolean } | null;
  updatedAt?: string; createdAt?: string; finishedAt?: string | null; nextWakeAt?: string | null;
}
export interface TaskStep {
  stepKey: string; label: string; state: TaskState; capabilityId: string | null; riskClass: 'R0' | 'R1' | 'R2' | 'R3';
  attempts: number; maxAttempts: number; generation: number; verified: boolean; reason: string | null;
  reasonCode: string | null; waitingOn: string[]; nextAttemptAt: string | null;
  delegate: { type: string; state: string; href: string | null } | null;
  undo: { compensationId: string; undoUntil: string } | null; can: { retry: boolean; undo: boolean };
}
export interface TaskApproval {
  approvalId: string; stepKey: string; kind: string; riskClass: string; digest: string;
  summary: Record<string, unknown>; requiredPermission: string; requiresStepUp: boolean; state: string;
  expiresAt: string; can: { decide: boolean; why: string | null };
}
export interface TaskReceipt {
  effectKey: string; stepKey: string; capabilityId: string; outcome: string; verified: boolean | null;
  checks: { name: string; ok: boolean }[]; changedRefs: { type: string; id: string; change: string }[];
  providerReceipt: { kind: string; jobId: string; state: string; verifiedAt: string | null } | null;
  costState: string; evidenceRefs: string[]; cannotRecall: string[]; at: string;
}
export interface TaskDetail extends TaskSummary { steps?: TaskStep[]; approvals?: TaskApproval[]; receipts?: TaskReceipt[] }
export interface TaskList { items: TaskSummary[]; nextCursor: string | null; counts: { open: number; needsMe: number }; asOf: string; engine: 'enabled' | 'disabled' }
export interface TaskEvent { id: string; seq: number; type: string; at: number; stage?: string; state?: string; label?: string; reasonCode?: string }
export interface TaskResponse { engine?: TaskDetail | { state: 'untracked' }; events: TaskEvent[]; cursor: number }
export interface TaskActionResult { verified?: boolean; outcome?: string; state?: string; note?: string; speakableSummary?: string }

const REQUEST_PREFIX = 'rafii.task-request.';
export function taskRequestKey(identity?: string): string {
  const fresh = () => `task:${crypto.randomUUID()}`;
  if (!identity || typeof sessionStorage === 'undefined') return fresh();
  try {
    const name = REQUEST_PREFIX + identity;
    const prior = sessionStorage.getItem(name);
    if (prior) return prior;
    const key = fresh(); sessionStorage.setItem(name, key); return key;
  } catch { return fresh(); }
}
export function forgetTaskRequest(identity: string) {
  try { sessionStorage.removeItem(REQUEST_PREFIX + identity); } catch { /* unavailable browser storage */ }
}

export function createTaskApi(getToken: TokenSource) {
  const base = (w: string) => `/api/workspaces/${encodeURIComponent(w)}/agent`;
  async function request<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    signal?.throwIfAborted();
    const res = await fetch(path, { method: body === undefined ? 'GET' : 'POST', signal, cache: 'no-store',
      headers: { ...APP_GUARD_HEADER, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (!res.ok) {
      const value = await res.json().catch(() => ({}));
      throw new ApiError(typeof value.error === 'string' ? value.error : 'This task could not be read or updated.', res.status, value.code);
    }
    return res.json() as Promise<T>;
  }
  const task = (w: string, id: string) => `${base(w)}/tasks/${encodeURIComponent(id)}`;
  return {
    list: (w: string, view: TaskView, scope: 'mine' | 'workspace', cursor: string | null, signal?: AbortSignal) =>
      request<TaskList>(`${base(w)}/tasks?${new URLSearchParams({ view, scope, limit: '20', ...(cursor ? { cursor } : {}) })}`, undefined, signal),
    detail: (w: string, id: string, signal?: AbortSignal, cursor = 0) => request<TaskResponse>(`${task(w, id)}?cursor=${cursor}`, undefined, signal),
    cancel: (w: string, id: string, version: number | undefined, key: string) =>
      request<TaskActionResult>(`${task(w, id)}/cancel`, { idempotencyKey: key, ...(version === undefined ? {} : { expectedVersion: version }) }),
    continue: (w: string, id: string, key: string) => request<TaskActionResult>(`${task(w, id)}/continue`, { idempotencyKey: key, modality: 'text' }),
    retry: (w: string, id: string, step: TaskStep, key: string) => request<TaskActionResult>(`${task(w, id)}/steps/${encodeURIComponent(step.stepKey)}/retry`,
      { idempotencyKey: key, expectedGeneration: step.generation }),
    undo: (w: string, id: string, step: TaskStep, key: string) => request<TaskActionResult>(`${task(w, id)}/steps/${encodeURIComponent(step.stepKey)}/undo`,
      { idempotencyKey: key, compensationId: step.undo?.compensationId }),
    decide: (w: string, approval: TaskApproval, decision: 'approve' | 'reject', key: string, timeZone: string) =>
      request<TaskActionResult>(`${base(w)}/approvals/${encodeURIComponent(approval.approvalId)}/decide`,
        { decision, digest: approval.digest, idempotencyKey: key, timeZone })
  };
}
