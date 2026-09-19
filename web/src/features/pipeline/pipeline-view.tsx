'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { NotificationStack } from '@/components/motion/notification-stack';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Button, buttonVariants } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { ScheduleDialog } from '@/features/queue/schedule-dialog';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import { keys, useAct, useChannels, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { relativeTime } from '@/lib/time';
import { useWorkspace } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { boardInvariants, COLUMN_META, COLUMN_ORDER, deriveBoard, type Board, type BoardCard, type BoardColumn, type ColumnKey, type PipelineJob } from './board';
import { DetailSheet } from './detail-sheet';
import { EditDraftDialog } from './edit-draft-dialog';
import { deriveNeedsYou, type NeedsYouItem } from './needs-you';
import { PipelineCard, type CardActions, type CardPermissions } from './pipeline-card';
import { SetAsideDialog } from './set-aside-dialog';

const infoContent = {
  title: 'Pipeline',
  sections: [
    {
      title: 'Left to right',
      description: 'Sources become drafts; a draft is prepared as an exact review of text, account and time; an approved review waits in the queue; the worker publishes; the provider confirms.'
    },
    {
      title: 'Why no dragging',
      description: 'Every move right is an explicit decision with a receipt (a review, an approval, a provider confirmation). The board shows state; the actions sit on each card and in its details.'
    },
    {
      title: 'Badges',
      description:
        'Waiting: approved, not yet due. Publishing: handed to the provider. Uncertain: the provider did not confirm, and nothing is retried until it is reconciled. Held: approval, capability or entitlement changed after approval; cancel it and prepare a new review. Verified: the provider confirmed the post. Fixture: a synthetic provider, not a real post.'
    },
    {
      title: 'Nothing disappears',
      description:
        'Set-aside drafts stay under Drafts, reviews past their approval deadline stay under Needs approval as Expired (their drafts come back to Drafts), and cancelled or failed jobs stay under the Queue with their receipts. The workspace keeps the 20 most recent reviews.'
    },
    {
      title: 'Who can do what',
      description:
        'People who can edit may edit drafts and set them aside. People who can approve may cancel a waiting or held job and approve reviews in the Queue. Schedule… needs approve, and edit as well when the draft has a proposed update or unknown details to confirm first. Everyone else sees the same board, read-only; a sample workspace is read-only for everyone.'
    }
  ]
};

/** Short column names for the phone's segment control. */
const SHORT_TITLE: Record<ColumnKey, string> = { sources: 'Sources', drafts: 'Drafts', review: 'Approval', queue: 'Queue', published: 'Published' };

/** Past this many cards a column asks before it renders more. */
const COLUMN_LIMIT = 40;

/** How often the board re-reads the snapshot while something is in flight or due (the worker runs every minute). */
const LIVE_REFRESH_MS = 15_000;

/** First-render entrance: 30ms apart, capped at the fifth card, so the last card settles within 300ms. */
const ENTER_DURATION = 0.18;
const ENTER_STAGGER = 0.03;
const ENTER_CAP = 4;
/** Closes faster than it opens. */
const EXIT_DURATION = 0.15;

const ALL = '__all';

/**
 * Re-reads the snapshot only while the board says something is moving (a job being published or due within
 * two minutes), and wakes the page when a waiting job enters that window or a review reaches its approval
 * deadline. Local to this page: the shared `useSnapshot` hook stays without a polling interval.
 */
function useLiveRefresh(board: Board, now: number, setNow: (now: number) => void) {
  const client = useQueryClient();
  const { workspaceId } = useWorkspace();
  const { live, wakeAt } = board;

  useEffect(() => {
    if (!live || !workspaceId) return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'hidden') return;
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    }, LIVE_REFRESH_MS);
    return () => clearInterval(timer);
  }, [client, live, workspaceId]);

  useEffect(() => {
    if (live || wakeAt === null) return;
    // setTimeout overflows past about 24.8 days. A timer that fires before `wakeAt` (capped, or early by a few
    // milliseconds) still moves `now`, and this effect re-arms for the same `wakeAt`; the board always puts `wakeAt`
    // after `now`, so it never spins.
    const delay = Math.min(Math.max(0, wakeAt * 1000 - Date.now()), 2_000_000_000);
    const timer = setTimeout(() => setNow(Date.now() / 1000), delay);
    return () => clearTimeout(timer);
  }, [live, wakeAt, now, setNow]);
}

