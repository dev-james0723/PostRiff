'use client';

import { Icons } from '@/components/icons';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

function humanize(key: string) {
  const spaced = key.replace(/([A-Z])/g, ' $1').toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** The API's own rules, folded away by default so they do not take the numbers' place. */
export function RulesCollapsible({ rules }: { rules: Record<string, string> }) {
  const entries = Object.entries(rules);
  if (entries.length === 0) return null;
  return (
    <Collapsible render={<Card className='gap-0 py-0' />}>
      <CollapsibleTrigger className='group/rules hover:bg-muted/50 flex w-full items-center justify-between gap-2 rounded-xl px-4 py-3 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring/50'>
        How to read these numbers
        <Icons.chevronDown
          aria-hidden
          className='text-muted-foreground size-4 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/rules:rotate-180 motion-reduce:transition-none'
        />
      </CollapsibleTrigger>
      <CollapsibleContent className='t-nav-panel'>
        <ul className='flex flex-col gap-2 px-4 pb-4 text-sm'>
          {entries.map(([key, value]) => (
            <li key={key}>
              <span className='font-medium'>{humanize(key)}</span>
              <span className='text-muted-foreground'> — {value}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
