'use client';

/**
 * Month picker for the day view's side panel. Adapted from Untitled UI React (MIT)
 * `components/application/date-picker/{calendar,cell}.tsx`: single selection only, app tokens instead of
 * Untitled UI's, and the dot marks days that have events rather than today. React Aria supplies the grid
 * roles, arrow-key movement between days and the locale's weekday names.
 */

import { useState } from 'react';
import { isToday, type CalendarDate, type DayOfWeek } from '@internationalized/date';
import {
  Button as AriaButton,
  Calendar as AriaCalendar,
  CalendarCell as AriaCalendarCell,
  CalendarGrid as AriaCalendarGrid,
  CalendarGridBody as AriaCalendarGridBody,
  CalendarGridHeader as AriaCalendarGridHeader,
  CalendarHeaderCell as AriaCalendarHeaderCell,
  Heading as AriaHeading
} from 'react-aria-components';
import { Icons } from '@/components/icons';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface MiniCalendarProps {
  value: CalendarDate;
  onChange: (date: CalendarDate) => void;
  /** Decides which cell is today. */
  timeZone: string;
  /** `YYYY-MM-DD` keys of days that get a dot. */
  markedDays?: ReadonlySet<string>;
  firstDayOfWeek?: DayOfWeek;
  className?: string;
}

export function MiniCalendar({ value, onChange, timeZone, markedDays, firstDayOfWeek, className }: MiniCalendarProps) {
  // The shown month follows the value when it changes elsewhere (header arrows, Today), and the arrow keys otherwise.
  const [shown, setShown] = useState(value);
  const [followed, setFollowed] = useState(value);
  if (followed.compare(value) !== 0) {
    setFollowed(value);
    setShown(value);
  }

  return (
    <AriaCalendar
      aria-label='Choose a day'
      value={value}
      onChange={onChange}
      focusedValue={shown}
      onFocusChange={setShown}
      firstDayOfWeek={firstDayOfWeek}
      className={cn('flex flex-col gap-2', className)}
    >
      <header className='flex items-center justify-between'>
        <AriaButton slot='previous' className={buttonVariants({ variant: 'quiet', size: 'icon-control' })}>
          <Icons.chevronLeft />
        </AriaButton>
        <AriaHeading className='text-sm font-medium' />
        <AriaButton slot='next' className={buttonVariants({ variant: 'quiet', size: 'icon-control' })}>
          <Icons.chevronRight />
        </AriaButton>
      </header>
      <AriaCalendarGrid weekdayStyle='short' className='w-full border-separate border-spacing-y-1'>
        <AriaCalendarGridHeader>
          {(day) => (
            <AriaCalendarHeaderCell className='p-0'>
              <div className='text-muted-foreground flex h-9 items-center justify-center text-xs font-medium'>{day.slice(0, 2)}</div>
            </AriaCalendarHeaderCell>
          )}
        </AriaCalendarGridHeader>
        <AriaCalendarGridBody className='[&_td]:p-0'>
          {(date) => (
            <MiniCalendarCell date={date} today={isToday(date, timeZone)} marked={markedDays?.has(date.toString()) ?? false} />
          )}
        </AriaCalendarGridBody>
      </AriaCalendarGrid>
    </AriaCalendar>
  );
}

function MiniCalendarCell({ date, today, marked }: { date: CalendarDate; today: boolean; marked: boolean }) {
  return (
    <AriaCalendarCell
      date={date}
      className={({ isDisabled, isFocusVisible, isOutsideMonth }) =>
        cn(
          'relative mx-auto size-9 focus:outline-hidden',
          isDisabled ? 'pointer-events-none' : 'cursor-pointer',
          isFocusVisible ? 'z-10' : 'z-0',
          isOutsideMonth && 'opacity-50'
        )
      }
    >
      {({ isDisabled, isFocusVisible, isSelected, formattedDate }) => {
        const selected = isSelected && !isDisabled;
        return (
          <div
            className={cn(
              'relative flex size-full items-center justify-center rounded-full text-sm transition-colors',
              isDisabled && 'text-muted-foreground',
              isFocusVisible && 'outline-ring outline-2 outline-offset-2',
              selected && 'rafii-action font-medium',
              !selected && !isDisabled && 'hover:rafii-lens',
              !selected && today && 'rafii-lens font-semibold'
            )}
          >
            {formattedDate}
            {marked && (
              <span
                aria-hidden
                className={cn(
                  'absolute bottom-1 left-1/2 size-[5px] -translate-x-1/2 rounded-full',
                  selected ? 'bg-background' : 'bg-foreground'
                )}
              />
            )}
          </div>
        );
      }}
    </AriaCalendarCell>
  );
}
