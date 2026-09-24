'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii';
import { QUICK_STARTS, QUICK_START_GROUPS, type QuickStart, type QuickStartGroup } from '@/config/quick-starts';
import { useMeasuredDisclosure } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

/** The greeting's name: the first word of a real display name, else nothing (never a sample name). */
export function greetingName(displayName: string | null | undefined): string | null {
  const first = (displayName ?? '').trim().split(/\s+/)[0] ?? '';
  return first && first.length <= 24 && !/^[\w.+-]+@/.test(first) ? first : null;
}

/** Neutral starting points (DNA §21.1): no personal projects, brands or sample data. */
export const STARTING_POINTS: { id: string; label: string; text: string }[] = [
  { id: 'behind', label: 'Behind the scenes', text: 'A behind-the-scenes thought: the quiet, imperfect work is usually where the best ideas begin. Turn this into a short post in my words.' },
  { id: 'lesson', label: 'Something I learned', text: 'One thing this week taught me about creating: consistency matters more than waiting for inspiration. Draft this as a post that ends with a question for readers.' },
  { id: 'research', label: 'Research a topic', text: 'Research the latest guidance on posting cadence for small creators and log every source before writing a short summary post.' },
  { id: 'plan', label: 'Plan the week', text: 'Plan this week: one post per selected channel, spread across Tuesday and Thursday mornings, from the notes below.' }
];

export function StartingPoints({ onPick, disabled }: { onPick: (text: string) => void; disabled?: boolean }) {
  return (
    <div className='text-muted-foreground flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs' aria-label='Ideas to get started'>
      <span>A little nudge?</span>
      {STARTING_POINTS.map((item) => (
        <button key={item.id} type='button' disabled={disabled} onClick={() => onPick(item.text)} className='rafii-focus hover:text-foreground inline-flex min-h-11 items-center gap-1 rounded-md font-medium'>
          {item.label}
          <Icons.arrowUpRight className='size-3' />
        </button>
      ))}
    </div>
  );
}

/**
 * The eleven quick starts, folded into a measured disclosure below the composer (DNA §21.1: the
 * templates stay reachable; they no longer compete with the composer). Picking one selects the
 * workspace content type exactly as before.
 */
export function QuickStartsDisclosure({ selected, onPick, disabled }: { selected: QuickStart | null; onPick: (item: QuickStart) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState<QuickStartGroup | 'all'>('all');
  const panel = useMeasuredDisclosure<HTMLDivElement>(open);
  const items = QUICK_STARTS.filter((item) => group === 'all' || item.group === group);
  return (
    <section className='flex flex-col gap-3' data-tour='quick-starts'>
      <button type='button' aria-expanded={open} aria-controls='rafii-quick-starts' onClick={() => setOpen((v) => !v)} className='rafii-focus text-muted-foreground hover:text-foreground flex min-h-11 w-full items-center justify-between gap-3 rounded-md text-left text-sm'>
        <span className='flex flex-col'>
          <span className='text-foreground font-medium'>More kinds of post</span>
          <span className='text-xs'>Eleven kinds people actually publish. Pick one, replace the brackets, send.</span>
        </span>
        <Icons.chevronDown aria-hidden className={cn('size-4 shrink-0 transition-transform duration-[400ms] ease-[var(--rafii-ease-soft)] motion-reduce:transition-none', open && 'rotate-180')} />
      </button>
      <div id='rafii-quick-starts' ref={panel}>
        <div className='flex flex-col gap-3 pb-1'>
          <SegmentedControl label='Quick start groups' size='sm' widths='content' value={group} onChange={setGroup} options={QUICK_START_GROUPS.map((item) => ({ value: item.id, label: item.label }))} className='max-w-full overflow-x-auto' />
          <div className='grid gap-2.5 sm:grid-cols-2'>
            {items.map((item) => {
              const active = selected?.id === item.id;
              return (
                <button key={item.id} type='button' aria-pressed={active} disabled={disabled} onClick={() => onPick(item)} className={cn('rafii-focus flex min-h-[4.5rem] flex-col gap-1 rounded-[var(--rafii-radius-card)] p-3.5 text-left transition-colors', active ? 'rafii-glass-selected' : 'rafii-quiet hover:rafii-glass')}>
                  <span className='text-foreground text-sm font-medium'>{item.title}</span>
                  <span className='text-muted-foreground text-xs leading-relaxed'>{item.explanation}</span>
                  <span className='text-muted-foreground/80 mt-auto pt-1 text-[11px] leading-relaxed'>Usually: {item.usually}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
