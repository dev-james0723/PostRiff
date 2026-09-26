'use client';

/**
 * The ＋ menu (chat-context SPEC §4.2). One attachment system owns local media, workspace references,
 * explicit skills and on-demand productivity connector picks. Connector content is never background-synced.
 */
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';

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
import type {
  Asset,
  AttachmentsCatalog,
  ProductivityConnectorCatalog,
  ProductivityConnectorConnection,
  Snapshot
} from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

import { LIMITS, type Chip } from './chips';
import type { PickerCategory } from './matcher';
import { LibraryGrid } from './library-grid';
import {
  pickerItems,
  type ConnectorItemLike,
  type PickerItem,
  type SkillLike
} from './picker-items';
import { usePickerSearch } from './use-picker-search';

export type PlusView =
  | 'menu'
  | 'library'
  | 'posts'
  | 'templates'
  | 'sources'
  | 'accounts'
  | 'skills'
  | 'connectors';

const ITEMS: {
  view: PlusView | 'device' | 'text';
  label: string;
  detail: string;
  icon: keyof typeof Icons;
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
  { view: 'skills', label: 'Skill', detail: 'Use an approved skill for this message', icon: 'sparkles' },
  {
    view: 'connectors',
    label: 'Connected apps',
    detail: 'Choose a Notion page or Gmail message',
    icon: 'link'
  },
  { view: 'accounts', label: 'Accounts', detail: 'Where this draft goes', icon: 'account' },
  { view: 'text', label: 'Text file', detail: '.txt or .md, up to 20 KB', icon: 'text' }
];

