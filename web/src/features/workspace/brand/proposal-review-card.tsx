'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Panel, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { useAct } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { type Refetchable } from './brand-parts';
import { ProfileDetails } from './voice-card';
import { describeChanges, voiceCounts, voiceStatus } from './voice-model';

type ApproveState = 'idle' | 'loading' | 'error';

function plural(count: number, one: string, many: string) {
  return count === 1 ? one : many;
}

/**
 * What approving does, from the snapshot (domain.profile_decide → _mark_stale, store.invalidate).
 * A count the snapshot does not carry is described without a number, never as 0.
 */
function impactSentences(drafts: number | null, bound: number | null) {
  const lines: string[] = [];
  if (drafts === null) lines.push('Every draft is marked for review.');
  else if (drafts > 0) lines.push(`${drafts} ${plural(drafts, 'draft is', 'drafts are')} marked for review.`);
  if (bound === null) lines.push('Any approved or scheduled posts are held, and each needs a new approval to go out.');
  else if (bound > 0) lines.push(`${bound} approved or scheduled ${plural(bound, 'post is', 'posts are')} held, and each needs a new approval to go out.`);
  else lines.push('No approved or scheduled posts are waiting to go out, so none are held.');
  return lines;
}

/**
 * A proposal that arrived while a voice is active. VoiceSetup only renders when no voice is active, so without
 * this panel an owner would be told a revision is waiting with nowhere to approve it. Approval is owner-only
 * (permissions.py profile_decide) and confirmed, because it holds approved or scheduled posts.
 * There is no discard: profile_decide reject also switches off the active voice (domain.py), so it is not offered.
 */
export function ProposalReviewCard({ state, workspaceRevision, isOwner, sample, query }: { state: SnapshotState | undefined; workspaceRevision: number; isOwner: boolean; sample: boolean; query: Refetchable }) {
  const act = useAct();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [approveState, setApproveState] = useState<ApproveState>('idle');
  const status = voiceStatus(state);
  const provisional = state?.speaker?.provisional ?? null;
  if (status.kind !== 'active' || !status.waiting || !provisional) return null;

  const revisions = state?.speaker?.revisions;
  // domain._voice numbers the next revision as the count so far plus one.
  const next = Array.isArray(revisions) ? revisions.length + 1 : null;
  const nextName = next ? `revision ${next}` : 'the proposed revision';
  const changes = status.record ? describeChanges(status.record.profile, provisional) : null;
  const counts = voiceCounts(state);
  const stale = provisional.status === 'stale';
  const canApprove = isOwner && !sample && !stale;

  async function approve() {
    setApproveState('loading');
    try {
      await act.mutateAsync({ revision: workspaceRevision, action: 'profile_decide', payload: { decision: 'approve', note: note.trim() } });
      setOpen(false);
      setApproveState('idle');
      toast.success(`${next ? `Revision ${next}` : 'The new revision'} is active.`);
    } catch (err) {
      setApproveState('error');
      if (err instanceof ApiError && err.status === 409) {
        // Someone changed the workspace meanwhile: load the latest state and let the owner look again.
        setOpen(false);
        void query.refetch();
        toast.error('The workspace changed. Review the latest proposal.');
        return;
      }
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t approve the revision.');
    }
  }

  return (
    <Panel
      material='glass'
      data-tour='brand-proposal'
      title={`Proposed ${nextName}`}
      titleId='brand-proposal-heading'
      description={stale ? 'A sample changed. Analyse your samples again before approving.' : `Drafts keep using revision ${status.revision} until ${canApprove ? 'you approve' : 'an owner approves'}.`}
      bodyClassName='gap-5 text-sm'
    >
      {changes && <p className='text-muted-foreground text-xs'>{changes.length ? `Since revision ${status.revision}: ${changes.join(' · ')}` : `Same as revision ${status.revision}.`}</p>}
      <ProfileDetails profile={provisional} observationsLabel='Observations in this proposal' />
      {canApprove && (
        <label htmlFor='voice-revision-guidance' className='flex flex-col gap-2 text-sm'>
          <span className='text-foreground font-medium'>Your guidance (optional)</span>
          <Textarea
            id='voice-revision-guidance'
            aria-label='Edited writing guidance for this voice revision'
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={1500}
            rows={3}
            disabled={act.isPending}
            placeholder='Plain, specific, never salesy.'
            className={TEXTAREA_CLASS}
          />
          <span className='text-muted-foreground text-xs'>Replaces the proposed observations.</span>
        </label>
      )}
      <div className='flex flex-col items-start gap-2'>
        {canApprove ? (
          <AlertDialog
            open={open}
            onOpenChange={(value) => {
              if (!value && approveState === 'loading') return;
              setOpen(value);
              if (value) setApproveState('idle');
            }}
          >
            <Button variant='action' size='control' onClick={() => setOpen(true)} disabled={act.isPending}>
              Approve…
            </Button>
            <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 md:rounded-[var(--rafii-radius-dialog)] md:p-6'>
              <AlertDialogHeader>
                <AlertDialogTitle>Approve {nextName}?</AlertDialogTitle>
                <AlertDialogDescription render={<div />} className='flex flex-col gap-2'>
                  <span>New drafts are written with it.</span>
                  {impactSentences(counts.drafts, counts.bound).map((line) => (
                    <span key={line}>{line}</span>
                  ))}
                  <span>Revision {status.revision} stays listed under Revisions.</span>
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel variant='glass' size='control' disabled={approveState === 'loading'}>
                  Keep revision {status.revision}
                </AlertDialogCancel>
                <Button variant='action' size='control' disabled={approveState === 'loading'} aria-busy={approveState === 'loading' || undefined} onClick={() => void approve()}>
                  {approveState === 'loading' ? (
                    <>
                      <Icons.spinner className='motion-safe:animate-spin' /> Approving…
                    </>
                  ) : approveState === 'error' ? (
                    'Try again'
                  ) : (
                    `Approve ${nextName}`
                  )}
                </Button>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : (
          <p className='text-muted-foreground text-xs'>{sample ? 'Sample workspace: approval isn’t available.' : 'Only an owner can approve.'}</p>
        )}
      </div>
    </Panel>
  );
}
