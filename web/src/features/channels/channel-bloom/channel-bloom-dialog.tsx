'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { IconArrowLeft, IconArrowRight, IconBookmark, IconCheck, IconFolder, IconFolderPlus, IconPlus, IconSearch, IconX } from '@tabler/icons-react';
import type { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { DRAFT_PLATFORMS } from '@/features/agent/composer';
import type { ChannelFolder } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { FOLDER_MAX, FOLDER_SHELF, FOLDER_SYMBOLS, accountMatches, canMove, cleanSelection, snapshotContext, toggleGroup, validateFolder, visibleFolders, type FolderAccount, type FolderContext, type FolderSource, type FolderSymbol } from '@/lib/channels/folders';
import { RAFII_EASE_CSS, RAFII_TIME, motionAllowed, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { AccountRow } from './account-row';
import { FolderCard } from './folder-card';
import { FolderEditor, editorValidation, type EditorDraft } from './folder-editor';
import { FolderInspector, type FolderCommand } from './folder-inspector';
import { MISSING_REASON, doneLabel, draftReason, draftableFrom, inspectorSlot, pickableAccounts, plural, readFolder, toggleFeedback } from './helpers';
import { folderErrorMessage, useChannelFolders } from './use-channel-folders';

export interface ChannelBloomCommit {
  /** The staged destination ids (`Phase2State.channels[].id`), deduplicated, connected and draftable. */
  accountIds: string[];
  /** The folders the selection came from, snapshotted now so later edits never rewrite this draft's label. */
  context: FolderContext;
}

export interface ChannelBloomDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `toFolderAccounts(state.phase2.channels)`: every connection, connected = not revoked. */
  accounts: FolderAccount[];
  /** `state.phase2.channelFolders ?? []`. */
  folders: ChannelFolder[];
  /** The committed selection the dialog starts from. */
  selected: readonly string[];
  /** The committed selection's folder context, if any. */
  context?: FolderContext | null;
  /** Done: the caller commits the staged selection (for example `useDestinations().commit`). */
  onCommit: (result: ChannelBloomCommit) => void;
}

/**
 * Channel Bloom (Rafii v9 addendum §2–§5): where a draft goes. Folders are saved account groups;
 * the dialog stages one destination set, Done commits it and Cancel, close or Escape discard it.
 * Folder edits are separate saved transactions and survive a cancelled selection.
 *
 * Escape closes the deepest layer first: menu → delete confirmation → editor → inspector → dialog.
 */
export function ChannelBloomDialog({ open, onOpenChange, accounts, folders, selected, context, onCommit }: ChannelBloomDialogProps) {
  const escapeRef = useRef<() => boolean>(() => false);
  const searchRef = useRef<HTMLInputElement>(null);
  // Each opening starts a fresh stage from the committed selection, even when the popup is still
  // mounted from its closing transition (or kept mounted by the host).
  const session = useRef({ open: false, count: 0 });
  if (open && !session.current.open) session.current.count += 1;
  session.current.open = open;
  const handleOpenChange = useCallback(
    (next: boolean, details: DialogPrimitive.Root.ChangeEventDetails) => {
      if (!next && details.reason === 'escape-key' && escapeRef.current()) {
        details.cancel();
        return;
      }
      onOpenChange(next);
    },
    [onOpenChange]
  );
  return (
    <RafiiDialog open={open} onOpenChange={handleOpenChange}>
      <RafiiDialogContent size='md' className='h-[calc(100dvh-1.25rem)] md:h-[min(53.75rem,93dvh)]' initialFocus={(type) => (type === 'touch' ? null : searchRef.current)}>
        <ChannelBloomPanel key={session.current.count} accounts={accounts} folders={folders} selected={selected} context={context ?? null} onCommit={onCommit} onOpenChange={onOpenChange} escapeRef={escapeRef} searchRef={searchRef} />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

interface PanelProps {
  accounts: FolderAccount[];
  folders: ChannelFolder[];
  selected: readonly string[];
  context: FolderContext | null;
  onCommit: (result: ChannelBloomCommit) => void;
  onOpenChange: (open: boolean) => void;
  escapeRef: RefObject<() => boolean>;
  searchRef: RefObject<HTMLInputElement | null>;
}

interface SelectionSnapshot {
  selected: string[];
  origins: FolderSource[];
}

interface EditorState {
  draft: EditorDraft;
  keepIds: string[];
  error: string | null;
}

const copySource = (source: FolderSource): FolderSource => ({ ...source, accountIds: [...source.accountIds] });
const asSymbol = (symbol: string | undefined): FolderSymbol => ((FOLDER_SYMBOLS as readonly string[]).includes(symbol ?? '') ? (symbol as FolderSymbol) : 'folder');
const LIMIT_MESSAGE = `You have ${FOLDER_MAX} folders, the limit. Delete one first.`;

function ChannelBloomPanel({ accounts, folders, selected: committed, context, onCommit, onOpenChange, escapeRef, searchRef }: PanelProps) {
  const uid = useId();
  const inspectorId = `${uid}-inspector`;
  const { reduced } = useMotionPreference();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const folderApi = useChannelFolders();
  const draftable = useMemo(() => draftableFrom(DRAFT_PLATFORMS), []);
  const pickable = useMemo(() => pickableAccounts(accounts, draftable), [accounts, draftable]);

  const [staged, setStaged] = useState<string[]>(() => cleanSelection(committed, pickable));
  const [origins, setOrigins] = useState<FolderSource[]>(() => (context?.sources ?? []).map(copySource));
  const [undo, setUndo] = useState<SelectionSnapshot | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [all, setAll] = useState(false);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);

  const root = useRef<HTMLDivElement>(null);
  const mainView = useRef<HTMLDivElement>(null);
  const editorView = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const newFolderRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const pendingChevron = useRef<string | null>(null);
  const view: 'main' | 'editor' = editor ? 'editor' : 'main';

  const trimmed = query.trim();
  const visible = useMemo(() => visibleFolders(folders, query, all, accounts), [folders, query, all, accounts]);
  const visibleAccounts = useMemo(() => (trimmed ? accounts.filter((a) => accountMatches(a, query)) : accounts), [accounts, query, trimmed]);
  // Only a folder on the visible shelf can stay inspected; the effect below syncs the state.
  const inspected = inspecting ? (visible.find((f) => f.id === inspecting) ?? null) : null;
  const slot = inspectorSlot(
    visible.findIndex((f) => f.id === inspecting),
    visible.length
  );
  const showFolders = !(trimmed && visible.length === 0);

  const chevronOf = useCallback((id: string) => root.current?.querySelector<HTMLElement>(`[data-folder-inspect="${CSS.escape(id)}"]`) ?? null, []);

  // A folder that scrolls out of the shelf (search, fewer folders, deletion elsewhere) closes its inspector.
  useEffect(() => {
    if (inspecting && !visible.some((f) => f.id === inspecting)) {
      setInspecting(null);
      setMenuOpen(false);
      setConfirmingDelete(false);
    }
  }, [inspecting, visible]);

  // The editor takes the name field; a saved folder hands focus to its chevron once the shelf shows it.
  useEffect(() => {
    if (view === 'editor') nameRef.current?.focus({ preventScroll: true });
  }, [view]);
  useEffect(() => {
    const id = pendingChevron.current;
    if (!id || view !== 'main') return;
    const el = chevronOf(id);
    if (!el) return;
    pendingChevron.current = null;
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: 'nearest' });
  });

  // View switch: the incoming view slides in a little (prototype `switchView`); nothing moves under reduced motion.
  const firstView = useRef(true);
  useLayoutEffect(() => {
    if (firstView.current) {
      firstView.current = false;
      return;
    }
    const el = view === 'editor' ? editorView.current : mainView.current;
    if (!el || reduced || !motionAllowed() || typeof el.animate !== 'function') return;
    el.animate([{ opacity: 0, transform: `translateX(${view === 'editor' ? 14 : -14}px)` }, { opacity: 1, transform: 'none' }], { duration: RAFII_TIME.view, easing: RAFII_EASE_CSS.soft });
  }, [view, reduced]);

  /* ---------------------------------------------------------------- staged selection */
  const snapshotNow = (): SelectionSnapshot => ({ selected: [...staged], origins: origins.map(copySource) });
  function announce(message: string, previous: SelectionSnapshot | null = null) {
    setFeedback(message);
    setUndo(previous);
  }
  function setSelection(next: readonly string[], message: string, nextOrigins: FolderSource[] = origins) {
    const previous = snapshotNow();
    setStaged(cleanSelection(next, pickable));
    setOrigins(nextOrigins);
    announce(message, previous);
  }
  function toggleFolder(folder: ChannelFolder) {
    const previous = snapshotNow();
    const removing = readFolder(folder, staged, accounts, draftable).state === 'all';
    const next = toggleGroup(staged, folder, pickable);
    const nextOrigins = origins.filter((o) => o.id !== folder.id);
    if (!removing) {
      const source = snapshotContext([folder], [folder.id], pickable).sources[0];
      if (source) nextOrigins.push(source);
    }
    setStaged(next);
    setOrigins(nextOrigins);
    announce(toggleFeedback(removing, Math.abs(next.length - previous.selected.length)), previous);
    if (!reduced && motionAllowed()) {
      root.current?.querySelector<HTMLElement>(`[data-folder-card="${CSS.escape(folder.id)}"] [data-glyph]`)?.animate([{ transform: 'scale(0.94)' }, { transform: 'scale(1.025)', offset: 0.55 }, { transform: 'scale(1)' }], { duration: 470, easing: RAFII_EASE_CSS.soft });
    }
  }
  function setAccount(id: string, checked: boolean) {
    setSelection(checked ? [...staged, id] : staged.filter((a) => a !== id), 'Account selection updated.');
  }
  function clearAll() {
    setSelection([], 'Selection cleared.', []);
  }
  function undoLast() {
    if (!undo) return;
    setStaged(undo.selected);
    setOrigins(undo.origins);
    announce('Selection restored.');
  }
  function done() {
    onCommit({ accountIds: [...staged], context: snapshotContext(folders, origins.map((o) => o.id), pickable) });
    onOpenChange(false);
  }
  function clearSearch() {
    setQuery('');
    searchRef.current?.focus({ preventScroll: true });
  }

  /* ---------------------------------------------------------------- inspector and its menu */
  function toggleInspector(id: string) {
    setMenuOpen(false);
    setConfirmingDelete(false);
    setInspecting((current) => (current === id ? null : id));
  }
  function closeInspector() {
    const id = inspecting;
    setInspecting(null);
    setMenuOpen(false);
    setConfirmingDelete(false);
    if (id) chevronOf(id)?.focus({ preventScroll: true });
  }
  const reveal = useCallback(
    (el: HTMLElement) => {
      if (!editor) el.scrollIntoView({ block: 'nearest', behavior: !reduced && motionAllowed() ? 'smooth' : 'instant' });
    },
    [editor, reduced]
  );
  async function runCommand(command: FolderCommand) {
    const folder = inspected;
    if (!folder) return;
    setMenuOpen(false);
    if (command === 'delete') {
      setConfirmingDelete(true);
      return;
    }
    try {
      if (command === 'pin') {
        await folderApi.pin(folder, !folder.pinned);
        announce(folder.pinned ? 'Folder unpinned.' : 'Folder pinned.');
      } else if (command === 'duplicate') {
        if (folders.length >= FOLDER_MAX) {
          announce(LIMIT_MESSAGE);
        } else {
          const { folder: copy } = await folderApi.duplicate(folder);
          setAll(true);
          setInspecting(copy.id);
          announce('Folder duplicated.');
        }
      } else {
        await folderApi.move(folder.id, command === 'up' ? -1 : 1);
        announce('Folder order updated.');
      }
    } catch (error) {
      announce(folderErrorMessage(error, "Couldn't change the folder."));
    }
    moreRef.current?.focus({ preventScroll: true });
  }
  async function confirmDelete() {
    const folder = inspected;
    if (!folder) return;
    try {
      await folderApi.remove(folder.id);
      setConfirmingDelete(false);
      setInspecting(null);
      announce('Folder deleted.');
      newFolderRef.current?.focus({ preventScroll: true });
    } catch (error) {
      announce(folderErrorMessage(error, "Couldn't delete the folder."));
    }
  }

  /* ---------------------------------------------------------------- editor (a separate saved transaction) */
  function openEditor(folder: ChannelFolder | null, fromSelection = false) {
    if (!folder && folders.length >= FOLDER_MAX) {
      announce(LIMIT_MESSAGE);
      return;
    }
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setMenuOpen(false);
    setConfirmingDelete(false);
    setEditor({
      draft: folder ? { id: folder.id, name: folder.name, symbol: asSymbol(folder.symbol), pinned: folder.pinned === true, accountIds: [...folder.accountIds] } : { name: '', symbol: 'folder', pinned: false, accountIds: fromSelection ? [...staged] : [] },
      keepIds: folder ? [...folder.accountIds] : [],
      error: null
    });
  }
  function cancelEditor() {
    setEditor(null);
    const target = returnFocus.current;
    returnFocus.current = null;
    requestAnimationFrame(() => {
      if (target?.isConnected) target.focus({ preventScroll: true });
      else newFolderRef.current?.focus({ preventScroll: true });
    });
  }
  async function saveEditor() {
    if (!editor || folderApi.busy) return;
    if (!editorValidation(editor.draft, folders, accounts, editor.keepIds).valid) return;
    let input: ReturnType<typeof validateFolder>;
    try {
      input = validateFolder(editor.draft, folders, accounts, editor.keepIds);
    } catch (error) {
      setEditor((current) => (current ? { ...current, error: error instanceof Error ? error.message : 'This folder cannot be saved yet.' } : current));
      return;
    }
    try {
      const { folder: saved, folders: list } = await folderApi.save(input);
      setEditor(null);
      setInspecting(null);
      setMenuOpen(false);
      setConfirmingDelete(false);
      const shows = (q: string, everything: boolean) => visibleFolders(list, q, everything, accounts).some((f) => f.id === saved.id);
      if (!shows(query, all)) {
        setQuery('');
        if (!shows('', all)) setAll(true);
      }
      pendingChevron.current = saved.id;
      returnFocus.current = null;
      announce('Folder saved.');
    } catch (error) {
      setEditor((current) => (current ? { ...current, error: folderErrorMessage(error) } : current));
    }
  }

  /* ---------------------------------------------------------------- Escape: deepest layer first */
  useEffect(() => {
    escapeRef.current = () => {
      if (menuOpen) {
        setMenuOpen(false);
        moreRef.current?.focus({ preventScroll: true });
        return true;
      }
      if (confirmingDelete) {
        setConfirmingDelete(false);
        moreRef.current?.focus({ preventScroll: true });
        return true;
      }
      if (editor) {
        cancelEditor();
        return true;
      }
      if (inspecting) {
        closeInspector();
        return true;
      }
      return false;
    };
  });

  /* ---------------------------------------------------------------- render */
  const shelf: ReactNode[] = [];
  const inspectorNode = (
    <FolderInspector
      key='inspector'
      id={inspectorId}
      folder={inspected}
      accounts={accounts}
      draftable={draftable}
      selected={staged}
      onMemberChange={setAccount}
      canEdit={canEdit}
      canMoveUp={inspected ? canMove(folders, inspected.id, -1) : false}
      canMoveDown={inspected ? canMove(folders, inspected.id, 1) : false}
      busy={folderApi.busy}
      menuOpen={menuOpen}
      onMenuOpenChange={(next) => {
        setMenuOpen(next);
        if (next) setConfirmingDelete(false);
      }}
      confirmingDelete={confirmingDelete}
      onCancelDelete={() => {
        setConfirmingDelete(false);
        moreRef.current?.focus({ preventScroll: true });
      }}
      onConfirmDelete={confirmDelete}
      onEdit={() => inspected && openEditor(inspected)}
      onCommand={runCommand}
      moreRef={moreRef}
      reduced={reduced}
      onRevealed={reveal}
    />
  );
  visible.forEach((folder, i) => {
    shelf.push(<FolderCard key={folder.id} folder={folder} reading={readFolder(folder, staged, accounts, draftable)} accounts={accounts} inspected={inspecting === folder.id} inspectorId={inspectorId} onToggle={() => toggleFolder(folder)} onInspect={() => toggleInspector(folder.id)} />);
    if (i === slot) shelf.push(inspectorNode);
  });
  if (slot < 0) shelf.push(inspectorNode);

  const editing = editor?.draft.id ? 'edit' : editor ? 'new' : null;
  const readOnlyTitle = canEdit ? undefined : 'Only editors can change folders.';

  return (
    <div ref={root} className='flex min-h-0 flex-1 flex-col'>
      <RafiiDialogHeader
        eyebrow={editing === 'edit' ? 'Edit folder' : editing === 'new' ? 'New folder' : 'Channel Bloom'}
        title={editing === 'edit' ? 'Make it' : editing === 'new' ? 'Keep a good' : 'Where should it'}
        accent={editing === 'edit' ? 'yours.' : editing === 'new' ? 'group.' : 'go?'}
        intro={editing ? 'A name, a few accounts. Ready for next time.' : 'Your usual accounts, one thoughtful shortcut.'}
        closeLabel='Cancel channel selection'
        back={
          editing ? (
            <Button variant='glass' size='icon-control' aria-label='Back to channels' onClick={cancelEditor} disabled={folderApi.busy}>
              <IconArrowLeft className='size-4' />
            </Button>
          ) : undefined
        }
      />

      <div ref={mainView} hidden={view !== 'main'} className='flex min-h-0 flex-1 flex-col' aria-label='Choose folders and individual accounts'>
        <div className='shrink-0 px-5 pb-3 md:px-7'>
          <div className='rafii-field flex h-12 items-center gap-2 rounded-2xl pr-1 pl-3.5'>
            <IconSearch aria-hidden className='text-muted-foreground size-[18px] shrink-0' />
            <input
              ref={searchRef}
              type='text'
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label='Search folders and accounts'
              placeholder='Find a folder or account…'
              autoComplete='off'
              className='text-foreground min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-[var(--rafii-text-tertiary)] md:text-sm'
            />
            {query && (
              <button type='button' aria-label='Clear search' onClick={clearSearch} className='rafii-focus text-muted-foreground hover:text-foreground flex size-10 shrink-0 items-center justify-center rounded-full'>
                <IconX className='size-4' />
              </button>
            )}
          </div>
        </div>

        <RafiiDialogBody className='pt-0.5'>
          {showFolders && (
            <section aria-labelledby={`${uid}-folders`}>
              <div className='mb-3 flex min-h-[2.625rem] items-center justify-between gap-2.5'>
                <h3 id={`${uid}-folders`} className='text-foreground flex items-center gap-2 text-sm font-medium'>
                  Your folders{' '}
                  <span className='rafii-quiet text-muted-foreground min-w-5 rounded-[7px] px-1.5 py-0.5 text-center text-[11px] leading-snug' aria-label={`${folders.length} ${folders.length === 1 ? 'folder' : 'folders'}`}>
                    {folders.length}
                  </span>
                </h3>
                <Button ref={newFolderRef} variant='quiet' size='lg' className='min-h-11 text-[13px]' onClick={() => openEditor(null)} disabled={!canEdit} title={readOnlyTitle}>
                  <IconPlus className='size-4' /> New folder
                </Button>
              </div>
              {folders.length === 0 && !trimmed ? (
                <StateMessage
                  kind='empty'
                  title='No folders yet'
                  media={
                    <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
                      <IconFolder className='size-5' />
                    </span>
                  }
                  action={
                    <Button variant='glass' size='control' onClick={() => openEditor(null)} disabled={!canEdit} title={readOnlyTitle}>
                      Create folder <IconArrowRight className='size-4' />
                    </Button>
                  }
                />
              ) : (
                <div className='grid grid-cols-2 items-start gap-2.5 md:gap-3'>{shelf}</div>
              )}
              {!trimmed && folders.length > FOLDER_SHELF && (
                <button type='button' aria-expanded={all} onClick={() => setAll((current) => !current)} className='rafii-quiet rafii-focus text-muted-foreground hover:text-foreground mx-auto mt-2.5 block min-h-11 rounded-xl px-4 text-xs transition-colors'>
                  {all ? 'Show fewer' : `View all ${folders.length} folders`}
                </button>
              )}
            </section>
          )}

          {visibleAccounts.length > 0 && (
            <section aria-labelledby={`${uid}-accounts`} className={cn(showFolders && 'mt-5')}>
              <div className='mb-1.5 flex min-h-[2.625rem] items-center justify-between gap-2.5'>
                <h3 id={`${uid}-accounts`} className='text-foreground text-sm font-medium'>
                  Individual accounts
                </h3>
                <small className='text-muted-foreground text-xs'>{staged.length} selected</small>
              </div>
              <div className='grid gap-1.5'>
                {visibleAccounts.map((account) => (
                  <AccountRow
                    key={account.id}
                    id={account.id}
                    platform={account.platform}
                    account={account.account}
                    state={account.state}
                    checked={staged.includes(account.id)}
                    onCheckedChange={(checked) => setAccount(account.id, checked)}
                    reason={!account.connected ? MISSING_REASON : !draftable(account.platform) ? draftReason(account.platform) : null}
                  />
                ))}
              </div>
            </section>
          )}

          {accounts.length === 0 && !trimmed && <StateMessage kind='empty' className='mt-5' title='No accounts connected yet.' description='Connect an account on the Channels page. Until then, a platform can still be drafted for without one.' />}
          {trimmed && visible.length === 0 && visibleAccounts.length === 0 && (
            <StateMessage
              kind='empty'
              title='No folders or accounts found.'
              description='Try a name, platform, or handle.'
              action={
                <Button variant='glass' size='control' onClick={clearSearch}>
                  Clear search
                </Button>
              }
            />
          )}
        </RafiiDialogBody>

        <RafiiDialogFooter className='gap-1'>
          <div role='status' aria-live='polite' className={cn('rafii-quiet text-muted-foreground flex min-h-10 items-center justify-between gap-2.5 rounded-xl px-2.5 py-1.5 text-xs', !feedback && 'sr-only')}>
            <span>{feedback ?? ''}</span>
            {feedback && undo && (
              <button type='button' onClick={undoLast} className='rafii-focus text-foreground hover:rafii-quiet min-h-8 min-w-11 shrink-0 rounded-lg px-2 text-xs font-semibold'>
                Undo
              </button>
            )}
          </div>
          <div className='flex min-h-10 items-center justify-between gap-1.5'>
            <Button variant='quiet' size='lg' className='min-h-11 text-[13px]' onClick={clearAll} disabled={staged.length === 0}>
              Clear
            </Button>
            <Button variant='quiet' size='lg' className='min-h-11 text-[13px]' onClick={() => openEditor(null, true)} disabled={staged.length === 0 || !canEdit} title={readOnlyTitle}>
              <IconFolderPlus className='size-4' /> Save selection as folder
            </Button>
          </div>
          <Button variant='action' size='control' className='w-full' onClick={done} aria-label={`Done, ${plural(staged.length, 'account')} selected`}>
            {doneLabel(staged.length)} <IconCheck className='size-4' />
          </Button>
          <p className='text-muted-foreground mt-1 flex items-center justify-center gap-1.5 text-[11px] leading-snug'>
            <IconBookmark aria-hidden className='size-3' /> Folders are saved to this workspace.
          </p>
        </RafiiDialogFooter>
      </div>

      <div ref={editorView} hidden={view !== 'editor'} className='flex min-h-0 flex-1 flex-col' aria-label='Folder details'>
        {editor && <FolderEditor draft={editor.draft} onChange={(draft) => setEditor((current) => (current ? { ...current, draft, error: null } : current))} folders={folders} accounts={accounts} draftable={draftable} keepIds={editor.keepIds} error={editor.error} busy={folderApi.busy} onSave={saveEditor} onCancel={cancelEditor} nameRef={nameRef} />}
      </div>
    </div>
  );
}
