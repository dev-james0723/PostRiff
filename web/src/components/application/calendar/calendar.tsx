'use client';

/**
 * Month, week and day calendar laid out after the Untitled UI calendar anatomy: a one-row header with
 * today's date icon, period title, range line, prev/Today/next group and a view dropdown; month cells with
 * 26px chips and a "+N more" link; week and day views on a 96px-per-hour ruler with a now marker; a day
 * panel with a month picker. Dates are `@internationalized/date` values; wording and weekday names come
 * from `@react-aria/i18n`. See README.md for the API.
 */

import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import {
  getLocalTimeZone,
  now,
  today,
  type CalendarDate,
  type DayOfWeek,
  type ZonedDateTime
} from '@internationalized/date';
import { I18nProvider, useDateFormatter } from '@react-aria/i18n';
import { AnimatePresence, motion, useReducedMotion, type Variants } from 'motion/react';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { EASE_OUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import {
  CALENDAR_VIEWS,
  DEFAULT_FIRST_DAY_OF_WEEK,
  DEFAULT_LOCALE,
  type CalendarDetailsContext,
  type CalendarEvent,
  type CalendarView
} from './config';
import { MiniCalendar } from './mini-calendar';
import { MonthView } from './month-view';
import { TimeGrid } from './time-grid';
import { eventsByDay, gridDays, isoWeek, shiftPeriod, visibleRange } from './utils';

export interface CalendarProps<T = unknown> {
  events: CalendarEvent<T>[];
  view: CalendarView;
  onViewChange: (view: CalendarView) => void;
  /** The day the views centre on: its month, its week, or the day itself. */
  focusedDate: CalendarDate;
  onFocusedDateChange: (date: CalendarDate) => void;
  /** IANA zone the grid is drawn in. Event times must already be in this zone. */
  timeZone: string;
  locale?: string;
  firstDayOfWeek?: DayOfWeek;
  /** Last item in the header, e.g. a "New event" button. */
  headerAction?: ReactNode;
  /** Content for an event's popover and for its card in the day panel. */
  renderEventDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
  /** Under the day panel's list. */
  dayPanelFooter?: ReactNode;
  /** What an event is called in counts and empty states. */
  noun?: { one: string; other: string };
  className?: string;
}

const PERIOD_VARIANTS: Variants = {
  enter: (direction: number) => ({ opacity: 0, x: direction * 16 }),
  center: { opacity: 1, x: 0 },
  exit: (direction: number) => ({ opacity: 0, x: direction * -16 })
};

export function Calendar<T>({ locale = DEFAULT_LOCALE, ...props }: CalendarProps<T>) {
  return (
    <I18nProvider locale={locale}>
      <CalendarFrame locale={locale} {...props} />
    </I18nProvider>
  );
}

/** The current time in `timeZone`, refreshed every 30 seconds. `null` on the server and the first client render. */
export function useCurrentTime(timeZone: string) {
  const [value, setValue] = useState<ZonedDateTime | null>(null);
  useEffect(() => {
    const tick = () => setValue(now(timeZone));
    tick();
    const timer = window.setInterval(tick, 30_000);
    return () => window.clearInterval(timer);
  }, [timeZone]);
  return value;
}

function CalendarFrame<T>({
  events,
  view,
  onViewChange,
  focusedDate,
  onFocusedDateChange,
  timeZone,
  locale,
  firstDayOfWeek = DEFAULT_FIRST_DAY_OF_WEEK,
  headerAction,
  renderEventDetails,
  dayPanelFooter,
  noun = { one: 'event', other: 'events' },
  className
}: CalendarProps<T> & { locale: string }) {
  const reduce = useReducedMotion();
  const titleId = useId();
  const [direction, setDirection] = useState(0);
  const keyboardMove = useRef(false);
  const currentTime = useCurrentTime(timeZone);
  const byDay = useMemo(() => eventsByDay(events), [events]);
  const days = useMemo(
    () => gridDays(view, focusedDate, locale, firstDayOfWeek),
    [view, focusedDate, locale, firstDayOfWeek]
  );

  const countLabel = (count: number) => (count === 0 ? `no ${noun.other}` : `${count} ${count === 1 ? noun.one : noun.other}`);

  // Later periods enter from the right and earlier ones from the left; a view switch only fades.
  function goTo(date: CalendarDate) {
    setDirection(Math.sign(date.compare(focusedDate)));
    onFocusedDateChange(date);
  }

  function openDay(date: CalendarDate) {
    setDirection(0);
    onFocusedDateChange(date);
    onViewChange('day');
  }

  const slide = (content: ReactNode) => (
    <div className='relative min-w-0 overflow-hidden'>
      <AnimatePresence mode='popLayout' initial={false} custom={reduce ? 0 : direction}>
        <motion.div
          key={`${view}:${days[0].toString()}`}
          custom={reduce ? 0 : direction}
          variants={PERIOD_VARIANTS}
          initial='enter'
          animate='center'
          exit='exit'
          transition={{ duration: reduce ? 0.12 : 0.24, ease: EASE_OUT }}
        >
          {content}
        </motion.div>
      </AnimatePresence>
    </div>
  );

  return (
    <section
      aria-labelledby={titleId}
      className={cn('bg-card text-card-foreground overflow-hidden rounded-xl border shadow-xs', className)}
    >
      <CalendarHeader
        view={view}
        focusedDate={focusedDate}
        timeZone={timeZone}
        locale={locale}
        firstDayOfWeek={firstDayOfWeek}
        titleId={titleId}
        action={headerAction}
        onPrevious={() => goTo(shiftPeriod(view, focusedDate, -1))}
        onNext={() => goTo(shiftPeriod(view, focusedDate, 1))}
        onToday={() => goTo(today(timeZone))}
        onViewChange={(next) => {
          setDirection(0);
          onViewChange(next);
        }}
      />

      {view === 'month' &&
        slide(
          <MonthView
            days={days}
            focusedDate={focusedDate}
            byDay={byDay}
            timeZone={timeZone}
            firstDayOfWeek={firstDayOfWeek}
            labelledBy={titleId}
            keyboardMove={keyboardMove}
            countLabel={countLabel}
            onFocusedDateChange={goTo}
            onOpenDay={openDay}
            renderDetails={renderEventDetails}
          />
        )}

      {view === 'week' &&
        slide(
          <TimeGrid
            days={days}
            focusedDate={focusedDate}
            byDay={byDay}
            timeZone={timeZone}
            currentTime={currentTime}
            countLabel={countLabel}
            onOpenDay={openDay}
            renderDetails={renderEventDetails}
          />
        )}

      {view === 'day' && (
        <div className='grid lg:grid-cols-[minmax(0,1fr)_20rem]'>
          {slide(
            <TimeGrid
              days={days}
              focusedDate={focusedDate}
              byDay={byDay}
              timeZone={timeZone}
              currentTime={currentTime}
              countLabel={countLabel}
              renderDetails={renderEventDetails}
            />
          )}
          <DayPanel
            date={focusedDate}
            byDay={byDay}
            timeZone={timeZone}
            firstDayOfWeek={firstDayOfWeek}
            noun={noun}
            countLabel={countLabel}
            onPick={goTo}
            renderDetails={renderEventDetails}
            footer={dayPanelFooter}
          />
        </div>
      )}
    </section>
  );
}

interface CalendarHeaderProps {
  view: CalendarView;
  focusedDate: CalendarDate;
  timeZone: string;
  locale: string;
  firstDayOfWeek: DayOfWeek;
  titleId: string;
  action?: ReactNode;
  onPrevious: () => void;
  onNext: () => void;
  onToday: () => void;
  onViewChange: (view: CalendarView) => void;
}

function CalendarHeader({
  view,
  focusedDate,
  timeZone,
  locale,
  firstDayOfWeek,
  titleId,
  action,
  onPrevious,
  onNext,
  onToday,
  onViewChange
}: CalendarHeaderProps) {
  const monthTitle = useDateFormatter({ month: 'long', year: 'numeric', timeZone });
  const dayTitle = useDateFormatter({ month: 'long', day: 'numeric', year: 'numeric', timeZone });
  const rangeLine = useDateFormatter({ month: 'short', day: 'numeric', year: 'numeric', timeZone });
  const weekdayLine = useDateFormatter({ weekday: 'long', timeZone });

  const range = visibleRange(view, focusedDate, locale, firstDayOfWeek);
  const start = range.start.toDate(timeZone);
  const end = range.end.toDate(timeZone);
  const title =
    view === 'day'
      ? dayTitle.format(start)
      : view === 'week'
        ? monthTitle.formatRange(start, end)
        : monthTitle.format(start);
  const subtitle = view === 'day' ? weekdayLine.format(start) : rangeLine.formatRange(start, end);
  const unit = view === 'month' ? 'month' : view === 'week' ? 'week' : 'day';

  return (
    <header className='flex flex-col gap-4 border-b p-4 lg:flex-row lg:items-center lg:justify-between lg:px-6 lg:py-5'>
      <div className='flex min-w-0 items-center gap-3'>
        <TodayIcon timeZone={timeZone} />
        <div className='min-w-0'>
          <div className='flex flex-wrap items-center gap-2'>
            <h2 id={titleId} aria-live='polite' className='text-lg font-semibold'>
              {title}
            </h2>
            {view !== 'month' && firstDayOfWeek === 'mon' && (
              <Badge variant='outline'>Week {isoWeek(range.start)}</Badge>
            )}
          </div>
          <p className='text-muted-foreground text-sm'>{subtitle}</p>
        </div>
      </div>

      <div className='flex flex-wrap items-center gap-2 md:gap-3'>
        <ButtonGroup aria-label='Change period'>
          <Button variant='outline' size='icon' aria-label={`Previous ${unit}`} onClick={onPrevious}>
            <Icons.chevronLeft />
          </Button>
          <Button variant='outline' onClick={onToday}>
            Today
          </Button>
          <Button variant='outline' size='icon' aria-label={`Next ${unit}`} onClick={onNext}>
            <Icons.chevronRight />
          </Button>
        </ButtonGroup>
        <Select value={view} onValueChange={(value) => onViewChange(value as CalendarView)}>
          <SelectTrigger aria-label='Calendar view' className='w-32'>
            <SelectValue>{CALENDAR_VIEWS.find((option) => option.value === view)?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {CALENDAR_VIEWS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {action}
      </div>
    </header>
  );
}

/** Today's month and day, the small date tile at the start of the header. */
function TodayIcon({ timeZone }: { timeZone: string }) {
  const monthShort = useDateFormatter({ month: 'short', timeZone });
  const date = today(timeZone);

  return (
    <div aria-hidden className='bg-background hidden w-14 shrink-0 flex-col overflow-hidden rounded-lg border text-center shadow-xs sm:flex'>
      <span className='bg-muted text-muted-foreground py-0.5 text-[10px] font-semibold tracking-wide uppercase'>
        {monthShort.format(date.toDate(timeZone))}
      </span>
      <span className='text-primary py-1 text-lg leading-6 font-bold tabular-nums'>{date.day}</span>
    </div>
  );
}

interface DayPanelProps<T> {
  date: CalendarDate;
  byDay: Map<string, CalendarEvent<T>[]>;
  timeZone: string;
  firstDayOfWeek: DayOfWeek;
  noun: { one: string; other: string };
  countLabel: (count: number) => string;
  onPick: (date: CalendarDate) => void;
  renderDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
  footer?: ReactNode;
}

function DayPanel<T>({ date, byDay, timeZone, firstDayOfWeek, noun, countLabel, onPick, renderDetails, footer }: DayPanelProps<T>) {
  const reduce = useReducedMotion();
  const headingId = useId();
  const heading = useDateFormatter({ weekday: 'long', month: 'long', day: 'numeric', timeZone });
  const time = useDateFormatter({ hour: 'numeric', minute: '2-digit', timeZone });
  const markedDays = useMemo(() => new Set(byDay.keys()), [byDay]);
  const events = byDay.get(date.toString()) ?? [];
  const count = countLabel(events.length);

  return (
    <aside className='flex min-w-0 flex-col gap-5 border-t p-4 lg:border-t-0 lg:border-l'>
      <MiniCalendar
        className='max-lg:hidden'
        value={date}
        onChange={onPick}
        timeZone={timeZone}
        markedDays={markedDays}
        firstDayOfWeek={firstDayOfWeek}
      />
      <section aria-labelledby={headingId} className='flex flex-col gap-3 lg:border-t lg:pt-5'>
        <div>
          <h3 id={headingId} className='text-sm font-semibold'>
            {heading.format(date.toDate(timeZone))}
          </h3>
          <p className='text-muted-foreground text-xs'>
            {events.length === 0 ? `No ${noun.other} on this day.` : `${count.charAt(0).toUpperCase()}${count.slice(1)}`}
          </p>
        </div>
        {events.length > 0 && (
          <ul className='flex flex-col gap-2'>
            {events.map((event, index) => (
              <motion.li
                // Keyed by day too, so picking another day plays the entrance again.
                key={`${date.toString()}:${event.id}`}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.22, ease: EASE_OUT, delay: Math.min(index, 7) * 0.04 }}
                className='rounded-lg border p-3 text-sm'
              >
                {renderDetails ? (
                  renderDetails(event, 'list')
                ) : (
                  <p className='flex items-center gap-2'>
                    {event.icon}
                    <span className='min-w-0 flex-1 truncate font-medium'>{event.title}</span>
                    <span className='text-muted-foreground text-xs tabular-nums'>{time.format(event.start.toDate())}</span>
                  </p>
                )}
              </motion.li>
            ))}
          </ul>
        )}
        {footer}
      </section>
    </aside>
  );
}

const subscribeToNothing = () => () => {};

/**
 * This browser's IANA time zone, or `null` on the server and while hydrating, so nothing zone-dependent is
 * rendered into HTML that the client would then disagree with.
 */
export function useLocalTimeZone() {
  return useSyncExternalStore(subscribeToNothing, getLocalTimeZone, () => null);
}
