'use client';

/**
 * The non-modal `@` list (chat-context SPEC §4.3). It never takes focus: on desktop a base-ui Popover anchored to the
 * textarea with `initialFocus={false}`/`finalFocus={false}`; on a coarse pointer a strip pinned to the keyboard's top
 * edge. The first row is always "Keep “@{query}” as text" and is highlighted; picking needs a tap, a click, or an
 * arrow key then Enter. Rows `preventDefault` on pointer down so the textarea keeps focus and the keyboard stays.
 * The textarea gets its ARIA and key handling from `mentionTextareaProps` / `handleMentionKeyDown` (composed by the
 * caller, never spread over its own handlers).
 */
import { useEffect, useState, type KeyboardEvent, type RefObject } from 'react';

import { Icons } from '@/components/icons';
import { Popover, PopoverContent } from '@/components/ui/popover';
import { useVisualViewport } from '@/hooks/use-visual-viewport';
import { isImeEvent } from '@/lib/ime';
import { cn } from '@/lib/utils';

import type { PickerCategory } from './matcher';
import type { PickerItem } from './picker-items';

export const MENTION_ROWS = 4;

export const GROUP_LABELS: Record<PickerCategory, string> = {
  posts: 'Posts',
  templates: 'Templates',
  accounts: 'Accounts',
  folders: 'Folders',
  sources: 'Sources',
  library: 'Library'
};

const ICON: Record<PickerItem['kind'], keyof typeof Icons> = {
  post: 'post',
  template: 'page',
  account: 'account',
  folder: 'folder',
  source: 'listDetails',
  image: 'media',
  video: 'video'
};

export type MentionOption =
  | { type: 'keep'; id: string; label: string }
  | { type: 'item'; id: string; label: string; item: PickerItem }
  | { type: 'more'; id: string; label: string };

/** Keep, up to four matches, and "More…" when there are more. Option ids are stable per list and item. */
export function mentionOptions(
  listId: string,
  query: string,
  items: readonly PickerItem[]
): MentionOption[] {
  const options: MentionOption[] = [
    { type: 'keep', id: `${listId}-keep`, label: `Keep “@${query}” as text` },
    ...items.slice(0, MENTION_ROWS).map((item) => ({
      type: 'item' as const,
      id: `${listId}-${item.kind}-${item.id}`,
      label: item.label,
      item
    }))
  ];
  if (items.length > MENTION_ROWS)
    options.push({ type: 'more', id: `${listId}-more`, label: 'More…' });
  return options;
}

/** The live-region line for a result set (SPEC §13). */
export function announcement(items: readonly PickerItem[]): string {
  if (!items.length) return 'No match. The @ stays as text.';
  return `${items.length} ${items.length === 1 ? 'match' : 'matches'} · ${items[0].label}`;
}

/** ARIA the textarea gains while the list exists (a textbox keeps its role; ARIA 1.2 allows these, no aria-expanded). */
export function mentionTextareaProps(
  open: boolean,
  listId: string,
  activeId: string | null
): {
  'aria-autocomplete': 'list';
  'aria-haspopup': 'listbox';
  'aria-controls'?: string;
  'aria-activedescendant'?: string;
} {
  return {
    'aria-autocomplete': 'list',
    'aria-haspopup': 'listbox',
    ...(open ? { 'aria-controls': listId } : {}),
    ...(open && activeId ? { 'aria-activedescendant': activeId } : {})
  };
}

export type MentionKeyAction =
  | { type: 'move'; index: number }
  | { type: 'choose'; index: number }
  | { type: 'close' };

/**
 * What a key does while the list is open; null leaves the key to the textarea. Enter on the Keep row does nothing
 * special (the text stays and typing goes on), so only an arrow key then Enter picks.
 */
export function mentionKey(key: string, active: number, count: number): MentionKeyAction | null {
  if (count <= 0) return null;
  if (key === 'Escape') return { type: 'close' };
  if (key === 'ArrowDown') return { type: 'move', index: (active + 1) % count };
  if (key === 'ArrowUp') return { type: 'move', index: (active - 1 + count) % count };
  if (key === 'Enter' && active > 0) return { type: 'choose', index: active };
  return null;
}

/**
 * The textarea's `onKeyDown` part for the list; returns true when the key was the list's. Escape closes only the list:
 * `preventDefault` + `stopPropagation` before any dialog sees it (DNA §12.5). IME keys are never the list's.
 */
export function handleMentionKeyDown(
  event: KeyboardEvent<HTMLTextAreaElement>,
  list: {
    open: boolean;
    active: number;
    count: number;
    composing?: boolean;
    onMove: (index: number) => void;
    onChoose: (index: number) => void;
    onClose: () => void;
  }
): boolean {
  if (!list.open || list.composing || isImeEvent(event)) return false;
  const action = mentionKey(event.key, list.active, list.count);
  if (!action) return false;
  event.preventDefault();
  event.stopPropagation();
  if (action.type === 'close') list.onClose();
  else if (action.type === 'move') list.onMove(action.index);
  else list.onChoose(action.index);
  return true;
}

