'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useSnapshot, keys } from '@/lib/api/hooks';
import type { LibraryAsset } from './use-library';

export function useLibraryCollections() {
  const { api, workspaceId } = useWorkspaceApi();
  return useQuery({ queryKey: ['library-collections', workspaceId], queryFn: () => api.libraryCollections(workspaceId), enabled: Boolean(workspaceId) });
}

export function CollectionManager({ canEdit }: { canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const collections = useLibraryCollections();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  async function change(action: () => Promise<unknown>) {
    setBusy(true);
    try { await action(); setName(''); await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] }); await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] }); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Could not update collections'); }
    finally { setBusy(false); }
  }
  if (!canEdit) return null;
  return <details className='rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3'>
    <summary className='rafii-focus cursor-pointer text-sm'>Manage collections</summary>
    <form className='mt-3 flex gap-2' onSubmit={(e) => { e.preventDefault(); void change(() => api.createLibraryCollection(workspaceId, name)); }}>
      <Input aria-label='New collection name' value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder='Collection name' />
      <Button type='submit' variant='glass' disabled={busy || !name.trim()}>Create</Button>
    </form>
    <ul className='mt-3 space-y-2'>{collections.data?.collections.map((c) => <li key={c.id} className='flex items-center justify-between gap-3 text-sm'>
      <span>{c.name} <span className='text-muted-foreground'>({c.count})</span></span>
      <Button variant='quiet' size='sm' disabled={busy} aria-label={`Remove collection ${c.name}`} onClick={() => void change(() => api.deleteLibraryCollection(workspaceId, c.id))}>Remove collection</Button>
    </li>)}</ul>
    <p className='text-muted-foreground mt-2 text-xs'>Removing a collection keeps its files in your Library.</p>
  </details>;
}

export function AssetOrganizer({ asset, canEdit }: { asset: LibraryAsset; canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const client = useQueryClient();
  const collections = useLibraryCollections();
  const [title, setTitle] = useState(asset.displayTitle ?? asset.originalFilename ?? '');
  const [tags, setTags] = useState((asset.tags ?? asset.aiTags ?? []).join(', '));
  const [selected, setSelected] = useState(asset.collections ?? []);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<string | null>(asset.sourceId ?? null);
  async function change(action: () => Promise<unknown>) {
    setBusy(true);
    try { await action(); await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] }); await client.invalidateQueries({ queryKey: ['library-file-detail', workspaceId, asset.id] }); await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] }); toast.success('Library updated'); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'Could not update this asset'); }
    finally { setBusy(false); }
  }
  if (!canEdit) return null;
  const normalized = ['document','file','audio'].includes(asset.assetKind ?? '');
  const ready = ['ready','unsupported'].includes(asset.processing ?? '');
  return <section aria-label='Organize asset' className='space-y-4'>
    <form className='space-y-3' onSubmit={(e) => { e.preventDefault(); void change(() => api.updateLibraryAsset(workspaceId, asset.id, { ...(title.trim() ? { title } : {}), tags: tags.split(',').map((t) => t.trim()).filter(Boolean), collections: selected })); }}>
      <label htmlFor={'library-title-'+asset.id} className='block text-xs'>Title<Input id={'library-title-'+asset.id} aria-label='Title' value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} className='mt-1' /></label>
      <label htmlFor={'library-tags-'+asset.id} className='block text-xs'>Tags, separated by commas<Input id={'library-tags-'+asset.id} aria-label='Tags, separated by commas' value={tags} maxLength={1200} onChange={(e) => setTags(e.target.value)} className='mt-1' /></label>
      {collections.data?.collections.length ? <fieldset><legend className='text-xs'>Collections</legend><div className='mt-1 flex flex-wrap gap-3'>{collections.data.collections.map((c) => {
        const id = `library-collection-${asset.id}-${c.id}`;
        return <label key={c.id} htmlFor={id} className='flex min-h-10 items-center gap-2 text-sm'>
          <input id={id} type='checkbox' aria-label={`Add to collection ${c.name}`} checked={selected.includes(c.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id))} />{c.name}
        </label>;
      })}</div></fieldset> : null}
      <Button type='submit' variant='glass' disabled={busy}>Save details</Button>
    </form>
    {normalized && (asset.canRetryProcessing || ['failed','queued'].includes(asset.processing ?? '')) ? <Button variant='glass' disabled={busy} onClick={() => void change(() => api.retryLibraryFile(workspaceId, asset.id))}>{asset.processing === 'unsupported' ? 'Index document' : 'Retry processing'}</Button> : null}
    {asset.assetKind === 'audio' && ready ? <details><summary className='rafii-focus cursor-pointer text-sm'>Add or replace transcript</summary>
      <p className='text-muted-foreground my-2 text-xs'>Automatic transcription is unavailable. A supplied transcript becomes searchable and keeps its provenance.</p>
      <label htmlFor={'library-transcript-'+asset.id} className='block text-xs'>Transcript<textarea id={'library-transcript-'+asset.id} aria-label='Transcript' className='rafii-quiet rafii-focus mt-1 min-h-28 w-full rounded-lg p-3 text-sm' maxLength={250000} value={text} onChange={(e) => setText(e.target.value)} /></label>
      <Button className='mt-2' variant='glass' disabled={busy || !text.trim()} onClick={() => void change(async () => { await api.libraryTranscript(workspaceId, asset.id, text); setSource(null); await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }); })}>Save transcript</Button>
    </details> : null}
    {normalized && ready && asset.indexingStatus === 'ready' ? <div className='space-y-2'>
      <Button variant='glass' disabled={busy || !snapshot.data || Boolean(source)} onClick={() => void change(async () => {
        const result = await api.librarySource(workspaceId, asset.id, snapshot.data!.revision); setSource(result.sourceId); await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      })}>{source ? 'Source added for review' : 'Use as a source'}</Button>
      <p className='text-muted-foreground text-xs'>Review the extracted facts and sharing permission in Ideas before Rafii uses them. Long documents use a labelled excerpt of up to 19,000 characters.</p>
      {source ? <a className='rafii-focus text-sm underline underline-offset-4' href={`/app/ideas?source=${encodeURIComponent(source)}`}>Review source in Ideas</a> : null}
    </div> : null}
  </section>;
}
