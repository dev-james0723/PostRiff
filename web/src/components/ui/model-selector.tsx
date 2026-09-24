'use client';

import { useId, useState } from 'react';
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
import { siClaude, siGooglegemini } from 'simple-icons';
import type { ModelOption } from '@/lib/api/types';
import { cn } from '@/lib/utils';

export function providerName(model?: ModelOption) {
  const identity =
    `${model?.route ?? ''} ${model?.provider ?? ''} ${model?.id ?? ''}`.toLowerCase();
  if (/claude|anthropic/.test(identity)) return 'Anthropic';
  if (/codex|openai|gpt/.test(identity)) return 'OpenAI';
  if (/gemini|google/.test(identity)) return 'Google';
  return (
    model?.provider ||
    (model?.route && !['fixture', 'managed'].includes(model.route) ? model.route : 'Rafii')
  );
}

/** Locally bundled brand marks: no third-party image requests from the composer. */
export function ProviderIcon({ model, className }: { model?: ModelOption; className?: string }) {
  const provider = providerName(model);
  const classes = cn('size-4 shrink-0', className);
  const mark = provider === 'Anthropic' ? siClaude : provider === 'Google' ? siGooglegemini : null;
  if (mark)
    return (
      <svg aria-hidden='true' className={classes} viewBox='0 0 24 24' fill='currentColor'>
        <path d={mark.path} />
      </svg>
    );
  if (provider === 'OpenAI') return <IconBrandOpenai aria-hidden='true' className={classes} />;
  const Icon = provider === 'Rafii' ? IconSparkles : IconTerminal2;
  return <Icon aria-hidden='true' className={classes} />;
}

export function routeLabel(model: ModelOption) {
  if (model.route === 'claude-code') return 'Claude Code · Local CLI';
  if (model.route === 'codex') return 'Codex CLI · Local CLI';
  if (model.route && !['fixture', 'managed'].includes(model.route))
    return `${model.route} · Local CLI`;
  return model.route === 'fixture' || model.id === 'deterministic-preview'
    ? 'Deterministic preview'
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
  model: string;
  onChoose: (id: string) => void;
  disabled?: boolean;
  reasoning?: string;
  reasoningOptions?: { id: string; detail: string }[];
  onReasoning?: (id: string) => void;
  /** A pill that sits in a row of tool pills (conversation composer): same height and radius as its neighbours. */
  compact?: boolean;
}

/** Adapted from the supplied model selector, using the runtime catalog as its source of truth. */
export function ModelSelector({
  options,
  model,
  onChoose,
  disabled,
  reasoning,
  reasoningOptions,
  onReasoning,
  compact = false
}: ModelSelectorProps) {
  const reasoningId = useId();
  const current = options.find((item) => item.id === model);
  const [highlighted, setHighlighted] = useState<ModelOption>();
  const preview = highlighted ?? current;
  return (
    <Combobox.Root<ModelOption>
      items={options}
      value={current ?? null}
      disabled={disabled}
      itemToStringLabel={(item) => `${item.label} ${providerName(item)} ${routeLabel(item)}`}
      isItemEqualToValue={(a, b) => a.id === b.id}
      onItemHighlighted={(item) => setHighlighted(item)}
      onOpenChange={() => setHighlighted(undefined)}
      onValueChange={(item) => {
        if (item?.qualified) onChoose(item.id);
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
                      disabled={!item.qualified}
                      title={item.detail}
                      className='group data-highlighted:rafii-quiet data-selected:rafii-glass-selected data-disabled:opacity-60 flex min-h-11 cursor-default items-start gap-2 rounded-[var(--rafii-radius-control)] p-2.5 text-sm outline-none'
                    >
                      <ProviderIcon model={item} className='mt-0.5' />
                      <span className='min-w-0 flex-1'>
                        <span className='block truncate font-medium'>{item.label}</span>
                        <span className='text-muted-foreground block text-xs'>
                          {providerName(item)} · {routeLabel(item)}
                        </span>
                        {!item.qualified && (
                          <span className='text-muted-foreground mt-1 block text-xs'>
                            Unavailable · {item.detail}
                          </span>
                        )}
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
                    <span className='text-sm font-medium'>{preview.label}</span>
                  </div>
                  <p className='text-muted-foreground text-xs'>
                    {providerName(preview)} · {routeLabel(preview)}
                  </p>
                  <p className='text-muted-foreground mt-3 text-xs leading-relaxed'>
                    {preview.detail}
                  </p>
                  <dl className='mt-4 grid grid-cols-2 gap-3 text-xs'>
                    <div>
                      <dt className='text-muted-foreground'>Availability</dt>
                      <dd className='mt-1'>{preview.qualified ? 'Ready' : 'Unavailable'}</dd>
                    </div>
                    <div>
                      <dt className='text-muted-foreground'>Billing</dt>
                      <dd className='mt-1'>
                        {billingLabel(preview.costClass)}
                      </dd>
                    </div>
                  </dl>
                  {preview.id === model &&
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
                              {item.id}
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
