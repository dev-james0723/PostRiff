'use client';

import { motion, useReducedMotion } from 'motion/react';
import Link from 'next/link';
import {
  type FocusEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState
} from 'react';
import { Icons } from '@/components/icons';
import { DynamicIsland, DynamicIslandView } from '@/components/motion/dynamic-island';
import { useSnapshot } from '@/lib/api/hooks';
import type { Phase2State } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { useDismiss } from '@/lib/hooks/use-dismiss';
import { cn } from '@/lib/utils';

/** Job states grouped the way the Queue and Calendar group them. */
const PUBLISHING = new Set(['submitting', 'provider_accepted', 'published', 'uncertain']);
const WAITING = new Set(['scheduled', 'approved', 'claimed']);
const DONE = new Set(['published', 'verified']);

const MINUTE = 60_000;
const DAY = 86_400_000;
/** How often the countdown to the next post is recomputed while there is one. */
const TICK_MS = 30_000;
/** How long "Published on …" stays up before the island returns to what it showed. */
const EVENT_MS = 4_000;
/** Hover intent: a pointer crossing the header does not pop the panel, a corner slip does not drop it. */
const OPEN_DELAY_MS = 90;
const CLOSE_DELAY_MS = 150;
/** A click this soon after hover opened the panel was aimed at the pill, so it must not close it. */
const CLICK_GRACE_MS = 450;
/** A blur this soon after a press inside the island came from that press, not from leaving. */
const PRESS_BLUR_MS = 300;

type Tone = 'publishing' | 'approvals' | 'failed' | 'next' | 'quiet' | 'published';

interface NextPost {
  platform: string;
  account: string;
  at: number;
}

interface Status {
  approvals: number;
  publishing: number;
  failed: number;
  next: NextPost | null;
}

interface Published {
  platform: string;
  others: number;
}

const DOT: Record<'approvals' | 'failed' | 'next' | 'quiet', string> = {
  approvals: 'bg-amber-500',
  failed: 'bg-red-500',
  next: 'bg-emerald-500',
  quiet: 'bg-background/40'
};

const ROW = 'flex min-h-9 w-full items-center gap-2.5 rounded-3xl px-3 py-1.5 text-left text-xs';
// The island is `bg-foreground text-background`, so hover and focus use the inverted tokens.
const ROW_ACTION = cn(
  ROW,
  'outline-none transition-colors hover:bg-background/10 focus-visible:bg-background/10 focus-visible:ring-2 focus-visible:ring-background/70 focus-visible:ring-inset'
);

const shortTime = new Intl.DateTimeFormat('en', {
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23'
});
const shortDate = new Intl.DateTimeFormat('en', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23'
});
const spokenTime = new Intl.DateTimeFormat('en', {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit'
});

/** Counts straight from the snapshot: open reviews, jobs in flight, recent failures, the next approved slot. */
function readStatus(phase2: Phase2State | undefined, now: number): Status {
  let publishing = 0;
  let failed = 0;
  let next: NextPost | null = null;
  for (const job of phase2?.jobs ?? []) {
    if (PUBLISHING.has(job.state)) {
      publishing += 1;
    } else if (job.state === 'failed') {
      const last = job.events?.at(-1)?.at;
      if (last !== undefined && last * 1000 >= now - DAY) failed += 1;
    } else if (WAITING.has(job.state)) {
      // The header renders on every page, so a job without timing is skipped rather than trusted.
      const at = Date.parse(job.manifest?.timing?.utc ?? '');
      if (at > now && (next === null || at < next.at)) {
        next = { platform: job.manifest.platform, account: job.manifest.account, at };
      }
    }
  }
  const approvals = (phase2?.reviews ?? []).filter(
    (review) => review.status === 'needs_review'
  ).length;
  return { approvals, publishing, failed, next };
}

function toneOf(status: Status): Tone {
  if (status.publishing > 0) return 'publishing';
  if (status.approvals > 0) return 'approvals';
  if (status.failed > 0) return 'failed';
  if (status.next) return 'next';
  return 'quiet';
}

