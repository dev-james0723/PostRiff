import type { CalendarCardSourceState, CalendarCardStatus } from '../../lib/site-agent/types';

export const CALENDAR_STATUS_META: Record<
  CalendarCardStatus,
  {
    label: string;
    tone: 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'loading';
    pulse?: boolean;
  }
> = {
  scheduled: { label: 'Scheduled', tone: 'info' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'warning' },
  in_flight: { label: 'In flight', tone: 'loading', pulse: true },
  failed_held_uncertain: { label: 'Failed / held / uncertain', tone: 'warning' },
  published: { label: 'Published, confirming', tone: 'info' },
  verified: { label: 'Verified live', tone: 'success' },
  unknown: { label: 'Unknown state', tone: 'warning' }
};

export const QUEUE_COUNT_META = [
  ['awaitingApproval', 'awaiting approval'],
  ['needsAttention', 'need attention'],
  ['inFlight', 'in flight'],
  ['published', 'published, confirming'],
  ['verified', 'verified live']
] as const;

/** Zero is real; missing, malformed and negative values stay visibly unavailable. */
export function calendarCountText(value: unknown): string {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? String(value) : '—';
}

export function calendarCountAria(label: string, value: unknown): string {
  return calendarCountText(value) === '—' ? `${label}: count unavailable` : `${label}: ${value}`;
}

export function calendarSourceText(
  calendar: CalendarCardSourceState,
  queue: CalendarCardSourceState
): string {
  if (calendar !== 'verified') return 'Calendar state could not be verified.';
  if (queue !== 'verified') return 'Calendar verified · queue count unavailable';
  return 'Calendar verified · queue checked';
}
