'use client';

import { useId, useState, type CSSProperties } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ApiError } from '@/lib/api/client';
import type { AssetRef, ComparisonResult } from '@/lib/api/library-intelligence-types';
import { OUTCOME_TEXT } from '@/lib/library/batch';
import { countLabel } from '@/lib/library/wording';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { assetTitle, dimensionsOf, kindLabel } from '../asset-card';
import type { LibraryAsset } from '../use-library';
import type { BatchKind, BatchParams, BatchRun } from './use-batch-actions';
import { ComparisonView } from './versions-panel';

/** Glass with an opaque fill where transparency is reduced or unsupported (the global material covers the rest). */
export const OPAQUE_GLASS_FALLBACK = '[@media(prefers-reduced-transparency:reduce)]:bg-popover [@media(prefers-reduced-transparency:reduce)]:backdrop-blur-none';

export interface SelectedItem {
  id: string;
  asset: LibraryAsset | null;
  title: string;
  ref: AssetRef;
}

/**
 * Batch actions appear only once something is selected (UI spec §5): collections, tags, a source pack, comparing two
 * versions and deleting, which has its own confirmation. Results are reported per item, never as "all done". While
 * the last run has items that didn't finish, its Retry (same keys) is the way forward: the other write controls wait
 * until it is retried or dismissed, so a lost answer is never re-sent as a new request.
 */
