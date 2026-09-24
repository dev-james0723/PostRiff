'use client';

import { IconCheck, IconChevronDown, IconPin } from '@tabler/icons-react';
import type { ChannelFolder } from '@/lib/api/types';
import type { FolderAccount } from '@/lib/channels/folders';
import { cn } from '@/lib/utils';
import { FolderGlyph } from './folder-glyph';
import { folderStateText, membersNote, type FolderReading } from './helpers';

export interface FolderCardProps {
  folder: ChannelFolder;
  reading: FolderReading;
  accounts: readonly FolderAccount[];
  inspected: boolean;
  /** The inspector element every chevron controls. */
  inspectorId: string;
  onToggle: () => void;
  onInspect: () => void;
}

const SURFACE: Record<FolderReading['state'], string> = {
  empty: 'bg-[linear-gradient(140deg,rgb(var(--rafii-highlight-rgb)/0.06),rgb(var(--rafii-highlight-rgb)/0.025))]',
  none: 'bg-[linear-gradient(140deg,rgb(var(--rafii-highlight-rgb)/0.095),rgb(var(--rafii-highlight-rgb)/0.035))]',
  mixed: 'bg-[linear-gradient(130deg,rgb(var(--rafii-highlight-rgb)/0.135),rgb(var(--rafii-highlight-rgb)/0.05))]',
  all: 'bg-[linear-gradient(130deg,rgb(var(--rafii-highlight-rgb)/0.2),rgb(var(--rafii-highlight-rgb)/0.075))] shadow-[inset_0_20px_25px_-27px_#fffa,0_12px_24px_-20px_#0008]'
};

/**
 * A compact glass folder (v9 addendum §2). The main hit area is a checkbox that selects the
 * whole group (`aria-checked` mixed when only some members are selected); the chevron is a
 * separate control that only opens the inspector. Neither needs hover or drag.
 */
export function FolderCard({ folder, reading, accounts, inspected, inspectorId, onToggle, onInspect }: FolderCardProps) {
  const checked: boolean | 'mixed' = reading.state === 'all' ? true : reading.state === 'mixed' ? 'mixed' : false;
  const note = membersNote(reading);
  const label = `${folder.name}${folder.pinned ? ', pinned' : ''}, ${reading.count} of ${reading.total} accounts selected${note ? `. ${note}` : ''}`;
  return (
    <article data-folder-card={folder.id} data-selection={reading.state} className={cn('group/card relative isolate min-w-0 rounded-[22px] shadow-[inset_0_14px_20px_-25px_#fff7,0_9px_25px_-25px_#0009] transition-[background,box-shadow] duration-[350ms]', SURFACE[reading.state])}>
      <button
        type='button'
        role='checkbox'
        aria-checked={checked}
        aria-label={label}
        disabled={reading.state === 'empty'}
        data-folder-select={folder.id}
        onClick={onToggle}
        className={cn(
          'rafii-focus relative flex min-h-[8.75rem] w-full min-w-0 flex-col items-start justify-center rounded-[22px] px-3.5 pt-2.5 pb-4 text-left',
          'md:grid md:min-h-32 md:grid-cols-[99px_minmax(0,1fr)] md:grid-rows-2 md:gap-x-3 md:p-4',
          'disabled:cursor-default active:[&_[data-glyph]]:scale-[0.97]'
        )}
      >
        <FolderGlyph folder={folder} accounts={accounts} inspected={inspected} className='mx-auto mb-0.5 md:col-start-1 md:row-span-2 md:mx-0 md:self-center' />
        <span aria-hidden className={cn('absolute top-3 right-3.5 flex size-5 items-center justify-center rounded-full transition-colors duration-300', reading.state === 'all' ? 'bg-foreground text-background' : 'text-foreground bg-[rgb(var(--rafii-highlight-rgb)/0.07)]')}>
          {reading.state === 'all' && <IconCheck className='size-3' stroke={2.5} />}
          {reading.state === 'mixed' && <span className='h-0.5 w-2.5 rounded-full bg-current' />}
        </span>
        <strong className='text-foreground mt-0.5 max-w-[calc(100%-1.5rem)] truncate text-sm font-medium md:mt-0 md:max-w-[calc(100%-0.25rem)] md:self-end'>{folder.name}</strong>
        <span className='text-muted-foreground mt-0.5 flex flex-col text-xs leading-relaxed md:mt-1 md:self-start'>
          <span>{folderStateText(reading)}</span>
          {note && <span>{note}</span>}
        </span>
        {folder.pinned && <IconPin aria-hidden className='text-muted-foreground/80 absolute top-3.5 left-4 size-3 md:top-3 md:left-3' />}
      </button>
      <button
        type='button'
        aria-label={`Open ${folder.name} folder`}
        aria-expanded={inspected}
        aria-controls={inspectorId}
        data-folder-inspect={folder.id}
        onClick={onInspect}
        className={cn(
          'rafii-focus absolute right-1.5 bottom-1.5 z-[3] flex size-11 items-center justify-center rounded-full transition-colors duration-200',
          inspected ? 'text-foreground bg-[rgb(var(--rafii-highlight-rgb)/0.095)]' : 'text-muted-foreground hover:text-foreground hover:bg-[rgb(var(--rafii-highlight-rgb)/0.095)]'
        )}
      >
        <IconChevronDown className={cn('rafii-spatial-motion size-4 transition-transform duration-[400ms] ease-[var(--rafii-ease-soft)]', inspected && 'rotate-180')} />
      </button>
    </article>
  );
}
