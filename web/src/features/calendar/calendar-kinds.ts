import type { CalendarEventColor } from '@/components/application/calendar/config';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { Job, Review } from '@/lib/api/types';

/**
 * What a calendar entry is, read straight from the snapshot. Reviews: `review` waits for approval, `expired`
 * passed `manifest.expiresAt` (approving it now returns 409), `stale` was invalidated by the backend because
 * something it was checked against changed. Jobs follow `job.state`; `held` is a job the worker will not run.
 */
export const KINDS = ['review', 'expired', 'stale', 'waiting', 'held', 'in-flight', 'processing', 'accepted', 'uncertain', 'unknown', 'assisted', 'manual', 'verified', 'failed', 'canceled'] as const;

export type Kind = (typeof KINDS)[number];

export interface KindMeta {
  label: string;
  color: CalendarEventColor;
  status: AnimatedBadgeStatus;
}

// Nine kinds share the calendar's nine event colours. `brand` follows the workspace theme, so it goes to the
// kind that least needs to stand out: a review that can no longer be approved and asks for nothing until the
// draft is prepared again.
export const KIND_META: Record<Kind, KindMeta> = {
  review: { label: 'Needs approval', color: 'yellow', status: 'warning' },
  expired: { label: 'Review expired', color: 'pink', status: 'danger' },
  stale: { label: 'Out of date', color: 'brand', status: 'neutral' },
  waiting: { label: 'Scheduled', color: 'blue', status: 'info' },
  held: { label: 'Needs action', color: 'orange', status: 'warning' },
  'in-flight': { label: 'Publishing', color: 'indigo', status: 'loading' },
  processing: { label: 'Preparing media', color: 'indigo', status: 'info' },
  accepted: { label: 'Accepted; checking result', color: 'indigo', status: 'info' },
  uncertain: { label: 'Result not confirmed', color: 'orange', status: 'warning' },
  unknown: { label: 'Unknown status', color: 'gray', status: 'warning' },
  assisted: { label: 'Finish in the app', color: 'orange', status: 'warning' },
  manual: { label: 'Marked completed by you', color: 'gray', status: 'neutral' },
  verified: { label: 'Published and verified', color: 'green', status: 'success' },
  failed: { label: 'Failed', color: 'red', status: 'danger' },
  canceled: { label: 'Canceled', color: 'gray', status: 'neutral' }
};

/** Job states the worker still runs at their time (`store.py` treats these as cancellable). */
export const WAITING_STATES = new Set(['approved', 'scheduled', 'claimed']);

/** Submitted or being reconciled (`store.py` IN_FLIGHT). */
export const IN_FLIGHT_STATES = new Set(['processing', 'submitting', 'provider_accepted', 'published', 'uncertain']);

export function jobKind(state: string): Kind {
  if (state === 'handoff_opened') return 'assisted';
  if (state === 'user_reported_completed') return 'manual';
  if (state === 'verified') return 'verified';
  if (state === 'failed') return 'failed';
  if (state === 'canceled') return 'canceled';
  if (state === 'held') return 'held';
  if (state === 'uncertain') return 'uncertain';
  if (state === 'processing') return 'processing';
  if (state === 'provider_accepted' || state === 'published') return 'accepted';
  if (state === 'submitting') return 'in-flight';
  if (WAITING_STATES.has(state)) return 'waiting';
  return 'unknown';
}

/** A review past `manifest.expiresAt` can no longer be approved (the backend answers 409). */
export function reviewExpired(review: Review, nowSeconds: number) {
  return review.status === 'needs_review' && review.manifest.expiresAt <= nowSeconds;
}

/** `null` for reviews the calendar leaves out: an approved review already shows as its job. */
export function reviewKind(review: Review, expired: boolean): Kind | null {
  if (review.status === 'stale') return 'stale';
  if (review.status !== 'needs_review') return null;
  return expired ? 'expired' : 'review';
}

/** Epoch seconds of a manifest's approved moment, or `null` when the value cannot be read. */
export function manifestSeconds(utc: string) {
  const parsed = Date.parse(utc);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

/** Refresh the snapshot while the worker is about to act or is acting on a job. */
export const LIVE_AHEAD_SECONDS = 5 * 60;
/** A waiting job this far past its time is left to the backend, which holds it after its approval expires. */
export const LIVE_OVERDUE_SECONDS = 60 * 60;

export function jobNeedsLiveRefresh(job: Job, nowSeconds: number) {
  if (IN_FLIGHT_STATES.has(job.state)) return true;
  if (!WAITING_STATES.has(job.state)) return false;
  const at = manifestSeconds(job.manifest.timing.utc);
  if (at === null) return false;
  return at - nowSeconds <= LIVE_AHEAD_SECONDS && nowSeconds - at <= LIVE_OVERDUE_SECONDS;
}
