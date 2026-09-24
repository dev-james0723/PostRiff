'use client';

import Link from 'next/link';
import { LevelBadge } from '@/components/app/level-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { CollectionRow, StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { cn } from '@/lib/utils';
import { capabilitySummary, enableAnalyticsHref, unreadVerifiedCount, type Coverage } from './coverage';

export type EmptyKind = 'no-connections' | 'no-analytics-capability' | 'nothing-verified' | 'awaiting-first-reading';

/**
 * Which of the four empty states applies, from the real channel, job and post lists.
 * Returns null whenever at least one post has a reading — real numbers always show.
 */
export function chooseEmptyKind(coverage: Coverage): EmptyKind | null {
  const posts = coverage.connections.reduce((n, c) => n + c.posts.length, 0) + coverage.unmatchedPosts.length;
  if (posts > 0) return null;
  if (coverage.connections.length === 0) return 'no-connections';
  const direct = coverage.connections.filter((c) => c.direct);
  if (direct.length === 0) return 'no-analytics-capability';
  const verified = direct.reduce((n, c) => n + c.verifiedJobs.length, 0);
  return verified === 0 ? 'nothing-verified' : 'awaiting-first-reading';
}

function NextStep({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={cn(buttonVariants({ variant: 'glass', size: 'default' }), 't-learn')}>
      {children}
      <LearnMoreChevron />
    </Link>
  );
}

function AskAdmin({ children }: { children: React.ReactNode }) {
  return <p className='text-muted-foreground text-xs'>{children}</p>;
}

export function AnalyticsEmptyState({ kind, coverage, canManage }: { kind: EmptyKind; coverage: Coverage; canManage: boolean }) {
  if (kind === 'no-connections') {
    return (
      <StateMessage
        kind='empty'
        title='No accounts connected'
        description='Analytics reads numbers for posts PostRiff published. Connect an account with the analytics capability first.'
        action={canManage ? <NextStep href='/app/channels'>Connect a channel</NextStep> : <AskAdmin>Ask an owner or admin to connect an account.</AskAdmin>}
      />
    );
  }
  if (kind === 'no-analytics-capability') {
    return (
      <StateMessage
        kind='permission'
        title='No account reports analytics yet'
        description='Analytics is a separate permission from publishing. Each connected account shows the level PostRiff has verified for it.'
        action={
          <ul className='flex w-full max-w-md flex-col gap-2 text-left'>
            {coverage.connections.map((connection) => (
              <CollectionRow
                key={connection.id}
                as='li'
                className='rafii-glass flex-wrap py-3'
                leading={<ChannelIcon platform={connection.platform} name={connection.platform} />}
                title={connection.account}
                meta={
                  <>
                    <span className='block'>{capabilitySummary(connection)}</span>
                    {connection.providerOffersAnalytics &&
                      !connection.direct &&
                      (canManage ? (
                        <Link href={enableAnalyticsHref(connection.providerId)} className='t-learn rafii-focus text-foreground mt-1 inline-flex w-fit items-center gap-0.5 rounded-md underline underline-offset-4'>
                          Enable analytics
                          <LearnMoreChevron />
                        </Link>
                      ) : (
                        <span className='mt-1 block'>Ask an owner or admin to enable analytics for this account.</span>
                      ))}
                  </>
                }
                actions={<LevelBadge level={connection.level} />}
              />
            ))}
          </ul>
        }
      />
    );
  }
  if (kind === 'nothing-verified') {
    return (
      <StateMessage
        kind='empty'
        title='Nothing published through PostRiff yet'
        description='Numbers are read for posts PostRiff published once the provider verifies them. Approve and schedule a post to start.'
        action={<NextStep href='/app/queue'>Open the queue</NextStep>}
      />
    );
  }
  const waiting = unreadVerifiedCount(coverage.connections.filter((c) => c.direct));
  return (
    <StateMessage
      kind='stale'
      title='Waiting for the first reading'
      description={`${waiting === 1 ? 'One verified post has' : `${waiting} verified posts have`} no reading yet. Readings are not scheduled yet, so there is no time to show; the numbers appear here once the provider has been asked.`}
      action={<NextStep href='/app/queue'>See the verified posts</NextStep>}
    />
  );
}
