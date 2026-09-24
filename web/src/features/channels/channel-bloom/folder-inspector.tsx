'use client';

import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { IconArrowDown, IconArrowUp, IconCopy, IconDots, IconPencil, IconPin, IconPinnedOff, IconTrash } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import type { ChannelFolder } from '@/lib/api/types';
import type { FolderAccount } from '@/lib/channels/folders';
import { RAFII_EASE_CSS, animateHeight, cancelAnimations, motionAllowed } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { AccountRow } from './account-row';
import { MISSING_REASON, draftReason, memberStatus, type Draftable } from './helpers';

export type FolderCommand = 'pin' | 'duplicate' | 'up' | 'down' | 'delete';

export interface FolderInspectorProps {
  id: string;
  /** The inspected folder; null closes the inspector. */
  folder: ChannelFolder | null;
  accounts: readonly FolderAccount[];
  draftable: Draftable;
  /** The staged destination ids; member rows edit this same set. */
  selected: readonly string[];
  onMemberChange: (id: string, checked: boolean) => void;
  canEdit: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  busy: boolean;
  menuOpen: boolean;
  onMenuOpenChange: (open: boolean) => void;
  confirmingDelete: boolean;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  onEdit: () => void;
  onCommand: (command: FolderCommand) => void;
  moreRef: RefObject<HTMLButtonElement | null>;
  reduced: boolean;
  /** Where the body scrolls, so the unfolded inspector can be brought into view. */
  onRevealed?: (element: HTMLElement) => void;
}

const MENU_ITEM = 'rafii-focus hover:rafii-glass-selected text-foreground flex min-h-11 items-center gap-2 rounded-[10px] px-2.5 text-left text-[13px] transition-colors disabled:opacity-35 disabled:hover:bg-transparent';

/**
 * The account inspector beneath a folder's row (v9 addendum §2): a measured disclosure that
 * unfolds to readable account rows, with Edit and the folder's management actions. Its
 * checkboxes edit the same staged selection as the individual account rows; the saved folder
 * only changes through Edit or the More menu.
 */
