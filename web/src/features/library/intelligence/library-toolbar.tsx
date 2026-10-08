'use client';

import { useId, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, SegmentedControl } from '@/components/rafii';
import type { LibraryDensity, LibraryKindParam, LibrarySortParam, LibraryUsageParam } from '@/lib/library/url-state';
import { countLabel, scopeDetail, scopeLabel, type ScopeDescription } from '@/lib/library/wording';
import { AnimatedCount } from './animated-count';

/**
 * The prominent search (UI spec §1, §5). The scope is always written out under the field in plain words — "Entire
 * permitted Library", "This collection" or "Selected N items" — and an exact query needs no conversation.
 */
export function LibrarySearchField({ value, onChange, scope, searching, aside }: { value: string; onChange: (value: string) => void; scope: ScopeDescription; searching: boolean; aside?: ReactNode }) {
  const id = useId();
  const label = scopeLabel(scope);
  return (
    <div className='flex min-w-0 flex-col gap-1.5'>
      <label htmlFor={id} className='rafii-field flex min-h-11 items-center gap-2.5 rounded-[var(--rafii-radius-control)] px-3.5 lg:min-h-12'>
        {searching ? <Icons.spinner aria-hidden className='text-muted-foreground size-4 shrink-0 animate-spin motion-reduce:animate-none' /> : <Icons.search aria-hidden className='text-muted-foreground size-4 shrink-0' />}
        <span className='sr-only'>Search Library</span>
        <input
          id={id}
          type='search'
          aria-label='Search Library'
          aria-describedby={`${id}-scope`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder='Search names, words inside files, tags or dimensions'
          autoComplete='off'
          enterKeyHint='search'
          className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm [&::-webkit-search-cancel-button]:appearance-none'
        />
        {value ? (
          <button type='button' aria-label='Clear search' onClick={() => onChange('')} className='rafii-focus text-muted-foreground hover:text-foreground -mr-1.5 flex size-11 shrink-0 items-center justify-center rounded-full'>
            <Icons.close className='size-4' aria-hidden />
          </button>
        ) : null}
      </label>
      <div className='flex min-w-0 items-center justify-between gap-2'>
        <p id={`${id}-scope`} data-library-scope={scope.kind} className='text-muted-foreground min-w-0 truncate px-1 text-xs' title={scopeDetail(scope)}>
          Searching <span className='text-foreground font-medium'>{label}</span>
          {scope.kind === 'collection' && scope.collectionName ? <span> · {scope.collectionName}</span> : null}
        </p>
        {aside}
      </div>
    </div>
  );
}

export const KIND_OPTIONS: { value: LibraryKindParam; label: string }[] = [
  { value: 'all', label: 'All types' },
  { value: 'image', label: 'Photos' },
  { value: 'video', label: 'Videos' },
  { value: 'audio', label: 'Audio' },
  { value: 'document', label: 'Documents' },
  { value: 'file', label: 'Other files' }
];

const SORT_LABELS: Record<LibrarySortParam, string> = {
  newest: 'Newest first',
  stored: 'Workspace order',
  largest: 'Largest first'
};

/** Used / Unused stays a filter (UI spec §1), with compact Type, Tag and Sort behind one labelled Filters panel. */
export function LibraryFilters({
  use,
  onUse,
  counts,
  kind,
  onKind,
  typeSelect,
  tag,
  onTag,
  tags,
  sort,
  onSort,
  sortOptions,
  defaultSort,
  searching
}: {
  use: LibraryUsageParam;
  onUse: (value: LibraryUsageParam) => void;
  /** Exact counts only (the whole set is loaded, or the server said); otherwise none are shown. */
  counts: Record<LibraryUsageParam, number> | null;
  kind: LibraryKindParam;
  onKind: (value: LibraryKindParam) => void;
  /** The Type select (rendered by the page with its stable id). */
  typeSelect: ReactNode;
  tag: string;
  onTag: (value: string) => void;
  tags: string[];
  sort: LibrarySortParam;
  onSort: (value: LibrarySortParam) => void;
  sortOptions: LibrarySortParam[];
  defaultSort: LibrarySortParam;
  searching: boolean;
}) {
  const active = (kind !== 'all' ? 1 : 0) + (tag ? 1 : 0) + (sort !== defaultSort && !searching ? 1 : 0);
  const clear = () => {
    onKind('all');
    onTag('');
    onSort(defaultSort);
  };
  const summary = [kind !== 'all' ? KIND_OPTIONS.find((option) => option.value === kind)?.label : null, tag ? `Tag: ${tag}` : null, sort !== defaultSort && !searching ? SORT_LABELS[sort] : null].filter(Boolean).join(' · ');
  const option = (value: LibraryUsageParam, text: string) => ({
    value,
    ariaLabel: counts ? `${text}, ${countLabel(counts[value])}` : text,
    label: (
      <>
        {text}
        {counts ? <AnimatedCount value={counts[value]} showNoun={false} label='' className='text-muted-foreground text-xs' /> : null}
      </>
    )
  });
  return (
    <div className='flex flex-col gap-2'>
      <div className='flex min-w-0 flex-wrap items-center gap-2'>
        <div data-tour='library-filter' className='min-w-0'>
          <SegmentedControl label='Filter by use' value={use} onChange={onUse} widths='content' options={[option('all', 'All'), option('unused', 'Unused'), option('used', 'Used')]} />
        </div>
        <FilterPanel count={active} onClear={clear} className='h-11 px-3.5'>
          {typeSelect}
          <FilterSelect id='library-tag' label='Tag' value={tag} onChange={onTag} options={[{ value: '', label: 'All tags' }, ...tags.map((entry) => ({ value: entry, label: entry }))]} />
          <FilterSelect
            id='library-sort'
            label={searching ? 'Sort (search results are ranked by relevance)' : 'Sort'}
            value={sort}
            onChange={(value) => onSort(value as LibrarySortParam)}
            options={sortOptions.map((value) => ({ value, label: SORT_LABELS[value] }))}
          />
        </FilterPanel>
      </div>
      <ActiveFilters count={active} summary={summary} onClear={clear} clearLabel='Clear filters' />
    </div>
  );
}

/** Persistent view controls: Gallery / List and density, beside the honest count line. */
export function LibraryViewControls({
  viewSwitch,
  density,
  onDensity,
  status
}: {
  /** Gallery / List (rendered by the page). */
  viewSwitch: ReactNode;
  density: LibraryDensity;
  onDensity: (value: LibraryDensity) => void;
  status: ReactNode;
}) {
  return (
    <div className='flex min-w-0 flex-wrap items-center gap-2'>
      <div data-tour='library-stats' className='text-muted-foreground min-w-0 flex-1 text-xs'>
        {status}
      </div>
      {viewSwitch}
      <SegmentedControl
        label='Density'
        value={density}
        onChange={onDensity}
        widths='content'
        options={[
          { value: 'comfortable', ariaLabel: 'Comfortable', title: 'Comfortable', label: <Icons.galleryVerticalEnd className='size-4' aria-hidden /> },
          { value: 'compact', ariaLabel: 'Compact', title: 'Compact', label: <Icons.columns className='size-4' aria-hidden /> }
        ]}
      />
    </div>
  );
}
