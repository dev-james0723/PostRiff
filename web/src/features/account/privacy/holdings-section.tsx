'use client';

import Link from 'next/link';
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

  return (
    <PrivacySection
      id='privacy-holdings'
      title='What PostRiff holds'
      description='Counted from this workspace just now. Unavailable means it could not be read, never zero.'
      data-tour='privacy-holdings'
    >
      <div className='grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5'>
        {snapshot.isPending ? (
          Array.from({ length: 4 }, (_, index) => <StatTile key={index} label='Loading' value='' loading />)
        ) : (
          <>
            <StatTile
              label='Sources'
              value={holdings?.sources ?? 'Unavailable'}
              footer={
                !holdings
                  ? 'Could not be read'
                  : holdings.withdrawnSources > 0
                    ? `${plural(holdings.withdrawnSources, 'source')} withdrawn`
                    : holdings.sources === 0
                      ? 'Nothing added yet'
                      : 'Text, links and files you added'
              }
            />
            <StatTile
              label='Drafts'
              value={holdings?.drafts ?? 'Unavailable'}
              footer={
                !holdings
                  ? 'Could not be read'
                  : holdings.blockedDrafts > 0
                    ? `${holdings.blockedDrafts} blocked by a retracted source`
                    : holdings.drafts === 0
                      ? 'Nothing added yet'
                      : 'Kept with their revision history'
              }
            />
            <StatTile
              label='Media files'
              value={holdings?.media ?? 'Unavailable'}
              footer={!holdings ? 'Could not be read' : holdings.media === 0 ? 'Nothing added yet' : 'Uploaded or generated images and video'}
            />
            <StatTile
              label='Linked accounts'
              value={holdings?.linkedAccounts ?? 'Unavailable'}
              footer={
                <Link href='/app/channels' className={linkClass}>
                  Details on Channels <LearnMoreChevron className='size-3.5' />
                </Link>
              }
            />
          </>
        )}
        {memory.isPending ? (
          <StatTile label='Learned preferences' value='' loading />
        ) : (
          <StatTile
            label='Learned preferences'
            value={learned ?? 'Unavailable'}
            footer={
              learned === null
                ? memory.error
                  ? 'Could not be read'
                  : 'Not reported for this workspace'
                : learned === 0
                  ? 'Nothing learned yet'
                  : 'About how drafts should read'
            }
          />
        )}
      </div>
      {snapshot.error ? <Unavailable query={snapshot} fallback='The workspace could not be read.' /> : null}
      {memory.error ? <Unavailable query={memory} fallback='Learned preferences could not be read.' /> : null}
    </PrivacySection>
  );
}
