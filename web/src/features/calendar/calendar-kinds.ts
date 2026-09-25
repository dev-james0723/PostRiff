import type { CalendarEventTone } from '@/components/application/calendar/config';
import type { StatusTone } from '@/features/queue/status-chip';
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
  /** How much light the calendar chip catches (`EVENT_TONES`); the label and glyph carry the state. */
  tone: CalendarEventTone;
  /** The status chip's role in details and filters; consistent with `tone` (attention ↔ warning, and so on). */
  status: StatusTone;
}

// Monochrome by rule (DNA §4.3): a state that asks for the person's attention catches the lens, work in progress
// sits on glass, a finished or dead entry stays quiet. Failed and expired are the only tinted ones (`--destructive`).
// Labels use the shared status words (`STATUS` in lib/status-labels.ts), written out here because a Node test
// imports this file directly, without the app's path aliases.
export const KIND_META: Record<Kind, KindMeta> = {
  review: { label: 'Needs review', tone: 'attention', status: 'warning' },
  expired: { label: 'Expired', tone: 'failure', status: 'danger' },
  stale: { label: 'Out of date', tone: 'attention', status: 'warning' },
  waiting: { label: 'Scheduled', tone: 'neutral', status: 'info' },
  held: { label: 'Needs action', tone: 'attention', status: 'warning' },
  'in-flight': { label: 'Publishing', tone: 'active', status: 'loading' },
  processing: { label: 'Preparing media', tone: 'neutral', status: 'info' },
  accepted: { label: 'Checking result', tone: 'neutral', status: 'info' },
  uncertain: { label: 'Result not confirmed', tone: 'attention', status: 'warning' },
  unknown: { label: 'Unknown', tone: 'attention', status: 'warning' },
  assisted: { label: 'Finish in app', tone: 'attention', status: 'warning' },
  manual: { label: 'Marked done', tone: 'quiet', status: 'neutral' },
  verified: { label: 'Published', tone: 'success', status: 'success' },
  failed: { label: 'Failed', tone: 'failure', status: 'danger' },
  canceled: { label: 'Cancelled', tone: 'quiet', status: 'neutral' }
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
