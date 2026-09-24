'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { keys, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { RaffiCampaign, RecurringDestination, RecurringOccurrence, RecurringTask, Snapshot, SnapshotState } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** One automation as the hub shows it: the recurring task, its brief and its runs (newest first). */
export interface Automation {
  task: RecurringTask;
  campaign: RaffiCampaign | undefined;
  name: string;
  destinations: RecurringDestination[];
  runs: RecurringOccurrence[];
  /** Runs that produced drafts. */
  drafted: RecurringOccurrence[];
  /** Automations made by the earlier campaign planner (one LinkedIn draft, no name). */
  legacy: boolean;
}

const ORDER: Record<string, number> = { active: 0, draft: 1, paused: 2, cancelled: 3 };

export function automationsOf(state: SnapshotState | undefined): Automation[] {
  const planning = state?.raffi?.campaignPlanning;
  if (!planning) return [];
  return planning.recurringTasks
    .map((task) => {
      const campaign = planning.campaigns.find((item) => item.id === task.campaignId);
      const runs = planning.occurrences.filter((item) => item.taskId === task.id).toSorted((a, b) => b.scheduledFor - a.scheduledFor);
      const legacy = task.authorityVersion !== 2;
      return {
        task,
        campaign,
        name: task.name || campaign?.goal || 'Untitled automation',
        destinations: task.destinations ?? (task.destination ? [task.destination] : []),
        runs,
        drafted: runs.filter((run) => run.state === 'completed' && run.conversationId),
        legacy
      };
    })
    .toSorted((a, b) => (ORDER[a.task.status] ?? 9) - (ORDER[b.task.status] ?? 9) || (b.task.updatedAt ?? b.task.createdAt ?? 0) - (a.task.updatedAt ?? a.task.createdAt ?? 0));
}

/** A countdown whose every date has passed, or a one-time date that has passed: still `active` on the server, with no next run. */
export function finished(automation: Pick<Automation, 'task'>): boolean {
  const kind = automation.task.schedule.kind;
  return automation.task.status === 'active' && (kind === 'countdown' || kind === 'once') && !automation.task.nextOccurrence;
}

/** Runs whose drafts nobody has opened or dismissed yet. */
export function unseen(automation: Pick<Automation, 'runs'>): RecurringOccurrence[] {
  return automation.runs.filter((run) => run.state === 'completed' && run.conversationId && !run.seenAt);
}

/** What the automation's runs cost since `since` (epoch seconds), in micro-dollars. */
export function spentSince(automation: Pick<Automation, 'runs'>, since: number): number {
  return automation.runs.reduce((sum, run) => sum + (run.state === 'completed' && (run.completedAt ?? run.scheduledFor) >= since ? (run.costUsdMicro ?? 0) : 0), 0);
}

/** The start of the viewer's current calendar month, in epoch seconds. */
export function monthStart(nowSeconds: number): number {
  const now = new Date(nowSeconds * 1000);
  return new Date(now.getFullYear(), now.getMonth(), 1).getTime() / 1000;
}

/** Campaign briefs that no automation uses yet (made by the earlier planner or a suggestion). */
export function unscheduledBriefs(state: SnapshotState | undefined): RaffiCampaign[] {
  const planning = state?.raffi?.campaignPlanning;
  if (!planning) return [];
  const used = new Set(planning.recurringTasks.filter((task) => task.status !== 'cancelled').map((task) => task.campaignId));
  return planning.campaigns.filter((campaign) => campaign.status !== 'cancelled' && !used.has(campaign.id));
}

/**
 * Snapshot-derived automations plus one serialized action channel. A stale revision
 * (`workspace_revision_conflict`) refetches the snapshot and retries once; any other refusal
 * (a disconnected account, missing facts) is returned to the caller unchanged.
 */
export function useAutomations() {
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  const automations = useMemo(() => automationsOf(state), [state]);
  const briefs = useMemo(() => unscheduledBriefs(state), [state]);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [pending, setPending] = useState(0);

  const act = useCallback(
    async (action: string, payload: Record<string, unknown>): Promise<Snapshot> => {
      const attempt = async (retry: boolean): Promise<Snapshot> => {
        const current = client.getQueryData<Snapshot>(keys.snapshot(workspaceId));
        try {
          const after = await api.act(workspaceId, current?.revision ?? 0, action, payload);
          client.setQueryData(keys.snapshot(workspaceId), after);
          return after;
        } catch (error) {
          if (retry && error instanceof ApiError && error.status === 409 && error.code === 'workspace_revision_conflict') {
            await client.refetchQueries({ queryKey: keys.snapshot(workspaceId) });
            return attempt(false);
          }
          throw error;
        }
      };
      const run = queue.current.then(
        () => attempt(true),
        () => attempt(true)
      );
      queue.current = run.catch(() => {});
      setPending((n) => n + 1);
      try {
        return await run;
      } finally {
        setPending((n) => n - 1);
      }
    },
    [api, client, workspaceId]
  );

  return { snapshot, state, automations, briefs, act, busy: pending > 0, workspaceId };
}
