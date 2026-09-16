'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Channel } from '@/config/channels';

type Filter = 'all' | 'hosted' | 'local';

export function ChannelDirectory({ channels }: { channels: Channel[] }) {
  const [filter, setFilter] = useState<Filter>('all');
  const visible = channels.filter((c) => filter === 'all' || c.group === filter);
  return (
    <div className='flex flex-col gap-6'>
      <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)}>
        <TabsList>
          <TabsTrigger value='all'>All ({channels.length})</TabsTrigger>
          <TabsTrigger value='hosted'>Hosted ({channels.filter((c) => c.group === 'hosted').length})</TabsTrigger>
          <TabsTrigger value='local'>Desktop companion ({channels.filter((c) => c.group === 'local').length})</TabsTrigger>
        </TabsList>
      </Tabs>
      <ul className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
        {visible.map((channel) => (
          <li key={channel.slug}>
            <Link href={`/channels/${channel.slug}`} className='bg-card hover:border-primary/60 flex h-full flex-col gap-2 rounded-xl border p-4 transition-colors'>
              <div className='flex items-center justify-between gap-2'>
                <span className='font-medium'>
                  {channel.name}
                  {channel.nameZh && <span className='text-muted-foreground ml-1.5 text-sm'>{channel.nameZh}</span>}
                </span>
                <CapabilityBadge level={channel.capability} />
              </div>
              <p className='text-muted-foreground text-sm text-pretty'>{channel.description}</p>
              {channel.reviewStatus && <p className='text-xs text-amber-600 dark:text-amber-400'>{channel.reviewStatus}</p>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
