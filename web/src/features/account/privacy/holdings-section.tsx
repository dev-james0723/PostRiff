'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { NumberTicker } from '@/components/motion/number-ticker';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import type { LearningSummary, Snapshot } from '@/lib/api/types';
import { holdingsFrom, plural } from './privacy-model';
import { PrivacySection, Unavailable, type Refetchable } from './section';

const TILE_CLASS = 'bg-card ring-foreground/10 flex min-w-0 flex-col gap-1 rounded-xl p-3 ring-1 sm:p-4';
const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 font-medium hover:underline';

/** Roll once, inside the motion budget: 0.26s per digit plus a 40ms stagger stays near 300ms for short numbers. */
function Count({ value }: { value: number }) {
  return <NumberTicker value={value} locale startOnView={false} duration={0.26} stagger={value >= 1000 ? 0 : 0.04} />;
}

function Tile({ label, value, hint }: { label: string; value: number | null; hint: ReactNode }) {
  return (
    <div className={TILE_CLASS}>
      <span className='text-muted-foreground text-xs font-medium'>{label}</span>
      <span className='text-2xl font-semibold tabular-nums'>
        {value === null ? <span className='text-muted-foreground text-base font-medium'>Unavailable</span> : <Count value={value} />}
      </span>
      <span className='text-muted-foreground text-xs'>{hint}</span>
    </div>
  );
}

function TileSkeleton() {
  return (
    <div className={TILE_CLASS} aria-hidden>
      <Skeleton className='h-3.5 w-20' />
      <Skeleton className='mt-1 h-7 w-12' />
      <Skeleton className='mt-1 h-3 w-28' />
    </div>
  );
}

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
          Array.from({ length: 4 }, (_, index) => <TileSkeleton key={index} />)
        ) : (
          <>
            <Tile
              label='Sources'
              value={holdings?.sources ?? null}
              hint={
                !holdings
                  ? 'Could not be read'
                  : holdings.withdrawnSources > 0
                    ? `${plural(holdings.withdrawnSources, 'source')} withdrawn`
                    : holdings.sources === 0
                      ? 'Nothing added yet'
                      : 'Text, links and files you added'
              }
            />
            <Tile
              label='Drafts'
              value={holdings?.drafts ?? null}
              hint={
                !holdings
                  ? 'Could not be read'
                  : holdings.blockedDrafts > 0
                    ? `${holdings.blockedDrafts} blocked by a retracted source`
                    : holdings.drafts === 0
                      ? 'Nothing added yet'
                      : 'Kept with their revision history'
              }
            />
            <Tile
              label='Media files'
              value={holdings?.media ?? null}
              hint={!holdings ? 'Could not be read' : holdings.media === 0 ? 'Nothing added yet' : 'Uploaded or generated images and video'}
            />
            <Tile
              label='Linked accounts'
              value={holdings?.linkedAccounts ?? null}
              hint={
                <Link href='/app/channels' className={linkClass}>
                  Details on Channels <LearnMoreChevron className='size-3.5' />
                </Link>
              }
            />
          </>
        )}
        {memory.isPending ? (
          <TileSkeleton />
        ) : (
          <Tile
            label='Learned preferences'
            value={learned}
            hint={
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
