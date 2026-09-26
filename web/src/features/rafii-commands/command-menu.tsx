'use client';

/**
 * The `/` command menu (docs/design/rafii-live-agent/CONTRACTS.md, Contract 7), shared by Rafii's panel and the Home
 * and conversation composers.
 *
 * Wiring, in the composer that owns the text:
 *
 *   <SlashCommandMenu value={text} caret={caret} anchorRef={composerRef} onPick={onPick} onDismiss={() => {}} />
 *
 * - `caret` is the input's `selectionStart`, updated in its onChange and onSelect.
 * - `anchorRef` is the composer box or the input itself; the menu sits just above it and keeps focus in the input.
 * - While open, the menu answers ↑↓, Enter/Tab and Esc on the input itself, so the input's own Enter-to-send handler
 *   never sees those presses, and it sets the combobox attributes on the input.
 * - `onPick(command, args, pick)`: set the text to `pick.value` and the caret to `pick.caret`. When `pick.action` is
 *   `'run'`, also `await command.execute(args)` and show the sentence it returns (client commands never reach Rafii).
 * - A whole `/command …` message sent without the menu: `parseSlash` on send, then `execute` for a client command or
 *   `commandPayload` next to the text for an agent command.
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { Surface } from '@/components/rafii/surface';
import { COMMANDS, type SlashCommand } from '@/lib/agent-runtime/commands';
import { cn } from '@/lib/utils';
import { applyPick, groupCommands, isImeEvent, slashMenuState, slashToken, stillDismissed, type SlashDismissal, type SlashMenuState, type SlashPick } from './menu-logic';

export { applyPick, filterCommands, groupCommands, isImeEvent, slashMenuState, slashToken } from './menu-logic';
export type { SlashDismissal, SlashMenuState, SlashPick, SlashRange, SlashToken } from './menu-logic';

export interface SlashCommandMenuProps {
  value: string;
  caret: number;
  anchorRef: RefObject<HTMLElement | null>;
  /** The person chose a command: `pick` says what the text becomes and whether the command runs now. */
  onPick: (command: SlashCommand, args: string, pick: SlashPick) => void;
  /** The person closed the menu with Esc; it stays closed while they keep typing the same word. */
  onDismiss: () => void;
  /** The composer's own IME state, when it tracks one; the menu also listens for composition on the input. */
  isComposing?: boolean;
  /** A narrower list for a composer that can't run every command; every command by default. */
  commands?: SlashCommand[];
}

/** Space between the menu and the anchor, and kept clear above the menu (px). */
const GAP = 6;
const EDGE = 8;
const MIN_HEIGHT = 144;
const MAX_HEIGHT = 352;

/**
 * Whether the menu is open for this text and caret, what follows the slash, and the `/word`'s range, plus `dismiss`
 * (Esc). The menu uses it itself; a composer can call it to know the same things.
 */
export function useSlashMenu({ value, caret, isComposing = false, commands = COMMANDS }: { value: string; caret: number; isComposing?: boolean; commands?: SlashCommand[] }): SlashMenuState & { dismiss: () => void } {
  const [dismissed, setDismissed] = useState<SlashDismissal | null>(null);
  const token = slashToken(value, caret);
  const holds = stillDismissed(token, dismissed);
  // Erasing the word, or starting another one, ends an Esc.
  if (dismissed && !holds) setDismissed(null);
  const start = token?.start;
  const query = token?.query;
  const dismiss = useCallback(() => {
    if (start !== undefined && query !== undefined) setDismissed({ start, query });
  }, [start, query]);
  return { ...slashMenuState(value, caret, { isComposing, dismissed: holds ? dismissed : null, commands }), dismiss };
}

