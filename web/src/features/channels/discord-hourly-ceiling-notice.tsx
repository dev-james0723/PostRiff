'use client';

import Link from 'next/link';
import { useId, useLayoutEffect, useRef, type ComponentProps } from 'react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { hourlyCeilingBody, type DiscordCopy } from '@/lib/channels/discord-copy';
import { hourlyCeilingState, type CeilingPlace } from '@/lib/channels/discord-hourly-ceiling';
import { cn } from '@/lib/utils';
import { DIALOG_ELEVATED, DIALOG_FOOTER_PLAIN } from './rafii-materials';

/**
 * What a person sees when the Discord hourly ceiling refuses an approval (`discord_workspace_hourly_ceiling`,
 * docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md): the title, the rule with its number, what is left undone,
 * and the ways to change the plan. There is deliberately no retry button, countdown or automatic retry here: waiting
 * does not free a future hour, and sending the same request again gets the same answer.
 */

export interface CeilingActions {
  /** A route to the draft, or what the caller does instead (the reply dialog goes back to its time field). */
  chooseTime?: { href: string } | { onClick: () => void };
  /** The Calendar day of the post. `many` says it for a selection that may span several hours. */
  see?: { href: string; many?: boolean };
  /** Called when a link is followed, so a dialog that stays mounted on the same page closes. */
  onNavigate?: () => void;
}

interface CeilingProps {
  copy: DiscordCopy;
  place: CeilingPlace;
  limit: number;
  /** The Queue move sentence: the earlier time is already cancelled. Only places where a post can be a move say it. */
  moving?: boolean;
  actions?: CeilingActions;
}

/** 48px targets that may wrap: the longest label is "See the posts in that hour". */
const ACTION = 'h-auto min-h-12 whitespace-normal py-2 text-center';
/** The 44px minimum, for a line of small text (the post card) whose other buttons are `sm` with `min-h-11`. */
const ACTION_COMPACT = 'h-auto min-h-11 whitespace-normal px-3 py-1.5 text-center';

function CeilingText({ copy, place, moving, className }: Pick<CeilingProps, 'copy' | 'place' | 'moving'> & { className?: string }) {
  return (
    <>
      <p data-hourly-ceiling-state className={cn('text-sm font-medium', className)}>
        {hourlyCeilingState(copy, place)}
      </p>
      {moving && (
        <p data-hourly-ceiling-moved className='text-muted-foreground text-xs'>
          {copy.hourlyCeilingMoved}
        </p>
      )}
    </>
  );
}

export function HourlyCeilingActions({ copy, actions, compact }: { copy: DiscordCopy; actions?: CeilingActions; compact?: boolean }) {
  const chooseTime = actions?.chooseTime;
  const see = actions?.see;
  if (!chooseTime && !see) return null;
  const onNavigate = actions?.onNavigate;
  const size = compact ? 'sm' : 'control';
  const sizing = compact ? ACTION_COMPACT : ACTION;
  return (
    <div data-hourly-ceiling-actions className='flex flex-wrap gap-2'>
      {chooseTime &&
        ('href' in chooseTime ? (
          <Link
            href={chooseTime.href}
            onClick={onNavigate}
            data-hourly-ceiling-action='choose-time'
            className={cn(buttonVariants({ variant: 'glass', size }), sizing)}
          >
            {copy.hourlyCeilingChooseTime}
          </Link>
        ) : (
          <Button type='button' variant='glass' size={size} className={sizing} data-hourly-ceiling-action='choose-time' onClick={chooseTime.onClick}>
            {copy.hourlyCeilingChooseTime}
          </Button>
        ))}
      {see && (
        <Link
          href={see.href}
          onClick={onNavigate}
          data-hourly-ceiling-action='see-posts'
          className={cn(buttonVariants({ variant: 'glass', size }), sizing)}
        >
          {see.many ? copy.hourlyCeilingSeePostsMany : copy.hourlyCeilingSeePosts}
        </Link>
      )}
    </div>
  );
}

/**
 * The refusal inside a screen that stays open (the bulk approval, the automation decision, the reply review). It
 * announces itself and takes keyboard focus, because the button that was pressed is disabled by now.
 */
export function HourlyCeilingNotice({ copy, place, limit, moving, actions, className }: CeilingProps & { className?: string }) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const section = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    heading.current?.focus({ preventScroll: true });
    // The whole explanation, not just its first line, comes into view inside a dialog that scrolls.
    section.current?.scrollIntoView({ block: 'nearest' });
  }, []);
  return (
    <section
      ref={section}
      role='alert'
      aria-labelledby={`${id}-title`}
      data-hourly-ceiling
      data-place={place}
      className={cn('flex flex-col gap-2 rounded-lg border p-3', className)}
    >
      <h3 id={`${id}-title`} ref={heading} tabIndex={-1} className='focus-visible:ring-ring/50 rounded text-base font-medium outline-none focus-visible:ring-3'>
        {copy.hourlyCeilingTitle}
      </h3>
      <p data-hourly-ceiling-body className='text-sm'>
        {hourlyCeilingBody(copy, limit)}
      </p>
      <CeilingText copy={copy} place={place} moving={moving} />
      <HourlyCeilingActions copy={copy} actions={actions} />
    </section>
  );
}

/**
 * The refusal of a single approval, in a dialog of its own: the approve button sits in cards of several layouts, and a
 * message that must be read and acted on should not vanish like a toast. Closing it changes nothing.
 */
export function HourlyCeilingDialog({
  open,
  onOpenChange,
  copy,
  place,
  limit,
  moving,
  actions,
  finalFocus
}: CeilingProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Where the keyboard goes on close. The approve button is disabled while it waits for the answer, so the browser has already moved focus off it. */
  finalFocus?: ComponentProps<typeof DialogContent>['finalFocus'];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        finalFocus={finalFocus}
        data-hourly-ceiling-dialog
        data-place={place}
        className={cn(DIALOG_ELEVATED, 'max-h-[calc(100dvh-2rem)] overflow-x-hidden overflow-y-auto sm:max-w-md')}
      >
        <DialogHeader>
          <DialogTitle className='text-lg font-medium tracking-tight'>{copy.hourlyCeilingTitle}</DialogTitle>
          {/* The whole explanation is the dialog's description, so a screen reader announces what was and was not approved with the rule. */}
          <DialogDescription className='flex flex-col gap-2'>
            <span data-hourly-ceiling-body>{hourlyCeilingBody(copy, limit)}</span>
            <span data-hourly-ceiling-state className='text-foreground block font-medium'>
              {hourlyCeilingState(copy, place)}
            </span>
            {moving && (
              <span data-hourly-ceiling-moved className='block text-xs'>
                {copy.hourlyCeilingMoved}
              </span>
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className={cn(DIALOG_FOOTER_PLAIN, 'flex-col sm:flex-row sm:flex-wrap sm:items-center sm:justify-start')}>
          <HourlyCeilingActions copy={copy} actions={{ ...actions, onNavigate: () => { actions?.onNavigate?.(); onOpenChange(false); } }} />
          <Button type='button' variant='quiet' size='control' className='h-12' data-hourly-ceiling-close onClick={() => onOpenChange(false)}>
            {copy.hourlyCeilingClose}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
