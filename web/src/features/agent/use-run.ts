'use client';

import { useEffect, useState } from 'react';
import type { Run } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const ACTIVE = new Set(['running', 'queued']);
const MAX_POLL_FAILURES = 20;

/**
 * Follows one Ideas run: replays its safe events from cursor 0 and keeps polling while the
 * runtime reports it running. A run handed in from the composer is shown immediately.
 */
export function useRun(runId: string | null, seed: Run | null = null) {
  const { api, workspaceId } = useWorkspaceApi();
  const [run, setRun] = useState<Run | null>(seed);

  useEffect(() => {
    if (seed && seed.runId === runId) setRun(seed);
  }, [seed, runId]);

  useEffect(() => {
    if (!runId) {
      setRun(null);
      return;
    }
    let disposed = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await api.runEvents(workspaceId, runId, 0);
        if (disposed) return;
        failures = 0;
        setRun(next);
        if (ACTIVE.has(next.status)) timer = setTimeout(poll, 1200);
      } catch {
        // Keep the last known state and keep asking with backoff: a dropped poll is not a finished run.
        failures += 1;
        if (!disposed && failures <= MAX_POLL_FAILURES) timer = setTimeout(poll, Math.min(15000, 1200 * 2 ** failures));
      }
    };
    if (!seed || seed.runId !== runId || ACTIVE.has(seed.status)) void poll();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, workspaceId, runId]);

  return run;
}
