'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { ActiveFilters, FilterPanel, FilterSelect, InfoTip, RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl, StateMessage, Workbar } from '@/components/rafii';
import { SemanticIllustration } from '@/components/rafii/semantic-illustration';
import { Button } from '@/components/ui/button';
import {
  ALL,
  EVIDENCE,
  PAIRINGS_BY_ID,
  PLANNING_ONLY_LABEL,
  PLATFORM_SLUGS,
  TAXONOMY_SOURCE,
  activeFilters,
  categoryOptions,
  categoryTitle,
  executionFor,
  filterItems,
  isPlanningOnly,
  itemsOf,
  pairingsFor,
  platformInfo,
  platformOptions,
  taxonomyItem,
  type Dimension,
  type Pairing,
  type TaxonomyItem
} from '@/lib/content-library';
import { RAFII_TIME, beginSwap, cancelAnimations } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

export interface ContentLibraryValue {
  editorialId: string;
  nativeId: string;
}

export interface ContentLibraryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The applied choice; staging starts from it every time the dialog opens. */
  value: ContentLibraryValue;
  /** Called once with both staged choices when "Use these choices" is pressed; close and Escape discard. */
  onApply: (value: ContentLibraryValue) => void;
  /** App platforms the composer can draft for (names such as `LinkedIn`, `Xiaohongshu`); narrows the app-fit filter. */
  platformsForFit?: string[];
}

type View = 'gallery' | 'list' | 'pairings';

const ARTWORK_KEY = 'rafii.library.artwork';
const NOTE = 'Changes this draft only. Your channels stay the same.';
const VIEWS: { value: View; label: ReactNode; ariaLabel: string }[] = [
  { value: 'gallery', ariaLabel: 'Gallery', label: <ViewLabel icon='dashboard'>Gallery</ViewLabel> },
  { value: 'list', ariaLabel: 'List', label: <ViewLabel icon='listDetails'>List</ViewLabel> },
  { value: 'pairings', ariaLabel: 'Pairings', label: <ViewLabel icon='columns'>Pairings</ViewLabel> }
];

function ViewLabel({ icon, children }: { icon: keyof typeof Icons; children: ReactNode }) {
  const Icon = Icons[icon];
  return (
    <>
      <Icon className='size-3.5' aria-hidden />
      {children}
    </>
  );
}

function readArtworkPaused(): boolean {
  try {
    return localStorage.getItem(ARTWORK_KEY) === 'paused';
  } catch {
    return false;
  }
}

function snapshotDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? iso : new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date);
}

/**
 * The Content Library (DNA v8 §3.1–3.3, §13, §14; prompt §6): WHAT (two dimension tabs) → FIND (search,
 * Filters) → VIEW (Gallery / List / Pairings) → COMMIT (the staged pair and one primary action). Filters
 * and views only change the representation; the staged pair survives them, including an item the current
 * filter hides (§13.6). Pairings stage both choices and never touch channels. Planning-only formats are
 * labelled, never coerced. Escape closes the deepest layer first: tooltip, evidence, filters, dialog.
 */
