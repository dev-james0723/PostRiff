'use client';

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MutableRefObject } from 'react';
import { IconCheck, IconChevronDown, IconPlus, IconSearch, IconWorld, IconX } from '@tabler/icons-react';
import { LanguageName } from '@/components/application/language-picker/language-badge';
import { groupsFor, loadRecent, saveRecent } from '@/components/application/language-picker/language-picker-content';
import { ChannelIcon } from '@/components/channel-icon';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { LocaleTag } from '@/lib/api/types';
import { FLAG_FONT, glyphFontFamily, locales } from '@/lib/locales';
import { useMeasuredDisclosure, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { cleanLanguages, MAX_LANGUAGES, planLanguageOps, runLanguageOp, stateKey, type LanguageDialogApi, type LanguageOp, type LanguageSelectionItem } from './language-dialog-ops';

export type { LanguageDialogApi, LanguageSelectionItem } from './language-dialog-ops';

export interface LanguageDialogProps<P extends string = string> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The composer's selected destinations (`useChannelLanguages().selection`). */
  selection: readonly LanguageSelectionItem<P>[];
  /** The hook itself (`useChannelLanguages(...)`): read through `languagesOf`, committed through `change/add/remove/useEverywhere`. */
  languages: LanguageDialogApi<P>;
  /** "Instagram · @studio" or "LinkedIn": how a destination is named in the dialog. */
  accountLabel: (item: LanguageSelectionItem<P>) => string;
  /** Which destination the "Output language for …" block edits first; defaults to the first selected. */
  initialKey?: string;
  /** Optional element id for the popup (for a trigger's `aria-controls`). */
  id?: string;
}

/**
 * Output-language dialog (Rafii v9 brief C; DNA v8 §16.3, §11.3, §10.6, §18.4). Everything inside
 * is staged: the target block edits one destination's language, the list shows every destination's
 * languages (several per destination, plus one to add), and the shared box is an override that
 * extends the same glass surface. "Apply languages" commits through the hook; Cancel, close and
 * Escape leave the applied configuration untouched. Only `language_settings` is written: existing
 * drafts are never translated or regenerated from here.
 */
