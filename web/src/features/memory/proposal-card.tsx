'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { keys, useMemoryProposals, useSnapshot } from '@/lib/api/hooks';
import type { MemoryProposal } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

const SOURCE_LABEL: Record<string, string> = {
  chat: 'You said so',
  deterministic: 'From your edits',
  model: 'From your edits',
  performance: 'From how posts did',
  legacy: 'Remembered earlier'
};

const DECIDED_TEXT: Record<string, string> = {
  remembered: 'Remembered. It shapes your next drafts; nothing already scheduled changes.',
  edited: 'Remembered with your wording. It shapes your next drafts; nothing already scheduled changes.',
  dismissed: 'Dismissed. PostRiff will not suggest this again for a while.',
  post_only: 'Applied to that draft only. Your preferences are unchanged.',
  expired: 'Expired without a decision.'
};

/**
 * One suggested preference, in the conversation and on the Memory page. Everything is a proposal until an
 * owner accepts it (preference-learning design §5.5); the card follows the live status, so a card in an older
 * turn shows what was decided later instead of offering the buttons again.
 */
export function ProposalCard({ proposal, className }: { proposal: MemoryProposal; className?: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const snapshot = useSnapshot();
  const proposals = useMemoryProposals();
  const live = proposals.data?.pending.find((p) => p.id === proposal.id) ?? proposals.data?.recent.find((p) => p.id === proposal.id);
  const status = live?.status ?? proposal.status;
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const [editing, setEditing] = useState(false);
  const [wording, setWording] = useState(proposal.statement);

  const decide = useMutation({
    mutationFn: (input: { decision: 'remember' | 'edit' | 'dismiss' | 'post_only'; statement?: string }) =>
      api.decideProposal(workspaceId, proposal.id, { ...input, expectedRevision: snapshot.data?.revision ?? 0 }),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.memory(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.memoryProposals(workspaceId) });
      setEditing(false);
      toast.success(DECIDED_TEXT[result.status] ?? 'Saved.');
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The decision could not be saved.')
  });

  const pending = status === 'pending';
  const busy = decide.isPending || snapshot.isLoading;
  const evidence = proposal.evidence?.length ?? 0;
  const why = proposal.why || (proposal.source === 'chat' ? 'You said so in chat.' : evidence > 0 ? `Seen in ${evidence} of your edits.` : undefined);

  return (
    <div className={cn('bg-card ring-foreground/10 flex flex-col gap-3 rounded-xl p-4 ring-1', className)} data-proposal={proposal.id}>
      <div className='flex flex-wrap items-center gap-2 text-xs'>
        <span aria-hidden className='text-amber-500'>✧</span>
        <Badge variant='outline'>{proposal.scopeLabel}</Badge>
        <Badge variant='secondary'>{SOURCE_LABEL[proposal.source] ?? proposal.source}</Badge>
        {proposal.op === 'update' && <Badge variant='secondary'>Replaces an earlier preference</Badge>}
        {!pending && <Badge variant='outline'>{status.replace('_', ' ')}</Badge>}
      </div>
      {editing ? (
        <div className='flex flex-col gap-2'>
          <Textarea value={wording} onChange={(e) => setWording(e.target.value)} rows={2} className='text-sm' aria-label='Preference wording' maxLength={160} />
          <p className='text-muted-foreground text-xs'>One sentence about how you write. Facts and numbers belong in Sources or Brand.</p>
        </div>
      ) : (
        <p className='text-base leading-snug font-semibold'>{live?.statement ?? proposal.statement}</p>
      )}
      {why && <p className='text-muted-foreground text-xs'>{why}</p>}
      {proposal.performance && (
        <p className='text-muted-foreground text-xs'>
          {proposal.performance.direction === 'supports' ? 'In line with this: ' : proposal.performance.direction === 'contradicts' ? 'Against this: ' : 'No clear difference: '}
          posts without the feature averaged {proposal.performance.withoutFeature.mean} {proposal.performance.metric} ({proposal.performance.withoutFeature.posts} posts), with it {proposal.performance.withFeature.mean} ({proposal.performance.withFeature.posts} posts). {proposal.performance.note}
        </p>
      )}
      {pending ? (
        <>
          <p className='text-muted-foreground border-t border-dashed pt-2 text-xs'>
            If you remember it, future drafts for {proposal.scopeLabel.toLowerCase().replace('all channels', 'every channel')} follow it. What you ask for in a message still wins, and nothing already scheduled changes.
          </p>
          {isOwner ? (
            <div className='flex flex-wrap items-center gap-2'>
              {editing ? (
                <>
                  <Button size='sm' disabled={busy || !wording.trim()} onClick={() => decide.mutate({ decision: 'edit', statement: wording.trim() })}>
                    Save wording
                  </Button>
                  <Button size='sm' variant='outline' disabled={busy} onClick={() => setEditing(false)}>
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button size='sm' disabled={busy} onClick={() => decide.mutate({ decision: 'remember' })}>
                    Remember this
                  </Button>
                  <Button size='sm' variant='outline' disabled={busy} onClick={() => setEditing(true)}>
                    Edit wording
                  </Button>
                  {proposal.variantId && (
                    <Button size='sm' variant='outline' disabled={busy} onClick={() => decide.mutate({ decision: 'post_only' })}>
                      Only for this post
                    </Button>
                  )}
                  <Button size='sm' variant='ghost' className='text-muted-foreground' disabled={busy} onClick={() => decide.mutate({ decision: 'dismiss' })}>
                    Don’t use
                  </Button>
                </>
              )}
            </div>
          ) : (
            <p className='text-muted-foreground text-xs'>Only a workspace owner can decide this.</p>
          )}
        </>
      ) : (
        <p className='text-muted-foreground text-xs'>{DECIDED_TEXT[status] ?? status}</p>
      )}
    </div>
  );
}
