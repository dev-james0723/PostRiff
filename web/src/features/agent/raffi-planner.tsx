'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { InfoTip, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/queue/status-chip';
import { runLabel, scheduleSummary, statusText } from '@/features/automations/schedule';
import { automationsOf, finished, unseen } from '@/features/automations/use-automations';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import { relativeTime } from '@/lib/time';
import type { SnapshotState } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * Home's planning strip: a compact view of the workspace's Automations (built and run on the
 * Automations page) beside Rafii's evidence-backed suggestions. A suggestion that points at a
 * campaign opens that brief in the Automation builder.
 */
export function RaffiPlanner({ state, revision, canEdit }: { state: SnapshotState; revision: number; canEdit: boolean; isOwner?: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const router = useRouter();
  const activeWorkspace = useRef(workspaceId);
  activeWorkspace.current = workspaceId;
  const [busy, setBusy] = useState(false);
  const automations = automationsOf(state).filter((item) => item.task.status !== 'cancelled');
  const active = automations.filter((item) => item.task.status === 'active');
  const checkedAt = state.raffi?.suggestionsCheckedAt;
  const suggestions = state.raffi?.suggestions ?? [];
  const open = suggestions.filter((item) => item.status === 'open').length;

  async function act(action: string, payload: Record<string, unknown>) {
    setBusy(true);
    try {
      const current = client.getQueryData<{ revision: number }>(keys.snapshot(workspaceId))?.revision ?? revision;
      const next = await api.act(workspaceId, current, action, payload);
      client.setQueryData(keys.snapshot(workspaceId), next);
      if (activeWorkspace.current !== workspaceId) return null;
      return next;
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Couldn’t save this change.');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function openSuggestion(suggestionId: string) {
    const next = await act('raffi_suggestion_accept', { suggestionId });
    const ref = next?.state.raffi?.suggestions?.find((item) => item.id === suggestionId)?.actionRef;
    if (!ref?.targetId || ref.workspaceId !== workspaceId) return;
    if (ref.targetType === 'job') router.push(`/app/queue?job=${encodeURIComponent(ref.targetId)}`);
    else if (ref.targetType === 'asset') router.push(`/app/queue?asset=${encodeURIComponent(ref.targetId)}`);
    else if (ref.targetType === 'channel') router.push('/app?new=1');
    else if (ref.targetType === 'campaign') router.push(`/app/automations?campaign=${encodeURIComponent(ref.targetId)}`);
  }

  return (
    <section className='grid gap-4 md:grid-cols-2' aria-label='Automations and Rafii suggestions'>
      <Surface material='glass' padding='md' className='flex flex-col gap-4'>
        <div className='flex items-center gap-1'>
          <h2 className='text-foreground text-lg font-normal tracking-[-0.01em]'>Automations</h2>
          <InfoTip label='About automations' description='Drafts on a schedule. You still approve every draft.' className='size-9' />
        </div>
        {automations.length === 0 ? (
          <StateMessage kind='empty' layout='inline' title='No automations yet' />
        ) : (
          <ul className='flex flex-col gap-2'>
            {automations.slice(0, 3).map((item) => {
              const status = finished(item) ? { label: 'Finished' } : statusText(item.task);
              const fresh = unseen(item).length;
              const next = item.task.status === 'active' && item.task.nextOccurrence ? (item.task.nextOccurrence.scheduledFor ?? Date.parse(item.task.nextOccurrence.utc) / 1000) : null;
              return (
                <li key={item.task.id}>
                  <Link href={`/app/automations?edit=${encodeURIComponent(item.task.id)}`} className='rafii-quiet rafii-focus flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--rafii-radius-control)] px-3 py-2'>
                    <Icons.bolt className='text-muted-foreground size-4 shrink-0' />
                    <span className='flex min-w-0 flex-[1_1_10rem] flex-col'>
                      <span className='truncate text-sm font-medium'>{item.name}</span>
                      <span className='text-muted-foreground truncate text-xs'>{next ? `Next ${runLabel(next * 1000, item.task.schedule.timeZone)}` : scheduleSummary(item.task.schedule)}</span>
                    </span>
                    {fresh > 0 && <StatusChip tone='info'>{fresh} new</StatusChip>}
                    <StatusChip tone={finished(item) ? 'neutral' : item.task.status === 'active' ? 'success' : item.task.status === 'paused' ? 'warning' : 'neutral'}>{status.label}</StatusChip>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        <div className='mt-auto flex flex-wrap items-center gap-2'>
          <Button variant='glass' size='sm' className='min-h-11' onClick={() => router.push('/app/automations')}>
            {automations.length ? `Open Automations${active.length ? ` · ${active.length} active` : ''}` : 'Open Automations'}
            <Icons.arrowRight />
          </Button>
          {canEdit && (
            <Button variant='quiet' size='sm' className='min-h-11' onClick={() => router.push('/app/automations?new=1')}>
              <Icons.add />
              New automation
            </Button>
          )}
        </div>
      </Surface>

      <Surface material='glass' padding='md'>
        <div className='mb-3 flex items-center justify-between gap-3'>
          <div className='flex min-w-0 flex-col gap-0.5'>
            <h2 className='text-foreground text-lg font-normal tracking-[-0.01em]'>{open > 0 ? `${open} idea${open === 1 ? '' : 's'} for you` : 'Suggestions'}</h2>
            {/* Suggestions change only when someone presses Refresh, so the header says when that last happened. */}
            <p className='text-muted-foreground text-xs'>{checkedAt ? `Last checked ${relativeTime(checkedAt)}. Refresh to check again.` : 'Not checked yet.'}</p>
          </div>
          {canEdit && <Button variant='glass' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_suggestion_refresh', {})}>Refresh</Button>}
        </div>
        <ul className='flex flex-col gap-2'>
          {open === 0 && <li><StateMessage kind='empty' layout='inline' title='No suggestions right now' /></li>}
          {/* The evidence behind each suggestion stays one hover away, not a line of ids under every item. */}
          {suggestions.filter((item) => item.status === 'open' || item.status === 'accepted').slice(-4).toReversed().map((item) => <li key={item.id} className='rafii-quiet flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[var(--rafii-radius-control)] px-3 py-2'>
            <p className='min-w-0 flex-[1_1_12rem] text-sm' title={item.evidence.length ? `Based on ${item.evidence.map((entry) => `${entry.type} ${entry.id.slice(0, 8)}`).join(', ')}` : undefined}>{item.reason}</p>
            {canEdit && <div className='flex flex-wrap gap-1'><Button variant='action' size='sm' className='min-h-11' disabled={busy} aria-label={`Review: ${item.reason}`} onClick={() => void openSuggestion(item.id)}>Review</Button><Button variant='quiet' size='sm' className='min-h-11' disabled={busy} aria-label={`Dismiss: ${item.reason}`} onClick={() => void act('raffi_suggestion_dismiss', { suggestionId: item.id })}>Dismiss</Button>{item.status === 'open' && <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_suggestion_snooze', { suggestionId: item.id, until: Date.now() / 1000 + 86400 })}>Snooze 1 day</Button>}</div>}
          </li>)}
        </ul>
      </Surface>
    </section>
  );
}
