'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/** 48px fields with 16px text on phones (no iOS zoom), quiet field material (DNA §10, §12). */
const FIELD = 'rafii-field h-12 rounded-[var(--rafii-radius-control)] px-3.5 text-base md:h-11 md:text-sm';
import { ApiError } from '@/lib/api/client';
import { keys, useModels } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function RaffiPlanner({ state, revision, canEdit, isOwner }: { state: SnapshotState; revision: number; canEdit: boolean; isOwner: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const router = useRouter();
  const activeWorkspace = useRef(workspaceId);
  activeWorkspace.current = workspaceId;
  const [editingCampaign, setEditingCampaign] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [audience, setAudience] = useState('');
  const [date, setDate] = useState('');
  const [venue, setVenue] = useState('');
  const [busy, setBusy] = useState(false);
  const models = useModels();
  const [writer, setWriter] = useState('deterministic-preview');
  const [costCap, setCostCap] = useState('0');
  const writers = models.data?.models.filter((model) => model.qualified) ?? [];
  const selectedWriter = writers.find((model) => model.id === writer);
  const planning = state.raffi?.campaignPlanning;
  const campaigns = planning?.campaigns ?? [];
  const tasks = planning?.recurringTasks ?? [];
  const suggestions = state.raffi?.suggestions ?? [];
  useEffect(() => { setGoal(''); setAudience(''); setDate(''); setVenue(''); setEditingCampaign(null); }, [workspaceId]);

  async function act(action: string, payload: Record<string, unknown>) {
    setBusy(true);
    try {
      const current = (client.getQueryData<{ revision: number }>(keys.snapshot(workspaceId))?.revision ?? revision);
      const next = await api.act(workspaceId, current, action, payload);
      client.setQueryData(keys.snapshot(workspaceId), next);
      if (activeWorkspace.current !== workspaceId) return null;
      return next;
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Rafii could not save this change.');
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function createCampaign() {
    if (!goal.trim() || !audience.trim()) return;
    const prior = campaigns.find((campaign) => campaign.id === editingCampaign);
    const next = await act(editingCampaign ? 'raffi_campaign_update' : 'raffi_campaign_create', { ...(editingCampaign ? { campaignId: editingCampaign } : {}), goal, audience, facts: { ...prior?.facts, date, venue } });
    if (next) { setGoal(''); setAudience(''); setDate(''); setVenue(''); setEditingCampaign(null); }
  }

  async function openSuggestion(suggestionId: string) {
    const next = await act('raffi_suggestion_accept', { suggestionId });
    const ref = next?.state.raffi?.suggestions?.find((item) => item.id === suggestionId)?.actionRef;
    if (!ref?.targetId || ref.workspaceId !== workspaceId) return;
    if (ref.targetType === 'job') router.push(`/app/queue?job=${encodeURIComponent(ref.targetId)}`);
    else if (ref.targetType === 'asset') router.push(`/app/queue?asset=${encodeURIComponent(ref.targetId)}`);
    else if (ref.targetType === 'campaign') {
      const campaign = next?.state.raffi?.campaignPlanning?.campaigns.find((item) => item.id === ref.targetId);
      if (!campaign) return;
      setEditingCampaign(campaign.id); setGoal(campaign.goal); setAudience(campaign.audience);
      setDate(campaign.facts.date ?? ''); setVenue(campaign.facts.venue ?? '');
      document.getElementById(`campaign-goal-${workspaceId}`)?.focus();
    }
  }

  async function previewWeekly(campaignId: string) {
    await act('raffi_recurrence_preview', { campaignId, schedule: { weekday: 'Monday', localTime: '09:00', timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone }, draftsPerOccurrence: 1, route: writer, maxCostUsdMicro: Math.round(Number(costCap) * 1_000_000) });
  }

  return (
    <section className='grid gap-4 md:grid-cols-2' aria-label='Campaign planning and Rafii suggestions'>
      <Surface material='glass' padding='md'>
        <div className='mb-4 flex flex-col gap-1'>
          <span className='rafii-eyebrow'>Plan ahead</span>
          <h2 className='text-foreground text-lg font-normal tracking-[-0.01em]'>
            Campaign <em className='rafii-serif'>planner</em>
          </h2>
          <p className='text-muted-foreground text-xs leading-relaxed'>Plans and recurring tasks prepare drafts only. Every post still needs its own review and approval.</p>
        </div>
        {canEdit && (
          <div className='grid gap-2 sm:grid-cols-2'>
            <Input disabled={busy} id={`campaign-goal-${workspaceId}`} aria-label='Campaign goal' value={goal} onChange={(event) => setGoal(event.target.value)} placeholder='Campaign goal' className={cn(FIELD, 'sm:col-span-2')} />
            <Input aria-label='Campaign audience' value={audience} onChange={(event) => setAudience(event.target.value)} placeholder='Audience' className={cn(FIELD, 'sm:col-span-2')} />
            <Input aria-label='Campaign date' value={date} onChange={(event) => setDate(event.target.value)} placeholder='Date, if relevant' className={FIELD} />
            <Input aria-label='Campaign venue' value={venue} onChange={(event) => setVenue(event.target.value)} placeholder='Venue, if relevant' className={FIELD} />
            <Button variant='action' size='control' className='sm:col-span-2' disabled={busy || !goal.trim() || !audience.trim()} onClick={() => void createCampaign()}>{editingCampaign ? 'Save campaign changes' : 'Create reviewable campaign'}</Button>
            {editingCampaign && <Button variant='quiet' size='control' className='sm:col-span-2' onClick={() => { setEditingCampaign(null); setGoal(''); setAudience(''); setDate(''); setVenue(''); }}>Cancel editing</Button>}
          </div>
        )}
        <div className='mt-4 space-y-2'>
          {campaigns.length === 0 && <StateMessage kind='empty' layout='inline' title='No campaigns yet.' description='Describe a goal and an audience; Rafii prepares drafts for you to review.' />}
          {campaigns.slice(-3).toReversed().map((campaign) => {
            const task = tasks.findLast((item) => item.campaignId === campaign.id && item.status !== 'cancelled');
            const latest = planning?.occurrences.findLast((item) => item.taskId === task?.id);
            return <Surface key={campaign.id} material='quiet' radius='control' padding='sm' className='text-sm'>
              <div className='font-medium'>{campaign.goal}</div>
              <div className='text-muted-foreground text-xs'>{campaign.status === 'needs_input' ? `Needs: ${campaign.missingFacts.join(', ')}` : `Version ${campaign.version} · ready to plan`}</div>
              {canEdit && campaign.status !== 'needs_input' && !task && <div className='mt-2 space-y-2'>
                <label className='block text-xs'>Draft writer<select aria-label='Recurring draft writer' className={cn(FIELD, 'rafii-focus mt-1 block w-full')} value={writer} onChange={(event) => { setWriter(event.target.value); setCostCap('0'); }}>{writers.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label>
                <p className='text-muted-foreground text-xs'>{selectedWriter?.egress === 'cloud' ? 'Campaign details will be sent to this cloud writer, including when it runs through a local CLI.' : 'Local deterministic preview; no model call.'} One LinkedIn draft in English each Monday at 9am in your time zone.</p>
                <label htmlFor={`recurring-cost-${campaign.id}`} className='block text-xs'>Maximum cost per occurrence (USD)<Input id={`recurring-cost-${campaign.id}`} aria-label='Recurring draft cost limit' type='number' min='0' max='10' step='0.01' value={costCap} onChange={(event) => setCostCap(event.target.value)} className={cn(FIELD, 'mt-1')} /></label>
                <Button variant='glass' size='control' className='mt-2' disabled={busy} onClick={() => void previewWeekly(campaign.id)}>Preview Monday 9am drafts</Button></div>}
              {task && <div className='mt-2 flex items-center justify-between gap-2 text-xs'><span>{task.status} · {task.route} · up to ${((task.maxCostUsdMicro ?? 0) / 1_000_000).toFixed(2)} per draft · next {task.nextOccurrence ? new Date(task.nextOccurrence.utc).toLocaleString() : 'not scheduled'}</span>{isOwner && task.status === 'draft' && <Button variant='action' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_recurrence_activate', { taskId: task.id, confirmed: true })}>Activate draft prep</Button>}
                {isOwner && task.status === 'active' && <Button size='sm' variant='glass' className='min-h-11' disabled={busy} onClick={() => void act('raffi_recurrence_pause', { taskId: task.id })}>Pause draft prep</Button>}
                {isOwner && task.status === 'paused' && !task.pauseReason && <Button variant='action' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_recurrence_resume', { taskId: task.id, confirmed: true })}>Resume draft prep</Button>}
                {isOwner && <Button size='sm' variant='quiet' className='min-h-11' disabled={busy} onClick={() => void act('raffi_recurrence_cancel', { taskId: task.id, confirmed: true })}>Cancel future drafts</Button>}
              </div>}
              {task?.pauseReason && <p className='mt-2 text-xs'>Schedule needs a new review. Cancel it and preview again with the current campaign facts.</p>}
              {latest && <p className='mt-2 text-xs'>Last preparation: {latest.state}{latest.reason ? ` · ${latest.reason.replaceAll('_', ' ')}` : ''}</p>}
              {campaign.items.filter((item) => item.conversationId).map((item) => <Button key={item.id} size='sm' variant='glass' className='mt-2 min-h-11' onClick={() => router.push(`/app/agent/${encodeURIComponent(item.conversationId!)}`)}>Review prepared draft</Button>)}
            </Surface>;
          })}
        </div>
      </Surface>

      <Surface material='glass' padding='md'>
        <div className='mb-4 flex items-start justify-between gap-3'>
          <div className='flex flex-col gap-1'>
            <span className='rafii-eyebrow'>Evidence first</span>
            <h2 className='text-foreground text-lg font-normal tracking-[-0.01em]'>
              Rafii <em className='rafii-serif'>suggestions</em>
            </h2>
            <p className='text-muted-foreground text-xs leading-relaxed'>Each suggestion names the workspace evidence behind it.</p>
          </div>
          {canEdit && <Button variant='glass' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_suggestion_refresh', {})}>Refresh</Button>}
        </div>
        <div className='space-y-2'>
          {suggestions.filter((item) => item.status === 'open').length === 0 && <StateMessage kind='empty' layout='inline' title='No suggestions right now.' description='No current evidence in this workspace supports one.' />}
          {suggestions.filter((item) => item.status === 'open' || item.status === 'accepted').slice(-4).toReversed().map((item) => <Surface key={item.id} material='quiet' radius='control' padding='sm'>
            <p className='text-sm'>{item.reason}</p>
            <p className='text-muted-foreground mt-1 text-xs'>{item.evidence.map((entry) => `${entry.type} ${entry.id.slice(0, 8)} · rev ${entry.revision}`).join(' · ')}</p>
            {canEdit && <div className='mt-2 flex gap-2'><Button variant='action' size='sm' className='min-h-11' disabled={busy} onClick={() => void openSuggestion(item.id)}>Open for review</Button><Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={() => void act('raffi_suggestion_dismiss', { suggestionId: item.id })}>Dismiss</Button></div>}
          </Surface>)}
        </div>
      </Surface>
    </section>
  );
}
