'use client';

import { useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface FilterPanelProps {
  /** Number of active constraints, shown on the trigger. */
  count: number;
  /** Fields relevant to this task only (DNA §12.3). */
  children: ReactNode;
  title?: string;
  eyebrow?: string;
  onClear?: () => void;
  /** Filters update the view immediately; Done only closes the panel (DNA §11.3). */
  doneLabel?: string;
  triggerLabel?: string;
  className?: string;
  /** Optional control, for a surface that must close the panel before opening another layer. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * The labelled Filters trigger and its temporary panel (DNA §10.5, §12.3). Closing restores
 * focus to the trigger (Popover behaviour); Escape closes the panel before any parent dialog.
 */
export function FilterPanel({ count, children, title = 'Filters & display', eyebrow = 'Refine your view', onClear, doneLabel = 'Done', triggerLabel = 'Filters', className, open: controlled, onOpenChange }: FilterPanelProps) {
  const [uncontrolled, setUncontrolled] = useState(false);
  const open = controlled ?? uncontrolled;
  const setOpen = (next: boolean) => {
    if (controlled === undefined) setUncontrolled(next);
    onOpenChange?.(next);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button variant='glass' size='control' aria-label={count ? `${triggerLabel}, ${count} active` : triggerLabel} className={cn('gap-2', className)}>
            <Icons.adjustments className='size-4' />
            <span>{triggerLabel}</span>
            {count > 0 && <span className='bg-foreground text-background inline-flex min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums'>{count}</span>}
          </Button>
        }
      />
      <PopoverContent align='end' className='rafii-elevated w-[min(23rem,calc(100vw-1.5rem))] gap-0 rounded-[1.375rem] p-5'>
        <div className='mb-4 flex items-start justify-between gap-3'>
          <div className='flex flex-col gap-1'>
            <span className='rafii-eyebrow'>{eyebrow}</span>
            <h3 className='text-foreground text-lg font-medium tracking-tight'>{title}</h3>
          </div>
          <Button variant='action' size='sm' onClick={() => setOpen(false)} className='gap-1.5'>
            {doneLabel}
            <Icons.check className='size-3.5' />
          </Button>
        </div>
        <div className='flex flex-col gap-4'>{children}</div>
        {onClear && count > 0 && (
          <button type='button' onClick={onClear} className='rafii-focus text-muted-foreground hover:text-foreground mt-4 self-start rounded-md text-xs underline underline-offset-2'>
            Clear all
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** A labelled native select with the Rafii field material and its own chevron (DNA §11.2). */
export function FilterSelect({ label, value, onChange, options, id }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; id?: string }) {
  return (
    <label className='flex flex-col gap-2 text-sm'>
      <span className='text-foreground font-medium'>{label}</span>
      <span className='relative block'>
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className='rafii-field rafii-focus h-12 w-full appearance-none rounded-[var(--rafii-radius-control)] pr-10 pl-3.5 text-base outline-none'
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <Icons.chevronDown aria-hidden className='text-muted-foreground pointer-events-none absolute top-1/2 right-3.5 size-4 -translate-y-1/2' />
      </span>
    </label>
  );
}
