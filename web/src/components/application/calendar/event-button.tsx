'use client';

import type { CSSProperties, ReactNode } from 'react';
import { useDateFormatter } from '@react-aria/i18n';
import { Icons, type Icon } from '@/components/icons';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { EVENT_TONES, type CalendarDetailsContext, type CalendarEvent, type CalendarEventTone } from './config';

/** The glyph that carries a tone's meaning beside the status text (DNA §4.3: never a bare grey dot). */
export const TONE_ICONS: Record<CalendarEventTone, Icon> = {
  quiet: Icons.circleDashed,
  neutral: Icons.clock,
  active: Icons.spinner,
  attention: Icons.warning,
  success: Icons.circleCheck,
  failure: Icons.circleX
};

export function ToneIcon({ tone, className }: { tone: CalendarEventTone; className?: string }) {
  const Glyph = TONE_ICONS[tone];
  return <Glyph aria-hidden className={cn('shrink-0', tone === 'active' && 'rafii-decorative-motion animate-spin motion-reduce:animate-none', className)} />;
}

interface EventButtonProps<T> {
  event: CalendarEvent<T>;
  /** `chip`: one 26px line for month cells. `block`: title over time, sized by the caller on the time ruler. */
  variant: 'chip' | 'block';
  timeZone: string;
  renderDetails?: (event: CalendarEvent<T>, context: CalendarDetailsContext) => ReactNode;
  /** Narrow week columns on phones keep only the material and glyph; the accessible name still says everything. */
  compact?: boolean;
  tabIndex?: number;
  className?: string;
  style?: CSSProperties;
}

export function EventButton<T>({
  event,
  variant,
  timeZone,
  renderDetails,
  compact = false,
  tabIndex,
  className,
  style
}: EventButtonProps<T>) {
  const timeFormatter = useDateFormatter({ hour: 'numeric', minute: '2-digit', timeZone });
  const time = timeFormatter.format(event.start.toDate());
  const label = [event.title, event.status, time].filter(Boolean).join(', ');

  const classes = cn(
    'rafii-focus flex min-w-0 rounded-[var(--rafii-radius-micro)] text-left text-xs transition-colors',
    EVENT_TONES[event.tone].chip,
    variant === 'chip' ? 'h-[26px] w-full items-center gap-1.5 px-1.5' : 'flex-col overflow-hidden px-2 py-1',
    className
  );

  const body =
    variant === 'chip' ? (
      <>
        {event.icon}
        <ToneIcon tone={event.tone} className='size-3' />
        <span className='min-w-0 flex-1 truncate font-medium'>{event.title}</span>
        <span className='shrink-0 tabular-nums'>{time}</span>
      </>
    ) : (
      <span className={cn('flex min-w-0 flex-col gap-0.5', compact && 'max-sm:hidden')}>
        <span className='flex min-w-0 items-center gap-1.5'>
          {event.icon}
          <ToneIcon tone={event.tone} className='size-3' />
          <span className='truncate font-medium'>{event.title}</span>
        </span>
        <span className='tabular-nums'>{time}</span>
      </span>
    );

  if (!renderDetails) {
    return (
      <div className={classes} style={style}>
        <span className='sr-only'>{label}</span>
        <span aria-hidden className='contents'>
          {body}
        </span>
      </div>
    );
  }

  return (
    <Popover>
      <PopoverTrigger data-tour='calendar-event' aria-label={label} tabIndex={tabIndex} className={classes} style={style}>
        {body}
      </PopoverTrigger>
      <PopoverContent align='start' className='rafii-elevated w-auto max-w-[calc(100vw-1rem)] rounded-[1.375rem] p-4 shadow-none ring-0'>
        {renderDetails(event, 'popover')}
      </PopoverContent>
    </Popover>
  );
}
