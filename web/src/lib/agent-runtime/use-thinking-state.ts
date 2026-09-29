'use client';

import { useEffect, useRef, useState } from 'react';
import type { ThinkingOp } from '@/components/agents/thinking/thinking-op';
import { useAgent } from './use-agent';
import { latestThinkingOp, thinkingOrbsEnabled } from './thinking-state';

export interface LiveThinkingState {
  op: ThinkingOp;
  runId: string | null;
  startedAt?: number;
  observing: boolean;
}

/**
 * Observe semantic progress for a synchronous Agent Runtime turn while its POST is still pending.
 * Failure is deliberately silent: the UI stays on the truthful generic `working` fallback.
 */
export function useThinkingState(conversationId: string | null, pending: boolean): LiveThinkingState {
  const agent = useAgent();
  const [state, setState] = useState<LiveThinkingState>({ op: 'working', runId: null, observing: false });
  const latestOp = useRef<ThinkingOp>('working');

  useEffect(() => {
    if (!pending || !thinkingOrbsEnabled()) {
      latestOp.current = 'working';
      setState({ op: 'working', runId: null, observing: false });
      return;
    }

    let disposed = false;
    let runId: string | null = null;
    let runStartedAt: number | undefined;
    let cursor = 0;
    let failures = 0;
    let discoveryStarted = performance.now();
    let timer: number | null = null;
    let transitionTimer: number | null = null;

    const schedule = (fn: () => void, ms: number) => {
      if (disposed) return;
      timer = window.setTimeout(fn, ms);
    };

    const applyOp = (op: ThinkingOp, startedAt?: number) => {
      if (disposed || op === latestOp.current) return;
      if (transitionTimer) window.clearTimeout(transitionTimer);
      transitionTimer = window.setTimeout(() => {
        if (disposed) return;
        latestOp.current = op;
        setState((current) => ({ ...current, op, ...(startedAt != null ? { startedAt } : {}) }));
      }, 280);
    };

    const pollEvents = async () => {
      if (!runId || disposed) return;
      try {
        const result = await agent.api.runEvents(agent.workspaceId, runId, cursor);
        if (disposed) return;
        failures = 0;
        cursor = result.cursor;
        const op = latestThinkingOp(result.events, latestOp.current);
        applyOp(op, runStartedAt);
        if (result.status === 'running') schedule(() => void pollEvents(), 400);
      } catch {
        failures += 1;
        schedule(() => void pollEvents(), Math.min(4000, 400 * 2 ** Math.min(failures, 4)));
      }
    };

    const discover = async () => {
      if (!conversationId || disposed) return;
      try {
        const found = await agent.api.activeRun(agent.workspaceId, conversationId);
        if (disposed) return;
        if (found?.runId) {
          runId = found.runId;
          runStartedAt = found.startedAt;
          setState({ op: latestOp.current, runId, startedAt: runStartedAt, observing: true });
          void pollEvents();
          return;
        }
      } catch {
        // A telemetry read never changes or fails the actual turn.
      }
      const elapsed = performance.now() - discoveryStarted;
      schedule(() => void discover(), elapsed < 2000 ? 200 : 500);
    };

    latestOp.current = 'working';
    setState({ op: 'working', runId: null, observing: Boolean(conversationId) });
    if (conversationId) void discover();

    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      if (transitionTimer) window.clearTimeout(transitionTimer);
    };
  // `agent.api` is memoized by useAgent; workspace/conversation/pending define one observer lifetime.
  }, [agent.api, agent.workspaceId, conversationId, pending]);

  return state;
}
