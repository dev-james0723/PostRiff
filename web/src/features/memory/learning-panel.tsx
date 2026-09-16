'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Switch } from '@/components/motion/switch';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useAct, useInvalidate, useMemory, useMemoryProposals, useSnapshot } from '@/lib/api/hooks';
import type { LearnedItem } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { ProposalCard } from './proposal-card';

const pct = (value: number) => `${Math.round(value * 100)}%`;

function scopeLabel(scope: LearnedItem['scope']) {
  const { platform, language, contentTypeId } = scope;
  const base = platform && language ? `${platform} · ${language}` : platform ? `${platform} · all languages` : language ? `All channels · ${language}` : 'All channels';
  return contentTypeId ? `${base} · ${contentTypeId}` : base;
}

/**
 * The learned half of memory (preference-learning design §5.6): proposals waiting for an owner, the items
 * PostRiff already follows, the switch that stops learning, and the reset that forgets everything.
 */
export function LearningPanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const proposals = useMemoryProposals();
  const memory = useMemory();
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const [confirmReset, setConfirmReset] = useState(false);
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
          toast.success(enabled ? 'PostRiff learns from what you tell it and how you edit again.' : 'Learning is off. Nothing new is recorded or proposed.');
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
          toast.success(cloudExtraction ? 'A cloud model may now read redacted before/after pairs of your edits.' : 'Only the rules that need no model read your edits now.');
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
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The reset could not be saved.')
      }
    );
  }

  const busy = act.isPending || update.isPending || snapshot.isLoading;

  return (
    <section className='bg-card ring-foreground/10 flex flex-col gap-4 rounded-xl p-4 ring-1' aria-labelledby='learned-preferences'>
      <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
        <div className='flex min-w-0 flex-col gap-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <span id='learned-preferences' className='text-sm font-semibold'>
              Learned preferences
            </span>
            {learning && <Badge variant={learning.enabled ? 'secondary' : 'outline'}>{learning.enabled ? `${listed.filter((i) => i.status === 'active').length} in your drafts` : 'Learning off'}</Badge>}
            {learning && learning.revision > 0 && <Badge variant='outline'>style rev {learning.revision}</Badge>}
          </div>
          <p className='text-muted-foreground max-w-prose text-xs leading-relaxed'>
            When you tell the agent how to write, or your edits show a pattern, PostRiff proposes a preference. Nothing changes until you accept it, a preference is about form only (length, openings, hashtags, how a post closes), and it shapes future drafts without touching anything already scheduled.
          </p>
          <p className='text-muted-foreground text-xs'>{isOwner ? 'You decide proposals and can pause, retire or forget any of them.' : 'Only an owner can decide proposals or change these.'}</p>
        </div>
        {learning && <Switch checked={learning.enabled} disabled={!isOwner || busy} onCheckedChange={setEnabled} ariaLabel='Learn from what I say and how I edit' label='Learn' />}
      </div>

      {learning && learning.enabled && (
        <div className='bg-muted/40 flex flex-col gap-2 rounded-lg p-3 sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-xs font-semibold'>Learn with a cloud model</span>
              <Badge variant={learning.cloudExtraction && cloudAccess ? 'secondary' : 'outline'}>{learning.cloudExtraction && cloudAccess ? 'On' : 'Off'}</Badge>
            </div>
            <p className='text-muted-foreground max-w-prose text-xs leading-relaxed'>
              Without this, only counting rules read your edits (hashtags, emoji, openings, closings, length). With it, a small cloud model reads before/after pairs of your edits with links, handles and numbers removed, and only for drafts whose sources you allowed on the cloud.
              {!cloudAccess ? ' It needs “Cloud model access” above to be on.' : ''}
            </p>
          </div>
          <Switch checked={learning.cloudExtraction} disabled={!isOwner || busy || !cloudAccess} onCheckedChange={setCloudExtraction} ariaLabel='Learn from my edits with a cloud model' label='Allow' />
        </div>
      )}

      {learning && learning.enabled && (
        <div className='bg-muted/40 flex flex-col gap-2 rounded-lg p-3 sm:flex-row sm:items-start sm:justify-between'>
          <div className='flex min-w-0 flex-col gap-1'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='text-xs font-semibold'>Learn from teammates’ edits</span>
              <Badge variant={learning.teamEdits ? 'secondary' : 'outline'}>{learning.teamEdits ? 'On' : 'Owners only'}</Badge>
            </div>
            <p className='text-muted-foreground max-w-prose text-xs leading-relaxed'>Until this is on, only an owner’s edits and approvals count as evidence for a proposal. What anyone says to the agent is always proposed to you.</p>
          </div>
          <Switch checked={learning.teamEdits} disabled={!isOwner || busy} onCheckedChange={setTeamEdits} ariaLabel='Count teammates’ edits as evidence' label='Allow' />
        </div>
      )}

      {proposals.isLoading && <Skeleton className='h-16 w-full' />}

      {latest && (
        <p className='text-muted-foreground text-xs'>
          {latest.styleRevision > 0 ? `Since style rev ${latest.styleRevision}: ` : 'Before any learned preference: '}
          {latest.approvals} approved draft{latest.approvals === 1 ? '' : 's'}, {pct(latest.meanEditDistance)} of the text changed before approval on average, {pct(latest.uneditedShare)} approved untouched
          {previous ? ` (rev ${previous.styleRevision}: ${pct(previous.meanEditDistance)} changed, ${pct(previous.uneditedShare)} untouched)` : ''}
          {latest.approvals < 5 ? ' · small sample' : ''}.
        </p>
      )}

      {pending.length > 0 && (
        <div className='flex flex-col gap-2'>
          <span className='text-muted-foreground text-xs font-medium'>Waiting for your decision · {pending.length}</span>
          {pending.map((proposal) => (
            <ProposalCard key={proposal.id} proposal={proposal} />
          ))}
        </div>
      )}

      {learning && listed.length === 0 && pending.length === 0 && !proposals.isLoading && (
        <p className='text-muted-foreground text-xs'>Nothing learned yet. Try telling the agent “from now on, no hashtags on Instagram”.</p>
      )}

      {listed.length > 0 && (
        <ul className='flex flex-col divide-y'>
          {listed.map((item) => (
            <li key={item.id} className='flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between'>
              <div className='flex min-w-0 flex-col gap-1'>
                <span className={item.status === 'paused' ? 'text-muted-foreground text-sm line-through' : 'text-sm'}>{item.statement}</span>
                <span className='text-muted-foreground text-xs'>
                  {scopeLabel(item.scope)} · {item.evidenceSummary ?? item.evidenceState.replace(/_/g, ' ')}
                  {item.since ? ` · ${String(item.since).slice(0, 10)}` : ''}
                  {item.status === 'paused' ? ' · paused' : ''}
                </span>
              </div>
              {isOwner && (
                <div className='flex shrink-0 items-center gap-1'>
                  <Button size='sm' variant='outline' disabled={busy} onClick={() => update.mutate({ id: item.id, status: item.status === 'paused' ? 'active' : 'paused' })}>
                    {item.status === 'paused' ? 'Resume' : 'Pause'}
                  </Button>
                  <Button size='sm' variant='ghost' className='text-muted-foreground' disabled={busy} onClick={() => update.mutate({ id: item.id, status: 'retired' })}>
                    Retire
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {(retired.length > 0 || listed.length > 0) && isOwner && (
        <div className='flex flex-wrap items-center gap-2 border-t pt-3'>
          {retired.length > 0 && <span className='text-muted-foreground text-xs'>{retired.length} retired</span>}
          <span className='grow' />
          {confirmReset ? (
            <>
              <span className='text-xs'>Forget every learned preference and the edit history?</span>
              <Button size='sm' variant='destructive' disabled={busy} onClick={reset}>
                Forget everything
              </Button>
              <Button size='sm' variant='outline' disabled={busy} onClick={() => setConfirmReset(false)}>
                Keep
              </Button>
            </>
          ) : (
            <Button size='sm' variant='ghost' className='text-muted-foreground' disabled={busy} onClick={() => setConfirmReset(true)}>
              Forget what you learned…
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
