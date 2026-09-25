'use client';

import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useFlash } from '@/hooks/use-flash';
import { useAct } from '@/lib/api/hooks';
import { formatDateTime } from '@/lib/time';
import { reportActionError } from './action-error';
import { epochOf, type QueueJob, type QueueReview } from './job-state';

/** `p2_approve_many` takes between one and ten exact reviews (`store.py` approve_many). */
export const APPROVE_MANY_LIMIT = 10;

interface ApproveManyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The exact reviews to approve, already capped at the limit. */
  reviews: QueueReview[];
  /** The jobs of the snapshot the batch is sent against, so only the jobs this approval creates are counted. */
  jobs: QueueJob[];
  revision: number;
  nowSeconds: number;
  /** Mutation errors that mean the workspace moved on offer a reload. */
  onReload: () => void;
}

/**
 * One confirmation for several exact approvals. Every row names the destination, the frozen local time and the
 * start of its digest, so approving the batch is the same promise as approving each card. The server applies
 * the batch in one transaction: all of them are scheduled, or none are.
 */
export function ApproveManyDialog({ open, onOpenChange, reviews, jobs, revision, nowSeconds, onReload }: ApproveManyDialogProps) {
  const act = useAct();
  const [outcome, flashOutcome] = useFlash<{ state: 'success' | 'error'; label: string }>(1200);
  const count = reviews.length;

  function approve() {
    if (outcome?.state === 'success' || count === 0) return;
    const keys = new Set(reviews.map((review) => review.manifest.idempotencyKey));
    // The command carries this snapshot's revision, so the server answers from exactly these jobs (or refuses with a
    // 409). A review whose post is already a job is approved without a new job (`store.py` approve returns early).
    const before = new Set(jobs.map((job) => job.id));
    act.mutate(
      {
        revision,
        action: 'p2_approve_many',
        payload: { confirmed: true, reviews: reviews.map((review) => ({ reviewId: review.id, digest: review.digest })) }
      },
      {
        onSuccess: (snapshot) => {
          // Read the count back from the jobs this approval created, not from what was sent.
          const scheduled = (snapshot.state.phase2?.jobs ?? []).filter((job) => keys.has(job.manifest.idempotencyKey) && !before.has(job.id)).length;
          flashOutcome({ state: 'success', label: `${scheduled} scheduled` });
          // A full batch reads on the button; only a partial one needs saying.
          if (scheduled === 0) toast.info('Already scheduled; nothing changed.');
          else if (scheduled < count) toast.success(`${scheduled} of ${count} scheduled; the rest already were.`);
          window.setTimeout(() => onOpenChange(false), 900);
        },
        onError: (err) => {
          // All or nothing: nothing in the batch was approved, so the list stays as it was.
          reportActionError(err, 'Couldn’t approve these posts', onReload);
          flashOutcome({ state: 'error', label: 'Try again' });
        }
      }
    );
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !act.isPending && onOpenChange(next)}>
      <DialogContent className='rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 sm:max-w-lg sm:rounded-[var(--rafii-radius-dialog)] sm:p-6 [&_[data-slot=dialog-close]]:top-3 [&_[data-slot=dialog-close]]:right-3 [&_[data-slot=dialog-close]]:size-10 [&_[data-slot=dialog-close]]:rounded-full'>
        <DialogHeader>
          <DialogTitle className='text-lg font-medium tracking-tight'>
            Approve {count} post{count === 1 ? '' : 's'}?
          </DialogTitle>
          <DialogDescription>Each publishes exactly as reviewed, at its time. If one can’t be approved, none are.</DialogDescription>
        </DialogHeader>
        <ul className='rafii-quiet flex max-h-[50dvh] flex-col gap-0.5 overflow-y-auto rounded-[var(--rafii-radius-control)] p-1.5 text-sm'>
          {reviews.map((review) => {
            const { manifest } = review;
            const passed = (epochOf(manifest.timing.utc) ?? Infinity) < nowSeconds;
            return (
              <li key={review.id} className='flex flex-col gap-0.5 rounded-[var(--rafii-radius-micro)] px-3 py-2'>
                <span className='flex min-w-0 items-center gap-2'>
                  <ChannelIcon platform={manifest.platform} name={manifest.platform} size='xs' />
                  <span className='truncate'>
                    {manifest.platform} · {manifest.account}
                  </span>
                </span>
                <span className='text-muted-foreground flex flex-wrap gap-x-2 text-xs' title={`${manifest.timing.timeZone} · ${review.digest.slice(0, 12)}`}>
                  <span>{formatDateTime(epochOf(manifest.timing.utc))}</span>
                  {passed && (
                    <span className='inline-flex items-center gap-1'>
                      <Icons.warning aria-hidden className='size-3' />
                      time passed · publishes soon
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
        <DialogFooter>
          <Button variant='glass' size='control' disabled={act.isPending} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {/* The shared stateful button keeps its loading/success/error roll; the wrapper gives it the 48px commit height (DNA §10.1). */}
          <span className='inline-flex [&_button]:h-12 [&_button]:rounded-[var(--rafii-radius-control)] [&_button]:px-4'>
            <StatefulButton
              state={act.isPending ? 'loading' : (outcome?.state ?? 'idle')}
              loadingText='Approving…'
              successText={outcome?.state === 'success' ? outcome.label : 'Scheduled'}
              errorText='Try again'
              disabled={count === 0}
              aria-disabled={outcome?.state === 'success' || undefined}
              onClick={approve}
            >
              Approve {count}
            </StatefulButton>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
