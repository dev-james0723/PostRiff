'use client';

import { IconChevronRight } from '@tabler/icons-react';
import { ChannelIcon } from '@/components/channel-icon';
import { cn } from '@/lib/utils';
import { deriveDeliverySummary, type DeliverySummaryRow } from './delivery-summary-ops';

export type {
  DeliverySummaryLanguage,
  DeliverySummaryRow,
  DeliverySummaryValue
} from './delivery-summary-ops';

export function DeliverySummary({
  rows,
  open,
  controls,
  disabled,
  onOpen
}: {
  rows: readonly DeliverySummaryRow[];
  open: boolean;
  controls: string;
  disabled?: boolean;
  onOpen: () => void;
}) {
  const summary = deriveDeliverySummary(rows);
  return (
    <button
      id={`${controls}-trigger`}
      type='button'
      aria-haspopup='dialog'
      aria-expanded={open}
      aria-controls={controls}
      aria-label={summary.accessible}
      disabled={disabled}
      onClick={onOpen}
      className={cn(
        'rafii-focus rafii-quiet hover:rafii-glass-selected mx-3 mb-1.5 flex min-h-11 min-w-0 items-center gap-3 rounded-[var(--rafii-radius-control)] px-3 py-1.5 text-left transition-colors',
        'disabled:pointer-events-none disabled:opacity-55'
      )}
    >
      <span aria-hidden className='flex shrink-0 items-center'>
        {summary.iconPlatforms.map((platform, index) => (
          <ChannelIcon
            key={`${platform}-${index}`}
            platform={platform}
            size='sm'
            className={cn(index > 0 && '-ml-1.5 ring-2 ring-[var(--background)]')}
          />
        ))}
        {summary.hiddenIconCount > 0 && (
          <span className='bg-muted text-muted-foreground -ml-1.5 inline-flex size-6 items-center justify-center rounded-md text-[10px] font-medium ring-2 ring-[var(--background)]'>
            +{summary.hiddenIconCount}
          </span>
        )}
      </span>
      <span
        aria-hidden
        className='flex min-w-0 flex-1 items-baseline gap-x-1.5 overflow-hidden text-sm'
      >
        <span className='text-foreground shrink-0 font-medium'>{summary.primary}</span>
        <span className='text-muted-foreground flex min-w-0 items-baseline gap-1'>
          <span aria-hidden>·</span>
          <span className='truncate'>{summary.secondaryLabel}</span>
          {summary.secondaryExtraCount > 0 && (
            <span className='shrink-0'>+{summary.secondaryExtraCount}</span>
          )}
        </span>
      </span>
      <IconChevronRight aria-hidden className='text-muted-foreground size-4 shrink-0' />
    </button>
  );
}
