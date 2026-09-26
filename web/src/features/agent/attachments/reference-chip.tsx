'use client';

/**
 * The Rafii chip (chat-context SPEC §4.4): a borderless glass pill modelled on `ChannelLanguageChip`'s segments, with a
 * 28 px thumbnail or a monochrome icon, the label (about 14ch), a visible role or state word, and a full-height 44 px
 * remove segment divided by a hairline. No red tints (DNA §4.3); state is words plus icons.
 */
import { forwardRef, type KeyboardEvent } from 'react';

import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useAssetImage } from '@/features/library/asset-card';

import type { Chip } from './chips';

const KIND_ICON: Record<Chip['kind'], keyof typeof Icons> = {
  post: 'post',
  template: 'page',
  source: 'listDetails',
  image: 'media',
  video: 'video'
};

/** The one visible word for a chip's role or state (SPEC §13 "Chip role words" / "Chip states"). */
export function chipWord(chip: Chip, opts: { needsOk?: boolean } = {}): string {
  const upload = chip.upload?.status;
  if (upload === 'failed') return 'Failed';
  if (upload === 'uploading')
    return typeof chip.upload?.progress === 'number'
      ? `Uploading ${chip.upload.progress}%`
      : 'Uploading';
  if (upload === 'preparing' || upload === 'checking') return 'Uploading';
  if (chip.kind === 'image' || chip.kind === 'video') {
    if (chip.role === 'reference') {
      if (chip.read?.status === 'reading') return 'Reading';
      if (chip.read?.status === 'read') return 'Read';
      if (chip.read?.status === 'failed') return 'Failed';
      return 'Reference';
    }
    // A video this browser couldn't decode still uploads (the server checks the container); the chip says so.
    if (chip.kind === 'video' && chip.meta?.noPreview) return 'No preview in this browser';
    if (chip.kind === 'video' && chip.meta?.lengthUnchecked) return 'Length not checked.';
    return 'In post';
  }
  if (chip.kind === 'post') return chip.role === 'rework' ? 'Rework' : 'For ideas';
  if (chip.kind === 'source' && opts.needsOk) return 'Needs your OK';
  return chip.kind === 'template' ? 'Template' : 'Source';
}

function wordIcon(chip: Chip, word: string): keyof typeof Icons | null {
  if (word === 'Failed') return 'alertCircle';
  if (word.startsWith('Uploading') || word === 'Reading') return 'spinner';
  if (word === 'Read') return 'check';
  if (chip.kind === 'post' && chip.role === 'rework') return 'edit';
  return null;
}

function Thumb({ chip }: { chip: Chip }) {
  const settled = !chip.upload || chip.upload.status === 'ready';
  const media = chip.kind === 'image' || chip.kind === 'video';
  const image = useAssetImage(chip.id, media && settled);
  const Icon = Icons[KIND_ICON[chip.kind]];
  if (media && image.data) {
    return (
      // A private object URL from the media route; next/image cannot optimise it.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={image.data} alt='' className='size-7 shrink-0 rounded-md object-cover' />
    );
  }
  return (
    <span
      aria-hidden
      className='bg-foreground/[0.06] flex size-7 shrink-0 items-center justify-center rounded-md'
    >
      <Icon className='text-muted-foreground size-4' />
    </span>
  );
}

export interface ReferenceChipProps {
  chip: Chip;
  /** Roving focus: only the active chip is in the tab order. */
  active: boolean;
  needsOk?: boolean;
  onOpen: () => void;
  onRemove: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void;
  onFocus?: () => void;
}

export const ReferenceChip = forwardRef<HTMLButtonElement, ReferenceChipProps>(
  function ReferenceChip({ chip, active, needsOk, onOpen, onRemove, onKeyDown, onFocus }, ref) {
    const word = chipWord(chip, { needsOk });
    const icon = wordIcon(chip, word);
    const WordIcon = icon ? Icons[icon] : null;
    return (
      <div
        data-slot='reference-chip'
        className='rafii-glass text-foreground inline-flex h-11 shrink-0 items-stretch overflow-hidden rounded-full text-xs whitespace-nowrap'
      >
        <button
          ref={ref}
          type='button'
          tabIndex={active ? 0 : -1}
          onClick={onOpen}
          onKeyDown={onKeyDown}
          onFocus={onFocus}
          aria-label={`${chip.label}, ${word}`}
          className='rafii-focus hover:bg-foreground/5 inline-flex min-w-0 items-center gap-2 rounded-l-full pr-3 pl-2'
        >
          <Thumb chip={chip} />
          <span className='max-w-[14ch] truncate font-medium'>{chip.label}</span>
          <span className='text-muted-foreground inline-flex items-center gap-1'>
            {WordIcon ? (
              <WordIcon
                aria-hidden
                className={cn(
                  'size-3.5',
                  (word.startsWith('Uploading') || word === 'Reading') && 'motion-safe:animate-spin'
                )}
              />
            ) : null}
            {word}
          </span>
        </button>
        <button
          type='button'
          tabIndex={-1}
          onClick={onRemove}
          aria-label={`Remove ${chip.label}`}
          className='rafii-focus border-foreground/10 text-muted-foreground hover:text-foreground hover:bg-foreground/5 inline-flex w-11 shrink-0 items-center justify-center rounded-r-full border-l'
        >
          <Icons.close aria-hidden className='size-4' />
        </button>
      </div>
    );
  }
);
