'use client';

import { useRef, useState } from 'react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useRelationshipPages } from '@/lib/growth-v2/relationships-hooks';
import { followUpLine, platformName, stateTone } from '@/lib/growth-v2/relationships-model';
import type { Relationship } from '@/lib/growth-v2/relationships-types';
import { cn } from '@/lib/utils';
import { currentCopy, currentLang, describeProblem, when } from './copy';
import { FollowUpCard } from './follow-up-card';
import { FollowUpCreate } from './follow-up-section';
import { useReturnFocus } from './focus';

/**
 * The "Follow-ups" view of the Inbox: open follow-ups, due first (the server's deterministic order), one row each with
 * its stage, reminder and next step. Pages of 25, "Load more" for the rest. Every loaded page refreshes together after
 * a change, so the list never collapses back to its first page; a list that couldn't load says so (never "no
 * follow-ups"), and a failed refresh keeps the last rows with a notice.
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
  const lang = currentLang();
  const list = useRelationshipPages({ state: 'open' });
  const [creating, setCreating] = useState(false);
  const newButton = useRef<HTMLButtonElement>(null);
  useReturnFocus(creating, newButton);

  if (list.isPending) return <StateMessage kind='loading' layout='inline' title={copy.loading} className='px-3 py-4' />;
  if (!list.data) {
    return (
      <div lang={lang}>
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.listFailed}
          description={<span lang={describeProblem(list.error, copy).lang}>{describeProblem(list.error, copy).message}</span>}
          action={<Button variant='glass' size='sm' className='h-9' onClick={() => void list.refetch()}>{copy.reload}</Button>}
          className='px-3 py-4'
        />
      </div>
    );
  }
  const pages = list.data.pages;
  const rows = pages.flatMap((page) => page.relationships).filter((item, index, all) => all.findIndex((other) => other.id === item.id) === index);
  const counts = pages[0]?.counts;

  const start = canEdit ? (
    creating ? (
      <FollowUpCreate onCreated={(created) => { setCreating(false); onSelect(created); }} onCancel={() => setCreating(false)} />
    ) : (
      <Button ref={newButton} variant='glass' size='sm' className='h-9 w-fit' onClick={() => setCreating(true)}>
        <Icons.add className='size-4' aria-hidden />
        {copy.newFollowUp}
      </Button>
    )
  ) : null;
  const stale = list.isRefetchError && (
    <p role='status' className='text-muted-foreground flex flex-wrap items-center gap-2 px-3 text-xs'>
      {copy.staleNotice}
      <Button variant='quiet' size='sm' className='h-9' onClick={() => void list.refetch()}>{copy.reload}</Button>
    </p>
  );
  if (rows.length === 0) {
    return (
      <div lang={lang} className='flex flex-col gap-2 p-1.5'>
        {stale}
        <StateMessage kind='empty' layout='inline' title={copy.empty} description={copy.emptyHint} className='px-3 py-4' />
        {start}
      </div>
    );
  }
  return (
    <div lang={lang} className='flex flex-col gap-2'>
      {start && <div className='px-1.5 pt-1.5'>{start}</div>}
      {stale}
      {counts?.dueNow === 0 && <p className='text-muted-foreground px-3 pt-2 text-xs'>{copy.nothingDue}</p>}
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
                {item.contact && <span className='text-muted-foreground truncate text-xs'>{platformName(item.contact.provider, copy.thePlatform)}{item.contact.ref ? ` · ${item.contact.ref}` : ''}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      {list.isFetchNextPageError && (
        <p role='alert' className='text-destructive px-3 text-sm'>
          <span lang={describeProblem(list.error, copy).lang}>{describeProblem(list.error, copy).message}</span>
        </p>
      )}
      {list.hasNextPage && (
        <Button variant='quiet' size='sm' disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
          {list.isFetchingNextPage ? copy.loading : copy.loadMore}
        </Button>
      )}
    </div>
  );
}

/** Where the Inbox stands on loading the conversation a follow-up's Reply asked for (see `InboxView`). */
export type ConversationSeek = 'idle' | 'seeking' | 'more' | 'missing';

/**
 * The follow-up on its own (no conversation open beside it): the same card, keyed by its id so nothing typed for one
 * follow-up survives a switch to another. Reply opens the conversation's composer; while the Inbox is still loading an
 * older conversation it says so here, with a way to keep looking.
 */
export function FollowUpPanel({
  relationshipId,
  canEdit,
  onReply,
  seek = 'idle',
  onKeepLooking
}: {
  relationshipId: string;
  canEdit: boolean;
  onReply?: (threadId: string) => void;
  seek?: ConversationSeek;
  onKeepLooking?: () => void;
}) {
  const copy = currentCopy();
  const lang = currentLang();
  return (
    <div lang={lang} className='flex flex-col gap-3'>
      <h2 className='text-muted-foreground text-xs font-medium'>{copy.section}</h2>
      {seek === 'seeking' && <StateMessage kind='loading' layout='inline' title={copy.findingConversation} />}
      {seek === 'more' && (
        <p role='status' className='text-muted-foreground flex flex-wrap items-center gap-2 text-sm'>
          {copy.conversationOlder}
          {onKeepLooking && <Button variant='glass' size='sm' className='h-9' onClick={onKeepLooking}>{copy.keepLooking}</Button>}
        </p>
      )}
      {seek === 'missing' && <p role='status' className='text-muted-foreground text-sm'>{copy.conversationMissing}</p>}
      <FollowUpCard key={relationshipId} relationshipId={relationshipId} canEdit={canEdit} focusOnLoad onReply={onReply} />
    </div>
  );
}