function ColumnHeader({ column, count }: { column: Pick<BoardColumn, 'key' | 'title' | 'hint'>; count: number | null }) {
  return (
    <header className='px-3 pt-2 pb-1'>
      <h3 id={`pipeline-col-${column.key}-title`} className='flex items-center gap-1.5 text-sm font-semibold'>
        {column.title}
        {count !== null && <DigitSwap value={count} className='text-muted-foreground font-normal' />}
      </h3>
      <p className='text-muted-foreground text-xs'>{column.hint}</p>
    </header>
  );
}

interface ColumnViewProps {
  column: BoardColumn;
  platform: string | null;
  now: number;
  permissions: CardPermissions;
  actions: CardActions;
  cancelPending: boolean;
  holdEpoch: number;
  lift: boolean;
  menu: boolean;
  /** On a phone the column is the page: no inner scroll and no fixed width. */
  single: boolean;
}

function ColumnView({ column, platform, now, permissions, actions, cancelPending, holdEpoch, lift, menu, single }: ColumnViewProps) {
  const reduce = useReducedMotion();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? column.items : column.items.slice(0, COLUMN_LIMIT);
  const hidden = column.items.length - visible.length;
  const footer = column.footer;
  const emptySentence = platform && column.key !== 'sources' ? `No ${platform} items in this column.` : column.empty;

  const renderCards = (cards: BoardCard[]) => (
    <AnimatePresence mode='popLayout'>
      {cards.map((card, index) => (
        // Entrance and glide on the wrapper, lift on the card: sharing one element, the entrance delay would
        // also hold the card up after the pointer leaves.
        <motion.div
          key={card.key}
          layoutId={reduce ? undefined : card.key}
          layout={reduce ? false : 'position'}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0, transition: { duration: ENTER_DURATION, ease: EASE_OUT, delay: Math.min(index, ENTER_CAP) * ENTER_STAGGER } }}
          exit={{ opacity: 0, transition: { duration: EXIT_DURATION, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
        >
          <PipelineCard card={card} now={now} permissions={permissions} actions={actions} cancelPending={cancelPending} holdEpoch={holdEpoch} lift={lift} menu={menu} />
        </motion.div>
      ))}
    </AnimatePresence>
  );

  return (
    <section
      id={`pipeline-col-${column.key}`}
      data-tour={`pipeline-col-${column.key}`}
      aria-labelledby={`pipeline-col-${column.key}-title`}
      className={cn('bg-muted/40 flex flex-col rounded-xl border', single ? 'w-full' : 'w-72 shrink-0 snap-start min-[1440px]:w-auto min-[1440px]:min-w-0')}
    >
      <ColumnHeader column={column} count={column.items.length} />
      <motion.div
        layoutScroll
        className={cn('relative flex flex-col gap-2 px-2 pb-2', !single && 'max-h-[calc(100dvh-14rem)] min-h-24 overflow-y-auto')}
      >
        {renderCards(visible)}
        {column.items.length === 0 && <p className='text-muted-foreground px-2 py-3 text-center text-xs text-balance'>{emptySentence}</p>}
        {hidden > 0 && (
          <Button variant='outline' size='sm' onClick={() => setShowAll(true)}>
            Show {hidden} more
          </Button>
        )}
        {footer && footer.items.length > 0 && (
          <Collapsible className='rounded-lg border border-dashed'>
            <CollapsibleTrigger className='group/footer hover:bg-muted/60 flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring/50'>
              <span className='flex items-center gap-1'>
                {footer.label} · <DigitSwap value={footer.items.length} />
              </span>
              <Icons.chevronDown
                aria-hidden
                className='text-muted-foreground size-4 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/footer:rotate-180 motion-reduce:transition-none'
              />
            </CollapsibleTrigger>
            <CollapsibleContent className='t-nav-panel'>
              <div className='flex flex-col gap-2 px-1.5 pb-1.5'>
                <p className='text-muted-foreground px-1 text-[11px]'>
                  {column.key === 'drafts'
                    ? 'Kept, not scheduled. Edit a draft to bring it back.'
                    : column.key === 'review'
                      ? 'Past the approval deadline, so they can no longer be approved. Their drafts are back in Drafts to schedule again.'
                      : 'Ended before or during publishing. The receipts stay here; nothing is retried.'}
                </p>
                {renderCards(footer.items)}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
        <Link href={column.href} className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), 'justify-start')}>
          {column.cta} <LearnMoreChevron />
        </Link>
      </motion.div>
    </section>
  );
}

