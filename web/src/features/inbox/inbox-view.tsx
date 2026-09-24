'use client';

import Link from 'next/link';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { SegmentedControl, StateMessage, Surface, type SegmentOption } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { SHEET_ELEVATED } from '@/features/channels/rafii-materials';
import { ApiError } from '@/lib/api/client';
import { useAudience, useChannels } from '@/lib/api/hooks';
import type { Audience, ChannelView, ProviderView, Thread } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { channelBadge, isVerified } from '@/lib/channels/state';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { ConnectionNote, CoverageStrip } from './coverage-strip';
import { InboxLevelBadge } from './level-badge';
import {
  apiCounts,
  commentReadNames,
  commentsReadFor,
  evidenceSentence,
  INBOX_FILTERS,
  isAnswered,
  mergedReplies,
  providerFor,
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
  title: 'Real replies, one at a time',
  sections: [
    { title: 'Original thread first', description: 'You always see the comment in context before writing.' },
    {
      title: 'Labelled suggestions',
      description:
        'A suggestion says what produced it (an AI model or a plain starter line) and is never sent on its own. You edit, then approve the exact account, thread and text.'
    },
    { title: 'No bulk, no auto-reply', description: 'Each reply is an individual approval.' },
    {
      title: 'Which accounts feed this inbox',
      description:
        'Comments appear for accounts whose provider supports comment ingestion and whose comments capability is Direct. Each capability shows its own level and evidence here and on the Channels page.'
    }
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
        title='Could not load comments'
        description={audience.error instanceof ApiError ? audience.error.message : 'The server did not answer.'}
        action={
          <Button variant='glass' size='control' onClick={() => void audience.refetch()}>
            <Icons.refresh className='size-4' />
            Retry
          </Button>
        }
      />
    );
  } else if (threads.length === 0) {
    main = <InboxEmpty data={data} channels={channels} providers={providers} channelsPending={channelsQuery.isPending} />;
  } else {
    main = (
      <div className={PANES}>
        <section aria-label='Comments' className='flex min-w-0 flex-col gap-3'>
          <div className='relative -mx-1 overflow-x-auto px-1 py-0.5'>
            <SegmentedControl options={filterOptions} value={params.filter} onChange={(value) => void setParams({ filter: value })} label='Show comments' widths='content' />
          </div>
          {!reported && counts?.replied == null && (
            <p className='text-muted-foreground text-xs leading-relaxed'>
              The server does not return reply history yet, so Unanswered and Replied only know about replies approved during this visit.
            </p>
          )}
          {audience.isError && (
            <StateMessage
              kind='stale'
              layout='inline'
              title='Could not refresh comments'
              description={`${audience.error instanceof ApiError ? audience.error.message : 'The server did not answer.'} The list shows the last comments loaded.`}
              action={
                <Button variant='glass' size='sm' className='h-9' onClick={() => void audience.refetch()}>
                  Retry
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
                      ? 'No comment has an approved reply yet.'
                      : 'No reply has been approved during this visit.'
                }
                description='The other comments are still here; this view is only filtered.'
                action={
                  <Button variant='quiet' size='sm' className='h-9' onClick={() => void setParams({ filter: 'all' })}>
                    Show all comments
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
    <PageContainer
      pageEyebrow='Conversations'
      pageTitle='Inbox'
      pageAccent='one reply at a time'
      pageDescription={`Comments on posts PostRiff published, from ${commentReadNames(providers)} accounts whose comments capability is Direct. Each reply is approved on its own.`}
      infoContent={infoContent}
    >
      <div className='flex min-w-0 flex-col gap-5'>
        <CoverageStrip
          channels={channels}
          providers={providers}
          isPending={channelsQuery.isPending}
          error={channelsQuery.error}
          onRetry={() => void channelsQuery.refetch()}
        />
        {main}
        {data && threads.length > 0 && <p className='text-muted-foreground text-xs'>{data.limits}</p>}
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

/** Per account, why no comment is here yet: the account, its comments and reply levels, and the evidence. */
function InboxEmpty({
  data,
  channels,
  providers,
  channelsPending
}: {
  data: Audience;
  channels: ChannelView[] | undefined;
  providers: ProviderView[] | undefined;
  channelsPending: boolean;
}) {
  let accounts: ReactNode = null;
  if (channelsPending) {
    accounts = <StateMessage kind='loading' layout='inline' title='Loading accounts…' />;
  } else if (!channels) {
    accounts = <StateMessage kind='partial' layout='inline' title='Account details are unavailable right now.' description='Retry above to load them.' />;
  } else if (channels.length > 0) {
    accounts = (
      <ul className='flex w-full flex-col gap-2 text-left' aria-label='Connected accounts and their comment coverage'>
        {channels.map((channel) => {
          const comments = channel.capabilities.comments_read;
          const reply = channel.capabilities.reply;
          const commentsLevel = comments?.level ?? 'Unsupported';
          const replyLevel = reply?.level ?? 'Unsupported';
          const provider = providerFor(channel.platform, providers);
          const badge = isVerified(channel) ? null : channelBadge(channel);
          let sentence;
          if (commentsLevel !== 'Direct') {
            sentence = `Comments are ${commentsLevel} for ${channel.account}, so PostRiff does not read its comments. ${evidenceSentence(comments, provider?.capabilities.comments_read, channel.platform)}`;
          } else if (commentsReadFor(channel.platform, providers)) {
            sentence = `Comments show up here after PostRiff publishes and verifies a post on ${channel.account}.`;
          } else {
            // A Direct level is not enough: the server reads comments for only some providers.
            sentence = `Comments are Direct for ${channel.account}, but PostRiff reads only ${commentReadNames(providers)} comments in this release, so none from ${channel.platform} appear here.`;
          }
          return (
            <Surface as='li' key={channel.id} material='quiet' radius='control' padding='sm' className='flex flex-col gap-1.5'>
              <div className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium'>
                <ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />
                <span className='truncate'>{channel.account}</span>
                <span className='text-muted-foreground text-xs font-normal'>{channel.platform}</span>
                {badge && <ConnectionNote badge={badge} />}
              </div>
              <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
                <span className='flex items-center gap-1'>
                  Comments <InboxLevelBadge level={commentsLevel} />
                </span>
                <span className='flex items-center gap-1'>
                  Reply <InboxLevelBadge level={replyLevel} />
                </span>
              </div>
              <p className='text-muted-foreground text-xs leading-relaxed'>{sentence}</p>
            </Surface>
          );
        })}
      </ul>
    );
  }

  return (
    <div className='flex flex-col gap-4' data-tour='inbox-empty'>
      <StateMessage
        kind='empty'
        title='No comments yet'
        description={
          channels && channels.length === 0
            ? `Connect a ${commentReadNames(providers)} account with Direct comments to read the comments on posts PostRiff publishes there.`
            : `Comments appear for ${commentReadNames(providers)} accounts whose comments capability is Direct, after PostRiff publishes and verifies a post there. Comments from other providers are not read in this release.`
        }
        media={
          <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
            <Icons.inbox className='size-5' />
          </span>
        }
        action={
          channels && channels.length === 0 ? (
            <Link href='/app/channels' className={buttonVariants({ variant: 'action', size: 'control' })}>
              Connect an account
            </Link>
          ) : undefined
        }
      />
      {accounts}
      <p className='text-muted-foreground text-xs'>{data.limits}</p>
    </div>
  );
}
