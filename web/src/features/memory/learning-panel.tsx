'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Switch } from '@/components/motion/switch';
import { InfoTip, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Band, Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { useAct, useInvalidate, useMemory, useMemoryProposals, useSnapshot } from '@/lib/api/hooks';
import type { LearnedItem } from '@/lib/api/types';
import { languageLabel } from '@/lib/locales';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { LearningHistory } from './learning-history';
import { StaleNotice, Unavailable } from './memory-states';
import { HoldActionButton } from '@/components/motion/hold-action-button';

const pct = (value: number) => `${Math.round(value * 100)}%`;

function scopeLabel(scope: LearnedItem['scope']) {
  const { platform, contentTypeId } = scope;
  const language = scope.language ? languageLabel(scope.language) : null;
  const base = platform && language ? `${platform} · ${language}` : platform ? `${platform} · all languages` : language ? `All channels · ${language}` : 'All channels';
  return contentTypeId ? `${base} · ${contentTypeId}` : base;
}

/**
 * The learned half of memory (preference-learning design §5.6): proposals waiting for an owner, the items
 * Rafii already follows, the switch that stops learning, and the reset that forgets everything.
 */
export function LearningPanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const proposals = useMemoryProposals();
  const memory = useMemory();
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetEpoch, setResetEpoch] = useState(0);
  const learning = proposals.data?.learning;
  const cloudAccess = memory.data?.egress?.cloud === true;
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const revision = snapshot.data?.revision ?? 0;
  const items = learning?.items ?? [];
  const listed = items.filter((item) => item.status === 'active' || item.status === 'paused');
  const retired = items.filter((item) => item.status === 'retired');
  const pending = proposals.data?.pending ?? [];
  const stats = proposals.data?.stats ?? [];
  const latest = stats.at(-1);
  const previous = stats.length > 1 ? stats.at(-2) : undefined;

  const update = useMutation({
    mutationFn: (input: { id: string; status: 'active' | 'paused' | 'retired' }) => api.updateLearnedItem(workspaceId, input.id, input.status, revision),
    // The list shows the new state (struck through when paused, gone when retired); no toast.
    onSuccess: () => invalidate('snapshot', 'memory', 'memoryProposals'),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Couldn’t save. Try again.')
  });

  function setEnabled(enabled: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { enabled } },
      {
        onSuccess: () => invalidate('memory', 'memoryProposals'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Couldn’t save the setting.')
      }
    );
  }

  function setCloudExtraction(cloudExtraction: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { cloudExtraction } },
      {
        onSuccess: () => invalidate('memory', 'memoryProposals'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Couldn’t save the setting.')
      }
    );
  }

  function setTeamEdits(teamEdits: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { teamEdits } },
      {
        onSuccess: () => invalidate('memory', 'memoryProposals'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Couldn’t save the setting.')
      }
    );
  }

  function reset() {
    act.mutate(
      { revision, action: 'learning_reset', payload: { confirmed: true } },
      {
        onSuccess: () => {
          setConfirmReset(false);
          invalidate('memory', 'memoryProposals');
          toast.success('Learned preferences forgotten');
        },
        onSettled: () => setResetEpoch((value) => value + 1),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Couldn’t reset. Try again.')
      }
    );
  }

  const busy = act.isPending || update.isPending || snapshot.isLoading || proposals.isError;

  return (
    <Panel
      titleId='learned-preferences'
      title={
        <span className='flex flex-wrap items-center gap-2'>
          Learned preferences
          {learning && <StatusChip icon={learning.enabled ? 'sparkles' : 'pause'}>{learning.enabled ? `${listed.filter((i) => i.status === 'active').length} in your drafts` : 'Learning off'}</StatusChip>}
        </span>
      }
      description={`Rafii suggests writing preferences from what you say and how you edit. ${isOwner ? 'You decide.' : 'An owner decides.'}`}
      actions={learning && <Switch checked={learning.enabled} disabled={!isOwner || busy} onCheckedChange={setEnabled} ariaLabel='Learn from what I say and how I edit' label='Learn' />}
    >
      {learning && learning.enabled && (
        <Band className='sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-foreground text-sm font-medium'>Learn with a cloud model</span>
              <StatusChip status={learning.cloudExtraction && cloudAccess ? 'success' : 'neutral'}>{learning.cloudExtraction && cloudAccess ? 'On' : 'Off'}</StatusChip>
            </div>
            <p className='text-muted-foreground flex max-w-prose items-center text-sm leading-relaxed'>
              {cloudAccess ? 'A cloud model may read redacted edits.' : 'Needs Cloud model access on first.'}
              <InfoTip
                label='About learning with a cloud model'
                className='-my-3'
                description='Counting rules always read your edits locally. On, a cloud model may also read redacted before/after pairs, only for drafts whose sources allow cloud use. Claude CLI sends text to the cloud and needs this too.'
              />
            </p>
          </div>
          <Switch checked={learning.cloudExtraction} disabled={!isOwner || busy || !cloudAccess} onCheckedChange={setCloudExtraction} ariaLabel='Learn from my edits with a cloud model' label='Allow' />
        </Band>
      )}

      {learning && learning.enabled && (
        <Band className='sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-foreground text-sm font-medium'>Learn from teammates’ edits</span>
              <StatusChip status={learning.teamEdits ? 'success' : 'neutral'}>{learning.teamEdits ? 'On' : 'Owners only'}</StatusChip>
            </div>
            <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>Count every member’s edits as evidence, not only owners’.</p>
          </div>
          <Switch checked={learning.teamEdits} disabled={!isOwner || busy} onCheckedChange={setTeamEdits} ariaLabel='Count teammates’ edits as evidence' label='Allow' />
        </Band>
      )}

      {proposals.isLoading && <StateMessage kind='loading' title='Loading learned preferences…' />}
      {!proposals.data && proposals.isError && <Unavailable message='Couldn’t load learned preferences.' query={proposals} />}
      {proposals.data && proposals.isRefetchError && <StaleNotice query={proposals} />}

      {latest && (
        <p className='text-muted-foreground text-xs leading-relaxed'>
          {latest.approvals} approval{latest.approvals === 1 ? '' : 's'} · {pct(latest.meanEditDistance)} edited on average · {pct(latest.uneditedShare)} untouched
          {previous ? <span className='hidden md:inline'>{` (before: ${pct(previous.meanEditDistance)} edited, ${pct(previous.uneditedShare)} untouched)`}</span> : ''}
          {latest.approvals < 5 ? ' · small sample' : ''}
        </p>
      )}

      {learning && listed.length === 0 && pending.length === 0 && !proposals.isLoading && (
        <StateMessage kind='empty' layout='inline' title='Nothing learned yet' description='Try: “From now on, no hashtags on Instagram.”' />
      )}

      {listed.length > 0 && (
        <ul className='flex flex-col gap-1'>
          {listed.map((item) => (
            <li key={item.id} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between'>
              <div className='flex min-w-0 flex-col gap-1'>
                <span className={item.status === 'paused' ? 'text-muted-foreground text-sm line-through' : 'text-foreground text-sm'}>{item.statement}</span>
                <span className='text-muted-foreground text-xs'>
                  {scopeLabel(item.scope)} · {item.evidenceSummary ?? item.evidenceState.replace(/_/g, ' ')}
                  {item.since ? ` · ${String(item.since).slice(0, 10)}` : ''}
                  {item.status === 'paused' ? ' · paused' : ''}
                </span>
              </div>
              {isOwner && (
                <div className='flex shrink-0 items-center gap-1'>
                  <Button size='default' variant='glass' disabled={busy} onClick={() => update.mutate({ id: item.id, status: item.status === 'paused' ? 'active' : 'paused' })}>
                    {item.status === 'paused' ? 'Resume' : 'Pause'}
                  </Button>
                  <Button size='default' variant='quiet' disabled={busy} onClick={() => update.mutate({ id: item.id, status: 'retired' })}>
                    Retire
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {proposals.data && <LearningHistory data={proposals.data} />}

      {learning && isOwner && (
        <div className='flex flex-wrap items-center gap-2 pt-1'>
          {retired.length > 0 && <span className='text-muted-foreground text-xs'>{retired.length} retired</span>}
          <span className='grow' />
          {confirmReset ? (
            <>
              <span className='text-foreground text-xs'>Forget every learned preference and the edit history?</span>
              <HoldActionButton
                key={resetEpoch}
                type='horizontal'
                holdDuration={900}
                disabled={busy}
                onHoldComplete={reset}
                holdingLabel='Keep holding…'
                completeLabel='Forgetting…'
                aria-label='Hold to forget learned preferences'
                className='bg-destructive text-destructive-foreground h-9 rounded-[var(--rafii-radius-control)] px-3'
              >
                Hold to forget everything
              </HoldActionButton>
              <Button size='default' variant='glass' disabled={busy} onClick={() => setConfirmReset(false)}>
                Keep
              </Button>
            </>
          ) : (
            <Button size='default' variant='quiet' disabled={busy} onClick={() => setConfirmReset(true)}>
              Forget what you learned…
            </Button>
          )}
        </div>
      )}
    </Panel>
  );
}
