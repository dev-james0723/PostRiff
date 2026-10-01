'use client';

import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
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
import { relativeTime } from '@/lib/time';
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
  TRIAGE_FILTERS,
  threadTime,
  type InboxFilter,
  type ReplyRecord
} from './model';
import type { ComposerState } from './reply-composer';
import { NoThreadSelected, ThreadDetail, ThreadHeading, threadHeadline } from './thread-detail';
import { ThreadList } from './thread-list';
import { useTwoPane } from './use-two-pane';
import { GrowthEntry } from '@/features/growth/studio-parts';
import { followUpsOff, useRelationshipList } from '@/lib/growth-v2/relationships-hooks';
import type { Relationship } from '@/lib/growth-v2/relationships-types';
import { currentCopy } from './follow-up/copy';
import { FollowUpList, FollowUpPanel } from './follow-up/follow-up-list';

const infoContent = {
  title: 'Inbox',
  sections: [
    { title: 'One reply at a time', description: 'You see the comment first. Each reply is approved on its own; nothing is sent in bulk or automatically.' },
    { title: 'Labelled suggestions', description: "Suggestions are written by Rafii's AI writer from the comment and, where available, your post, facts you cleared for public use and the voice memory you allowed a cloud model to read. You edit, then approve the exact text." },
    { title: 'Which accounts appear', description: 'Accounts whose Comments level is Direct, on platforms Rafii reads comments from.' }
  ]
};

const PARAMS = {
  filter: parseAsStringLiteral(INBOX_FILTERS).withDefault('all'),
  thread: parseAsString,
  /** The follow-up shown with (or instead of) a conversation in the Follow-ups view. */
  relationship: parseAsString
};

const EMPTY_COMPOSER: ComposerState = { text: '', draft: null };

/** Both panes share one height below the header so each scrolls on its own. */
const PANE_HEIGHT = 'lg:max-h-[calc(100dvh-16rem)] lg:min-h-80';

/** Conversation list beside the open thread from `lg` up (DNA §21.5); below it the thread is a separate step. */
const PANES = 'grid min-w-0 gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]';

const FILTER_LABELS: Record<InboxFilter, string> = { all: 'All', needs_reply: 'Needs reply', review: 'Review', fyi: 'FYI', unanswered: 'Unanswered', replied: 'Replied', follow_ups: 'Follow-ups' };

export function InboxView() {
  const { workspaceId } = useWorkspaceApi();
  const [, setParams] = useQueryStates(PARAMS, { history: 'replace', scroll: false });
  const previous = useRef(workspaceId);
  // A comment from one workspace means nothing in another: switching drops the open one.
  useEffect(() => {
    if (previous.current === workspaceId) return;
    previous.current = workspaceId;
    void setParams({ thread: null, relationship: null });
  }, [workspaceId, setParams]);
  // Keyed by workspace so unsaved reply text and this visit's approvals never carry across.
  return <InboxPage key={workspaceId} />;
}

