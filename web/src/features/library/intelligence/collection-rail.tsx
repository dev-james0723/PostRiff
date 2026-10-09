'use client';

import { useId, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Input } from '@/components/ui/input';
import { countLabel, storageNotice } from '@/lib/library/wording';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useLibraryCollections } from '../library-organizer';
import { Control, IconControl } from '../ui/controls';
import { SmartCollectionDialog } from './smart-collections';

/**
 * One destination in the rail. Wide screens: a full-width row with its count. Phones and tablets: a chip in a single
 * row that scrolls inside itself.
 */
function railItem(selected: boolean) {
  return cn(
    'rafii-focus inline-flex h-9 shrink-0 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 text-[13px] whitespace-nowrap transition-colors duration-150 pointer-coarse:h-11',
    'lg:h-8 lg:w-full lg:justify-between lg:px-2.5 lg:whitespace-normal lg:pointer-coarse:h-11',
    selected ? 'bg-foreground/[0.07] text-foreground font-medium' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05]'
  );
}

function RailCount({ value }: { value: number }) {
  return (
    <span aria-hidden className='text-muted-foreground text-xs tabular-nums'>
      {value.toLocaleString()}
    </span>
  );
}

function RailGroup({ label, action, children }: { label: string; action?: ReactNode; children: ReactNode }) {
  return (
    <li className='flex shrink-0 lg:flex-col lg:gap-0.5'>
      <div className='hidden h-8 items-center justify-between pr-1 pl-2.5 lg:flex'>
        <span className='text-muted-foreground text-xs font-medium'>{label}</span>
        {action}
      </div>
      <ul aria-label={label} className='flex gap-1 lg:flex-col lg:gap-0.5'>
        {children}
      </ul>
    </li>
  );
}

/**
 * The Library navigation rail (redesign §3; UI spec §1): All assets, Collections and Smart views, with a quiet storage
 * meter at the foot. A collapsible column beside the results on wide screens, a single-row switcher on tablets and
 * phones. One element in one place in the DOM, so the switcher and its management are never duplicated for assistive
 * tech. Collection management lives here, in its navigation context, instead of above the results.
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
  const manual = list.filter((collection) => collection.kind !== 'smart');
  const smart = list.filter((collection) => collection.kind === 'smart');
  const [managing, setManaging] = useState(false);
  const [building, setBuilding] = useState(false);
  const panelId = useId();
  const notice = storage ? storageNotice(storage.usedBytes, storage.limitBytes) : null;

  if (collapsed) {
    return (
      <nav aria-label='Collections' className={cn('hidden lg:flex lg:flex-col lg:items-center lg:gap-1', className)}>
        <IconControl label='Show collections' side='right' aria-expanded={false} onClick={() => onCollapsedChange(false)}>
          <Icons.panelLeft aria-hidden />
        </IconControl>
        <IconControl label='All assets' side='right' active={!active} aria-current={!active ? 'true' : undefined} onClick={() => onSelect('')}>
          <Icons.media aria-hidden />
        </IconControl>
      </nav>
    );
  }

  const item = (collection: (typeof list)[number]) => (
    <li key={collection.id} className='flex'>
      <button
        type='button'
        className={railItem(active === collection.id)}
        aria-current={active === collection.id ? 'true' : undefined}
        aria-label={`${collection.name}, ${collection.kind === 'smart' ? 'smart collection, ' : ''}${countLabel(collection.count)}`}
        onClick={() => onSelect(collection.id)}
      >
        <span className='flex min-w-0 items-center gap-2'>
          {collection.kind === 'smart' ? <Icons.sparkles className='size-3.5 shrink-0' aria-hidden /> : <Icons.folder className='size-3.5 shrink-0 opacity-70' aria-hidden />}
          <span className='max-w-[12rem] truncate lg:max-w-none'>{collection.name}</span>
        </span>
        <RailCount value={collection.count} />
      </button>
    </li>
  );

  return (
    <nav aria-label='Collections' className={cn('flex min-w-0 flex-col gap-2 lg:sticky lg:top-20 lg:gap-4', className)}>
      <div className='hidden items-center justify-between lg:flex'>
        <h2 className='text-sm font-medium'>Library</h2>
        <IconControl label='Hide collections' size='sm' side='right' aria-expanded onClick={() => onCollapsedChange(true)}>
          <Icons.panelLeft aria-hidden />
        </IconControl>
      </div>
      {/* Phones and tablets: one horizontal row that scrolls inside itself, never the page. */}
      <ul className='scrollbar-hide -mx-1 flex min-w-0 gap-1 overflow-x-auto px-1 lg:mx-0 lg:flex-col lg:gap-4 lg:overflow-visible lg:px-0'>
        <li className='flex'>
          <button type='button' className={railItem(!active)} aria-current={!active ? 'true' : undefined} onClick={() => onSelect('')}>
            <span className='flex min-w-0 items-center gap-2'>
              <Icons.media className='size-3.5 shrink-0 opacity-70' aria-hidden />
              All assets
            </span>
          </button>
        </li>
        {manual.length ? <RailGroup label='Collections'>{manual.map(item)}</RailGroup> : null}
        {smart.length || (smartCollections && canEdit) ? (
          <RailGroup
            label='Smart views'
            action={
              smartCollections && canEdit ? (
                <IconControl label='New smart view' size='sm' side='right' onClick={() => setBuilding(true)}>
                  <Icons.add aria-hidden />
                </IconControl>
              ) : undefined
            }
          >
            {smart.map(item)}
          </RailGroup>
        ) : null}
        {canEdit ? (
          <li className='flex'>
            <button
              type='button'
              aria-expanded={managing}
              aria-controls={panelId}
              onClick={() => setManaging((value) => !value)}
              className={cn(railItem(false), 'lg:justify-start')}
            >
              <Icons.folder className='size-3.5 shrink-0' aria-hidden />
              Manage collections
            </button>
          </li>
        ) : null}
      </ul>
      {canEdit && managing ? (
        <CollectionManagement id={panelId} onRemoved={(id) => id === active && onSelect('')} smartCollections={smartCollections} onBuildSmart={() => setBuilding(true)} />
      ) : null}
      {smartCollections && canEdit ? (
        <SmartCollectionDialog open={building} onOpenChange={setBuilding} existing={null} onSaved={(id) => onSelect(id)} onAnnounce={onAnnounce ?? (() => undefined)} />
      ) : null}
      {notice && notice.level !== 'unknown' ? (
        <div className='hidden flex-col gap-1.5 px-2.5 lg:flex'>
          <div aria-hidden className='bg-foreground/[0.08] h-1 overflow-hidden rounded-full'>
            <div className={cn('h-full rounded-full', notice.level === 'ok' ? 'bg-foreground/40' : 'bg-destructive')} style={{ width: `${Math.min(100, Math.max(2, (notice.ratio ?? 0) * 100))}%` }} />
          </div>
          <p className={cn('text-xs tabular-nums', notice.level === 'ok' ? 'text-muted-foreground' : 'text-foreground font-medium')}>{notice.label}</p>
        </div>
      ) : null}
    </nav>
  );
}

