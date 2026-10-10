'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { LibraryMetadataFields, LibraryMetadataReceipt, LibraryMetadataSelection } from '@/lib/api/library-metadata';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from './use-library';

const LABELS = { title: 'Title', tags: 'Tags', collections: 'Collections' };
function fieldValue(fields: LibraryMetadataFields, key: keyof LibraryMetadataFields) {
  if (key === 'collections') return fields.collections.length ? fields.collections.map(c => `${c.name} (${c.id})`).join(', ') : 'No collections';
  if (key === 'tags') return fields.tags.length ? JSON.stringify(fields.tags) : 'No tags';
  return fields.title || 'Untitled';
}

/** The selection is explicit metadata only; a workspace switch discards every receipt. */
export function LibraryMetadataPreview({ changes, disabled = false }: { changes: LibraryMetadataSelection[]; disabled?: boolean }) {
  const { workspaceId } = useWorkspaceApi();
  const actor = useAuth().user?.id;
  if (!actor) return null;
  return <MetadataReview key={workspaceId + actor} changes={changes} disabled={disabled} />;
}

function MetadataReview({ changes, disabled, initialReceipt = null }: { changes: LibraryMetadataSelection[]; disabled: boolean; initialReceipt?: LibraryMetadataReceipt | null }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [receipt, setReceipt] = useState<LibraryMetadataReceipt | null>(initialReceipt);
  const [reviewKey, setReviewKey] = useState('');
  const selectionKey = JSON.stringify(changes);
  const shown = receipt && (receipt.status !== 'prepared' || reviewKey === selectionKey) ? receipt : null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(kind: 'preview' | 'apply' | 'undo') {
    setBusy(true); setError(null);
    try {
      const result = kind === 'preview' ? await api.previewLibraryMetadata(workspaceId, changes)
        : kind === 'apply' ? await api.applyLibraryMetadata(workspaceId, receipt!.receiptId)
          : await api.undoLibraryMetadata(workspaceId, receipt!.receiptId);
      setReceipt(result);
      if (kind === 'preview') setReviewKey(selectionKey);
      if (kind !== 'preview') await Promise.all([
        client.invalidateQueries({ queryKey: ['library-assets', workspaceId] }),
        client.invalidateQueries({ queryKey: ['library-file-detail', workspaceId] }),
        client.invalidateQueries({ queryKey: ['library-collections', workspaceId] }),
        client.invalidateQueries({ queryKey: ['library-metadata-history', workspaceId] }),
        client.invalidateQueries({ queryKey: ['library-metadata-receipt', workspaceId] }),
        client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) })
      ]);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Could not complete this Library change.';
      setError(message);
      if (reason instanceof ApiError && reason.status === 409 && kind === 'undo') setReceipt(r => r ? { ...r, canUndo: false, undoReason: message } : r);
      if (reason instanceof ApiError && [403, 404, 409].includes(reason.status) && kind === 'apply') setReceipt(null);
    } finally { setBusy(false); }
  }
  return <div className='space-y-3' aria-label='Library metadata changes'>
    {!shown ? <Button type='button' variant='glass' disabled={disabled || busy || !changes.length || changes.length > 20} onClick={() => void run('preview')}>{busy ? 'Preparing preview…' : 'Preview changes'}</Button> : null}
    {error ? <p role='alert' className='text-sm'>{error}</p> : null}
    {shown ? <section aria-label='Metadata change preview' className='rafii-quiet space-y-4 rounded-lg p-3'>
      <p role='status' className='text-sm font-medium'>{shown.status === 'prepared' ? `Review changes to ${shown.entries.length} ${shown.entries.length === 1 ? 'asset' : 'assets'}` : shown.status === 'applied' ? 'Changes applied and verified' : 'Changes undone and verified'}</p>
      <p className='text-muted-foreground text-xs'>Only titles, tags and collection membership change. File contents stay in your Library.</p>
      <ul className='space-y-4'>{shown.entries.map(entry => <li key={entry.assetId} className='space-y-2'>
        <p className='break-words text-sm font-medium'>{entry.current.title || 'Untitled asset'}</p>
        <p className='text-muted-foreground break-all text-xs'>Asset {entry.assetId}</p>
        <dl className='space-y-3'>{entry.changedFields.map(field => <div key={field} className='space-y-1 text-sm'>
          <dt className='font-medium'>{LABELS[field]}</dt>
          <dd className='grid min-w-0 gap-2 sm:grid-cols-2'>
            <div className='min-w-0 break-words'><span className='text-muted-foreground text-xs'>Current</span><p className='whitespace-pre-wrap'>{fieldValue(entry.current, field)}</p></div>
            <div className='min-w-0 break-words'><span className='text-muted-foreground text-xs'>Proposed</span><p className='whitespace-pre-wrap'>{fieldValue(entry.proposed, field)}</p></div>
          </dd>
        </div>)}</dl>
      </li>)}</ul>
      {shown.status === 'prepared' ? <div className='flex flex-wrap gap-2'>
        <Button type='button' variant='glass' disabled={busy} onClick={() => void run('apply')}>{busy ? 'Applying…' : 'Apply changes'}</Button>
        <Button type='button' variant='quiet' disabled={busy} onClick={() => setReceipt(null)}>Discard preview</Button>
      </div> : null}
      {shown.status === 'applied' ? <div className='space-y-2'>
        <Button type='button' variant='glass' disabled={busy || !shown.canUndo} onClick={() => void run('undo')}>{busy ? 'Undoing…' : 'Undo changes'}</Button>
        <p className='text-muted-foreground text-xs'>{shown.undoReason || 'Undo is available for 24 hours while these assets and collections remain unchanged. Permissions are checked again.'}</p>
      </div> : null}
      {shown.status !== 'prepared' && !initialReceipt ? <Button type='button' variant='quiet' disabled={busy} onClick={() => setReceipt(null)}>Prepare another change</Button> : null}
      <p className='text-muted-foreground break-all text-xs'>Change receipt: {shown.receiptId}</p>
    </section> : null}
  </div>;
}

