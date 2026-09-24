'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { SegmentedControl } from '@/components/rafii';
import type { Channel } from '@/config/channels';

type Filter = 'all' | 'hosted' | 'local';

/**
 * WHAT → FIND: one radio-pattern lens narrows the same grid without touching anything else
 * (DNA §10.4, §13.5); tiles are quiet reading surfaces that catch light on hover and focus.
 */
export function ChannelDirectory({ channels }: { channels: Channel[] }) {
  const [filter, setFilter] = useState<Filter>('all');
  const visible = channels.filter((c) => filter === 'all' || c.group === filter);
  const hosted = channels.filter((c) => c.group === 'hosted').length;
  const local = channels.filter((c) => c.group === 'local').length;
  return (
    <div className='flex flex-col gap-6'>
      <SegmentedControl<Filter>
        label='Show channels'
        widths='content'
        value={filter}
        onChange={setFilter}
        options={[
          { value: 'all', label: `All (${channels.length})` },
          { value: 'hosted', label: `Hosted (${hosted})` },
          {
            value: 'local',
            ariaLabel: `Desktop companion (${local})`,
            label: (
              <>
                <span className='sm:hidden'>Companion</span>
                <span className='hidden sm:inline'>Desktop companion</span> ({local})
              </>
            )
          }
        ]}
      />
      {/* minmax(0,1fr): a card never widens its column past the page (no sideways scroll on phones). */}
      <ul className='grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3'>
        {visible.map((channel) => (
          <li key={channel.slug} className='flex min-w-0'>
            <Link
              href={`/channels/${channel.slug}`}
              className='rafii-quiet hover:rafii-glass rafii-focus flex min-w-0 flex-1 flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4 transition-[background,box-shadow] duration-200'
            >
              <div className='flex items-center justify-between gap-2'>
                <span className='text-foreground flex min-w-0 items-center gap-2 font-medium'>
                  <ChannelIcon slug={channel.slug} name={channel.name} />
                  <span className='truncate'>
                    {channel.name}
                    {channel.nameZh && <span className='text-muted-foreground ml-1.5 text-sm font-normal'>{channel.nameZh}</span>}
                  </span>
                </span>
                <CapabilityBadge level={channel.capability} />
              </div>
              <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{channel.description}</p>
              {channel.reviewStatus && (
                <p className='text-muted-foreground flex items-center gap-1.5 text-xs'>
                  <Icons.clock className='size-3.5 shrink-0' aria-hidden />
                  {channel.reviewStatus}
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
