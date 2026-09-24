'use client';

import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { IconArrowDown, IconArrowUp, IconCopy, IconFolderPlus, IconPencil, IconPin, IconPinnedOff, IconTrash } from '@tabler/icons-react';
import { ActiveFilters, RafiiDialog, RafiiDialogContent, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { ChannelFolder } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import {
  FOLDER_MAX,
  FOLDER_SHELF,
  FOLDER_SYMBOLS,
  canMove,
  cleanSelection,
  selectionLabel,
  snapshotContext,
  toggleGroup,
  validateFolder,
  visibleFolders,
  type FolderAccount,
  type FolderSymbol
} from '@/lib/channels/folders';
import { RAFII_EASE_CSS, motionAllowed, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { AccountRow } from './channel-bloom/account-row';
import { FolderCard } from './channel-bloom/folder-card';
import { FolderEditor, editorValidation, type EditorDraft } from './channel-bloom/folder-editor';
import { MISSING_REASON, inspectorSlot, memberStatus, plural, readFolder } from './channel-bloom/helpers';
import { folderErrorMessage, useChannelFolders } from './channel-bloom/use-channel-folders';
import { CONTROL_44 } from './rafii-materials';

/**
 * Saved folders on the Channels page (DNA §21.6 grouping; v9 addendum §2–§4), built from the
 * Channel Bloom package: the same `useChannelFolders` transactions (`p2_folder_save | delete |
 * move`), the same `FolderCard`, `FolderEditor` and `AccountRow`, and the same folder rules.
 *
 * What a folder does here: its card narrows the account list below to its members (a view
 * filter, never a mutation — contracts rule 4). Drafts choose destinations in Channel Bloom,
 * not here. Every connected member counts on this page, whatever drafting can write for; the
 * dialog reads draftability because that is where destinations are chosen.
 */

export interface ChannelFoldersSectionProps {
  accounts: FolderAccount[];
  /** Account ids the page is narrowed to (empty = every account). Cards and member ticks edit this set. */
  view: string[];
  onViewChange: (ids: string[]) => void;
}

interface EditorState {
  draft: EditorDraft;
  keepIds: string[];
  error: string | null;
}

type FolderCommand = 'pin' | 'duplicate' | 'up' | 'down' | 'delete';

const everyPlatform = () => true;
const asSymbol = (symbol: string | undefined): FolderSymbol => ((FOLDER_SYMBOLS as readonly string[]).includes(symbol ?? '') ? (symbol as FolderSymbol) : 'folder');
const LIMIT_MESSAGE = `This workspace already has ${FOLDER_MAX} folders. Delete one before adding another.`;

/** The members and management actions of one folder, unfolded beneath its card. */
function FolderPanel({
  id,
  folder,
  accounts,
  view,
  onMember,
  canEdit,
  busy,
  canMoveUp,
  canMoveDown,
  confirmingDelete,
  onEdit,
  onCommand,
  onCancelDelete,
  onConfirmDelete,
  keepRef
}: {
  id: string;
  folder: ChannelFolder;
  accounts: readonly FolderAccount[];
  view: readonly string[];
  onMember: (id: string, checked: boolean) => void;
  canEdit: boolean;
  busy: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  confirmingDelete: boolean;
  onEdit: () => void;
  onCommand: (command: FolderCommand) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  keepRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <div id={id} className='rafii-quiet col-span-full min-w-0 rounded-[var(--rafii-radius-card)] p-4'>
      <div className='mb-3 flex flex-wrap items-center gap-2'>
        <div className='min-w-0 flex-1'>
          <span className='rafii-eyebrow'>Inside the folder</span>
          <h3 className='text-foreground mt-1 text-[15px] font-medium break-words'>{folder.name}</h3>
        </div>
        {canEdit && (
          <div role='group' aria-label={`${folder.name} folder actions`} className='flex flex-wrap items-center gap-1'>
            <Button variant='quiet' className={CONTROL_44} onClick={onEdit} disabled={busy}>
              <IconPencil className='size-4' />
              Edit
            </Button>
            <Button variant='quiet' className={CONTROL_44} onClick={() => onCommand('pin')} disabled={busy}>
              {folder.pinned ? <IconPinnedOff className='size-4' /> : <IconPin className='size-4' />}
              {folder.pinned ? 'Unpin' : 'Pin'}
            </Button>
            <Button variant='quiet' className={CONTROL_44} onClick={() => onCommand('duplicate')} disabled={busy}>
              <IconCopy className='size-4' />
              Duplicate
            </Button>
            <Button variant='quiet' size='icon-control' aria-label='Move folder up' onClick={() => onCommand('up')} disabled={busy || !canMoveUp}>
              <IconArrowUp className='size-4' />
            </Button>
            <Button variant='quiet' size='icon-control' aria-label='Move folder down' onClick={() => onCommand('down')} disabled={busy || !canMoveDown}>
              <IconArrowDown className='size-4' />
            </Button>
            <Button variant='quiet' className={cn(CONTROL_44, 'text-destructive hover:text-destructive')} onClick={() => onCommand('delete')} disabled={busy}>
              <IconTrash className='size-4' />
              Delete
            </Button>
          </div>
        )}
      </div>
      {confirmingDelete && (
        <div role='group' aria-labelledby={`${id}-delete-title`} className='rafii-glass-selected mb-3 rounded-[14px] p-3.5'>
          <strong id={`${id}-delete-title`} className='text-foreground text-[13px] font-medium break-words'>
            Delete “{folder.name}”?
          </strong>
          <p className='text-muted-foreground mt-2 text-xs leading-relaxed'>This removes the folder only. Accounts stay connected and draft destinations stay unchanged.</p>
          <div className='mt-2.5 flex gap-1.5'>
            <Button ref={keepRef} variant='glass' size='control' className='min-h-11 flex-1 text-[13px]' onClick={onCancelDelete} disabled={busy}>
              Keep folder
            </Button>
            <Button variant='action' size='control' className='min-h-11 flex-1 text-[13px]' onClick={onConfirmDelete} disabled={busy}>
              Delete folder
            </Button>
          </div>
        </div>
      )}
      <div className='grid gap-1.5'>
        {folder.accountIds.map((memberId) => {
          const account = accounts.find((a) => a.id === memberId);
          if (!account) {
            return <AccountRow key={memberId} id={memberId} kind='member' platform='Removed account' account='This connection is gone' checked={false} onCheckedChange={() => {}} reason={MISSING_REASON} />;
          }
          const missing = memberStatus(memberId, accounts, everyPlatform) === 'missing';
          return (
            <AccountRow
              key={memberId}
              id={memberId}
              kind='member'
              platform={account.platform}
              account={account.account}
              state={account.state}
              checked={view.includes(memberId)}
              onCheckedChange={(checked) => onMember(memberId, checked)}
              reason={missing ? MISSING_REASON : null}
            />
          );
        })}
      </div>
      <p className='text-muted-foreground mt-3 text-xs leading-relaxed'>Ticks only change which accounts this page shows. The saved folder changes through Edit.</p>
    </div>
  );
}

export function ChannelFoldersSection({ accounts, view, onViewChange }: ChannelFoldersSectionProps) {
  const uid = useId();
  const panelId = `${uid}-folder-panel`;
  const { reduced } = useMotionPreference();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const folderApi = useChannelFolders();
  const { folders } = folderApi;

  const [all, setAll] = useState(false);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const root = useRef<HTMLElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const newFolderRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const pendingChevron = useRef<string | null>(null);

  const shelf = useMemo(() => visibleFolders(folders, '', all, accounts), [folders, all, accounts]);
  const inspected = inspecting ? (shelf.find((f) => f.id === inspecting) ?? null) : null;
  const slot = inspectorSlot(
    shelf.findIndex((f) => f.id === inspecting),
    shelf.length
  );
  const hidden = folders.length - shelf.length;

  // A folder that leaves the shelf (fewer folders, deletion elsewhere) closes its panel.
  useEffect(() => {
    if (inspecting && !shelf.some((f) => f.id === inspecting)) {
      setInspecting(null);
      setConfirmingDelete(false);
    }
  }, [inspecting, shelf]);

  // A saved folder hands focus to its chevron once the shelf shows it.
  useEffect(() => {
    const id = pendingChevron.current;
    if (!id || editor) return;
    const el = root.current?.querySelector<HTMLElement>(`[data-folder-inspect="${CSS.escape(id)}"]`);
    if (!el) return;
    pendingChevron.current = null;
    el.focus({ preventScroll: true });
  });

  useEffect(() => {
    if (confirmingDelete) keepRef.current?.focus({ preventScroll: true });
  }, [confirmingDelete]);

  /* ---------------------------------------------------------------- the view filter (never a mutation) */
  function toggleFolder(folder: ChannelFolder) {
    const removing = readFolder(folder, view, accounts, everyPlatform).state === 'all';
    const next = toggleGroup(view, folder, accounts);
    onViewChange(next);
    setFeedback(next.length === 0 ? 'Showing every account.' : `${removing ? 'Hiding' : 'Showing'} ${folder.name}. ${plural(next.length, 'account')} in view.`);
    if (!reduced && motionAllowed()) {
      root.current?.querySelector<HTMLElement>(`[data-folder-card="${CSS.escape(folder.id)}"] [data-glyph]`)?.animate([{ transform: 'scale(0.94)' }, { transform: 'scale(1.025)', offset: 0.55 }, { transform: 'scale(1)' }], { duration: 470, easing: RAFII_EASE_CSS.soft });
    }
  }
  function setMember(id: string, checked: boolean) {
    onViewChange(cleanSelection(checked ? [...view, id] : view.filter((a) => a !== id), accounts));
  }
  function clearView() {
    onViewChange([]);
    setFeedback('Showing every account.');
  }

  /* ---------------------------------------------------------------- folder commands (saved transactions) */
  function toggleInspector(id: string) {
    setConfirmingDelete(false);
    setInspecting((current) => (current === id ? null : id));
  }
  async function runCommand(command: FolderCommand) {
    const folder = inspected;
    if (!folder) return;
    if (command === 'delete') {
      setConfirmingDelete(true);
      return;
    }
    try {
      if (command === 'pin') {
        await folderApi.pin(folder, !folder.pinned);
        setFeedback(folder.pinned ? 'Folder unpinned.' : 'Folder pinned to the shelf.');
      } else if (command === 'duplicate') {
        if (folders.length >= FOLDER_MAX) {
          setFeedback(LIMIT_MESSAGE);
        } else {
          const { folder: copy } = await folderApi.duplicate(folder);
          setAll(true);
          setInspecting(copy.id);
          setFeedback('Folder duplicated. Accounts and draft destinations are unchanged.');
        }
      } else {
        await folderApi.move(folder.id, command === 'up' ? -1 : 1);
        setFeedback('Folder order updated.');
      }
    } catch (error) {
      setFeedback(folderErrorMessage(error, 'The folder could not be changed. Nothing was lost.'));
    }
  }
  async function confirmDelete() {
    const folder = inspected;
    if (!folder) return;
    try {
      await folderApi.remove(folder.id);
      setConfirmingDelete(false);
      setInspecting(null);
      setFeedback('Folder deleted. Accounts and draft destinations are unchanged.');
      newFolderRef.current?.focus({ preventScroll: true });
    } catch (error) {
      setFeedback(folderErrorMessage(error, 'The folder could not be deleted. Nothing was changed.'));
    }
  }

  /* ---------------------------------------------------------------- editor (a separate saved transaction) */
  function openEditor(folder: ChannelFolder | null) {
    if (!folder && folders.length >= FOLDER_MAX) {
      setFeedback(LIMIT_MESSAGE);
      return;
    }
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirmingDelete(false);
    setEditor({
      draft: folder ? { id: folder.id, name: folder.name, symbol: asSymbol(folder.symbol), pinned: folder.pinned === true, accountIds: [...folder.accountIds] } : { name: '', symbol: 'folder', pinned: false, accountIds: [] },
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
      setConfirmingDelete(false);
      if (!visibleFolders(list, '', all, accounts).some((f) => f.id === saved.id)) setAll(true);
      pendingChevron.current = saved.id;
      returnFocus.current = null;
      setFeedback('Folder saved. Accounts and draft destinations are unchanged.');
    } catch (error) {
      setEditor((current) => (current ? { ...current, error: folderErrorMessage(error) } : current));
    }
  }

  /* ---------------------------------------------------------------- render */
  if (accounts.length === 0 && folders.length === 0) return null;

  const sources = folders.filter((folder) => readFolder(folder, view, accounts, everyPlatform).state === 'all');
  const viewSummary = view.length > 0 ? selectionLabel(view, snapshotContext(folders, sources.map((f) => f.id), accounts)) : null;
  const editing = editor?.draft.id ? 'edit' : editor ? 'new' : null;

  const shelfNodes: ReactNode[] = [];
  const panel = inspected ? (
    <FolderPanel
      key='panel'
      id={panelId}
      folder={inspected}
      accounts={accounts}
      view={view}
      onMember={setMember}
      canEdit={canEdit}
      busy={folderApi.busy}
      canMoveUp={canMove(folders, inspected.id, -1)}
      canMoveDown={canMove(folders, inspected.id, 1)}
      confirmingDelete={confirmingDelete}
      onEdit={() => openEditor(inspected)}
      onCommand={(command) => void runCommand(command)}
      onCancelDelete={() => setConfirmingDelete(false)}
      onConfirmDelete={() => void confirmDelete()}
      keepRef={keepRef}
    />
  ) : null;
  shelf.forEach((folder, i) => {
    shelfNodes.push(
      <FolderCard
        key={folder.id}
        folder={folder}
        reading={readFolder(folder, view, accounts, everyPlatform)}
        accounts={accounts}
        inspected={inspecting === folder.id}
        inspectorId={panelId}
        onToggle={() => toggleFolder(folder)}
        onInspect={() => toggleInspector(folder.id)}
      />
    );
    if (i === slot && panel) shelfNodes.push(panel);
  });

  const newFolderButton = (withRef: boolean) => (
    <Button ref={withRef ? newFolderRef : undefined} variant='glass' size='control' onClick={() => openEditor(null)} disabled={accounts.length === 0}>
      <IconFolderPlus className='size-4' />
      New folder
    </Button>
  );

  return (
    <section ref={root} aria-labelledby='folders-heading' className='flex flex-col gap-4'>
      <div className='flex flex-col gap-3 md:flex-row md:items-end md:justify-between'>
        <div className='flex min-w-0 flex-col gap-1'>
          <h2 id='folders-heading' className='text-foreground text-lg font-medium tracking-tight'>
            Saved folders
          </h2>
          <p className='text-muted-foreground max-w-[70ch] text-sm leading-relaxed'>
            Named groups of your accounts. Pick one to show only its accounts below; drafts choose their destinations in Channel Bloom. A folder is a
            shortcut, not a platform: it never means its accounts are connected or publishable.
          </p>
        </div>
        <div className='flex shrink-0 flex-wrap items-center gap-2'>
          {(hidden > 0 || all) && folders.length > FOLDER_SHELF && (
            <Button variant='quiet' className={CONTROL_44} aria-expanded={all} onClick={() => setAll((value) => !value)}>
              {all ? 'Show fewer' : `View all ${folders.length}`}
            </Button>
          )}
          {canEdit ? newFolderButton(true) : <span className='text-muted-foreground text-xs'>Only editors can change folders.</span>}
        </div>
      </div>
      <p role='status' aria-live='polite' className={cn('text-xs leading-relaxed', feedback ? 'text-muted-foreground' : 'sr-only')}>
        {feedback ?? ''}
      </p>
      {folderApi.loading ? (
        <StateMessage kind='loading' layout='inline' title='Loading folders…' />
      ) : folders.length === 0 ? (
        <StateMessage
          kind='empty'
          layout='inline'
          title='No folders yet'
          description='Save the accounts you post to together as a folder and pick them in one tap next time.'
          action={canEdit ? newFolderButton(false) : undefined}
          className='rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3'
        />
      ) : (
        <div className='grid gap-3 md:grid-cols-2'>{shelfNodes}</div>
      )}
      {viewSummary && <ActiveFilters count={Math.max(1, sources.length)} summary={viewSummary} onClear={clearView} clearLabel='Show all accounts' />}

      <RafiiDialog
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open) cancelEditor();
        }}
      >
        <RafiiDialogContent size='sm' className='md:h-[min(46rem,92dvh)]' initialFocus={(type) => (type === 'touch' ? null : nameRef.current)}>
          <RafiiDialogHeader
            eyebrow={editing === 'edit' ? 'Edit folder' : 'New folder'}
            title={editing === 'edit' ? 'Make it' : 'Keep a good'}
            accent={editing === 'edit' ? 'yours.' : 'group.'}
            intro='A name, a few accounts. Ready for next time.'
          />
          {editor && (
            <FolderEditor
              draft={editor.draft}
              onChange={(next) => setEditor((current) => (current ? { ...current, draft: next, error: null } : current))}
              folders={folders}
              accounts={accounts}
              draftable={everyPlatform}
              keepIds={editor.keepIds}
              error={editor.error}
              busy={folderApi.busy}
              onSave={() => void saveEditor()}
              onCancel={cancelEditor}
              nameRef={nameRef}
            />
          )}
        </RafiiDialogContent>
      </RafiiDialog>
    </section>
  );
}
