'use client';

import { useId, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

export interface WorkbarProps {
  /** FIND: the search field value. Omit both to render no search. */
  search?: string;
  onSearch?: (value: string) => void;
  searchPlaceholder?: string;
  searchLabel?: string;
  /** VIEW: a quieter representation switch (SegmentedControl). */
  view?: ReactNode;
  /** The labelled Filters trigger (FilterPanel). */
  filters?: ReactNode;
  /** Task tabs rendered above the bar (WHAT). */
  tabs?: ReactNode;
  /** Applied-filter summary shown while the panel is closed. */
  summary?: ReactNode;
  /** Live result count for assistive tech and the bar's right edge. */
  count?: ReactNode;
  className?: string;
}

/**
 * The FIND / VIEW row of a collection page (DNA §3.1, §9.1): search takes the flexible side;
 * view controls and the Filters trigger sit together. Below 50rem the search gets its own
 * full-width row (observed 800px breakpoint), so it never shrinks beside a select.
 */
export function Workbar({ search, onSearch, searchPlaceholder = 'Search…', searchLabel = 'Search', view, filters, tabs, summary, count, className }: WorkbarProps) {
  const id = useId();
  const hasSearch = onSearch !== undefined;
  return (
    <div className={cn('@container/workbar flex flex-col gap-3', className)}>
      {tabs}
      <div className='flex flex-col gap-2 @[50rem]/workbar:flex-row @[50rem]/workbar:items-center'>
        {hasSearch && (
          <label htmlFor={id} className='rafii-field flex min-h-11 flex-1 items-center gap-2.5 rounded-[var(--rafii-radius-control)] px-3.5 @[50rem]/workbar:min-h-11.5'>
            <Icons.search aria-hidden className='text-muted-foreground size-4 shrink-0' />
            <span className='sr-only'>{searchLabel}</span>
            <input
              id={id}
              type='search'
              aria-label={searchLabel}
              value={search ?? ''}
              onChange={(event) => onSearch?.(event.target.value)}
              placeholder={searchPlaceholder}
              autoComplete='off'
              className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm [&::-webkit-search-cancel-button]:appearance-none'
            />
            {search && (
              <button type='button' aria-label='Clear search' onClick={() => onSearch?.('')} className='rafii-focus text-muted-foreground hover:text-foreground -mr-1 flex size-8 items-center justify-center rounded-full'>
                <Icons.close className='size-3.5' />
              </button>
            )}
          </label>
        )}
        {(view || filters || count) && (
          <div className='flex flex-wrap items-center gap-2 @[50rem]/workbar:shrink-0'>
            {view}
            {filters}
            {count && <span className='text-muted-foreground ml-auto text-xs tabular-nums' role='status' aria-live='polite'>{count}</span>}
          </div>
        )}
      </div>
      {summary}
    </div>
  );
}

/** The applied-filter line shown while the panel is closed (DNA §10.5): count, summary, Clear. */
export function ActiveFilters({ count, summary, onClear, clearLabel = 'Clear filters' }: { count: number; summary: ReactNode; onClear: () => void; clearLabel?: string }) {
  if (count === 0) return null;
  return (
    <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs' role='status'>
      <span>
        {count} {count === 1 ? 'filter' : 'filters'} · <span className='text-foreground'>{summary}</span>
      </span>
      <button type='button' onClick={onClear} className='rafii-focus text-foreground rounded-md underline underline-offset-2'>
        {clearLabel}
      </button>
    </div>
  );
}
