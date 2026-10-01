'use client';

import { useId } from 'react';
import { cn } from '@/lib/utils';
import { factLabel, factText } from './model';
import type { FactValue, Facts, FounderAction } from './types';

/**
 * The server's description of an action (`target`, `current`, `effect`, `result`) as labelled lists. Values are written
 * as sent, through the shared formatters; nothing is added up or derived here. Ids wrap so a phone never scrolls sideways.
 */
const ID_KEY = /(^id$|Id$|Ids$|Ref$)/;

function Nested({ value }: { value: FactValue }) {
  if (Array.isArray(value)) {
    return (
      <ul className='flex flex-col gap-2'>
        {value.map((item, index) => (
          <li key={`${index}-${typeof item === 'object' ? 'record' : String(item)}`}>{item && typeof item === 'object' && !Array.isArray(item) ? <FactList facts={item} nested /> : String(item)}</li>
        ))}
      </ul>
    );
  }
  if (value && typeof value === 'object') return <FactList facts={value} nested />;
  return null;
}

export function FactList({ facts, nested = false, className }: { facts: Facts | null | undefined; nested?: boolean; className?: string }) {
  const entries = Object.entries(facts ?? {});
  if (entries.length === 0) return <p className='text-muted-foreground text-xs'>Nothing recorded.</p>;
  return (
    <dl className={cn('grid grid-cols-[minmax(6.5rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1.5', nested ? 'rafii-quiet rounded-[var(--rafii-radius-control)] p-2.5 text-xs' : 'text-sm', className)}>
      {entries.map(([key, value]) => {
        const text = factText(key, value, facts ?? {});
        return (
          <div key={key} className='contents'>
            <dt className='text-muted-foreground text-xs leading-5'>{factLabel(key)}</dt>
            <dd className={cn('min-w-0 leading-5 break-words', ID_KEY.test(key) && 'font-mono text-xs break-all')}>{text ?? <Nested value={value} />}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function FactSection({ title, facts }: { title: string; facts: Facts | null | undefined }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className='flex min-w-0 flex-col gap-2'>
      <h3 id={id} className='rafii-eyebrow'>
        {title}
      </h3>
      <FactList facts={facts} />
    </section>
  );
}

/** Target, current value and effect from the preview; the result once the action ran. */
export function ActionSummary({ action, showResult = false }: { action: FounderAction; showResult?: boolean }) {
  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <FactSection title='Target' facts={action.target} />
      <FactSection title='Current value' facts={action.current} />
      <FactSection title={showResult ? 'Effect' : 'Effect if you confirm'} facts={action.effect} />
      {showResult && action.result && <FactSection title='Result' facts={action.result} />}
    </div>
  );
}
