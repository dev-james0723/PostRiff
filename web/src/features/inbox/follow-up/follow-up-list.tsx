'use client';

import { useEffect, useState } from 'react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/growth-v2/request';
import { useRelationshipList, useRelationshipsApi } from '@/lib/growth-v2/relationships-hooks';
import { followUpLine, platformName, stateTone } from '@/lib/growth-v2/relationships-model';
import type { Relationship } from '@/lib/growth-v2/relationships-types';
import { cn } from '@/lib/utils';
import { currentCopy, when } from './copy';
import { FollowUpCard } from './follow-up-card';
import { FollowUpCreate } from './follow-up-section';

/**
 * The "Follow-ups" view of the Inbox: open follow-ups, due first (the server's deterministic order), one row each with
 * its stage, reminder and next step. Pages of 25, "Load more" for the rest; nothing is fetched beyond what is shown.
 */
export function FollowUpList({
  selectedId,
  onSelect,
  canEdit
}: {
  selectedId: string | null;
  onSelect: (relationship: Relationship) => void;
  canEdit: boolean;
}) {
  const copy = currentCopy();
  const { api, w } = useRelationshipsApi();
  const first = useRelationshipList({ state: 'open' });
  const [extra, setExtra] = useState<Relationship[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setExtra([]);
    setCursor(first.data?.nextCursor ?? null);
  }, [first.data]);

  if (first.isPending) return <StateMessage kind='loading' layout='inline' title={copy.loading} className='px-3 py-4' />;
  if (first.isError || !first.data) {
    return (
      <StateMessage
        kind='error'
        layout='inline'
        title={errorMessage(first.error, copy.failed)}
        action={<Button variant='glass' size='sm' className='h-9' onClick={() => void first.refetch()}>{copy.reload}</Button>}
        className='px-3 py-4'
      />
    );
  }
  const rows = [...first.data.relationships, ...extra.filter((item) => !first.data.relationships.some((known) => known.id === item.id))];

  async function loadMore() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    setProblem(null);
    try {
      const page = await api.list(w, { state: 'open', cursor });
      setExtra((current) => [...current, ...page.relationships.filter((item) => !current.some((known) => known.id === item.id))]);
      setCursor(page.nextCursor);
    } catch (error) {
      setProblem(errorMessage(error, copy.failed));
    } finally {
      setLoadingMore(false);
    }
  }

  const start = canEdit ? (
    creating ? (
      <FollowUpCreate onCreated={(created) => { setCreating(false); onSelect(created); }} onCancel={() => setCreating(false)} />
    ) : (
      <Button variant='glass' size='sm' className='h-9 w-fit' onClick={() => setCreating(true)}>
        <Icons.add className='size-4' aria-hidden />
        {copy.newFollowUp}
      </Button>
    )
  ) : null;
  if (rows.length === 0) {
    return (
      <div className='flex flex-col gap-2 p-1.5'>
        <StateMessage kind='empty' layout='inline' title={copy.empty} description={copy.emptyHint} className='px-3 py-4' />
        {start}
      </div>
    );
  }
  return (
    <div className='flex flex-col gap-2'>
      {start && <div className='px-1.5 pt-1.5'>{start}</div>}
      {first.data.counts.dueNow === 0 && <p className='text-muted-foreground px-3 pt-2 text-xs'>{copy.nothingDue}</p>}
      <ul className='flex flex-col gap-1' aria-label={copy.tab}>
        {rows.map((item) => {
          const selected = item.id === selectedId;
          return (
            <li key={item.id}>
              <button
                type='button'
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(item)}
                className={cn(
                  'rafii-focus relative flex min-h-14 w-full flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-left transition-colors motion-reduce:transition-none',
                  selected ? 'rafii-glass-selected' : 'hover:bg-foreground/5'
                )}
              >
                <span className='flex min-w-0 items-center gap-2'>
                  {item.followUp.dueNow && <Icons.clock className='text-foreground size-4 shrink-0' aria-label={copy.dueNow} />}
                  <span className='text-foreground truncate text-sm font-medium'>{item.displayName}</span>
                  <AnimatedBadge layout={false} size='sm' status={stateTone(item.state)} showIcon={false} className='rafii-quiet ml-auto border-0' contentKey={item.state}>
                    {copy.states[item.state]}
                  </AnimatedBadge>
                </span>
                <span className={cn('text-xs', item.followUp.dueNow ? 'text-foreground' : 'text-muted-foreground')}>{followUpLine(item, copy, when)}</span>
                {item.nextAction && <span className='text-muted-foreground line-clamp-2 text-sm break-words'>{copy.nextAction}: {item.nextAction}</span>}
                {item.contact && <span className='text-muted-foreground truncate text-xs'>{platformName(item.contact.provider)}{item.contact.ref ? ` · ${item.contact.ref}` : ''}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      {problem && <p role='alert' className='text-destructive px-3 text-sm'>{problem}</p>}
      {cursor && (
        <Button variant='quiet' size='sm' disabled={loadingMore} onClick={() => void loadMore()}>
          {loadingMore ? copy.loading : copy.loadMore}
        </Button>
      )}
    </div>
  );
}

/** The follow-up on its own (no conversation open beside it): the same card, with the reply route it allows. */
export function FollowUpPanel({ relationshipId, canEdit }: { relationshipId: string; canEdit: boolean }) {
  const copy = currentCopy();
  return (
    <div className='flex flex-col gap-3'>
      <h2 className='text-muted-foreground text-xs font-medium'>{copy.section}</h2>
      <FollowUpCard relationshipId={relationshipId} canEdit={canEdit} focusOnLoad />
    </div>
  );
}

