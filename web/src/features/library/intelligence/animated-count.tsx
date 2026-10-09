'use client';

import { DigitSwap } from '@/components/motion/digit-swap';
import { cn } from '@/lib/utils';
import { countLabel } from '@/lib/library/wording';

/**
 * Rolling digits with one accessible name (UI spec §6, A065). The animated glyphs and DigitSwap's own text are
 * hidden from assistive tech; one visually hidden label carries the count with its noun in the right number.
 * Every animated count in the Library goes through here.
 */
export function AnimatedCount({
  value,
  singular = 'item',
  pluralForm,
  label,
  showNoun = true,
  className
}: {
  value: number;
  singular?: string;
  pluralForm?: string;
  /** Overrides the spoken text, e.g. "Unused, 3 items". */
  label?: string;
  showNoun?: boolean;
  className?: string;
}) {
  const spoken = label ?? countLabel(value, singular, pluralForm);
  const noun = countLabel(value, singular, pluralForm).replace(/^[\d,]+\s/, '');
  return (
    <span data-animated-count='' className={cn('inline-flex items-center gap-1', className)}>
      <span className='sr-only'>{spoken}</span>
      <span aria-hidden='true' className='inline-flex items-center gap-1'>
        <DigitSwap value={value} />
        {showNoun ? <span>{noun}</span> : null}
      </span>
    </span>
  );
}