export function ContentLibraryDialog({ open, onOpenChange, value, onApply, platformsForFit }: ContentLibraryDialogProps) {
  const panelId = useId();
  const noteId = useId();
  const [tab, setTab] = useState<Dimension>('editorial');
  const [view, setView] = useState<View>('gallery');
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<Record<Dimension, string>>({ editorial: ALL, native: ALL });
  const [platform, setPlatform] = useState(ALL);
  const [staged, setStaged] = useState<ContentLibraryValue>(value);
  const [paused, setPaused] = useState(false);
  const [evidence, setEvidence] = useState<{ pairingId: string | null } | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const pendingSwap = useRef<((incoming: HTMLElement) => void) | null>(null);

  // Staging starts from the applied value on every open; the search is fresh, view and filters are remembered.
  const { editorialId: appliedEditorial, nativeId: appliedNative } = value;
  useEffect(() => {
    if (!open) return;
    setStaged({ editorialId: appliedEditorial, nativeId: appliedNative });
    setQuery('');
    setEvidence(null);
    setPaused(readArtworkPaused());
  }, [open, appliedEditorial, appliedNative]);

  const fitOptions = useMemo(() => platformOptions(platformsForFit), [platformsForFit]);
  const platformFilter = fitOptions.some((option) => option.value === platform) ? platform : ALL;
  const filters = useMemo(() => ({ query, category: category[tab], platform: platformFilter }), [query, category, tab, platformFilter]);
  const items = useMemo(() => filterItems(tab, filters), [tab, filters]);
  const total = itemsOf(tab).length;
  const counts = useMemo(() => ({ editorial: itemsOf('editorial').length, native: itemsOf('native').length }), []);
  const active = activeFilters(tab, filters);
  const selectedId = tab === 'editorial' ? staged.editorialId : staged.nativeId;
  const swapKey = `${tab}|${view}|${filters.category}|${filters.platform}`;

  /** Crossfades the collection (320ms, DNA §18.3): the outgoing layer stays inert until the incoming one settles. */
  const transition = useCallback((direction: 1 | -1, update: () => void) => {
    if (host.current) pendingSwap.current = beginSwap(host.current, direction, RAFII_TIME.view);
    update();
    if (body.current) body.current.scrollTop = 0;
  }, []);
  useLayoutEffect(() => {
    const run = pendingSwap.current;
    pendingSwap.current = null;
    const incoming = host.current?.querySelector<HTMLElement>('[data-swap-current]');
    if (run && incoming) run(incoming);
  }, [swapKey]);
  useEffect(() => {
    const element = host.current;
    return () => cancelAnimations(element);
  }, [open]);

  function changeTab(next: Dimension) {
    if (next === tab) return;
    transition(next === 'native' ? 1 : -1, () => {
      setTab(next);
      setQuery('');
    });
  }
  function changeView(next: View) {
    if (next === view) return;
    const order: View[] = ['gallery', 'list', 'pairings'];
    transition(order.indexOf(next) > order.indexOf(view) ? 1 : -1, () => setView(next));
  }
  function changeCategory(next: string) {
    if (next === category[tab]) return;
    transition(1, () => setCategory((current) => ({ ...current, [tab]: next })));
  }
  function changePlatform(next: string) {
    if (next === platformFilter) return;
    transition(1, () => setPlatform(next));
  }
  function clearFilters(includeSearch: boolean) {
    transition(-1, () => {
      setCategory((current) => ({ ...current, [tab]: ALL }));
      setPlatform(ALL);
      if (includeSearch) setQuery('');
    });
  }
  function select(id: string) {
    setStaged((current) => (tab === 'editorial' ? { ...current, editorialId: id } : { ...current, nativeId: id }));
  }
  function usePairing(pairing: Pairing) {
    setStaged({ editorialId: pairing.editorial, nativeId: pairing.native });
    toast('Pairing selected. Your channels are unchanged.');
  }
  function toggleArtwork() {
    const next = !paused;
    setPaused(next);
    try {
      if (next) localStorage.setItem(ARTWORK_KEY, 'paused');
      else localStorage.removeItem(ARTWORK_KEY);
    } catch {
      /* private mode: the choice lasts for this dialog only */
    }
  }
  function apply() {
    onApply(staged);
    onOpenChange(false);
  }

  /** Arrow keys, Home and End move between the cards of the live collection (one or two columns). */
  function onGridKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const card = (event.target as HTMLElement).closest<HTMLElement>('[data-library-item]');
    const current = host.current?.querySelector<HTMLElement>('[data-swap-current]');
    if (!card || !current) return;
    const cards = Array.from(current.querySelectorAll<HTMLElement>('[data-library-item]:not(:disabled)'));
    const index = cards.indexOf(card);
    if (index < 0) return;
    event.preventDefault();
    const columns = Math.max(1, getComputedStyle(current).gridTemplateColumns.split(' ').length);
    const steps: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns };
    const step = steps[event.key] ?? 0;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? cards.length - 1 : Math.max(0, Math.min(cards.length - 1, index + step));
    cards[next]?.focus();
  }

  const pairing = evidence?.pairingId ? PAIRINGS_BY_ID[evidence.pairingId] : null;
  const evidenceRecords = pairing ? pairing.evidence.map((id) => EVIDENCE[id]).filter(Boolean) : Object.values(EVIDENCE);

  return (
    <RafiiDialog
      open={open}
      onOpenChange={(next, details) => {
        // A child layer owns Escape and outside presses while it is open (DNA §12.5).
        if (!next && evidence && (details.reason === 'escape-key' || details.reason === 'outside-press')) {
          details.cancel();
          return;
        }
        onOpenChange(next);
      }}
    >
      <RafiiDialogContent size='lg' className='h-[calc(100dvh-1rem)] md:h-[min(58rem,94dvh)]'>
        <RafiiDialogHeader eyebrow='Content Library' title='Find your' accent='next idea.' closeLabel='Close content library'>
          <Workbar
            tabs={
              <SegmentedControl<Dimension>
                pattern='tabs'
                size='lg'
                label='Content choices'
                value={tab}
                onChange={changeTab}
                panelIds={[panelId, panelId]}
                className='[&>button]:min-h-[3.625rem] [&>button]:py-2'
                options={[
                  { value: 'editorial', ariaLabel: `What you want to say: editorial type, ${counts.editorial}`, label: <TabLabel eyebrow='What you want to say' title='Editorial type' count={counts.editorial} /> },
                  { value: 'native', ariaLabel: `How you present it: native format, ${counts.native}`, label: <TabLabel eyebrow='How you present it' title='Native format' count={counts.native} /> }
                ]}
              />
            }
            search={query}
            onSearch={setQuery}
            searchLabel='Search content library'
            searchPlaceholder={tab === 'editorial' ? 'Search editorial types…' : 'Search native formats…'}
            view={<SegmentedControl<View> pattern='radio' size='sm' widths='content' label='Library view' value={view} onChange={changeView} options={VIEWS} className='[&>button]:min-h-11' />}
            filters={
              <FilterPanel count={active.count} onClear={() => clearFilters(false)} open={filtersOpen} onOpenChange={setFiltersOpen}>
                <FilterSelect
                  label='Category'
                  value={filters.category}
                  onChange={changeCategory}
                  options={categoryOptions(tab).map((option) => ({ value: option.value, label: `${option.label} · ${option.count}` }))}
                />
                <FilterSelect label='Suggested app fit' value={platformFilter} onChange={changePlatform} options={fitOptions} />
                <div className='flex items-center justify-between gap-3'>
                  <div className='flex flex-col gap-0.5'>
                    <span className='text-foreground text-sm font-medium'>Artwork motion</span>
                  </div>
                  <Button variant='glass' size='control' aria-pressed={paused} onClick={toggleArtwork} className='gap-2 text-xs'>
                    {paused ? <Icons.play className='size-3.5' /> : <Icons.pause className='size-3.5' />}
                    {paused ? 'Play artwork' : 'Pause artwork'}
                  </Button>
                </div>
                <Button
                  variant='quiet'
                  size='control'
                  onClick={() => {
                    // One layer at a time: the filter panel closes before the evidence dialog opens.
                    setFiltersOpen(false);
                    setEvidence({ pairingId: null });
                  }}
                  className='-mx-2 justify-between gap-2 px-2 text-sm'
                >
                  <span className='flex items-center gap-2'>
                    <Icons.info className='size-4' />
                    About app fit &amp; evidence
                  </span>
                  <Icons.arrowUpRight className='size-4' />
                </Button>
              </FilterPanel>
            }
            summary={<ActiveFilters count={active.count} summary={active.summary} onClear={() => clearFilters(false)} clearLabel='Clear' />}
          />
        </RafiiDialogHeader>

        <RafiiDialogBody className='pt-1'>
          <div ref={body} role='tabpanel' id={panelId} aria-label={tab === 'editorial' ? 'Editorial types' : 'Native formats'} className='@container/library flex flex-col gap-3.5'>
            <div className='flex items-center justify-between gap-3'>
              <strong className='text-muted-foreground text-sm font-medium'>{categoryTitle(tab, filters.category)}</strong>
              <span role='status' aria-live='polite' className='text-muted-foreground text-xs tabular-nums'>
                {items.length} / {total}
              </span>
            </div>
            {view === 'pairings' && (
              <div className='rafii-quiet flex gap-3 rounded-[var(--rafii-radius-card)] p-4'>
                <span aria-hidden className='text-muted-foreground text-xl leading-none'>
                  ↗
                </span>
                <div className='flex flex-col gap-1.5'>
                  <strong className='text-sm font-medium'>From idea to format to audience.</strong>
                  <span className='text-muted-foreground text-xs leading-relaxed'>Curated suggestions, not a ranking.</span>
                  <button type='button' onClick={() => setEvidence({ pairingId: null })} className='rafii-focus text-foreground mt-1 min-h-8 self-start rounded-md text-xs underline underline-offset-4'>
                    Read the evidence
                  </button>
                </div>
              </div>
            )}
            <div ref={host} className='relative'>
              <div key={swapKey} data-swap-current data-view={view} className={cn('grid grid-cols-1 items-start', view === 'list' ? 'gap-2' : 'gap-3.5', view === 'gallery' && '@[37.5rem]/library:grid-cols-2')}>
                {items.map((item) => {
                  const selected = item.id === selectedId;
                  const shared = { item, selected, paused, onSelect: select, onKey: onGridKey };
                  if (view === 'list') return <ListRow key={item.id} {...shared} />;
                  if (view === 'pairings') return <PairingCard key={item.id} {...shared} platform={platformFilter} onEvidence={(id) => setEvidence({ pairingId: id })} onUsePairing={usePairing} />;
                  return <GalleryCard key={item.id} {...shared} />;
                })}
              </div>
            </div>
            {items.length === 0 && (
              <StateMessage
                kind='empty'
                title='No matches in this corner.'
                action={
                  <Button variant='glass' size='control' onClick={() => clearFilters(true)}>
                    Clear filters
                  </Button>
                }
              />
            )}
          </div>
        </RafiiDialogBody>

        <RafiiDialogFooter>
          <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
            <div className='grid min-w-0 flex-1 grid-cols-2 gap-3' aria-live='polite'>
              <StagedChoice eyebrow='Editorial type' id={staged.editorialId} paused={paused} />
              <StagedChoice eyebrow='Native format' id={staged.nativeId} paused={paused} />
            </div>
            <Button variant='action' size='control' onClick={apply} aria-describedby={noteId} className='shrink-0 gap-2 sm:min-w-44'>
              Use these choices
              <Icons.check className='size-4' />
            </Button>
          </div>
          <p id={noteId} className='text-muted-foreground text-xs leading-relaxed'>
            {NOTE}
          </p>
        </RafiiDialogFooter>

        <RafiiDialog open={evidence !== null} onOpenChange={(next) => !next && setEvidence(null)}>
          <RafiiDialogContent size='md' className='md:max-h-[min(50rem,90dvh)]'>
            <RafiiDialogHeader eyebrow='A little context' title='Fit is not' accent='a leaderboard.' closeLabel='Close evidence' />
            <RafiiDialogBody className='flex flex-col gap-3 pb-6'>
              {pairing && (
                <section className='rafii-quiet rounded-[var(--rafii-radius-card)] p-5'>
                  <span className='rafii-eyebrow'>Fit suggestion</span>
                  <h4 className='mt-2 text-lg font-medium'>
                    {taxonomyItem(pairing.editorial)?.title} → {taxonomyItem(pairing.native)?.title}
                  </h4>
                  <p className='mt-2 text-sm leading-relaxed'>{pairing.why}</p>
                  <p className='text-muted-foreground mt-2.5 text-xs leading-relaxed'>{pairing.surface_note}</p>
                </section>
              )}
              <p className='text-muted-foreground text-sm leading-relaxed'>
                Suggested fit is our editorial judgement. <strong className='text-foreground font-medium'>Usage</strong> means how often a format was posted. <strong className='text-foreground font-medium'>Engagement</strong> measures a response. Neither establishes the most popular editorial topic, and the metrics are not
                directly comparable across platforms.
              </p>
              {evidenceRecords.length === 0 ? (
                <StateMessage kind='empty' layout='inline' title='No measured data for this pairing.' />
              ) : (
                evidenceRecords.map((record) => (
                  <article key={record.id} className='rafii-quiet rounded-[var(--rafii-radius-card)] p-5'>
                    <span className='rafii-eyebrow'>{record.kind}</span>
                    <h4 className='mt-2 text-base font-medium'>{record.label}</h4>
                    <p className='mt-2 text-sm leading-relaxed'>{record.finding}</p>
                    <p className='text-muted-foreground mt-2 text-xs leading-relaxed'>Sample: {record.sample}</p>
                    <p className='text-muted-foreground mt-2 text-xs leading-relaxed'>Limits: {record.limit}</p>
                    <a href={record.url} target='_blank' rel='noopener noreferrer' className='rafii-focus mt-2.5 inline-flex min-h-8 items-center gap-1 rounded-md text-xs underline underline-offset-4'>
                      {record.publisher} · {record.date}
                      <Icons.arrowUpRight className='size-3.5' aria-hidden />
                    </a>
                  </article>
                ))
              )}
              <p className='text-muted-foreground text-xs leading-relaxed'>
                Research snapshot: {snapshotDate(TAXONOMY_SOURCE.reviewedAt)}. No live analytics. Xiaohongshu pairings are unverified suggestions. Doesn’t check platform support or account eligibility.
              </p>
            </RafiiDialogBody>
          </RafiiDialogContent>
        </RafiiDialog>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Pieces                                                                      */
/* -------------------------------------------------------------------------- */

function TabLabel({ eyebrow, title, count }: { eyebrow: string; title: string; count: number }) {
  return (
    <span className='flex w-full min-w-0 flex-col items-start gap-0.5 text-left'>
      <span className='rafii-eyebrow hidden sm:block'>{eyebrow}</span>
      <span className='flex items-baseline gap-2 text-sm'>
        <span className='truncate'>{title}</span>
        <span className='text-muted-foreground text-xs tabular-nums'>· {count}</span>
      </span>
    </span>
  );
}

function ItemTags({ item }: { item: TaxonomyItem }) {
  return (
    <span className='flex flex-wrap items-center gap-1.5'>
      {item.tags.map((tag, index) => (
        <span key={tag} className={cn('text-muted-foreground rounded-md text-[11px] leading-tight tracking-wide', index === 0 ? '' : 'rafii-quiet px-1.5 py-0.5')}>
          {tag}
        </span>
      ))}
    </span>
  );
}

function PlanningLabel() {
  return (
    <span className='text-muted-foreground inline-flex items-center gap-1 text-[11px] leading-tight'>
      <Icons.slash className='size-3' aria-hidden />
      {PLANNING_ONLY_LABEL}
    </span>
  );
}

/** Suggested app fit as provider marks (they keep their colour, DNA §4.3); an empty fit is a specialist surface. */
function FitMarks({ ids, compact }: { ids: string[]; compact?: boolean }) {
  if (ids.length === 0) return <span className='text-muted-foreground text-xs'>Specialist surface</span>;
  const labels = ids.map((id) => platformInfo(id)?.label ?? id);
  return (
    <span role='img' aria-label={`Suggested app fit: ${labels.join(', ')}`} className='inline-flex shrink-0 items-center gap-1'>
      {ids.slice(0, 4).map((id) => (
        <ChannelIcon key={id} slug={PLATFORM_SLUGS[id] ?? id} name={platformInfo(id)?.label} size={compact ? 'xs' : 'sm'} />
      ))}
      {ids.length > 4 && <span className='text-muted-foreground text-[11px] tabular-nums'>+{ids.length - 4}</span>}
    </span>
  );
}

function SelectedCheck({ selected, className }: { selected: boolean; className?: string }) {
  return (
    <span aria-hidden className={cn('grid shrink-0 place-items-center transition-[opacity,transform] duration-300 ease-[var(--rafii-ease-soft)]', selected ? 'scale-100 opacity-100' : 'scale-75 opacity-0', className)}>
      <Icons.check className='size-3.5' />
    </span>
  );
}

function ItemInfo({ item, className }: { item: TaxonomyItem; className?: string }) {
  const mapping = executionFor(item.id);
  return (
    <InfoTip
      label={`About ${item.title}`}
      title={item.title}
      className={className}
      description={
        <>
          {item.description}
          {mapping && (
            <>
              <br />
              <span className='mt-1 block'>{mapping.execution === 'planning-only' ? `${PLANNING_ONLY_LABEL}. ${mapping.note}` : mapping.note}</span>
            </>
          )}
        </>
      }
    />
  );
}

interface CardProps {
  item: TaxonomyItem;
  selected: boolean;
  paused: boolean;
  onSelect: (id: string) => void;
  /** Grid navigation between cards (arrows, Home, End). */
  onKey: (event: KeyboardEvent<HTMLButtonElement>) => void;
}

const shell = (selected: boolean) => cn('relative min-w-0 transition-[background,box-shadow] duration-200', selected ? 'rafii-glass-selected' : 'rafii-quiet');

function GalleryCard({ item, selected, paused, onSelect, onKey }: CardProps) {
  const planning = isPlanningOnly(item.id);
  return (
    <article data-selected={selected} className={cn(shell(selected), 'flex flex-col rounded-[var(--rafii-radius-card)]')}>
      <button type='button' data-library-item={item.id} aria-pressed={selected} onClick={() => onSelect(item.id)} onKeyDown={onKey} className='rafii-focus flex w-full flex-col rounded-[inherit] text-left'>
        <span className='relative m-2.5 mb-0 block overflow-hidden rounded-[0.8125rem]'>
          <SemanticIllustration id={item.id} size='large' decorative motion={!paused} />
          <SelectedCheck selected={selected} className='absolute top-2.5 right-2.5 size-7 rounded-full bg-[#1b1b1b] text-white' />
        </span>
        <span className='flex flex-col gap-1.5 px-4 pt-3.5 pr-14 pb-4'>
          <ItemTags item={item} />
          <span className={cn('leading-snug text-balance', item.dimension === 'editorial' ? 'text-[1.375rem] font-normal tracking-[-0.01em] [font-family:var(--rafii-font-editorial)]' : 'text-lg font-medium tracking-tight')}>{item.title}</span>
          <span className='text-muted-foreground min-h-9 text-[0.8125rem] leading-relaxed'>{item.description}</span>
          {planning && <PlanningLabel />}
          <span className='mt-2 flex min-h-7 flex-wrap items-center gap-2.5'>
            <span className='rafii-eyebrow'>Suggested fit</span>
            <FitMarks ids={item.platforms} />
          </span>
        </span>
      </button>
      <ItemInfo item={item} className='absolute right-2 bottom-3' />
    </article>
  );
}

function ListRow({ item, selected, paused, onSelect, onKey }: CardProps) {
  const planning = isPlanningOnly(item.id);
  return (
    <article data-selected={selected} className={cn(shell(selected), 'flex items-center rounded-[0.875rem]')}>
      <button type='button' data-library-item={item.id} aria-pressed={selected} onClick={() => onSelect(item.id)} onKeyDown={onKey} className='rafii-focus flex min-h-[4.5rem] w-full items-center gap-3.5 rounded-[inherit] py-3 pr-14 pl-3 text-left'>
        <SemanticIllustration id={item.id} size='compact' decorative motion={!paused} className='size-12 shrink-0 rounded-[0.8125rem]' />
        <span className='flex min-w-0 flex-1 flex-col gap-1.5'>
          <span className='text-sm leading-snug font-medium'>{item.title}</span>
          <ItemTags item={item} />
          {planning && <PlanningLabel />}
        </span>
        <span className='hidden sm:flex'>
          <FitMarks ids={item.platforms} compact />
        </span>
        <SelectedCheck selected={selected} className='size-5' />
      </button>
      <ItemInfo item={item} className='absolute top-1/2 right-2 -translate-y-1/2' />
    </article>
  );
}

function PairingCard({ item, selected, paused, onSelect, onKey, platform, onEvidence, onUsePairing }: CardProps & { platform: string; onEvidence: (pairingId: string) => void; onUsePairing: (pairing: Pairing) => void }) {
  const planning = isPlanningOnly(item.id);
  const routes = pairingsFor(item, platform);
  return (
    <article data-selected={selected} className={cn(shell(selected), 'flex flex-col gap-2.5 rounded-[var(--rafii-radius-card)] px-4 pb-4')}>
      <div className='relative'>
        <button type='button' data-library-item={item.id} aria-pressed={selected} onClick={() => onSelect(item.id)} onKeyDown={onKey} className='rafii-focus flex w-full items-center gap-3.5 rounded-xl py-4 pr-12 text-left'>
          <SemanticIllustration id={item.id} size='compact' decorative motion={!paused} className='size-11 shrink-0 rounded-xl' />
          <span className='flex min-w-0 flex-1 flex-col gap-1'>
            <ItemTags item={item} />
            <span className='text-base leading-snug font-medium'>{item.title}</span>
            {planning && <PlanningLabel />}
          </span>
          <SelectedCheck selected={selected} className='size-5' />
        </button>
        <ItemInfo item={item} className='absolute top-1/2 right-0 -translate-y-1/2' />
      </div>
      <div className='flex flex-col gap-2.5'>
        {routes.length === 0 && <p className='text-muted-foreground text-xs leading-relaxed'>No pairing for this app. Clear the app filter to see all.</p>}
        {routes.map((pairing) => {
          const other = taxonomyItem(item.dimension === 'editorial' ? pairing.native : pairing.editorial);
          const editorial = taxonomyItem(pairing.editorial);
          const native = taxonomyItem(pairing.native);
          if (!other || !editorial || !native) return null;
          const main = pairing.evidence[0] ? EVIDENCE[pairing.evidence[0]] : null;
          return (
            <div key={pairing.id} className='rafii-quiet flex flex-col gap-2.5 rounded-[0.8125rem] p-3.5'>
              <div className='flex items-center gap-2.5'>
                <span aria-hidden className='text-muted-foreground hidden sm:block'>
                  ↳
                </span>
                <SemanticIllustration id={other.id} size='compact' decorative motion={!paused} className='size-9 shrink-0 rounded-lg' />
                <span className='flex min-w-0 flex-1 flex-col gap-0.5'>
                  <span className='rafii-eyebrow'>{item.dimension === 'editorial' ? 'Present as' : 'Try this intent'}</span>
                  <span className='text-sm leading-snug font-medium'>{other.title}</span>
                </span>
                <span aria-hidden className='text-muted-foreground'>
                  →
                </span>
                <FitMarks ids={pairing.platforms} compact />
              </div>
              <p className='text-muted-foreground text-[0.8125rem] leading-relaxed'>{pairing.why}</p>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <Button variant='quiet' size='sm' onClick={() => onEvidence(pairing.id)} className='h-11 gap-1.5 px-2 text-xs'>
                  <Icons.info className='size-3.5' />
                  {main ? main.kind : 'Fit suggestion'}
                </Button>
                <Button variant='glass' size='sm' onClick={() => onUsePairing(pairing)} aria-label={`Use ${editorial.title} with ${native.title}`} className='h-11 gap-1.5 px-3 text-xs'>
                  Use pairing
                  <Icons.arrowUpRight className='size-3.5' />
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function StagedChoice({ eyebrow, id, paused }: { eyebrow: string; id: string; paused: boolean }) {
  const item = taxonomyItem(id);
  const planning = isPlanningOnly(id);
  return (
    <div className='flex min-w-0 items-center gap-2.5'>
      <SemanticIllustration id={id} size='compact' decorative motion={!paused} className='size-8 shrink-0 rounded-lg' />
      <span className='flex min-w-0 flex-col'>
        <span className='rafii-eyebrow'>{eyebrow}</span>
        <span className='text-foreground truncate text-sm font-medium'>{item?.title ?? 'Legacy item'}</span>
        {planning && <span className='text-muted-foreground truncate text-[11px]'>{PLANNING_ONLY_LABEL}</span>}
      </span>
    </div>
  );
}
