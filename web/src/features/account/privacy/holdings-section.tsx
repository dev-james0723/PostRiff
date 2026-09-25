'use client';

import Link from 'next/link';
import { Surface } from '@/components/rafii';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import type { LearningSummary, Snapshot } from '@/lib/api/types';
import { StatTile } from '../settings-section';
import { holdingsFrom, plural } from './privacy-model';
import { PrivacySection, Unavailable, type Refetchable } from './section';

const linkClass = 't-learn rafii-focus text-foreground inline-flex items-center gap-0.5 rounded-sm font-medium hover:underline';

export function HoldingsSection({
  snapshot,
  memory
}: {
  snapshot: Refetchable & { data?: Snapshot; isPending: boolean };
  memory: Refetchable & { data?: { learning?: LearningSummary }; isPending: boolean };
}) {
  const holdings = snapshot.data ? holdingsFrom(snapshot.data.state) : null;
  const learning = memory.data?.learning;
  const learned = learning ? learning.items.filter((item) => item.status === 'active').length : null;

  const unread = 'Couldn’t read';

  return (
    <PrivacySection id='privacy-holdings' title='Your data' data-tour='privacy-holdings'>
      <Surface material='quiet' radius='card' padding='md' className='grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 xl:grid-cols-5'>
        {snapshot.isPending ? (
          Array.from({ length: 4 }, (_, index) => <StatTile key={index} label='Loading' value='' loading bare />)
        ) : (
          <>
            <StatTile
              bare
              label='Sources'
              value={holdings?.sources ?? 'Unavailable'}
              footer={!holdings ? unread : holdings.withdrawnSources > 0 ? `${plural(holdings.withdrawnSources, 'source')} withdrawn` : undefined}
            />
            <StatTile
              bare
              label='Drafts'
              value={holdings?.drafts ?? 'Unavailable'}
              footer={!holdings ? unread : holdings.blockedDrafts > 0 ? `${holdings.blockedDrafts} blocked by a retracted source` : undefined}
            />
            <StatTile bare label='Media files' value={holdings?.media ?? 'Unavailable'} footer={!holdings ? unread : undefined} />
            <StatTile
              bare
              label='Linked accounts'
              value={holdings?.linkedAccounts ?? 'Unavailable'}
              footer={
                <Link href='/app/channels' className={linkClass}>
                  Channels <LearnMoreChevron className='size-3.5' />
                </Link>
              }
            />
          </>
        )}
        {memory.isPending ? (
          <StatTile bare label='Learned preferences' value='' loading />
        ) : (
          <StatTile
            bare
            label='Learned preferences'
            value={learned ?? 'Unavailable'}
            footer={learned === null ? (memory.error ? unread : 'Not reported') : undefined}
          />
        )}
      </Surface>
      {snapshot.error ? <Unavailable query={snapshot} fallback='Couldn’t read this workspace.' /> : null}
      {memory.error ? <Unavailable query={memory} fallback='Couldn’t read learned preferences.' /> : null}
    </PrivacySection>
  );
}
