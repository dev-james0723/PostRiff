'use client';

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Icons } from '@/components/icons';
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from '@/components/ui/drawer';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useMediaQuery } from '@/hooks/use-media-query';
import { FLAG_FONT, glyphFontFamily, locales, type LocaleEntry } from '@/lib/locales';
import { cn } from '@/lib/utils';

import type { LanguagePickerProps, PickerAction } from './language-picker';

interface Row {
  entry: LocaleEntry;
  reason?: string;
  alias?: string | null;
}

const RECENT_KEY = 'postriff.language-picker.recent';

export function loadRecent(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]');
    return Array.isArray(value) ? value.filter((tag) => typeof tag === 'string' && locales.entry(tag)).slice(0, 3) : [];
  } catch {
    return [];
  }
}

export function saveRecent(tag: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([tag, ...loadRecent().filter((t) => t !== tag)].slice(0, 3)));
  } catch {
    /* private window: recents are a convenience */
  }
}

export function groupsFor(query: string, suggestions: { tag: string; reason: string }[], recent: string[]) {
  if (query.trim()) {
    return [{ id: 'results', label: null as string | null, native: '', rows: locales.search(query).map((r): Row => ({ entry: r.entry, alias: r.alias })) }];
  }
  const groups: { id: string; label: string | null; native: string; rows: Row[] }[] = [];
  const suggested = suggestions.flatMap((s): Row[] => {
    const entry = locales.entry(s.tag);
    return entry ? [{ entry, reason: s.reason }] : [];
  });
  if (suggested.length) groups.push({ id: 'suggested', label: 'Suggested', native: '', rows: suggested });
  const recentRows = recent.flatMap((tag): Row[] => {
    const entry = locales.entry(tag);
    return entry ? [{ entry }] : [];
  });
  if (recentRows.length) groups.push({ id: 'recent', label: 'Recent', native: '', rows: recentRows });
  for (const family of locales.catalogue.families) {
    const rows = locales.entries
      .filter((e) => e.family === family.id)
      .toSorted((a, b) => Number(a.regionless) - Number(b.regionless) || Number(Boolean(b.guide)) - Number(Boolean(a.guide)))
      .map((entry): Row => ({ entry }));
    if (rows.length) groups.push({ id: family.id, label: family.label, native: family.native, rows });
  }
  return groups;
}

/**
 * Search-first language list (languages plan §4.1, §7.1): a popover on desktop, a bottom sheet below 768px.
 * Rows lead with the flag and the language's own name; the input drives the listbox with aria-activedescendant.
 */
export function LanguagePicker({ trigger, title, selected, onPick, suggestions = [], actions = [], disabled, defaultOpen = false }: LanguagePickerProps & { defaultOpen?: boolean }) {
  const { isOpen: phone } = useMediaQuery();
  const [open, setOpen] = useState(defaultOpen);

  function pick(tag: string) {
    saveRecent(tag);
    setOpen(false);
    onPick(tag);
  }

  const closing = actions.map((action) => ({
    ...action,
    onClick: () => {
      setOpen(false);
      action.onClick();
    }
  }));
  const list = open ? <LanguageList title={title} selected={selected} suggestions={suggestions} actions={closing} onPick={pick} onClose={() => setOpen(false)} phone={phone} /> : null;

  if (phone) {
    return (
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerTrigger disabled={disabled} render={trigger} />
        <DrawerContent className='[--drawer-height:85dvh]'>{list}</DrawerContent>
      </Drawer>
    );
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger disabled={disabled} render={trigger} />
      <PopoverContent align='start' className='max-h-[min(30rem,70vh)] w-[min(22.5rem,calc(100vw-2rem))] gap-0 overflow-hidden p-0'>
        {list}
      </PopoverContent>
    </Popover>
  );
}