export function LibraryMetadataHistory() {
  const { api, workspaceId } = useWorkspaceApi();
  const actor = useAuth().user?.id;
  const [selected, setSelected] = useState<string | null>(null);
  const history = useQuery({ queryKey: ['library-metadata-history', workspaceId, actor], queryFn: () => api.libraryMetadataHistory(workspaceId), enabled: Boolean(workspaceId && actor), retry: false });
  const detail = useQuery({ queryKey: ['library-metadata-receipt', workspaceId, actor, selected], queryFn: () => api.libraryMetadataReceipt(workspaceId, selected!), enabled: Boolean(selected && workspaceId && actor), retry: false });
  if (history.error instanceof ApiError && history.error.code === 'library_metadata_unavailable') return null;
  if (!history.isError && !history.data?.changes.length) return null;
  return <details className='rafii-quiet space-y-3 rounded-lg p-4' onToggle={event => { if (event.currentTarget.open) void history.refetch(); }}>
    <summary className='rafii-focus cursor-pointer text-sm'>Recent metadata changes</summary>
    <p className='text-muted-foreground text-xs'>Your last 10 applied changes in this workspace. Open a receipt to check whether Undo is still available.</p>
    {history.isError ? <p role='alert' className='text-sm'>{history.error.message}</p> : null}
    <ul className='space-y-2'>{history.data?.changes.map(change => <li key={change.receiptId} className='flex flex-wrap items-center justify-between gap-2 text-sm'>
      <span className='min-w-0 break-words'>{change.firstTitle || 'Untitled asset'} · {change.assetCount} {change.assetCount === 1 ? 'asset' : 'assets'} · {change.status === 'undone' ? 'Undone' : 'Applied'}</span>
      <Button type='button' variant='quiet' size='sm' onClick={() => { setSelected(change.receiptId); if (selected === change.receiptId) void detail.refetch(); }}>Open change</Button>
    </li>)}</ul>
    {detail.isFetching ? <p role='status' className='text-sm'>Checking current permissions and Library details…</p> : selected && detail.data ? <MetadataReview key={selected + detail.data.status} changes={[]} disabled initialReceipt={detail.data} /> : null}
    {selected && detail.isError ? <p role='alert' className='text-sm'>{detail.error.message}</p> : null}
  </details>;
}

/** Explicit selection from the current result page, never an implicit whole-Library update. */
export function LibraryBatchOrganizer({ assets, collections }: { assets: LibraryAsset[]; collections: { id: string; name: string }[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [replaceTags, setReplaceTags] = useState(false);
  const [tags, setTags] = useState('');
  const [replaceCollections, setReplaceCollections] = useState(false);
  const [groups, setGroups] = useState<string[]>([]);
  const chosen = selected.filter(id => assets.some(a => a.id === id));
  const changes = chosen.map(assetId => ({ assetId, changes: {
    ...(replaceTags ? { tags: tags.split(',').map(t => t.trim()).filter(Boolean) } : {}),
    ...(replaceCollections ? { collections: groups } : {})
  } }));
  return <details className='rafii-quiet rounded-lg p-4'>
    <summary className='rafii-focus cursor-pointer text-sm'>Organize selected assets</summary>
    <div className='mt-3 space-y-4'>
      <p className='text-muted-foreground text-xs'>Choose up to 20 assets from these results. Review exact changes before applying them.</p>
      <fieldset className='max-h-52 space-y-1 overflow-y-auto'><legend className='mb-2 text-sm'>Assets to change ({chosen.length}/20)</legend>
        {assets.map(asset => <label key={asset.id} className='flex min-h-10 items-center gap-2 text-sm'>
          <input type='checkbox' aria-label={`Select ${asset.displayTitle || asset.originalFilename || asset.id}`} checked={chosen.includes(asset.id)} disabled={!chosen.includes(asset.id) && chosen.length >= 20}
            onChange={e => setSelected(e.target.checked ? [...chosen, asset.id] : chosen.filter(id => id !== asset.id))} />
          <span className='min-w-0 break-words'>{asset.displayTitle || asset.originalFilename || asset.id}</span>
        </label>)}
      </fieldset>
      <label className='flex min-h-10 items-center gap-2 text-sm'><input type='checkbox' checked={replaceTags} onChange={e => setReplaceTags(e.target.checked)} />Replace tags for selected assets</label>
      {replaceTags ? <Input aria-label='Replacement tags' value={tags} maxLength={1200} onChange={e => setTags(e.target.value)} placeholder='Comma-separated tags; empty removes all tags' /> : null}
      <label className='flex min-h-10 items-center gap-2 text-sm'><input type='checkbox' checked={replaceCollections} onChange={e => setReplaceCollections(e.target.checked)} />Replace collections for selected assets</label>
      {replaceCollections ? <fieldset className='flex flex-wrap gap-3'><legend className='mb-2 text-xs'>Choose collections; none removes all memberships</legend>{collections.map(c => <label key={c.id} className='flex min-h-10 items-center gap-2 text-sm'>
        <input type='checkbox' checked={groups.includes(c.id)} onChange={e => setGroups(e.target.checked ? [...groups, c.id] : groups.filter(id => id !== c.id))} />{c.name}
      </label>)}</fieldset> : null}
      <LibraryMetadataPreview changes={changes} disabled={!replaceTags && !replaceCollections} />
    </div>
  </details>;
}
