'use client';

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import Link from 'next/link';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { IconCheck, IconChevronDown, IconSearch, IconX } from '@tabler/icons-react';
import { InfoTip, RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, SegmentedControl, StateMessage } from '@/components/rafii';
import { ReasoningBars } from '@/components/rafii/reasoning-bars';
import { Button } from '@/components/ui/button';
import { billingLabel, CostBadge, ProviderIcon, providerName, routeLabel } from '@/components/ui/model-selector';
import type { AgentInfo, ModelCatalog, ModelOption } from '@/lib/api/types';
import { motionAllowed, RAFII_EASE_CSS, useCrossfadeSwap, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { AUTO_LEVEL, chooseLevel, hasAutoLevel, levelHint, levelsFor } from './reasoning-map';
import { useOpenGeneration } from './language-dialog';
import { AUTO_MODEL, modelName, shortLabel } from './use-model';

export interface ModelDialogValue {
  /** AUTO_MODEL (follow the workspace default) or a catalogue id. */
  model: string;
  /** A level id the writer lists (`auto`, `high`, `thorough`; `quick` or `low` on the fixture and CLI routes). */
  reasoning: string;
}

/** What the Auto row stands for: the writer Auto resolves to now and whose default that is. */
export interface ModelDialogAuto {
  option: ModelOption | undefined;
  source: 'workspace' | 'deployment';
  /** Why the workspace default was not used (it is no longer offered), when that happened. */
  note?: string | null;
}

export interface ModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The live catalog (`useModels().data`); undefined while loading. */
  catalog: ModelCatalog | undefined;
  /** The committed choice (`useModelChoice().dialogValue`); browsing in the dialog never changes it until "Use this model". */
  value: ModelDialogValue;
  /** `useModelChoice().applyDialog`: Auto is kept as Auto, never pinned to the model it resolves to. */
  onApply: (next: ModelDialogValue) => void;
  /** Remembered level per model id or AUTO_MODEL (`useModelChoice().reasoningFor`), read when another row is browsed. */
  reasoningFor?: (modelId: string) => string | null | undefined;
  /** Offers Auto as the first row; null or omitted = no Auto row. */
  auto?: ModelDialogAuto | null;
  /** The workspace pays in credits: level hints name credits (otherwise they compare with Auto). */
  credits?: boolean;
  /** Optional element id for the popup (for a trigger's `aria-controls`). */
  id?: string;
}

type Mode = 'api' | 'cli';

function isCli(model: ModelOption | undefined) {
  return Boolean(model?.route && !['fixture', 'managed'].includes(model.route));
}

/** A row that can be staged: offered, and priced when it is a managed writer. */
function selectable(model: ModelOption | undefined) {
  return Boolean(model?.qualified && model.priced !== false);
}

interface ProviderGroup {
  id: string;
  name: string;
  mode: Mode;
  sample: ModelOption;
  models: ModelOption[];
}

function groupProviders(models: readonly ModelOption[]): ProviderGroup[] {
  const groups: ProviderGroup[] = [];
  for (const model of models) {
    const mode: Mode = isCli(model) ? 'cli' : 'api';
    const name = providerName(model);
    const id = `${mode}:${name}`;
    let group = groups.find((item) => item.id === id);
    if (!group) {
      group = { id, name, mode, sample: model, models: [] };
      groups.push(group);
    }
    group.models.push(model);
  }
  return groups;
}

/** Rail and list wording for a provider name; the fixture route reads as a preview, not a vendor. */
function providerLabel(name: string) {
  return name === 'fixture' ? 'Preview' : name;
}

function agentProvider(agent: AgentInfo) {
  return providerName({ id: agent.id, label: agent.name, qualified: false, detail: '', route: agent.id, provider: agent.vendor });
}

function authLabel(status: string) {
  if (status === 'ok') return 'Signed in';
  if (status === 'missing') return 'Not signed in';
  if (status === 'expired') return 'Sign-in expired';
  return 'Sign-in status unknown';
}

