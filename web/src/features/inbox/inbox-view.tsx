'use client';

import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl, StateMessage, Surface, type SegmentOption } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { SHEET_ELEVATED } from '@/features/channels/rafii-materials';
import { ApiError } from '@/lib/api/client';
import { useAudience, useChannels } from '@/lib/api/hooks';
import type { Audience, ChannelView, ProviderView, Thread } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CoverageStrip } from './coverage-strip';
import {
  apiCounts,
  commentReadNames,
  commentsReadFor,
  INBOX_FILTERS,
  isAnswered,
  mergedReplies,
  replyHistoryReported,
  THREAD_PAGE_LIMIT,
  threadTime,
  type InboxFilter,
  type ReplyRecord
} from './model';
import type { ComposerState } from './reply-composer';
import { NoThreadSelected, ThreadDetail, ThreadHeading, threadHeadline } from './thread-detail';
import { ThreadList } from './thread-list';
import { useTwoPane } from './use-two-pane';

const infoContent = {
  title: 'Inbox',
  sections: [
    { title: 'One reply at a time', description: 'You see the comment first. Each reply is approved on its own; nothing is sent in bulk or automatically.' },
    { title: 'Labelled suggestions', description: 'A suggestion says whether AI or a plain starter line wrote it. You edit, then approve the exact text.' },
    { title: 'Which accounts appear', description: 'Accounts whose Comments level is Direct, on platforms Rafii reads comments from.' }
  ]
};

const PARAMS = {
  filter: parseAsStringLiteral(INBOX_FILTERS).withDefault('all'),
  thread: parseAsString
};

const EMPTY_COMPOSER: ComposerState = { text: '', draft: null };

/** Both panes share one height below the header so each scrolls on its own. */
const PANE_HEIGHT = 'lg:max-h-[calc(100dvh-16rem)] lg:min-h-80';

/** Conversation list beside the open thread from `lg` up (DNA §21.5); below it the thread is a separate step. */
const PANES = 'grid min-w-0 gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]';

const FILTER_LABELS: Record<InboxFilter, string> = { all: 'All', unanswered: 'Unanswered', replied: 'Replied' };

export function InboxView() {
  const { workspaceId } = useWorkspaceApi();
  const [, setParams] = useQueryStates(PARAMS, { history: 'replace', scroll: false });
  const previous = useRef(workspaceId);
  // A comment from one workspace means nothing in another: switching drops the open one.
  useEffect(() => {
    if (previous.current === workspaceId) return;
    previous.current = workspaceId;
    void setParams({ thread: null });
  }, [workspaceId, setParams]);
  // Keyed by workspace so unsaved reply text and this visit's approvals never carry across.
  return <InboxPage key={workspaceId} />;
}

