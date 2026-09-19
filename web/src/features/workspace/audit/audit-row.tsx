'use client';

import type { ComponentProps } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Badge } from '@/components/ui/badge';
import type { AuditEvent } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { describeAuditEvent, personOf, personText, timeOfDay, type AuditLookup, type Person } from './audit-model';

/**
 * "You", "System", a member's profile name with their role, or (when they set no name) their role with the
 * start of their id. Never an email address.
 */
export function PersonChip({ person, className, ...props }: { person: Person; className?: string } & ComponentProps<'span'>) {
  if (person.kind === 'you' || person.kind === 'system') {
    return (
      <span {...props} className={cn('inline-flex', className)} title={person.explains}>
        <Badge variant={person.kind === 'you' ? 'secondary' : 'outline'}>{person.name}</Badge>
      </span>
    );
  }
  return (
    <span
      {...props}
      className={cn('inline-flex max-w-full min-w-0 items-baseline gap-1 text-xs whitespace-nowrap', className)}
      title={person.role ? `${personText(person)}. ${person.explains}` : person.explains}
    >
      <span className='text-foreground min-w-0 truncate'>{person.name}</span>
      {person.role ? (
        <span className='text-muted-foreground shrink-0'>{person.role}</span>
      ) : (
        <span className='text-muted-foreground shrink-0 font-mono'>{person.short}</span>
      )}
    </span>
  );
}

/**
 * One event: the sentence, what it was about, who did it and when. The whole row is one button that
 * opens the detail sheet, so nothing interactive nests inside it.
 */
export function AuditRow({
  event,
  lookup,
  now,
  onOpen,
  tour,
  enterDelay
}: {
  event: AuditEvent;
  lookup: AuditLookup;
  now: number;
  onOpen: () => void;
  /** First row on the page: carries the tour anchors. */
  tour: boolean;
  /** Seconds to wait before sliding in; null for rows already on screen when the page loaded. */
  enterDelay: number | null;
}) {
  const reduce = useReducedMotion();
  const described = describeAuditEvent(event, lookup);
  const person = personOf(event.actor, lookup);
  const iso = new Date(event.at * 1000).toISOString();
  const absolute = formatDateTime(event.at);

  return (
    <motion.li
      initial={enterDelay === null ? false : { opacity: 0, y: reduce ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: enterDelay ?? 0, ease: EASE_OUT }}
      data-tour={tour ? 'audit-row' : undefined}
    >
      <button
        type='button'
        onClick={onOpen}
        className='hover:bg-muted/50 focus-visible:ring-ring/50 flex w-full flex-wrap items-start gap-x-3 gap-y-1 px-3 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset sm:flex-nowrap sm:items-center sm:px-4'
      >
        <span className='order-1 flex min-w-0 flex-[1_1_calc(100%-2rem)] flex-col gap-0.5 sm:order-2 sm:flex-1'>
          <span className='flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1'>
            {described.tone === 'warning' && (
              <AnimatedBadge status='warning' size='sm' pulse={false} aria-hidden title='Worth a second look' className='px-1.5' />
            )}
            <span className='text-sm font-medium break-words'>
              {described.tone === 'warning' && <span className='sr-only'>Worth a second look: </span>}
              {described.headline}
            </span>
          </span>
          {described.detail && <span className='text-muted-foreground text-xs break-words'>{described.detail}</span>}
        </span>
        <Icons.chevronRight aria-hidden className='text-muted-foreground order-2 mt-0.5 size-4 shrink-0 sm:order-4 sm:mt-0' />
        <PersonChip person={person} data-tour={tour ? 'audit-actor' : undefined} className='order-3 sm:w-40 sm:shrink-0 sm:justify-end' />
        <span className='text-muted-foreground order-4 flex items-baseline gap-1.5 text-xs sm:order-1 sm:w-24 sm:shrink-0 sm:flex-col sm:gap-0'>
          <time dateTime={iso} title={absolute} className='text-foreground tabular-nums sm:text-sm'>
            {timeOfDay(event.at)}
          </time>
          <span aria-hidden className='sm:hidden'>
            ·
          </span>
          <span>{relativeTime(event.at, now)}</span>
        </span>
        <span className='sr-only'>Open details</span>
      </button>
    </motion.li>
  );
}
