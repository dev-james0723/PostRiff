'use client';

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import Link from 'next/link';
import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import { IconCheck, IconChevronDown, IconSearch, IconX } from '@tabler/icons-react';
import { InfoTip, RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, SegmentedControl, StateMessage } from '@/components/rafii';
import { ReasoningBars } from '@/components/rafii/reasoning-bars';
import { Button } from '@/components/ui/button';
import { billingLabel, ProviderIcon, providerName, routeLabel } from '@/components/ui/model-selector';
import type { AgentInfo, ModelCatalog, ModelOption } from '@/lib/api/types';
import { motionAllowed, RAFII_EASE_CSS, useCrossfadeSwap, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { mapReasoning, normaliseLevel, REASONING_BARS, type ReasoningLevel } from './reasoning-map';
import { useOpenGeneration } from './language-dialog';
import { shortLabel } from './use-model';

export interface ModelDialogValue {
  model: string;
  /** The reasoning preference (`low | medium | high | xhigh | max`); an option id is accepted and normalised. */
  reasoning: string;
}

export interface ModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The live catalog (`useModels().data`); undefined while loading. */
  catalog: ModelCatalog | undefined;
  /** The committed choice; browsing in the dialog never changes it until "Use this model". */
  value: ModelDialogValue;
  onApply: (next: ModelDialogValue) => void;
  /** Remembered preference per model (`useModelChoice().reasoningFor`), read when another model is browsed. */
  reasoningFor?: (modelId: string) => string | null | undefined;
  /** Optional element id for the popup (for a trigger's `aria-controls`). */
  id?: string;
}

type Mode = 'api' | 'cli';

