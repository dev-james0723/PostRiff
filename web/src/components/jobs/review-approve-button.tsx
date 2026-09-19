'use client';

import { toast } from 'sonner';
import { StatefulButton } from '@/components/motion/button';
import { useFlash } from '@/hooks/use-flash';
import { useAct } from '@/lib/api/hooks';
import type { Review } from '@/lib/api/types';
import { reportActionError } from '@/features/queue/action-error';

/** Submits only the exact reviewed digest and verifies the returned receipt before claiming success. */
export function ReviewApproveButton({ review, revision, allowed, nowSeconds, onReload, onOpenJob }: {
  review: Review; revision: number; allowed: boolean; nowSeconds: number;
  onReload: () => void; onOpenJob: (jobId: string) => void;
}) {
  const act = useAct();
  const [outcome, flashOutcome] = useFlash<'success' | 'error'>();
  const manifest = review.manifest;
  const expired = manifest.expiresAt <= nowSeconds;
  if (!allowed || review.status !== 'needs_review') return null;
  return (
          <StatefulButton
            state={act.isPending ? 'loading' : (outcome ?? 'idle')}
            loadingText='Approving…'
            successText='Scheduled'
            errorText='Try again'
            disabled={expired}
            // Approved: the card is on its way out. It keeps full opacity so "Scheduled" reads, but takes no second click.
            aria-disabled={outcome === 'success' || undefined}
            onClick={() => {
              if (outcome === 'success') return;
              act.mutate(
                { revision, action: 'p2_approve', payload: { reviewId: review.id, digest: review.digest, confirmed: true } },
                {
                  // Say "scheduled" only when the server's answer shows it: this review approved and its job there.
                  onSuccess: (next) => {
                    const phase = next.state.phase2;
                    const approved = phase?.reviews.find((r) => r.id === review.id)?.status === 'approved';
                    const job = phase?.jobs.find((j) => j.manifest.idempotencyKey === manifest.idempotencyKey);
                    if (approved && job) {
                      toast.success('Approved and scheduled.');
                      flashOutcome('success');
                    } else if (job) {
                      toast.info('This exact post was already a job, so nothing new was scheduled.', {
                        action: { label: 'Open job', onClick: () => onOpenJob(job.id) }
                      });
                    } else {
                      toast.error('The approval was answered, but no job appeared. Reload the queue to check.', {
                        action: { label: 'Reload', onClick: onReload }
                      });
                      flashOutcome('error');
                    }
                  },
                  onError: (err) => {
                    reportActionError(err, 'Approval failed.', onReload);
                    flashOutcome('error');
                  }
                }
              );
            }}
          >
            Approve & schedule
          </StatefulButton>
  );
}
