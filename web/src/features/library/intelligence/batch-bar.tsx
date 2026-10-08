'use client';

import { useId, useRef, useState, type CSSProperties } from 'react';
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
import type { AssetRef, SourcePack } from '@/lib/api/library-intelligence-types';
import { OUTCOME_TEXT, newIdempotencyKey, outcomeFromActionResult, outcomeFromError, reduceBatchOutcomes, type BatchOutcome } from '@/lib/library/batch';
import { normalizeKey } from '@/lib/library/url-state';
import { countLabel } from '@/lib/library/wording';
import { formatBytes } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { assetTitle, dimensionsOf, kindLabel } from '../asset-card';
import type { LibraryAsset } from '../use-library';
import type { BatchKind, BatchParams, BatchRun } from './use-batch-actions';

/** Glass with an opaque fill where transparency is reduced or unsupported (the global material covers the rest). */
export const OPAQUE_GLASS_FALLBACK = '[@media(prefers-reduced-transparency:reduce)]:bg-popover [@media(prefers-reduced-transparency:reduce)]:backdrop-blur-none';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export interface SelectedItem {
  id: string;
  asset: LibraryAsset | null;
  title: string;
  ref: AssetRef;
}

/**
 * Batch actions appear only once something is selected (UI spec §5): collections, tags, a source pack, comparing two
 * versions and deleting, which has its own confirmation. Results are reported per item, never as "all done".
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
  stickyBottom,
  onAnnounce
}: {
  selected: SelectedItem[];
  collections: { id: string; name: string }[];
  activeCollection: { id: string; name: string } | null;
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
  stickyBottom: string;
  onAnnounce: (message: string) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dialog, setDialog] = useState<'pack' | 'compare' | null>(null);
  const [tag, setTag] = useState('');
  const [tagOpen, setTagOpen] = useState(false);
  const tagId = useId();
  const ids = selected.map((item) => item.id);
  const count = selected.length;
  const busy = Boolean(run?.running);
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
                    <DropdownMenuItem key={collection.id} className='min-h-11 px-3' onClick={() => onRun('collection-add', ids, { collectionId: collection.id, collectionName: collection.name })}>
                      {collection.name}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
            {canEdit && activeCollection ? (
              <Button variant='glass' size='control' className='h-11 shrink-0' disabled={busy} onClick={() => onRun('collection-remove', ids, { collectionId: activeCollection.id, collectionName: activeCollection.name })}>
                Remove from this collection
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
                    <label htmlFor={tagId} className='text-sm font-medium'>
                      Tag for {countLabel(count)}
                    </label>
                    <Input id={tagId} value={tag} maxLength={60} onChange={(event) => setTag(event.target.value)} className='h-11' />
                    <Button type='submit' variant='action' size='control' disabled={!tag.trim()}>
                      Add tag
                    </Button>
                  </form>
                </PopoverContent>
              </Popover>
            ) : null}
            {canEdit ? (
              <Button variant='glass' size='control' className='h-11 shrink-0' disabled={busy} onClick={() => setDialog('pack')}>
                <Icons.sparkles aria-hidden />
                Build source pack
              </Button>
            ) : null}
            {count === 2 ? (
              <Button variant='glass' size='control' className='h-11 shrink-0' disabled={busy} onClick={() => setDialog('compare')}>
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

      <SourcePackDialog open={dialog === 'pack'} onOpenChange={(open) => setDialog(open ? 'pack' : null)} items={selected} onAnnounce={onAnnounce} />
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

/**
 * A source pack from the selection: evidence and style samples apart, with rationale, gaps and rights warnings. Each
 * selected item says whether it went in and why not. Saving is one explicit action with its own idempotency key.
 */
