'use client';

import Link from 'next/link';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { orderMetricKeys, providerLabel } from './coverage';
import { MetricCell } from './metric-value';
import type { PostRowData } from './posts-table';

function Row({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className='grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-0.5 py-1.5'>
      <dt className='text-muted-foreground text-xs'>{label}</dt>
      <dd className={cn('min-w-0 text-sm break-words', mono && 'font-mono text-xs')}>{children}</dd>
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  return (
    <Button
      variant='quiet'
      size='icon-sm'
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          toast.success(`${label} copied.`);
        } catch {
          toast.error("Couldn't copy.");
        }
      }}
    >
      <Icons.copy />
    </Button>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className='rafii-eyebrow'>{children}</h3>;
}

/**
 * Everything the summary holds about one post, as it was returned: the provider's metrics with
 * their own names, the rate with its denominator, the reading time, and the publishing job's
 * text and receipt when the workspace snapshot still has that job.
 */
export function PostSheet({ row, families, open, onOpenChange }: { row: PostRowData | null; families: Record<string, string[]>; open: boolean; onOpenChange: (open: boolean) => void }) {
  const isMobile = useIsMobile();
  const post = row?.post;
  const job = row?.job ?? null;
  const text = job?.manifest.payload.text?.trim() || null;
  return (
    <Sheet open={open && row !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        className={cn(
          'rafii-elevated gap-0 overflow-y-auto border-0 data-[side=right]:sm:max-w-[30rem]',
          isMobile ? 'max-h-[85dvh] rounded-t-[var(--rafii-radius-mobile-dialog)]' : 'rounded-l-[var(--rafii-radius-dialog)]'
        )}
      >
        {post && (
          <>
            <SheetHeader className='pr-12'>
              <SheetTitle className='flex flex-wrap items-center gap-2'>
                <ChannelIcon platform={post.platform || post.provider} name={post.platform || post.provider} />
                {providerLabel(post)}
                {row?.connection && <span className='text-muted-foreground font-normal'>{row.connection.account}</span>}
                <StatusChip icon={null}>{post.publishedState.replace(/_/g, ' ')}</StatusChip>
              </SheetTitle>
              <SheetDescription>{[post.language, post.contentOrigin.replace(/_/g, ' ')].filter(Boolean).join(' · ')}</SheetDescription>
            </SheetHeader>
            <div className='flex flex-col gap-6 px-4 pb-4'>
              <section className='flex flex-col gap-2'>
                <SectionTitle>Text</SectionTitle>
                {text ? <p className='text-sm whitespace-pre-wrap'>{text}</p> : <p className='text-muted-foreground text-sm'>Text not available here. Open it in Queue.</p>}
              </section>
              <section className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4'>
                <SectionTitle>{providerLabel(post)} metrics</SectionTitle>
                <dl className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3'>
                  {orderMetricKeys(Object.keys(post.metrics), families).map((key) => {
                    const metric = post.metrics[key];
                    return (
                      <div key={key} className='flex flex-col'>
                        <dt className='text-muted-foreground text-xs'>
                          <span className='capitalize'>{metric.nativeName}</span>
                          {metric.unit && metric.unit !== 'count' ? <span className='opacity-70'> · {metric.unit}</span> : null}
                        </dt>
                        <dd>
                          <MetricCell metric={metric} />
                        </dd>
                      </div>
                    );
                  })}
                </dl>
                {Object.keys(post.rates).length > 0 && (
                  <dl className='mt-1 flex flex-col gap-1 text-sm'>
                    {Object.entries(post.rates).map(([key, rate]) => (
                      <div key={key} className='flex flex-wrap items-baseline gap-x-2'>
                        <dt className='text-muted-foreground text-xs'>{key.replace(/([A-Z])/g, ' $1').toLowerCase()}</dt>
                        <dd className={cn('tabular-nums', rate.numerator === null || rate.denominator === null ? 'text-muted-foreground italic' : undefined)}>{rate.display}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
              {/* One read per post today: the Readings section (PostReadings) returns when the API sends a history. The read time is in Details. */}
              <section className='flex flex-col gap-2'>
                <SectionTitle>Details</SectionTitle>
                <dl className='flex flex-col'>
                  <Row label='Post ID' mono>
                    <span className='inline-flex max-w-full items-center gap-1'>
                      <span className='truncate'>{post.providerPostId}</span>
                      <CopyButton value={post.providerPostId} label='post ID' />
                    </span>
                  </Row>
                  <Row label='Published'>
                    {job?.verification
                      ? `${formatDateTime(job.verification.at)} · ${job.verification.method.replace(/_/g, ' ')}`
                      : job
                        ? `${job.state.replace(/_/g, ' ')} · not verified`
                        : 'Not found in Queue'}
                  </Row>
                  {/* Platform and account are in the title; only an unmatched account is worth a row. */}
                  {!row?.connection && <Row label='Account'>Not linked to an account</Row>}
                  {post.contentTypeId && <Row label='Content type'>{post.contentTypeId}</Row>}
                  <Row label='Read'>{formatDateTime(post.freshness.observedAt)}</Row>
                </dl>
              </section>
            </div>
            <SheetFooter className='rafii-panel'>
              <Link href={post.jobId ? `/app/queue?job=${encodeURIComponent(post.jobId)}` : '/app/queue'} className={cn('t-learn w-fit', buttonVariants({ variant: 'glass', size: 'default' }))}>
                Open in Queue
                <LearnMoreChevron />
              </Link>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
