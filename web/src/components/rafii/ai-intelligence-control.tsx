'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';

export interface IntelligenceOption<T extends string> {
  id: T;
  label: string;
  description: string;
}

/** A feature supplies its own supported presets and server-side pricing. */
export function AiIntelligenceControl<T extends string>({ options, value, onChange, disabled }: {
  options: readonly IntelligenceOption<T>[]; value: T; onChange: (value: T) => void; disabled?: boolean;
}) {
  const titleId = useId();
  const selected = options.findIndex(option => option.id === value);
  const option = options[selected];
  if (!option || options.length < 2) return null;
  return <section aria-labelledby={titleId} className='rafii-quiet grid min-w-0 gap-3 rounded-xl p-4'>
    <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1'>
      <h4 id={titleId} className='text-sm font-medium'>AI intelligence</h4>
      <span className='text-sm font-semibold'>{option.label}</span>
    </div>
    <Slider min={0} max={options.length - 1} step={1} value={[selected]} disabled={disabled}
      className='[&_[data-slot=slider-thumb]]:size-4 [&_[data-slot=slider-track]]:h-1.5 [&>div]:min-h-8'
      getAriaLabel={() => 'AI intelligence'} getAriaValueText={(_, index) => options[index]?.label ?? ''}
      onValueChange={next => { const item = options[Array.isArray(next) ? next[0] : Number(next)]; if (item) onChange(item.id); }} />
    <div className='-mx-2 -mt-3 grid grid-flow-col auto-cols-fr'>
      {options.map(item => <Button key={item.id} type='button' variant='quiet' size='sm' tabIndex={-1}
        disabled={disabled} aria-pressed={value === item.id} onClick={() => onChange(item.id)}
        className='min-h-10 min-w-0 whitespace-normal px-0.5 text-center text-[11px] leading-tight text-muted-foreground aria-pressed:text-foreground sm:text-xs'>
        {item.label}
      </Button>)}
    </div>
    <p className='text-sm text-muted-foreground'>{option.description}</p>
  </section>;
}