/** Create and remove collections. Removing a collection keeps its files. */
function CollectionManagement({
  id,
  onRemoved,
  smartCollections,
  onBuildSmart
}: {
  id: string;
  onRemoved: (collectionId: string) => void;
  smartCollections: boolean;
  onBuildSmart: () => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const collections = useLibraryCollections();
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);

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
    <section id={id} aria-label='Manage collections' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-2.5'>
      <form
        className='flex gap-1.5'
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) void change(() => api.createLibraryCollection(workspaceId, name.trim()));
        }}
      >
        <Input aria-label='New collection name' value={name} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder='New collection' className='h-9 min-w-0 text-sm pointer-coarse:h-11' />
        <Control type='submit' tone='secondary' size='md' disabled={busy || !name.trim()}>
          Create
        </Control>
      </form>
      {collections.data?.collections.length ? (
        <ul className='flex flex-col'>
          {collections.data.collections.map((collection) => (
            <li key={collection.id} className='flex min-h-9 items-center justify-between gap-2 text-[13px] pointer-coarse:min-h-11'>
              <span className='min-w-0 truncate'>
                {collection.name} <span className='text-muted-foreground tabular-nums'>({collection.count})</span>
              </span>
              <Control
                tone='ghost'
                size='sm'
                className='shrink-0'
                disabled={busy}
                aria-label={`Remove collection ${collection.name}`}
                onClick={() => void change(() => api.deleteLibraryCollection(workspaceId, collection.id), () => onRemoved(collection.id))}
              >
                Remove
              </Control>
            </li>
          ))}
        </ul>
      ) : null}
      {smartCollections ? (
        <Control tone='ghost' size='sm' className='self-start' icon={<Icons.sparkles aria-hidden />} onClick={onBuildSmart}>
          New smart view
        </Control>
      ) : null}
      <p className='text-muted-foreground text-xs leading-relaxed'>Removing a collection keeps its files in your Library. Smart views add and remove items by their rules.</p>
    </section>
  );
}
