import type { ReactNode } from 'react';
import type { DayOfWeek, ZonedDateTime } from '@internationalized/date';

export type CalendarView = 'month' | 'week' | 'day';

export const CALENDAR_VIEWS: { value: CalendarView; label: string }[] = [
  { value: 'month', label: 'Month view' },
  { value: 'week', label: 'Week view' },
  { value: 'day', label: 'Day view' }
];

/** Nine event colours. `gray` and `brand` follow the active theme; the rest are fixed hues. */
export type CalendarEventColor =
  | 'gray'
  | 'brand'
  | 'red'
  | 'orange'
  | 'yellow'
  | 'green'
  | 'blue'
  | 'indigo'
  | 'pink';

/** `chip` styles the month chip and the week/day block (with its hover state); `dot` is the mobile month marker. */
export const EVENT_COLORS: Record<CalendarEventColor, { chip: string; dot: string }> = {
  gray: {
    chip: 'border-border bg-muted text-foreground hover:bg-accent',
    dot: 'bg-muted-foreground'
  },
  brand: {
    chip: 'border-primary/25 bg-primary/10 text-primary hover:bg-primary/15',
    dot: 'bg-primary'
  },
  red: {
    chip: 'border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300 dark:hover:bg-red-500/20',
    dot: 'bg-red-500'
  },
  orange: {
    chip: 'border-orange-200 bg-orange-50 text-orange-700 hover:bg-orange-100 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300 dark:hover:bg-orange-500/20',
    dot: 'bg-orange-500'
  },
  yellow: {
    chip: 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/20',
    dot: 'bg-amber-500'
  },
  green: {
    chip: 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:bg-emerald-500/20',
    dot: 'bg-emerald-500'
  },
  blue: {
    chip: 'border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300 dark:hover:bg-sky-500/20',
    dot: 'bg-sky-500'
  },
  indigo: {
    chip: 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300 dark:hover:bg-indigo-500/20',
    dot: 'bg-indigo-500'
  },
  pink: {
    chip: 'border-pink-200 bg-pink-50 text-pink-700 hover:bg-pink-100 dark:border-pink-500/30 dark:bg-pink-500/10 dark:text-pink-300 dark:hover:bg-pink-500/20',
    dot: 'bg-pink-500'
  }
};

export interface CalendarEvent<TData = unknown> {
  id: string;
  title: string;
  /** The exact moment, already in the zone the calendar shows. */
  start: ZonedDateTime;
  /** Leave out for moments (a post goes out at one time); the block then takes `MIN_EVENT_MINUTES`. */
  end?: ZonedDateTime;
  color: CalendarEventColor;
  /** Read with the title, so colour never carries the meaning alone. */
  status?: string;
  /** Leading visual, e.g. a channel icon. Decorative: keep it `aria-hidden`. */
  icon?: ReactNode;
  data?: TData;
}

/** Where event details render: a popover from a chip or block, or the day view's list. */
export type CalendarDetailsContext = 'popover' | 'list';

/** Week and day views are a ruler: 96px per hour, so a 30 minute block is 48px. */
export const HOUR_HEIGHT = 96;

/** Moments and very short events still get a block tall enough for a title and a time. */
export const MIN_EVENT_MINUTES = 30;

/** Month cells show this many chips; a busier day shows one fewer plus a "+N more" link to the day. */
export const MONTH_CHIP_LIMIT = 3;

export const DEFAULT_LOCALE = 'en';

export const DEFAULT_FIRST_DAY_OF_WEEK: DayOfWeek = 'mon';
