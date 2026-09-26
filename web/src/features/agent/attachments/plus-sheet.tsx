'use client';

/**
 * The ＋ menu (chat-context SPEC §4.2). On a fine pointer and a wide screen it is a `DropdownMenu`; otherwise one
 * `RafiiDialog` sheet with internal views: the menu, the Library grid, search views (the field on top) and accounts.
 * Android back steps out of a view, then closes the sheet (`useCloseWatcher`); the sheet sizes to the visible viewport
 * so the keyboard never covers the first result. Device and text-file pickers are hidden inputs owned by the bar,
 * clicked inside the tap (`onPickDevice`, `onPickText`).
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { Icons } from '@/components/icons';
import {
  RafiiDialog,
  RafiiDialogBody,
  RafiiDialogContent,
  RafiiDialogHeader
} from '@/components/rafii/rafii-dialog';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { useCloseWatcher } from '@/hooks/use-close-watcher';
import { useVisualViewport } from '@/hooks/use-visual-viewport';
import type { Asset, Snapshot } from '@/lib/api/types';

import { LIMITS, type Chip } from './chips';
import type { PickerCategory } from './matcher';
import { LibraryGrid } from './library-grid';
import { pickerItems, type PickerItem } from './picker-items';
import { usePickerSearch } from './use-picker-search';

export type PlusView = 'menu' | 'library' | 'posts' | 'templates' | 'sources' | 'accounts';

const ITEMS: {
  view: PlusView | 'device' | 'text';
  label: string;
  detail: string;
  icon: 'upload' | 'media' | 'post' | 'page' | 'listDetails' | 'account' | 'text';
}[] = [
  { view: 'device', label: 'Photo or video', detail: 'From this device', icon: 'upload' },
  {
    view: 'library',
    label: 'From Library',
    detail: 'Photos and videos you uploaded',
    icon: 'media'
  },
  { view: 'posts', label: 'Post', detail: 'Rework a draft or use it for ideas', icon: 'post' },
  {
    view: 'templates',
    label: 'Template',
    detail: 'Write this message with a template',
    icon: 'page'
  },
  { view: 'sources', label: 'Source', detail: 'Facts Rafii may use', icon: 'listDetails' },
  { view: 'accounts', label: 'Accounts', detail: 'Where this draft goes', icon: 'account' },
  { view: 'text', label: 'Text file', detail: '.txt or .md, up to 20 KB', icon: 'text' }
];

const TITLES: Record<PlusView, string> = {
  menu: 'Add to this message',
  library: 'Library',
  posts: 'Post',
  templates: 'Template',
  sources: 'Source',
  accounts: 'Accounts'
};

const SEARCH: Partial<Record<PlusView, { placeholder: string; groups: PickerCategory[] }>> = {
  posts: { placeholder: 'Search posts', groups: ['posts'] },
  templates: { placeholder: 'Search templates', groups: ['templates'] },
  sources: { placeholder: 'Search sources', groups: ['sources'] },
  accounts: { placeholder: 'Search accounts and folders', groups: ['accounts', 'folders'] }
};

function useWideFinePointer(): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(pointer: fine) and (min-width: 768px)');
    setWide(query.matches);
    const update = (event: MediaQueryListEvent) => setWide(event.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return wide;
}

function SearchView({
  view,
  snapshot,
  owner,
  onPick
}: {
  view: PlusView;
  snapshot: Snapshot | null | undefined;
  owner: string | null | undefined;
  onPick: (item: PickerItem) => void;
}) {
  const [query, setQuery] = useState('');
  const spec = SEARCH[view];
  const local = useMemo(() => {
    const result = pickerItems(snapshot, owner, query, 50);
    return result.groups
      .filter((group) => spec?.groups.includes(group.category))
      .flatMap((group) => group.items);
  }, [snapshot, owner, query, spec]);
  const items = usePickerSearch(query, local, { enabled: Boolean(spec), categories: spec?.groups });
  if (!spec) return null;
  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3'>
      <Input
        autoFocus
        type='search'
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={spec.placeholder}
        aria-label={spec.placeholder}
        className='text-base md:text-sm'
      />
      <ul className='flex min-h-0 flex-col gap-1 overflow-y-auto'>
        {items.map((item) => (
          <li key={`${item.kind}:${item.id}`}>
            <button
              type='button'
              onClick={() => onPick(item)}
              className='rafii-focus hover:bg-foreground/5 flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left text-sm'
            >
              <span className='min-w-0 flex-1 truncate'>{item.label}</span>
              {item.sublabel ? (
                <span className='text-muted-foreground max-w-[45%] shrink-0 truncate text-xs'>
                  {item.sublabel}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface PlusSheetProps {
  trigger: (props: { onClick?: () => void }) => ReactNode;
  snapshot: Snapshot | null | undefined;
  owner: string | null | undefined;
  chips: readonly Chip[];
  creditMode: boolean;
  onPickDevice: () => void;
  onPickText: () => void;
  onPickItem: (item: PickerItem) => void;
  onAddAssets: (assets: Asset[]) => void;
  /** Set to open a view from outside (the `@` list's "More…"). */
  requestedView?: PlusView | null;
  onRequestedViewHandled?: () => void;
}

