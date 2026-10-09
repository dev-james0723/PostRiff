'use client';

import { useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { useNotificationCenter } from '@/lib/coworker/hooks';
import { useAttention } from '@/lib/use-attention';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SiteAgentLauncher } from '@/features/site-agent/launcher';
import { panelStore, usePanel } from '@/features/site-agent/store';
import { adaptAttention, adaptServer } from './presentation';
import { deriveLiveState, type RafiiLiveState, useLiveRunStore } from './live-state';

/** The existing Ask Rafii slot becomes the Live Pill without adding a header control. */
export function RafiiLivePill({ state, onOpen }: { state: RafiiLiveState; onOpen: () => void }) {
  const reduce = useReducedMotion();
  const Icon = state.status === 'success' ? Icons.check
    : state.status === 'error' || state.status === 'degraded' ? Icons.warning
      : state.status === 'waiting' ? Icons.alertCircle : Icons.sparkles;
  return (
    <div className='flex h-11 w-11 shrink-0 items-center justify-center sm:w-32' data-live-pill-state={state.status}>
      {state.status === 'idle' ? <SiteAgentLauncher /> : (
      <motion.button
        type='button'
        layout
        initial={false}
        animate={{ width: '100%' }}
        transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 330, damping: 34 }}
        onClick={onOpen}
        aria-label={state.label + '. Open task.'}
        className='rafii-focus flex h-11 min-w-11 items-center justify-center gap-2 overflow-hidden rounded-full border border-foreground/15 bg-foreground px-2.5 text-background shadow-sm sm:px-3'
      >
        <Icon aria-hidden='true' className='size-4 shrink-0' />
        <span className='hidden min-w-0 truncate text-xs font-medium sm:inline'>{state.label}</span>
        {state.status === 'running' && typeof state.progress === 'number' && (
          <svg aria-hidden='true' viewBox='0 0 16 16' className='size-4 shrink-0 -rotate-90'>
            <circle cx='8' cy='8' r='6' fill='none' stroke='currentColor' strokeOpacity='.28' strokeWidth='2' />
            <circle cx='8' cy='8' r='6' fill='none' stroke='currentColor' strokeWidth='2'
              strokeDasharray={`${(state.progress / 100) * 37.7} 37.7`} strokeLinecap='round' />
          </svg>
        )}
        {state.status === 'running' && typeof state.progress === 'number' && <span className='sr-only'>{state.progress}% complete</span>}
      </motion.button>
      )}
    </div>
  );
}

/** Follows a known run only after its page stops updating it; there is no idle visual polling. */
export function WorkspaceLivePill() {
  const { api, workspaceId } = useWorkspaceApi();
  const router = useRouter();
  const runsByKey = useLiveRunStore((state) => state.runs);
  const panelBusy = usePanel((state) => Boolean(state.busy[workspaceId]));
  const attention = useAttention();
  const server = useNotificationCenter();
  const runs = useMemo(() => Object.values(runsByKey).filter((run) => run.workspaceId === workspaceId), [runsByKey, workspaceId]);
  const waiting = useMemo(() => [
    ...attention.items.filter((item) => item.id === 'approvals' || item.id === 'automation-drafts').map(adaptAttention),
    ...(server.data?.items ?? []).filter((item) => item.status === 'delivered' && item.actionable).map(adaptServer)
  ], [attention.items, server.data?.items]);
  const state = deriveLiveState(runs, waiting, panelBusy);
  const activeIds = runs.filter((run) => run.status === 'queued' || run.status === 'running').map((run) => run.runId).toSorted().join(',');

  useEffect(() => {
    if (!activeIds || !workspaceId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const failures = new Map<string, number>();
    const follow = async () => {
      for (const runId of activeIds.split(',')) {
        const current = useLiveRunStore.getState().runs[workspaceId + ':' + runId];
        if (!current || !['queued', 'running'].includes(current.status) || Date.now() - current.updatedAt < 2500) continue;
        try {
          const next = await api.runEvents(workspaceId, runId, 0);
          if (!stopped) useLiveRunStore.getState().report(workspaceId, next);
          failures.delete(runId);
        } catch {
          const count = (failures.get(runId) ?? 0) + 1;
          failures.set(runId, count);
          if (!stopped && count >= 3) useLiveRunStore.getState().degrade(workspaceId, runId);
        }
      }
      if (!stopped) timer = setTimeout(follow, 1500);
    };
    timer = setTimeout(follow, 1500);
    return () => { stopped = true; if (timer) clearTimeout(timer); };
  }, [activeIds, api, workspaceId]);

  useEffect(() => {
    const terminal = runs.filter((run) => ['completed', 'applied', 'failed', 'cancelled'].includes(run.status));
    const timers = terminal.map((run) => setTimeout(() => {
      const current = useLiveRunStore.getState().runs[workspaceId + ':' + run.runId];
      if (current && current.updatedAt === run.updatedAt) useLiveRunStore.getState().forget(workspaceId, run.runId);
    }, Math.max(0, run.updatedAt + (run.status === 'failed' ? 8000 : 4500) - Date.now())));
    return () => timers.forEach(clearTimeout);
  }, [runs, workspaceId]);

  return <RafiiLivePill state={state} onOpen={() => {
    if ('href' in state && state.href) router.push(state.href);
    else if (panelBusy) panelStore.setOpen(true);
  }} />;
}
