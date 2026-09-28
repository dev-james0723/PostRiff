'use client';

/**
 * The composer's attachment row (chat-context SPEC §4.4, §11.1): a 44×44 ＋ button, the chips in one scrolling row with
 * an edge mask and roving focus (one tab stop, arrow keys; Delete/Backspace removes and moves on), one polite live
 * region, and the hidden file inputs, mounted here (outside any popup) and clicked inside the tap. Removal is undoable
 * for 5 s from a "Removed · Undo" toast. Tapping a chip opens its options: a Popover on a fine pointer, a sheet otherwise.
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { toast } from 'sonner';

import { Icons } from '@/components/icons';
import {
  RafiiDialog,
  RafiiDialogBody,
  RafiiDialogContent,
  RafiiDialogHeader
} from '@/components/rafii/rafii-dialog';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent } from '@/components/ui/popover';
import type { AttachmentsCatalog, Snapshot } from '@/lib/api/types';

import type { Chip } from './chips';
import { ChipOptions, MediaOptions } from './media-options';
import { PlusSheet, type PlusView } from './plus-sheet';
import { ReferenceChip } from './reference-chip';
import { UNDO_MS } from './state';
import { TextFileSheet } from './text-file-sheet';
import type { ComposerAttachments } from './use-composer-attachments';

/** The composer's one polite live region: pass `announce` to `useComposerAttachments`, `message` to the bar. */
export function useLiveRegion() {
  const [message, setMessage] = useState('');
  const announce = useCallback((next: string) => {
    // Clear first so the same words are announced again.
    setMessage('');
    setTimeout(() => setMessage(next), 30);
  }, []);
  return { message, announce };
}

