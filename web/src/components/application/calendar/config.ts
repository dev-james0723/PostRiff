import type { ReactNode } from 'react';
import type { DayOfWeek, ZonedDateTime } from '@internationalized/date';

export type CalendarView = 'month' | 'week' | 'day';

export const CALENDAR_VIEWS: { value: CalendarView; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'week', label: 'Week' },
  { value: 'day', label: 'Day' }
];

/**
 * Monochrome event tones (Rafii DNA §4.3). The state is always carried by the event's `status` text and the tone's
 * glyph (`event-button.tsx`); the tone only decides how much light a chip catches. `failure` is the one tone with a
 * tint, through the approved `--destructive` token; the others stay grayscale in both themes.
 */
export type CalendarEventTone = 'quiet' | 'neutral' | 'active' | 'attention' | 'success' | 'failure';

/** `chip` styles the month chip and the week/day block (with its hover state); `dot` is the mobile month marker. */
export const EVENT_TONES: Record<CalendarEventTone, { chip: string; dot: string }> = {
  quiet: { chip: 'rafii-quiet text-muted-foreground hover:text-foreground', dot: 'bg-foreground/25' },
  neutral: { chip: 'rafii-quiet text-foreground hover:rafii-glass', dot: 'bg-foreground/55' },
  active: { chip: 'rafii-glass text-foreground hover:rafii-glass-selected', dot: 'bg-foreground/70' },
  attention: { chip: 'rafii-lens text-foreground', dot: 'bg-foreground' },
  success: { chip: 'rafii-quiet text-foreground hover:rafii-glass', dot: 'bg-foreground/40' },
  failure: { chip: 'rafii-quiet text-destructive hover:rafii-glass', dot: 'bg-destructive' }
};

export interface CalendarEvent<TData = unknown> {
  id: string;
  title: string;
  /** The exact moment, already in the zone the calendar shows. */
  start: ZonedDateTime;
  /** Leave out for moments (a post goes out at one time); the block then takes `MIN_EVENT_MINUTES`. */
  end?: ZonedDateTime;
  tone: CalendarEventTone;
  /** Read with the title, so the tone never carries the meaning alone. */
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
