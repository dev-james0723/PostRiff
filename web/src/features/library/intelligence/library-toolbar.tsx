'use client';

import { useId, type ReactNode } from 'react';
import { IconArrowsSort, IconBaselineDensityMedium, IconBaselineDensitySmall, IconLayoutGrid, IconLayoutList } from '@tabler/icons-react';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii';
import type { LibraryDensity, LibraryKindParam, LibrarySortParam, LibraryStatusParam, LibraryUsageParam } from '@/lib/library/url-state';
import { countLabel, scopeDetail, scopeLabel, type ScopeDescription, type ScopeKind } from '@/lib/library/wording';
import { Control, ToolbarDivider, ToolbarSelect } from '../ui/controls';

/**
 * The prominent search (UI spec §1, §5; redesign §3). One 40 px field; under it the scope in plain words — "Entire
 * permitted Library", "This collection" or "Selected N items" — which is also the scope picker. An exact query needs
 * no conversation.
 */
export function LibrarySearchField({
  value,
  onChange,
  scope,
  searching,
  scopeOptions,
  onScope,
  aside
}: {
  value: string;
  onChange: (value: string) => void;
  scope: ScopeDescription;
  searching: boolean;
  /** The scopes that exist right now (a collection is open, something is selected); one entry means no picker. */
  scopeOptions?: ScopeKind[];
  onScope?: (kind: ScopeKind) => void;
  aside?: ReactNode;
}) {
  const id = useId();
  const label = scopeLabel(scope);
  const choices = scopeOptions && scopeOptions.length > 1 && onScope ? scopeOptions : null;
  const optionLabel = (kind: ScopeKind) => scopeDetail({ ...scope, kind });
  return (
    <div className='flex min-w-0 flex-col gap-1.5'>
      <label
        htmlFor={id}
        className='rafii-field focus-within:ring-ring/40 flex h-10 items-center gap-2.5 rounded-[var(--rafii-radius-control)] px-3 transition-shadow duration-150 focus-within:ring-2 pointer-coarse:h-11'
      >
        {searching ? <Icons.spinner aria-hidden className='text-muted-foreground size-4 shrink-0 animate-spin motion-reduce:animate-none' /> : <Icons.search aria-hidden className='text-muted-foreground size-4 shrink-0' />}
        <span className='sr-only'>Search Library</span>
        <input
          id={id}
          type='search'
          name='library-search'
          aria-label='Search Library'
          aria-describedby={`${id}-scope`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder='Search names, words inside files, tags…'
          autoComplete='off'
          enterKeyHint='search'
          className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm [&::-webkit-search-cancel-button]:appearance-none'
        />
        {value ? (
          <button type='button' aria-label='Clear search' onClick={() => onChange('')} className='rafii-focus text-muted-foreground hover:text-foreground -mr-1 flex size-7 shrink-0 items-center justify-center rounded-full pointer-coarse:size-9'>
            <Icons.close className='size-4' aria-hidden />
          </button>
        ) : (
          <kbd aria-hidden className='text-muted-foreground ring-foreground/15 hidden h-5 min-w-5 items-center justify-center rounded-md px-1 text-[11px] ring-1 md:inline-flex'>
            /
          </kbd>
        )}
      </label>
      <div className='flex min-h-7 min-w-0 items-center justify-between gap-2'>
        <p id={`${id}-scope`} data-library-scope={scope.kind} className='text-muted-foreground relative flex min-w-0 items-center gap-1 px-1 text-xs' title={scopeDetail(scope)}>
          <span className='truncate'>
            Searching <span className='text-foreground font-medium'>{label}</span>
            {scope.kind === 'collection' && scope.collectionName ? <span> · {scope.collectionName}</span> : null}
          </span>
          {choices ? (
            <>
              <Icons.chevronDown aria-hidden className='size-3.5 shrink-0' />
              {/* The written scope is the picker: a native select laid over it (keyboard and touch pickers for free). */}
              <select
                aria-label='Search scope'
                value={scope.kind}
                onChange={(event) => onScope?.(event.target.value as ScopeKind)}
                className='rafii-focus absolute inset-0 cursor-pointer opacity-0'
              >
                {choices.map((kind) => (
                  <option key={kind} value={kind}>
                    {optionLabel(kind)}
                  </option>
                ))}
              </select>
            </>
          ) : null}
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

/** One spoken name per option: the count joins the words, never a second label. */
const withCount = (text: string, value: number | undefined) => (typeof value === 'number' ? `${text} · ${value.toLocaleString()}` : text);

const USE_LABELS: Record<LibraryUsageParam, string> = { all: 'Any use', unused: 'Unused', used: 'Used in posts' };
const STATUS_LABELS: Record<LibraryStatusParam, string> = { all: 'Any status', ready: 'Ready', processing: 'Processing', attention: 'Needs attention' };

/**
 * One compact toolbar (redesign §3): Type, Usage, Status and Tag filters on the left — Used/Unused is a filter here, not
 * navigation — and the count, sort and the persistent Gallery/List and density controls on the right. It wraps on
 * narrow screens instead of hiding anything behind a panel.
 */
export function LibraryFilters({
  use,
  onUse,
  counts,
  kind,
  onKind,
  kindCounts,
  status,
  onStatus,
  statusCounts,
  tag,
  onTag,
  tags,
  sort,
  onSort,
  sortOptions,
  searching,
  onClear,
  summary,
  view
}: {
  use: LibraryUsageParam;
  onUse: (value: LibraryUsageParam) => void;
  /** Exact counts only (the whole set is loaded, or the server said); otherwise none are shown. */
  counts: Record<LibraryUsageParam, number> | null;
  kind: LibraryKindParam;
  onKind: (value: LibraryKindParam) => void;
  kindCounts: Partial<Record<LibraryKindParam, number>> | null;
  status: LibraryStatusParam;
  onStatus: (value: LibraryStatusParam) => void;
  statusCounts: Record<LibraryStatusParam, number> | null;
  tag: string;
  onTag: (value: string) => void;
  tags: string[];
  sort: LibrarySortParam;
  onSort: (value: LibrarySortParam) => void;
  sortOptions: LibrarySortParam[];
  searching: boolean;
  /** Clears every filter (not the query or scope). */
  onClear: () => void;
  /** The honest count line (items, loaded, processing). */
  summary: ReactNode;
  /** Gallery/List and density (rendered by the page). */
  view: ReactNode;
}) {
  const active = (kind !== 'all' ? 1 : 0) + (use !== 'all' ? 1 : 0) + (status !== 'all' ? 1 : 0) + (tag ? 1 : 0);
  return (
    <div role='toolbar' aria-label='Filter and view' data-tour='library-filter' className='flex min-w-0 flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-1'>
      {/* Phones: one row that scrolls inside itself (never the page); wider screens: it wraps. */}
      <div className='scrollbar-hide -mx-1 flex min-w-0 items-center gap-1 overflow-x-auto px-1 max-sm:pr-6 max-sm:[mask-image:linear-gradient(to_right,#000_calc(100%_-_1.5rem),transparent)] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0'>
        <ToolbarSelect
          id='library-kind'
          label='Type'
          icon={<Icons.adjustments />}
          value={kind}
          defaultValue='all'
          onChange={onKind}
          options={KIND_OPTIONS.map((option) => ({ value: option.value, label: option.value === 'all' ? option.label : withCount(option.label, kindCounts?.[option.value]) }))}
        />
        <ToolbarSelect
          id='library-use'
          label='Usage'
          value={use}
          defaultValue='all'
          onChange={onUse}
          options={(['all', 'unused', 'used'] as const).map((value) => ({ value, label: value === 'all' ? USE_LABELS[value] : withCount(USE_LABELS[value], counts?.[value]) }))}
        />
        <ToolbarSelect
          id='library-status'
          label='Status'
          value={status}
          defaultValue='all'
          onChange={onStatus}
          options={(['all', 'ready', 'processing', 'attention'] as const).map((value) => ({ value, label: value === 'all' ? STATUS_LABELS[value] : withCount(STATUS_LABELS[value], statusCounts?.[value]) }))}
        />
        {tags.length || tag ? (
          <ToolbarSelect id='library-tag' label='Tag' value={tag} defaultValue='' onChange={onTag} options={[{ value: '', label: 'Any tag' }, ...tags.map((entry) => ({ value: entry, label: entry }))]} />
        ) : null}
        {active ? (
          <Control tone='ghost' size='sm' className='shrink-0' onClick={onClear} aria-label={`Clear ${countLabel(active, 'filter')}`}>
            Clear
          </Control>
        ) : null}
        <ToolbarDivider />
        <ToolbarSelect
          id='library-sort'
          label={searching ? 'Sort (search results are ranked by relevance)' : 'Sort'}
          icon={<IconArrowsSort />}
          value={sort}
          onChange={onSort}
          options={sortOptions.map((value) => ({ value, label: SORT_LABELS[value] }))}
        />
      </div>
      <div className='flex min-w-0 items-center gap-1 sm:ml-auto'>
        <div data-tour='library-stats' className='text-muted-foreground min-w-0 flex-1 px-1 text-xs tabular-nums sm:flex-none'>
          {summary}
        </div>
        {view}
      </div>
    </div>
  );
}

/** Persistent view controls: Gallery / List and density, one segmented pair each. */
export function LibraryViewSwitch({ mode, onMode, density, onDensity }: { mode: 'gallery' | 'list'; onMode: (value: 'gallery' | 'list') => void; density: LibraryDensity; onDensity: (value: LibraryDensity) => void }) {
  return (
    <div className='flex items-center gap-1'>
      <SegmentedControl
        label='Library view'
        size='sm'
        value={mode}
        onChange={onMode}
        widths='content'
        options={[
          { value: 'gallery', label: <IconLayoutGrid className='size-4' aria-hidden />, ariaLabel: 'Gallery', title: 'Gallery' },
          { value: 'list', label: <IconLayoutList className='size-4' aria-hidden />, ariaLabel: 'List', title: 'List' }
        ]}
      />
      <SegmentedControl
        label='Density'
        size='sm'
        value={density}
        onChange={onDensity}
        widths='content'
        options={[
          { value: 'comfortable', ariaLabel: 'Comfortable', title: 'Comfortable spacing', label: <IconBaselineDensityMedium className='size-4' aria-hidden /> },
          { value: 'compact', ariaLabel: 'Compact', title: 'Compact spacing', label: <IconBaselineDensitySmall className='size-4' aria-hidden /> }
        ]}
      />
    </div>
  );
}