export function BatchBar({
  selected,
  collections,
  activeCollection,
  canEdit,
  usedCount,
  run,
  onRun,
  onRetry,
  onDismissRun,
  onSelectAll,
  onClear,
  canSelectMore,
  searchWithin,
  onSearchWithin,
  onBuildPack,
  packNote,
  stickyBottom
}: {
  selected: SelectedItem[];
  collections: { id: string; name: string; kind?: 'manual' | 'smart' }[];
  activeCollection: { id: string; name: string; kind?: 'manual' | 'smart' } | null;
  canEdit: boolean;
  /** Selected items used in a post, for the deletion impact. */
  usedCount: number;
  run: BatchRun | null;
  onRun: (kind: BatchKind, ids: string[], params: BatchParams) => void;
  onRetry: () => void;
  onDismissRun: () => void;
  onSelectAll: () => void;
  onClear: () => void;
  canSelectMore: boolean;
  /** Search only the selected items ("Selected N items" scope). */
  searchWithin: boolean;
  onSearchWithin: (on: boolean) => void;
  /** Source packs, when the Library intelligence service answers here (absent: the entry point is hidden). */
  onBuildPack?: (() => void) | null;
  /** Why source packs are off or limited here, in plain words. */
  packNote?: string | null;
  stickyBottom: string;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dialog, setDialog] = useState<'compare' | null>(null);
  const [tag, setTag] = useState('');
  const [tagOpen, setTagOpen] = useState(false);
  const tagId = useId();
  const ids = selected.map((item) => item.id);
  const count = selected.length;
  // A run with items that didn't finish waits for its own Retry (or Dismiss) before another write starts.
  const unresolved = Boolean(run && !run.running && run.summary.retryIds.length > 0);
  const busy = Boolean(run?.running) || unresolved;
  if (count === 0 && !run) return null;

  return (
    <div
      role='region'
      aria-label='Selected items'
      style={{ bottom: stickyBottom } as CSSProperties}
      className={cn('rafii-elevated sticky z-20 flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-2', OPAQUE_GLASS_FALLBACK)}
    >
      {run ? <RunReport run={run} items={selected} onRetry={onRetry} onDismiss={onDismissRun} /> : null}
      {count > 0 ? (
        <div className='flex flex-wrap items-center gap-2'>
          <span className='px-2 text-sm font-medium tabular-nums'>{countLabel(count)} selected</span>
          {canSelectMore ? (
            <Button variant='quiet' size='control' className='h-11' onClick={onSelectAll}>
              Select all shown
            </Button>
          ) : null}
          <Button variant='quiet' size='control' className='h-11' onClick={onClear}>
            Clear selection
          </Button>
          <Button variant='quiet' size='control' className='h-11' aria-pressed={searchWithin} onClick={() => onSearchWithin(!searchWithin)}>
            {searchWithin ? <Icons.check aria-hidden /> : null}
            Search only these
          </Button>
          <div className='scrollbar-hide -mx-1 flex min-w-0 basis-full gap-2 overflow-x-auto px-1 md:ml-auto md:basis-auto'>
            {canEdit && collections.length ? (
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button variant='glass' size='control' className='h-11 shrink-0' disabled={busy}>
                      <Icons.folder aria-hidden />
                      Add to collection
                    </Button>
                  }
                />
                <DropdownMenuContent align='end' className='rafii-elevated min-w-56 rounded-[var(--rafii-radius-card)] p-1.5'>
                  {collections.map((collection) => (
                    <DropdownMenuItem
                      key={collection.id}
                      className='min-h-11 gap-2 px-3'
                      onClick={() => onRun(collection.kind === 'smart' ? 'collection-include' : 'collection-add', ids, { collectionId: collection.id, collectionName: collection.name })}
                    >
                      {collection.kind === 'smart' ? <Icons.sparkles className='size-3.5' aria-hidden /> : null}
                      <span className='min-w-0 flex-1 truncate'>{collection.name}</span>
                      {collection.kind === 'smart' ? <span className='text-muted-foreground text-xs'>include</span> : null}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            {canEdit && activeCollection ? (
              <Button
                variant='glass'
                size='control'
                className='h-11 shrink-0'
                disabled={busy}
                onClick={() => onRun(activeCollection.kind === 'smart' ? 'collection-exclude' : 'collection-remove', ids, { collectionId: activeCollection.id, collectionName: activeCollection.name })}
              >
                {activeCollection.kind === 'smart' ? 'Exclude from this collection' : 'Remove from this collection'}
              </Button>
            ) : null}
            {canEdit ? (
              <Popover open={tagOpen} onOpenChange={setTagOpen}>
                <PopoverTrigger
                  render={
                    <Button variant='glass' size='control' className='h-11 shrink-0' disabled={busy}>
                      Add tag
                    </Button>
                  }
                />
                <PopoverContent align='end' className='rafii-elevated w-72 rounded-[var(--rafii-radius-card)] p-3'>
                  <form
                    className='flex flex-col gap-2'
                    onSubmit={(event) => {
                      event.preventDefault();
                      const value = tag.trim();
                      if (!value) return;
                      onRun('tag-add', ids, { tag: value });
                      setTag('');
                      setTagOpen(false);
                    }}
                  >
                    <label htmlFor={tagId} className='flex flex-col gap-1.5 text-sm font-medium'>
                      Tag for {countLabel(count)}
                      <Input id={tagId} value={tag} maxLength={60} onChange={(event) => setTag(event.target.value)} className='h-11 font-normal' />
                    </label>
                    <Button type='submit' variant='action' size='control' disabled={!tag.trim()}>
                      Add tag
                    </Button>
                  </form>
                </PopoverContent>
              </Popover>
            ) : null}
            {canEdit && onBuildPack ? (
              <Button variant='glass' size='control' className='h-11 shrink-0' disabled={Boolean(run?.running)} title={packNote ?? undefined} onClick={onBuildPack}>
                <Icons.sparkles aria-hidden />
                Build source pack
              </Button>
            ) : null}
            {count === 2 ? (
              <Button variant='glass' size='control' className='h-11 shrink-0' disabled={Boolean(run?.running)} onClick={() => setDialog('compare')}>
                Compare
              </Button>
            ) : null}
            {canEdit ? (
              <Button variant='destructive' size='control' className='h-11 shrink-0 rounded-[var(--rafii-radius-control)]' disabled={busy} onClick={() => setConfirmDelete(true)}>
                <Icons.trash aria-hidden />
                Delete selected…
              </Button>
            ) : null}
          </div>
          {unresolved ? <p className='text-muted-foreground basis-full px-2 text-xs'>Retry or dismiss the last change before starting another.</p> : null}
        </div>
      ) : null}

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 md:p-6'>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {countLabel(count)}?</AlertDialogTitle>
            <AlertDialogDescription>
              {usedCount > 0 ? `${countLabel(usedCount)} ${usedCount === 1 ? 'is' : 'are'} used in a post. ` : ''}
              This permanently deletes the stored files. Scheduled posts using them will need a new review; published posts aren’t affected. Each item reports its own result.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' size='control'>
              Keep
            </AlertDialogCancel>
            <AlertDialogAction
              variant='destructive'
              size='control'
              className='rounded-[var(--rafii-radius-control)]'
              onClick={() => {
                onRun('delete', ids, {});
                setConfirmDelete(false);
              }}
            >
              Delete {countLabel(count)}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {count === 2 ? <CompareDialog open={dialog === 'compare'} onOpenChange={(open) => setDialog(open ? 'compare' : null)} items={selected} /> : null}
    </div>
  );
}

/** The run's line plus every item that did not simply succeed, each with its reason. */
function RunReport({ run, items, onRetry, onDismiss }: { run: BatchRun; items: SelectedItem[]; onRetry: () => void; onDismiss: () => void }) {
  const titles = new Map(items.map((item) => [item.id, item.title]));
  const notable = run.outcomes.filter((outcome) => outcome.status !== 'applied');
  return (
    <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <div className='flex flex-wrap items-center gap-2'>
        {run.running ? <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' aria-hidden /> : run.summary.rollbackIds.length ? <Icons.warning className='size-4' aria-hidden /> : <Icons.circleCheck className='size-4' aria-hidden />}
        <p className='text-sm font-medium'>{run.summary.label}</p>
        <span className='ml-auto flex gap-2'>
          {!run.running && run.summary.retryIds.length ? (
            <Button variant='glass' size='control' className='h-11' onClick={onRetry}>
              Retry {countLabel(run.summary.retryIds.length)}
            </Button>
          ) : null}
          {!run.running ? (
            <Button variant='quiet' size='control' className='h-11' onClick={onDismiss}>
              Dismiss
            </Button>
          ) : null}
        </span>
      </div>
      {notable.length && !run.running ? (
        <ul className='flex max-h-40 flex-col gap-1 overflow-y-auto text-sm'>
          {notable.map((outcome) => (
            <li key={outcome.id} className='flex flex-wrap items-baseline justify-between gap-x-3'>
              <span className='min-w-0 truncate'>{titles.get(outcome.id) ?? 'An item'}</span>
              <span className='text-muted-foreground text-xs'>
                {OUTCOME_TEXT[outcome.status]}
                {outcome.message ? ` · ${outcome.message}` : ''}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function factsOf(item: SelectedItem) {
  const asset = item.asset;
  if (!asset) return [item.title];
  return [assetTitle(asset), kindLabel(asset), dimensionsOf(asset), typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null, asset.mime].filter((value): value is string => Boolean(value));
}

/** Two items side by side through the server's comparison: honest about what it can compare for these formats. */
function CompareDialog({ open, onOpenChange, items }: { open: boolean; onOpenChange: (open: boolean) => void; items: SelectedItem[] }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.libraryCompare(workspaceId, items.map((item) => item.ref)));
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 503 ? 'Comparing isn’t available in this version yet. The basic facts are shown above.' : failure instanceof Error ? failure.message : 'The comparison didn’t finish.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='lg'>
        <RafiiDialogHeader title='Compare' intro='Each side keeps its own version and approval. Nothing is replaced from here.' />
        <RafiiDialogBody className='flex flex-col gap-4'>
          {result ? (
            <ComparisonView result={result} />
          ) : (
            <div className='grid gap-3 sm:grid-cols-2'>
              {items.map((item, index) => (
                <div key={item.id} className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-card)] p-3 text-sm'>
                  <span className='rafii-eyebrow'>{index === 0 ? 'First' : 'Second'}</span>
                  {factsOf(item).map((fact) => (
                    <span key={fact} className='break-words'>
                      {fact}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}
          {error ? (
            <p role='alert' className='text-muted-foreground text-sm'>
              {error}
            </p>
          ) : null}
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row justify-end'>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button variant='action' size='control' disabled={busy} onClick={() => void compare()}>
            {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            Compare details
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
