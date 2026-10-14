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

const isKnownCount = (value: unknown): value is number => calendarCountText(value) !== '—';

/** Zero tiles say nothing the "nothing scheduled" line or the grid doesn't; unknown and non-zero stay. */
export function visibleCalendarStatuses<T extends { count: unknown }>(statuses: T[] | undefined): T[] {
  return (statuses ?? []).filter((status) => calendarCountText(status.count) !== '0');
}

/** True only for a verified range whose total and every status count are a real 0. */
export function calendarRangeIsEmpty(block: {
  total: unknown;
  statuses?: { count: unknown }[];
  sources?: { calendarRange?: CalendarCardSourceState };
}): boolean {
  return (
    block.sources?.calendarRange === 'verified' &&
    block.total === 0 &&
    (block.statuses ?? []).every((status) => status.count === 0)
  );
}

export function calendarEmptyText(rangeLabel: string): string {
  return `Nothing scheduled in ${rangeLabel}`;
}

export type QueueChip = { key: string; text: string; aria: string };

/** Non-zero and unknown queue counts; all-zero becomes one "Queue clear" chip, all-unknown one "Queue —". */
export function queueChips(queue: Partial<Record<(typeof QUEUE_COUNT_META)[number][0], unknown>> | undefined): QueueChip[] {
  const values = QUEUE_COUNT_META.map(([key, label]) => ({ key, label, value: queue?.[key] }));
  if (values.every(({ value }) => value === 0))
    return [{ key: 'clear', text: 'Queue clear', aria: 'Queue clear: all counts 0' }];
  if (values.every(({ value }) => !isKnownCount(value)))
    return [{ key: 'unknown', text: 'Queue —', aria: 'Queue counts unavailable' }];
  return values
    .filter(({ value }) => value !== 0)
    .map(({ key, label, value }) => ({
      key,
      text: `${calendarCountText(value)} ${label}`,
      aria: calendarCountAria(label, value)
    }));
}

export const WEEKDAY_INITIALS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY_MS = 86_400_000;

function isoDay(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const ms = Date.parse(`${value}T00:00:00Z`);
  return Number.isNaN(ms) || new Date(ms).toISOString().slice(0, 10) !== value ? null : ms;
}

/** "Tue 3 Nov: 2 posts" / "no posts" / "count unavailable" — the cell's accessible name. */
export function calendarDayLabel(date: string, count: unknown): string {
  const ms = isoDay(date);
  const d = ms === null ? null : new Date(ms);
  const name = d ? `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}` : date;
  if (!isKnownCount(count)) return `${name}: count unavailable`;
  return `${name}: ${count === 0 ? 'no posts' : count === 1 ? '1 post' : `${count} posts`}`;
}

export type CalendarGridCell = { date: string; day: number; count: number | null; label: string };

/** Monday-first weeks covering the range; cells outside it are null. Malformed dates are dropped. */
export function calendarGrid(
  days: { date: string; count: number | null }[] | null | undefined
): (CalendarGridCell | null)[][] {
  const byDay = new Map<number, CalendarGridCell>();
  for (const entry of days ?? []) {
    const ms = isoDay(entry?.date);
    if (ms === null) continue;
    const count = isKnownCount(entry.count) ? entry.count : null;
    byDay.set(ms, {
      date: entry.date,
      day: new Date(ms).getUTCDate(),
      count,
      label: calendarDayLabel(entry.date, count)
    });
  }
  if (!byDay.size) return [];
  const keys = [...byDay.keys()];
  const first = Math.min(...keys);
  const last = Math.max(...keys);
  const start = first - ((new Date(first).getUTCDay() + 6) % 7) * DAY_MS;
  const weeks: (CalendarGridCell | null)[][] = [];
  for (let cursor = start; cursor <= last; cursor += 7 * DAY_MS)
    weeks.push(Array.from({ length: 7 }, (_, i) => byDay.get(cursor + i * DAY_MS) ?? null));
  return weeks;
}

export function calendarSourceText(
  calendar: CalendarCardSourceState,
  queue: CalendarCardSourceState
): string {
  if (calendar !== 'verified') return 'Calendar state could not be verified.';
  if (queue !== 'verified') return 'Calendar verified · queue count unavailable';
  return 'Calendar verified · queue checked';
}
