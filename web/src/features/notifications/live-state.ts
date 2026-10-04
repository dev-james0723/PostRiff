import { create } from 'zustand';
import type { Run } from '@/lib/api/types';
import type { NotificationViewModel } from './presentation';

export type LiveRun = {
  workspaceId: string;
  runId: string;
  conversationId: string;
  status: string;
  stage?: string;
  progress?: number;
  updatedAt: number;
};

type LiveRunStore = {
  runs: Record<string, LiveRun>;
  report: (workspaceId: string, run: Run) => void;
  degrade: (workspaceId: string, runId: string) => void;
  forget: (workspaceId: string, runId: string) => void;
};

const keyOf = (workspaceId: string, runId: string) => workspaceId + ':' + runId;

export const useLiveRunStore = create<LiveRunStore>((set) => ({
  runs: {},
  report: (workspaceId, run) => set((current) => {
    const progress = run.events.findLast((event) => event.type === 'progress.updated');
    const next: LiveRun = {
      workspaceId, runId: run.runId, conversationId: run.conversationId,
      status: run.status, stage: progress?.stage,
      progress: typeof progress?.percent === 'number' && progress.percent >= 0 && progress.percent <= 100 ? progress.percent : undefined,
      updatedAt: Date.now()
    };
    return { runs: { ...current.runs, [keyOf(workspaceId, run.runId)]: next } };
  }),
  degrade: (workspaceId, runId) => set((current) => {
    const key = keyOf(workspaceId, runId);
    const previous = current.runs[key];
    return previous ? { runs: { ...current.runs, [key]: { ...previous, status: 'degraded', updatedAt: Date.now() } } } : current;
  }),
  forget: (workspaceId, runId) => set((current) => {
    const runs = { ...current.runs };
    delete runs[keyOf(workspaceId, runId)];
    return { runs };
  })
}));

export type RafiiLiveState =
  | { status: 'idle' }
  | { status: 'running'; label: string; href?: string; count: number; progress?: number }
  | { status: 'waiting'; label: string; href: string }
  | { status: 'success'; label: string; href: string }
  | { status: 'error'; label: string; href: string }
  | { status: 'degraded'; label: string; href?: string };

/** Server-confirmed run events and already durable attention are the only inputs. */
export function deriveLiveState(runs: readonly LiveRun[], attention: readonly NotificationViewModel[], panelBusy = false): RafiiLiveState {
  const ordered = runs.toSorted((a, b) => b.updatedAt - a.updatedAt);
  const active = ordered.filter((run) => run.status === 'queued' || run.status === 'running');
  const matchedWaiting = attention.find((item) => item.kind === 'action_required' && item.href && item.taskId && active.some((run) => run.runId === item.taskId));
  if (matchedWaiting?.href) return { status: 'waiting', label: 'Needs your input', href: matchedWaiting.href };
  if (active.length) {
    const first = active[0];
    const label = active.length > 1 ? 'Rafii · ' + active.length + ' tasks running'
      : first.stage ? 'Rafii · ' + first.stage.replace(/_/g, ' ') : 'Rafii · Working…';
    return { status: 'running', label, href: '/app/agent/' + encodeURIComponent(first.conversationId), count: active.length, progress: first.progress };
  }
  if (panelBusy) return { status: 'running', label: 'Rafii · Working…', count: 1 };
  const last = ordered[0];
  if (last) {
    const href = '/app/agent/' + encodeURIComponent(last.conversationId);
    if (last.status === 'degraded') return { status: 'degraded', label: 'Rafii connection lost', href };
    if (last.status === 'failed') return { status: 'error', label: 'Rafii couldn’t finish', href };
    if (last.status === 'completed' || last.status === 'applied') return { status: 'success', label: 'Rafii finished', href };
  }
  const waiting = attention.find((item) => item.kind === 'action_required' && item.href && item.source === 'attention');
  if (waiting?.href) return { status: 'waiting', label: 'Needs your input', href: waiting.href };
  return { status: 'idle' };
}
