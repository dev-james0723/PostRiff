/**
 * Job-state vocabulary for the Pipeline board.
 *
 * The sets and the hold-to-cancel classes overlap `features/queue/job-state.ts`, which the Queue page owns.
 * Follow-up: keep one copy and import it from both pages, so the two boards cannot drift. Values mirror
 * `src/postriff_phase2/store.py` (`TERMINAL`, `IN_FLIGHT`, `cancel`, the `held` event written by `invalidate`)
 * and `hosted_worker.py` (re-authorisation at claim, `nextAction`). Unlike the Queue's `canCancel`, a held job
 * is cancellable here: `store.py` cancel only refuses terminal states.
 */
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';

/** Approved and waiting for the worker. `p2_cancel` ends these at once (`store.py` cancel). */
export const WAITING = new Set(['scheduled', 'approved', 'claimed']);
/** The worker has handed the post to the provider. A cancel here cannot recall it; it turns uncertain. */
export const PUBLISHING = new Set(['submitting', 'provider_accepted', 'published']);
/** The provider gave no confirmation; PostRiff reconciles before it ever retries. */
export const UNCERTAIN = 'uncertain';
/** Approval, capability or entitlement changed after approval; the worker skips it until it is cancelled. */
export const HELD = 'held';
export const IN_FLIGHT = new Set([...PUBLISHING, UNCERTAIN]);
export const DONE = new Set(['verified']);
export const FAILED = new Set(['failed', 'canceled']);
/** A job that still stands for its draft's exact revision on the board. */
export const LIVE_JOB = new Set([...WAITING, ...IN_FLIGHT, HELD, ...DONE]);

/** `ended` is failed or cancelled; `other` is a state this client does not know yet, kept in the Queue column. */
export type JobGroup = 'waiting' | 'publishing' | 'uncertain' | 'held' | 'verified' | 'ended' | 'other';

export function jobGroup(state: string): JobGroup {
  if (WAITING.has(state)) return 'waiting';
  if (PUBLISHING.has(state)) return 'publishing';
  if (state === UNCERTAIN) return 'uncertain';
  if (state === HELD) return 'held';
  if (DONE.has(state)) return 'verified';
  if (FAILED.has(state)) return 'ended';
  // A state added on the server later: shown with its receipt, never dropped and never called failed.
  return 'other';
}

/**
 * The sentence under a job that needs someone: why it is held, or what to do about a failed, unconfirmed or
 * unrecognised job. `invalidate` (`store.py`) and the hosted worker's re-authorisation write `held` without
 * touching `nextAction`, so an earlier worker cycle's `nextAction` can still sit on a held job; the held event's own
 * message is the reason. `null` for jobs that need no one.
 */
export function jobNote(job: { state: string; nextAction?: string; events: { state: string; message: string }[] }): string | null {
  const group = jobGroup(job.state);
  if (group === 'held') return job.events.findLast((event) => event.state === HELD)?.message || job.nextAction || null;
  if (group === 'uncertain' || group === 'other' || job.state === 'failed') return job.nextAction || job.events.at(-1)?.message || null;
  return null;
}

/** Whether a person with the approve permission may still cancel the job (`p2_cancel` before submission). */
export function isCancellable(job: { state: string; cancelRequested?: boolean }) {
  const group = jobGroup(job.state);
  return (group === 'waiting' || group === 'held') && !job.cancelRequested;
}

export interface JobBadge {
  status: AnimatedBadgeStatus;
  label: string;
  pulse: boolean;
  title?: string;
}

/** A state in plain words, with the British spelling the rest of the page uses. */
export const stateWords = (value: string) => (value === 'canceled' ? 'cancelled' : value.replace(/_/g, ' '));
const words = stateWords;

/**
 * One badge per job group, so "uncertain" and "held" never read as "scheduled", and "published" never reads as
 * confirmed before the provider verified it.
 */
export function jobBadge(job: { state: string; cancelRequested?: boolean; verification?: { method?: string | null } | null }): JobBadge {
  const group = jobGroup(job.state);
  const label = words(job.state);
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
      return { status: 'warning', label: 'held', pulse: false, title: 'Something changed after approval. Cancel it, then prepare a new review.' };
    case 'verified':
      return {
        status: 'success',
        label: job.verification?.method ? `verified · ${words(job.verification.method)}` : 'verified',
        pulse: false,
        title: 'Confirmed by the provider.'
      };
    case 'ended':
      return job.state === 'failed' ? { status: 'danger', label: 'failed', pulse: false } : { status: 'neutral', label: 'cancelled', pulse: false };
    default:
      return { status: 'neutral', label, pulse: false, title: 'A state this page does not recognise yet; open the details for its events.' };
  }
}

// Sized for a card row, with the corner radius of the app's small buttons.
export const HOLD_CANCEL_CLASS = 'h-7 min-w-0 bg-secondary px-3 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
// An opaque destructive tint for both the fill and its liquid edge, so the two meet without a seam.
export const HOLD_CANCEL_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
export const HOLD_CANCEL_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
