'use client';

import { useId, useMemo, useState } from 'react';
import Link from 'next/link';
import { Combobox } from '@base-ui/react/combobox';
import {
  IconBrandOpenai,
  IconCheck,
  IconChevronDown,
  IconSearch,
  IconTerminal2,
  IconSparkles
} from '@tabler/icons-react';
import { siBytedance, siClaude, siGooglegemini, siMeta, siMinimax } from 'simple-icons';
import type { ModelOption } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/** The model's maker (the catalogue's `maker`, else a managed id's prefix) → the vendor name the icons and rail use. */
const MAKERS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  bytedance: 'ByteDance',
  minimax: 'MiniMax',
  meta: 'Meta',
  deepseek: 'DeepSeek',
  alibaba: 'Alibaba'
};

function isCliRoute(model?: ModelOption) {
  return Boolean(model?.route && !['fixture', 'managed'].includes(model.route));
}

export function providerName(model?: ModelOption) {
  const identity =
    `${model?.route ?? ''} ${model?.provider ?? ''} ${model?.id ?? ''}`.toLowerCase();
  if (/claude|anthropic/.test(identity)) return 'Anthropic';
  if (/codex|openai|gpt/.test(identity)) return 'OpenAI';
  if (/gemini|google/.test(identity)) return 'Google';
  const prefix = !isCliRoute(model) && model?.id.includes('/') ? (model?.id.split('/')[0] ?? '') : '';
  const maker = (model?.maker ?? prefix).toLowerCase();
  if (MAKERS[maker]) return MAKERS[maker];
  return (
    model?.provider ||
    (isCliRoute(model) ? model?.route : 'Rafii') ||
    'Rafii'
  );
}

/** Locally bundled brand marks: no third-party image requests from the composer. */
export function ProviderIcon({ model, className }: { model?: ModelOption; className?: string }) {
  const provider = providerName(model);
  const classes = cn('size-4 shrink-0', className);
  const mark =
    provider === 'Anthropic'
      ? siClaude
      : provider === 'Google'
        ? siGooglegemini
        : provider === 'ByteDance'
          ? siBytedance
          : provider === 'MiniMax'
            ? siMinimax
            : provider === 'Meta'
              ? siMeta
              : null;
  if (mark)
    return (
      <svg aria-hidden='true' className={classes} viewBox='0 0 24 24' fill='currentColor'>
        <path d={mark.path} />
      </svg>
    );
  if (provider === 'OpenAI') return <IconBrandOpenai aria-hidden='true' className={classes} />;
  // The terminal mark is for CLI routes only; a managed writer from any other maker is Rafii's.
  const Icon = isCliRoute(model) ? IconTerminal2 : IconSparkles;
  return <Icon aria-hidden='true' className={classes} />;
}

/** "$", "$$" or "$$$" by the catalogue's cost tier, read out as its label ("Medium cost"); nothing when unpriced. */
export function CostBadge({ model, className }: { model?: ModelOption; className?: string }) {
  const tier = model?.costTier;
  if (tier !== 1 && tier !== 2 && tier !== 3) return null;
  const label = model?.costTierLabel || ['Lower cost', 'Medium cost', 'Higher cost'][tier - 1];
  return (
    <span className={cn('text-muted-foreground shrink-0 font-mono text-xs font-normal tracking-tight', className)}>
      <span aria-hidden='true'>{'$'.repeat(tier)}</span>
      <span className='sr-only'>{label}</span>
    </span>
  );
}

export function routeLabel(model: ModelOption) {
  if (model.route === 'claude-code') return 'Claude Code · Local CLI';
  if (model.route === 'codex') return 'Codex CLI · Local CLI';
  if (model.route && !['fixture', 'managed'].includes(model.route))
    return `${model.route} · Local CLI`;
  return model.route === 'fixture' || model.id === 'deterministic-preview'
    ? 'Templates (no AI model)'
    : 'Rafii · Managed';
}

/** Billing wording shared with the model dialog. */
export function billingLabel(costClass?: string) {
  return costClass === 'subscription'
    ? 'CLI subscription'
    : costClass === 'paid'
      ? 'Workspace usage'
      : costClass === 'none'
        ? 'No model charge'
        : 'Not reported';
}