/** A row's name: the managed display name, else the catalogue label, else the short label for the id. */
function rowName(option: ModelOption | undefined, id: string) {
  return option?.displayName ?? option?.label ?? shortLabel(option, id);
}

/**
 * Model and reasoning dialog (Rafii v9 brief C; DNA v8 §15.3–15.4, §11.3). API models: Auto first (the workspace
 * default, else Rafii's), then the featured writers, then "More models" for everything else; CLI models keep the
 * provider rail. Rows and levels browse a staged choice; "Use this model" commits it. Reasoning lists only the levels
 * the staged writer offers (Auto offers Auto and Thorough), each named by what it sends.
 */
export function ModelDialog({ open, onOpenChange, catalog, value, onApply, reasoningFor, auto, credits, id }: ModelDialogProps) {
  const titleId = useId();
  const generation = useOpenGeneration(open);
  return (
    <RafiiDialog open={open} onOpenChange={(next) => onOpenChange(next)}>
      <RafiiDialogContent size='md' id={id} aria-labelledby={titleId}>
        <ModelStage
          key={generation}
          catalog={catalog}
          value={value}
          reasoningFor={reasoningFor}
          auto={auto ?? null}
          credits={Boolean(credits)}
          titleId={titleId}
          onCancel={() => onOpenChange(false)}
          onApply={(next) => {
            onApply(next);
            onOpenChange(false);
          }}
        />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

interface StageProps {
  catalog: ModelCatalog | undefined;
  value: ModelDialogValue;
  reasoningFor?: ModelDialogProps['reasoningFor'];
  auto: ModelDialogAuto | null;
  credits: boolean;
  titleId: string;
  onApply: (next: ModelDialogValue) => void;
  onCancel: () => void;
}

function ModelStage({ catalog, value, reasoningFor, auto, credits, titleId, onApply, onCancel }: StageProps) {
  const ids = useId();
  const { reduced } = useMotionPreference();
  const models = useMemo(() => catalog?.models ?? [], [catalog]);
  const groups = useMemo(() => groupProviders(models), [models]);
  const optionFor = (modelId: string) => (modelId === AUTO_MODEL ? auto?.option : models.find((model) => model.id === modelId));
  const committed = optionFor(value.model);
  const committedCli = value.model !== AUTO_MODEL && isCli(committed);

  /* API models: featured writers in the catalogue's order, the rest behind "More models". */
  const apiModels = useMemo(() => models.filter((model) => !isCli(model)), [models]);
  const featured = useMemo(() => (catalog?.featured ?? []).map((featuredId) => apiModels.find((model) => model.id === featuredId)).filter((model): model is ModelOption => Boolean(model)), [catalog?.featured, apiModels]);
  const more = useMemo(() => apiModels.filter((model) => !featured.includes(model)), [apiModels, featured]);

  const [staged, setStaged] = useState(value.model);
  const [level, setLevel] = useState(value.reasoning || AUTO_LEVEL);
  const [mode, setMode] = useState<Mode>(() => (committedCli ? 'cli' : 'api'));
  const [provider, setProvider] = useState(() => (committedCli && committed ? `cli:${providerName(committed)}` : (groups.find((group) => group.mode === 'cli')?.id ?? '')));
  const [query, setQuery] = useState('');
  const [listKey, setListKey] = useState(0);
  // Open from the start when nothing is featured (templates must stay reachable) or the committed writer is in there.
  const [moreOpen, setMoreOpen] = useState(() => featured.length === 0 || more.some((model) => model.id === value.model));

  /* Most people draft with the writers under Rafii; the CLI switch appears only where the API host reports one. */
  const hasCli = groups.some((group) => group.mode === 'cli') || (catalog?.agents?.length ?? 0) > 0;
  const rail = groups.filter((group) => group.mode === 'cli');
  const activeGroup = rail.find((group) => group.id === provider) ?? rail[0];
  const stagedIsAuto = staged === AUTO_MODEL;
  const stagedOption = optionFor(staged);
  const trimmed = query.trim().toLowerCase();
  const showAuto = Boolean(auto) && mode === 'api' && !trimmed;
  const visible = trimmed
    ? models.filter((model) => `${model.label} ${model.displayName ?? ''} ${model.family ?? ''} ${model.id} ${providerName(model)} ${routeLabel(model)} ${model.detail}`.toLowerCase().includes(trimmed))
    : mode === 'cli'
      ? (activeGroup?.models ?? [])
      : [...featured, ...(moreOpen ? more : [])];
  const agents = mode === 'cli' ? (catalog?.agents ?? []).filter((agent) => !activeGroup || agentProvider(agent) === activeGroup.name) : [];

  /* Reasoning: the staged writer's own levels; on Auto only Auto and Thorough, since the model may change under you. */
  const managed = hasAutoLevel(stagedOption?.reasoning);
  const levels = levelsFor(stagedOption?.reasoning ?? catalog?.reasoning, stagedIsAuto && managed);
  const effective = chooseLevel(levels, level, managed);
  const hint = levelHint(effective, levels.find((item) => item.id === AUTO_LEVEL), credits);
  const autoName = auto?.option ? modelName(auto.option, auto.option.id) : null;
  const capsule = stagedIsAuto ? (autoName ? `Auto · ${autoName}` : 'Auto') : rowName(stagedOption, staged);

  /* Crossfade of the list (DNA §18.3): snapshot before the change, settle after the DOM updates. */
  const host = useRef<HTMLDivElement>(null);
  const { swap, settle } = useCrossfadeSwap(host);
  useLayoutEffect(() => {
    settle();
  }, [listKey, settle]);
  function showProvider(nextId: string, nextMode: Mode = mode) {
    const order = groups.map((group) => group.id);
    const direction: 1 | -1 = order.indexOf(nextId) >= order.indexOf(activeGroup?.id ?? '') ? 1 : -1;
    swap(direction);
    setMode(nextMode);
    setProvider(nextId);
    setQuery('');
    setListKey((key) => key + 1);
  }
  function switchMode(next: Mode) {
    if (next === mode) return;
    const first = groups.find((group) => group.mode === next);
    if (next === 'cli' && first) showProvider(first.id, next);
    else {
      swap(next === 'cli' ? 1 : -1);
      setMode(next);
      setQuery('');
      setListKey((key) => key + 1);
    }
  }

  /* Provider lens (CLI mode): one element that glides between rail tabs (DNA §18.5). */
  const railRef = useRef<HTMLDivElement>(null);
  const [lens, setLens] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const node = railRef.current;
    if (!node) return;
    const measure = () => {
      const active = activeGroup ? node.querySelector<HTMLElement>(`[data-provider="${CSS.escape(activeGroup.id)}"]`) : null;
      setLens(active ? { x: active.offsetLeft, y: active.offsetTop, w: active.offsetWidth, h: active.offsetHeight } : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [activeGroup, rail.length, mode]);
  function onRailKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !rail.length) return;
    event.preventDefault();
    const index = Math.max(0, rail.findIndex((group) => group.id === activeGroup?.id));
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? rail.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : rail.length - 1)) % rail.length;
    const target = rail[next];
    if (target.id !== activeGroup?.id) showProvider(target.id);
    railRef.current?.querySelector<HTMLElement>(`[data-provider="${CSS.escape(target.id)}"]`)?.focus({ preventScroll: true });
  }

  /* Capsule label swap (330ms) when the staged model changes. */
  const capsuleLabel = useRef<HTMLElement>(null);
  const lastLabel = useRef(capsule);
  useEffect(() => {
    if (capsule === lastLabel.current) return;
    lastLabel.current = capsule;
    const node = capsuleLabel.current;
    if (node && motionAllowed() && typeof node.animate === 'function') {
      node.animate([{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 330, easing: RAFII_EASE_CSS.ui });
    }
  }, [capsule]);

  function stage(modelId: string) {
    if (modelId === staged) return;
    if (modelId === AUTO_MODEL ? !auto?.option?.qualified : !selectable(optionFor(modelId))) return;
    setStaged(modelId);
    setLevel(reasoningFor?.(modelId) ?? AUTO_LEVEL);
  }

  /* One tab stop in the Models radiogroup (the staged row, else the first enabled one); arrows move and stage. */
  const enabledRows = [...(showAuto && auto?.option?.qualified ? [AUTO_MODEL] : []), ...visible.filter((model) => selectable(model)).map((model) => model.id)];
  const tabStop = enabledRows.includes(staged) ? staged : enabledRows[0];
  function onRowsKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const nodes = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not([disabled])'));
    if (!nodes.length) return;
    event.preventDefault();
    const index = nodes.indexOf(document.activeElement as HTMLButtonElement);
    const step = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? nodes.length - 1 : index < 0 ? 0 : (index + step + nodes.length) % nodes.length;
    nodes[next].focus();
    const rowId = nodes[next].dataset.row;
    if (rowId) stage(rowId);
  }
  function onLevelsKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    const enabled = levels.filter((item) => item.available);
    if (!enabled.length) return;
    event.preventDefault();
    const index = enabled.findIndex((item) => item.id === effective?.id);
    const step = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : -1;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1 : (Math.max(0, index) + step + enabled.length) % enabled.length;
    setLevel(enabled[next].id);
    event.currentTarget.querySelector<HTMLElement>(`[data-level="${CSS.escape(enabled[next].id)}"]`)?.focus();
  }

  const panelId = `${ids}-panel`;
  const moreId = `${ids}-more`;
  const canApply = stagedIsAuto ? Boolean(auto?.option?.qualified) : selectable(stagedOption);

  function row(model: ModelOption) {
    const chosen = model.id === staged;
    const unpriced = model.qualified && model.priced === false;
    return (
      <button
        key={model.id}
        type='button'
        role='radio'
        aria-checked={chosen}
        disabled={!selectable(model)}
        tabIndex={tabStop === model.id ? 0 : -1}
        data-row={model.id}
        title={`${[model.family, providerLabel(providerName(model))].filter(Boolean).join(' · ')} · ${routeLabel(model)}${model.detail ? ` · ${model.detail}` : ''}`}
        onClick={() => stage(model.id)}
        className={cn(
          'rafii-focus flex min-h-16 w-full items-start gap-3 rounded-[var(--rafii-radius-card)] px-3 py-3 text-left transition-colors duration-200',
          chosen ? 'rafii-glass-selected' : 'hover:rafii-quiet',
          !selectable(model) && 'cursor-not-allowed opacity-60'
        )}
      >
        <ProviderIcon model={model} className='mt-0.5 size-5' />
        <span className='flex min-w-0 flex-1 flex-col gap-1'>
          <span className='text-foreground flex items-center gap-2 text-[15px] leading-tight font-medium [overflow-wrap:anywhere]'>
            {rowName(model, model.id)}
            <CostBadge model={model} />
            {chosen && <IconCheck aria-hidden className='size-4 shrink-0' />}
          </span>
          {/* Who pays stays visible; provider and route live in the row's tooltip. */}
          <span className={cn('text-xs leading-relaxed', selectable(model) ? 'text-muted-foreground' : 'text-foreground')}>
            {!model.qualified ? `Unavailable · ${model.detail}` : unpriced ? 'Unavailable · No price is configured for this model.' : billingLabel(model.costClass)}
          </span>
        </span>
      </button>
    );
  }

  const autoChosen = stagedIsAuto;
  const autoDetail = auto ? [autoName ? `Uses ${autoName}` : 'No writer available', auto.source === 'workspace' ? 'the workspace default' : 'Rafii’s default'].join(' · ') : '';

  return (
    <>
      <div className='flex shrink-0 items-center justify-between gap-4 px-5 pt-4 md:px-7 md:pt-6'>
        <span className='rafii-eyebrow'>Model</span>
        <DialogPrimitive.Title id={titleId} className='sr-only'>
          Choose a model
        </DialogPrimitive.Title>
        <DialogPrimitive.Close aria-label='Close model settings' className='rafii-glass rafii-focus hover:rafii-glass-selected flex size-11 shrink-0 items-center justify-center rounded-full'>
          <IconX aria-hidden className='size-4' />
        </DialogPrimitive.Close>
      </div>
      <RafiiDialogBody className='pt-2'>
        <div aria-live='polite' className='rafii-glass-selected mx-auto mt-1 mb-5 flex min-h-14 max-w-full items-center justify-center gap-3 rounded-full px-5 py-3 text-lg font-medium tracking-[-0.01em]'>
          <ProviderIcon model={stagedIsAuto ? undefined : stagedOption} className='size-6' />
          <strong ref={capsuleLabel} className='min-w-0 truncate font-medium'>
            {capsule}
          </strong>
          <IconChevronDown aria-hidden className='text-muted-foreground size-4 rotate-180' />
        </div>

        {!catalog ? (
          <StateMessage kind='loading' title='Loading the model catalog' />
        ) : models.length === 0 ? (
          <StateMessage kind='empty' title='No models available' action={<Link href='/app/account/models' className='text-foreground text-sm underline underline-offset-2'>Set up models</Link>} />
        ) : (
          <>
            <div className='mb-3 flex flex-wrap items-center justify-between gap-3'>
              {hasCli && (
                <>
                  <SegmentedControl<Mode> label='Connection mode' size='sm' widths='content' value={mode} onChange={switchMode} options={[{ value: 'api', label: 'API models' }, { value: 'cli', label: 'CLI' }]} />
                  <InfoTip label='About API and CLI models' description='API models run through Rafii. CLI models run on the computer that hosts Rafii, with your own CLI sign-in.' className='size-9' />
                </>
              )}
            </div>

            <div className={cn('rafii-quiet grid min-h-[22rem] overflow-hidden rounded-[var(--rafii-radius-card)]', mode === 'cli' ? 'grid-cols-[3.25rem_minmax(0,1fr)] md:grid-cols-[4.25rem_minmax(0,1fr)]' : 'grid-cols-1')}>
              {mode === 'cli' && (
                <div ref={railRef} role='tablist' aria-label='Model providers' aria-orientation='vertical' className='relative isolate flex flex-col items-center gap-2 px-1 py-3 md:px-2'>
                  <span
                    aria-hidden
                    className={cn('rafii-lens pointer-events-none absolute top-0 left-0 z-0 rounded-[1rem]', !reduced && 'transition-[transform,width,height] duration-[440ms] ease-[var(--rafii-ease-soft)]')}
                    style={lens ? { transform: `translate(${lens.x}px, ${lens.y}px)`, width: lens.w, height: lens.h, opacity: 1 } : { opacity: 0 }}
                  />
                  {rail.map((group) => {
                    const active = group.id === activeGroup?.id;
                    return (
                      <button
                        key={group.id}
                        type='button'
                        role='tab'
                        id={`${ids}-tab-${group.id}`}
                        data-provider={group.id}
                        aria-selected={active}
                        aria-controls={panelId}
                        aria-label={`${providerLabel(group.name)} models`}
                        title={providerLabel(group.name)}
                        tabIndex={active ? 0 : -1}
                        onClick={() => !active && showProvider(group.id)}
                        onKeyDown={onRailKeyDown}
                        className={cn('rafii-focus relative z-10 flex size-11 shrink-0 items-center justify-center rounded-[1rem] transition-colors duration-200 md:size-12', active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground')}
                      >
                        <ProviderIcon model={group.sample} className='size-6' />
                      </button>
                    );
                  })}
                  {rail.length === 0 && <span className='text-muted-foreground px-1 text-center text-[11px] leading-tight'>None</span>}
                </div>
              )}

              <div
                id={panelId}
                role={mode === 'cli' ? 'tabpanel' : undefined}
                aria-labelledby={mode === 'cli' && activeGroup ? `${ids}-tab-${activeGroup.id}` : undefined}
                className='flex min-w-0 flex-col'
              >
                <div className='flex min-h-14 items-center gap-2.5 px-3 md:px-4'>
                  <IconSearch aria-hidden className='text-muted-foreground size-5 shrink-0' />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    aria-label='Search models'
                    placeholder='Search models'
                    autoComplete='off'
                    spellCheck={false}
                    className='placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm'
                  />
                  {query && (
                    <button type='button' aria-label='Clear model search' onClick={() => setQuery('')} className='rafii-focus text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-full'>
                      <IconX aria-hidden className='size-4' />
                    </button>
                  )}
                </div>

                <div className='bg-background/40 flex min-h-0 flex-1 flex-col rounded-tl-[var(--rafii-radius-card)] p-3'>
                  {mode === 'cli' && !trimmed && (
                    <div className='mb-3 flex flex-col gap-2'>
                      {agents.length === 0 ? (
                        <p className='text-muted-foreground px-1 text-xs leading-relaxed'>No CLI found.</p>
                      ) : (
                        agents.map((agent) => {
                          const ready = agent.installed && agent.authStatus === 'ok';
                          return (
                            <div key={agent.id} className='rafii-glass flex flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3.5 py-3 text-xs leading-relaxed'>
                              <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                                <span className='text-foreground text-sm font-medium'>{agent.name}</span>
                                {agent.vendor && <span className='text-muted-foreground'>{agent.vendor}</span>}
                                <span className={cn('ml-auto rounded-full px-2 py-0.5', ready ? 'bg-foreground text-background' : 'rafii-quiet text-muted-foreground')}>{ready ? 'Ready' : 'Setup needed'}</span>
                              </div>
                              <p className='text-muted-foreground' title={[agent.version, agent.host].filter(Boolean).join(' · ') || undefined}>
                                {agent.installed ? 'Installed' : 'Not installed'} · {authLabel(agent.authStatus)}
                              </p>
                              {agent.guidance && <p className='text-foreground'>{agent.guidance}</p>}
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}

                  <div ref={host} className='relative min-w-0'>
                    <div data-swap-current className='min-w-0'>
                      <p className='rafii-eyebrow px-2 pb-2'>{trimmed ? `Search results · ${visible.length}` : mode === 'cli' ? providerLabel(activeGroup?.name ?? 'Models') : 'Models'}</p>
                      {visible.length === 0 && !showAuto ? (
                        <StateMessage kind='empty' layout='inline' title='No models found.' className='px-2' />
                      ) : (
                        // oxlint-disable-next-line jsx-a11y/interactive-supports-focus -- arrow keys bubble up from the focusable radios inside
                        <div role='radiogroup' aria-label='Models' onKeyDown={onRowsKeyDown} className='flex max-h-[22rem] flex-col gap-1 overflow-y-auto overscroll-contain md:max-h-[26rem]'>
                          {showAuto && auto && (
                            <button
                              type='button'
                              role='radio'
                              aria-checked={autoChosen}
                              aria-label='Auto'
                              aria-describedby={`${ids}-auto-detail`}
                              disabled={!auto.option?.qualified}
                              tabIndex={tabStop === AUTO_MODEL ? 0 : -1}
                              data-row={AUTO_MODEL}
                              onClick={() => stage(AUTO_MODEL)}
                              className={cn(
                                'rafii-focus flex min-h-16 w-full items-start gap-3 rounded-[var(--rafii-radius-card)] px-3 py-3 text-left transition-colors duration-200',
                                autoChosen ? 'rafii-glass-selected' : 'hover:rafii-quiet',
                                !auto.option?.qualified && 'cursor-not-allowed opacity-60'
                              )}
                            >
                              <ProviderIcon className='mt-0.5 size-5' />
                              <span className='flex min-w-0 flex-1 flex-col gap-1'>
                                <span className='text-foreground flex items-center gap-2 text-[15px] leading-tight font-medium'>
                                  Auto
                                  {autoChosen && <IconCheck aria-hidden className='size-4 shrink-0' />}
                                </span>
                                <span id={`${ids}-auto-detail`} className='text-muted-foreground text-xs leading-relaxed [overflow-wrap:anywhere]'>
                                  {autoDetail}
                                  {auto.note ? `. ${auto.note}` : ''}
                                </span>
                              </span>
                            </button>
                          )}
                          {trimmed || mode === 'cli' ? (
                            visible.map(row)
                          ) : (
                            <>
                              {featured.map(row)}
                              <div id={moreId} hidden={!moreOpen} className='flex flex-col gap-1'>
                                {moreOpen && more.map(row)}
                              </div>
                            </>
                          )}
                        </div>
                      )}
                      {mode === 'api' && !trimmed && more.length > 0 && (
                        <button
                          type='button'
                          aria-expanded={moreOpen}
                          aria-controls={moreId}
                          onClick={() => setMoreOpen((open) => !open)}
                          className='rafii-focus text-muted-foreground hover:text-foreground mt-1 flex min-h-11 w-full items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 text-left text-sm'
                        >
                          <span className='text-foreground font-medium'>More models</span>
                          <span className='flex items-center gap-2 text-xs'>
                            {more.length}
                            <IconChevronDown aria-hidden className={cn('size-4 shrink-0 transition-transform duration-[400ms] ease-[var(--rafii-ease-soft)] motion-reduce:transition-none', moreOpen && 'rotate-180')} />
                          </span>
                        </button>
                      )}
                    </div>
                  </div>

                  <div className='mt-4 px-0.5'>
                    <div className='text-muted-foreground mb-2.5 flex items-center gap-2.5 px-2 text-sm'>
                      {effective?.id === AUTO_LEVEL ? (
                        <span className='text-foreground text-xs font-medium'>Auto</span>
                      ) : (
                        <ReasoningBars count={effective?.bars ?? 0} muted={!effective} />
                      )}
                      <span id={`${ids}-reasoning`}>Reasoning</span>
                      <span className='text-muted-foreground ml-auto truncate text-xs'>{capsule}</span>
                    </div>
                    {levels.length > 0 && (
                      // oxlint-disable-next-line jsx-a11y/interactive-supports-focus -- arrow keys bubble up from the focusable radios inside
                      <div role='radiogroup' aria-labelledby={`${ids}-reasoning`} aria-describedby={`${ids}-reasoning-help`} onKeyDown={onLevelsKeyDown} className='flex flex-wrap gap-1.5'>
                        {levels.map((item) => {
                          const chosen = effective?.id === item.id;
                          return (
                            <button
                              key={item.id}
                              type='button'
                              role='radio'
                              aria-checked={chosen}
                              disabled={!item.available}
                              tabIndex={chosen ? 0 : -1}
                              data-level={item.id}
                              aria-label={item.available ? `${item.label}: sends ${item.sends}` : `${item.label}: unavailable${item.detail ? `, ${item.detail}` : ''}`}
                              title={item.detail || undefined}
                              onClick={() => setLevel(item.id)}
                              className={cn(
                                'rafii-focus inline-flex min-h-11 items-center justify-center rounded-[var(--rafii-radius-control)] px-3.5 text-[13px] font-medium transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40',
                                chosen ? 'rafii-glass-selected text-foreground' : 'rafii-quiet text-muted-foreground hover:text-foreground'
                              )}
                            >
                              {item.label}
                            </button>
                          );
                        })}
                      </div>
                    )}
                    <p id={`${ids}-reasoning-help`} className='text-muted-foreground mt-2 min-h-4 px-2 text-xs leading-relaxed' aria-live='polite'>
                      {levels.length === 0 ? 'This model has no reasoning setting.' : [effective?.detail, hint].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <div className='flex flex-col-reverse gap-2 sm:flex-row sm:items-center'>
          <Link href='/app/account/models' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center rounded-[var(--rafii-radius-control)] px-2 text-xs'>
            Manage models <span aria-hidden>↗</span>
          </Link>
          <div className='flex flex-1 flex-col-reverse gap-2 sm:flex-row sm:justify-end'>
            <Button variant='quiet' size='control' onClick={onCancel}>
              Cancel
            </Button>
            <Button variant='action' size='control' disabled={!canApply} onClick={() => onApply({ model: staged, reasoning: effective?.id ?? level })}>
              Use this model <IconCheck aria-hidden />
            </Button>
          </div>
        </div>
      </RafiiDialogFooter>
    </>
  );
}
