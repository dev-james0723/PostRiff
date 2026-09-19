'use client';

import Link from 'next/link';
import { LevelBadge } from '@/components/app/level-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { buttonVariants } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { cn } from '@/lib/utils';
import {
  capabilitySummary,
  enableAnalyticsHref,
  unreadVerifiedCount,
  type Coverage
} from './coverage';

export type EmptyKind =
  | 'no-connections'
  | 'no-analytics-capability'
  | 'nothing-verified'
  | 'awaiting-first-reading';

/**
 * Which of the four empty states applies, from the real channel, job and post lists.
 * Returns null whenever at least one post has a reading — real numbers always show.
 */
export function chooseEmptyKind(coverage: Coverage): EmptyKind | null {
  const posts =
    coverage.connections.reduce((n, c) => n + c.posts.length, 0) + coverage.unmatchedPosts.length;
  if (posts > 0) return null;
  if (coverage.connections.length === 0) return 'no-connections';
  const direct = coverage.connections.filter((c) => c.direct);
  if (direct.length === 0) return 'no-analytics-capability';
  const verified = direct.reduce((n, c) => n + c.verifiedJobs.length, 0);
  return verified === 0 ? 'nothing-verified' : 'awaiting-first-reading';
}

function NextStep({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 't-learn')}>
      {children}
      <LearnMoreChevron />
    </Link>
  );
}

function AskAdmin({ children }: { children: React.ReactNode }) {
  return <p className='text-muted-foreground text-xs'>{children}</p>;
}

export function AnalyticsEmptyState({
  kind,
  coverage,
  canManage
}: {
  kind: EmptyKind;
  coverage: Coverage;
  canManage: boolean;
}) {
  if (kind === 'no-connections') {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant='icon'>
            <Icons.trendingUp />
          </EmptyMedia>
          <EmptyTitle>No accounts connected</EmptyTitle>
          <EmptyDescription>
            Analytics reads numbers for posts PostRiff published. Connect an account with the
            analytics capability first.
          </EmptyDescription>
        </EmptyHeader>
        {canManage ? (
          <NextStep href='/app/channels'>Connect a channel</NextStep>
        ) : (
          <AskAdmin>Ask an owner or admin to connect an account.</AskAdmin>
        )}
      </Empty>
    );
  }
  if (kind === 'no-analytics-capability') {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant='icon'>
            <Icons.lock />
          </EmptyMedia>
          <EmptyTitle>No account reports analytics yet</EmptyTitle>
          <EmptyDescription>
            Analytics is a separate permission from publishing. Each connected account shows the
            level PostRiff has verified for it.
          </EmptyDescription>
        </EmptyHeader>
        <ul className='flex w-full max-w-md flex-col gap-2 text-left text-sm'>
          {coverage.connections.map((connection) => (
            <li key={connection.id} className='flex flex-col gap-1 rounded-lg border p-3'>
              <span className='flex flex-wrap items-center gap-2'>
                <ChannelIcon platform={connection.platform} name={connection.platform} />
                <span className='font-medium'>{connection.account}</span>
                <LevelBadge level={connection.level} />
              </span>
              <span className='text-muted-foreground text-xs'>{capabilitySummary(connection)}</span>
              {connection.providerOffersAnalytics &&
                !connection.direct &&
                (canManage ? (
                  <Link
                    href={enableAnalyticsHref(connection.providerId)}
                    className='t-learn text-primary inline-flex w-fit items-center gap-0.5 text-xs hover:underline'
                  >
                    Enable analytics
                    <LearnMoreChevron />
                  </Link>
                ) : (
                  <AskAdmin>Ask an owner or admin to enable analytics for this account.</AskAdmin>
                ))}
            </li>
          ))}
        </ul>
      </Empty>
    );
  }
  if (kind === 'nothing-verified') {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant='icon'>
            <Icons.send />
          </EmptyMedia>
          <EmptyTitle>Nothing published through PostRiff yet</EmptyTitle>
          <EmptyDescription>
            Numbers are read for posts PostRiff published once the provider verifies them. Approve
            and schedule a post to start.
          </EmptyDescription>
        </EmptyHeader>
        <NextStep href='/app/queue'>Open the queue</NextStep>
      </Empty>
    );
  }
  const waiting = unreadVerifiedCount(coverage.connections.filter((c) => c.direct));
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant='icon'>
          <Icons.hourglass />
        </EmptyMedia>
        <EmptyTitle>Waiting for the first reading</EmptyTitle>
        <EmptyDescription>
          {waiting === 1 ? 'One verified post has' : `${waiting} verified posts have`} no reading
          yet. Readings are not scheduled yet, so there is no time to show; the numbers appear here
          once the provider has been asked.
        </EmptyDescription>
      </EmptyHeader>
      <NextStep href='/app/queue'>See the verified posts</NextStep>
    </Empty>
  );
}
