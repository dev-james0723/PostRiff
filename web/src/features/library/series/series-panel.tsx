'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusChip } from '@/features/queue/status-chip';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { errorMessage } from '@/lib/growth-v2/request';
import { seriesOff, useSeriesList } from '@/lib/growth-v2/series-hooks';
import type { SeriesSummary } from '@/lib/growth-v2/series-types';
import { coverageLine, fill, type SeriesCopy } from './series-copy';
import { SeriesCreateDialog } from './series-create';
import { SeriesDetailDialog } from './series-detail';
import { useSeriesCopy } from './use-series-copy';

function SeriesRow({ item, copy, onOpen }: { item: SeriesSummary; copy: SeriesCopy; onOpen: () => void }) {
  const origin = item.origin.kind === 'post'
    ? fill(copy.fromPost, { platform: item.origin.platform ?? '', date: item.origin.publishedAt ?? '' })
    : fill(copy.fromSource, { title: item.origin.title ?? '' });
  return (
    <button
      type='button'
      onClick={onOpen}
      className='rafii-glass hover:rafii-glass-selected rafii-focus flex min-h-14 w-full flex-col gap-1 rounded-[var(--rafii-radius-control)] px-4 py-3 text-left'
    >
      <span className='flex flex-wrap items-center gap-2'>
        <span className='min-w-0 flex-1 truncate text-sm font-medium'>{item.title}</span>
        <StatusChip tone={item.status === 'active' ? 'info' : 'neutral'}>{copy.status[item.status]}</StatusChip>
        {item.needsFactReview > 0 && <StatusChip tone='warning'>{fill(copy.needsReview, { n: item.needsFactReview })}</StatusChip>}
      </span>
      <span className='text-muted-foreground text-xs'>
        {item.origin.available ? origin : copy.originGone} · {coverageLine(copy, item.coveredCount, item.episodes)}
        {item.followers > 0 ? ` · ${fill(copy.followers, { n: item.followers })}` : ''}
      </span>
    </button>
  );
}

/**
 * Signature Series inside Library (the surface that holds reusable material): the list, starting a series from an old
 * post or a source, and each series' episodes, facts and decisions. Hidden when the deployment has the feature off.
 */
export function SeriesSection() {
  const copy = useSeriesCopy();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const [archived, setArchived] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useSeriesList(archived);
  if (seriesOff(list)) return null;
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <Surface as='section' material='quiet' radius='card' padding='md' aria-labelledby='series-heading' className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='flex min-w-0 flex-[1_1_18rem] flex-col gap-1'>
          <h2 id='series-heading' className='text-base font-medium'>{copy.sectionTitle}</h2>
          <p className='text-muted-foreground text-sm leading-relaxed'>{copy.sectionIntro}</p>
        </div>
        <div className='flex flex-wrap gap-2'>
          <Button variant='quiet' size='lg' className='min-h-11' aria-pressed={archived} onClick={() => setArchived((value) => !value)}>
            {archived ? copy.hideArchived : copy.showArchived}
          </Button>
          {canEdit && (
            <Button variant='glass' size='lg' className='min-h-11' onClick={() => setCreating(true)}>
              <Icons.add aria-hidden />
              {copy.newSeries}
            </Button>
          )}
        </div>
      </div>
      {list.isPending ? (
        <div className='flex flex-col gap-2' aria-hidden>
          <Skeleton className='h-14 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-14 w-full rounded-[var(--rafii-radius-control)]' />
        </div>
      ) : list.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.loadError}
          description={errorMessage(list.error)}
          action={<Button variant='glass' size='lg' onClick={() => void list.refetch()}>{copy.retry}</Button>}
        />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title={copy.emptyTitle} description={copy.emptyBody} />
      ) : (
        <ul role='list' aria-labelledby='series-heading' className='flex flex-col gap-2'>
          {items.map((item) => (
            <li key={item.id}>
              <SeriesRow item={item} copy={copy} onOpen={() => setOpenId(item.id)} />
            </li>
          ))}
        </ul>
      )}
      {list.hasNextPage && (
        <Button variant='quiet' size='lg' className='min-h-11 self-start' disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
          {copy.showMore}
        </Button>
      )}
      {canEdit && <SeriesCreateDialog open={creating} onOpenChange={setCreating} onCreated={(id) => { setCreating(false); setOpenId(id); }} />}
      <SeriesDetailDialog seriesId={openId} onClose={() => setOpenId(null)} />
    </Surface>
  );
}