function useFinePointer(): boolean {
  const [fine, setFine] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(pointer: fine)');
    setFine(query.matches);
    const update = (event: MediaQueryListEvent) => setFine(event.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return fine;
}

export interface AttachmentBarProps {
  attachments: ComposerAttachments;
  conversationId?: string;
  liveMessage: string;
  snapshot: Snapshot | null | undefined;
  owner: string | null | undefined;
  catalog: AttachmentsCatalog | null | undefined;
  creditMode: boolean;
  fixtureWriter: boolean;
  isOwner: boolean;
  /** "More…" in the `@` list opens this view. */
  requestedView?: PlusView | null;
  onRequestedViewHandled?: () => void;
  onRecentPosts?: () => void;
  /** Home splits the bar: the ＋ button in the Context row (`plus`), the chips under the text (`chips`). */
  part?: 'all' | 'plus' | 'chips';
}

export function AttachmentBar({
  attachments,
  conversationId,
  liveMessage,
  snapshot,
  owner,
  catalog,
  creditMode,
  fixtureWriter,
  isOwner,
  requestedView,
  onRequestedViewHandled,
  onRecentPosts,
  part = 'all'
}: AttachmentBarProps) {
  const { chips } = attachments;
  const fine = useFinePointer();
  const deviceInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLInputElement>(null);
  const plusButton = useRef<HTMLButtonElement>(null);
  const chipButtons = useRef(new Map<string, HTMLButtonElement>());
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const active = chips.find((chip) => chip.key === focusKey)?.key ?? chips[0]?.key ?? null;
  const openChip = chips.find((chip) => chip.key === openKey) ?? null;

  const accept = [
    ...(catalog?.photo.accept ?? ['image/jpeg', 'image/png']),
    ...(catalog?.photo.convertFrom ?? []),
    ...(catalog?.video.enabled ? catalog.video.mimes : [])
  ].join(',');

  useEffect(() => {
    if (!attachments.notice) return;
    toast(attachments.notice);
    attachments.dismissNotice();
  }, [attachments]);

  const remove = useCallback(
    (chip: Chip) => {
      const index = chips.findIndex((item) => item.key === chip.key);
      const next = chips[index + 1] ?? chips[index - 1] ?? null;
      attachments.remove(chip.key);
      setOpenKey(null);
      toast('Removed', {
        duration: UNDO_MS,
        action: { label: 'Undo', onClick: () => attachments.undo(chip.key) }
      });
      // Focus moves to the next chip, or to ＋ when none is left.
      requestAnimationFrame(() =>
        (next ? chipButtons.current.get(next.key) : plusButton.current)?.focus()
      );
      if (next) setFocusKey(next.key);
    },
    [attachments, chips]
  );

  function onChipKey(event: KeyboardEvent<HTMLButtonElement>, chip: Chip, index: number) {
    const move = (to: number) => {
      const target = chips[Math.max(0, Math.min(chips.length - 1, to))];
      if (!target) return;
      event.preventDefault();
      setFocusKey(target.key);
      chipButtons.current.get(target.key)?.focus();
    };
    if (event.key === 'ArrowRight') move(index + 1);
    else if (event.key === 'ArrowLeft') move(index - 1);
    else if (event.key === 'Home') move(0);
    else if (event.key === 'End') move(chips.length - 1);
    else if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      remove(chip);
    }
  }

  const needsOk = (chip: Chip) =>
    chip.kind === 'source' &&
    !(snapshot?.state.sources?.find((source) => source.id === chip.id)?.facts ?? []).some(
      (fact) => fact.approved
    );

  const options = openChip ? (
    openChip.kind === 'image' || openChip.kind === 'video' ? (
      <MediaOptions
        chip={openChip}
        conversationId={conversationId}
        asset={snapshot?.state.phase2?.assets.find((asset) => asset.id === openChip.id) ?? null}
        catalog={catalog}
        creditMode={creditMode}
        fixtureWriter={fixtureWriter}
        isOwner={isOwner}
        onRole={(role) => attachments.setRole(openChip.key, role)}
        onRead={() => void attachments.read(openChip.key)}
        onRetry={() => attachments.retry(openChip.key)}
        onRemove={() => remove(openChip)}
      />
    ) : (
      <ChipOptions
        chip={openChip}
        onRole={(role) => attachments.setRole(openChip.key, role)}
        onRemove={() => remove(openChip)}
      />
    )
  ) : null;

  return (
    <div className='flex min-w-0 items-center gap-2'>
      {part !== 'chips' && (
        <>
          <input
            ref={deviceInput}
            aria-label='Photo or video'
            type='file'
            multiple
            hidden
            accept={accept}
            onChange={(event) => {
              if (event.target.files) attachments.addFiles(event.target.files);
              event.target.value = '';
            }}
          />
          <input
            ref={textInput}
            aria-label='Text file'
            type='file'
            hidden
            accept='.txt,.md,text/plain,text/markdown'
            onChange={(event) => {
              if (event.target.files) attachments.addFiles(event.target.files);
              event.target.value = '';
            }}
          />
          <PlusSheet
            trigger={({ onClick }) => (
              <Button
                ref={plusButton}
                type='button'
                variant='glass'
                size='icon-control'
                className='size-11 shrink-0 rounded-full'
                aria-label='Add to message'
                onClick={onClick}
              >
                <Icons.add aria-hidden className='size-5' />
              </Button>
            )}
            snapshot={snapshot}
            owner={owner}
            catalog={catalog}
            chips={chips}
            creditMode={creditMode}
            onPickDevice={() => deviceInput.current?.click()}
            onPickText={() => textInput.current?.click()}
            onRecentPosts={onRecentPosts}
            onPickItem={(item) => void attachments.addReference(item)}
            onRememberConnectorItems={attachments.rememberConnectorItems}
            onAddAssets={(assets) => attachments.addLibrary(assets)}
            requestedView={requestedView}
            onRequestedViewHandled={onRequestedViewHandled}
          />
          <TextFileSheet result={attachments.textFile} onDone={attachments.dismissTextFile} />
        </>
      )}
      {part !== 'plus' && (
        <>
          {chips.length > 0 ? (
            <div
              role='group'
              aria-label='Attached to this message'
              className='scroll-fade-x scrollbar-none flex min-w-0 flex-1 gap-2 overflow-x-auto overscroll-x-contain py-0.5'
            >
              {chips.map((chip, index) => (
                <ReferenceChip
                  key={chip.key}
                  ref={(element) => {
                    if (element) chipButtons.current.set(chip.key, element);
                    else chipButtons.current.delete(chip.key);
                  }}
                  chip={chip}
                  active={chip.key === active}
                  needsOk={needsOk(chip)}
                  onFocus={() => setFocusKey(chip.key)}
                  onKeyDown={(event) => onChipKey(event, chip, index)}
                  onOpen={() => setOpenKey(chip.key)}
                  onRemove={() => remove(chip)}
                />
              ))}
            </div>
          ) : null}
          <div aria-live='polite' className='sr-only'>
            {liveMessage}
          </div>
          {openChip && fine ? (
            <Popover open onOpenChange={(next) => (next ? undefined : setOpenKey(null))}>
              <PopoverContent
                anchor={chipButtons.current.get(openChip.key) ?? null}
                side='top'
                align='start'
                className='w-80'
              >
                {options}
              </PopoverContent>
            </Popover>
          ) : null}
          <RafiiDialog
            open={Boolean(openChip && !fine)}
            onOpenChange={(next) => (next ? undefined : setOpenKey(null))}
          >
            <RafiiDialogContent size='sm'>
              <RafiiDialogHeader title={openChip?.label ?? ''} />
              <RafiiDialogBody>{options}</RafiiDialogBody>
            </RafiiDialogContent>
          </RafiiDialog>
        </>
      )}
    </div>
  );
}