export function FolderInspector({ id, folder: inspected, accounts, draftable, selected, onMemberChange, canEdit, canMoveUp, canMoveDown, busy, menuOpen, onMenuOpenChange, confirmingDelete, onCancelDelete, onConfirmDelete, onEdit, onCommand, moreRef, reduced, onRevealed }: FolderInspectorProps) {
  const box = useRef<HTMLDivElement>(null);
  const shown = useRef<string | null>(null);
  const mounted = useRef(false);
  const lastHeight = useRef(0);
  const lastFolder = useRef<ChannelFolder | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  // The folder whose rows stay visible while the inspector folds closed.
  const [closing, setClosing] = useState<ChannelFolder | null>(null);
  const folderId = inspected?.id ?? null;
  if (inspected) lastFolder.current = inspected;
  const displayed = inspected ?? closing;

  // Track the rendered height so a switch between folders (or a close) can animate from the current height.
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      lastHeight.current = el.getBoundingClientRect().height;
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const was = shown.current;
    shown.current = folderId;
    if (!mounted.current) {
      mounted.current = true;
      el.style.height = folderId ? 'auto' : '0px';
      el.style.overflow = 'hidden';
      el.inert = !folderId;
      el.setAttribute('aria-hidden', String(!folderId));
      return;
    }
    if (was === folderId) return;
    const animated = !reduced && motionAllowed() && typeof el.animate === 'function';
    if (was) el.style.height = `${lastHeight.current}px`;
    if (!folderId) {
      // Keep the rows on screen while the box folds away; drop them once it has closed.
      if (animated) setClosing(lastFolder.current);
      animateHeight(el, false, { enabled: animated });
      if (animated) {
        Promise.all(el.getAnimations().map((a) => a.finished.catch(() => {}))).then(() => {
          if (shown.current === null) setClosing(null);
        });
      }
      return;
    }
    setClosing(null);
    animateHeight(el, true, { enabled: animated });
    if (animated) {
      el.querySelectorAll<HTMLElement>('[data-peek]').forEach((mark, i) => {
        mark.animate([{ opacity: 0, transform: 'translateY(-12px) rotate(-8deg) scale(0.8)' }, { opacity: 1, transform: 'none' }], { duration: 430, delay: 90 + i * 45, easing: RAFII_EASE_CSS.soft, fill: 'backwards' });
      });
    }
    const reveal = () => {
      if (shown.current === folderId) onRevealed?.(el);
    };
    if (animated) Promise.all(el.getAnimations().map((a) => a.finished.catch(() => {}))).then(reveal);
    else requestAnimationFrame(reveal);
  }, [folderId, onRevealed, reduced]);

  useLayoutEffect(() => () => cancelAnimations(box.current), []);

  useEffect(() => {
    if (confirmingDelete) keepRef.current?.focus({ preventScroll: true });
  }, [confirmingDelete]);

  const menuId = `${id}-menu`;
  const folder = displayed;
  return (
    <div ref={box} id={id} className='col-span-full min-w-0 overflow-hidden'>
      {folder && (
        <div className='rounded-[20px] bg-[linear-gradient(130deg,rgb(var(--rafii-highlight-rgb)/0.06),rgb(var(--rafii-highlight-rgb)/0.025))] p-4 shadow-[inset_0_12px_24px_-24px_#fff5]'>
          <div className='mb-2 flex items-center gap-1.5'>
            <div className='min-w-0 flex-1'>
              <span className='rafii-eyebrow'>Inside the folder</span>
              <h3 className='text-foreground mt-1 text-[15px] font-medium break-words'>{folder.name}</h3>
            </div>
            <Button variant='quiet' size='lg' className='min-h-11 text-[13px]' onClick={onEdit} disabled={!canEdit || busy} title={canEdit ? undefined : 'Only editors can change folders.'}>
              <IconPencil className='size-4' /> Edit
            </Button>
            <button
              ref={moreRef}
              type='button'
              aria-label='More folder actions'
              aria-expanded={menuOpen}
              aria-controls={menuId}
              disabled={!canEdit || busy}
              title={canEdit ? undefined : 'Only editors can change folders.'}
              onClick={() => onMenuOpenChange(!menuOpen)}
              className='rafii-glass rafii-focus hover:rafii-glass-selected text-muted-foreground aria-expanded:text-foreground flex size-11 shrink-0 items-center justify-center rounded-xl disabled:opacity-40'
            >
              <IconDots className='size-[18px]' />
            </button>
          </div>
          {menuOpen && (
            <div id={menuId} role='group' aria-label={`${folder.name} folder actions`} className='mb-3 grid grid-cols-2 gap-1 rounded-[13px] bg-[rgb(var(--rafii-highlight-rgb)/0.04)] p-1.5'>
              <button type='button' className={MENU_ITEM} onClick={() => onCommand('pin')}>
                {folder.pinned ? <IconPinnedOff className='size-3.5' /> : <IconPin className='size-3.5' />}
                {folder.pinned ? 'Unpin folder' : 'Pin folder'}
              </button>
              <button type='button' className={MENU_ITEM} onClick={() => onCommand('duplicate')}>
                <IconCopy className='size-3.5' /> Duplicate
              </button>
              <button type='button' className={MENU_ITEM} disabled={!canMoveUp} onClick={() => onCommand('up')}>
                <IconArrowUp className='size-3.5' /> Move up
              </button>
              <button type='button' className={MENU_ITEM} disabled={!canMoveDown} onClick={() => onCommand('down')}>
                <IconArrowDown className='size-3.5' /> Move down
              </button>
              <button type='button' className={cn(MENU_ITEM, 'col-span-2')} onClick={() => onCommand('delete')}>
                <IconTrash className='size-3.5' /> Delete folder
              </button>
            </div>
          )}
          {confirmingDelete && (
            <div role='group' aria-labelledby={`${id}-delete-title`} className='rafii-glass-selected mb-2.5 rounded-[14px] p-3.5'>
              <strong id={`${id}-delete-title`} className='text-foreground text-[13px] font-medium break-words'>
                Delete “{folder.name}”?
              </strong>
              <p className='text-muted-foreground mt-2 text-xs leading-relaxed'>This removes the folder only. Accounts and draft destinations stay unchanged.</p>
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
              const status = memberStatus(memberId, accounts, draftable);
              if (!account) {
                return <AccountRow key={memberId} id={memberId} platform='Removed account' account='This connection is gone' checked={false} onCheckedChange={() => {}} reason={MISSING_REASON} peek />;
              }
              return (
                <AccountRow
                  key={memberId}
                  id={memberId}
                  platform={account.platform}
                  account={account.account}
                  state={account.state}
                  checked={selected.includes(memberId)}
                  onCheckedChange={(checked) => onMemberChange(memberId, checked)}
                  reason={status === 'missing' ? MISSING_REASON : status === 'unavailable' ? draftReason(account.platform) : null}
                  peek
                />
              );
            })}
          </div>
          <p className='text-muted-foreground mt-3 text-xs leading-relaxed'>Changes here are just for this draft. The saved folder stays the same.</p>
        </div>
      )}
    </div>
  );
}
