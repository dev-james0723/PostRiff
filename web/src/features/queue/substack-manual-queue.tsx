'use client';

import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { substackManualLabel, type SubstackManualEntry } from '@/lib/substack/manual-queue';
import { formatDateTime } from '@/lib/time';
import { StatusChip } from './status-chip';

export function SubstackManualQueue({ entries }: { entries: SubstackManualEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <section aria-labelledby='substack-manual-queue-title' className='flex flex-col gap-3' data-testid='substack-manual-queue'>
      <div className='flex flex-col gap-1'>
        <h2 id='substack-manual-queue-title' className='text-foreground text-lg font-medium'>Substack manual handoffs · {entries.length}</h2>
        <p className='text-muted-foreground text-sm'>These drafts need you to finish in Substack. Target times and prepared handoffs do not confirm publication.</p>
      </div>
      <ul className='grid gap-3 md:grid-cols-2'>
        {entries.map((entry) => (
          <li key={entry.id}>
            <Surface material='quiet' radius='card' padding='md' className='flex h-full flex-col gap-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <span className='flex min-w-0 items-center gap-2 font-medium'><ChannelIcon platform='Substack' name='Substack' size='xs' /><span className='line-clamp-2'>{entry.title}</span></span>
                <StatusChip tone={entry.due ? 'warning' : 'neutral'}>{substackManualLabel(entry)}</StatusChip>
              </div>
              <p className='text-muted-foreground truncate text-xs'>{entry.publicationUrl}</p>
              <p className='text-muted-foreground text-sm'>{entry.atSeconds === null ? 'Ready for manual handoff' : `Target: ${formatDateTime(entry.atSeconds)}`}</p>
              <Link href={entry.href} className={buttonVariants({ variant: 'glass', size: 'control', className: 'mt-auto self-start' })}>Open Substack draft</Link>
            </Surface>
          </li>
        ))}
      </ul>
    </section>
  );
}
