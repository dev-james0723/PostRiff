'use client';

import { useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { StatefulButton } from '@/components/motion/button';
import { HourlyCeilingDialog } from '@/features/channels/discord-hourly-ceiling-notice';
import { useFlash } from '@/hooks/use-flash';
import { useLocalTimeZone } from '@/hooks/use-local-time-zone';
import { useAct } from '@/lib/api/hooks';
import type { Review } from '@/lib/api/types';
import { reportActionError } from '@/features/queue/action-error';
import { discordCopy } from '@/lib/channels/discord-copy';
import { calendarDayHref, draftHref, hourlyCeilingLimit, isHourlyCeiling } from '@/lib/channels/discord-hourly-ceiling';
import { usePreferences } from '@/lib/preferences';
import { STATUS } from '@/lib/status-labels';

/** Submits only the exact reviewed digest and verifies the returned receipt before claiming success. */
export function ReviewApproveButton({ review, revision, allowed, nowSeconds, onReload, onOpenJob }: {
  review: Review; revision: number; allowed: boolean; nowSeconds: number;
  onReload: () => void; onOpenJob: (jobId: string) => void;
}) {
  const act = useAct();
  const [outcome, flashOutcome] = useFlash<'success' | 'error' | 'full'>();
  // The Discord hourly ceiling refuses the approval: the limit it names, while the explanation is open.
  const [full, setFull] = useState<number | null>(null);
  const copy = discordCopy(usePreferences().locale);
  const zone = useLocalTimeZone();
  const button = useRef<HTMLButtonElement>(null);
  const manifest = review.manifest;
  const seeHref = useMemo(() => calendarDayHref(Date.parse(manifest.timing.utc), zone), [manifest.timing.utc, zone]);
  const expired = manifest.expiresAt <= nowSeconds;
  const actionLabel = manifest.platform === 'Douyin'
    ? 'Approve Douyin video & schedule'
    : 'Approve & schedule';
  if (!allowed || review.status !== 'needs_review') return null;
  const draft = draftHref(manifest.variantId);
  return (
    <>
          <StatefulButton
            ref={button}
            state={act.isPending ? 'loading' : outcome === 'full' ? 'error' : (outcome ?? 'idle')}
            loadingText='Approving…'
            successText='Scheduled'
            errorText={outcome === 'full' ? copy.hourlyCeilingButton : 'Try again'}
            disabled={expired}
            data-review-approve={review.id}
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
                      // The card leaves at once, so a short toast carries the outcome.
                      toast.success(STATUS.scheduled);
                      flashOutcome('success');
                    } else if (job) {
                      toast.info('Already scheduled', {
                        action: { label: 'Open', onClick: () => onOpenJob(job.id) }
                      });
                    } else {
                      toast.error('Couldn’t confirm it was scheduled', {
                        description: 'Reload to check.',
                        action: { label: 'Reload', onClick: onReload }
                      });
                      flashOutcome('error');
                    }
                  },
                  onError: (err) => {
                    // A full hour is the plan's answer, not a failure to retry: the review is unchanged and still waiting.
                    if (isHourlyCeiling(err)) {
                      setFull(hourlyCeilingLimit(err));
                      flashOutcome('full');
                      return;
                    }
                    reportActionError(err, 'Couldn’t approve this post', onReload);
                    flashOutcome('error');
                  }
                }
              );
            }}
          >
            {actionLabel}
          </StatefulButton>
          <HourlyCeilingDialog
            open={full !== null}
            onOpenChange={(open) => { if (!open) setFull(null); }}
            finalFocus={button}
            copy={copy}
            place='single'
            limit={full ?? hourlyCeilingLimit(null)}
            // The web has no Move action: a move is a cancel, a new review for the new time, and this approval.
            moving
            actions={{ ...(draft ? { chooseTime: { href: draft } } : {}), see: { href: seeHref } }}
          />
    </>
  );
}