function BoardSkeleton({ single }: { single: boolean }) {
  if (single) {
    return (
      <div className='flex flex-col gap-3' aria-busy='true'>
        <Skeleton className='h-9 w-full rounded-lg' />
        <div className='bg-muted/40 flex flex-col gap-2 rounded-xl border p-2'>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className='h-28 w-full rounded-lg' />
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className='flex gap-4 overflow-hidden pb-2 min-[1440px]:grid min-[1440px]:grid-cols-5' aria-busy='true'>
      {COLUMN_ORDER.map((key) => (
        <section key={key} aria-labelledby={`pipeline-col-${key}-title`} className='bg-muted/40 flex w-72 shrink-0 flex-col rounded-xl border min-[1440px]:w-auto min-[1440px]:min-w-0'>
          {/* Real titles; the count stays blank until the snapshot says what it is. */}
          <ColumnHeader column={COLUMN_META[key]} count={null} />
          <div className='flex flex-col gap-2 px-2 pb-2'>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className='h-24 w-full rounded-lg' />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function PipelineView() {
  const snapshot = useSnapshot();
  const act = useAct();
  const router = useRouter();
  const access = useWorkspaceAccess();
  const isMobile = useIsMobile();
  const reduce = useReducedMotion();
  // The lift is a hover affordance: a touch device would keep a tapped card raised.
  const hoverCapable = useHoverCapable();
  const lift = hoverCapable && !reduce;
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });

  const channels = useChannels();
  const state = snapshot.data?.state;
  const readOnly = Boolean(state?.workspace?.sample);
  const permissions = useMemo<CardPermissions>(() => ({ canEdit, canApprove, readOnly }), [canEdit, canApprove, readOnly]);

  const [now, setNow] = useState(() => Date.now() / 1000);
  // Every snapshot that arrives re-reads the clock, so "expired" and "due within two minutes" stay true to it.
  useEffect(() => setNow(Date.now() / 1000), [snapshot.dataUpdatedAt]);

  const [platform, setPlatform] = useState<string | null>(null);
  const [mobileColumn, setMobileColumn] = useState<ColumnKey | null>(null);
  const [opened, setOpened] = useState<BoardCard | null>(null);
  const [scheduling, setScheduling] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [settingAside, setSettingAside] = useState<string | null>(null);
  // A hold button goes disabled mid-press while its cancel is pending, so its release can go unheard. After a failed
  // cancel the buttons remount instead of staying stuck on "Cancelling…"; a successful one takes the button away.
  const [holdEpoch, setHoldEpoch] = useState(0);

  const fullBoard = useMemo(() => deriveBoard(state, null, now), [state, now]);
  const activePlatform = platform !== null && fullBoard.platforms.some((p) => p.platform === platform) ? platform : null;
  const board = useMemo(() => (activePlatform ? deriveBoard(state, activePlatform, now) : fullBoard), [activePlatform, fullBoard, now, state]);
  const needsYou = useMemo(() => deriveNeedsYou(fullBoard, { canApprove: canApprove && !readOnly, channels: channels.data?.channels }), [fullBoard, canApprove, readOnly, channels.data]);

  // No test runner in web/ yet: in development the board checks its own promises on every snapshot.
  useEffect(() => {
    if (process.env.NODE_ENV === 'production' || !state) return;
    const problems = boardInvariants(state, fullBoard, now);
    if (problems.length > 0) console.warn('[pipeline] board invariants failed', problems);
  }, [state, fullBoard, now]);

  useLiveRefresh(fullBoard, now, setNow);

  const firstNeedsColumn = needsYou.map((item) => ('column' in item.target ? item.target.column : null)).find((column) => column !== null) ?? null;
  const mobileKey: ColumnKey = mobileColumn ?? firstNeedsColumn ?? 'drafts';

  const revision = snapshot.data?.revision ?? 0;
  const client = useQueryClient();
  const { workspaceId } = useWorkspace();

  // Focus goes back to the card that opened the sheet; if it re-rendered or moved, to that card's new copy.
  const opener = useRef<{ element: HTMLElement | null; key: string } | null>(null);
  const returnFocus = useCallback(() => {
    const from = opener.current;
    if (!from) return null;
    if (from.element?.isConnected) return from.element;
    return document.querySelector<HTMLElement>(`[data-card-key="${CSS.escape(from.key)}"] [data-card-open]`);
  }, []);

  const actions: CardActions = {
    open: (card) => {
      const active = document.activeElement;
      opener.current = { element: active instanceof HTMLElement && active !== document.body ? active : null, key: card.key };
      setOpened(card);
    },
    // A dialog replaces the sheet instead of stacking two modal layers.
    edit: (variantId) => {
      setOpened(null);
      setEditing(variantId);
    },
    schedule: (variantId) => {
      setOpened(null);
      setScheduling(variantId);
    },
    setAside: (variantId) => {
      setOpened(null);
      setSettingAside(variantId);
    },
    cancel: (job: PipelineJob) => {
      act.mutate(
        { revision, action: 'p2_cancel', payload: { jobId: job.id } },
        {
          onSuccess: () => toast.success('Cancel requested.'),
          onError: (err) => {
            toast.error(err instanceof ApiError ? err.message : 'Could not cancel.');
            setHoldEpoch((epoch) => epoch + 1);
            // "Workspace changed; reload.": read it again so the card shows the job as it is now.
            if (err instanceof ApiError && err.status === 409 && workspaceId) void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
          }
        }
      );
    }
  };

  function goTo(item: NeedsYouItem) {
    if ('href' in item.target) {
      router.push(item.target.href);
      return;
    }
    const column = item.target.column;
    if (isMobile) {
      setMobileColumn(column);
      document.getElementById('pipeline-board')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      return;
    }
    document.getElementById(`pipeline-col-${column}`)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest', inline: 'start' });
  }

  // The empty board's own "Draft a post" sits right under the title, so the header carries no second copy.
  const canDraft = canEdit && !readOnly;

  const columnProps = { platform: activePlatform, now, permissions, actions, cancelPending: act.isPending, holdEpoch, lift, menu: hoverCapable };

  return (
    <PageContainer pageTitle='Pipeline' pageDescription='Where every draft is, and what it is waiting for.' infoContent={infoContent}>
      {scheduling !== null && <ScheduleDialog key={scheduling} open onOpenChange={(open) => !open && setScheduling(null)} variantId={scheduling} />}
      {editing !== null && <EditDraftDialog key={editing} open onOpenChange={(open) => !open && setEditing(null)} variantId={editing} />}
      {settingAside !== null && <SetAsideDialog key={settingAside} open onOpenChange={(open) => !open && setSettingAside(null)} variantId={settingAside} />}
      <DetailSheet
        opened={opened}
        board={fullBoard}
        state={state}
        now={now}
        permissions={permissions}
        actions={actions}
        cancelPending={act.isPending}
        holdEpoch={holdEpoch}
        onShow={setOpened}
        onClose={() => setOpened(null)}
        returnFocus={returnFocus}
      />

      {!snapshot.data ? (
        snapshot.isError ? (
          <Empty className='flex-none border'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <Icons.refresh />
              </EmptyMedia>
              <EmptyTitle>The board could not load</EmptyTitle>
              <EmptyDescription>{snapshot.error instanceof ApiError ? snapshot.error.message : 'The workspace snapshot did not arrive.'}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button onClick={() => void snapshot.refetch()} disabled={snapshot.isFetching}>
                Try again
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <BoardSkeleton single={isMobile} />
        )
      ) : (
        <div className='flex min-w-0 flex-col gap-4'>
          {snapshot.isError && (
            <p className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs' role='status'>
              <Icons.alertCircle className='size-3.5 text-amber-600 dark:text-amber-400' aria-hidden />
              The latest refresh failed. Last updated {relativeTime(snapshot.dataUpdatedAt / 1000)}.
              <Button variant='link' size='xs' className='h-auto p-0' onClick={() => void snapshot.refetch()} disabled={snapshot.isFetching}>
                Try again
              </Button>
            </p>
          )}
          {channels.isError && (
            <p className='text-muted-foreground flex items-center gap-2 text-xs' role='status'>
              <Icons.broadcast className='size-3.5' aria-hidden />
              Channel capabilities unavailable, so channels that cannot publish directly are not listed.
            </p>
          )}
          {readOnly && (
            <p className='text-muted-foreground flex items-center gap-2 text-xs' role='note'>
              <Icons.lock className='size-3.5' aria-hidden />
              This is a sample workspace, so the board is read-only.
            </p>
          )}

          {fullBoard.empty && (
            <Empty className='flex-none border'>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.kanban />
                </EmptyMedia>
                <EmptyTitle>Nothing on the board yet</EmptyTitle>
                <EmptyDescription>
                  Sources become drafts. A draft becomes an exact review of text, account and time. An approved review becomes a job, and the provider confirms it. Start with one sentence.
                </EmptyDescription>
              </EmptyHeader>
              {!canDraft && <p className='text-muted-foreground text-sm'>{readOnly ? 'A sample workspace is read-only.' : 'An editor in this workspace adds drafts.'}</p>}
              {canDraft && (
                <EmptyContent className='flex-row flex-wrap justify-center'>
                  {/* Creating starts in the Home composer; sources live in Ideas. */}
                  <Link href='/app' className={buttonVariants()}>
                    Draft a post
                  </Link>
                  <Link href='/app/ideas' className={buttonVariants({ variant: 'outline' })}>
                    Add a source
                  </Link>
                </EmptyContent>
              )}
            </Empty>
          )}

          {(needsYou.length > 0 || fullBoard.platforms.length > 1) && (
            <div className='flex flex-col gap-3 md:flex-row md:items-end md:justify-between'>
              {needsYou.length > 0 ? (
                // The collapsed stack draws its peeking cards a little above its own box; the top padding keeps them off the page description.
                <div data-tour='pipeline-needs-you' className='w-full max-w-[22rem] pt-4'>
                  {/* The stack is one button labelled by its count, so the items themselves are listed for screen readers here. */}
                  <ul className='sr-only'>
                    {needsYou.map((item) => (
                      <li key={item.id}>
                        {item.title}. {item.description}
                      </li>
                    ))}
                  </ul>
                  <NotificationStack
                    items={needsYou.map((item) => {
                      const Icon = Icons[item.icon];
                      return {
                        id: item.id,
                        title: (
                          <span className='inline-flex items-center gap-1.5'>
                            <Icon className='text-muted-foreground size-3.5 shrink-0' aria-hidden />
                            {item.title}
                          </span>
                        ),
                        description: item.description
                      };
                    })}
                    collapsedLabel='Needs you'
                    expandedLabel={needsYou[0].action}
                    onViewAll={() => goTo(needsYou[0])}
                    classNames={{ content: 'py-3', count: 'bg-primary text-primary-foreground dark:bg-primary' }}
                  />
                </div>
              ) : (
                <span />
              )}
              {fullBoard.platforms.length > 1 && (
                // The counts widen the tabs: on a narrow screen the list scrolls sideways instead of pushing the page wider.
                <Tabs value={activePlatform ?? ALL} onValueChange={(value) => setPlatform(value === ALL ? null : value)} variant='pill' className='max-w-full min-w-0'>
                  <TabsList aria-label='Filter by platform' className='scrollbar-hide relative max-w-full overflow-x-auto border'>
                    <TabsTrigger value={ALL} className='gap-1.5 px-3 py-1' title='Drafts, reviews and jobs on every platform'>
                      All
                      <DigitSwap value={fullBoard.platformTotal} className='text-xs opacity-75' />
                    </TabsTrigger>
                    {fullBoard.platforms.map((entry) => (
                      <TabsTrigger key={entry.platform} value={entry.platform} className='gap-1.5 px-3 py-1' title={`${entry.platform} drafts, reviews and jobs`}>
                        <ChannelIcon platform={entry.platform} name={entry.platform} size='xs' />
                        {entry.platform}
                        <DigitSwap value={entry.count} className='text-xs opacity-75' />
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              )}
            </div>
          )}

          {isMobile ? (
            <div id='pipeline-board' className='flex min-w-0 scroll-mt-4 flex-col gap-3'>
              <Tabs value={mobileKey} onValueChange={(value) => setMobileColumn(value as ColumnKey)} variant='segment' className='max-w-full min-w-0'>
                <TabsList aria-label='Board column' data-tour='pipeline-board' className='scrollbar-hide relative flex w-full max-w-full overflow-x-auto border'>
                  {board.columns.map((column) => (
                    <TabsTrigger key={column.key} value={column.key} className='w-full gap-1 px-1 py-1.5 text-xs' wrapperClassName='flex-1'>
                      {SHORT_TITLE[column.key]}
                      <DigitSwap value={column.items.length} className='opacity-75' />
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
              {board.columns
                .filter((column) => column.key === mobileKey)
                .map((column) => (
                  <ColumnView key={`${column.key}-${activePlatform ?? ALL}`} column={column} single {...columnProps} />
                ))}
            </div>
          ) : (
            <motion.div
              layoutScroll
              id='pipeline-board'
              data-tour='pipeline-board'
              // `relative` makes the scroller the containing block for absolutely positioned descendants (the counts'
              // screen-reader text), which would otherwise escape it and widen the page.
              className='relative flex min-w-0 snap-x snap-mandatory gap-4 overflow-x-auto pb-2 min-[1440px]:grid min-[1440px]:snap-none min-[1440px]:grid-cols-5 min-[1440px]:overflow-x-visible'
            >
              {board.columns.map((column) => (
                <ColumnView key={`${column.key}-${activePlatform ?? ALL}`} column={column} single={false} {...columnProps} />
              ))}
            </motion.div>
          )}
        </div>
      )}
    </PageContainer>
  );
}
