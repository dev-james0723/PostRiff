'use client';

import { useId, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { countLabel, storageNotice } from '@/lib/library/wording';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useLibraryCollections } from '../library-organizer';
import { SmartCollectionDialog } from './smart-collections';

function chip(selected: boolean) {
  return cn(
    'rafii-focus inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3.5 text-sm whitespace-nowrap transition-colors lg:w-full lg:justify-between lg:whitespace-normal',
    selected ? 'rafii-glass-selected text-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:rafii-quiet'
  );
}

/**
 * Collection navigation (UI spec §1): a collapsible rail beside the results on wide screens, a single-row switcher on
 * tablets and phones. One element in one place in the DOM, so the switcher and its management are never duplicated
 * for assistive tech. Collection management lives here, in its navigation context, instead of above the results.
 */
export function CollectionRail({
  active,
  onSelect,
  canEdit,
  collapsed,
  onCollapsedChange,
  storage,
  smartCollections = false,
  onAnnounce,
  className
}: {
  active: string;
  onSelect: (collectionId: string) => void;
  canEdit: boolean;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  storage?: { usedBytes: number; limitBytes: number } | null;
  /** Smart collections can be created when the Library intelligence service answers in this build. */
  smartCollections?: boolean;
  onAnnounce?: (message: string) => void;
  className?: string;
}) {
  const collections = useLibraryCollections();
  const list = collections.data?.collections ?? [];
  const [managing, setManaging] = useState(false);
  const panelId = useId();
  const notice = storage ? storageNotice(storage.usedBytes, storage.limitBytes) : null;

  if (collapsed) {
    return (
      <nav aria-label='Collections' className={cn('hidden lg:flex lg:flex-col lg:items-center', className)}>
        <Button variant='glass' size='icon-control' aria-label='Show collections' aria-expanded={false} onClick={() => onCollapsedChange(false)}>
          <Icons.panelLeft aria-hidden />
        </Button>
      </nav>
    );
  }

  return (
    <nav aria-label='Collections' className={cn('flex min-w-0 flex-col gap-2 lg:sticky lg:top-20 lg:gap-3', className)}>
      <div className='hidden items-center justify-between gap-2 lg:flex'>
        <h2 className='rafii-eyebrow'>Collections</h2>
        <Button variant='quiet' size='icon-control' aria-label='Hide collections' aria-expanded onClick={() => onCollapsedChange(true)}>
          <Icons.panelLeft aria-hidden />
        </Button>
      </div>
      {/* Phones and tablets: one horizontal row that scrolls inside itself, never the page. */}
      <ul className='scrollbar-hide -mx-1 flex min-w-0 gap-1.5 overflow-x-auto px-1 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0'>
        <li className='flex'>
          <button type='button' className={chip(!active)} aria-current={!active ? 'true' : undefined} onClick={() => onSelect('')}>
            <span>Entire Library</span>
          </button>
        </li>
        {list.map((collection) => (
          <li key={collection.id} className='flex'>
            <button
              type='button'
              className={chip(active === collection.id)}
              aria-current={active === collection.id ? 'true' : undefined}
              aria-label={`${collection.name}, ${collection.kind === 'smart' ? 'smart collection, ' : ''}${countLabel(collection.count)}`}
              onClick={() => onSelect(collection.id)}
            >
              <span className='flex min-w-0 items-center gap-1.5'>
                {collection.kind === 'smart' ? <Icons.sparkles className='size-3.5 shrink-0' aria-hidden /> : null}
                <span className='max-w-[12rem] truncate lg:max-w-none'>{collection.name}</span>
                {collection.kind === 'smart' ? <span className='text-muted-foreground text-[11px]'>Smart</span> : null}
              </span>
              <span aria-hidden className='text-muted-foreground text-xs tabular-nums'>
                {collection.count}
              </span>
            </button>
          </li>
        ))}
        {canEdit ? (
          <li className='flex'>
            <button
              type='button'
              aria-expanded={managing}
              aria-controls={panelId}
              onClick={() => setManaging((value) => !value)}
              className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3.5 text-sm whitespace-nowrap lg:w-full'
            >
              <Icons.folder className='size-4' aria-hidden />
              Manage collections
            </button>
          </li>
        ) : null}
      </ul>
      {canEdit && managing ? (
        <CollectionManagement id={panelId} onRemoved={(id) => id === active && onSelect('')} smartCollections={smartCollections} onCreated={(id) => onSelect(id)} onAnnounce={onAnnounce} />
      ) : null}
      {notice && notice.level !== 'unknown' ? (
        <p className={cn('hidden px-1 text-xs lg:block', notice.level === 'ok' ? 'text-muted-foreground' : 'text-foreground font-medium')}>{notice.label}</p>
      ) : null}
    </nav>
  );
}

/** Create and remove collections. Removing a collection keeps its files. */
function CollectionManagement({
  id,
  onRemoved,
  smartCollections,
  onCreated,
  onAnnounce
}: {
  id: string;
  onRemoved: (collectionId: string) => void;
  smartCollections: boolean;
  onCreated: (collectionId: string) => void;
  onAnnounce?: (message: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const collections = useLibraryCollections();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [building, setBuilding] = useState(false);

  async function change(action: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    try {
      await action();
      setName('');
      after?.();
      await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] });
      await client.invalidateQueries({ queryKey: ['library-assets', workspaceId] });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not update collections');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id={id} aria-label='Manage collections' className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-3'>
      <form
        className='flex gap-2'
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) void change(() => api.createLibraryCollection(workspaceId, name.trim()));
        }}
      >
        <Input aria-label='New collection name' value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder='Collection name' className='h-11 min-w-0' />
        <Button type='submit' variant='glass' size='control' className='h-11' disabled={busy || !name.trim()}>
          Create
        </Button>
      </form>
      {collections.data?.collections.length ? (
        <ul className='flex flex-col gap-1'>
          {collections.data.collections.map((collection) => (
            <li key={collection.id} className='flex min-h-11 items-center justify-between gap-2 text-sm'>
              <span className='min-w-0 truncate'>
                {collection.name} <span className='text-muted-foreground'>({collection.count})</span>
              </span>
              <Button
                variant='quiet'
                size='lg'
                className='h-11 shrink-0'
                disabled={busy}
                aria-label={`Remove collection ${collection.name}`}
                onClick={() => void change(() => api.deleteLibraryCollection(workspaceId, collection.id), () => onRemoved(collection.id))}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {smartCollections ? (
        <>
          <Button variant='glass' size='control' className='h-11 self-start' onClick={() => setBuilding(true)}>
            <Icons.sparkles aria-hidden />
            New smart collection
          </Button>
          <SmartCollectionDialog open={building} onOpenChange={setBuilding} existing={null} onSaved={onCreated} onAnnounce={onAnnounce ?? (() => undefined)} />
        </>
      ) : null}
      <p className='text-muted-foreground text-xs'>Removing a collection keeps its files in your Library. Smart collections add and remove items by their criteria.</p>
    </section>
  );
}
