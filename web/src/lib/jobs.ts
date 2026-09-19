/** Shared publishing states. Only provider-verified jobs are complete. */
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { Job, Review, Phase2State } from '@/lib/api/types';

/** Approved and waiting for the worker; `p2_cancel` ends these at once. */
export const WAITING: ReadonlySet<string> = new Set(['scheduled', 'approved', 'claimed']);
/** The worker has handed the post to the provider. A cancel here cannot recall it; it turns uncertain. */
export const PUBLISHING: ReadonlySet<string> = new Set(['submitting', 'provider_accepted', 'published']);
/** The worker handed the post to the provider, or the provider has not confirmed it yet. */
export const IN_FLIGHT: ReadonlySet<string> = new Set([...PUBLISHING, 'uncertain']);
/**
 * Approval, capability or entitlement changed after approval. The worker skips a held job, and it still counts
 * toward the account's daily limit until it is cancelled (`store.py` approve counts every job not failed or cancelled).
 */
export const HELD: ReadonlySet<string> = new Set(['held']);
export const DONE: ReadonlySet<string> = new Set(['verified']);
/** How a job ends without a verified post. */
export const ENDED: ReadonlySet<string> = new Set(['failed', 'canceled']);

/** `hosted_worker.py` fails a job once it has made this many attempts. */
export const MAX_ATTEMPTS = 3;

/** `ended` is failed or cancelled; `other` is a state this client does not know yet, shown under All. */
export type JobGroup = 'waiting' | 'publishing' | 'uncertain' | 'held' | 'verified' | 'ended' | 'other';

export function jobGroup(state: string): JobGroup {
  if (WAITING.has(state)) return 'waiting';
  if (PUBLISHING.has(state)) return 'publishing';
  if (state === 'uncertain') return 'uncertain';
  if (HELD.has(state)) return 'held';
  if (DONE.has(state)) return 'verified';
  if (ENDED.has(state)) return 'ended';
  // A state added on the server later: shown with its receipt, never dropped and never called failed.
  return 'other';
}

export const FILTER_VALUES = ['all', 'waiting', 'in-flight', 'held', 'done', 'ended'] as const;
export type Filter = (typeof FILTER_VALUES)[number];

export const FILTERS: { value: Filter; label: string; empty: string }[] = [
  { value: 'all', label: 'All', empty: 'Approved posts appear here as jobs the worker runs at the approved time.' },
  { value: 'waiting', label: 'Waiting', empty: 'A waiting job is approved and has not reached the provider yet. It can still be cancelled.' },
  { value: 'in-flight', label: 'In flight', empty: 'An in-flight job is with the provider. When the provider does not confirm, PostRiff reconciles and never resubmits.' },
  { value: 'held', label: 'Held', empty: 'A held job needs a new review; nothing publishes from it.' },
  { value: 'done', label: 'Verified', empty: 'A verified job is one the provider confirmed as published.' },
  { value: 'ended', label: 'Ended', empty: 'Failed and cancelled jobs end here, with the reason they stopped.' }
];

/** Fields present on every job the API sends (`store.py` approve, `hosted_worker.py`) but not in the shared type. */
export type QueueJob = Job;
export type QueueReview = Review;

/** A state in plain words, with the British spelling the rest of the page uses. */
export const stateWords = (value: string) => (value === 'canceled' ? 'cancelled' : value.replace(/_/g, ' '));

/** The badge colour of a bare state, for timeline events (a job's own badge is `jobBadge`). */
export function stateStatus(state: string): AnimatedBadgeStatus {
  switch (jobGroup(state)) {
    case 'waiting':
      return 'info';
    case 'publishing':
      return 'loading';
    case 'uncertain':
    case 'held':
      return 'warning';
    case 'verified':
      return 'success';
    case 'ended':
      return state === 'failed' ? 'danger' : 'neutral';
    default:
      return 'neutral';
  }
}

