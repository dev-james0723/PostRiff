'use client';

import Link from 'next/link';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Separator } from '@/components/ui/separator';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { orderMetricKeys, providerLabel } from './coverage';
import { MetricCell } from './metric-value';
import { PostReadings } from './post-readings';
import type { PostRowData } from './posts-table';

function Row({
  label,
  children,
  mono
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
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
      variant='ghost'
      size='icon-xs'
      aria-label={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          toast.success(`${label} copied.`);
        } catch {
          toast.error('Could not copy.');
        }
      }}
    >
      <Icons.copy />
    </Button>
  );
}

/**
 * Everything the summary holds about one post, as it was returned: the provider's metrics with
 * their own names, the rate with its denominator, the reading time, and the publishing job's
 * text and receipt when the workspace snapshot still has that job.
 */
export function PostSheet({
  row,
  families,
  open,
  onOpenChange
}: {
  row: PostRowData | null;
  families: Record<string, string[]>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isMobile = useIsMobile();
  const post = row?.post;
  const job = row?.job ?? null;
  const text = job?.manifest.payload.text?.trim() || null;
  return (
    <Sheet open={open && row !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        className={cn(
          'gap-0 overflow-y-auto data-[side=right]:sm:max-w-[30rem]',
          isMobile && 'max-h-[85dvh] rounded-t-xl'
        )}
      >
        {post && (
          <>
            <SheetHeader className='pr-12'>
              <SheetTitle className='flex flex-wrap items-center gap-2'>
                <ChannelIcon
                  platform={post.platform || post.provider}
                  name={post.platform || post.provider}
                />
                {providerLabel(post)}
                {row?.connection && (
                  <span className='text-muted-foreground font-normal'>
                    {row.connection.account}
                  </span>
                )}
                <Badge variant='outline'>{post.publishedState.replace(/_/g, ' ')}</Badge>
              </SheetTitle>
              <SheetDescription>
                {post.language || 'Language not recorded'} · {post.contentOrigin.replace(/_/g, ' ')}
              </SheetDescription>
            </SheetHeader>
            <div className='flex flex-col gap-5 px-4 pb-4'>
              <section className='flex flex-col gap-1.5'>
                <h3 className='text-xs font-medium tracking-wide uppercase'>Text</h3>
                {text ? (
                  <p className='text-sm whitespace-pre-wrap'>{text}</p>
                ) : (
                  <p className='text-muted-foreground text-sm'>
                    The text is not part of this reading. The queue shows the post as it was
                    approved.
                  </p>
                )}
              </section>
              <Separator />
              <section className='flex flex-col gap-1.5'>
                <h3 className='text-xs font-medium tracking-wide uppercase'>
                  {providerLabel(post)} metrics
                </h3>
                <dl className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3'>
                  {orderMetricKeys(Object.keys(post.metrics), families).map((key) => {
                    const metric = post.metrics[key];
                    return (
                      <div key={key} className='flex flex-col'>
                        <dt className='text-muted-foreground text-xs'>
                          <span className='capitalize'>{metric.nativeName}</span>
                          {metric.unit && metric.unit !== 'count' ? (
                            <span className='opacity-70'> · {metric.unit}</span>
                          ) : null}
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
                        <dt className='text-muted-foreground text-xs'>
                          {key.replace(/([A-Z])/g, ' $1').toLowerCase()}
                        </dt>
                        <dd
                          className={cn(
                            'tabular-nums',
                            rate.numerator === null || rate.denominator === null
                              ? 'text-muted-foreground italic'
                              : undefined
                          )}
                        >
                          {rate.display}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                <p className='text-muted-foreground text-xs'>
                  Native names from {providerLabel(post)}; never added to another provider’s
                  numbers.
                </p>
              </section>
              <Separator />
              <section className='flex flex-col gap-1.5'>
                <h3 className='text-xs font-medium tracking-wide uppercase'>Readings</h3>
                <PostReadings readings={[{ observedAt: post.freshness.observedAt }]} />
                <p className='text-muted-foreground text-xs'>
                  Read {formatDateTime(post.freshness.observedAt)} · stored{' '}
                  {formatDateTime(post.freshness.ingestedAt)}
                </p>
              </section>
              <Separator />
              <section>
                <h3 className='text-xs font-medium tracking-wide uppercase'>Details</h3>
                <dl className='divide-y'>
                  <Row label='Provider post id' mono>
                    <span className='inline-flex max-w-full items-center gap-1'>
                      <span className='truncate'>{post.providerPostId}</span>
                      <CopyButton value={post.providerPostId} label='Provider post id' />
                    </span>
                  </Row>
                  <Row label='Job' mono>
                    {post.jobId ?? (
                      <span className='text-muted-foreground font-sans text-sm'>
                        Not linked to a job
                      </span>
                    )}
                  </Row>
                  <Row label='Published'>
                    {job?.verification
                      ? `${formatDateTime(job.verification.at)} · ${job.verification.method.replace(/_/g, ' ')}`
                      : job
                        ? `${job.state.replace(/_/g, ' ')} · not verified`
                        : 'The publishing job is not in this workspace snapshot'}
                  </Row>
                  <Row label='Platform'>{post.platform || post.provider}</Row>
                  <Row label='Account'>
                    {row?.connection?.account ?? 'Not matched to a connected account'}
                  </Row>
                  {post.contentTypeId && <Row label='Content type'>{post.contentTypeId}</Row>}
                  <Row label='Definitions'>{post.definitionVersion}</Row>
                  <Row label='Observed'>{formatDateTime(post.freshness.observedAt)}</Row>
                  <Row label='Ingested'>{formatDateTime(post.freshness.ingestedAt)}</Row>
                </dl>
              </section>
            </div>
            <SheetFooter className='border-t'>
              <Link
                href='/app/queue'
                className='t-learn text-primary inline-flex items-center gap-0.5 text-sm hover:underline'
              >
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