function isCli(model: ModelOption | undefined) {
  return Boolean(model?.route && !['fixture', 'managed'].includes(model.route));
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

/**
 * Model and reasoning dialog (Rafii v9 brief C; DNA v8 §15.3–15.4, §11.3). The selected-model
 * capsule, the API/CLI switch, a vertical provider rail with one lens, search and model rows all
 * browse a staged choice; "Use this model" commits it. Reasoning is a per-model preference mapped
 * onto the route's real options (`reasoning-map.ts`), with the effective value written under the
 * control so nothing is claimed that the provider does not do.
 */
export function ModelDialog({ open, onOpenChange, catalog, value, onApply, reasoningFor, id }: ModelDialogProps) {
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

function ModelStage({ catalog, value, reasoningFor, titleId, onApply, onCancel }: { catalog: ModelCatalog | undefined; value: ModelDialogValue; reasoningFor?: ModelDialogProps['reasoningFor']; titleId: string; onApply: (next: ModelDialogValue) => void; onCancel: () => void }) {
  const ids = useId();
  const { reduced } = useMotionPreference();
  const models = useMemo(() => catalog?.models ?? [], [catalog]);
  const groups = useMemo(() => groupProviders(models), [models]);
  const committed = models.find((model) => model.id === value.model);

  const defaultLevel = (model: ModelOption | undefined) => mapReasoning(null, model?.reasoning ?? catalog?.reasoning, '').preference;
  const [staged, setStaged] = useState(value.model);
  const [preference, setPreference] = useState<ReasoningLevel>(() => normaliseLevel(value.reasoning) ?? defaultLevel(committed));
  const [mode, setMode] = useState<Mode>(() => (isCli(committed) ? 'cli' : 'api'));
  const [provider, setProvider] = useState(() => (committed ? `${isCli(committed) ? 'cli' : 'api'}:${providerName(committed)}` : (groups[0]?.id ?? '')));
  const [query, setQuery] = useState('');
  const [listKey, setListKey] = useState(0);

  const rail = groups.filter((group) => group.mode === mode);
  const activeGroup = rail.find((group) => group.id === provider) ?? rail[0];
  const stagedOption = models.find((model) => model.id === staged);
  const trimmed = query.trim().toLowerCase();
  const visible = trimmed
    ? models.filter((model) => `${model.label} ${model.id} ${providerName(model)} ${routeLabel(model)} ${model.detail}`.toLowerCase().includes(trimmed))
    : (activeGroup?.models ?? []);
  const mapping = mapReasoning(preference, stagedOption?.reasoning ?? catalog?.reasoning, shortLabel(stagedOption, staged));
  const agents = (catalog?.agents ?? []).filter((agent) => !activeGroup || agentProvider(agent) === activeGroup.name);

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
    if (first) showProvider(first.id, next);
    else {
      swap(next === 'cli' ? 1 : -1);
      setMode(next);
      setQuery('');
      setListKey((key) => key + 1);
    }
  }

  /* Provider lens: one element that glides between rail tabs (DNA §18.5). */
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
  }, [activeGroup, rail.length]);
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
  const lastLabel = useRef(stagedOption?.label ?? staged);
  useEffect(() => {
    const label = stagedOption?.label ?? staged;
    if (label === lastLabel.current) return;
    lastLabel.current = label;
    const node = capsuleLabel.current;
    if (node && motionAllowed() && typeof node.animate === 'function') {
      node.animate([{ opacity: 0, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 330, easing: RAFII_EASE_CSS.ui });
    }
  }, [staged, stagedOption]);

  function stage(model: ModelOption) {
    if (!model.qualified || model.id === staged) return;
    setStaged(model.id);
    setPreference(normaliseLevel(reasoningFor?.(model.id)) ?? defaultLevel(model));
  }

  const panelId = `${ids}-panel`;
  const notAppliedValue = preference === 'xhigh' ? 'high' : preference;
  const reasoningValue = mapping.applied ? (mapping.selected?.id ?? mapping.segments[0].id) : notAppliedValue;
  const canApply = Boolean(stagedOption?.qualified);

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
          <ProviderIcon model={stagedOption} className='size-6' />
          <strong ref={capsuleLabel} className='min-w-0 truncate font-medium'>
            {stagedOption?.label ?? staged}
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
              <SegmentedControl<Mode> label='Connection mode' size='sm' widths='content' value={mode} onChange={switchMode} options={[{ value: 'api', label: 'API models' }, { value: 'cli', label: 'CLI' }]} />
              <InfoTip label='About API and CLI models' description='API models run through Rafii. CLI models run on the computer that hosts Rafii, with your own CLI sign-in.' className='size-9' />
            </div>

            <div className='rafii-quiet grid min-h-[22rem] grid-cols-[3.25rem_minmax(0,1fr)] overflow-hidden rounded-[var(--rafii-radius-card)] md:grid-cols-[4.25rem_minmax(0,1fr)]'>
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

              <div id={panelId} role='tabpanel' aria-labelledby={activeGroup ? `${ids}-tab-${activeGroup.id}` : undefined} className='flex min-w-0 flex-col'>
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
                      <p className='rafii-eyebrow px-2 pb-2'>{trimmed ? `Search results · ${visible.length}` : providerLabel(activeGroup?.name ?? 'Models')}</p>
                      {visible.length === 0 ? (
                        <StateMessage kind='empty' layout='inline' title='No models found.' className='px-2' />
                      ) : (
                        <div role='radiogroup' aria-label='Models' className='flex max-h-[19rem] flex-col gap-1 overflow-y-auto overscroll-contain'>
                          {visible.map((model) => {
                            const chosen = model.id === staged;
                            return (
                              <button
                                key={model.id}
                                type='button'
                                role='radio'
                                aria-checked={chosen}
                                disabled={!model.qualified}
                                title={`${providerLabel(providerName(model))} · ${routeLabel(model)}${model.detail ? ` · ${model.detail}` : ''}`}
                                onClick={() => stage(model)}
                                className={cn(
                                  'rafii-focus flex min-h-16 w-full items-start gap-3 rounded-[var(--rafii-radius-card)] px-3 py-3 text-left transition-colors duration-200',
                                  chosen ? 'rafii-glass-selected' : 'hover:rafii-quiet',
                                  !model.qualified && 'cursor-not-allowed opacity-60'
                                )}
                              >
                                <ProviderIcon model={model} className='mt-0.5 size-5' />
                                <span className='flex min-w-0 flex-1 flex-col gap-1'>
                                  <span className='text-foreground flex items-center gap-2 text-[15px] leading-tight font-medium [overflow-wrap:anywhere]'>
                                    {model.label}
                                    {chosen && <IconCheck aria-hidden className='size-4 shrink-0' />}
                                  </span>
                                  {/* Who pays stays visible; provider and route live in the row's tooltip. */}
                                  <span className={cn('text-xs leading-relaxed', model.qualified ? 'text-muted-foreground' : 'text-foreground')}>{model.qualified ? billingLabel(model.costClass) : `Unavailable · ${model.detail}`}</span>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className='mt-4 px-0.5'>
                    <div className='text-muted-foreground mb-2.5 flex items-center gap-2.5 px-2 text-sm'>
                      <ReasoningBars count={mapping.applied ? (mapping.selected?.bars ?? 0) : REASONING_BARS[preference]} muted={!mapping.applied} />
                      <span id={`${ids}-reasoning`} title={mapping.summary}>
                        Reasoning
                      </span>
                      <span className='text-muted-foreground ml-auto truncate text-xs'>{stagedOption?.label ?? staged}</span>
                    </div>
                    <SegmentedControl
                      label='Reasoning'
                      size='sm'
                      value={reasoningValue}
                      onChange={(next) => {
                        const segment = mapping.segments.find((item) => item.id === next);
                        if (segment) setPreference(segment.level);
                      }}
                      options={mapping.segments.map((segment) => ({
                        value: segment.id,
                        label: segment.label,
                        ariaLabel: mapping.applied ? `${segment.label}: sends ${segment.id}` : `${segment.label}: not applied by this provider`,
                        title: segment.detail || undefined,
                        disabled: !mapping.applied
                      }))}
                      className={cn(!mapping.applied && 'opacity-60')}
                    />
                    <p className='text-muted-foreground mt-2 min-h-4 px-2 text-xs leading-relaxed' aria-live='polite'>
                      {mapping.applied ? (mapping.selected?.detail ?? '') : 'This model has no reasoning setting.'}
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
            <Button variant='action' size='control' disabled={!canApply} onClick={() => onApply({ model: staged, reasoning: preference })}>
              Use this model <IconCheck aria-hidden />
            </Button>
          </div>
        </div>
      </RafiiDialogFooter>
    </>
  );
}

