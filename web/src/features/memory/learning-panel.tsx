'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Switch } from '@/components/motion/switch';
import { StateMessage } from '@/components/rafii';
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
    onSuccess: (_result, input) => {
      invalidate('snapshot', 'memory', 'memoryProposals');
      toast.success(input.status === 'paused' ? 'Paused. It stays here but leaves your drafts.' : input.status === 'active' ? 'Back in your drafts.' : 'Retired.');
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The change could not be saved.')
  });

  function setEnabled(enabled: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { enabled } },
      {
        onSuccess: () => {
          invalidate('memory', 'memoryProposals');
          toast.success(enabled ? 'Rafii learns from what you tell it and how you edit again.' : 'Learning is off. Nothing new is recorded or proposed.');
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The setting could not be saved.')
      }
    );
  }

  function setCloudExtraction(cloudExtraction: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { cloudExtraction } },
      {
        onSuccess: () => {
          invalidate('memory', 'memoryProposals');
          toast.success(
            cloudExtraction
              ? 'Cloud extraction permission is on. The configured extractor and memory sharing determine whether a model reads edit pairs.'
              : 'Cloud extraction permission is off. Counting rules can still run. Claude CLI also needs cloud permission.'
          );
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The setting could not be saved.')
      }
    );
  }

  function setTeamEdits(teamEdits: boolean) {
    act.mutate(
      { revision, action: 'learning_settings', payload: { teamEdits } },
      {
        onSuccess: () => {
          invalidate('memory', 'memoryProposals');
          toast.success(teamEdits ? 'Edits by every member now count as evidence.' : 'Only owners’ edits count as evidence now.');
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The setting could not be saved.')
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
          toast.success('Forgotten. Learned preferences, proposals and the edit history are gone.');
        },
        onSettled: () => setResetEpoch((value) => value + 1),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The reset could not be saved.')
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
          {learning && learning.revision > 0 && <StatusChip icon={null}>style rev {learning.revision}</StatusChip>}
        </span>
      }
      description={
        <>
          When you tell the agent how to write, or your edits show a pattern, Rafii proposes a preference. Nothing changes until you accept it, a preference is about form only (length, openings, hashtags, how a post closes), and it shapes future drafts
          without touching anything already scheduled.
          <span className='mt-1 block text-xs'>{isOwner ? 'You decide proposals and can pause, retire or forget any of them.' : 'Only an owner can decide proposals or change these.'}</span>
        </>
      }
      actions={learning && <Switch checked={learning.enabled} disabled={!isOwner || busy} onCheckedChange={setEnabled} ariaLabel='Learn from what I say and how I edit' label='Learn' />}
    >
      {learning && learning.enabled && (
        <Band className='sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-foreground text-sm font-medium'>Learn with a cloud model</span>
              <StatusChip status={learning.cloudExtraction && cloudAccess ? 'success' : 'neutral'}>{learning.cloudExtraction && cloudAccess ? 'On' : 'Off'}</StatusChip>
            </div>
            <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>
              Counting rules read your edits. This permits a configured cloud extractor to read redacted before/after pairs, only for drafts whose sources allow cloud use. Claude CLI sends text to a cloud provider and needs the same permission.
              {!cloudAccess ? ' It needs “Cloud model access” above to be on.' : ''}
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
            <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>Until this is on, only an owner’s edits and approvals count as evidence for a proposal. What anyone says to the agent is always proposed to you.</p>
          </div>
          <Switch checked={learning.teamEdits} disabled={!isOwner || busy} onCheckedChange={setTeamEdits} ariaLabel='Count teammates’ edits as evidence' label='Allow' />
        </Band>
      )}

      {proposals.isLoading && <StateMessage kind='loading' title='Loading learned preferences…' />}
      {!proposals.data && proposals.isError && <Unavailable message='Learned preferences are unavailable right now.' query={proposals} />}
      {proposals.data && proposals.isRefetchError && <StaleNotice query={proposals} />}

      {latest && (
        <p className='text-muted-foreground text-xs leading-relaxed'>
          {latest.styleRevision > 0 ? `Since style rev ${latest.styleRevision}: ` : 'Before any learned preference: '}
          {latest.approvals} approved draft{latest.approvals === 1 ? '' : 's'}, {pct(latest.meanEditDistance)} of the text changed before approval on average, {pct(latest.uneditedShare)} approved untouched
          {previous ? ` (rev ${previous.styleRevision}: ${pct(previous.meanEditDistance)} changed, ${pct(previous.uneditedShare)} untouched)` : ''}
          {latest.approvals < 5 ? ' · small sample' : ''}.
        </p>
      )}

      {learning && listed.length === 0 && pending.length === 0 && !proposals.isLoading && (
        <StateMessage kind='empty' layout='inline' title='Nothing learned yet.' description='Try telling the agent “from now on, no hashtags on Instagram”.' />
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