export function LanguageDialog<P extends string = string>({ open, onOpenChange, selection, languages, accountLabel, initialKey, id }: LanguageDialogProps<P>) {
  const escapeRef = useRef<(() => boolean) | null>(null);
  const [queue, setQueue] = useState<LanguageOp<P>[]>([]);
  const closeWhenDrained = useRef(false);
  const applying = queue.length > 0;
  const generation = useOpenGeneration(open);

  /* One hook call per render: each `change/add/remove` computes from the hook's latest state. */
  useEffect(() => {
    if (!queue.length) {
      if (closeWhenDrained.current) {
        closeWhenDrained.current = false;
        onOpenChange(false);
      }
      return;
    }
    const [op, ...rest] = queue;
    runLanguageOp(languages, op);
    setQueue(rest);
  }, [queue, languages, onOpenChange]);

  return (
    <RafiiDialog
      open={open}
      onOpenChange={(next, details) => {
        if (next) {
          onOpenChange(true);
          return;
        }
        if (details.reason === 'escape-key' && escapeRef.current?.()) {
          details.cancel();
          return;
        }
        if (applying) {
          details.cancel();
          return;
        }
        onOpenChange(false);
      }}
    >
      <RafiiDialogContent size='md' id={id}>
        <RafiiDialogHeader eyebrow='Output language' title='Every audience.' accent='The right language.' closeLabel='Close language settings' />
        <LanguageStage
          key={generation}
          selection={selection}
          languages={languages}
          accountLabel={accountLabel}
          initialKey={initialKey}
          applying={applying}
          escapeRef={escapeRef}
          onCancel={() => onOpenChange(false)}
          onApply={(ops) => {
            if (!ops.length) {
              onOpenChange(false);
              return;
            }
            closeWhenDrained.current = true;
            setQueue(ops);
          }}
        />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/**
 * Counts openings so a staged editor can be keyed on it: every open starts from the applied
 * configuration even when the previous popup is still finishing its exit transition.
 */
export function useOpenGeneration(open: boolean) {
  const [generation, setGeneration] = useState(0);
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setGeneration((current) => current + 1);
  }
  return generation;
}

interface StageProps<P extends string> {
  selection: readonly LanguageSelectionItem<P>[];
  languages: LanguageDialogApi<P>;
  accountLabel: (item: LanguageSelectionItem<P>) => string;
  initialKey?: string;
  applying: boolean;
  escapeRef: MutableRefObject<(() => boolean) | null>;
  onApply: (ops: LanguageOp<P>[]) => void;
  onCancel: () => void;
}

type Slot = 'target' | 'shared';

function LanguageStage<P extends string>({ selection, languages, accountLabel, initialKey, applying, escapeRef, onApply, onCancel }: StageProps<P>) {
  const ids = useId();
  const { reduced } = useMotionPreference();
  const items = selection;
  const [staged, setStaged] = useState<Record<string, LocaleTag[]>>(() => Object.fromEntries(items.map((item) => [stateKey(item), cleanLanguages(languages.languagesOf(item))])));
  const [target, setTarget] = useState<{ key: string; index: number; adding: boolean }>(() => ({
    key: initialKey && items.some((item) => stateKey(item) === initialKey) ? initialKey : items[0] ? stateKey(items[0]) : '',
    index: 0,
    adding: false
  }));
  const [shared, setShared] = useState(false);
  const [sharedTag, setSharedTag] = useState<LocaleTag | null>(null);
  const [catalogue, setCatalogue] = useState<{ slot: Slot; open: boolean }>({ slot: 'target', open: false });

  const targetItem = items.find((item) => stateKey(item) === target.key) ?? items[0];
  const targetList = targetItem ? (staged[stateKey(targetItem)] ?? []) : [];
  const targetTag: LocaleTag | null = target.adding ? null : (targetList[target.index] ?? targetList[0] ?? null);
  const targetLabel = targetItem ? accountLabel(targetItem) : '';

  const targetButton = useRef<HTMLButtonElement>(null);
  const sharedButton = useRef<HTMLButtonElement>(null);
  const individualRef = useMeasuredDisclosure<HTMLElement>(!shared);
  const sharedRef = useMeasuredDisclosure<HTMLDivElement>(shared);
  const targetSlotRef = useMeasuredDisclosure<HTMLDivElement>(catalogue.slot === 'target' && catalogue.open);
  const sharedSlotRef = useMeasuredDisclosure<HTMLDivElement>(catalogue.slot === 'shared' && catalogue.open);

  useEffect(() => {
    escapeRef.current = catalogue.open
      ? () => {
          closeCatalogue();
          return true;
        }
      : null;
    return () => {
      escapeRef.current = null;
    };
  });

  function focusOwner(slot: Slot) {
    (slot === 'shared' ? sharedButton : targetButton).current?.focus({ preventScroll: true });
  }
  function openCatalogue(slot: Slot) {
    setCatalogue({ slot, open: true });
  }
  function closeCatalogue() {
    setCatalogue((current) => ({ ...current, open: false }));
    if (target.adding) setTarget((current) => ({ ...current, index: 0, adding: false }));
    focusOwner(catalogue.slot);
  }
  function editSlot(key: string, index: number) {
    setTarget({ key, index, adding: false });
    openCatalogue('target');
    targetButton.current?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
  }
  function addSlot(key: string) {
    setTarget({ key, index: (staged[key] ?? []).length, adding: true });
    openCatalogue('target');
    targetButton.current?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
  }
  function removeSlot(key: string, index: number) {
    setStaged((current) => {
      const list = current[key] ?? [];
      if (list.length <= 1) return current;
      return { ...current, [key]: list.filter((_, i) => i !== index) };
    });
    if (target.key === key && target.index >= index) setTarget({ key, index: Math.max(0, target.index - 1), adding: false });
  }
  function toggleShared() {
    const next = !shared;
    setShared(next);
    setSharedTag(null);
    setCatalogue((current) => ({ ...current, open: false }));
    if (target.adding) setTarget((current) => ({ ...current, index: 0, adding: false }));
  }
  function pick(tag: LocaleTag) {
    saveRecent(tag);
    if (catalogue.slot === 'shared') {
      setSharedTag(tag);
      setCatalogue({ slot: 'shared', open: false });
      focusOwner('shared');
      return;
    }
    const key = target.key;
    const list = staged[key] ?? [];
    const next = cleanLanguages(target.adding ? [...list, tag] : list.map((current, i) => (i === target.index ? tag : current)));
    setStaged((current) => ({ ...current, [key]: next }));
    setTarget({ key, index: Math.max(0, next.indexOf(tag)), adding: false });
    setCatalogue({ slot: 'target', open: false });
    focusOwner('target');
  }

  const suggestions = useMemo(() => {
    const platform = targetItem?.platform;
    const remembered = platform ? (languages.settings?.channels[platform] ?? []) : [];
    const usual = platform ? locales.usualFor(platform) : null;
    const list = [
      ...(catalogue.slot === 'target' ? remembered.map((tag) => ({ tag, reason: 'Last used here' })) : []),
      ...(catalogue.slot === 'target' && usual ? [{ tag: usual, reason: `Usual for ${platform}` }] : []),
      ...(languages.suggestions ?? [])
    ];
    return list.filter((item, i) => list.findIndex((other) => other.tag === item.tag) === i);
  }, [targetItem?.platform, languages.settings, languages.suggestions, catalogue.slot]);

  const catalogueId = `${ids}-catalogue`;
  const canApply = !applying && items.length > 0 && (!shared || Boolean(sharedTag));
  const hint = shared ? (sharedTag ? 'Applies to every channel.' : 'Choose a language below.') : 'Each channel keeps its own.';
  const modeLabel = shared ? (sharedTag ? 'Shared language' : 'Choose a shared language') : 'Individual languages';

  function apply() {
    onApply(planLanguageOps(items, (item) => languages.languagesOf(item), staged, shared ? sharedTag : null));
  }

  const catalogueNode = (slot: Slot) => (
    <LocaleCatalogue
      id={catalogueId}
      open={catalogue.slot === slot && catalogue.open}
      selected={slot === 'shared' ? (sharedTag ? [sharedTag] : []) : targetTag ? [targetTag] : []}
      suggestions={suggestions}
      onPick={pick}
      onClose={closeCatalogue}
    />
  );

  return (
    <>
      <RafiiDialogBody>
        {items.length === 0 ? (
          <StateMessage kind='empty' title='Choose a channel first' />
        ) : (
          <>
            <section ref={individualRef} aria-labelledby={`${ids}-target-label`} className='-mx-1 px-1'>
              <div className='pt-1 pb-1'>
                <p id={`${ids}-target-label`} className='text-foreground mb-2.5 text-sm font-medium'>
                  {target.adding ? `Add a language for ${targetLabel}` : `Output language for ${targetLabel}`}
                  {!target.adding && targetList.length > 1 && <span className='text-muted-foreground font-normal'> · {Math.min(target.index, targetList.length - 1) + 1} of {targetList.length}</span>}
                </p>
                <button
                  ref={targetButton}
                  type='button'
                  aria-expanded={catalogue.slot === 'target' && catalogue.open}
                  aria-controls={catalogueId}
                  onClick={() => (catalogue.slot === 'target' && catalogue.open ? closeCatalogue() : openCatalogue('target'))}
                  className={targetButtonClass}
                >
                  {targetTag ? <LocaleButtonContent tag={targetTag} /> : <PlaceholderContent label='Choose a language…' />}
                  <Chevron open={catalogue.slot === 'target' && catalogue.open} reduced={reduced} />
                </button>
                <div ref={targetSlotRef}>{catalogue.slot === 'target' && catalogueNode('target')}</div>
              </div>
            </section>

            <section aria-labelledby={`${ids}-shared-label`} className={cn('mt-4 overflow-hidden rounded-[var(--rafii-radius-card)] transition-[background] duration-[400ms] ease-[var(--rafii-ease-soft)]', shared ? 'rafii-glass-selected' : 'rafii-glass')}>
              <div className='flex min-h-[4.75rem] items-center gap-3.5 px-4 py-4'>
                <div className='min-w-0 flex-1'>
                  <p id={`${ids}-shared-label`} className='text-foreground text-sm font-medium'>
                    All channels use the same language
                  </p>
                  <p className='text-muted-foreground mt-0.5 text-xs leading-relaxed'>{hint}</p>
                </div>
                <button
                  type='button'
                  role='switch'
                  aria-checked={shared}
                  aria-labelledby={`${ids}-shared-label`}
                  aria-expanded={shared}
                  aria-controls={`${ids}-shared-content`}
                  onClick={toggleShared}
                  className='rafii-focus flex min-h-11 min-w-12 shrink-0 items-center justify-center rounded-full'
                >
                  <span aria-hidden className={cn('relative block h-7 w-12 rounded-full transition-colors duration-200', shared ? 'bg-foreground' : 'bg-foreground/20')}>
                    <span className={cn('bg-background absolute top-1 left-1 block size-5 rounded-full shadow-sm', !reduced && 'transition-transform duration-200 ease-[var(--rafii-ease-ui)]', shared && 'translate-x-5')} />
                  </span>
                </button>
              </div>
              <div ref={sharedRef} id={`${ids}-shared-content`}>
                <div className='px-4 pb-4'>
                  <h3 className='text-foreground mb-3 text-sm font-medium'>Select a language for every channel</h3>
                  <button
                    ref={sharedButton}
                    type='button'
                    aria-expanded={catalogue.slot === 'shared' && catalogue.open}
                    aria-controls={catalogueId}
                    onClick={() => (catalogue.slot === 'shared' && catalogue.open ? closeCatalogue() : openCatalogue('shared'))}
                    className={cn(targetButtonClass, 'rafii-quiet min-h-[3.375rem] shadow-none')}
                  >
                    {sharedTag ? <LocaleButtonContent tag={sharedTag} /> : <PlaceholderContent label='Choose a shared language…' />}
                    <Chevron open={catalogue.slot === 'shared' && catalogue.open} reduced={reduced} />
                  </button>
                  <div ref={sharedSlotRef}>{catalogue.slot === 'shared' && catalogueNode('shared')}</div>
                </div>
              </div>
            </section>

            <div className='mt-5 mb-2 flex items-center justify-between gap-3'>
              <span className='rafii-eyebrow'>Channel outputs</span>
              <span className='text-muted-foreground text-xs'>{modeLabel}</span>
            </div>
            <ul className='flex flex-col gap-1.5'>
              {items.map((item) => {
                const key = stateKey(item);
                const own = staged[key] ?? [];
                const list = shared && sharedTag ? [sharedTag] : own;
                const label = accountLabel(item);
                return (
                  <li key={key} className='rafii-quiet flex min-h-[3.125rem] flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-[1rem] px-2.5 py-1.5'>
                    <ChannelIcon platform={item.platform} size='sm' />
                    <span className='text-foreground min-w-[7.5rem] flex-1 text-sm font-medium break-words'>{label}</span>
                    <span className='flex flex-wrap items-center gap-1.5'>
                      {list.map((tag, index) => {
                        const entry = locales.entry(tag);
                        const pressed = !shared && target.key === key && target.index === index && !target.adding;
                        return (
                          <span key={`${tag}-${index}`} className='flex items-center'>
                            <button
                              type='button'
                              aria-pressed={pressed}
                              disabled={shared}
                              aria-label={`Output language for ${label}${list.length > 1 ? ` ${index + 1} of ${list.length}` : ''}: ${entry?.english ?? tag}. Change`}
                              onClick={() => editSlot(key, index)}
                              className={cn('rafii-focus flex min-h-11 max-w-56 items-center gap-1.5 rounded-[var(--rafii-radius-control)] px-2.5 text-xs transition-colors duration-200', pressed ? 'rafii-glass-selected' : 'rafii-glass hover:rafii-glass-selected', shared && 'opacity-70')}
                            >
                              <LanguageName language={tag} className='max-w-[15ch]' />
                              <IconChevronDown aria-hidden className='text-muted-foreground size-3.5 shrink-0' />
                            </button>
                            {!shared && own.length > 1 && (
                              <button type='button' aria-label={`Remove ${entry?.english ?? tag} from ${label}`} onClick={() => removeSlot(key, index)} className='rafii-focus text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-full'>
                                <IconX aria-hidden className='size-3.5' />
                              </button>
                            )}
                          </span>
                        );
                      })}
                      {!shared && own.length < MAX_LANGUAGES && (
                        <button type='button' aria-label={`Add another language for ${label}`} title='Add another language' onClick={() => addSlot(key)} className='rafii-focus rafii-glass hover:rafii-glass-selected text-muted-foreground hover:text-foreground flex size-11 items-center justify-center rounded-[var(--rafii-radius-control)]'>
                          <IconPlus aria-hidden className='size-4' />
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className='text-muted-foreground mt-4 text-xs leading-relaxed'>Applies to new drafts only.</p>
          </>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <div className='flex flex-col-reverse gap-2 sm:flex-row sm:justify-end'>
          <Button variant='quiet' size='control' disabled={applying} onClick={onCancel}>
            Cancel
          </Button>
          <Button variant='action' size='control' disabled={!canApply} aria-busy={applying || undefined} onClick={apply}>
            {applying ? 'Applying…' : 'Apply languages'} <IconCheck aria-hidden />
          </Button>
        </div>
      </RafiiDialogFooter>
    </>
  );
}

const targetButtonClass = 'rafii-glass hover:rafii-glass-selected aria-expanded:rafii-glass-selected rafii-focus flex min-h-[3.8125rem] w-full items-center gap-3 rounded-[1rem] px-4 py-3 text-left transition-colors duration-200';

function Chevron({ open, reduced }: { open: boolean; reduced: boolean }) {
  return <IconChevronDown aria-hidden className={cn('text-muted-foreground ml-auto size-4 shrink-0', !reduced && 'transition-transform duration-[400ms] ease-[var(--rafii-ease-soft)]', open && 'rotate-180')} />;
}

function LocaleButtonContent({ tag }: { tag: LocaleTag }) {
  const entry = locales.entry(tag);
  if (!entry) return <span className='text-foreground text-sm font-medium'>{tag}</span>;
  return (
    <>
      <span aria-hidden className='w-7 shrink-0 text-center text-2xl leading-none' style={{ fontFamily: FLAG_FONT }}>
        {entry.flag}
      </span>
      <span className='flex min-w-0 flex-1 flex-col gap-0.5'>
        <strong lang={entry.tag} dir={entry.dir} className='text-foreground text-sm font-medium [overflow-wrap:anywhere]' style={{ fontFamily: glyphFontFamily(entry.glyphs) }}>
          {entry.native}
        </strong>
        <small className='text-muted-foreground text-xs'>{entry.english}</small>
      </span>
    </>
  );
}

function PlaceholderContent({ label }: { label: string }) {
  return (
    <>
      <IconWorld aria-hidden className='text-muted-foreground size-5 shrink-0' />
      <span className='text-foreground text-sm'>{label}</span>
    </>
  );
}

/**
 * The full catalogue, inline (a measured disclosure owns its height): the production locale
 * search with flags, native names, aliases, regionless and Tuned marks, keyboard navigation and
 * a did-you-mean fallback. Search text and the active row stay put while the list updates.
 */
function LocaleCatalogue({ id, open, selected, suggestions, onPick, onClose }: { id: string; open: boolean; selected: LocaleTag[]; suggestions: { tag: LocaleTag; reason: string }[]; onPick: (tag: LocaleTag) => void; onClose: () => void }) {
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
    if (!open) return;
    setQuery('');
    setActive(0);
    if (window.innerWidth > 760) input.current?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    listbox.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  function search(next: string) {
    setQuery(next);
    setActive(0);
    if (listbox.current) listbox.current.scrollTop = 0;
  }
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const moves: Record<string, number> = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 };
    if (event.key in moves && rows.length) {
      event.preventDefault();
      setActive((current) => Math.min(rows.length - 1, Math.max(0, current + moves[event.key])));
    } else if (event.key === 'Enter' && rows[active]) {
      event.preventDefault();
      onPick(rows[active].entry.tag);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  }

  let index = -1;
  return (
    <div id={id} className='rafii-quiet mt-3 flex flex-col overflow-hidden rounded-[1rem]'>
      <div className='rafii-field flex min-h-12 items-center gap-2.5 px-3.5'>
        <IconSearch aria-hidden className='text-muted-foreground size-[18px] shrink-0' />
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
          aria-label='Search languages or regions'
          placeholder='Search languages or regions'
          autoComplete='off'
          spellCheck={false}
          className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm'
        />
        {query && (
          <button type='button' aria-label='Clear language search' onClick={() => search('')} className='rafii-focus text-muted-foreground hover:text-foreground flex size-9 shrink-0 items-center justify-center rounded-full'>
            <IconX aria-hidden className='size-4' />
          </button>
        )}
      </div>
      <div ref={listbox} id={`${id}-list`} role='listbox' aria-label='Languages' className='max-h-[17rem] overflow-y-auto overscroll-contain px-1.5 pb-1.5'>
        {rows.length === 0 && query.trim() ? (
          <div className='text-muted-foreground flex flex-col items-center gap-2 px-4 py-7 text-center text-sm'>
            <span className='[overflow-wrap:anywhere]'>
              No language matches <span className='text-foreground font-medium'>“{query.trim()}”</span>.
            </span>
            {guess ? (
              <button type='button' onClick={() => search(guess)} className='rafii-glass hover:rafii-glass-selected rafii-focus text-foreground min-h-11 rounded-full px-4'>
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
                <p id={`${id}-g-${group.id}`} className='rafii-eyebrow px-2 pt-3 pb-1'>
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
                    className={cn('flex min-h-11 cursor-pointer items-center gap-2.5 rounded-[var(--rafii-radius-control)] px-2 py-1.5', position === active && 'rafii-glass-selected')}
                  >
                    <span aria-hidden className='w-7 shrink-0 text-center text-xl leading-none' style={{ fontFamily: FLAG_FONT }}>
                      {entry.flag}
                    </span>
                    <span className='flex min-w-0 flex-1 flex-col'>
                      <span lang={entry.tag} dir={entry.dir} className='text-foreground text-sm font-medium [overflow-wrap:anywhere]' style={{ fontFamily: glyphFontFamily(entry.glyphs) }}>
                        {entry.native}
                      </span>
                      {subtitle && <span className='text-muted-foreground text-xs'>{subtitle}</span>}
                    </span>
                    {row.reason && <span className='text-muted-foreground shrink-0 text-[11px]'>{row.reason}</span>}
                    {entry.reviewed && <span className='rafii-quiet text-muted-foreground shrink-0 rounded-full px-1.5 py-0.5 text-[11px]'>Tuned</span>}
                    {entry.regionless && <span className='rafii-quiet text-muted-foreground shrink-0 rounded-full px-1.5 py-0.5 text-[11px]'>No region</span>}
                    <span className='w-4 shrink-0'>{isChosen && <IconCheck aria-hidden className='size-4' />}</span>
                    {isChosen && <span className='sr-only'>, current language</span>}
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
      <p role='status' aria-live='polite' className='text-muted-foreground px-3.5 py-2 text-[11px]'>
        {query.trim() ? `${rows.length} matching ${rows.length === 1 ? 'choice' : 'choices'}${guess ? ` · Did you mean ${guess}?` : ''}` : `${locales.entries.length} language and regional choices`}
      </p>
    </div>
  );
}

