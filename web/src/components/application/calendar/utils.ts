import {
  endOfMonth,
  endOfWeek,
  startOfMonth,
  startOfWeek,
  toCalendarDate,
  type CalendarDate,
  type DayOfWeek,
  type ZonedDateTime
} from '@internationalized/date';
import type { CalendarEvent, CalendarView } from './config';

/** Every day from `start` to `end`, both included. */
export function daysBetween(start: CalendarDate, end: CalendarDate): CalendarDate[] {
  const days: CalendarDate[] = [];
  for (let day = start; day.compare(end) <= 0; day = day.add({ days: 1 })) days.push(day);
  return days;
}

/** The days a view lays out: whole weeks around the month, the week, or the one day. */
export function gridDays(view: CalendarView, date: CalendarDate, locale: string, firstDayOfWeek: DayOfWeek) {
  if (view === 'month') {
    return daysBetween(
      startOfWeek(startOfMonth(date), locale, firstDayOfWeek),
      endOfWeek(endOfMonth(date), locale, firstDayOfWeek)
    );
  }
  if (view === 'week') return daysBetween(startOfWeek(date, locale, firstDayOfWeek), endOfWeek(date, locale, firstDayOfWeek));
  return [date];
}

/** The period a view covers, for the header's range line. */
export function visibleRange(view: CalendarView, date: CalendarDate, locale: string, firstDayOfWeek: DayOfWeek) {
  if (view === 'month') return { start: startOfMonth(date), end: endOfMonth(date) };
  if (view === 'week') return { start: startOfWeek(date, locale, firstDayOfWeek), end: endOfWeek(date, locale, firstDayOfWeek) };
  return { start: date, end: date };
}

/** One period back or forward. Months keep the day where they can (31 January + 1 month is 28 February). */
export function shiftPeriod(view: CalendarView, date: CalendarDate, step: 1 | -1) {
  if (view === 'month') return date.add({ months: step });
  if (view === 'week') return date.add({ weeks: step });
  return date.add({ days: step });
}

/** ISO 8601 week number (weeks start on Monday; week 1 holds the year's first Thursday). */
export function isoWeek(date: CalendarDate) {
  const thursday = new Date(Date.UTC(date.year, date.month - 1, date.day));
  thursday.setUTCDate(thursday.getUTCDate() + 4 - (thursday.getUTCDay() || 7));
  const yearStart = Date.UTC(thursday.getUTCFullYear(), 0, 1);
  return Math.ceil(((thursday.getTime() - yearStart) / 86_400_000 + 1) / 7);
}

/** `YYYY-MM-DD` of the day a moment falls on, in its own zone. */
export function dayKey(value: ZonedDateTime | CalendarDate) {
  return ('timeZone' in value ? toCalendarDate(value) : value).toString();
}

/** Events keyed by the day they start on (`YYYY-MM-DD`), each day sorted by time. */
export function eventsByDay<T>(events: CalendarEvent<T>[]) {
  const byDay = new Map<string, CalendarEvent<T>[]>();
  const sorted = events.toSorted((a, b) => a.start.compare(b.start));
  for (const event of sorted) {
    const key = dayKey(event.start);
    const list = byDay.get(key);
    if (list) list.push(event);
    else byDay.set(key, [event]);
  }
  return byDay;
}

export function minutesIntoDay(value: ZonedDateTime) {
  return value.hour * 60 + value.minute;
}

export interface PositionedEvent<T> {
  event: CalendarEvent<T>;
  /** Pixels from midnight. */
  top: number;
  height: number;
  /** Side-by-side slot inside a run of overlapping events. */
  lane: number;
  lanes: number;
}

const DAY_MINUTES = 24 * 60;

/**
 * Places one day's events on the time ruler. Overlapping events share the column: each takes the first
 * lane that is free at its start, and the whole overlapping run splits the width by its lane count.
 */
export function layoutDay<T>(events: CalendarEvent<T>[], hourHeight: number, minMinutes: number): PositionedEvent<T>[] {
  const spans = events
    .map((event) => {
      const endsSameDay = event.end && dayKey(event.end) === dayKey(event.start);
      const rawStart = minutesIntoDay(event.start);
      const rawEnd = event.end ? (endsSameDay ? minutesIntoDay(event.end) : DAY_MINUTES) : rawStart;
      const length = Math.max(rawEnd - rawStart, minMinutes);
      // Late moments move up so the block stays inside the day instead of spilling past midnight.
      const start = Math.min(rawStart, DAY_MINUTES - length);
      return { event, start, end: start + length };
    })
    .toSorted((a, b) => a.start - b.start || b.end - a.end);

  const placed: PositionedEvent<T>[] = [];
  let run: { span: (typeof spans)[number]; lane: number }[] = [];
  let laneEnds: number[] = [];
  let runEnd = -1;

  const closeRun = () => {
    for (const { span, lane } of run) {
      placed.push({
        event: span.event,
        top: (span.start / 60) * hourHeight,
        height: ((span.end - span.start) / 60) * hourHeight,
        lane,
        lanes: laneEnds.length
      });
    }
    run = [];
    laneEnds = [];
    runEnd = -1;
  };

  for (const span of spans) {
    if (run.length > 0 && span.start >= runEnd) closeRun();
    let lane = laneEnds.findIndex((end) => end <= span.start);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(span.end);
    } else {
      laneEnds[lane] = span.end;
    }
    run.push({ span, lane });
    runEnd = Math.max(runEnd, span.end);
  }
  closeRun();
  return placed;
}
