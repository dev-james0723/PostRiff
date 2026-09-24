'use client';

/**
 * One column of the draft board: its cards (entrance and glide, lift on hover), the "Show more" limit, the
 * footer group ("Set aside", "Expired", "Cancelled or failed") and the column's call to action. Queue's Drafts
 * tab renders the drafts column with it (Rafii v9 folded the Pipeline board into Queue).
 */
import { useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Button, buttonVariants } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import type { BoardCard, BoardColumn } from './board';
import { PipelineCard, type CardActions, type CardPermissions } from './pipeline-card';

/** Past this many cards a column asks before it renders more. */
const COLUMN_LIMIT = 40;

/** Cards glide into place (DNA §18.6); a long column never staggers its entrance. */
const ENTER_DURATION = 0.18;
/** Closes faster than it opens. */
const EXIT_DURATION = 0.15;


/** The column's quiet reading panel (DNA §5.2): the cards inside are its opaque rows. */
export const COLUMN_CLASS = 'rafii-quiet flex flex-col rounded-[var(--rafii-radius-card)]';

export function ColumnHeader({ column, count }: { column: Pick<BoardColumn, 'key' | 'title' | 'hint'>; count: number | null }) {
  return (
    <header className='px-4 pt-3 pb-1.5'>
      <h3 id={`pipeline-col-${column.key}-title`} className='flex items-center gap-1.5 text-sm font-medium'>
        {column.title}
        {count !== null && <DigitSwap value={count} className='text-muted-foreground font-normal tabular-nums' />}
      </h3>
      <p className='text-muted-foreground text-xs'>{column.hint}</p>
    </header>
  );
}

export interface ColumnViewProps {
  column: BoardColumn;
  platform: string | null;
  now: number;
  permissions: CardPermissions;
  actions: CardActions;
  cancelPending: boolean;
  holdEpoch: number;
  lift: boolean;
  menu: boolean;
  /** On a phone the column is the page: no inner scroll and no fixed width. */
  single: boolean;
}

export function ColumnView({ column, platform, now, permissions, actions, cancelPending, holdEpoch, lift, menu, single }: ColumnViewProps) {
  const reduce = useReducedMotion();
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? column.items : column.items.slice(0, COLUMN_LIMIT);
  const hidden = column.items.length - visible.length;
  const footer = column.footer;
  const emptySentence = platform && column.key !== 'sources' ? `No ${platform} items in this column.` : column.empty;

  const renderCards = (cards: BoardCard[]) => (
    <AnimatePresence mode='popLayout'>
      {cards.map((card) => (
        // Entrance and glide on the wrapper, lift on the card: sharing one element, the entrance would also hold
        // the card up after the pointer leaves.
        <motion.div
          key={card.key}
          layoutId={reduce ? undefined : card.key}
          layout={reduce ? false : 'position'}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0, transition: { duration: ENTER_DURATION, ease: EASE_OUT } }}
          exit={{ opacity: 0, transition: { duration: EXIT_DURATION, ease: EASE_OUT } }}
          transition={{ layout: SPRING_LAYOUT }}
        >
          <PipelineCard card={card} now={now} permissions={permissions} actions={actions} cancelPending={cancelPending} holdEpoch={holdEpoch} lift={lift} menu={menu} />
        </motion.div>
      ))}
    </AnimatePresence>
  );

  return (
    <section
      id={`pipeline-col-${column.key}`}
      data-tour={`pipeline-col-${column.key}`}
      aria-labelledby={`pipeline-col-${column.key}-title`}
      className={cn(COLUMN_CLASS, single ? 'w-full' : 'w-72 shrink-0 snap-start min-[1440px]:w-auto min-[1440px]:min-w-0')}
    >
      <ColumnHeader column={column} count={column.items.length} />
      <motion.div
        layoutScroll
        className={cn('relative flex flex-col gap-2 px-2 pb-2', !single && 'max-h-[calc(100dvh-14rem)] min-h-24 overflow-y-auto')}
      >
        {renderCards(visible)}
        {column.items.length === 0 && <p className='text-muted-foreground px-2 py-3 text-center text-[13px] leading-relaxed text-balance'>{emptySentence}</p>}
        {hidden > 0 && (
          <Button variant='glass' size='control' onClick={() => setShowAll(true)}>
            Show {hidden} more
          </Button>
        )}
        {footer && footer.items.length > 0 && (
          <Collapsible className='rafii-quiet rounded-[var(--rafii-radius-control)]'>
            <CollapsibleTrigger className='group/footer rafii-focus hover:rafii-glass-selected flex min-h-11 w-full items-center justify-between gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left text-[13px] font-medium'>
              <span className='flex items-center gap-1'>
                {footer.label} · <DigitSwap value={footer.items.length} />
              </span>
              <Icons.chevronDown
                aria-hidden
                className='text-muted-foreground size-4 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/footer:rotate-180 motion-reduce:transition-none'
              />
            </CollapsibleTrigger>
            <CollapsibleContent className='t-nav-panel'>
              <div className='flex flex-col gap-2 px-1.5 pb-1.5'>
                <p className='text-muted-foreground px-1.5 text-xs leading-relaxed'>
                  {column.key === 'drafts'
                    ? 'Kept, not scheduled. Edit a draft to bring it back.'
                    : column.key === 'review'
                      ? 'Past the approval deadline, so they can no longer be approved. Their drafts are back in Drafts to schedule again.'
                      : 'Ended before or during publishing. The receipts stay here; nothing is retried.'}
                </p>
                {renderCards(footer.items)}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
        <Link href={column.href} className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'lg' }), 'justify-start')}>
          {column.cta} <LearnMoreChevron />
        </Link>
      </motion.div>
    </section>
  );
}
