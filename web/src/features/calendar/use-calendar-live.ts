'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { keys } from '@/lib/api/hooks';
import type { Job } from '@/lib/api/types';
import { useWorkspace } from '@/lib/workspace/provider';
import { jobNeedsLiveRefresh } from './calendar-kinds';

/** How often the snapshot is read again while a job is due or in flight. The worker runs once a minute. */
export const LIVE_REFRESH_MS = 30_000;

/** Epoch seconds, refreshed every 30 seconds so reviews turn "expired" without a reload. `null` until mounted. */
export function useNowSeconds(intervalMs = 30_000) {
  const [value, setValue] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setValue(Date.now() / 1000);
    tick();
    const timer = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return value;
}

/** Whether the viewport is at least `px` wide. `false` on the server and while hydrating. */
export function useMinWidth(px: number) {
  const query = `(min-width: ${px}px)`;
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    () => window.matchMedia(query).matches,
    () => false
  );
}

/**
 * Reads the snapshot again every 30 seconds while any job is in flight or waiting within five minutes of its
 * time, so a chip turns from Scheduled to Publishing to Published without a reload. Idle otherwise, and
 * skipped while the tab is hidden (React Query refetches on focus). Returns whether it is running.
 */
export function useLiveSnapshotRefresh(jobs: Job[] | undefined, nowSeconds: number | null) {
  const client = useQueryClient();
  const { workspaceId } = useWorkspace();
  const live = Boolean(jobs && nowSeconds !== null && jobs.some((job) => jobNeedsLiveRefresh(job, nowSeconds)));

  useEffect(() => {
    if (!live || !workspaceId) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [client, live, workspaceId]);

  return live;
}