/** "in 4 min", "in 2h 13m", "in 3d 5h". */
function countdown(ms: number) {
  const minutes = Math.floor(ms / MINUTE);
  if (minutes < 1) return 'in <1 min';
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `in ${hours}h ${minutes % 60}m` : `in ${hours}h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `in ${days}d ${hours % 24}h` : `in ${days}d`;
}

/** "Thu 14:30" inside the coming week; the date joins once a weekday alone would be ambiguous. */
function slot(at: number, now: number) {
  return (at - now < 6 * DAY ? shortTime : shortDate).format(at);
}

function publishedOn({ platform, others }: Published) {
  return others > 0 ? `${platform} +${others} more` : platform;
}

/**
 * The accessible name of the island's toggle. It carries the whole state, but no countdown: a
 * name that changed every 30 seconds would be re-announced inside the island's live region.
 */
function describe(status: Status, published: Published | null) {
  const parts: string[] = [];
  if (published) parts.push(`published on ${publishedOn(published)}`);
  if (status.publishing) parts.push(`${status.publishing} publishing now`);
  if (status.approvals) parts.push(`${status.approvals} waiting for approval`);
  if (status.failed) parts.push(`${status.failed} failed in the last 24 hours`);
  if (status.next) {
    parts.push(`next post on ${status.next.platform}, ${spokenTime.format(status.next.at)}`);
  }
  return `Publishing status: ${parts.length > 0 ? parts.join('; ') : 'all quiet'}`;
}

function isKeyboardFocus(target: EventTarget) {
  try {
    return target instanceof Element && target.matches(':focus-visible');
  } catch {
    return false;
  }
}

/** A fixed 16px slot so every row's text starts on the same line whatever the mark is. */
function Glyph({ tone }: { tone: Tone }) {
  const reduce = useReducedMotion();
  return (
    <span aria-hidden='true' className='grid size-4 shrink-0 place-items-center'>
      {tone === 'publishing' ? (
        <Icons.spinner className={cn('size-3.5 text-violet-500', !reduce && 'animate-spin')} />
      ) : tone === 'published' ? (
        <span className='grid size-4 place-items-center rounded-full bg-emerald-500 text-white'>
          <Icons.check className='size-3' stroke={3} />
        </span>
      ) : (
        <span className={cn('size-2 rounded-full', DOT[tone])} />
      )}
    </span>
  );
}

/**
 * Live publishing status on the DynamicIsland: a compact pill for what matters most right now,
 * a panel with every open item on hover, focus or tap, and a short "Published on …" moment
 * when a job the page already knew about is confirmed. Reads only the workspace snapshot.
 */
export function LiveIsland({ className }: { className?: string }) {
  const snapshot = useSnapshot();
  const phase2 = snapshot.data?.state.phase2;
  const jobs = phase2?.jobs;
  const reduce = useReducedMotion();
  const listId = useId();

  // The clock ticks only while a next post is counting down; a fresh snapshot moves it as well,
  // so a long quiet stretch never leaves a stale "next" on screen.
  const [tick, setTick] = useState(() => Date.now());
  const now = Math.max(tick, snapshot.dataUpdatedAt);
  const status = readStatus(phase2, now);
  const hasNext = status.next !== null;
  useEffect(() => {
    if (!hasNext) return;
    const id = window.setInterval(() => setTick(Date.now()), TICK_MS);
    return () => window.clearInterval(id);
  }, [hasNext]);

  // "Published on …" fires only for a job that was already in the previous snapshot and has just
  // reached published or verified; the first snapshot only seeds what was seen.
  const seen = useRef<Map<string, string> | null>(null);
  const [published, setPublished] = useState<Published | null>(null);
  useEffect(() => {
    if (!jobs) return;
    const previous = seen.current;
    seen.current = new Map(jobs.map((job) => [job.id, job.state]));
    if (!previous) return;
    const flipped = jobs.filter((job) => {
      const before = previous.get(job.id);
      return before !== undefined && !DONE.has(before) && DONE.has(job.state);
    });
    if (flipped.length === 0) return;
    // A new object each time, so a second confirmation restarts the timer.
    setPublished({
      platform: flipped[0].manifest?.platform ?? 'your channel',
      others: flipped.length - 1
    });
  }, [jobs]);
  useEffect(() => {
    if (!published) return;
    const id = window.setTimeout(() => setPublished(null), EVENT_MS);
    return () => window.clearTimeout(id);
  }, [published]);

  const rootRef = useRef<HTMLDivElement>(null);
  const compactRef = useRef<HTMLButtonElement>(null);
  const headerRef = useRef<HTMLButtonElement>(null);
  const hoverTimer = useRef<number | undefined>(undefined);
  const hovering = useRef(false);
  const hoverOpenedAt = useRef(0);
  const pressedAt = useRef(Number.NEGATIVE_INFINITY);
  const [open, setOpen] = useState(false);
  const [focusWithin, setFocusWithin] = useState(false);

  const close = useCallback(() => {
    window.clearTimeout(hoverTimer.current);
    setOpen(false);
  }, []);
  // Escape anywhere, or a press outside the island, closes the panel.
  useDismiss(open, close, rootRef);
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);

  // While focus is inside, the event stays in the pill or the panel: swapping to the event view
  // would unmount the control that holds focus.
  const view = open ? 'details' : published && !focusWithin ? 'event' : null;

  // Each view renders its own toggle, so when a swap removes the focused one, focus follows to
  // its counterpart instead of falling back to the page.
  useEffect(() => {
    const root = rootRef.current;
    const active = document.activeElement;
    if (!root || !active || !root.contains(active)) return;
    const target =
      view === 'details' ? headerRef.current : view === null ? compactRef.current : null;
    if (target && target !== active) target.focus({ preventScroll: true });
  }, [view]);

  const hoverTo = (next: boolean) => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(
      () => {
        if (next) hoverOpenedAt.current = performance.now();
        setOpen(next);
      },
      next ? OPEN_DELAY_MS : CLOSE_DELAY_MS
    );
  };

  const onPointerEnter = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'touch') return;
    hovering.current = true;
    hoverTo(true);
  };

  const onPointerLeave = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'touch') return;
    hovering.current = false;
    hoverTo(false);
  };

  const onFocus = (event: FocusEvent<HTMLDivElement>) => {
    setFocusWithin(true);
    if (rootRef.current?.contains(event.relatedTarget as Node | null)) return;
    // Keyboard focus arriving from outside opens the panel; a mouse or touch press does not,
    // so the click that follows it can toggle.
    if (isKeyboardFocus(event.target)) {
      window.clearTimeout(hoverTimer.current);
      setOpen(true);
    }
  };

  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (rootRef.current?.contains(event.relatedTarget as Node | null)) return;
    setFocusWithin(false);
    // A press on the panel's own text hands focus to the page without leaving the island.
    if (performance.now() - pressedAt.current < PRESS_BLUR_MS) return;
    close();
  };

  const onHeaderClick = () => {
    if (hovering.current && performance.now() - hoverOpenedAt.current < CLICK_GRACE_MS) return;
    close();
  };

  if (!snapshot.data) return null;

  const tone = toneOf(status);
  const label = describe(status, published);
  const next = status.next;
  const quiet = tone === 'quiet' && !published;

  const compact = (
    <button
      ref={compactRef}
      type='button'
      aria-expanded={false}
      aria-label={label}
      onClick={() => {
        window.clearTimeout(hoverTimer.current);
        setOpen(true);
      }}
      // Negative margins let the button cover the whole pill, padding included.
      className='-mx-4 -my-1.5 flex min-w-[126px] items-center justify-center self-stretch rounded-full px-4 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-background/70 focus-visible:ring-inset'
    >
      {/* Capped to the header track the island sits in (100cqw), so the pill never reaches the
          breadcrumbs or the actions; outside a container it caps against the viewport. */}
      <span
        aria-hidden='true'
        className='flex max-w-[min(14rem,calc(100cqw_-_3rem))] min-w-0 items-center gap-2'
      >
        {published ? (
          <>
            <Glyph tone='published' />
            <span className='truncate'>Published on {publishedOn(published)}</span>
          </>
        ) : (
          <>
            <Glyph tone={tone} />
            {tone === 'publishing' ? (
              <span className='truncate'>Publishing {status.publishing}</span>
            ) : tone === 'approvals' ? (
              <span className='truncate'>{status.approvals} to approve</span>
            ) : tone === 'failed' ? (
              <span className='truncate'>{status.failed} failed</span>
            ) : next ? (
              <>
                <span className='truncate'>Next · {next.platform}</span>
                <span className='shrink-0 text-background/60 tabular-nums'>
                  {countdown(next.at - now)}
                </span>
              </>
            ) : (
              <span className='truncate text-background/80'>All quiet</span>
            )}
          </>
        )}
      </span>
    </button>
  );

  return (
    <motion.div
      ref={rootRef}
      initial={reduce ? false : { opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { duration: 0.35, ease: EASE_OUT }}
      className={cn('pointer-events-auto', className)}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      onPointerDown={() => {
        pressedAt.current = performance.now();
      }}
      onFocus={onFocus}
      onBlur={onBlur}
    >
      <DynamicIsland view={view} compact={compact}>
        <DynamicIslandView id='details' className='p-1.5'>
          <div className='flex w-72 flex-col'>
            <button
              ref={headerRef}
              type='button'
              aria-expanded={true}
              aria-controls={listId}
              aria-label={label}
              onClick={onHeaderClick}
              className={cn(ROW_ACTION, 'font-medium')}
            >
              <Glyph tone={published ? 'published' : tone} />
              <span aria-hidden='true' className='min-w-0 flex-1 truncate'>
                Publishing status
              </span>
              <Icons.chevronUp
                aria-hidden='true'
                className='size-3.5 shrink-0 text-background/60'
              />
            </button>
            <ul
              id={listId}
              className='mt-1 flex flex-col gap-0.5 border-t border-background/10 pt-1'
            >
              {published ? (
                <li className={ROW}>
                  <Glyph tone='published' />
                  <span className='min-w-0 flex-1 truncate'>
                    Published on {publishedOn(published)}
                  </span>
                </li>
              ) : null}
              {status.approvals > 0 ? (
                <li>
                  <Link href='/app/queue' onClick={close} className={ROW_ACTION}>
                    <Glyph tone='approvals' />
                    <span className='min-w-0 flex-1 truncate'>Waiting for approval</span>
                    <span className='font-medium tabular-nums'>{status.approvals}</span>
                    <Icons.chevronRight
                      aria-hidden='true'
                      className='size-3.5 shrink-0 text-background/50'
                    />
                  </Link>
                </li>
              ) : null}
              {status.publishing > 0 ? (
                <li className={ROW}>
                  <Glyph tone='publishing' />
                  <span className='min-w-0 flex-1 truncate'>Publishing now</span>
                  <span className='font-medium tabular-nums'>{status.publishing}</span>
                  <span aria-hidden='true' className='size-3.5 shrink-0' />
                </li>
              ) : null}
              {next ? (
                <li>
                  <Link href='/app/calendar' onClick={close} className={ROW_ACTION}>
                    <Glyph tone='next' />
                    <span className='flex min-w-0 flex-1 flex-col'>
                      <span className='truncate'>
                        Next post · {next.platform} · {next.account}
                      </span>
                      <span className='truncate text-background/60 tabular-nums'>
                        {slot(next.at, now)}{' '}
                        {/* Hidden from assistive tech: it changes every 30 seconds. */}
                        <span aria-hidden='true'>({countdown(next.at - now)})</span>
                      </span>
                    </span>
                    <Icons.chevronRight
                      aria-hidden='true'
                      className='size-3.5 shrink-0 text-background/50'
                    />
                  </Link>
                </li>
              ) : null}
              {status.failed > 0 ? (
                <li>
                  <Link href='/app/queue' onClick={close} className={ROW_ACTION}>
                    <Glyph tone='failed' />
                    <span className='min-w-0 flex-1 truncate'>Failed in the last 24 h</span>
                    <span className='font-medium tabular-nums'>{status.failed}</span>
                    <Icons.chevronRight
                      aria-hidden='true'
                      className='size-3.5 shrink-0 text-background/50'
                    />
                  </Link>
                </li>
              ) : null}
              {quiet ? (
                <li className={cn(ROW, 'text-background/60')}>
                  Nothing waiting, publishing or scheduled.
                </li>
              ) : null}
            </ul>
          </div>
        </DynamicIslandView>
        <DynamicIslandView id='event' className='gap-2.5 px-4 py-2.5'>
          <span
            aria-hidden='true'
            className='grid size-6 shrink-0 place-items-center rounded-full bg-emerald-500 text-white'
          >
            <Icons.check className='size-3.5' stroke={3} />
          </span>
          <span className='max-w-56 truncate text-sm font-medium'>
            {published ? `Published on ${publishedOn(published)}` : null}
          </span>
        </DynamicIslandView>
      </DynamicIsland>
    </motion.div>
  );
}