function InboxPage() {
  const audience = useAudience();
  const channelsQuery = useChannels();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canReply = checkAccess(access, { permission: 'reply' });
  const twoPane = useTwoPane();
  const [params, setParams] = useQueryStates(PARAMS, { history: 'replace', scroll: false });
  const [composers, setComposers] = useState<Record<string, ComposerState>>({});
  const [sessionReplies, setSessionReplies] = useState<Record<string, ReplyRecord[]>>({});
  // The sheet keeps showing the comment it opened with while it slides closed.
  const [sheetThreadId, setSheetThreadId] = useState<string | null>(null);

  const data = audience.data;
  const channels = channelsQuery.data?.channels;
  const providers = channelsQuery.data?.providers;
  const channelsById = useMemo(() => new Map((channels ?? []).map((channel) => [channel.id, channel])), [channels]);

  const threads = useMemo(() => (data?.threads ?? []).toSorted((a, b) => threadTime(b).at - threadTime(a).at), [data]);
  const repliesFor = useCallback((thread: Thread) => mergedReplies(thread, sessionReplies[thread.threadId]), [sessionReplies]);
  const answered = useCallback((thread: Thread) => repliesFor(thread).some(isAnswered), [repliesFor]);
  const reported = replyHistoryReported(threads);
  const counts = data ? countsFor(data, threads, reported, answered) : null;
  const filtered = threads.filter((thread) => (params.filter === 'all' ? true : params.filter === 'replied' ? answered(thread) : !answered(thread)));
  const freshReplyIds = useMemo(() => new Set(Object.values(sessionReplies).flatMap((list) => list.map((reply) => reply.draftId))), [sessionReplies]);

  const selected = params.thread ? (threads.find((thread) => thread.threadId === params.thread) ?? null) : null;
  const missing = Boolean(params.thread && data && !selected);
  if (selected && selected.threadId !== sheetThreadId) setSheetThreadId(selected.threadId);
  const sheetThread = sheetThreadId ? (threads.find((thread) => thread.threadId === sheetThreadId) ?? null) : null;

  const select = (threadId: string) => void setParams({ thread: threadId });
  const clear = () => void setParams({ thread: null });

  const latestReply = useCallback(
    (thread: Thread) => {
      const replies = repliesFor(thread);
      return replies.findLast(isAnswered) ?? replies.findLast((reply) => reply.status === 'draft');
    },
    [repliesFor]
  );

  function detailFor(thread: Thread) {
    return (
      <ThreadDetail
        key={thread.threadId}
        thread={thread}
        channel={channelsById.get(thread.connectionId)}
        replies={repliesFor(thread)}
        freshReplyIds={freshReplyIds}
        composer={composers[thread.threadId] ?? EMPTY_COMPOSER}
        onComposerChange={(patch) =>
          setComposers((current) => ({ ...current, [thread.threadId]: { ...(current[thread.threadId] ?? EMPTY_COMPOSER), ...patch } }))
        }
        onApproved={(reply) => setSessionReplies((current) => ({ ...current, [thread.threadId]: [...(current[thread.threadId] ?? []), reply] }))}
        canEdit={canEdit}
        canReply={canReply}
      />
    );
  }

  // WHAT: the three reply-state views. Counts the server cannot vouch for are left out, never guessed.
  const filterOptions: SegmentOption<InboxFilter>[] = INBOX_FILTERS.map((filter) => {
    const count = counts?.[filter] ?? null;
    return {
      value: filter,
      label: (
        <>
          {FILTER_LABELS[filter]}
          {count !== null && <DigitSwap value={count} className='text-muted-foreground text-xs' />}
        </>
      )
    };
  });

  let main: ReactNode;
  if (audience.isPending) {
    main = <InboxSkeleton />;
  } else if (!data) {
    main = (
      <StateMessage
        kind='error'
        title="Couldn't load comments"
        description={audience.error instanceof ApiError ? audience.error.message : undefined}
        action={
          <Button variant='glass' size='control' onClick={() => void audience.refetch()}>
            <Icons.refresh className='size-4' />
            Try again
          </Button>
        }
      />
    );
  } else if (threads.length === 0) {
    main = <InboxEmpty channels={channels} providers={providers} />;
  } else {
    main = (
      <div className={PANES}>
        <section aria-label='Comments' className='flex min-w-0 flex-col gap-3'>
          <div className='relative -mx-1 overflow-x-auto px-1 py-0.5'>
            <SegmentedControl options={filterOptions} value={params.filter} onChange={(value) => void setParams({ filter: value })} label='Show comments' widths='content' />
          </div>
          {!reported && counts?.replied == null && (
            <p className='text-muted-foreground text-xs leading-relaxed'>Replied counts only replies approved this visit.</p>
          )}
          {audience.isError && (
            <StateMessage
              kind='stale'
              layout='inline'
              title="Couldn't refresh. Showing the last comments loaded."
              description={audience.error instanceof ApiError ? audience.error.message : undefined}
              action={
                <Button variant='glass' size='sm' className='h-9' onClick={() => void audience.refetch()}>
                  Try again
                </Button>
              }
              className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3'
            />
          )}
          <Surface material='quiet' radius='card' padding='none' data-tour='inbox-threads' className={cn('p-1.5 lg:overflow-y-auto', PANE_HEIGHT)}>
            {filtered.length > 0 ? (
              <ThreadList threads={filtered} selectedId={params.thread} onSelect={select} channelsById={channelsById} latestReply={latestReply} />
            ) : (
              <StateMessage
                kind='empty'
                layout='inline'
                title={
                  params.filter === 'unanswered'
                    ? 'Nothing waiting for a reply.'
                    : reported
                      ? 'No replies yet.'
                      : 'No replies approved this visit.'
                }
                action={
                  <Button variant='quiet' size='sm' className='h-9' onClick={() => void setParams({ filter: 'all' })}>
                    Show all
                  </Button>
                }
                className='px-3 py-4'
              />
            )}
          </Surface>
        </section>
        {twoPane && (
          <Surface material='quiet' radius='card' padding='none' className={cn('flex min-w-0 flex-col overflow-y-auto', PANE_HEIGHT)}>
            {selected ? (
              <>
                <div className='rafii-panel sticky top-0 z-10 rounded-t-[var(--rafii-radius-card)] px-5 py-3'>
                  <ThreadHeading thread={selected} channel={channelsById.get(selected.connectionId)} />
                </div>
                <div className='px-5 py-4'>{detailFor(selected)}</div>
              </>
            ) : (
              <NoThreadSelected missing={missing} onClear={clear} />
            )}
          </Surface>
        )}
      </div>
    );
  }

  const sheetHeadline = sheetThread ? threadHeadline(sheetThread, channelsById.get(sheetThread.connectionId)) : null;

  return (
    <PageContainer pageTitle='Inbox' infoContent={infoContent}>
      <div className='flex min-w-0 flex-col gap-5'>
        <CoverageStrip
          channels={channels}
          providers={providers}
          isPending={channelsQuery.isPending}
          error={channelsQuery.error}
          onRetry={() => void channelsQuery.refetch()}
        />
        {main}
        {/* The API's own limits line: secondary, so desktop only. */}
        {data && threads.length > 0 && <p className='text-muted-foreground hidden text-xs md:block'>{data.limits}</p>}
      </div>
      {/* Below `lg` the open comment is its own step: the list stays behind, Back returns to it (DNA §21.5). */}
      {!twoPane && (
        <Sheet open={Boolean(selected)} onOpenChange={(open) => !open && clear()}>
          <SheetContent side='right' showCloseButton={false} className={cn(SHEET_ELEVATED, 'data-[side=right]:w-full data-[side=right]:sm:max-w-lg')}>
            {sheetThread && sheetHeadline && (
              <>
                <SheetHeader className='gap-3 px-4 pt-3 pb-3'>
                  <Button variant='quiet' size='sm' className='-ml-2 h-11 w-fit gap-1 px-2.5 text-sm' onClick={clear}>
                    <Icons.chevronLeft className='size-4' aria-hidden />
                    Back to comments
                  </Button>
                  <div className='flex min-w-0 items-center gap-2.5'>
                    <ChannelIcon platform={sheetHeadline.platform} name={sheetHeadline.platform} />
                    <div className='min-w-0'>
                      <SheetTitle className='truncate'>{sheetHeadline.title}</SheetTitle>
                      <SheetDescription className='truncate text-xs'>{sheetHeadline.meta}</SheetDescription>
                    </div>
                  </div>
                </SheetHeader>
                <div className='min-h-0 flex-1 overflow-y-auto px-4 pt-1 pb-[max(1rem,env(safe-area-inset-bottom))]'>{detailFor(sheetThread)}</div>
              </>
            )}
          </SheetContent>
        </Sheet>
      )}
    </PageContainer>
  );
}