export function SlashCommandMenu({ value, caret, anchorRef, onPick, onDismiss, isComposing = false, commands }: SlashCommandMenuProps) {
  const listId = useId();
  const input = useAnchorField(anchorRef, value);
  const { composing, focused } = useFieldState(input);
  const menu = useSlashMenu({ value, caret, isComposing: isComposing || composing, commands });
  // Clicking elsewhere hides the menu; coming back to the input shows it again.
  const open = menu.open && (input ? focused : true);
  const rows = menu.commands;

  const [active, setActive] = useState(0);
  const [activeFor, setActiveFor] = useState(menu.query);
  if (activeFor !== menu.query) {
    setActiveFor(menu.query);
    setActive(0);
  }
  const current = Math.min(active, Math.max(0, rows.length - 1));

  const box = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const place = usePlacement(open, anchorRef, box, value);

  function pick(index: number) {
    const command = rows[index];
    if (!command || !menu.range) return;
    const result = applyPick(value, menu.range, command);
    onPick(command, result.args, result);
    // Once the composer has applied the new text, the caret goes where the pick left it.
    const field = input;
    requestAnimationFrame(() => {
      if (!(field instanceof HTMLTextAreaElement || field instanceof HTMLInputElement) || field.value !== result.value) return;
      field.focus({ preventScroll: true });
      field.setSelectionRange(result.caret, result.caret);
    });
  }

  function close() {
    menu.dismiss();
    onDismiss();
  }

  // The key listener is attached once per input and reads the latest rows through this ref.
  const latest = useRef<{ open: boolean; count: number; current: number; pick: (index: number) => void; close: () => void } | null>(null);
  useLayoutEffect(() => {
    latest.current = { open, count: rows.length, current, pick, close };
  });

  useEffect(() => {
    if (!input) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const now = latest.current;
      if (!now?.open || !now.count || isImeEvent(event) || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') setActive((now.current + (event.key === 'ArrowDown' ? 1 : -1) + now.count) % now.count);
      else if (event.key === 'Enter' || event.key === 'Tab') now.pick(now.current);
      else if (event.key === 'Escape') now.close();
      else return;
      // Handled here: the input's own handlers (Enter to send, Esc to close the panel) don't see this press.
      event.preventDefault();
      event.stopPropagation();
    };
    input.addEventListener('keydown', onKeyDown);
    return () => input.removeEventListener('keydown', onKeyDown);
  }, [input]);

  // The input drives the listbox (focus never leaves it): combobox attributes while the menu is open.
  useEffect(() => {
    if (!input || !open) return;
    return setAttributes(input, {
      'aria-controls': listId,
      'aria-autocomplete': 'list',
      'aria-activedescendant': rows.length ? `${listId}-option-${current}` : null,
      // A textarea keeps its textbox role; a one-line input becomes the combobox itself.
      ...(input instanceof HTMLInputElement ? { role: 'combobox', 'aria-expanded': 'true' } : {})
    });
  }, [input, open, listId, current, rows.length]);

  // Keep the active row in view (its group's heading too, when it is the group's first row).
  useEffect(() => {
    const scroller = list.current;
    if (!open || !scroller) return;
    if (current === 0) {
      scroller.scrollTop = 0;
      return;
    }
    const item = scroller.querySelector<HTMLElement>(`[data-index="${current}"]`);
    if (!item) return;
    const top = item.previousElementSibling?.tagName === 'P' && item.parentElement ? item.parentElement.offsetTop : item.offsetTop;
    if (top < scroller.scrollTop) scroller.scrollTop = top;
    else if (item.offsetTop + item.offsetHeight > scroller.scrollTop + scroller.clientHeight) scroller.scrollTop = item.offsetTop + item.offsetHeight - scroller.clientHeight;
  }, [open, current, rows.length]);

  if (!open) return null;
  let index = -1;
  return (
    <div
      ref={box}
      data-slot='slash-command-menu'
      className='z-30'
      style={{ position: 'absolute', ...(place ? { left: place.left, top: place.top, width: place.width, transform: 'translateY(-100%)' } : { left: 0, right: 0, bottom: `calc(100% + ${GAP}px)` }) }}
    >
      <Surface material='elevated' radius='control' padding='none' className='overflow-hidden'>
        <div ref={list} id={listId} role='listbox' aria-label='Commands' className='overflow-y-auto overscroll-contain p-1.5' style={{ position: 'relative', maxHeight: place?.maxHeight ?? MAX_HEIGHT }}>
          {groupCommands(rows).map((group) => (
            <div key={group.id} role='group' aria-labelledby={`${listId}-${group.id}`}>
              <p id={`${listId}-${group.id}`} className='text-muted-foreground px-2 pt-2 pb-1 text-[11px] font-medium tracking-wide uppercase'>
                {group.label}
              </p>
              {group.commands.map((command) => {
                index += 1;
                const position = index;
                const selected = position === current;
                return (
                  <div
                    key={command.name}
                    id={`${listId}-option-${position}`}
                    role='option'
                    aria-selected={selected}
                    data-index={position}
                    tabIndex={-1}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseMove={() => {
                      if (!selected) setActive(position);
                    }}
                    onClick={() => pick(position)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') pick(position);
                    }}
                    className={cn('flex min-h-10 cursor-pointer flex-col justify-center gap-0.5 rounded-md px-2 py-1.5 pointer-coarse:min-h-11', selected && 'bg-accent text-accent-foreground')}
                  >
                    <span className='flex min-w-0 items-baseline gap-1.5'>
                      <span className='shrink-0 text-sm font-medium'>/{command.name}</span>
                      {command.argsHint && <span className='text-muted-foreground truncate text-xs'>{command.argsHint}</span>}
                    </span>
                    <span className='text-muted-foreground text-xs leading-snug'>{command.description}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </Surface>
      <p className='sr-only' aria-live='polite'>
        {rows.length === 1 ? '1 command' : `${rows.length} commands`}
      </p>
    </div>
  );
}

const FIELD = 'textarea, input:not([type]), input[type="text"], input[type="search"], [contenteditable="true"], [contenteditable=""]';

/** The text field inside the anchor (or the anchor itself). */
function useAnchorField(anchorRef: RefObject<HTMLElement | null>, value: string): HTMLElement | null {
  const [field, setField] = useState<HTMLElement | null>(null);
  // The anchor may mount after the menu, or change: look again as the text changes (state only changes when it does).
  useEffect(() => {
    const anchor = anchorRef.current;
    const next = anchor ? (anchor.matches(FIELD) ? anchor : anchor.querySelector<HTMLElement>(FIELD)) : null;
    setField((previous) => (previous === next ? previous : next));
  }, [anchorRef, value]);
  return field;
}

/** Focus and IME composition on the field, from its own events. */
function useFieldState(field: HTMLElement | null): { composing: boolean; focused: boolean } {
  const [composing, setComposing] = useState(false);
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!field) return;
    const onFocus = () => setFocused(true);
    const onBlur = () => {
      setFocused(false);
      setComposing(false);
    };
    const onStart = () => setComposing(true);
    const onEnd = () => setComposing(false);
    setFocused(field.ownerDocument.activeElement === field);
    field.addEventListener('focus', onFocus);
    field.addEventListener('blur', onBlur);
    field.addEventListener('compositionstart', onStart);
    field.addEventListener('compositionend', onEnd);
    return () => {
      field.removeEventListener('focus', onFocus);
      field.removeEventListener('blur', onBlur);
      field.removeEventListener('compositionstart', onStart);
      field.removeEventListener('compositionend', onEnd);
    };
  }, [field]);
  return { composing, focused };
}

interface Place {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
}

/** Just above the anchor, as wide as it, wherever the menu sits in the tree; re-measured as the text grows or moves. */
function usePlacement(open: boolean, anchorRef: RefObject<HTMLElement | null>, box: RefObject<HTMLDivElement | null>, value: string): Place | null {
  const [place, setPlace] = useState<Place | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const anchor = anchorRef.current;
      const menu = box.current;
      if (!anchor || !menu) return;
      const next = placeAbove(anchor, menu);
      setPlace((prev) => (prev && prev.left === next.left && prev.top === next.top && prev.width === next.width && prev.maxHeight === next.maxHeight ? prev : next));
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (anchorRef.current) observer?.observe(anchorRef.current);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, anchorRef, box, value]);
  return place;
}

function placeAbove(anchor: HTMLElement, menu: HTMLElement): Place {
  const parent = (menu.offsetParent as HTMLElement | null) ?? menu.ownerDocument.documentElement;
  const a = anchor.getBoundingClientRect();
  const p = parent.getBoundingClientRect();
  return {
    left: Math.round(a.left - p.left - parent.clientLeft + parent.scrollLeft),
    top: Math.round(a.top - p.top - parent.clientTop + parent.scrollTop - GAP),
    width: Math.round(a.width),
    maxHeight: Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, a.top - clipTop(menu) - GAP - EDGE)))
  };
}

/** The top edge of the nearest ancestor that would cut the menu off, or the window's. */
function clipTop(menu: HTMLElement): number {
  for (let node = menu.parentElement; node && node !== menu.ownerDocument.body; node = node.parentElement) {
    if (getComputedStyle(node).overflowY !== 'visible') return Math.max(0, node.getBoundingClientRect().top);
  }
  return 0;
}

/** Set attributes on an element the composer renders; the returned function puts back what was there. */
function setAttributes(element: HTMLElement, attributes: Record<string, string | null>): () => void {
  const previous = Object.keys(attributes).map((name) => [name, element.getAttribute(name)] as const);
  const apply = (name: string, value: string | null) => (value === null ? element.removeAttribute(name) : element.setAttribute(name, value));
  for (const [name, value] of Object.entries(attributes)) apply(name, value);
  return () => {
    for (const [name, value] of previous) apply(name, value);
  };
}