export function matchesFilter(state: string, filter: Filter) {
  if (filter === 'waiting') return WAITING.has(state);
  if (filter === 'in-flight') return IN_FLIGHT.has(state);
  if (filter === 'held') return HELD.has(state);
  if (filter === 'done') return DONE.has(state);
  if (filter === 'ended') return ENDED.has(state);
  return true;
}

export function epochOf(iso: string | undefined) {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

/**
 * `p2_cancel` before the provider has the post: waiting jobs, and held ones (which the worker skips but which still
 * count toward the account's daily limit). After submission a cancel cannot recall anything, so it is not offered.
 */
export function canCancel(job: { state: string; cancelRequested?: boolean }) {
  return (WAITING.has(job.state) || HELD.has(job.state)) && !job.cancelRequested;
}

export interface JobBadge {
  status: AnimatedBadgeStatus;
  label: string;
  pulse: boolean;
  title?: string;
}

/**
 * One badge per job group, so "uncertain" and "held" never read as "scheduled", and "published" never reads as
 * confirmed before the provider verified it. Only publishing and cancelling pulse.
 */
export function jobBadge(job: { state: string; cancelRequested?: boolean; verification?: { method?: string | null } | null }): JobBadge {
  const group = jobGroup(job.state);
  const label = stateWords(job.state);
  // Only a job that has not reached the provider is actually being cancelled; after submission the request
  // turns the job uncertain, and that is what the badge says.
  if (job.cancelRequested && (group === 'waiting' || group === 'held')) {
    return { status: 'loading', label: 'cancelling', pulse: true, title: `Cancel requested while ${label}` };
  }
  switch (group) {
    case 'waiting':
      return { status: 'info', label: 'waiting', pulse: false, title: `Approved and waiting for its time (${label})` };
    case 'publishing':
      return job.state === 'published'
        ? { status: 'loading', label: 'published · verifying', pulse: true, title: 'The provider reported it published; PostRiff has not verified it yet.' }
        : { status: 'loading', label, pulse: true, title: 'Handed to the provider; waiting for its answer.' };
    case 'uncertain':
      return {
        status: 'warning',
        label: 'uncertain · reconciling',
        pulse: false,
        title: job.cancelRequested
          ? 'A cancel was requested after submission, which cannot recall the post. Nothing is retried until it is reconciled.'
          : 'The provider did not confirm; nothing is retried until it is reconciled.'
      };
    case 'held':
      return { status: 'warning', label: 'held', pulse: false, title: 'Something changed after approval. Nothing publishes from this job; prepare a new review.' };
    case 'verified':
      return {
        status: 'success',
        label: job.verification?.method ? `verified · ${stateWords(job.verification.method)}` : 'verified',
        pulse: false,
        title: 'Confirmed by the provider.'
      };
    case 'ended':
      return job.state === 'failed' ? { status: 'danger', label: 'failed', pulse: false } : { status: 'neutral', label: 'cancelled', pulse: false };
    default:
      return { status: 'neutral', label, pulse: false, title: 'A state this page does not recognise yet; open the receipt for its events.' };
  }
}

/** Jobs approved against a fixture channel: the synthetic provider never reaches a real account. */
export function isSynthetic(job: { manifest: { execution: string } }) {
  return job.manifest.execution === 'synthetic';
}

/**
 * The worker's `nextAction`, only while it still describes the job. The worker writes it together with the event and
 * `providerConfirmed` when it completes an attempt; a later hold, failure or cancel (claim, `invalidate`) adds an
 * event without touching it, so an older note would describe a state the job has left.
 */
export function workerNote(job: Pick<Job, 'state' | 'nextAction' | 'providerConfirmed' | 'events'>): string | null {
  const last = job.events.at(-1);
  if (!job.nextAction || !last) return null;
  return last.state === job.state && last.message === job.providerConfirmed ? job.nextAction : null;
}

/**
 * The line under a job's state: why it was held (the server's own sentence on the held event), or, for a failed or
 * unconfirmed job, the worker's current note or else its last event. Nothing for jobs that need no one.
 */
export function stateNote(job: Pick<Job, 'state' | 'nextAction' | 'providerConfirmed' | 'events'>): string | null {
  if (HELD.has(job.state)) {
    return job.events.findLast((event) => event.state === 'held')?.message || null;
  }
  if (job.state === 'failed' || job.state === 'uncertain' || jobGroup(job.state) === 'other') {
    return workerNote(job) ?? (job.events.at(-1)?.message || null);
  }
  return null;
}

/** When the worker next looks at a job: its lease-aware `nextAt`, or the approved time. */
export function nextCheckAt(job: QueueJob) {
  return job.nextAt ?? epochOf(job.manifest.timing.utc);
}

/**
 * Something is moving: a job with the provider, or a waiting job the worker picks up within two minutes.
 * The page refreshes the snapshot only then.
 */
export function isLive(jobs: QueueJob[], nowSeconds: number) {
  return jobs.some((job) => {
    if (!IN_FLIGHT.has(job.state) && !WAITING.has(job.state)) return false;
    const next = nextCheckAt(job);
    if (IN_FLIGHT.has(job.state) && next === null) return true;
    return next !== null && next <= nowSeconds + 120;
  });
}

/** The newest event the hosted worker itself wrote; approvals and cancels do not count as worker activity. */
export function latestWorkerActivity(jobs: QueueJob[]): number | null {
  let latest: number | null = null;
  for (const job of jobs) {
    for (const event of job.events) {
      if (event.execution === 'hosted-worker' && (latest === null || event.at > latest)) latest = event.at;
    }
  }
  return latest;
}

/** "in 4 min", "in 2h 13m", "in 3d 5h" (the live island's wording). Null once the time has passed. */
export function countdown(targetSeconds: number | null, nowSeconds: number) {
  if (targetSeconds === null || targetSeconds <= nowSeconds) return null;
  return countdownMs((targetSeconds - nowSeconds) * 1000);
}

// Sized for a table cell, with the corner radius of the app's small buttons.
export const HOLD_CANCEL_CLASS = 'h-7 min-w-0 bg-secondary px-3 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
// An opaque destructive tint for both the fill and its liquid edge, so the two meet without a seam.
export const HOLD_CANCEL_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
export const HOLD_CANCEL_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';

export const SENDING = IN_FLIGHT;
export const FAILED = ENDED;
export const LIVE_JOB: ReadonlySet<string> = new Set([...WAITING, ...IN_FLIGHT, ...HELD, ...DONE]);
export const isCancellable = canCancel;
export const jobNote = stateNote;

export function countSending(phase2: Phase2State | undefined) {
  return (phase2?.jobs ?? []).filter((job) => SENDING.has(job.state)).length;
}

const MINUTE = 60_000;
const DAY = 86_400_000;
/** How often the countdown to the next post is recomputed while there is one. */
export const TICK_MS = 30_000;

export interface NextPost {
  jobId: string;
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
    if (IN_FLIGHT.has(job.state)) {
      publishing += 1;
    } else if (job.state === 'failed') {
      const last = job.events?.at(-1)?.at;
      if (last !== undefined && last * 1000 >= now - DAY) failed += 1;
    } else if (WAITING.has(job.state)) {
      // A job without a readable timing is skipped rather than trusted.
      const at = scheduledAt(job);
      if (at > now && (next === null || at < next.at)) {
        next = { jobId: job.id, platform: job.manifest.platform, account: job.manifest.account, channelId: job.manifest.channelId, at };
      }
    }
  }
  const approvals = (phase2?.reviews ?? []).filter((review) => review.status === 'needs_review').length;
  return { approvals, publishing, failed, next };
}

/** "in 4 min", "in 2h 13m", "in 3d 5h". */
export function countdownMs(ms: number) {
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