/** Tab counts that are complete; a count the server cannot vouch for is left out rather than guessed. */
function countsFor(data: Audience, threads: Thread[], reported: boolean, answered: (thread: Thread) => boolean): Record<InboxFilter, number | string | null> {
  const server = apiCounts(data);
  const capped = threads.length >= THREAD_PAGE_LIMIT;
  const repliedHere = reported && !capped ? threads.filter(answered).length : null;
  return {
    all: server?.all ?? (capped ? `${THREAD_PAGE_LIMIT}+` : threads.length),
    replied: server?.replied ?? repliedHere,
    unanswered: server?.unanswered ?? (repliedHere === null ? null : threads.length - repliedHere)
  };
}

/** Loading keeps the two-pane geometry (DNA §20.1) and says what is being loaded. */
function InboxSkeleton() {
  return (
    <div className={PANES}>
      <StateMessage kind='loading' title='Loading comments…' />
      <div aria-hidden className='rafii-quiet hidden min-h-48 rounded-[var(--rafii-radius-card)] lg:block' />
    </div>
  );
}

/**
 * No comments yet. The coverage strip above already lists each account with its Comments and Reply
 * levels and their evidence, so this state only says what is missing, with no second account list.
 */
function InboxEmpty({ channels, providers }: { channels: ChannelView[] | undefined; providers: ProviderView[] | undefined }) {
  const noAccounts = channels !== undefined && channels.length === 0;
  const anyDirect = (channels ?? []).some((channel) => channel.capabilities.comments_read?.level === 'Direct' && commentsReadFor(channel.platform, providers));
  return (
    <div data-tour='inbox-empty'>
      <StateMessage
        kind='empty'
        title='No comments yet'
        description={
          noAccounts
            ? undefined
            : anyDirect
              ? 'Comments are read once, when Rafii verifies a post it published. Later comments aren’t collected yet.'
              : `Comments appear for ${commentReadNames(providers)} accounts with Direct comments.`
        }
        media={
          <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
            <Icons.inbox className='size-5' />
          </span>
        }
      />
    </div>
  );
}
