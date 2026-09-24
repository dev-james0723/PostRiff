'use client';

import { useId, useMemo, useState, type KeyboardEvent, type RefObject } from 'react';
import { IconCheck, IconPin } from '@tabler/icons-react';
import { RafiiDialogBody, RafiiDialogFooter } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { ChannelFolder } from '@/lib/api/types';
import { FOLDER_NAME_MAX, FOLDER_SYMBOLS, cleanSelection, validateFolder, type FolderAccount, type FolderSymbol } from '@/lib/channels/folders';
import { cn } from '@/lib/utils';
import { AccountRow } from './account-row';
import { FolderGlyph, SYMBOL_ICONS } from './folder-glyph';
import { MISSING_REASON, SYMBOL_LABELS, draftReason, plural, type Draftable } from './helpers';

export interface EditorDraft {
  /** Set when editing an existing folder. */
  id?: string;
  name: string;
  symbol: FolderSymbol;
  pinned: boolean;
  accountIds: string[];
}

export interface FolderEditorProps {
  draft: EditorDraft;
  onChange: (next: EditorDraft) => void;
  folders: ChannelFolder[];
  accounts: readonly FolderAccount[];
  draftable: Draftable;
  /** The stored members of the folder being edited; stale ones may stay (an explicit choice, not a drop). */
  keepIds: readonly string[];
  /** A server-side failure to show next to the fields; the draft is kept. */
  error: string | null;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
  nameRef: RefObject<HTMLInputElement | null>;
}

/** Client-side reading of the draft: mirrors the server so Save is only enabled for a folder it would accept. */
export function editorValidation(draft: EditorDraft, folders: ChannelFolder[], accounts: readonly FolderAccount[], keepIds: readonly string[]): { valid: boolean; message: string | null } {
  try {
    validateFolder(draft, folders, accounts as FolderAccount[], keepIds);
    return { valid: true, message: null };
  } catch (error) {
    return { valid: false, message: error instanceof Error ? error.message : 'This folder cannot be saved yet.' };
  }
}

/**
 * The folder editor (v9 addendum §4): a separate saved transaction. Name, optional symbol,
 * pin and members; the live folder object previews the result. Saving changes the folder only
 * and never applies destinations.
 */
