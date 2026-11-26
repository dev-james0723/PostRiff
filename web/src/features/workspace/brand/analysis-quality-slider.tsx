'use client';

import { useId } from 'react';
import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';
import { SelectField } from '../rafii-parts';
import { QUALITY_ORDER, nearestAvailable, providerOptions, qualityAt, qualityIndex, type ProviderChoice, type QualityId } from './analysis-quality';
import type { BrainTranslate } from './brain-types';

/** One stop as the slider shows it: its model, whether it can be chosen, and its cost line once a quote is known. */
export interface QualityStopView {
  id: QualityId;
  model: string;
  available: boolean;
  /** "About 12 credits" or "US$0.05"; absent until a quote is known. */
  cost?: string | null;
  /** Why an unavailable stop cannot be chosen ("Not offered here", "Not enough credits"). */
  note?: string | null;
}

export function qualityCopy(t: BrainTranslate): Record<QualityId, { name: string; detail: string }> {
  return {
    economy: {
      name: t('Economy', '經濟', '经济'),
      detail: t('The cheapest reading. It finds the main habits and can miss subtler ones.', '最便宜的解讀，能找出主要習慣，但可能漏掉較細微的地方。', '最便宜的解读，能找出主要习惯，但可能漏掉较细微的地方。')
    },
    balanced: {
      name: t('Balanced', '平衡', '平衡'),
      detail: t('A careful reading at a moderate cost.', '以中等費用作仔細解讀。', '以中等费用作仔细解读。')
    },
    best: {
      name: t('Best', '最佳', '最佳'),
      detail: t('The most thorough reading. It notices the subtlest habits and uses the most credits.', '最深入的解讀，能察覺最細微的習慣，用最多點數。', '最深入的解读，能察觉最细微的习惯，用最多点数。')
    }
  };
}

/**
 * The analysis quality slider: Economy, Balanced, Best. Moving it never starts or charges anything; the screen around
 * it shows the chosen stop's quote and asks for approval. Keyboard: arrow keys move between stops.
 */
export function AnalysisQualitySlider({
  stops,
  value,
  onChange,
  disabled,
  t
}: {
  stops: QualityStopView[];
  value: QualityId | null;
  onChange: (next: QualityId) => void;
  disabled?: boolean;
  t: BrainTranslate;
}) {
  const id = useId();
  const copy = qualityCopy(t);
  const current = stops.find((stop) => stop.id === value) ?? null;
  const offered = stops.some((stop) => stop.available);
  const spoken = (stop: QualityStopView | undefined) =>
    stop ? [copy[stop.id].name, stop.cost, stop.available ? null : stop.note ?? t('not available', '不可選用', '不可选用')].filter(Boolean).join(', ') : '';
  return (
    <div className='flex min-w-0 flex-col gap-3' data-testid='analysis-quality'>
      <div className='flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1'>
        <span id={`${id}-label`} className='text-foreground text-sm font-medium'>
          {t('Analysis quality', '分析質素', '分析质量')}
        </span>
        {current && (
          <span className='text-foreground text-sm tabular-nums' data-testid='analysis-quality-selected'>
            {copy[current.id].name}
            {current.cost ? ` · ${current.cost}` : ''}
          </span>
        )}
      </div>
      <Slider
        min={0}
        max={QUALITY_ORDER.length - 1}
        step={1}
        value={[value ? qualityIndex(value) : 1]}
        disabled={disabled || !offered}
        aria-labelledby={`${id}-label`}
        thumbProps={{
          'aria-labelledby': `${id}-label`,
          'aria-describedby': `${id}-detail`,
          getAriaValueText: (_formatted: string, position: number) => spoken(stops.find((stop) => stop.id === qualityAt(position)))
        }}
        onValueChange={(next) => {
          const position = Array.isArray(next) ? next[0] : next;
          const snapped = nearestAvailable(stops, qualityAt(Number(position)));
          if (snapped && snapped !== value) onChange(snapped);
        }}
        className='py-2'
      />
      <ol className='grid grid-cols-3 gap-2 text-xs' aria-hidden='true'>
        {QUALITY_ORDER.map((quality) => {
          const stop = stops.find((item) => item.id === quality);
          return (
            <li
              key={quality}
              className={cn(
                'flex min-w-0 flex-col gap-0.5',
                quality === 'balanced' && 'items-center text-center',
                quality === 'best' && 'items-end text-end',
                stop?.available ? 'text-foreground' : 'text-muted-foreground'
              )}
            >
              <span className={cn('font-medium', quality === value && 'underline underline-offset-4')}>{copy[quality].name}</span>
              <span className='text-muted-foreground tabular-nums'>{stop?.available ? stop.cost ?? '' : stop?.note ?? t('Not offered here', '此處未有提供', '此处未提供')}</span>
            </li>
          );
        })}
      </ol>
      <p id={`${id}-detail`} className='text-muted-foreground text-sm leading-relaxed' data-testid='analysis-quality-detail'>
        {current ? (
          copy[current.id].detail
        ) : offered ? (
          t('Choose a quality to see its cost.', '請選擇質素以查看費用。', '请选择质量以查看费用。')
        ) : (
          t('AI analysis is not offered in this workspace right now.', '此工作區現時未有提供 AI 分析。', '此工作区目前未提供 AI 分析。')
        )}
      </p>
    </div>
  );
}

/**
 * "Advanced · choose AI provider", closed by default: for agencies or teams whose policy requires one provider. It lists
 * the providers the chosen quality can use, by maker. A choice is honoured exactly or the analysis does not start; it
 * is never replaced by another provider. Hidden when the quality has only one provider to choose.
 */
export function AdvancedProvider({
  choices,
  value,
  onChange,
  disabled,
  t
}: {
  choices: readonly ProviderChoice[] | undefined;
  value: string | null;
  onChange: (model: string | null) => void;
  disabled?: boolean;
  t: BrainTranslate;
}) {
  const options = providerOptions(choices);
  if (options.length < 2) return null;
  return (
    <details className='min-w-0 text-sm' data-testid='analysis-provider' open={value ? true : undefined}>
      <summary className='rafii-focus text-muted-foreground min-h-11 cursor-pointer py-3'>{t('Advanced · choose AI provider', '進階 · 選擇 AI 供應商', '高级 · 选择 AI 供应商')}</summary>
      <div className='flex min-w-0 flex-col gap-2 pb-2'>
        <SelectField label={t('AI provider', 'AI 供應商', 'AI 供应商')} value={value ?? ''} onChange={(event) => onChange(event.target.value || null)} disabled={disabled} className='sm:max-w-md'>
          <option value=''>{t('Recommended for this quality', '此質素的建議選擇', '此质量的推荐选择')}</option>
          {options.map((option) => (
            <option key={option.model} value={option.model}>
              {option.label}
            </option>
          ))}
        </SelectField>
        <p className='text-muted-foreground text-xs'>
          {t(
            'For teams whose policy requires one provider. Rafii uses exactly this provider, or does not start.',
            '適用於政策要求指定供應商的團隊。Rafii 只會使用此供應商，否則不會開始。',
            '适用于政策要求指定供应商的团队。Rafii 只会使用此供应商，否则不会开始。'
          )}
        </p>
      </div>
    </details>
  );
}
