'use client';

import { useEffect, useRef } from 'react';
import type { TimeSavingsTaskKind } from '@/lib/api/types';
import { useWorkspace } from '@/lib/workspace/provider';
import { ACTIVITY_EVENTS, ActiveTimeTracker, HEARTBEAT_MS, newSessionKey } from './active-time';

/**
 * Measure a person's active time on one workflow (a composer conversation, a draft being edited or scheduled) and
 * send it as cumulative, idempotent heartbeats. Nothing is sent until there is at least one active second: a
 * workflow nobody worked on stays unmeasured, never "0". Stops when `enabled` turns false or the component unmounts.
 * The server alone decides whether any outcome earns time back.
 */
export function useActiveWorkTimer({ workflowKey, taskKind, enabled = true }: { workflowKey: string | null | undefined; taskKind: TimeSavingsTaskKind; enabled?: boolean }) {
  const { api, workspaceId } = useWorkspace();
  const flushRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!enabled || !workflowKey || !workspaceId || typeof document === 'undefined') return;
    const clientSessionKey = newSessionKey();
    const tracker = new ActiveTimeTracker(performance.now(), document.visibilityState === 'visible');
    let sequence = 0;
    let sent = 0;
    let closed = false;

    const send = (close: boolean, keepalive: boolean) => {
      if (closed) return;
      const seconds = tracker.seconds(performance.now());
      if (close) closed = true;
      if (seconds === 0 || (seconds === sent && !close)) return;
      sequence += 1;
      sent = seconds;
      void api
        .recordActiveTime(workspaceId, { clientSessionKey, workflowKey, taskKind, activeSeconds: seconds, sequence, ...(close ? { closed: true } : {}) }, { keepalive })
        .catch(() => undefined);
    };
    const onActivity = () => tracker.activity(performance.now());
    const onVisibility = () => {
      const visible = document.visibilityState === 'visible';
      tracker.visibility(visible, performance.now());
      // Hidden is often the last reliable moment on phones: send what there is, keep the session open.
      if (!visible) send(false, true);
    };
    const onPageHide = () => send(true, true);

    for (const type of ACTIVITY_EVENTS) window.addEventListener(type, onActivity, { passive: true, capture: true });
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    const interval = window.setInterval(() => send(false, false), HEARTBEAT_MS);
    flushRef.current = () => send(false, false);

    return () => {
      window.clearInterval(interval);
      for (const type of ACTIVITY_EVENTS) window.removeEventListener(type, onActivity, { capture: true });
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
      send(true, true);
      flushRef.current = () => undefined;
    };
  }, [api, workspaceId, workflowKey, taskKind, enabled]);

  /** Send the seconds so far now, e.g. just before an action that completes the workflow. */
  return { flush: () => flushRef.current() };
}