/** A textarea blur that moves into the list keeps it open. */
export function blurStaysOpen(relatedTarget: EventTarget | null, listId: string): boolean {
  return (
    typeof Element !== 'undefined' &&
    relatedTarget instanceof Element &&
    Boolean(relatedTarget.closest(`[id="${listId}"]`))
  );
}

function useCoarsePointer(): boolean {
  const [coarse, setCoarse] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(pointer: coarse)');
    setCoarse(query.matches);
    const update = (event: MediaQueryListEvent) => setCoarse(event.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return coarse;
}

function Rows({
  listId,
  options,
  active,
  coarse,
  onActive,
  onChoose
}: {
  listId: string;
  options: MentionOption[];
  active: number;
  coarse: boolean;
  onActive: (index: number) => void;
  onChoose: (index: number) => void;
}) {
  return (
    <div id={listId} role='listbox' aria-label='Suggestions' className='flex flex-col'>
      {options.map((option, index) => {
        const Icon =
          option.type === 'item'
            ? Icons[ICON[option.item.kind]]
            : option.type === 'keep'
              ? Icons.text
              : Icons.search;
        const sublabel =
          option.type === 'item'
            ? [option.item.sublabel, option.item.kind === 'account' ? option.item.state : null]
                .filter(Boolean)
                .join(' · ')
            : '';
        return (
          // oxlint-disable-next-line jsx-a11y/interactive-supports-focus, jsx-a11y/click-events-have-key-events -- options are reached from the focused textarea through aria-activedescendant (handleMentionKeyDown); taking focus would close the mobile keyboard (SPEC §4.3)
          <div
            key={option.id}
            id={option.id}
            role='option'
            aria-selected={index === active}
            onPointerDown={(event) => event.preventDefault()}
            onPointerEnter={() => onActive(index)}
            onClick={() => onChoose(index)}
            className={cn(
              'flex cursor-default items-center gap-2 rounded-md px-2 text-sm select-none',
              coarse ? 'min-h-11' : 'min-h-8',
              index === active ? 'bg-accent text-accent-foreground' : 'text-foreground'
            )}
          >
            <Icon aria-hidden className='text-muted-foreground size-4 shrink-0' />
            <span className='min-w-0 flex-1 truncate'>{option.label}</span>
            {sublabel ? (
              <span className='text-muted-foreground max-w-[45%] shrink-0 truncate text-xs'>
                {sublabel}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export function MentionList({
  open,
  listId,
  query,
  items,
  active,
  anchor,
  onActive,
  onPick,
  onKeep,
  onMore,
  onClose,
  onAnnounce,
  inline = false
}: {
  open: boolean;
  listId: string;
  query: string;
  /** Ranked matches (`flatten(pickerItems(...))`, merged with server results). */
  items: readonly PickerItem[];
  /** Highlighted option index; 0 is the Keep row. */
  active: number;
  anchor: RefObject<HTMLTextAreaElement | null>;
  onActive: (index: number) => void;
  onPick: (item: PickerItem) => void;
  onKeep: () => void;
  onMore: () => void;
  onClose: () => void;
  onAnnounce?: (message: string) => void;
  /** Render in place (inside a modal dialog, whose popup is the only interactive layer), above the field. */
  inline?: boolean;
}) {
  const coarse = useCoarsePointer();
  const viewport = useVisualViewport();
  const options = mentionOptions(listId, query, items);
  const summary = announcement(items);

  useEffect(() => {
    if (open) onAnnounce?.(summary);
  }, [open, summary, onAnnounce]);

  const choose = (index: number) => {
    const option = options[index];
    if (!option) return;
    if (option.type === 'item') onPick(option.item);
    else if (option.type === 'more') onMore();
    else onKeep();
  };

  // The list closes when nothing matches; the @ stays as text (announced above).
  if (!open || items.length === 0) return null;

  const rows = (
    <Rows
      listId={listId}
      options={options}
      active={Math.min(active, options.length - 1)}
      coarse={coarse}
      onActive={onActive}
      onChoose={choose}
    />
  );

  if (inline) {
    return (
      <div className='bg-popover text-popover-foreground ring-foreground/10 absolute inset-x-0 bottom-full z-10 mb-1 rounded-lg p-1 shadow-md ring-1'>
        {rows}
      </div>
    );
  }

  if (coarse) {
    // Pinned to the keyboard's top edge; without a visual viewport, just above the textarea.
    const hasViewport = typeof window !== 'undefined' && Boolean(window.visualViewport);
    const bottom = hasViewport
      ? viewport.offsetTop + viewport.height
      : (anchor.current?.getBoundingClientRect().top ?? 0);
    return (
      <div
        className='bg-popover text-popover-foreground ring-foreground/10 fixed inset-x-0 z-50 border-t p-1 shadow-md ring-1'
        style={{ top: bottom, transform: 'translateY(-100%)' }}
      >
        {rows}
      </div>
    );
  }

  return (
    <Popover open onOpenChange={(next) => (next ? undefined : onClose())} modal={false}>
      <PopoverContent
        anchor={anchor}
        initialFocus={false}
        finalFocus={false}
        side='top'
        align='start'
        className='w-80 max-w-[calc(100vw-2rem)] gap-0 p-1'
      >
        {rows}
      </PopoverContent>
    </Popover>
  );
}