const TITLES: Record<PlusView, string> = {
  menu: 'Add to this message',
  library: 'Library',
  posts: 'Post',
  templates: 'Template',
  sources: 'Source',
  accounts: 'Accounts',
  skills: 'Skills',
  connectors: 'Connected apps'
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
  const items = usePickerSearch(query, local, {
    enabled: Boolean(spec),
    categories: spec?.groups
  });
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

function SkillsView({
  skills,
  onPick
}: {
  skills: readonly SkillLike[];
  onPick: (item: PickerItem) => void;
}) {
  const [query, setQuery] = useState('');
  const items = useMemo(
    () =>
      skills
        .filter((skill) =>
          [skill.name, skill.description, skill.version]
            .join(' ')
            .toLocaleLowerCase()
            .includes(query.trim().toLocaleLowerCase())
        )
        .map<PickerItem>((skill) => ({
          kind: 'skill',
          id: skill.id,
          label: skill.name,
          sublabel: skill.description || skill.version,
          search: [skill.description, skill.version].filter(Boolean).join('\n')
        })),
    [query, skills]
  );

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3'>
      <Input
        autoFocus
        type='search'
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder='Search skills'
        aria-label='Search skills'
        className='text-base md:text-sm'
      />
      {items.length ? (
        <ul className='flex min-h-0 flex-col gap-1 overflow-y-auto'>
          {items.map((item) => (
            <li key={item.id}>
              <button
                type='button'
                onClick={() => onPick(item)}
                className='rafii-focus hover:bg-foreground/5 flex min-h-11 w-full items-center gap-3 rounded-md px-2 py-2 text-left'
              >
                <Icons.sparkles aria-hidden className='text-muted-foreground size-4 shrink-0' />
                <span className='flex min-w-0 flex-1 flex-col'>
                  <span className='truncate text-sm'>{item.label}</span>
                  {item.sublabel ? (
                    <span className='text-muted-foreground line-clamp-2 text-xs'>{item.sublabel}</span>
                  ) : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className='text-muted-foreground px-2 py-4 text-sm'>
          {skills.length ? 'No matching skills.' : 'No explicit skills are available on this deployment.'}
        </p>
      )}
    </div>
  );
}

function connectionLabel(connection: ProductivityConnectorConnection): string {
  const provider = connection.provider === 'gmail' ? 'Gmail' : connection.provider === 'notion' ? 'Notion' : connection.provider;
  return `${provider} · ${connection.account}`;
}

function ConnectedAppsView({
  onPick,
  onRemember
}: {
  onPick: (item: PickerItem) => void;
  onRemember: (items: readonly ConnectorItemLike[]) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [catalog, setCatalog] = useState<ProductivityConnectorCatalog | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<ConnectorItemLike[]>([]);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.connectorCatalog(workspaceId).then(
      (result) => {
        if (!alive) return;
        setCatalog(result);
        const first = result.connections.find((connection) => !connection.revoked);
        setSelected((current) => current ?? first?.connectionId ?? null);
        setLoading(false);
      },
      () => {
        if (!alive) return;
        setError('Connected apps are unavailable right now.');
        setLoading(false);
      }
    );
    return () => {
      alive = false;
    };
  }, [api, workspaceId]);

  const connect = async (provider: string) => {
    setError(null);
    try {
      const result = await api.connectorOauthStart(workspaceId, provider);
      window.location.assign(result.authorizeUrl);
    } catch {
      setError('This app cannot be connected right now.');
    }
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected || !query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const result = await api.connectorSearch(workspaceId, selected, query.trim(), 12);
      const found: ConnectorItemLike[] = result.items.map((item) => ({
        referenceId: item.referenceId,
        connectionId: item.connectionId,
        provider: item.provider,
        title: item.title,
        excerpt: item.excerpt,
        expiresAt: item.expiresAt
      }));
      setItems(found);
      onRemember(found);
    } catch {
      setItems([]);
      setError('Rafii could not search that connected app. Reconnect it or try again.');
    } finally {
      setSearching(false);
    }
  };

  if (loading) {
    return <p role='status' className='text-muted-foreground px-2 py-4 text-sm'>Loading connected apps…</p>;
  }
  if (!catalog) {
    return <p role='alert' className='text-muted-foreground px-2 py-4 text-sm'>{error ?? 'Connected apps are unavailable.'}</p>;
  }

  const liveConnections = catalog.connections.filter((connection) => !connection.revoked);
  const availableProviders = catalog.providers.filter((provider) => provider.enabled);

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        {catalog.providers.map((provider) => {
          const live = liveConnections.filter((connection) => connection.provider === provider.id);
          const name = provider.id === 'gmail' ? 'Gmail' : provider.id === 'notion' ? 'Notion' : provider.id;
          return (
            <div key={provider.id} className='rafii-quiet flex min-h-11 items-center gap-3 rounded-xl px-3 py-2'>
              <Icons.link aria-hidden className='text-muted-foreground size-4 shrink-0' />
              <span className='min-w-0 flex-1'>
                <span className='block text-sm font-medium'>{name}</span>
                <span className='text-muted-foreground block text-xs'>
                  {!provider.enabled
                    ? 'Off on this deployment'
                    : !provider.configured
                      ? 'Server setup required'
                      : live.length
                        ? `${live.length} connected`
                        : 'Not connected'}
                </span>
              </span>
              {provider.enabled && provider.configured && !live.length ? (
                <Button variant='glass' size='sm' onClick={() => void connect(provider.id)}>
                  Connect
                </Button>
              ) : null}
            </div>
          );
        })}
      </div>

      {availableProviders.length === 0 ? (
        <p className='text-muted-foreground px-2 text-sm'>
          Connected apps are off on this deployment.
        </p>
      ) : null}

      {liveConnections.length ? (
        <>
          <div className='flex flex-wrap gap-2' role='group' aria-label='Connected app accounts'>
            {liveConnections.map((connection) => (
              <Button
                key={connection.connectionId}
                variant={selected === connection.connectionId ? 'action' : 'glass'}
                size='sm'
                onClick={() => {
                  setSelected(connection.connectionId);
                  setItems([]);
                  setQuery('');
                }}
              >
                {connectionLabel(connection)}
              </Button>
            ))}
          </div>
          <form onSubmit={search} className='flex gap-2'>
            <Input
              type='search'
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder='Search the selected app'
              aria-label='Search the selected connected app'
              className='text-base md:text-sm'
            />
            <Button type='submit' variant='glass' disabled={!query.trim() || searching}>
              {searching ? 'Searching…' : 'Search'}
            </Button>
          </form>
          {items.length ? (
            <ul className='flex min-h-0 flex-col gap-1 overflow-y-auto'>
              {items.map((item) => (
                <li key={item.referenceId}>
                  <button
                    type='button'
                    onClick={() =>
                      onPick({
                        kind: 'connector_item',
                        id: item.referenceId,
                        label: item.title,
                        sublabel: [item.provider, item.excerpt].filter(Boolean).join(' · '),
                        provider: item.provider,
                        connectionId: item.connectionId,
                        expiresAt: item.expiresAt
                      })
                    }
                    className='rafii-focus hover:bg-foreground/5 flex min-h-11 w-full items-start gap-3 rounded-md px-2 py-2 text-left'
                  >
                    <Icons.link aria-hidden className='text-muted-foreground mt-0.5 size-4 shrink-0' />
                    <span className='min-w-0 flex-1'>
                      <span className='block truncate text-sm'>{item.title}</span>
                      <span className='text-muted-foreground line-clamp-2 text-xs'>{item.excerpt || item.provider}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : query.trim() && !searching ? (
            <p className='text-muted-foreground px-2 text-sm'>No matching items yet.</p>
          ) : null}
        </>
      ) : availableProviders.some((provider) => provider.configured) ? (
        <p className='text-muted-foreground px-2 text-sm'>
          Connect Notion or Gmail above, then choose exactly what Rafii may read.
        </p>
      ) : null}

      {error ? <p role='alert' className='text-muted-foreground px-2 text-sm'>{error}</p> : null}
    </div>
  );
}

export interface PlusSheetProps {
  trigger: (props: { onClick?: () => void }) => ReactNode;
  snapshot: Snapshot | null | undefined;
  owner: string | null | undefined;
  catalog: AttachmentsCatalog | null | undefined;
  chips: readonly Chip[];
  creditMode: boolean;
  onPickDevice: () => void;
  onPickText: () => void;
  onPickItem: (item: PickerItem) => void;
  onRememberConnectorItems: (items: readonly ConnectorItemLike[]) => void;
  onAddAssets: (assets: Asset[]) => void;
  requestedView?: PlusView | null;
  onRequestedViewHandled?: () => void;
}

export function PlusSheet({
  trigger,
  snapshot,
  owner,
  catalog,
  chips,
  creditMode,
  onPickDevice,
  onPickText,
  onPickItem,
  onRememberConnectorItems,
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

  const pickAndClose = (item: PickerItem) => {
    onPickItem(item);
    close();
  };

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
          ) : view === 'skills' ? (
            <SkillsView skills={catalog?.skills ?? []} onPick={pickAndClose} />
          ) : view === 'connectors' ? (
            <ConnectedAppsView onPick={pickAndClose} onRemember={onRememberConnectorItems} />
          ) : view ? (
            <SearchView view={view} snapshot={snapshot} owner={owner} onPick={pickAndClose} />
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
