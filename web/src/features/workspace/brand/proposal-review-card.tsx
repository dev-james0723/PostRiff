'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useAct } from '@/lib/api/hooks';
import type { SnapshotState } from '@/lib/api/types';
import { type Refetchable } from './brand-parts';
import { ProfileDetails } from './voice-card';
import { describeChanges, voiceCounts, voiceStatus } from './voice-model';

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
 * this card an owner would be told a revision is waiting with nowhere to approve it. Approval is owner-only
 * (permissions.py profile_decide) and confirmed, because it holds approved or scheduled posts.
 * There is no discard: profile_decide reject also switches off the active voice (domain.py), so it is not offered.
 */
export function ProposalReviewCard({
  state,
  workspaceRevision,
  isOwner,
  sample,
  query
}: {
  state: SnapshotState | undefined;
  workspaceRevision: number;
  isOwner: boolean;
  sample: boolean;
  query: Refetchable;
}) {
  const act = useAct();
  const [open, setOpen] = useState(false);
  const [buttonState, setButtonState] = useState<ButtonState>('idle');
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
    setButtonState('loading');
    try {
      await act.mutateAsync({ revision: workspaceRevision, action: 'profile_decide', payload: { decision: 'approve', note: '' } });
      setOpen(false);
      toast.success(`${next ? `Revision ${next}` : 'The proposed revision'} is active. New drafts are written with it.`);
    } catch (err) {
      setButtonState('error');
      if (err instanceof ApiError && err.status === 409) {
        // Someone changed the workspace meanwhile: load the latest state and let the owner look again.
        setOpen(false);
        void query.refetch();
        toast.error('This workspace changed while you were looking. The latest version is loaded; review the proposal again.');
        return;
      }
      toast.error(err instanceof ApiError ? err.message : 'The revision could not be approved.');
    }
  }

  return (
    <Card data-tour='brand-proposal' className='min-w-0'>
      <CardHeader>
        <CardTitle>Proposed {nextName}</CardTitle>
        <CardDescription>
          {stale
            ? 'A supporting sample changed or was revoked. Analyse the current selected samples again.'
            : canApprove
            ? `Waiting for your approval. Drafts keep using revision ${status.revision} until you approve it.`
            : `Waiting for an owner. Drafts keep using revision ${status.revision} until an owner approves it.`}
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-5 text-sm'>
        {changes && (
          <p className='text-muted-foreground text-xs'>
            {changes.length ? `Compared with revision ${status.revision}: ${changes.join(' · ')}` : `Same as revision ${status.revision}.`}
          </p>
        )}
        <ProfileDetails profile={provisional} observationsLabel='Observations in this proposal' />
      </CardContent>
      <CardFooter className='flex flex-col items-start gap-2'>
        {canApprove ? (
          <AlertDialog
            open={open}
            onOpenChange={(value) => {
              if (!value && buttonState === 'loading') return;
              setOpen(value);
              if (value) setButtonState('idle');
            }}
          >
            <Button onClick={() => setOpen(true)} disabled={act.isPending}>
              Review and approve
            </Button>
            <AlertDialogContent>
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
                <AlertDialogCancel disabled={buttonState === 'loading'}>Keep revision {status.revision}</AlertDialogCancel>
                <StatefulButton state={buttonState} loadingText='Approving…' errorText='Try again' onClick={() => void approve()}>
                  Approve {nextName}
                </StatefulButton>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : (
          <p className='text-muted-foreground text-xs'>
            {sample ? 'This sample workspace is read-only, so the proposal cannot be approved here.' : 'Only an owner can approve a voice revision.'}
          </p>
        )}
        <p className='text-muted-foreground text-xs'>
          Discarding a proposal is not available yet: today it would also switch off revision {status.revision}.
        </p>
      </CardFooter>
    </Card>
  );
}