function InboxPage() {
  const { api, workspaceId } = useWorkspaceApi();
  const audience = useAudience();
  const channelsQuery = useChannels();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canReply = checkAccess(access, { permission: 'reply' });
  const twoPane = useTwoPane();
  const [params, setParams] = useQueryStates(PARAMS, { history: 'replace', scroll: false });
  const [composers, setComposers] = useState<Record<string, ComposerState>>({});
  const [sessionReplies, setSessionReplies] = useState<Record<string, ReplyRecord[]>>({});
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [extraThreads, setExtraThreads] = useState<Thread[]>([]);
  const [pageCursor, setPageCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // The sheet keeps showing the comment it opened with while it slides closed.
  const [sheetThreadId, setSheetThreadId] = useState<string | null>(null);
  const [sheetRelationshipId, setSheetRelationshipId] = useState<string | null>(null);
  const [sheetKind, setSheetKind] = useState<'thread' | 'relationship'>('thread');
  // Relationship follow-ups: one bounded read for the tab and its due count; 404 feature_disabled hides the tab.
  const followUps = useRelationshipList({ state: 'open', due: 'due_now', limit: 1 });
  const followUpsAvailable = Boolean(followUps.data);
  const followUpCopy = currentCopy();

  const data = audience.data;
  useEffect(() => {
    setExtraThreads([]);
    setPageCursor(data?.nextCursor ?? null);
  }, [data]);
  const channels = channelsQuery.data?.channels;
  const providers = channelsQuery.data?.providers;
  const channelsById = useMemo(() => new Map((channels ?? []).map((channel) => [channel.id, channel])), [channels]);

  const allThreads = useMemo(() => [...(data?.threads ?? []), ...extraThreads], [data, extraThreads]);
  const triageById = useMemo(() => new Map(allThreads.filter((thread) => thread.triage).map((thread) => [thread.threadId, thread.triage!])), [allThreads]);
  const threads = useMemo(() => {
    const order: Record<string, number> = { needs_reply: 0, review: 1, fyi: 2, done: 3, ignore: 4 };
    return allThreads.toSorted((a, b) =>
      (triageById.has(a.threadId) && triageById.has(b.threadId)
        ? (order[triageById.get(a.threadId)!.priority] - order[triageById.get(b.threadId)!.priority])
        : 0) || threadTime(b).at - threadTime(a).at);
  }, [allThreads, triageById]);
  const repliesFor = useCallback((thread: Thread) => mergedReplies(thread, sessionReplies[thread.threadId]), [sessionReplies]);
  const answered = useCallback((thread: Thread) => repliesFor(thread).some(isAnswered), [repliesFor]);
  const reported = replyHistoryReported(threads);
  const triageComplete = data?.engagementEnabled === true && pageCursor === null && (data.nextCursor === null || extraThreads.length > 0);
  const triageCount = (kind: string) => triageComplete ? [...triageById.values()].filter((item) => item.priority === kind).length : null;
  const counts = data ? { ...countsFor(data, threads, reported, answered),
    needs_reply: triageCount('needs_reply'), review: triageCount('review'), fyi: triageCount('fyi') } : null;
  const activeFilter = (TRIAGE_FILTERS.includes(params.filter) && !data?.engagementEnabled) || (params.filter === 'follow_ups' && followUpsOff(followUps)) ? 'all' : params.filter;
  const filtered = threads.filter((thread) => activeFilter === 'all' ? true
    : activeFilter === 'replied' ? answered(thread)
    : activeFilter === 'unanswered' ? !thread.tombstoned && !answered(thread)
    : triageById.get(thread.threadId)?.priority === activeFilter);
  const freshReplyIds = useMemo(() => new Set(Object.values(sessionReplies).flatMap((list) => list.map((reply) => reply.draftId))), [sessionReplies]);

  const selected = params.thread ? (threads.find((thread) => thread.threadId === params.thread) ?? null) : null;
  useEffect(() => {
    if (selected && !twoPane) toast.dismiss('page-tour-inbox-tips');
  }, [selected, twoPane]);
  const missing = Boolean(params.thread && data && !selected);
  // A follow-up whose conversation is not loaded (or that has none) opens on its own.
  const relationshipOnly = activeFilter === 'follow_ups' && params.relationship && !selected ? params.relationship : null;
  if (selected && selected.threadId !== sheetThreadId) setSheetThreadId(selected.threadId);
  if (selected && sheetKind !== 'thread') setSheetKind('thread');
  if (relationshipOnly && relationshipOnly !== sheetRelationshipId) setSheetRelationshipId(relationshipOnly);
  if (relationshipOnly && sheetKind !== 'relationship') setSheetKind('relationship');
  const sheetThread = sheetThreadId ? (threads.find((thread) => thread.threadId === sheetThreadId) ?? null) : null;

  const select = (threadId: string) => void setParams({ thread: threadId, relationship: null });
  const clear = () => void setParams({ thread: null, relationship: null });
  const selectFollowUp = (relationship: Relationship) => void setParams({ relationship: relationship.id, thread: relationship.threadIds[0] ?? null });

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
        channel={channelsById.get(thread.connectionId)?.platform.toLowerCase() === thread.provider.toLowerCase() ? channelsById.get(thread.connectionId) : undefined}
        replies={repliesFor(thread)}
        freshReplyIds={freshReplyIds}
        composer={composers[thread.threadId] ?? EMPTY_COMPOSER}
        onComposerChange={(patch) =>
          setComposers((current) => ({ ...current, [thread.threadId]: { ...(current[thread.threadId] ?? EMPTY_COMPOSER), ...patch } }))
        }
        onApproved={(reply) => setSessionReplies((current) => ({ ...current, [thread.threadId]: [...(current[thread.threadId] ?? []), reply] }))}
        triage={triageById.get(thread.threadId)}
        replySendingEnabled={data?.replySendingEnabled === true}
        canEdit={canEdit}
        canReply={canReply}
      />
    );
  }

  // WHAT: the three reply-state views. Counts the server cannot vouch for are left out, never guessed.
  const filterOptions: SegmentOption<InboxFilter>[] = INBOX_FILTERS.filter(
    (filter) => (!TRIAGE_FILTERS.includes(filter) || data?.engagementEnabled === true) && (filter !== 'follow_ups' || followUpsAvailable)
  ).map((filter) => {
    const count = filter === 'follow_ups' ? (followUps.data?.counts.dueNow ?? null) : (counts?.[filter] ?? null);
    return {
      value: filter,
      label: (
        <>
          {filter === 'follow_ups' ? followUpCopy.tab : FILTER_LABELS[filter]}
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
  } else if (threads.length === 0 && !(followUpsAvailable && ((followUps.data?.counts.open ?? 0) > 0 || activeFilter === 'follow_ups'))) {
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
            {activeFilter === 'follow_ups' ? (
              <FollowUpList selectedId={params.relationship} onSelect={selectFollowUp} canEdit={canEdit} />
            ) : filtered.length > 0 ? (
              <ThreadList threads={filtered} selectedId={params.thread} onSelect={select} channelsById={channelsById} latestReply={latestReply} triageById={triageById} />
            ) : (
              <StateMessage
                kind='empty'
                layout='inline'
                title={
                  activeFilter === 'unanswered' || activeFilter === 'needs_reply'
                    ? 'Nothing waiting for a reply.'
                    : activeFilter === 'review' || activeFilter === 'fyi'
                      ? 'No comments in this category.'
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
          {pageCursor && activeFilter !== 'follow_ups' && <Button variant='quiet' size='sm' disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? 'Loading…' : 'Load more comments'}
          </Button>}
          {pageCursor && data?.engagementEnabled && activeFilter !== 'follow_ups' && <p className='text-muted-foreground text-xs'>Engagement filters cover loaded comments. Load more to see older ones.</p>}
        </section>
        {twoPane && (
          <Surface material='quiet' radius='card' padding='none' className={cn('flex min-w-0 flex-col overflow-y-auto', PANE_HEIGHT)}>
            {selected ? (
              <>
                <div className='rafii-panel sticky top-0 z-10 rounded-t-[var(--rafii-radius-card)] px-5 py-3'>
                  <ThreadHeading thread={selected} channel={channelsById.get(selected.connectionId)?.platform.toLowerCase() === selected.provider.toLowerCase() ? channelsById.get(selected.connectionId) : undefined} />
                </div>
                <div className='px-5 py-4'>{detailFor(selected)}</div>
              </>
            ) : relationshipOnly ? (
              <div className='px-5 py-4'>
                <FollowUpPanel relationshipId={relationshipOnly} canEdit={canEdit} />
              </div>
            ) : activeFilter === 'follow_ups' ? (
              <p className='text-muted-foreground flex h-full min-h-48 items-center justify-center p-6 text-center text-sm'>{followUpCopy.pick}</p>
            ) : (
              <NoThreadSelected missing={missing} onClear={clear} />
            )}
          </Surface>
        )}
      </div>
    );
  }

  const sheetHeadline = sheetThread ? threadHeadline(sheetThread, channelsById.get(sheetThread.connectionId)?.platform.toLowerCase() === sheetThread.provider.toLowerCase() ? channelsById.get(sheetThread.connectionId) : undefined) : null;
  const syncRows = data?.sync ?? [];
  const neverChecked = syncRows.length === 0 || syncRows.some((row) => row.lastSyncAt === null);
  const oldestCheck = syncRows.length > 0 && !neverChecked ? Math.min(...syncRows.map((row) => row.lastSyncAt!)) : null;
  const syncError = syncRows.find((row) => row.errorCode);

  async function checkForComments() {
    setSyncing(true);
    setSyncMessage(null);
    try {
      const result = await api.syncAudience(workspaceId);
      setSyncMessage(result.availability === 'available'
        ? `Checked ${result.checkedPosts ?? 0} posts; ${result.ingested ?? 0} new comments.`
        : result.reason ?? result.connections?.find((row) => row.reason)?.reason ?? 'Comment refresh is unavailable.');
      await audience.refetch();
    } catch (error) {
      setSyncMessage(error instanceof ApiError ? error.message : 'Comment refresh is unavailable.');
    } finally {
      setSyncing(false);
    }
  }

  async function loadMore() {
    if (!pageCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await api.audience(workspaceId, pageCursor);
      setExtraThreads((current) => [...current, ...page.threads.filter((item) => !current.some((known) => known.threadId === item.threadId))]);
      setPageCursor(page.nextCursor ?? null);
    } catch (error) {
      setSyncMessage(error instanceof ApiError ? error.message : 'Could not load older comments.');
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <PageContainer pageTitle='Inbox' infoContent={infoContent}>
      <div className='flex min-w-0 flex-col gap-5'>
        <GrowthEntry audience />
        <div className='flex flex-wrap items-center justify-between gap-2' aria-live='polite'>
          <div className='text-muted-foreground text-sm'>
            {oldestCheck === null ? 'Never checked for new comments' : `Checked ${relativeTime(oldestCheck)}`}
            {syncError && <span> · Provider refresh unavailable ({syncError.errorCode})</span>}
            {typeof data?.counts?.unanswered === 'number' && <span> · {data.counts.unanswered} unanswered</span>}
          </div>
          <Button variant='glass' size='control' disabled={syncing || !data} onClick={() => void checkForComments()}>
            <Icons.refresh className='size-4' aria-hidden />
            {syncing ? 'Checking…' : 'Check for new comments'}
          </Button>
          {syncMessage && <p className='text-muted-foreground w-full text-sm'>{syncMessage}</p>}
        </div>
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
        <Sheet open={Boolean(selected) || Boolean(relationshipOnly)} onOpenChange={(open) => !open && clear()}>
          <SheetContent side='right' showCloseButton={false} className={cn(SHEET_ELEVATED, 'data-[side=right]:w-full data-[side=right]:sm:max-w-lg')}>
            {sheetKind === 'relationship' && sheetRelationshipId && (
              <>
                <SheetHeader className='gap-3 px-4 pt-3 pb-3'>
                  <Button variant='quiet' size='sm' className='-ml-2 h-11 w-fit gap-1 px-2.5 text-sm' onClick={clear}>
                    <Icons.chevronLeft className='size-4' aria-hidden />
                    {followUpCopy.tab}
                  </Button>
                  <SheetTitle>{followUpCopy.section}</SheetTitle>
                  <SheetDescription className='sr-only'>{followUpCopy.remindersNote}</SheetDescription>
                </SheetHeader>
                <div className='min-h-0 flex-1 overflow-y-auto px-4 pt-1 pb-[max(1rem,env(safe-area-inset-bottom))]'>
                  <FollowUpPanel relationshipId={sheetRelationshipId} canEdit={canEdit} />
                </div>
              </>
            )}
            {sheetKind === 'thread' && sheetThread && sheetHeadline && (
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
function countsFor(data: Audience, threads: Thread[], reported: boolean, answered: (thread: Thread) => boolean): Partial<Record<InboxFilter, number | string | null>> {
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
              ? 'Rafii checks comments when a post is verified. Use Check for new comments to refresh later replies.'
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