function LanguageList({
  title,
  selected,
  suggestions,
  actions,
  onPick,
  onClose,
  phone
}: {
  title: string;
  selected: string[];
  suggestions: { tag: string; reason: string }[];
  actions: PickerAction[];
  onPick: (tag: string) => void;
  onClose: () => void;
  phone: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const listbox = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const recent = useMemo(() => loadRecent(), []);
  const groups = useMemo(() => groupsFor(query, suggestions, recent), [query, suggestions, recent]);
  const rows = useMemo(() => groups.flatMap((group) => group.rows), [groups]);
  const chosen = useMemo(() => new Set(selected.map((tag) => locales.canonical(tag) ?? tag)), [selected]);
  const guess = query.trim() && rows.length === 0 ? locales.didYouMean(query) : null;

  useEffect(() => {
    input.current?.focus({ preventScroll: true });
  }, []);
  useEffect(() => {
    listbox.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  function search(next: string) {
    setQuery(next);
    setActive(0);
    if (listbox.current) listbox.current.scrollTop = 0;
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const count = rows.length;
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 };
    if (event.key in moves && count) {
      event.preventDefault();
      setActive((current) => Math.min(count - 1, Math.max(0, current + moves[event.key])));
    } else if (event.key === 'Enter' && rows[active]) {
      event.preventDefault();
      onPick(rows[active].entry.tag);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  }

  let index = -1;
  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', phone ? 'h-full' : 'max-h-[min(30rem,70vh)]')}>
      {phone ? (
        <DrawerTitle className='px-4 pt-4 pb-1 text-base font-semibold'>{title}</DrawerTitle>
      ) : (
        <p className='text-foreground px-3 pt-2.5 text-xs font-medium'>{title}</p>
      )}
      <div className={cn('flex items-center gap-2', phone ? 'bg-muted mx-3 my-2 rounded-lg px-3 py-2.5' : 'border-b px-3 py-2')}>
        <Icons.search className='text-muted-foreground size-4 shrink-0' />
        <input
          ref={input}
          value={query}
          onChange={(event) => search(event.target.value)}
          onKeyDown={onKeyDown}
          /* eslint-disable-next-line jsx-a11y/no-redundant-roles -- assistive tech reads a text input as a textbox; the listbox pattern needs combobox */
          role='combobox'
          aria-expanded='true'
          aria-controls={`${id}-list`}
          aria-autocomplete='list'
          aria-activedescendant={rows[active] ? `${id}-${active}` : undefined}
          aria-label='Search languages'
          placeholder='Search languages or regions'
          autoComplete='off'
          spellCheck={false}
          className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-sm outline-none'
        />
        {query && (
          <button type='button' aria-label='Clear search' onClick={() => search('')} className='text-muted-foreground hover:text-foreground'>
            <Icons.close className='size-3.5' />
          </button>
        )}
      </div>
      <p className='sr-only' aria-live='polite'>
        {query.trim() ? (rows.length ? `${rows.length} ${rows.length === 1 ? 'result' : 'results'}` : guess ? `No results. Did you mean ${guess}?` : 'No results') : ''}
      </p>
      <div ref={listbox} id={`${id}-list`} role='listbox' aria-label='Languages' className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-1.5 pb-2'>
        {rows.length === 0 && query.trim() ? (
          <div className='text-muted-foreground flex flex-col items-center gap-2 px-4 py-8 text-center text-sm'>
            <span>
              No language matches <span className='text-foreground font-medium'>“{query.trim()}”</span>.
            </span>
            {guess ? (
              <button type='button' onClick={() => search(guess)} className='bg-card ring-foreground/10 hover:bg-muted rounded-full px-3 py-1 text-foreground ring-1'>
                Did you mean <span className='font-medium'>{guess}</span>?
              </button>
            ) : (
              <span>Try its English name, its own name, or a region.</span>
            )}
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.id} role='group' aria-labelledby={group.label ? `${id}-g-${group.id}` : undefined} aria-label={group.label ? undefined : 'Results'}>
              {group.label && (
                <p id={`${id}-g-${group.id}`} className='text-muted-foreground px-2 pt-2.5 pb-1 text-[11px] font-medium tracking-wide uppercase'>
                  {group.label}
                  {group.native && <span className='tracking-normal normal-case'> · {group.native}</span>}
                </p>
              )}
              {group.rows.map((row) => {
                index += 1;
                const position = index;
                const { entry } = row;
                const isChosen = chosen.has(entry.tag);
                const subtitle = row.alias ? `${entry.english} · “${row.alias}”` : entry.english !== entry.native ? entry.english : entry.regionless ? 'No region chosen' : '';
                return (
                  <div
                    key={`${group.id}-${entry.tag}`}
                    id={`${id}-${position}`}
                    role='option'
                    aria-selected={position === active}
                    data-index={position}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseMove={() => position !== active && setActive(position)}
                    tabIndex={-1}
                    onClick={() => onPick(entry.tag)}
                    onKeyDown={(event) => event.key === 'Enter' && onPick(entry.tag)}
                    className={cn('flex cursor-pointer items-center gap-2.5 rounded-md px-2', phone ? 'min-h-12 py-2' : 'py-1.5', position === active && 'bg-accent')}
                  >
                    <span aria-hidden className='w-6 shrink-0 text-center text-lg leading-none' style={{ fontFamily: FLAG_FONT }}>
                      {entry.flag}
                    </span>
                    <span className='flex min-w-0 flex-1 flex-col'>
                      <span lang={entry.tag} dir={entry.dir} className='truncate text-sm font-medium' style={{ fontFamily: glyphFontFamily(entry.glyphs) }}>
                        {entry.native}
                      </span>
                      {subtitle && <span className='text-muted-foreground truncate text-xs'>{subtitle}</span>}
                    </span>
                    {row.reason && <span className='text-muted-foreground shrink-0 text-[11px]'>{row.reason}</span>}
                    {entry.reviewed && <span className='text-muted-foreground shrink-0 rounded-full border px-1.5 text-[10.5px]'>Tuned</span>}
                    {entry.regionless && <span className='rafii-quiet text-muted-foreground shrink-0 rounded-full px-1.5 text-[11px]'>No region</span>}
                    <span className='w-3.5 shrink-0'>{isChosen && <Icons.check className='size-3.5' />}</span>
                    {isChosen && <span className='sr-only'>, current language</span>}
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
      {actions.length > 0 && (
        <div className={cn('flex flex-wrap justify-end gap-1.5 border-t px-3 py-2', phone && 'pb-[calc(0.5rem+env(safe-area-inset-bottom))]')}>
          {actions.map((action, i) => (
            <button
              key={i}
              type='button'
              onClick={action.onClick}
              className={cn('bg-card ring-foreground/10 hover:bg-muted inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium ring-1', phone && 'h-10 flex-1 justify-center text-sm', action.quiet && 'text-muted-foreground')}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
