/**
 * Job vocabulary for the Queue page: the state sets, the groups and badges, the filters, and the job fields the API
 * sends that `lib/api/types.ts` does not declare yet. Values mirror `src/postriff_phase2/store.py` (`TERMINAL`,
 * `IN_FLIGHT`, `invalidate`, cancel) and `hosted_worker.py` (claim, complete, the 3-attempt limit).
 *
 * `jobGroup` and `jobBadge` match `features/pipeline/job-state.ts` word for word, so a job reads the same on both
 * pages. Follow-up: have the Pipeline import them from here and drop its copy.
 */
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { Job, Review } from '@/lib/api/types';

/** Approved and waiting for the worker; `p2_cancel` ends these at once. */
export const WAITING = new Set(['scheduled', 'approved', 'claimed']);
/** The worker has handed the post to the provider. A cancel here cannot recall it; it turns uncertain. */
export const PUBLISHING = new Set(['submitting', 'provider_accepted', 'published']);
/** The worker handed the post to the provider, or the provider has not confirmed it yet. */
export const IN_FLIGHT = new Set([...PUBLISHING, 'uncertain']);
/**
 * Approval, capability or entitlement changed after approval. The worker skips a held job, and it still counts
 * toward the account's daily limit until it is cancelled (`store.py` approve counts every job not failed or cancelled).
 */
export const HELD = new Set(['held']);
export const DONE = new Set(['verified']);
/** How a job ends without a verified post. */
export const ENDED = new Set(['failed', 'canceled']);

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
export type QueueJob = Omit<Job, 'events'> & {
  approvedBy?: string;
  approvedAt?: number;
  approvalDigest?: string;
  nextAt?: number;
  checks?: number;
  scheduleId?: string | null;
  /** A permalink, once the worker records one. Not written today; shown only when present. */
  url?: string;
  events: (Job['events'][number] & { execution?: string })[];
};

export type QueueReview = Review & { createdAt?: number };

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
export function workerNote(job: QueueJob): string | null {
  const last = job.events.at(-1);
  if (!job.nextAction || !last) return null;
  return last.state === job.state && last.message === job.providerConfirmed ? job.nextAction : null;
}

/**
 * The line under a job's state: why it was held (the server's own sentence on the held event), or, for a failed or
 * unconfirmed job, the worker's current note or else its last event. Nothing for jobs that need no one.
 */
export function stateNote(job: QueueJob): string | null {
  if (HELD.has(job.state)) {
    return job.events.findLast((event) => event.state === 'held')?.message || null;
  }
  if (job.state === 'failed' || job.state === 'uncertain') {
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
  const minutes = Math.floor((targetSeconds - nowSeconds) / 60);
  if (minutes < 1) return 'in <1 min';
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return minutes % 60 ? `in ${hours}h ${minutes % 60}m` : `in ${hours}h`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `in ${days}d ${hours % 24}h` : `in ${days}d`;
}

// Sized for a table cell, with the corner radius of the app's small buttons.
export const HOLD_CANCEL_CLASS = 'h-7 min-w-0 bg-secondary px-3 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
// An opaque destructive tint for both the fill and its liquid edge, so the two meet without a seam.
export const HOLD_CANCEL_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
export const HOLD_CANCEL_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