export function PlusSheet({
  trigger,
  snapshot,
  owner,
  chips,
  creditMode,
  onPickDevice,
  onPickText,
  onPickItem,
  onAddAssets,
  requestedView,
  onRequestedViewHandled
}: PlusSheetProps) {
  const wide = useWideFinePointer();
  const viewport = useVisualViewport();
  const [view, setView] = useState<PlusView | null>(null);
  const open = view !== null;
  const media = chips.filter((chip) => chip.kind === 'image' || chip.kind === 'video');

  useEffect(() => {
    if (!requestedView) return;
    setView(requestedView);
    onRequestedViewHandled?.();
  }, [requestedView, onRequestedViewHandled]);

  const close = () => setView(null);
  // Android back: out of a view to the menu on phones, then closed.
  useCloseWatcher(open, () =>
    setView((current) => (current && current !== 'menu' && !wide ? 'menu' : null))
  );

  function choose(target: PlusView | 'device' | 'text') {
    if (target === 'device') {
      close();
      onPickDevice();
    } else if (target === 'text') {
      close();
      onPickText();
    } else setView(target);
  }

  const hint = creditMode ? (
    <p className='text-muted-foreground px-2 pb-1 text-xs'>Videos cost more to read than photos.</p>
  ) : null;

  const sheet = (
    <RafiiDialog open={open} onOpenChange={(next) => (next ? undefined : close())}>
      <RafiiDialogContent
        size='sm'
        className='flex flex-col'
        style={viewport.height ? { maxHeight: viewport.height - 16 } : undefined}
      >
        <RafiiDialogHeader
          title={view ? TITLES[view] : TITLES.menu}
          back={
            view && view !== 'menu' && !wide ? (
              <Button
                variant='glass'
                size='icon-control'
                className='rounded-full'
                aria-label='Back'
                onClick={() => setView('menu')}
              >
                <Icons.chevronLeft aria-hidden className='size-4' />
              </Button>
            ) : undefined
          }
        />
        <RafiiDialogBody className='flex min-h-0 flex-1 flex-col'>
          {view === 'menu' ? (
            <ul className='flex flex-col gap-1'>
              {ITEMS.map((item) => {
                const Icon = Icons[item.icon];
                return (
                  <li key={item.view}>
                    <button
                      type='button'
                      onClick={() => choose(item.view)}
                      className='rafii-focus hover:bg-foreground/5 flex min-h-11 w-full items-center gap-3 rounded-md px-2 py-2 text-left'
                    >
                      <Icon aria-hidden className='text-muted-foreground size-5 shrink-0' />
                      <span className='flex min-w-0 flex-col'>
                        <span className='text-sm'>{item.label}</span>
                        <span className='text-muted-foreground text-xs'>{item.detail}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
              {hint}
            </ul>
          ) : view === 'library' ? (
            <LibraryGrid
              assets={snapshot?.state.phase2?.assets}
              room={Math.max(0, LIMITS.attachments - media.length)}
              hasVideo={media.some((chip) => chip.kind === 'video')}
              onAdd={(assets) => {
                onAddAssets(assets);
                close();
              }}
              onUpload={() => choose('device')}
            />
          ) : view ? (
            <SearchView
              view={view}
              snapshot={snapshot}
              owner={owner}
              onPick={(item) => {
                onPickItem(item);
                close();
              }}
            />
          ) : null}
        </RafiiDialogBody>
      </RafiiDialogContent>
    </RafiiDialog>
  );

  if (wide) {
    return (
      <>
        <DropdownMenu>
          <DropdownMenuTrigger render={trigger({}) as React.ReactElement} />
          <DropdownMenuContent align='start' className='w-72'>
            <DropdownMenuGroup>
              <DropdownMenuLabel>Add to this message</DropdownMenuLabel>
              {ITEMS.map((item) => {
                const Icon = Icons[item.icon];
                return (
                  <DropdownMenuItem
                    key={item.view}
                    onClick={() => choose(item.view)}
                    className='items-start gap-3 py-2'
                  >
                    <Icon aria-hidden className='text-muted-foreground mt-0.5 size-4 shrink-0' />
                    <span className='flex min-w-0 flex-col'>
                      <span>{item.label}</span>
                      <span className='text-muted-foreground text-xs'>{item.detail}</span>
                    </span>
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuGroup>
            {hint}
          </DropdownMenuContent>
        </DropdownMenu>
        {sheet}
      </>
    );
  }
  return (
    <>
      {trigger({ onClick: () => setView('menu') })}
      {sheet}
    </>
  );
}