function SourcePackDialog({ open, onOpenChange, items, onAnnounce }: { open: boolean; onOpenChange: (open: boolean) => void; items: SelectedItem[]; onAnnounce: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const id = useId();
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [pack, setPack] = useState<SourcePack | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const saveKey = useRef<{ pack: string; key: string } | null>(null);

  const included = new Map<string, string>();
  for (const ref of pack?.evidenceRefs ?? []) included.set(normalizeKey(ref.assetRef.assetId), 'Evidence');
  for (const ref of pack?.styleRefs ?? []) if (!included.has(normalizeKey(ref.assetRef.assetId))) included.set(normalizeKey(ref.assetRef.assetId), 'Style sample');
  const warnings = new Map((pack?.rightsWarnings ?? []).map((warning) => [normalizeKey(warning.assetId), warning.message]));
  const outcomes: BatchOutcome[] = pack
    ? items.map((item): BatchOutcome => {
        const role = included.get(normalizeKey(item.id));
        return role ? { id: item.id, status: 'applied', message: role } : { id: item.id, status: 'skipped', message: warnings.get(normalizeKey(item.id)) ?? 'Not used for this goal', retryable: false };
      })
    : [];
  const summary = reduceBatchOutcomes(outcomes, 'included');

  async function build() {
    if (!goal.trim()) {
      setError('Say what you’re making first.');
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const refs = items.map((item) => item.ref);
      const result = await api.libraryRecommendSources(workspaceId, {
        userGoal: goal.trim(),
        selectedSourceRefs: refs.map((assetRef) => ({ assetRef })),
        scope: { kind: 'selection', assetRefs: refs },
        purpose: 'draft_evidence'
      });
      setPack(result);
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 503 ? 'Source packs aren’t available in this version yet.' : failure instanceof Error ? failure.message : 'The source pack couldn’t be built.');
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!pack) return;
    const digest = `${pack.packId}:${pack.revision}`;
    if (!saveKey.current || saveKey.current.pack !== digest) saveKey.current = { pack: digest, key: newIdempotencyKey('lib-pack', randomKey) };
    setBusy(true);
    setError(null);
    try {
      const result = await api.libraryAction(workspaceId, {
        actionId: `pack-${Date.now()}`,
        uiInstanceId: 'library-batch',
        actionType: 'source_pack.create',
        targetRefs: items.map((item) => item.ref),
        expectedRevision: pack.revision,
        idempotencyKey: saveKey.current.key,
        payload: { packId: pack.packId, userGoal: goal.trim() }
      });
      const outcome = outcomeFromActionResult('pack', result);
      if (outcome.status === 'applied') {
        setSaved(true);
        onAnnounce(`Source pack saved. ${summary.label}.`);
      } else setError(outcome.message ?? 'The source pack wasn’t saved.');
    } catch (failure) {
      setError(outcomeFromError('pack', failure instanceof ApiError ? failure : null).message ?? 'The source pack wasn’t saved.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='md'>
        <RafiiDialogHeader title='Build source pack' intro={`From ${countLabel(items.length, 'selected item')}. Evidence and style samples are kept apart; nothing here approves a fact or its rights.`} />
        <RafiiDialogBody className='flex flex-col gap-4'>
          <label htmlFor={`${id}-goal`} className='flex flex-col gap-1.5 text-sm font-medium'>
            What are you making?
            <Input id={`${id}-goal`} value={goal} maxLength={300} onChange={(event) => setGoal(event.target.value)} placeholder='A post about the spring recital' className='h-11 font-normal' />
          </label>
          {error ? (
            <p role='alert' className='text-destructive text-sm'>
              {error}
            </p>
          ) : null}
          {pack ? (
            <div className='flex flex-col gap-4'>
              <p className='text-sm font-medium'>{summary.label}</p>
              <PackList title='Evidence' entries={pack.evidenceRefs.map((ref) => ({ key: `${ref.assetRef.assetId}-${ref.segmentId ?? ''}`, title: ref.displayTitle, detail: [ref.rationale, ref.rights].filter(Boolean).join(' · ') }))} />
              <PackList title='Style samples' entries={pack.styleRefs.map((ref) => ({ key: `${ref.assetRef.assetId}-${ref.sampleId}`, title: ref.displayTitle, detail: ref.rationale }))} />
              {pack.gaps.length ? <PackList title='Missing' entries={pack.gaps.map((gap, index) => ({ key: `gap-${index}`, title: gap.message, detail: '' }))} /> : null}
              {pack.rightsWarnings.length ? <PackList title='Rights to check' entries={pack.rightsWarnings.map((warning, index) => ({ key: `rights-${index}`, title: warning.message, detail: '' }))} /> : null}
              <ul className='flex flex-col gap-1 text-sm'>
                {outcomes.map((outcome) => (
                  <li key={outcome.id} className='flex flex-wrap items-baseline justify-between gap-x-3'>
                    <span className='min-w-0 truncate'>{items.find((item) => item.id === outcome.id)?.title ?? 'An item'}</span>
                    <span className='text-muted-foreground text-xs'>{outcome.message}</span>
                  </li>
                ))}
              </ul>
              {saved ? <p className='text-sm'>Saved. Attach it to a draft from Ideas when you write.</p> : null}
            </div>
          ) : null}
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row justify-end'>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {pack && !saved ? (
            <Button variant='action' size='control' disabled={busy} onClick={() => void save()}>
              Save source pack
            </Button>
          ) : (
            <Button variant='action' size='control' disabled={busy || !goal.trim() || saved} onClick={() => void build()}>
              {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              Build
            </Button>
          )}
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

function PackList({ title, entries }: { title: string; entries: { key: string; title: string; detail: string }[] }) {
  return (
    <div className='flex flex-col gap-1'>
      <p className='rafii-eyebrow'>{title}</p>
      {entries.length ? (
        <ul className='flex flex-col gap-1.5'>
          {entries.map((entry) => (
            <li key={entry.key} className='flex flex-col text-sm'>
              <span>{entry.title}</span>
              {entry.detail ? <span className='text-muted-foreground text-xs'>{entry.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className='text-muted-foreground text-sm'>None</p>
      )}
    </div>
  );
}

function factsOf(item: SelectedItem) {
  const asset = item.asset;
  if (!asset) return [item.title];
  return [assetTitle(asset), kindLabel(asset), dimensionsOf(asset), typeof asset.bytes === 'number' ? formatBytes(asset.bytes) : null, asset.mime].filter((value): value is string => Boolean(value));
}

/** Two items side by side, plus whatever the comparison service can say for this type. */
function CompareDialog({ open, onOpenChange, items }: { open: boolean; onOpenChange: (open: boolean) => void; items: SelectedItem[] }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [result, setResult] = useState<{ differences: { field: string; before: string; after: string }[]; summary: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare() {
    setBusy(true);
    setError(null);
    try {
      const response = await api.libraryCompare(workspaceId, items.map((item) => item.ref));
      const raw = Array.isArray(response.differences) ? (response.differences as unknown[]) : [];
      const differences = raw
        .map((entry) => (entry && typeof entry === 'object' ? (entry as Record<string, unknown>) : null))
        .filter((entry): entry is Record<string, unknown> => Boolean(entry && typeof entry.field === 'string'))
        .map((entry) => ({ field: String(entry.field), before: String(entry.before ?? '—'), after: String(entry.after ?? '—') }));
      setResult({ differences, summary: typeof response.summary === 'string' ? response.summary : null });
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 503 ? 'Comparing versions isn’t available in this version yet. The basic facts are shown above.' : failure instanceof Error ? failure.message : 'The comparison didn’t finish.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='md'>
        <RafiiDialogHeader title='Compare' intro='Each side keeps its own version. Nothing is replaced from here.' />
        <RafiiDialogBody className='flex flex-col gap-4'>
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
          {error ? (
            <p role='alert' className='text-muted-foreground text-sm'>
              {error}
            </p>
          ) : null}
          {result ? (
            <div className='flex flex-col gap-2'>
              {result.summary ? <p className='text-sm'>{result.summary}</p> : null}
              {result.differences.length ? (
                <table className='w-full text-left text-sm'>
                  <thead>
                    <tr className='text-muted-foreground text-xs'>
                      <th scope='col' className='py-1 pr-3 font-medium'>
                        Field
                      </th>
                      <th scope='col' className='py-1 pr-3 font-medium'>
                        First
                      </th>
                      <th scope='col' className='py-1 font-medium'>
                        Second
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.differences.map((difference) => (
                      <tr key={difference.field}>
                        <th scope='row' className='py-1 pr-3 font-normal'>
                          {difference.field}
                        </th>
                        <td className='py-1 pr-3'>{difference.before}</td>
                        <td className='py-1'>{difference.after}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : !result.summary ? (
                <p className='text-muted-foreground text-sm'>No differences were reported for this type of item.</p>
              ) : null}
            </div>
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