export function FolderEditor({ draft, onChange, folders, accounts, draftable, keepIds, error, busy, onSave, onCancel, nameRef }: FolderEditorProps) {
  const uid = useId();
  const [attempted, setAttempted] = useState(false);
  const validation = useMemo(() => editorValidation(draft, folders, accounts, keepIds), [draft, folders, accounts, keepIds]);
  const showRule = !validation.valid && (attempted || draft.name.trim().length > 0);
  const message = error ?? (showRule ? validation.message : null);
  const connectedMembers = cleanSelection(draft.accountIds, accounts as FolderAccount[]).length;
  const staleMembers = draft.accountIds.filter((id) => keepIds.includes(id) && !accounts.some((a) => a.id === id && a.connected));
  const errorId = `${uid}-error`;
  const symbolLabelId = `${uid}-symbol`;

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    setAttempted(true);
    if (validation.valid && !busy) onSave();
  }

  function setMember(id: string, checked: boolean) {
    onChange({ ...draft, accountIds: checked ? Array.from(new Set([...draft.accountIds, id])) : draft.accountIds.filter((member) => member !== id) });
  }

  return (
    <>
      <RafiiDialogBody className='pt-1'>
        <div className='my-3 flex min-h-24 items-center justify-start gap-4 md:justify-center'>
          <FolderGlyph folder={{ symbol: draft.symbol, accountIds: draft.accountIds }} accounts={accounts} />
          <strong className='text-foreground max-w-60 text-lg font-medium break-words'>{draft.name.trim() || 'Your new folder'}</strong>
        </div>

        <div className='mt-3 flex min-h-9 items-center justify-between gap-2.5 text-sm'>
          <label id={`${uid}-name-label`} htmlFor={`${uid}-name`} className='text-foreground'>
            Folder name
          </label>
          <span className='text-muted-foreground text-xs' aria-live='polite'>
            {draft.name.length} / {FOLDER_NAME_MAX}
          </span>
        </div>
        <input
          ref={nameRef}
          id={`${uid}-name`}
          type='text'
          value={draft.name}
          maxLength={FOLDER_NAME_MAX}
          placeholder='e.g. Festival, Personal, Launch week'
          autoComplete='off'
          aria-labelledby={`${uid}-name-label`}
          aria-describedby={errorId}
          aria-invalid={message ? true : undefined}
          disabled={busy}
          onChange={(event) => onChange({ ...draft, name: event.target.value })}
          onKeyDown={onKeyDown}
          className='rafii-field rafii-focus mt-1 min-h-12 w-full rounded-[14px] px-3.5 text-base leading-normal placeholder:text-[var(--rafii-text-tertiary)]'
        />

        <div className='mt-4 flex min-h-9 items-center justify-between gap-2.5 text-sm'>
          <span id={symbolLabelId} className='text-foreground'>
            Folder symbol
          </span>
          <span className='text-muted-foreground text-xs'>Optional</span>
        </div>
        <div role='group' aria-labelledby={symbolLabelId} className='mt-1 flex justify-between gap-1.5 md:gap-2'>
          {FOLDER_SYMBOLS.map((symbol) => {
            const Icon = SYMBOL_ICONS[symbol];
            const active = draft.symbol === symbol;
            return (
              <button
                key={symbol}
                type='button'
                aria-pressed={active}
                aria-label={`${SYMBOL_LABELS[symbol]} symbol`}
                title={SYMBOL_LABELS[symbol]}
                disabled={busy}
                onClick={() => onChange({ ...draft, symbol })}
                className={cn('rafii-focus flex min-h-11 min-w-0 flex-1 items-center justify-center rounded-xl transition-colors duration-200', active ? 'rafii-glass-selected text-foreground' : 'text-muted-foreground hover:text-foreground bg-[rgb(var(--rafii-highlight-rgb)/0.03)]')}
              >
                <Icon className='size-[19px]' stroke={1.75} />
              </button>
            );
          })}
        </div>

        <label className='mt-2.5 flex min-h-12 cursor-pointer items-center gap-2.5 text-sm'>
          <input type='checkbox' aria-label='Pin to the folder shelf' checked={draft.pinned} disabled={busy} onChange={(event) => onChange({ ...draft, pinned: event.target.checked })} className='accent-foreground rafii-focus size-[17px] rounded' />
          <span className='text-foreground'>Pin to the folder shelf</span>
          <IconPin aria-hidden className='text-muted-foreground ml-auto size-3.5' />
        </label>

        <div className='mt-3 flex min-h-9 items-center justify-between gap-2.5 text-sm'>
          <span className='text-foreground'>Include accounts</span>
          <span className='text-muted-foreground text-xs'>{plural(connectedMembers, 'account')} selected</span>
        </div>
        <div className='mt-1 grid gap-1.5'>
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              id={account.id}
              kind='member'
              platform={account.platform}
              account={account.account}
              state={account.state}
              checked={draft.accountIds.includes(account.id)}
              onCheckedChange={(checked) => setMember(account.id, checked)}
              reason={!account.connected ? MISSING_REASON : null}
              hint={account.connected && !draftable(account.platform) ? draftReason(account.platform) : null}
            />
          ))}
          {staleMembers
            .filter((id) => !accounts.some((a) => a.id === id))
            .map((id) => (
              <AccountRow key={id} id={id} kind='member' platform='Removed account' account='This connection is gone' checked={draft.accountIds.includes(id)} onCheckedChange={(checked) => setMember(id, checked)} hint={MISSING_REASON} />
            ))}
          {accounts.length === 0 && <p className='text-muted-foreground text-sm'>Connect an account first; folders group the accounts of this workspace.</p>}
        </div>

        <p id={errorId} role='status' aria-live='polite' className={cn('mt-3 text-xs leading-relaxed', message ? 'text-foreground' : 'sr-only')}>
          {message ?? ''}
        </p>
        <p className='text-muted-foreground mt-3 text-xs leading-relaxed'>Saving changes the folder only. Your current draft destinations and output settings stay untouched.</p>
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row items-center gap-3'>
        <Button variant='quiet' size='lg' className='min-h-11 text-[13px]' onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant='action'
          size='control'
          className='flex-1'
          disabled={!validation.valid || busy}
          onClick={() => {
            setAttempted(true);
            onSave();
          }}
        >
          {busy ? 'Saving…' : 'Save folder'} <IconCheck className='size-4' />
        </Button>
      </RafiiDialogFooter>
    </>
  );
}
