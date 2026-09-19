'use client';

import Link from 'next/link';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useAudience, useChannels } from '@/lib/api/hooks';
import type { Audience, ChannelView, ProviderView, Thread } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { channelBadge, isVerified } from '@/lib/channels/state';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { CoverageStrip } from './coverage-strip';
import { InboxLevelBadge } from './level-badge';
import {
  apiCounts,
  COMMENT_READ_NAMES,
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
        `Comments appear only for ${COMMENT_READ_NAMES} accounts whose comments capability is Direct; comments from other providers are not read in this release. Each capability shows its own level and evidence here and on the Channels page.`
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

  let main;
  if (audience.isPending) {
    main = <InboxSkeleton />;
  } else if (!data) {
    main = (
      <Alert variant='destructive'>
        <Icons.alertCircle />
        <AlertTitle>Could not load comments</AlertTitle>
        <AlertDescription>{audience.error instanceof ApiError ? audience.error.message : 'The server did not answer.'}</AlertDescription>
        <AlertAction>
          <Button variant='outline' size='sm' onClick={() => void audience.refetch()}>
            Retry
          </Button>
        </AlertAction>
      </Alert>
    );
  } else if (threads.length === 0) {
    main = <InboxEmpty data={data} channels={channels} providers={providers} channelsPending={channelsQuery.isPending} />;
  } else {
    main = (
      <div className='grid min-w-0 gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]'>
        <section aria-label='Comments' className='flex min-w-0 flex-col gap-3'>
          <div className='-mx-1 overflow-x-auto px-1'>
            <Tabs value={params.filter} onValueChange={(value) => void setParams({ filter: value as InboxFilter })} variant='segment'>
              <TabsList aria-label='Show comments' className='border'>
                {INBOX_FILTERS.map((filter) => {
                  const count = counts?.[filter] ?? null;
                  return (
                    <TabsTrigger key={filter} value={filter} className='gap-1.5 px-3'>
                      {FILTER_LABELS[filter]}
                      {count !== null && <DigitSwap value={count} className='text-xs opacity-75' />}
                    </TabsTrigger>
                  );
                })}
              </TabsList>
            </Tabs>
          </div>
          {!reported && counts?.replied == null && (
            <p className='text-muted-foreground text-xs'>
              The server does not return reply history yet, so Unanswered and Replied only know about replies approved during this visit.
            </p>
          )}
          {audience.isError && (
            <Alert variant='destructive'>
              <Icons.alertCircle />
              <AlertTitle>Could not refresh comments</AlertTitle>
              <AlertDescription>
                {audience.error instanceof ApiError ? audience.error.message : 'The server did not answer.'} The list shows the last comments loaded.
              </AlertDescription>
              <AlertAction>
                <Button variant='outline' size='sm' onClick={() => void audience.refetch()}>
                  Retry
                </Button>
              </AlertAction>
            </Alert>
          )}
          <div data-tour='inbox-threads' className={`min-w-0 lg:overflow-y-auto ${PANE_HEIGHT}`}>
            {filtered.length > 0 ? (
              <ThreadList threads={filtered} selectedId={params.thread} onSelect={select} channelsById={channelsById} latestReply={latestReply} />
            ) : (
              <p className='text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm'>
                {params.filter === 'unanswered'
                  ? 'Nothing waiting for a reply.'
                  : reported
                    ? 'No comment has an approved reply yet.'
                    : 'No reply has been approved during this visit.'}
              </p>
            )}
          </div>
        </section>
        {twoPane && (
          <Card className={`min-w-0 gap-0 overflow-y-auto py-0 ${PANE_HEIGHT}`}>
            {selected ? (
              <>
                <CardHeader className='bg-card sticky top-0 z-10 border-b py-3'>
                  <ThreadHeading thread={selected} channel={channelsById.get(selected.connectionId)} />
                </CardHeader>
                <CardContent className='py-4'>{detailFor(selected)}</CardContent>
              </>
            ) : (
              <NoThreadSelected missing={missing} onClear={clear} />
            )}
          </Card>
        )}
      </div>
    );
  }

  const sheetHeadline = sheetThread ? threadHeadline(sheetThread, channelsById.get(sheetThread.connectionId)) : null;

  return (
    <PageContainer
      pageTitle='Inbox'
      pageDescription={`Comments on posts PostRiff published, from ${COMMENT_READ_NAMES} accounts whose comments capability is Direct. Each reply is approved on its own.`}
      infoContent={infoContent}
    >
      <div className='flex min-w-0 flex-col gap-4'>
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
      {!twoPane && (
        <Sheet open={Boolean(selected)} onOpenChange={(open) => !open && clear()}>
          <SheetContent side='right' className='gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-lg'>
            {sheetThread && sheetHeadline && (
              <>
                <SheetHeader className='border-b pr-12'>
                  <div className='flex min-w-0 items-center gap-2'>
                    <ChannelIcon platform={sheetHeadline.platform} name={sheetHeadline.platform} />
                    <div className='min-w-0'>
                      <SheetTitle className='truncate'>{sheetHeadline.title}</SheetTitle>
                      <SheetDescription className='truncate text-xs'>{sheetHeadline.meta}</SheetDescription>
                    </div>
                  </div>
                </SheetHeader>
                <div className='min-h-0 flex-1 overflow-y-auto p-4'>{detailFor(sheetThread)}</div>
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

function InboxSkeleton() {
  return (
    <div className='grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[360px_minmax(0,1fr)]'>
      <div className='flex flex-col gap-2'>
        <Skeleton className='h-9 w-64 max-w-full' />
        <Skeleton className='h-16 w-full' />
        <Skeleton className='h-16 w-full' />
        <Skeleton className='h-16 w-full' />
      </div>
      <Skeleton className='hidden h-48 w-full lg:block' />
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
  let accounts;
  if (channelsPending) {
    accounts = (
      <div className='flex w-full flex-col gap-2'>
        <Skeleton className='h-14 w-full' />
        <Skeleton className='h-14 w-full' />
      </div>
    );
  } else if (!channels) {
    accounts = <p className='text-muted-foreground text-sm'>Account details are unavailable right now; retry above.</p>;
  } else if (channels.length === 0) {
    accounts = (
      <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        Connect an account
      </Link>
    );
  } else {
    accounts = (
      <ul className='flex w-full flex-col gap-2 text-left'>
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
            sentence = `Comments are Direct for ${channel.account}, but PostRiff reads only ${COMMENT_READ_NAMES} comments in this release, so none from ${channel.platform} appear here.`;
          }
          return (
            <li key={channel.id} className='bg-muted/40 flex flex-col gap-1.5 rounded-lg border p-3'>
              <div className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium'>
                <ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />
                <span className='truncate'>{channel.account}</span>
                <span className='text-muted-foreground text-xs font-normal'>{channel.platform}</span>
                {badge && <span className='text-muted-foreground text-xs font-normal'>· {badge.label}</span>}
              </div>
              <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
                <span className='flex items-center gap-1'>
                  Comments <InboxLevelBadge level={commentsLevel} />
                </span>
                <span className='flex items-center gap-1'>
                  Reply <InboxLevelBadge level={replyLevel} />
                </span>
              </div>
              <p className='text-muted-foreground text-xs'>{sentence}</p>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <Empty className='border' data-tour='inbox-empty'>
      <EmptyHeader>
        <EmptyMedia variant='icon'>
          <Icons.inbox />
        </EmptyMedia>
        <EmptyTitle>No comments yet</EmptyTitle>
        <EmptyDescription>
          {channels && channels.length === 0
            ? `Connect a ${COMMENT_READ_NAMES} account with Direct comments to read the comments on posts PostRiff publishes there.`
            : `Comments appear for ${COMMENT_READ_NAMES} accounts whose comments capability is Direct, after PostRiff publishes and verifies a post there. Comments from other providers are not read in this release.`}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent className='max-w-xl'>
        {accounts}
        <p className='text-muted-foreground text-xs'>{data.limits}</p>
      </EmptyContent>
    </Empty>
  );
}
