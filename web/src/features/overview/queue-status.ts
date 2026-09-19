import type { Job, Phase2State } from '@/lib/api/types';

/*
 * Local copy of the queue reading in `components/layout/live-island.tsx` (`readStatus`, the state
 * groups and `countdown`), so the Overview's "Next up" and the header island count the same way.
 * Kept in step by hand until the shared version lands in `lib/`; see the Overview report.
 * Additions over the island: the next post carries its `channelId`, times are written in the
 * viewer's zone, and `readWeek` buckets the coming days.
 */

/** Job states grouped the way the Queue and Calendar group them (copied from the Live Island). */
export const PUBLISHING: ReadonlySet<string> = new Set(['submitting', 'provider_accepted', 'published', 'uncertain']);
export const WAITING: ReadonlySet<string> = new Set(['scheduled', 'approved', 'claimed']);
/**
 * The island's PUBLISHING without `published`: a post the provider already accepted is waiting for
 * its receipt, not being sent. The Overview's stat cards count it under Published, so the strip and
 * the "sending now" badge leave it out to keep one number per job on the page.
 */
export const SENDING: ReadonlySet<string> = new Set(['submitting', 'provider_accepted', 'uncertain']);

export function countSending(phase2: Phase2State | undefined) {
  return (phase2?.jobs ?? []).filter((job) => SENDING.has(job.state)).length;
}

const MINUTE = 60_000;
const DAY = 86_400_000;
/** How often the countdown to the next post is recomputed while there is one. */
export const TICK_MS = 30_000;

export interface NextPost {
  platform: string;
  account: string;
  channelId?: string;
  /** Epoch milliseconds. */
  at: number;
}

export interface QueueStatus {
  approvals: number;
  publishing: number;
  failed: number;
  next: NextPost | null;
}

function scheduledAt(job: Job) {
  return Date.parse(job.manifest?.timing?.utc ?? '');
}

/** Counts straight from the snapshot: open reviews, jobs in flight, recent failures, the next approved slot. `now` is ms. */
export function readStatus(phase2: Phase2State | undefined, now: number): QueueStatus {
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
      // A job without a readable timing is skipped rather than trusted.
      const at = scheduledAt(job);
      if (at > now && (next === null || at < next.at)) {
        next = { platform: job.manifest.platform, account: job.manifest.account, channelId: job.manifest.channelId, at };
      }
    }
  }
  const approvals = (phase2?.reviews ?? []).filter((review) => review.status === 'needs_review').length;
  return { approvals, publishing, failed, next };
}

/** "in 4 min", "in 2h 13m", "in 3d 5h". */
export function countdown(ms: number) {
  const minutes = Math.floor(ms / MINUTE);
  if (minutes < 1) return 'in <1 min';
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `in ${hours}h ${minutes % 60}m` : `in ${hours}h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `in ${days}d ${hours % 24}h` : `in ${days}d`;
}

/* ---------- the coming week, in the viewer's zone ---------- */

const keyFormatters = new Map<string, Intl.DateTimeFormat>();

/** "2026-09-16" for an instant, as the calendar date in `timeZone`. */
export function dayKey(ms: number, timeZone: string) {
  let format = keyFormatters.get(timeZone);
  if (!format) {
    format = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' });
    keyFormatters.set(timeZone, format);
  }
  const parts = Object.fromEntries(format.formatToParts(ms).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export interface StripJob {
  id: string;
  platform: string;
  account: string;
}

export interface StripDay {
  /** "YYYY-MM-DD" in the viewer's zone; also the Calendar's `date` parameter. */
  key: string;
  /** UTC midnight of that calendar date, for weekday and day-of-month labels only. */
  date: Date;
  /** Approved jobs whose slot falls on this day. */
  waiting: StripJob[];
  /** Jobs being sent to the provider (`SENDING`), by their slot day. */
  sending: StripJob[];
  /** Jobs that failed within the last 24 hours, by the day they failed. */
  failed: number;
}

/**
 * `days` calendar days starting today in `timeZone`. Only jobs with a readable timing are placed;
 * a job still being sent whose slot was before today is shown on today, where the work is happening.
 */
export function readWeek(phase2: Phase2State | undefined, now: number, timeZone: string, days = 7): StripDay[] {
  const [year, month, day] = dayKey(now, timeZone).split('-').map(Number);
  const week: StripDay[] = Array.from({ length: days }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, day + index));
    return { key: date.toISOString().slice(0, 10), date, waiting: [], sending: [], failed: 0 };
  });
  const byKey = new Map(week.map((entry) => [entry.key, entry]));
  const first = week[0];

  for (const job of phase2?.jobs ?? []) {
    const entry = { id: job.id, platform: job.manifest?.platform ?? '', account: job.manifest?.account ?? '' };
    if (job.state === 'failed') {
      const last = job.events?.at(-1)?.at;
      if (last === undefined || last * 1000 < now - DAY) continue;
      const target = byKey.get(dayKey(last * 1000, timeZone));
      if (target) target.failed += 1;
      continue;
    }
    const inFlight = SENDING.has(job.state);
    if (!inFlight && !WAITING.has(job.state)) continue;
    const at = scheduledAt(job);
    if (Number.isNaN(at)) continue;
    const key = dayKey(at, timeZone);
    const target = byKey.get(key) ?? (inFlight && key < first.key ? first : undefined);
    if (!target) continue;
    (inFlight ? target.sending : target.waiting).push(entry);
  }
  return week;
}
