'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function RaffiPlanner({ state, revision, canEdit }: { state: SnapshotState; revision: number; canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [goal, setGoal] = useState('');
  const [audience, setAudience] = useState('');
  const [date, setDate] = useState('');
  const [venue, setVenue] = useState('');
  const [busy, setBusy] = useState(false);
  const planning = state.raffi?.campaignPlanning;
  const campaigns = planning?.campaigns ?? [];
  const tasks = planning?.recurringTasks ?? [];
  const suggestions = state.raffi?.suggestions ?? [];

  async function act(action: string, payload: Record<string, unknown>) {
    setBusy(true);
    try {
      const current = (client.getQueryData<{ revision: number }>(keys.snapshot(workspaceId))?.revision ?? revision);
      const next = await api.act(workspaceId, current, action, payload);
      client.setQueryData(keys.snapshot(workspaceId), next);
      return next;
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Raffi could not save this change.');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function createCampaign() {
    if (!goal.trim() || !audience.trim()) return;
    const next = await act('raffi_campaign_create', { goal, audience, facts: { ...(date ? { date } : {}), ...(venue ? { venue } : {}) } });
    if (next) { setGoal(''); setAudience(''); setDate(''); setVenue(''); }
  }

  async function previewWeekly(campaignId: string) {
    await act('raffi_recurrence_preview', { campaignId, schedule: { weekday: 'Monday', localTime: '09:00', timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone }, draftsPerOccurrence: 1, route: 'local-cli' });
  }

  return (
    <section className='grid gap-4 md:grid-cols-2' aria-label='Campaign planning and Raffi suggestions'>
      <div className='bg-card ring-foreground/10 rounded-xl p-4 shadow-xs ring-1'>
        <div className='mb-3'>
          <h2 className='font-semibold'>Campaign planner</h2>
          <p className='text-muted-foreground text-xs'>Plans and recurring tasks prepare drafts only. Every post still needs its own review and approval.</p>
        </div>
        {canEdit && (
          <div className='grid gap-2 sm:grid-cols-2'>
            <Input value={goal} onChange={(event) => setGoal(event.target.value)} placeholder='Campaign goal' className='sm:col-span-2' />
            <Input value={audience} onChange={(event) => setAudience(event.target.value)} placeholder='Audience' className='sm:col-span-2' />
            <Input value={date} onChange={(event) => setDate(event.target.value)} placeholder='Date, if relevant' />
            <Input value={venue} onChange={(event) => setVenue(event.target.value)} placeholder='Venue, if relevant' />
            <Button className='sm:col-span-2' disabled={busy || !goal.trim() || !audience.trim()} onClick={() => void createCampaign()}>Create reviewable campaign</Button>
          </div>
        )}
        <div className='mt-3 space-y-2'>
          {campaigns.length === 0 && <p className='text-muted-foreground text-xs'>No campaigns yet.</p>}
          {campaigns.slice(-3).toReversed().map((campaign) => {
            const task = tasks.find((item) => item.campaignId === campaign.id);
            return <div key={campaign.id} className='border-border rounded-lg border p-3 text-sm'>
              <div className='font-medium'>{campaign.goal}</div>
              <div className='text-muted-foreground text-xs'>{campaign.status === 'needs_input' ? `Needs: ${campaign.missingFacts.join(', ')}` : `Version ${campaign.version} · ready to plan`}</div>
              {canEdit && campaign.status !== 'needs_input' && !task && <Button variant='outline' size='sm' className='mt-2' disabled={busy} onClick={() => void previewWeekly(campaign.id)}>Preview Monday 9am drafts</Button>}
              {task && <div className='mt-2 flex items-center justify-between gap-2 text-xs'><span>{task.status} · next {task.nextOccurrence ? new Date(task.nextOccurrence.utc).toLocaleString() : 'not scheduled'}</span>{task.status === 'draft' && <Button size='sm' disabled={busy} onClick={() => void act('raffi_recurrence_activate', { taskId: task.id, confirmed: true })}>Activate draft prep</Button>}</div>}
            </div>;
          })}
        </div>
      </div>

      <div className='bg-card ring-foreground/10 rounded-xl p-4 shadow-xs ring-1'>
        <div className='mb-3 flex items-start justify-between gap-3'>
          <div><h2 className='font-semibold'>Raffi suggestions</h2><p className='text-muted-foreground text-xs'>Each suggestion names the workspace evidence behind it.</p></div>
          {canEdit && <Button variant='outline' size='sm' disabled={busy} onClick={() => void act('raffi_suggestion_refresh', {})}>Refresh</Button>}
        </div>
        <div className='space-y-2'>
          {suggestions.filter((item) => item.status === 'open').length === 0 && <p className='text-muted-foreground text-xs'>No current evidence supports a suggestion.</p>}
          {suggestions.filter((item) => item.status === 'open').slice(0, 4).map((item) => <div key={item.id} className='border-border rounded-lg border p-3'>
            <p className='text-sm'>{item.reason}</p>
            <p className='text-muted-foreground mt-1 text-[11px]'>{item.evidence.map((entry) => `${entry.type} ${entry.id.slice(0, 8)} · rev ${entry.revision}`).join(' · ')}</p>
            {canEdit && <div className='mt-2 flex gap-2'><Button size='sm' onClick={() => void act('raffi_suggestion_accept', { suggestionId: item.id })}>Open for review</Button><Button variant='ghost' size='sm' onClick={() => void act('raffi_suggestion_dismiss', { suggestionId: item.id })}>Dismiss</Button></div>}
          </div>)}
        </div>
      </div>
    </section>
  );
}
