'use client';
import { useState } from 'react';
import Link from 'next/link';
import { IconBell } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { useAttention } from '@/lib/use-attention';

export function NotificationBell() {
  const attention = useAttention();
  const [open, setOpen] = useState(false);
  const readable = !attention.loading && attention.unavailable.length === 0;
  const label = readable ? `Notifications, ${attention.items.length} need attention` : 'Notifications, status unavailable';
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger render={<Button variant='ghost' size='icon' aria-label={label} className='relative' />}>
      <IconBell className='size-5' />
      {readable && attention.items.length > 0 && <span className='bg-primary text-primary-foreground absolute -top-0.5 -right-0.5 rounded-full px-1 text-[10px]'>{attention.items.length}</span>}
    </PopoverTrigger>
    <PopoverContent align='end' className='max-h-[70dvh] w-80 max-w-[calc(100vw-2rem)] overflow-y-auto p-4'>
      <PopoverTitle>Needs your attention</PopoverTitle>
      {attention.loading && <p role='status' className='text-muted-foreground text-sm'>Loading current status…</p>}
      {attention.unavailable.length > 0 && <p role='status' className='text-muted-foreground text-sm'>Some status is unavailable. Open the Overview to retry.</p>}
      {readable && attention.items.length === 0 && <p className='text-muted-foreground text-sm'>Nothing needs your attention right now.</p>}
      {attention.items.map((item) => <Link key={item.id} href={item.href} onClick={() => setOpen(false)} className='hover:bg-muted rounded-md border p-3'><span className='block text-sm font-medium'>{item.title}</span><span className='text-muted-foreground block text-xs'>{item.description}</span></Link>)}
      <Link href='/app/account/notifications' onClick={() => setOpen(false)} className='text-xs underline'>Notification settings</Link>
    </PopoverContent>
  </Popover>;
}