export interface ModelSelectorProps {
  options: ModelOption[];
  /** The concrete model a run uses. */
  model: string;
  /** What the person chose, when it differs from `model`: 'auto' (AUTO_MODEL in features/agent/use-model.ts) or an id. */
  value?: string;
  /** Offer Auto as the first item: its label ("Auto · gpt-6-sol") and the option Auto resolves to. */
  auto?: { label: string; option: ModelOption | undefined };
  onChoose: (id: string) => void;
  disabled?: boolean;
  reasoning?: string;
  reasoningOptions?: { id: string; detail: string; label?: string }[];
  onReasoning?: (id: string) => void;
  /** A pill that sits in a row of tool pills (conversation composer): same height and radius as its neighbours. */
  compact?: boolean;
}

/** The Auto item's id; the same literal as AUTO_MODEL (kept here so this component needs no feature import). */
const AUTO_ITEM = 'auto';

/** Rows that cannot be chosen: not qualified, or a managed writer the deployment has no price for. */
function selectable(item: ModelOption) {
  return item.qualified && item.priced !== false;
}

/** Adapted from the supplied model selector, using the runtime catalog as its source of truth. */
export function ModelSelector({
  options,
  model,
  value,
  auto,
  onChoose,
  disabled,
  reasoning,
  reasoningOptions,
  onReasoning,
  compact = false
}: ModelSelectorProps) {
  const reasoningId = useId();
  const items = useMemo<ModelOption[]>(() => {
    if (!auto) return options;
    const resolved = auto.option;
    const item: ModelOption = {
      id: AUTO_ITEM,
      label: auto.label,
      qualified: Boolean(resolved?.qualified),
      detail: `Follows the workspace default${resolved ? `: now ${resolved.displayName ?? resolved.label}` : ''}.`,
      costClass: resolved?.costClass
    };
    return [item, ...options];
  }, [auto, options]);
  const selected = value ?? model;
  const current = items.find((item) => item.id === selected);
  const [highlighted, setHighlighted] = useState<ModelOption>();
  const preview = highlighted ?? current;
  return (
    <Combobox.Root<ModelOption>
      items={items}
      value={current ?? null}
      disabled={disabled}
      itemToStringLabel={(item) => `${item.label} ${providerName(item)} ${routeLabel(item)}`}
      isItemEqualToValue={(a, b) => a.id === b.id}
      onItemHighlighted={(item) => setHighlighted(item)}
      onOpenChange={() => setHighlighted(undefined)}
      onValueChange={(item) => {
        if (item && selectable(item)) onChoose(item.id);
      }}
    >
      <Combobox.Trigger
        aria-label='Model'
        title={current?.detail}
        className={cn(
          'rafii-glass hover:rafii-glass-selected data-popup-open:rafii-glass-selected rafii-focus flex shrink-0 items-center gap-2 font-medium disabled:opacity-50',
          compact ? 'h-10 max-w-44 rounded-full px-3.5 text-xs sm:h-9' : 'h-11 max-w-64 rounded-[var(--rafii-radius-control)] px-3.5 text-sm'
        )}
      >
        <ProviderIcon model={current} className='size-4' />
        <span className='truncate'>{current?.label ?? (options.length ? 'Select model' : 'Loading models…')}</span>
        <IconChevronDown aria-hidden='true' className='size-3.5 shrink-0 text-muted-foreground' />
      </Combobox.Trigger>
      <Combobox.Portal>
        <Combobox.Positioner align='end' sideOffset={8} collisionPadding={12} className='z-50'>
          <Combobox.Popup
            aria-label='Select model and provider'
            className='rafii-elevated text-foreground max-h-(--available-height) w-[min(36rem,calc(100vw-1.5rem))] overflow-y-auto rounded-[var(--rafii-radius-card)] outline-none'
          >
            <div className='rafii-quiet flex items-center gap-2 px-3'>
              <IconSearch aria-hidden='true' className='text-muted-foreground size-4' />
              <Combobox.Input
                aria-label='Search models and providers'
                placeholder='Search models or providers…'
                className='h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground md:text-sm'
              />
            </div>
            <div className='flex flex-col sm:flex-row'>
              <div className='min-w-0 flex-1'>
                <Combobox.Empty className='text-muted-foreground p-4 text-center text-sm empty:hidden'>
                  No models found. Try another provider or model.
                </Combobox.Empty>
                <Combobox.List className='max-h-64 overflow-y-auto overscroll-contain p-1.5 sm:max-h-80'>
                  {(item: ModelOption) => (
                    <Combobox.Item
                      key={item.id}
                      value={item}
                      disabled={!selectable(item)}
                      title={item.detail}
                      className='group data-highlighted:rafii-quiet data-selected:rafii-glass-selected data-disabled:opacity-60 flex min-h-11 cursor-default items-start gap-2 rounded-[var(--rafii-radius-control)] p-2.5 text-sm outline-none'
                    >
                      <ProviderIcon model={item} className='mt-0.5' />
                      <span className='min-w-0 flex-1'>
                        <span className='flex min-w-0 items-baseline gap-2'>
                          <span className='truncate font-medium'>{item.displayName ?? item.label}</span>
                          <CostBadge model={item} />
                        </span>
                        <span className='text-muted-foreground block text-xs'>
                          {item.id === AUTO_ITEM ? 'Workspace default' : `${providerName(item)} · ${routeLabel(item)}`}
                        </span>
                        {!item.qualified ? (
                          <span className='text-muted-foreground mt-1 block text-xs'>
                            Unavailable · {item.detail}
                          </span>
                        ) : item.priced === false ? (
                          <span className='text-muted-foreground mt-1 block text-xs'>
                            Unavailable · No price is configured for this model.
                          </span>
                        ) : null}
                      </span>
                      <Combobox.ItemIndicator>
                        <IconCheck aria-hidden='true' className='size-4' />
                      </Combobox.ItemIndicator>
                    </Combobox.Item>
                  )}
                </Combobox.List>
              </div>
              {preview && (
                <aside
                  aria-label='Model details'
                  className='rafii-quiet w-full shrink-0 p-3 sm:w-56'
                >
                  <div className='mb-2 flex items-center gap-2'>
                    <ProviderIcon model={preview} />
                    <span className='text-sm font-medium'>{preview.displayName ?? preview.label}</span>
                    <CostBadge model={preview} />
                  </div>
                  <p className='text-muted-foreground text-xs'>
                    {preview.id === AUTO_ITEM ? 'Workspace default' : `${[preview.family, providerName(preview)].filter(Boolean).join(' · ')} · ${routeLabel(preview)}`}
                  </p>
                  <p className='text-muted-foreground mt-3 text-xs leading-relaxed'>
                    {preview.detail}
                  </p>
                  <dl className='mt-4 grid grid-cols-2 gap-3 text-xs'>
                    <div>
                      <dt className='text-muted-foreground'>Availability</dt>
                      <dd className='mt-1'>{selectable(preview) ? 'Ready' : 'Unavailable'}</dd>
                    </div>
                    <div>
                      <dt className='text-muted-foreground'>Billing</dt>
                      <dd className='mt-1'>
                        {billingLabel(preview.costClass)}
                      </dd>
                    </div>
                  </dl>
                  {preview.id === selected &&
                    reasoningOptions &&
                    reasoningOptions.length > 1 &&
                    onReasoning && (
                      <div className='mt-4 pt-3'>
                        <label
                          htmlFor={reasoningId}
                          className='text-muted-foreground mb-2 block text-xs'
                        >
                          Reasoning effort
                        </label>
                        <select
                          id={reasoningId}
                          value={reasoning}
                          disabled={disabled}
                          onChange={(event) => onReasoning(event.target.value)}
                          className='rafii-field rafii-focus h-11 w-full rounded-[var(--rafii-radius-control)] px-2.5 text-base md:text-sm'
                        >
                          {reasoningOptions.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.label ?? item.id}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                </aside>
              )}
            </div>
            <Link
              href='/app/account/models'
              className='text-muted-foreground hover:rafii-quiet focus-visible:rafii-quiet rafii-focus block min-h-11 px-3 py-3 text-xs'
            >
              Models &amp; providers <span aria-hidden='true'>↗</span>
            </Link>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
